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

import sys, json, os, subprocess, shutil, webbrowser, threading, socket, tempfile
from pathlib import Path

try:
    from bottle import Bottle, request, response, run
except ImportError:
    print("\n[ERROR] Missing dependency.  Run:  pip install bottle\n")
    sys.exit(1)

app = Bottle()

# Increase form field size limit — map files can be 1-5MB
# Default 102400 (100KB) silently truncates large text fields
from bottle import BaseRequest
BaseRequest.MEMFILE_MAX = 10 * 1024 * 1024   # 10MB

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

    mb = re.search(r'MEMORY\s*\{([^}]+)', content, re.DOTALL)
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
            r'\{([^{}]*(?:\{[^{}]*[^{}]*)*)[^>]*>\s*(\w+)?(?:\s*AT\s*>\s*(\w+))?',
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
            r'\s*\[\s*\d+\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+'
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
# MAP FILE PARSER (inline — no separate module needed)
# ---------------------------------------------------------------------------

import re


def parse_map(content):
    """
    Returns dict with:
      sections   - list of {name, addr, size, units:[{file, size}]}
      symbols    - list of {name, addr, size, file, section}
      discarded  - list of {name, file}
      cross_refs - list of {symbol, referenced_by}
      summary    - {total_flash, total_ram, by_file:[{file, flash, ram}]}
    """
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    sections   = _parse_sections(content)
    discarded  = _parse_discarded(content)
    symbols    = _extract_symbols(sections)
    cross_refs = _parse_cross_refs(content)
    summary    = _make_summary(sections)

    return {
        "sections":   sections,
        "symbols":    symbols,
        "discarded":  discarded,
        "cross_refs": cross_refs[:100],   # cap for JSON size
        "summary":    summary,
    }


def _parse_sections(content):
    """
    Parse the main memory map block.
    GCC map format:
    .section        0xaddr   0xsize
     .section.sub   0xaddr   0xsize  path/to/file.o
                    0xaddr   symbol_name
    """
    sections = []
    current_sec = None

    # Find the memory map block
    map_start = re.search(r'^Linker script and memory map', content, re.MULTILINE)
    if not map_start:
        map_start = re.search(r'^\.(text|data|bss|rodata)', content, re.MULTILINE)
    start_pos = map_start.start() if map_start else 0

    lines = content[start_pos:].splitlines()

    for line in lines:
        # Top-level section: ".name   0xADDR   0xSIZE"
        m = re.match(r'^(\.\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*$', line)
        if m:
            current_sec = {
                "name":  m.group(1),
                "addr":  int(m.group(2), 16),
                "size":  int(m.group(3), 16),
                "units": [],
                "symbols": [],
            }
            sections.append(current_sec)
            continue

        # Sub-section with file: " .sub  0xADDR  0xSIZE  file.o"
        m = re.match(r'^\s+(\.\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)', line)
        if m and current_sec:
            fname = m.group(4)
            sz    = int(m.group(3), 16)
            if sz > 0:
                current_sec["units"].append({
                    "subsection": m.group(1),
                    "addr":       int(m.group(2), 16),
                    "size":       sz,
                    "file":       _short_path(fname),
                    "file_full":  fname,
                })
            continue

        # Symbol definition: "  0xADDR  symbol_name"
        m = re.match(r'^\s+(0x[0-9a-fA-F]{4,})\s+(\S+)\s*$', line)
        if m and current_sec:
            addr = int(m.group(1), 16)
            name = m.group(2)
            if not name.startswith('0x') and not name.startswith('.'):
                current_sec["symbols"].append({"name": name, "addr": addr})
            continue

    return [s for s in sections if s['size'] > 0]


def _parse_discarded(content):
    discarded = []
    in_disc   = False
    for line in content.splitlines():
        if 'Discarded input sections' in line:
            in_disc = True
            continue
        if in_disc:
            if line.strip() == '' or (line[0] not in ' \t' and '.' not in line):
                in_disc = False
                continue
            m = re.match(r'\s+(\.\S+)\s+0x\S+\s+0x\S+\s+(\S+)', line)
            if m:
                discarded.append({
                    "name": m.group(1),
                    "file": _short_path(m.group(2)),
                    "file_full": m.group(2),
                })
    return discarded


def _parse_cross_refs(content):
    refs = []
    in_xref = False
    for line in content.splitlines():
        if 'Cross Reference Table' in line:
            in_xref = True
            continue
        if in_xref:
            m = re.match(r'^(\S+)\s+(\S+)', line)
            if m:
                refs.append({"symbol": m.group(1), "referenced_by": m.group(2)})
    return refs


def _extract_symbols(sections):
    """Flatten all symbols from sections into a searchable list."""
    symbols = []
    for sec in sections:
        # Symbols listed in map
        for sym in sec.get('symbols', []):
            symbols.append({
                "name":    sym['name'],
                "addr":    sym['addr'],
                "size":    0,           # map doesn't always give size per symbol
                "section": sec['name'],
                "file":    "",
            })
        # One symbol per unit (the unit itself)
        for u in sec.get('units', []):
            symbols.append({
                "name":    u['subsection'],
                "addr":    u['addr'],
                "size":    u['size'],
                "section": sec['name'],
                "file":    u['file'],
            })
    return symbols


def _make_summary(sections):
    """Per-file flash and RAM usage."""
    FLASH_SECS = {'.text', '.rodata', '.data', '.init', '.fini',
                  '.itcm_text', '.acfls_code_rom', '.pflash'}
    RAM_SECS   = {'.data', '.bss', '.dtcm_data', '.dtcm_bss',
                  '.non_cacheable_data', '.non_cacheable_bss',
                  '.sram_data', '.sram_bss', '.heap', '.stack'}

    by_file = {}
    total_flash = total_ram = 0

    for sec in sections:
        is_flash = any(sec['name'].startswith(s) for s in FLASH_SECS)
        is_ram   = any(sec['name'].startswith(s) for s in RAM_SECS)
        for u in sec.get('units', []):
            f = u['file']
            if f not in by_file:
                by_file[f] = {'file': f, 'flash': 0, 'ram': 0, 'total': 0}
            if is_flash:
                by_file[f]['flash'] += u['size']
                total_flash += u['size']
            if is_ram:
                by_file[f]['ram'] += u['size']
                total_ram += u['size']
            by_file[f]['total'] += u['size']

    ranked = sorted(by_file.values(), key=lambda x: -x['total'])
    return {
        "total_flash": total_flash,
        "total_ram":   total_ram,
        "by_file":     ranked[:80],   # top 80 contributors
    }


def _short_path(p):
    """Shorten a path to the last 2 components for display."""
    p = p.replace('\\', '/')
    parts = [x for x in p.split('/') if x]
    if len(parts) <= 2:
        return p
    return '/'.join(parts[-2:])



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
  --bg:#080b10;--surf:#0d1117;--s2:#161b22;--s3:#1c2330;--s4:#21262d;
  --bdr:#21262d;--bdr2:#2d333b;--txt:#c9d1d9;--dim:#6e7681;--dim2:#8b949e;
  --acc:#58a6ff;--grn:#3fb950;--ora:#d29922;--red:#f85149;--pur:#bc8cff;--cyn:#39d353;
  --mono:'JetBrains Mono',monospace;--ui:'Syne',sans-serif;
  --rad:8px;--rad2:6px;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--txt);font-family:var(--mono);font-size:13px;display:flex;flex-direction:column;overflow:hidden}

