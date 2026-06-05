#!/usr/bin/env python3
"""
Linker MemMap Viewer
====================
Run:   python app.py
Opens: http://localhost:5000  (auto-scans for free port)

Usage:
  1. Drop .ld file — memory map, regions, sections
  2. Drop .elf/.axf — symbols, sizes, DMA warnings, addr→line
  3. Drop .map file — per-.o breakdown, GC'd sections
  4. Set toolchain prefix, e.g.:
       D:\\NXP\\S32DS\\build_tools\\gcc_v11.4\\gcc-11.4-arm32-eabi\\bin\\arm-none-eabi-

Requires:  pip install bottle
"""

import os, sys, json, socket, webbrowser, threading, tempfile, shutil
from pathlib import Path

# ── PyInstaller compatibility ─────────────────────────────────────────────
# When frozen as .exe, files are in sys._MEIPASS (temp extraction folder).
# When running as a script, use the directory of this file.
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from bottle import Bottle, request, response, run, static_file, BaseRequest
except ImportError:
    print('\n[ERROR] Missing dependency.  Run:  pip install bottle\n')
    sys.exit(1)

# Allow large map/elf uploads (up to 256 MB)
BaseRequest.MEMFILE_MAX = 10 * 1024 * 1024  # 10 MB for text form fields

from parsers.ld_parser  import parse_linker_script
from parsers.map_parser import parse_map
from parsers.elf_parser import (
    resolve_tools, save_elf, analyse_elf,
    assign_symbols, make_warnings, startup_cost, run_tool
)

app = Bottle()

# ── Static files ──────────────────────────────────────────────────────────

@app.route('/static/<filename:path>')
def serve_static(filename):
    resp = static_file(filename, root=os.path.join(BASE_DIR, 'static'))
    # Prevent browser caching during development
    resp.set_header('Cache-Control', 'no-cache, no-store, must-revalidate')
    resp.set_header('Pragma', 'no-cache')
    resp.set_header('Expires', '0')
    return resp

# ── Pages ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    tmpl = os.path.join(BASE_DIR, 'templates', 'index.html')
    with open(tmpl, 'r', encoding='utf-8') as f:
        return f.read()

# ── API routes ────────────────────────────────────────────────────────────

@app.route('/parse_ld', method='POST')
def route_parse_ld():
    response.content_type = 'application/json'
    try:
        content = request.forms.get('content', '')
        if not content.strip():
            return json.dumps({"error": "Empty file"})
        return json.dumps(parse_linker_script(content))
    except Exception as ex:
        return json.dumps({"error": str(ex)})


@app.route('/parse_map', method='POST')
def route_parse_map():
    response.content_type = 'application/json'
    try:
        # Large map files may exceed MEMFILE_MAX — bottle moves them to request.files
        content = request.forms.get('content', '')
        if not content.strip():
            up = request.files.get('content')
            if up:
                up.file.seek(0)
                content = up.file.read().decode('utf-8', errors='replace')
        if not content.strip():
            return json.dumps({"error": "Empty map file — file may be too large or wrong format"})
        return json.dumps(parse_map(content))
    except Exception as ex:
        return json.dumps({"error": str(ex)})


@app.route('/analyse_elf', method='POST')
def route_analyse_elf():
    response.content_type = 'application/json'
    tmp = None
    try:
        up = request.files.get('elf')
        if not up:
            return json.dumps({"error": "No ELF file received"})

        raw_tools = json.loads(request.forms.get('tools', '{}'))
        ld_data   = json.loads(request.forms.get('ld_data', '{}'))

        # Save ELF — closed before subprocess opens it (Windows file-lock fix)
        tmp   = save_elf(up)
        tools = resolve_tools(raw_tools)

        symbols, elf_secs, debug = analyse_elf(tmp, tools)

        ld_secs = ld_data.get('sections', [])
        assign_symbols(symbols, elf_secs, ld_secs)

        for reg in ld_data.get('regions', []):
            reg['used_bytes'] = sum(
                elf_secs.get(s['name'], {}).get('size', 0)
                for s in reg.get('sections', []))

        return json.dumps({
            "symbols":      symbols,
            "elf_sections": elf_secs,
            "warnings":     make_warnings(ld_data, elf_secs, symbols),
            "startup":      startup_cost(ld_secs, elf_secs),
            "debug":        debug,
        })

    except Exception as ex:
        import traceback
        return json.dumps({"error": str(ex), "trace": traceback.format_exc()})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except Exception: pass


