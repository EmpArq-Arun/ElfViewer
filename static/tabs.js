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
