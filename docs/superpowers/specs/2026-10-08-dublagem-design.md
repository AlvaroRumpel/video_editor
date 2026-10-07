# Dublagem e tradução — design (subprojeto 7)

Data: 2026-10-08. Série "portar ideias do OpenMontage" (reescrita própria,
nada copiado — AGPL). Depende de: `clips.py` (`words_out`, `frases`, `edl`,
`render`), `audio.py` (`mix_trilha`), `budget.py` (autorizar/registrar,
`_chave_elevenlabs`), `folha.py`/`folha.js` (6b), `eventos.py` (6a/6c),
`video-use/helpers/render.py`.

## Objetivo

Levar um vídeo pronto (longo, shorts dele e ads) para outro idioma:
legenda traduzida, faixa de áudio dublada (multi-language audio do YouTube),
vídeo dublado completo (voz + textos na tela traduzidos) e ads/shorts em
espanhol — com tradução controlada (glossário, aprovação antes de gastar) e
custo sob orçamento.

## Decisões do usuário

- Entregas: legenda traduzida; áudio dublado (faixa extra); vídeo dublado
  separado; shorts/ads em espanhol. Tudo num subprojeto só (fala + textos
  na tela).
- Voz por peça: voz clonada (canal) ou voz de biblioteca (ads de marca),
  configurável por projeto.
- Abordagem: pipeline próprio (tradução pelo Claude + TTS por frase +
  encaixe no tempo + remix em camadas); textos na tela por
  extração/aplicação de strings em cópias localizadas.
- Sem sincronia labial (talking head fica com boca em português).

## Configuração

- `ui/glossario.json`: `{"<termo pt>": {"es": "...", "en": "..."} | "manter"}`.
  Semente com termos jurídicos/marca ("Anotus": "manter", "súmula",
  "jurisprudência", "STF": "manter", "vade mecum": "manter", "OAB": "manter",
  "flashcard"…). Comparação sem diferenciar maiúsculas, por palavra inteira.
- `ui/vozes.json`: `{"padrao": {"voice_id", "nome"}, "<marca>": {...}}`
  (usuário preenche). Projeto: `state.json.dub = {"voz": {"voice_id","nome"},
  "idiomas": {"es": {"etapa": "<frases|traducao|tts|encaixe|mix|pronto>"}}}`
  (merge). Voz do projeto > marca (`edit/shorts/<marca>/…`) > `padrao`.
- `ui/precos.json`: `elevenlabs_tts` `{"unidade": "caractere", "usd": 0.0,
  "creditos": 0, "nota": "medir na 1a rodada"}`.

## Fala — `ui/dublagem.py`

Padrão dos módulos `ui/*.py` (stdlib; `sys.path.insert`; subprocess em lista,
`timeout`, `_run`/`_fetch` injetáveis; CLI JSON UTF-8, exit 0/1/2).
Diretório de trabalho: `<proj>/dub/<lang>/`. `lang` = `[a-z]{2}`.

### `dublagem.json`

```json
{"lang": "es", "voz": {"voice_id": "...", "nome": "..."},
 "frases": [{"id": "f001", "t_in": 12.4, "t_out": 15.85, "orig": "...", "trad": null,
             "audio": null, "hash": null, "dur": null, "fator": null, "estado": "nova"}]}
```
`estado` ∈ `nova | traduzida | gerada | encaixada | estoura`.

### Funções

- `frases(proj, lang, words) -> dict` — `words` = palavras na timeline do
  export (`clips/words_out.json`, gerado por `clips.py words-out`). Agrupa
  com `clips.frases(words, pausa=0.35)` e quebra frases > 12 s na palavra mais
  próxima do meio. Cria/atualiza `dublagem.json` preservando `trad` de frases
  cujo `orig` não mudou (por id + texto).
- `validar(proj, lang, root) -> {"ok", "erros": [...], "longas": [...]}`:
  toda frase com `trad` não vazia; termos do glossário presentes no `orig`
  exigem o alvo (ou o original, se "manter") no `trad`; estimativa de fala
  `len(trad) / CPS[lang]` (CPS: `es` 15, `en` 14, padrão 14) > 1.15 × slot →
  frase em `longas` (Claude encurta antes de gastar). `ok` = sem erros e sem
  longas.
- `tts(proj, lang, root, aprovacao=None, _fetch=None) -> dict` — frases com
  `trad` cujo `hash` (sha1 de `voice_id + "\n" + trad`) difere do salvo ou sem
  `audio`: soma caracteres → `budget.autorizar(root, proj, "elevenlabs_tts",
  chars, aprovacao)`; status ≠ ok → devolve `{"status", "motivo", "estimativa"}`
  sem gerar. ok → POST `https://api.elevenlabs.io/v1/text-to-speech/<voice_id>`
  (`model_id` `eleven_multilingual_v2`, `output_format` `mp3_44100_128`) por
  frase → `dub/<lang>/fNNN.mp3`; atualiza `audio`, `hash`, `estado: gerada`;
  `budget.registrar` com os caracteres gerados. Erro de rede numa frase para
  o lote e registra só o que foi gerado.
