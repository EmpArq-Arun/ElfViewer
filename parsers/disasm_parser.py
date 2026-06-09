"""
disasm_parser.py  —  arm-none-eabi-objdump wrapper + fault analyser
====================================================================

OPERATION MODES (what files are needed):

    ELF only (minimum):
        • Function boundary detection (from symbol table in ELF)
        • Full disassembly of the function
        • Instruction highlighting at crash address
        • Fault pattern analysis
        • addr2line source file:line (if ELF has DWARF debug sections)

    ELF + built with -g (recommended):
        • Everything above PLUS
        • C source lines interleaved with instructions
        • Exact source line of the crash highlighted

    ELF + .o files (future):
        • Per-object-file contribution already shown in Map tab
        • Disassembly is always from the linked ELF — .o not needed here

ARM THUMB-2 ADDRESS ALIGNMENT:
    Cortex-M processors always run in Thumb state.
    Instructions are either 16-bit (2 bytes) or 32-bit (4 bytes).
    A crash PC or BFAR may NOT be instruction-aligned:
    - On a data access fault (BusFault/MemManage), BFAR holds the DATA
      ADDRESS, not the instruction address. Use PC from the stack frame.
    - LR on entry to a fault handler has bit 0 set (Thumb mode indicator).
      Strip it: real_addr = LR & ~1
    - If the address falls between two instruction addresses in the listing,
      we find the instruction IMMEDIATELY BEFORE (address ≤ target).

PROCESSOR ALIGNMENT RULES:
    Cortex-M0/M0+:  Thumb only, all instructions 16-bit (2-byte aligned)
    Cortex-M3:      Thumb-2,   instructions 16 or 32-bit (2-byte aligned)
    Cortex-M4/M7:   Thumb-2,   instructions 16 or 32-bit (2-byte aligned)
    Cortex-M33:     Thumb-2,   instructions 16 or 32-bit (2-byte aligned)

    All ARM Cortex-M processors align instructions to 2-byte boundaries.
    Addresses with bit 0 set are NEVER instruction addresses (bit 0 = Thumb
    mode flag in BX/BLX operands only).

    Algorithm for finding the instruction at a given address:
        1. Strip bit 0:  addr = addr & ~1
        2. Look for exact match in the disassembly listing
        3. If not found, take the instruction with the highest address ≤ addr
           (this handles mid-instruction addresses from BFAR)

OBJDUMP -S OUTPUT FORMAT (arm-none-eabi-objdump 11.x):

    The output interleaves C source with assembly when -g is present:

        00401234 <BswSpi_Exchange>:
        BswSpi_Exchange():
        ../src/Bsw/Bsw_Spi.c:120
          uint32_t timeout = 100;
           401234:    2064          movs  r0, #100
           401236:    9001          str   r0, [sp, #4]

        ../src/Bsw/Bsw_Spi.c:122
          if (pDev->pRxBuf != NULL) {
           401238:    6878          ldr   r0, [r7, #4]
           40123a:    6803          ldr   r3, [r0, #0]

    WITHOUT -g:
        00401234 <BswSpi_Exchange>:
           401234:    2064          movs  r0, #100
           401236:    9001          str   r0, [sp, #4]

    Source lines appear as PLAIN TEXT (no // prefix) between instruction
    blocks.  They can be:
        - File/line markers:  "../src/file.c:122"
        - Function signature: "BswSpi_Exchange():"
        - C code:             "  if (ptr != NULL) {"

EMBEDDED ENGINEER NOTES:
    To get source interleaving, build with -g or -g3:
        arm-none-eabi-gcc -g3 -O0 ...    ← best for debugging
        arm-none-eabi-gcc -g  -O2 ...    ← production debug (optimised)
    The -g flag adds DWARF sections to the ELF but does NOT affect the
    generated machine code.  The flasher/bootloader ignores DWARF sections.

    Key crash registers to know:
        PC   = address of instruction that faulted
        LR   = return address (bit 0 set in Thumb, strip it: LR & ~1)
        BFAR = Bus Fault Address Register (data address that caused fault)
        MMFAR= MemManage Fault Address Register
        SP   = Stack Pointer at time of fault
    Enter these in the Address Inspector to see what was executing there.
"""

