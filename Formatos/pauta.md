# Pauta mensal com dados (interno; pedido `pauta`)

Entrada: `target = {marca, mes}`. Saída: `edit/shorts/<marca>/PAUTA.md` novo
(mesmo formato do existente) + `edit/shorts/<marca>/pauta-AAAA-MM/pesquisa.md`.

1. Ler a `PAUTA.md` anterior (temas já usados, o que rendeu) e
   `justmind/divulgacao/CRONOGRAMA.md` §10 (regras editoriais).
2. Pesquisa (WebSearch): calendário acadêmico/provas do mês; mudanças de lei
   e súmulas do mês (planalto, STF, STJ); perguntas frequentes do público
   (fóruns, "como estudar..."); o que concorrentes postaram (inspiração).
   Gravar em `pauta-AAAA-MM/pesquisa.md`; `validar` + `snapshot`.
3. 6 ângulos (mix 4 carrosséis + 2 reels; 1 promoção), cada um com `[F#]`
   nos fatos que o justificam; não repetir tema usado nos últimos 3 meses.
4. `waiting_reply`: "pauta <mes> pronta — ver Docs (projeto `edit/shorts/<marca>`). `ok` / `mudar: ...`".
5. `ok` → substituir a `PAUTA.md` (manter a antiga como `PAUTA-AAAA-MM.md`).
