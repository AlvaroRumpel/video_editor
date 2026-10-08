# Kit de motion (HyperFrames) — design (subprojeto 9)

Data: 2026-10-08. Origem: item "Motion design via HyperFrames" do fora de
escopo do subprojeto 8 (`2026-10-08-video-ia-design.md`). Depende de:
`audio.py` (`mix-sfx`, `cues.json`), `eventos.py` (etapas, decisões),
`localiza.py` (dublagem de textos na tela), receitas `padrao-ads.md` e
`edit/shorts/campeio/BRAND.md`.

## Objetivo

Reels/ads todo animados com o refinamento do HyperFrames, a custo de token
menor que o motion escrito à mão hoje. O Claude **monta** vídeos a partir de
peças prontas e de um `cenas.json`, em vez de **escrever** animação do zero a
cada vídeo.

## Spike que motivou (2026-10-08, descartável)

Mesmo brief nos três motores, dois rounds (overlay alpha 4 s; reel 5 s
1080x1920 com lettering, íris, grão):

| | Remotion | capture.js | HyperFrames |
|---|---|---|---|
| Tokens do agente (R1 / R2) | 84k / 103k | 86k / 108k | 113k / 145k |
| Render R2 | 38 s | 38 s | 39 s |
| Qualidade visual (avaliação do usuário) | 2º | 3º | **1º** |

O custo extra do HyperFrames veio de partir do zero: ler catálogo, adaptar
demo 16:9, cair em armadilha (troca silenciosa de fonte, GSAP via CDN,
`init` instalando skills). O kit paga esse custo uma vez.

## Decisões do usuário

- Motor dos reels/ads: **HyperFrames** (qualidade visual vencedora).
- Escopo v1: **reels/ads 9:16**. Remotion segue nos overlays do longo; ads
  antigos ficam no `capture.js` como estão.
- Marcas: **qualquer marca** — componentes iguais, tema por marca. Nasce com
  Anotus e Campeio.
- Uso: **híbrido** — `cenas.json` com tipos do kit no dia a dia; cena
  `custom` (HTML à mão com componentes) quando o roteiro pedir algo fora do
  catálogo; custom repetido em ≥ 2 vídeos vira tipo novo no kit.

## Estrutura

```
motion/                         versionado (node_modules ignorado)
  package.json                  hyperframes 0.8.141 travado (versão do spike)
  kit/
    vendor/gsap.min.js          sem CDN: render roda offline
    fonts/                      Fraunces, Inter, Archivo, IBM Plex Mono (.ttf locais + OFL.txt)
    kit.css                     @font-face com famílias próprias ("K Fraunces"…), reset, safe area
    componentes.js              letras, palavras, mascara, marcaTexto, risco, contador,
                                grao, manchas, kenBurns, assinatura, fixos, cue
    transicoes/                 fade (padrão), iris (shader SDF), wipe
  temas/
    anotus.json
    campeio.json  campeio/icone.png
  cenas/                        templates por tipo: frase, numero, lista, tela, endcard
  amostras/cenas.json           todos os tipos, nas duas marcas (golden test)
ui/motion.py                    CLI: montar | render | folha
```

- Famílias de fonte com **nome próprio** (`K Fraunces`, `K Inter`…): o
  HyperFrames remapeia nomes conhecidos em silêncio (spike R1: Consolas →
  JetBrains Mono, Segoe UI → Roboto).
- `.gitignore`: acrescentar `motion/node_modules/`.
- Blocos do catálogo HyperFrames que deram certo no spike (`grain-overlay`,
  `bottom-up-letters`, `inline-highlight`, `sdf-iris`) são a base de
  `componentes.js`/`transicoes/`, adaptados a 9:16 e ao tema. Apache 2.0:
  crédito no cabeçalho do arquivo. O catálogo **não** entra no fluxo por
  vídeo (`hyperframes add` fica para quem evolui o kit).
- GSAP vendorizado na versão que o template do hyperframes 0.8.141 usa
  (licença padrão do GSAP permite uso comercial).

## `cenas.json`

Fica em `edit/shorts/<marca>/<tema>/cenas.json`, escrito pelo Claude a partir
do `roteiro.md` aprovado.

