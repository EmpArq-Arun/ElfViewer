#!/usr/bin/env python3
"""
Linker MemMap Viewer - ELF Symbol Analyser
==========================================
Run:  python linker_viewer.py
Opens browser automatically at http://localhost:5000

Usage:
  1. Drop .ld linker script in sidebar
  2. Drop .elf/.axf in sidebar (optional - for symbol analysis)
  3. Paste your toolchain path in the Prefix field, e.g.:
       D:/NXP/S32DS.3.6.4/S32DS/build_tools/gcc_v11.4/gcc-11.4-arm32-eabi/bin/arm-none-eabi-
     (trailing dash optional - auto-detected)
  4. Click Analyse ELF

Requires:  pip install bottle
"""

import re, sys, json, os, subprocess, shutil, webbrowser, threading, socket, tempfile
from pathlib import Path

try:
    from bottle import Bottle, request, response, run
except ImportError:
    print("\n[ERROR] Missing dependency.  Run:  pip install bottle\n")
    sys.exit(1)

app = Bottle()

# ---------------------------------------------------------------------------
# LINKER SCRIPT PARSER
# ---------------------------------------------------------------------------

SECTION_HINTS = {
    ".text":                    ("Code",       "Compiled C/C++ functions"),
    ".startup":                 ("Code",       "Reset handler and startup assembly"),
    ".systeminit":              ("Code",       "Clock and core init before main()"),
    ".intc_vector":             ("Vectors",    "Interrupt vector table — ISR function pointers"),
    ".isr_vector":              ("Vectors",    "STM32 interrupt vector table"),
    ".core_loop":               ("Code",       "Core idle loop"),
    ".init":                    ("Code",       "C runtime .init functions"),
    ".fini":                    ("Code",       "C runtime .fini functions"),
    ".itcm_text":               ("ITCM Code",  "Code in Instruction TCM — zero wait-state execution"),
    ".acfls_code_rom":          ("Flash Acc",  "Flash driver in ROM — must be copied to RAM before use"),
    ".acfls_code_ram":          ("Flash Acc",  "Flash driver running from RAM during erase/write"),
    ".acmem_43_infls_code_rom": ("Flash Acc",  "Internal flash driver in ROM"),
    ".acmem_43_infls_code_ram": ("Flash Acc",  "Internal flash driver running from RAM"),
    ".rodata":                  ("RO Data",    "Read-only data — string literals, const globals"),
    ".mcal_const":              ("RO Data",    "MCAL driver constant configuration"),
    ".mcal_const_cfg":          ("RO Data",    "MCAL configuration structures from tooling"),
    ".mcal_const_no_cacheable": ("RO Data NC", "MCAL constants in non-cacheable SRAM for DMA"),
    ".boot_header":             ("Boot",       "Boot header for ROM bootloader / HSE"),
    ".pflash":                  ("Flash",      "Primary flash — code and read-only data"),
    ".data":                    ("Init Data",  "Initialised globals — stored in flash, copied to SRAM at boot"),
    ".mcal_data":               ("Init Data",  "MCAL driver initialised state"),
    ".ramcode":                 ("Init Data",  "Code that must execute from RAM"),
    ".dtcm_data":               ("DTCM Data",  "Initialised data in Data TCM — zero wait-state"),
    ".mcal_data_no_cacheable":  ("NC Data",    "Driver data in non-cacheable SRAM for DMA peripherals"),
    ".non_cacheable_data":      ("NC Data",    "Non-cacheable SRAM — DMA buffers, IPC frames"),
    ".mcal_shared_data":        ("Shared",     "Initialised data shared between cores"),
    ".shareable_data":          ("Shared",     "Shareable memory for multiple cores"),
    ".bss":                     ("BSS",        "Uninitialised globals — zeroed at boot, costs no flash"),
    ".mcal_bss":                ("BSS",        "Uninitialised MCAL driver state"),
    ".dtcm_bss":                ("DTCM BSS",   "Uninitialised data in Data TCM"),
    ".mcal_bss_no_cacheable":   ("NC BSS",     "Uninitialised non-cacheable SRAM — DMA buffers"),
    ".non_cacheable_bss":       ("NC BSS",     "Uninitialised non-cacheable SRAM"),
    ".mcal_shared_bss":         ("Shared BSS", "Uninitialised shared memory between cores"),
    ".shareable_bss":           ("Shared BSS", "Uninitialised shareable memory"),
    ".standby_data":            ("Standby",    "Preserved across low-power standby — not zeroed on wakeup"),
    ".heap":                    ("Heap",       "malloc/free arena — keep small in safety-critical code"),
    "_user_heap_stack":         ("Heap+Stack", "STM32 CubeMX combined heap+stack reservation"),
    ".stack":                   ("Stack",      "Main stack — overflow causes HardFault"),
    ".int_vector":              ("Vect RAM",   "Vector table in RAM — enables runtime IRQ remapping"),
    ".int_results":             ("Results",    "BIST / test results storage"),
    ".ARM":                     ("ARM Init",   "ARM runtime init/fini arrays"),
    ".preinit_array":           ("Init Array", "Pre-init constructor pointers"),
    ".init_array":              ("Init Array", "Global constructor pointers — C++ static init"),
    ".fini_array":              ("Fini Array", "Global destructor pointers"),
    ".sram_data":               ("Init Data",  "Initialised data in SRAM"),
    ".sram_bss":                ("BSS",        "Uninitialised SRAM"),
    ".data_tcm_data":           ("DTCM Data",  "Initialised data in Data TCM"),
    ".bss_tcm_data":            ("DTCM BSS",   "Uninitialised data in Data TCM"),
}

TYPE_COLORS = {
    "Code":"#3b82f6","ITCM Code":"#06b6d4","Flash Acc":"#8b5cf6",
    "Vectors":"#f59e0b","Vect RAM":"#f59e0b","RO Data":"#10b981",
    "RO Data NC":"#059669","Boot":"#6366f1","Flash":"#2563eb",
    "Init Data":"#f97316","DTCM Data":"#fb923c","NC Data":"#ef4444",
    "Shared":"#ec4899","Shared BSS":"#a855f7","BSS":"#64748b",
    "DTCM BSS":"#475569","NC BSS":"#94a3b8","Standby":"#14b8a6",
    "Heap":"#84cc16","Heap+Stack":"#65a30d","Stack":"#a3e635",
    "Results":"#6b7280","ARM Init":"#8b5cf6","Init Array":"#7c3aed",
    "Fini Array":"#6d28d9","Unknown":"#374151",
}

REGION_COLORS = {
    "flash":"#0d2140","sram":"#0d2818","itcm":"#0d1e33",
    "dtcm":"#1a0d33","dflash":"#1e1e0d","default":"#141420",
}

DMA_SAFE  = {".non_cacheable_data",".non_cacheable_bss",
             ".mcal_data_no_cacheable",".mcal_bss_no_cacheable"}
CACHEABLE = {".data",".bss",".sram_data",".sram_bss",
             ".dtcm_data",".dtcm_bss",".ramcode"}


def _pv(s):
    """Parse linker numeric literal."""
    s = s.strip()
    try:
        s2 = re.sub(r'(?i)0x([0-9a-f]+)', lambda m: str(int(m.group(1),16)), s)
        s2 = re.sub(r'(?i)(\d+)[kK]', lambda m: str(int(m.group(1))*1024), s2)
        s2 = re.sub(r'(?i)(\d+)[mM]', lambda m: str(int(m.group(1))*1048576), s2)
        return int(eval(s2))
    except Exception:
        return 0


def _strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _classify_region(name, attrs):
    n, a = name.lower(), attrs.lower()
    if 'itcm' in n:                               return 'itcm'
    if 'dtcm' in n or 'stack' in n:               return 'dtcm'
    if 'dflash' in n or 'data_flash' in n:        return 'dflash'
    if 'flash' in n or 'rom' in n or ('r' in a and 'x' in a): return 'flash'
    if 'sram' in n or 'ram' in n:                 return 'sram'
    return 'default'


