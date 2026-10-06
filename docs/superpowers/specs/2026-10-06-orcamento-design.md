# Controle de orçamento — design

Data: 2026-10-06. Primeiro subprojeto da série "portar ideias do OpenMontage"
(reescrita própria; nada copiado do repo AGPL).

## Objetivo

Toda ferramenta que gasta dinheiro ou cota (hoje: ElevenLabs Scribe; em breve:
SFX/música ElevenLabs, stock, dublagem, vídeo por IA) precisa de autorização
antes de gastar e registra o gasto real depois. O usuário vê na UI quanto cada
projeto e o mês consumiram e aprova gastos acima de um limite pela fila que já
existe (`waiting_reply`).

## Regras aprovadas

Três mecanismos combinados (decisão do usuário):

1. **Teto por projeto** (padrão global, editável por projeto).
2. **Teto mensal** (soma de todos os projetos no mês corrente).
3. **Aprovação por ação**: qualquer gasto estimado acima de `aprovar_acima`
   pede OK na UI, mesmo dentro dos tetos.

Cota grátis (ElevenLabs no plano free) é um saldo em **créditos**, não em
dólar. Entra no orçamento como "saldo restante" lido da API, sem estimativa
própria; se a ação estimada passar do restante, vira `precisa_aprovacao` com
aviso "cota acaba".

## Arquivos

| Arquivo | Dono | Conteúdo |
|---|---|---|
| `.ui-runtime/budget.json` | UI (editável) | `{"teto_mensal_usd": 30, "teto_projeto_usd": 5, "aprovar_acima_usd": 0.5, "tetos_projeto": {"<pid>": 12}}` |
| `ui/precos.json` | repo | `{"<provedor>": {"unidade": "min_audio", "usd": 0.0, "creditos": 0}}` — preço por unidade. ElevenLabs free: `usd: 0`, `creditos` por unidade |
| `<proj>/ui/costs.jsonl` | `budget.py` | uma linha por gasto, só acréscimo: `{"ts", "provedor", "unidades", "usd", "creditos", "aprovacao": <qid|null>, "nota"}` |
| `.ui-runtime/quota.json` | `budget.py` (cache) | último saldo lido da API ElevenLabs: `{"elevenlabs": {"usados", "limite", "reset_ts", "lido_em"}}` |

Padrão de escrita: reler do disco antes de gravar (`budget.json`), `atomic_write_json`;
`costs.jsonl` é append puro, sem reescrita.

## Módulo `ui/budget.py`

Sem FastAPI, como `pipeline.py`.

```python
estimar(provedor, unidades) -> {"usd": float, "creditos": int}
gasto_projeto(proj) -> {"usd", "creditos"}            # soma do costs.jsonl
gasto_mes(root, ano_mes=None) -> {"usd", "creditos"}  # soma de todos os costs.jsonl do mês
autorizar(root, proj, provedor, unidades, aprovacao=None) -> Decisao
registrar(proj, provedor, unidades, usd=None, creditos=None, aprovacao=None, nota="")
saldo_elevenlabs(root, max_idade_s=300) -> {"usados","limite","restante"}  # GET /v1/user/subscription, cache em quota.json
```

`Decisao = {"status": "ok" | "precisa_aprovacao" | "bloqueado", "motivo": str, "estimativa": {...}}`

Ordem de avaliação em `autorizar`:

1. `gasto_mes + estimativa > teto_mensal` → `bloqueado` ("teto mensal"),
   salvo `aprovacao` presente (id de pedido `waiting_reply` respondido com sim).
2. `gasto_projeto + estimativa > teto_projeto` → idem ("teto do projeto").
3. provedor em créditos e `estimativa.creditos > restante` → `precisa_aprovacao`
   ("cota ElevenLabs acaba: restam N").
4. `estimativa.usd > aprovar_acima` → `precisa_aprovacao`.
5. senão `ok`.

Com `aprovacao` informada, 1–4 passam e o id vai gravado na linha do
`costs.jsonl` (rastreável). `autorizar` nunca grava; `registrar` grava.

Ferramenta paga = `autorizar` → (se não `ok`, pedido `waiting_reply` na fila,
texto com estimativa e motivo; parar) → executar → `registrar` com valor real.

## Servidor (`ui/server.py`)

- `GET /api/budget` → `budget.json` + `gasto_mes` + saldo ElevenLabs (cache).
- `PUT /api/budget` → merge (reler antes) nos campos de `budget.json`.
- `load_project` passa a incluir `"custos": gasto_projeto(proj)` e
  `"teto_projeto"` efetivo.
- `WATCH` ganha `"costs": "ui/costs.jsonl"` e `.ui-runtime/budget.json`
  para o SSE refletir gasto ao vivo.

## UI (`app.js` / `style.css`)

- Cabeçalho do projeto: selo `US$ 1,20 / 5,00` (barra fina; vermelho ao
  passar de 80%). Clique abre input do teto do projeto.
- Lista de projetos: linha "mês: US$ 7,40 / 30,00 · ElevenLabs 4.200/10.000
  créditos" com os tetos editáveis inline.
- Pedido `waiting_reply` de orçamento é o mesmo card de pergunta de hoje; a
  resposta "sim"/"não" é texto livre, como já funciona.

## Transcrição atual (Scribe)

`video-use/` fica fora do repo; não é alterado. Ao rodar `transcribe.py` pela
sessão, registrar por fora: `registrar(proj, "elevenlabs_scribe",
unidades=minutos_do_audio)`. Entrada em `precos.json` com `creditos` por
minuto; o número real vem da diferença de `saldo_elevenlabs` antes/depois na
primeira rodada e fica anotado no próprio `precos.json`.

## CLAUDE.md

Adicionar ao protocolo: "Antes de qualquer ação paga, `budget.autorizar`;
`precisa_aprovacao`/`bloqueado` → `waiting_reply` com estimativa; depois,
`budget.registrar`." Receitas em `Formatos/` referenciam a regra onde
houver etapa paga.

## Testes

`ui/test_budget.py`, pytest com `tmp_path` como root:

- `ok` abaixo de todos os limites;
- `precisa_aprovacao` por `aprovar_acima`;
- `precisa_aprovacao` por cota (saldo mockado);
- `bloqueado` por teto do projeto e por teto mensal;
- `aprovacao` informada libera e fica gravada no `costs.jsonl`;
- `gasto_mes` ignora meses anteriores e soma vários projetos;
- `PUT /api/budget` faz merge sem perder chaves (TestClient, como
  `test_server.py`).

## Fora de escopo

Preço de provedores ainda não integrados (entram com seus subprojetos);
conversão de câmbio; histórico além do mês corrente na UI (o `costs.jsonl`
guarda tudo, a tela só mostra o mês).
