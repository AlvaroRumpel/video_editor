# B-roll de stock — design

Data: 2026-10-06. Quarto subprojeto da série "portar ideias do OpenMontage"
(reescrita própria). Depende do EDL/overlays do video-use, da fila da UI e
do módulo `audio.py` só pelo estilo (ffmpeg via subprocess).

## Objetivo

No YouTube longo, cobrir trechos da fala com footage/foto de bancos gratuitos,
escolhidos pela relevância ao que está sendo dito, aprovados em lote pela UI
e injetados no `edl.json` como overlays que o `recomposite.py` já aplica.

## Decisões do usuário

- Modos visuais: **cut-in full-frame** (2–4 s), **janela de browser**
  (slot `1032,190 850×584` da receita), **foto com Ken Burns**.
- Seleção: Claude varre a transcrição e propõe em lote (contact sheet →
  `waiting_reply`); também atende instrução pontual ("b-roll de X no corte N").
- Fontes: Pexels, Pixabay, Unsplash, Archive.org/Wikimedia. Chaves em
  `video-use/.env` (`PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY`);
  Archive/Wikimedia sem chave.
- Relevância: busca por texto (termo em inglês derivado da fala) + avaliação
  de frames pelo Claude; **CLIP local opcional** (`torch` + `open_clip`,
  `requirements-clip.txt` separado) reordena candidatos quando instalado.
- Fora: ads (identidade é motion próprio), corpus/índice local, busca por
  imagem, tradução automática.

## Artefatos

### `edit/<proj>/broll.json`

```json
{"momentos": [
  {"id": "b01", "t_in": 83.2, "t_out": 86.4, "modo": "cutin",
   "frase": "o prazo da apelação é de 15 dias úteis",
   "termo": "courthouse calendar deadline", "fontes": ["pexels", "pixabay"],
   "candidatos": [
     {"arq": "broll/cand/b01-1.mp4", "fonte": "pexels", "id": "123", "autor": "Nome",
      "url": "https://www.pexels.com/video/123/", "licenca": "Pexels License",
      "tipo": "video", "dur": 12.0, "largura": 1920, "score": null}
   ],
   "escolhido": "b01-1", "offset": 2.5, "status": "proposto"}
]}
```

- `modo ∈ {cutin, janela, foto}`; `tipo ∈ {video, foto}`; `status ∈ {proposto, aprovado, vetado}`.
- `t_in`/`t_out` em segundos **da timeline de saída** (igual a `start_in_output`).
- `offset`: segundo inicial dentro do clipe fonte (vídeo). Foto ignora.
- `score`: `null` sem CLIP; `float` 0–1 com CLIP.

### Diretórios

```
edit/<proj>/broll/cand/<id>-<k>.<mp4|jpg> + .json   candidatos baixados + metadados
edit/<proj>/broll/out/<id>.<mp4|mov>                overlay pronto (1920×1080, 60 fps)
edit/<proj>/broll/sheet.png                         contact sheet do lote
edit/<proj>/creditos.md                             créditos dos clipes usados
```

`broll/` entra no `.gitignore` via `edit/` (já ignorado).

## Módulo `ui/stock.py`

Stdlib + ffmpeg (subprocess), mesmo molde de `audio.py`; `_fetch(url, headers) -> (status, bytes)` injetável.

| Função | Faz |
|---|---|
| `chaves() -> dict` | lê `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY` (env ou `video-use/.env`, mesmo parser de `budget._chave_elevenlabs`) |
| `buscar(termo, tipo, fontes, n, dst_dir, _fetch=None) -> list[cand]` | por fonte: Pexels `GET /videos/search?query&per_page&orientation=landscape` / `GET /v1/search/photos`; Pixabay `GET /api/videos/?key&q&per_page` / `GET /api/?key&q&image_type=photo`; Unsplash `GET /search/photos?query&orientation=landscape` (header `Authorization: Client-ID`); Archive.org `advancedsearch.php?q=<termo> AND mediatype:movies&fl[]=identifier&output=json` + `metadata/<id>` (primeiro `.mp4` ≤ 100 MB); Wikimedia `api.php?action=query&list=search&srsearch=<termo> filetype:video|bitmap&srnamespace=6&format=json` + `imageinfo&iiprop=url|size|extmetadata`. Filtros: vídeo largura ≥ 1280, 3 s ≤ dur ≤ 30 s, paisagem; foto largura ≥ 1920. Baixa até `n` por fonte (menor variante com largura ≥ 1920, senão ≥ 1280), grava `<id>-<k>.<ext>` e `.json`. Fonte sem chave → aviso em `avisos`, pula. HTTP 429 → espera `Retry-After` (máx. 60 s) uma vez, depois aviso. |
| `sheet(broll_json, dst_png)` | 1 frame por candidato (vídeo: em 30 % da duração; foto: a própria), rótulo `b01-1 · pexels · 12 s` desenhado com `drawtext`, grade via `tile` (colunas = máx. de candidatos, uma linha por momento), tiles 480×270 |
| `ranquear(broll_json) -> dict` | `import open_clip, torch` falhando → `{"ok": false, "motivo": "CLIP não instalado"}`. Senão: modelo `ViT-B-32` (`laion2b_s34b_b79k`), texto = `termo`; vídeo: 3 frames (10/50/90 %); `score` = média da similaridade cosseno normalizada; reordena `candidatos` por `score` desc e grava |
| `preparar(broll_json, edl_json, proj) -> dict` | só `status == "aprovado"`. Cut-in: `-ss offset -t (t_out−t_in)`, `scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=60,fade=in:d=0.25,fade=out:st=<dur−0.25>:d=0.25`, `-an`, H.264 CRF 18 → `broll/out/<id>.mp4`. Janela: mesmo recorte em `850×584`, composto em canvas transparente 1920×1080 em `(1032,190)` → `qtrle` `.mov` (argb). Foto: `zoompan=z='min(zoom+0.0004,1.08)':d=<frames>:s=1920x1080:fps=60` full-frame, ou recorte 850×584 no slot (modo `janela` com `tipo foto`). Depois merge em `edl.json.overlays`: reler, manter overlays cujo `file` não começa com `broll/out/`, substituir os de b-roll, `start_in_output = t_in`, `duration = t_out − t_in`; escrever atômico. Conflito: intervalo que cruza outro overlay não-broll → erro listando ids; nada escrito |
| `creditos(broll_json, dst_md)` | só aprovados: `- b01 · Pexels · <autor> · <url> · Pexels License`; bloco "Para a descrição" com os que exigem crédito (Unsplash, Wikimedia CC-BY) |
| CLI | `python ui/stock.py buscar "<termo>" --tipo video|foto --fontes a,b --n 3 --dst <dir>` · `sheet <broll.json> <png>` · `ranquear <broll.json>` · `preparar <broll.json> <edl.json> <proj>` · `creditos <broll.json> <md>`; JSON stdout UTF-8; exit 0 ok / 1 erro de validação (conflito, nada aprovado) / 2 erro de execução |