def parse_linker_script(content):
    content = _strip_comments(content)
    regions, reg_map = [], {}

    mb = re.search(r'MEMORY\s*\{([^}]+)\}', content, re.DOTALL)
    if mb:
        for m in re.finditer(
            r'(\w+)\s*(?:\(([^)]*)\))?\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*,'
            r'\s*LENGTH\s*=\s*(0x[0-9A-Fa-f]+|\d+)',
            mb.group(1)
        ):
            name  = m.group(1)
            attrs = (m.group(2) or '').strip()
            origin, length = _pv(m.group(3)), _pv(m.group(4))
            rtype = _classify_region(name, attrs)
            reg   = {"name":name,"attrs":attrs,"origin":origin,"length":length,
                     "end":origin+length,"type":rtype,
                     "color":REGION_COLORS.get(rtype,REGION_COLORS["default"]),
                     "sections":[],"used_bytes":0}
            regions.append(reg)
            reg_map[name] = reg

    sections = []
    sb = re.search(r'SECTIONS\s*\{(.+)', content, re.DOTALL)
    if sb:
        for m in re.finditer(
            r'(\.[\w.]+)\s*(?:\([^)]*\))?\s*(?::\s*(?:AT\s*\([^)]+\)\s*)?)?'
            r'\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}[^>]*>\s*(\w+)?(?:\s*AT\s*>\s*(\w+))?',
            sb.group(1), re.DOTALL
        ):
            sname = m.group(1)
            noload = bool(re.search(r'\bNOLOAD\b', m.group(0)))
            vma, lma = m.group(3), m.group(4)
            hint  = next((k for k in SECTION_HINTS if sname.startswith(k)), None)
            stype, sdesc = SECTION_HINTS.get(hint or sname, ("Unknown","Unknown section"))
            sec = {"name":sname,"vma":vma,"lma":lma,"noload":noload,
                   "type":stype,"desc":sdesc,
                   "dma_safe":sname in DMA_SAFE,"cacheable":sname in CACHEABLE,
                   "color":TYPE_COLORS.get(stype,TYPE_COLORS["Unknown"]),
                   "size":0,"symbols":[]}
            sections.append(sec)
            if vma and vma in reg_map:
                reg_map[vma]["sections"].append(sec)

    entry = ""
    em = re.search(r'ENTRY\s*\((\w+)\)', content)
    if em:
        entry = em.group(1)

    return {"regions":regions,"sections":sections,"entry":entry}


# ---------------------------------------------------------------------------
# TOOLCHAIN PATH RESOLUTION
# ---------------------------------------------------------------------------

def normalize_prefix(raw):
    """
    Accept toolchain prefix in any format the user might paste:
      D:/NXP/bin/arm-none-eabi-     full prefix, trailing dash
      D:/NXP/bin/arm-none-eabi      full prefix, no trailing dash
      D:/NXP/bin/                   directory only
      D:/NXP/bin                    directory, no trailing sep
      arm-none-eabi-                bare prefix on PATH
      (empty string)                use PATH only
    Always returns a prefix that ends with '-' or is empty.
    """
    p = (raw or '').strip()
    if not p:
        return ''
    # Already correct
    if p.endswith('-'):
        return p
    # Directory separator at end — append standard triplet
    if p[-1] in ('/', '\\'):
        return p + 'arm-none-eabi-'
    # Check if the last path component looks like a directory (no hyphens)
    last = os.path.basename(p)
    if '-' not in last:
        # It's a directory path without trailing sep
        return p + os.sep + 'arm-none-eabi-'
    # Must be missing the trailing dash (e.g. 'arm-none-eabi')
    return p + '-'


def find_tool(candidates):
    """
    Return the first candidate that exists as an executable.
    Tries with and without .exe suffix (Windows).
    Falls back to first non-empty candidate so the error message is useful.
    """
    first = ''
    for raw in candidates:
        t = (raw or '').strip()
        if not t:
            continue
        if not first:
            first = t
        # shutil.which handles PATH lookup and .exe extension on Windows
        found = shutil.which(t)
        if found:
            return found
        # Direct absolute path check (handles paths not on PATH)
        if os.path.isfile(t):
            return t
        if os.path.isfile(t + '.exe'):
            return t + '.exe'
    return first  # nothing found — return first so error message names the tool


def resolve_tools(raw):
    """
    Build a dict of resolved absolute paths for nm/readelf/size/addr2line.
    'raw' is the dict sent from the browser:
      { nm, re, size, a2l, prefix }
    Priority per tool:
      1. prefix + basename  (if prefix given)
      2. explicit field value (if it looks like an absolute path)
      3. explicit field value as bare name (PATH lookup)
      4. arm-none-eabi-<basename>  (standard ARM name)
      5. bare <basename>
    """
    prefix = normalize_prefix(raw.get('prefix', ''))

    def _candidates(field_key, basename):
        explicit = (raw.get(field_key) or '').strip()
        # Is explicit an absolute path?
        explicit_is_abs = explicit and (
            (len(explicit) > 1 and explicit[1] == ':') or  # Windows C:\...
            explicit.startswith('/') or
            os.sep in explicit or '/' in explicit
        )
        cands = []
        if prefix:
            cands.append(prefix + basename)            # 1. prefix + basename
        if explicit_is_abs:
            cands.append(explicit)                     # 2. absolute explicit
        if explicit and not explicit_is_abs:
            cands.append(explicit)                     # 3. bare explicit name
        cands.append('arm-none-eabi-' + basename)      # 4. standard ARM
        cands.append(basename)                         # 5. bare
        return cands

    return {
        'nm':   find_tool(_candidates('nm',   'nm')),
        're':   find_tool(_candidates('re',   'readelf')),
        'size': find_tool(_candidates('size', 'size')),
        'a2l':  find_tool(_candidates('a2l',  'addr2line')),
        'prefix_in':  raw.get('prefix',''),
        'prefix_out': prefix,
    }


# ---------------------------------------------------------------------------
# ELF ANALYSIS
# ---------------------------------------------------------------------------

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


def run_tool(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, errors='replace')
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return '', 'Tool not found: ' + args[0], 1
    except subprocess.TimeoutExpired:
        return '', 'Timeout running: ' + ' '.join(args), 1
    except Exception as e:
        return '', str(e), 1


def save_elf(upload):
    """Write uploaded ELF to a temp file and CLOSE it before returning.
    Critical on Windows — open file handles block subprocess access."""
    suffix = Path(upload.filename).suffix or '.elf'
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        upload.file.seek(0)
        with os.fdopen(fd, 'wb') as f:
            while True:
                chunk = upload.file.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    except Exception:
        try: os.unlink(path)
        except Exception: pass
        raise
    return path   # closed, safe for subprocess


def parse_nm_line(parts):
    """Parse one line of nm output in BSD or POSIX format."""
    def is_hex(s):
        return bool(re.match(r'^[0-9a-fA-F]{6,}$', s))
    def is_type(s):
        return len(s) == 1 and s in 'TtDdBbRrWwUuAaCcVvGgSsIi'

    # Strip tab-separated source file annotation if present
    source = ''
    clean = []
    for p in parts:
        if '\t' in p:
            source = p.strip('\t')
            break
        clean.append(p)
    parts = clean

    try:
        if len(parts) >= 3 and is_hex(parts[0]):
            # BSD format
            if len(parts) >= 4 and is_hex(parts[1]) and is_type(parts[2]):
                # ADDR SIZE TYPE NAME
                addr, size, ntype_raw, name = int(parts[0],16), int(parts[1],16), parts[2], ' '.join(parts[3:])
            elif is_type(parts[1]):
                # ADDR TYPE NAME
                addr, size, ntype_raw, name = int(parts[0],16), 0, parts[1], ' '.join(parts[2:])
            else:
                return None
        elif len(parts) >= 2 and is_type(parts[0]):
            # Undefined:  U name
            addr, size, ntype_raw, name = 0, 0, parts[0], ' '.join(parts[1:])
        elif len(parts) >= 3:
            # POSIX: NAME TYPE ADDR [SIZE]
            name     = parts[0]
            ntype_raw= parts[1]
            addr     = int(parts[2],16) if is_hex(parts[2]) else 0
            size     = int(parts[3],16) if len(parts)>3 and is_hex(parts[3]) else 0
        else:
            return None

        ntype = NM_TYPES.get(ntype_raw, 'other')
        return {"name":name,"addr":addr,"size":size,"type":ntype,
                "type_raw":ntype_raw,"global":ntype_raw.isupper(),
                "color":SYM_COLORS.get(ntype,SYM_COLORS['other']),
                "source":source,"section":None}
    except (ValueError, IndexError):
        return None


