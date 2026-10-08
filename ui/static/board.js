// Stepper + Board do projeto. Dados: S.quadro (eventos.quadro) + S.proj.

function infoAudio(st) {
  const a = st.audio;
  if (!a) return '';
  const partes = [];
  if (a.trilha) partes.push(`trilha ${a.trilha} · ${a.nivel_db ?? -18} dB · duck ${a.duck_db ?? -8} dB`);
  if (a.denoise) partes.push(`denoise ${a.denoise}`);
  if (a.ruido_db != null) partes.push(`ruído ${Number(a.ruido_db).toFixed(0)} dB`);
  return partes.length ? 'áudio: ' + partes.join(' · ') : '';
}

const cnt = v => Array.isArray(v) ? v.length : (v ?? 0);

function infoBroll(st) {
  const b = st.broll;
  if (!b) return '';
  const fontes = Object.entries(b.fontes || {}).map(([k, v]) => `${k} ${v}`).join(', ');
  return `b-roll: ${cnt(b.aprovados)}/${cnt(b.momentos)} aprovados${fontes ? ' · ' + fontes : ''}`;
}

function infoClips(st) {
  const c = st.clips;
  if (!c) return '';
  return `clips: ${cnt(c.aprovados)} aprovados · ${cnt(c.renderizados)} renderizados · ${cnt(c.publora_drafts)} drafts`;
}

function infoRef(st) {
  const r = st.ref;
  if (!r) return '';
  return `ref: ${cnt(r.conceitos)} conceitos` + (r.escolhido ? ` · escolhido ${r.escolhido}` : '') +
    (r.produzidos && r.produzidos.length ? ` · produzidos ${r.produzidos.join(', ')}` : '');
}

function infoDub(st) {
  const i = st.dub && st.dub.idiomas;
  if (!i || typeof i !== 'object') return '';
  const partes = Object.keys(i).sort().map(l => `${l} ${(i[l] && i[l].etapa) || '?'}`);
  return partes.length ? 'dub: ' + partes.join(' · ') : '';
}

const INFO_SLOT = [['audio', infoAudio], ['visual', infoBroll], ['candidatos', infoClips], ['referencia', infoRef], ['dublagem', infoDub]];

function renderStepper() {
  const q = S.quadro;
  const box = el('stepper');
  if (!q || !q.etapas.length) { box.innerHTML = '<span class="step-tag">sem etapas</span>'; return; }
  box.innerHTML = q.etapas.map(e =>
    `<button class="step st-${e.status}" data-etapa="${escapeHtml(e.id)}" title="${STATUS_LABEL[e.status] || e.status}">` +
    `${e.status === 'espera' ? '❓ ' : ''}${escapeHtml(e.rotulo)}</button>`).join('') +
    (q.sem_historico ? '<span class="step-tag">sem histórico</span>' : '');
}

el('stepper').addEventListener('click', e => {
  const b = e.target.closest('.step');
  if (!b) return;
  S.scrollTo = b.dataset.etapa;
  goTab('board');
});

const fmtHora = ts => ts ? new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';
const fmtDur = (a, b) => fmtMSS(((b ? new Date(b) : new Date()) - new Date(a)) / 1000);

// decisão do Claude: resumo na linha, motivo/custo ao expandir (<details> nativo)
function decisaoHtml(d) {
  const alt = d.alternativas && d.alternativas.length
    ? ` <span class="dim">(vs ${escapeHtml(d.alternativas.join(', '))})</span>` : '';
  const conf = d.confianca
    ? ` <span class="conf conf-${escapeHtml(d.confianca)}" title="confiança ${escapeHtml(d.confianca)}">●</span>` : '';
  const custo = d.custo_usd != null ? ` <span class="mono">${fmtUSD(d.custo_usd)}</span>` : '';
  return `<details class="dec" data-k="${escapeHtml(d.ts + '|' + d.assunto)}">
      <summary><span class="tag">${escapeHtml(d.assunto)}</span> ${escapeHtml(d.escolha)}${alt}${conf}</summary>
      <div class="dec-mot">${escapeHtml(d.motivo || 'sem motivo registrado')}${custo}</div>
    </details>`;
}

function boardCard(e, infos, pedido, fora) {
  // duração só com fim (inicio→fim) ou em andamento (inicio→agora); falha/pulada/espera = só a hora de início
  const tempo = e.inicio && e.fim ? `${fmtHora(e.inicio)}–${fmtHora(e.fim)} · ${fmtDur(e.inicio, e.fim)}`
    : e.inicio && e.status === 'andamento' ? `${fmtHora(e.inicio)} · ${fmtDur(e.inicio)}`
    : fmtHora(e.inicio || e.fim);
  const linhas = (infos[e.id] || []).map(t => `<div class="info-line">${escapeHtml(t)}</div>`).join('');
  const pergunta = pedido ? escapeHtml(pedido.resultado || pedido.text || '') : '';
  const perg = !pedido ? ''
    : FOLHAS.includes(pedido.folha)
      ? `<div class="board-pergunta">
          <div class="board-q">${pergunta}</div>
          <a class="board-folha" href="${hashFor(S.pid, 'aprovacao')}">abrir folha ›</a>
        </div>`
      : `<div class="board-pergunta">
          <div class="board-q">${pergunta}</div>
          <textarea class="board-reply-input" data-pid="${escapeHtml(S.pid)}" data-qid="${pedido.id}" rows="2" placeholder="responder... (Enter envia, Ctrl+Enter quebra linha)"></textarea>
          <button class="board-reply-send" data-qid="${pedido.id}">Enviar</button>
        </div>`;
  return `<div class="board-card st-${e.status}" id="card-${escapeHtml(e.id)}">
      <div class="bc-head"><span class="bc-rot">${escapeHtml(e.rotulo)}</span>
        <span class="bc-status">${STATUS_LABEL[e.status] || e.status}</span>
        ${fora ? '<span class="tag">fora da receita</span>' : ''}
        <span class="spacer"></span><span class="mono dim">${tempo}</span>
        <span class="mono">${e.custo_usd > 0 ? fmtUSD(e.custo_usd) : ''}</span></div>
      ${e.nota ? `<div class="bc-nota">${escapeHtml(e.nota)}</div>` : ''}
      ${linhas}${(e.decisoes || []).map(decisaoHtml).join('')}${perg}
    </div>`;
}

