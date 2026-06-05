"""ELF binary analysis — nm, readelf, size, addr2line."""
import re, os, subprocess, shutil, tempfile
from pathlib import Path

# ── Toolchain resolution ───────────────────────────────────────────────────

def normalize_prefix(raw):
    """Accept any prefix format, always return one ending with '-' or ''."""
    p = (raw or '').strip()
    if not p:             return ''
    if p.endswith('-'):   return p
    if p[-1] in ('/', '\\'): return p + 'arm-none-eabi-'
    last = os.path.basename(p)
    if '-' not in last:   return p + os.sep + 'arm-none-eabi-'
    return p + '-'


def find_tool(candidates):
    """Return first candidate that exists as an executable."""
    first = ''
    for raw in candidates:
        t = (raw or '').strip()
        if not t: continue
        if not first: first = t
        if shutil.which(t):             return shutil.which(t)
        if os.path.isfile(t):           return t
        if os.path.isfile(t + '.exe'):  return t + '.exe'
    return first


def resolve_tools(raw):
    """Build resolved paths for nm/readelf/size/addr2line."""
    prefix = normalize_prefix(raw.get('prefix', ''))

    def candidates(field, basename):
        explicit = (raw.get(field) or '').strip()
        is_abs = explicit and (
            (len(explicit) > 1 and explicit[1] == ':') or
            explicit.startswith('/') or os.sep in explicit or '/' in explicit
        )
        c = []
        if prefix:                      c.append(prefix + basename)
        if is_abs:                      c.append(explicit)
        if explicit and not is_abs:     c.append(explicit)
        c.append('arm-none-eabi-' + basename)
        c.append(basename)
        return c

    return {
        'nm':   find_tool(candidates('nm',   'nm')),
        're':   find_tool(candidates('re',   'readelf')),
        'size': find_tool(candidates('size', 'size')),
        'a2l':  find_tool(candidates('a2l',  'addr2line')),
        'prefix_in':  raw.get('prefix', ''),
        'prefix_out': prefix,
    }


# ── Subprocess helper ──────────────────────────────────────────────────────

def run_tool(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, errors='replace')
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return '', 'Tool not found: ' + args[0], 1
    except subprocess.TimeoutExpired:
        return '', 'Timeout: ' + ' '.join(args), 1
    except Exception as e:
        return '', str(e), 1


def save_elf(upload):
    """Write uploaded ELF to temp file and CLOSE it before returning.
    Critical on Windows — open handles block subprocess access."""
    suffix = Path(upload.filename).suffix or '.elf'
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        upload.file.seek(0)
        with os.fdopen(fd, 'wb') as f:
            while True:
                chunk = upload.file.read(65536)
                if not chunk: break
                f.write(chunk)
    except Exception:
        try: os.unlink(path)
        except Exception: pass
        raise
    return path


# ── nm parsing ────────────────────────────────────────────────────────────

NM_TYPES = {
    'T':'function','t':'function','W':'weak','w':'weak',
    'D':'variable','d':'variable','B':'variable','b':'variable',
    'R':'constant','r':'constant','C':'common','c':'common',
    'U':'undefined','A':'absolute','a':'absolute',
    'V':'weak_obj','v':'weak_obj','G':'small_data','g':'small_data',
    'S':'small_bss','s':'small_bss','I':'indirect','i':'indirect',
}
SYM_COLORS = {
    'function':'#3b82f6','variable':'#f97316','constant':'#10b981',
    'weak':'#6366f1','undefined':'#6e7681','absolute':'#f59e0b',
    'common':'#8b5cf6','other':'#374151',
}


