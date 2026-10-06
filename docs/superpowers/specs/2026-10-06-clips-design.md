# Clip Factory — design (subprojeto 5a)

Data: 2026-10-06. Quinto subprojeto da série "portar ideias do OpenMontage"
(reescrita própria). O "vídeo de referência" (5b) fica em spec próprio.

## Objetivo

De um YouTube longo já exportado, produzir um lote de Shorts: candidatos por
heurística → curadoria e nota do Claude → aprovação em lote na UI → EDLs por
clipe e plataforma → render → rascunhos no Publora. Substitui os scripts
hardcoded `edit/shorts/words_out.py` e `edit/shorts/build_shorts.py`.

## Decisões do usuário

- Ranking **híbrido**: script gera ~20 candidatos; Claude reordena, dá nota
  1–5, define beats e corta para a meta.
- Meta N por vídeo (≈ 1 short a cada 8 min; 5–8 num vídeo de 40–60 min).
- **Mapa de plataforma**: Shorts (≤ 60 s), Reels (≤ 90 s), TikTok (≤ 60 s,
  legenda queimada). 1 EDL por variante.
- Legenda queimada opcional por clipe.
- Aprovados viram **drafts** no Publora (nunca agendados: plano Starter limita
  3 agendados / 7 dias — memória `publora-postagem`).
- Fonte sempre o **export horizontal** (`Export/<nome> - horizontal.mp4`),
  nunca o bruto. Reframe `crop=608:1080:{x}:0,scale=1080:1920:flags=lanczos`,
  `x` por clipe (padrão 636). Overlays Remotion do longo não entram.

## Artefatos

### `edit/<proj>/clips/words_out.json`

Palavras na timeline do export: `[{"t": 0.225, "e": 0.985, "w": "Então,"}, ...]`
(mesma matemática do `build_srt.py`: cada range do EDL contribui suas palavras
deslocadas pela soma das durações **reais** (`real_durations.json`) dos
segmentos anteriores).

### `edit/<proj>/clips/clips.json`

```json
{"fonte": "Export/<nome> - horizontal.mp4", "meta_n": 6, "x_padrao": 636,
 "clipes": [
  {"id": "c01", "slug": "zero-assinantes", "nota": 5,
   "gancho": "Então, eu criei um SaaS.",
   "ranges": [{"t_in": 0.175, "t_out": 2.125, "beat": "HOOK"},
              {"t_in": 9.065, "t_out": 18.822, "beat": "CUSTO"}],
   "x": 636, "legenda": true, "plataformas": ["shorts", "reels", "tiktok"],
   "status": "proposto",
   "heuristica": {"score": 0.71, "motivos": ["pausa antes", "pergunta", "fecha em ponto"]}}
 ]}
```

- `status ∈ {proposto, aprovado, vetado}`; `nota` 1–5 (do Claude; `null` até curadoria).
- `t_in`/`t_out` já com padding (−50 ms / +80 ms) aplicado e sentados em
  fronteira de palavra do `words_out.json`.
- `heuristica` é preenchida por `candidatos`; o Claude não a edita.

### Saídas

```
edit/<proj>/clips/<NN-slug>-<plat>/edl.json     1 dir por clipe×plataforma (render.py usa edit_dir = pai do EDL)
edit/<proj>/clips/<NN-slug>-<plat>/legenda.srt  quando legenda queimada (referenciado no EDL por "subtitles")
edit/<proj>/clips/clips.md                       tabela para o modal Docs
Export/shorts/<proj>/<NN-slug>-<plat>.mp4        render final
```

EDL gerado: `{"version": 1, "sources": {"EXPORT": "<abs>"}, "ranges": [{"source": "EXPORT", "start", "end", "beat", "quote"}], "grade": "crop=608:1080:<x>:0,scale=1080:1920:flags=lanczos", "overlays": [], "subtitles": "legenda.srt"?}`.

## Módulo `ui/clips.py`

Stdlib; `render.py` por subprocess; mesmo molde dos outros módulos.