import re
from typing import Optional


# ---------------------------------------------------------------------------
# ARM instruction categories
# ---------------------------------------------------------------------------

LOAD_INSNS = {
    'ldr','ldrb','ldrh','ldrsb','ldrsh','ldrd','ldm','ldmia','ldmdb',
    'pop','vldr','vldm','vldmia','vldmdb','ldrex','ldrexb','ldrexh',
}
STORE_INSNS = {
    'str','strb','strh','strd','stm','stmia','stmdb',
    'push','vstr','vstm','vstmia','vstmdb','strex','strexb','strexh',
}
BRANCH_INSNS = {
    'b','bl','bx','blx','bxj','cbz','cbnz','tbb','tbh',
    'beq','bne','blt','bgt','ble','bge','bhi','blo','bhs','bls',
    'bcc','bcs','bmi','bpl','bvs','bvc','bal',
}

# All Cortex-M processors align instructions to 2-byte boundaries
THUMB_ALIGNMENT = 2


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def disassemble(
    tmp_path:      str,
    tools:         dict,
    target_addr:   int,
    context_lines: int  = 10,
    func_start:    Optional[int] = None,
    func_end:      Optional[int] = None,
    processor:     str  = 'cortex-m4',   # 'cortex-m0', 'm3', 'm4', 'm7', 'm33'
    source_dir:    Optional[str] = None,  # hint for addr2line source search
) -> dict:
    """
    Disassemble the function containing target_addr and analyse the crash.

    Works with ELF only — no .o or .c files required.
    If the ELF was built with -g, C source lines are automatically
    interleaved from the DWARF debug information inside the ELF itself.

    Parameters
    ----------
    tmp_path      Path to saved ELF (already on disk, closed before this call)
    tools         resolve_tools() dict — needs 'objdump' and 'a2l' keys
    target_addr   Crash address (PC, LR&~1, or BFAR from fault handler)
    context_lines Instructions before/after to show in context view (1–100)
    func_start    Known function start from nm — skips a scan pass
    func_end      Known function end from nm
    processor     Cortex-M variant — affects alignment interpretation
    source_dir    Directory to search for source files (addr2line -d flag)

    Returns dict with keys:
        instructions    list[dict]  — structured instruction+source records
        target_idx      int         — index of the instruction AT target_addr
        target_addr_aligned int     — actual aligned address used
        context_start   int         — first index for context window
        context_end     int         — last  index for context window
        func_name       str
        func_start      int
        func_end        int
        source_file     str
        source_line     int
        target_source_line  int     — C source line number of target instr
        has_source      bool
        fault_analysis  dict|None
        raw_objdump     str         — full raw objdump output (for debug)
        error           str|None
    """
    from parsers.elf_parser import run_tool

    objdump  = tools.get('objdump', 'arm-none-eabi-objdump')
    addr2line = tools.get('a2l',    'arm-none-eabi-addr2line')

    # ── Align the target address ──────────────────────────────────────────
    # Bit 0 is the Thumb mode flag in BX/BLX — strip it for a real address.
    # All Cortex-M instructions are 2-byte aligned.
    target_aligned = target_addr & ~1

    # ── Find function boundaries ──────────────────────────────────────────
    if func_start is None:
        func_start, func_end, func_name = _find_func_bounds(
            tmp_path, objdump, target_aligned)
    else:
        func_name = ''

    if func_start is None:
        # No symbol found — disassemble a fixed window
        func_start = max(0, target_aligned - 0x100)
        func_end   = target_aligned + 0x100
        func_name  = '(unknown — no symbol at this address)'

    if func_end is None or func_end <= func_start:
        func_end = func_start + 0x400

    # ── Run objdump ───────────────────────────────────────────────────────
    # Try with --source first (needs -g in the ELF).
    # Fall back to pure disassembly if source flag causes empty output.
    raw_output = ''
    has_source  = False

    # Build candidate arg lists to try in order of preference:
    #   1. --source with source path prefix (if source_dir given)
    #   2. --source without prefix (works when paths resolve locally)
    #   3. Pure disassembly (always works, no source)
    base_args = [
        objdump, '--disassemble', '--wide',
        f'--start-address={hex(func_start)}',
        f'--stop-address={hex(func_end)}',
        tmp_path
    ]
    candidates = []

    # With source remapping via user-provided directory
    if source_dir:
        # --prefix-strip strips leading path components to make paths relative,
        # then --prefix prepends the user's local source root.
        # We try strip levels 1-5 to handle various build path depths.
        for strip in range(1, 6):
            candidates.append([
                objdump, '--disassemble', '--source', '--wide',
                f'--prefix-strip={strip}',
                f'--prefix={source_dir}',
                f'--start-address={hex(func_start)}',
                f'--stop-address={hex(func_end)}',
                tmp_path
            ])

    # Without remapping (works if built on same machine, or paths are absolute)
    candidates.append([objdump, '--disassemble', '--source', '--wide',
                       f'--start-address={hex(func_start)}',
                       f'--stop-address={hex(func_end)}', tmp_path])

    # Pure disassembly fallback (always produces output)
    candidates.append(base_args)

    raw_output = ''
    for attempt_args in candidates:
        stdout, stderr, rc = run_tool(attempt_args, timeout=60)
        if stdout.strip():
            raw_output = stdout
            break

    if not raw_output.strip():
        raw_output = ''

    if not raw_output.strip():
        return {
            'error': 'objdump produced no output — check toolchain prefix.',
            'instructions': [], 'target_idx': -1,
            'target_addr_aligned': target_aligned,
        }

    # Pull function name from objdump if we didn't have it
    if not func_name or 'unknown' in func_name:
        func_name = _extract_func_name(raw_output) or func_name

    # ── Parse output ─────────────────────────────────────────────────────
    instructions = _parse_objdump(raw_output)

    # has_source = True only if we actually got source_code records,
    # not just because we passed --source (paths may not resolve on this machine)
    has_source = any(r['type'] == 'source_code' for r in instructions)

    # ── Find target instruction ───────────────────────────────────────────
    # Algorithm (handles non-aligned input addresses from BFAR etc.):
    #   1. Strip bit 0 (Thumb flag)
    #   2. Look for exact match
    #   3. If not found, take instruction with highest address ≤ target_aligned
    #      (this is correct for mid-instruction BFAR addresses)
    target_idx = _find_target_instruction(instructions, target_aligned)

    # ── Context window ────────────────────────────────────────────────────
    # The window is defined as: the N instructions before and after the target.
    # We then EXPAND the index range to include all source/loc/sig records
    # that sit between those boundary instructions, so they are always visible.
    insn_indices = [i for i, r in enumerate(instructions) if r['type'] == 'insn']
    context_start, context_end = 0, len(instructions) - 1
    if target_idx >= 0 and insn_indices:
        rank = next((r for r, i in enumerate(insn_indices) if i >= target_idx), 0)
        lo   = insn_indices[max(0, rank - context_lines)]
        hi   = insn_indices[min(len(insn_indices)-1, rank + context_lines)]
        # Walk backward/forward from the boundary instructions to include
        # adjacent source_loc, source_code, func_sig, and blank records.
        # This ensures C source lines interleaved with instructions are never
        # hidden when the instructions they annotate are in the context window.
        context_start = _expand_to_source(instructions, lo, direction=-1)
        context_end   = _expand_to_source(instructions, hi, direction=+1)
        # Final check: also include any source records between context_start
        # and context_end that might have been missed by index arithmetic
        # (they are always inside the range by definition of context_end >= context_start)

    # ── Source line of target instruction ─────────────────────────────────
    # Walk backwards from target_idx to find the most recent source marker
    target_source_line = 0
    if target_idx >= 0:
        for j in range(target_idx, -1, -1):
            r = instructions[j]
            if r['type'] == 'source_loc' and r.get('line'):
                target_source_line = r['line']
                break

    # ── addr2line for exact source location ──────────────────────────────
    source_file, source_line = '', 0
    a2l_args = [addr2line, '-e', tmp_path, '-f', '-C', '-p', hex(target_aligned)]
    if source_dir:
        a2l_args += ['-d', source_dir]
    a2l_out, _, _ = run_tool(a2l_args, timeout=10)
    if a2l_out.strip() and '??' not in a2l_out:
        m = re.search(r'at (.+):(\d+)', a2l_out)
        if m:
            source_file = m.group(1)
            source_line = int(m.group(2))

    # ── Fault analysis ────────────────────────────────────────────────────
    fault_analysis = None
    if target_idx >= 0:
        fault_analysis = _analyse_fault(
            instructions, target_idx, target_aligned, func_start, func_end)

    # ── Direct source file injection ────────────────────────────────────
    # If objdump --source didn't produce C lines (paths didn't resolve),
    # but we have a source_file from addr2line AND a source_dir was given,
    # inject the relevant source lines directly from the file.
    source_lines_map = {}   # line_number → source_code_text
    if not has_source and source_file and source_dir:
        source_lines_map = _read_source_file(source_file, source_dir)
        if source_lines_map:
            instructions = _inject_source_lines(instructions, source_lines_map)
            has_source = True

    return {
        'instructions':         instructions,
        'target_idx':           target_idx,
        'target_addr_aligned':  target_aligned,
        'context_start':        context_start,
        'context_end':          context_end,
        'func_name':            func_name,
        'func_start':           func_start,
        'func_end':             func_end,
        'source_file':          source_file,
        'source_line':          source_line,
        'target_source_line':   target_source_line,
        'has_source':           has_source,
        'fault_analysis':       fault_analysis,
        'raw_objdump':          raw_output[:8000],
        'error':                None,
    }