def parse_nm_line(parts):
    def is_hex(s): return bool(re.match(r'^[0-9a-fA-F]{6,}$', s))
    def is_type(s): return len(s) == 1 and s in 'TtDdBbRrWwUuAaCcVvGgSsIi'

    source = ''
    clean = []
    for p in parts:
        if '\t' in p: source = p.strip('\t'); break
        clean.append(p)
    parts = clean

    try:
        if len(parts) >= 3 and is_hex(parts[0]):
            if len(parts) >= 4 and is_hex(parts[1]) and is_type(parts[2]):
                addr, size, ntype_raw, name = int(parts[0],16), int(parts[1],16), parts[2], ' '.join(parts[3:])
            elif is_type(parts[1]):
                addr, size, ntype_raw, name = int(parts[0],16), 0, parts[1], ' '.join(parts[2:])
            else: return None
        elif len(parts) >= 2 and is_type(parts[0]):
            addr, size, ntype_raw, name = 0, 0, parts[0], ' '.join(parts[1:])
        elif len(parts) >= 3:
            name = parts[0]
            ntype_raw = parts[1]
            addr = int(parts[2],16) if is_hex(parts[2]) else 0
            size = int(parts[3],16) if len(parts)>3 and is_hex(parts[3]) else 0
        else: return None

        ntype = NM_TYPES.get(ntype_raw, 'other')
        return {"name": name, "addr": addr, "size": size, "type": ntype,
                "type_raw": ntype_raw, "global": ntype_raw.isupper(),
                "color": SYM_COLORS.get(ntype, SYM_COLORS['other']),
                "source": source, "section": None, "file": ""}
    except (ValueError, IndexError):
        return None


def parse_nm_output(stdout):
    seen, syms = set(), []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.endswith(':'): continue
        parts = line.split()
        if len(parts) < 2: continue
        sym = parse_nm_line(parts)
        if not sym: continue
        name = sym['name']
        if not name or name.startswith('$'): continue
        key = (name, sym['addr'])
        if key in seen: continue
        seen.add(key)
        syms.append(sym)
    return sorted(syms, key=lambda s: s['addr'])


def parse_readelf_output(stdout):
    secs = {}
    for line in stdout.splitlines():
        m = re.match(
            r'\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+'
            r'([0-9a-fA-F]+)\s+([0-9a-fA-F]+)', line)
        if m:
            secs[m.group(1)] = {"addr": int(m.group(3),16),
                                 "size": int(m.group(5),16),
                                 "type": m.group(2), "flags": ""}
    return secs


def parse_size_output(stdout):
    sizes = {}
    for line in stdout.splitlines():
        m = re.match(r'^(\S+)\s+(0x[0-9a-fA-F]+|\d+)\s+(0x[0-9a-fA-F]+|\d+)', line)
        if m:
            try: sizes[m.group(1)] = {'size': int(m.group(2),0), 'addr': int(m.group(3),0)}
            except Exception: pass
    return sizes


def analyse_elf(tmp_path, tools):
    """Run nm/readelf/size on tmp_path. Return (symbols, elf_secs, debug_info)."""
    nm_t, re_t, sz_t = tools['nm'], tools['re'], tools['size']

    nm_out, nm_err, nm_rc = run_tool([nm_t, '--print-size', '--radix=x', tmp_path])
    if not nm_out.strip():
        nm_out, nm_err, nm_rc = run_tool([nm_t, '--print-size', '--radix=x',
                                            '--line-numbers', tmp_path])
    if not nm_out.strip():
        nm_out, nm_err, nm_rc = run_tool([nm_t, tmp_path])

    re_out, re_err, re_rc = run_tool([re_t, '-S', '--wide', tmp_path])
    sz_out, sz_err, sz_rc = run_tool([sz_t, '-A', '-x', tmp_path])

    def exists(t):
        return bool(shutil.which(t)) or os.path.isfile(t) or os.path.isfile(t+'.exe')

    debug = {
        "file_size":    os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0,
        "prefix_in":    tools['prefix_in'],
        "prefix_out":   tools['prefix_out'],
        "nm_tool":      nm_t,   "nm_ok":  exists(nm_t),
        "nm_rc":        nm_rc,  "nm_lines": len([l for l in nm_out.splitlines() if l.strip()]),
        "nm_stderr":    nm_err[:800]   if nm_err else "",
        "nm_sample":    nm_out[:1200]  if nm_out else "(empty)",
        "re_tool":      re_t,   "re_ok":  exists(re_t),
        "re_rc":        re_rc,
        "re_stderr":    re_err[:400]   if re_err else "",
        "re_sample":    re_out[:600]   if re_out else "(empty)",
        "sz_tool":      sz_t,   "sz_ok":  exists(sz_t),
        "sz_rc":        sz_rc,
        "sz_stderr":    sz_err[:300]   if sz_err else "",
    }

    symbols  = parse_nm_output(nm_out)
    elf_secs = parse_readelf_output(re_out)
    sz_data  = parse_size_output(sz_out)

    for name, s in sz_data.items():
        if name in elf_secs:
            if elf_secs[name]['size'] == 0: elf_secs[name]['size'] = s['size']
        else:
            elf_secs[name] = {'addr': s['addr'], 'size': s['size'],
                              'type': 'PROGBITS', 'flags': ''}

    return symbols, elf_secs, debug


