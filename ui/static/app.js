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

function toggleApproval(i) {
  const cur = new Set((S.proj.state && S.proj.state.aprovacoes) || []);
  if (cur.has(i)) cur.delete(i); else cur.add(i);
  postJSON('/api/state', { id: S.pid }, { aprovacoes: [...cur] })
    .then(() => loadProject(S.pid));
}

function sendVeto(i) {
  postJSON('/api/queue', { id: S.pid }, {
    type: 'veto', target: i, text: `revisar/remover corte #${i}`,
  }).then(() => loadProject(S.pid));
}

function renderCutList() {
  const ranges = S.proj.edl.ranges;
  const aprovacoes = new Set((S.proj.state && S.proj.state.aprovacoes) || []);
  const queue = S.proj.queue || [];
  el('cut-list').innerHTML = ranges.map((r, i) => {
    const cls = aprovacoes.has(i) ? 'status-approved'
      : queueTargetsSegment(queue, i) ? 'status-pending' : '';
    return `<div class="cut-row ${cls}" data-i="${i}">
      <span class="cut-label">#${i}  ${fmtTime(r.start)}–${fmtTime(r.end)}</span>
      <button class="cut-up" data-i="${i}">👍</button>
      <button class="cut-down" data-i="${i}">👎</button>
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
  }).then(() => { ta.value = ''; loadProject(S.pid); });
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
    ctx.fillStyle = 'rgba(79,140,255,0.4)';
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
    S.selected = hit.index;
    const ic = el('instr-context');
    if (ic) ic.textContent = `sobre corte #${hit.index}`;
    renderTimeline();
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

function onPointerDown(e) {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  const hit = hitSegment(x, y);
  if (hit && hit.edge) {
    drag = { type: 'edge', seg: hit.index, edge: hit.edge, startX: x, deltaSec: 0 };
    canvas.setPointerCapture(e.pointerId);
    return;
  }
  drag = { type: 'pan', startX: x, startT0: view.t0, moved: false };
  canvas.setPointerCapture(e.pointerId);
}

function onPointerMove(e) {
  if (!drag) return;
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  if (drag.type === 'edge') {
    drag.deltaSec = (x - drag.startX) / view.pxPerSec;
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
      }).then(() => loadProject(S.pid));
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
  buildTimeMap();
  initTimelineOnce();
  if (S.pid !== lastFitPid) { fitView(); lastFitPid = S.pid; }
  renderCutList();
  renderTimeline();
  renderQueue();
  renderProgress();
  if (S.formats) renderFormatSelect(); else loadFormats().then(renderFormatSelect);
}

// ---------------------------------------------------------------------
// Fila viva, render/progresso, formatos, novo vídeo (Task 9)
// ---------------------------------------------------------------------

const STATUS_ICON = { pending: '⏳', executing: '▶', waiting_reply: '❓', done: '✅', failed: '❌' };

function renderQueue() {
  const queue = (S.proj.queue || []).slice().reverse();
  el('queue-panel').innerHTML = queue.length ? queue.map(e => {
    const icon = STATUS_ICON[e.status] || '';
    const sub = e.resultado ? `<div class="queue-sub">${escapeHtml(e.resultado)}</div>` : '';
    const reply = e.status === 'waiting_reply' ? `<div class="queue-reply">
        <input type="text" class="queue-reply-input" data-qid="${e.id}" placeholder="responder...">
        <button class="queue-reply-send" data-qid="${e.id}">Enviar</button>
      </div>` : '';
    return `<div class="queue-row">
      <div class="queue-main"><span class="queue-icon">${icon}</span><span class="queue-text">${escapeHtml(e.text || e.type)}</span></div>
      ${sub}${reply}
    </div>`;
  }).join('') : '<div class="queue-empty">fila vazia</div>';
}

function sendReply(qid, text) {
  return postJSON('/api/reply', { id: S.pid }, { qid, text }).then(() => loadProject(S.pid));
}

el('queue-panel').addEventListener('click', e => {
  const btn = e.target.closest('.queue-reply-send');
  if (!btn) return;
  const input = el('queue-panel').querySelector(`.queue-reply-input[data-qid="${btn.dataset.qid}"]`);
  const text = input.value.trim();
  if (text) sendReply(+btn.dataset.qid, text);
});
el('queue-panel').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.classList.contains('queue-reply-input')) return;
  const text = e.target.value.trim();
  if (text) sendReply(+e.target.dataset.qid, text);
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
  const [brutos, formats] = await Promise.all([getJSON('/api/brutos'), loadFormats()]);
  el('modal').innerHTML = `
    <div class="modal-box">
      <button class="modal-close">×</button>
      <h3>Novo vídeo</h3>
      <label>Bruto
        <select id="new-bruto">${brutos.map(b => `<option value="${b}">${b}</option>`).join('')}</select>
      </label>
      <label>Formato
        <select id="new-formato">${formats.map(f => `<option value="${f.name}">${f.name}</option>`).join('')}</select>
      </label>
      <label>Nome
        <input type="text" id="new-nome" placeholder="nome do vídeo">
      </label>
      <button id="new-send">Enviar</button>
      <div id="new-confirm" hidden>pedido enviado — Claude vai iniciar a edição</div>
    </div>`;
  el('modal').hidden = false;
  el('new-send').addEventListener('click', () => {
    const bruto = el('new-bruto').value;
    const formato = el('new-formato').value;
    const nome = el('new-nome').value.trim();
    if (!nome) return;
    postJSON('/api/new-project', {}, { bruto, formato, nome })
      .then(() => { el('new-confirm').hidden = false; });
  });
}

el('btn-new').addEventListener('click', openNewProjectModal);

loadProjects();
