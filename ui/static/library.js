// Biblioteca (#/): grade de projetos, filtros, poll de 5s enquanto visível.
S.lib = { items: [], formato: null, soEsperando: false, busca: '', key: null };
let libTimer = null;

const SIGLA = { 'padrao-youtube-longo': 'YT', 'padrao-youtube-shorts': 'SH', 'padrao-ads': 'AD',
  pauta: 'PA', referencia: 'RF', thumbnail: 'TH' };
const sigla = f => SIGLA[f] || (f || '?').slice(0, 2).toUpperCase();

function startLibrary() {
  S.lib.key = null;   // força redesenho ao voltar
  loadLibrary();
  if (!libTimer) libTimer = setInterval(loadLibrary, 5000);
  getJSON('/api/budget').then(b => { S.budget = b; if (!S.proj) renderBudget(); }).catch(() => {});
}

function stopLibrary() {
  clearInterval(libTimer);
  libTimer = null;
}

async function loadLibrary() {
  try {
    const [items, gq, act] = await Promise.all([
      getJSON('/api/library'), getJSON('/api/global-queue'), getJSON('/api/activity')]);
    if (document.body.dataset.route !== 'library') return;
    S.lib.items = items; S.globalQueue = gq; S.activity = act;
    renderLibrary();
    renderQueue();
  } catch (e) {
    console.warn('biblioteca falhou', e);
  }
}

function libCard(p) {
  const href = '#/p/' + encodeURIComponent(p.id);
  const v = encodeURIComponent(p.atividade || '');
  const capa = `/api/capa?id=${encodeURIComponent(p.id)}&v=${v}`;
  const dots = p.etapas.map(e =>
    `<i class="st-${e.status}" title="${escapeHtml(e.rotulo)} · ${STATUS_LABEL[e.status] || e.status}"></i>`).join('');
  const atual = p.atual ? `${escapeHtml(p.atual.rotulo)} · ${STATUS_LABEL[p.atual.status] || p.atual.status}`
    : !p.etapas.length ? 'sem etapas' : p.sem_historico ? 'sem histórico' : 'parado';
  return `<a class="lib-card" href="${href}">
      <div class="lib-capa"><span class="lib-sigla">${sigla(p.formato)}</span>
        <img src="${capa}" alt="" loading="lazy" onerror="this.remove()"></div>
      <div class="lib-info">
        <div class="lib-nome">${escapeHtml(p.name)}</div>
        <div class="lib-meta"><span class="tag">${escapeHtml(p.formato || 'sem formato')}</span>
          ${p.pendencias ? `<span class="tag espera">❓ ${p.pendencias}</span>` : ''}
          <span class="spacer"></span><span class="mono dim">${fmtUSD(p.custo_usd)}</span></div>
        <div class="lib-dots">${dots}</div>
        <div class="lib-atual dim">${atual}</div>
      </div>
    </a>`;
}

function renderLibrary() {
  const L = S.lib;
  const online = L.items.some(p => p.claude_online);
  el('claude-status').className = online ? 'online' : 'offline';
  el('claude-status').textContent = online ? 'Claude escutando' : 'Claude offline';
  const formatos = [...new Set(L.items.map(p => p.formato).filter(Boolean))].sort();
  const busca = L.busca.toLowerCase();
  const vis = L.items.filter(p => (!L.formato || p.formato === L.formato)
    && (!L.soEsperando || p.pendencias > 0)
    && (!busca || p.name.toLowerCase().includes(busca)));
  const key = JSON.stringify([formatos, L.formato, L.soEsperando, vis]);
  if (key === L.key) return;   // nada mudou: não redesenha (sem piscar capa)
  L.key = key;
  el('lib-chips').innerHTML =
    `<button class="lib-chip${!L.formato ? ' on' : ''}" data-formato="">todos</button>` +
    formatos.map(f => `<button class="lib-chip${L.formato === f ? ' on' : ''}" data-formato="${escapeHtml(f)}">${escapeHtml(f)}</button>`).join('') +
    `<button class="lib-chip espera${L.soEsperando ? ' on' : ''}" data-esperando="1">❓ esperando você</button>`;
  el('lib-grid').innerHTML = vis.length ? vis.map(libCard).join('')
    : '<div class="lib-vazio dim">nenhum projeto</div>';
}

el('lib-chips').addEventListener('click', e => {
  const b = e.target.closest('.lib-chip');
  if (!b) return;
  if (b.dataset.esperando) S.lib.soEsperando = !S.lib.soEsperando;
  else S.lib.formato = b.dataset.formato || null;
  renderLibrary();
});

el('lib-busca').addEventListener('input', e => {
  S.lib.busca = e.target.value.trim();
  renderLibrary();
});