// rascunhos de resposta por `${pid}:${qid}` — sobrevivem a redesenho e troca de aba
const boardDrafts = {};
const draftKey = t => t.dataset.pid + ':' + t.dataset.qid;   // pid gravado no DOM: troca de projeto não mistura

function renderBoard() {
  const box = el('tab-board');
  box.querySelectorAll('.board-reply-input').forEach(t => { boardDrafts[draftKey(t)] = t.value; });
  const ae = document.activeElement;
  const foco = ae && ae.classList.contains('board-reply-input')
    ? { k: draftKey(ae), a: ae.selectionStart, b: ae.selectionEnd } : null;
  const abertos = new Set([...box.querySelectorAll('details.dec[open]')].map(d => d.dataset.k));
  const q = S.quadro || { etapas: [], fora_da_receita: [], atual: null };
  const st = (S.proj && S.proj.state) || {};
  const ids = new Set(q.etapas.map(e => e.id));
  const infos = {}, outros = [];
  for (const [slot, fn] of INFO_SLOT) {
    const t = fn(st);
    if (!t) continue;
    if (ids.has(slot)) (infos[slot] = infos[slot] || []).push(t); else outros.push(t);
  }
  const pedido = ((S.proj && S.proj.queue) || [])
    .filter(e => e.status === 'waiting_reply').sort((a, b) => a.id - b.id)[0];
  const todas = q.etapas.concat(q.fora_da_receita);
  const atualEspera = todas.find(e => e.id === q.atual && e.status === 'espera');
  const alvo = (atualEspera || todas.find(e => e.status === 'espera') || {}).id;
  let html = q.etapas.map(e => boardCard(e, infos, e.id === alvo ? pedido : null, false)).join('');
  html += q.fora_da_receita.map(e => boardCard(e, infos, e.id === alvo ? pedido : null, true)).join('');
  const soltas = q.decisoes_soltas || [];
  if (outros.length || soltas.length) html += `<div class="board-card" id="card-outros"><div class="bc-head"><span class="bc-rot">outros</span></div>` +
    outros.map(t => `<div class="info-line">${escapeHtml(t)}</div>`).join('') + soltas.map(decisaoHtml).join('') + '</div>';
  box.innerHTML = html || '<div class="board-vazio dim">sem etapas — o formato deste projeto não declara etapas</div>';
  box.querySelectorAll('details.dec').forEach(d => { if (abertos.has(d.dataset.k)) d.open = true; });
  box.querySelectorAll('.board-reply-input').forEach(t => {
    const k = draftKey(t);
    if (boardDrafts[k]) t.value = boardDrafts[k];
    if (foco && foco.k === k) { t.focus(); t.setSelectionRange(foco.a, foco.b); }
  });
  let alvoScroll = null;
  if (S.scrollTo) { alvoScroll = S.scrollTo; S.scrollTo = null; }
  else if (S.boardScrolled !== S.pid) { S.boardScrolled = S.pid; alvoScroll = q.atual; }
  const c = alvoScroll && document.getElementById('card-' + alvoScroll);
  if (c) c.scrollIntoView({ block: 'center' });
}

function boardReply(input) {
  const text = input.value.trim();
  if (!text) return;
  const k = draftKey(input);
  delete boardDrafts[k];
  input.value = '';
  sendReply(+input.dataset.qid, text, 'proj').catch(e => {   // falhou: texto volta ao rascunho
    console.warn(e);
    if (!boardDrafts[k]) boardDrafts[k] = text;
    el('tab-board').querySelectorAll('.board-reply-input').forEach(t => {
      if (draftKey(t) === k && !t.value) t.value = text;
    });
  });
}

el('tab-board').addEventListener('click', e => {
  const b = e.target.closest('.board-reply-send');
  if (b) boardReply(b.closest('.board-pergunta').querySelector('.board-reply-input'));
});
el('tab-board').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.classList.contains('board-reply-input')) return;
  e.preventDefault();
  if (e.ctrlKey) {   // Ctrl+Enter = quebra de linha (como no painel da fila)
    const ta = e.target, p = ta.selectionStart;
    ta.value = ta.value.slice(0, p) + '\n' + ta.value.slice(ta.selectionEnd);
    ta.selectionStart = ta.selectionEnd = p + 1;
    return;
  }
  boardReply(e.target);   // Enter puro = envia
});
