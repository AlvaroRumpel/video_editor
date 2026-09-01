# Formato: Padrão YouTube (horizontal)

Método completo da edição de talking head para YouTube. Derivado do vídeo
"Eu criei um SaaS" (2026-08-16). Serve como receita reproduzível: seguindo este
documento, uma nova sessão chega no mesmo resultado sem redescobrir nada.

Ferramentas: `video-use/helpers/*` (ffmpeg + ElevenLabs Scribe), Remotion para
motion graphics, Edge headless para captura de site.

---

## 0. Entrega

| | |
|---|---|
| Container | MP4, H.264 High, `yuv420p`, `+faststart` |
| Vídeo | 1920×1080 @ **60 fps** (igual à fonte; nunca deixar cair pra 24) |
| Qualidade | segmentos CRF 20 `preset fast` · composite CRF 18 |
| Áudio | AAC 192 kbps 48 kHz estéreo, **−14 LUFS / −1 dBTP / LRA 11** |
| Legenda | `master.srt` separado, não queimada |
| Export | `Export/<nome do vídeo> - horizontal.mp4` (+ `.srt` de mesmo nome) |

---

## 0.1 Estrutura de pastas e nome do arquivo

```
bruto/      arquivo original da gravação
edit/       tudo que a sessão produz (transcript, EDL, clipes, animações, final.mp4)
assets/     imagens que o usuário fornece
Formatos/   estas receitas
Export/     entregas finais
```

**Primeira ação de toda edição: renomear o bruto para o nome do vídeo.**
`bruto/2026-08-16 01-26-31.mkv` → `bruto/Eu criei um SaaS.mkv`. Assim bruto, transcrição
e export compartilham o mesmo nome e o material continua rastreável meses depois.

O nome sai do conteúdo, então na prática a ordem é: transcrever → ler → renomear. Ao
renomear **depois** de transcrever, renomear junto:

1. `edit/transcripts/<antigo>.json` → `<novo>.json` — o cache é indexado pelo nome do
   arquivo; sem isso a próxima chamada re-transcreve do zero (custa API e muda os
   timestamps, invalidando o EDL inteiro)
2. `sources.MAIN` no `edit/edl.json` — o JSON escapa as barras, então editar por
   substituição de texto falha; carregar com `json` e reescrever
3. Os caminhos hardcoded nos scripts de `edit/*.py`

**Com o bruto em subpasta, passar `--edit-dir` sempre:**
```
python video-use/helpers/transcribe.py "bruto/<nome>.mkv" --edit-dir "edit"
```
O helper resolve `edit/` relativo ao vídeo. Sem a flag, ele cria `bruto/edit/` e
re-transcreve, ignorando o cache que já existe.

---

## 0.2 Medir a sincronia do bruto ANTES de cortar

A gravação pode chegar com o áudio atrasado em relação à imagem (no vídeo do THE GOAT
foram **~1000 ms**, constante do início ao fim). Isso envenena tudo em silêncio: o
transcript vive no tempo do **áudio**, o corte é planejado nesse tempo, e o vídeo acaba
extraído nos mesmos números — então a imagem fica adiantada em relação à palavra e o
resultado "parece errado" sem dar pra dizer se está adiantado ou atrasado.

Medição (`edit/check_source_av.py`): movimento da região da boca (diferença entre frames
num crop do rosto, a 60 Hz) × envelope de onsets da fala, correlação cruzada em várias
janelas de 150 s. Rodar em 6-9 pontos e tirar a mediana; se as janelas concordarem, o
atraso é constante e vale um deslocamento fixo. Confirmar com o dono do vídeo por
amostras: mesmo trecho renderizado com o vídeo adiantado em 0,8 / 1,0 / 1,2 s.

Correção: o EDL continua no tempo do áudio (transcript), e a **extração do vídeo** puxa
`SRC_AV_DELAY` segundos para trás (`extract_par.py`). Legenda, overlays e trilha não
mudam — só a imagem se desloca. O ar da cabeça fica limitado a `primeira palavra − delay`,
senão o primeiro segmento pede imagem antes do início do arquivo.

