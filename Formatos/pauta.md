---
etapas: pesquisa, pauta, aprovacao=aprovação
---
# Pauta mensal com dados (interno; pedido `pauta`)

> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera --nota "<pergunta curta>"|pulada|falha [--nota]`):
> pesquisa = passos 1–2 · pauta = passo 3 · aprovacao = passos 4–5.

Entrada: `target = {marca, mes}`. Projeto de trabalho:
`edit/shorts/<marca>/pauta-AAAA-MM/` (criar `ui/` e `ui/state.json` = `{"formato": "pauta"}` nele para aparecer na UI e o log de etapas validar).
Saída: `pesquisa.md` e o rascunho `PAUTA.md` dentro dele; só após `ok` vai
para `edit/shorts/<marca>/PAUTA.md`.

1. Ler a `PAUTA.md` anterior (temas já usados, o que rendeu) e
   `justmind/divulgacao/CRONOGRAMA.md` §10 (regras editoriais).
2. Pesquisa (WebSearch): calendário acadêmico/provas do mês; mudanças de lei
   e súmulas do mês (planalto, STF, STJ); perguntas frequentes do público
   (fóruns, "como estudar..."); o que concorrentes postaram (inspiração).
   Gravar em `edit/shorts/<marca>/pauta-AAAA-MM/pesquisa.md`; `validar` + `snapshot`.
3. 6 ângulos (mix 4 carrosséis + 2 reels; 1 promoção), cada um com `[F#]`
   nos fatos que o justificam; não repetir tema usado nos últimos 3 meses.
   Rascunho em `edit/shorts/<marca>/pauta-AAAA-MM/PAUTA.md` (mesmo formato
   da existente).
4. `waiting_reply` nesse projeto: "pauta <mes> pronta — ver Docs no projeto
   `edit/shorts/<marca>/pauta-AAAA-MM`. `ok` / `mudar: ...`".
5. `ok` → copiar `pauta-AAAA-MM/PAUTA.md` para `edit/shorts/<marca>/PAUTA.md`
   (manter a antiga como `PAUTA-AAAA-MM-anterior.md`).