- `encaixar(proj, lang, _run=None) -> dict` — para cada frase com áudio: `dur`
  (ffprobe), `fator = dur / (t_out − t_in)`; `fator ≤ 1` → usa como está;
  `1 < fator ≤ 1.25` → `atempo=fator`; `> 1.25` → `estado: estoura` (não
  entra). Monta `dub/<lang>/voz.wav` (48 kHz mono, duração = duração do export)
  posicionando cada frase em `t_in` (`adelay` + `amix`, normalize=0). Devolve
  `{"encaixadas", "aceleradas", "estouradas": [ids]}`. Com estouradas o voz.wav
  é gerado mesmo assim (Claude decide: encurtar e refazer).
- `srt(proj, lang) -> str` — cues = frases com `trad` (texto quebrado em
  linhas ≤ 42 caracteres, ≤ 2 linhas por cue; frase longa vira várias cues
  proporcionais ao tamanho).
- `mixar(proj, lang, export, nome, root, video=None, _run=None) -> dict` —
  `export` = vídeo final em PT; `video` = vídeo com overlays localizados (se
  houver, ver Textos) ou `export`. Gera em `Export/`:
  `<nome> - <lang>.m4a` (voz.wav + trilha de `state.json.audio` via
  `audio.mix_trilha`, ou só voz com loudnorm −14 se não houver trilha),
  `<nome> - <lang>.mp4` (vídeo de `video` + esse áudio) e
  `<nome> - <lang>.srt`.
- `words(proj, lang) -> list` — pseudo-palavras traduzidas: cada frase
  distribui suas palavras pelo intervalo `[t_in, t_out]` proporcional ao
  tamanho; formato `{"t","e","w"}` de `words_out`. Salva
  `dub/<lang>/words.json` (usado pelos shorts).
- `edl(proj, lang, root) -> dict` — copia `edl.json` para
  `dub/<lang>/edl.json` trocando cada `overlays[].file`
  `animations/remotion/out/X.mov` por `animations/remotion/out_<lang>/X.mov`
  quando este existir; devolve `{"trocados", "mantidos"}`.
- CLI: `frases`, `validar`, `tts [--aprovacao]`, `encaixar`, `srt`, `mixar
  --export --nome [--video]`, `words`, `edl`.

## Textos na tela — `ui/localiza.py`

- `extrair(arquivos, saida) -> dict` — `.html`: nós de texto visíveis
  (`html.parser`, ignora `script`/`style`) e atributos `alt`/`title`;
  `.tsx`/`.jsx`: texto entre tags JSX (`>…<` sem `{`) e literais `"…"`/`'…'`
  com espaço e letra (exclui os que parecem classe CSS — só `[a-z0-9:-]` e
  espaços —, caminhos e URLs). Normaliza espaços. Saída
  `{"textos": {"<orig>": {"id": "tNN", "trad": null, "arquivos": [...]}}}`;
  mescla com saída existente preservando `trad`.
- `aplicar(textos, origem, destino) -> dict` — copia `origem` (arquivo ou
  pasta) para `destino` e substitui cada `orig` por `trad` só entre
  delimitadores: `>\s*orig\s*<`, `"orig"`, `'orig'`, `alt="orig"`,
  `title="orig"`; ordem do mais longo ao mais curto. `trad == "="` mantém.
  `trad` vazio/nulo em algum texto → `ValueError` listando ids, nada copiado.
  Devolve `{"substituicoes": n, "arquivos": [...]}`.
- `checar(html, frames=8, largura=540, altura=960) -> dict` — Playwright
  chromium: abre o arquivo, espera `window.READY`, para N frames distribuídos
  chama `window.seek(f)` e lista elementos com texto cujo
  `scrollWidth > clientWidth + 1` ou `scrollHeight > clientHeight + 1` ou caixa
  fora do palco → `{"ok", "estouros": [{"frame","seletor","texto"}]}`.
- CLI: `extrair <arquivos…> --saida`, `aplicar <textos.json> <origem>
  <destino>`, `checar <html> [--frames]`.

Por formato (receita `Formatos/dublagem.md`):
- Longo: extrair de `edit/animations/remotion/src` → traduzir → `aplicar` em
  `edit/animations/remotion/src.<lang>/` → renderizar as composições usadas
  no `edl.json` para `out_<lang>/` → `dublagem.py edl` → `render.py
  dub/<lang>/edl.json` → `mixar --video`.
- Ads: extrair `anim.html` → traduzir → `aplicar` → `anim.<lang>.html` →
  `checar` → captura/montagem/SFX/trilha da receita de ads → `…-<lang>.mp4`.
