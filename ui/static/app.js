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
const putJSON = (path, params, body) =>
  fetch(api(path, params), { method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });
const escapeHtml = s => String(s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const TABS = ['board', 'edicao', 'docs', 'custos'];
const STATUS_LABEL = { pendente: 'pendente', andamento: 'em andamento', fim: 'ok',
  espera: 'esperando você', pulada: 'pulada', falha: 'falha' };
const hashFor = (pid, tab) => `#/p/${encodeURIComponent(pid)}/${tab}`;

function parseHash() {
  const m = location.hash.match(/^#\/p\/([^/]+)(?:\/([a-z]+))?$/);
  if (!m) return { route: 'library' };
  return { route: 'project', pid: decodeURIComponent(m[1]), tab: TABS.includes(m[2]) ? m[2] : null };
}

function lastTab(pid) { try { return localStorage.getItem('tab:' + pid); } catch { return null; } }
function saveTab(pid, tab) { try { localStorage.setItem('tab:' + pid, tab); } catch { /* sem storage */ } }

function goTab(tab) {
  const h = hashFor(S.pid, tab);
  if (location.hash === h) route(); else location.hash = h;
}

async function route() {
  const r = parseHash();
  const body = document.body;
  if (r.route === 'library') {
    body.dataset.route = 'library';
    if (S.es) { S.es.close(); S.es = null; }
    S.pid = null; S.proj = null; S.quadro = null; S.selected = null;
    const v = el('player');
    v.pause(); if (v.getAttribute('src')) v.removeAttribute('src');
    el('render-progress').hidden = true;   // progresso é por projeto
    renderBudget();
    startLibrary();
    return;
  }
  stopLibrary();
  let tab = r.tab || lastTab(r.pid) || 'board';
  if (!TABS.includes(tab)) tab = 'board';
  if (r.tab !== tab) { history.replaceState(null, '', hashFor(r.pid, tab)); }
  const prev = body.dataset.tab;
  body.dataset.route = 'project';
  body.dataset.tab = tab;
  saveTab(r.pid, tab);
  if (S.pid !== r.pid || !S.proj) await loadProject(r.pid);
  else renderTab(tab, prev);
}

window.addEventListener('hashchange', route);
// aba clicável antes do load terminar (href só é preenchido em renderTabs)
el('tabs').addEventListener('click', e => {
  const a = e.target.closest('a[data-tab]');
  if (!a || a.classList.contains('off')) return;
  e.preventDefault();
  const h = hashFor(parseHash().pid, a.dataset.tab);
  if (location.hash === h) route(); else location.hash = h;
});

// stubs — reatribuídos por buildTimeMap() após cada load de projeto
let outToSrc = t => t, srcToOut = t => t;

function buildTimeMap() {
  const ranges = S.proj.edl.ranges;
  let acc = 0;
  const map = ranges.map(r => {
    const seg = { srcStart: r.start, srcEnd: r.end,
                  outStart: acc, outEnd: acc + (r.end - r.start) };
    acc = seg.outEnd;
    return seg;
  });
  outToSrc = t => {
    for (const s of map)
      if (t <= s.outEnd) return s.srcStart + Math.max(0, t - s.outStart);
    return map.length ? map[map.length - 1].srcEnd : t;
  };
  srcToOut = t => {
    for (const s of map) {
      if (t < s.srcStart) return s.outStart;      // gap: fim do anterior
      if (t <= s.srcEnd) return s.outStart + (t - s.srcStart);
    }
    return map.length ? map[map.length - 1].outEnd : t;
  };
  return map;
}

async function loadProject(pid) {
  try {
    await loadProjectInner(pid);
  } catch (err) {   // servidor reiniciando etc.: tenta de novo em 2s se ainda estamos nele
    console.warn('loadProject falhou, retry em 2s', err);
    setTimeout(() => { if (parseHash().pid === pid) loadProject(pid); }, 2000);
  }
}

async function loadProjectInner(pid) {
  const r = await fetch(api('/api/project', { id: pid }));
  if (r.status === 400 || r.status === 404) { location.hash = '#/'; return; }
  const proj = await r.json();
  const [wave, quadro, gq, act, bud] = await Promise.all([
    getJSON('/api/waveform', { id: pid }), getJSON('/api/quadro', { id: pid }),
    getJSON('/api/global-queue'), getJSON('/api/activity'),
    getJSON('/api/budget').catch(() => null)]);
  if (parseHash().pid !== pid) return;   // usuário saiu do projeto durante o load
  const novo = S.pid !== pid;
  S.pid = pid; S.proj = proj; S.wave = wave; S.quadro = quadro;
  S.globalQueue = gq; S.activity = act; S.budget = bud;
  if (novo) { S.selected = null; S.docsPid = null; }
  const v = el('player');
  el('no-preview').hidden = S.proj.has_preview;
  if (S.proj.has_preview)
    v.src = api('/api/video', { id: pid, kind: 'preview' });
  else if (v.getAttribute('src')) v.removeAttribute('src');
  renderAll();
  if (novo || !S.es) connectSSE(pid);
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
      if (changed.includes('docs') && document.body.dataset.tab === 'docs') renderDocsTab();
    }
    last = snap;
  };
}

// ---------------------------------------------------------------------
// Lista de cortes + instruções (Task 8)
// ---------------------------------------------------------------------

