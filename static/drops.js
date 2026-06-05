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

'use strict';

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