# ---------------------------------------------------------------------------
# Function boundary detection
# ---------------------------------------------------------------------------

def _find_func_bounds(tmp_path, objdump, target_addr):
    """
    Scan a window around target_addr to find the enclosing function.
    Uses objdump's symbol-annotated output: "004012a0 <FuncName>:"
    """
    from parsers.elf_parser import run_tool

    window_start = max(0, target_addr - 0x1000)
    window_end   = target_addr + 0x1000

    args = [objdump, '--disassemble', '--wide',
            f'--start-address={hex(window_start)}',
            f'--stop-address={hex(window_end)}', tmp_path]
    stdout, _, _ = run_tool(args, timeout=30)

    func_start = func_end = func_name = None

    for m in re.finditer(r'^([0-9a-fA-F]+)\s+<([^>]+)>:', stdout, re.MULTILINE):
        addr = int(m.group(1), 16)
        if addr <= target_addr:
            func_start = addr
            func_name  = m.group(2)
        elif func_start is not None and func_end is None:
            func_end = addr
            break

    return func_start, func_end, func_name


def _extract_func_name(output):
    m = re.search(r'<([^>]+)>:', output)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# objdump output parser
# ---------------------------------------------------------------------------

def _parse_objdump(stdout):
    """
    Parse arm-none-eabi-objdump -d [-S] output into a structured list.

    Record types:
        insn        — an instruction line
        source_code — a C source code line (from -S / DWARF)
        source_loc  — a file:line marker (e.g. "../src/file.c:122")
        func_sig    — function signature line  (e.g. "BswSpi_Exchange():")
        label       — function header (e.g. "004012a0 <BswSpi_Exchange>:")
        blank       — empty line

    Each insn record:
        addr, raw_bytes, mnemonic, operands, is_load, is_store, is_branch

    Each source_loc record:
        file, line   (parsed from "../path/file.c:NNN")

    Each source_code record:
        text         (the C code line)
    """
    records = []
    lines   = stdout.splitlines()
    n       = len(lines)
    i       = 0

    while i < n:
        line = lines[i]

        # ── Function header: "004012a0 <FuncName>:" ───────────────────────
        m = re.match(r'^([0-9a-fA-F]+)\s+<([^>]+)>:\s*$', line.strip())
        if m:
            records.append({
                'type':  'label',
                'addr':  int(m.group(1), 16),
                'text':  line.strip(),
                'name':  m.group(2),
            })
            i += 1
            continue

        # ── Instruction line: "  401234:   b5 30   push  {r4, r5, lr}" ────
        # objdump format: optional leading spaces, hex addr, colon,
        # whitespace, hex bytes (2-char groups), whitespace, mnemonic, operands
        # Two output formats from different objdump versions:
        #   Tab:   "   401234:\t2064      \tmovs\tr0, #100"
        #   Space: "   401234:   b5 30         push   {r4, r5, lr}"
        m = re.match(
            r'^\s*([0-9a-fA-F]+):'
            r'(?:\t([0-9a-fA-F ]+?)\t'
            r'|\s+((?:[0-9a-fA-F]{2}\s)+)\s*)'
            r'([a-zA-Z][a-zA-Z0-9_\.]*)'
            r'(?:[ \t]+(.*))?$',
            line
        )
        if m:
            raw_bytes = (m.group(2) or m.group(3) or '').strip()
            mnem = (m.group(4) or '').lower()
            mnem_base = re.sub(r'\.(w|n|wide|narrow)$', '', mnem)
            ops = (m.group(5) or '').strip()
            ops = re.sub(r'\s*;.*$', '', ops).strip()
            records.append({
                'type':      'insn',
                'addr':      int(m.group(1), 16),
                'raw_bytes': raw_bytes,
                'mnemonic':  mnem_base,
                'operands':  ops,
                'is_load':   mnem_base in LOAD_INSNS,
                'is_store':  mnem_base in STORE_INSNS,
                'is_branch': mnem_base in BRANCH_INSNS,
                'text':      line.rstrip(),
            })
            i += 1
            continue

        stripped = line.strip()

        # ── Source file:line marker: "../src/file.c:122" ──────────────────
        # These appear between instruction blocks when -S is active.
        # They look like a relative or absolute path followed by :number
        m = re.match(r'^(.+\.(c|cpp|cxx|cc|h|hpp|s|asm))(?::(\d+))?(?:$|\s)', stripped)
        if m and not stripped.startswith('Disassembly'):
            file_ = m.group(1)
            line_no = int(m.group(3)) if m.group(3) else 0
            records.append({
                'type': 'source_loc',
                'file': file_,
                'line': line_no,
                'text': stripped,
            })
            i += 1
            continue

        # ── Function signature line: "BswSpi_Exchange():" ─────────────────
        if re.match(r'^\w[\w:~<>*&, ]*\([^)]*\)\s*(?:const\s*)?:', stripped):
            records.append({'type': 'func_sig', 'text': stripped})
            i += 1
            continue

        # ── C source code line ─────────────────────────────────────────────
        # These are non-empty, non-blank lines that don't match any of the
        # above patterns.  They appear after a file:line marker.
        # We only treat a line as source code if the PREVIOUS record was
        # a source_loc or another source_code (to avoid false positives).
        if stripped and not stripped.startswith('Disassembly') \
                    and not stripped.startswith('.') \
                    and records \
                    and records[-1]['type'] in ('source_loc','source_code','func_sig'):
            records.append({'type': 'source_code', 'text': stripped})
            i += 1
            continue

        # ── Blank line or section header ──────────────────────────────────
        if not stripped or stripped.startswith('Disassembly'):
            records.append({'type': 'blank', 'text': ''})
            i += 1
            continue

        # Unrecognised line — skip
        i += 1

    # Second pass: annotate each source_code line with the source_loc line
    # number immediately before it.  This lets the JS highlight the C source
    # line that corresponds to the target instruction.
    current_line = 0
    for rec in records:
        if rec['type'] == 'source_loc' and rec.get('line'):
            current_line = rec['line']
        elif rec['type'] == 'source_code':
            rec['_src_line'] = current_line
        elif rec['type'] == 'insn':
            rec['_src_line'] = current_line   # track which source line each insn belongs to

    return records