| Função | Faz |
|---|---|
| `words_out(edl: dict, transcript: dict, real: list[float]) -> list` | versão genérica do `words_out.py` |
| `frases(words, pausa=0.6) -> list[{"t","e","texto","palavras"}]` | agrupa por pausa ≥ 0,6 s ou pontuação final (`.?!`) |
| `candidatos(words, n=20, min_s=25, max_s=60) -> list` | janelas que começam numa fronteira de frase e terminam em fim de frase, dentro de `[min_s, max_s]`; score = `0.35·gancho + 0.25·fechamento + 0.20·densidade + 0.20·autonomia` — gancho: pergunta `?`, número, "eu/minha", absoluto (`sempre|nunca|todo|ninguém`) nos 3 s iniciais; fechamento: termina em `.`/`!`/`?` seguido de pausa ≥ 0,8 s; densidade: palavras/s normalizada (2–3,5 w/s = 1); autonomia: sem dêiticos (`isso|esse|essa|aqui|aquilo|ele|ela`) nos 2 s iniciais. Dedupe: descarta janela com > 60 % de sobreposição temporal com outra de score maior. Devolve `[{"t_in","t_out","texto","score","motivos"}]` com padding aplicado |
| `validar(clips: dict, words: list) -> {"ok","erros","avisos"}` | bordas em fronteira de palavra (± 5 ms após remover o padding); duração por plataforma (shorts 20–60, reels 20–90, tiktok 20–60) para cada plataforma do clipe; ranges de um clipe sem sobreposição e em ordem crescente de `t_in` **não** exigida (cold open permitido) mas sem duplicar texto; `aprovados ≤ meta_n + 2`; dois aprovados com > 50 % de palavras em comum → erro; `slug` único `[a-z0-9-]+`; `x` par e `0 ≤ x ≤ 1312` |
| `edl(clips: dict, proj: Path, export: Path) -> {"gerados": [...]}` | só `aprovado`; por plataforma: dir `clips/<NN-slug>-<plat>/`, `edl.json`, `legenda.srt` se `legenda` ou `plat == "tiktok"` (cues de 1–3 palavras, ≤ 1,2 s, tempo relativo ao clipe somando ranges), `clips.md` (tabela id · nota · duração · gancho · plataformas · status) |
| `render(clips: dict, proj: Path, export_dir: Path, preview=False) -> {"renderizados", "erros"}` | `python video-use/helpers/render.py <edl> -o Export/shorts/<proj>/<NN-slug>-<plat>.mp4 [--preview]` por dir; erro de um não para os outros |
| CLI | `words-out <edl> <transcript> <real_durations> <out.json>` · `candidatos <words_out.json> <out.json> [--n 20]` · `validar <clips.json> <words_out.json>` · `edl <clips.json> <proj> <export.mp4>` · `render <clips.json> <proj> <export_dir> [--preview]`; JSON stdout UTF-8; exit 0 / 1 (validação) / 2 (execução) |

`NN` = posição do clipe na lista de aprovados ordenada por `nota` desc, `t_in` asc (2 dígitos).

## Fluxo (receita `padrao-youtube-shorts.md`, reescrita)

1. `python ui/clips.py words-out edit/<proj>/edl.json edit/<proj>/transcripts/<fonte>.json edit/<proj>/real_durations.json edit/<proj>/clips/words_out.json`.
2. `python ui/clips.py candidatos edit/<proj>/clips/words_out.json edit/<proj>/clips/candidatos.json --n 20`.
3. Curadoria (Claude): ler `candidatos.json` + transcript; escolher `meta_n` + 2; para cada um: `nota`, `gancho`, `slug`, `beats`, cold open se valer, `x`, `legenda`, `plataformas`; escrever `clips.json` (`status: proposto`). Regras: hook nos 2 s; 1 ideia por clipe; termina em virada ou CTA; evitar dois clipes do mesmo trecho.
4. `validar` → corrigir até `ok`.
5. `edl` (gera `clips.md`) → `waiting_reply`: "clipes: N propostos — ver Docs › clips/clips.md. responda `ok`, ou `c03:não c05:nota 3 c07:x=700 c02:sem-legenda`".
6. Aplicar resposta → `status`, re-`validar`, re-`edl`.
7. `render --preview` → `waiting_reply` "previews em Export/shorts/<proj>/ — `ok` ou ajustes" → `render` final.
8. Publora (Claude via MCP, conta da marca da memória `publora-postagem`): para cada arquivo final, `create_post` draft (legenda = gancho + 1 frase + hashtags do padrão da marca; sem travessão), `get_upload_url` → PUT → `complete_media`; nunca `scheduled`. Registrar `state.json.clips = {"propostos", "aprovados", "renderizados", "publora_drafts": [ids]}`.

Instrução pontual ("faz um short do trecho dos 12 anos") = entrada única em `clips.json` sem passar por `candidatos`.

## UI

Sem tela nova: Docs lista `clips/clips.md`? — o modal lista só `*.md` na raiz do projeto, então `edl` grava **`edit/<proj>/clips.md`** (raiz) além de `clips/clips.md`. Linha informativa `clips: 6 aprovados · 4 renderizados · 3 drafts` a partir de `state.json.clips` (mesmo padrão de áudio/b-roll).

## Orçamento

Nada pago (transcrição já existe; Publora é assinatura).

## Testes (`ui/test_clips.py`)

- `words_out`: EDL de 2 ranges com drift (`real` ≠ `end−start`) → palavras do 2.º range deslocadas pela duração real do 1.º.
- `frases`: pausa e pontuação quebram; sem pausa junta.
- `candidatos`: transcript sintético de 120 s com um trecho de 40 s que começa com pergunta após pausa e termina em `.` + pausa → é o 1.º candidato; janelas sobrepostas deduplicadas; nenhuma fora de `[25, 60]`.
- `validar`: borda fora de palavra → erro; shorts de 70 s → erro, reels de 70 s → ok; ranges sobrepostos → erro; dois aprovados iguais → erro; `x` ímpar → erro; `aprovados > meta_n+2` → erro.
- `edl`: 1 clipe aprovado × 3 plataformas → 3 dirs com `edl.json` (grade com `x`, ranges com `quote`), `legenda.srt` só em tiktok (+ onde `legenda: true`), `clips.md` na raiz e em `clips/`.
- `render`: export sintético de 10 s (1920×1080@60 com tom) → `render.py` real `--preview` → saída 1080×1920; erro num EDL não impede o outro.
- CLI: `validar` exit 1; `candidatos` JSON.

## Fora de escopo

Vídeo de referência (5b); agendamento no Publora; miniatura/capa do short;
legendas estilizadas (usa o estilo do `render.py`); detecção de rosto para o `x`.
