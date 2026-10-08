# Vídeo por IA — design (subprojeto 8)

Data: 2026-10-08. Série "portar ideias do OpenMontage" (reescrita própria,
nada copiado — AGPL). Depende de: `stock.py` (`broll.json`, `preparar`,
`creditos`, `sheet`), `folha.py`/`folha.js` (folha `broll`, 6b),
`budget.py` (autorizar/registrar), `eventos.py` (decisões, 6c),
`audio.py` (molde do `_gerar` pago).

## Objetivo

Gerar footage por IA quando stock não resolve, nos três usos:

1. **B-roll do longo** — momento sem candidato bom de stock recebe quadros
   gerados como candidatos extras na mesma folha `broll`.
2. **Ads/shorts sem bruto** — cenas que pedem footage real (conceitos
   `exige_ia` da referência, ou roteiro de ad) geradas em 9:16.
3. **Imagem→vídeo de assets** — animar foto/print/mockup da marca.

Custo sempre sob orçamento, com aprovação **antes** de gastar com vídeo.

## Decisões do usuário

- Provedor: **fal.ai** (uma chave, vários modelos atrás da mesma API de
  fila; trocar modelo = trocar id em `ui/ia.json`). Decidido pelo Claude a
  pedido do usuário; revisável.
- Modelo: **barato padrão + caro sob pedido** — padrão econômico
  (ex.: Kling 2.5 Turbo / Seedance, ~US$0,05–0,07/s); top (ex.: Veo 3.1 /
  Kling 3 Pro, ~US$0,22–0,40/s) só quando o usuário pede ou em momento
  herói (gancho do ad), sempre com custo na pergunta. Preços de referência
  2026, conferidos na 1ª rodada.
- Aprovação: **quadro primeiro** — 2–3 imagens-chave por momento
  (centavos); folha mostra os quadros; só o escolhido vira vídeo
  (imagem→vídeo). Mesmo caminho anima assets da marca.
- Gatilho no longo: **Claude propõe, usuário aprova** — stock primeiro;
  IA só em momento sem candidato bom de stock.
- Estilo: **preset por marca** em `ui/ia.json` (sufixo de prompt).
- Abordagem: **estender o b-roll** — candidato IA dentro do `broll.json`,
  mesma folha, mesmo `preparar`. Sem subsistema paralelo.
- Defaults assumidos: clipe sem áudio; 5 s gerados e cortados ao momento;
  saída do modelo escalada para 1920×1080 (longo) ou 1080×1920 (ads);
  aviso de conteúdo sintético na publicação.

## Configuração

- `ui/ia.json` (novo, commitado):

  ```json
  {"modelos": {"quadro": "<endpoint fal texto→imagem>",
               "video": "<endpoint fal imagem→vídeo econômico>",
               "video_top": "<endpoint fal imagem→vídeo top>"},
   "duracao_s": 5,
   "estilos": {"padrao": "documentary footage, natural light, neutral tones",
               "anotus": "photoreal, soft light, purple and lilac accents"}}
  ```

  Os ids exatos dos endpoints são conferidos no plano (mudam com o
  catálogo do fal). Chave da marca = mesma dedução de `dublagem`
  (`edit/shorts/<marca>/…`), senão `padrao`.
- `video-use/.env`: `FAL_KEY` (mesmo parser de `budget._chave_elevenlabs`).
- `ui/precos.json`: entradas novas
  - `fal_quadro` `{"unidade": "imagem", "usd": <conferir>, "creditos": 0}`
  - `fal_video` `{"unidade": "segundo", "usd": <conferir>, "creditos": 0}`
  - `fal_video_top` `{"unidade": "segundo", "usd": <conferir>, "creditos": 0}`

  Valores iniciais do site do fal no plano; 1ª rodada real confere contra o
  débito no painel do fal e corrige.

## Artefatos

Candidato IA no `edit/<proj>/broll.json` (campos novos; o resto igual ao
candidato de stock):

```json
{"arq": "broll/cand/b03-ia1.png", "fonte": "ia", "tipo": "foto",
 "prompt": "close-up of a judge's gavel on a wooden desk",
 "estilo": "padrao", "aspecto": "16:9", "custo_est": 0.35,
 "licenca": "gerado por IA (fal/<modelo quadro>)", "autor": "", "url": "",
 "dur": 0.0, "largura": 1920}
```

Depois de `animar`:

```json
{"arq": "broll/cand/b03-ia1.mp4", "tipo": "video", "dur": 5.0,
 "quadro": "broll/cand/b03-ia1.png", "modelo_video": "<endpoint>",
 "licenca": "gerado por IA (fal/<modelo vídeo>)"}
```

- Durante a geração: `fal_req = {"id", "modelo", "status_url",
  "response_url"}` gravado **antes** do poll; removido ao concluir.
  Download falho após `COMPLETED` mantém `fal_req` + `resultado_url`.
- Momento: campo opcional `modelo: "video" | "video_top"` (padrão
  `video`). `modo` novo `cena` (ads, sem `preparar`). `modo: foto` nunca é
  animado — o quadro IA vira foto com Ken Burns pelo `preparar` existente.
