"""Security tests for the operating-system evidence collector."""

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = REPOSITORY_ROOT / "tools" / "coleta_zabbix_os.sh"


class TestOSCollector(unittest.TestCase):
    def _write_executable(self, path, content):
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_collector_allowlists_config_and_redacts_sensitive_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            os_release = temporary_path / "os-release"
            zabbix_config = temporary_path / "zabbix_server.conf"
            output_file = temporary_path / "nested evidence.txt"
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()

            os_release.write_text(
                'PRETTY_NAME="Test Linux"\nVERSION="1.0"\nIGNORED=value\n',
                encoding="utf-8",
            )
            zabbix_config.write_text(
                """
# Synthetic configuration used only by this test.
CacheSize=128M
StartPollers = 10
DBPassword=synthetic-db-password-value
ApiToken=synthetic-api-token-value
SNMPCommunity=synthetic-community-value
TLSPSKIdentity=synthetic-psk-identity
CredentialFile=/synthetic/credential-file
CustomPaSsWd=synthetic-mixed-case-value
DBName=not-allowlisted
""".lstrip(),
                encoding="utf-8",
            )
            self._write_executable(
                fake_bin / "ps",
                """#!/bin/sh
if [ "$*" != "-eo pid=,comm=,pcpu=,pmem= --sort=-pcpu" ]; then
    echo "unexpected ps arguments: $*" >&2
    exit 42
fi
printf '  123 zabbix_server            1.2  3.4\\n'
""",
            )
            self._write_executable(
                fake_bin / "systemctl",
                """#!/bin/sh
case "$1" in
    is-active) echo active ;;
    is-enabled) echo enabled ;;
    *) echo synthetic-status-argument-leak; exit 42 ;;
esac
""",
            )
            self._write_executable(
                fake_bin / "uptime",
                """#!/bin/sh
echo 'up 1 day; ApiToken=synthetic-defensive-redaction-value'
""",
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "ZABBIX_OS_RELEASE_FILE": str(os_release),
                    "ZABBIX_SERVER_CONF_FILE": str(zabbix_config),
                    "ZABBIX_EVIDENCE_OUTPUT_FILE": str(output_file),
                }
            )

            result = subprocess.run(
                ["bash", str(COLLECTOR)],
                cwd=temporary_path,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_file.is_file())
            evidence = output_file.read_text(encoding="utf-8")

            self.assertIn("CacheSize=128M", evidence)
            self.assertIn("StartPollers = 10", evidence)
            self.assertIn("123 zabbix_server", evidence)
            self.assertIn("[REDACTED: linha potencialmente sensivel omitida]", evidence)
            self.assertNotIn("not-allowlisted", evidence)
            self.assertNotIn("synthetic-status-argument-leak", evidence)

            forbidden_fragments = (
                "DBPassword",
                "synthetic-db-password-value",
                "ApiToken",
                "synthetic-api-token-value",
                "SNMPCommunity",
                "synthetic-community-value",
                "TLSPSKIdentity",
                "synthetic-psk-identity",
                "CredentialFile",
                "synthetic/credential-file",
                "CustomPaSsWd",
                "synthetic-mixed-case-value",
                "synthetic-defensive-redaction-value",
            )
            for fragment in forbidden_fragments:
                with self.subTest(fragment=fragment):
                    self.assertNotIn(fragment, evidence)

            self.assertEqual(stat.S_IMODE(output_file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
