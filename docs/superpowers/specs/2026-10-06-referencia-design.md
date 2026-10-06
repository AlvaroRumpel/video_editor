# Vídeo de referência — design (subprojeto 5b)

Data: 2026-10-06. Sexto subprojeto da série "portar ideias do OpenMontage"
(reescrita própria). Depende de: orçamento (`budget.py`), pesquisa
(`pesquisa.py validar`), receita de ads, modal Docs, `stock.sheet` (padrão de
contact sheet).

## Objetivo

A partir de um Reel/Short/TikTok (URL ou arquivo), medir o que o faz
funcionar (ritmo de fala, cortes, texto na tela, áudio) e propor 2–3
conceitos diferenciados de ad Anotus, cada um com roteiro no formato da
receita de ads e um **animatic** (storyboard com a identidade da marca). O
usuário escolhe pela UI; o escolhido entra no fluxo de produção já existente.

## Decisões do usuário

- Entrada: URL via `yt-dlp` (instalação do usuário: `pip install yt-dlp`) ou
  arquivo local em `bruto/ref/`. Instagram pode exigir cookies → erro com
  dica "baixe à mão e passe o arquivo".
- Análise: transcrição (Scribe, paga, via orçamento) + ritmo de fala; cortes
  e ritmo visual (`scdet`); texto na tela; música × fala.
- Saída: conceitos A/B/C **todos com roteiro + animatic**; produção completa
  só do escolhido (ou dos listados em `produzir: A B`).
- Custo por conceito: transcrição da referência, SFX/música gerada,
  horas de produção, "exige vídeo por IA" (subprojeto 8).
- Assunção aceita: texto na tela = Claude lendo `sheet.png` (sem tesseract).

## Artefatos

```
bruto/ref/<slug>.mp4                    vídeo de referência (nunca commitado; bruto/ é ignorado)
bruto/ref/<slug>.json                   {"origem": "url|arquivo", "url", "plataforma", "autor", "titulo", "dur", "publicado", "baixado_em"}
edit/shorts/<proj>/ref/analise.json     ver abaixo
edit/shorts/<proj>/ref/sheet.png        keyframes: 1 por corte (máx. 24), grade 6 colunas, tiles 320×568, rótulo "t=12.4s"
edit/shorts/<proj>/conceitos.md         análise resumida + tabela A/B/C
edit/shorts/<proj>/roteiro-A.md …       formato ads (hook / cenas / CTA / cues), [F#] onde houver fato
edit/shorts/<proj>/animatic-A.png …     storyboard 4×2 (até 8 quadros 1080×1920 reduzidos a 270×480)
edit/shorts/<proj>/pesquisa.md          quando algum conceito cita fato (regra de fontes vale)
```

### `analise.json`

```json
{"video": "bruto/ref/x.mp4", "dur": 31.2, "largura": 1080, "altura": 1920,
 "fala": {"wps": 3.1, "pausas_por_min": 6, "gancho_2s": "você sabe que...", "cta": "link na bio", "dur_fala": 27.0},
 "cortes": [0.0, 2.4, 5.1, ...], "plano_medio_s": 2.6, "cortes_por_min": 23,
 "audio": {"lufs": -14.8, "fala_pct": 0.86, "musica": true},
 "sheet": "ref/sheet.png", "transcript": "transcripts/x.json"}
```

`fala` é `null` quando não há transcrição.

### `conceitos.md`

```markdown
# Referência: <titulo> — <plataforma> · <autor> · <url>

## O que faz funcionar
- gancho: "<2 s iniciais>" · <wps> palavras/s · <cortes_por_min> cortes/min · plano médio <s> · música <sim/não> · texto na tela: <resumo do sheet>

## Conceitos
| | A | B | C |
|---|---|---|---|
| Ideia | ... | ... | ... |
| Mantém | ritmo 23 cortes/min, gancho com pergunta | ... | ... |
| Muda | tema → prazo recursal; visual → motion Anotus | ... | ... |
| Custo (créditos/R$) | 0 / R$ 0 | 200 cr (SFX) | ... |
| Horas | 2 | 3 | 5 |
| Exige IA | não | não | sim (clipe gerado — subprojeto 8) |
| Roteiro | roteiro-A.md | roteiro-B.md | roteiro-C.md |
| Animatic | animatic-A.png | animatic-B.png | animatic-C.png |
```

## Módulo `ui/referencia.py`

Stdlib + ffmpeg (subprocess) + `playwright.sync_api` (já instalado; import tardio só em `animatic`). `_run` injetável para `yt-dlp`.