- Rótulo do candidato continua `b03-<k>` (índice), sem gramática nova.

```
edit/<proj>/broll/cand/<mid>-ia<k>.png    quadro gerado (ou cópia do asset)
edit/<proj>/broll/cand/<mid>-ia<k>.mp4    clipe animado
```

## Módulo `ui/ia_video.py`

Stdlib (`urllib`, `base64`, `json`) + ffmpeg por subprocess, molde de
`audio.py`; `_fetch(metodo, url, headers, body) -> (status, headers, bytes)`
injetável. Gasto autorizado e registrado por dentro — receita nunca chama
`budget.py` por fora.

### Cliente fal (fila)

- Envio: `POST https://queue.fal.run/<endpoint>` com
  `Authorization: Key <FAL_KEY>`, JSON → `request_id`, `status_url`,
  `response_url`.
- Poll de `status_url` a cada 5 s até `COMPLETED` / `FAILED`; timeout
  10 min → `pendente`.
- `COMPLETED` → GET `response_url` → URL da mídia → download.
- Cobrança do fal ocorre no sucesso: `budget.registrar` roda logo após
  `COMPLETED`, **antes** do download/conversão; bytes baixados vão ao disco
  antes de qualquer conversão (regra do `audio._gerar`).
- Imagem de entrada do imagem→vídeo: data URI base64 do png. Se o endpoint
  não aceitar data URI (conferir no plano), usar o upload de storage do fal.
- HTTP 429/5xx: espera `Retry-After` (máx. 60 s) e tenta 1 vez.

### Funções

| Função | Faz |
|---|---|
| `config(root) -> dict` | lê `ui/ia.json`; valida chaves `modelos.quadro/video/video_top` |
| `prompt_final(cfg, prompt, estilo) -> str` | `prompt + ", " + estilos[estilo]`; estilo ausente → `padrao` |
| `quadros(root, proj, mid, prompt, estilo=None, n=3, aspecto="16:9", aprovacao=None, _fetch=None) -> dict` | momento `mid` precisa existir no `broll.json`. `autorizar(fal_quadro, n)` → status ≠ ok devolve a decisão sem gerar. Gera `n` imagens → `broll/cand/<mid>-ia<k>.png` (k continua após os existentes) → `registrar` → anexa candidatos (`custo_est` = estimativa de `animar` desse candidato) com merge atômico |
| `asset(proj, mid, arquivo, movimento) -> dict` | copia `arquivo` para `broll/cand/<mid>-ia<k>.<ext>` como candidato `fonte: ia`, `prompt = movimento`; sem custo |
| `estimar(root, proj) -> dict` | momentos `aprovado` cujo `escolhido` é candidato IA `tipo foto` e `modo ≠ foto` → `{"itens": [{"id", "modelo", "usd"}], "usd": total, "texto": "animar 3 clipes ≈ US$1,05"}` |
| `animar(root, proj, ids=None, aprovacao=None, _fetch=None) -> dict` | mesmo filtro do `estimar` (opcional `ids`). Uma `autorizar` por provedor (`fal_video`, `fal_video_top`) com unidades = segundos somados; qualquer status ≠ ok → devolve a decisão sem gerar nada. Por item: `fal_req` presente → só poll; senão envia (prompt final, imagem, `duracao_s`, aspecto). Concluído → `registrar` → baixa `<mid>-ia<k>.mp4` → candidato vira `video` (`dur` via ffprobe, `quadro`, `modelo_video`) com merge atômico |

Escrita do `broll.json`: sempre relê do disco, faz merge por `id` de
momento e `arq` de candidato, escreve atômico (tmp + replace). Nunca
sobrescreve candidatos/momentos que não conhece.

Saída de `animar`: `{"status": "ok", "feitos": [...], "falhas":
[{"id", "erro"}], "pendentes": [...], "usd": x}`.

### CLI

```
python ui/ia_video.py quadros <proj> <mid> "<prompt>" [--estilo x] [--n 3] [--aspecto 16:9|9:16] [--aprovacao id]
python ui/ia_video.py asset   <proj> <mid> <arquivo> "<movimento>"
python ui/ia_video.py estimar <proj>
python ui/ia_video.py animar  <proj> [--ids b03,b05] [--aprovacao id]
```

JSON UTF-8 no stdout. Exit no contrato do `audio.py`: 0 ok, 2
`precisa_aprovacao`, 3 `bloqueado` (do orçamento), 1 qualquer erro
(validação ou execução, com `{"erro"}`). `animar` com falhas parciais e
ao menos um feito/pendente → exit 0 (falhas no JSON); nenhum feito nem
pendente e falhas → exit 1.

## Receitas

- **`Formatos/padrao-youtube-longo.md` §5.1 (b-roll):** depois de
  `stock.py buscar`/`sheet`, momento sem candidato bom → `ia_video.py
  quadros` (2–3, prompt em inglês derivado da frase). Até 4 momentos IA por
  vídeo sem perguntar antes; acima disso a pergunta da folha pede. Folha
  aprovada → `ia_video.py estimar` vira a frase de custo → `animar` (exit
  2/3 → `waiting_reply` com o texto, repetir com `--aprovacao`) → só então
  `stock.py preparar`.
