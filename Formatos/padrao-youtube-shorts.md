---
etapas: transcricao=transcrição, candidatos, aprovacao=aprovação, render, draft=draft Publora
---
# Formato: Padrão YouTube — Shorts (vertical 9:16)

> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> transcricao = Método 1 · candidatos = Método 2–4 · aprovacao = Método 5 (`espera` no waiting_reply) ·
> render = Método 6 · draft = Método 7–8.
> Rodando dentro de projeto longo: logar só a etapa `shorts` no projeto longo — `inicio` no começo,
> `espera` nas aprovações, `inicio` ao retomar, `fim` no fim, com `--nota` por subpasso; as etapas
> acima valem só para projeto com formato próprio.

Shorts são cortes derivados do **export horizontal pronto** — nunca do bruto.
O horizontal já está cortado, gradeado e com punch-ins, então um short custa um
re-encode, não uma re-edição. Receita provada em `edit/shorts/build_shorts.py`
(SaaS) e `edit-the-goat/shorts/` (THE GOAT).

## Entrega

| | |
|---|---|
| Vídeo | 1080×1920 @ 60 fps, H.264, `yuv420p`, `+faststart` |
| Reframe | `crop=608:1080:{x}:0,scale=1080:1920:flags=lanczos` (janela 608×1080 do frame 1920×1080) |
| x do crop | escolher por short; `x=636` centraliza o talking head e derruba a coluna de overlays da edição horizontal |
| Áudio | herdado do export (já está −14 LUFS) |
| Saída | `Export/shorts/<proj>/<NN-slug>-<plat>.mp4` |

## Método (Clip Factory — `ui/clips.py`)

1. Palavras na timeline do export:
   `python ui/clips.py words-out edit/<proj>/edl.json edit/<proj>/transcripts/<fonte>.json edit/<proj>/real_durations.json edit/<proj>/clips/words_out.json`
   (transcrição já existe; nada pago).
2. Candidatos por heurística (gancho, fechamento, densidade, autonomia):
   `python ui/clips.py candidatos edit/<proj>/clips/words_out.json edit/<proj>/clips/candidatos.json --n 20`.
3. **Curadoria (Claude):** ler `candidatos.json` + transcript; escolher `meta_n` + 2
   (meta ≈ 1 short a cada 8 min do longo; 5–8 em 40–60 min). Para cada clipe:
   `nota` 1–5, `gancho` (primeira frase, ≤ 2 s), `slug`, `ranges` com `beat`
   (cold open permitido: um range do fim antes do início), `x` (par; 636 centraliza
   o talking head e derruba a coluna de overlays), `legenda`, `plataformas`
   (`shorts` ≤ 60 s, `reels` ≤ 90 s, `tiktok` ≤ 60 s com legenda). Escrever
   `edit/<proj>/clips/clips.json` com `status: proposto`. Regras: hook nos 2 s;
   uma ideia por clipe; termina em virada ou CTA; nunca dois clipes do mesmo trecho.
4. `python ui/clips.py validar edit/<proj>/clips/clips.json edit/<proj>/clips/words_out.json` → corrigir até `ok`.
5. `python ui/clips.py edl edit/<proj>/clips/clips.json edit/<proj> "Export/<nome> - horizontal.mp4"`
   → `waiting_reply` com `folha: "clips"`: "clipes: N propostos — aprove na aba Aprovação
   (ou Docs › clips.md)". Resposta `ok` + exceções, ex. `ok c03:não c05:nota 3 c07:x=700 c02:sem-legenda`
   (também `cNN:legenda`). Aplicar a resposta
   (`status`, `nota`, `x`, `legenda`), re-`validar`, re-`edl`. `ok` = todos os
   `proposto` viram `aprovado`; `cNN:não` = `vetado`; os demais campos (`nota`,
   `x`, `legenda`) só mudam onde indicado.
6. `python ui/clips.py render edit/<proj>/clips/clips.json edit/<proj> Export/shorts/<proj> --preview`
   → `waiting_reply` "previews em Export/shorts/<proj>/ — `ok` ou ajustes" → `render` final (sem `--preview`).
7. **Publora (Claude via MCP):** conta da marca (memória `publora-postagem`); para cada
   `.mp4` final (subir SÓ os arquivos listados em `renderizados` do `render`
   final, nunca listar a pasta): `create_post` como draft (legenda = gancho + 1 frase + hashtags do
   padrão; sem travessão), `get_upload_url` → `PUT` → `complete_media`. Nunca
   `scheduled` (Starter: 3 agendados / 7 dias).
8. `state.json.clips = {"propostos", "aprovados", "renderizados", "publora_drafts": [ids]}` (merge).

Instrução pontual ("faz um short do trecho dos 12 anos") = um clipe em `clips.json`
sem passar por `candidatos`; passos 4–8.

## Convenção de projeto

Os clipes vivem em `edit/<proj>/clips/<NN-slug>-<plat>/` (1 dir por EDL — o
`render.py` usa o dir do EDL como cache de segmentos). Lotes antigos
(`edit/shorts/edl_*.json`, `build_shorts.py`, `words_out.py`) são trabalho
finalizado; ficam como estão. Short que precisar de edição própria na UI =
`edit/shorts/<slug>/` com `edl.json`, como antes.
