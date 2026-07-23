# -*- mode: python ; coding: utf-8 -*-
# Build with: pyinstaller pyinstaller.spec
#
# Produces a one-folder ("onedir") bundle containing the main executable plus
# all dependencies. templates/ and prompts/ are bundled as data so
# core.paths.resource_path() can find them at runtime regardless of the
# process's current working directory.

import sys

block_cipher = None

hiddenimports = []
if sys.platform == "win32":
    hiddenimports += ["keyring.backends.Windows"]
elif sys.platform == "darwin":
    hiddenimports += ["keyring.backends.macOS"]
else:
    hiddenimports += ["keyring.backends.SecretService", "keyring.backends.kwallet"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("prompts", "prompts"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AuditoriaZabbix",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AuditoriaZabbix",
)
