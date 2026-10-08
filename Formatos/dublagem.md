# Dublagem e tradução (sub-fluxo; etapa `dublagem` do projeto)

> Etapas: todo este fluxo é a etapa `dublagem` do projeto — `python ui/eventos.py etapa <proj> dublagem inicio`,
> `... espera --nota "<pergunta>"` em cada aprovação, `... inicio` ao retomar, `... fim --nota "<lang>: mp4/m4a/srt"`.
> Atualizar `state.json.dub.idiomas.<lang>.etapa` (merge) a cada passo: `frases → traducao → tts → encaixe → mix → pronto`.

Entrada: projeto pronto (export final em `Export/<nome> - horizontal.mp4` ou `final.mp4`), idioma `<lang>` (2 letras).
Voz: `state.json.dub.voz` do projeto, senão a da marca/`padrao` em `ui/vozes.json` (registrar a escolha:
`python ui/eventos.py decisao <proj> provedor "<nome da voz>" --etapa dublagem --motivo "<por quê>"`).
Glossário: `ui/glossario.json` (termo → tradução por idioma, ou "manter").

Escopo por formato:
- Longo/shorts: tudo (Fala + Tela + Montagem).
- Ads SEM narração: pular Fala e Voz (passos 1–4, 7–8 e a parte de áudio do 10); só Tela (5), folha
  `traducao` só com a seção Tela (6) e montagem do passo 11 (captura/montagem/SFX/trilha como em `padrao-ads.md`).
- Ads COM narração: o fluxo de fala precisa de transcrição/words do ad — fora do escopo por enquanto
  (dublar à mão; a parte de Tela segue como acima).

## Fala

1. Palavras na timeline do export (se ainda não existir):
   `python ui/clips.py words-out edit/<proj>/edl.json edit/<proj>/transcripts/<fonte>.json edit/<proj>/real_durations.json edit/<proj>/clips/words_out.json`.
2. `python ui/dublagem.py frases edit/<proj> <lang> --words edit/<proj>/clips/words_out.json`.
3. Traduzir (Claude): preencher `trad` de cada frase em `edit/<proj>/dub/<lang>/dublagem.json` (merge;
   preservar outros campos). Respeitar o glossário; não mudar o sentido de fatos com `[F#]`; caber no tempo.
4. `python ui/dublagem.py validar edit/<proj> <lang>` → corrigir até `ok` (erros = sem tradução/glossário;
   `longas` = encurtar a frase antes de gastar crédito). Frases com `"pular": true` não são validadas;
   "nenhuma frase para dublar" = todas puladas.

## Tela (se houver texto na tela)

5. Longo: `python ui/localiza.py extrair edit/animations/remotion/src --saida edit/<proj>/dub/<lang>/textos.json`
   (pasta = recursivo em .html/.htm/.tsx/.jsx; não depende de glob do shell).
   Ads (kit): `python ui/localiza.py extrair edit/shorts/<marca>/<tema>/cenas.json --saida edit/shorts/<marca>/<tema>/dub/<lang>/textos.json`
   (+ os `cenas/*.html` de cenas custom, se houver). Ads legados: o mesmo com `anim.html`.
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
   - `fNNN: ` com valor VAZIO = essa frase não é dublada: gravar `"pular": true` na frase (não só esvaziar
     `trad`). `validar` a ignora; `tts`/`encaixar`/`srt`/`words` pulam — vira SILÊNCIO na faixa dublada
     (a voz original não entra). `frases` preserva o `pular` ao reagrupar. Para voltar a dublar: remover `pular`.
   - `tNN: ` com valor VAZIO = manter o original na tela (`"trad": "="`).
   - Edição igual à proposta atual = nada a fazer.
   - Demais linhas (depois das edições) = comentário do usuário, não edição — ler e atender.
   Depois de aplicar, re-rodar `python ui/dublagem.py validar edit/<proj> <lang>`.

## Voz (paga)

7. `python ui/dublagem.py tts edit/<proj> <lang>` (valida, autoriza e registra no orçamento sozinho).
   Exit 1 com `"status": "invalido"` = `validar` falhou → corrigir (passo 4); `--forcar` só se o usuário mandar.
   Exit 2/3 → `waiting_reply` com motivo + estimativa; aprovado → repetir com `--aprovacao <id>`.
   Exit 4 = erro (HTTP/rede/disco), ver `"erro"`; o que já foi gerado está registrado — repetir só refaz o resto.
   `precos.json` assume ~1 crédito/caractere (o `autorizar` checa o saldo ElevenLabs).
   1ª rodada: `python ui/budget.py saldo` antes/depois → confirmar `creditos` por caractere em `ui/precos.json`.