Regras de momento (na receita, não no código): 6–12 por vídeo; 2–4 s cada;
≥ 20 s entre b-rolls; nunca sobre overlay Remotion nem frase de ênfase 1.12;
nunca cobrindo legenda queimada (longo usa SRT separado — ok).

## Servidor e UI

- `GET /api/file?id&name` → serve `broll/sheet.png` e `broll/*.png`
  (`image/png`); nome validado `^broll/[\w\-]+\.png$`; 404 ausente.
- Modal Docs: lista também `broll/sheet.png`; ao selecionar, renderiza
  `<img src="/api/file?...">` em vez de HTML.
- `renderTimeline`: overlays cujo `file` começa com `broll/out/` ganham
  faixa fina (4 px) acima dos clipes, cor distinta; tooltip com o `id`.
- `state.json.broll = {"momentos", "aprovados", "fontes": {"pexels": 3, ...}}`
  → linha informativa ao lado da de áudio.
- Fila: nenhum tipo novo. Aprovação em lote = `waiting_reply` com
  `resultado` "b-roll: 8 momentos — ver Docs › broll/sheet.png. responda `ok`,
  `b03:2 b05:não b07:1` (índice do candidato ou não)". Instrução pontual =
  tipo `instrucao` existente.

## Receita — `padrao-youtube-longo.md`, nova §5.1 "B-roll de stock" (após §5)

1. Ler `transcripts/<fonte>.json` e `fatos.md`; escolher momentos pelas regras;
   escrever `broll.json` (`status: proposto`, `termo` em inglês, `modo`).
2. `python ui/stock.py buscar "<termo>" --tipo <video|foto> --fontes pexels,pixabay --n 3 --dst edit/<proj>/broll/cand` por momento; anexar candidatos.
3. `ranquear` (se CLIP instalado; senão olhar os frames do sheet).
4. `sheet edit/<proj>/broll.json edit/<proj>/broll/sheet.png`.
5. `waiting_reply` com o resumo; aplicar a resposta (`escolhido`/`status`).
6. `preparar edit/<proj>/broll.json edit/<proj>/edl.json edit/<proj>` →
   `python edit/recomposite.py` (ou o render final).
7. `creditos edit/<proj>/broll.json edit/<proj>/creditos.md`; colar o bloco na
   descrição ao exportar.
8. `state.json.broll` (merge).

§9 ganha: "overlays de b-roll: um frame no meio de cada um (nada cortado,
nada sobre o rosto no modo janela); `creditos.md` na descrição".

## CLAUDE.md

Regra: "Footage/foto de terceiros só via `ui/stock.py` (licença e crédito
registrados em `broll.json`/`creditos.md`); nunca baixar à mão. Sem custo;
sem orçamento."

## Testes (`ui/test_stock.py`, `ui/test_server.py`)

Mídia sintética por ffmpeg em `tmp_path`; `_fetch` injetado devolvendo JSON
mínimo de cada API e bytes de um MP4/JPG sintético; `skipif` sem ffmpeg.

- `buscar`: Pexels devolve 3 vídeos (1 abaixo de 1280, 1 de 45 s) → só 1
  baixado, metadados corretos; fonte sem chave → aviso e nenhum fetch;
  429 com `Retry-After: 0` → segunda tentativa.
- `sheet`: 2 momentos × 2 candidatos → PNG 960×540 (2 colunas × 2 linhas de 480×270).
- `ranquear`: sem CLIP → `ok: false`, `broll.json` intacto.
- `preparar`: cut-in → `out/b01.mp4` 1920×1080 60 fps, duração = `t_out − t_in` ± 0.05,
  sem áudio; janela → `.mov` com alpha (ffprobe `pix_fmt` argb); foto →
  duração certa; merge preserva overlay Remotion existente e substitui b-roll
  anterior; conflito → exit 1, EDL intacto; `vetado`/`proposto` ignorados.
- `creditos`: só aprovados; Unsplash entra no bloco "Para a descrição".
- Servidor: `/api/file` serve PNG, recusa `broll/../x.png` e `.md`; Docs lista o sheet.
- CLI: `ranquear` sem CLIP exit 0 com `ok:false`; `preparar` conflito exit 1.

## Fora de escopo

Ads; índice/corpus local; busca por imagem de referência; tradução automática
do termo; edição de `broll.json` pela UI (só via fila); CLIP no
`requirements.txt` padrão.
