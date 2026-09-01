# Formato: Padrão YouTube — Shorts (vertical 9:16)

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
| Saída | `Export/shorts/<lote>/<nome>.mp4` |

## Método

1. **Fonte**: o export horizontal em `Export/<nome> - horizontal.mp4`.
2. **Timings**: `words_out.py` mapeia os tempos de palavra do Scribe para a
   timeline do export — toda borda de corte senta em fronteira de palavra
   (padding 50ms antes / 80ms depois).
3. **EDL por short**: um `edl_NN-<slug>.json` por short; o reframe (crop+scale)
   vai no campo `grade` do EDL — o `render.py` aplica depois do scale dele,
   então roda por segmento na extração.
4. **Estrutura**: hook forte nos primeiros 2s → desenvolvimento → virada/CTA.
   3–5 ranges por short, 30–60s total.
5. **Render**: `render.py <edl> -o <out>` (helpers do video-use).
6. **Legendas**: queimadas ou não conforme o destino; se queimadas, sempre por
   último na cadeia de filtros.

## Convenção de projeto (UI)

Short novo que precisar de edição própria na UI = diretório próprio
`edit/shorts/<slug>/` com `edl.json` — aparece sozinho no seletor de projetos.
Lotes antigos (vários `edl_*.json` num dir só) são trabalho finalizado; ficam
como estão.