- **`Formatos/padrao-ads.md` (etapa `producao`):** cena que pede footage
  real → momento `modo: cena` no `broll.json` (`t_in`/`t_out` do roteiro),
  `--aspecto 9:16`, mesma folha `broll`. Clipe animado entra como
  `<video>` no `anim.html` ou concatenado por ffmpeg; sem `preparar`.
  Asset da marca → `ia_video.py asset`.
- **`Formatos/referencia.md`:** conceito `exige_ia: true` calcula custo com
  `fal_*` de `precos.json`; produção segue o caminho dos ads.
- **Top sob pedido:** Claude grava `modelo: "video_top"` no momento só por
  pedido explícito ("b03 no top") ou momento herói, com custo na pergunta.
- **Decisões:** escolher IA no lugar de stock →
  `eventos.py decisao broll "IA <mid>" --alt "stock <rótulo>" --custo <usd>`;
  usar `video_top` → `decisao provedor`.
- **1ª rodada:** 1 quadro + 1 clipe econômico; conferir débito no painel
  do fal; corrigir `usd` em `precos.json`.

## Folha `broll`

`folha.py` `_broll`: candidato `fonte == "ia"` ganha rótulo
`b03-4 · ia · ~US$0,35` (de `custo_est`) e `prompt` no title da miniatura.
Miniatura = o png (já é `tipo foto`). Gramática da resposta inalterada
(`ok b03:4`). Sem mudança no servidor.

## Créditos e divulgação

`stock.py creditos`:
- Linha `- b03 · gerado por IA · fal/<modelo>`; `_exige_credito` falso.
- Ao menos um clipe IA aprovado → bloco **"Divulgação"** no `creditos.md`:
  marcar "conteúdo alterado ou sintético" no YouTube Studio e rótulo de IA
  no Instagram. Etapa `qc` confere o bloco.

## Erros

| Caso | Comportamento |
|---|---|
| Sem `FAL_KEY` | exit 1 `"FAL_KEY ausente em video-use/.env"`; nada gasto |
| `ui/ia.json` ausente/inválido | exit 1 com a chave faltando |
| Orçamento `precisa_aprovacao`/`bloqueado` | exit 2/3 com motivo + estimativa; nada enviado |
| HTTP 4xx no envio (moderação, parâmetro) | item em `falhas` com a mensagem do fal; sem registro de gasto; Claude reescreve o prompt ou desiste de IA no momento |
| 429/5xx | espera `Retry-After` (máx. 60 s), 1 nova tentativa; depois item em `falhas` |
| `FAILED` no poll | sem registro; limpa `fal_req`; item em `falhas` |
| Timeout 10 min | mantém `fal_req`; item em `pendentes`; próximo `animar` só faz poll |
| Download falha após `COMPLETED` | gasto já registrado; mantém `fal_req` + `resultado_url`; próximo `animar` só baixa |
| `escolhido` IA sem arquivo no disco | exit 1 listando ids |
| `quadros` com `mid` inexistente | exit 1 |

## Testes

`ui/test_ia_video.py` (pytest, `_fetch` falso, sem rede; root temporário
com `precos.json`/`budget.json` fixture):

- `quadros`: autoriza `n` → pngs + candidatos `fonte ia` com `custo_est` →
  1 registro no `costs.jsonl`. Orçamento exit 2 → nada baixado, nada
  anexado.
- `animar` feliz: envio → 2 polls → `COMPLETED` → mp4 (gerado por ffmpeg no
  fake) → candidato `video`; `stock.preparar` aceita o momento.
- Retomada: `fal_req` presente → nenhum envio, só poll.
- `FAILED` → sem registro. Download falho após `COMPLETED` → registro feito,
  `fal_req` + `resultado_url` mantidos; nova chamada só baixa.
- Filtro: `modo foto` e candidato de stock ignorados; `modelo: video_top`
  usa o endpoint top e o provedor `fal_video_top`.
- `estimar` soma certo com preços fixture.
- Merge: candidato adicionado entre leitura e escrita sobrevive.
- `asset`: copia sem chamar `_fetch` e sem registro.
- CLI: exit 0/1/2/3 conforme contrato.
- `test_folha.py`: rótulo IA com custo e prompt.
- `test_stock.py`: `creditos` com linha IA + bloco Divulgação só quando há
  clipe IA aprovado.
- `test_ui_smoke.py`: fixture com momento de candidato IA → folha mostra o
  quadro → resposta `ok b03:4` gravada.

## Fora de escopo

- Toggle "top" e "regerar quadro" na folha (veto → Claude gera novos quadros
  no próximo ciclo).
- Lote paralelo (fila do fal é sequencial aqui; paralelizar se a espera
  incomodar).
- Áudio gerado junto do clipe; sincronia labial; avatar falante (HeyGen).
- Consistência de personagem entre clipes (referência de personagem).
- Texto→vídeo direto sem quadro.
- Motion design via HyperFrames (HTML→MP4, Apache 2.0) no lugar de
  `capture.py`/Remotion → **subprojeto 9**, brainstorm próprio com spike.
