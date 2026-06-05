"""
callgraph_parser.py  —  GCC -fcallgraph-info=su,da parser
==========================================================

GCC FLAGS:
    -fstack-usage          generates .su files (per-function stack frame + type)
    -fcallgraph-info=su,da generates .ci files (call graph with stack costs)

S32DS / arm-none-eabi-gcc location:
    Project → Properties → C/C++ Build → Settings →
    Compiler → Miscellaneous → Other flags

FULL RECOMMENDED SET:
    -fstack-usage -fcallgraph-info=su,da -Wstack-usage=256

ACTUAL GCC .CI FILE FORMAT (arm-none-eabi-gcc 11.x):
    The -fcallgraph-info flag is documented in the GCC internals manual
    but the output format changed several times. This parser handles the
    format produced by GCC 9–13 as used in arm-none-eabi toolchains.

    A .ci file contains one block per function:

        IpcMaster_Task/12 (IpcMaster_Task, ENQUEUE)
          Type: function definition analyzed
          Body size: 236
          Stack usage: 64
          Called by: OsTask_10ms/3 (OsTask_10ms)
          Calls: BswSpi_Exchange/7 (BswSpi_Exchange)
          Calls: vTaskDelay/99 (vTaskDelay)

    Key fields:
        "Stack usage: N"    — this function's OWN stack frame in bytes
        "Body size: N"      — code size in bytes (useful for bloat cross-ref)
        "Calls: funcname/N" — this function calls funcname
        "Called by: ..."    — reverse edges (we derive from Calls instead)

    The function name format is "symbol/cgraph_uid" — we strip the /N suffix.
    The block ends when the next blank line + new function header starts.

WHAT THIS MODULE PRODUCES:
    analyse_callgraph(ci_contents, su_entries)
        → worst-case stack depth per function via DFS over the call graph

EMBEDDED ENGINEER — WHY WORST-CASE MATTERS:
    .su alone gives "IpcMaster_Task frame = 64 bytes".
    .ci tells you the full chain:
        IpcMaster_Task (64)
          → BswSpi_Exchange (32)
            → LPSPI_DRV_MasterTransfer (128)
    Total worst-case = 64 + 32 + 128 = 224 bytes.
    Your FreeRTOS task stack must be AT LEAST this large.

SOFTWARE ENGINEER — ALGORITHM:
    Standard longest-path in a directed graph via DFS + memoisation.
    Cycles (recursive calls) are detected and capped at one level.
    Time complexity: O(V + E), same as topological sort.
"""

import re
from collections import defaultdict


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyse_callgraph(ci_contents, su_entries=None):
    """
    Full analysis from a list of raw .ci file text strings.

    Parameters
    ----------
    ci_contents : list[str]   Raw text of each .ci file
    su_entries  : list[dict]  Already-parsed .su entries {func, size, type, ...}
                              Used to fill in stack frame sizes where .ci has none.

    Returns
    -------
    dict with keys:
        worst_case    {func_name: {frame, worst_case, path, file, line, recursive}}
        has_recursive bool — any recursive calls detected
        has_unbounded bool — any dynamic-stack functions in any call chain
        node_count    int
        edge_count    int
        top_worst     list[dict] — top 20 by worst_case depth
        format_sample str  — first 10 lines of first .ci file (for debugging)
    """
    if not ci_contents:
        return None

    # Parse each file, merge into one graph
    all_nodes  = {}   # uid → node dict
    all_edges  = []   # list of {caller_uid, callee_name}  (resolved later)
    uid_offset = 0    # avoid UID collisions across files

    format_sample = ''

    for file_idx, content in enumerate(ci_contents):
        if file_idx == 0:
            format_sample = '\n'.join(content.splitlines()[:15])

        nodes, edges = _parse_ci(content, uid_offset)
        all_nodes.update(nodes)
        all_edges.extend(edges)
        uid_offset += 100000   # generous gap between file UIDs

    # Build name→uid index (multiple definitions possible in different TUs)
    name_to_uids = defaultdict(list)
    for uid, node in all_nodes.items():
        name_to_uids[node['name']].append(uid)

    # Fill frame sizes from .su data for any node that has frame=0
    su_map = {}
    if su_entries:
        for e in su_entries:
            su_map[e['func']] = e.get('size', 0)
    for node in all_nodes.values():
        if node['frame'] == 0 and node['name'] in su_map:
            node['frame'] = su_map[node['name']]

    # Resolve edges: callee_name → callee_uid (pick first match)
    adj = defaultdict(list)   # caller_uid → [callee_uid, ...]
    for edge in all_edges:
        caller_uid   = edge['caller_uid']
        callee_uids  = name_to_uids.get(edge['callee_name'], [])
        if callee_uids:
            adj[caller_uid].append(callee_uids[0])

    # Compute worst-case stack depth via DFS
    worst_case = _compute_worst_case(all_nodes, adj)

    # Identify unbounded functions (dynamic stack, not bounded)
    unbounded_names = set()
    if su_entries:
        for e in su_entries:
            t = e.get('type', '')
            if 'dynamic' in t and 'bounded' not in t:
                unbounded_names.add(e['func'])

    has_unbounded = any(
        any(n in unbounded_names for n in v.get('path', []))
        for v in worst_case.values()
    )
    has_recursive = any(v.get('recursive', False) for v in worst_case.values())

    top_worst = sorted(
        [{'func': k, **v} for k, v in worst_case.items()],
        key=lambda x: -x['worst_case']
    )[:20]

    return {
        'worst_case':    worst_case,
        'has_recursive': has_recursive,
        'has_unbounded': has_unbounded,
        'node_count':    len(all_nodes),
        'edge_count':    len(all_edges),
        'top_worst':     top_worst,
        'format_sample': format_sample,
    }


