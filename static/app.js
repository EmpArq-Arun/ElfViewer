// ========================================================================
// STATE.JS
// ========================================================================


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


// ========================================================================
// UTILS.JS
// ========================================================================

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
// tip element accessed lazily via getTip()
function getTip(){return document.getElementById('tip');}
function addTip(el,info){
  el.addEventListener('mouseenter',e=>{
    let h=`<div class="tn">${info.name}</div>`;
    (info.rows||[]).forEach(([k,v])=>h+=`<div class="tr2"><span>${k}</span><span class="tv">${v}</span></div>`);
    if(info.desc)h+=`<div class="tdesc">${info.desc}</div>`;
    getTip().innerHTML=h;getTip().classList.add('on');tipPos(e);
  });
  el.addEventListener('mousemove',tipPos);
  el.addEventListener('mouseleave',()=>getTip().classList.remove('on'));
}
function tipPos(e){
  const x=e.clientX+14,y=e.clientY+10;
  const w=tip.offsetWidth||260,h=tip.offsetHeight||100;
  getTip().style.left=Math.min(x,innerWidth-w-8)+'px';
  getTip().style.top=Math.min(y,innerHeight-h-8)+'px';
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
function download(name,content){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([content],{type:'text/csv'}));
  a.download=name;a.click();
}

// ── Init moved to DOMContentLoaded in index.html ──────────────────────────
// (loadFeatureState and buildFeaturesPanel called there, after all scripts load)

// ========================================================================
// TABS.JS
// ========================================================================

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

// ═══════════════════════════════════════════════════════════════════════════
// ISSUE 6 — STACK DEPTH (.su file parsing)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// STACK DEPTH — .su file management
// ═══════════════════════════════════════════════════════════════════════════

const SU_DATA = {
  entries:   [],       // all parsed entries across all loaded files
  filtered:  [],
  loadedFiles: [],     // {name, count} — files successfully loaded
  scanResults: [],     // [{path, name, selected}] — from server scan
  sortCol: 'size', sortDir: -1
};

// ── Initialise drop zone (called from DOMContentLoaded) ───────────────────
function initStackDrop() {
  const div = document.getElementById('su-drop');
  const inp = document.getElementById('su-fi');
  if (!div || !inp) return;

  div.addEventListener('dragover',  e => { e.preventDefault(); div.classList.add('over'); });
  div.addEventListener('dragleave', () => div.classList.remove('over'));
  div.addEventListener('drop', e => {
    e.preventDefault(); div.classList.remove('over');
    loadSUFiles(Array.from(e.dataTransfer.files));
  });
  div.addEventListener('click', e => { if (e.target !== inp) inp.click(); });
  inp.addEventListener('change', e => {
    loadSUFiles(Array.from(e.target.files));
    inp.value = '';   // reset so same file can be re-added
  });
}

// ── Load files from browser drop / picker ────────────────────────────────
function loadSUFiles(files) {
  const suFiles = files.filter(f => f.name.endsWith('.su'));
  if (!suFiles.length) {
    document.getElementById('su-scan-status').textContent =
      'No .su files found — make sure GCC -fstack-usage flag is enabled';
    return;
  }

  let loaded = 0;
  suFiles.forEach(file => {
    const reader = new FileReader();
    reader.onload = e => {
      const count = parseSUFile(file.name, e.target.result);
      // Track which files are loaded
      const existing = SU_DATA.loadedFiles.find(f => f.name === file.name);
      if (existing) existing.count = count;
      else SU_DATA.loadedFiles.push({ name: file.name, count });
      loaded++;
      if (loaded === suFiles.length) {
        updateSUDropLabel();
        renderStackDepth();
      }
    };
    reader.readAsText(file);
  });
}

