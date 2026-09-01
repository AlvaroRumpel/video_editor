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
4. Pedido grande/ambíguo → `status: "waiting_reply"` + pergunta em
   `resultado`. UI devolve resposta em `reply` e volta status a `pending`.
   TODA pergunta ao usuário passa por aqui — nunca só no chat: o usuário
   acompanha e responde pela UI.
5. Tarefa longa (ex.: novo-projeto): manter `status: "executing"` e ir
   atualizando `resultado` com o status atual em uma frase curta a cada
   etapa concluída ("transcrevendo...", "gerando animações 2/5..."). A UI
   mostra isso ao vivo.
6. Pedidos com `status: "cancelado"` (Ctrl+Z na UI): ignorar, nunca executar.
7. Fim: `status: "done"` + nota curta em `resultado`, ou `"failed"` + motivo.

## Regras

- Confirmação de estratégia do video-use continua valendo (via waiting_reply).
- UI nunca edita edl.json; toda mutação passa por aqui.
- Progresso de render: atualizar `state.json` por segmento concluído.
