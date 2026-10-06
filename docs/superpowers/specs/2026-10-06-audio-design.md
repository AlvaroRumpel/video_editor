# Áudio: denoise, trilha com ducking, SFX e música gerada — design

Data: 2026-10-06. Segundo subprojeto da série "portar ideias do OpenMontage"
(reescrita própria; nada copiado do repo AGPL). Depende do controle de
orçamento (`ui/budget.py`, spec de 2026-10-06).

## Objetivo

Quatro recursos de áudio que o editor não tem hoje:

1. **Denoise da voz** em todo bruto (leve, sempre; forte só com aprovação).
2. **Trilha contínua com ducking** no YouTube longo, escolhida das 15 de
   `assets/music/` ou gerada quando nenhuma serve.
3. **SFX da marca** nos motions dos ads: biblioteca gerada uma vez, disparada
   por cues.
4. **Música gerada por vídeo** (ElevenLabs Music) como alternativa à biblioteca.

Toda geração paga passa por `budget.autorizar` / `budget.registrar`. A UI não
ganha tela nova: aprovações usam a fila (`waiting_reply`), estado vai em
`state.json.audio`, custo aparece no selo do orçamento.

## Decisões do usuário

- Trilha do longo: contínua, baixa, ducking suave (não só em trechos).
- Seleção: Claude propõe 1 das 15 e pede OK; resposta "gerar" cria uma nova.
- Denoise: leve sempre (pula se o bruto já é limpo); forte só após pergunta
  na UI quando o ruído passa do limiar.
- SFX: biblioteca fixa da marca em `assets/sfx/`, gerada uma vez; cada motion
  exporta `cues.json`.
- Shorts: herdam o denoise (a fonte é o export do longo); trilha em shorts
  fora de escopo.

## Módulo `ui/audio.py`

Sem FastAPI, mesmo molde de `budget.py`: funções puras sobre `ffmpeg`
(subprocess) e `urllib`; CLI em `__main__`. Sem dependência nova.

| Função | Faz | Depende |
|---|---|---|
| `medir_ruido(src) -> float` | `silencedetect` (−40 dB, ≥ 0,4 s) acha o primeiro trecho silencioso; `astats` nesse trecho devolve RMS em dB. Sem silêncio: usa os primeiros 0,5 s | ffmpeg |
| `denoise(src, dst, forte=False) -> Path` | leve: `afftdn=nf=-25:nt=w`; forte: `arnndn=m=assets/rnnoise/std.rnnn`. Saída WAV 48 kHz mono PCM s16 | ffmpeg |
| `mix_trilha(video, trilha, dst, nivel_db=-18.0, duck_db=-8.0, fade_s=1.5)` | voz = áudio do `video`; trilha em loop (`aloop`) cortada na duração; `sidechaincompress` (voz como sidechain; `threshold=0.02:ratio=6:attack=200:release=800`) aplica o duck; `amix` voz + trilha (trilha a `nivel_db`); `afade` in/out; `loudnorm=I=-14:TP=-1:LRA=11`; `-c:v copy`, AAC 192k | ffmpeg |
| `mix_sfx(video, cues, sfx_dir, dst)` | para cada cue `{t, som, ganho_db}`: entrada `sfx_dir/<som>.wav` com `adelay=t*1000`, `volume=ganho_db`; `amix` de todos + áudio original (se houver); `-c:v copy` | ffmpeg |
| `gerar_sfx(root, proj, prompt, dur_s, dst, _fetch=None)` | `budget.autorizar(root, proj, "elevenlabs_sfx", 1)` → POST `/v1/sound-generation` `{text, duration_seconds}` → grava MP3 → converte WAV → `budget.registrar` | budget |
| `gerar_musica(root, proj, prompt, dur_s, dst, _fetch=None)` | idem com `"elevenlabs_music"`, POST `/v1/music` `{prompt, music_length_ms}` | budget |

`gerar_*` devolvem `{"status": "ok", "path"}` ou `{"status": "precisa_aprovacao" | "bloqueado", "motivo"}` — a sessão transforma em `waiting_reply` e repete com `aprovacao=`. `_fetch(key, url, body) -> bytes` injetável para teste; chave via `budget._chave_elevenlabs()`.

CLI: `python ui/audio.py medir-ruido <src>` · `denoise <src> <dst> [--forte]` ·
`mix-trilha <video> <trilha> <dst> [--nivel -18] [--duck -8]` ·
`mix-sfx <video> <cues.json> <sfx_dir> <dst>` ·
`gerar-sfx <proj> "<prompt>" <dur> <dst> [--aprovacao N]` ·
`gerar-musica <proj> "<prompt>" <dur> <dst> [--aprovacao N]`.
Saída JSON em stdout, UTF-8; erro → `{"erro"}` exit 1; `precisa_aprovacao`
exit 2; `bloqueado` exit 3 (mesmos códigos do `budget.py`).

## Preços

`ui/precos.json` ganha `elevenlabs_sfx` (unidade: `efeito`) e
`elevenlabs_music` (unidade: `faixa`), ambos `usd: 0`, `creditos` medido na
primeira rodada por diferença de `budget.py saldo` antes/depois, anotado no
próprio arquivo (mesmo protocolo do Scribe).

## Assets

