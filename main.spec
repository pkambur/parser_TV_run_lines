# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('bin\\\\tesseract.exe', 'bin'), ('bin\\\\ffmpeg.exe', 'bin'), ('bin\\\\ffprobe.exe', 'bin')],
    datas=[('channels.json', '.'), ('keywords.json', '.'), ('Р24 (1).png', '.'), ('bin\\\\tessdata', 'bin\\\\tessdata'), ('config.json', '.')],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='Мониторинг строк МЧС',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