function selectCut(i) {
  S.selected = i;
  const ic = el('instr-context');
  if (ic) ic.textContent = `sobre corte #${i}`;
  const r = S.proj.edl.ranges[i];
  const player = el('player');
  if (player) player.currentTime = srcToOut(r.start);
  renderTimeline();
}

// pilha de undo (Ctrl+Z): cancela o último pedido enviado / desfaz o último 👍
const undoStack = [];

function pushQueueUndo(res) {
  return res.json().then(entry => {
    undoStack.push({ kind: 'queue', pid: S.pid, qid: entry.id });
    return entry;
  });
}

function toggleApproval(i, fromUndo) {
  const cur = new Set((S.proj.state && S.proj.state.aprovacoes) || []);
  if (cur.has(i)) cur.delete(i); else cur.add(i);
  if (!fromUndo) undoStack.push({ kind: 'approve', pid: S.pid, i });
  postJSON('/api/state', { id: S.pid }, { aprovacoes: [...cur] })
    .then(() => loadProject(S.pid));
}

function sendVeto(i) {
  postJSON('/api/queue', { id: S.pid }, {
    type: 'veto', target: i, text: `revisar/remover corte #${i}`,
  }).then(pushQueueUndo).then(() => loadProject(S.pid));
}

function undoLast() {
  const a = undoStack.pop();
  if (!a || a.pid !== S.pid) return;
  if (a.kind === 'queue') {
    postJSON('/api/cancel', { id: a.pid }, { qid: a.qid })
      .then(() => loadProject(S.pid));
  } else if (a.kind === 'approve') {
    toggleApproval(a.i, true);
  }
}

document.addEventListener('keydown', e => {
  const tag = (e.target.tagName || '').toUpperCase();
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
    e.target.isContentEditable;
  if (e.ctrlKey && e.key.toLowerCase() === 'z' && !typing) {
    e.preventDefault(); undoLast();
  }
  if (e.key === ' ' && !typing) {           // espaço = play/pause
    e.preventDefault();
    const p = el('player');
    if (p && p.src) { if (p.paused) p.play(); else p.pause(); }
  }
});

function renderCutList() {
  const ranges = S.proj.edl.ranges;
  const aprovacoes = new Set((S.proj.state && S.proj.state.aprovacoes) || []);
  const queue = S.proj.queue || [];
  el('cut-list').innerHTML = ranges.map((r, i) => {
    const cls = aprovacoes.has(i) ? 'status-approved'
      : queueTargetsSegment(queue, i) ? 'status-pending' : '';
    return `<div class="cut-row ${cls}" data-i="${i}">
      <span class="cut-label">#${i}  ${fmtTime(r.start)}–${fmtTime(r.end)}</span>
      <button class="cut-up" data-i="${i}" title="Aprovar corte (marca verde; Ctrl+Z desfaz)">👍</button>
      <button class="cut-down" data-i="${i}" title="Vetar corte — pede revisão/remoção pro Claude">👎</button>
    </div>`;
  }).join('');
}

el('cut-list').addEventListener('click', e => {
  const row = e.target.closest('.cut-row');
  if (!row) return;
  const i = +row.dataset.i;
  if (e.target.closest('.cut-up')) return toggleApproval(i);
  if (e.target.closest('.cut-down')) return sendVeto(i);
  selectCut(i);
});

function sendInstruction() {
  const ta = el('instr-text');
  const text = ta.value.trim();
  if (!text) return;
  postJSON('/api/queue', { id: S.pid }, {
    type: 'instrucao', target: S.selected, text,
  }).then(pushQueueUndo).then(() => { ta.value = ''; loadProject(S.pid); });
}

el('instr-send').addEventListener('click', sendInstruction);
el('instr-text').addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); sendInstruction(); }
});

// ---------------------------------------------------------------------
// Timeline (Task 7): tracks V/A/T/FX, zoom/pan, playhead
// ---------------------------------------------------------------------

let canvas, ctx;
let view = { t0: 0, pxPerSec: 50 };     // janela visível, eixo do bruto (src)
let layout = {};                        // posições Y calculadas por render
let tlInited = false;
let lastFitPid = null;
let drag = null;
window.__tl = { segmentsDrawn: 0 };

function fitView() {
  const dur = (S.wave && S.wave.duration) || S.proj.source_duration || 60;
  const w = canvas.clientWidth || 800;
  view.t0 = 0;
  view.pxPerSec = Math.min(2000, Math.max(1, w / Math.max(dur, 1)));
}

function niceInterval(pxPerSec, minPx = 70) {
  const candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600];
  for (const c of candidates) if (c * pxPerSec >= minPx) return c;
  return candidates[candidates.length - 1];
}

function fmtTime(t) {
  t = Math.max(0, t);
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function truncateText(text, maxW) {
  if (maxW <= 2) return '';
  if (ctx.measureText(text).width <= maxW) return text;
  let lo = 0, hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    const s = text.slice(0, mid) + '…';
    if (ctx.measureText(s).width <= maxW) lo = mid; else hi = mid - 1;
  }
  return lo > 0 ? text.slice(0, lo) + '…' : '';
}

function queueTargetsSegment(queue, i) {
  return queue.some(e => (e.status === 'pending' || e.status === 'executing' || e.status === 'waiting_reply') &&
    (e.target === i || (e.target && typeof e.target === 'object' && e.target.seg === i)));
}

