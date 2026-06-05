# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Linker MemMap Viewer
#
# Build command (run from the lmv/ directory):
#   pyinstaller linker_memmap.spec
#
# Output:
#   dist/LinkerMemMap.exe   ← single file, no install needed

import os

# Collect all static assets (CSS, JS, HTML) that must be bundled
# PyInstaller copies these into a temp folder at runtime
datas = [
    ('static',    'static'),     # static/app.css, static/*.js
    ('templates', 'templates'),  # templates/index.html
    ('README.md', '.'),          # optional, nice to have
]

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # bottle uses these at runtime but PyInstaller may miss them
        'bottle',
        'email.mime.text',
        'email.mime.multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we definitely don't need — shrinks the exe
        'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL',
        'tkinter', 'wx', 'gtk',
        'IPython', 'jupyter',
        'test', 'unittest',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LinkerMemMap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # compress with UPX if available (reduces size ~30%)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # keep console so you see the port number and errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',  # uncomment and add an .ico file to brand it
)