/* ── Header ── */
header{background:var(--surf);border-bottom:1px solid var(--bdr);padding:10px 18px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;flex-shrink:0;z-index:200;position:relative}
h1{font-family:var(--ui);font-size:16px;font-weight:800;color:#fff;letter-spacing:-.5px;white-space:nowrap}
h1 em{color:var(--acc);font-style:normal}
.chip{background:var(--s2);border:1px solid var(--bdr);border-radius:4px;padding:2px 8px;font-size:11px;color:var(--dim);white-space:nowrap;transition:.2s}
.chip.grn{background:#0d2318;border-color:#1a5c2a;color:var(--grn)}
.chip.blu{background:#0d1e33;border-color:#1a3a6a;color:var(--acc)}
.chip.ora{background:#1e1008;border-color:#5a3010;color:var(--ora)}
.chip.pur{background:#160d2a;border-color:#3a1a6a;color:var(--pur)}
.spacer{flex:1}
.hbtn{background:var(--s2);border:1px solid var(--bdr);color:var(--txt);padding:5px 11px;
  border-radius:var(--rad2);cursor:pointer;font:11px var(--mono);transition:.15s;white-space:nowrap}
.hbtn:hover{border-color:var(--acc);color:var(--acc)}
.hbtn.act{border-color:var(--acc);color:var(--acc);background:#0c1929}

/* ── Layout ── */
.layout{display:flex;flex:1;overflow:hidden;min-height:0}

/* ── Sidebar ── */
.sidebar{width:248px;min-width:200px;background:var(--surf);border-right:1px solid var(--bdr);
  display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto;overflow-x:hidden}
.sidebar::-webkit-scrollbar{width:4px}
.sidebar::-webkit-scrollbar-thumb{background:var(--s3);border-radius:2px}
.sb-sec{border-bottom:1px solid var(--bdr);padding:12px 14px}
.sb-title{font-family:var(--ui);font-size:10px;font-weight:700;color:var(--dim);
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.sb-title .req{font-size:9px;padding:1px 5px;border-radius:3px;font-weight:500;letter-spacing:0}

/* Drop areas */
.drop-area{border:2px dashed var(--bdr);border-radius:var(--rad);padding:12px 10px;text-align:center;
  cursor:pointer;transition:.2s;position:relative;background:var(--bg);user-select:none}
.drop-area:hover,.drop-area.over{border-color:var(--acc);background:#0c1929}
.drop-area input[type=file]{position:absolute;width:1px;height:1px;
  opacity:0;pointer-events:none}
.drop-area .dico{font-size:20px;margin-bottom:4px;pointer-events:none}
.drop-area p{font-size:11px;color:var(--dim);line-height:1.4;pointer-events:none}
.drop-area.loaded{border-color:var(--grn);border-style:solid}
.drop-area.loaded p{color:var(--grn)}
.fname{font-size:10px;color:var(--acc);margin-top:5px;word-break:break-all;line-height:1.3}
progress{width:100%;height:3px;margin-top:5px;border-radius:2px;background:var(--s3);border:none;display:none}
progress::-webkit-progress-bar{background:var(--s3);border-radius:2px}
progress::-webkit-progress-value{background:var(--acc);border-radius:2px}

/* Toolchain */
.tool-row{display:flex;flex-direction:column;gap:3px;margin-bottom:6px}
.tool-row label{font-size:10px;color:var(--dim)}
.tool-row input{background:var(--bg);border:1px solid var(--bdr);border-radius:4px;
  padding:5px 8px;color:var(--txt);font:11px var(--mono);width:100%;transition:.15s}
.tool-row input:focus{outline:none;border-color:var(--acc)}
.run-btn{width:100%;padding:8px;background:var(--acc);color:#000;border:none;border-radius:var(--rad2);
  font:600 12px var(--ui);cursor:pointer;transition:.15s;margin-top:5px}
.run-btn:hover{background:#79baff}
.run-btn:disabled{background:var(--s3);color:var(--dim);cursor:default}
#tool-status{font-size:10px;color:var(--dim);margin-top:5px;line-height:1.5;min-height:14px}

/* ── Features Panel ── */
.feat-panel{padding:0}
.feat-group{border-bottom:1px solid var(--bdr)}
.feat-group-hdr{display:flex;align-items:center;gap:6px;padding:8px 14px;cursor:pointer;
  font-size:11px;color:var(--dim);transition:.15s;user-select:none}
.feat-group-hdr:hover{color:var(--txt);background:var(--s2)}
.feat-group-hdr .arrow{font-size:9px;transition:.2s;flex-shrink:0}
.feat-group-hdr.open .arrow{transform:rotate(90deg)}
.feat-group-body{display:none;padding:4px 0 8px 0}
.feat-group-body.open{display:block}
.feat-item{display:flex;align-items:flex-start;gap:8px;padding:5px 14px 5px 24px;
  transition:.15s;cursor:pointer}
.feat-item:hover{background:var(--s2)}
.feat-item.disabled{opacity:0.4;cursor:not-allowed}
.feat-item input[type=checkbox]{accent-color:var(--acc);width:13px;height:13px;
  flex-shrink:0;margin-top:1px;cursor:pointer}
.feat-item.disabled input{cursor:not-allowed}
.feat-label{flex:1}
.feat-name{font-size:11px;color:var(--txt);line-height:1.3}
.feat-item.disabled .feat-name{color:var(--dim)}
.feat-desc{font-size:10px;color:var(--dim);line-height:1.3;margin-top:1px}
.feat-reqs{display:flex;gap:3px;margin-top:3px}
.req-dot{width:16px;height:16px;border-radius:3px;font-size:8px;font-weight:700;
  display:flex;align-items:center;justify-content:center;flex-shrink:0}
.req-dot.ld {background:#0d2140;color:var(--acc);border:1px solid #1a3a6a}
.req-dot.elf{background:#1e0d33;color:var(--pur);border:1px solid #3a1a6a}
.req-dot.map{background:#1e1008;color:var(--ora);border:1px solid #5a3010}
.req-dot.off{background:var(--s3);color:var(--dim);border:1px solid var(--bdr)}

/* ── Main ── */
.main{flex:1;overflow:auto;padding:16px 20px;display:flex;flex-direction:column}
.main::-webkit-scrollbar{width:6px}
.main::-webkit-scrollbar-thumb{background:var(--s3);border-radius:3px}

/* ── Tabs ── */
.tabs{display:flex;border-bottom:1px solid var(--bdr);margin-bottom:14px;overflow-x:auto;flex-shrink:0}
.tabs::-webkit-scrollbar{height:3px}
.tabs::-webkit-scrollbar-thumb{background:var(--s3)}
.tab{padding:7px 14px;cursor:pointer;font-size:12px;color:var(--dim);
  border-bottom:2px solid transparent;transition:.15s;white-space:nowrap;flex-shrink:0;user-select:none}
.tab:hover{color:var(--txt)}
.tab.act{color:var(--acc);border-bottom-color:var(--acc)}
.tab .badge{background:var(--red);color:#fff;border-radius:10px;font-size:9px;
  padding:1px 5px;margin-left:4px;vertical-align:middle}
.pane{display:none;flex:1;min-height:0}
.pane.act{display:block}

/* ── Memory SVG ── */
#mc{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:16px;overflow-x:auto;margin-bottom:12px}
#leg{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}
.li{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--dim);cursor:default}
.ld2{width:10px;height:10px;border-radius:2px;flex-shrink:0}

/* ── Tables ── */
.card-wrap{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);overflow:hidden;margin-bottom:12px}
.tbl-hdr{background:var(--s2);padding:9px 14px;font-family:var(--ui);font-size:12px;font-weight:600;
  color:#fff;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tbl-hdr .sub{font-size:11px;color:var(--dim);font-weight:400;font-family:var(--mono)}
.tbl-hdr .tbl-actions{margin-left:auto;display:flex;gap:6px}
table{width:100%;border-collapse:collapse}
th{background:var(--s2);color:var(--dim);font-size:10px;font-weight:500;text-transform:uppercase;
  letter-spacing:.07em;padding:7px 12px;text-align:left;border-bottom:1px solid var(--bdr);
  cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--txt)}
th.sa::after{content:' ↑'}th.sd::after{content:' ↓'}
td{padding:6px 12px;border-bottom:1px solid #0a0e14;font-size:12px;vertical-align:middle;
  max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr.clickable:hover td{background:#0a0f18;cursor:pointer}
.hx{color:var(--acc);font-size:11px}
.sz{color:var(--grn)}
.dim{color:var(--dim)}
.tb{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;border:1px solid;vertical-align:middle}

/* Filter bar */
.filter-bar{display:flex;gap:7px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
.search{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad2);
  padding:5px 10px;color:var(--txt);font:12px var(--mono);flex:1;min-width:150px;transition:.15s}
.search:focus{outline:none;border-color:var(--acc)}
select.fsel{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad2);
  padding:5px 8px;color:var(--txt);font:12px var(--mono);cursor:pointer;transition:.15s}
select.fsel:focus{outline:none;border-color:var(--acc)}
.cnt{font-size:11px;color:var(--dim);flex-shrink:0}

/* Stat cards */
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:12px}
.stat{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);padding:14px 16px;
  transition:.15s;cursor:default}
.stat:hover{border-color:var(--bdr2)}
.snum{font-family:var(--ui);font-size:24px;font-weight:800;color:var(--acc);margin-bottom:3px;line-height:1}
.slbl{font-size:10px;color:var(--dim);line-height:1.4}

/* Warning cards */
.warn-list{display:flex;flex-direction:column;gap:7px}
.wcard{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:12px 14px;display:flex;gap:10px;transition:.15s;cursor:pointer}
.wcard:hover{border-color:var(--bdr2)}
.wcard.error{border-color:#5a1a1a;background:#140808}
.wcard.warn{border-color:#5a3d1a;background:#100c05}
.wcard.info{border-color:#1a2a3a;background:#08101a}
.wico{font-size:18px;flex-shrink:0;margin-top:1px}
.wtitle{font-weight:500;color:#fff;font-size:12px;margin-bottom:3px}
.wcat{font-size:10px;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:.07em}
.wdet{font-size:11px;color:#8b949e;line-height:1.5}

/* Startup */
.sr{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--bdr);font-size:12px}
.sr:last-child{border:none}
.stype{padding:2px 7px;border-radius:3px;font-size:10px;font-weight:500;width:58px;text-align:center;flex-shrink:0}
.copied{background:#0d1e33;color:var(--acc);border:1px solid #1a3a6a}
.zeroed{background:#0d2318;color:var(--grn);border:1px solid #1a5c2a}

/* Addr2line */
.a2l-inp{display:flex;gap:7px;margin-bottom:9px}
.a2l-inp input{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad2);
  padding:6px 10px;color:var(--txt);font:12px var(--mono);flex:1;transition:.15s}
.a2l-inp input:focus{outline:none;border-color:var(--acc)}
.a2l-res{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:14px;font-size:12px;min-height:54px;white-space:pre-wrap;line-height:1.6}

/* Fill bar */
.fill-bg{background:var(--s3);border-radius:3px;height:6px;display:inline-block;vertical-align:middle}
.fill-bar{height:6px;border-radius:3px;transition:width .3s}

/* Section cards */
.sec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:10px}
.sec-card{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:12px 14px;display:flex;gap:10px;cursor:pointer;transition:.15s;position:relative}
.sec-card:hover{border-color:var(--bdr2);transform:translateY(-1px);box-shadow:0 4px 20px #00000040}
.sc-dot{width:10px;height:10px;border-radius:2px;margin-top:3px;flex-shrink:0}
.sc-name{font-size:12px;font-weight:500;color:#fff;margin-bottom:3px;line-height:1.3}
.sc-type{font-size:10px;color:var(--dim);margin-bottom:4px}
.sc-desc{font-size:11px;color:#8b949e;line-height:1.5}
.sc-size{font-size:11px;color:var(--grn);margin-top:4px;font-weight:500}
.badge{font-size:9px;padding:1px 5px;border-radius:3px;background:var(--s2);
  color:var(--dim);border:1px solid var(--bdr);margin-left:3px;vertical-align:middle}
.nb{background:#200d0d;border-color:#5a1a1a;color:var(--red)}
.vb{background:#0d1a2a;border-color:#1a3a6a;color:var(--acc)}
.gb{background:#0d1e0d;border-color:#1a4a1a;color:var(--grn)}
.cb{background:#1e1208;border-color:#4a3008;color:var(--ora)}

/* Empty state */
.empty{text-align:center;padding:48px 32px;color:var(--dim)}
.empty .eico{font-size:36px;margin-bottom:12px}
.empty h3{font-family:var(--ui);font-size:15px;color:#fff;margin-bottom:8px}
.empty p{font-size:12px;line-height:1.6}

/* ── POPUP / MODAL ── */
.modal-overlay{position:fixed;inset:0;background:#00000090;z-index:1000;display:flex;
  align-items:flex-start;justify-content:center;padding:40px 20px;overflow-y:auto;
  opacity:0;pointer-events:none;transition:opacity .2s;backdrop-filter:blur(4px)}
.modal-overlay.open{opacity:1;pointer-events:all}
.modal{background:var(--surf);border:1px solid var(--bdr2);border-radius:12px;
  width:min(860px,95vw);max-height:85vh;display:flex;flex-direction:column;
  box-shadow:0 24px 80px #00000080;transform:translateY(-12px);transition:transform .2s;overflow:hidden}
.modal-overlay.open .modal{transform:translateY(0)}
.modal-head{padding:18px 20px 14px;border-bottom:1px solid var(--bdr);display:flex;align-items:flex-start;gap:12px;flex-shrink:0}
.modal-icon{font-size:28px;flex-shrink:0;margin-top:2px}
.modal-title{font-family:var(--ui);font-size:18px;font-weight:700;color:#fff;margin-bottom:3px}
.modal-subtitle{font-size:12px;color:var(--dim);line-height:1.4}
.modal-close{margin-left:auto;background:var(--s2);border:1px solid var(--bdr);color:var(--dim);
  width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:16px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;transition:.15s}
.modal-close:hover{color:#fff;border-color:var(--dim)}
.modal-body{overflow-y:auto;padding:0;flex:1}
.modal-body::-webkit-scrollbar{width:6px}
.modal-body::-webkit-scrollbar-thumb{background:var(--s3);border-radius:3px}
.modal-tabs{display:flex;border-bottom:1px solid var(--bdr);padding:0 20px;background:var(--s2);flex-shrink:0}
.modal-tab{padding:8px 14px;cursor:pointer;font-size:12px;color:var(--dim);
  border-bottom:2px solid transparent;transition:.15s;white-space:nowrap}
.modal-tab:hover{color:var(--txt)}
.modal-tab.act{color:var(--acc);border-bottom-color:var(--acc)}
.modal-pane{display:none;padding:18px 20px}
.modal-pane.act{display:block}

/* Popup specific */
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.info-card{background:var(--s2);border:1px solid var(--bdr);border-radius:var(--rad);padding:12px 14px}
.info-label{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px}
.info-value{font-size:13px;color:#fff;font-weight:500;word-break:break-all}
.info-value.hx{color:var(--acc)}
.info-value.sz{color:var(--grn)}
.contrib-bar{margin-bottom:6px}
.contrib-name{font-size:11px;color:var(--dim);margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.contrib-row{display:flex;align-items:center;gap:8px}
.contrib-fill{height:14px;border-radius:3px;min-width:3px;transition:width .4s}
.contrib-sz{font-size:11px;color:var(--grn);flex-shrink:0}
.sym-mini-table{width:100%;border-collapse:collapse;font-size:11px}
.sym-mini-table th{background:var(--s3);color:var(--dim);padding:5px 9px;text-align:left;font-weight:500;font-size:10px}
.sym-mini-table td{padding:5px 9px;border-bottom:1px solid #0a0e14;color:var(--txt)}
.sym-mini-table tr:last-child td{border:none}
.sym-mini-table tr:hover td{background:var(--s2);cursor:pointer}
.warn-details{background:var(--s2);border-radius:var(--rad);padding:14px;font-size:12px;
  color:#8b949e;line-height:1.7;margin-bottom:12px}
.code-block{background:var(--bg);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:12px 14px;font:12px var(--mono);color:var(--acc);white-space:pre-wrap;
  overflow-x:auto;margin-bottom:12px}
.section-contributors{display:flex;flex-direction:column;gap:4px}
.tag-row{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.tag{font-size:10px;padding:2px 7px;border-radius:12px;background:var(--s2);
  border:1px solid var(--bdr);color:var(--dim)}

/* Treemap */
.treemap{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:12px;min-height:120px}
.tree-cell{border-radius:4px;display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:.15s;overflow:hidden;position:relative;font-size:10px;
  font-weight:500;color:rgba(255,255,255,0.9);text-align:center;padding:4px}
.tree-cell:hover{filter:brightness(1.2);z-index:1}
.tree-cell .tc-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
.tree-cell .tc-size{font-size:9px;opacity:.8;display:block}

/* Bloat / Dead Code panes */
.bloat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-bottom:14px}
.bloat-card{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:12px 14px;cursor:pointer;transition:.15s}
.bloat-card:hover{border-color:var(--bdr2);transform:translateY(-1px)}
.bc-rank{font-size:10px;color:var(--dim);margin-bottom:4px}
.bc-name{font-size:12px;color:#fff;font-weight:500;margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bc-meta{font-size:11px;color:var(--dim)}
.bc-size{font-size:20px;font-family:var(--ui);font-weight:800;color:var(--acc);margin-top:4px}

/* Tooltip */
#tip{position:fixed;background:#161b22;border:1px solid var(--bdr2);border-radius:var(--rad);
  padding:10px 13px;font-size:11px;pointer-events:none;opacity:0;transition:opacity .12s;
  z-index:9999;max-width:280px;box-shadow:0 8px 32px #00000090;line-height:1.5}
#tip.on{opacity:1}
.tn{font-weight:600;color:#fff;margin-bottom:6px;font-size:12px;font-family:var(--ui)}
.tr2{display:flex;justify-content:space-between;gap:14px;color:var(--dim);margin-bottom:2px}
.tv{color:var(--acc)}
.tdesc{margin-top:7px;color:#8b949e;line-height:1.5;border-top:1px solid var(--bdr);padding-top:7px;font-size:10px}

/* Debug pane */
.dbg-out{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--rad);
  padding:14px;font-size:11px;line-height:1.7;white-space:pre-wrap;min-height:100px}

/* XRef */
.xref-item{padding:9px 12px;border-bottom:1px solid var(--bdr);display:flex;gap:12px;
  align-items:flex-start;cursor:pointer;transition:.15s}
.xref-item:hover{background:var(--s2)}
.xref-sym{font-size:12px;color:var(--acc);font-weight:500;flex-shrink:0;min-width:200px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.xref-ref{font-size:11px;color:var(--dim)}
footer{text-align:center;padding:10px;color:var(--dim);font-size:11px;flex-shrink:0;
  border-top:1px solid var(--bdr);background:var(--surf)}
</style>
</head>
<body>

<!-- ── Header ── -->
<header>
  <h1>Linker <em>MemMap</em></h1>
  <span class="chip">Analyser</span>
  <span class="chip blu" id="fchip" style="display:none">📋 <span id="fname"></span></span>
  <span class="chip pur" id="echip" style="display:none">⚙️ <span id="ename"></span></span>
  <span class="chip ora" id="mchip" style="display:none">🗺 <span id="mname"></span></span>
  <span class="chip grn" id="entry-chip" style="display:none">⚡ <span id="esym"></span></span>
  <span class="chip grn" id="sym-chip"   style="display:none"><span id="symcount"></span> symbols</span>
  <div class="spacer"></div>
  <button class="hbtn" id="feat-toggle-btn" onclick="toggleFeatures()">⚙ Features</button>
  <button class="hbtn" onclick="toggleSidebar()">☰ Files</button>
</header>

<!-- ── Layout ── -->
<div class="layout">

  <!-- ── Sidebar ── -->
  <div class="sidebar" id="sidebar">

    <!-- LD drop -->
    <div class="sb-sec">
      <div class="sb-title">
        <span class="req-dot ld">LD</span> Linker Script
      </div>
      <div class="drop-area" id="ld-drop">
        <input type="file" accept=".ld,.lds,.x" id="ld-fi">
        <div class="dico">📋</div>
        <p>Drop .ld file<br>or click to browse</p>
      </div>
      <div class="fname" id="ld-name" style="display:none"></div>
    </div>

    <!-- ELF drop -->
    <div class="sb-sec">
      <div class="sb-title">
        <span class="req-dot elf">ELF</span> Binary
      </div>
      <div class="drop-area" id="elf-drop">
        <input type="file" id="elf-fi">
        <div class="dico">⚙️</div>
        <p>Drop .elf / .axf<br>for symbol analysis</p>
      </div>
      <div class="fname" id="elf-name" style="display:none"></div>
      <progress id="elf-prog" max="100"></progress>
    </div>

    <!-- Map drop -->
    <div class="sb-sec">
      <div class="sb-title">
        <span class="req-dot map">MAP</span> Linker Map
      </div>
      <div class="drop-area" id="map-drop">
        <input type="file" accept=".map" id="map-fi">
        <div class="dico">🗺</div>
        <p>Drop .map file<br>for per-file breakdown</p>
      </div>
      <div class="fname" id="map-name" style="display:none"></div>
    </div>

    <!-- Toolchain -->
    <div class="sb-sec">
      <div class="sb-title"><span class="req-dot elf">ELF</span> Toolchain</div>
      <div class="tool-row">
        <label>Prefix path (replaces fields below)</label>
        <input id="t-prefix" placeholder="e.g. D:\NXP\bin\arm-none-eabi-">
      </div>
      <div class="tool-row"><label>nm</label>
        <input id="t-nm" value="arm-none-eabi-nm"></div>
      <div class="tool-row"><label>readelf</label>
        <input id="t-re" value="arm-none-eabi-readelf"></div>
      <div class="tool-row"><label>size</label>
        <input id="t-sz" value="arm-none-eabi-size"></div>
      <div class="tool-row"><label>addr2line</label>
        <input id="t-a2l" value="arm-none-eabi-addr2line"></div>
      <button class="run-btn" id="analyse-btn" onclick="runAnalysis()" disabled>▶ Analyse ELF</button>
      <div id="tool-status"></div>
    </div>

    <!-- Features panel -->
    <div class="sb-sec feat-panel" id="feat-panel" style="display:none">
      <div class="sb-title" style="margin-bottom:6px">⚙ Features</div>
      <div id="feat-groups"></div>
    </div>

  </div><!-- /sidebar -->

  <!-- ── Main content ── -->
  <div class="main" id="main">

    <!-- Welcome -->
    <div class="empty" id="welcome">
      <div class="eico">🗂️</div>
      <h3>Drop any combination of files to begin</h3>
      <p>📋 <strong>.ld</strong> — memory map, section layout, region sizes<br>
         ⚙️ <strong>.elf</strong> — symbols, sizes, DMA warnings, addr→line<br>
         🗺 <strong>.map</strong> — per-file flash/RAM, contributors, GC'd sections<br><br>
         Each file is optional. All three together gives the complete picture.<br>
         Click any row, section, or region for a detailed popup.</p>
    </div>

    <!-- App -->
    <div id="app" style="display:none">
      <div class="tabs" id="tabs">
        <div class="tab act" data-pane="map"   onclick="tab(this)">🗺 Memory Map</div>
        <div class="tab"     data-pane="sec"   onclick="tab(this)">📦 Sections</div>
        <div class="tab"     data-pane="sym"   onclick="tab(this)">🔍 Symbols</div>
        <div class="tab"     data-pane="warn"  onclick="tab(this)">⚠ Warnings <span class="badge" id="warn-badge" style="display:none"></span></div>
        <div class="tab"     data-pane="bloat" onclick="tab(this)">💾 Bloat</div>
        <div class="tab"     data-pane="start" onclick="tab(this)">🚀 Startup</div>
        <div class="tab"     data-pane="map2"  onclick="tab(this)">📂 Map File</div>
        <div class="tab"     data-pane="dead"  onclick="tab(this)">🗑 Dead Code</div>
        <div class="tab"     data-pane="a2l"   onclick="tab(this)">📍 Addr→Line</div>
        <div class="tab"     data-pane="dbg"   onclick="tab(this)">🐛 Debug</div>
      </div>

      <!-- MEMORY MAP -->
      <div class="pane act" id="pane-map">
        <div id="mc"><svg id="map-svg"></svg></div>
        <div id="leg"></div>
        <div class="card-wrap">
          <div class="tbl-hdr">Region Summary</div>
          <table><thead><tr>
            <th>Region</th><th>Origin</th><th>End</th><th>Size</th>
            <th>Type</th><th>Used</th><th>Free</th><th>Fill</th><th>Sections</th>
          </tr></thead><tbody id="rtb"></tbody></table>
        </div>
      </div>

      <!-- SECTIONS -->
      <div class="pane" id="pane-sec">
        <div class="filter-bar">
          <input class="search" id="sec-q" placeholder="Filter sections…" oninput="filterSecs()">
          <select class="fsel" id="sec-type" onchange="filterSecs()">
            <option value="">All types</option>
          </select>
          <span class="cnt" id="sec-cnt"></span>
        </div>
        <div class="sec-grid" id="sec-grid"></div>
      </div>

      <!-- SYMBOLS -->
      <div class="pane" id="pane-sym">
        <div class="empty" id="sym-empty">
          <div class="eico">⚙️</div><h3>Load an ELF to explore symbols</h3>
          <p>Drop a .elf / .axf and click <strong>Analyse ELF</strong>.</p>
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
            <select class="fsel" id="sym-f" onchange="filterSyms()">
              <option value="">All files</option>
            </select>
            <select class="fsel" id="sym-g" onchange="filterSyms()">
              <option value="">Global+Local</option>
              <option value="1">Global only</option>
              <option value="0">Local only</option>
            </select>
            <span class="cnt" id="sym-cnt"></span>
          </div>
          <div class="card-wrap">
            <div class="tbl-hdr">
              Symbols
              <div class="tbl-actions">
                <button class="hbtn" onclick="exportSymbols()">⬇ CSV</button>
              </div>
            </div>
            <table id="sym-tbl"><thead><tr>
              <th onclick="sortSym('name')">Symbol</th>
              <th onclick="sortSym('addr')">Address</th>
              <th onclick="sortSym('size')">Size</th>
              <th onclick="sortSym('type')">Type</th>
              <th onclick="sortSym('section')">Section</th>
              <th onclick="sortSym('file')">File</th>
            </tr></thead><tbody id="sym-body"></tbody></table>
          </div>
        </div>
      </div>

      <!-- WARNINGS -->
      <div class="pane" id="pane-warn">
        <div class="filter-bar">
          <select class="fsel" id="warn-lvl" onchange="filterWarns()">
            <option value="">All levels</option>
            <option value="error">Errors only</option>
            <option value="warn">Warnings only</option>
            <option value="info">Info only</option>
          </select>
          <select class="fsel" id="warn-cat" onchange="filterWarns()">
            <option value="">All categories</option>
          </select>
          <span class="cnt" id="warn-cnt"></span>
        </div>
        <div class="warn-list" id="warn-list"></div>
      </div>

      <!-- BLOAT -->
      <div class="pane" id="pane-bloat">
        <div class="empty" id="bloat-empty">
          <div class="eico">💾</div><h3>Load ELF or Map for bloat analysis</h3>
          <p>Shows largest functions, variables, and per-library flash usage.</p>
        </div>
        <div id="bloat-content" style="display:none">
          <div class="sg" id="bloat-stats"></div>
          <div id="bloat-treemap-wrap" class="card-wrap" style="display:none">
            <div class="tbl-hdr">Flash by library / object file <span class="sub">(click cell to filter symbols)</span></div>
            <div class="treemap" id="bloat-treemap" style="padding:12px;min-height:140px"></div>
          </div>
          <div class="card-wrap">
            <div class="tbl-hdr">Largest functions <span class="sub">click row for details</span></div>
            <table><thead><tr>
              <th onclick="sortBloat('fn','name')">Function</th>
              <th onclick="sortBloat('fn','size')">Size</th>
              <th onclick="sortBloat('fn','section')">Section</th>
              <th onclick="sortBloat('fn','file')">File</th>
            </tr></thead><tbody id="bloat-fn"></tbody></table>
          </div>
          <div class="card-wrap">
            <div class="tbl-hdr">Largest variables <span class="sub">click row for details</span></div>
            <table><thead><tr>
              <th onclick="sortBloat('var','name')">Variable</th>
              <th onclick="sortBloat('var','size')">Size</th>
              <th onclick="sortBloat('var','section')">Section</th>
              <th onclick="sortBloat('var','file')">File</th>
            </tr></thead><tbody id="bloat-var"></tbody></table>
          </div>
          <div class="card-wrap" id="dup-card" style="display:none">
            <div class="tbl-hdr">Duplicate symbol names <span class="sub">same name, multiple object files</span></div>
            <table><thead><tr><th>Symbol</th><th>Count</th><th>Files</th></tr></thead>
            <tbody id="bloat-dup"></tbody></table>
          </div>
        </div>
      </div>

      <!-- STARTUP -->
      <div class="pane" id="pane-start">
        <div class="sg" id="start-stats"></div>
        <div class="card-wrap">
          <div class="tbl-hdr">Copy table — what startup code does before main()</div>
          <div style="padding:12px" id="start-rows"></div>
        </div>
      </div>

      <!-- MAP FILE -->
      <div class="pane" id="pane-map2">
        <div class="empty" id="map2-empty">
          <div class="eico">📂</div><h3>Drop a .map file to see per-file breakdown</h3>
          <p>Shows which .o/.a files contribute to each section,<br>GC'd sections, fill bytes, and library breakdown.</p>
        </div>
        <div id="map2-content" style="display:none">
          <div class="sg" id="map2-stats"></div>
          <div class="card-wrap">
            <div class="tbl-hdr">Flash + RAM by object file
              <span class="sub">click row to filter symbols</span>
              <div class="tbl-actions">
                <button class="hbtn" onclick="exportMapCSV()">⬇ CSV</button>
              </div>
            </div>
            <div class="filter-bar" style="padding:8px 12px 0;margin:0">
              <input class="search" id="map2-q" placeholder="Filter files…" oninput="filterMapFiles()">
              <select class="fsel" id="map2-lib" onchange="filterMapFiles()">
                <option value="">All libraries</option>
              </select>
              <span class="cnt" id="map2-cnt"></span>
            </div>
            <table><thead><tr>
              <th onclick="sortMap('file')">File</th>
              <th onclick="sortMap('flash')">Flash</th>
              <th onclick="sortMap('ram')">RAM</th>
              <th onclick="sortMap('total')">Total</th>
              <th>Bar</th>
              <th>Symbols</th>
            </tr></thead><tbody id="map2-tbody"></tbody></table>
          </div>
          <div class="card-wrap" id="sec-contrib-card">
            <div class="tbl-hdr">Section contributors <span class="sub">which files fill each section</span></div>
            <table><thead><tr>
              <th>Section</th><th>Total size</th><th>Top contributors</th>
            </tr></thead><tbody id="sec-contrib-body"></tbody></table>
          </div>
          <div class="card-wrap">
            <div class="tbl-hdr">Discarded / GC'd sections
              <span class="sub">removed by --gc-sections</span>
            </div>
            <table><thead><tr><th>Section</th><th>File</th></tr></thead>
            <tbody id="map2-disc"></tbody>
          </div>
        </div>
      </div>

      <!-- DEAD CODE -->
      <div class="pane" id="pane-dead">
        <div class="empty" id="dead-empty">
          <div class="eico">🗑</div><h3>Load a .map file to see dead code analysis</h3>
          <p>Requires <code>--gc-sections</code> linker flag to be effective.</p>
        </div>
        <div id="dead-content" style="display:none">
          <div class="sg" id="dead-stats"></div>
          <div class="card-wrap">
            <div class="tbl-hdr">GC'd sections by file <span class="sub">click to see what was removed</span></div>
            <table><thead><tr>
              <th onclick="sortDead('file')">File</th>
              <th onclick="sortDead('count')">Sections removed</th>
              <th onclick="sortDead('size')">Est. bytes saved</th>
            </tr></thead><tbody id="dead-tbody"></tbody></table>
          </div>
          <div class="card-wrap">
            <div class="tbl-hdr">All discarded sections</div>
            <div class="filter-bar" style="padding:8px 12px 0;margin:0">
              <input class="search" id="dead-q" placeholder="Filter…" oninput="filterDead()">
            </div>
            <table><thead><tr><th>Section</th><th>File</th></tr></thead>
            <tbody id="dead-all"></tbody></table>
          </div>
        </div>
      </div>

      <!-- ADDR2LINE -->
      <div class="pane" id="pane-a2l">
        <p style="color:var(--dim);font-size:12px;margin-bottom:10px">
          Resolve any hex address to source file and line number.<br>
          Click any symbol or section row to auto-fill.
        </p>
        <div class="a2l-inp">
          <input id="a2l-addr" placeholder="0x00401234" onkeydown="if(event.key==='Enter')doA2L()">
          <button class="hbtn" onclick="doA2L()">Look up</button>
        </div>
        <div class="a2l-res" id="a2l-res">Result will appear here…</div>
        <div style="margin-top:12px">
          <div class="tbl-hdr" style="border-radius:var(--rad) var(--rad) 0 0">Recent lookups</div>
          <div class="card-wrap" style="border-radius:0 0 var(--rad) var(--rad);margin:0">
            <table><thead><tr><th>Address</th><th>Result</th></tr></thead>
            <tbody id="a2l-history"></tbody></table>
          </div>
        </div>
      </div>

      <!-- DEBUG -->
      <div class="pane" id="pane-dbg">
        <p style="color:var(--dim);font-size:12px;margin-bottom:10px">
          Runs nm, readelf, and size on your ELF and shows exact output.<br>
          Use when symbol count is 0 or tools cannot be found.
        </p>
        <button class="hbtn" onclick="runDebug()" style="margin-bottom:12px">🔬 Run diagnostics</button>
        <div class="dbg-out" id="dbg-out">Click Run diagnostics with an ELF loaded.</div>
      </div>

    </div><!-- /app -->
  </div><!-- /main -->
</div><!-- /layout -->

<!-- ── Popup Modal ── -->
<div class="modal-overlay" id="modal-overlay" onclick="closeModal(event)">
  <div class="modal" id="modal">
    <div class="modal-head">
      <div class="modal-icon" id="modal-icon">📦</div>
      <div>
        <div class="modal-title" id="modal-title">Details</div>
        <div class="modal-subtitle" id="modal-subtitle"></div>
      </div>
      <button class="modal-close" onclick="closeModalBtn()">✕</button>
    </div>
    <div class="modal-tabs" id="modal-tabs"></div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<div id="tip"></div>
<footer>Linker MemMap · Drop files anywhere · Click anything for details</footer>

<script>
// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════
const $=id=>document.getElementById(id);
const NS='http://www.w3.org/2000/svg';

const S={
  ld:null, elfFile:null, mapData:null,
  syms:[], fSyms:[], elfSecs:{},
  warns:[], startup:null,
  symSort:'size', symDir:-1,
  mapSort:'total', mapDir:-1,
  deadSort:'count', deadDir:-1,
  bloatFnSort:'size', bloatFnDir:-1,
  bloatVarSort:'size', bloatVarDir:-1,
  allWarns:[],
  a2lHistory:[],
};

// Feature registry — each entry: {id, name, desc, requires, group, default}
// requires: array of 'ld','elf','map'
const FEATURES=[
  // Memory Map
  {id:'f_fillbars',  name:'Region fill bars',       desc:'Shows % used with colour-coded fill bars',   req:['ld','elf'], group:'Memory Map', def:true},
  {id:'f_lmavma',    name:'LMA→VMA arrows',          desc:'Visualise flash→RAM copy sections',           req:['ld'],       group:'Memory Map', def:true},
  {id:'f_symhover',  name:'Largest symbol in hover', desc:'Tooltip shows biggest symbol per section',    req:['ld','elf'], group:'Memory Map', def:true},
  // Sections
  {id:'f_secsize',   name:'Exact section sizes',     desc:'Real sizes from ELF section headers',         req:['elf'],      group:'Sections',   def:true},
  {id:'f_secflags',  name:'Section flags decoded',   desc:'AX/WA flags with warning on odd combos',      req:['elf'],      group:'Sections',   def:true},
  {id:'f_seccontrib',name:'Contributor list',        desc:'Which .o files fill each section',            req:['map'],      group:'Sections',   def:true},
  {id:'f_secfill',   name:'Fill/padding bytes',      desc:'Wasted bytes between symbols per section',    req:['map'],      group:'Sections',   def:true},
  // Symbols
  {id:'f_symprov',   name:'File provenance',         desc:'Which .o file each symbol came from',         req:['map'],      group:'Symbols',    def:true},
  {id:'f_symfilt',   name:'Filter by .o file',       desc:'Dropdown to show symbols from one file only', req:['map','elf'],group:'Symbols',    def:true},
  {id:'f_symweak',   name:'Weak symbol highlight',   desc:'Colour-code weak vs strong definitions',      req:['elf'],      group:'Symbols',    def:true},
  {id:'f_symdup',    name:'Duplicate detection',     desc:'Same name in multiple object files',          req:['elf'],      group:'Symbols',    def:true},
  // Map File tab
  {id:'f_mapsym',    name:'Symbols per file',        desc:'Click file row to filter symbols table',      req:['map','elf'],group:'Map File',   def:true},
  {id:'f_mapregion', name:'Colour by region',        desc:'Colour-code files by memory region type',     req:['map','ld'], group:'Map File',   def:true},
  {id:'f_mapdma',    name:'DMA hazard per file',     desc:'Flag files contributing to cacheable+DMA secs',req:['map','ld','elf'],group:'Map File',def:true},
  {id:'f_maplib',    name:'Library grouping',        desc:'Group and subtotal by .a archive',            req:['map'],      group:'Map File',   def:true},
  // Warnings
  {id:'f_wdma',      name:'DMA buffer in cached RAM',desc:'Variables likely used with DMA in cached RAM',req:['ld','elf'], group:'Warnings',  def:true},
  {id:'f_wunplaced', name:'Unplaced symbols',        desc:'Symbols outside all known LD sections',       req:['ld','elf'], group:'Warnings',  def:true},
  {id:'f_wprintf',   name:'printf/malloc detection', desc:'Flag if printf family appears in symbols',    req:['elf'],      group:'Warnings',  def:true},
  {id:'f_woverlap',  name:'Section overlap check',   desc:'Detects overlapping address ranges',          req:['ld','elf'], group:'Warnings',  def:true},
  {id:'f_walign',    name:'Alignment waste',         desc:'Large alignment with small content',          req:['elf'],      group:'Warnings',  def:false},
  // Bloat
  {id:'f_bloatfn',   name:'Largest functions',       desc:'Ranked list of biggest code symbols',         req:['elf'],      group:'Bloat',     def:true},
  {id:'f_bloatvar',  name:'Largest variables',       desc:'Ranked list of biggest data symbols',         req:['elf'],      group:'Bloat',     def:true},
  {id:'f_bloattree', name:'Library treemap',         desc:'Visual breakdown by .a/.o file contribution', req:['map'],      group:'Bloat',     def:true},
  {id:'f_bloatdup',  name:'Duplicate symbols',       desc:'Same function name from multiple .o files',   req:['elf'],      group:'Bloat',     def:true},
  // Dead Code
  {id:'f_deadlist',  name:'GC\'d sections list',     desc:'Sections removed by --gc-sections',           req:['map'],      group:'Dead Code', def:true},
  {id:'f_deadfile',  name:'By-file GC summary',      desc:'Which files had most dead code removed',      req:['map'],      group:'Dead Code', def:true},
  // Startup
  {id:'f_startexact',name:'Exact copy sizes',        desc:'Real startup copy table from ELF',            req:['ld','elf'], group:'Startup',   def:true},
  {id:'f_startfile', name:'Per-file copy contrib',   desc:'Which .o contributes most to startup copy',   req:['ld','map'], group:'Startup',   def:false},
];

// Load saved feature state
function loadFeatureState(){
  try{
    const saved=JSON.parse(localStorage.getItem('lmv_features')||'{}');
    FEATURES.forEach(f=>{
      f.enabled = f.id in saved ? saved[f.id] : f.def;
    });
  }catch(e){
    FEATURES.forEach(f=>f.enabled=f.def);
  }
}
function saveFeatureState(){
  const state={};
  FEATURES.forEach(f=>state[f.id]=f.enabled);
  localStorage.setItem('lmv_features',JSON.stringify(state));
}
function feat(id){
  const f=FEATURES.find(x=>x.id===id);
  return f&&f.enabled&&f.available;
}
function updateFeatureAvailability(){
  FEATURES.forEach(f=>{
    f.available=f.req.every(r=>(r==='ld'&&!!S.ld)||(r==='elf'&&S.syms.length>0)||(r==='map'&&!!S.mapData));
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// FEATURES PANEL
// ═══════════════════════════════════════════════════════════════════════════
function buildFeaturesPanel(){
  updateFeatureAvailability();
  const container=$('feat-groups');
  container.innerHTML='';
  const groups=[...new Set(FEATURES.map(f=>f.group))];
  groups.forEach(g=>{
    const feats=FEATURES.filter(f=>f.group===g);
    const allAvail=feats.every(f=>f.available);
    const anyEnabled=feats.some(f=>f.enabled&&f.available);
    const div=document.createElement('div');
    div.className='feat-group';
    div.innerHTML=`
      <div class="feat-group-hdr open" onclick="toggleGroup(this)">
        <span class="arrow">▶</span>
        <span style="flex:1;font-family:var(--ui);font-size:11px;font-weight:600">${g}</span>
        <span style="font-size:10px;color:${allAvail?'var(--grn)':'var(--ora)'}">
          ${feats.filter(f=>f.available).length}/${feats.length}
        </span>
      </div>
      <div class="feat-group-body open">
        ${feats.map(f=>featItemHTML(f)).join('')}
      </div>`;
    container.appendChild(div);
  });
  // Bind checkboxes
  container.querySelectorAll('input[type=checkbox]').forEach(cb=>{
    cb.addEventListener('change',e=>{
      const f=FEATURES.find(x=>x.id===e.target.dataset.id);
      if(f&&f.available){f.enabled=e.target.checked;saveFeatureState();rerender();}
      else e.target.checked=!e.target.checked;
    });
  });
}

function featItemHTML(f){
  const reqDots=(['ld','elf','map']).map(r=>{
    const needed=f.req.includes(r);
    const have=(r==='ld'&&!!S.ld)||(r==='elf'&&S.syms.length>0)||(r==='map'&&!!S.mapData);
    const cls=needed?(have?r:'off'):'';
    const label=r.toUpperCase();
    return `<span class="req-dot ${cls}" title="${needed?r+' required':r+' not needed'}">${label}</span>`;
  }).join('');
  const disabled=!f.available;
  const title=disabled?`Requires: ${f.req.join(', ')} file${f.req.length>1?'s':''}`:'';
  return `<div class="feat-item ${disabled?'disabled':''}" title="${title}">
    <input type="checkbox" data-id="${f.id}" ${f.enabled&&!disabled?'checked':''} ${disabled?'disabled':''}>
    <div class="feat-label">
      <div class="feat-name">${f.name}</div>
      <div class="feat-desc">${f.desc}</div>
      <div class="feat-reqs">${reqDots}</div>
    </div>
  </div>`;
}

function toggleGroup(hdr){
  hdr.classList.toggle('open');
  hdr.nextElementSibling.classList.toggle('open');
}
function toggleFeatures(){
  const p=$('feat-panel');
  const btn=$('feat-toggle-btn');
  const showing=p.style.display!=='none';
  p.style.display=showing?'none':'';
  btn.classList.toggle('act',!showing);
}

// ═══════════════════════════════════════════════════════════════════════════
// FILE DROPS
// ═══════════════════════════════════════════════════════════════════════════
function setupDrop(dId,iId,cb){
  const d=$(dId), inp=$(iId);
  // Drag events on the div
  d.addEventListener('dragover', e=>{e.preventDefault();e.stopPropagation();d.classList.add('over')});
  d.addEventListener('dragleave',e=>{e.stopPropagation();d.classList.remove('over')});
  d.addEventListener('drop', e=>{
    e.preventDefault();e.stopPropagation();
    d.classList.remove('over');
    const f=e.dataTransfer.files[0];
    if(f)cb(f);
  });
  // Click on the div (not the input itself) opens file picker
  d.addEventListener('click', e=>{
    if(e.target!==inp) inp.click();
  });
  // File selected via picker
  inp.addEventListener('change', e=>{
    const f=e.target.files[0];
    if(f){cb(f);inp.value='';}   // reset so same file can be reloaded
  });
}
setupDrop('ld-drop','ld-fi',f=>{if(f){const r=new FileReader();r.onload=e=>uploadLD(f.name,e.target.result);r.readAsText(f);}});
setupDrop('elf-drop','elf-fi',f=>{if(f){S.elfFile=f;markDrop('elf-drop','elf-name',f.name);$('echip').style.display='';$('ename').textContent=f.name;$('analyse-btn').disabled=false;$('tool-status').textContent='ELF ready — click Analyse ELF';}});
setupDrop('map-drop','map-fi',f=>{if(f){const r=new FileReader();r.onload=e=>uploadMap(f.name,e.target.result);r.readAsText(f);}});

window.addEventListener('dragover',e=>e.preventDefault());
window.addEventListener('drop',e=>{
  e.preventDefault();
  const f=e.dataTransfer.files[0];if(!f)return;
  const n=f.name.toLowerCase();
  if(n.endsWith('.ld')||n.endsWith('.lds')||n.endsWith('.x')){const r=new FileReader();r.onload=ev=>uploadLD(f.name,ev.target.result);r.readAsText(f);}
  else if(n.endsWith('.map')){const r=new FileReader();r.onload=ev=>uploadMap(f.name,ev.target.result);r.readAsText(f);}
});

function markDrop(dropId,nameId,name){
  $(dropId).classList.add('loaded');
  $(dropId).querySelector('p').textContent=name;
  $(nameId).textContent=name;$(nameId).style.display='';
}

// ═══════════════════════════════════════════════════════════════════════════
// UPLOAD FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════
async function uploadLD(name,text){
  const fd=new FormData();fd.append('content',text);fd.append('filename',name);
  const res=await fetch('/parse_ld',{method:'POST',body:fd});
  const d=await res.json();
  if(d.error){alert('LD parse error:\n'+d.error);return;}
  S.ld=d;
  markDrop('ld-drop','ld-name',name);
  $('fchip').style.display='';$('fname').textContent=name;
  if(d.entry){$('entry-chip').style.display='';$('esym').textContent=d.entry;}
  showApp();rerender();
}

async function uploadMap(name,text){
  const fd=new FormData();fd.append('content',text);fd.append('filename',name);
  const res=await fetch('/parse_map',{method:'POST',body:fd});
  const d=await res.json();
  if(d.error){alert('Map parse error:\n'+d.error);return;}
  S.mapData=d;
  markDrop('map-drop','map-name',name);
  $('mchip').style.display='';$('mname').textContent=name;
  showApp();rerender();
}

async function runAnalysis(){
  if(!S.elfFile){alert('Drop an ELF file first');return;}
  const btn=$('analyse-btn');
  btn.disabled=true;btn.textContent='⏳ Uploading…';
  const prog=$('elf-prog');prog.style.display='';prog.value=0;
  const prefix=$('t-prefix').value.trim();
  const tools={nm:$('t-nm').value.trim(),re:$('t-re').value.trim(),
    size:$('t-sz').value.trim(),a2l:$('t-a2l').value.trim(),prefix};
  const fd=new FormData();
  fd.append('elf',S.elfFile);
  fd.append('tools',JSON.stringify(tools));
  fd.append('ld_data',JSON.stringify(S.ld||{regions:[],sections:[],entry:''}));
  try{
    const d=await new Promise((res,rej)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST','/analyse_elf');
      xhr.upload.onprogress=e=>{if(e.lengthComputable){prog.value=Math.round(e.loaded/e.total*80);$('tool-status').textContent=`Uploading ${Math.round(e.loaded/1024)}KB / ${Math.round(e.total/1024)}KB`;}};
      xhr.onload=()=>{prog.value=100;try{res(JSON.parse(xhr.responseText));}catch(e){rej(new Error('Bad JSON'));}};
      xhr.onerror=()=>rej(new Error('Network error'));
      xhr.send(fd);
    });
    prog.style.display='none';btn.disabled=false;btn.textContent='▶ Analyse ELF';
    if(d.error){$('tool-status').textContent='❌ '+d.error;if(d.debug)populateDebug(d.debug);return;}
    S.syms=d.symbols;S.elfSecs=d.elf_sections;S.warns=d.warnings;S.startup=d.startup;
    $('sym-chip').style.display='';$('symcount').textContent=d.symbols.length;
    $('elf-name').textContent=S.elfFile.name;$('elf-name').style.display='';
    if(d.debug)populateDebug(d.debug);
    const ok=d.symbols.length>0;
    $('tool-status').textContent=ok?`✅ ${d.symbols.length} symbols`:`⚠ 0 symbols — check Debug tab`;
    if(!ok)switchTab('dbg');
    showApp();rerender();
  }catch(e){
    prog.style.display='none';btn.disabled=false;btn.textContent='▶ Analyse ELF';
    $('tool-status').textContent='❌ '+e.message;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// RERENDER — called whenever state changes
// ═══════════════════════════════════════════════════════════════════════════
function rerender(){
  updateFeatureAvailability();
  buildFeaturesPanel();
  enrichSymbolsFromMap();
  if(S.ld||Object.keys(S.elfSecs).length>0) renderMap();
  renderSections();
  renderSymbols();
  renderWarnings();
  renderBloat();
  renderStartup();
  renderMapFile();
  renderDeadCode();
}

// ═══════════════════════════════════════════════════════════════════════════
// ENRICH — cross-reference map data into symbols
// ═══════════════════════════════════════════════════════════════════════════
function enrichSymbolsFromMap(){
  if(!S.mapData||!S.syms.length)return;
  // Build addr→file index from map units
  const addrFile={};
  S.mapData.sections.forEach(sec=>{
    sec.units.forEach(u=>{
      // Map address range → file
      for(let a=u.addr;a<u.addr+u.size;a+=4)addrFile[a]=u.file;
    });
  });
  S.syms.forEach(sym=>{
    if(!sym.file&&addrFile[sym.addr])sym.file=addrFile[sym.addr];
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
const hx=n=>'0x'+n.toString(16).toUpperCase().padStart(8,'0');
function fz(n){if(n>=1048576)return(n/1048576).toFixed(2)+' MB';if(n>=1024)return(n/1024).toFixed(1)+' KB';return n+' B';}
function mkEl(p,tag,attrs){const e=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));p.appendChild(e);return e;}
function svgT(p,text,attrs){const e=mkEl(p,'text',{...attrs,'font-family':'JetBrains Mono,monospace','pointer-events':'none'});e.textContent=text;return e;}
function showApp(){
  $('welcome').style.display='none';
  const a=$('app');
  a.style.setProperty('display','block','important');
}
function toggleSidebar(){const s=$('sidebar');s.style.display=s.style.display==='none'?'':'none';}

function tab(el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('act'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('act'));
  el.classList.add('act');$('pane-'+el.dataset.pane).classList.add('act');
}
function switchTab(name){
  const el=document.querySelector(`.tab[data-pane="${name}"]`);
  if(el){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('act'));
    document.querySelectorAll('.pane').forEach(p=>p.classList.remove('act'));
    el.classList.add('act');$('pane-'+name).classList.add('act');}
}

// ═══════════════════════════════════════════════════════════════════════════
// MEMORY MAP SVG
// ═══════════════════════════════════════════════════════════════════════════
function renderMap(){
  const svg=$('map-svg');svg.innerHTML='';
  const regs=(S.ld?.regions||[]).filter(r=>r.length>0);
  if(!regs.length){
    svgT(svg,'No MEMORY regions (load a .ld file)',{x:10,y:24,fill:'#555','font-size':12});
    svg.setAttribute('width',400);svg.setAttribute('height',36);
    renderRegionTable([]);return;
  }
  const AW=95,BW=196,LW=240,PAD_T=40,PAD_B=28,MIN_H=28,GAP=4;
  const totalLog=regs.reduce((s,r)=>s+Math.log2(Math.max(r.length,256)),0);
  const CH=Math.max(480,regs.length*100);
  const rh=r=>Math.max(MIN_H,(Math.log2(Math.max(r.length,256))/totalLog)*CH);
  const totalH=regs.reduce((s,r)=>s+rh(r)+GAP,0)+PAD_T+PAD_B;
  svg.setAttribute('width',AW+BW+LW);svg.setAttribute('height',totalH);
  svg.setAttribute('viewBox',`0 0 ${AW+BW+LW} ${totalH}`);
  svgT(svg,'ADDRESS',{x:AW/2,y:26,fill:'#6e7681','font-size':9,'text-anchor':'middle','letter-spacing':'0.1em'});
  svgT(svg,'REGION / SECTIONS',{x:AW+BW/2,y:26,fill:'#6e7681','font-size':9,'text-anchor':'middle','letter-spacing':'0.1em'});

  let y=PAD_T;const RTBL=[];
  for(const reg of regs){
    const h=rh(reg);
    const usedBytes=reg.sections.reduce((s,sec)=>s+(S.elfSecs[sec.name]?.size||0),0);
    const usedPct=reg.length>0?Math.min(1,usedBytes/reg.length):0;
    RTBL.push({...reg,usedBytes,usedPct,freeBytes:Math.max(0,reg.length-usedBytes)});

    const rb=mkEl(svg,'rect',{x:AW,y,width:BW,height:h,fill:reg.color,rx:4,
      stroke:'#2a3548','stroke-width':1,cursor:'pointer'});
    rb.addEventListener('click',()=>openRegionPopup(reg,usedBytes,usedPct));
    addTip(rb,{name:reg.name,rows:[
      ['Start',hx(reg.origin)],['End',hx(reg.end)],['Size',fz(reg.length)],
      ['Type',reg.type],['Used',usedBytes?fz(usedBytes)+' ('+Math.round(usedPct*100)+'%)':'load ELF'],
      ['Free',usedBytes?fz(Math.max(0,reg.length-usedBytes)):'—'],
    ],desc:'Click for detailed region view'});

    svgT(svg,hx(reg.origin),{x:AW-5,y:y+12,fill:'#58a6ff','font-size':9,'text-anchor':'end'});
    svgT(svg,hx(reg.end),{x:AW-5,y:y+h,fill:'#3a4450','font-size':9,'text-anchor':'end'});
    mkEl(svg,'line',{x1:AW-4,y1:y,x2:AW,y2:y,stroke:'#444','stroke-width':1});
    mkEl(svg,'line',{x1:AW-4,y1:y+h,x2:AW,y2:y+h,stroke:'#333','stroke-width':1});
    svgT(svg,reg.name,{x:AW+BW+10,y:y+14,fill:'#fff','font-size':12,'font-weight':600,'font-family':'Syne,sans-serif','pointer-events':'none'});
    svgT(svg,fz(reg.length),{x:AW+BW+10,y:y+27,fill:'#6e7681','font-size':10});
    if(usedBytes>0&&feat('f_fillbars')){
      const col=usedPct>0.95?'#f85149':usedPct>0.8?'#d29922':'#3fb950';
      svgT(svg,Math.round(usedPct*100)+'% used',{x:AW+BW+10,y:y+40,fill:col,'font-size':10});
    }

    const secs=reg.sections;
    if(secs.length){
      const sh=Math.max(10,(h-4)/secs.length);
      secs.forEach((sec,i)=>{
        const sy=y+2+i*sh,sH=Math.min(sh,(h-4)-i*sh)-1;
        if(sH<3)return;
        const secSz=S.elfSecs[sec.name]?.size||0;
        // LMA arrow if section has VMA≠LMA
        const isLMA=sec.lma&&feat('f_lmavma');
        const sr=mkEl(svg,'rect',{x:AW+2,y:sy,width:BW-4,height:sH,
          fill:sec.color,rx:2,opacity:isLMA?0.95:0.85,cursor:'pointer'});
        if(isLMA){
          // Small arrow indicator
          mkEl(svg,'text',{x:AW+BW-8,y:sy+sH/2+4,fill:'#fff','font-size':8,
            'text-anchor':'end','pointer-events':'none'}).textContent='↗';
        }
        sr.addEventListener('click',()=>openSectionPopup(sec));
        // Largest symbol in hover
        let tipDesc=sec.desc;
        if(feat('f_symhover')&&S.syms.length){
          const sn=sec.name;
          const largest=S.syms.filter(s=>s.section===sn&&s.size>0).sort((a,b)=>b.size-a.size)[0];
          if(largest)tipDesc=`Largest: ${largest.name} (${fz(largest.size)}). ${sec.desc}`;
        }
        addTip(sr,{name:sec.name,rows:[
          ['Type',sec.type],['→ VMA',sec.vma||'—'],
          ['← LMA',sec.lma||'—'],['NOLOAD',sec.noload?'Yes':'No'],
          ['Size',secSz?fz(secSz):'load ELF'],
        ],desc:tipDesc+' — click for details'});
        if(sH>14)svgT(svg,sec.name,{x:AW+7,y:sy+sH/2+4,fill:'#fff','font-size':Math.min(10,sH-2)});
      });
    }
    y+=h+GAP;
  }

  // Legend
  const leg=$('leg');leg.innerHTML='';
  const seen=new Set();
  (S.ld?.sections||[]).forEach(s=>{if(seen.has(s.type))return;seen.add(s.type);
    const d=document.createElement('div');d.className='li';
    d.innerHTML=`<div class="ld2" style="background:${s.color}"></div>${s.type}`;leg.appendChild(d);});

  renderRegionTable(RTBL);
}

function renderRegionTable(rtbl){
  const rtb=$('rtb');rtb.innerHTML='';
  rtbl.forEach(r=>{
    const p=r.usedPct,col=p>0.95?'#f85149':p>0.8?'#d29922':'#3fb950';
    const bar=r.usedBytes&&feat('f_fillbars')?`<div class="fill-bg" style="width:80px"><div class="fill-bar" style="width:${Math.round(p*78)}px;background:${col}"></div></div>`:'—';
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`<td><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${r.color};margin-right:6px;vertical-align:middle"></span>${r.name}</td>
      <td class="hx">${hx(r.origin)}</td><td class="hx">${hx(r.end)}</td>
      <td class="sz">${fz(r.length)}</td><td class="dim">${r.type}</td>
      <td>${r.usedBytes?fz(r.usedBytes):'—'}</td><td>${r.usedBytes?fz(r.freeBytes):'—'}</td>
      <td>${bar}</td>
      <td style="max-width:200px">${r.sections.map(s=>`<span style="color:${s.color};font-size:10px;cursor:pointer;margin-right:4px" data-sec-name="${s.name}">${s.name}</span>`).join('')}</td>`;
    tr.addEventListener('click', e=>{
      const secName=e.target.dataset.secName;
      if(secName){e.stopPropagation();const sec=findSection(secName);if(sec)openSectionPopup(sec);return;}
      openRegionPopup(r,r.usedBytes,r.usedPct);
    });
    rtb.appendChild(tr);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SECTIONS
// ═══════════════════════════════════════════════════════════════════════════
function renderSections(){
  const secs=S.ld?.sections||[];
  // Populate type filter
  const tf=$('sec-type');const prev=tf.value;
  tf.innerHTML='<option value="">All types</option>';
  [...new Set(secs.map(s=>s.type))].sort().forEach(t=>{
    const o=document.createElement('option');o.value=t;o.textContent=t;tf.appendChild(o);
  });
  tf.value=prev;
  filterSecs();
}
function filterSecs(){
  const q=($('sec-q')?.value||'').toLowerCase();
  const t=$('sec-type')?.value||'';
  const secs=(S.ld?.sections||[]).filter(s=>{
    if(q&&!s.name.toLowerCase().includes(q))return false;
    if(t&&s.type!==t)return false;
    return true;
  });
  $('sec-cnt').textContent=`${secs.length} sections`;
  const g=$('sec-grid');g.innerHTML='';
  secs.forEach(s=>{
    const elfSec=S.elfSecs[s.name];
    const sz=elfSec?.size||0;
    const mapSec=S.mapData?.sections.find(ms=>ms.name===s.name);
    const contribCount=mapSec?.units.length||0;
    const d=document.createElement('div');d.className='sec-card';
    d.innerHTML=`
      <div class="sc-dot" style="background:${s.color}"></div>
      <div style="flex:1;min-width:0">
        <div class="sc-name">${s.name}
          ${s.noload?'<span class="badge nb">NOLOAD</span>':''}
          ${s.vma?`<span class="badge vb">→ ${s.vma}</span>`:''}
          ${s.lma?`<span class="badge">LMA:${s.lma}</span>`:''}
          ${s.dma_safe?'<span class="badge gb">DMA-safe</span>':''}
          ${s.cacheable?'<span class="badge cb">cached</span>':''}
        </div>
        <div class="sc-type">${s.type}</div>
        <div class="sc-desc">${s.desc}</div>
        ${sz&&feat('f_secsize')?`<div class="sc-size">${fz(sz)}</div>`:''}
        ${contribCount&&feat('f_seccontrib')?`<div style="font-size:10px;color:var(--dim);margin-top:3px">${contribCount} contributor${contribCount>1?'s':''}</div>`:''}
        ${elfSec&&feat('f_secflags')?`<div class="tag-row"><span class="tag">${elfSec.flags||'no flags'}</span><span class="tag">${elfSec.type}</span></div>`:''}
      </div>`;
    d.addEventListener('click',()=>openSectionPopup(s));
    g.appendChild(d);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SYMBOLS
// ═══════════════════════════════════════════════════════════════════════════
const TCOL={function:'#3b82f6',variable:'#f97316',constant:'#10b981',
  weak:'#6366f1',undefined:'#6e7681',absolute:'#f59e0b',other:'#374151'};

function renderSymbols(){
  if(!S.syms.length){$('sym-empty').style.display='';$('sym-content').style.display='none';return;}
  $('sym-empty').style.display='none';$('sym-content').style.display='';
  // Populate filters
  const ss=$('sym-s');ss.innerHTML='<option value="">All sections</option>';
  [...new Set(S.syms.map(s=>s.section).filter(Boolean))].sort()
    .forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;ss.appendChild(o);});
  // File filter from map
  const sf=$('sym-f');sf.innerHTML='<option value="">All files</option>';
  if(feat('f_symfilt')){
    [...new Set(S.syms.map(s=>s.file).filter(Boolean))].sort()
      .forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;sf.appendChild(o);});
  }
  filterSyms();
}
function filterSyms(){
  const q=($('sym-q')?.value||'').toLowerCase();
  const t=$('sym-t')?.value||'';
  const sec=$('sym-s')?.value||'';
  const fil=$('sym-f')?.value||'';
  const g=$('sym-g')?.value||'';
  S.fSyms=S.syms.filter(s=>{
    if(q&&!s.name.toLowerCase().includes(q))return false;
    if(t&&s.type!==t)return false;
    if(sec&&s.section!==sec)return false;
    if(fil&&s.file!==fil)return false;
    if(g==='1'&&!s.global)return false;
    if(g==='0'&&s.global)return false;
    return true;
  });
  sortAndRenderSyms();
}
function sortSym(col){
  if(S.symSort===col)S.symDir*=-1;else{S.symSort=col;S.symDir=-1;}
  document.querySelectorAll('#sym-tbl th').forEach((th,i)=>{
    th.classList.remove('sa','sd');
    if(['name','addr','size','type','section','file'][i]===col)th.classList.add(S.symDir>0?'sa':'sd');
  });
  sortAndRenderSyms();
}
function sortAndRenderSyms(){
  const {symSort:col,symDir:dir}=S;
  const sorted=[...S.fSyms].sort((a,b)=>{
    const va=a[col]??'',vb=b[col]??'';
    return(typeof va==='number'?va-vb:va.toString().localeCompare(vb.toString()))*dir;
  });
  $('sym-cnt').textContent=`${sorted.length} / ${S.syms.length}`;
  const tbody=$('sym-body');tbody.innerHTML='';
  sorted.slice(0,3000).forEach(s=>{
    const c=TCOL[s.type]||TCOL.other;
    // Weak highlighting
    const nameStyle=feat('f_symweak')&&s.type==='weak'?'color:#bc8cff':s.global?'color:#fff':'color:#8b949e';
    const tr=document.createElement('tr');tr.className='clickable';
    const fileCell=feat('f_symprov')&&s.file?s.file:'—';
    tr.innerHTML=`
      <td style="${nameStyle};font-size:11px" title="${s.name}">${s.name}</td>
      <td class="hx">${hx(s.addr)}</td>
      <td class="sz">${s.size?fz(s.size):'—'}</td>
      <td><span class="tb" style="color:${c};border-color:${c}33;background:${c}11">${s.type}</span></td>
      <td class="dim">${s.section||'—'}</td>
      <td class="dim" style="font-size:10px" title="${s.file||''}">${fileCell}</td>`;
    tr.addEventListener('click',()=>openSymbolPopup(s));
    tbody.appendChild(tr);
  });
  if(sorted.length>3000){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td colspan="6" style="text-align:center;color:var(--dim);padding:10px">${sorted.length-3000} more — refine filter</td>`;
    tbody.appendChild(tr);
  }
}
function exportSymbols(){
  if(!S.syms.length)return;
  const lines=['Name,Address,Size,Type,Section,File'];
  S.fSyms.forEach(s=>lines.push(`"${s.name}","${hx(s.addr)}","${s.size}","${s.type}","${s.section||''}","${s.file||''}"`));
  download('symbols.csv',lines.join('\n'));
}

// ═══════════════════════════════════════════════════════════════════════════
// WARNINGS
// ═══════════════════════════════════════════════════════════════════════════
function renderWarnings(){
  // Generate extra warnings based on enabled features
  const extra=[];
  if(feat('f_wprintf')&&S.syms.length){
    const printfSyms=S.syms.filter(s=>['printf','fprintf','sprintf','snprintf','vprintf','puts'].some(p=>s.name===p||s.name.endsWith('_'+p)));
    if(printfSyms.length)extra.push({level:'warn',category:'Printf/malloc',
      message:`printf family detected: ${printfSyms.map(s=>s.name).join(', ')}`,
      detail:'printf brings in ~40KB of formatting code. Consider lighter alternatives (itoa, custom print) for embedded.',
      symbols:printfSyms});
    const mallocSym=S.syms.filter(s=>['malloc','free','calloc','realloc','_malloc_r'].includes(s.name));
    if(mallocSym.length)extra.push({level:'info',category:'Dynamic Memory',
      message:`Dynamic memory allocator linked: ${mallocSym.map(s=>s.name).join(', ')}`,
      detail:'malloc/free can cause fragmentation and non-deterministic timing. Consider static allocation in ASIL-B context.',
      symbols:mallocSym});
  }
  if(feat('f_woverlap')&&S.ld&&Object.keys(S.elfSecs).length){
    const ranges=[];
    S.ld.regions.forEach(r=>{
      if(r.length>0)ranges.push({name:r.name,start:r.origin,end:r.end});
    });
    for(let i=0;i<ranges.length;i++)for(let j=i+1;j<ranges.length;j++){
      if(ranges[i].start<ranges[j].end&&ranges[j].start<ranges[i].end)
        extra.push({level:'error',category:'Region Overlap',
          message:`Regions ${ranges[i].name} and ${ranges[j].name} overlap!`,
          detail:`${ranges[i].name}: ${hx(ranges[i].start)}–${hx(ranges[i].end)} | ${ranges[j].name}: ${hx(ranges[j].start)}–${hx(ranges[j].end)}`});
    }
  }
  if(feat('f_wunplaced')&&S.ld&&S.syms.length){
    const allRanges=[];
    S.ld.regions.forEach(r=>{if(r.length>0)allRanges.push([r.origin,r.end]);});
    const orphans=S.syms.filter(s=>s.addr>0&&s.type!=='undefined'&&s.size>0&&
      !allRanges.some(([a,b])=>s.addr>=a&&s.addr<b));
    if(orphans.length)extra.push({level:'warn',category:'Unplaced Symbols',
      message:`${orphans.length} symbol(s) outside all memory regions`,
      detail:'These symbols have addresses that fall outside the linker script MEMORY map. Possible orphan section or missing region.',
      symbols:orphans.slice(0,20)});
  }

  S.allWarns=[...(S.warns||[]),...extra];
  // Populate category filter
  const cats=[...new Set(S.allWarns.map(w=>w.category))].sort();
  const wc=$('warn-cat');const prev=wc.value;
  wc.innerHTML='<option value="">All categories</option>';
  cats.forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;wc.appendChild(o);});
  wc.value=prev;
  const badge=$('warn-badge');
  const errCount=S.allWarns.filter(w=>w.level==='error').length;
  badge.textContent=errCount||S.allWarns.length;
  badge.style.display=S.allWarns.length?'':'none';
  badge.style.background=errCount?'var(--red)':'var(--ora)';
  filterWarns();
}
function filterWarns(){
  const lvl=$('warn-lvl').value,cat=$('warn-cat').value;
  const filtered=S.allWarns.filter(w=>{
    if(lvl&&w.level!==lvl)return false;
    if(cat&&w.category!==cat)return false;
    return true;
  });
  $('warn-cnt').textContent=`${filtered.length} of ${S.allWarns.length}`;
  const ICONS={error:'🔴',warn:'🟡',info:'🔵'};
  const wl=$('warn-list');wl.innerHTML='';
  if(!filtered.length){
    wl.innerHTML='<div class="empty"><div class="eico">✅</div><h3>No warnings match filter</h3></div>';return;
  }
  filtered.forEach(w=>{
    const d=document.createElement('div');d.className=`wcard ${w.level}`;
    d.innerHTML=`<div class="wico">${ICONS[w.level]||'ℹ'}</div>
      <div style="flex:1"><div class="wcat">${w.category}</div>
      <div class="wtitle">${w.message}</div>
      <div class="wdet">${w.detail}</div></div>`;
    d.addEventListener('click',()=>openWarningPopup(w));
    wl.appendChild(d);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// BLOAT
// ═══════════════════════════════════════════════════════════════════════════
function renderBloat(){
  const hasSym=S.syms.length>0,hasMap=!!S.mapData;
  if(!hasSym&&!hasMap){$('bloat-empty').style.display='';$('bloat-content').style.display='none';return;}
  $('bloat-empty').style.display='none';$('bloat-content').style.display='';
  // Stats
  const fns=S.syms.filter(s=>s.type==='function'&&s.size>0).sort((a,b)=>b.size-a.size);
  const vars=S.syms.filter(s=>s.type==='variable'&&s.size>0).sort((a,b)=>b.size-a.size);
  const totalCode=fns.reduce((s,f)=>s+f.size,0);
  const totalData=vars.reduce((s,v)=>s+v.size,0);
  $('bloat-stats').innerHTML=`
    <div class="stat"><div class="snum">${fz(totalCode)}</div><div class="slbl">Total code (functions)</div></div>
    <div class="stat"><div class="snum" style="color:var(--ora)">${fz(totalData)}</div><div class="slbl">Total data (variables)</div></div>
    <div class="stat"><div class="snum" style="color:var(--pur)">${fns.length}</div><div class="slbl">Functions</div></div>
    <div class="stat"><div class="snum" style="color:var(--red)">${vars.length}</div><div class="slbl">Variables</div></div>`;

  // Treemap from map file
  if(hasMap&&feat('f_bloattree')){
    $('bloat-treemap-wrap').style.display='';
    renderTreemap('bloat-treemap',S.mapData.summary.by_file,'flash');
  } else $('bloat-treemap-wrap').style.display='none';

  // Functions table
  if(feat('f_bloatfn'))renderBloatTable('bloat-fn',fns.slice(0,50),['name','size','section','file']);
  // Variables table
  if(feat('f_bloatvar'))renderBloatTable('bloat-var',vars.slice(0,50),['name','size','section','file']);

  // Duplicates
  if(feat('f_bloatdup')&&S.syms.length){
    const byName={};
    S.syms.filter(s=>s.type==='function').forEach(s=>{
      if(!byName[s.name])byName[s.name]=[];
      byName[s.name].push(s);
    });
    const dups=Object.entries(byName).filter(([,v])=>v.length>1).sort((a,b)=>b[1].length-a[1].length);
    const dc=$('dup-card');dc.style.display=dups.length?'':'none';
    const db=$('bloat-dup');db.innerHTML='';
    dups.slice(0,30).forEach(([name,syms])=>{
      const tr=document.createElement('tr');tr.className='clickable';
      tr.innerHTML=`<td style="color:var(--acc);font-size:11px">${name}</td>
        <td class="sz">${syms.length}</td>
        <td class="dim" style="font-size:10px">${[...new Set(syms.map(s=>s.file).filter(Boolean))].join(', ')||'—'}</td>`;
      tr.addEventListener('click',()=>openDuplicatePopup(name,syms));
      db.appendChild(tr);
    });
  }
}
function renderBloatTable(tbodyId,syms,cols){
  const tbody=$(tbodyId);tbody.innerHTML='';
  syms.forEach((s,i)=>{
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`<td style="font-size:11px;color:#fff" title="${s.name}">${s.name}</td>
      <td class="sz">${fz(s.size)}</td>
      <td class="dim">${s.section||'—'}</td>
      <td class="dim" style="font-size:10px">${s.file||'—'}</td>`;
    tr.addEventListener('click',()=>openSymbolPopup(s));
    tbody.appendChild(tr);
  });
}
function sortBloat(table,col){/* simplified — re-render with new sort */}

function renderTreemap(containerId,data,sizeKey){
  const container=$(containerId);container.innerHTML='';
  if(!data.length)return;
  const total=data.reduce((s,r)=>s+r[sizeKey],0);
  if(!total)return;
  const maxW=container.offsetWidth||600;
  const COLORS=['#3b82f6','#f97316','#10b981','#8b5cf6','#f59e0b','#ef4444','#06b6d4','#ec4899','#84cc16','#6366f1'];
  data.slice(0,40).forEach((r,i)=>{
    if(!r[sizeKey])return;
    const pct=r[sizeKey]/total;
    const w=Math.max(40,pct*maxW*0.9);
    const h=Math.max(32,Math.min(80,pct*600));
    const cell=document.createElement('div');
    cell.className='tree-cell';
    cell.style.cssText=`width:${w}px;height:${h}px;background:${COLORS[i%COLORS.length]}22;
      border:1px solid ${COLORS[i%COLORS.length]}66;`;
    cell.innerHTML=`<div><div class="tc-name">${r.file}</div><div class="tc-size">${fz(r[sizeKey])}</div></div>`;
    cell.addEventListener('click',()=>{$('sym-f').value=r.file;filterSyms();switchTab('sym');});
    addTip(cell,{name:r.file,rows:[['Flash',fz(r.flash)],['RAM',fz(r.ram)],['Total',fz(r.total)]],desc:'Click to filter symbols by this file'});
    container.appendChild(cell);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// STARTUP
// ═══════════════════════════════════════════════════════════════════════════
function renderStartup(){
  const ss=$('start-stats'),sr=$('start-rows');ss.innerHTML='';sr.innerHTML='';
  if(!S.startup){
    ss.innerHTML='<div class="stat"><div class="snum" style="color:#6e7681">?</div><div class="slbl">Load ELF for exact figures</div></div>';return;
  }
  const {total_copy,total_zero,items}=S.startup;
  ss.innerHTML=`
    <div class="stat"><div class="snum">${fz(total_copy)}</div><div class="slbl">Copied flash→RAM<br>larger = slower boot</div></div>
    <div class="stat"><div class="snum" style="color:var(--grn)">${fz(total_zero)}</div><div class="slbl">Zeroed (BSS)<br>fast memset</div></div>`;
  items.forEach(it=>{
    const contrib=S.mapData?.sections.find(s=>s.name===it.section);
    const d=document.createElement('div');d.className='sr';
    d.innerHTML=`<span class="stype ${it.type}">${it.type}</span>
      <span style="color:#fff;flex:1;font-size:12px">${it.section}</span>
      <span class="sz">${fz(it.size)}</span>
      ${it.vma?`<span class="dim" style="font-size:11px">${it.vma}</span>`:''}
      ${it.lma?`<span class="dim" style="font-size:11px">← ${it.lma}</span>`:''}
      ${contrib&&feat('f_startfile')?`<span style="font-size:10px;color:var(--dim)">${contrib.units.length} files</span>`:''}`;
    d.addEventListener('click',()=>{if(contrib)openSectionContribPopup(it.section,contrib.units);});
    sr.appendChild(d);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// MAP FILE TAB
// ═══════════════════════════════════════════════════════════════════════════
function renderMapFile(){
  if(!S.mapData){$('map2-empty').style.display='';$('map2-content').style.display='none';return;}
  $('map2-empty').style.display='none';$('map2-content').style.display='';
  const {total_flash,total_ram,by_file}=S.mapData.summary;
  $('map2-stats').innerHTML=`
    <div class="stat"><div class="snum">${fz(total_flash)}</div><div class="slbl">Total flash usage</div></div>
    <div class="stat"><div class="snum" style="color:var(--ora)">${fz(total_ram)}</div><div class="slbl">Total RAM usage</div></div>
    <div class="stat"><div class="snum" style="color:var(--pur)">${by_file.length}</div><div class="slbl">Object files</div></div>
    <div class="stat"><div class="snum" style="color:var(--dim)">${S.mapData.discarded.length}</div><div class="slbl">GC'd sections</div></div>`;

  // Library filter
  if(feat('f_maplib')){
    const libs=[...new Set(by_file.map(r=>{const m=r.file.match(/([^/\\]+\.a)\(/);return m?m[1]:null;}).filter(Boolean))].sort();
    const ml=$('map2-lib');ml.innerHTML='<option value="">All libraries</option>';
    libs.forEach(l=>{const o=document.createElement('option');o.value=l;o.textContent=l;ml.appendChild(o);});
  }

  filterMapFiles();
  renderSectionContribs();
  renderDiscarded();
}
function filterMapFiles(){
  const q=($('map2-q')?.value||'').toLowerCase();
  const lib=$('map2-lib')?.value||'';
  const rows=(S.mapData?.summary.by_file||[]).filter(r=>{
    if(q&&!r.file.toLowerCase().includes(q))return false;
    if(lib&&!r.file.includes(lib))return false;
    return true;
  });
  $('map2-cnt').textContent=`${rows.length} files`;
  renderMapTable(rows);
}
let mapSortCol='total',mapSortDir=-1;
function sortMap(col){if(mapSortCol===col)mapSortDir*=-1;else{mapSortCol=col;mapSortDir=-1;}filterMapFiles();}
function renderMapTable(rows){
  const maxFlash=Math.max(...rows.map(r=>r.flash),1);
  const sorted=[...rows].sort((a,b)=>(typeof a[mapSortCol]==='number'?a[mapSortCol]-b[mapSortCol]:a[mapSortCol].localeCompare(b[mapSortCol]))*mapSortDir);
  const tbody=$('map2-tbody');tbody.innerHTML='';
  sorted.forEach(r=>{
    const barW=Math.round((r.flash/maxFlash)*100);
    // Region colour if feature enabled
    let rowColor='';
    if(feat('f_mapregion')&&S.ld){
      const addr=S.mapData?.sections.flatMap(s=>s.units).find(u=>u.file===r.file)?.addr||0;
      const reg=S.ld.regions.find(rg=>addr>=rg.origin&&addr<rg.end);
      if(reg)rowColor=`border-left:3px solid ${reg.color}`;
    }
    // DMA hazard
    let dmaBadge='';
    if(feat('f_mapdma')&&S.ld){
      const fileUnits=(S.mapData?.sections||[]).flatMap(s=>s.units.filter(u=>u.file===r.file));
      const inCached=fileUnits.some(u=>S.ld.sections.find(s=>s.name===u.subsection?.split('.').slice(0,2).join('.')&&s.cacheable));
      const inNC=fileUnits.some(u=>S.ld.sections.find(s=>s.name===u.subsection?.split('.').slice(0,2).join('.')&&s.dma_safe));
      if(inCached&&inNC)dmaBadge='<span class="badge cb" style="margin-left:4px">⚠ DMA</span>';
    }
    // Symbol count if cross-referenced
    const symCount=feat('f_mapsym')?S.syms.filter(s=>s.file===r.file).length:0;
    const tr=document.createElement('tr');tr.className='clickable';
    tr.style=rowColor;
    tr.innerHTML=`
      <td style="font-size:11px;color:#fff;max-width:240px" title="${r.file}">${r.file}${dmaBadge}</td>
      <td class="sz">${r.flash?fz(r.flash):'—'}</td>
      <td style="color:var(--ora)">${r.ram?fz(r.ram):'—'}</td>
      <td class="dim">${fz(r.total)}</td>
      <td><div class="fill-bg" style="width:100px"><div class="fill-bar" style="width:${barW}px;background:#3b82f6"></div></div></td>
      <td class="dim">${symCount||'—'}</td>`;
    tr.addEventListener('click',()=>openFilePopup(r));
    tbody.appendChild(tr);
  });
}
function renderSectionContribs(){
  const tbody=$('sec-contrib-body');tbody.innerHTML='';
  (S.mapData?.sections||[]).forEach(sec=>{
    if(!sec.units.length)return;
    const top=sec.units.slice().sort((a,b)=>b.size-a.size).slice(0,3);
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`
      <td style="color:var(--acc);font-size:11px">${sec.name}</td>
      <td class="sz">${fz(sec.size)}</td>
      <td style="font-size:11px;color:var(--dim)">${top.map(u=>`${u.file} (${fz(u.size)})`).join(', ')}</td>`;
    tr.addEventListener('click',()=>openSectionContribPopup(sec.name,sec.units));
    tbody.appendChild(tr);
  });
}
function renderDiscarded(){
  const disc=$('map2-disc');disc.innerHTML='';
  const d=S.mapData?.discarded||[];
  if(!d.length){disc.innerHTML='<tr><td colspan="2" style="color:var(--dim);padding:10px">No discarded sections</td></tr>';return;}
  d.forEach(s=>{
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`<td style="color:#f97316;font-size:11px">${s.name}</td><td class="dim" style="font-size:11px">${s.file}</td>`;
    disc.appendChild(tr);
  });
}
function exportMapCSV(){
  if(!S.mapData)return;
  const lines=['File,Flash,RAM,Total'];
  S.mapData.summary.by_file.forEach(r=>lines.push(`"${r.file}","${r.flash}","${r.ram}","${r.total}"`));
  download('map_breakdown.csv',lines.join('\n'));
}

// ═══════════════════════════════════════════════════════════════════════════
// DEAD CODE
// ═══════════════════════════════════════════════════════════════════════════
function renderDeadCode(){
  if(!S.mapData){$('dead-empty').style.display='';$('dead-content').style.display='none';return;}
  $('dead-empty').style.display='none';$('dead-content').style.display='';
  const disc=S.mapData.discarded||[];
  const byFile={};
  disc.forEach(d=>{if(!byFile[d.file])byFile[d.file]={file:d.file,count:0,size:0,sections:[]};byFile[d.file].count++;byFile[d.file].sections.push(d.name);});
  const rows=Object.values(byFile).sort((a,b)=>b.count-a.count);
  $('dead-stats').innerHTML=`
    <div class="stat"><div class="snum" style="color:var(--red)">${disc.length}</div><div class="slbl">Sections GC'd</div></div>
    <div class="stat"><div class="snum" style="color:var(--grn)">${rows.length}</div><div class="slbl">Files with dead code</div></div>`;
  const tbody=$('dead-tbody');tbody.innerHTML='';
  rows.forEach(r=>{
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`<td style="font-size:11px;color:#fff">${r.file}</td>
      <td class="sz">${r.count}</td><td class="dim">—</td>`;
    tr.addEventListener('click',()=>openDeadFilePopup(r));
    tbody.appendChild(tr);
  });
  filterDead();
}
function filterDead(){
  const q=($('dead-q')?.value||'').toLowerCase();
  const disc=(S.mapData?.discarded||[]).filter(d=>!q||d.name.toLowerCase().includes(q)||d.file.toLowerCase().includes(q));
  const da=$('dead-all');da.innerHTML='';
  disc.forEach(d=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td style="color:#f97316;font-size:11px">${d.name}</td><td class="dim" style="font-size:11px">${d.file}</td>`;
    da.appendChild(tr);
  });
}
function sortDead(col){}

// ═══════════════════════════════════════════════════════════════════════════
// ADDR2LINE
// ═══════════════════════════════════════════════════════════════════════════
async function doA2L(addr){
  const a=addr||$('a2l-addr').value.trim();
  if(!a)return;
  $('a2l-addr').value=a;
  $('a2l-res').textContent='Looking up…';
  if(!S.elfFile){$('a2l-res').textContent='No ELF file loaded';return;}
  const prefix=$('t-prefix').value.trim();
  const fd=new FormData();
  fd.append('addr',a);
  fd.append('prefix',prefix);
  fd.append('a2l_tool',$('t-a2l').value.trim());
  fd.append('elf',S.elfFile);
  const res=await fetch('/addr2line',{method:'POST',body:fd});
  const d=await res.json();
  const result=d.result||d.error||'No result';
  $('a2l-res').textContent=result;
  S.a2lHistory.unshift({addr:a,result});
  if(S.a2lHistory.length>20)S.a2lHistory.pop();
  const hist=$('a2l-history');hist.innerHTML='';
  S.a2lHistory.forEach(h=>{
    const tr=document.createElement('tr');tr.className='clickable';
    tr.innerHTML=`<td class="hx">${h.addr}</td><td style="font-size:11px;color:var(--dim)">${h.result}</td>`;
    tr.addEventListener('click',()=>{$('a2l-addr').value=h.addr;$('a2l-res').textContent=h.result;});
    hist.appendChild(tr);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// DEBUG
// ═══════════════════════════════════════════════════════════════════════════
function populateDebug(dbg){
  let out='';
  if(dbg.prefix_in)out+=`Prefix input:    ${dbg.prefix_in}\nPrefix resolved: ${dbg.prefix_out}\n\n`;
  [['NM',dbg.nm_tool,dbg.nm_ok,dbg.nm_rc,dbg.nm_lines,dbg.nm_stderr,dbg.nm_sample],
   ['READELF',dbg.re_tool,dbg.re_ok,dbg.re_rc,0,dbg.re_stderr,dbg.re_sample],
   ['SIZE',dbg.sz_tool,dbg.sz_ok,dbg.sz_rc,0,dbg.sz_stderr,'']].forEach(([n,t,ok,rc,lines,err,sample])=>{
    out+=`${'═'.repeat(52)}\nTOOL: ${n}\n  Path:    ${t}\n  Found:   ${ok?'✅ YES':'❌ NO — wrong path or not installed'}\n  RC:      ${rc}\n`;
    if(n==='NM')out+=`  Symbols: ${lines} ${lines>0?'✅':'❌'}\n`;
    if(err)out+=`  STDERR:  ${err}\n`;
    if(sample)out+=`\nSAMPLE:\n${sample}\n`;
    out+='\n';
  });
  $('dbg-out').textContent=out;
}
async function runDebug(){
  if(!S.elfFile){$('dbg-out').textContent='Drop an ELF file first';return;}
  $('dbg-out').textContent='Running diagnostics…';
  const prefix=$('t-prefix').value.trim();
  const tools={nm:$('t-nm').value.trim(),re:$('t-re').value.trim(),size:$('t-sz').value.trim(),prefix};
  const fd=new FormData();fd.append('elf',S.elfFile);fd.append('tools',JSON.stringify(tools));
  const res=await fetch('/debug_elf',{method:'POST',body:fd});
  const d=await res.json();
  if(d.error){$('dbg-out').textContent='ERROR: '+d.error;return;}
  let out=`File size: ${(d.file_size/1024).toFixed(1)} KB\nPrefix in:  ${d.prefix_in||'(none)'}\nPrefix out: ${d.prefix_out||'(none)'}\n\n`;
  for(const[n,t] of Object.entries(d.tools||{})){
    out+=`${'═'.repeat(52)}\nTOOL: ${n.toUpperCase()}\n  Path:   ${t.path}\n  Found:  ${t.found?'✅':'❌'}\n  RC:     ${t.rc}\n  Lines:  ${t.lines} ${t.lines>0?'✅':'⚠'}\n`;
    if(t.stderr)out+=`  STDERR: ${t.stderr}\n`;
    if(t.stdout)out+=`\nOUTPUT:\n${t.stdout}\n`;
    out+='\n';
  }
  $('dbg-out').textContent=out;
}

// ═══════════════════════════════════════════════════════════════════════════
// POPUP SYSTEM
// ═══════════════════════════════════════════════════════════════════════════
function openModal(icon,title,subtitle,tabs,panes){
  $('modal-icon').textContent=icon;
  $('modal-title').textContent=title;
  $('modal-subtitle').textContent=subtitle;
  const mt=$('modal-tabs');mt.innerHTML='';
  const mb=$('modal-body');mb.innerHTML='';
  if(tabs.length<=1){
    // No tab bar for single-pane modals
    const p=document.createElement('div');p.className='modal-pane act';p.innerHTML=panes[0];
    mb.appendChild(p);
  } else {
    tabs.forEach((t,i)=>{
      const el=document.createElement('div');el.className='modal-tab'+(i===0?' act':'');
      el.textContent=t;el.onclick=()=>{
        mt.querySelectorAll('.modal-tab').forEach(x=>x.classList.remove('act'));
        mb.querySelectorAll('.modal-pane').forEach(x=>x.classList.remove('act'));
        el.classList.add('act');mb.querySelectorAll('.modal-pane')[i].classList.add('act');
      };
      mt.appendChild(el);
    });
    panes.forEach((html,i)=>{
      const p=document.createElement('div');p.className='modal-pane'+(i===0?' act':'');
      p.innerHTML=html;mb.appendChild(p);
    });
  }
  // Bind addr2line, filter, and sym-click buttons after render
  setTimeout(()=>{
    mb.querySelectorAll('[data-a2l]').forEach(btn=>{
      btn.addEventListener('click',()=>{switchTab('a2l');doA2L(btn.dataset.a2l);closeModalBtn();});
    });
    mb.querySelectorAll('[data-filter-sec]').forEach(btn=>{
      btn.addEventListener('click',()=>{
        $('sym-s').value=btn.dataset.filterSec;
        filterSyms();switchTab('sym');closeModalBtn();
      });
    });
    mb.querySelectorAll('[data-filter-file]').forEach(btn=>{
      btn.addEventListener('click',()=>{
        $('sym-f').value=btn.dataset.filterFile;
        filterSyms();switchTab('sym');closeModalBtn();
      });
    });
  },50);
  $('modal-overlay').classList.add('open');
}
function closeModal(e){if(e.target===$('modal-overlay'))closeModalBtn();}
function closeModalBtn(){$('modal-overlay').classList.remove('open');}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModalBtn();});

// ── Region popup ──────────────────────────────────────────────────────────
function openRegionPopup(reg,usedBytes,usedPct){
  const free=Math.max(0,reg.length-usedBytes);
  const pct=Math.round(usedPct*100);
  const col=usedPct>0.95?'var(--red)':usedPct>0.8?'var(--ora)':'var(--grn)';
  const secRows=reg.sections.map((s,idx)=>{
    const sz=S.elfSecs[s.name]?.size||0;
    return `<tr class="clickable" data-sec-name="${s.name}">
      <td><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${s.color};margin-right:6px"></span>${s.name}</td>
      <td class="dim">${s.type}</td>
      <td class="sz">${sz?fz(sz):'—'}</td>
      <td class="dim">${s.noload?'<span class="badge nb">NOLOAD</span>':''}${s.lma?'<span class="badge vb">LMA</span>':''}</td>
    </tr>`;}).join('');

  const overview=`
    <div class="info-grid">
      <div class="info-card"><div class="info-label">Start address</div><div class="info-value hx">${hx(reg.origin)}</div></div>
      <div class="info-card"><div class="info-label">End address</div><div class="info-value hx">${hx(reg.end)}</div></div>
      <div class="info-card"><div class="info-label">Total size</div><div class="info-value sz">${fz(reg.length)}</div></div>
      <div class="info-card"><div class="info-label">Region type</div><div class="info-value">${reg.type}</div></div>
      ${usedBytes?`<div class="info-card"><div class="info-label">Used</div><div class="info-value" style="color:${col}">${fz(usedBytes)} (${pct}%)</div></div>
      <div class="info-card"><div class="info-label">Free</div><div class="info-value sz">${fz(free)}</div></div>`:''}
    </div>
    ${usedBytes?`<div style="background:var(--s2);border-radius:4px;height:10px;margin-bottom:14px">
      <div style="background:${col};width:${pct}%;height:10px;border-radius:4px;transition:width .5s"></div></div>`:''}
    <div class="card-wrap">
      <div class="tbl-hdr">Sections in this region</div>
      <table><thead><tr><th>Section</th><th>Type</th><th>Size</th><th>Flags</th></tr></thead>
      <tbody>${secRows}</tbody></table>
    </div>`;

  openModal('🗄',reg.name,`${reg.type} · ${hx(reg.origin)} → ${hx(reg.end)}`,['Overview'],[overview]);
  // Bind section row clicks after modal renders
  setTimeout(()=>{
    document.querySelectorAll('#modal-body tr[data-sec-name]').forEach(tr=>{
      tr.addEventListener('click',()=>{const sec=findSection(tr.dataset.secName);if(sec){closeModalBtn();openSectionPopup(sec);}});
    });
  },50);
}

// ── Section popup ─────────────────────────────────────────────────────────
function openSectionPopup(sec){
  const elfSec=S.elfSecs[sec.name];
  const sz=elfSec?.size||0;
  const mapSec=S.mapData?.sections.find(s=>s.name===sec.name);
  const symsInSec=S.syms.filter(s=>s.section===sec.name).sort((a,b)=>b.size-a.size);
  const maxSz=symsInSec[0]?.size||1;

  const overview=`
    <div class="info-grid">
      <div class="info-card"><div class="info-label">Type</div><div class="info-value">${sec.type}</div></div>
      <div class="info-card"><div class="info-label">VMA region</div><div class="info-value">${sec.vma||'—'}</div></div>
      <div class="info-card"><div class="info-label">LMA region</div><div class="info-value">${sec.lma||'—'}</div></div>
      <div class="info-card"><div class="info-label">NOLOAD</div><div class="info-value">${sec.noload?'Yes — not in flash image':'No'}</div></div>
      ${sz?`<div class="info-card"><div class="info-label">Size</div><div class="info-value sz">${fz(sz)}</div></div>`:''}
      ${elfSec?`<div class="info-card"><div class="info-label">ELF flags</div><div class="info-value">${elfSec.flags||'none'} · ${elfSec.type}</div></div>`:''}
    </div>
    <div class="warn-details">${sec.desc}</div>
    <div class="tag-row">
      ${sec.dma_safe?'<span class="tag" style="color:var(--grn);border-color:#1a5c2a">✓ DMA-safe</span>':''}
      ${sec.cacheable?'<span class="tag" style="color:var(--ora);border-color:#5a3010">⚠ Cached</span>':''}
      ${sec.lma?'<span class="tag" style="color:var(--acc)">Copied from flash at startup</span>':''}
    </div>
    ${symsInSec.length?`<button class="hbtn" style="margin-top:12px" data-filter-sec="${sec.name}">🔍 Filter symbols by this section</button>`:''}`;

  // Contributors from map
  const contribHTML=mapSec?.units.length?`
    <div class="section-contributors">
      ${mapSec.units.slice().sort((a,b)=>b.size-a.size).map(u=>`
        <div class="contrib-bar">
          <div class="contrib-name" title="${u.file_full}">${u.file} — ${u.subsection}</div>
          <div class="contrib-row">
            <div class="contrib-fill" style="background:#3b82f688;width:${Math.round(u.size/mapSec.size*260)}px"></div>
            <span class="contrib-sz">${fz(u.size)}</span>
          </div>
        </div>`).join('')}
    </div>`:'<p style="color:var(--dim)">Load a .map file to see contributors</p>';

  // Top symbols
  const symHTML=symsInSec.length?`
    <table class="sym-mini-table">
      <thead><tr><th>Symbol</th><th>Size</th><th>Type</th></tr></thead>
      <tbody>${symsInSec.slice(0,30).map(s=>`
        <tr class="clickable" data-sym-name="${s.name}" data-sym-addr="${s.addr}">
          <td style="color:var(--acc)">${s.name}</td>
          <td class="sz">${s.size?fz(s.size):'—'}</td>
          <td><span class="tb" style="color:${TCOL[s.type]||'#fff'};border-color:${TCOL[s.type]||'#fff'}33">${s.type}</span></td>
        </tr>`).join('')}
      </tbody>
    </table>`:'<p style="color:var(--dim)">Load ELF to see symbols</p>';

  const tabs=['Overview','Contributors','Symbols'];
  const panes=[overview,contribHTML,symHTML];
  openModal(sec.dma_safe?'🔒':'📦',sec.name,`${sec.type} · ${sec.vma||'?'} region`,tabs,panes);
  setTimeout(()=>{
    document.querySelectorAll('#modal-body tr[data-sym-name]').forEach(tr=>{
      tr.addEventListener('click',()=>{
        const sym=findSymbol(tr.dataset.symName,parseInt(tr.dataset.symAddr));
        if(sym){closeModalBtn();openSymbolPopup(sym);}
      });
    });
  },50);
}

// ── Symbol popup ──────────────────────────────────────────────────────────
function openSymbolPopup(sym){
  const isFunc=sym.type==='function';
  const warnMatch=S.allWarns.filter(w=>w.symbols?.some&&w.symbols.some(s=>s.name===sym.name));
  const reg=S.ld?.regions.find(r=>sym.addr>=r.origin&&sym.addr<r.end);
  const sec=S.ld?.sections.find(s=>s.name===sym.section);

  const overview=`
    <div class="info-grid">
      <div class="info-card"><div class="info-label">Address</div><div class="info-value hx">${hx(sym.addr)}</div></div>
      <div class="info-card"><div class="info-label">Size</div><div class="info-value sz">${sym.size?fz(sym.size):'unknown'}</div></div>
      <div class="info-card"><div class="info-label">Type</div><div class="info-value">${sym.type} ${sym.global?'(global)':'(local)'}</div></div>
      <div class="info-card"><div class="info-label">Section</div><div class="info-value">${sym.section||'—'}</div></div>
      ${reg?`<div class="info-card"><div class="info-label">Memory region</div><div class="info-value">${reg.name} (${reg.type})</div></div>`:''}
      ${sec?`<div class="info-card"><div class="info-label">Cacheable</div><div class="info-value">${sec.cacheable?'<span style="color:var(--ora)">Yes — DMA-unsafe</span>':'<span style="color:var(--grn)">No</span>'}</div></div>`:''}
    </div>
    ${sym.file?`<div class="info-card" style="margin-bottom:12px"><div class="info-label">Source file</div><div class="info-value">${sym.file}</div></div>`:''}
    ${warnMatch.length?`<div style="background:#200d0d;border:1px solid #5a1a1a;border-radius:var(--rad);padding:10px 12px;margin-bottom:12px;font-size:11px;color:var(--red)">⚠ ${warnMatch.map(w=>w.message).join('<br>')}</div>`:''}
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="hbtn" data-a2l="${hx(sym.addr)}">📍 Addr→Line</button>
      ${sym.section?`<button class="hbtn" data-filter-sec="${sym.section}">🔍 Section symbols</button>`:''}
      ${sym.file?`<button class="hbtn" data-filter-file="${sym.file}">📂 File symbols</button>`:''}
    </div>`;

  const hexView=`
    <div class="code-block">${sym.name}:\n  Address: ${hx(sym.addr)}\n  Size:    ${sym.size?sym.size+' bytes ('+fz(sym.size)+')':'unknown'}\n  Type:    ${sym.type_raw||sym.type} (${sym.global?'global':'local'})\n  Section: ${sym.section||'?'}\n  File:    ${sym.file||'unknown'}</div>
    ${isFunc?`<p style="color:var(--dim);font-size:12px">To disassemble this function, run:<br>
      <code style="color:var(--acc)">arm-none-eabi-objdump -d --start-address=${hx(sym.addr)} --stop-address=${hx(sym.addr+sym.size)} your.elf</code></p>`:''}`;

  openModal(isFunc?'⚡':'📦',sym.name,`${sym.type} · ${hx(sym.addr)} · ${sym.size?fz(sym.size):'?'}`,
    ['Overview','Details'],[overview,hexView]);
}

// ── Warning popup ─────────────────────────────────────────────────────────
function openWarningPopup(w){
  const ICONS={error:'🔴',warn:'🟡',info:'🔵'};
  const symRows=(w.symbols||[]).slice(0,20).map(s=>`
    <tr class="clickable" data-sym-name="${s.name}" data-sym-addr="${s.addr}">
      <td style="color:var(--acc);font-size:11px">${s.name}</td>
      <td class="hx">${hx(s.addr)}</td>
      <td class="sz">${s.size?fz(s.size):'—'}</td>
    </tr>`).join('');

  const body=`
    <div class="warn-details" style="margin-bottom:12px">${w.detail}</div>
    ${symRows?`<div class="card-wrap"><div class="tbl-hdr">Related symbols</div>
      <table><thead><tr><th>Symbol</th><th>Address</th><th>Size</th></tr></thead>
      <tbody>${symRows}</tbody></table></div>`:''}`;

  openModal(ICONS[w.level]||'ℹ',w.message,w.category,[],[body]);
  setTimeout(()=>{
    document.querySelectorAll('#modal-body tr[data-sym-name]').forEach(tr=>{
      tr.addEventListener('click',()=>{
        const sym=findSymbol(tr.dataset.symName,parseInt(tr.dataset.symAddr));
        if(sym){closeModalBtn();openSymbolPopup(sym);}
      });
    });
  },50);
}

// ── File popup (from map) ─────────────────────────────────────────────────
function openFilePopup(row){
  const fileSections=(S.mapData?.sections||[]).filter(s=>s.units.some(u=>u.file===row.file));
  const fileSyms=S.syms.filter(s=>s.file===row.file).sort((a,b)=>b.size-a.size);

  const overview=`
    <div class="info-grid">
      <div class="info-card"><div class="info-label">Flash</div><div class="info-value sz">${fz(row.flash)}</div></div>
      <div class="info-card"><div class="info-label">RAM</div><div class="info-value" style="color:var(--ora)">${fz(row.ram)}</div></div>
      <div class="info-card"><div class="info-label">Total</div><div class="info-value">${fz(row.total)}</div></div>
      <div class="info-card"><div class="info-label">Sections</div><div class="info-value">${fileSections.length}</div></div>
    </div>
    ${fileSections.map(sec=>{
      const u=sec.units.find(u=>u.file===row.file);
      return u?`<div class="contrib-bar"><div class="contrib-name">${sec.name}</div>
        <div class="contrib-row">
          <div class="contrib-fill" style="background:${u.size>1024?'#ef444488':'#3b82f688'};width:${Math.min(260,u.size/row.total*260)}px"></div>
          <span class="contrib-sz">${fz(u.size)}</span>
        </div></div>`:''}).join('')}
    <div style="margin-top:12px;display:flex;gap:8px">
      <button class="hbtn" data-filter-file="${row.file}">🔍 Filter symbols by file</button>
    </div>`;

  const symHTML=fileSyms.length?`
    <table class="sym-mini-table">
      <thead><tr><th>Symbol</th><th>Size</th><th>Type</th><th>Section</th></tr></thead>
      <tbody>${fileSyms.slice(0,40).map(s=>`
        <tr class="clickable" data-sym-name="${s.name}" data-sym-addr="${s.addr}">
          <td style="color:var(--acc)">${s.name}</td>
          <td class="sz">${s.size?fz(s.size):'—'}</td>
          <td style="color:${TCOL[s.type]||'#fff'}">${s.type}</td>
          <td class="dim">${s.section||'—'}</td>
        </tr>`).join('')}
      </tbody>
    </table>`:'<p style="color:var(--dim)">Load ELF to see symbols from this file</p>';

  openModal('📂',row.file,`Flash: ${fz(row.flash)} · RAM: ${fz(row.ram)}`,['Overview','Symbols'],[overview,symHTML]);
  setTimeout(()=>{
    document.querySelectorAll('#modal-body tr[data-sym-name]').forEach(tr=>{
      tr.addEventListener('click',()=>{
        const sym=findSymbol(tr.dataset.symName,parseInt(tr.dataset.symAddr));
        if(sym){closeModalBtn();openSymbolPopup(sym);}
      });
    });
  },50);
}

// ── Section contributors popup ────────────────────────────────────────────
function openSectionContribPopup(secName,units){
  const sorted=[...units].sort((a,b)=>b.size-a.size);
  const total=units.reduce((s,u)=>s+u.size,0);
  const body=`
    <div style="margin-bottom:14px;color:var(--dim);font-size:12px">Total: <span style="color:var(--grn)">${fz(total)}</span> from ${units.length} object files</div>
    <div class="section-contributors">
      ${sorted.map(u=>`
        <div class="contrib-bar" style="cursor:pointer" onclick="closeModalBtn();$('map2-q').value='${u.file}';filterMapFiles();switchTab('map2')">
          <div class="contrib-name" title="${u.file_full}">${u.file} · <span style="color:var(--dim)">${u.subsection}</span></div>
          <div class="contrib-row">
            <div class="contrib-fill" style="background:#3b82f688;width:${Math.round(u.size/total*280)}px"></div>
            <span class="contrib-sz">${fz(u.size)}</span>
          </div>
        </div>`).join('')}
    </div>`;
  openModal('📂',secName,'Section contributors',[],[body]);
}

// ── Dead code file popup ──────────────────────────────────────────────────
function openDeadFilePopup(r){
  const body=`
    <p style="color:var(--dim);font-size:12px;margin-bottom:12px">${r.count} section(s) GC'd from this file by <code>--gc-sections</code></p>
    <div class="code-block">${r.sections.join('\n')}</div>
    <p style="color:var(--dim);font-size:11px;margin-top:8px">These functions/variables were compiled but never referenced — the linker removed them, saving flash space.</p>`;
  openModal('🗑',r.file,`${r.count} sections removed`,[],[body]);
}

// ── Duplicate symbol popup ────────────────────────────────────────────────
function openDuplicatePopup(name,syms){
  const body=`
    <p style="color:var(--ora);font-size:12px;margin-bottom:12px">Function '${name}' appears in ${syms.length} object files. This may indicate ODR violations or accidental duplication.</p>
    <table class="sym-mini-table">
      <thead><tr><th>Address</th><th>Size</th><th>File</th></tr></thead>
      <tbody>${syms.map(s=>`<tr class="clickable" data-sym-name="${s.name}" data-sym-addr="${s.addr}">
        <td class="hx">${hx(s.addr)}</td>
        <td class="sz">${fz(s.size)}</td>
        <td class="dim">${s.file||'—'}</td></tr>`).join('')}
      </tbody>
    </table>`;
  openModal('⚠',name,`Duplicate in ${syms.length} files`,[],[body]);
  setTimeout(()=>{
    document.querySelectorAll('#modal-body tr[data-sym-name]').forEach(tr=>{
      tr.addEventListener('click',()=>{
        const sym=findSymbol(tr.dataset.symName,parseInt(tr.dataset.symAddr));
        if(sym){closeModalBtn();openSymbolPopup(sym);}
      });
    });
  },50);
}

// ═══════════════════════════════════════════════════════════════════════════
// LOOKUP HELPERS — safe alternatives to JSON-in-HTML
// ═══════════════════════════════════════════════════════════════════════════
function findSection(name){
  return S.ld?.sections.find(s=>s.name===name)||null;
}
function findSymbol(name,addr){
  return S.syms.find(s=>s.name===name&&s.addr===addr)||S.syms.find(s=>s.name===name)||null;
}

// ═══════════════════════════════════════════════════════════════════════════
// TOOLTIP
// ═══════════════════════════════════════════════════════════════════════════
const tip=$('tip');
function addTip(el,info){
  el.addEventListener('mouseenter',e=>{
    let h=`<div class="tn">${info.name}</div>`;
    (info.rows||[]).forEach(([k,v])=>h+=`<div class="tr2"><span>${k}</span><span class="tv">${v}</span></div>`);
    if(info.desc)h+=`<div class="tdesc">${info.desc}</div>`;
    tip.innerHTML=h;tip.classList.add('on');tipPos(e);
  });
  el.addEventListener('mousemove',tipPos);
  el.addEventListener('mouseleave',()=>tip.classList.remove('on'));
}
function tipPos(e){
  const x=e.clientX+14,y=e.clientY+10;
  const w=tip.offsetWidth||260,h=tip.offsetHeight||100;
  tip.style.left=Math.min(x,innerWidth-w-8)+'px';
  tip.style.top=Math.min(y,innerHeight-h-8)+'px';
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
function download(name,content){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([content],{type:'text/csv'}));
  a.download=name;a.click();
}

// ── Init ──────────────────────────────────────────────────────────────────
loadFeatureState();
buildFeaturesPanel();
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


@app.route('/parse_map', method='POST')
def route_parse_map():
    response.content_type = 'application/json'
    try:
        # Try forms first; if field exceeded MEMFILE_MAX bottle puts it in files
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
