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
from parsers.callgraph_parser import analyse_callgraph
from parsers.disasm_parser   import disassemble
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

@app.route('/scan_su', method='POST')
def route_scan_su():
    """
    Walk a directory tree and catalogue ALL analysis-relevant GCC output files.

    Searches recursively for:
        .su  → per-function stack frame sizes (needs -fstack-usage)
        .ci  → call graph with stack costs (needs -fcallgraph-info=su,da)
        .d   → header dependency lists (generated automatically)
        .o   → object files (exist in every build)

    Returns:
        {
          "su_files":  [...],   list of .su files found
          "ci_files":  [...],   list of .ci files found
          "d_files":   [...],   list of .d  files found
          "o_files":   [...],   count of .o files (not listed individually)
          "has_su":    bool,
          "has_ci":    bool,
          "has_d":     bool,
          "summary":   str      human-readable description of what was found
        }

    EMBEDDED ENGINEER NOTE:
        If has_su=True and has_ci=True  → full worst-case call-chain analysis available
        If has_su=True and has_ci=False → per-function frame sizes only (add -fcallgraph-info=su,da)
        If has_su=False                 → no stack data (add -fstack-usage and rebuild)
    """
    response.content_type = 'application/json'
    try:
        path = request.forms.get('path', '').strip()
        if not path:
            return json.dumps({"error": "No path provided"})

        # Support environment variables and ~ in path (useful for CI/CD paths)
        path = os.path.expandvars(os.path.expanduser(path))

        if not os.path.isdir(path):
            return json.dumps({
                "error": f"Directory not found: {path}",
                "hint":  "Check the path is a build output directory (e.g. Debug/ or Release/)"
            })

        su_files, ci_files, d_files = [], [], []
        o_count = 0

        # os.walk recurses into ALL subdirectories automatically.
        # We only skip hidden dirs (.git, .svn) and non-build dirs.
        # NOTE: dirs[:] modifies the list IN PLACE — this is the correct
        # way to prune os.walk subdirectory traversal.
        for root, dirs, fnames in os.walk(path):
            dirs[:] = sorted(
                d for d in dirs
                if not d.startswith('.')
                and d not in ('node_modules', '.git', '.svn', '__pycache__', '.vs')
            )

            rel = os.path.relpath(root, path)
            rel = '' if rel == '.' else rel

            for fname in sorted(fnames):
                full = os.path.join(root, fname)
                size = os.path.getsize(full)

                if fname.endswith('.su'):
                    su_files.append({
                        "path": full,
                        "name": fname,
                        "stem": fname[:-3],    # filename without .su, matches .ci stem
                        "dir":  rel or '(root)',
                        "size": size,
                    })
                elif fname.endswith('.ci'):
                    ci_files.append({
                        "path": full,
                        "name": fname,
                        "stem": fname[:-3],
                        "dir":  rel or '(root)',
                        "size": size,
                    })
                elif fname.endswith('.d'):
                    d_files.append({
                        "path": full,
                        "name": fname,
                        "dir":  rel or '(root)',
                        "size": size,
                    })
                elif fname.endswith('.o') or fname.endswith('.obj'):
                    o_count += 1

        # Sort all lists: shallowest first then alphabetical
        key = lambda f: (f['dir'].count(os.sep), f['name'])
        su_files.sort(key=key)
        ci_files.sort(key=key)
        d_files.sort(key=key)

        # Match .ci files to .su files by stem (same base filename)
        su_stems = {f['stem'] for f in su_files}
        ci_stems = {f['stem'] for f in ci_files}
        matched  = su_stems & ci_stems    # files that have both .su and .ci

        # Build human-readable summary for the UI
        has_su = len(su_files) > 0
        has_ci = len(ci_files) > 0
        has_d  = len(d_files)  > 0

        if has_su and has_ci:
            summary = (
                f"Found {len(su_files)} .su and {len(ci_files)} .ci files "
                f"({len(matched)} matched pairs). "
                f"Full worst-case call-chain analysis available."
            )
            level = "full"
        elif has_su:
            summary = (
                f"Found {len(su_files)} .su files but no .ci files. "
                f"Per-function stack frames available. "
                f"Add -fcallgraph-info=su,da for worst-case call-chain analysis."
            )
            level = "partial"
        else:
            summary = (
                f"No .su files found in {path}. "
                f"Add -fstack-usage to GCC flags and rebuild."
            )
            level = "none"

        return json.dumps({
            "su_files":  su_files,
            "ci_files":  ci_files,
            "d_files":   d_files,   # not used by UI yet, but available
            "o_count":   o_count,
            "has_su":    has_su,
            "has_ci":    has_ci,
            "has_d":     has_d,
            "matched":   len(matched),
            "level":     level,      # "full" | "partial" | "none"
            "summary":   summary,
        })

    except PermissionError as ex:
        return json.dumps({"error": f"Permission denied: {ex.filename}"})
    except Exception as ex:
        import traceback
        return json.dumps({"error": str(ex), "trace": traceback.format_exc()})