// ── Path scan — server-side directory walk ───────────────────────────────
async function scanSUPath() {
  const pathInput = document.getElementById('su-path');
  const status    = document.getElementById('su-scan-status');
  const path = pathInput.value.trim();
  if (!path) { status.textContent = 'Enter a directory path first'; return; }

  status.textContent = 'Scanning…';
  document.getElementById('su-picker').style.display = 'none';

  try {
    const fd = new FormData();
    fd.append('path', path);
    const res = await fetch('/scan_su', { method: 'POST', body: fd });
    const d   = await res.json();

    if (d.error) { status.textContent = 'Error: ' + d.error; return; }
    if (!d.files || !d.files.length) {
      status.textContent = 'No .su files found in that directory. Check the path and rebuild with -fstack-usage.';
      return;
    }

    SU_DATA.scanResults = d.files.map(f => ({ ...f, selected: true }));
    status.textContent = '';
    renderSUPicker(d.files.length);

  } catch(e) {
    status.textContent = 'Scan failed: ' + e.message;
  }
}

function renderSUPicker(total) {
  const picker = document.getElementById('su-picker');
  const list   = document.getElementById('su-picker-list');
  const title  = document.getElementById('su-picker-title');

  title.textContent = total + ' .su file' + (total !== 1 ? 's' : '') + ' found';
  list.innerHTML = '';

  SU_DATA.scanResults.forEach((f, i) => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 6px;border-radius:4px;cursor:pointer';
    row.innerHTML =
      '<input type="checkbox" ' + (f.selected ? 'checked' : '') + ' style="accent-color:var(--acc);flex-shrink:0">' +
      '<span style="font-size:11px;color:#8b949e;flex-shrink:0;width:160px;overflow:hidden;text-overflow:ellipsis" title="' + f.path + '">' + f.name + '</span>' +
      '<span style="font-size:10px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + f.path + '">' + f.dir + '</span>';
    const cb = row.querySelector('input');
    cb.addEventListener('change', () => { SU_DATA.scanResults[i].selected = cb.checked; });
    row.addEventListener('click', e => { if (e.target !== cb) { cb.checked = !cb.checked; SU_DATA.scanResults[i].selected = cb.checked; }});
    list.appendChild(row);
  });

  picker.style.display = '';
}

function suPickerSelectAll()  { SU_DATA.scanResults.forEach(f => f.selected = true);  renderSUPicker(SU_DATA.scanResults.length); }
function suPickerSelectNone() { SU_DATA.scanResults.forEach(f => f.selected = false); renderSUPicker(SU_DATA.scanResults.length); }

async function loadSelectedSU() {
  const selected = SU_DATA.scanResults.filter(f => f.selected);
  if (!selected.length) { alert('Select at least one file'); return; }

  const btn = document.querySelector('[onclick="loadSelectedSU()"]');
  btn.textContent = 'Loading…'; btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('paths', JSON.stringify(selected.map(f => f.path)));
    const res = await fetch('/load_su_files', { method: 'POST', body: fd });
    const d   = await res.json();

    if (d.error) { alert('Load error: ' + d.error); return; }

    // Parse each returned file content
    d.files.forEach(f => {
      const count = parseSUFile(f.name, f.content);
      const existing = SU_DATA.loadedFiles.find(x => x.name === f.name);
      if (existing) existing.count = count;
      else SU_DATA.loadedFiles.push({ name: f.name, count });
    });

    document.getElementById('su-picker').style.display = 'none';
    document.getElementById('su-path').value = '';
    document.getElementById('su-scan-status').textContent =
      'Loaded ' + d.files.length + ' file' + (d.files.length !== 1 ? 's' : '');
    updateSUDropLabel();
    renderStackDepth();

  } catch(e) {
    alert('Load failed: ' + e.message);
  } finally {
    btn.textContent = '▶ Load selected'; btn.disabled = false;
  }
}

// ── Parse one .su file content ────────────────────────────────────────────
function parseSUFile(filename, content) {
  const slashPos = Math.max(filename.lastIndexOf('/'), filename.lastIndexOf('\\'));
  const shortName = slashPos >= 0 ? filename.slice(slashPos + 1) : filename;
  let count = 0;
  for (const line of content.split('\n')) {
    const m = line.match(/^([^:]+):(\d+):\d+:(\S+)\s+(\d+)\s+(\S+)/);
    if (!m) continue;
    // Upsert: update existing entry if re-loading same file
    const idx = SU_DATA.entries.findIndex(e => e.func === m[3] && e.file === shortName);
    const entry = { file: shortName, line: parseInt(m[2]), func: m[3],
                    size: parseInt(m[4]), type: m[5].replace(',', ' ') };
    if (idx >= 0) SU_DATA.entries[idx] = entry;
    else SU_DATA.entries.push(entry);
    count++;
  }
  return count;
}

