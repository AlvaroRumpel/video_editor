// Folhas de aprovação (aba "Aprovação"): mostram o artefato do pedido waiting_reply com `folha`
// e montam a resposta textual (`ok` + exceções). A UI não escreve artefato: só responde a fila.
// Cada tipo registra em FOLHA_TIPOS: { sel(d), html(d), marca(box, d, s), clique?(e, d, s), entrada?(e, d, s), resposta(d, s) }.
const FOLHA_TIPOS = {};
const folhaSel = {};   // `${pid}:${qid}` → seleção + comentário (sobrevive a redesenho e troca de aba)
let folhaAtual = { key: null, tipo: null, qid: null, dados: null, erro: null };

function pedidoFolha() {
  return ((S.proj && S.proj.queue) || [])
    .filter(e => e.status === 'waiting_reply' && FOLHAS.includes(e.folha))
    .sort((a, b) => a.id - b.id)[0] || null;
}

const midia = arq => api('/api/file', { id: S.pid, name: arq });
const okMais = toks => (toks.length ? 'ok ' + toks.join(' ') : 'ok');

function resposta(tipo, d, s) {   // pura
  const T = FOLHA_TIPOS[tipo];
  return T && d && s ? T.resposta(d, s) : '';
}

// pedido respondido por qualquer caminho (folha, fila, board): o mesmo qid pode voltar a
// waiting_reply com artefato refeito, então a próxima folha redesenha do zero
function esqueceFolha() {
  el('tab-aprovacao').dataset.key = '';
  for (const k in folhaSel) if (k.startsWith(S.pid + ':')) delete folhaSel[k];
}