def assign_symbols(symbols, elf_secs, ld_sections):
    ranges = sorted(
        [(s['addr'], s['addr']+s['size'], n)
         for n, s in elf_secs.items() if s['size'] > 0])
    sec_map = {s['name']: s for s in ld_sections}
    for sym in symbols:
        if sym['addr'] == 0 or sym['type'] == 'undefined': continue
        sym['section'] = next(
            (name for start,end,name in ranges if start <= sym['addr'] < end), None)
        if sym['section'] and sym['section'] in sec_map:
            sec_map[sym['section']].setdefault('symbols', []).append(sym)


def make_warnings(ld_data, elf_secs, symbols):
    warns = []
    for reg in ld_data.get('regions', []):
        used = sum(elf_secs.get(s['name'], {}).get('size', 0) for s in reg['sections'])
        if reg['length'] > 0:
            pct = used / reg['length']
            if pct > 0.95:
                warns.append({"level":"error","category":"Memory Overflow",
                    "message":f"{reg['name']} is {pct*100:.1f}% full ({used:,}/{reg['length']:,} bytes)",
                    "detail":"Region nearly full — linker will error on next build."})
            elif pct > 0.80:
                warns.append({"level":"warn","category":"Memory Pressure",
                    "message":f"{reg['name']} is {pct*100:.1f}% full ({used:,}/{reg['length']:,} bytes)",
                    "detail":"Consider LTO, const to flash, or increasing region size."})

    cacheable_ranges = []
    for sec in ld_data.get('sections', []):
        if sec['cacheable']:
            es = elf_secs.get(sec['name'], {})
            if es.get('size', 0) > 0:
                cacheable_ranges.append((es['addr'], es['addr']+es['size'], sec['name']))

    dma_kw = ['buf','buffer','frame','ipc','spi','dma','rx','tx',
               'fifo','packet','msg','transfer']
    for sym in symbols:
        if sym['size'] < 4 or sym['type'] not in ('variable','common'): continue
        if not any(k in sym['name'].lower() for k in dma_kw): continue
        for start,end,sec_name in cacheable_ranges:
            if start <= sym['addr'] < end:
                warns.append({"level":"warn","category":"DMA Safety",
                    "message":f"'{sym['name']}' ({sym['size']} B) in cacheable '{sec_name}'",
                    "detail":f"0x{sym['addr']:08X} — DMA access here causes cache incoherency. "
                             f"Move to .non_cacheable_bss.",
                    "symbols":[sym]})
                break

    for sym in sorted([s for s in symbols if s['size']>1024
                       and s['type'] in ('variable','common')],
                      key=lambda s: -s['size'])[:5]:
        warns.append({"level":"info","category":"Large RAM Symbol",
            "message":f"'{sym['name']}' uses {sym['size']:,} bytes",
            "detail":f"0x{sym['addr']:08X} in {sym.get('section','?')}. "
                     f"If constant, consider placing in flash.",
            "symbols":[sym]})

    for sym in sorted([s for s in symbols if s['size']>4096 and s['type']=='function'],
                      key=lambda s: -s['size'])[:5]:
        warns.append({"level":"info","category":"Large Function",
            "message":f"'{sym['name']}' is {sym['size']:,} bytes",
            "detail":f"0x{sym['addr']:08X}. Large functions increase I-cache pressure.",
            "symbols":[sym]})

    return warns


def startup_cost(ld_sections, elf_secs):
    items, total_copy, total_zero = [], 0, 0
    for sec in ld_sections:
        sz = elf_secs.get(sec['name'], {}).get('size', 0)
        if not sz: continue
        if sec['noload']:
            total_zero += sz
            items.append({"section":sec['name'],"type":"zeroed","size":sz,
                          "vma":sec['vma'],"lma":sec['lma']})
        elif sec['lma']:
            total_copy += sz
            items.append({"section":sec['name'],"type":"copied","size":sz,
                          "vma":sec['vma'],"lma":sec['lma']})
    return {"items":items,"total_copy":total_copy,"total_zero":total_zero}
