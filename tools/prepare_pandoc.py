#!/usr/bin/env python3
"""Download and verify the platform Pandoc binary used by PyInstaller."""

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

import pypandoc


MIN_VERSION = (3, 1, 7)


def _version_tuple(version):
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", str(version))
    if not match:
        raise RuntimeError(f"Versão do Pandoc não reconhecida: {version}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def prepare(output_dir):
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    executable = destination / ("pandoc.exe" if sys.platform == "win32" else "pandoc")

    with tempfile.TemporaryDirectory(prefix="pandoc_build_download_") as download_dir:
        pypandoc.download_pandoc(
            targetfolder=str(destination),
            delete_installer=True,
            download_folder=download_dir,
        )

    if not executable.is_file():
        raise RuntimeError(f"Pandoc não foi criado em {executable}")

    os.environ["PYPANDOC_PANDOC"] = str(executable)
    pypandoc.clean_pandocpath_cache()
    pypandoc.clean_version_cache()
    version = pypandoc.get_pandoc_version()
    if _version_tuple(version) < MIN_VERSION:
        raise RuntimeError(f"Pandoc {version} é anterior ao mínimo 3.1.7")
    print(f"Pandoc {version} preparado em {executable}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    prepare(args.output_dir)


if __name__ == "__main__":
    main()