@app.route('/load_su_files', method='POST')
def route_load_su_files():
    """
    Read the contents of selected .su and .ci files and return them.

    Accepts .su files (stack frame data) AND .ci files (call graph data).
    Both are plain text — same read logic, different consumer on the JS side.
    """
    response.content_type = 'application/json'
    try:
        paths = json.loads(request.forms.get('paths', '[]'))
        if not paths:
            return json.dumps({"error": "No paths provided"})

        files  = []
        errors = []
        for path in paths:
            path = os.path.expandvars(os.path.expanduser(path))
            if not os.path.isfile(path):
                errors.append(f"Not found: {path}")
                continue
            # Accept .su (stack usage) and .ci (call graph info) — both plain text
            if not (path.endswith('.su') or path.endswith('.ci')):
                errors.append(f"Unsupported file type (expected .su or .ci): {path}")
                continue
            try:
                with open(path, 'r', errors='replace') as fh:
                    content = fh.read()
                files.append({
                    "name":    os.path.basename(path),
                    "path":    path,
                    "content": content,
                    "type":    "ci" if path.endswith('.ci') else "su",
                })
            except Exception as e:
                errors.append(f"{path}: {e}")

        return json.dumps({"files": files, "errors": errors})

    except Exception as ex:
        return json.dumps({"error": str(ex)})



@app.route('/disassemble', method='POST')
def route_disassemble():
    """
    Disassemble the function containing a given address.

    Accepts:
        addr           hex string  e.g. "0x00401234"
        context_lines  int         lines before/after target (default 10)
        func_start     hex string  optional — if caller knows from nm
        func_end       hex string  optional
        prefix         str         toolchain prefix
        tools_json     JSON str    full tools dict (nm, re, size, a2l, objdump)

    Returns:
        Full disassembly result from disasm_parser.disassemble()

    EMBEDDED ENGINEER NOTE:
        The disassembly is most useful when the ELF was built with -g.
        Without debug info, C source lines won't appear — but ARM Thumb-2
        instruction analysis still works.
    """
    response.content_type = 'application/json'
    tmp = None
    try:
        up = request.files.get('elf')
        if not up:
            return json.dumps({"error": "No ELF file — load ELF and click Analyse ELF first"})

        addr_str = request.forms.get('addr', '').strip()
        if not addr_str:
            return json.dumps({"error": "No address provided"})

        try:
            target_addr = int(addr_str, 0)
        except ValueError:
            return json.dumps({"error": f"Invalid address: {addr_str}"})

        context_lines = int(request.forms.get('context_lines', '10'))
        context_lines = max(1, min(context_lines, 100))   # clamp 1–100

        raw_tools = json.loads(request.forms.get('tools_json', '{}'))
        tools     = resolve_tools(raw_tools)

        # Optional known function bounds (avoids a second objdump pass)
        func_start_str = request.forms.get('func_start', '').strip()
        func_end_str   = request.forms.get('func_end',   '').strip()
        func_start = int(func_start_str, 0) if func_start_str else None
        func_end   = int(func_end_str,   0) if func_end_str   else None

        tmp = save_elf(up)

        source_dir = request.forms.get('source_dir', '').strip() or None
        if source_dir:
            source_dir = os.path.expandvars(os.path.expanduser(source_dir))

        result = disassemble(
            tmp_path      = tmp,
            tools         = tools,
            target_addr   = target_addr,
            context_lines = context_lines,
            func_start    = func_start,
            func_end      = func_end,
            source_dir    = source_dir,
        )
        return json.dumps(result)

    except Exception as ex:
        import traceback
        return json.dumps({"error": str(ex), "trace": traceback.format_exc()})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except Exception: pass


@app.route('/debug_ci', method='POST')
def route_debug_ci():
    """
    Debug route: returns the first 60 lines of an uploaded .ci file
    so we can see the actual GCC format and fix the parser accordingly.
    """
    response.content_type = 'application/json'
    try:
        content = request.forms.get('content', '')
        if not content:
            up = request.files.get('file')
            if up:
                up.file.seek(0)
                content = up.file.read().decode('utf-8', errors='replace')
        lines   = content.splitlines()
        return json.dumps({
            "total_lines": len(lines),
            "sample":      lines[:60],
            "raw60":       content[:3000],
        })
    except Exception as ex:
        return json.dumps({"error": str(ex)})


