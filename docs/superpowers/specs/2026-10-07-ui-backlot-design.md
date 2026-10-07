# UI estilo Backlot — design (subprojeto 6a)

Data: 2026-10-07. Sétimo subprojeto da série "portar ideias do OpenMontage"
(reescrita própria, nada copiado — AGPL). Inspiração: Backlot (biblioteca de
projetos + board ao vivo de etapas). Depende de: `ui/server.py`, `ui/static/*`,
`budget.py` (`costs.jsonl`, `gasto_projeto`), filas e `state.json` atuais.

## Objetivo

Trocar a UI de "editor de um projeto" por um estúdio: tela inicial com todos
os projetos (biblioteca) e, dentro de cada projeto, uma trilha de etapas da
receita que acende ao vivo, com o que espera o usuário e quanto custou cada
etapa. O editor atual (player + timeline + cortes) vira uma aba, sem perder
nada.

## Decisões do usuário

- Série 6 dividida: **6a** biblioteca + board + log de eventos (este doc);
  **6b** aprovação pré-render (contact sheet por cena); **6c** decisões +
  replay. 6b/6c têm spec própria.
- Etapas: **receita declara + Claude loga** (sem inferir do disco). Projeto
  sem log = stepper cinza "sem histórico".
- Layout **A**: biblioteca em grade de cards → projeto com stepper no topo e
  abas Board | Edição | Docs | Custos. Fila + atividade sempre à esquerda.
- Estilo **Estúdio escuro** (preto profundo, âmbar, Inter + JetBrains Mono).

## Navegação

SPA no mesmo `index.html`, rotas por hash:

- `#/` — biblioteca.
- `#/p/<id>/<aba>` — projeto; `aba` ∈ `board|edicao|docs|custos`.
  `#/p/<id>` sem aba = última aba usada nesse projeto (`localStorage`,
  try/catch) ou `board`.
- `<id>` = id atual de `find_projects` (caminho relativo a `edit/`),
  codificado com `encodeURIComponent`.
- Link antigo sem hash → biblioteca.

JS dividido em scripts clássicos sem build, compartilhando globais (mesmo
padrão do `app.js` atual; converter 960 linhas para módulos ES não compra
nada): `app.js` (roteador + shell + editor existente), `library.js`,
`board.js`. Bootstrap no `DOMContentLoaded` (depois dos três scripts).

## Dados

### Etapas declaradas na receita

Cada `Formatos/*.md` ganha front-matter nas primeiras linhas:

```
---
etapas: roteiro?, transcricao=transcrição, cortes, fatos, visual, audio=áudio, legenda, render, entrega
---
```

- Separador `,`; espaços em volta ignorados.
- `id` = `[a-z0-9-]+` (ASCII, é o que o CLI recebe). `=Rótulo` opcional
  (exibição); sem rótulo, exibe o `id`.
- Sufixo `?` no id = etapa opcional (exibição igual; só documenta).
- Sem front-matter ou sem chave `etapas` → formato "sem etapas".
- `/api/formats` devolve o texto cru (com front-matter): o editor de
  Formatos salva o `content` inteiro via `PUT`, então esconder o
  front-matter o apagaria no próximo salvar.
- Logo abaixo do título, cada receita ganha um bloco `> Etapas:` mapeando
  cada id para as seções da receita (ex.: `cortes = §2`), para o Claude
  saber quando logar.

Listas iniciais:

| formato | etapas |
|---|---|
| padrao-youtube-longo | `roteiro?, transcricao=transcrição, cortes, fatos, visual, audio=áudio, legenda, render, entrega` |
| padrao-youtube-shorts | `transcricao=transcrição, candidatos, aprovacao=aprovação, render, draft=draft Publora` |
| padrao-ads | `referencia?=referência, pesquisa, roteiro, producao=produção, audio=áudio, render, qc=QC` |
| pauta | `pesquisa, pauta, aprovacao=aprovação` |
| thumbnail | `frame, recorte, composicao=composição, variacoes=variações` |

`visual` (longo) agrupa grade, punch-in, motion e b-roll; `audio` agrupa
limpeza e trilha.

Projetos de referência têm `formato: padrao-ads` desde o passo 0 de
`referencia.md`, então o fluxo referência é a etapa opcional `referencia` do
ads (`inicio` no passo 0, notas por subpasso, `fim` na escolha) — sem lista
própria. `pauta.md` e `padrao-youtube-longo.md` §0.0 passam a criar
`ui/state.json` com `formato` (`pauta` / `padrao-youtube-longo`) junto com
`ui/`, para o log validar.

### Log de eventos

`<proj>/ui/eventos.jsonl`, só acréscimo, uma linha por evento:

```json
{"ts": "2026-10-07T17:20:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "inicio", "nota": "23 cortes"}
```

