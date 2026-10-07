# video_editor — protocolo da UI

UI local: `python ui/server.py` → http://127.0.0.1:8765

## Papel do Claude na sessão

Quando o usuário pedir para "escutar a UI":
1. Tocar `edit/<proj>/ui/heartbeat` (arquivo vazio, re-touch a cada ciclo de
   escuta; UI considera online se mtime < 10s).
2. Monitorar `edit/*/ui/queue.json`, `edit/shorts/*/ui/queue.json` e
   `.ui-runtime/queue.json` (fila global de novo-projeto).
3. Pedido `pending` mais antigo primeiro (FIFO, um por vez).

## Ciclo de um pedido

**Atenção — escrita concorrente:** antes de QUALQUER escrita em `queue.json`,
reler o arquivo do disco e fazer merge por `id` — nunca sobrescrever entradas
que você não conhece (a UI pode ter adicionado um pedido novo enquanto você
processava o anterior). O mesmo cuidado vale para `state.json`: ao escrever
progresso de render, preservar as chaves que não são suas (ex.: `aprovacoes`)
em vez de sobrescrever o objeto inteiro.

1. Marcar `status: "executing"` (reescrever o queue.json atômico).
2. Ler `ui/state.json` → `formato` = receita em `Formatos/<formato>.md`;
   seguir a receita.
3. Tipos:
   - `instrucao` — texto livre; `target` = índice do corte ou null (geral).
   - `veto` — `target` = índice do corte; revisar/remover.
   - `borda` — `target` = `{seg, edge: start|end, delta_ms}`; ajustar range
     no edl.json respeitando limites de palavra (regras do video-use).
   - `render` — `text` = `preview`|`final`; rodar render.py escrevendo
     progresso em `state.json` → `{"render": {"fase", "pct", "eta"}}`.
   - `novo-projeto` — `target` = `{bruto, formato, nome, descricao, fontes}`;
     com bruto: renomear bruto
     (memória "renomear-bruto"), criar dir de edição, iniciar pipeline.
     Sem bruto (formato ads): criar `edit/shorts/<slug>/` com `ui/`, seguir
     `Formatos/padrao-ads.md` usando `descricao` + `fontes` como briefing.
     Em ambos: criar/mesclar `<proj>/ui/state.json` com
     `{"formato": target.formato}` antes da primeira etapa (preservar chaves
     existentes).
   - `roteiro` — `target` = `{tema, duracao_min, publico, nome}`; fila global;
     seguir `padrao-youtube-longo.md` §0.0 (pesquisa → roteiro.md → aprovação).
     `novo-projeto` com o mesmo nome reaproveita `edit/<slug>/` (mantém
     pesquisa.md/roteiro.md).
   - `pauta` — `target` = `{marca, mes}`; fila global; seguir `Formatos/pauta.md`.
   - `referencia` — `target` = `{origem, marca, nome, briefing}`; fila global;
     seguir `Formatos/referencia.md` (baixar → analisar → conceitos A/B/C + animatic → escolha).
4. Pedido grande/ambíguo → `status: "waiting_reply"` + pergunta em
   `resultado`. UI devolve resposta em `reply` e volta status a `pending`.
   TODA pergunta ao usuário passa por aqui — nunca só no chat: o usuário
   acompanha e responde pela UI.
   Aprovação com folha visual (b-roll, clipes, conceitos, overlays): gravar no
   pedido `"folha": "broll" | "clips" | "conceitos" | "overlays"` junto com a
   pergunta — a UI mostra a aba Aprovação e devolve a resposta no formato
   `ok` + exceções: `ok` = tudo como proposto; `ok b03:2 b05:não` = as
   exceções valem e o resto fica aprovado como proposto. Resposta só com
   tokens (sem `ok`) continua válida. Pedido da fila global (ex.: referencia):
   criar o pedido com `folha` na fila do projeto (a folha só abre de lá).
5. Tarefa longa (ex.: novo-projeto): manter `status: "executing"` e ir
   atualizando `resultado` com o status atual em uma frase curta a cada
   etapa concluída ("transcrevendo...", "gerando animações 2/5..."). A UI
   mostra isso ao vivo.
   Além disso, manter `.ui-runtime/activity.json` =
   `{"atual": "<ação de agora>", "anterior": "<ação concluída>", "ts": "<ISO>"}`
   a cada mudança de ação — vira a caixinha "o que o Claude está fazendo"
   na UI (some sozinha se ficar >10min sem update).
