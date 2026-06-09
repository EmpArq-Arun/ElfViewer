# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Linker MemMap Viewer
# Build:  pyinstaller linker_memmap.spec  (from inside the lmv/ directory)
# Output: dist/LinkerMemMap.exe
#
# ISSUE 6 — libdep.so / 0xc000012f error:
#   This error occurs when PyInstaller bundles shared libraries that Windows
#   cannot load (typically Linux .so files accidentally included).
#   Fixes applied:
#     - Explicit excludes list strips unused heavy packages
#     - collect_data_files / collect_dynamic_libs not used (no heavy deps)
#     - UPX compression disabled — UPX can corrupt some PE headers on Win32
#
# ISSUE 7 — No terminal window in background:
#   console=False  →  no black CMD window appears alongside the browser
#   The server runs as a hidden background process.
#   The browser page sends POST /shutdown to stop it cleanly.
#   A system tray icon is NOT added (requires additional dependencies) but
#   the browser page has a "Stop server" button that calls /shutdown.

import os
import sys

# Collect all static assets that must be bundled with the exe
datas = [
    ('static',    'static'),      # CSS + JS
    ('templates', 'templates'),   # index.html
    ('parsers',   'parsers'),     # Python parser modules
    ('README.md', '.'),
]

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'bottle',
        'parsers.ld_parser',
        'parsers.elf_parser',
        'parsers.map_parser',
        'parsers.callgraph_parser',
        'parsers.disasm_parser',
        'email.mime.text',
        'email.mime.multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Strip everything we don't need — reduces size and avoids
        # bundling Linux shared libs that cause the 0xc000012f error
        'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'Pillow',
        'tkinter', 'wx', 'gtk', 'gi',
        'IPython', 'jupyter', 'notebook',
        'test', 'unittest', 'doctest',
        'pydoc', 'xml.etree',
        'cryptography', 'OpenSSL', 'ssl',
        'sqlite3',
        '_pytest', 'pytest',
        'setuptools', 'pkg_resources',
        'distutils',
        'email.mime.image',    # keep text + multipart, drop image
        'http.server',         # we use bottle, not stdlib server
        'xmlrpc',
    ],
    noarchive=False,
    optimize=1,
)

# Filter out any .so files that aren't for Windows — these cause 0xc000012f
# (They can appear when building on WSL or if Python was built on Linux)
def is_windows_binary(src, dst):
    if src.endswith('.so') or '.so.' in src:
        return False   # skip Linux shared libs
    return True

a.binaries = [(dst, src, typ) for (dst, src, typ) in a.binaries
              if is_windows_binary(src, dst)]

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
    upx=False,          # ISSUE 6 FIX: UPX disabled — can corrupt PE headers
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # ISSUE 7 FIX: no console window — server runs silently
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Uncomment to add a custom icon:
    # icon='icon.ico',
)