function drawRuler(w, h) {
  ctx.fillStyle = '#1e1e1e';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#3c3c3c';
  ctx.fillStyle = '#ccc';
  ctx.font = '10px system-ui';
  ctx.textBaseline = 'top';
  const interval = niceInterval(view.pxPerSec);
  const tEnd = view.t0 + w / view.pxPerSec;
  const start = Math.floor(view.t0 / interval) * interval;
  for (let t = start; t <= tEnd; t += interval) {
    const x = (t - view.t0) * view.pxPerSec;
    ctx.beginPath();
    ctx.moveTo(x, h - 6); ctx.lineTo(x, h);
    ctx.stroke();
    ctx.fillText(fmtTime(t), x + 2, 2);
  }
}

function drawV(y, h) {
  const ranges = S.proj.edl.ranges;
  const aprovacoes = new Set((S.proj.state && S.proj.state.aprovacoes) || []);
  const queue = S.proj.queue || [];
  let drawn = 0;
  for (let i = 0; i < ranges.length; i++) {
    const r = ranges[i];
    const x0 = (r.start - view.t0) * view.pxPerSec;
    const x1 = (r.end - view.t0) * view.pxPerSec;
    const w = Math.max(1, x1 - x0);
    ctx.fillStyle = '#3c3c3c';
    ctx.fillRect(x0, y, w, h);
    if (aprovacoes.has(i)) {
      ctx.fillStyle = 'rgba(76,175,80,0.35)';
      ctx.fillRect(x0, y, w, h);
    }
    if (queueTargetsSegment(queue, i)) {
      ctx.fillStyle = 'rgba(230,162,60,0.4)';
      ctx.fillRect(x0, y, w, h);
    }
    ctx.lineWidth = i === S.selected ? 2 : 1;
    ctx.strokeStyle = i === S.selected ? '#4f8cff' : '#555';
    ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(0, w - 1), h - 1);
    drawn++;
  }
  return drawn;
}

function drawA(y, h) {
  const wave = S.wave;
  if (!wave || !wave.peaks || !wave.peaks.length || !wave.duration) return;
  const peaks = wave.peaks;
  const n = peaks.length;
  const dur = wave.duration;
  const mid = y + h / 2;
  const tStart = view.t0;
  const tEnd = view.t0 + layout.cssW / view.pxPerSec;
  const i0 = Math.max(0, Math.floor((tStart / dur) * n) - 1);
  const i1 = Math.min(n - 1, Math.ceil((tEnd / dur) * n) + 1);
  ctx.strokeStyle = '#4f8cff';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = i0; i <= i1; i++) {
    const t = (i / n) * dur;
    const x = (t - view.t0) * view.pxPerSec;
    const amp = Math.max(0.02, peaks[i]) * (h / 2 - 2);
    ctx.moveTo(x, mid - amp);
    ctx.lineTo(x, mid + amp);
  }
  ctx.stroke();
}

function drawT(y, h) {
  const phrases = S.proj.phrases || [];
  ctx.font = '10px system-ui';
  ctx.textBaseline = 'top';
  for (const p of phrases) {
    const x0 = (p.start - view.t0) * view.pxPerSec;
    const x1 = (p.end - view.t0) * view.pxPerSec;
    if (x1 < 0 || x0 > layout.cssW) continue;
    const w = Math.max(1, x1 - x0);
    ctx.fillStyle = 'rgba(79,140,255,0.12)';
    ctx.fillRect(x0, y, w, h - 2);
    ctx.strokeStyle = '#3c3c3c';
    ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(0, w - 1), h - 3);
    ctx.fillStyle = '#ccc';
    ctx.fillText(truncateText(p.text || '', w - 4), x0 + 2, y + 2);
  }
}

function drawFX(y, h) {
  const bandH = h / 3;
  ctx.textBaseline = 'top';

  // zoom != 1.0 por segmento
  const zoomsArr = S.proj.zooms || [];
  const ranges = S.proj.edl.ranges;
  ctx.font = '9px system-ui';
  for (let i = 0; i < ranges.length; i++) {
    const z = zoomsArr[i];
    if (!z || z === 1.0) continue;
    const r = ranges[i];
    const x0 = (r.start - view.t0) * view.pxPerSec;
    const x1 = (r.end - view.t0) * view.pxPerSec;
    if (x1 < 0 || x0 > layout.cssW) continue;
    const w = Math.max(1, x1 - x0);
    ctx.fillStyle = 'rgba(230,162,60,0.5)';
    ctx.fillRect(x0, y, w, bandH - 2);
    ctx.fillStyle = '#e6a23c';
    ctx.fillText(`${z.toFixed(2)}x`, x0 + 2, y + 1);
  }

  // overlays (start_in_output -> eixo do bruto via outToSrc)
  const overlays = (S.proj.edl && S.proj.edl.overlays) || [];
  const oy = y + bandH;
  for (const o of overlays) {
    const srcStart = outToSrc(o.start_in_output);
    const srcEnd = outToSrc(o.start_in_output + o.duration);
    const x0 = (srcStart - view.t0) * view.pxPerSec;
    const x1 = (srcEnd - view.t0) * view.pxPerSec;
    if (x1 < 0 || x0 > layout.cssW) continue;
    const w = Math.max(1, x1 - x0);
    ctx.fillStyle = (o.file || '').startsWith('broll/out/') ? 'rgba(255,170,60,0.55)' : 'rgba(79,140,255,0.4)';
    ctx.fillRect(x0, oy, w, bandH - 2);
    ctx.fillStyle = '#ccc';
    ctx.fillText(truncateText(o.file || '', w - 4), x0 + 2, oy + 1);
  }

  // legendas SRT (tempo de saída -> eixo do bruto via outToSrc)
  const srt = S.proj.srt || [];
  const sy = y + 2 * bandH;
  for (const s of srt) {
    const srcStart = outToSrc(s.start);
    const srcEnd = outToSrc(s.end);
    const x0 = (srcStart - view.t0) * view.pxPerSec;
    const x1 = (srcEnd - view.t0) * view.pxPerSec;
    if (x1 < 0 || x0 > layout.cssW) continue;
    const w = Math.max(1, x1 - x0);
    ctx.fillStyle = 'rgba(76,175,80,0.25)';
    ctx.fillRect(x0, sy, w, bandH - 2);
    ctx.fillStyle = '#ccc';
    ctx.fillText(truncateText(s.text || '', w - 4), x0 + 2, sy + 1);
  }
}