# ---------------------------------------------------------------------------
# Target instruction finding (Thumb-2 aware)
# ---------------------------------------------------------------------------

def _find_target_instruction(records, target_aligned):
    """
    Find the instruction at or immediately before target_aligned.

    ARM Thumb-2 rules:
        - All instruction addresses are even (bit 0 = 0)
        - A BFAR/MMFAR may point to a DATA address, not an instruction.
          In that case we highlight the instruction that CAUSED the access.
        - We always take the last instruction with addr <= target_aligned.

    Returns: index into records, or -1 if no instructions found.
    """
    # Step 1: exact match (most common case — PC from stack frame)
    for i, r in enumerate(records):
        if r['type'] == 'insn' and r['addr'] == target_aligned:
            return i

    # Step 2: largest instruction address ≤ target_aligned
    # (handles BFAR pointing into the middle of a memory operand)
    best_i   = -1
    best_addr = -1
    for i, r in enumerate(records):
        if r['type'] == 'insn' and r['addr'] <= target_aligned:
            if r['addr'] > best_addr:
                best_addr = r['addr']
                best_i    = i

    return best_i


def _expand_to_source(records, boundary_idx, direction):
    """
    Expand a context boundary index to include adjacent source lines.
    direction: -1 = expand backward, +1 = expand forward.
    """
    idx = boundary_idx
    n   = len(records)
    while 0 <= idx < n:
        next_idx = idx + direction
        if 0 <= next_idx < n and records[next_idx]['type'] in ('source_code','source_loc','func_sig','blank'):
            idx = next_idx
        else:
            break
    return idx


