# video_editor

Editor de vídeo dirigido por conversa com Claude Code, construído sobre o skill
[video-use](https://github.com/browser-use/video-use) (vendored em `video-use/`,
fora do repo).

- `Formatos/` — receitas de edição aprovadas (YouTube, Reels, thumbnail)
- `docs/superpowers/specs/` — specs de design
- `ui/` — painel web local tipo Premiere: preview, timeline do EDL, fila de
  instruções pro Claude (ver spec em `docs/`)

Mídia (vídeos brutos, trilhas, exports, sessões de edição) fica fora do Git —
ver `.gitignore`.
