"""Linker script (.ld) parser — GCC/arm-none-eabi format."""
import re

SECTION_HINTS = {
    ".text":                    ("Code",       "Compiled C/C++ functions"),
    ".startup":                 ("Code",       "Reset handler and startup assembly"),
    ".systeminit":              ("Code",       "Clock and core init before main()"),
    ".intc_vector":             ("Vectors",    "Interrupt vector table"),
    ".isr_vector":              ("Vectors",    "STM32 interrupt vector table"),
    ".core_loop":               ("Code",       "Core idle loop"),
    ".init":                    ("Code",       "C runtime .init functions"),
    ".fini":                    ("Code",       "C runtime .fini functions"),
    ".itcm_text":               ("ITCM Code",  "Code in ITCM — zero wait-state"),
    ".acfls_code_rom":          ("Flash Acc",  "Flash driver ROM copy"),
    ".acfls_code_ram":          ("Flash Acc",  "Flash driver running from RAM"),
    ".acmem_43_infls_code_rom": ("Flash Acc",  "Internal flash driver ROM"),
    ".acmem_43_infls_code_ram": ("Flash Acc",  "Internal flash driver RAM"),
    ".rodata":                  ("RO Data",    "Read-only data — const globals, literals"),
    ".mcal_const":              ("RO Data",    "MCAL driver constant configuration"),
    ".mcal_const_cfg":          ("RO Data",    "MCAL generated configuration structures"),
    ".mcal_const_no_cacheable": ("RO Data NC", "MCAL constants in non-cacheable SRAM"),
    ".boot_header":             ("Boot",       "Boot header for ROM bootloader / HSE"),
    ".pflash":                  ("Flash",      "Primary flash — code and read-only data"),
    ".data":                    ("Init Data",  "Initialised globals — copied flash→RAM at boot"),
    ".mcal_data":               ("Init Data",  "MCAL driver initialised state"),
    ".ramcode":                 ("Init Data",  "Code that must execute from RAM"),
    ".dtcm_data":               ("DTCM Data",  "Initialised data in Data TCM"),
    ".mcal_data_no_cacheable":  ("NC Data",    "Driver data in non-cacheable SRAM for DMA"),
    ".non_cacheable_data":      ("NC Data",    "Non-cacheable SRAM — DMA buffers, IPC frames"),
    ".mcal_shared_data":        ("Shared",     "Initialised data shared between cores"),
    ".shareable_data":          ("Shared",     "Shareable memory for multiple cores"),
    ".bss":                     ("BSS",        "Uninitialised globals — zeroed at boot"),
    ".mcal_bss":                ("BSS",        "Uninitialised MCAL driver state"),
    ".dtcm_bss":                ("DTCM BSS",   "Uninitialised data in Data TCM"),
    ".mcal_bss_no_cacheable":   ("NC BSS",     "Uninitialised non-cacheable SRAM"),
    ".non_cacheable_bss":       ("NC BSS",     "Uninitialised non-cacheable SRAM"),
    ".mcal_shared_bss":         ("Shared BSS", "Uninitialised shared memory between cores"),
    ".shareable_bss":           ("Shared BSS", "Uninitialised shareable memory"),
    ".standby_data":            ("Standby",    "Preserved across low-power standby"),
    ".heap":                    ("Heap",       "malloc/free arena"),
    "_user_heap_stack":         ("Heap+Stack", "STM32 CubeMX combined heap+stack"),
    ".stack":                   ("Stack",      "Main stack — overflow causes HardFault"),
    ".int_vector":              ("Vect RAM",   "Vector table in RAM — runtime IRQ remap"),
    ".int_results":             ("Results",    "BIST / test results storage"),
    ".ARM":                     ("ARM Init",   "ARM runtime init/fini arrays"),
    ".preinit_array":           ("Init Array", "Pre-init constructor pointers"),
    ".init_array":              ("Init Array", "Global constructor pointers"),
    ".fini_array":              ("Fini Array", "Global destructor pointers"),
    ".sram_data":               ("Init Data",  "Initialised data placed in SRAM"),
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
    s = s.strip()
    try:
        s2 = re.sub(r'(?i)0x([0-9a-f]+)', lambda m: str(int(m.group(1), 16)), s)
        s2 = re.sub(r'(?i)(\d+)[kK]', lambda m: str(int(m.group(1)) * 1024), s2)
        s2 = re.sub(r'(?i)(\d+)[mM]', lambda m: str(int(m.group(1)) * 1048576), s2)
        return int(eval(s2))
    except Exception:
        return 0


def _strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _classify_region(name, attrs):
    n, a = name.lower(), attrs.lower()
    if 'itcm' in n:                                return 'itcm'
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
            reg = {"name": name, "attrs": attrs, "origin": origin,
                   "length": length, "end": origin + length, "type": rtype,
                   "color": REGION_COLORS.get(rtype, REGION_COLORS["default"]),
                   "sections": [], "used_bytes": 0}
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
            sname  = m.group(1)
            noload = bool(re.search(r'\bNOLOAD\b', m.group(0)))
            vma, lma = m.group(3), m.group(4)
            hint  = next((k for k in SECTION_HINTS if sname.startswith(k)), None)
            stype, sdesc = SECTION_HINTS.get(hint or sname, ("Unknown", "Unknown section"))
            sec = {"name": sname, "vma": vma, "lma": lma, "noload": noload,
                   "type": stype, "desc": sdesc,
                   "dma_safe": sname in DMA_SAFE, "cacheable": sname in CACHEABLE,
                   "color": TYPE_COLORS.get(stype, TYPE_COLORS["Unknown"]),
                   "size": 0, "symbols": []}
            sections.append(sec)
            if vma and vma in reg_map:
                reg_map[vma]["sections"].append(sec)

    entry = ""
    em = re.search(r'ENTRY\s*\((\w+)\)', content)
    if em:
        entry = em.group(1)

    return {"regions": regions, "sections": sections, "entry": entry}
