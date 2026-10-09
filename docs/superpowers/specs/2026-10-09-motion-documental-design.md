# Motion documental sincronizado à fala — design (subprojeto 10)

Data: 2026-10-09. Origem: Gate 2 do episódio 001 (Batavia) do canal
Kryvantis (`D:\Projetos\dark_videos`). Depende de: `narrado.py` (episodio.json →
TTS → kit), kit de motion (`motion/kit`, subprojeto 9), `audio.py`
(`mix_trilha`, `mix_sfx`, `cues.json`), tema `dark-historia`.

## Problema

O rascunho do 001 (8:57) ficou monótono: cada cena é **uma** imagem com Ken
Burns ou **um** cartão de texto, e o motor não sabe quando cada palavra é dita
(a narração é por cena). Nada reage à fala. Também faltam abertura e
encerramento de vídeo de YouTube.

## Spike que motivou (2026-10-09, descartável)

Dois testes de 12,6 s com a mesma fala (c01), animados à mão em HyperFrames
com tempos por palavra do faster-whisper (`small`, CPU, int8):

- **A — documentário dark:** câmera viva sobre gravura, data/número surgindo na
  palavra, régua de km, grão/vinheta/flicker.
- **B — mistura doc + dados:** mapa de época (Mar di India, 1650, CC0) com
  câmera, rota desenhada, ping + etiqueta, painel contador com 1 ponto por
  pessoa, palavras cinéticas com risco, transições ligadas (mergulho no ponto →
  gravura; recuo gravura → mapa), linha com contador de km.

Resultado: alinhamento por palavra funciona (números saem em dígitos: "300",
"3 mil"); render de 12,6 s em ~1 min. Armadilhas achadas: `fromTo` do GSAP
renderiza o estado inicial em t=0 (`immediateRender: false` em tudo que
começa depois de 0); `faster_whisper.decode_audio` quebra com o `av` instalado
(decodificar com ffmpeg e passar o array).

## Decisões do usuário

- Estilo: **B (mistura doc + dados)** — base documental com motion explicativo
  em dados, mapas e momentos-chave.
- Sincronia: **caminho 3** — beats por frase por padrão, gatilho na palavra
  exata quando o beat pedir.
- Abertura: **cold open + vinheta curta** (~4 s) com título do episódio.
- Encerramento: fala final + **tela final de 20 s** para elementos do YouTube.
- Som: **trilha + SFX grátis** (trilha da YouTube Audio Library baixada pelo
  usuário; SFX sintetizados).
- Custo: zero (vale a regra do canal "sem custo até ter retorno").

## Fluxo

```
roteiro (Gate 1) → tts → alinhar → direção → visuais → render → som → Gate 2
```

Gate 1 continua só texto + fontes. A direção visual é avaliada no Gate 2.

### Alinhar (`ui/alinhar.py`, novo)

- Entrada: `<proj>/<lang>/audio/cNN.mp3` e o `texto.<lang>` de cada cena.
- Decodifica com ffmpeg (16 kHz mono s16le) → faster-whisper `small`,
  `word_timestamps=True`, idioma do episódio.
- **Casamento roteiro × transcrição:** tokeniza os dois (minúsculas, sem
  pontuação, sem acento); normaliza números por extenso do roteiro para dígitos
  (`trezentas` → `300`, `três mil` → `3 mil`); `difflib.SequenceMatcher` nos
  tokens; palavras do roteiro sem par herdam tempo interpolado entre vizinhas
  casadas. Saída: tempo de **cada palavra do roteiro**, não da transcrição.
- Grava `<proj>/<lang>/palavras.json`:
  `{"cNN": [{"w": "trezentas", "i": 7, "s": 4.34, "e": 4.66}, ...]}`
  (tempos relativos ao início do áudio da cena; `i` = índice do token no texto).
- Cache por hash do mp3: só realinha cena cujo áudio mudou.
- CLI: `python ui/narrado.py alinhar <proj> [--lang pt]`.
- Dependência: `faster-whisper` em `requirements.txt`; primeira execução baixa
  o modelo (~460 MB). Sem rede depois.

### Direção (dados no `episodio.json`)