## 1. Pipeline (ordem obrigatória)

```
transcribe.py            → transcripts/<fonte>.json     (word-level, cacheado)
pack_transcripts.py      → takes_packed.md              (leitura por frase)
candidates.py            → candidates.txt               (fillers/gaguejos/repetições)
plan_cuts.py             → edl.json + cuts_debug.json   (cortes)
verify_text.py           → verify_text.txt              (revisar texto ANTES de renderizar)
rezoom.py                → clips_zoom/ + base.mp4       (extração com punch-in + grade)
measure_drift.py         → real_durations.json          (deriva de frame)
build_srt.py             → master.srt                   (timeline real)
Remotion render_some.ps1 → animations/remotion/out/*.mov (overlays com alpha)
build_outro.py           → outro.mp4 + base_final.mp4   (end card concatenado)
finalize_edl.py          → edl.json com grade+overlays
recomposite.py           → final.mp4                    (overlays + loudnorm)
```

**Regras que quebram silenciosamente se ignoradas:**

1. Extração **por segmento** → concat `-c copy`. Nunca filtergraph em passada única (re-encoda duas vezes).
2. Fade de áudio de 30 ms nas duas bordas de cada segmento (`afade`). Sem isso, estalo em todo corte.
3. Legenda é o **último** filtro do grafo, depois de todo overlay.
4. Overlay usa `setpts=PTS-STARTPTS+T/TB`, senão aparece o meio da animação.
5. Nunca cortar dentro de palavra. Toda borda cai em fronteira de palavra do Scribe.
6. Transcrição sempre word-level verbatim. Nunca SRT/frase (perde os gaps sub-segundo).
7. Transcrição é cacheada. Só re-transcrever se o arquivo fonte mudar.
8. **Deriva de frame** (§6) — recalcular sempre que o EDL mudar.

---

## 2. Corte de fala

Nível "equilibrado". Sai ~13% da duração.

**Remover:**
- Hesitações `Hã / hã / ãh` com duração ≥ 0,15 s
- Fragmentos de falsa partida: token com `--` ou prefixo repetido (`tinha--`, `comple--`, `pro--`)
- Repetição imediata da mesma palavra (`de, de` · `pro, pro, pro`), ≥ 0,15 s, mantendo a última
- Tiques regionais (`pá`, `pow`) só quando ≥ 0,30 s
- Silêncios > 0,70 s → encurtar para 0,35 s (0,45 s se o gap original passava de 1,5 s)
- Cabeça: deixar 0,40 s antes da primeira palavra · Cauda: 0,60 s depois da última

**Nunca remover automaticamente:**
- Fragmento que carrega a única cópia da palavra certa (`so-sou`, `q-qual`, `vi-visualização`,
  `des-interessante`, `doc-docs`, `t-tudo`). Deletar quebra a frase — sempre revisar à mão.
- Repetição retórica ("Podia. Podia ir pro Photoshop?")
- Palavra hifenizada real (`pós-graduação`) — o detector de fragmento pega falso positivo
- Fala entre aspas ("Ah, que besteira") — parece filler, é citação

**Falsas partidas que só fecham com o vizinho** precisam de lista manual de índices
(ex.: "vou mandar-- mandei" → apagar `vou` junto). Ver `EXTRA` em `plan_cuts.py`.

**Mecânica:** a deleção de palavra se expande até o silêncio vizinho (±50 ms), então a
emenda cai em silêncio e não na borda da consoante. Cortes separados por menos de 0,35 s
**sem palavra no meio** são fundidos — ilha de 0,1 s de silêncio soa pior que cortar junto.
Nenhum segmento final abaixo de 0,30 s.

**Checar sempre:** `verify_text.py` imprime o texto que sobrou com `|` em cada emenda.
Ler isso antes de renderizar — é o único jeito barato de pegar frase quebrada.