@app.route('/debug_elf', method='POST')
def route_debug_elf():
    response.content_type = 'application/json'
    tmp = None
    try:
        up = request.files.get('elf')
        if not up:
            return json.dumps({"error": "No ELF file"})

        raw_tools = json.loads(request.forms.get('tools', '{}'))
        tmp   = save_elf(up)
        tools = resolve_tools(raw_tools)
        fsize = os.path.getsize(tmp)
        results = {
            "file_size":  fsize,
            "prefix_in":  tools['prefix_in'],
            "prefix_out": tools['prefix_out'],
            "tools": {}
        }

        for name, t, extra in [
            ('nm',   tools['nm'],   ['--print-size', '--radix=x']),
            ('re',   tools['re'],   ['-S', '--wide']),
            ('size', tools['size'], ['-A', '-x']),
        ]:
            stdout, stderr, rc = run_tool([t] + extra + [tmp])
            results["tools"][name] = {
                "path":   t,
                "found":  bool(shutil.which(t)) or os.path.isfile(t) or os.path.isfile(t+'.exe'),
                "rc":     rc,
                "lines":  len([l for l in stdout.splitlines() if l.strip()]),
                "stdout": stdout[:3000] if stdout else "",
                "stderr": stderr[:800]  if stderr else "",
            }
        return json.dumps(results)

    except Exception as ex:
        import traceback
        return json.dumps({"error": str(ex), "trace": traceback.format_exc()})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except Exception: pass


@app.route('/addr2line', method='POST')
def route_addr2line():
    response.content_type = 'application/json'
    tmp = None
    try:
        addr   = request.forms.get('addr', '').strip()
        raw    = {'prefix': request.forms.get('prefix', ''),
                  'a2l':    request.forms.get('a2l_tool', '')}
        up     = request.files.get('elf')

        if not addr:  return json.dumps({"error": "No address"})
        if not up:    return json.dumps({"error": "No ELF file"})

        try:    addr_int = int(addr, 0)
        except: return json.dumps({"error": f"Bad address: {addr}"})

        tmp  = save_elf(up)
        tool = resolve_tools(raw)['a2l']
        out, err, _ = run_tool([tool, '-e', tmp, '-f', '-C', '-p', hex(addr_int)])
        return json.dumps({"result": out.strip() or err.strip() or "No result"})

    except Exception as ex:
        return json.dumps({"error": str(ex)})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except Exception: pass


# ── Server startup ────────────────────────────────────────────────────────

def find_free_port(candidates):
    for port in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('localhost', port))
                return port
        except OSError:
            pass
    return None


def open_browser(port):
    import time
    time.sleep(0.8)
    webbrowser.open(f'http://localhost:{port}')


if __name__ == '__main__':
    candidates = [5000, 5500, 7000, 7777, 8000, 8080, 8888, 9000, 3000]
    if len(sys.argv) > 1:
        try: candidates = [int(sys.argv[1])] + candidates
        except ValueError: pass

    PORT = find_free_port(candidates)
    if not PORT:
        print('\n[ERROR] No free port found. Try:  python app.py 12345\n')
        sys.exit(1)

    print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  Linker MemMap Viewer  →  http://localhost:{PORT:<5}    ║
  ║                                                      ║
  ║  Files:  lmv/                                        ║
  ║    app.py          ← this file (server + routes)     ║
  ║    parsers/        ← ld_parser, elf_parser, map      ║
  ║    static/         ← CSS + JS modules                ║
  ║    templates/      ← index.html                      ║
  ║                                                      ║
  ║  Toolchain prefix examples:                          ║
  ║    arm-none-eabi-                                    ║
  ║    D:/NXP/S32DS/bin/arm-none-eabi-                   ║
  ║                                                      ║
  ║  Ctrl+C to stop                                      ║
  ╚══════════════════════════════════════════════════════╝
""")
    threading.Thread(target=open_browser, args=(PORT,), daemon=True).start()
    run(app, host='localhost', port=PORT, quiet=True,
        max_request_size=256 * 1024 * 1024)
