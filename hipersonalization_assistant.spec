# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = collect_data_files("bs4")
datas += [("assets/hipersonalization.ico", "assets")]
hiddenimports = collect_submodules("keyring.backends")

analysis = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="hipersonalization订单处理助手 v0.13 by Robin+Codex",
    icon="assets/hipersonalization.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
