# Pesquisa web + roteiro — design

Data: 2026-10-06. Terceiro subprojeto da série "portar ideias do OpenMontage"
(reescrita própria). Depende do protocolo da fila (`CLAUDE.md`) e da UI.

## Objetivo

Antes de escrever roteiro — e depois de gravar — toda afirmação factual passa
por pesquisa com fonte citada. Um artefato único (`pesquisa.md`) alimenta
quatro portas de entrada:

1. **Ads**: `novo-projeto` (formato ads) → pesquisa → `roteiro.md` → produção.
2. **Longo, antes de gravar**: pedido `roteiro` → pesquisa → `roteiro.md` com
   estrutura e bullets para o usuário gravar.
3. **Longo, depois da transcrição**: `fatos.md` — afirmações verificáveis da
   fala, checadas; erro/imprecisão vira sugestão de overlay ou corte.
4. **Pauta mensal**: pedido `pauta` → `PAUTA.md` com ângulos ancorados em
   dados.

## Decisões do usuário

- Motor de busca: o que render melhor → **WebSearch/WebFetch da sessão**
  (grátis, já disponível). `ui/pesquisa.py` só valida e arquiva; API paga
  (Tavily/Brave) fica como upgrade, entraria como provedor em `precos.json`.
- Fontes aceitas para fato: **primárias/oficiais** (planalto.gov.br, STF, STJ,
  `*.jus.br`, `*.gov.br`, Diário Oficial) **e doutrina reconhecida** (lista
  editável). Blogs/vídeos só como inspiração de ângulo, nunca como fonte de
  fato.

## Artefatos

### `edit/<proj>/pesquisa.md`

```markdown
# Pesquisa — <tema>
<!-- gerado: AAAA-MM-DD · formato: ads|longo|pauta -->

## Pergunta
<o que o vídeo precisa responder>

## Achados
- [F1] <fato em uma frase> — fonte: <nome> (<lei|jurisprudência|doutrina|dado|outro>) — <URL> — acesso AAAA-MM-DD
  > trecho literal curto (≤ 300 caracteres)
- [F2] ...

## Ângulos
- <o que outros já fizeram sobre o tema> — <URL> (inspiração)
- <lacuna / ângulo não explorado>

## Riscos
- <termo ambíguo, lei alterada recentemente, pegadinha de prova>

## Fontes rejeitadas
- <URL> — <motivo: blog sem autoria, lei revogada, data antiga...>
```

Ids `[F#]` são únicos no arquivo e referenciados pelos outros artefatos.

### `edit/<proj>/roteiro.md` (ads e longo pré-gravação)

```markdown
# Roteiro — <título>
<!-- formato: ads|longo · duração alvo: NN s|min · pesquisa: pesquisa.md -->

## Hook (≤ 2 s)
<frase>

## Cenas            (ads)        |  ## Estrutura        (longo)
1. <texto na tela / fala> [F1]   |  1. <bloco> — bullets com [F#]
   sfx: pop-dourado              |

## CTA
<texto>

## Cues (ads)
[{"t": 0.0, "som": "pop-dourado"}, ...]
```

Regra: toda afirmação factual leva `[F#]`; frase sem `[F#]` é opinião, método
ou instrução — permitido. `validar` cobra isso só para frases que o
`extrair-fatos` classificaria como verificáveis (número, artigo/lei, súmula,
"sempre/nunca/todo/proibido").

### `edit/<proj>/fatos.md` (longo pós-transcrição)

| t (s) | trecho | status | fonte | ação |
|---|---|---|---|---|
| 83.2 | "o prazo é de 15 dias" | errado | [F3] CPC art. 1003 §5º: 15 dias úteis | overlay "15 dias **úteis**" |

`status ∈ {ok, impreciso, errado, sem_fonte}`; `ação ∈ {nada, overlay: <texto>, corte}`.

### `PAUTA.md` (pauta)

