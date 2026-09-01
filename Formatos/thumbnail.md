# Formato: Thumbnail YouTube

Recorte do apresentador sobre fundo chapado + tipografia pesada. 1280×720 PNG.
Sem geração de imagem por IA — a matéria-prima é sempre frame do próprio vídeo.

## Regra que manda em tudo

A thumbnail é julgada em **210 px de largura** (feed do celular), não em 1280.
Sempre renderizar uma versão reduzida e conferir. Se não lê a 210, não serve.
Na prática: no máximo 3–5 palavras, número grande quando existir, uma ideia só.

## Escolha do frame — medir, não olhar

Escolher a olho numa contact sheet **falha**: motion blur de webcam e olhar fora da câmera
não aparecem em miniatura. Foi rejeitado duas vezes assim. O jeito certo é pontuar o vídeo
inteiro (`score_frames.py`):

1. `ffmpeg -vf fps=1,scale=1280:-2` despeja ~1 frame por segundo
2. Haar `haarcascade_frontalface_default` — **se não detecta face frontal, ele não está
   olhando pra câmera**; é o filtro que resolve o "olhando pro nada"
3. Haar `haarcascade_eye` dentro da caixa do rosto — confirma olhos abertos
4. Variância do Laplaciano na **metade superior do rosto** = foco/motion blur.
   Medir só no rosto, não no quadro: fundo liso derruba a métrica global
5. `score = nitidez × (1 + 0,5 × olhos) × (tamanho do rosto / 300)`
6. Espaçar os picks em ≥ 8 s, senão saem 20 frames do mesmo segundo

Depois, `pick_best.py` refina no sub-segundo: o dump é a 1 fps, e a diferença entre
`344,00s` e `344,45s` foi de 39 para 99 de nitidez — o frame certo está entre as amostras.

Só então olhar as ~12 melhores e escolher por expressão.

**Silhueta fechada ganha.** Mão aberta e braço esticado invadem a coluna de texto —
punho fechado, mão perto do rosto ou braços baixos recortam muito melhor. Se o recorte
sair largo demais, cortar a lateral que entraria no texto antes de compor.

OpenCV: `CascadeClassifier` não existe na 5.x. Fixar `opencv-python==4.10.0.84`.

## Recorte (rembg)

`rembg` não roda no Python 3.14 (sem wheel de `onnxruntime`). Ambiente isolado:

```
uv venv --python 3.12 edit/.venv-thumb
uv pip install --python edit/.venv-thumb/Scripts/python.exe rembg onnxruntime pillow
```

Venv criado pelo uv não tem `pip` — usar `uv pip install`, nunca `python -m pip`.

Modelo: `u2net_human_seg` (específico pra pessoa, melhor que o `u2net` genérico).
`alpha_matting=True` dá borda de cabelo mais limpa mas o solver falha em alguns frames
("Cholesky decomposition failed") — envolver em `try/except` e cair pra máscara simples.
Depois do recorte, `getbbox()` + crop pra remover o vazio, senão o layout não ancora.

Resto de cadeira e suporte de headset costumam vir junto. Em fundo escuro somem — não vale
a pena limpar à mão.

Webcam é mole e o recorte ainda é ampliado na thumbnail: aplicar `UnsharpMask(radius=2.2,
percent=125, threshold=3)` **só no RGB**, remontando o alpha original depois — nitidez na
imagem sem serrilhar a borda do recorte.

## Composição

Ordem de camadas (errar isso apaga a pessoa):

```
1. fundo            linear-gradient(135deg, #0B0E16, #141C2E 58%, #0B0E16)
2. glow de acento   radial azul atrás do corpo, canto inferior direito
3. scrim            gradiente escuro só no lado do texto, até ~58% da largura
4. pessoa           por CIMA do scrim
5. tipografia
```

Camiseta preta em fundo quase preto some. Correções obrigatórias no recorte:
`brightness(1.20) contrast(1.08) saturate(1.08)` + `drop-shadow(0 0 34px rgba(77,141,255,0.55))`
como luz de contorno.

**Tipografia:** `Segoe UI Black`, peso 900, `letter-spacing` negativo. Número/valor em
`#4D8DFF`, resto em branco, régua de acento entre os blocos. Coluna de texto: `left 68`,
largura 620. Pessoa ancorada à direita, `height 762`, `right -40`.

## Variações

Gerar 3 com ângulos de gancho diferentes, para testar:
- número/perda ("R$ 0 em 2 semanas")
- afirmação + virada ("Criei um SaaS / ninguém usou")
- resultado + postura ("0 assinantes / e eu faria de novo")

## Entrega

`Export/<nome do vídeo> - thumb 1.png` … `thumb 3.png`, junto do MP4.
Limite do YouTube: 2 MB por arquivo (as saídas ficam ~1 MB).

## Armadilha de encoding

`Set-Content` do PowerShell reescreve UTF-8 errado e vira mojibake em texto com acento
("ninguém" → "ninguÃ©m") — e isso vai parar renderizado na imagem. Editar `.tsx` com a
ferramenta de edição, nunca com redirecionamento de PowerShell.