8. `python ui/dublagem.py encaixar edit/<proj> <lang> --export "Export/<nome> - horizontal.mp4"`.
   `estouradas` → encurtar essas frases, `validar`, `tts` (só elas são refeitas), `encaixar` de novo.
   `desatualizadas` (áudio de outro texto/voz, ou sem tradução) não entram no voz.wav → rodar `tts` e `encaixar` de novo.
   Aceleração > 1.15× → `python ui/eventos.py decisao <proj> outro "acelerar fNNN" --etapa dublagem --motivo "..."`.

## Montagem

9. Longo com overlays traduzidos:
   - `python ui/localiza.py aplicar edit/<proj>/dub/<lang>/textos.json edit/animations/remotion/src edit/animations/remotion/src.<lang>`
     (pasta-destino só é substituída se foi criada pelo `aplicar` — marca `.localiza`; senão erro, nada apagado).
     `nao_encontrados` não vazio → abrir o fonte, ver como o texto aparece (quebra, entidade, prop), corrigir a
     chave ou os `contextos` em `textos.json` e rodar `aplicar` de novo até vazio.
   - Renderizar só as composições usadas no `edl.json` do projeto, de `edit/animations/remotion`, igual ao
     `render_some.ps1` mas com a entrada localizada e saída em `out_<lang>/` (alfa preservado):
     `npx remotion render src.<lang>/index.tsx <Composicao> out_<lang>/seq_<Composicao> --sequence --image-format=png --log=error`
     + `ffmpeg -y -v error -framerate 60 -i out_<lang>/seq_<Composicao>/element-%03d.png -c:v qtrle -pix_fmt argb out_<lang>/<Composicao>.mov`
     (apagar a `seq_` depois). `out_<lang>/` tem que ficar ao lado do `out/` que o `edl.json` referencia
     (`animations/remotion/out/X.mov` → `animations/remotion/out_<lang>/X.mov`, relativo ao projeto).
   - `python ui/dublagem.py edl edit/<proj> <lang>` (troca os overlays que têm versão em `out_<lang>/`).
   - `python ui/dublagem.py video edit/<proj> <lang>` → `dub/<lang>/video.mp4` (overlays localizados sobre
     `base_final.mp4`, sem refazer os cortes).
   - Projeto sem `base_final.mp4` (o `video` recusa): fallback
     `python video-use/helpers/render.py edit/<proj>/dub/<lang>/edl.json -o edit/<proj>/dub/<lang>/video.mp4 --no-subtitles`.
   - Depois: passo 10 com `--video edit/<proj>/dub/<lang>/video.mp4`.
10. `python ui/dublagem.py mixar edit/<proj> <lang> --export "Export/<nome> - horizontal.mp4" --nome "<nome>" [--video edit/<proj>/dub/<lang>/video.mp4]`
    → `Export/<nome> - <lang>.mp4`, `.m4a` (faixa extra do YouTube, upload manual) e `.srt`.
11. Ads (kit): `python ui/localiza.py aplicar edit/shorts/<marca>/<tema>/dub/<lang>/textos.json edit/shorts/<marca>/<tema>/cenas.json edit/shorts/<marca>/<tema>/cenas.<lang>.json`
    (`nao_encontrados` não vazio → como no passo 9). O end card precisa de `cta`, `tagline` e `url` escritos em
    `cenas.<lang>.json` (o `montar --lang` recusa sem eles; os padrões do tema são pt-BR) e `numero` formata pelo
    `<lang>` sozinho (`1.250` vs `1,250`). Cenas custom: `python ui/localiza.py aplicar <textos> edit/shorts/<marca>/<tema>/cenas
    edit/shorts/<marca>/<tema>/cenas.<lang>` (pasta → cópia com marca `.localiza`) e apontar cada `html` custom de
    `cenas.<lang>.json` para `cenas.<lang>/cNN.html`. Depois `python ui/motion.py montar <proj> --lang <lang>` (estouro de texto
    traduzido vira erro com o id da cena → encurtar a tradução); `python ui/motion.py render <proj> --lang <lang>` →
    `video.<lang>.mp4` + `cues.<lang>.json`; SFX/trilha como em `padrao-ads.md` → `…-<lang>.mp4`.
    Ads legados (`anim.html`): `aplicar` para `anim.<lang>.html` + `localiza.py checar` (comparar com o original) + captura antiga.

## Shorts dublados

12. `python ui/dublagem.py words edit/<proj> <lang>`;
    `python ui/clips.py edl edit/<proj>/clips/clips.json edit/<proj> "Export/<nome> - <lang>.mp4" --lang <lang>`;
    `python ui/clips.py render edit/<proj>/clips/clips.json edit/<proj> Export/shorts/<proj>/<lang> --lang <lang>`.