function drawPlayhead(cssH) {
  const player = el('player');
  if (!player) return;
  const t = outToSrc(player.currentTime || 0);
  const x = (t - view.t0) * view.pxPerSec;
  if (x < 0 || x > layout.cssW) return;
  ctx.strokeStyle = '#e05252';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, cssH);
  ctx.stroke();
}

function renderTimeline() {
  if (!canvas || !S.proj) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  if (cssW <= 0 || cssH <= 0) return;
  const pxW = Math.round(cssW * dpr), pxH = Math.round(cssH * dpr);
  if (canvas.width !== pxW) canvas.width = pxW;
  if (canvas.height !== pxH) canvas.height = pxH;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#252526';
  ctx.fillRect(0, 0, cssW, cssH);

  const rulerH = 20;
  const restH = cssH - rulerH;
  const vH = restH * 0.34, aH = restH * 0.22, tH = restH * 0.18;
  const fxH = restH - vH - aH - tH;
  const vY = rulerH, aY = vY + vH, tY = aY + aH, fxY = tY + tH;
  layout = { rulerH, vY, vH, aY, aH, tY, tH, fxY, fxH, cssW, cssH };

  drawRuler(cssW, rulerH);
  const segmentsDrawn = drawV(vY, vH);
  drawA(aY, aH);
  drawT(tY, tH);
  drawFX(fxY, fxH);
  drawPlayhead(cssH);
  if (drag && drag.type === 'edge') drawEdgeGhost();

  window.__tl = { segmentsDrawn };
}

function drawEdgeGhost() {
  const r = S.proj.edl.ranges[drag.seg];
  const baseT = drag.edge === 'start' ? r.start : r.end;
  const t = baseT + drag.deltaSec;
  const x = (t - view.t0) * view.pxPerSec;
  const deltaMs = Math.round(drag.deltaSec * 1000);
  ctx.save();
  ctx.strokeStyle = '#e6a23c';
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x, layout.vY);
  ctx.lineTo(x, layout.vY + layout.vH);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#e6a23c';
  ctx.font = '10px system-ui';
  ctx.textBaseline = 'bottom';
  ctx.fillText(`${deltaMs > 0 ? '+' : ''}${deltaMs}ms`, x + 4, layout.vY);
  ctx.restore();
}

function hitSegment(x, y) {
  if (!S.proj || y < layout.vY || y > layout.vY + layout.vH) return null;
  const t = view.t0 + x / view.pxPerSec;
  const ranges = S.proj.edl.ranges;
  for (let i = 0; i < ranges.length; i++) {
    const r = ranges[i];
    if (t >= r.start && t <= r.end) {
      const xStart = (r.start - view.t0) * view.pxPerSec;
      const xEnd = (r.end - view.t0) * view.pxPerSec;
      let edge = null;
      if (Math.abs(x - xStart) <= 5) edge = 'start';
      else if (Math.abs(x - xEnd) <= 5) edge = 'end';
      return { index: i, edge };
    }
  }
  return null;
}

function handleTimelineClick(x, y) {
  const hit = hitSegment(x, y);
  if (hit) {
    selectCut(hit.index);   // seleciona E posiciona o player no clipe
    return;
  }
  const t = view.t0 + x / view.pxPerSec;
  const player = el('player');
  if (player) player.currentTime = srcToOut(t);
}