| Função | Faz |
|---|---|
| `slug_de(origem) -> str` | URL → id do vídeo (`youtube.com/shorts/<id>`, `instagram.com/reel/<id>`, `tiktok.com/.../video/<id>`) ou `ref-<hash8>`; arquivo → stem sanitizado `[a-z0-9-]` |
| `baixar(origem, dst_dir, _run=None) -> dict` | URL: `[sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--write-info-json", "--no-playlist", "-o", "<dst>/<slug>.%(ext)s", url]`; `yt_dlp` não importável → `RuntimeError("yt-dlp não instalado: pip install yt-dlp")`; stderr com `login`/`cookies`/`rate-limit` → `RuntimeError("plataforma exige login — baixe à mão em bruto/ref/ e passe o arquivo")`. Arquivo: copia para `dst_dir/<slug>.mp4`. Escreve `<slug>.json` (campos do info-json: `uploader`, `title`, `duration`, `upload_date`, `webpage_url`, `extractor_key`; arquivo local: `plataforma: "arquivo"`). Devolve o dict |
| `cortes(video, limiar=10) -> list[float]` | `ffmpeg -i v -vf "scdet=t=<limiar>" -an -f null -` → parse `lavfi.scd.time=`; sempre inclui `0.0`; ordenado, dedupe < 0,2 s |
| `keyframes(video, tempos, dst_png, max_n=24)` | se `len(tempos) < 4`: tempos = `range(0, dur, 2)`; 1 frame em `t + 0.1`; tile 320×568 (`force_original_aspect_ratio=decrease` + `pad`), `drawtext` "t=12.4s"; `tile=6xR` |
| `audio(video) -> dict` | `ebur128` → `lufs` (integrated); `fala_pct`: `highpass=f=200,lowpass=f=3400,silencedetect=n=-35dB:d=0.3` → 1 − (silêncio / dur); `musica`: `bandreject=f=1000:w=2600` (tira a banda de voz) + `astats` RMS > −40 dB |
| `fala(transcript: dict) -> dict` | `wps` = palavras / dur_fala; `pausas_por_min` (gaps ≥ 0,5 s); `gancho_2s` = palavras com `start < 2.0`; `cta` = últimas 2 frases (`pipeline.phrases_from_transcript`); `dur_fala` = último `end` − primeiro `start` |
| `analisar(video, proj, transcript_json=None) -> dict` | roda `cortes`, `keyframes` → `ref/sheet.png`, `audio`, `fala` (se transcript), `ffprobe` dims; grava `ref/analise.json`; devolve |
| `cenas_de(roteiro_md) -> list[{"n","texto","sfx"}]` | parse de "## Cenas": itens numerados `1. <texto> [F#]` e linha `sfx:` opcional; máx. 8 |
| `animatic(roteiro_md, dst_png, marca="anotus")` | HTML por cena (540×960 CSS; fundo `#F3F2FA`, texto Fraunces 700 `#2B215C` ≤ 120 caracteres, pill com "cena N", wordmark `Anotus.` com ponto dourado `#D4A017`; marca ≠ anotus → paleta neutra), Playwright chromium `deviceScaleFactor=2` → PNG 1080×1920 por cena em `tmp/`, `tile=4x2` (black pad) → `dst_png`. Playwright ausente → `RuntimeError("playwright não instalado")` |
| CLI | `baixar <url|arquivo> <dst_dir>` · `analisar <video> <proj> [--transcript <json>]` · `animatic <roteiro.md> <dst.png> [--marca anotus]`; JSON stdout UTF-8; exit 0 / 1 (validação: origem inválida, roteiro sem cenas) / 2 (execução) |

Transcrição fica fora do módulo: a receita chama `transcribe.py` (video-use) sob o orçamento e passa o JSON.

## Servidor e UI

- `QUEUE_TYPES` + `new_project`: formato `referencia` → entrada `{"type": "referencia", "target": {"origem", "marca", "nome", "briefing"}}` na fila global; 400 sem `origem` ou `nome`.
- `GET /api/brutos-ref` → nomes em `bruto/ref/*.mp4`.
- Modal Novo vídeo: formato `referencia` mostra "URL" (texto) **ou** "Arquivo em bruto/ref" (select de `/api/brutos-ref`), marca, nome, briefing; esconde bruto/fontes.
- `/api/file` e a lista do Docs: aceitar `ref/<nome>.png` e `animatic-<A-Z>.png` (regex `^(broll|ref)/[\w\-]+\.png$|^animatic-[A-Z]\.png$`; path resolvido dentro do projeto).
- Linha informativa `ref: 3 conceitos · escolhido B` de `state.json.ref = {"conceitos", "escolhido", "produzidos": [...]}`.