Feita pela sessão depois do Gate 1. Campos novos (todos opcionais; cena sem
`beats` renderiza como hoje):

```json
{
 "mapa": {"src": "assets/mapa.jpg", "fonte_url": "...", "licenca": "CC0", "credito": "...",
          "pontos": {"cabo": [120, 2920], "abrolhos": [2636, 2196], "batavia": [2554, 1540]}},
 "vinheta_apos": "c03",
 "cenas": [
  {"id": "c01", "texto": {...}, "fontes": [...],
   "fundo": {"tipo": "mapa"},
   "beats": [
     {"em": "junho", "faz": "data", "t": {"pt": "Junho 1629"}},
     {"faz": "rota", "de": "cabo", "para": "abrolhos", "navio": true},
     {"em": "trezentas", "faz": "contador", "valor": 300, "legenda": {"pt": "sobreviventes"}, "pontos": true},
     {"em": "ilhas", "faz": "palavras", "palavras": ["ilhas", "sem", "água"], "risco": "água"}
   ]}
 ]
}
```

- `pontos` do mapa em pixels do arquivo original.
- `fundo`: `{"tipo": "mapa"}` | `{"tipo": "imagem", "src": ..., "fonte_url", "licenca", "credito"}`
  (mesmas regras de licença de `visual.arquivo`) | `{"tipo": "escuro"}`.
  Cena com `beats` e sem `fundo` usa o `visual` atual como fundo.
- `em`: palavra do texto da cena que dispara o beat. Ausente → início da frase
  seguinte à do beat anterior (primeiro beat → início da fala).
  Palavra repetida no texto: `"em": "água#2"` (2ª ocorrência).
- Textos visíveis nos beats seguem o padrão `{"pt": ...}` (dublagem futura).

### Vocabulário de beats

| `faz` | campos | efeito |
|---|---|---|
| `camera` | mapa: `para` (ponto), `zoom`; imagem: `area` [x,y,w,h] em frações | movimento principal da câmera |
| `rota` | `de`, `para`, `via` (pontos opcionais), `navio` (bool), `km` (número) | desenha caminho; navio anda; régua conta até `km` |
| `ponto` | `ponto`, `rotulo` | ping vermelho + etiqueta |
| `contador` | `valor`, `prefixo`, `sufixo`, `legenda`, `pontos` (bool, ≤ 500) | painel com número contando; 1 ponto por unidade |
| `data` | `t` | carimbo (mês/ano) no canto |
| `rotulo` | `nome`, `papel` | letreiro de pessoa ou lugar |
| `palavras` | `palavras` (lista), `risco` (palavra) | cada palavra entra no tempo em que é dita |
| `citacao` | `t`, `autor` | aspas + autor sobre fundo escurecido |
| `lista` | `itens` [{`t`, `em`}] | cada item entra na sua palavra |
| `linha_tempo` | `marcos` [{`data`, `t`, `em`}] | datas numa linha, marcador anda |
| `inserto` | `src` + licença | troca a imagem de fundo dentro da cena |

Câmera nunca parada: entre beats, deriva lenta contínua (escala e posição).

### Transições entre cenas

Automáticas, com `"saida": {"transicao": ...}` para forçar:
- mapa → imagem: **mergulho** (zoom no último ponto citado → clarão → imagem
  entra de escala 1.7 para 1.15).
- imagem → mapa: **recuo** (imagem encolhe e some; mapa abre do ponto).
- demais: **corte com whoosh** ou **dissolve** curto (0,3 s).

### Ritmo (validador)

- Erro: palavra de `em` inexistente no texto; ponto inexistente no `mapa`;
  `faz` desconhecido; campos obrigatórios faltando.
- Trecho > 6 s de fala sem beat nem troca de cena: aviso no rascunho, erro no
  render final.
- Contenção (true crime): sem beat ilustrativo de violência; mortes como dado.

### Camada fixa

Grão animado (determinístico, 12 trocas/s), vinheta radial, flicker leve. Cores
do tema: dourado (`acento`) para dados/rotas, vermelho (`risco`) para
perigo/pontos. Textos com sombra forte para ler sobre gravura clara.

## Abertura e encerramento (tema `dark-historia`)

