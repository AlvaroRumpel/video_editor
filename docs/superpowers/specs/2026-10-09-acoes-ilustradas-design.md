# Ações ilustradas e frase conectada — design (subprojeto 11)

Data: 2026-10-09. Origem: feedback do usuário sobre o 001 (Batavia) do canal
Kryvantis (`D:\Projetos\dark_videos`) e preparação do 002 (Crippen). Depende de:
motion documental (subprojeto 10: `motion/kit/doc.js`, `narrado.py`, `alinhar.py`).

## Problema

1. Episódios e shorts não podem parecer slideshow: quando a fala descreve uma ação
   ou um diálogo, deve aparecer uma ilustração animada disso, não só câmera sobre imagem.
2. O beat `palavras` mostra palavras-chave soltas ("ORDERS · SAME · ISLAND"). O usuário
   quer **frase que ligue palavra a palavra**, não palavras isoladas.

## Decisões do usuário (2026-10-09)

- Abordagem: **rigs SVG feitos à mão no kit** (descartados pacotes Lottie e imagem/vídeo de IA:
  estilo destoa do canal, licença incerta, custo).
- Acabamento **mais refinado** que o protótipo mostrado (ver "Estilo").
- Não é cena completa: são **ações específicas**, vinhetas curtas sobre o fundo que a cena já
  tem (mapa, imagem de arquivo ou escuro).
- Custo zero (regra do canal).

## A. Frase conectada (beat `palavras` + campo `frase`)

```json
{"em": "ordenou", "faz": "palavras", "frase": "ordenou que fossem para a mesma ilha", "risco": "mesma"}
```

- `frase` é trecho **literal e contíguo** do texto da cena (mesma regra de casamento de
  `palavras`, sem pular palavra). Cada palavra entra no tempo em que é dita; a frase
  fica inteira na tela até o próximo beat do slot `centro`.
- Layout: quebra em até 2 linhas, fonte automática (110 px até 4 palavras, descendo até 64 px);
  frase com mais de 10 palavras é erro (usar `citacao`).
- `risco` e `destaque` (lista de palavras em cor de acento) marcam só as palavras-chave.
- `palavras` com lista continua válido (001 não muda). Validador **avisa** quando uma lista
  tem menos de 4 palavras: "palavras soltas, prefira `frase`".
- Regra de direção em `Formatos/dark-historia.md`: texto na tela é frase da fala.

## B. Beat `acao` (vinheta ilustrada)

```json
{"em": "reconheceu", "faz": "acao", "modelo": "olha", "ator": "kendall", "alvo": "casal", "lado": "esq"}
{"em": "telegrafou", "faz": "acao", "modelo": "telegrama", "texto": {"pt": "Suspeitos a bordo"}}
```

- Entra na palavra `em`, dura o tempo do modelo (padrão 2,5 s; máx. 8 s) e sai sozinha.
  Conta como beat para `RITMO_MAX` (6 s sem beat).
- Posição: `lado` (`esq` | `dir` | `centro`, padrão `dir`), `escala` (0,6 a 1,2). Ocupa o slot
  `acao`; nunca cobre o slot `painel` (contador). Pode coexistir com `camera`, `data`, `rotulo`.
- Fica sobre o fundo atual com um véu escuro suave e vinheta de borda; o fundo não é
  substituído.

### Vocabulário de modelos (v1, vocabulário fechado)

| `modelo` | campos | o que mostra |
|---|---|---|
| `olha` | `ator`, `alvo` | ator vira a cabeça e a linha de visão se desenha até o alvo; "!" sobre ele |
| `fala` | `ator`, `alvo`, `texto` (opcional) | dois atores frente a frente, balão do falante com ícone ou texto curto |
| `telegrama` | `texto` | pulso sai da antena, envelope cruza a tela, linhas de sinal |
| `le` | `ator`, `texto` | ator lê uma folha/carta; linhas do texto aparecem no papel |
| `aponta` | `ator`, `alvo` | ator estende o braço e aponta |
| `sobe_a_bordo` | `ator` | ator sobe uma escada/prancha até o convés |
| `anda` | `ator`, `de`, `para` | ator caminha entre dois lados da vinheta |

Não existe modelo de violência (arma, golpe, sangue, corpo). A regra do 001 vale: violência
nunca vira beat ilustrativo. Modelo novo = mudança no kit, não no episódio.

### Atores

Definidos uma vez no `episodio.json` e reutilizados em todas as cenas:

```json
"atores": {
  "kendall": {"traje": "capitao", "nome": {"pt": "Capitão Kendall"}},
  "dew": {"traje": "inspetor"},
  "casal": {"traje": ["medico", "menino"]}
}
```

- `traje`: `capitao`, `inspetor`, `medico`, `secretaria`, `menino`, `marinheiro`, `civil`
  (silhueta + chapéu/acessório). Lista = grupo de figuras lado a lado.
- Rótulo opcional (`nome`) aparece como letreiro junto à figura na primeira entrada.
- Figuras são silhuetas, sem rosto: nomes e papéis vêm da fala e do rótulo.

### Estilo (mais refinado que o protótipo)

- Tinta sobre fundo escuro, na linguagem das gravuras do 001: contorno creme, preenchimento
  quase preto, **hachura** (traços paralelos) nas dobras e sombras, linha com variação leve
  de espessura e tremor de ±0,6 px a 12 fps (como o flicker do kit), cor de acento só no
  elemento narrativo (envelope, "!", linha de visão).
- Proporções de figura mais naturais (cabeça 1/7,5, ombros e quadril marcados) e poses por
  rig: torso, cabeça, braço (2 segmentos) ×2, pernas ×2. Poses interpoladas por GSAP com
  ease de "peso" (acelera e assenta), sem quicar.
- Respiração sutil (0,5 px) enquanto parado; nada de bounce.
- Sombra no chão e leve reflexo na água quando há mar.

### Implementação

- Novo arquivo `motion/kit/acoes.js`, carregado depois de `doc.js` quando o cenas.json traz
  beats `acao`. Registra o beat no mapa de beats do `doc.js` e o slot `acao` em `SLOT`.
- Cada modelo é uma função `(ctx, b, atores) -> instante em que termina`, usando só
  `ctx.c.tl` (GSAP) e `KIT.cue` para SFX (reaproveita `tique`, `whoosh`, `impacto`;
  `telegrama` ganha o sfx `morse`, sintetizado como os demais).
- Tudo que depende do tempo fica em `tl`/`KIT.pintor`, nunca `onUpdate` (regra do kit).
- `narrado.py`: `FAZ["acao"] = ("modelo",)`; validação do modelo, dos atores e dos campos por
  modelo; `resolver_beats` já resolve `s` por `em`. `frase` resolve `ts` por palavra como em
  `palavras`.
- Folha de QC (`motion.py folha`): inclui um quadro por `acao` (no meio da duração).

### Fora de escopo

Sincronia labial, rostos, imagens ou vídeo de IA, pacotes Lottie, animação 3D, shorts 9:16
(mesmo kit, mas layout vertical fica para depois), mudar o 001 já publicado.

## Testes

- Unitários (`test_narrado.py`): `frase` válida e inválida (não contígua, > 10 palavras),
  aviso de palavras soltas, `acao` com modelo/ator inexistente, campo faltando, `acao` de
  violência rejeitada por não existir, `RITMO_MAX` contando `acao`.
- Golden (`test_motion_golden.py`): quadro de cada modelo com ator de teste.
- Render do 002 como teste de integração real (Gate 2).

## Decisões em aberto

Nenhuma bloqueante. A paleta e as silhuetas finais são ajustadas na folha de QC do 002.