// ── Clear all loaded data ─────────────────────────────────────────────────
function clearSUData() {
  SU_DATA.entries     = [];
  SU_DATA.filtered    = [];
  SU_DATA.loadedFiles = [];
  SU_DATA.scanResults = [];
  document.getElementById('stack-content').style.display     = 'none';
  document.getElementById('su-loaded-list').style.display    = 'none';
  document.getElementById('su-clear-btn').style.display      = 'none';
  document.getElementById('su-file-count').textContent       = '';
  document.getElementById('su-drop-label').textContent       = 'Drop .su files here (multiple OK) — or click to browse';
  document.getElementById('su-scan-status').textContent      = '';
  document.getElementById('su-picker').style.display         = 'none';
}

// ── Update the drop zone label and loaded file list ───────────────────────
function updateSUDropLabel() {
  const n = SU_DATA.loadedFiles.length;
  const total = SU_DATA.entries.length;
  document.getElementById('su-drop-label').textContent =
    n + ' file' + (n !== 1 ? 's' : '') + ' loaded (' + total + ' functions) — drop more to add';
  document.getElementById('su-file-count').textContent = n + ' file' + (n !== 1 ? 's' : '');
  document.getElementById('su-clear-btn').style.display = '';

  // Show loaded file chips
  const listEl  = document.getElementById('su-loaded-list');
  const itemsEl = document.getElementById('su-loaded-items');
  listEl.style.display = '';
  itemsEl.innerHTML = '';
  SU_DATA.loadedFiles.forEach(f => {
    const chip = document.createElement('div');
    chip.style.cssText = 'display:flex;align-items:center;gap:5px;background:var(--s2);' +
      'border:1px solid var(--bdr);border-radius:4px;padding:2px 8px;font-size:11px;' +
      'color:#8b949e;white-space:nowrap';
    chip.innerHTML = '<span>' + f.name + '</span>' +
      '<span style="color:var(--dim)">(' + f.count + ')</span>' +
      '<span style="cursor:pointer;color:var(--dim);padding:0 2px" title="Remove this file">✕</span>';
    chip.querySelector('span:last-child').addEventListener('click', () => removeSUFile(f.name));
    itemsEl.appendChild(chip);
  });
}

// ── Remove a single loaded file ───────────────────────────────────────────
function removeSUFile(filename) {
  SU_DATA.entries     = SU_DATA.entries.filter(e => e.file !== filename);
  SU_DATA.loadedFiles = SU_DATA.loadedFiles.filter(f => f.name !== filename);
  if (SU_DATA.loadedFiles.length) {
    updateSUDropLabel();
    renderStackDepth();
  } else {
    clearSUData();
  }
}

function renderStackDepth() {
  if (!SU_DATA.entries.length) return;
  $('stack-no-data').style.display = 'none';
  $('stack-content').style.display = '';

  const entries = SU_DATA.entries;
  const maxSize = Math.max(...entries.map(e => e.size), 1);
  const totalFuncs = entries.length;
  const unbounded = entries.filter(e => e.type.includes('dynamic') && !e.type.includes('bounded'));
  const worstCase = entries.filter(e => e.type === 'static').reduce((m, e) => Math.max(m, e.size), 0);

  $('stack-stats').innerHTML = `
    <div class="stat"><div class="snum">${totalFuncs}</div><div class="slbl">Functions analysed</div></div>
    <div class="stat"><div class="snum" style="color:var(--grn)">${worstCase}</div><div class="slbl">Largest static frame (bytes)</div></div>
    <div class="stat"><div class="snum" style="color:${unbounded.length?'var(--red)':'var(--grn)'}">${unbounded.length}</div>
      <div class="slbl">Unbounded dynamic frames<br>${unbounded.length?'⚠ investigate these':'✓ none found'}</div></div>
    <div class="stat"><div class="snum" style="color:var(--dim)">${entries.filter(e=>e.type.includes('dynamic')&&e.type.includes('bounded')).length}</div>
      <div class="slbl">Bounded dynamic frames</div></div>`;

  // Unbounded card
  const ubCard = $('stack-unbounded-card');
  ubCard.style.display = unbounded.length ? '' : 'none';
  const ubBody = $('stack-unbounded');
  ubBody.innerHTML = '';
  unbounded.forEach(e => {
    const tr = document.createElement('tr');
    tr.className = 'stack-unbounded-row clickable';
    tr.innerHTML = `<td style="font-size:11px">${e.func}</td><td class="dim" style="font-size:11px">${e.file}:${e.line}</td>`;
    ubBody.appendChild(tr);
  });

  filterStack();
}

