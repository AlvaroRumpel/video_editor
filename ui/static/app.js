const S = { pid: null, proj: null, wave: null, selected: null, es: null };
const el = id => document.getElementById(id);
const api = (path, params = {}) => {
  const u = new URL(path, location.origin);
  Object.entries(params).forEach(([k, v]) => u.searchParams.set(k, v));
  return u;
};
const getJSON = async (path, params) => (await fetch(api(path, params))).json();
const postJSON = (path, params, body) =>
  fetch(api(path, params), { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });

// stubs — Task 7 troca pelo mapeamento real via EDL
let outToSrc = t => t, srcToOut = t => t;

async function loadProjects() {
  const projs = await getJSON('/api/projects');
  const sel = el('proj-select');
  sel.innerHTML = projs.map(p =>
    `<option value="${p.id}">${p.name}</option>`).join('');
  sel.onchange = () => loadProject(sel.value);
  if (projs.length) loadProject(localStorage.lastPid || projs[0].id);
}

async function loadProject(pid) {
  S.pid = pid; localStorage.lastPid = pid;
  S.proj = await getJSON('/api/project', { id: pid });
  S.wave = await getJSON('/api/waveform', { id: pid });
  const v = el('player');
  el('no-preview').hidden = S.proj.has_preview;
  if (S.proj.has_preview)
    v.src = api('/api/video', { id: pid, kind: 'preview' });
  renderAll();          // definida nas tasks 7-9
  connectSSE(pid);
}

function connectSSE(pid) {
  if (S.es) S.es.close();
  S.es = new EventSource(api('/api/events', { id: pid }));
  let last = null;
  S.es.onmessage = async ev => {
    const snap = JSON.parse(ev.data);
    el('claude-status').className = snap.claude_online ? 'online' : 'offline';
    el('claude-status').textContent =
      snap.claude_online ? 'Claude escutando' : 'Claude offline';
    if (last) {
      const changed = Object.keys(snap.mtimes)
        .filter(k => snap.mtimes[k] !== last.mtimes[k]);
      if (changed.length) await loadProject(pid);   // recarrega tudo (simples)
    }
    last = snap;
  };
}

function renderAll() { /* preenchida nas próximas tasks */ }

loadProjects();