# ---------------------------------------------------------------------------
# Fault pattern analysis
# ---------------------------------------------------------------------------

# ARM Cortex-M physical memory map (common S32K3 / STM32 layout)
# These ranges are used to classify what the faulting address is touching.
FLASH_RANGES  = [(0x00000000, 0x10000000)]   # internal + external flash
SRAM_RANGES   = [(0x20000000, 0x40000000)]   # all SRAM variants
PERIPH_RANGES = [(0x40000000, 0xE0000000)]   # peripheral space
NULL_WINDOW   = 0x00000100                   # NULL pointer detection threshold


def _addr_in(addr, ranges):
    return any(lo <= addr < hi for lo, hi in ranges)


def _analyse_fault(records, target_idx, target_addr, func_start, func_end):
    """
    Heuristic fault analysis based on the instruction and address.

    Checks in order of certainty:
        1. Address in NULL window          → null dereference
        2. Store to flash                  → write to read-only memory
        3. Access to peripheral space      → clock/privilege issue
        4. BX/BLX instruction              → bad function pointer
        5. Misaligned halfword/word access → unaligned access fault
        6. SRAM address with preceding BL  → PC corrupted into SRAM
        7. SP-relative operand             → possible stack overflow
    """
    if target_idx < 0 or target_idx >= len(records):
        return None

    insn = records[target_idx]
    if insn['type'] != 'insn':
        return None

    mnem = insn['mnemonic']
    ops  = insn['operands'].lower()

    # Preceding instructions (up to 5, for context)
    prev = [records[j] for j in range(max(0, target_idx-5), target_idx)
            if records[j]['type'] == 'insn']

    # ── 1. NULL / near-NULL pointer ───────────────────────────────────────
    if target_addr < NULL_WINDOW:
        if insn['is_load'] or insn['is_store']:
            return _make('null_deref', 'high',
                f'Address {hex(target_addr)} is in the NULL window (0–0xFF). '
                f'A pointer that should have been initialised was NULL or was never assigned.')
        if insn['is_branch']:
            return _make('bad_branch', 'high',
                f'Branch to {hex(target_addr)}: this is the ARM exception vector table. '
                f'A function pointer was NULL.')

    # ── 2. Write to flash ─────────────────────────────────────────────────
    if insn['is_store'] and _addr_in(target_addr, FLASH_RANGES):
        return _make('write_to_flash', 'high',
            f'Store instruction writing to {hex(target_addr)} which is in flash. '
            f'Flash is read-only during normal execution. '
            f'A const qualifier may have been cast away, or a buffer overflow '
            f'corrupted a pointer into flash range.')

    # ── 3. Peripheral access ──────────────────────────────────────────────
    if (insn['is_load'] or insn['is_store']) and _addr_in(target_addr, PERIPH_RANGES):
        return _make('peripheral_access', 'high',
            f'Memory access to peripheral register at {hex(target_addr)}. '
            f'Common causes: peripheral clock not enabled (check PCC register), '
            f'accessing a peripheral from an unprivileged thread with MPU active, '
            f'or a NULL base-pointer to a peripheral struct.')

    # ── 4. Bad branch / corrupt function pointer ──────────────────────────
    if insn['is_branch'] and mnem in ('bx', 'blx'):
        return _make('bad_branch', 'medium',
            f'BX/BLX at {hex(insn["addr"])}: indirect branch through a register. '
            f'The target register may contain NULL, an uninitialised value, or a '
            f'corrupted function pointer. Check all function pointer initialisations '
            f'and any buffers adjacent to function pointer tables.')

    # ── 5. Unaligned access ───────────────────────────────────────────────
    if mnem in ('ldrh','strh','ldrsh') and (target_addr & 1):
        return _make('unaligned_access', 'high',
            f'Halfword access (LDRH/STRH) to odd address {hex(target_addr)}. '
            f'ARM requires halfword accesses to be 2-byte aligned. '
            f'Check struct packing (__attribute__((packed))) and DMA buffer alignment.')
    if mnem in ('ldr','str','ldrd','strd') and (target_addr & 3):
        return _make('unaligned_access', 'high',
            f'Word access (LDR/STR) to non-4-byte-aligned address {hex(target_addr)}. '
            f'If UNALIGN_TRP is set in CCR (common in RTOS configs) this causes UsageFault. '
            f'Check struct packing and pointer casts from byte arrays.')

    # ── 6. PC into SRAM (instruction fetch from data memory) ─────────────
    if _addr_in(target_addr, SRAM_RANGES):
        if any(p['is_branch'] for p in prev[-2:]):
            return _make('iaccviol', 'medium',
                f'Address {hex(target_addr)} is in SRAM. A preceding branch '
                f'may have jumped into data memory. This indicates a corrupt '
                f'return address (stack smash) or an uninitialised function pointer '
                f'that happens to point into SRAM.')

    # ── 7. SP-relative access ─────────────────────────────────────────────
    if (insn['is_load'] or insn['is_store']) and ('[sp' in ops or 'sp,' in ops):
        return _make('stack_overflow', 'low',
            f'SP-relative memory access at {hex(insn["addr"])}. '
            f'If SP was corrupted or exhausted (stack overflow), this access '
            f'lands in an unmapped or protected region. '
            f'Check task stack sizes against worst-case call depth in the Stack Depth tab.')

    return None