def parse_nm_output(stdout):
    seen, syms = set(), []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.endswith(':'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        sym = parse_nm_line(parts)
        if not sym:
            continue
        name = sym['name']
        if not name or name.startswith('$'):
            continue
        key = (name, sym['addr'])
        if key in seen:
            continue
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
            secs[m.group(1)] = {
                "addr": int(m.group(3),16),
                "size": int(m.group(5),16),
                "type": m.group(2), "flags": ""}
    return secs


def parse_size_output(stdout):
    sizes = {}
    for line in stdout.splitlines():
        m = re.match(r'^(\S+)\s+(0x[0-9a-fA-F]+|\d+)\s+(0x[0-9a-fA-F]+|\d+)', line)
        if m:
            try:
                sizes[m.group(1)] = {'size':int(m.group(2),0),'addr':int(m.group(3),0)}
            except Exception:
                pass
    return sizes


def assign_symbols(symbols, elf_secs, ld_sections):
    ranges = sorted(
        [(s['addr'], s['addr']+s['size'], n)
         for n,s in elf_secs.items() if s['size']>0])
    sec_map = {s['name']: s for s in ld_sections}
    orphans = []
    for sym in symbols:
        if sym['addr'] == 0 or sym['type'] == 'undefined':
            continue
        sym['section'] = next(
            (name for start,end,name in ranges if start <= sym['addr'] < end),
            None)
        if sym['section'] and sym['section'] in sec_map:
            sec_map[sym['section']].setdefault('symbols',[]).append(sym)
        elif sym['section'] is None:
            orphans.append(sym)
    return orphans


def make_warnings(ld_data, elf_secs, symbols):
    warns = []
    # Region fill
    for reg in ld_data.get('regions',[]):
        used = sum(elf_secs.get(s['name'],{}).get('size',0) for s in reg['sections'])
        if reg['length'] > 0:
            pct = used / reg['length']
            if pct > 0.95:
                warns.append({"level":"error","category":"Memory Overflow",
                    "message":f"{reg['name']} is {pct*100:.1f}% full ({used:,}/{reg['length']:,} bytes)",
                    "detail":"Region nearly full. Next build may fail to link."})
            elif pct > 0.80:
                warns.append({"level":"warn","category":"Memory Pressure",
                    "message":f"{reg['name']} is {pct*100:.1f}% full ({used:,}/{reg['length']:,} bytes)",
                    "detail":"Consider LTO, moving const data to flash, or growing region."})
    # DMA safety
    cacheable_ranges = []
    for sec in ld_data.get('sections',[]):
        if sec['cacheable']:
            es = elf_secs.get(sec['name'],{})
            if es.get('size',0) > 0:
                cacheable_ranges.append((es['addr'], es['addr']+es['size'], sec['name']))
    dma_kw = ['buf','buffer','frame','ipc','spi','dma','rx','tx','fifo','packet','msg','transfer']
    for sym in symbols:
        if sym['size'] < 4 or sym['type'] not in ('variable','common'):
            continue
        if not any(k in sym['name'].lower() for k in dma_kw):
            continue
        for start,end,sec_name in cacheable_ranges:
            if start <= sym['addr'] < end:
                warns.append({"level":"warn","category":"DMA Safety",
                    "message":f"'{sym['name']}' ({sym['size']} B) is in cacheable '{sec_name}'",
                    "detail":f"0x{sym['addr']:08X}. If this buffer is accessed by DMA, "
                             f"cache incoherency will cause silent data corruption. "
                             f"Move to .non_cacheable_bss or .mcal_bss_no_cacheable."})
                break
    # Large RAM symbols
    for sym in sorted([s for s in symbols if s['size']>1024
                       and s['type'] in ('variable','common')],key=lambda s:-s['size'])[:5]:
        warns.append({"level":"info","category":"Large RAM Symbol",
            "message":f"'{sym['name']}' uses {sym['size']:,} bytes",
            "detail":f"0x{sym['addr']:08X} in {sym.get('section','?')}. "
                     f"If constant, consider moving to flash (const qualifier)."})
    # Large functions
    for sym in sorted([s for s in symbols if s['size']>4096
                       and s['type']=='function'],key=lambda s:-s['size'])[:5]:
        warns.append({"level":"info","category":"Large Function",
            "message":f"'{sym['name']}' is {sym['size']:,} bytes",
            "detail":f"0x{sym['addr']:08X}. Large functions increase I-cache pressure."})
    return warns


def startup_cost(ld_sections, elf_secs):
    items, total_copy, total_zero = [], 0, 0
    for sec in ld_sections:
        sz = elf_secs.get(sec['name'],{}).get('size',0)
        if not sz:
            continue
        if sec['noload']:
            total_zero += sz
            items.append({"section":sec['name'],"type":"zeroed","size":sz,
                          "vma":sec['vma'],"lma":sec['lma']})
        elif sec['lma']:
            total_copy += sz
            items.append({"section":sec['name'],"type":"copied","size":sz,
                          "vma":sec['vma'],"lma":sec['lma']})
    return {"items":items,"total_copy":total_copy,"total_zero":total_zero}


# ---------------------------------------------------------------------------
# HTML — loaded from external string below
# ---------------------------------------------------------------------------


HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Linker MemMap</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Syne:wght@400;600;700;800&display=swap');
:root{
  --bg:#080b10;--surf:#0d1117;--s2:#161b22;--s3:#1c2330;
  --bdr:#21262d;--txt:#c9d1d9;--dim:#6e7681;
  --acc:#58a6ff;--grn:#3fb950;--ora:#d29922;--red:#f85149;
  --mono:'JetBrains Mono',monospace;--ui:'Syne',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--txt);font-family:var(--mono);font-size:13px;display:flex;flex-direction:column}
header{background:var(--surf);border-bottom:1px solid var(--bdr);padding:12px 20px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;flex-shrink:0;
  position:sticky;top:0;z-index:100}