---

## 3. Color grade

Aplicada **por segmento durante a extração** (nunca depois do concat).

```
eq=contrast=1.08:saturation=1.06,
colorbalance=rm=0.03:bm=-0.02:rh=0.03:bh=-0.03,
curves=master='0/0 0.25/0.235 0.75/0.79 1/1'
```

Correção leve para webcam: contraste, calor sutil na pele, curva S suave. O preset
`warm_cinematic` do helper dessatura demais para webcam — não usar aqui.
Testar sempre em um frame com pele antes de rodar os 196 segmentos.

---

## 4. Punch-in (dinâmica dos cortes)

Enquadramento fixo por trecho, sem animação — corte com mudança de enquadramento lê
como troca de câmera; corte com enquadramento idêntico lê como jump cut.

| Nível | Uso |
|---|---|
| 1.00 | padrão |
| 1.05 | alternado a cada corte, para nenhum corte ficar seco |
| 1.12 | frases de ênfase (lista manual, ~15 por vídeo) |

- Trecho < 1,2 s **herda** o enquadramento anterior (senão pisca nos micro-cortes)
- Crop centrado em X, `y = 15%` do que sobra → o punch tira o microfone embaixo, não a folga da cabeça
- `scale=1920:1080:flags=lanczos` no upscale
- Dimensões de crop sempre pares

O zoom fica gravado no corte: mudar a lista de ênfase custa re-extrair tudo (~40 min).

---

## 5. Motion graphics (Remotion)

**Alpha:** sequência PNG → `qtrle` `.mov`.
`npx remotion render <comp> out/seq_X --sequence --image-format=png`, depois
`ffmpeg -framerate 60 -i seq_X/element-%03d.png -c:v qtrle -pix_fmt argb X.mov`.
VP8/VP9 `yuva420p` **não** funciona — o decoder libvpx local falha no bitstream com alpha.

**Paleta:**
```
acento    #4D8DFF   (azul; convive com o roxo do Anotus)
texto     #F4F4F6
dim       #8E8E99   → #CFCFD8 quando o texto fica sobre vídeo, não sobre painel
painel    rgba(11,11,13,0.88) + borda rgba(255,255,255,0.13) + raio 18
fontes    'Segoe UI Semibold' (títulos) · Consolas (labels/mono)
```

**Posições fixas** (1920×1080):
| Elemento | Posição |
|---|---|
| Título de abertura, chips de stack, medidor | topo-esquerda `110,150` |
| Lower third, chips de feature | baixo-esquerda `110, 760-790` |
| Janela de browser (b-roll) | direita `1032,190`, `850×584` |
| Chips de CTA | baixo-direita `right:110, top:700` |

**Regras de movimento:**
- Nunca easing linear. `ease-out cubic` para entrada, `ease-in-out` para percurso contínuo
- Entrada = fade + subida de ~24 px em 18 frames; stagger de 6-14 frames entre irmãos
- Segurar o frame final ≥ 1 s antes de sair
- Nunca revelar dois elementos novos ao mesmo tempo
- Texto branco sobre parede clara **precisa de scrim**: gradiente diagonal + máscara vertical
  (`mask-image`) nas duas bordas — gradiente só horizontal deixa banda dura visível
- Sincronia: a animação chega no frame de destino **na palavra falada**, então
  `start_in_output = tempo da palavra − lead-in da animação`

**Antes de renderizar tudo:** compositar um still sobre um frame real do vídeo no momento
certo. Já custou re-render descobrir que a janela cobria o rosto e que o eyebrow cinza
sumia sobre o scrim.

**B-roll de app:** recriar as telas em CSS dá movimento real (lista montando, texto sendo
digitado, contador subindo, cursor clicando) e vale mais que print parado. Print serve de
fallback. Landing page: capturar com
`msedge --headless=new --window-size=1440,2200 --screenshot=...` e rolar dentro da moldura.

---

## 6. Deriva de timeline (a armadilha)

