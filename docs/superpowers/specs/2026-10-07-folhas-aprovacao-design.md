# Folhas de aprovação pré-render — design (subprojeto 6b)

Data: 2026-10-07. Série "portar ideias do OpenMontage" (reescrita própria,
nada copiado — AGPL). Depende de: 6a (SPA com abas, board, fila com
rascunhos, `sendReply`), `ui/stock.py` (`broll.json`), `ui/clips.py`
(`clips/clips.json`), `ui/referencia.py` (conceitos + animatic), `edl.json`
(overlays).

## Objetivo

Trocar as aprovações por código digitado ("b03:2 b05:não", "c03:não",
"A") por folhas visuais clicáveis que mostram o material de verdade (vídeo
candidato, recorte vertical do clipe, animatic, frame do overlay) e geram a
mesma resposta de texto que o Claude já sabe aplicar.

## Decisões do usuário

- Folhas: **b-roll, clipes, conceitos A/B/C, overlays**.
- Fluxo: **a folha monta a resposta** e envia no `waiting_reply` aberto
  (`/api/reply`). A UI continua sem escrever artefato do pipeline.
- Lugar: **aba "Aprovação ❓"**, visível só quando há folha aberta.

## Protocolo

- Pedido da fila ganha campo opcional `folha` ∈
  `broll | clips | conceitos | overlays`. O Claude o grava ao abrir o
  `waiting_reply` de uma aprovação (junto com `resultado` = pergunta).
  Sem `folha`, nada muda.
- Sintaxe de resposta unificada: **`ok` + exceções**. `ok` sozinho = tudo
  aprovado como proposto; `ok b02:2 b05:não` = exceções valem, o resto
  aprovado como proposto. Receitas passam a dizer isso explicitamente.
  Respostas antigas (só tokens, sem `ok`) continuam válidas como hoje.
- Responder digitando na fila continua funcionando.

## Artefatos lidos

| folha | arquivo | campos usados |
|---|---|---|
| `broll` | `broll.json` | `momentos[]`: `id`, `t_in`, `t_out`, `termo`, `modo`, `status`, `escolhido?`; `candidatos[]`: `fonte`, `id`, `tipo` (`video`/`foto`), `arq` (relativo ao projeto), `dur`, `licenca`, `autor` |
| `clips` | `clips/clips.json` | `x_padrao?`; `clipes[]`: `id`, `slug`, `status`, `nota`, `gancho`, `ranges[]` (`t_in`, `t_out`, timeline do export = `final.mp4`), `x?`, `legenda?`, `plataformas[]` |
| `conceitos` | `conceitos.json` (**novo**) | `conceitos[]`: `id` (`A`/`B`/`C`), `ideia`, `mantem`, `muda`, `custo` (texto), `horas`, `exige_ia` (bool), `animatic` (`animatic-X.png`) |
| `overlays` | `overlays/folha.json` (**novo**, gerado por helper) | `overlays[]`: `id` (`o01`…), `arquivo`, `t` (início na saída), `dur`, `png` (`overlays/oNN.png`) |

`conceitos.json` é escrito pelo Claude junto com `conceitos.md` (passo 4 de
`Formatos/referencia.md`).

## Módulo `ui/folha.py`

Padrão `ui/*.py`: stdlib; `sys.path.insert` antes de `import pipeline`;
subprocess em lista com `_run` injetável e `timeout`; CLI JSON UTF-8 no
stdout, exit 0 / 1 (`ValueError`) / 2.

- `TIPOS = ("broll", "clips", "conceitos", "overlays")`.
- `ler(proj: Path, tipo: str) -> dict` — normaliza o artefato do tipo:
  - `broll` → `{"momentos": [{"id","t_in","t_out","termo","modo","status","escolhido","candidatos":[{"rotulo": "bNN-k","fonte","tipo","arq","dur","licenca","autor"}]}]}`
    (só momentos `status == "proposto"`; `escolhido` default = primeiro rótulo).
  - `clips` → `{"x_padrao", "clipes": [{"id","slug","nota","gancho","ranges":[{"t_in","t_out"}],"x","legenda","plataformas","dur"}]}`
    (só `status == "proposto"`; `x` = `x` ou `x_padrao` ou 636; `dur` = soma dos ranges).
  - `conceitos` → `{"conceitos": [...]}` com os campos da tabela, `animatic`
    só se o arquivo existir (senão `null`).
  - `overlays` → conteúdo de `overlays/folha.json`, `png` só se existir.
  - Tipo inválido, arquivo ausente, JSON inválido ou campo obrigatório
    faltando → `ValueError` com motivo curto. Campos obrigatórios: `id` em
    cada item; `candidatos` (lista) no b-roll; `ranges` no clipe.
- `overlays(proj: Path, _run=None) -> dict` — para cada item de
  `edl.json["overlays"]` (com `file`, `start_in_output`, `duration`):
  frame no meio do overlay (`t = start + dur/2`) composto sobre o
  `final.mp4` (ou `preview.mp4`) no mesmo tempo; sem vídeo base, sobre
  fundo preto 1920x1080. Saída `overlays/oNN.png` (640 de largura) +
  `overlays/folha.json`. `edl.json` sem overlays → folha com lista vazia.
  Overlay cujo arquivo falta → item com `png: null` e `erro`.
- CLI: `python ui/folha.py overlays <proj>` e `python ui/folha.py ler <proj> <tipo>`.

## Servidor

- `GET /api/folha?id=&tipo=` → `folha.ler(...)`; tipo inválido → 400;
  `ValueError` → 422 com o motivo.
