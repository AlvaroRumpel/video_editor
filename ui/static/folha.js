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

// ---- clipes: caixa 9:16 com o recorte real (crop 608x1080 em x do quadro 1920x1080) ----
const ALTURA_916 = 320;
const ESC_916 = ALTURA_916 / 1080;

function tocaClipe(card, c) {
  const v = card.querySelector('.fl-916 video');
  if (!v.paused) { v.pause(); return; }
  let i = 0;
  v.currentTime = c.ranges[0].t_in;
  v.ontimeupdate = () => {
    if (v.currentTime < c.ranges[i].t_out) return;
    i += 1;
    if (i >= c.ranges.length) { v.pause(); v.ontimeupdate = null; return; }
    v.currentTime = c.ranges[i].t_in;
  };
  v.play().catch(() => {});
}

FOLHA_TIPOS.clips = {
  sel: d => ({ c: Object.fromEntries(d.clipes.map(c => [c.id, { veto: false, nota: c.nota, x: c.x, legenda: c.legenda }])) }),
  html: d => {
    const src = api('/api/video', { id: S.pid, kind: S.proj.has_final ? 'final' : 'preview' });
    return d.clipes.map(c => `<div class="fl-clip" data-c="${escapeHtml(c.id)}">
        <div class="fl-916" title="clique: tocar/pausar o clipe"><video muted preload="metadata" src="${src}" onerror="${falta}"></video></div>
        <div class="fl-ganch">${escapeHtml(c.gancho)}</div>
        <div class="mono dim">${escapeHtml(c.id)} · ${fmtMSS(c.dur)} · ${escapeHtml(c.plataformas.join(', '))}</div>
        <div class="fl-nota">${[1, 2, 3, 4, 5].map(n => `<button data-nota="${n}" title="nota ${n}">★</button>`).join('')}</div>
        <label class="fl-xl">x <input type="range" class="fl-x" min="0" max="1312" step="2"> <span class="mono fl-xv"></span></label>
        <label><input type="checkbox" class="fl-legenda"> legenda</label>
        <button class="fl-veto">vetar</button>
      </div>`).join('') || '<div class="dim">nenhum clipe proposto</div>';
  },
  marca: (box, d, s) => box.querySelectorAll('.fl-clip').forEach(k => {
    const x = s.c[k.dataset.c];
    k.classList.toggle('vetado', x.veto);
    k.querySelectorAll('.fl-nota button').forEach(b => b.classList.toggle('on', +b.dataset.nota <= (x.nota || 0)));
    const r = k.querySelector('.fl-x');
    if (+r.value !== x.x) r.value = x.x;
    k.querySelector('.fl-xv').textContent = x.x;
    k.querySelector('.fl-legenda').checked = x.legenda;
    k.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
    k.querySelector('.fl-916 video').style.transform = `translateX(${-x.x * ESC_916}px)`;
  }),
  clique: (e, d, s) => {
    const k = e.target.closest('.fl-clip');
    if (!k) return false;
    const x = s.c[k.dataset.c];
    const n = e.target.closest('[data-nota]');
    if (n) { x.nota = +n.dataset.nota; return true; }
    if (e.target.closest('.fl-veto')) { x.veto = !x.veto; return true; }
    if (e.target.classList.contains('fl-legenda')) { x.legenda = e.target.checked; return true; }
    if (e.target.closest('.fl-916')) tocaClipe(k, d.clipes.find(c => c.id === k.dataset.c));
    return false;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-x')) return false;
    s.c[e.target.closest('.fl-clip').dataset.c].x = +e.target.value;
    return true;
  },
  resposta: (d, s) => okMais(d.clipes.flatMap(c => {
    const x = s.c[c.id];
    if (x.veto) return [`${c.id}:não`];
    const t = [];
    if (x.nota !== c.nota) t.push(`${c.id}:nota ${x.nota}`);
    if (x.x !== c.x) t.push(`${c.id}:x=${x.x}`);
    if (x.legenda !== c.legenda) t.push(`${c.id}:${x.legenda ? 'legenda' : 'sem-legenda'}`);
    return t;
  })),
};