Mesmo formato já em uso (`edit/shorts/anotus/PAUTA.md`), com cada ângulo
seguido de `[F#]` apontando para `edit/shorts/<marca>/pauta-AAAA-MM/pesquisa.md`.

### `edit/<proj>/fontes/F#.html`

Snapshot da página citada (auditoria se o link morrer).

## Módulo `ui/pesquisa.py`

Sem FastAPI, stdlib (`urllib`, `re`, `json`, `html.parser` só para título).
Não busca: valida, arquiva, extrai.

| Função / CLI | Faz |
|---|---|
| `parse_pesquisa(md) -> dict` | `{"achados": [{"id","fato","fonte","tipo","url","acesso","trecho"}], "angulos": [...], "riscos": [...], "rejeitadas": [...]}` |
| `classificar(url) -> "oficial"|"doutrina"|"inspiracao"` | por `ui/fontes.json` (`{"oficial": ["planalto.gov.br", "stf.jus.br", "stj.jus.br", "*.jus.br", "*.gov.br", "in.gov.br"], "doutrina": [...]}`); sufixo de domínio, `*.` casa subdomínios |
| `validar(md_path, _fetch=None) -> {"ok", "erros", "avisos"}` | erros: achado sem URL; URL que não responde 2xx/3xx (HEAD, fallback GET, timeout 10 s); fato com fonte `inspiracao`; `[F#]` duplicado; `roteiro.md`/`fatos.md` referenciando `[F#]` inexistente. Avisos: acesso > 180 dias; trecho vazio |
| `snapshot(md_path, dir, _fetch=None)` | grava `F#.html` (≤ 2 MB cada) + `fontes/index.json` `{id, url, titulo, salvo_em}` |
| `extrair_fatos(transcript_json) -> list` | frases (por pausa ≥ 0,5 s ou pontuação) que contêm: número + unidade/`%`/`dias`/`anos`; `art\.`, `Lei n`, `súmula`, `inciso`, `§`; `sempre|nunca|todo|toda|proibido|vedado|obrigat`. Devolve `[{"t", "trecho", "gatilho"}]`. Heurística; só aponta |
| CLI | `python ui/pesquisa.py validar <md> [--roteiro <md>] [--fatos <md>]` · `snapshot <md> <dir>` · `extrair-fatos <transcript.json>` — JSON em stdout, exit 0 ok / 1 erro de validação / 2 erro de execução |

`_fetch(url) -> (status:int, body:bytes)` injetável para teste.

## Servidor e UI

- `GET /api/docs?id=<pid>` → lista `*.md` do projeto (nome, mtime).
- `GET /api/doc?id=<pid>&name=<arquivo.md>` → `{"name", "html"}`; markdown
  mínimo em Python (títulos, listas, negrito/itálico, código inline, blocos
  `>`, tabelas simples, links) — sem lib; nome validado (`[\w\-. ]+\.md`, sem
  `/`), path dentro do projeto.
- UI: botão **Docs** no header (ao lado de Formatos) → modal com lista à
  esquerda e documento à direita (mesmo padrão do modal de formatos); somente
  leitura. `WATCH` ganha `"docs": "*.md"` via mtime do mais recente, para o
  modal atualizar quando eu gravar um artefato.
- Fila: tipos novos `roteiro` (`target = {tema, duracao_min, publico}`) e
  `pauta` (`target = {marca, mes}`), ambos na fila global (`.ui-runtime`);
  `QUEUE_TYPES` do servidor aceita os dois; UI ganha "Roteiro" e "Pauta" no
  modal de Novo vídeo (campo de formato: ads | longo | roteiro | pauta —
  `roteiro`/`pauta` escondem o bruto e mostram os campos do `target`).

## Fluxo por porta (receitas)

### Ads — `padrao-ads.md`, seção nova "Pesquisa e roteiro" antes de "Técnica de produção"

1. Ler `descricao` + `fontes` do pedido e a `PAUTA.md` da marca.
2. 5–15 buscas (WebSearch): fato central, lei/artigo citado, jurisprudência
   recente, o que concorrentes postaram (ângulos), perguntas do público.
