"""GCC linker .map file parser."""
import re


def parse_map(content):
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    sections  = _parse_sections(content)
    discarded = _parse_discarded(content)
    symbols   = _extract_symbols(sections)
    summary   = _make_summary(sections)
    return {"sections": sections, "symbols": symbols,
            "discarded": discarded, "summary": summary}


def _parse_sections(content):
    sections, current = [], None
    map_start = re.search(r'^Linker script and memory map', content, re.MULTILINE)
    if not map_start:
        map_start = re.search(r'^\.(text|data|bss|rodata)', content, re.MULTILINE)
    start = map_start.start() if map_start else 0

    for line in content[start:].splitlines():
        m = re.match(r'^(\.\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*$', line)
        if m:
            current = {"name": m.group(1), "addr": int(m.group(2),16),
                       "size": int(m.group(3),16), "units": [], "symbols": []}
            sections.append(current)
            continue

        m = re.match(r'^\s+(\.\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)', line)
        if m and current:
            sz = int(m.group(3),16)
            if sz > 0:
                current["units"].append({
                    "subsection": m.group(1), "addr": int(m.group(2),16),
                    "size": sz, "file": _short(m.group(4)),
                    "file_full": m.group(4)})
            continue

        m = re.match(r'^\s+(0x[0-9a-fA-F]{4,})\s+(\S+)\s*$', line)
        if m and current:
            name = m.group(2)
            if not name.startswith('0x') and not name.startswith('.'):
                current["symbols"].append({"name": name, "addr": int(m.group(1),16)})

    return [s for s in sections if s['size'] > 0]


def _parse_discarded(content):
    disc, in_disc = [], False
    for line in content.splitlines():
        if 'Discarded input sections' in line: in_disc = True; continue
        if in_disc:
            if line.strip() == '' and in_disc: continue
            m = re.match(r'\s+(\.\S+)\s+0x\S+\s+0x\S+\s+(\S+)', line)
            if m:
                disc.append({"name": m.group(1), "file": _short(m.group(2)),
                             "file_full": m.group(2)})
            elif line and line[0] not in ' \t': in_disc = False
    return disc


def _extract_symbols(sections):
    syms = []
    for sec in sections:
        for s in sec.get('symbols', []):
            syms.append({"name": s['name'], "addr": s['addr'],
                         "size": 0, "section": sec['name'], "file": ""})
        for u in sec.get('units', []):
            syms.append({"name": u['subsection'], "addr": u['addr'],
                         "size": u['size'], "section": sec['name'], "file": u['file']})
    return syms


def _make_summary(sections):
    FLASH = {'.text','.rodata','.data','.init','.fini','.itcm_text','.pflash'}
    RAM   = {'.data','.bss','.dtcm_data','.dtcm_bss','.non_cacheable_data',
             '.non_cacheable_bss','.sram_data','.sram_bss','.heap','.stack'}
    by_file = {}
    total_flash = total_ram = 0
    for sec in sections:
        is_flash = any(sec['name'].startswith(s) for s in FLASH)
        is_ram   = any(sec['name'].startswith(s) for s in RAM)
        for u in sec.get('units', []):
            f = u['file']
            if f not in by_file:
                by_file[f] = {'file': f, 'flash': 0, 'ram': 0, 'total': 0}
            if is_flash: by_file[f]['flash'] += u['size']; total_flash += u['size']
            if is_ram:   by_file[f]['ram']   += u['size']; total_ram   += u['size']
            by_file[f]['total'] += u['size']
    ranked = sorted(by_file.values(), key=lambda x: -x['total'])
    return {"total_flash": total_flash, "total_ram": total_ram, "by_file": ranked[:80]}


def _short(p):
    p = p.replace('\\', '/')
    parts = [x for x in p.split('/') if x]
    return '/'.join(parts[-2:]) if len(parts) > 2 else p
