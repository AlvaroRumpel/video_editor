// Aba "Linha do tempo": eventos do projeto em ordem (etapas, decisões, perguntas, respostas, custos)
// com filtros e replay — o servidor manda um quadro resumido por evento, o cliente só indexa.
const LINHA_TIPOS = ['etapa', 'decisao', 'pergunta', 'resposta', 'custo'];
const LINHA_ROT = { etapa: 'etapas', decisao: 'decisões', pergunta: 'perguntas', resposta: 'respostas', custo: 'custos' };
const LINHA_ICO = { etapa: '▸', decisao: '◆', pergunta: '❓', resposta: '↩', custo: '$' };
const LINHA_STATUS = { inicio: 'início', fim: 'fim', espera: 'espera', pulada: 'pulada', falha: 'falha' };
let linhaDados = { pid: null, eventos: [], quadros: [] };
const linhaFiltro = { tipos: new Set(LINHA_TIPOS), assunto: null };
let linhaPos = 0, linhaTimer = null, linhaVel = 1, linhaReq = 0;

const tipoLinha = e => (e.tipo === 'etapa' && e.status === 'espera' && e.nota ? 'pergunta' : e.tipo);

function textoLinha(e) {
  const t = tipoLinha(e);
  if (t === 'custo') return `${e.provedor} · ${fmtUSD(e.usd)}${e.nota ? ' · ' + e.nota : ''}`;
  if (t === 'resposta') return `você: ${e.texto}`;
  if (t === 'decisao') return `${e.assunto} · ${e.escolha}${e.alternativas.length ? ' (vs ' + e.alternativas.join(', ') + ')' : ''}${e.motivo ? ' — ' + e.motivo : ''}`;
  if (t === 'pergunta') return `${e.etapa} · ${e.nota}`;
  return `${e.etapa} · ${LINHA_STATUS[e.status] || e.status}${e.nota ? ' — ' + e.nota : ''}`;
}

function visiveis() {
  return linhaDados.eventos.map((_, i) => i).filter(i => {
    const e = linhaDados.eventos[i], t = tipoLinha(e);
    return linhaFiltro.tipos.has(t) && (t !== 'decisao' || !linhaFiltro.assunto || e.assunto === linhaFiltro.assunto);
  });
}

async function renderLinha(forcar, redesenhar = false) {
  const pid = S.pid;
  if (linhaDados.pid !== pid) {   // outro projeto: nunca mostrar a linha do anterior, nem enquanto carrega
    pausaLinha();
    linhaPos = 0;
    linhaFiltro.assunto = null;
    linhaDados = { pid: null, eventos: [], quadros: [] };   // pid fica null até o fetch dar certo
    el('tab-linha').innerHTML = '<div class="dim linha-msg">carregando…</div>';
  } else if (!forcar) { desenhaLinha(); return; }
  const req = ++linhaReq;
  let d;
  try { d = await getJSON('/api/linha', { id: pid }); } catch (e) {
    console.warn('linha falhou', e);
    if (req === linhaReq && S.pid === pid && linhaDados.pid !== pid)
      el('tab-linha').innerHTML = '<div class="dim linha-msg">linha indisponível</div>';
    return;
  }
  if (req !== linhaReq || S.pid !== pid) return;   // resposta atrasada ou projeto trocado
  const eventos = d.eventos || [];
  // log é só-acréscimo: mesmo tamanho = nada mudou; não redesenha (preserva arraste do scrub e scroll).
  // redesenhar (state.json mudou): receita/rótulos dos quadros podem ter mudado mesmo sem evento novo —
  // compara os quadros (progresso de render também mexe no state e não deve piscar a aba)
  if (linhaDados.pid === pid && eventos.length === linhaDados.eventos.length
      && (!redesenhar || JSON.stringify(d.quadros || []) === JSON.stringify(linhaDados.quadros))) return;
  linhaDados = { pid, eventos, quadros: d.quadros || [] };
  desenhaLinha();
}