async function renderFolha() {
  const box = el('tab-aprovacao');
  const p = pedidoFolha();
  if (!p) { box.innerHTML = ''; box.dataset.key = ''; return; }
  const key = `${S.pid}:${p.id}`;
  if (box.dataset.key === key) return;   // já desenhada: SSE não apaga vídeo, seleção nem comentário
  box.dataset.key = key;
  folhaAtual = { key, tipo: p.folha, qid: p.id, dados: null, erro: null };
  box.innerHTML = '<div class="dim fl-carregando">carregando folha…</div>';
  try {
    const r = await fetch(api('/api/folha', { id: S.pid, tipo: p.folha }));
    if (folhaAtual.key !== key) return;
    if (r.ok) folhaAtual.dados = await r.json();
    else folhaAtual.erro = (await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`;
  } catch (e) {
    if (folhaAtual.key !== key) return;
    folhaAtual.erro = String(e);
  }
  desenhaFolha(box, p);
}

function desenhaFolha(box, p) {
  const { key, tipo, dados, erro } = folhaAtual;
  const T = FOLHA_TIPOS[tipo];
  const cab = `<div class="fl-cab"><span class="tag">${escapeHtml(tipo)}</span>
    <span class="fl-perg">${escapeHtml(p.resultado || p.text || '')}</span></div>`;
  if (erro || !T) {
    box.innerHTML = cab + `<div class="fl-erro">folha indisponível — responda pela fila
      <div class="dim">${escapeHtml(erro || 'tipo desconhecido')}</div></div>`;
    return;
  }
  if (!folhaSel[key]) folhaSel[key] = { ...T.sel(dados), coment: '' };
  box.innerHTML = cab + `<div class="fl-corpo fl-${tipo}">${T.html(dados)}</div>
    <div class="fl-rodape">
      <div class="mono" id="fl-resp"></div>
      <textarea id="fl-coment" rows="2" placeholder="comentário (opcional)"></textarea>
      <button id="fl-enviar">Enviar</button>
    </div>`;
  el('fl-coment').value = folhaSel[key].coment || '';
  atualizaFolha();
}

function atualizaFolha() {
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (!T || !s || !el('fl-resp')) return;
  T.marca(el('tab-aprovacao'), dados, s);
  const r = resposta(tipo, dados, s);
  el('fl-resp').textContent = r || '—';
  el('fl-enviar').disabled = !r;
}

function enviaFolha() {
  const { key, tipo, dados, qid } = folhaAtual;
  const s = folhaSel[key];
  const r = resposta(tipo, dados, s);
  if (!r) return;
  const coment = (s.coment || '').trim();
  el('fl-enviar').disabled = true;
  sendReply(qid, coment ? r + '\n' + coment : r, 'proj')
    .then(() => { delete folhaSel[key]; })
    .catch(e => {   // falhou: seleção e comentário continuam em folhaSel
      console.warn(e);
      if (el('fl-enviar')) el('fl-enviar').disabled = false;
    });
}

el('tab-aprovacao').addEventListener('click', e => {
  if (e.target.closest('#fl-enviar')) { enviaFolha(); return; }
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (T && s && T.clique && T.clique(e, dados, s)) atualizaFolha();
});

el('tab-aprovacao').addEventListener('input', e => {
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (!s) return;
  if (e.target.id === 'fl-coment') { s.coment = e.target.value; return; }
  if (T && T.entrada && T.entrada(e, dados, s)) atualizaFolha();
});

// vídeo candidato toca no hover
el('tab-aprovacao').addEventListener('mouseover', e => {
  const v = e.target.closest('.fl-cand video');
  if (v) v.play().catch(() => {});
});
el('tab-aprovacao').addEventListener('mouseout', e => {
  const v = e.target.closest('.fl-cand video');
  if (v) v.pause();
});

// ---- b-roll: momento × candidatos ----
const kDe = rot => (rot ? +String(rot).split('-').pop() : 1);
const falta = "this.parentNode.classList.add('fl-falta')";

FOLHA_TIPOS.broll = {
  sel: d => ({ m: Object.fromEntries(d.momentos.map(m => [m.id, { k: kDe(m.escolhido), prop: kDe(m.escolhido), veto: false }])) }),
  html: d => d.momentos.map(m => `<div class="fl-row" data-m="${escapeHtml(m.id)}">
      <div class="fl-lab"><b>${escapeHtml(m.id)}</b><span class="mono">${fmtMSS(m.t_in)}</span>
        <span>${escapeHtml(m.termo)}</span><span class="dim">${escapeHtml(m.modo)}</span></div>
      <div class="fl-cands">${m.candidatos.map((c, i) => `<div class="fl-cand" data-k="${i + 1}">
        ${c.tipo === 'video'
          ? `<video muted loop preload="metadata" src="${midia(c.arq)}" onerror="${falta}"></video>`
          : `<img alt="" src="${midia(c.arq)}" onerror="${falta}">`}
        <span class="fl-leg">${i + 1} · ${escapeHtml(c.fonte)} · ${c.tipo === 'video' ? Math.round(c.dur) + 's' : 'foto'}${c.licenca ? ' · ' + escapeHtml(c.licenca) : ''}</span>
      </div>`).join('')}</div>
      <button class="fl-veto">vetar</button>
    </div>`).join('') || '<div class="dim">nenhum momento proposto</div>',
  marca: (box, d, s) => box.querySelectorAll('.fl-row').forEach(r => {
    const x = s.m[r.dataset.m];
    r.classList.toggle('vetado', x.veto);
    r.querySelectorAll('.fl-cand').forEach(c => c.classList.toggle('sel', !x.veto && +c.dataset.k === x.k));
    r.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
  }),
  clique: (e, d, s) => {
    const r = e.target.closest('.fl-row');
    if (!r) return false;
    const x = s.m[r.dataset.m];
    if (e.target.closest('.fl-veto')) { x.veto = !x.veto; return true; }
    const c = e.target.closest('.fl-cand');
    if (!c) return false;
    x.k = +c.dataset.k; x.veto = false;
    return true;
  },
  resposta: (d, s) => okMais(d.momentos.flatMap(m => {
    const x = s.m[m.id];
    return x.veto ? [`${m.id}:não`] : x.k !== x.prop ? [`${m.id}:${x.k}`] : [];
  })),
};