```json
{
  "marca": "anotus",
  "aspecto": "9:16",
  "cenas": [
    { "id": "c01", "tipo": "frase", "fundo": "claro",
      "linhas": [
        { "t": "Pare de", "estilo": "punch", "anim": "palavras" },
        { "t": "decorar.", "estilo": "serif", "anim": "letras",
          "destaque": ["marca-texto", "risco"] }
      ],
      "saida": { "transicao": "iris", "dur": 0.47 } },
    { "id": "c02", "tipo": "frase", "fundo": "marca",
      "linhas": [
        { "t": "Comece a", "estilo": "punch", "anim": "palavras" },
        { "t": "entender", "estilo": "serif", "anim": "mascara",
          "cor": "acento", "destaque": ["assinatura"] }
      ] },
    { "id": "c03", "tipo": "endcard", "cta": "Teste grátis" }
  ]
}
```

### Campos

- Raiz: `marca` (nome de `motion/temas/<marca>.json`), `aspecto` (só
  `"9:16"` na v1 → 1080x1920 @ 30 fps), `cenas` (lista ordenada).
- Toda cena: `id` (`cNN`, único), `tipo`, `fundo` ∈ `claro|escuro|marca`
  (default do tema por tipo), `dur` opcional (s), `fixos` (default `true`),
  `saida` opcional `{transicao: fade|iris|wipe, dur}` (default = transição
  padrão do tema).
- `frase`: `linhas[]` com `t` (texto), `estilo` ∈ `serif|punch|corpo|mono`,
  `anim` ∈ `palavras|letras|mascara|fade`, `cor` ∈ `tinta|acento|destaque`
  (default por estilo/fundo), `destaque[]` ⊂ `marca-texto|risco|assinatura`,
  `em` opcional (s desde o início da cena).
- `numero`: `valor` (número), `formato` (`"pt-BR"` default), `prefixo`/
  `sufixo`, `legenda`, `de` (default 0).
- `lista`: `titulo` opcional, `itens[]` (texto), `marcador` ∈
  `numero|assinatura|check`.
- `tela`: `arquivo` (png/jpg/mp4 relativo ao projeto), `moldura` ∈
  `celular|browser|nenhuma`, `label` (pill), `kenburns` (default `true` para
  imagem).
- `endcard`: `cta` (default do tema), `tagline`/`url` (default do tema).
- `custom`: `html` (caminho relativo ao projeto), `dur` (obrigatório).

### Regras de tempo

Tempo é automático, com as regras que já existem nas duas marcas: um
elemento novo por vez; segurar estado final ≥ 0,8 s; end card ≥ 1,2 s;
easings nunca lineares (out-cubic reveals, in-out-cubic draws, out-back
pops). `dur`/`em` só quando precisa casar com fala/trilha; `dur` menor que o
mínimo calculado é erro de validação.

### Tema (`motion/temas/<marca>.json`)

Traduz papéis em valores; o mesmo `cenas.json` roda em qualquer marca
trocando `marca`.

```json
{
  "cores": { "tinta": "#2B215C", "acento": "#D4A017", "destaque": "rgba(255,214,90,.55)",
             "fundo": { "claro": "#F3F2FA", "escuro": "#2B215C", "marca": "#4A3D8F" },
             "texto_sobre": { "escuro": "#FFFFFF", "marca": "#FFFFFF" } },
  "fontes": { "serif": ["K Fraunces", 700, "italic"], "punch": ["K Inter", 800],
              "corpo": ["K Inter", 500], "mono": ["K Inter", 500] },
  "assinatura": { "tipo": "ponto", "cor": "#D4A017" },
  "fixos": { "wordmark": "Anotus.", "pill": true, "barra": false, "grao": 0.12 },
  "endcard": { "tagline": "Seu segundo cérebro jurídico", "cta": "Teste grátis / link na bio" },
  "transicao_padrao": { "tipo": "fade", "dur": 0.3 },
  "regras": { "numero_mono": false }
}
```