3. Escrever `pesquisa.md`; `python ui/pesquisa.py validar` + `snapshot`.
4. `waiting_reply`: "pesquisa: N achados, M ângulos, R riscos — ver Docs.
   `seguir` / `aprofundar: <o quê>`".
5. Escrever `roteiro.md` (hook, cenas com `[F#]`, CTA, cues); `validar --roteiro`.
6. `waiting_reply`: "roteiro pronto — ver Docs. `ok` / `mudar: ...`".
7. Produção (motion → SFX → trilha, como já descrito).

### Longo antes de gravar — `padrao-youtube-longo.md`, "0.0 Roteiro antes de gravar (opcional)"

Pedido `roteiro` → criar `edit/<slug>/` com `ui/` → passos 2–6 acima com
formato `longo` (estrutura em blocos, bullets, duração alvo) → fim: "roteiro em
Docs; grave e crie o projeto com o bruto". O projeto fica listado na UI como
"não iniciado" até o bruto chegar.

### Longo depois da transcrição — "1.1 Checagem de fatos"

Após `transcribe.py`: `extrair-fatos` → para cada trecho, pesquisar (fonte
oficial/doutrina) → `fatos.md` → se houver `errado`/`impreciso`:
`waiting_reply` listando-os com a ação sugerida; `ok` → aplicar overlays
(Remotion, texto curto no canto) ou cortes via EDL (regras de palavra). `ok`
em tudo → só registrar em `state.json.fatos = {"total", "errados", "imprecisos"}`.

### Pauta — `Formatos/pauta.md` (interno, fora do dropdown como `thumbnail`)

Pedido `pauta` → `edit/shorts/<marca>/pauta-AAAA-MM/pesquisa.md` (calendário
acadêmico/provas, mudanças de lei do mês, perguntas frequentes, o que a
concorrência postou, temas já usados em `PAUTA.md` anterior) → `PAUTA.md`
novo com 6 ângulos + `[F#]` → `waiting_reply` "pauta pronta — ver Docs".

## CLAUDE.md

- Tipos `roteiro` e `pauta` no ciclo de pedidos.
- Regra: "Fato citado em roteiro/overlay exige `[F#]` com fonte `oficial` ou
  `doutrina` (`ui/fontes.json`). Blog/vídeo = inspiração. `pesquisa.py validar`
  antes de pedir aprovação."

## Orçamento

Nenhuma ação paga. A receita anota que a busca é da sessão. Se entrar API de
busca, vira provedor em `precos.json` e segue o protocolo de orçamento.

## Testes (`ui/test_pesquisa.py`, `ui/test_server.py`)

- `parse_pesquisa`: arquivo de exemplo → 2 achados com todos os campos; `[F#]`
  duplicado → erro em `validar`.
- `classificar`: `https://www.planalto.gov.br/...` → oficial; `x.jus.br` →
  oficial; domínio da lista doutrina → doutrina; `blog.com` → inspiracao.
- `validar` com `_fetch` injetado: URL 404 → erro; fato com fonte
  `inspiracao` → erro; acesso antigo → aviso; roteiro com `[F9]` inexistente →
  erro; tudo certo → `ok: true`.
- `snapshot`: grava `F1.html` e `index.json`; corpo > 2 MB truncado.
- `extrair_fatos`: transcript sintético com 4 frases → só as 2 com gatilho.
- Servidor: `/api/docs` lista; `/api/doc` renderiza título/lista/tabela/link;
  nome com `..` → 400; `QUEUE_TYPES` aceita `roteiro`/`pauta`.
- CLI: `validar` exit 1 com erro; `extrair-fatos` JSON.

## Fora de escopo

Busca por API; geração de imagens para pauta; publicação no Publora;
renderização de markdown completa (sem HTML embutido, sem imagens);
verificação automática de fatos (a checagem é minha, o script só extrai e
valida formato).
