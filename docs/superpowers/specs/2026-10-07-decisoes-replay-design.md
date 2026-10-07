# Decisões + linha do tempo/replay — design (subprojeto 6c)

Data: 2026-10-07. Série "portar ideias do OpenMontage" (reescrita própria,
nada copiado — AGPL). Depende de: 6a (`ui/eventos.py`, `eventos.jsonl`,
`quadro`, board, SPA com abas), 6b (aba Aprovação), `budget.py`
(`costs.jsonl`).

## Objetivo

Registrar as escolhas que o Claude faz (provedor, trilha, b-roll, corte,
grade…) com alternativas, motivo, custo e confiança, e mostrar:

1. no Board, as decisões de cada etapa;
2. numa aba "Linha do tempo", tudo que aconteceu no projeto em ordem
   (etapas, decisões, perguntas, respostas, custos) com filtros e replay
   animado (scrubber + play) que reconstrói o estado das etapas e o custo
   acumulado em cada instante;
3. numa página "Decisões", as decisões de todos os projetos, filtráveis por
   assunto, com as escolhas mais frequentes.

## Decisões do usuário

- Propósitos: entender o porquê; diagnosticar resultado ruim; reaproveitar
  entre projetos; replay animado.
- Tudo no `eventos.jsonl` (mesmo log do 6a, campo `tipo` aberto).

## Dados (`<proj>/ui/eventos.jsonl`, só acréscimo)

### Decisão (escrita pelo Claude via CLI)

```json
{"ts": "2026-10-07T17:20:00+00:00", "tipo": "decisao", "etapa": "audio", "assunto": "trilha",
 "escolha": "Phoenix2026", "alternativas": ["Incredulity", "Unraveling"],
 "motivo": "calma, piano, combina com tom reflexivo", "custo_usd": 0.0, "confianca": "alta"}
```

- `assunto` ∈ `ASSUNTOS` = `provedor, trilha, sfx, broll, corte, grade,
  zoom, overlay, legenda, conceito, clipe, thumbnail, render, outro`.
- `etapa` opcional; se presente, precisa estar nas etapas da receita do
  projeto (mesma validação do `registrar` do 6a).
- `escolha` texto não vazio; `alternativas` lista de textos (pode ser vazia);
  `motivo` texto (pode ser vazio).
- `custo_usd` opcional, número finito ≥ 0 (estimativa no momento; gasto real
  segue em `costs.jsonl`).
- `confianca` opcional ∈ `alta | media | baixa`.
- Campos omitidos não são gravados (exceto `alternativas` → `[]`, `motivo` → `""`).

### Resposta (escrita pelo servidor)

`/api/reply` com `id` de projeto (não `_global`) acrescenta
`{"ts", "tipo": "resposta", "qid", "texto"}` ao `eventos.jsonl` do projeto,
depois de gravar o `queue.json`. Erro ao escrever o log não falha o reply.

### Pergunta

Sem evento novo: o protocolo passa a exigir `--nota "<pergunta curta>"` no
`etapa ... espera` (o evento `etapa/espera` com nota é a pergunta na linha do
tempo).

### Custos

Lidos de `costs.jsonl` (já têm `ts`, `provedor`, `usd`, `nota`).

## Módulo `ui/eventos.py` (extensões)

- `ASSUNTOS: tuple`, `CONFIANCAS = ("alta", "media", "baixa")`.
- `registrar_decisao(proj, assunto, escolha, etapa=None, alternativas=(),
  motivo="", custo_usd=None, confianca=None, root=None) -> dict` — valida
  (projeto existe; assunto; escolha não vazia; etapa contra a receita se
  dada — receita sem etapas + etapa dada = erro; confianca; custo finito ≥ 0)
  e faz append. Inválido → `ValueError`, nada escrito.
- `registrar_resposta(proj, qid, texto) -> dict` — append (dir `ui/` criado
  se faltar).
- `ler(proj, tipo="etapa")` — `tipo=None` devolve todos os eventos válidos
  (`ts` parseável e `tipo` ∈ `etapa|decisao|resposta`); validação por tipo:
  `etapa` como hoje; `decisao` exige `assunto` texto e `escolha` texto
  (assunto fora da lista vira `outro` na leitura); `resposta` exige `qid`.
  Linha inválida é ignorada.
- `quadro(proj, root=None, agora=None, ate=None)` — `ate` (datetime aware)
  filtra eventos e custos com `ts <= ate`; `agora` default passa a ser
  `ate` quando dado. Cada etapa (e `fora_da_receita`) ganha `decisoes`:
  lista das decisões daquela etapa (ordem do log); decisões sem etapa ou de
  etapa desconhecida vão para a chave nova `decisoes_soltas`.
- `linha(proj, root=None) -> dict` —
  `{"eventos": [...], "quadros": [...]}`:
  - `eventos`: etapas, decisões, respostas e custos (`tipo: "custo"`,
    com `provedor`, `usd`, `nota`) ordenados por `ts` (estável: empate
    mantém ordem de origem, log antes de custos). Cada item ganha
    `custo_acum` (soma de `usd` dos custos até ele, 4 casas).
  - `quadros[i]` = resumo de `quadro(proj, ate=eventos[i].ts)`:
    `{"etapas": [{"id","status"}], "atual"}`.