Campeio: `fundo.marca` = gradiente hero do `BRAND.md`, `assinatura` =
`{"tipo": "icone", "arquivo": "campeio/icone.png"}`, `barra: true`,
`numero_mono: true` (IBM Plex Mono), Archivo 800–900 nos títulos. Valores
saem de `padrao-ads.md` e `BRAND.md` (fonte da verdade continua lá; o tema é
a tradução para o kit).

### Custom

`{"id": "c04", "tipo": "custom", "html": "cenas/c04.html", "dur": 3}`. O
arquivo é um fragmento HTML com um `<script>` que exporta
`montar(tl, el, tema, kit)`: `tl` = timeline GSAP da cena, `el` = container,
`tema` = tema resolvido (também como variáveis CSS `--k-tinta`, `--k-acento`…),
`kit` = componentes. Eventos de som via `kit.cue("tick")`. Custom que aparece
em ≥ 2 vídeos vira tipo em `motion/cenas/` (decisão registrada).

## Módulo `ui/motion.py`

### `montar <proj> [--cenas cenas.<lang>.json]`

1. Valida schema (tipos, enums, ids únicos, `destaque` coerente, arquivos de
   `tela`/`custom` existentes, tema existente).
2. Gera `<proj>/motion/` (pasta gerada, sobrescrita a cada `montar`): uma
   subcomposição HyperFrames por cena (`cenas/cNN.html`, a partir do template
   do tipo + tema) e a raiz `index.html` encadeando-as. `motion/kit/` e o
   asset do tema são copiados para `<proj>/motion/kit/` (o HyperFrames só
   serve arquivos de dentro da pasta da composição).
3. Abre cada cena no Chromium (Playwright Python, já usado em
   `referencia.py`/`localiza.py`) e lê `window.__kit`: duração calculada,
   eventos de som, medidas de texto no estado final.
4. Validação de layout: texto fora da safe area (1080x1920: x 80..1000,
   y 180..1660), linha estourando a largura, fonte em fallback
   (`document.fonts.check` + família computada ≠ família do tema) → erro com
   `id` da cena.
5. Escreve `data-start` de cada cena na raiz (somando durações e
   sobreposição de transição) e `<proj>/cues.json` no formato do
   `audio.py mix-sfx` (`[{"t", "som", "ganho_db"}]`).

Saída JSON: `{"ok", "duracao", "cenas": [{"id", "dur"}], "erros": [{"id", "motivo"}]}`.
Exit 1 com `erros` não vazio; nada renderiza.

Mapa de som padrão: assinatura → `pop-dourado`; `letras`/`mascara` →
`whoosh-reveal`; pill → `click-pill`; endcard → `sting-endcard`; contador →
`tick`; entrada por subida → `rise` (nomes da biblioteca `assets/sfx/`).

### `render <proj> [--rascunho] [--lang xx]`

- Exige `montar` atual (raiz mais nova que `cenas.json` e que o tema; senão
  roda `montar` antes).
- `npx hyperframes render` a partir de `motion/` (binário do `motion/node_modules`,
  nunca versão solta) → `<proj>/video.mp4` (mudo, encode padrão dos ads:
  1080x1920 @ 30, H.264 yuv420p `-crf 18`, range tv). `--rascunho` →
  540x960, `video_rascunho.mp4`. `--lang xx` → `video.<xx>.mp4` a partir de
  `cenas.<xx>.json`.
- Progresso em `state.json` → `{"render": {"fase", "pct", "eta"}}` lendo a
  saída do HyperFrames (merge preservando chaves alheias, como o resto da UI).
- Depois: `ffprobe` confere dimensão, fps, frames = duração × 30, `yuv420p`
  range tv; falha vira erro.

### `folha <proj>`

Contact sheet `qc/folha.png`: para cada cena, frame do meio da entrada e do
estado final, mais o meio de cada transição (a partir de `video.mp4`). Vira o
passo 1 do QC do `padrao-ads.md`.

## Receitas e protocolo