FAULT_META = {
    'null_deref': {
        'icon': '🔴', 'title': 'Null pointer dereference',
        'desc': 'An instruction accessed memory through a pointer that is NULL or uninitialised.',
        'fix':  'Add NULL checks before all pointer dereferences. '
                'Check the BFAR register in your HardFault handler to confirm the data address. '
                'Initialise all pointers before use.',
    },
    'write_to_flash': {
        'icon': '🟡', 'title': 'Write to read-only flash',
        'desc': 'A store instruction targeted the flash address range. '
                'Flash is read-only during normal code execution.',
        'fix':  'Look for const qualifiers being cast away (const_cast, (T*) casts). '
                'Check for buffer overflows that corrupt a pointer to land in flash. '
                'Verify DMA destination addresses are not in flash.',
    },
    'peripheral_access': {
        'icon': '⚡', 'title': 'Peripheral register access fault',
        'desc': 'A memory access targeted the peripheral register space (0x40000000+).',
        'fix':  'Ensure the peripheral clock is enabled before the first register access. '
                'On S32K3: check PCC_<PERIPH>_CGC bit. '
                'Check thread privilege level if using RTOS with MPU enabled.',
    },
    'bad_branch': {
        'icon': '🔴', 'title': 'Bad branch / corrupt function pointer',
        'desc': 'A branch instruction jumped to an address that is not valid executable code. '
                'The most common cause is a NULL or corrupted function pointer.',
        'fix':  'Check all function pointer initialisations. '
                'Verify callback/ISR registration code. '
                'Look for buffer overflows adjacent to function pointer tables. '
                'Check LR on ISR entry — it should be 0xFFFFFFF9 or 0xFFFFFFFD on Cortex-M.',
    },
    'unaligned_access': {
        'icon': '🟡', 'title': 'Unaligned memory access',
        'desc': 'An instruction accessed memory at a non-aligned address. '
                'ARM Cortex-M raises UsageFault if UNALIGN_TRP is set in CCR.',
        'fix':  'Remove __attribute__((packed)) from structs accessed by pointer. '
                'Use memcpy() instead of pointer casting for unaligned byte streams. '
                'Ensure DMA buffers start at 4-byte-aligned addresses.',
    },
    'iaccviol': {
        'icon': '🔴', 'title': 'Instruction fetch from non-executable region',
        'desc': 'The CPU tried to fetch an instruction from SRAM or peripheral space. '
                'This happens when a corrupt return address or function pointer sends PC into data.',
        'fix':  'Enable MPU XN (execute-never) on SRAM to catch this early. '
                'Check for stack smashes that overwrite the saved LR on the stack. '
                'Review all function pointer and callback assignments.',
    },
    'stack_overflow': {
        'icon': '🟠', 'title': 'Possible stack overflow',
        'desc': 'The faulting instruction uses SP (stack pointer) and the access may have '
                'gone below the allocated stack.',
        'fix':  'Increase the task stack size. '
                'Use the Stack Depth tab to compute worst-case stack usage with -fstack-usage. '
                'Enable FreeRTOS stack overflow checking: configCHECK_FOR_STACK_OVERFLOW=2.',
    },
}


