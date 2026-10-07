# Vídeo de referência → conceitos de ad (interno; pedido `referencia`)

Entrada: `target = {origem, marca, nome, briefing}`. Projeto: `edit/shorts/<slug-do-nome>/` com `ui/`.
Referência é inspiração de **mecanismo** (ritmo, estrutura, gancho), nunca cópia
de texto, visual ou música. `conceitos.md` registra URL e autor.

1. `python ui/referencia.py baixar "<origem>" bruto/ref` → `bruto/ref/<slug>.mp4` + `.json`.
   Exit 2 com "baixe à mão" (URL com login, ex.: Instagram) → pedir pela fila (`waiting_reply`) que o
   usuário coloque o arquivo em `bruto/ref/` e passe o nome.
2. Transcrição (paga): `python ui/budget.py autorizar edit/shorts/<proj> elevenlabs_scribe <minutos>`
   → `python video-use/helpers/transcribe.py bruto/ref/<slug>.mp4 --edit-dir edit/shorts/<proj>`
   → `python ui/budget.py registrar ...`.
3. `python ui/referencia.py analisar bruto/ref/<slug>.mp4 edit/shorts/<proj> --transcript edit/shorts/<proj>/transcripts/<slug>.json`.
4. Ler `ref/sheet.png` (texto na tela, enquadramento, cor), `ref/analise.json`, o briefing e
   `edit/shorts/<marca>/PAUTA.md` → `conceitos.md` no formato do spec (tabela A/B/C: ideia ·
   mantém · muda · custo créditos/R$ via `ui/precos.json` · horas · exige IA · roteiro · animatic).
   Três ângulos fixos: **A** mesmo mecanismo, outro tema; **B** mesmo tema, outro mecanismo;
   **C** o contrário do original. Cada conceito → `roteiro-X.md` no formato de ads
   (`## Hook`, `## Cenas` numeradas com `sfx:` opcional, `## CTA`, `## Cues`). Fato citado →
   `pesquisa.md` + `python ui/pesquisa.py validar edit/shorts/<proj>/pesquisa.md --roteiro edit/shorts/<proj>/roteiro-X.md`.
5. `python ui/referencia.py animatic edit/shorts/<proj>/roteiro-A.md edit/shorts/<proj>/animatic-A.png --marca <marca>` (B, C idem).
6. `waiting_reply`: "referência analisada — ver Docs › conceitos.md, animatic-A/B/C.png.
   responda `A` | `B` | `C` | `ajuste: ...` | `produzir: A B`".
7. Escolhido: copiar `roteiro-X.md` → `roteiro.md`; `state.json.ref = {"conceitos": 3, "escolhido": "X", "produzidos": []}`
   (merge); seguir `Formatos/padrao-ads.md` a partir de "Técnica de produção".
   `produzir: A B` → cada um em `edit/shorts/<proj>/<X>/` com `ui/`, `state.json.ref.produzidos += [X]`.
