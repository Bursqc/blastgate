# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['blastgate', 'blastgate.gui', 'blastgate.gui.app', 'blastgate.gui.utils', 'blastgate.gui.dialogs', 'blastgate.gui.dialogs.connect', 'blastgate.gui.dialogs.settings', 'blastgate.gui.dialogs.wifi', 'blastgate.gui.dialogs.node_detail', 'blastgate.gui.dialogs.calibration', 'blastgate.gui.dialogs.setup_wizard', 'blastgate.gui.components', 'blastgate.gui.components.animated_toggle', 'blastgate.gui.components.dropdown_menu', 'blastgate.gui.components.loading_spinner', 'blastgate.gui.components.rounded_tile', 'blastgate.network', 'blastgate.network.client', 'blastgate.network.engine', 'blastgate.network.discovery', 'blastgate.network.protocol', 'blastgate.models', 'blastgate.models.config', 'blastgate.models.status', 'blastgate.models.node', 'blastgate.controllers', 'blastgate.controllers.auto_controller', 'blastgate.utils', 'blastgate.utils.helpers', 'blastgate.utils.validators', 'blastgate.utils.errors', 'blastgate.utils.firewall', 'blastgate.constants', 'blastgate.config', 'blastgate.logging_config', 'blastgate.exceptions', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont']
tmp_ret = collect_all('ttkbootstrap')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pydantic')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['blastgate\\__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Blastgate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Blastgate',
)