function onWheel(e) {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const tAtCursor = view.t0 + x / view.pxPerSec;
  view.pxPerSec = Math.min(2000, Math.max(1, view.pxPerSec * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
  view.t0 = tAtCursor - x / view.pxPerSec;
  renderTimeline();
}

// arrasto de borda só com zoom suficiente (1px <= 100ms); senão vira pan
const EDGE_DRAG_MIN_PXPERSEC = 10;
const EDGE_DRAG_MAX_SEC = 2;      // ajuste fino: nunca mais que ±2s por arrasto

function onPointerDown(e) {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  const hit = hitSegment(x, y);
  if (hit && hit.edge && view.pxPerSec >= EDGE_DRAG_MIN_PXPERSEC) {
    drag = { type: 'edge', seg: hit.index, edge: hit.edge, startX: x, deltaSec: 0 };
    canvas.setPointerCapture(e.pointerId);
    return;
  }
  drag = { type: 'pan', startX: x, startT0: view.t0, moved: false };
  canvas.setPointerCapture(e.pointerId);
}

function onPointerMove(e) {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  if (!drag) {   // hover: dica visual de onde dá pra arrastar borda
    const hit = hitSegment(x, e.clientY - rect.top);
    canvas.style.cursor = hit && hit.edge &&
      view.pxPerSec >= EDGE_DRAG_MIN_PXPERSEC ? 'ew-resize' : 'default';
    return;
  }
  if (drag.type === 'edge') {
    const d = (x - drag.startX) / view.pxPerSec;
    drag.deltaSec = Math.max(-EDGE_DRAG_MAX_SEC, Math.min(EDGE_DRAG_MAX_SEC, d));
    renderTimeline();
    return;
  }
  const dx = x - drag.startX;
  if (Math.abs(dx) > 3) drag.moved = true;
  if (drag.moved) {
    view.t0 = drag.startT0 - dx / view.pxPerSec;
    renderTimeline();
  }
}

function onPointerUp(e) {
  if (!drag) return;
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  if (drag.type === 'edge') {
    const { seg: i, edge, deltaSec: delta } = drag;
    if (Math.abs(delta * 1000) >= 30) {
      postJSON('/api/queue', { id: S.pid }, {
        type: 'borda',
        target: { seg: i, edge, delta_ms: Math.round(delta * 1000) },
        text: `${edge === 'start' ? 'início' : 'fim'} do corte #${i} ${delta > 0 ? '+' : ''}${Math.round(delta * 1000)}ms`,
      }).then(pushQueueUndo).then(() => loadProject(S.pid));
    }
    drag = null;
    renderTimeline();
    return;
  }
  if (!drag.moved) handleTimelineClick(x, y);
  drag = null;
}

function rafLoop() {
  const player = el('player');
  if (player && !player.paused && !player.ended) renderTimeline();
  requestAnimationFrame(rafLoop);
}

function initTimelineOnce() {
  if (tlInited) return;
  tlInited = true;
  canvas = el('timeline');
  ctx = canvas.getContext('2d');
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  window.addEventListener('resize', () => renderTimeline());
  requestAnimationFrame(rafLoop);
}

function renderAll() {
  if (!S.proj) return;
  const body = document.body;
  if (body.dataset.tab === 'edicao' && !S.proj.has_edl) {   // sem edl.json: Edição desabilitada
    body.dataset.tab = 'board';
    history.replaceState(null, '', hashFor(S.pid, 'board'));
  }
  buildTimeMap();
  initTimelineOnce();
  if (S.pid !== lastFitPid) { fitView(); lastFitPid = S.pid; }
  renderHeader();
  renderTabs();
  renderStepper();
  renderCutList();
  renderTimeline();
  renderQueue();
  renderProgress();
  renderBudget();
  const tab = body.dataset.tab;
  if (tab === 'board') renderBoard();
  if (tab === 'custos') renderCustosTab();
  if (tab === 'docs' && S.docsPid !== S.pid) { S.docsPid = S.pid; renderDocsTab(); }
  if (S.formats) renderFormatSelect(); else loadFormats().then(renderFormatSelect);
}

function renderHeader() {
  el('proj-name').textContent = S.pid.split('/').slice(-2).join('/');
  el('proj-cost').textContent = fmtUSD((S.proj.custos || {}).usd);
}

function renderTabs() {
  const tab = document.body.dataset.tab;
  document.querySelectorAll('#tabs a').forEach(a => {
    a.href = hashFor(S.pid, a.dataset.tab);
    a.classList.toggle('on', a.dataset.tab === tab);
    a.classList.toggle('off', a.dataset.tab === 'edicao' && !(S.proj && S.proj.has_edl));
  });
}

function renderTab(tab, prev) {
  renderTabs();
  if (tab === 'board') renderBoard();
  else if (tab === 'custos') renderCustosTab();
  else if (tab === 'docs') { S.docsPid = S.pid; renderDocsTab(); }
  else if (tab === 'edicao' && prev !== 'edicao')
    requestAnimationFrame(() => { fitView(); renderTimeline(); });
}

// ---------------------------------------------------------------------
// Fila viva, render/progresso, formatos, novo vídeo (Task 9)
// ---------------------------------------------------------------------

const STATUS_ICON = { pending: '⏳', executing: '▶', waiting_reply: '❓', done: '✅', failed: '❌', cancelado: '🚫' };

function renderActivity() {
  const a = S.activity || {};
  const box = el('activity-box');
  if (!box) return;
  const fresh = a.ts && (Date.now() - new Date(a.ts).getTime()) < 10 * 60 * 1000;
  box.hidden = !(a.atual && fresh);
  if (box.hidden) return;
  el('activity-now-text').textContent = a.atual;
  el('activity-prev').hidden = !a.anterior;
  if (a.anterior) el('activity-prev-text').textContent = a.anterior;
}

function renderQueue() {
  renderActivity();
  const projEntries = S.proj
    ? (S.proj.queue || []).map(e => ({ ...e, _scope: 'proj' }))
    : (S.lib.items || []).flatMap(p => (p.fila || []).map(e => ({ ...e, _scope: p.id, _nome: p.name })));
  const globalEntries = (S.globalQueue || []).map(e => ({ ...e, _scope: 'global' }));
  const merged = projEntries.concat(globalEntries).sort((a, b) => b.id - a.id);
  el('queue-panel').innerHTML = merged.length ? merged.map(e => {
    const icon = STATUS_ICON[e.status] || '';
    const prefix = e._scope === 'global' ? '[novo] ' : e._nome ? `[${escapeHtml(e._nome)}] ` : '';
    const sub = e.resultado ? `<div class="queue-sub">${escapeHtml(e.resultado)}</div>` : '';
    const replySent = e.reply && e.status !== 'waiting_reply'
      ? `<div class="queue-sub queue-you">você: ${escapeHtml(e.reply)}${e.status === 'pending' ? ' — aguardando o Claude retomar' : ''}</div>` : '';
    const reply = e.status === 'waiting_reply' ? `<div class="queue-reply">
        <textarea class="queue-reply-input" data-qid="${e.id}" data-scope="${escapeHtml(e._scope)}" placeholder="responder... (Enter envia, Ctrl+Enter quebra linha)" rows="2"></textarea>
        <button class="queue-reply-send" data-qid="${e.id}" data-scope="${escapeHtml(e._scope)}">Enviar</button>
      </div>` : '';
    return `<div class="queue-row">
      <div class="queue-main"><span class="queue-icon">${icon}</span><span class="queue-text">${prefix}${escapeHtml(e.text || e.type)}</span></div>
      ${sub}${replySent}${reply}
    </div>`;
  }).join('') : '<div class="queue-empty">fila vazia</div>';
}

function sendReply(qid, text, scope) {
  const pid = scope === 'global' ? '_global' : scope === 'proj' ? S.pid : scope;
  return postJSON('/api/reply', { id: pid }, { qid, text })
    .then(() => (S.pid ? loadProject(S.pid) : loadLibrary()));
}

el('queue-panel').addEventListener('click', e => {
  const btn = e.target.closest('.queue-reply-send');
  if (!btn) return;
  const input = el('queue-panel').querySelector(
    `.queue-reply-input[data-qid="${btn.dataset.qid}"][data-scope="${btn.dataset.scope}"]`);
  const text = input.value.trim();
  if (text) sendReply(+btn.dataset.qid, text, btn.dataset.scope);
});
el('queue-panel').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.classList.contains('queue-reply-input')) return;
  if (e.ctrlKey) {   // Ctrl+Enter = quebra de linha
    const ta = e.target, p = ta.selectionStart;
    ta.value = ta.value.slice(0, p) + '\n' + ta.value.slice(ta.selectionEnd);
    ta.selectionStart = ta.selectionEnd = p + 1;
    e.preventDefault();
    return;
  }
  e.preventDefault();   // Enter puro = envia
  const text = e.target.value.trim();
  if (text) sendReply(+e.target.dataset.qid, text, e.target.dataset.scope);
});