- `decisoes(root, assunto=None) -> dict` — varre `pipeline.find_projects`:
  `{"decisoes": [{"projeto","nome","ts","etapa","assunto","escolha",
  "alternativas","motivo","custo_usd","confianca"}], "frequentes":
  [{"escolha","n"}]}` ordenadas por `ts` desc; `frequentes` só quando
  `assunto` dado (contagem de `escolha`, desc, empate alfabético). Projeto
  ilegível é pulado.
- CLI: `decisao <proj> <assunto> <escolha> [--etapa] [--alt ...]
  [--motivo] [--custo] [--confianca]`, `linha <proj>`, `decisoes
  [--assunto]` (mesmo padrão: JSON UTF-8, exit 0/1/2, `--root`).

## Servidor

- `GET /api/linha?id=` → `eventos.linha`.
- `GET /api/decisoes?assunto=` → `eventos.decisoes` (assunto fora da lista
  → 400).
- `GET /api/quadro` passa a incluir `decisoes` por etapa e
  `decisoes_soltas` (vem de `quadro`).
- `/api/reply` chama `eventos.registrar_resposta` para projeto (try/except,
  nunca falha o reply).
- SSE do projeto já observa `ui/eventos.jsonl` (6a).

## Frontend

### Board (`board.js`)

Cada card lista as decisões da etapa: `assunto · escolha (vs alt1, alt2) ·
●confiança`; clique expande motivo + custo estimado. `decisoes_soltas` vão
para o card "outros". Texto sempre via `escapeHtml`.

### Aba "Linha do tempo" (`linha.js`, aba `linha` depois de Custos)

- Busca `/api/linha` ao abrir a aba e quando o SSE recarrega o projeto com a
  aba visível.
- Lista cronológica: hora (mono), ícone por tipo (etapa ▸, decisão ◆,
  pergunta ❓ = etapa/espera com nota, resposta ↩, custo $), texto curto.
- Filtros (chips, combináveis): tipo (`etapa`, `decisao`, `pergunta`,
  `resposta`, `custo`) e assunto (aparece com `decisao` marcado).
- Replay no topo: `<input type=range>` de 0 a N−1 sobre os eventos
  **visíveis** pelo filtro; ▶/⏸ toca avançando 1 evento a cada 600 ms (2× =
  300 ms); mini-stepper com os status de `quadros[i]` (mesmas cores do
  stepper do 6a); contador `custo_acum` do evento; evento atual destacado e
  rolado para a vista. Clicar num item da lista move o scrubber até ele.
- Sem eventos: "sem histórico".

### Página "Decisões" (`decisoes.js`, rota `#/decisoes`)

- Botão "Decisões" no topo da biblioteca; `←` volta à biblioteca.
- Chips por assunto + busca (cliente) em escolha/motivo/projeto.
- Tabela: projeto (link `#/p/<id>/linha`), data, etapa, assunto, escolha,
  alternativas, motivo, confiança, custo.
- Com assunto selecionado: bloco "escolhas mais frequentes" (`escolha ×n`).

## Protocolo (`CLAUDE.md`, seção "Decisões" após "Etapas")

- Registrar só escolhas entre alternativas reais que mudam resultado ou
  custo (provedor, trilha, candidato de b-roll, x do clipe, grade, conceito,
  corte polêmico); óbvias sem alternativa, não. Teto ~30 por projeto.
- Comando: `python ui/eventos.py decisao <proj> <assunto> "<escolha>"
  --etapa <id> --alt "<alt>" ... --motivo "<por quê>" [--custo <usd>]
  [--confianca alta|media|baixa]`.
- Assunto fora da lista → `outro` + explicar no motivo.
- `etapa ... espera` sempre com `--nota "<pergunta curta>"`.

## Erros

| situação | comportamento |
|---|---|
| decisão inválida no CLI | exit 1, nada escrito |
| linha corrompida / tipo desconhecido no log | ignorada |
| assunto fora da lista no log | lido como `outro` |
| falha ao gravar `resposta` | reply segue normal |
| projeto ilegível em `/api/decisoes` | pulado |
| projeto sem log | linha vazia ("sem histórico"); board sem decisões |

## Testes

- `ui/test_eventos.py`: `registrar_decisao` (válido; assunto, escolha vazia,
  etapa fora da receita, confiança, custo NaN/negativo inválidos → nada
  escrito); `registrar_resposta`; `ler(tipo=None)` com corrompidas/tipos
  desconhecidos/assunto fora da lista; `quadro(ate=)` (status e custo no
  instante); `quadro` com `decisoes` por etapa e `decisoes_soltas`; `linha`
  (ordem, custos mesclados, `custo_acum`, um quadro por evento); `decisoes`
  (vários projetos, filtro, `frequentes`, projeto ilegível pulado); CLI.
- `ui/test_server.py`: `/api/linha`, `/api/decisoes` (+400 assunto
  inválido), `/api/quadro` com decisões, `/api/reply` grava `resposta` e
  não falha se o log falhar; `_global` não grava.
- `ui/test_ui_smoke.py`: decisões no card do Board (expandir motivo); aba
  Linha do tempo (filtro decisão, scrubber move mini-stepper e custo, play
  avança, clique na lista move scrubber); página Decisões (filtro `trilha`,
  frequentes, link para o projeto).

## Fora do escopo (6c)

Registrar decisões retroativas de projetos antigos; editar decisões pela
UI; exportar o log; gráficos.
