# Video Editor UI — Design

Data: 2026-09-01
Status: aprovado em conversa (híbrido, abordagem A, layout/dados/fila/render aprovados por seção)

## Objetivo

Painel web local tipo Premiere para visualizar e controlar o pipeline de edição
de vídeo dirigido pelo Claude Code (skill video-use). Modelo **híbrido**: a UI
observa os artefatos do pipeline e envia pedidos para uma fila; o Claude da
sessão do terminal escuta a fila e executa. A UI nunca edita EDL/vídeo
diretamente.

## Arquitetura

- **Servidor**: `ui/server.py` — FastAPI + uvicorn, porta 8765.
  - Serve `static/` (página única, JS puro, sem build step).
  - Serve vídeos (`preview.mp4`, `final.mp4`) com HTTP range requests.
  - Lê artefatos do pipeline; escreve apenas `ui/queue.json`, `ui/state.json`
    e `Formatos/*.md` (editor de receitas).
  - Observa arquivos (polling ~1s) e empurra mudanças via **SSE**.
- **Frontend**: `ui/static/index.html` (+ `app.js`, `style.css`) — tema escuro.
- **Claude (esta sessão)**: monitor de arquivo sobre `queue.json` dos projetos;
  executa pedidos FIFO, um por vez; atualiza status; toca
  `ui/heartbeat` enquanto escuta.

## Descoberta de projetos

Servidor escaneia `video_editor/` por diretórios contendo `edl.json`
(inclui `edit/shorts/*`). Dropdown no topo troca o projeto ativo.
Projeto sem `edl.json` aparece como "não iniciado" (permite apenas
"Novo vídeo" / instrução geral).

## Layout

```
topo:    [Projeto ▾] [Formato ▾] [Novo vídeo] [Formatos] [Render Preview] [Render Final] [barra de progresso]
centro:  PLAYER (esq) | LISTA DE CORTES com 👍👎 + INSTRUÇÃO contextual + status da fila (dir)
rodapé:  TIMELINE com zoom/pan: V (segmentos EDL), A (waveform), T (transcrição), FX (zooms/overlays/legendas)
```

Comportamentos:

- Clique em segmento (timeline ou lista) → seleciona; instrução ganha contexto
  "sobre corte #N". Sem seleção = instrução geral.
- Arrastar borda de segmento → gera pedido `borda` ("estica/encolhe X em ±ms")
  na fila; segmento marcado como "pendente". Não edita `edl.json`.
- 👎 → pedido `veto` ("revisar/remover corte #N"). 👍 → marca aprovado em
  `state.json` (verde), sem pedido.
- **Eixos de tempo**: a timeline usa o tempo do vídeo BRUTO (segmentos usados +
  gaps do que foi cortado); o player toca `preview.mp4` (tempo de saída).
  Playhead sincronizado bidirecionalmente via mapeamento do EDL
  (saída ↔ fonte); clique num gap (trecho cortado) posiciona o player no
  fim do segmento anterior. Waveform e transcrição alinhadas ao tempo do bruto.
- Painel de fila: cada pedido com status pendente → executando → pronto/falhou,
  ao vivo. Pedido em "aguardando resposta" mostra a pergunta do Claude e campo
  de resposta.
- Aviso "Claude offline" quando heartbeat velho (> ~10s).

## Formatos

- Dropdown de formato do projeto (arquivos de `Formatos/*.md`); escolha salva
  em `state.json` e enviada como contexto em todo pedido.
- Aba "Formatos": viewer (markdown renderizado) + editor (salvar de volta).
- "Novo vídeo": escolhe arquivo de `bruto/` + formato → pedido `novo-projeto`
  na fila (Claude inicia a edição, renomeando o bruto conforme memória).

## Dados

Somente leitura pela UI: `edl.json`, `takes_packed.md`, `transcripts/*.json`,
`zooms.json`, `master.srt`, `preview.mp4`/`final.mp4`, `bruto/*`.

Novos, por projeto, em `edit/<proj>/ui/`:

- `queue.json` — lista de pedidos:
  `{id, ts, type: instrução|render|borda|veto|novo-projeto, target, text, status: pending|executing|waiting_reply|done|failed, resultado}`.
  UI escreve `pending` e respostas; Claude escreve o resto.
- `state.json` — `{formato, aprovações: [ids], render: {fase, pct, eta}}`.
- `heartbeat` — tocado pelo Claude enquanto escuta.
- `cache/` — waveform (ffmpeg → picos JSON, gerado na primeira abertura).

Sem filmstrip no v1 (waveform + transcrição localizam trecho; adicionar se
fizer falta).

## Fluxo de um pedido

1. UI escreve `pending` em `queue.json`.
2. Claude (monitor de arquivo) acorda, marca `executing`, executa com a receita
   do formato como contexto.
3. Pedido grande → Claude responde `waiting_reply` com pergunta (regra de
   confirmação de estratégia do video-use continua valendo); UI mostra campo de
   resposta.
4. Fim → `done` + nota curta, ou `failed` + motivo. UI recarrega
   EDL/preview via SSE.

FIFO estrito, um pedido por vez (EDL não suporta edição concorrente).
Sessão fechada → pedidos acumulam como `pending`.

## Render

Botões enfileiram pedido `render` (preview|final). Claude roda `render.py`
escrevendo progresso em `state.json` (fase extract/concat/overlays/subtitles,
% por segmentos, ETA por média móvel). Barra no topo. Final aprovado pelo
usuário ("está pronto") → exportar para `Export/` conforme memória.

## Erros

- Pedido falhou → `failed` + motivo legível; fila segue.
- Sem `preview.mp4` → player mostra "sem preview — peça um render".
- Sem `edl.json` → projeto "não iniciado".

## Teste

- `ui/test_server.py` — sobe servidor contra projeto fake em tmp; valida
  endpoints (EDL, waveform, escrita/leitura de queue, SSE).
- Verificação visual da UI via Playwright (screenshots + interações) antes de
  apresentar.

## Fora de escopo (v1)

- Edição direta de EDL pela UI (tudo passa pelo Claude).
- Filmstrip/thumbnails na timeline.
- Chat completo embutido (Agent SDK) — modelo é fila híbrida.
- Multi-usuário/rede; servidor é localhost.
