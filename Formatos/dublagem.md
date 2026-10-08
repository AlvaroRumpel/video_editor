# Dublagem e tradução (sub-fluxo; etapa `dublagem` do projeto)

> Etapas: todo este fluxo é a etapa `dublagem` do projeto — `python ui/eventos.py etapa <proj> dublagem inicio`,
> `... espera --nota "<pergunta>"` em cada aprovação, `... inicio` ao retomar, `... fim --nota "<lang>: mp4/m4a/srt"`.
> Atualizar `state.json.dub.idiomas.<lang>.etapa` (merge) a cada passo: `frases → traducao → tts → encaixe → mix → pronto`.

Entrada: projeto pronto (export final em `Export/<nome> - horizontal.mp4` ou `final.mp4`), idioma `<lang>` (2 letras).
Voz: `state.json.dub.voz` do projeto, senão a da marca/`padrao` em `ui/vozes.json` (registrar a escolha:
`python ui/eventos.py decisao <proj> provedor "<nome da voz>" --etapa dublagem --motivo "<por quê>"`).
Glossário: `ui/glossario.json` (termo → tradução por idioma, ou "manter").

## Fala

1. Palavras na timeline do export (se ainda não existir):
   `python ui/clips.py words-out edit/<proj>/edl.json edit/<proj>/transcripts/<fonte>.json edit/<proj>/real_durations.json edit/<proj>/clips/words_out.json`.
2. `python ui/dublagem.py frases edit/<proj> <lang> --words edit/<proj>/clips/words_out.json`.
3. Traduzir (Claude): preencher `trad` de cada frase em `edit/<proj>/dub/<lang>/dublagem.json` (merge;
   preservar outros campos). Respeitar o glossário; não mudar o sentido de fatos com `[F#]`; caber no tempo.
4. `python ui/dublagem.py validar edit/<proj> <lang>` → corrigir até `ok` (erros = sem tradução/glossário;
   `longas` = encurtar a frase antes de gastar crédito).

## Tela (se houver texto na tela)

5. Longo: `python ui/localiza.py extrair edit/animations/remotion/src/*.tsx --saida edit/<proj>/dub/<lang>/textos.json`.
   Ads: `python ui/localiza.py extrair edit/shorts/<marca>/<tema>/anim.html --saida edit/shorts/<marca>/<tema>/dub/<lang>/textos.json`.
   Traduzir (Claude): preencher `trad`; `"="` para manter (marca, números de lei, código que a heurística pegou).
   `extrair` grava `contextos` por texto (`texto`/`atributo`/`script` no html; `jsx`/`literal` no tsx) — o `aplicar`
   só troca o texto nesses contextos. Não são extraídos: textos montados dinamicamente em JS (concatenação,
   template, array de letras — não são literais) e rótulos/props JSX de uma palavra só (ex.: `label="Prazo"`,
   `{'Prazo'}`; literal só entra com espaço). Conferir o fonte e, se aparecem na tela, acrescentar à mão em
   `textos.json` (chave = texto original; `{"id": "tNN", "trad": ..., "arquivos": [...], "contextos": [...]}` com o
   contexto certo — `literal` para prop/string no tsx, `script` para string JS no html).

## Aprovação

6. `waiting_reply` com `"folha": "traducao"` e `"lang": "<lang>"`: "tradução <lang> pronta — revise na aba Aprovação".
   Resposta `ok` ou `ok` + linhas `fNNN: <texto>` / `tNN: <texto>` → aplicar nos arquivos, re-`validar`.
   Gramática da resposta:
   - Linhas que casam `^[ft]\d+: ` (ou `^[ft]\d+:$`, se o espaço final foi aparado) são edições: o texto depois
     de `: ` substitui a tradução (`trad`) daquele id — `fNNN` em `dublagem.json`, `tNN` em `textos.json`.
   - `fNNN: ` com valor VAZIO = essa frase não é dublada: deixar `trad` vazio (e limpar `audio`/`hash` se já
     havia áudio); `tts`/`encaixar`/`srt` pulam a frase. O `validar` vai listá-la como "sem tradução" — esperado,
     ignorar só esses ids.
   - `tNN: ` com valor VAZIO = manter o original na tela (`"trad": "="`).
   - Edição igual à proposta atual = nada a fazer.
   - Demais linhas (depois das edições) = comentário do usuário, não edição — ler e atender.
   Depois de aplicar, re-rodar `python ui/dublagem.py validar edit/<proj> <lang>`.

## Voz (paga)

7. `python ui/dublagem.py tts edit/<proj> <lang>` (autoriza e registra no orçamento sozinho). Exit 2/3 →
   `waiting_reply` com motivo + estimativa; aprovado → repetir com `--aprovacao <id>`.
   1ª rodada: `python ui/budget.py saldo` antes/depois → `creditos` por caractere em `ui/precos.json`.
8. `python ui/dublagem.py encaixar edit/<proj> <lang> --export "Export/<nome> - horizontal.mp4"`.
   `estouradas` → encurtar essas frases, `validar`, `tts` (só elas são refeitas), `encaixar` de novo.
   Aceleração > 1.15× → `python ui/eventos.py decisao <proj> outro "acelerar fNNN" --etapa dublagem --motivo "..."`.

## Montagem

9. Longo com overlays traduzidos: `python ui/localiza.py aplicar edit/<proj>/dub/<lang>/textos.json edit/animations/remotion/src edit/animations/remotion/src.<lang>`;
   renderizar só as composições usadas no `edl.json` com entrada `src.<lang>/index.tsx` para
   `edit/animations/remotion/out_<lang>/`; `python ui/dublagem.py edl edit/<proj> <lang>`;
   `python video-use/helpers/render.py edit/<proj>/dub/<lang>/edl.json -o edit/<proj>/dub/<lang>/video.mp4 --no-subtitles`.
10. `python ui/dublagem.py mixar edit/<proj> <lang> --export "Export/<nome> - horizontal.mp4" --nome "<nome>" [--video edit/<proj>/dub/<lang>/video.mp4]`
    → `Export/<nome> - <lang>.mp4`, `.m4a` (faixa extra do YouTube, upload manual) e `.srt`.
11. Ads: `python ui/localiza.py aplicar edit/shorts/<marca>/<tema>/dub/<lang>/textos.json edit/shorts/<marca>/<tema>/anim.html edit/shorts/<marca>/<tema>/anim.<lang>.html`;
    `python ui/localiza.py checar edit/shorts/<marca>/<tema>/anim.<lang>.html` → corrigir estouros (encurtar texto);
    rodar o `checar` também no `anim.html` original: só contam os estouros que aparecem na cópia e não no original
    (o original já pode acusar estados de animação como estouro).
    captura/montagem/SFX/trilha como em `padrao-ads.md` usando `anim.<lang>.html` → `…-<lang>.mp4`.

## Shorts dublados

12. `python ui/dublagem.py words edit/<proj> <lang>`;
    `python ui/clips.py edl edit/<proj>/clips/clips.json edit/<proj> "Export/<nome> - <lang>.mp4" --lang <lang>`;
    `python ui/clips.py render edit/<proj>/clips/clips.json edit/<proj> Export/shorts/<proj>/<lang> --lang <lang>`.