Cada segmento extraído fecha em fronteira de frame, então a saída codificada fica **mais
longa** que a soma do EDL — ~8 ms por corte, 1,5 s ao fim de 196 cortes. Legenda e overlay
autorados no tempo planejado saem progressivamente adiantados.

Correção obrigatória:
1. `measure_drift.py` mede cada `clips_*/seg_*.mp4` → `real_durations.json`
2. `build_srt.py` acumula offset com as durações **reais**
3. `finalize_edl.py` guarda `start_in_output` já na timeline real

Se o EDL mudar, refazer os três. Se só o filtro mudar (grade, zoom), as durações não mudam —
conferir com `measure_drift.py` e reaproveitar.

---

## 6.1 A faixa de áudio precisa ser reconstruída da fonte

O áudio que vem junto dos segmentos concatenados **não serve** para o corte final.
Cada segmento fecha o vídeo em fronteira de frame (+~24 ms) e o AAC não acompanha, então
`concat -c copy` de 352 segmentos deixa a faixa de áudio cheia de buracos de timestamp
(8,6 s somados neste vídeo). O player respeita o PTS e toca certo — mas **qualquer passada
de filtro** (mixar trilha, normalizar) materializa os buracos como silêncio e o áudio vai
atrasando: +0,4 s no minuto 2, +8,3 s no fim. É o defeito que soa como "dessincronizado"
sem dar pra dizer se está adiantado ou atrasado.

Correção (`build_audio.py`): montar a faixa inteira direto do bruto, um segmento por vez,
cada um com **exatamente a duração codificada do segmento de vídeo** (`real_durations.json`),
em PCM cru, e concatenar os bytes. A soma bate com o vídeo por construção.

Conferência obrigatória antes de entregar: correlação cruzada do áudio do render contra o
bruto em pelo menos três pontos (início, meio, fim). Tem que dar ~0 ms nos três —
se crescer do começo para o fim, a faixa foi montada errado.

## 7. Legenda

`master.srt` na timeline real, texto original (sem CAPS), quebra em pontuação forte,
em vírgula a partir de 5 palavras, teto de 8 palavras / 42 caracteres, mínimo 0,5 s por cue,
sem sobreposição. O estilo 2-palavras-MAIÚSCULAS do `render.py` é para vertical/social —
não usar em vídeo longo horizontal.

---

## 8. End card

Clipe **opaco concatenado**, não overlay — assim não depende de alinhamento de timeline
no ponto mais frágil do vídeo.

- 6 s. Último frame do corte vira fundo, desfocando e escurecendo em ~0,6 s
- O blur é animado **dentro do Remotion** (CSS filter). `gblur` do ffmpeg não aceita sigma variável no tempo
- Conteúdo: eyebrow · nome/URL grande · régua de acento desenhando · uma linha de subtítulo
- Encodar com os mesmos parâmetros dos segmentos + `anullsrc` estéreo 48 kHz → concat `-c copy`
- Antes dele, chips de CTA sincronizados na fala ("like", "comentário") no canto inferior direito
- Ícones em SVG, nunca emoji (Chrome headless renderiza emoji de forma inconsistente)

---

## 9. Verificação antes de entregar

1. `verify_text.py` — nenhuma frase quebrada
2. `timeline_view.py` no **resultado**, em 4+ emendas: sem pico de áudio, sem flash
3. Frame de cada overlay compositado: posição, legibilidade, nada cobrindo o rosto
4. `ffprobe`: duração bate com o esperado, 60 fps, `yuv420p`
5. SRT: último cue fecha junto com a última fala
6. Grade consistente entre início, meio e fim

---

## 10. Custo de iteração

| Mudança | Custo |
|---|---|
| Overlay, legenda, áudio | ~20 min (reaproveita `base_final.mp4` via `recomposite.py`) |
| Corte, grade, zoom | +40 min (re-extrai os 196 segmentos) |

Agrupar pedidos que tocam o corte. Nunca re-transcrever.