- **Cold open:** cenas até `vinheta_apos`.
- **Vinheta (~4 s, molde fixo):** selo K (`canal/identidade/avatar.png` como
  base visual) carimba sobre textura de papel com impacto e poeira; anéis
  vermelhos se desenham; "KRYVANTIS" datilografado; título curto do episódio
  (`titulo_curto.<lang>`, fallback `thumb_texto`) em Fraunces itálico; saída
  por mergulho no selo.
- **Chamada final:** última cena com beats (selo pulsa em "inscreva";
  nomes das fontes do `pesquisa.md` passam em "referências").
- **Tela final (20 s, sem fala):** fundo escuro com o mapa desfocado; dois
  quadros-guia nas posições dos elementos de tela final do YouTube (inscrever +
  próximo vídeo); "Próxima história" + tagline; trilha sobe e faz fade.

## Som

- **Trilha:** `dark_videos/canal/trilhas/` (fora do git) + `canal/trilhas.json`
  (`arquivo`, `licenca`, `atribuicao`). Atribuição exigida entra na descrição.
  Mix com `audio.mix_trilha` (ducking sob a voz); nível sobe na vinheta e na
  tela final; fade out no fim.
- **SFX:** `motion/sfx/*.wav` sintetizados com ffmpeg uma vez (whoosh, impacto,
  ping, tique, máquina de escrever, carimbo, clarão) por `ui/audio.py sfx-kit`.
  Cada beat/transição emite cue no `cues.json` (mecanismo existente); mix com
  `audio.mix_sfx`, volume discreto.
- **Loudness final:** −14 LUFS integrado (YouTube), true peak ≤ −1 dBTP.

## Componentes e arquivos

| arquivo | papel |
|---|---|
| `ui/alinhar.py` (novo) | faster-whisper + casamento texto × transcrição → `palavras.json` |
| `ui/narrado.py` | CLI `alinhar`; valida `mapa`/`fundo`/`beats`/ritmo; resolve `em` → tempo absoluto; insere vinheta e tela final; etapa `som` |
| `motion/kit/doc.js` (novo) | fundo com câmera (mapa/imagem/escuro), beats, transições ligadas, camada fixa; registra cues |
| `motion/temas/dark-historia.json` + `motion/kit/temas/dark-historia/` | moldes da vinheta e da tela final, textura de papel, selo |
| `ui/audio.py` | `sfx-kit` (síntese), envelope da trilha por trecho, loudness final |
| `motion/sfx/` (novo) | SFX sintetizados |
| `dark_videos/Formatos/dark-historia.md` | receita com as etapas novas |

`kit.js` atual segue intacto para reels/ads; `doc.js` é carregado só quando o
`cenas.json` traz `"modo": "doc"`.

## Erros

- Alinhamento com < 70% das palavras casadas numa cena → erro com o trecho
  (provável TTS truncado ou texto alterado depois do TTS).
- Modelo whisper ausente e sem rede → erro claro com o comando de download.
- Trilha ausente → render segue sem trilha, com aviso (não bloqueia rascunho;
  bloqueia final).
- Cena cujo texto mudou depois do alinhamento (hash) → exige `alinhar` de novo.

## Testes

- `test_alinhar.py`: casamento com números por extenso × dígitos, palavras
  omitidas pelo whisper, palavras repetidas (`#2`), interpolação; whisper
  substituído por stub (sem modelo nos testes).
- `test_narrado.py`: validação de beats/mapa/fundo, regra dos 6 s, resolução
  `em` → tempo absoluto, inserção de vinheta/tela final.
- `test_motion_golden.py`: episódio mínimo com mapa + 4 beats + transição de
  mergulho; quadros-chave comparados com referência.
- `test_audio.py`: SFX sintetizados existem e têm duração esperada; trilha
  abaixa sob voz; loudness final −14 ± 1 LUFS.
- Aceite: 001 Batavia re-renderizado com direção completa → Gate 2 do usuário.

## Fora de escopo

- Cenário 3D, partículas pesadas, vídeo IA.
- Mapas vetoriais modernos (só mapa de época por imagem).
- Dublagem EN do motion (campos já localizáveis; fluxo fica para o @kryvantis_en).
- Edição dos elementos de tela final no YouTube Studio (manual do usuário).