6. Pedidos com `status: "cancelado"` (Ctrl+Z na UI): ignorar, nunca executar.
7. Fim: `status: "done"` + nota curta em `resultado`, ou `"failed"` + motivo.

## Etapas (board da UI)

Cada receita declara `etapas:` no front-matter e um mapa `> Etapas` no topo.
Registrar no log do projeto (a UI acende a trilha ao vivo):

- Começou etapa: `python ui/eventos.py etapa <proj> <id> inicio`.
- Concluiu: `python ui/eventos.py etapa <proj> <id> fim --nota "<resumo curto>"`.
- Abriu `waiting_reply` dentro dela: `... <id> espera --nota "<pergunta curta>"` (a nota é a pergunta na linha do tempo).
- Retomou depois da resposta: `... <id> inicio` de novo.
- Etapa opcional que não vai rodar: `... <id> pulada`. Erro: `... <id> falha --nota "<motivo>"`.
- exit 1 (etapa/status inválido, formato sem etapas) → conferir o front-matter
  da receita e o `formato` do `state.json`; nunca inventar id.
- Custo por etapa sai sozinho do `costs.jsonl` (intervalo início→fim).

## Decisões (linha do tempo da UI)

Registrar só escolhas entre alternativas reais que mudam resultado ou custo
(provedor, trilha, candidato de b-roll, x do clipe, grade, conceito, corte
polêmico). Escolha óbvia sem alternativa não entra. Teto ~30 por projeto.

`python ui/eventos.py decisao <proj> <assunto> "<escolha>" --etapa <id> --alt "<alternativa>" ... --motivo "<por quê>" [--custo <usd estimado>] [--confianca alta|media|baixa]`

`assunto` ∈ provedor, trilha, sfx, broll, corte, grade, zoom, overlay,
legenda, conceito, clipe, thumbnail, render, outro (fora da lista → `outro`
e explicar no motivo). `--etapa` precisa estar na receita (ou omitir).
Respostas do usuário entram sozinhas no log (só da fila do projeto; a fila global não entra — o servidor grava no `/api/reply`).

## Orçamento (ações pagas)

Antes de QUALQUER ação que gaste dinheiro ou cota (ElevenLabs, stock pago,
vídeo por IA...):

1. `python ui/budget.py autorizar <proj> <provedor> <unidades>`.
2. exit 2 (`precisa_aprovacao`) ou 3 (`bloqueado`) → pedido `waiting_reply`
   na fila com `resultado` = motivo + estimativa ("gerar 5 clipes Kling ≈
   US$1,40 — aprova?"). Esperar `reply` afirmativo; repetir o passo 1 com
   `--aprovacao <id do pedido>`.
3. Executar.
4. `python ui/budget.py registrar <proj> <provedor> <unidades> [--usd real]
   [--aprovacao <id>]`.

Provedores e preços: `ui/precos.json` (provedor novo = entrada nova antes de
usar). Transcrição Scribe: registrar `elevenlabs_scribe` com minutos do áudio
após `transcribe.py`; na primeira rodada, medir `python ui/budget.py saldo`
antes/depois e anotar `creditos` por minuto em `precos.json`.

## Fontes (pesquisa e roteiro)

Fato citado em roteiro, overlay ou pauta exige `[F#]` em `pesquisa.md` com
fonte `oficial` ou `doutrina` (`ui/fontes.json`). Blog, vídeo, rede social =
inspiração de ângulo, nunca fato. `python ui/pesquisa.py validar` antes de
pedir aprovação; `snapshot` guarda as páginas em `fontes/`. Busca =
WebSearch/WebFetch da sessão (sem custo, sem orçamento).

Footage/foto de terceiros (b-roll) só via `python ui/stock.py` — licença e
crédito ficam em `broll.json`/`creditos.md`; nunca baixar à mão. Sem custo,
sem orçamento. Fluxo: `padrao-youtube-longo.md` §5.1.

Shorts: `Formatos/padrao-youtube-shorts.md` (Clip Factory, `ui/clips.py`). Publora
só como **draft** (`create_post` + upload + `complete_media`); nunca agendar sem
pedido explícito — Starter limita 3 agendados / 7 dias.

Vídeo de referência (Reel/Short) = inspiração de mecanismo, nunca cópia; URL e autor ficam em conceitos.md. Download só via ui/referencia.py (yt-dlp ou arquivo em bruto/ref/).

## Regras

- Confirmação de estratégia do video-use continua valendo (via waiting_reply).
- UI nunca edita edl.json; toda mutação passa por aqui.
- Progresso de render: atualizar `state.json` por segmento concluído.