header h1{font-family:var(--ui);font-size:16px;font-weight:800;color:#fff;letter-spacing:-.5px;white-space:nowrap}
header h1 em{color:var(--acc);font-style:normal}
.chip{background:var(--s2);border:1px solid var(--bdr);border-radius:4px;padding:2px 8px;font-size:11px;color:var(--dim)}
.chip.grn{background:#0d2318;border-color:#1a5c2a;color:var(--grn)}
.chip.blu{background:#0d1e33;border-color:#1a3a6a;color:var(--acc)}
.chip.ora{background:#1e1008;border-color:#5a3010;color:var(--ora)}
.spacer{flex:1}
.hbtn{background:var(--s2);border:1px solid var(--bdr);color:var(--txt);padding:4px 10px;
  border-radius:5px;cursor:pointer;font:11px var(--mono);transition:.15s}
.hbtn:hover{border-color:var(--acc);color:var(--acc)}
.layout{display:flex;flex:1;overflow:hidden;min-height:0}
.sidebar{width:240px;min-width:200px;background:var(--surf);border-right:1px solid var(--bdr);
  display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto}
.main{flex:1;overflow:auto;padding:20px}
.sb-section{border-bottom:1px solid var(--bdr);padding:14px}
.sb-title{font-family:var(--ui);font-size:10px;font-weight:700;color:var(--dim);
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}
.drop-area{border:2px dashed var(--bdr);border-radius:8px;padding:14px 10px;text-align:center;
  cursor:pointer;transition:.2s;position:relative;background:var(--bg)}
.drop-area:hover,.drop-area.over{border-color:var(--acc);background:#0c1929}
.drop-area input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.drop-area .dico{font-size:22px;margin-bottom:5px}
.drop-area p{font-size:11px;color:var(--dim);line-height:1.4}
.drop-area.has-file p{color:var(--grn)}
.drop-area.has-file{border-color:var(--grn)}
.file-name{font-size:10px;color:var(--acc);margin-top:6px;word-break:break-all}
.tool-row{display:flex;flex-direction:column;gap:3px;margin-bottom:7px}
.tool-row label{font-size:10px;color:var(--dim)}
.tool-row input{background:var(--bg);border:1px solid var(--bdr);border-radius:4px;
  padding:5px 8px;color:var(--txt);font:11px var(--mono);width:100%;transition:.15s}
.tool-row input:focus{outline:none;border-color:var(--acc)}
.run-btn{width:100%;padding:8px;background:var(--acc);color:#000;border:none;border-radius:6px;
  font:600 12px var(--ui);cursor:pointer;transition:.15s;margin-top:6px}
.run-btn:hover{background:#79baff}
.run-btn:disabled{background:var(--s3);color:var(--dim);cursor:default}
#tool-status{font-size:10px;color:var(--dim);margin-top:6px;line-height:1.5;min-height:16px}
.tabs{display:flex;border-bottom:1px solid var(--bdr);margin-bottom:16px;overflow-x:auto}
.tab{padding:8px 14px;cursor:pointer;font-size:12px;color:var(--dim);
  border-bottom:2px solid transparent;transition:.15s;white-space:nowrap;flex-shrink:0}
.tab:hover{color:var(--txt)}
.tab.act{color:var(--acc);border-bottom-color:var(--acc)}
.pane{display:none}
.pane.act{display:block}
#mc{background:var(--surf);border:1px solid var(--bdr);border-radius:10px;
  padding:18px;overflow-x:auto;margin-bottom:14px}
#leg{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.li{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--dim)}
.ld{width:10px;height:10px;border-radius:2px;flex-shrink:0}
.card-wrap{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;overflow:hidden;margin-bottom:14px}
.tbl-hdr{background:var(--s2);padding:9px 14px;font-family:var(--ui);font-size:12px;font-weight:600;color:#fff}
table{width:100%;border-collapse:collapse}
th{background:var(--s2);color:var(--dim);font-size:10px;font-weight:500;text-transform:uppercase;
  letter-spacing:.07em;padding:8px 12px;text-align:left;border-bottom:1px solid var(--bdr);
  cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--txt)}
th.sa::after{content:' ↑'}th.sd::after{content:' ↓'}
td{padding:7px 12px;border-bottom:1px solid #0a0e14;font-size:12px;vertical-align:middle;
  max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:#0a0f18;cursor:pointer}
.hx{color:var(--acc);font-size:11px}
.sz{color:var(--grn)}
.dim{color:var(--dim)}
.tb{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;border:1px solid}
.filter-bar{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
.search{background:var(--surf);border:1px solid var(--bdr);border-radius:5px;
  padding:6px 10px;color:var(--txt);font:12px var(--mono);flex:1;min-width:160px}
.search:focus{outline:none;border-color:var(--acc)}
select.fsel{background:var(--surf);border:1px solid var(--bdr);border-radius:5px;
  padding:6px 8px;color:var(--txt);font:12px var(--mono);cursor:pointer}
.cnt{font-size:11px;color:var(--dim)}
.warn-list{display:flex;flex-direction:column;gap:8px}
.wcard{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;padding:13px 15px;display:flex;gap:10px}
.wcard.error{border-color:#5a1a1a;background:#140808}
.wcard.warn{border-color:#5a3d1a;background:#100c05}
.wcard.info{border-color:#1a2a3a;background:#08101a}
.wico{font-size:18px;flex-shrink:0;margin-top:1px}
.wtitle{font-weight:500;color:#fff;font-size:13px;margin-bottom:3px}
.wcat{font-size:10px;color:var(--dim);margin-bottom:5px;text-transform:uppercase;letter-spacing:.07em}
.wdet{font-size:11px;color:#8b949e;line-height:1.55}
.sg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.stat{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;padding:14px}
.snum{font-family:var(--ui);font-size:26px;font-weight:800;color:var(--acc);margin-bottom:3px}
.slbl{font-size:11px;color:var(--dim)}
.sr{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--bdr);font-size:12px}
.sr:last-child{border:none}
.stype{padding:2px 7px;border-radius:3px;font-size:10px;font-weight:500;width:58px;text-align:center;flex-shrink:0}
.copied{background:#0d1e33;color:var(--acc);border:1px solid #1a3a6a}
.zeroed{background:#0d2318;color:var(--grn);border:1px solid #1a5c2a}
.a2l-inp{display:flex;gap:8px;margin-bottom:10px}
.a2l-inp input{background:var(--surf);border:1px solid var(--bdr);border-radius:5px;
  padding:6px 10px;color:var(--txt);font:12px var(--mono);flex:1}
.a2l-inp input:focus{outline:none;border-color:var(--acc)}
.a2l-res{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;padding:14px;
  font-size:12px;min-height:54px;white-space:pre-wrap;line-height:1.6}
.fill-bg{background:var(--s3);border-radius:3px;height:6px;width:80px;display:inline-block;vertical-align:middle}
.fill-bar{height:6px;border-radius:3px}
.sec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.sec-card{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;
  padding:12px 14px;display:flex;gap:10px}
.sc-dot{width:10px;height:10px;border-radius:2px;margin-top:3px;flex-shrink:0}
.sc-name{font-size:12px;font-weight:500;color:#fff;margin-bottom:3px}
.sc-type{font-size:10px;color:var(--dim);margin-bottom:4px}
.sc-desc{font-size:11px;color:#8b949e;line-height:1.5}
.badge{font-size:9px;padding:1px 5px;border-radius:3px;background:var(--s2);
  color:var(--dim);border:1px solid var(--bdr);margin-left:3px;vertical-align:middle}
.nb{background:#200d0d;border-color:#5a1a1a;color:var(--red)}
.vb{background:#0d1a2a;border-color:#1a3a6a;color:var(--acc)}
.db{background:#0d1e0d;border-color:#1a4a1a;color:var(--grn)}
.cb{background:#1e1208;border-color:#4a3008;color:var(--ora)}
.empty{text-align:center;padding:48px;color:var(--dim)}
.empty .eico{font-size:36px;margin-bottom:12px}
.empty h3{font-family:var(--ui);font-size:15px;color:#fff;margin-bottom:8px}
.empty p{font-size:12px;line-height:1.6}
#tip{position:fixed;background:#161b22;border:1px solid var(--bdr);border-radius:9px;
  padding:12px 15px;font-size:12px;pointer-events:none;opacity:0;transition:opacity .12s;
  z-index:9999;max-width:300px;box-shadow:0 12px 40px #00000090}
#tip.on{opacity:1}
.tn{font-weight:600;color:#fff;margin-bottom:7px;font-size:13px;font-family:var(--ui)}
.tr2{display:flex;justify-content:space-between;gap:14px;color:var(--dim);margin-bottom:2px}
.tv{color:var(--acc)}
.tdesc{margin-top:8px;color:#8b949e;line-height:1.5;border-top:1px solid var(--bdr);
  padding-top:8px;font-size:11px}
footer{text-align:center;padding:14px;color:var(--dim);font-size:11px;flex-shrink:0;
  border-top:1px solid var(--bdr)}
progress{width:100%;height:4px;margin-top:6px;border-radius:2px;
  background:var(--s3);border:none;display:none}
progress::-webkit-progress-bar{background:var(--s3);border-radius:2px}
progress::-webkit-progress-value{background:var(--acc);border-radius:2px}
</style>
</head>
<body>
<header>
  <h1>Linker <em>MemMap</em></h1>
  <span class="chip">ELF Analyser</span>
  <span class="chip blu" id="fchip" style="display:none">📋 <span id="fname"></span></span>
  <span class="chip ora" id="echip" style="display:none">⚙️ <span id="ename"></span></span>
  <span class="chip grn" id="entry-chip" style="display:none">⚡ <span id="esym"></span></span>
  <span class="chip grn" id="sym-chip" style="display:none"><span id="symcount"></span> symbols</span>
  <div class="spacer"></div>
  <button class="hbtn" onclick="toggleSidebar()">☰ Sidebar</button>
</header>
<div class="layout">
  <!-- Sidebar -->
  <div class="sidebar" id="sidebar">
    <div class="sb-section">
      <div class="sb-title">Linker Script (.ld)</div>
      <div class="drop-area" id="ld-drop">
        <input type="file" accept=".ld,.lds,.x" id="ld-fi">
        <div class="dico">📋</div>
        <p>Drop .ld file here<br>or click to browse</p>
      </div>
      <div class="file-name" id="ld-name" style="display:none"></div>
    </div>
    <div class="sb-section">
      <div class="sb-title">ELF Binary (optional)</div>
      <div class="drop-area" id="elf-drop">
        <input type="file" id="elf-fi">
        <div class="dico">🔧</div>
        <p>Drop .elf / .axf here<br>for symbol analysis</p>
      </div>
      <div class="file-name" id="elf-name" style="display:none"></div>
      <progress id="elf-progress" max="100"></progress>
    </div>
    <div class="sb-section">
      <div class="sb-title">Toolchain</div>
      <div class="tool-row">
        <label>Prefix (fill this OR individual paths below)</label>
        <input id="t-prefix" placeholder="e.g.  D:\NXP\S32DS\bin\arm-none-eabi-">
        <div style="font-size:10px;color:var(--dim);margin-top:3px;line-height:1.4">
          Paste the full path ending with <strong style="color:var(--acc)">arm-none-eabi-</strong><br>
          or just the bin directory — auto-detected either way
        </div>
      </div>
      <div class="tool-row"><label>nm</label>
        <input id="t-nm" value="arm-none-eabi-nm"></div>
      <div class="tool-row"><label>readelf</label>
        <input id="t-re" value="arm-none-eabi-readelf"></div>
      <div class="tool-row"><label>size</label>
        <input id="t-sz" value="arm-none-eabi-size"></div>
      <div class="tool-row"><label>addr2line</label>
        <input id="t-a2l" value="arm-none-eabi-addr2line"></div>
      <button class="run-btn" id="analyse-btn" onclick="runAnalysis()" disabled>
        ▶ Analyse ELF
      </button>
      <div id="tool-status"></div>
    </div>
  </div>

  <!-- Main -->
  <div class="main" id="main-content">
    <div class="empty" id="welcome">
      <div class="eico">🗂️</div>
      <h3>Drop a linker script to start</h3>
      <p>Load a <strong>.ld</strong> file from the sidebar to visualise your memory map.<br><br>
         Optionally drop an <strong>.elf</strong> file for full symbol analysis —<br>
         sizes, DMA safety warnings, addr→line lookup, and more.</p>
    </div>
    <div id="app-content" style="display:none">
      <div class="tabs" id="tabs">
        <div class="tab act" data-pane="map"    onclick="tab(this)">🗺 Memory Map</div>
        <div class="tab"     data-pane="sec"    onclick="tab(this)">📦 Sections</div>
        <div class="tab"     data-pane="sym"    onclick="tab(this)">🔍 Symbols</div>
        <div class="tab"     data-pane="warn"   onclick="tab(this)">⚠ Warnings <span id="warn-n"></span></div>
        <div class="tab"     data-pane="start"  onclick="tab(this)">🚀 Startup Cost</div>
        <div class="tab"     data-pane="a2l"    onclick="tab(this)">📍 Addr→Line</div>
        <div class="tab"     data-pane="dbg"    onclick="tab(this)">🐛 Debug</div>
      </div>

      <!-- MAP -->
      <div class="pane act" id="pane-map">
        <div id="mc"><svg id="map-svg"></svg></div>
        <div id="leg"></div>
        <div class="card-wrap">
          <div class="tbl-hdr">Region Summary</div>
          <table><thead><tr>
            <th>Region</th><th>Start</th><th>End</th><th>Size</th>
            <th>Type</th><th>Used</th><th>Free</th><th>Fill</th>
          </tr></thead><tbody id="rtb"></tbody></table>
        </div>
      </div>

      <!-- SECTIONS — always populated from LD -->
      <div class="pane" id="pane-sec">
        <div class="sec-grid" id="sec-grid"></div>
      </div>

      <!-- SYMBOLS -->
      <div class="pane" id="pane-sym">
        <div class="empty" id="sym-empty">
          <div class="eico">⚙️</div>
          <h3>Load an ELF to explore symbols</h3>
          <p>Drop a .elf / .axf file and click <strong>Analyse ELF</strong>.</p>
        </div>
        <div id="sym-content" style="display:none">
          <div class="filter-bar">
            <input class="search" id="sym-q" placeholder="Search symbols…" oninput="filterSyms()">
            <select class="fsel" id="sym-t" onchange="filterSyms()">
              <option value="">All types</option>
              <option value="function">Functions</option>
              <option value="variable">Variables</option>
              <option value="constant">Constants</option>
              <option value="weak">Weak</option>
              <option value="undefined">Undefined</option>
            </select>
            <select class="fsel" id="sym-s" onchange="filterSyms()">
              <option value="">All sections</option>
            </select>
            <select class="fsel" id="sym-g" onchange="filterSyms()">
              <option value="">Global+Local</option>
              <option value="1">Global only</option>
              <option value="0">Local only</option>
            </select>
            <span class="cnt" id="sym-cnt"></span>
          </div>
          <div class="card-wrap">
            <table id="sym-tbl">
              <thead><tr>
                <th onclick="sortSym('name')">Symbol</th>
                <th onclick="sortSym('addr')">Address</th>
                <th onclick="sortSym('size')">Size</th>
                <th onclick="sortSym('type')">Type</th>
                <th onclick="sortSym('section')">Section</th>
                <th>Source</th>
              </tr></thead>
              <tbody id="sym-body"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- WARNINGS -->
      <div class="pane" id="pane-warn">
        <div class="warn-list" id="warn-list"></div>
      </div>

      <!-- STARTUP -->
      <div class="pane" id="pane-start">
        <div class="sg" id="start-stats"></div>
        <div class="card-wrap">
          <div class="tbl-hdr">Copy table — what startup code does before main()</div>
          <div style="padding:12px" id="start-rows"></div>
        </div>
      </div>

      <!-- DEBUG -->
      <div class="pane" id="pane-dbg">
        <p style="color:var(--dim);font-size:12px;margin-bottom:10px">
          Runs nm, readelf, and size on your ELF and shows raw output.
          Use this to diagnose why symbols are not loading.
        </p>
        <button class="hbtn" onclick="runDebug()" style="margin-bottom:12px">
          🔬 Run diagnostics
        </button>
        <div id="dbg-out" style="background:var(--surf);border:1px solid var(--bdr);
          border-radius:8px;padding:16px;font-size:11px;line-height:1.7;
          white-space:pre-wrap;min-height:100px;font-family:var(--mono)">
          Click "Run diagnostics" with an ELF file loaded to see raw tool output.
        </div>
      </div>

      <!-- ADDR2LINE -->
      <div class="pane" id="pane-a2l">
        <p style="color:var(--dim);font-size:12px;margin-bottom:10px">
          Resolve any hex address to its source file and line number.<br>
          Click a symbol row to auto-fill its address.
        </p>
        <div class="a2l-inp">
          <input id="a2l-addr" placeholder="0x00401234" onkeydown="if(event.key==='Enter')doA2L()">
          <button class="hbtn" onclick="doA2L()">Look up</button>
        </div>
        <div class="a2l-res" id="a2l-res">Result will appear here…</div>
      </div>
    </div>
  </div>
</div>
<div id="tip"></div>
<footer>Linker MemMap Viewer · Drop .ld or .elf anywhere to reload</footer>

<script>
const $=id=>document.getElementById(id);
const NS='http://www.w3.org/2000/svg';

// ── State ─────────────────────────────────────────────────────────────────────
const S={
  ld: null,          // parsed linker data
  elfFile: null,     // File object from drop
  syms: [],          // all symbols
  fSyms: [],         // filtered symbols
  elfSecs: {},       // elf section headers
  symSort:'size', symDir:-1,
  lastA2lTool: 'arm-none-eabi-addr2line',
};

// ── File drops ────────────────────────────────────────────────────────────────
function setupDrop(dropId, inputId, cb){
  const d=$(dropId), i=$(inputId);
  d.addEventListener('dragover',  e=>{e.preventDefault();d.classList.add('over')});
  d.addEventListener('dragleave', ()=>d.classList.remove('over'));
  d.addEventListener('drop',      e=>{e.preventDefault();d.classList.remove('over');cb(e.dataTransfer.files[0])});
  i.addEventListener('change',    e=>cb(e.target.files[0]));
}
setupDrop('ld-drop','ld-fi', f=>{
  if(!f)return;
  const r=new FileReader();
  r.onload=e=>uploadLD(f.name, e.target.result);
  r.readAsText(f);
});
setupDrop('elf-drop','elf-fi', f=>{
  if(!f)return;
  S.elfFile=f;
  $('elf-name').textContent=f.name; $('elf-name').style.display='';
  $('elf-drop').classList.add('has-file');
  $('elf-drop').querySelector('p').textContent=f.name;
  $('echip').style.display=''; $('ename').textContent=f.name;
  $('analyse-btn').disabled=false;
  $('tool-status').textContent='ELF ready — click Analyse ELF';
});
// Global drop — .ld files only (ELF is binary, needs sidebar drop)
window.addEventListener('dragover', e=>e.preventDefault());
window.addEventListener('drop', e=>{
  e.preventDefault();
  const f=e.dataTransfer.files[0];
  if(!f)return;
  const n=f.name.toLowerCase();
  if(n.endsWith('.ld')||n.endsWith('.lds')||n.endsWith('.x')){
    const r=new FileReader();
    r.onload=ev=>uploadLD(f.name,ev.target.result);
    r.readAsText(f);
  }
});

// ── Upload & parse LD ─────────────────────────────────────────────────────────
async function uploadLD(name, text){
  const fd=new FormData();
  fd.append('content',text); fd.append('filename',name);
  const res=await fetch('/parse_ld',{method:'POST',body:fd});
  const d=await res.json();
  if(d.error){alert('Parse error:\n'+d.error);return}
  S.ld=d;
  $('fchip').style.display=''; $('fname').textContent=name;
  $('ld-name').textContent=name; $('ld-name').style.display='';
  $('ld-drop').classList.add('has-file');
  $('ld-drop').querySelector('p').textContent=name;
  if(d.entry){$('entry-chip').style.display='';$('esym').textContent=d.entry}
  $('welcome').style.display='none';
  $('app-content').style.display='';
  // Always render sections from LD immediately
  renderMap(d, {});
  renderSections(d);
  renderWarnings([]);
  renderStartup(d, {}, null);
}

// ── Upload ELF binary & analyse ───────────────────────────────────────────────
async function runAnalysis(){
  if(!S.elfFile){alert('Drop an ELF file in the sidebar first');return}
  if(!S.ld){alert('Load a linker script first');return}

  const btn=$('analyse-btn');
  btn.disabled=true; btn.textContent='⏳ Uploading…';
  $('tool-status').textContent='Uploading ELF…';

  const prog=$('elf-progress');
  prog.style.display=''; prog.value=0;

  // Build tool paths from prefix or individual fields
  // Send raw values — server-side _resolve_tools handles all path formats
  const tools={
    nm:     $('t-nm').value.trim(),
    re:     $('t-re').value.trim(),
    size:   $('t-sz').value.trim(),
    a2l:    $('t-a2l').value.trim(),
    prefix: $('t-prefix').value.trim(),
  };
  S.lastA2lTool=tools.a2l;

  // Upload the binary via XHR so we can track progress
  const fd=new FormData();
  fd.append('elf', S.elfFile);
  fd.append('tools', JSON.stringify(tools));
  fd.append('ld_data', JSON.stringify(S.ld));

  try{
    const res = await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST','/analyse_elf');
      xhr.upload.onprogress=e=>{
        if(e.lengthComputable){
          prog.value=Math.round(e.loaded/e.total*80);
          $('tool-status').textContent=`Uploading ${Math.round(e.loaded/1024)}KB / ${Math.round(e.total/1024)}KB`;
        }
      };
      xhr.onload=()=>{
        prog.value=100;
        try{resolve(JSON.parse(xhr.responseText))}
        catch(e){reject(new Error('Bad JSON response'))}
      };
      xhr.onerror=()=>reject(new Error('Network error'));
      xhr.send(fd);
    });

    prog.style.display='none';
    btn.textContent='▶ Analyse ELF';
    btn.disabled=false;

    if(res.error){
      $('tool-status').textContent='❌ '+res.error;
      if(res.trace) console.error(res.trace);
      return;
    }

    const symMsg = res.symbols.length > 0
      ? `✅ ${res.symbols.length} symbols loaded`
      : `⚠ 0 symbols — check Debug tab for details`;
    $('tool-status').textContent = symMsg;
    showDebugSummary(res);
    S.syms=res.symbols; S.elfSecs=res.elf_sections;

    $('sym-chip').style.display=''; $('symcount').textContent=res.symbols.length;

    // Populate section filter dropdown
    const ss=$('sym-s'); ss.innerHTML='<option value="">All sections</option>';
    [...new Set(res.symbols.map(s=>s.section).filter(Boolean))].sort()
      .forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;ss.appendChild(o)});

    renderMap(S.ld, res.elf_sections);
    renderSections(S.ld);   // keep sections tab up to date with real sizes
    renderSymbols(res.symbols);
    renderWarnings(res.warnings);
    renderStartup(S.ld, res.elf_sections, res.startup);

  }catch(e){
    prog.style.display='none';
    btn.textContent='▶ Analyse ELF';
    btn.disabled=false;
    $('tool-status').textContent='❌ '+e.message;
  }
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function tab(el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('act'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('act'));
  el.classList.add('act');
  $('pane-'+el.dataset.pane).classList.add('act');
}
function switchToTab(name){
  const el=document.querySelector(`.tab[data-pane="${name}"]`);
  if(el){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('act'));
    document.querySelectorAll('.pane').forEach(p=>p.classList.remove('act'));
    el.classList.add('act');$('pane-'+name).classList.add('act');}
}
function toggleSidebar(){
  const s=$('sidebar');
  s.style.display=s.style.display==='none'?'flex':'none';
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const hx=n=>'0x'+n.toString(16).toUpperCase().padStart(8,'0');
function fz(n){
  if(n>=1048576)return(n/1048576).toFixed(2)+' MB';
  if(n>=1024)return(n/1024).toFixed(1)+' KB';
  return n+' B';
}
function mkEl(p,tag,attrs){
  const e=document.createElementNS(NS,tag);
  Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));
  p.appendChild(e);return e;
}
function svgT(p,text,attrs){
  const e=mkEl(p,'text',{...attrs,'font-family':'JetBrains Mono,monospace','pointer-events':'none'});
  e.textContent=text;return e;
}
function svgTI(p,text,attrs){  // interactive text
  const e=mkEl(p,'text',{...attrs,'font-family':'JetBrains Mono,monospace'});
  e.textContent=text;return e;
}

// ── Memory map SVG ────────────────────────────────────────────────────────────
function renderMap(data, elfSecs){
  const svg=$('map-svg'); svg.innerHTML='';
  const regs=data.regions.filter(r=>r.length>0);
  if(!regs.length){
    svgT(svg,'No MEMORY regions found',{x:20,y:30,fill:'#555','font-size':13});
    return;
  }
  const AW=95,BW=196,LW=230,PAD_T=44,PAD_B=30,MIN_H=28,GAP=4;
  const totalLog=regs.reduce((s,r)=>s+Math.log2(Math.max(r.length,256)),0);
  const CH=Math.max(480,regs.length*100);
  const rh=r=>Math.max(MIN_H,(Math.log2(Math.max(r.length,256))/totalLog)*CH);
  const totalH=regs.reduce((s,r)=>s+rh(r)+GAP,0)+PAD_T+PAD_B;
  svg.setAttribute('width',AW+BW+LW);
  svg.setAttribute('height',totalH);
  svg.setAttribute('viewBox',`0 0 ${AW+BW+LW} ${totalH}`);

  svgT(svg,'ADDRESS',{x:AW/2,y:28,fill:'#6e7681','font-size':9,'text-anchor':'middle','letter-spacing':'0.1em'});
  svgT(svg,'REGION / SECTIONS',{x:AW+BW/2,y:28,fill:'#6e7681','font-size':9,'text-anchor':'middle','letter-spacing':'0.1em'});

  let y=PAD_T;
  const RTBL=[];
  for(const reg of regs){
    const h=rh(reg);
    const usedBytes=reg.sections.reduce((s,sec)=>s+(elfSecs[sec.name]?.size||0),0);
    const usedPct=reg.length>0?Math.min(1,usedBytes/reg.length):0;
    RTBL.push({...reg,usedBytes,usedPct,freeBytes:Math.max(0,reg.length-usedBytes)});

    const rb=mkEl(svg,'rect',{x:AW,y,width:BW,height:h,fill:reg.color,rx:4,
      stroke:'#2a3548','stroke-width':1,cursor:'pointer'});
    hover(rb,{name:reg.name,rows:[
      ['Start',hx(reg.origin)],['End',hx(reg.end)],['Size',fz(reg.length)],
      ['Type',reg.type],['Attrs',reg.attrs||'—'],
      ['Used',usedBytes?fz(usedBytes)+'  ('+Math.round(usedPct*100)+'%)':'load ELF'],
      ['Free',usedBytes?fz(Math.max(0,reg.length-usedBytes)):'—'],
    ],desc:`Memory region. Contains ${reg.sections.length} section(s).`});

    svgT(svg,hx(reg.origin),{x:AW-5,y:y+12,fill:'#58a6ff','font-size':9,'text-anchor':'end'});
    svgT(svg,hx(reg.end),{x:AW-5,y:y+h,fill:'#3a4450','font-size':9,'text-anchor':'end'});
    mkEl(svg,'line',{x1:AW-4,y1:y,x2:AW,y2:y,stroke:'#444','stroke-width':1});
    mkEl(svg,'line',{x1:AW-4,y1:y+h,x2:AW,y2:y+h,stroke:'#333','stroke-width':1});

    svgT(svg,reg.name,{x:AW+BW+10,y:y+13,fill:'#fff','font-size':12,'font-weight':600,'font-family':'Syne,sans-serif','pointer-events':'none'});
    svgT(svg,fz(reg.length),{x:AW+BW+10,y:y+26,fill:'#6e7681','font-size':10});
    if(usedBytes>0){
      const col=usedPct>0.95?'#f85149':usedPct>0.8?'#d29922':'#3fb950';
      svgT(svg,Math.round(usedPct*100)+'% used',{x:AW+BW+10,y:y+39,fill:col,'font-size':10});
    }

    const secs=reg.sections;
    if(secs.length){
      const sh=Math.max(10,(h-4)/secs.length);
      secs.forEach((sec,i)=>{
        const sy=y+2+i*sh, sH=Math.min(sh,(h-4)-i*sh)-1;
        if(sH<3)return;
        const secSz=elfSecs[sec.name]?.size||0;
        const sr=mkEl(svg,'rect',{x:AW+2,y:sy,width:BW-4,height:sH,
          fill:sec.color,rx:2,opacity:0.85,cursor:'pointer'});
        hover(sr,{name:sec.name,rows:[
          ['Type',sec.type],['→ VMA',sec.vma||'—'],
          ['← LMA',sec.lma||'—'],['NOLOAD',sec.noload?'Yes (not in image)':'No'],
          ['Size',secSz?fz(secSz):'load ELF'],
        ],desc:sec.desc});
        if(sH>14) svgT(svg,sec.name,{x:AW+7,y:sy+sH/2+4,fill:'#fff',
          'font-size':Math.min(10,sH-2)});
      });
    }
    y+=h+GAP;
  }

  // Legend
  const leg=$('leg'); leg.innerHTML='';
  const seen=new Set();
  data.sections.forEach(s=>{
    if(seen.has(s.type))return; seen.add(s.type);
    const d=document.createElement('div'); d.className='li';
    d.innerHTML=`<div class="ld" style="background:${s.color}"></div>${s.type}`;
    leg.appendChild(d);
  });

  // Region table
  const rtb=$('rtb'); rtb.innerHTML='';
  RTBL.forEach(r=>{
    const p=r.usedPct;
    const col=p>0.95?'#f85149':p>0.8?'#d29922':'#3fb950';
    const bar=r.usedBytes?`<div class="fill-bg"><div class="fill-bar" style="width:${Math.round(p*78)}px;background:${col}"></div></div>`:'—';
    const tr=document.createElement('tr'); tr.innerHTML=`
      <td><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${r.color};margin-right:6px;vertical-align:middle"></span>${r.name}</td>
      <td class="hx">${hx(r.origin)}</td><td class="hx">${hx(r.end)}</td>
      <td class="sz">${fz(r.length)}</td><td class="dim">${r.type}</td>
      <td>${r.usedBytes?fz(r.usedBytes):'—'}</td>
      <td>${r.usedBytes?fz(r.freeBytes):'—'}</td>
      <td>${bar}</td>`;
    rtb.appendChild(tr);
  });
}

// ── Sections tab — always rendered from LD, survives ELF reload ───────────────
function renderSections(data){
  const g=$('sec-grid'); g.innerHTML='';
  data.sections.forEach(s=>{
    const d=document.createElement('div'); d.className='sec-card';
    d.innerHTML=`
      <div class="sc-dot" style="background:${s.color}"></div>
      <div>
        <div class="sc-name">${s.name}
          ${s.noload?'<span class="badge nb">NOLOAD</span>':''}
          ${s.vma?`<span class="badge vb">→ ${s.vma}</span>`:''}
          ${s.lma?`<span class="badge">LMA: ${s.lma}</span>`:''}
          ${s.dma_safe?'<span class="badge db">DMA-safe</span>':''}
          ${s.cacheable?'<span class="badge cb">cached</span>':''}
        </div>
        <div class="sc-type">${s.type}</div>
        <div class="sc-desc">${s.desc}</div>
      </div>`;
    g.appendChild(d);
  });
}

// ── Symbols ───────────────────────────────────────────────────────────────────
const TCOL={'function':'#3b82f6','variable':'#f97316','constant':'#10b981',
  'weak':'#6366f1','undefined':'#6e7681','absolute':'#f59e0b','other':'#374151'};

function renderSymbols(syms){
  $('sym-empty').style.display='none';
  $('sym-content').style.display='';
  S.syms=syms;
  filterSyms();
}

function filterSyms(){
  const q=($('sym-q').value||'').toLowerCase();
  const t=$('sym-t').value, sec=$('sym-s').value, g=$('sym-g').value;
  S.fSyms=S.syms.filter(s=>{
    if(q&&!s.name.toLowerCase().includes(q))return false;
    if(t&&s.type!==t)return false;
    if(sec&&s.section!==sec)return false;
    if(g==='1'&&!s.global)return false;
    if(g==='0'&&s.global)return false;
    return true;
  });
  sortAndRenderSyms();
}

function sortSym(col){
  if(S.symSort===col)S.symDir*=-1; else{S.symSort=col;S.symDir=-1}
  document.querySelectorAll('#sym-tbl th').forEach((th,i)=>{
    th.classList.remove('sa','sd');
    const cols=['name','addr','size','type','section'];
    if(cols[i]===col)th.classList.add(S.symDir>0?'sa':'sd');
  });
  sortAndRenderSyms();
}

function sortAndRenderSyms(){
  const {symSort:col,symDir:dir}=S;
  const sorted=[...S.fSyms].sort((a,b)=>{
    const va=a[col]??'', vb=b[col]??'';
    return(typeof va==='number'?(va-vb):va.toString().localeCompare(vb.toString()))*dir;
  });
  const tbody=$('sym-body'); tbody.innerHTML='';
  $('sym-cnt').textContent=`${sorted.length} / ${S.syms.length}`;
  const MAX=2000;
  sorted.slice(0,MAX).forEach(s=>{
    const c=TCOL[s.type]||TCOL.other;
    const tr=document.createElement('tr');
    tr.innerHTML=`
      <td style="color:${s.global?'#fff':'#8b949e'};font-size:11px" title="${s.name}">${s.name}</td>
      <td class="hx">${hx(s.addr)}</td>
      <td class="sz">${s.size?fz(s.size):'—'}</td>
      <td><span class="tb" style="color:${c};border-color:${c}33;background:${c}11">${s.type}</span></td>
      <td class="dim">${s.section||'—'}</td>
      <td class="dim" style="font-size:10px" title="${s.source||''}">${
        s.source?s.source.replace(/^.*[/\\]/,''):'—'}</td>`;
    tr.addEventListener('click',()=>{
      $('a2l-addr').value=hx(s.addr);
      switchToTab('a2l');
      doA2L();
    });
    tbody.appendChild(tr);
  });
  if(sorted.length>MAX){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td colspan="6" style="text-align:center;color:var(--dim);padding:10px">
      ${sorted.length-MAX} more — refine your filter</td>`;
    tbody.appendChild(tr);
  }
}

// ── Warnings ──────────────────────────────────────────────────────────────────
function renderWarnings(warns){
  const ICONS={error:'🔴',warn:'🟡',info:'🔵'};
  $('warn-n').textContent=warns.length?`(${warns.length})`:'';
  const wl=$('warn-list'); wl.innerHTML='';
  if(!warns.length){
    wl.innerHTML='<div class="empty"><div class="eico">✅</div><h3>No warnings</h3>'
      +'<p>Load an ELF file and click Analyse ELF to run checks.</p></div>';
    return;
  }
  warns.forEach(w=>{
    const d=document.createElement('div'); d.className=`wcard ${w.level}`;
    d.innerHTML=`<div class="wico">${ICONS[w.level]||'ℹ'}</div>
      <div><div class="wcat">${w.category}</div>
      <div class="wtitle">${w.message}</div>
      <div class="wdet">${w.detail}</div></div>`;
    wl.appendChild(d);
  });
}

// ── Startup cost ──────────────────────────────────────────────────────────────
function renderStartup(ldData, elfSecs, startup){
  const ss=$('start-stats'), sr=$('start-rows');
  ss.innerHTML=''; sr.innerHTML='';
  if(!startup){
    ss.innerHTML=`
      <div class="stat"><div class="snum" style="color:#6e7681">?</div>
        <div class="slbl">Bytes copied flash→RAM<br>Load ELF for exact figures</div></div>
      <div class="stat"><div class="snum" style="color:#6e7681">?</div>
        <div class="slbl">Bytes zeroed (BSS)<br>Load ELF for exact figures</div></div>`;
    return;
  }
  const {total_copy,total_zero,items}=startup;
  ss.innerHTML=`
    <div class="stat"><div class="snum">${fz(total_copy)}</div>
      <div class="slbl">Copied flash→RAM at startup<br>Larger = slower boot</div></div>
    <div class="stat"><div class="snum" style="color:var(--grn)">${fz(total_zero)}</div>
      <div class="slbl">Zeroed (BSS) at startup<br>Fast — just memset</div></div>`;
  items.forEach(it=>{
    const d=document.createElement('div'); d.className='sr';
    d.innerHTML=`<span class="stype ${it.type}">${it.type}</span>
      <span style="color:#fff;flex:1;font-size:12px">${it.section}</span>
      <span class="sz">${fz(it.size)}</span>
      ${it.vma?`<span class="dim" style="font-size:11px">${it.vma}</span>`:''}
      ${it.lma?`<span class="dim" style="font-size:11px">← ${it.lma}</span>`:''}`;
    sr.appendChild(d);
  });
}

// ── Debug ────────────────────────────────────────────────────────────────────
async function runDebug(){
  if(!S.elfFile){
    $('dbg-out').textContent='Drop an ELF file in the sidebar first.';
    return;
  }
  $('dbg-out').textContent='Running tools…';
  const prefix=$('t-prefix').value.trim();
  const tools={
    nm:     $('t-nm').value.trim(),
    re:     $('t-re').value.trim(),
    size:   $('t-sz').value.trim(),
    a2l:    $('t-a2l').value.trim(),
    prefix: $('t-prefix').value.trim(),
  };
  const fd=new FormData();
  fd.append('elf', S.elfFile);
  fd.append('tools', JSON.stringify(tools));
  try{
    const res=await fetch('/debug_elf',{method:'POST',body:fd});
    const d=await res.json();
    if(d.error){$('dbg-out').textContent='ERROR: '+d.error+(d.trace?'\n\n'+d.trace:'');return}
    let out='';
    out+=`ELF file size: ${d.file_size.toLocaleString()} bytes\n\n`;
    for(const[name,t] of Object.entries(d.tools||{})){
      const ok=t.rc===0&&t.lines>0;
      out+=`${'═'.repeat(60)}\n`;
      out+=`TOOL: ${name.toUpperCase()}\n`;
      out+=`  Path:   ${t.path}\n`;
      out+=`  Found:  ${t.found?'✅ YES':'❌ NO — not on PATH, check spelling/prefix'}\n`;
      out+=`  Cmd:    ${t.cmd}\n`;
      out+=`  RC:     ${t.rc}\n`;
      out+=`  Lines:  ${t.lines} ${ok?'✅':'⚠ (0 lines = tool failed or ELF has no symbols)'}\n`;
      if(t.stderr) out+=`  STDERR: ${t.stderr}\n`;
      out+=`\nOUTPUT (first 2000 chars):\n${t.stdout||'(empty)'}\n\n`;
    }
    $('dbg-out').textContent=out;
  }catch(e){
    $('dbg-out').textContent='Fetch error: '+e.message;
  }
}

// Show debug info in status after ELF analysis
function showDebugSummary(d){
  if(!d.debug)return;
  const dbg=d.debug;
  const ok=dbg.nm_lines>0;
  const status=ok
    ? `✅ nm: ${dbg.nm_lines} symbols | path: ${dbg.nm_tool}`
    : `❌ nm returned 0 symbols — see Debug tab`;
  $('tool-status').textContent=status;
  // Always populate the debug pane with latest info
  let out='';
  if(dbg.prefix_input)
    out+=`Prefix input:    ${dbg.prefix_input}\n`;
  if(dbg.prefix_resolved)
    out+=`Prefix resolved: ${dbg.prefix_resolved}\n`;
  out+='\n';
  const tools2=[
    {name:'NM',      tool:dbg.nm_tool,  rc:dbg.nm_rc,  found:dbg.nm_found,  lines:dbg.nm_lines,  err:dbg.nm_stderr,  out:dbg.nm_sample},
    {name:'READELF', tool:dbg.re_tool,  rc:dbg.re_rc,  found:dbg.re_found,  lines:0,              err:dbg.re_stderr,  out:dbg.re_sample},
    {name:'SIZE',    tool:dbg.sz_tool,  rc:dbg.sz_rc,  found:dbg.sz_found,  lines:0,              err:dbg.sz_stderr,  out:''},
  ];
  for(const t of tools2){
    out+=`${'═'.repeat(56)}\n`;
    out+=`TOOL: ${t.name}\n`;
    out+=`  Resolved path: ${t.tool}\n`;
    out+=`  Exists/found:  ${t.found?'✅ YES':'❌ NO — path is wrong or tool not installed'}\n`;
    out+=`  Exit code:     ${t.rc}\n`;
    if(t.name==='NM') out+=`  Symbols found: ${t.lines} ${t.lines>0?'✅':'❌'}\n`;
    if(t.err)  out+=`  STDERR: ${t.err}\n`;
    if(t.out)  out+=`\nSAMPLE OUTPUT:\n${t.out}\n`;
    out+='\n';
  }
  $('dbg-out').textContent=out;
  if(!ok) switchToTab('dbg');
}

// ── Addr2line ─────────────────────────────────────────────────────────────────
async function doA2L(){
  const addr=$('a2l-addr').value.trim();
  if(!addr)return;
  $('a2l-res').textContent='Looking up…';
  const fd=new FormData();
  fd.append('addr',addr);
  fd.append('prefix',$('t-prefix').value.trim());
  fd.append('a2l_tool',$('t-a2l').value.trim());
  if(S.elfFile) fd.append('elf',S.elfFile);
  const res=await fetch('/addr2line',{method:'POST',body:fd});
  const d=await res.json();
  $('a2l-res').textContent=d.result||d.error||'No result';
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tip=$('tip');
function hover(el,info){
  el.addEventListener('mouseenter',e=>{
    let h=`<div class="tn">${info.name}</div>`;
    info.rows.forEach(([k,v])=>h+=`<div class="tr2"><span>${k}</span><span class="tv">${v}</span></div>`);
    if(info.desc)h+=`<div class="tdesc">${info.desc}</div>`;
    tip.innerHTML=h; tip.classList.add('on'); tipPos(e);
  });
  el.addEventListener('mousemove',tipPos);
  el.addEventListener('mouseleave',()=>tip.classList.remove('on'));
}
function tipPos(e){
  const x=e.clientX+14,y=e.clientY+10;
  const w=tip.offsetWidth||280,h=tip.offsetHeight||120;
  tip.style.left=Math.min(x,innerWidth-w-8)+'px';
  tip.style.top=Math.min(y,innerHeight-h-8)+'px';
}
</script>
</body>
</html>

"""


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    response.content_type = 'text/html; charset=utf-8'
    return HTML


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

        # Save ELF — file is CLOSED before any subprocess opens it (Windows fix)
        tmp   = save_elf(up)
        tools = resolve_tools(raw_tools)

        nm_t, re_t, sz_t = tools['nm'], tools['re'], tools['size']

        # Run tools
        nm_out, nm_err, nm_rc = run_tool([nm_t, '--print-size', '--radix=x', tmp])
        if not nm_out.strip():
            nm_out, nm_err, nm_rc = run_tool([nm_t, '--print-size', '--radix=x',
                                               '--line-numbers', tmp])
        if not nm_out.strip():
            nm_out, nm_err, nm_rc = run_tool([nm_t, tmp])

        re_out, re_err, re_rc = run_tool([re_t, '-S', '--wide', tmp])
        sz_out, sz_err, sz_rc = run_tool([sz_t, '-A', '-x', tmp])

        nm_lines = [l for l in nm_out.splitlines() if l.strip()]

        # Build debug info — always included in response
        def tool_ok(t):
            return (bool(shutil.which(t)) or
                    os.path.isfile(t) or
                    os.path.isfile(t + '.exe'))

        debug = {
            "file_size":    os.path.getsize(tmp) if os.path.exists(tmp) else 0,
            "prefix_in":    tools['prefix_in'],
            "prefix_out":   tools['prefix_out'],
            "nm_tool":      nm_t,  "nm_ok": tool_ok(nm_t),
            "nm_rc":        nm_rc, "nm_lines": len(nm_lines),
            "nm_stderr":    nm_err[:800]  if nm_err else "",
            "nm_sample":    nm_out[:1200] if nm_out else "(empty)",
            "re_tool":      re_t,  "re_ok": tool_ok(re_t),
            "re_rc":        re_rc,
            "re_stderr":    re_err[:400]  if re_err else "",
            "re_sample":    re_out[:600]  if re_out else "(empty)",
            "sz_tool":      sz_t,  "sz_ok": tool_ok(sz_t),
            "sz_rc":        sz_rc,
            "sz_stderr":    sz_err[:300]  if sz_err else "",
        }

        symbols  = parse_nm_output(nm_out)
        elf_secs = parse_readelf_output(re_out)
        sz_data  = parse_size_output(sz_out)

        for name, s in sz_data.items():
            if name in elf_secs:
                if elf_secs[name]['size'] == 0:
                    elf_secs[name]['size'] = s['size']
            else:
                elf_secs[name] = {'addr':s['addr'],'size':s['size'],
                                  'type':'PROGBITS','flags':''}

        ld_secs = ld_data.get('sections', [])
        assign_symbols(symbols, elf_secs, ld_secs)

        for reg in ld_data.get('regions', []):
            reg['used_bytes'] = sum(
                elf_secs.get(s['name'],{}).get('size',0)
                for s in reg.get('sections',[]))

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
        results = {"file_size": fsize, "prefix_in": tools['prefix_in'],
                   "prefix_out": tools['prefix_out'], "tools": {}}

        for name, t, args_extra in [
            ('nm',   tools['nm'],   ['--print-size','--radix=x']),
            ('re',   tools['re'],   ['-S','--wide']),
            ('size', tools['size'], ['-A','-x']),
        ]:
            stdout, stderr, rc = run_tool([t] + args_extra + [tmp])
            def tool_ok(p):
                return bool(shutil.which(p)) or os.path.isfile(p) or os.path.isfile(p+'.exe')
            results["tools"][name] = {
                "path":   t,
                "found":  tool_ok(t),
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
        addr   = request.forms.get('addr','').strip()
        raw    = {'prefix': request.forms.get('prefix',''),
                  'a2l':    request.forms.get('a2l_tool','')}
        up     = request.files.get('elf')
        if not addr:
            return json.dumps({"error": "No address"})
        if not up:
            return json.dumps({"error": "No ELF file"})
        try:
            addr_int = int(addr, 0)
        except ValueError:
            return json.dumps({"error": f"Bad address: {addr}"})
        tmp  = save_elf(up)
        tool = resolve_tools(raw)['a2l']
        out, err, rc = run_tool([tool, '-e', tmp, '-f', '-C', '-p', hex(addr_int)])
        return json.dumps({"result": out.strip() or err.strip() or "No result"})
    except Exception as ex:
        return json.dumps({"error": str(ex)})
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except Exception: pass


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def _find_free_port(candidates):
    for port in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('localhost', port))
                return port
        except OSError:
            print(f"  Port {port} busy, trying next...")
    return None


if __name__ == '__main__':
    candidates = [5000, 5500, 7000, 7777, 8000, 8080, 8888, 9000, 3000]
    if len(sys.argv) > 1:
        try: candidates = [int(sys.argv[1])] + candidates
        except ValueError: pass

    PORT = _find_free_port(candidates)
    if not PORT:
        print("\n[ERROR] No free port. Try:  python linker_viewer.py 12345\n")
        sys.exit(1)

    print(f"""
  Linker MemMap Viewer  ->  http://localhost:{PORT}

  Toolchain prefix examples:
    arm-none-eabi-
    D:/NXP/S32DS.3.6.4/S32DS/build_tools/gcc_v11.4/gcc-11.4-arm32-eabi/bin/arm-none-eabi-
    (or same path with backslashes - both work)

  Ctrl+C to stop
""")
    threading.Thread(
        target=lambda: (lambda: webbrowser.open(f'http://localhost:{PORT}'))(),
        daemon=True).start()
    run(app, host='localhost', port=PORT, quiet=True, max_request_size=256*1024*1024)