- `/api/file` passa a aceitar também
  `^broll/cand/[\w\-.]+\.(mp4|webm|jpg|jpeg|png)$` e `^overlays/o\d{2,3}\.png$`,
  com contenção (`is_relative_to`) como hoje e media type pelo sufixo
  (`video/mp4`, `video/webm`, `image/jpeg`, `image/png`). `FileResponse`
  atende `Range` (vídeo no hover).

## Frontend

### Aba e ciclo

- `TABS` ganha `aprovacao`. A aba só aparece (e só é navegável) quando o
  projeto tem pedido `waiting_reply` com `folha`; vale o mais antigo.
  Sem pedido, `#/p/<id>/aprovacao` cai para `board`.
- Selo ❓ na aba. Card da etapa em `espera` no Board: se o pedido tem
  `folha`, mostra link "abrir folha" no lugar da caixa de resposta.
- Cabeçalho da aba: pergunta (`resultado`) + tipo.
- Rodapé: **resposta gerada** (mono, só leitura) + campo opcional de
  comentário (anexado em nova linha) + Enviar → `sendReply(qid, texto,
  'proj')`. Depois do envio o pedido vira `pending`, a aba some, rota vai
  para `board`.
- Seleção começa no padrão do artefato; fica em memória por `pid:qid`
  (sobrevive a troca de aba e a redesenho por SSE); descartada ao enviar,
  restaurada se o envio falhar.
- `folha.js` expõe `resposta(tipo, folha, sel) -> string` (função pura).

### B-roll

Linha por momento: `id`, tempo de saída `m:ss`, termo, modo; candidatos
lado a lado 16:9 — vídeo = `<video muted preload="metadata">` com
`src=/api/file?...arq` que toca no hover; foto = `<img>`; legenda
fonte · duração · licença. Clique escolhe (contorno âmbar); botão "vetar"
por linha (alterna). Resposta: exceções em ordem de id — `bNN:k` quando
escolhido ≠ 1º, `bNN:não` quando vetado; nenhuma → `ok`; senão
`ok ` + tokens.

### Clipes

Card por clipe: caixa 9:16 com `<video>` do `final.mp4` (fallback
`preview.mp4`) tocando os `ranges` em sequência (play/pausa no clique);
recorte simulado por CSS a partir de `x` (crop real = `608x1080` em `x` de
um quadro 1920x1080 → vídeo escalado para a altura da caixa e deslocado
`-x * escala`). Gancho, duração, plataformas; nota 1–5 clicável; slider
`x` (0–1312, passo 2) com valor; alternar legenda; aprovar/vetar.
Resposta: `ok` + exceções na ordem dos ids: `cNN:não`, `cNN:nota N`,
`cNN:x=N`, `cNN:legenda` / `cNN:sem-legenda` (só o que mudou em relação ao
proposto).

### Conceitos

Três colunas: animatic (clique amplia em overlay simples), ideia, mantém,
muda, custo, horas, selo "exige IA". Rádio para escolher um; alternância
"produzir vários" troca rádio por checkboxes; campo "ajuste". Resposta:
`ajuste: <texto>` se o campo ajuste tiver texto; senão `produzir: A B` com
2+ marcados; senão a letra escolhida. Nada escolhido → Enviar desabilitado.

### Overlays

Grade de frames (16:9) com tempo `m:ss`, nome do arquivo, `dur`. Por
overlay: "vetar" (alterna) ou "pedir mudança" (campo de texto).
Resposta: `ok` + exceções: `oNN:não`, `oNN: <texto>`.

### Erros

- `/api/folha` 422/404 → aba mostra "folha indisponível — responda pela
  fila" + a pergunta + motivo.
- Mídia ausente → tile com placeholder (sem quebrar a linha).
- Envio falhou → seleção e comentário preservados (mesmo padrão do board).

## Receitas e CLAUDE.md

- `CLAUDE.md`, ciclo do pedido / item 4: "aprovação com folha visual:
  gravar `folha` no pedido (`broll|clips|conceitos|overlays`); resposta
  vem como `ok` + exceções".
- `padrao-youtube-longo.md` §5.1 passo 5: `waiting_reply` com
  `folha: broll`; texto da resposta "`ok` ou `ok b03:2 b05:não`".
  Novo passo de overlays (etapa `visual`, antes do render final):
  `python ui/folha.py overlays edit/<proj>` → `waiting_reply` com
  `folha: overlays`; `oNN:não` = remover overlay do `edl.json`;
  `oNN: <texto>` = refazer conforme instrução.
- `padrao-youtube-shorts.md` passo 5: `folha: clips`; sintaxe `ok` + tokens.
- `referencia.md` passo 4: escrever também `conceitos.json` (campos da
  tabela acima); passo 6: `folha: conceitos`.

## Testes

- `ui/test_folha.py`: `ler` para cada tipo (válido; arquivo ausente; JSON
  inválido; campo obrigatório faltando; filtra não-propostos; defaults de
  `escolhido`/`x`/`dur`); `overlays` com `_run` falso (com vídeo base,
  sem vídeo base, edl sem overlays, overlay com arquivo ausente); CLI exit
  codes.
- `ui/test_server.py`: `/api/folha` (ok, tipo inválido 400, artefato
  ausente 422), `/api/file` para `broll/cand/*.mp4` e `overlays/oNN.png`
  (ok, media type, traversal 400).
- `ui/test_ui_smoke.py`: por tipo, fixture com pedido `waiting_reply` +
  `folha`: abre a aba, clica, confere a resposta gerada, envia e verifica
  `reply` + `pending` no `queue.json`; aba ausente sem folha; link "abrir
  folha" no card em espera.

## Fora do escopo (6b)

Custo real por item (stock é grátis; vídeo por IA = subprojeto 8);
aprovar sem pergunta aberta; UI escrevendo artefato; decisões + replay
(6c).
