"""Static checks for the hardened Docker GUI launcher."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class TestWaylandLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (REPOSITORY_ROOT / "exec_wayland.fish").read_text(encoding="utf-8")
        cls.dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_default_container_uses_calling_user_and_no_privilege_escalation(self):
        self.assertIn("--user (id -u):(id -g)", self.script)
        self.assertIn("--read-only", self.script)
        self.assertIn("--cap-drop ALL", self.script)
        self.assertIn("no-new-privileges:true", self.script)
        self.assertNotIn("sudo", self.script)
        self.assertNotIn("xhost +local:root", self.script)

    def test_host_network_is_explicit_and_source_code_is_not_mounted(self):
        self.assertIn("case --host-network", self.script)
        self.assertIn("set -a docker_args --network host", self.script)
        self.assertNotIn("--net host", self.script)
        self.assertNotIn('"$PWD:/app"', self.script)
        self.assertIn('--volume "$data_dir:/data:rw"', self.script)
        self.assertIn("--workdir /data", self.script)
        self.assertIn('chmod 700 -- "$data_dir"', self.script)
        self.assertIn('chmod 700 -- "$data_dir/tmp"', self.script)

    def test_graphical_mounts_are_authenticated_and_wayland_is_conditional(self):
        self.assertIn("XAUTHORITY=/tmp/.Xauthority", self.script)
        self.assertIn('"$xauthority:/tmp/.Xauthority:ro"', self.script)
        self.assertIn("if test -S \"$candidate\"", self.script)
        self.assertIn('"$candidate:/tmp/$WAYLAND_DISPLAY:rw"', self.script)
        self.assertIn("install -d --mode=1777 /tmp/.X11-unix", self.dockerfile)


if __name__ == "__main__":
    unittest.main()