function desenhaLinha() {
  const box = el('tab-linha');
  const evs = linhaDados.eventos;
  if (!evs.length) { box.innerHTML = '<div class="dim linha-vazio">sem histórico</div>'; return; }
  const vis = visiveis();
  linhaPos = Math.min(linhaPos, Math.max(vis.length - 1, 0));
  const assuntos = [...new Set(evs.filter(e => e.tipo === 'decisao').map(e => e.assunto))].sort();
  const chipsAssunto = linhaFiltro.tipos.has('decisao') && assuntos.length
    ? '<span class="dim">assunto:</span>' + ['', ...assuntos].map(a =>
      `<button class="lib-chip${(linhaFiltro.assunto || '') === a ? ' on' : ''}" data-assunto="${escapeHtml(a)}">${escapeHtml(a || 'todos')}</button>`).join('')
    : '';
  box.innerHTML = `<div class="linha-topo">
      <div class="linha-ctl">
        <button id="linha-play">${linhaTimer ? '⏸' : '▶'}</button>
        <button id="linha-vel" class="mono">${linhaVel}×</button>
        <input type="range" id="linha-scrub" min="0" max="${Math.max(vis.length - 1, 0)}" value="${linhaPos}"${vis.length ? '' : ' disabled'}>
        <span class="mono" id="linha-custo"></span>
      </div>
      <div id="linha-mini" class="linha-mini"></div>
      <div class="linha-filtros">${LINHA_TIPOS.map(t =>
        `<button class="lib-chip${linhaFiltro.tipos.has(t) ? ' on' : ''}" data-tipo="${t}">${LINHA_ICO[t]} ${LINHA_ROT[t]}</button>`).join('')}${chipsAssunto}</div>
    </div>
    <ol class="linha-lista">${vis.map((i, k) => {
      const e = evs[i], t = tipoLinha(e);
      return `<li class="linha-item lt-${t}" data-k="${k}">
          <span class="mono dim" title="${escapeHtml(new Date(e.ts).toLocaleString('pt-BR'))}">${fmtHora(e.ts)}</span>
          <span class="linha-ico">${LINHA_ICO[t]}</span><span>${escapeHtml(textoLinha(e))}</span></li>`;
    }).join('')}</ol>`;
  marcaLinha();
}

function marcaLinha() {
  const vis = visiveis();
  const box = el('tab-linha');
  if (!el('linha-scrub')) return;
  if (!vis.length) { el('linha-custo').textContent = ''; el('linha-mini').innerHTML = ''; return; }
  const i = vis[linhaPos];
  const q = linhaDados.quadros[i] || { etapas: [], atual: null };
  el('linha-scrub').value = linhaPos;
  el('linha-custo').textContent = 'acumulado ' + fmtUSD(linhaDados.eventos[i].custo_acum);
  el('linha-mini').innerHTML = q.etapas.map(e =>
    `<span class="step st-${e.status}${e.id === q.atual ? ' atual' : ''}">${escapeHtml(e.rotulo)}</span>`).join('');
  box.querySelectorAll('.linha-item').forEach(li => li.classList.toggle('cur', +li.dataset.k === linhaPos));
  const cur = box.querySelector('.linha-item.cur');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function tocaLinha() {
  if (!visiveis().length) return;
  if (linhaPos >= visiveis().length - 1) linhaPos = 0;
  linhaTimer = setInterval(() => {
    if (linhaPos >= visiveis().length - 1 || document.body.dataset.tab !== 'linha'
        || document.body.dataset.route !== 'project') { pausaLinha(); return; }
    linhaPos += 1;
    marcaLinha();
  }, 600 / linhaVel);
  if (el('linha-play')) el('linha-play').textContent = '⏸';
  marcaLinha();
}

function pausaLinha() {
  clearInterval(linhaTimer);
  linhaTimer = null;
  if (el('linha-play')) el('linha-play').textContent = '▶';
}

el('tab-linha').addEventListener('click', e => {
  const t = e.target;
  if (t.id === 'linha-play') { if (linhaTimer) pausaLinha(); else tocaLinha(); return; }
  if (t.id === 'linha-vel') {
    linhaVel = linhaVel === 1 ? 2 : 1;
    t.textContent = linhaVel + '×';
    if (linhaTimer) { pausaLinha(); tocaLinha(); }
    return;
  }
  const chip = t.closest('[data-tipo],[data-assunto]');
  if (chip) {
    if (chip.dataset.tipo) {
      const s = linhaFiltro.tipos, k = chip.dataset.tipo;
      if (s.has(k)) s.delete(k); else s.add(k);
    } else {
      linhaFiltro.assunto = chip.dataset.assunto || null;
    }
    linhaPos = 0;
    desenhaLinha();
    return;
  }
  const li = t.closest('.linha-item');
  if (li) { linhaPos = +li.dataset.k; marcaLinha(); }
});

el('tab-linha').addEventListener('input', e => {
  if (e.target.id === 'linha-scrub') { linhaPos = +e.target.value; marcaLinha(); }
});
