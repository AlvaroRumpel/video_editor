# Padrão Ads (identidade aprovada 2026-08-31; origem: Reels Anotus)

Receita dos 4 vídeos de `Export/shorts/anotus/`. Todo Reel novo do Anotus segue isto.

## Identidade visual

**Paleta**
| Papel | Cor |
|---|---|
| Fundo | `#F3F2FA` (lavanda clara) |
| Tinta / headlines | `#2B215C` |
| Roxo primário (pills CTA, números) | `#4A3D8F` |
| Lilás apoio | `#B9B3E6` |
| Dourado (o "ponto" da marca) | `#D4A017` |
| Alerta | `#C0392B` · Sucesso `#2E7D4F` · Marca-texto `rgba(255,214,90,.55)` |

**Tipografia**
- Display/serif: **Fraunces** (Google Fonts, 600/700 + itálico; fallback Georgia). Headlines em caixa mista.
- Punch/labels: **Inter** (500/700/900; fallback Segoe UI). Palavras de impacto em Inter 900 CAIXA ALTA.
- Cards brutos em PIL: Segoe UI Bold (`segoeuib.ttf`) p/ labels, `georgiaz.ttf` p/ wordmark.

**Motivos recorrentes (usar sempre)**
1. **Ponto dourado animado** — entra com easeOutBack como ponto final de frases-chave; no end card voa ao centro e vira o ponto do logo.
2. **Wordmark "Anotus."** — Fraunces itálico ~26px CSS + ponto dourado, rodapé centro (y≈920 CSS), 55% opacidade, em toda cena exceto end card.
3. **End card padrão** (mesma coreografia sempre): ponto voa ao centro e quica → "Anotus" (Fraunces itálico 700 ~110px CSS) revela da esquerda pra direita atrás do ponto → ponto assenta após o "s" → tagline "Seu segundo cérebro jurídico" (Inter 500 `#5A5878`) → pill roxa com CTA branco → linha Inter 900. Reutilizável pronto: `edit/shorts/anotus/features/motion/cta.mp4` (4.6s, CTA "Teste grátis / link na bio").
4. **Pill de label** — branca, borda lilás, radius total, ponto dourado + texto Segoe Bold roxo; topo centro (y=52px @1080).
5. **Moldura de celular (bezel)** p/ footage do app: furo arredondado 44px em (100,178,980,1742) @1080x1920, borda branca 8px, pill de label no topo, wordmark embaixo. Gerador: `edit/shorts/anotus/features/build_bezels.py` e `r8v2/build_pills.py`.

**Regras de motion**
- Nunca linear: easeOutCubic (reveals), easeInOutCubic (draws), easeOutBack (pops).
- Um elemento novo por vez. Segurar estado final de cena ≥0.8s. End card ≥1.2s.
- Transição consistente por vídeo (crossfade 0.3s pelo fundo lavanda).
- Safe areas (CSS 540x960): texto em x 40..500, nada importante acima de y=90 ou abaixo de y=830.

**Copy**: PT-BR, sem travessão (regra do repo), gancho direto nos 2 primeiros segundos, CTA sempre alinhado à estratégia (`justmind/divulgacao/INSTAGRAM.md`): produto no máx. 1 a cada 4 posts; CTA de salvar nos de método.

## Técnica de produção

**Motion graphics** (100% determinístico, sem GSAP/Remotion):
1. `anim.html` com stage 540x960 CSS; `window.seek(frame)` posiciona tudo como função pura do frame (30fps); sem CSS animation/transition; `window.READY=true` após `document.fonts.ready` (timeout 5s).
2. Captura: Playwright chromium headless, `viewport 540x960, deviceScaleFactor: 2` → screenshot por frame = 1080x1920 nítido. Exemplos: `edit/shorts/anotus/r8v2/capture.js`, `features/motion/`, `cronograma/`, `reler/`.
3. Montagem: `ffmpeg -framerate 30 -i frames/f_%04d.png` + encode padrão.

**Footage do app** (dash.anotus.app):
- Login de automação: Turnstile bloqueia senha; usar **magic link** via admin API (`edit/shorts/anotus-r8/magic_link.js`, lê `justmind/.env`) e salvar `state.json` (sessão reutilizável).
- Flutter = canvas: cliques por coordenada (mapear com screenshots antes). Upload via evento `filechooser` normal.
- Gravar com `recordVideo` 1080x1920: o Playwright NÃO escala — página fica 540x960 no canto. Corrigir com `crop=540:960:0:0,scale=1080:1920:flags=lanczos` (full-frame) ou `scale=880:1564` + `pad` (dentro do bezel).
- Conta de teste `teste@jusmind.app`; conteúdo sempre fictício/lei pública (regra de sigilo). Takes prontos em `edit/shorts/anotus-r8/take1..4.mp4` (fluxo completo, nota+busca, referências, flashcards+revisão+exportar).

**Encode padrão** (tudo igual → concat `-c copy`):
`-r 30 -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -profile:v high -an`, 1080x1920.

**Áudio**: música de `assets/music/`, `loudnorm=I=-15:TP=-1.5:LRA=11`, fade out 1.2s no fim, aac 192k, `+faststart`. Trilha diferente por vídeo (usadas: Phoenix2026=01, Incredulity=02, Unraveling=03, bed-unraveling=04).

**Duração alvo**: 27-35s.

## QC antes de entregar
1. Contact sheet + frames nas bordas de cena (atenção: `fps=0.5` em vídeo de concat amostra torto o início; conferir cenas iniciais com `-ss` direto).
2. Checar: legibilidade, safe areas, fontes carregadas (Fraunces serif de verdade, não fallback genérico), ponto dourado presente, wordmark, end card padrão.
3. `ffprobe`: duração esperada, 1080x1920@30, faixa de áudio presente.

## Entrega
- Preview em `edit/shorts/anotus/<tema>/preview.mp4`; só copiar pra `Export/shorts/anotus/NN-<tema-kebab>.mp4` após aprovação.
- Registrar sessão em `edit/project.md`.