## Receita — `Formatos/referencia.md` (interna, fora do dropdown)

1. `python ui/referencia.py baixar "<url|bruto/ref/x.mp4>" bruto/ref` → anotar `url/autor` para o `conceitos.md`.
2. Orçamento: `python ui/budget.py autorizar edit/shorts/<proj> elevenlabs_scribe <min>` → `transcribe.py bruto/ref/<slug>.mp4` → `registrar`. (`waiting_reply` se exit 2/3.)
3. `python ui/referencia.py analisar bruto/ref/<slug>.mp4 edit/shorts/<proj> --transcript edit/shorts/<proj>/transcripts/<slug>.json`.
4. Claude: ler `ref/sheet.png` (texto na tela, enquadramento, cor), `analise.json`, briefing e `PAUTA.md` da marca → `conceitos.md` (3 conceitos: mesmo mecanismo/outro tema; mesmo tema/outro mecanismo; contrário do original) + `roteiro-A/B/C.md`. Fatos → `pesquisa.md` + `pesquisa.py validar --roteiro`. Custo: créditos via `precos.json`, horas estimadas, `exige IA` quando o conceito depende de clipe gerado.
5. `python ui/referencia.py animatic edit/shorts/<proj>/roteiro-A.md edit/shorts/<proj>/animatic-A.png --marca <marca>` ×3.
6. `waiting_reply`: "referência analisada — ver Docs › conceitos.md e animatic-A/B/C.png. responda `A` | `B` | `C` | `ajuste: ...` | `produzir: A B`".
7. Escolhido → `cp roteiro-X.md roteiro.md`; `state.json.ref` (merge); seguir `padrao-ads.md` a partir de "Técnica de produção". `produzir: A B` → produção completa de cada um em subpasta `edit/shorts/<proj>/<X>/`.

`CLAUDE.md`: tipo `referencia` no ciclo de pedidos → `Formatos/referencia.md`. Regra: referência é inspiração de **mecanismo**, nunca cópia de texto/visual; `conceitos.md` registra URL e autor.

## Orçamento

Só a transcrição é paga (receita passo 2). SFX/música dos conceitos são
estimativa (produção depois passa pelo orçamento normal).

## Testes (`ui/test_referencia.py`, `ui/test_server.py`)

- `slug_de`: 3 URLs → ids; arquivo → stem sanitizado.
- `baixar`: arquivo local → cópia + json `plataforma: arquivo`; URL com `_run` injetado → comando contém `-m yt_dlp`, `--no-playlist`, `-o .../<slug>.%(ext)s`; info-json fake → campos mapeados; `_run` com stderr "login required" → `RuntimeError` com "baixe à mão"; `yt_dlp` não importável (monkeypatch `sys.modules`) → erro de instalação.
- `cortes`: vídeo sintético 9 s com 3 trocas de cor (a 3, 6 s) → `[0.0, ~3, ~6]` ± 0,15.
- `keyframes`: 3 cortes → grade 6×1 (1920×568); `< 4` cortes com `dur` 9 s → tempos 0/2/4/6/8.
- `audio`: tom 1 kHz puro → `musica` false, `fala_pct` ≈ 1; tom + ruído branco −20 dB → `musica` true.
- `fala`: transcript sintético → `wps`, `gancho_2s`, `cta`.
- `analisar`: grava `analise.json` com todas as chaves; sem transcript → `fala: null`.
- `cenas_de`: roteiro com 3 cenas + `sfx:` → 3 itens; sem "## Cenas" → `[]`.
- `animatic`: roteiro de 3 cenas → PNG 1080×960 (4×2 de 270×480) (`skipif` sem Playwright/chromium).
- Servidor: `referencia` em `QUEUE_TYPES`; `new_project` com `formato: referencia` → entrada; 400 sem origem; `/api/brutos-ref`; `/api/file` aceita `ref/sheet.png` e `animatic-A.png`, recusa `ref/../x.png` e `animatic-a.png`.
- CLI: `analisar` em vídeo inexistente → exit 2; `animatic` sem cenas → exit 1.

## Fora de escopo

OCR automático; download com cookies; métricas de engajamento; produção
completa dos 3 por padrão; análise de múltiplas referências de uma vez.