function filterStack() {
  const q   = ($('stack-q')?.value || '').toLowerCase();
  const typ = $('stack-type')?.value || '';
  SU_DATA.filtered = SU_DATA.entries.filter(e => {
    if (q   && !e.func.toLowerCase().includes(q) && !e.file.toLowerCase().includes(q)) return false;
    if (typ && !e.type.includes(typ)) return false;
    return true;
  });
  sortAndRenderStack();
}

function sortStack(col) {
  if (SU_DATA.sortCol === col) SU_DATA.sortDir *= -1;
  else { SU_DATA.sortCol = col; SU_DATA.sortDir = -1; }
  sortAndRenderStack();
}

function sortAndRenderStack() {
  const { sortCol: col, sortDir: dir } = SU_DATA;
  const sorted = [...SU_DATA.filtered].sort((a, b) => {
    const va = col === 'size' ? a.size : (a[col] || '');
    const vb = col === 'size' ? b.size : (b[col] || '');
    return (typeof va === 'number' ? va - vb : va.toString().localeCompare(vb.toString())) * dir;
  });

  $('stack-cnt').textContent = `${sorted.length} / ${SU_DATA.entries.length}`;
  const tbody = $('stack-tbody'); tbody.innerHTML = '';
  const maxSize = Math.max(...SU_DATA.entries.map(e => e.size), 1);

  sorted.slice(0, 500).forEach(e => {
    const typeClass = e.type.includes('unbounded') || (e.type.includes('dynamic') && !e.type.includes('bounded'))
      ? 'stack-dynamic' : e.type.includes('bounded') ? 'stack-bounded' : 'stack-static';
    const barW = Math.round(e.size / maxSize * 80);
    const tr = document.createElement('tr'); tr.className = 'clickable';
    tr.innerHTML = `
      <td style="font-size:11px;color:#fff">${e.func}</td>
      <td>
        <span class="sz" style="margin-right:6px">${e.size}</span>
        <div class="fill-bg" style="width:80px;display:inline-block">
          <div class="fill-bar" style="width:${barW}px;background:${
            e.size > 1024 ? 'var(--red)' : e.size > 256 ? 'var(--ora)' : 'var(--grn)'}"></div>
        </div>
      </td>
      <td><span class="stack-type-badge ${typeClass}">${e.type}</span></td>
      <td class="dim" style="font-size:10px">${e.file}:${e.line}</td>`;
    // Click to jump to address inspector with symbol name lookup
    tr.addEventListener('click', () => {
      const sym = S.syms.find(s => s.name === e.func || s.name.endsWith(e.func));
      if (sym) openSymbolPopup(sym);
    });
    tbody.appendChild(tr);
  });
}

function exportStackCSV() {
  const lines = ['Function,Stack bytes,Type,File,Line'];
  SU_DATA.filtered.forEach(e => lines.push(`"${e.func}","${e.size}","${e.type}","${e.file}","${e.line}"`));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n')], {type:'text/csv'}));
  a.download = 'stack_usage.csv'; a.click();
}