// ---- conceitos A/B/C ----
FOLHA_TIPOS.conceitos = {
  sel: () => ({ um: null, varios: false, marcados: [], ajuste: '' }),
  html: d => `<label class="fl-varios"><input type="checkbox" class="fl-varios-cb"> produzir vários</label>
    <div class="fl-cols">${d.conceitos.map(c => `<div class="fl-col" data-cc="${escapeHtml(c.id)}">
        ${c.animatic ? `<img class="fl-anim" alt="animatic ${escapeHtml(c.id)}" title="clique: ampliar" src="${midia(c.animatic)}" onerror="this.classList.add('fl-falta')">`
                     : '<div class="fl-anim fl-falta"></div>'}
        <h4>${escapeHtml(c.id)}</h4>
        <p>${escapeHtml(c.ideia)}</p>
        <dl><dt>mantém</dt><dd>${escapeHtml(c.mantem)}</dd><dt>muda</dt><dd>${escapeHtml(c.muda)}</dd>
          <dt>custo</dt><dd class="mono">${escapeHtml(c.custo)}</dd><dt>horas</dt><dd class="mono">${escapeHtml(c.horas ?? '')}</dd></dl>
        ${c.exige_ia ? '<span class="tag espera">exige IA</span>' : ''}
        <label class="fl-um"><input type="radio" name="fl-um" value="${escapeHtml(c.id)}"> escolher</label>
        <label class="fl-mult"><input type="checkbox" class="fl-mult-cb" value="${escapeHtml(c.id)}"> produzir</label>
      </div>`).join('')}</div>
    <label class="fl-ajuste-l">ajuste <textarea class="fl-ajuste" rows="2" placeholder="em vez de escolher, pedir mudança"></textarea></label>`,
  marca: (box, d, s) => {
    box.querySelector('.fl-varios-cb').checked = s.varios;
    box.querySelectorAll('.fl-um').forEach(l => { l.hidden = s.varios; });
    box.querySelectorAll('.fl-mult').forEach(l => { l.hidden = !s.varios; });
    box.querySelectorAll('input[name=fl-um]').forEach(r => { r.checked = r.value === s.um; });
    box.querySelectorAll('.fl-mult-cb').forEach(c => { c.checked = s.marcados.includes(c.value); });
    box.querySelectorAll('.fl-col').forEach(c => c.classList.toggle('sel',
      s.varios ? s.marcados.includes(c.dataset.cc) : c.dataset.cc === s.um));
    const a = box.querySelector('.fl-ajuste');
    if (a.value !== s.ajuste) a.value = s.ajuste;
  },
  clique: (e, d, s) => {
    const t = e.target;
    if (t.tagName === 'IMG' && t.classList.contains('fl-anim')) { t.classList.toggle('grande'); return false; }
    if (t.classList.contains('fl-varios-cb')) { s.varios = t.checked; return true; }
    if (t.name === 'fl-um') { s.um = t.value; return true; }
    if (t.classList.contains('fl-mult-cb')) {
      s.marcados = t.checked ? [...new Set([...s.marcados, t.value])] : s.marcados.filter(v => v !== t.value);
      return true;
    }
    return false;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-ajuste')) return false;
    s.ajuste = e.target.value;
    return true;
  },
  resposta: (d, s) => {
    if (s.ajuste.trim()) return 'ajuste: ' + s.ajuste.trim();
    if (s.varios) return s.marcados.length >= 2 ? 'produzir: ' + [...s.marcados].sort().join(' ') : (s.marcados[0] || '');
    return s.um || '';
  },
};

// ---- overlays: frame de cada overlay do edl.json ----
FOLHA_TIPOS.overlays = {
  sel: d => ({ o: Object.fromEntries(d.overlays.map(o => [o.id, { veto: false, texto: '' }])) }),
  html: d => (d.overlays.length ? `<div class="fl-grade">${d.overlays.map(o => `<div class="fl-ov" data-o="${escapeHtml(o.id)}">
        ${o.png ? `<img alt="" src="${midia(o.png)}" onerror="this.classList.add('fl-falta')">`
                : `<div class="fl-falta fl-ovph">${escapeHtml(o.erro || 'sem frame')}</div>`}
        <div class="mono dim">${escapeHtml(o.id)} · ${fmtMSS(o.t)} · ${o.dur.toFixed(1)}s</div>
        <div class="fl-arq dim">${escapeHtml(o.arquivo)}</div>
        <button class="fl-veto">vetar</button>
        <input type="text" class="fl-otexto" placeholder="pedir mudança...">
      </div>`).join('')}</div>` : '<div class="dim">nenhum overlay</div>'),
  marca: (box, d, s) => box.querySelectorAll('.fl-ov').forEach(k => {
    const x = s.o[k.dataset.o];
    k.classList.toggle('vetado', x.veto);
    k.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
    const t = k.querySelector('.fl-otexto');
    t.disabled = x.veto;
    if (t.value !== x.texto) t.value = x.texto;
  }),
  clique: (e, d, s) => {
    const k = e.target.closest('.fl-ov');
    if (!k || !e.target.closest('.fl-veto')) return false;
    const x = s.o[k.dataset.o];
    x.veto = !x.veto;
    return true;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-otexto')) return false;
    s.o[e.target.closest('.fl-ov').dataset.o].texto = e.target.value;
    return true;
  },
  resposta: (d, s) => okMais(d.overlays.flatMap(o => {
    const x = s.o[o.id];
    return x.veto ? [`${o.id}:não`] : x.texto.trim() ? [`${o.id}: ${x.texto.trim()}`] : [];
  })),
};
