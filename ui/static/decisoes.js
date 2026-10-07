// Página "Decisões" (#/decisoes): decisões do Claude em todos os projetos; filtro por assunto
// (o servidor devolve as escolhas mais frequentes) e busca no cliente.
const decEstado = { assunto: null, busca: '', assuntos: [], dados: { decisoes: [], frequentes: [] }, req: 0 };

async function renderDecisoesPage() {
  const req = ++decEstado.req;   // clique rápido nos chips: só a resposta mais nova desenha
  let assuntos = [], dados = { decisoes: [], frequentes: [] };
  try {
    const todos = await getJSON('/api/decisoes');
    assuntos = [...new Set(todos.decisoes.map(d => d.assunto))].sort();
    dados = decEstado.assunto ? await getJSON('/api/decisoes', { assunto: decEstado.assunto }) : todos;
  } catch (e) {
    console.warn('decisões falhou', e);
  }
  if (req !== decEstado.req || document.body.dataset.route !== 'decisoes') return;
  decEstado.assuntos = assuntos; decEstado.dados = dados;
  desenhaDecisoes();
}

function desenhaDecisoes() {
  const { assunto, busca, dados } = decEstado;
  el('dec-chips').innerHTML = ['', ...decEstado.assuntos].map(a =>
    `<button class="lib-chip${(assunto || '') === a ? ' on' : ''}" data-assunto="${escapeHtml(a)}">${escapeHtml(a || 'todos')}</button>`).join('');
  el('dec-freq').innerHTML = assunto && dados.frequentes.length
    ? `<div class="dec-freq"><span class="dim">escolhas mais frequentes · ${escapeHtml(assunto)}:</span> ${
      dados.frequentes.map(f => `<span class="tag">${escapeHtml(f.escolha)} ×${f.n}</span>`).join(' ')}</div>`
    : '';
  const b = busca.toLowerCase();
  const linhas = dados.decisoes.filter(d =>
    !b || [d.escolha, d.motivo, d.nome, d.projeto].join(' ').toLowerCase().includes(b));
  el('dec-tabela').innerHTML = linhas.length
    ? `<table class="dec-tab"><thead><tr><th>projeto</th><th>data</th><th>etapa</th><th>assunto</th><th>escolha</th>
        <th>alternativas</th><th>motivo</th><th>conf.</th><th>US$</th></tr></thead><tbody>${linhas.map(d => `<tr>
        <td><a href="${hashFor(d.projeto, 'linha')}">${escapeHtml(d.nome)}</a></td>
        <td class="mono">${escapeHtml(new Date(d.ts).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }))}</td>
        <td>${escapeHtml(d.etapa || '')}</td><td>${escapeHtml(d.assunto)}</td><td><b>${escapeHtml(d.escolha)}</b></td>
        <td class="dim">${escapeHtml(d.alternativas.join(', '))}</td><td>${escapeHtml(d.motivo)}</td>
        <td>${d.confianca ? `<span class="conf conf-${escapeHtml(d.confianca)}">●</span> ${escapeHtml(d.confianca)}` : ''}</td>
        <td class="mono">${d.custo_usd != null ? fmtUSD(d.custo_usd) : ''}</td></tr>`).join('')}</tbody></table>`
    : `<div class="dim dec-vazio">${dados.decisoes.length ? 'nada encontrado' : 'nenhuma decisão registrada'}</div>`;
}

el('dec-chips').addEventListener('click', e => {
  const b = e.target.closest('[data-assunto]');
  if (!b) return;
  decEstado.assunto = b.dataset.assunto || null;
  renderDecisoesPage();
});
el('dec-busca').addEventListener('input', e => {
  decEstado.busca = e.target.value.trim();
  desenhaDecisoes();
});
el('btn-decisoes').addEventListener('click', () => { location.hash = '#/decisoes'; });