// ========================================================================
// POPUPS.JS
// ========================================================================

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
      <div class="info-card"><div class="info-label">Start address</div><div class="info-value hx">${hx(sym.addr)}</div></div>
      <div class="info-card"><div class="info-label">End address</div><div class="info-value hx">${sym.size?hx(sym.addr+sym.size-1):'—'}</div></div>
      <div class="info-card"><div class="info-label">Size</div><div class="info-value sz">${sym.size?fz(sym.size)+' ('+sym.size+' bytes)':'unknown'}</div></div>
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



// ========================================================================
// RENDER.JS
// ========================================================================

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
    svgT(svg,hx(reg.end),{x:AW-5,y:y+h,fill:'#8b949e','font-size':9,'text-anchor':'end'});
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
    const endAddr=s.size?hx(s.addr+s.size-1):'';
    tr.innerHTML=`
      <td style="${nameStyle};font-size:11px" title="${s.name}">${s.name}</td>
      <td class="hx">${hx(s.addr)}</td>
      <td class="hx" style="color:#8b949e;font-size:10px">${endAddr}</td>
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

// ========================================================================
// DROPS.JS
// ========================================================================

// ═══════════════════════════════════════════════════════════════════════════
// FILE DROPS  — the only file that handles user file input
//
// Why this was broken before:
//   1. JSON.stringify inside onclick="" attributes corrupted the HTML parser
//      so getElementById() returned null and NO event listeners fired
//   2. Overlaid invisible input ate clicks before div handler ran
//   3. pointer-events on child elements blocked the click from reaching input
//
// Fix: inputs are display:none. Div click calls input.click() explicitly.
//      All wiring runs inside DOMContentLoaded so DOM is guaranteed ready.
// ═══════════════════════════════════════════════════════════════════════════

function initDropZones() {
    wireDropZone('ld-drop',  'ld-fi',  handleLDFile);
    wireDropZone('elf-drop', 'elf-fi', handleELFFile);
    wireDropZone('map-drop', 'map-fi', handleMapFile);
    wireWindowDrop();
    console.log('[drops] Drop zones wired');
}

function wireDropZone(divId, inputId, cb) {
    const div = document.getElementById(divId);
    const inp = document.getElementById(inputId);
    if (!div || !inp) { console.error('[drops] Missing element:', divId, inputId); return; }

    div.addEventListener('dragover',  function(e){ e.preventDefault(); e.stopPropagation(); div.classList.add('over'); });
    div.addEventListener('dragleave', function(e){ e.stopPropagation(); div.classList.remove('over'); });
    div.addEventListener('drop', function(e){
        e.preventDefault(); e.stopPropagation();
        div.classList.remove('over');
        var f = e.dataTransfer && e.dataTransfer.files[0];
        if (f) cb(f);
    });
    div.addEventListener('click', function(e){
        if (e.target === inp) return;
        inp.click();
    });
    inp.addEventListener('change', function(e){
        var f = e.target.files && e.target.files[0];
        if (f) { cb(f); inp.value = ''; }
    });
}

function wireWindowDrop() {
    window.addEventListener('dragover', function(e){ e.preventDefault(); });
    window.addEventListener('drop', function(e){
        e.preventDefault();
        var f = e.dataTransfer && e.dataTransfer.files[0];
        if (!f) return;
        var n = f.name.toLowerCase();
        if (n.endsWith('.ld') || n.endsWith('.lds') || n.endsWith('.x')) handleLDFile(f);
        else if (n.endsWith('.map')) handleMapFile(f);
    });
}

function handleLDFile(file) {
    var r = new FileReader();
    r.onload  = function(e) { uploadLD(file.name, e.target.result); };
    r.onerror = function()  { alert('Failed to read ' + file.name); };
    r.readAsText(file);
}

function handleELFFile(file) {
    S.elfFile = file;
    markDropLoaded('elf-drop', 'elf-name', file.name);
    document.getElementById('echip').style.display = '';
    document.getElementById('ename').textContent   = file.name;
    document.getElementById('analyse-btn').disabled = false;
    document.getElementById('tool-status').textContent = 'ELF ready — click Analyse ELF';
}

function handleMapFile(file) {
    var r = new FileReader();
    r.onload  = function(e) { uploadMap(file.name, e.target.result); };
    r.onerror = function()  { alert('Failed to read ' + file.name); };
    r.readAsText(file);
}

async function uploadLD(name, text) {
    try {
        var fd = new FormData();
        fd.append('content', text);
        fd.append('filename', name);
        var res = await fetch('/parse_ld', { method:'POST', body:fd });
        var d = await res.json();
        if (d.error) { alert('LD parse error:\n' + d.error); return; }
        S.ld = d;
        markDropLoaded('ld-drop', 'ld-name', name);
        document.getElementById('fchip').style.display = '';
        document.getElementById('fname').textContent = name;
        if (d.entry) {
            document.getElementById('entry-chip').style.display = '';
            document.getElementById('esym').textContent = d.entry;
        }
        showApp(); rerender();
    } catch(e) { alert('Upload failed: ' + e.message); }
}

async function uploadMap(name, text) {
    try {
        var fd = new FormData();
        fd.append('content', text);
        fd.append('filename', name);
        var res = await fetch('/parse_map', { method:'POST', body:fd });
        var d = await res.json();
        if (d.error) { alert('Map error:\n' + d.error); return; }
        S.mapData = d;
        markDropLoaded('map-drop', 'map-name', name);
        document.getElementById('mchip').style.display = '';
        document.getElementById('mname').textContent = name;
        showApp(); rerender();
    } catch(e) { alert('Upload failed: ' + e.message); }
}

async function runAnalysis() {
    if (!S.elfFile) { alert('Drop an ELF file first'); return; }
    var btn    = document.getElementById('analyse-btn');
    var prog   = document.getElementById('elf-prog');
    var status = document.getElementById('tool-status');
    btn.disabled = true; btn.textContent = 'Uploading...';
    prog.style.display = ''; prog.value = 0;

    var tools = {
        nm:     document.getElementById('t-nm').value.trim(),
        re:     document.getElementById('t-re').value.trim(),
        size:   document.getElementById('t-sz').value.trim(),
        a2l:    document.getElementById('t-a2l').value.trim(),
        prefix: document.getElementById('t-prefix').value.trim(),
    };
    var fd = new FormData();
    fd.append('elf', S.elfFile);
    fd.append('tools', JSON.stringify(tools));
    fd.append('ld_data', JSON.stringify(S.ld || {regions:[],sections:[],entry:''}));

    try {
        var d = await new Promise(function(resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/analyse_elf');
            xhr.upload.onprogress = function(e) {
                if (e.lengthComputable) {
                    prog.value = Math.round(e.loaded/e.total*80);
                    status.textContent = 'Uploading ' + Math.round(e.loaded/1024) + 'KB';
                }
            };
            xhr.onload  = function() { try { resolve(JSON.parse(xhr.responseText)); } catch(e){ reject(e); } };
            xhr.onerror = function() { reject(new Error('Network error')); };
            xhr.send(fd);
        });

        prog.style.display = 'none'; btn.disabled = false; btn.textContent = 'Analyse ELF';
        if (d.error) { status.textContent = 'Error: ' + d.error; if(d.debug) populateDebug(d.debug); return; }

        S.syms = d.symbols; S.elfSecs = d.elf_sections; S.warns = d.warnings; S.startup = d.startup;
        document.getElementById('sym-chip').style.display = '';
        document.getElementById('symcount').textContent = d.symbols.length;
        status.textContent = d.symbols.length > 0 ? '✓ ' + d.symbols.length + ' symbols' : 'Warning: 0 symbols — check Debug tab';
        if (d.debug) populateDebug(d.debug);
        if (!d.symbols.length) switchTab('dbg');
        showApp(); rerender();
    } catch(e) {
        prog.style.display = 'none'; btn.disabled = false; btn.textContent = 'Analyse ELF';
        status.textContent = 'Error: ' + e.message;
    }
}

function markDropLoaded(dropId, nameId, name) {
    var drop = document.getElementById(dropId);
    var nameEl = document.getElementById(nameId);
    if (drop) { drop.classList.add('loaded'); var p=drop.querySelector('p'); if(p) p.textContent=name; }
    if (nameEl) { nameEl.textContent = name; nameEl.style.display = ''; }
}