# ---------------------------------------------------------------------------
# .ci file parser  —  handles all GCC 9-13 format variants
# ---------------------------------------------------------------------------

def _parse_ci(content, uid_offset=0):
    """
    Parse one .ci file.

    GCC produces several slightly different layouts depending on version
    and flags. We handle them all by:
      1. Splitting on function header lines (detected by "funcname/UID" pattern)
      2. For each block, extracting all useful fields with multiple regex attempts
      3. Collecting "Calls:" lines to build the edge list

    Returns: (nodes_dict, edges_list)
        nodes_dict : {uid → {name, file, line, frame, body_size, type}}
        edges_list : [{caller_uid, callee_name}]
    """
    nodes  = {}
    edges  = []

    # ── Split content into per-function blocks ────────────────────────────
    # A block starts with a line like:
    #     FunctionName/42 (FunctionName, ...)
    #     FunctionName/42 (FunctionName)
    # The "/42" is the cgraph UID — unique per translation unit.
    block_starts = list(re.finditer(
        r'^(\S+)/(\d+)\s*\([^)]*\)',
        content, re.MULTILINE
    ))

    for i, match in enumerate(block_starts):
        # Extract the raw block text up to the next block header
        block_start = match.start()
        block_end   = block_starts[i+1].start() if i+1 < len(block_starts) else len(content)
        block       = content[block_start:block_end]

        # Parse function name and UID from header
        raw_name = match.group(1)
        uid      = uid_offset + int(match.group(2))

        # Clean up the name: strip leading path separators, template brackets etc.
        name = _clean_funcname(raw_name)

        node = {
            'name':      name,
            'file':      '',
            'line':      0,
            'frame':     0,     # own stack frame bytes
            'body_size': 0,     # code size bytes
            'type':      'function',
            'recursive': False,
        }

        # ── Extract fields from block lines ──────────────────────────────
        for line in block.splitlines():
            ls = line.strip()

            # Stack usage / frame size
            # Variants: "Stack usage: 64"  "stack usage: 64 bytes (static)"
            m = re.match(r'Stack usage:\s*(\d+)', ls, re.IGNORECASE)
            if m:
                node['frame'] = int(m.group(1))
                continue

            # Body size (code size)
            m = re.match(r'Body size:\s*(\d+)', ls, re.IGNORECASE)
            if m:
                node['body_size'] = int(m.group(1))
                continue

            # Function type
            m = re.match(r'Type:\s*(.+)', ls, re.IGNORECASE)
            if m:
                node['type'] = m.group(1).strip()
                continue

            # Source location  "filename:line:col"  or  "At filename:line"
            m = re.match(r'(?:At\s+)?(.+\.(?:c|cpp|cxx|cc|h|hpp))(?::(\d+))?', ls)
            if m and not ls.startswith('Call'):
                node['file'] = _short_path(m.group(1))
                if m.group(2):
                    node['line'] = int(m.group(2))
                continue

            # Call edges  "Calls: FunctionName/42 (FunctionName)"
            #             "Calls: FunctionName/42"
            m = re.match(r'Calls:\s*(\S+)/\d+(?:\s*\([^)]*\))?', ls, re.IGNORECASE)
            if m:
                callee_name = _clean_funcname(m.group(1))
                edges.append({'caller_uid': uid, 'callee_name': callee_name})
                continue

            # Some versions list multiple callees per line as space-separated
            # "Calls: A/1 (A) B/2 (B)"
            if ls.lower().startswith('calls:'):
                for cm in re.finditer(r'(\S+)/(\d+)', ls):
                    callee_name = _clean_funcname(cm.group(1))
                    callee_uid  = uid_offset + int(cm.group(2))
                    edges.append({'caller_uid': uid, 'callee_name': callee_name})

        nodes[uid] = node

    return nodes, edges