function fmtMSS(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function renderProgress() {
  const r = S.proj.state && S.proj.state.render;
  const box = el('render-progress');
  if (!r || r.pct >= 100) { box.hidden = true; return; }
  box.hidden = false;
  el('render-bar').style.width = `${r.pct}%`;
  el('render-label').textContent = `${r.fase} · ${r.pct}% · ${fmtMSS(r.eta)}`;
}

const fmtUSD = v => `US$ ${(v || 0).toFixed(2)}`;

function renderBudget() {
  let usd, teto;
  if (S.proj) { usd = (S.proj.custos || {}).usd || 0; teto = S.proj.teto_projeto || 0; }
  else {
    const b = S.budget || {};
    usd = (b.gasto_mes || {}).usd || 0; teto = (b.budget || {}).teto_mensal_usd || 0;
  }
  const pct = teto ? Math.min(100, usd / teto * 100) : 0;
  el('budget-badge').className = 'budget' + (pct >= 80 ? ' warn' : '');
  el('budget-bar').style.width = `${pct}%`;
  el('budget-label').textContent = `${fmtUSD(usd)} / ${fmtUSD(teto)}`;
}

function openBudgetModal() {
  const b = S.budget || {}; const bb = b.budget || {}; const m = b.gasto_mes || {};
  const ev = b.elevenlabs;
  const cota = ev ? `${ev.usados.toLocaleString('pt-BR')} / ${ev.limite.toLocaleString('pt-BR')} créditos` : 'saldo indisponível';
  el('modal').innerHTML = `
    <div class="modal-box budget-modal">
      <button class="modal-close">×</button>
      <h3>Orçamento</h3>
      <div>Mês ${escapeHtml(b.mes || '')}: <b>${fmtUSD(m.usd)}</b> / ${fmtUSD(bb.teto_mensal_usd)} · ElevenLabs ${cota}</div>
      ${S.proj ? `<div>Projeto atual: <b>${fmtUSD((S.proj.custos || {}).usd)}</b> / ${fmtUSD(S.proj.teto_projeto)}</div>` : ''}
      <label>Teto mensal (US$) <input type="number" min="0" step="0.5" id="b-mensal" value="${bb.teto_mensal_usd ?? ''}"></label>
      <label>Teto padrão por projeto (US$) <input type="number" min="0" step="0.5" id="b-proj" value="${bb.teto_projeto_usd ?? ''}"></label>
      ${S.proj ? `<label>Teto deste projeto (US$) <input type="number" min="0" step="0.5" id="b-este" value="${S.proj.teto_projeto ?? ''}"></label>` : ''}
      <label>Pedir aprovação acima de (US$) <input type="number" min="0" step="0.1" id="b-acima" value="${bb.aprovar_acima_usd ?? ''}"></label>
      <div id="b-erro" class="error" style="color:#c33"></div>
      <button id="b-save">Salvar</button>
    </div>`;
  el('modal').hidden = false;
  const inicialEste = S.proj ? el('b-este').value : null;
  el('b-save').onclick = () => {
    const body = {
      teto_mensal_usd: +el('b-mensal').value,
      teto_projeto_usd: +el('b-proj').value,
      aprovar_acima_usd: +el('b-acima').value,
    };
    if (S.proj) {
      const este = el('b-este').value;
      if (este !== inicialEste)   // só fixa/remove o teto próprio se o campo mudou
        body.tetos_projeto = { [S.pid]: este === '' ? null : +este };
    }
    putJSON('/api/budget', {}, body).then(async r => {
      if (r && r.ok === false) {
        const j = await r.json().catch(() => ({}));
        el('b-erro').textContent = j.detail || 'erro ao salvar';
        return;
      }
      closeModal(); if (S.pid) loadProject(S.pid); else getJSON('/api/budget').then(b => { S.budget = b; renderBudget(); });
    }).catch(e => { el('b-erro').textContent = String(e); });
  };
}

el('budget-badge').addEventListener('click', openBudgetModal);

function requestRender(kind) {
  postJSON('/api/queue', { id: S.pid }, { type: 'render', target: null, text: kind })
    .then(() => loadProject(S.pid));
}

el('btn-render-preview').addEventListener('click', () => requestRender('preview'));
el('btn-render-final').addEventListener('click', () => requestRender('final'));

async function loadFormats() {
  S.formats = await getJSON('/api/formats');
  return S.formats;
}

function renderFormatSelect() {
  const sel = el('format-select');
  sel.innerHTML = (S.formats || []).map(f =>
    `<option value="${f.name}">${f.name}</option>`).join('');
  sel.value = (S.proj.state && S.proj.state.formato) || '';
}

el('format-select').addEventListener('change', () => {
  postJSON('/api/state', { id: S.pid }, { formato: el('format-select').value })
    .then(() => loadProject(S.pid));
});

function closeModal() {
  S.docsOpen = false;
  el('modal').hidden = true;
  el('modal').innerHTML = '';
}

el('modal').addEventListener('click', e => {
  if (e.target.id === 'modal' || e.target.closest('.modal-close')) closeModal();
});

async function openFormatsModal() {
  const formats = await loadFormats();
  el('modal').innerHTML = `
    <div class="modal-box modal-formats">
      <button class="modal-close">×</button>
      <h3>Formatos</h3>
      <div class="modal-formats-body">
        <div class="modal-formats-list">${formats.map(f =>
          `<div class="modal-formats-item" data-name="${f.name}">${f.name}</div>`).join('')}</div>
        <div class="modal-formats-edit">
          <textarea id="formats-textarea"></textarea>
          <button id="formats-save">Salvar</button>
        </div>
      </div>
    </div>`;
  el('modal').hidden = false;
  let current = null;
  const setActive = name => {
    current = name;
    el('formats-textarea').value = (formats.find(f => f.name === name) || {}).content || '';
    el('modal').querySelectorAll('.modal-formats-item').forEach(it =>
      it.classList.toggle('active', it.dataset.name === name));
  };
  el('modal').querySelectorAll('.modal-formats-item').forEach(it =>
    it.addEventListener('click', () => setActive(it.dataset.name)));
  if (formats.length) setActive(formats[0].name);
  el('formats-save').addEventListener('click', () => {
    if (!current) return;
    putJSON('/api/format', { name: current }, { content: el('formats-textarea').value })
      .then(loadFormats);
  });
}

el('btn-formats').addEventListener('click', openFormatsModal);

async function openNewProjectModal() {
  const [brutos, formats, brutosRef] = await Promise.all([getJSON('/api/brutos'), loadFormats(), getJSON('/api/brutos-ref')]);
  el('modal').innerHTML = `
    <div class="modal-box">
      <button class="modal-close">×</button>
      <h3>Novo vídeo</h3>
      <label>Formato
        <select id="new-formato">${formats.map(f => `<option value="${f.name}">${f.name}</option>`).join('')}
          <option value="roteiro">roteiro (pesquisa + estrutura antes de gravar)</option>
          <option value="pauta">pauta (ideias do mês com dados)</option>
          <option value="referencia">referência (Reel/Short → conceitos de ad)</option></select>
      </label>
      <label>Bruto
        <select id="new-bruto">${brutos.map(b => `<option value="${b}">${b}</option>`).join('')}</select>
      </label>
      <label>Nome
        <input type="text" id="new-nome" placeholder="nome do vídeo">
      </label>
      <label>Descrição
        <textarea id="new-descricao" placeholder="o que você quer no vídeo..."></textarea>
      </label>
      <label>Fontes
        <input type="text" id="new-fontes" placeholder="projeto, links, docs de onde tirar as informações">
      </label>
      <label class="so-roteiro">Duração alvo (min)<input type="number" id="new-duracao" min="1" value="8"></label>
      <label class="so-roteiro">Público<input type="text" id="new-publico" placeholder="ex.: estudantes de Direito, 1º ano"></label>
      <label class="so-pauta">Marca<input type="text" id="new-marca" placeholder="anotus"></label>
      <label class="so-pauta">Mês<input type="month" id="new-mes"></label>
      <label class="so-ref">URL da referência<input type="text" id="new-ref-url" placeholder="https://www.instagram.com/reel/..."></label>
      <label class="so-ref">ou arquivo em bruto/ref<select id="new-ref-arquivo"><option value="">—</option>${brutosRef.map(b => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join('')}</select></label>
      <label class="so-ref">Marca<input type="text" id="new-ref-marca" placeholder="anotus"></label>
      <button id="new-send" title="Envia o pedido pra fila do Claude">Enviar</button>
      <div id="new-confirm" hidden>pedido enviado — veja a fila</div>
    </div>`;
  el('modal').hidden = false;
  const ajustaCampos = () => {
    const f = el('new-formato').value;
    const isAds = f === 'padrao-ads', isRot = f === 'roteiro', isPauta = f === 'pauta', isRef = f === 'referencia';
    const sel = el('new-bruto');
    const has = sel.querySelector('option[value=""]');
    if ((isAds || isRot || isPauta) && !has) sel.insertAdjacentHTML('afterbegin',
      '<option value="" selected>— sem bruto —</option>');
    if (!(isAds || isRot || isPauta) && has) has.remove();
    sel.closest('label').hidden = isRot || isPauta || isRef;
    el('modal').querySelectorAll('.so-roteiro').forEach(x => x.hidden = !isRot);
    el('modal').querySelectorAll('.so-pauta').forEach(x => x.hidden = !isPauta);
    el('modal').querySelectorAll('.so-ref').forEach(x => x.hidden = !isRef);
    el('new-nome').closest('label').hidden = isPauta;
    el('new-fontes').closest('label').hidden = isPauta || isRef;
    el('new-descricao').placeholder = isRot ? 'tema do vídeo' : isPauta ? 'contexto do mês (opcional)'
      : isRef ? 'briefing: o que o ad precisa dizer' : 'o que você quer no vídeo...';
  };
  el('new-formato').addEventListener('change', ajustaCampos);
  ajustaCampos();
  el('new-send').addEventListener('click', () => {
    const formato = el('new-formato').value;
    const body = { formato, nome: el('new-nome').value.trim(), descricao: el('new-descricao').value.trim(),
                   fontes: el('new-fontes').value.trim(), bruto: el('new-bruto').value || null };
    if (formato === 'roteiro') { body.duracao_min = +el('new-duracao').value; body.publico = el('new-publico').value.trim();
      if (!body.descricao || !body.nome) return; }
    else if (formato === 'pauta') { body.marca = el('new-marca').value.trim(); body.mes = el('new-mes').value;
      if (!body.marca || !body.mes) return; }
    else if (formato === 'referencia') {
      body.origem = el('new-ref-url').value.trim() || (el('new-ref-arquivo').value ? 'bruto/ref/' + el('new-ref-arquivo').value : '');
      body.marca = el('new-ref-marca').value.trim();
      if (!body.origem || !body.nome) return; }
    else if (!body.nome || (!body.bruto && !body.descricao)) return;
    postJSON('/api/new-project', {}, body).then(() => { el('new-confirm').hidden = false; });
  });
}

el('btn-new').addEventListener('click', openNewProjectModal);

async function renderDocsTab() {
  const pid = S.pid;
  const docs = await getJSON('/api/docs', { id: pid });
  if (S.pid !== pid) return;
  const box = el('tab-docs');
  box.innerHTML = `<div class="docs-body">
      <div class="modal-formats-list">${docs.map(d =>
        `<div class="modal-formats-item" data-name="${escapeHtml(d.name)}">${escapeHtml(d.name)}</div>`).join('')
        || '<div class="modal-docs-empty">nenhum doc no projeto</div>'}</div>
      <div class="modal-docs-view" id="docs-view"></div>
    </div>`;
  const show = async name => {
    S.docsName = name;
    if (name.endsWith('.png')) {
      el('docs-view').innerHTML = '<img style="max-width:100%" src="' + api('/api/file', { id: pid, name }) + '">';
    } else {
      const d = await getJSON('/api/doc', { id: pid, name });
      el('docs-view').innerHTML = d.html;   // servidor já escapou tudo
    }
    box.querySelectorAll('.modal-formats-item').forEach(it =>
      it.classList.toggle('active', it.dataset.name === name));
  };
  box.querySelectorAll('.modal-formats-item').forEach(it =>
    it.addEventListener('click', () => show(it.dataset.name)));
  const ini = docs.find(d => d.name === S.docsName) || docs[0];
  if (ini) show(ini.name);
}

function renderCustosTab() {
  const c = S.proj.custos || { usd: 0, creditos: 0 };
  const q = S.quadro || { etapas: [], fora_da_receita: [] };
  const linhas = q.etapas.concat(q.fora_da_receita).filter(e => e.custo_usd > 0);
  const soma = linhas.reduce((s, e) => s + e.custo_usd, 0);
  const resto = Math.max(0, (c.usd || 0) - soma);
  const temResto = resto > 0.00005;
  el('tab-custos').innerHTML = `<div class="custos">
      <div class="custos-total">Projeto: <b class="mono">${fmtUSD(c.usd)}</b> / <span class="mono">${fmtUSD(S.proj.teto_projeto)}</span> · <span class="mono">${c.creditos || 0}</span> créditos</div>
      <table class="custos-tab"><thead><tr><th>etapa</th><th>US$</th></tr></thead><tbody>
        ${linhas.map(e => `<tr><td>${escapeHtml(e.rotulo)}</td><td class="mono">${fmtUSD(e.custo_usd)}</td></tr>`).join('')}
        ${temResto ? `<tr><td class="dim">fora de etapa</td><td class="mono">${fmtUSD(resto)}</td></tr>` : ''}
      </tbody></table>
      ${linhas.length || temResto ? '' : '<div class="dim">nenhum gasto ainda</div>'}
      <button id="custos-tetos">Editar tetos</button>
    </div>`;
  el('custos-tetos').onclick = openBudgetModal;
}

window.addEventListener('DOMContentLoaded', route);   // depois de library.js e board.js