@app.route('/analyse_callgraph', method='POST')
def route_analyse_callgraph():
    """
    Parse uploaded .ci files and compute worst-case stack depths.

    Accepts:
        ci_contents  JSON array of {name, content} objects
        su_entries   JSON array of already-parsed .su entries (for frame-size fallback)

    Returns callgraph analysis from callgraph_parser.analyse_callgraph().

    SOFTWARE ENGINEER NOTE:
        This route does the heavy computation server-side so the browser
        doesn't need to implement a graph algorithm. The result is a simple
        dict that the frontend renders as a table + call-chain visualisation.
    """
    response.content_type = 'application/json'
    try:
        ci_list   = json.loads(request.forms.get('ci_contents', '[]'))
        su_list   = json.loads(request.forms.get('su_entries',  '[]'))

        if not ci_list:
            return json.dumps({"error": "No .ci file contents provided"})

        contents = [item['content'] for item in ci_list if 'content' in item]
        result   = analyse_callgraph(contents, su_list or None)

        if result is None:
            return json.dumps({"error": "Callgraph analysis produced no results"})

        # top_worst path lists can be large — truncate to 10 steps for the UI
        for item in result.get('top_worst', []):
            if len(item.get('path', [])) > 10:
                item['path'] = item['path'][:10] + ['...']

        return json.dumps(result)

    except Exception as ex:
        import traceback
        return json.dumps({"error": str(ex), "trace": traceback.format_exc()})


@app.route('/scan_source', method='POST')
def route_scan_source():
    """
    Walk a directory tree and return all source files found.

    Searches recursively for: .c .cpp .cxx .cc .h .hpp .s .asm .inc
    Returns list of {path, name, ext, dir, size} sorted shallowest-first.

    The browser cannot access the filesystem directly — this route lets the
    user type a path and see what source files the server finds, then pick
    which ones to load (same pattern as /scan_su for .su/.ci files).
    """
    response.content_type = 'application/json'
    try:
        path = (request.forms.get('path', '') or '').strip()
        if not path:
            return json.dumps({"error": "No path provided"})

        path = os.path.expandvars(os.path.expanduser(path))
        if not os.path.isdir(path):
            return json.dumps({"error": f"Directory not found: {path}"})

        SOURCE_EXTS = {'.c', '.cpp', '.cxx', '.cc', '.h', '.hpp',
                       '.s', '.asm', '.inc', '.c++', '.hxx', '.h++'}

        files = []
        for root, dirs, fnames in os.walk(path):
            # Skip common non-source directories
            dirs[:] = sorted(d for d in dirs
                             if not d.startswith('.')
                             and d not in ('node_modules', '.git', '.svn',
                                           '__pycache__', 'Debug', 'Release',
                                           'build', 'dist', '.vs', 'obj'))
            rel = os.path.relpath(root, path)
            rel = '' if rel == '.' else rel
            for fname in sorted(fnames):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SOURCE_EXTS:
                    full = os.path.join(root, fname)
                    files.append({
                        "path": full,
                        "name": fname,
                        "ext":  ext,
                        "dir":  rel or '(root)',
                        "size": os.path.getsize(full),
                    })

        # Sort: shallowest first, then alphabetical
        files.sort(key=lambda f: (f['dir'].count(os.sep), f['name']))

        return json.dumps({"files": files, "total": len(files), "root": path})

    except PermissionError as ex:
        return json.dumps({"error": f"Permission denied: {ex.filename}"})
    except Exception as ex:
        return json.dumps({"error": str(ex)})


@app.route('/load_source_files', method='POST')
def route_load_source_files():
    """
    Read selected source files and return their contents.
    Used when the user picks files from the /scan_source picker.
    """
    response.content_type = 'application/json'
    try:
        paths = json.loads(request.forms.get('paths', '[]'))
        if not paths:
            return json.dumps({"error": "No paths provided"})

        files  = []
        errors = []
        SOURCE_EXTS = {'.c', '.cpp', '.cxx', '.cc', '.h', '.hpp',
                       '.s', '.asm', '.inc', '.c++', '.hxx', '.h++'}

        for path in paths:
            path = os.path.expandvars(os.path.expanduser(path))
            ext  = os.path.splitext(path)[1].lower()
            if not os.path.isfile(path):
                errors.append(f"Not found: {path}"); continue
            if ext not in SOURCE_EXTS:
                errors.append(f"Not a source file: {path}"); continue
            try:
                with open(path, 'r', errors='replace') as fh:
                    content = fh.read()
                files.append({"name": os.path.basename(path),
                              "path": path, "content": content})
            except Exception as e:
                errors.append(f"{path}: {e}")

        return json.dumps({"files": files, "errors": errors})

    except Exception as ex:
        return json.dumps({"error": str(ex)})



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