- `assets/rnnoise/std.rnnn` — modelo RNNoise padrão (arquivo público do
  projeto rnnoise-models, commitado; ~300 KB). Sem ele, `denoise(forte=True)`
  falha com erro explícito.
- `assets/sfx/` — 6 sons, ~1 s, WAV: `pop-dourado`, `whoosh-reveal`,
  `click-pill`, `sting-endcard`, `tick`, `rise`. Gerados uma vez por
  `gerar_sfx`; `assets/sfx/CREDITS.md` guarda prompt, duração e data de cada
  um. Estão fora do `.gitignore` (são da marca, pequenos).

## Receitas

### `padrao-youtube-longo.md`

- **0.3 Ruído e limpeza da voz** (nova, antes de 1. Pipeline): `medir_ruido`
  no bruto → `state.json.audio.ruido_db`. Se < −60 dB: pula denoise. Senão
  `denoise` leve → `edit/<proj>/voz_limpa.wav`; **transcrição e `build_audio.py`
  usam `voz_limpa.wav`** como fonte de áudio (vídeo continua vindo do bruto;
  a regra 6.1 continua valendo — a faixa é reconstruída a partir do WAV
  limpo). Se ruído > −45 dB: `waiting_reply` "ruído de fundo alto
  (−38 dB); aplicar denoise forte (RNNoise)? pode deixar a voz levemente
  metálica" → sim: `denoise(forte=True)`.
- **8.1 Trilha** (nova, após 8. End card e antes de 9. Verificação):
  1. Escolher 1 trilha das 15 pelo tom do vídeo (tabela de tom → trilha
     sugerida fica na receita, preenchida na primeira rodada).
  2. `waiting_reply`: "trilha: sb-Amberlight (calma, piano). ok / outra: <nome> / gerar: <descrição>".
  3. `gerar` → `gerar_musica` com prompt = descrição + "instrumental, sem vocal, loopável, −18 LUFS" e `dur_s` = duração do final; passa pelo orçamento.
  4. `mix_trilha(final.mp4, trilha, final.mp4)` (escreve em temp e substitui).
  5. `state.json.audio` ← `{trilha, nivel_db, duck_db}`.
  6. Repetir seção 9: `ffprobe` loudness −14 e correlação cruzada da voz em 3 pontos (a mixagem não pode mover a voz).
- Instrução "trilha mais baixa/alta" → ajustar `nivel_db` ±3 dB e remixar a partir de `final_sem_trilha.mp4` (guardado antes do passo 4).

### `padrao-youtube-shorts.md`

Nota em "Método 1. Fonte": o export já vem com voz limpa e trilha do longo; não
reaplicar denoise nem trilha.

### `padrao-ads.md`

- "Técnica de produção" ganha **SFX**: cada `anim.html` exporta
  `cues.json` ao lado (lista `{t, som, ganho_db}` derivada dos frames dos
  eventos: ponto dourado = `pop-dourado`, reveal = `whoosh-reveal`, pill =
  `click-pill`, end card = `sting-endcard`). Após montar o vídeo mudo:
  `mix_sfx` → depois a trilha pelo caminho já existente (`loudnorm −15`), com
  a trilha a −20 dB enquanto houver SFX nos 300 ms seguintes
  (`sidechaincompress` com os SFX como sidechain).
- "Áudio" ganha a opção **música gerada**: quando o briefing pede tom
  específico, `gerar_musica` com prompt da `descricao`, `dur_s` = duração
  alvo; passa pelo orçamento.
- Primeira rodada: gerar a biblioteca de `assets/sfx/` (6 chamadas,
  aprovação única na UI com o custo total).

## `state.json.audio`

```json
{"ruido_db": -52.3, "denoise": "leve", "trilha": "sb-Amberlight",
 "nivel_db": -18, "duck_db": -8}
```

Escrita pela sessão com merge (reler, preservar outras chaves). A UI mostra
como linha informativa no painel do projeto (`app.js`: se `state.audio`
existir, renderiza "áudio: trilha X · −18 dB · denoise leve").

## Testes (`ui/test_audio.py`)

Fixtures geram WAV/MP4 sintéticos com ffmpeg (`sine` + `anoisesrc`,
`color` para vídeo), marcados `skipif` sem ffmpeg no PATH.

- `medir_ruido`: tom com silêncio de ruído a −50 dB → devolve ≈ −50 ± 3.
- `denoise`: RMS do trecho de ruído cai ≥ 6 dB; duração igual à entrada.
- `mix_trilha`: RMS da trilha nos trechos com fala < RMS nos trechos sem
  fala (medido com `astats` nas janelas); loudness integrada ≈ −14 ± 1;
  vídeo inalterado (`ffprobe` codec/duração).
- `mix_sfx`: energia no instante do cue > energia 1 s antes; `-c:v copy`.
- `gerar_sfx`/`gerar_musica`: `_fetch` injetado devolve bytes de um WAV;
  `budget` em `tmp_path` com `precos.json` de teste; `autorizar` bloqueado →
  nenhum fetch; ok → arquivo criado e `costs.jsonl` com 1 linha.
- CLI: `medir-ruido` imprime JSON; `gerar-sfx` com projeto inexistente →
  exit 1.

## Fora de escopo

Trilha em shorts; SFX no longo; ducking por fala em ads (não há fala); seleção
automática de trilha por análise musical (a escolha é por tom descrito na
receita); UI dedicada de áudio.