- Shorts: `clips.py edl … --lang <lang>` (fonte = `Export/<nome> - <lang>.mp4`,
  legenda de `dub/<lang>/words.json`, pastas `clips/<lang>/…`) e `render …
  --lang <lang>` para `Export/shorts/<proj>/<lang>/`.

## `clips.py` (extensão)

- `edl(clips, proj, export, words, pasta="clips")` e `render(clips, proj,
  export_dir, preview=False, _run=None, pasta="clips")`: `pasta` define onde
  ficam os `NN-slug-plat/edl.json` (default inalterado).
- CLI `edl … [--lang xx]`: usa `dub/xx/words.json` e `pasta="clips/xx"`;
  `render … [--lang xx]` usa `pasta="clips/xx"`.

## Folha `traducao` (6b)

- `folha.ler(proj, "traducao", lang=None)` — lê `dub/<lang>/dublagem.json`
  e (se existir) `dub/<lang>/textos.json`; `lang` default = único idioma
  presente em `dub/` (vários → `ValueError`).
  `{"lang", "frases": [{"id","t_in","t_out","orig","trad","slot","estimativa"}],
  "textos": [{"id","orig","trad","arquivos"}]}`.
- `/api/folha?tipo=traducao[&lang=]`.
- `folha.js`: duas seções (Fala, Tela); cada linha mostra original e um
  campo editável com a tradução; fala mostra `slot` vs `estimativa` (vermelho
  se estimativa > slot). Resposta: `ok` + `fNNN: <texto>` / `tNN: <texto>`
  para cada linha editada (texto ≠ proposto, uma linha da resposta por
  edição, separadas por `\n`).
- `FOLHAS` (app.js) e `folha.TIPOS` ganham `traducao`.

## UI

- Board: etapa `dublagem` mostra linha de info `dub: es pronto · en tts`
  (de `state.json.dub.idiomas`).
- Docs: `dub/<lang>/*.srt` e `textos.json`/`dublagem.json` não entram (Docs só
  mostra `.md`/png); o `.srt` final fica em `Export/`.

## Receitas e protocolo

- `Formatos/dublagem.md` (nova, sem front-matter — como `referencia.md`, é
  sub-fluxo): todo o fluxo é a etapa `dublagem` do projeto (`inicio` →
  `espera --nota` na folha `traducao` e no orçamento → `inicio` ao retomar →
  `fim --nota "es: m4a/mp4/srt"`), decisões (voz, acelerações > 1.15×) via
  `eventos.py decisao`, `state.json.dub.idiomas.<lang>.etapa` atualizado a
  cada passo.
- `padrao-youtube-longo.md` e `padrao-ads.md`: etapa opcional `dublagem?` +
  mapa apontando para `Formatos/dublagem.md`.
- CLAUDE.md seção "Dublagem": glossário obrigatório; `validar` antes de
  `tts`; folha `traducao` antes de gastar; voz por projeto; nunca traduzir
  fato sem `[F#]` mudando sentido; orçamento via `tts`.

## Erros

| situação | comportamento |
|---|---|
| sem `voice_id` resolvido | `tts` → ValueError "configure ui/vozes.json" |
| orçamento negado | `tts` devolve status, nada gerado |
| erro HTTP no TTS | para o lote, registra o gerado, exit 2 |
| frase estoura (> 1.25×) | `estado: estoura`, fora do voz.wav, listada |
| texto sem tradução no `aplicar` | ValueError, nada copiado |
| projeto sem trilha | áudio = só voz com loudnorm |
| chromium ausente | `checar` → exit 2 com motivo |

## Testes

- `ui/test_dublagem.py`: `frases` (pausa, pontuação, quebra > 12 s, preserva
  trad); `validar` (sem trad, glossário, longas); `tts` (`_fetch` falso,
  cache por hash, troca de voz invalida cache, orçamento ok/negado,
  registrar, erro HTTP no meio); `encaixar` (ffmpeg real com tons
  sintéticos: ≤1, atempo, estoura; duração do voz.wav); `srt`; `words`;
  `edl` (troca só o que existe); `mixar` (com e sem trilha, `--video`);
  CLI.
- `ui/test_localiza.py`: `extrair` html/tsx (ignora script/classe/URL,
  mescla preservando trad); `aplicar` (delimitadores, mais longo primeiro,
  "=", falta de trad → nada copiado); `checar` (html sintético com estouro;
  pula sem chromium).
- `ui/test_clips.py`: `edl`/`render` com `pasta` e CLI `--lang`.
- `ui/test_folha.py` + `test_server.py` + smoke: folha `traducao` (ler,
  vários idiomas → erro, editar linha gera `ok\nf002: …`).

## Fora do escopo

Sincronia labial; separar voz/música de vídeos sem trilha separada;
thumbnails traduzidas; upload da faixa no YouTube (manual); idiomas
direita→esquerda; clonar voz pela API (usuário cria no site e põe o
`voice_id` em `vozes.json`).
