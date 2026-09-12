# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['nebula.py'],
    pathex=[],
    binaries=[],
    datas=[('nebula_ui/index.html', 'nebula_ui'), ('nebula_ui/menu.png', 'nebula_ui'), ('config.example.json', '.')],
    hiddenimports=['events', 'visual', 'window_capture', 'nebula_settings', 'providers', 'ScreenCaptureKit', 'WebKit', 'keyring.backends.macOS'],
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
    name='Nebula',
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
    name='Nebula',
)
app = BUNDLE(
    coll,
    name='Nebula.app',
    icon='nebula_ui/Nebula.icns',
    bundle_identifier='local.nebula.app',
    info_plist={'LSUIElement': True, 'NSPrincipalClass': 'NSApplication',
                'CFBundleShortVersionString': '2.0.0', 'CFBundleVersion': '3'},
)