- `padrao-ads.md` › "Técnica de produção" › Motion: troca o bloco
  `anim.html`/`capture.js` por: `cenas.json` (do roteiro aprovado) →
  `motion.py montar` → `render --rascunho` → `folha` → ajustar →
  `render` → `audio.py mix-sfx video.mp4 cues.json …` (SFX e trilha como
  hoje). O bloco antigo vira "Ads legados (capture.js)" curto, só para
  manutenção dos existentes.
- `BRAND.md` (Campeio) › Técnica: aponta para `motion/temas/campeio.json` e
  para o `padrao-ads.md`.
- Cenas por IA e footage do app: entram como cena `tela` (`arquivo` mp4,
  `moldura`), em vez do concat por ffmpeg.
- Dublagem (`dublagem.md` passo 11, ads novos): `localiza.py extrair` e
  `aplicar` aceitam `cenas.json` (campos de texto: `t`, `itens[]`, `titulo`,
  `legenda`, `label`, `cta`, `tagline`) → `cenas.<lang>.json`;
  `motion.py montar --cenas cenas.<lang>.json` substitui o `checar` (estouro
  vira erro de validação); `render --lang <lang>`. Custom HTML segue pelo
  caminho atual de `.html` do `localiza.py`.
- `eventos.py`: assunto novo `motion` (transição fora do padrão, custom no
  lugar de tipo, promoção de custom a tipo).
- `CLAUDE.md`: regra curta — motion de reel/ad só via `ui/motion.py`;
  custom repetido vira tipo no kit.
- Etapa continua `producao`; sem custo, sem orçamento.

## Erros

- `motion/node_modules` ausente → erro "rodar `npm ci` em `motion/`"; não
  instala sozinho.
- Tema inexistente, tipo desconhecido, campo inválido → erro de `montar` com
  `id` da cena.
- Layout/fonte (safe area, estouro, fallback) → erro de `montar`; nunca aviso.
- `dur` abaixo do mínimo calculado → erro com o mínimo na mensagem.
- Render falhou → exit ≠ 0 com as últimas 20 linhas do stderr; na UI, etapa
  `producao` `falha --nota "<motivo>"`.
- `ffprobe` fora do esperado → erro com o valor encontrado.
- Lint do HyperFrames: só erros contam; avisos de subcomposição ignorados
  (ruído visto no spike).

## Testes

`ui/test_motion.py` (pytest, sem render):
- schema: válido passa; tipo desconhecido, `destaque` inválido, id
  duplicado, custom sem `dur` falham com `id` certo;
- tema: o mesmo `cenas.json` resolve cores/fontes diferentes em `anotus` e
  `campeio`; papel ausente no tema é erro;
- `montar` gera uma subcomposição por cena e `data-start` somando durações
  com sobreposição de transição;
- `cues.json` sai com os eventos esperados de uma cena `frase` com
  `assinatura` (usa Chromium; pula se Playwright ausente);
- layout: linha longa de propósito vira erro de estouro; fonte inexistente
  vira erro de fallback.

`ui/test_motion_golden.py` (lento, marcado; pula sem Node/`motion/node_modules`):
renderiza `motion/amostras/cenas.json` nas duas marcas e compara frames-chave
com PNGs de referência por PSNR ≥ 35 dB. Atualizar referências só de
propósito (`--atualizar`). Upgrade do hyperframes só com esse teste passando.

## Critério de sucesso (piloto)

- Próximo reel do Anotus da `PAUTA.md` sai pelo kit sem cena custom.
- Tokens da etapa de motion < baseline do capture.js no spike (~108k para
  5 s), medido na sessão do piloto.
- Visual aprovado pelo usuário no preview.
- O mesmo `cenas.json` com `"marca": "campeio"` renderiza sem erro.

## Fora de escopo

- Aspectos 16:9 e 4:5 (o tema e o validador já usam papéis/safe area por
  aspecto; acrescentar quando houver pedido).
- Overlays do vídeo longo (Remotion continua; reavaliar após o piloto).
- Migrar ads antigos do `capture.js`.
- Mixer de áudio do HyperFrames (áudio segue no `audio.py`).
- Folha de aprovação nova na UI (aprovação continua pelo preview + QC).
- Catálogo HyperFrames (`add`) no fluxo por vídeo.
- Render na nuvem (Lambda do HyperFrames).