- `ts` = `datetime.now(timezone.utc).isoformat()` (mesmo formato de
  `costs.jsonl`); comparações sempre como `datetime` aware, nunca string.
  UI exibe em hora local.
- `tipo` = `"etapa"` no 6a; o campo fica aberto (6c adiciona `"decisao"`).
- `status` ∈ `inicio | fim | espera | pulada | falha`.
- `nota` opcional, frase curta.
- Escrita: um único `write` de `json.dumps(...) + "\n"` em modo append
  (UTF-8). Nunca reescrever o arquivo.

### Módulo `ui/eventos.py`

Padrão dos módulos `ui/*.py` (stdlib, CLI com JSON UTF-8 no stdout, exit 0 ok
/ 1 validação / 2 execução, `sys.path.insert` antes de `import pipeline`).

- `etapas_de(formato, root) -> list[dict]` — lê front-matter de
  `Formatos/<formato>.md`; cada item `{"id", "rotulo", "opcional"}`; `[]` se
  sem etapas ou arquivo inexistente.
- `registrar(proj, etapa, status, nota=None, root=None) -> dict` — valida
  projeto (dir existe), `status`, e `etapa` contra as etapas do formato do
  `state.json`; inválido → `ValueError`. Formato sem etapas → `ValueError`.
  Faz o append e devolve o evento.
- `ler(proj) -> list[dict]` — linhas válidas em ordem; linha corrompida
  (JSON inválido ou sem `etapa`/`status`) é ignorada.
- `quadro(proj, root=None) -> dict` — derivado:
  ```
  {"formato", "sem_historico": bool,
   "etapas": [{"id","rotulo","opcional","status","inicio","fim","nota","custo_usd"}],
   "fora_da_receita": [ ...mesmo shape... ],
   "atual": "<id>|null"}
  ```
  - `status` da etapa = status do último evento dela; sem evento =
    `"pendente"`; último evento `inicio` → `"andamento"`.
  - `inicio` = ts do último `inicio`; `fim` = ts do `fim` posterior a esse
    `inicio` (ou null). `nota` = última nota não vazia da etapa.
  - `atual` = etapa com `inicio` sem `fim` posterior de ts mais recente;
    se nenhuma, a última com `espera`; senão null.
  - `custo_usd` = soma de `usd` das linhas de `costs.jsonl` com `ts` dentro de
    `[inicio, fim]` (ou `[inicio, agora]` se em andamento). Gasto fora de
    qualquer intervalo não entra em etapa (continua no total do projeto).
  - Etapas no log que não existem na receita → `fora_da_receita`.
  - `sem_historico` = nenhum evento válido.
- CLI: `python ui/eventos.py etapa <proj> <etapa> <status> [--nota "..."]` e
  `python ui/eventos.py quadro <proj>`.

## Servidor

- `GET /api/library` — para cada projeto de `find_projects`:
  `{id, name, formato, started, has_preview, has_final, etapas: [{id, rotulo, status}],
  atual: {id, rotulo, status}|null, sem_historico: bool, pendencias: int,
  fila: [pedidos pending|executing|waiting_reply], custo_usd: float,
  claude_online: bool, atividade: ISO|null}`.
  - `pendencias` = pedidos `waiting_reply` em `<proj>/ui/queue.json`.
  - `custo_usd` = `budget.gasto_projeto(proj)` total.
  - `atividade` = maior mtime entre `ui/*`, `edl.json`, `preview.mp4`,
    `final.mp4`. Lista ordenada por `atividade` desc.
  - Erro ao ler um projeto não derruba a lista: o projeto entra com campos
    mínimos (`id`, `name`) e `etapas: []`.
- `GET /api/quadro?id=` — `eventos.quadro(proj)`.
- `GET /api/capa?id=` — primeira fonte existente:
  1. `thumbnail*.png` no dir do projeto (ordem alfabética);
  2. frame de `final.mp4` (ou `preview.mp4`) em 10% da duração (ffprobe +
     ffmpeg, args em lista), cache `ui/capa.jpg`, refeito se o vídeo tiver
     mtime maior que o cache;
  3. `animatic-A.png` ou `ref/sheet.png`;
  4. nenhuma → 404 (cliente mostra placeholder com sigla do formato).
  Falha de ffmpeg → segue para as fontes seguintes. Caminho resolvido sempre
  contido no dir do projeto (`is_relative_to`).
- SSE por projeto passa a observar também `ui/eventos.jsonl`.
- `load_project` ganha `has_edl` (aba Edição).

## Frontend

### Shell

- Header: na biblioteca, título + "+ Novo vídeo" + selo de orçamento; no
  projeto, `←` + nome + tag de formato + custo total (mono) + barra de render
  existente.