def _make(pattern, confidence, detail):
    m = FAULT_META.get(pattern, {})
    return {
        'pattern':    pattern,
        'icon':       m.get('icon', 'ℹ'),
        'title':      m.get('title', pattern),
        'confidence': confidence,
        'detail':     detail,
        'description': m.get('desc', ''),
        'fix':        m.get('fix', ''),
    }


# ---------------------------------------------------------------------------
# Source file reading helpers
# ---------------------------------------------------------------------------

def _read_source_file(source_file_path: str, source_dir: str) -> dict:
    """
    Try to read a source file, returning a dict of {line_number: text}.

    We search for the file in several ways:
        1. Absolute path as-is (works if machine has same path layout)
        2. Basename only in source_dir (most common — file is in the project)
        3. Last N components of the path joined with source_dir
           (handles build/src/module/file.c → source_dir/src/module/file.c)
        4. Recursive search in source_dir for the basename

    Returns {} if the file cannot be found.
    """
    import os

    basename = os.path.basename(source_file_path)
    # Path components of the original path (after stripping drive letters)
    norm = source_file_path.replace('\\', '/').replace('\\\\', '/')
    parts = [p for p in norm.split('/') if p and ':' not in p]

    candidates = []

    # 1. Absolute path
    if os.path.isabs(source_file_path):
        candidates.append(source_file_path)

    # 2. Last 1-4 components joined with source_dir
    for depth in range(1, min(5, len(parts) + 1)):
        sub = os.path.join(source_dir, *parts[-depth:])
        candidates.append(sub)
        candidates.append(sub.replace('/', os.sep))

    # 3. Basename in source_dir
    candidates.append(os.path.join(source_dir, basename))

    # Try each candidate
    for path in candidates:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            return {i+1: line.rstrip() for i, line in enumerate(lines)}
        except (IOError, OSError):
            continue

    # 4. Recursive search (slow but thorough — only if others failed)
    try:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if basename in files:
                path = os.path.join(root, basename)
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                return {i+1: line.rstrip() for i, line in enumerate(lines)}
    except (IOError, OSError):
        pass

    return {}


def _inject_source_lines(instructions: list, source_lines: dict) -> list:
    """
    Insert source_code records before instruction groups based on their
    _src_line annotation (from addr2line / DWARF).

    When objdump --source fails to resolve paths, we still have _src_line
    on each instruction from the DWARF.  This function reads the actual
    source lines from the file and injects them.

    We inject:
        - A source_loc marker when the source line changes
        - The C source line itself as a source_code record
    """
    if not source_lines:
        return instructions

    result     = []
    last_line  = -1

    for rec in instructions:
        if rec['type'] == 'insn':
            line_no = rec.get('_src_line', 0)
            if line_no and line_no != last_line and line_no in source_lines:
                # Inject the source line before this instruction
                result.append({
                    'type': 'source_code',
                    'text': source_lines[line_no],
                    '_src_line': line_no,
                })
                last_line = line_no
        result.append(rec)

    return result
