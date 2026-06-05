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

  // Extra symbol analysis (issue 5)
  renderExtraSymbolAnalysis();

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
  const COLORS=['#3b82f6','#f97316','#10b981','#8b5cf6','#f59e0b','#ef4444','#06b6d4','#ec4899','#84cc16','#6366f1'];
  // Use flex-wrap layout — each cell is proportional but min 120px wide
  // Height scales with importance so large contributors are visually dominant
  const maxVal=data[0][sizeKey]||1;
  data.slice(0,40).forEach((r,i)=>{
    if(!r[sizeKey])return;
    const pct=r[sizeKey]/total;
    const pctOfMax=r[sizeKey]/maxVal;
    // Width: proportional, min 140px, max 320px
    const w=Math.min(320,Math.max(140,Math.round(pct*1800)));
    // Height: taller for bigger contributors
    const h=Math.min(120,Math.max(64,Math.round(pctOfMax*110+40)));
    const col=COLORS[i%COLORS.length];
    const cell=document.createElement('div');
    cell.className='tree-cell';
    cell.style.cssText=`width:${w}px;height:${h}px;`
      +`background:${col}1a;border:1px solid ${col}55;`
      +`display:flex;flex-direction:column;justify-content:flex-end;padding:8px;`
      +`cursor:pointer;border-radius:4px;overflow:hidden;position:relative;transition:.15s`;
    // Percentage bar at bottom
    cell.innerHTML=`
      <div style="position:absolute;bottom:0;left:0;right:0;height:${Math.round(pctOfMax*100)}%;`
        +`background:${col}22;z-index:0"></div>
      <div style="position:relative;z-index:1">
        <div style="font-size:10px;font-weight:600;color:#fff;white-space:normal;`
          +`word-break:break-all;line-height:1.3;margin-bottom:3px">${r.file}</div>
        <div style="font-size:11px;color:${col};font-weight:700">${fz(r[sizeKey])}</div>
        <div style="font-size:9px;color:#6e7681">${Math.round(pct*100)}%</div>
      </div>`;
    cell.addEventListener('click',()=>{$('sym-f').value=r.file;filterSyms();switchTab('sym');});
    cell.addEventListener('mouseenter',()=>cell.style.filter='brightness(1.3)');
    cell.addEventListener('mouseleave',()=>cell.style.filter='');
    addTip(cell,{name:r.file,rows:[
      ['Flash',fz(r.flash)],['RAM',fz(r.ram)],['Total',fz(r.total)],
      ['% of total',Math.round(pct*100)+'%']
    ],desc:'Click to filter symbols by this file'});
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
// ADDRESS INSPECTOR
// Cross-references an address against ELF symbols, LD sections,
// map file, and addr2line simultaneously.
// ═══════════════════════════════════════════════════════════════════════════

// Called from drops.js / symbol clicks — sets the input and inspects
function doA2L(addr) {
  if (addr) { $('a2l-addr').value = addr; }
  inspectAddress();
}
function setStatus(msg, pct) {
  const s = document.getElementById('ai-status');
  if (s) s.textContent = msg || 'Done';
  const p = $('ai-progress');
  if (p) p.value = pct;
}

function onAddrInput(inp) {
  // Accept bare hex without 0x prefix
  const v = inp.value.replace(/^0x/i, '').replace(/[^0-9a-fA-F]/g, '');
  inp.dataset.clean = v;
}

function clearInspector() {
  $('a2l-addr').value = '';
  $('ai-results').style.display = 'none';
}

function clearHistory() {
  S.a2lHistory = [];
  $('ai-history').innerHTML = '';
}

async function inspectAddress() {
  const raw = ($('a2l-addr').value || '').trim();
  if (!raw) return;

  let addrInt;
  try {
    addrInt = parseInt(raw.replace(/^0x/i, ''), 16);
    if (isNaN(addrInt)) throw new Error();
  } catch(e) {
    $('ai-results').style.display = '';
    $('ai-banner').className = 'ai-banner notfound';
    $('ai-banner').innerHTML = '<span class="ai-addr">' + raw + '</span><span class="ai-sum">Not a valid hex address</span>';
    return;
  }

  const hexAddr = '0x' + addrInt.toString(16).toUpperCase().padStart(8, '0');
  $('a2l-addr').value = hexAddr;
  $('ai-results').style.display = '';
  $('ai-progress').style.display = '';
  $('ai-progress').value = 0;
  $('ai-banner').className = 'ai-banner';
  $('ai-banner').innerHTML = '<span class="ai-addr">' + hexAddr + '</span>'
    + '<span class="ai-sum" id="ai-status">Inspecting…</span>';

  // ── 1. ELF symbol lookup ──────────────────────────────────────────────
  setStatus('Searching symbols…', 20);
  const symResult = inspectSymbol(addrInt);

  // ── 2. LD section / region lookup ────────────────────────────────────
  setStatus('Checking sections…', 45);
  const secResult = inspectSection(addrInt);

  // ── 3. Map file lookup ────────────────────────────────────────────────
  setStatus('Searching map file…', 60);
  const mapResult = inspectMap(addrInt);

  // ── 4. addr2line (async — server call) ───────────────────────────────
  setStatus('Calling addr2line…', 80);
  const a2lResult = await inspectA2L(addrInt);
  setStatus('', 100);
  $('ai-progress').style.display = 'none';

  // ── Render all four cards ─────────────────────────────────────────────
  renderSymCard(symResult, addrInt);
  renderSecCard(secResult);
  renderMapCard(mapResult);
  renderA2LCard(a2lResult);

  // ── Summary banner ────────────────────────────────────────────────────
  renderBanner(hexAddr, symResult, secResult, mapResult, a2lResult);

  // ── Offset bar ────────────────────────────────────────────────────────
  if (symResult.sym) renderOffsetBar(addrInt, symResult.sym);
  else $('ai-offset-bar').style.display = 'none';

  // ── History ───────────────────────────────────────────────────────────
  const entry = {
    addr:    hexAddr,
    symName: symResult.sym ? symResult.sym.name : '—',
    secName: secResult.sec ? secResult.sec.name : '—',
    source:  a2lResult.short || '—',
  };
  S.a2lHistory.unshift(entry);
  if (S.a2lHistory.length > 30) S.a2lHistory.pop();
  renderInspectHistory();
}

// ── Symbol lookup ─────────────────────────────────────────────────────────

function inspectSymbol(addr) {
  if (!S.syms || !S.syms.length) return { sym: null, reason: 'no_elf' };

  // Find symbol that contains this address (addr >= sym.addr && addr < sym.addr + sym.size)
  let best = null;
  for (const sym of S.syms) {
    if (sym.size > 0 && addr >= sym.addr && addr < sym.addr + sym.size) {
      // Prefer smaller (more specific) symbol
      if (!best || sym.size < best.size) best = sym;
    }
  }

  // If no ranged match, find nearest symbol below (for zero-size symbols)
  if (!best) {
    const below = S.syms.filter(s => s.addr <= addr).sort((a, b) => b.addr - a.addr);
    if (below.length) {
      const nearest = below[0];
      const gap = addr - nearest.addr;
      return { sym: nearest, offset: gap, exact: false, reason: 'nearest' };
    }
    return { sym: null, reason: 'not_found' };
  }

  return { sym: best, offset: addr - best.addr, exact: true, reason: 'found' };
}

// ── Section / region lookup ───────────────────────────────────────────────

function inspectSection(addr) {
  const result = { sec: null, reg: null, elfSec: null };
  if (!S.ld) return result;

  // Find LD section by cross-referencing ELF section addresses
  for (const [name, es] of Object.entries(S.elfSecs || {})) {
    if (es.size > 0 && addr >= es.addr && addr < es.addr + es.size) {
      result.elfSec = { name, ...es };
      // Find matching LD section
      result.sec = S.ld.sections.find(s => s.name === name) || null;
      break;
    }
  }

  // Find memory region
  for (const reg of (S.ld.regions || [])) {
    if (reg.length > 0 && addr >= reg.origin && addr < reg.end) {
      result.reg = reg;
      break;
    }
  }

  return result;
}

// ── Map file lookup ───────────────────────────────────────────────────────

function inspectMap(addr) {
  if (!S.mapData) return { unit: null, reason: 'no_map' };

  // Search through all section units for one whose address range contains addr
  for (const sec of S.mapData.sections) {
    for (const unit of sec.units) {
      if (unit.size > 0 && addr >= unit.addr && addr < unit.addr + unit.size) {
        return { unit, section: sec, reason: 'found' };
      }
    }
  }

  // Nearest unit below addr
  let best = null, bestDist = Infinity;
  for (const sec of S.mapData.sections) {
    for (const unit of sec.units) {
      if (unit.addr <= addr) {
        const d = addr - unit.addr;
        if (d < bestDist) { bestDist = d; best = { unit, section: sec }; }
      }
    }
  }
  if (best) return { ...best, offset: bestDist, reason: 'nearest' };
  return { unit: null, reason: 'not_found' };
}

// ── addr2line ─────────────────────────────────────────────────────────────

async function inspectA2L(addr) {
  if (!S.elfFile) return { result: null, short: null, reason: 'no_elf' };
  try {
    const fd = new FormData();
    fd.append('addr',     '0x' + addr.toString(16));
    fd.append('prefix',   $('t-prefix').value.trim());
    fd.append('a2l_tool', $('t-a2l').value.trim());
    fd.append('elf',      S.elfFile);
    const res = await fetch('/addr2line', { method: 'POST', body: fd });
    const d   = await res.json();
    const raw = d.result || '';
    if (!raw || raw.includes('??')) return { result: raw, short: null, reason: 'unknown' };
    // Extract short form: last path component + line
    const atIdx = raw.indexOf(' at ');
    const afterAt = atIdx >= 0 ? raw.slice(atIdx + 4) : raw;
    const slashIdx = Math.max(afterAt.lastIndexOf('/'), afterAt.lastIndexOf('\\'));
    const short = slashIdx >= 0 ? afterAt.slice(slashIdx + 1) : afterAt;
    return { result: raw, short, reason: 'found' };
  } catch(e) {
    return { result: null, short: null, reason: 'error', error: e.message };
  }
}

// ── Card renderers ────────────────────────────────────────────────────────

function aiRow(key, value, cls) {
  return `<div class="ai-row"><span class="k">${key}</span><span class="v ${cls||''}">${value}</span></div>`;
}

function renderSymCard(r, addr) {
  const body = $('ai-sym-body');
  if (r.reason === 'no_elf') {
    body.innerHTML = '<span class="ai-na">Load ELF and click Analyse ELF</span>';
    return;
  }
  if (!r.sym) {
    body.innerHTML = '<span class="ai-na">No symbol found at this address</span>';
    return;
  }
  const sym = r.sym;
  const TCOL = { function:'#3b82f6', variable:'#f97316', constant:'#10b981',
                  weak:'#6366f1', undefined:'#6e7681', other:'#374151' };
  const col  = TCOL[sym.type] || TCOL.other;
  const offsetStr = r.offset !== undefined
    ? `+0x${r.offset.toString(16).toUpperCase()} (${r.offset} bytes in)`
    : '';
  const exact = r.reason === 'found';

  body.innerHTML =
    aiRow('Name',    `<strong style="color:#fff">${sym.name}</strong>`) +
    aiRow('Type',    `<span style="color:${col}">${sym.type}</span>${sym.global ? '' : ' <span style="color:var(--dim);font-size:10px">(local)</span>'}`) +
    aiRow('Start',   `0x${sym.addr.toString(16).toUpperCase().padStart(8,'0')}`, 'hx') +
    (sym.size ? aiRow('Size', fz(sym.size) + ` (${sym.size} bytes)`, 'sz') : '') +
    (sym.size ? aiRow('End',  `0x${(sym.addr+sym.size-1).toString(16).toUpperCase().padStart(8,'0')} (inclusive)`, 'hx') : '') +
    (offsetStr ? aiRow(exact ? 'Offset' : 'Nearest offset', offsetStr, exact ? 'sz' : 'warn') : '') +
    (sym.file ? aiRow('File', sym.file, 'file') : '');
}

function renderSecCard(r) {
  const body = $('ai-sec-body');
  if (!S.ld) {
    body.innerHTML = '<span class="ai-na">Load a .ld linker script</span>';
    return;
  }
  if (!r.reg && !r.sec) {
    body.innerHTML = '<span class="ai-na">Address is outside all defined memory regions</span>';
    return;
  }
  let html = '';
  if (r.reg) {
    html +=
      aiRow('Region',   `<strong style="color:#fff">${r.reg.name}</strong>`) +
      aiRow('Type',     r.reg.type) +
      aiRow('Range',    `0x${r.reg.origin.toString(16).toUpperCase()} – 0x${r.reg.end.toString(16).toUpperCase()}`, 'hx') +
      aiRow('Size',     fz(r.reg.length), 'sz');
  }
  if (r.elfSec) {
    html += `<div style="border-top:1px solid var(--bdr);margin:6px 0;padding-top:6px">` +
      aiRow('Section',  `<strong style="color:#fff">${r.elfSec.name}</strong>`) +
      aiRow('ELF size', fz(r.elfSec.size), 'sz') +
      `</div>`;
  }
  if (r.sec) {
    html +=
      (r.sec.cacheable ? aiRow('Cache', '<span class="v warn">⚠ CACHEABLE — unsafe for DMA</span>') : '') +
      (r.sec.dma_safe  ? aiRow('DMA',   '<span class="v ok">✓ DMA-safe (non-cacheable)</span>') : '') +
      (r.sec.noload    ? aiRow('NOLOAD','Not in flash image — zeroed/filled at startup') : '') +
      (r.sec.lma       ? aiRow('LMA',   'Copied from ' + r.sec.lma + ' at startup', 'file') : '');
  }
  body.innerHTML = html || '<span class="ai-na">No section info available</span>';
}

function renderMapCard(r) {
  const body = $('ai-map-body');
  if (r.reason === 'no_map') {
    body.innerHTML = '<span class="ai-na">Load a .map file</span>';
    return;
  }
  if (!r.unit) {
    body.innerHTML = '<span class="ai-na">Address not found in map file</span>';
    return;
  }
  const inRange = r.reason === 'found';
  body.innerHTML =
    aiRow('File',       `<strong style="color:#fff">${r.unit.file}</strong>`) +
    (r.unit.file_full !== r.unit.file ? aiRow('Full path', r.unit.file_full, 'file') : '') +
    aiRow('Subsection', r.unit.subsection) +
    aiRow('Unit start', `0x${r.unit.addr.toString(16).toUpperCase().padStart(8,'0')}`, 'hx') +
    aiRow('Unit size',  fz(r.unit.size), 'sz') +
    aiRow('In section', r.section.name) +
    (!inRange ? aiRow('Note', `+0x${r.offset.toString(16)} after unit start (nearest match)`, 'warn') : '');
}

function renderA2LCard(r) {
  const body = $('ai-a2l-body');
  if (r.reason === 'no_elf') {
    body.innerHTML = '<span class="ai-na">Load ELF and click Analyse ELF</span>';
    return;
  }
  if (!r.result || r.reason === 'error') {
    body.innerHTML = '<span class="ai-na">' + (r.error || 'addr2line not available') + '</span>';
    return;
  }
  if (r.reason === 'unknown') {
    body.innerHTML = '<span class="ai-na">Symbol not found (may be stripped or inline)</span>';
    return;
  }
  // Parse the addr2line output:  "funcname() at file.c:123"
  const parts  = r.result.match(/^(.*?) at (.+):(\d+)$/);
  if (parts) {
    body.innerHTML =
      aiRow('Function', `<strong style="color:#fff">${parts[1]}</strong>`) +
      aiRow('File',     parts[2], 'src') +
      aiRow('Line',     `<strong style="color:var(--acc)">${parts[3]}</strong>`);
  } else {
    body.innerHTML = `<div style="font-size:11px;color:var(--pur);word-break:break-all">${r.result}</div>`;
  }
}

function renderBanner(hexAddr, symR, secR, mapR, a2lR) {
  const banner = $('ai-banner');
  const hasAny = symR.sym || secR.reg || mapR.unit;
  banner.className = 'ai-banner ' + (hasAny ? 'found' : 'notfound');

  let parts = [`<span class="ai-addr">${hexAddr}</span>`];
  if (symR.sym) {
    const exact = symR.reason === 'found';
    const TCOL = { function:'#3b82f6', variable:'#f97316', constant:'#10b981',
                    weak:'#6366f1', other:'#374151' };
    const col = TCOL[symR.sym.type] || TCOL.other;
    parts.push(`<span class="ai-sum">→ <span class="ai-sym-name">${symR.sym.name}</span>` +
      (exact && symR.offset ? ` <span style="color:var(--dim)">+0x${symR.offset.toString(16)}</span>` : '') +
      ` <span style="color:${col};font-size:11px">${symR.sym.type}</span></span>`);
  }
  if (secR.reg) {
    parts.push(`<span style="color:var(--dim);font-size:11px">in ${secR.reg.name}` +
      (secR.elfSec ? ` / ${secR.elfSec.name}` : '') + `</span>`);
  }
  if (secR.sec && secR.sec.cacheable) {
    parts.push('<span style="color:var(--ora);font-size:11px">⚠ cacheable</span>');
  }
  if (mapR.unit) {
    parts.push(`<span style="color:var(--ora);font-size:11px">📂 ${mapR.unit.file}</span>`);
  }
  if (!hasAny) {
    parts.push('<span class="ai-sum">Address not found in any loaded data source</span>');
  }
  banner.innerHTML = parts.join(' ');
}

function renderOffsetBar(addr, sym) {
  if (!sym.size) { $('ai-offset-bar').style.display = 'none'; return; }
  $('ai-offset-bar').style.display = '';
  const pct    = Math.min(1, (addr - sym.addr) / sym.size);
  const pctPx  = Math.round(pct * 100);
  $('ai-offset-fill').style.width   = pctPx + '%';
  $('ai-offset-marker').style.left  = pctPx + '%';
  const offset = addr - sym.addr;
  $('ai-offset-labels').innerHTML =
    `<span>0x${sym.addr.toString(16).toUpperCase()} (start)</span>` +
    `<span style="color:var(--acc)">+0x${offset.toString(16)} = ${Math.round(pct*100)}%</span>` +
    `<span>0x${(sym.addr+sym.size).toString(16).toUpperCase()} (end)</span>`;
}

function renderInspectHistory() {
  const tbody = $('ai-history');
  tbody.innerHTML = '';
  S.a2lHistory.forEach(h => {
    const tr = document.createElement('tr');
    tr.className = 'clickable';
    tr.innerHTML =
      `<td class="hx">${h.addr}</td>` +
      `<td style="color:#fff;font-size:11px">${h.symName}</td>` +
      `<td class="dim" style="font-size:11px">${h.secName}</td>` +
      `<td class="dim" style="font-size:11px">${h.source}</td>`;
    tr.addEventListener('click', () => {
      $('a2l-addr').value = h.addr;
      inspectAddress();
    });
    tbody.appendChild(tr);
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
// ISSUE 5 — EXTRA SYMBOL ANALYSIS
// Additional symbol intelligence beyond duplicate detection
// ═══════════════════════════════════════════════════════════════════════════

function renderExtraSymbolAnalysis() {
  if (!S.syms.length) return;

  // ── Weak symbols with no strong override ──────────────────────────────
  const weakSyms = S.syms.filter(s => s.type === 'weak' || s.type === 'weak_obj');
  const strongNames = new Set(S.syms.filter(s => s.type === 'function' || s.type === 'variable').map(s => s.name));
  const unresolved = weakSyms.filter(s => !strongNames.has(s.name));

  // ── printf/malloc/heap usage ───────────────────────────────────────────
  const heapSigns = ['malloc','free','calloc','realloc','_malloc_r','_sbrk',
                     'printf','fprintf','sprintf','snprintf','puts','scanf'];
  const heapSyms = S.syms.filter(s => heapSigns.includes(s.name));

  // ── Interrupt handlers (ISR detection) ───────────────────────────────
  const isrPatterns = [/^[A-Z][A-Za-z0-9_]+_IRQHandler$/, /^[A-Z][A-Za-z0-9_]+_Handler$/,
                       /^SysTick/, /^HardFault/, /^NMI_/, /^PendSV/];
  const isrSyms = S.syms.filter(s => s.type === 'function'
    && isrPatterns.some(p => p.test(s.name)));

  // ── Section size contribution per file (from map) ─────────────────────
  // (already in map file tab — cross-reference here)

  // Expose via bloat content area as extra cards
  const bloatContent = $('bloat-content');
  if (!bloatContent) return;

  // Remove old extra cards
  document.querySelectorAll('.extra-sym-card').forEach(e => e.remove());

  const makeCard = (title, subtitle, rows, clickCb) => {
    const card = document.createElement('div');
    card.className = 'card-wrap extra-sym-card';
    let rowsHtml = rows.slice(0,20).map(r =>
      `<tr class="clickable" data-sym-name="${r.name}" data-sym-addr="${r.addr}">
        <td style="color:var(--acc);font-size:11px">${r.name}</td>
        <td class="hx">${hx(r.addr)}</td>
        <td class="sz">${r.size ? fz(r.size) : '—'}</td>
        <td class="dim" style="font-size:10px">${r.file||r.section||'—'}</td>
       </tr>`).join('');
    card.innerHTML = `<div class="tbl-hdr">${title}<span class="sub">${subtitle}</span></div>
      <table><thead><tr><th>Name</th><th>Address</th><th>Size</th><th>File/Section</th></tr></thead>
      <tbody>${rowsHtml||'<tr><td colspan="4" style="color:var(--dim);padding:10px">None found</td></tr>'}</tbody></table>`;
    card.querySelectorAll('tr[data-sym-name]').forEach(tr => {
      tr.addEventListener('click', () => {
        const sym = findSymbol(tr.dataset.symName, parseInt(tr.dataset.symAddr));
        if (sym) openSymbolPopup(sym);
      });
    });
    return card;
  };

  if (unresolved.length) {
    bloatContent.appendChild(makeCard(
      '⚠ Weak symbols with no strong definition',
      'these use the weak fallback — may be intentional or a missing implementation',
      unresolved
    ));
  }

  if (heapSyms.length) {
    bloatContent.appendChild(makeCard(
      '🧱 Dynamic memory / printf family',
      'linked symbols that indicate heap or formatted I/O usage',
      heapSyms
    ));
  }

  if (isrSyms.length) {
    bloatContent.appendChild(makeCard(
      '⚡ Interrupt handlers',
      'ISR functions — candidates for ITCM placement for fast response',
      isrSyms.sort((a,b) => b.size - a.size)
    ));
  }
}

// =============================================================================
// STACK DEPTH ANALYSIS
// =============================================================================
//
// This tab supports two levels of analysis depending on which GCC flags
// were used during the build:
//
//   Level 1 — .su only (needs -fstack-usage)
//     • Per-function stack frame size
//     • Static / dynamic / dynamic-bounded classification
//     • Sorted list with bar chart
//     • Unbounded frame warning
//
//   Level 2 — .su + .ci (needs -fstack-usage AND -fcallgraph-info=su,da)
//     • Everything from Level 1 PLUS:
//     • Worst-case stack depth across the full call chain
//     • "IpcMaster_Task calls BswSpi_Exchange calls LPSPI_DRV_MasterTransfer"
//     • Recursive function detection
//     • Top-N deepest call chains with path visualisation
//
// HOW TO ENABLE (S32DS / arm-none-eabi-gcc):
//   Project → Properties → C/C++ Build → Settings →
//   Compiler → Miscellaneous → Other flags, add:
//     -fstack-usage -fcallgraph-info=su,da -Wstack-usage=256
//
//   Then use the scan feature to point at the Debug/ or Release/ build folder.
//   The tool finds all .su and .ci files automatically across all subfolders.
//
// WHY WORST-CASE MATTERS (embedded engineer note):
//   Each FreeRTOS task needs a stack large enough for its deepest call chain.
//   .su alone gives "IpcMaster_Task frame = 64 bytes".
//   .ci tells you "IpcMaster_Task → BswSpi_Exchange → LPSPI_DRV_MasterTransfer
//   total = 64 + 8 + 32 + 4 + 128 = 236 bytes".
//   Without this, you're guessing task stack sizes — common cause of stack overflow.
// =============================================================================

// ── Shared state ─────────────────────────────────────────────────────────────

const SU_DATA = {
    entries:      [],   // {func, file, line, size, type}  — from .su files
    loadedFiles:  [],   // {name, count}                   — files loaded so far
    scanResults:  null, // full scan response from /scan_su
    ciContents:   [],   // {name, content}                 — raw .ci file text
    cgResult:     null, // result from /analyse_callgraph
    filtered:     [],
    sortCol: 'worst_case', sortDir: -1,  // default sort: worst-case depth
};

// ── Drop zone wiring ──────────────────────────────────────────────────────────

/**
 * Called from DOMContentLoaded in index.html.
 * Wires up the .su / .ci file drop zone and click-to-browse.
 * Inputs are display:none siblings — no CSS overlay tricks needed.
 */
function initStackDrop() {
    const div = document.getElementById('su-drop');
    const inp = document.getElementById('su-fi');
    if (!div || !inp) { console.warn('[stack] su-drop or su-fi not found'); return; }

    div.addEventListener('dragover',  e => { e.preventDefault(); div.classList.add('over'); });
    div.addEventListener('dragleave', ()  => div.classList.remove('over'));
    div.addEventListener('drop', e => {
        e.preventDefault(); div.classList.remove('over');
        loadSUFiles(Array.from(e.dataTransfer.files));
    });
    // Click anywhere on the div opens the file picker
    div.addEventListener('click', e => { if (e.target !== inp) inp.click(); });
    inp.addEventListener('change', e => {
        loadSUFiles(Array.from(e.target.files));
        inp.value = '';   // allow re-selecting the same file
    });
}

// ── File loading (drag-and-drop or file picker) ───────────────────────────────

/**
 * Process files dropped or selected by the user.
 * Accepts any mix of .su and .ci files in one drop.
 * Calling this again adds to existing data (does not replace it).
 */
function loadSUFiles(files) {
    const suFiles = files.filter(f => f.name.endsWith('.su'));
    const ciFiles = files.filter(f => f.name.endsWith('.ci'));

    if (!suFiles.length && !ciFiles.length) {
        suScanStatus('No .su or .ci files found. Drop files from your GCC build output directory.');
        return;
    }

    const total = suFiles.length + ciFiles.length;
    let done = 0;

    const onAllLoaded = () => {
        done++;
        if (done === total) {
            updateSUDropLabel();
            if (SU_DATA.ciContents.length) {
                runCallgraphAnalysis();   // .ci present → compute worst-case chains
            } else {
                renderStackDepth();       // .su only → render frame sizes
            }
        }
    };

    suFiles.forEach(file => {
        readText(file, text => {
            const count = parseSUFile(file.name, text);
            upsertLoadedFile(file.name, count);
            onAllLoaded();
        });
    });

    ciFiles.forEach(file => {
        readText(file, text => {
            // Upsert: replace if same file re-dropped
            const idx = SU_DATA.ciContents.findIndex(c => c.name === file.name);
            if (idx >= 0) SU_DATA.ciContents[idx] = { name: file.name, content: text };
            else          SU_DATA.ciContents.push(  { name: file.name, content: text });
            onAllLoaded();
        });
    });
}

function readText(file, cb) {
    const r = new FileReader();
    r.onload  = e => cb(e.target.result);
    r.onerror = () => suScanStatus('Failed to read ' + file.name);
    r.readAsText(file);
}

// ── Directory scan ────────────────────────────────────────────────────────────

/**
 * Send the typed directory path to the server.
 * Server walks the ENTIRE tree (all subdirectories) and returns all
 * .su, .ci, .d, .o files it finds.
 *
 * The server route uses os.walk() which Python documents as:
 *   "For each directory in the tree rooted at top (including top itself),
 *    it yields a 3-tuple (dirpath, dirnames, filenames)."
 * This means ALL subdirectories are searched automatically.
 */
async function scanSUPath() {
    const pathEl  = document.getElementById('su-path');
    const path = (pathEl ? pathEl.value : '').trim();
    if (!path) { suScanStatus('Enter a directory path first'); return; }

    suScanStatus('Scanning all subdirectories…');
    document.getElementById('su-picker').style.display = 'none';

    try {
        const fd = new FormData();
        fd.append('path', path);
        const res = await fetch('/scan_su', { method: 'POST', body: fd });
        const d   = await res.json();

        if (d.error) {
            suScanStatus('Error: ' + d.error + (d.hint ? ' — ' + d.hint : ''));
            return;
        }

        SU_DATA.scanResults = d;

        // Show what was found before the picker
        renderScanSummary(d);

        if (d.has_su || d.has_ci) {
            renderSUPicker(d);
        }
    } catch(e) {
        suScanStatus('Network error: ' + e.message);
    }
}

/**
 * Display a colour-coded summary of what the scan found.
 * This tells the user clearly whether they have full or partial analysis.
 */
function renderScanSummary(d) {
    const status = document.getElementById('su-scan-status');

    const icons = { full: '✅', partial: '⚠️', none: '❌' };
    const cols  = { full: 'var(--grn)', partial: 'var(--ora)', none: 'var(--red)' };

    let html = `<span style="color:${cols[d.level]}">${icons[d.level]} ${d.summary}</span>`;

    if (d.level === 'partial') {
        html += `<br><span style="color:var(--dim);font-size:10px">
            Add <code style="color:var(--acc)">-fcallgraph-info=su,da</code> to GCC flags
            for worst-case call-chain analysis, then rebuild.</span>`;
    } else if (d.level === 'none') {
        html += `<br><span style="color:var(--dim);font-size:10px">
            Add <code style="color:var(--acc)">-fstack-usage</code> to GCC flags
            and rebuild. Files go in the same directory as your .o files.</span>`;
    }

    if (d.has_su && d.has_ci && d.matched > 0) {
        html += `<br><span style="color:var(--dim);font-size:10px">
            ${d.matched} matched .su/.ci pairs — full worst-case depth available.</span>`;
    }

    status.innerHTML = html;
}

/**
 * Render the file picker list.
 * Files are grouped by subdirectory for readability.
 * .ci files are shown alongside their matching .su file.
 */
function renderSUPicker(d) {
    const picker = document.getElementById('su-picker');
    const list   = document.getElementById('su-picker-list');
    const title  = document.getElementById('su-picker-title');

    const suCount = d.su_files.length;
    const ciCount = d.ci_files.length;

    title.textContent =
        suCount + ' .su' + (ciCount ? ' + ' + ciCount + ' .ci' : '') +
        ' files found across all subdirectories';

    list.innerHTML = '';

    // Group files by directory for easier navigation
    const dirs = {};
    d.su_files.forEach(f => {
        if (!dirs[f.dir]) dirs[f.dir] = { su: [], ci: [] };
        dirs[f.dir].su.push(f);
    });
    d.ci_files.forEach(f => {
        if (!dirs[f.dir]) dirs[f.dir] = { su: [], ci: [] };
        dirs[f.dir].ci.push(f);
    });

    // Initialise selected state on scanResults
    SU_DATA.scanResults.su_files.forEach(f => { if (f.selected === undefined) f.selected = true; });
    SU_DATA.scanResults.ci_files.forEach(f => { if (f.selected === undefined) f.selected = true; });

    // Render one group per directory
    Object.keys(dirs).sort().forEach(dir => {
        const group = dirs[dir];

        // Directory header row
        const hdr = document.createElement('div');
        hdr.style.cssText = 'padding:5px 6px 2px;font-size:10px;color:var(--acc);' +
            'font-weight:600;border-top:1px solid var(--bdr);margin-top:4px';
        hdr.textContent = dir;
        list.appendChild(hdr);

        // .su file rows
        group.su.forEach(f => {
            const hasCi = dirs[dir].ci.some(c => c.stem === f.stem);
            const row = makePickerRow(
                f, 'su', hasCi ? '🔗' : '📄',
                hasCi ? 'Matched .ci found — worst-case analysis available' : '',
                SU_DATA.scanResults.su_files
            );
            list.appendChild(row);
        });

        // .ci-only rows (ci with no matching .su — unusual but possible)
        group.ci.filter(c => !dirs[dir].su.some(s => s.stem === c.stem)).forEach(f => {
            const row = makePickerRow(f, 'ci', '📊', 'Call graph only — no .su match', SU_DATA.scanResults.ci_files);
            list.appendChild(row);
        });
    });

    picker.style.display = '';
}

function makePickerRow(f, ext, icon, hint, listRef) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 6px;' +
        'border-radius:4px;cursor:pointer;transition:.1s';
    row.innerHTML =
        `<input type="checkbox" ${f.selected ? 'checked' : ''} style="accent-color:var(--acc);flex-shrink:0">` +
        `<span style="font-size:10px;color:${ext==='ci'?'var(--ora)':'var(--acc)'};flex-shrink:0">${icon}</span>` +
        `<span style="font-size:11px;color:#fff;flex-shrink:0">${f.name}</span>` +
        `<span style="font-size:10px;color:var(--dim);flex-grow:1">${hint}</span>` +
        `<span style="font-size:10px;color:var(--dim);flex-shrink:0">${(f.size/1024).toFixed(1)}KB</span>`;

    row.addEventListener('mouseenter', () => row.style.background = 'var(--s2)');
    row.addEventListener('mouseleave', () => row.style.background = '');

    const cb = row.querySelector('input');
    const toggle = () => {
        f.selected = !f.selected; cb.checked = f.selected;
    };
    cb.addEventListener('change', () => { f.selected = cb.checked; });
    row.addEventListener('click', e => { if (e.target !== cb) toggle(); });
    return row;
}

function suPickerSelectAll() {
    if (!SU_DATA.scanResults) return;
    SU_DATA.scanResults.su_files.forEach(f => f.selected = true);
    SU_DATA.scanResults.ci_files.forEach(f => f.selected = true);
    renderSUPicker(SU_DATA.scanResults);
}
function suPickerSelectNone() {
    if (!SU_DATA.scanResults) return;
    SU_DATA.scanResults.su_files.forEach(f => f.selected = false);
    SU_DATA.scanResults.ci_files.forEach(f => f.selected = false);
    renderSUPicker(SU_DATA.scanResults);
}

/**
 * Load the files the user selected from the picker.
 * Sends paths to the server which reads them — browser never needs filesystem access.
 */
async function loadSelectedSU() {
    if (!SU_DATA.scanResults) return;
    const selSU = SU_DATA.scanResults.su_files.filter(f => f.selected);
    const selCI = SU_DATA.scanResults.ci_files.filter(f => f.selected);

    if (!selSU.length && !selCI.length) {
        alert('Select at least one file from the list'); return;
    }

    const btn = document.querySelector('[onclick="loadSelectedSU()"]');
    if (btn) { btn.textContent = 'Loading…'; btn.disabled = true; }
    suScanStatus('Loading ' + (selSU.length + selCI.length) + ' files…');

    try {
        const allPaths = [
            ...selSU.map(f => ({ path: f.path, type: 'su', name: f.name })),
            ...selCI.map(f => ({ path: f.path, type: 'ci', name: f.name })),
        ];

        const fd = new FormData();
        fd.append('paths', JSON.stringify(allPaths.map(f => f.path)));
        const res = await fetch('/load_su_files', { method: 'POST', body: fd });
        const d   = await res.json();

        if (d.error) { suScanStatus('Error: ' + d.error); return; }

        // Distribute loaded contents into .su and .ci buckets
        d.files.forEach(f => {
            if (f.name.endsWith('.su')) {
                const count = parseSUFile(f.name, f.content);
                upsertLoadedFile(f.name, count);
            } else if (f.name.endsWith('.ci')) {
                const idx = SU_DATA.ciContents.findIndex(c => c.name === f.name);
                if (idx >= 0) SU_DATA.ciContents[idx] = { name: f.name, content: f.content };
                else          SU_DATA.ciContents.push(  { name: f.name, content: f.content });
            }
        });

        document.getElementById('su-picker').style.display = 'none';
        updateSUDropLabel();

        if (d.errors && d.errors.length) {
            suScanStatus('Loaded with ' + d.errors.length + ' errors: ' + d.errors[0]);
        } else {
            suScanStatus('');
        }

        if (SU_DATA.ciContents.length) {
            await runCallgraphAnalysis();
        } else {
            renderStackDepth();
        }
    } catch(e) {
        suScanStatus('Load failed: ' + e.message);
    } finally {
        if (btn) { btn.textContent = '▶ Load selected'; btn.disabled = false; }
    }
}

// ── .su file parsing ──────────────────────────────────────────────────────────

/**
 * Parse one GCC .su file.
 *
 * GCC .su format (one line per function):
 *   path/to/source.c:lineNo:colNo:functionName   frameBytes   frameType
 *
 * frameType is one of:
 *   static           — known at compile time, reliable
 *   dynamic          — uses alloca() or VLAs, UNBOUNDED, investigate
 *   dynamic,bounded  — dynamic but compiler proved an upper bound exists
 *
 * EMBEDDED ENGINEER NOTE:
 *   Only "static" frames can be safely summed for worst-case stack calculation.
 *   "dynamic" frames are a red flag — they can grow without bound at runtime.
 *
 * Returns: count of functions parsed
 */
function parseSUFile(filename, content) {
    const slash = Math.max(filename.lastIndexOf('/'), filename.lastIndexOf('\\'));
    const shortName = slash >= 0 ? filename.slice(slash + 1) : filename;
    let count = 0;

    for (const line of content.split('\n')) {
        // Match: "path/file.c:NN:NN:funcName   NNN   type"
        const m = line.match(/^([^:]+):(\d+):\d+:(\S+)\s+(\d+)\s+(\S+)/);
        if (!m) continue;

        const entry = {
            file: shortName,
            line: parseInt(m[2]),
            func: m[3],
            size: parseInt(m[4]),
            // Normalise "dynamic,bounded" → "dynamic bounded" for easier display
            type: m[5].replace(',', ' '),
        };

        // Upsert: update existing entry if the same file is re-loaded
        const idx = SU_DATA.entries.findIndex(
            e => e.func === entry.func && e.file === shortName
        );
        if (idx >= 0) SU_DATA.entries[idx] = entry;
        else          SU_DATA.entries.push(entry);
        count++;
    }
    return count;
}

// ── Callgraph analysis (Level 2) ──────────────────────────────────────────────

/**
 * Send loaded .ci contents to the server for worst-case stack computation.
 * The server uses callgraph_parser.py to run DFS over the call graph.
 * Results are merged back into the UI alongside the .su frame sizes.
 */
async function runCallgraphAnalysis() {
    suScanStatus('Computing worst-case call chains…');
    try {
        const fd = new FormData();
        fd.append('ci_contents', JSON.stringify(SU_DATA.ciContents));
        fd.append('su_entries',  JSON.stringify(SU_DATA.entries));
        const res = await fetch('/analyse_callgraph', { method: 'POST', body: fd });
        const d   = await res.json();

        if (d.error) {
            suScanStatus('Callgraph error: ' + d.error);
            // Still show .su data even if .ci analysis failed
            renderStackDepth();
            return;
        }

        SU_DATA.cgResult = d;
        suScanStatus('');
        renderStackDepth();
    } catch(e) {
        suScanStatus('Callgraph request failed: ' + e.message);
        renderStackDepth();
    }
}

// ── Rendering ─────────────────────────────────────────────────────────────────

/**
 * Main render function for the Stack Depth tab.
 * Adapts its output based on what data is available:
 *   - .su only  → shows frame sizes, flags unbounded frames
 *   - .su + .ci → additionally shows worst-case totals and call chains
 */
function renderStackDepth() {
    if (!SU_DATA.entries.length) return;

    $('stack-content').style.display = '';

    const entries    = SU_DATA.entries;
    const cg         = SU_DATA.cgResult;   // null if no .ci files
    const hasCG      = cg !== null;

    // ── Stats cards ─────────────────────────────────────────────────────
    const totalFuncs   = entries.length;
    const unbounded    = entries.filter(e => e.type.includes('dynamic') && !e.type.includes('bounded'));
    const maxFrame     = Math.max(...entries.map(e => e.size), 0);
    const maxWorstCase = hasCG
        ? Math.max(...Object.values(cg.worst_case).map(v => v.worst_case), 0)
        : maxFrame;

    $('stack-stats').innerHTML = `
        <div class="stat">
            <div class="snum">${totalFuncs}</div>
            <div class="slbl">Functions analysed</div>
        </div>
        <div class="stat">
            <div class="snum" style="color:var(--grn)">${maxFrame}</div>
            <div class="slbl">Largest single frame<br>(bytes, .su data)</div>
        </div>
        ${hasCG ? `<div class="stat">
            <div class="snum" style="color:var(--acc)">${maxWorstCase}</div>
            <div class="slbl">Worst-case call chain<br>(bytes, .ci data)</div>
        </div>` : `<div class="stat" style="opacity:0.5">
            <div class="snum">—</div>
            <div class="slbl">Worst-case chain<br>add -fcallgraph-info=su,da</div>
        </div>`}
        <div class="stat">
            <div class="snum" style="color:${unbounded.length ? 'var(--red)' : 'var(--grn)'}">
                ${unbounded.length}
            </div>
            <div class="slbl">Unbounded dynamic frames<br>${unbounded.length ? '⚠ investigate' : '✓ none'}</div>
        </div>
        ${hasCG && cg.has_recursive ? `<div class="stat">
            <div class="snum" style="color:var(--ora)">⟳</div>
            <div class="slbl">Recursive calls detected<br>stack depth is unbounded</div>
        </div>` : ''}`;

    // ── Callgraph top-N panel (only when .ci data available) ─────────────
    const cgPanel = $('stack-cg-panel');
    if (cgPanel) {
        if (hasCG && cg.top_worst && cg.top_worst.length) {
            cgPanel.style.display = '';
            const tbody = $('stack-cg-tbody');
            tbody.innerHTML = '';
            const absMax = cg.top_worst[0].worst_case || 1;
            cg.top_worst.forEach(item => {
                const pct = Math.round(item.worst_case / absMax * 100);
                const tr = document.createElement('tr');
                tr.className = 'clickable';
                // Show call chain as "A → B → C"
                const chain = item.path.join(' → ');
                tr.innerHTML = `
                    <td style="font-size:11px;color:#fff">${item.func}</td>
                    <td>
                        <span class="sz" style="margin-right:6px">${item.worst_case}</span>
                        <div class="fill-bg" style="width:80px;display:inline-block">
                            <div class="fill-bar" style="width:${pct * 0.8}px;background:${
                                item.worst_case > 1024 ? 'var(--red)' :
                                item.worst_case > 512  ? 'var(--ora)' : 'var(--grn)'
                            }"></div>
                        </div>
                    </td>
                    <td class="sz">${item.frame}</td>
                    <td style="font-size:10px;color:var(--dim);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                        title="${chain}">${chain}</td>
                    <td>${item.recursive
                        ? '<span class="stack-type-badge stack-dynamic">recursive</span>' : ''}</td>`;
                tr.addEventListener('click', () => {
                    // Cross-tab: open symbol popup if ELF is loaded
                    const sym = findSymbol(item.func, null);
                    if (sym) openSymbolPopup(sym);
                    else {
                        // Fall back to address inspector
                        $('a2l-addr').value = item.func;
                        switchTab('a2l');
                    }
                });
                tbody.appendChild(tr);
            });
        } else {
            cgPanel.style.display = 'none';
        }
    }

    // ── Unbounded warning card ────────────────────────────────────────────
    const ubCard = $('stack-unbounded-card');
    ubCard.style.display = unbounded.length ? '' : 'none';
    const ubBody = $('stack-unbounded');
    ubBody.innerHTML = '';
    unbounded.forEach(e => {
        const tr = document.createElement('tr');
        tr.className = 'stack-unbounded-row clickable';
        tr.innerHTML = `<td style="font-size:11px">${e.func}</td>
            <td class="dim" style="font-size:11px">${e.file}:${e.line}</td>`;
        tr.addEventListener('click', () => {
            const sym = findSymbol(e.func, null);
            if (sym) openSymbolPopup(sym);
        });
        ubBody.appendChild(tr);
    });

    filterStack();
}

function filterStack() {
    const q   = ($('stack-q')?.value   || '').toLowerCase();
    const typ = $('stack-type')?.value || '';
    SU_DATA.filtered = SU_DATA.entries.filter(e => {
        if (q   && !e.func.toLowerCase().includes(q)
                && !e.file.toLowerCase().includes(q)) return false;
        if (typ && !e.type.includes(typ)) return false;
        return true;
    });
    sortAndRenderStack();
}

function sortStack(col) {
    // When sorting by worst_case but no .ci data, fall back to size
    if (col === 'worst_case' && !SU_DATA.cgResult) col = 'size';
    if (SU_DATA.sortCol === col) SU_DATA.sortDir *= -1;
    else { SU_DATA.sortCol = col; SU_DATA.sortDir = -1; }
    sortAndRenderStack();
}

function sortAndRenderStack() {
    const { sortCol: col, sortDir: dir } = SU_DATA;
    const cg = SU_DATA.cgResult;

    const sorted = [...SU_DATA.filtered].sort((a, b) => {
        let va, vb;
        if (col === 'size') {
            va = a.size; vb = b.size;
        } else if (col === 'worst_case') {
            // Merge .ci worst-case into sort value; fall back to .su frame size
            va = cg?.worst_case[a.func]?.worst_case ?? a.size;
            vb = cg?.worst_case[b.func]?.worst_case ?? b.size;
        } else {
            va = a[col] || ''; vb = b[col] || '';
        }
        return (typeof va === 'number' ? va - vb : va.toString().localeCompare(vb.toString())) * dir;
    });

    $('stack-cnt').textContent = `${sorted.length} / ${SU_DATA.entries.length}`;

    const tbody   = $('stack-tbody');
    tbody.innerHTML = '';
    const maxSize = Math.max(...SU_DATA.entries.map(e => e.size), 1);
    const hasCG   = !!cg;

    sorted.slice(0, 500).forEach(e => {
        const typeClass =
            e.type.includes('dynamic') && !e.type.includes('bounded') ? 'stack-dynamic' :
            e.type.includes('bounded')                                  ? 'stack-bounded' :
                                                                          'stack-static';
        const barW = Math.round(e.size / maxSize * 80);
        const wc   = hasCG ? cg.worst_case[e.func] : null;
        const wcStr = wc ? `${wc.worst_case}` : '—';
        const wcCol = !wc ? 'var(--dim)' :
                      wc.worst_case > 1024 ? 'var(--red)' :
                      wc.worst_case > 512  ? 'var(--ora)' : 'var(--grn)';
        const chainStr = wc && wc.path.length > 1
            ? wc.path.slice(1).join(' → ')
            : '';

        const tr = document.createElement('tr');
        tr.className = 'clickable';
        tr.innerHTML = `
            <td style="font-size:11px;color:#fff">${e.func}</td>
            <td>
                <span class="sz" style="margin-right:6px">${e.size}</span>
                <div class="fill-bg" style="width:80px;display:inline-block">
                    <div class="fill-bar" style="width:${barW}px;background:${
                        e.size > 1024 ? 'var(--red)' : e.size > 256 ? 'var(--ora)' : 'var(--grn)'
                    }"></div>
                </div>
            </td>
            <td style="color:${wcCol};font-weight:${wc?'600':'400'}">${wcStr}</td>
            <td><span class="stack-type-badge ${typeClass}">${e.type}</span></td>
            <td class="dim" style="font-size:10px">${e.file}:${e.line}</td>
            <td style="font-size:10px;color:var(--dim);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                title="${chainStr}">${chainStr}</td>`;

        tr.addEventListener('click', () => {
            // Link to ELF symbol popup when ELF is loaded
            const sym = findSymbol(e.func, null);
            if (sym) openSymbolPopup(sym);
            else {
                // Link to stack depth tab isn't circular — click opens symbol search
                $('sym-q').value = e.func;
                filterSyms();
                switchTab('sym');
            }
        });
        tbody.appendChild(tr);
    });
}

function exportStackCSV() {
    const hasCG = !!SU_DATA.cgResult;
    const lines = ['Function,Frame bytes,Worst-case bytes,Type,File,Line,Call chain'];
    SU_DATA.filtered.forEach(e => {
        const wc = hasCG ? SU_DATA.cgResult.worst_case[e.func] : null;
        lines.push(`"${e.func}","${e.size}","${wc ? wc.worst_case : ''}","${e.type}","${e.file}","${e.line}","${wc ? wc.path.join(' → ') : ''}"`);
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    a.download = 'stack_usage.csv';
    a.click();
}

// ── State management helpers ──────────────────────────────────────────────────

function upsertLoadedFile(name, count) {
    const ex = SU_DATA.loadedFiles.find(f => f.name === name);
    if (ex) ex.count = count;
    else    SU_DATA.loadedFiles.push({ name, count });
}

function updateSUDropLabel() {
    const n = SU_DATA.loadedFiles.length;
    const total = SU_DATA.entries.length;
    const ci    = SU_DATA.ciContents.length;

    const lblEl = document.getElementById('su-drop-label');
    if (lblEl) lblEl.textContent =
        `${n} .su${ci ? ' + ' + ci + ' .ci' : ''} file${n !== 1 ? 's' : ''} loaded` +
        ` (${total} functions) — drop more to add`;

    const cntEl = document.getElementById('su-file-count');
    if (cntEl) cntEl.textContent = `${n} file${n !== 1 ? 's' : ''}${ci ? ' + ' + ci + ' .ci' : ''}`;

    const clrBtn = document.getElementById('su-clear-btn');
    if (clrBtn) clrBtn.style.display = '';

    // Update loaded file chips
    const listEl  = document.getElementById('su-loaded-list');
    const itemsEl = document.getElementById('su-loaded-items');
    if (listEl && itemsEl) {
        listEl.style.display = '';
        itemsEl.innerHTML = '';
        SU_DATA.loadedFiles.forEach(f => {
            const chip = document.createElement('div');
            chip.style.cssText = 'display:flex;align-items:center;gap:5px;background:var(--s2);' +
                'border:1px solid var(--bdr);border-radius:4px;padding:2px 8px;font-size:11px;' +
                'color:#8b949e';
            chip.innerHTML = `<span>${f.name}</span>` +
                `<span style="color:var(--dim)">(${f.count})</span>` +
                `<span style="cursor:pointer;color:var(--dim)" title="Remove this file">✕</span>`;
            chip.querySelector('span:last-child').addEventListener('click', () => removeSUFile(f.name));
            itemsEl.appendChild(chip);
        });
        // Show .ci chips too
        SU_DATA.ciContents.forEach(f => {
            const chip = document.createElement('div');
            chip.style.cssText = 'display:flex;align-items:center;gap:5px;background:var(--s2);' +
                'border:1px solid #5a3010;border-radius:4px;padding:2px 8px;font-size:11px;color:var(--ora)';
            chip.innerHTML = `<span>📊 ${f.name}</span>` +
                `<span style="cursor:pointer;color:var(--dim)" title="Remove .ci file">✕</span>`;
            chip.querySelector('span:last-child').addEventListener('click', () => removeCIFile(f.name));
            itemsEl.appendChild(chip);
        });
    }
}

function removeSUFile(filename) {
    SU_DATA.entries     = SU_DATA.entries.filter(e => e.file !== filename);
    SU_DATA.loadedFiles = SU_DATA.loadedFiles.filter(f => f.name !== filename);
    if (SU_DATA.loadedFiles.length) {
        updateSUDropLabel();
        SU_DATA.cgResult = null;  // invalidate callgraph — frame data changed
        if (SU_DATA.ciContents.length) runCallgraphAnalysis();
        else renderStackDepth();
    } else {
        clearSUData();
    }
}

function removeCIFile(filename) {
    SU_DATA.ciContents = SU_DATA.ciContents.filter(c => c.name !== filename);
    SU_DATA.cgResult   = null;
    updateSUDropLabel();
    if (SU_DATA.ciContents.length) runCallgraphAnalysis();
    else renderStackDepth();
}

function clearSUData() {
    SU_DATA.entries      = [];
    SU_DATA.filtered     = [];
    SU_DATA.loadedFiles  = [];
    SU_DATA.scanResults  = null;
    SU_DATA.ciContents   = [];
    SU_DATA.cgResult     = null;

    ['stack-content','su-loaded-list','su-picker'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    const clr = document.getElementById('su-clear-btn');
    if (clr) clr.style.display = 'none';
    const cnt = document.getElementById('su-file-count');
    if (cnt) cnt.textContent = '';
    const lbl = document.getElementById('su-drop-label');
    if (lbl) lbl.textContent = 'Drop .su or .ci files here (multiple OK) — or click to browse';
    suScanStatus('');
}

function suScanStatus(msg) {
    const el = document.getElementById('su-scan-status');
    if (el) el.innerHTML = msg;
}

// =============================================================================
// CI FORMAT DEBUGGER
// =============================================================================
// The GCC -fcallgraph-info=su,da format is not well-documented.
// This tool shows the raw parsed result so we can verify the parser.
// =============================================================================

function toggleCIDebug() {
    const body = document.getElementById('ci-debug-body');
    if (body) body.style.display = body.style.display === 'none' ? '' : 'none';
}

async function inspectCIFormat() {
    const text = (document.getElementById('ci-sample-text')?.value || '').trim();
    const out  = document.getElementById('ci-debug-out');
    if (!text) { if (out) out.textContent = 'Paste some .ci content first'; return; }

    if (out) out.textContent = 'Sending to server…';

    try {
        const fd = new FormData();
        fd.append('content', text);
        const res = await fetch('/debug_ci', { method: 'POST', body: fd });
        const d   = await res.json();

        if (d.error) { if (out) out.textContent = 'Error: ' + d.error; return; }

        // Show the raw lines so we can see the actual format
        let report = `Total lines in sample: ${d.total_lines}\n\n`;
        report += `First ${Math.min(60, d.sample.length)} lines:\n`;
        report += '─'.repeat(60) + '\n';
        d.sample.forEach((line, i) => {
            report += `${String(i+1).padStart(3,'0')}: ${line}\n`;
        });
        report += '\n─'.repeat(60) + '\n';
        report += 'Copy the above and send to the developer so the parser can be fixed.\n';
        report += 'GitHub issue / email: include file name and GCC version (arm-none-eabi-gcc --version)';

        if (out) out.textContent = report;
    } catch(e) {
        if (out) out.textContent = 'Request failed: ' + e.message;
    }
}