- Lateral esquerda fixa: fila + atividade (existentes) e, abaixo, a caixa de
  instrução (movida do side-pane da edição). Contexto da instrução: "instrução
  geral" ou "corte N" quando há corte selecionado na Edição. Na biblioteca a
  fila mostra a fila global + pedidos ativos de todos os projetos (prefixo
  `[nome]`, resposta vai para o projeto certo); a caixa de instrução some.
  Status "Claude escutando" na biblioteca = algum projeto com heartbeat.

### Biblioteca (`library.js`)

- Grade responsiva de cards (mín. 240px). Card: capa 16:9 (`object-fit:
  cover`; 404 → placeholder com sigla), nome, tag de formato, linha de pontos
  por etapa (cor do status), texto "<rótulo> · <status>" da etapa atual, selo
  âmbar "❓ N" se `pendencias > 0`, custo em mono.
- Filtros: chips por formato (dos projetos presentes), chip "esperando você",
  busca por nome (cliente).
- Refaz `GET /api/library` a cada 5s enquanto a rota `#/` está ativa.
- Clique no card → `#/p/<id>`.

### Projeto (`board.js` + editor existente)

- Stepper horizontal com as etapas: ok verde, andamento âmbar com brilho,
  espera contorno âmbar + ❓, falha vermelho, pulada riscada, pendente cinza.
  Clique → aba Board, rola até o card. `sem_historico` → stepper cinza +
  etiqueta "sem histórico". Formato sem etapas → "sem etapas".
- **Board**: um card por etapa na ordem da receita; rola até `atual` ao abrir.
  Card: rótulo, status, início/fim e duração (mono), nota, custo. Etapa em
  `espera`: o pedido `waiting_reply` mais antigo do projeto aparece no card com
  campo de resposta (reusa `sendReply`). As linhas de info atuais entram no
  card da etapa: áudio → `audio`, b-roll → `visual`, clips → `candidatos`,
  ref → `referencia` (no formato sem essa etapa, ficam num card "outros" no
  fim). `fora_da_receita` aparece no fim com etiqueta.
- **Edição**: editor atual intacto; rodapé da timeline (220px) só nesta aba.
  Aba desabilitada se o projeto não tem `edl.json`.
- **Docs**: conteúdo do modal Docs atual, renderizado na aba.
- **Custos**: conteúdo do modal de orçamento filtrado ao projeto + tabela
  custo por etapa (de `quadro`).
- Atualização: SSE do projeto → recarrega `quadro` e a aba visível.

### Estilo

`style.css`: tokens em `:root` — `--bg #0e0e10`, `--panel #151518`,
`--border #232328`, `--text #e8e6e3`, `--text-dim #77757d`, `--accent
#f0b24a`, `--ok #5fd38a`, `--pending #f0b24a`, `--fail #e05252`; fontes Inter
(texto) e JetBrains Mono (tempos, valores) via Google Fonts `<link>`. Cantos
6–8px. Editor herda os tokens (só cor muda).

## Protocolo do Claude

`CLAUDE.md` ganha seção "Etapas":

- Ao começar etapa da receita: `python ui/eventos.py etapa <proj> <id> inicio`.
- Ao concluir: `... fim --nota "<resumo curto>"`.
- Ao abrir `waiting_reply` dentro de uma etapa: `... espera`.
- Etapa opcional que não vai rodar: `... pulada`. Erro: `... falha --nota "<motivo>"`.
- exit 1 do CLI (etapa inválida) → conferir front-matter da receita; nunca
  inventar id.

## Erros

| situação | comportamento |
|---|---|
| linha corrompida em `eventos.jsonl` | ignorada; demais valem |
| `state.json` sem formato / formato sem etapas | "sem etapas"; Board vazio; outras abas normais |
| etapa no log fora da receita | card "fora da receita" no fim |
| ffmpeg falha na capa | próxima fonte / placeholder |
| projeto ilegível na biblioteca | card mínimo, lista não quebra |
| `registrar` com etapa/status inválido | `ValueError` / exit 1, nada escrito |

## Testes

- `tests/test_eventos.py`: parse de front-matter (rótulo, `?`, ausente),
  `registrar` válido/inválido (nada escrito no inválido), `ler` com linha
  corrompida, `quadro` (pendente, andamento, fim, espera → atual, pulada,
  falha, fora da receita, sem histórico, reinício após fim), atribuição de
  custo por intervalo (dentro, fora, em andamento), CLI exit codes.
- `tests/test_server_*.py`: `/api/library` (com log, sem log, sem formato,
  projeto ilegível, ordem por atividade, pendências), `/api/quadro`,
  `/api/capa` em cada fallback (ffmpeg mockado) e contenção de caminho.
- Smoke Playwright (`tests/test_ui_smoke.py`, pula se chromium indisponível):
  sobe servidor com root temporário, abre `#/`, clica card, vê stepper, troca
  para Edição e vê o player.

## Fora do escopo (6a)

Aprovação pré-render (6b); decisões + replay (6c); SSE global; inferir estado
de projetos antigos pelo disco; drag-and-drop/kanban.
