---
name: edit-video
description: Sobe a UI do video_editor (servidor + navegador) e deixa o Claude escutando a fila de pedidos. Use quando o usuário rodar /edit-video ou pedir pra "abrir o editor" / "escutar a UI".
---

# /edit-video — subir a UI e escutar a fila

Passos, nesta ordem:

1. **Servidor** — verificar se a porta 8765 já responde
   (`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/api/projects`).
   Se não responder, subir em background: `python ui/server.py`
   (cwd = raiz do video_editor). Aguardar ~2s e conferir que responde.
2. **Navegador** — abrir `http://127.0.0.1:8765` no navegador padrão
   (PowerShell: `Start-Process "http://127.0.0.1:8765"`).
3. **Escuta** — OBRIGATORIAMENTE via ferramenta **Monitor** (persistent: true)
   rodando `python ui/listener.py`. NUNCA via Bash em background: Bash só
   notifica quando o processo TERMINA (nunca, no caso do listener) — a sessão
   ficaria surda pra fila, exatamente o bug que já aconteceu. O Monitor
   notifica a CADA linha: o listener toca os heartbeats (UI mostra "Claude
   escutando") e imprime `PENDING ...` por pedido novo OU resposta nova do
   usuário (reply de um waiting_reply) — cada linha acorda a sessão na hora.
4. Avisar o usuário: UI aberta, escutando.

## Ao receber um pedido (linha PENDING do monitor)

Executar conforme o `CLAUDE.md` da raiz do projeto (protocolo da fila):
FIFO, marcar `executing` → executar seguindo a receita do formato em
`state.json`/`Formatos/` → `done`/`failed` com `resultado` legível.
Pedido grande ou ambíguo → `waiting_reply` com a pergunta em `resultado` —
TODA pergunta ao usuário vai pela fila, nunca só no chat. Em tarefa longa,
manter `executing` e atualizar `resultado` com o status atual a cada etapa
("transcrevendo...", "gerando animações 2/5...") — a UI mostra ao vivo.
A cada mudança de ação, escrever `.ui-runtime/activity.json`:
`{"atual": "...", "anterior": "...", "ts": "<ISO UTC>"}` (caixinha de
atividade na UI).
Pedidos `cancelado` nunca são executados. Ao editar `queue.json`/`state.json`,
sempre reler antes e mesclar por `id` / preservar chaves alheias.

`novo-projeto` sem `bruto` (formato ads): criar `edit/shorts/<slug>/` com
`ui/`, seguir `Formatos/padrao-ads.md`, usando `descricao` e `fontes` do
pedido como briefing.