# ---------------------------------------------------------------------------
# Worst-case stack depth  —  DFS with memoisation
# ---------------------------------------------------------------------------

def _compute_worst_case(nodes, adj):
    """
    Compute worst-case total stack depth for every function.

    worst_case(f) = frame(f) + max over all callees c of:
                        worst_case(c)

    Edge "cost" in GCC .ci is the number of bytes pushed BEFORE the call
    (arguments on stack, alignment padding). In the format we parse,
    this is not always available, so we treat the callee's own frame as
    the contribution — which is the conservative (safe) approach.

    Recursive calls: detected by presence of the caller in the current
    DFS path. The recursive edge contributes 0 additional depth (same
    as GCC's own stack analysis behaviour).
    """
    memo    = {}   # uid → (worst_case_bytes, path_list)
    in_path = set()

    def dfs(uid):
        if uid in memo:
            return memo[uid]
        if uid not in nodes:
            return (0, [])

        node  = nodes[uid]
        frame = node.get('frame', 0)

        # Cycle detection: if we visit this node while it's in the current
        # DFS path, we have a recursive call. Return frame only.
        if uid in in_path:
            node['recursive'] = True
            return (frame, [node['name']])

        in_path.add(uid)
        best_extra = 0
        best_path  = []

        for callee_uid in adj.get(uid, []):
            callee_wc, callee_path = dfs(callee_uid)
            if callee_wc > best_extra:
                best_extra = callee_wc
                best_path  = callee_path

        in_path.discard(uid)

        result = (frame + best_extra, [node['name']] + best_path)
        memo[uid] = result
        return result

    results = {}
    for uid, node in nodes.items():
        worst, path = dfs(uid)
        name = node['name']
        # If the same function appears in multiple TUs, keep the worst case
        if name not in results or worst > results[name]['worst_case']:
            results[name] = {
                'frame':      node.get('frame', 0),
                'body_size':  node.get('body_size', 0),
                'worst_case': worst,
                'path':       path,
                'file':       node.get('file', ''),
                'line':       node.get('line', 0),
                'recursive':  node.get('recursive', False),
            }
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_funcname(raw):
    """
    Strip compiler-added suffixes and prefixes from function names.

    GCC sometimes qualifies names with:
      - Namespace/class prefixes:  MyClass::myMethod  → keep as-is (readable)
      - .cold / .constprop.0 suffixes → strip (they're compiler-generated clones)
      - Leading dots: .L_IpcMaster_Task → strip the dot
    """
    name = raw.strip()
    # Strip .cold, .constprop.N, .isra.N, .part.N compiler clone suffixes
    name = re.sub(r'\.(cold|constprop|isra|part|lto_priv)\.\d*$', '', name)
    # Strip leading dot (internal labels)
    name = name.lstrip('.')
    return name or raw.strip()


def _short_path(p):
    """Return just the last two components of a filesystem path."""
    p = p.replace('\\', '/')
    parts = [x for x in p.split('/') if x]
    return '/'.join(parts[-2:]) if len(parts) > 2 else p
