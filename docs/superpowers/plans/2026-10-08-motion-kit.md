# Kit de motion (HyperFrames) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reels/ads 9:16 montados a partir de um `cenas.json` por um kit HyperFrames versionado (`motion/`) e uma CLI `ui/motion.py` (`montar | render | folha`).

**Architecture:** `ui/motion.py` valida o `cenas.json`, resolve papéis pelo tema da marca e gera `<proj>/motion/index.html`. É uma composição HyperFrames única: cada cena é um `.clip` da raiz, e o kit (`motion/kit/kit.js` + GSAP vendorizado) monta a timeline no browser a partir de `window.__KIT_DADOS`. Uma passada no Chromium (Playwright) lê duração, eventos de som e medidas de layout. Depois disso, `montar` grava os tempos reais na raiz e o `cues.json`. `render` chama o `hyperframes` travado em `motion/node_modules`, confere o resultado no ffprobe e grava o progresso no `state.json`.

**Tech Stack:** Python 3.14 (stdlib + Playwright, já usado em `ui/localiza.py`), pytest, ffmpeg/ffprobe, Node 24 + `hyperframes@0.8.141` + `gsap@3.14.2`.

**Spec:** `docs/superpowers/specs/2026-10-08-motion-kit-design.md`

## Global Constraints

- Saída: 1080x1920, 30 fps, H.264 `yuv420p` range tv, sem áudio. Encode final com `-crf 18`.
- Só aspecto `"9:16"` na v1.
- Safe area (px @1080x1920): x 80..1000, y 180..1660.
- Tempo automático: segurar o estado final por ≥ 0,8 s (end card ≥ 1,2 s). Easings nunca lineares, exceto a barra de progresso.
- hyperframes travado em `0.8.141` e gsap em `3.14.2`, com versões exatas no `motion/package.json`. Nunca usar `npx hyperframes@latest`.
- Render offline: GSAP e fontes ficam locais em `motion/kit/`. Nada de CDN nem Google Fonts.
- Fontes com família própria (`K Fraunces`, `K Inter`, `K Archivo`, `K Plex Mono`), porque o HyperFrames remapeia nomes conhecidos em silêncio.
- Env do render: `HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`, `HF_CLI_TELEMETRY_DISABLED=1`, `HYPERFRAMES_SKIP_SKILLS=1`.
- Pastas geradas (`<proj>/motion[.<lang>]/`) só podem ser apagadas se tiverem o arquivo marcador `.motion`.
- PT-BR em mensagens e docs. Sem travessão em copy (regra do repo).
- CLI no padrão de `ui/`: stdout é um JSON; `{"erro": ...}` + exit 1 em falha; `montar` com `ok: false` → exit 1.
- Testes rodam da raiz do repo: `python -m pytest ui/test_motion.py -q`.

## Ajustes ao spec (decididos neste plano; T8 atualiza o spec)

1. A composição é **única**: as cenas são `.clip` da raiz, e não subcomposições em arquivos separados. Tipos e transições ficam em `motion/kit/kit.js`, então não existem as pastas `cenas/` e `transicoes/`.
2. `estilo` passa a ser `display|punch|corpo|mono`. `serif` virou `display`, porque a Campeio não tem serifa.
3. `cor` passa a ser `tinta|acento|sobre`. `destaque` era fundo de marca-texto, não cor de texto.
4. No tema, `fixos` = `{wordmark, wordmark_fonte, barra, grao}`. A pill passa a ser da cena `tela` (`label`). `transicao_padrao` vira `{transicao, dur}`.
5. `--lang xx` substitui `--cenas`. As saídas viram `motion.<lang>/`, `cues.<lang>.json` e `video.<lang>.mp4`.
6. `--rascunho` usa a qualidade `draft` do HyperFrames, ainda em 1080x1920, porque `--resolution` só aumenta.
7. `dur` padrão da cena `tela`: 3 s para imagem; para vídeo, a duração do arquivo.

## Review Focus

1. **HyperFrames suprimindo callbacks no seek.** Se acontecer, `pintores` (grão, contador, brilho da íris) congelam. O esperado é contador e grão mudando entre frames. Coberto em T6: dois frames do contador precisam diferir.
2. **`<video>` dentro de cena `tela`.** O frame final da cena precisa mostrar o clipe, não preto. Coberto em T6 pela variação de luma na região da moldura.
3. **Pasta `motion/` do usuário** sem o marcador. O `montar` deve recusar com erro e nunca apagar. Coberto em T3.
4. **Texto traduzido mais longo** (`cenas.en.json`). Deve virar erro de estouro no `montar --lang`, e não um vídeo cortado. Coberto em T3 (linha longa) e T7 (aplicar gera o json que o montar lê).
5. **`state.json` escrito pela UI durante o render.** As chaves alheias (`aprovacoes`) precisam ser preservadas. Coberto em T5.

---

### Task 1: Esqueleto `motion/` (deps travadas, GSAP, fontes, ícone)

**Files:**
- Create: `motion/package.json`, `motion/package-lock.json` (gerado), `motion/kit/vendor/gsap.min.js`, `motion/kit/fonts/*.ttf`, `motion/kit/fonts/OFL-*.txt`, `motion/temas/campeio/icone.png`
- Create: `ui/motion.py` (esqueleto: constantes)
- Modify: `.gitignore`
- Test: `ui/test_motion.py`

**Interfaces:**
- Produces: `motion.ROOT: Path`, `motion.MOTION: Path` (= `ROOT/"motion"`), `motion.FPS = 30`, `motion.W = 1080`, `motion.H = 1920`, `motion.SAFE = (80, 180, 1000, 1660)`.

- [ ] **Step 1: Write the failing test**

`ui/test_motion.py`:
```python
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import motion


def test_kit_tem_vendor_fontes_e_icone():
    k = motion.MOTION / "kit"
    for f in ("vendor/gsap.min.js", "fonts/Fraunces.ttf", "fonts/Fraunces-Italic.ttf", "fonts/Inter.ttf",
              "fonts/Archivo.ttf", "fonts/IBMPlexMono-Medium.ttf", "fonts/IBMPlexMono-SemiBold.ttf"):
        assert (k / f).stat().st_size > 10_000, f
    assert (motion.MOTION / "temas" / "campeio" / "icone.png").stat().st_size > 1_000
    pkg = json.loads((motion.MOTION / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"] == {"gsap": "3.14.2", "hyperframes": "0.8.141"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest ui/test_motion.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'motion'`

- [ ] **Step 3: Create the skeleton**

`ui/motion.py`:
```python
"""Kit de motion (HyperFrames): cenas.json → composição → vídeo dos reels/ads.

montar: valida, gera <proj>/motion[.<lang>]/ (kit copiado + index.html), mede no
Chromium (duração, sons, layout) e grava cues[.<lang>].json.
render: hyperframes de motion/node_modules → video[.<lang>].mp4 conferido no ffprobe.
folha: contact sheet de QC a partir do vídeo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = pipeline.ROOT
MOTION = ROOT / "motion"
FPS = 30
W, H = 1080, 1920
SAFE = (80, 180, 1000, 1660)  # x0, y0, x1, y1
```

`motion/package.json`:
```json
{
  "name": "video-editor-motion",
  "private": true,
  "description": "Kit de motion dos reels/ads (HyperFrames). Rodar `npm ci` uma vez.",
  "dependencies": {
    "gsap": "3.14.2",
    "hyperframes": "0.8.141"
  }
}
```

Run (Git Bash, from repo root):
```bash
cd motion && HYPERFRAMES_SKIP_SKILLS=1 HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 npm install --save-exact && cd ..
mkdir -p motion/kit/vendor motion/kit/fonts motion/temas/campeio
cp motion/node_modules/gsap/dist/gsap.min.js motion/kit/vendor/gsap.min.js
B=https://raw.githubusercontent.com/google/fonts/main/ofl
curl -sSfL -o motion/kit/fonts/Fraunces.ttf "$B/fraunces/Fraunces%5BSOFT,WONK,opsz,wght%5D.ttf"
curl -sSfL -o motion/kit/fonts/Fraunces-Italic.ttf "$B/fraunces/Fraunces-Italic%5BSOFT,WONK,opsz,wght%5D.ttf"
curl -sSfL -o motion/kit/fonts/Inter.ttf "$B/inter/Inter%5Bopsz,wght%5D.ttf"
curl -sSfL -o motion/kit/fonts/Archivo.ttf "$B/archivo/Archivo%5Bwdth,wght%5D.ttf"
curl -sSfL -o motion/kit/fonts/IBMPlexMono-Medium.ttf "$B/ibmplexmono/IBMPlexMono-Medium.ttf"
curl -sSfL -o motion/kit/fonts/IBMPlexMono-SemiBold.ttf "$B/ibmplexmono/IBMPlexMono-SemiBold.ttf"
for f in fraunces inter archivo ibmplexmono; do curl -sSfL -o "motion/kit/fonts/OFL-$f.txt" "$B/$f/OFL.txt"; done
cp edit/shorts/campeio/icon-campeio.png motion/temas/campeio/icone.png
```
Se alguma URL de fonte der 404: `gh api repos/google/fonts/contents/ofl/<familia> --jq '.[].name'` e usar o nome atual.

Append to `.gitignore`:
```
# Kit de motion: dependências Node (npm ci em motion/)
motion/node_modules/
```

The `package.json` must end with `"gsap": "3.14.2"` and `"hyperframes": "0.8.141"`, with no `^`. Fix it by hand if npm added one.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add .gitignore motion/package.json motion/package-lock.json motion/kit motion/temas ui/motion.py ui/test_motion.py
git commit -m "feat(motion): esqueleto do kit (deps travadas, gsap e fontes locais)"
```

---

### Task 2: Temas, validação e resolução de papéis

**Files:**
- Create: `motion/temas/anotus.json`, `motion/temas/campeio.json`
- Modify: `ui/motion.py`
- Test: `ui/test_motion.py`

**Interfaces:**
- Consumes: `motion.MOTION`.
- Produces:
  - `carregar_tema(marca: str, motion_dir: Path = MOTION) -> dict` (ValueError)
  - `validar(dados, proj: Path) -> list[dict]` (`[{"id", "motivo"}]`, `id` = id da cena, `"raiz"` ou `"#n"`)
  - `resolver(dados: dict, tema: dict, proj: Path) -> dict` (cópia com defaults)
  - `_css_vars(tema) -> str`
  - `_tema_js(tema) -> dict`
  - `_dentro(proj, rel) -> Path | None`
  - `_duracao(p: Path) -> float`
  - constantes `TIPOS, FUNDOS, ESTILOS, ANIMS, CORES, DESTAQUES, TRANSICOES, MOLDURAS, MARCADORES, EXT_IMG, EXT_VID`
- Cena resolvida (consumida pelo kit em T3/T4):
  - toda cena: `fundo`, `fixos`, `saida` (`{transicao, dur}` com dur alinhado a quadro, ou `None` na última) e `dur` (número ou `None`);
  - `frase.linhas[]`: `estilo, anim, cor, destaque, em`;
  - `numero`: `de, formato, prefixo, sufixo, legenda, cor, estilo`;
  - `lista`: `titulo, marcador, cor`;
  - `tela`: `video: bool, moldura, label, kenburns, dur`;
  - `endcard`: `cta, tagline, url, cor`.

- [ ] **Step 1: Write the failing tests**

Append to `ui/test_motion.py`:
```python
def _cenas(**extra):
    d = {"marca": "anotus", "aspecto": "9:16", "cenas": [
        {"id": "c01", "tipo": "frase", "linhas": [
            {"t": "Pare de", "estilo": "punch"},
            {"t": "decorar.", "estilo": "display", "anim": "letras", "destaque": ["marca-texto", "risco"]}]},
        {"id": "c02", "tipo": "endcard"}]}
    d.update(extra)
    return d


def test_temas_carregam_e_diferem():
    a, c = motion.carregar_tema("anotus"), motion.carregar_tema("campeio")
    assert a["cores"]["acento"] != c["cores"]["acento"]


def test_tema_inexistente_e_marca_invalida():
    with pytest.raises(ValueError, match="tema não existe"):
        motion.carregar_tema("nada")
    with pytest.raises(ValueError, match="marca inválida"):
        motion.carregar_tema("../x")


def test_tema_sem_chave(tmp_path):
    (tmp_path / "temas").mkdir()
    t = json.loads((motion.MOTION / "temas" / "anotus.json").read_text(encoding="utf-8"))
    del t["cores"]["acento"]
    (tmp_path / "temas" / "x.json").write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(ValueError, match="falta cores.acento"):
        motion.carregar_tema("x", tmp_path)


def test_validar_ok(tmp_path):
    assert motion.validar(_cenas(), tmp_path) == []


@pytest.mark.parametrize("mut, cid, trecho", [
    (lambda d: d["cenas"][0].update(tipo="xpto"), "c01", "tipo desconhecido"),
    (lambda d: d["cenas"][1].update(id="c01"), "c01", "id duplicado"),
    (lambda d: d["cenas"][0].update(id="cena1"), "#0", "id inválido"),
    (lambda d: d["cenas"][0]["linhas"][1].update(destaque=["neon"]), "c01", "destaque inválido"),
    (lambda d: d["cenas"][0]["linhas"][0].update(estilo="serif"), "c01", "estilo inválido"),
    (lambda d: d["cenas"][0]["linhas"][0].update(t=" "), "c01", "falta t"),
    (lambda d: d["cenas"].append({"id": "c03", "tipo": "custom", "html": "x.html"}), "c03", "html não encontrado"),
    (lambda d: d["cenas"].append({"id": "c03", "tipo": "custom", "html": "x.html"}), "c03", "custom precisa de dur"),
    (lambda d: d["cenas"][1].update(saida={"transicao": "fade", "dur": 0.3}), "c02", "última cena"),
    (lambda d: d["cenas"][0].update(saida={"transicao": "zoom", "dur": 0.3}), "c01", "saida precisa"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "tela", "arquivo": "../fora.png"}), "c09", "arquivo não encontrado"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "lista", "itens": ["a"] * 7}), "c09", "no máximo 6"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "numero", "valor": "mil"}), "c09", "valor precisa"),
    (lambda d: d.update(aspecto="16:9"), "raiz", "aspecto"),
])
def test_validar_erros(tmp_path, mut, cid, trecho):
    d = _cenas()
    mut(d)
    erros = motion.validar(d, tmp_path)
    assert any(e["id"] == cid and trecho in e["motivo"] for e in erros), erros


def test_validar_tela_fora_do_projeto(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (tmp_path / "fora.png").write_bytes(b"x")
    d = _cenas()
    d["cenas"].insert(1, {"id": "c09", "tipo": "tela", "arquivo": "../fora.png"})
    assert any(e["id"] == "c09" for e in motion.validar(d, proj))


def test_resolver_defaults_e_temas(tmp_path):
    d = _cenas()
    a = motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)
    c = motion.resolver(d, motion.carregar_tema("campeio"), tmp_path)
    l0 = a["cenas"][0]["linhas"][0]
    assert (l0["anim"], l0["cor"], l0["destaque"], l0["em"]) == ("palavras", "tinta", [], None)
    assert a["cenas"][0]["saida"] == {"transicao": "fade", "dur": 0.3}
    assert a["cenas"][1]["saida"] is None and a["cenas"][1]["fixos"] is False
    assert a["cenas"][1]["fundo"] == "marca" and a["cenas"][1]["cor"] == "sobre"
    assert a["cenas"][1]["cta"] != c["cenas"][1]["cta"]
    assert d["cenas"][0]["linhas"][0] == {"t": "Pare de", "estilo": "punch"}  # não muta a entrada


def test_resolver_saida_alinhada_a_quadro(tmp_path):
    d = _cenas()
    d["cenas"][0]["saida"] = {"transicao": "iris", "dur": 0.47}
    r = motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)
    assert r["cenas"][0]["saida"]["dur"] == round(14 / 30, 6)


def test_resolver_numero_mono_por_tema(tmp_path):
    d = {"marca": "x", "cenas": [{"id": "c01", "tipo": "numero", "valor": 1250}]}
    assert motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)["cenas"][0]["estilo"] == "display"
    assert motion.resolver(d, motion.carregar_tema("campeio"), tmp_path)["cenas"][0]["estilo"] == "mono"


def test_css_vars_e_tema_js():
    css = motion._css_vars(motion.carregar_tema("campeio"))
    assert "--k-fundo-marca:linear-gradient" in css and '--k-mono-familia:"K Plex Mono"' in css
    tj = motion._tema_js(motion.carregar_tema("campeio"))
    assert tj["assinatura"] == {"tipo": "icone", "src": "kit/tema/icone.png"} and tj["barra"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ui/test_motion.py -q`
Expected: FAIL with `AttributeError: module 'motion' has no attribute 'carregar_tema'`

- [ ] **Step 3: Write the themes**

`motion/temas/anotus.json`:
```json
{
  "cores": {
    "tinta": "#2B215C", "acento": "#D4A017", "sobre": "#FFFFFF",
    "marca_texto": "rgba(255,214,90,.55)", "risco": "#4A3D8F", "manchas": "#B9B3E6",
    "fundo": {"claro": "#F3F2FA", "escuro": "#2B215C", "marca": "#4A3D8F"}
  },
  "fontes": {
    "display": {"familia": "K Fraunces", "peso": 700, "estilo": "italic"},
    "punch": {"familia": "K Inter", "peso": 800},
    "corpo": {"familia": "K Inter", "peso": 500},
    "mono": {"familia": "K Inter", "peso": 700}
  },
  "assinatura": {"tipo": "ponto"},
  "fixos": {"wordmark": "Anotus.", "wordmark_fonte": "display", "barra": false, "grao": 0.10},
  "endcard": {"marca": "Anotus", "tagline": "Seu segundo cérebro jurídico", "cta": "Teste grátis", "url": "link na bio"},
  "pill": {"borda": "#B9B3E6", "texto": "#4A3D8F"},
  "transicao_padrao": {"transicao": "fade", "dur": 0.3},
  "regras": {"numero_mono": false}
}
```

`motion/temas/campeio.json`:
```json
{
  "cores": {
    "tinta": "#23281E", "acento": "#E8833A", "sobre": "#FFFFFF",
    "marca_texto": "rgba(232,131,58,.30)", "risco": "#A32D14", "manchas": "#A8C08F",
    "fundo": {"claro": "#F5F3EB", "escuro": "#1A2016",
              "marca": "linear-gradient(168deg, #243420 0%, #2F4429 46%, #3D5435 100%)"}
  },
  "fontes": {
    "display": {"familia": "K Archivo", "peso": 900},
    "punch": {"familia": "K Archivo", "peso": 800},
    "corpo": {"familia": "K Archivo", "peso": 500},
    "mono": {"familia": "K Plex Mono", "peso": 600}
  },
  "assinatura": {"tipo": "icone", "arquivo": "campeio/icone.png"},
  "fixos": {"wordmark": "Campeio", "wordmark_fonte": "punch", "barra": true, "grao": 0.06},
  "endcard": {"marca": "Campeio", "tagline": "O campeio na palma da mão.", "cta": "Teste grátis por 30 dias", "url": "campeio.com"},
  "pill": {"borda": "#E9EDE2", "texto": "#3D5435"},
  "transicao_padrao": {"transicao": "fade", "dur": 0.3},
  "regras": {"numero_mono": true}
}
```

- [ ] **Step 4: Implement in `ui/motion.py`**

Update the imports at the top to:
```python
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
```
Append after the constants:
```python
TIPOS = ("frase", "numero", "lista", "tela", "endcard", "custom")
FUNDOS = ("claro", "escuro", "marca")
ESTILOS = ("display", "punch", "corpo", "mono")
ANIMS = ("palavras", "letras", "mascara", "fade")
CORES = ("tinta", "acento", "sobre")
DESTAQUES = ("marca-texto", "risco", "assinatura")
TRANSICOES = ("fade", "wipe", "iris")
MOLDURAS = ("celular", "browser", "nenhuma")
MARCADORES = ("numero", "assinatura", "check")
EXT_IMG = (".png", ".jpg", ".jpeg")
EXT_VID = (".mp4",)
ID_RE = re.compile(r"c\d{2,}")
MARCA_RE = re.compile(r"[a-z0-9-]+")
FUNDO_PADRAO = {"frase": "claro", "numero": "claro", "lista": "claro", "tela": "claro",
                "endcard": "marca", "custom": "claro"}
TEMA_CHAVES = (
    "cores.tinta", "cores.acento", "cores.sobre", "cores.marca_texto", "cores.risco", "cores.manchas",
    "cores.fundo.claro", "cores.fundo.escuro", "cores.fundo.marca",
    "fontes.display.familia", "fontes.display.peso", "fontes.punch.familia", "fontes.punch.peso",
    "fontes.corpo.familia", "fontes.corpo.peso", "fontes.mono.familia", "fontes.mono.peso",
    "assinatura.tipo", "fixos.wordmark", "fixos.wordmark_fonte", "fixos.barra", "fixos.grao",
    "endcard.marca", "endcard.tagline", "endcard.cta", "endcard.url", "pill.borda", "pill.texto",
    "transicao_padrao.transicao", "transicao_padrao.dur", "regras.numero_mono")


def _pega(d, caminho: str):
    for k in caminho.split("."):
        if not isinstance(d, dict) or k not in d:
            raise KeyError(caminho)
        d = d[k]
    return d


def carregar_tema(marca, motion_dir: Path = MOTION) -> dict:
    if not isinstance(marca, str) or not MARCA_RE.fullmatch(marca):
        raise ValueError(f"marca inválida: {marca!r}")
    p = motion_dir / "temas" / f"{marca}.json"
    if not p.is_file():
        raise ValueError(f"tema não existe: {p}")
    tema = json.loads(p.read_text(encoding="utf-8"))
    for ch in TEMA_CHAVES:
        try:
            _pega(tema, ch)
        except KeyError:
            raise ValueError(f"tema {marca}: falta {ch}") from None
    if tema["assinatura"]["tipo"] == "icone" and \
            not (motion_dir / "temas" / tema["assinatura"].get("arquivo", "-")).is_file():
        raise ValueError(f"tema {marca}: arquivo do ícone da assinatura não existe")
    return tema


def _dentro(proj: Path, rel) -> Path | None:
    """Arquivo relativo ao projeto, existente e sem escapar dele."""
    if not isinstance(rel, str) or not rel:
        return None
    p = (Path(proj) / rel).resolve()
    return p if p.is_relative_to(Path(proj).resolve()) and p.is_file() else None


def _num(v, minimo=0.0) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= minimo


def _str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _cor(c, e):
    if "cor" in c and c["cor"] not in CORES:
        e(f"cor inválida: {c['cor']!r}")


def _v_frase(c, proj, e):
    linhas = c.get("linhas")
    if not isinstance(linhas, list) or not linhas:
        return e("linhas vazio")
    for k, ln in enumerate(linhas, 1):
        if not isinstance(ln, dict) or not _str(ln.get("t")):
            e(f"linha {k}: falta t")
            continue
        if ln.get("estilo", "punch") not in ESTILOS:
            e(f"linha {k}: estilo inválido: {ln['estilo']!r}")
        if ln.get("anim", "palavras") not in ANIMS:
            e(f"linha {k}: anim inválida: {ln['anim']!r}")
        if ln.get("cor", "tinta") not in CORES:
            e(f"linha {k}: cor inválida: {ln['cor']!r}")
        d = ln.get("destaque", [])
        if not isinstance(d, list) or any(x not in DESTAQUES for x in d) or len(set(d)) != len(d):
            e(f"linha {k}: destaque inválido: {d!r}")
        if "em" in ln and not _num(ln["em"]):
            e(f"linha {k}: em precisa ser número >= 0")


def _v_numero(c, proj, e):
    if not _num(c.get("valor"), float("-inf")):
        e("valor precisa ser número")
    if "de" in c and not _num(c["de"], float("-inf")):
        e("de precisa ser número")
    for k in ("formato", "prefixo", "sufixo", "legenda"):
        if k in c and not isinstance(c[k], str):
            e(f"{k} precisa ser texto")
    _cor(c, e)


def _v_lista(c, proj, e):
    itens = c.get("itens")
    if not isinstance(itens, list) or not itens or not all(_str(x) for x in itens):
        e("itens precisa ser lista de textos")
    elif len(itens) > 6:
        e("no máximo 6 itens")
    if c.get("marcador", "numero") not in MARCADORES:
        e(f"marcador inválido: {c['marcador']!r}")
    if "titulo" in c and not isinstance(c["titulo"], str):
        e("titulo precisa ser texto")
    _cor(c, e)


def _v_tela(c, proj, e):
    p = _dentro(proj, c.get("arquivo"))
    if p is None:
        e(f"arquivo não encontrado no projeto: {c.get('arquivo')!r}")
    elif p.suffix.lower() not in EXT_IMG + EXT_VID:
        e(f"formato não suportado: {p.suffix} (png, jpg, mp4)")
    if c.get("moldura", "celular") not in MOLDURAS:
        e(f"moldura inválida: {c['moldura']!r}")
    if "label" in c and not isinstance(c["label"], str):
        e("label precisa ser texto")
    if "kenburns" in c and not isinstance(c["kenburns"], bool):
        e("kenburns precisa ser true/false")


def _v_endcard(c, proj, e):
    for k in ("cta", "tagline", "url"):
        if k in c and not _str(c[k]):
            e(f"{k} precisa ser texto")
    _cor(c, e)


def _v_custom(c, proj, e):
    p = _dentro(proj, c.get("html"))
    if p is None or p.suffix.lower() not in (".html", ".htm"):
        e(f"html não encontrado no projeto: {c.get('html')!r}")
    if "dur" not in c:
        e("custom precisa de dur")


VALIDA_TIPO = {"frase": _v_frase, "numero": _v_numero, "lista": _v_lista, "tela": _v_tela,
               "endcard": _v_endcard, "custom": _v_custom}


def validar(dados, proj: Path) -> list[dict]:
    if not isinstance(dados, dict):
        return [{"id": "raiz", "motivo": "cenas.json não é um objeto"}]
    erros = []

    def e(i, m):
        erros.append({"id": i, "motivo": m})

    if dados.get("aspecto", "9:16") != "9:16":
        e("raiz", "aspecto: só 9:16 na v1")
    cenas = dados.get("cenas")
    if not isinstance(cenas, list) or not cenas:
        e("raiz", "cenas vazio")
        return erros
    vistos = set()
    for n, c in enumerate(cenas):
        if not isinstance(c, dict):
            e(f"#{n}", "cena não é objeto")
            continue
        i = c.get("id")
        if not isinstance(i, str) or not ID_RE.fullmatch(i):
            e(f"#{n}", f"id inválido: {i!r} (use cNN)")
            continue
        if i in vistos:
            e(i, "id duplicado")
        vistos.add(i)
        tipo = c.get("tipo")
        if tipo not in TIPOS:
            e(i, f"tipo desconhecido: {tipo!r}")
            continue
        if "fundo" in c and c["fundo"] not in FUNDOS:
            e(i, f"fundo inválido: {c['fundo']!r}")
        if "dur" in c and not (_num(c["dur"]) and c["dur"] > 0):
            e(i, "dur precisa ser número > 0")
        if "fixos" in c and not isinstance(c["fixos"], bool):
            e(i, "fixos precisa ser true/false")
        if "saida" in c:
            s = c["saida"]
            if n == len(cenas) - 1:
                e(i, "última cena não tem saida")
            elif not isinstance(s, dict) or s.get("transicao") not in TRANSICOES \
                    or not (_num(s.get("dur")) and 0 < s["dur"] <= 2):
                e(i, "saida precisa de transicao (fade|wipe|iris) e dur em (0, 2]")
        VALIDA_TIPO[tipo](c, proj, lambda m, i=i: e(i, m))
    return erros


def _duracao(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out.strip()), 3)


def _quadro(s: float) -> float:
    return round(round(s * FPS) / FPS, 6)


def resolver(dados: dict, tema: dict, proj: Path) -> dict:
    d = copy.deepcopy(dados)
    cenas = d["cenas"]
    for n, c in enumerate(cenas):
        t = c["tipo"]
        c.setdefault("fundo", FUNDO_PADRAO[t])
        c.setdefault("fixos", t != "endcard")
        cor = "tinta" if c["fundo"] == "claro" else "sobre"
        if n < len(cenas) - 1:
            s = c.get("saida") or tema["transicao_padrao"]
            c["saida"] = {"transicao": s["transicao"], "dur": _quadro(s["dur"])}
        else:
            c["saida"] = None
        if t == "frase":
            for ln in c["linhas"]:
                ln.setdefault("estilo", "punch")
                ln.setdefault("anim", "palavras")
                ln.setdefault("cor", cor)
                ln.setdefault("destaque", [])
                ln.setdefault("em", None)
        elif t == "numero":
            for k, v in (("de", 0), ("formato", "pt-BR"), ("prefixo", ""), ("sufixo", ""), ("legenda", ""), ("cor", cor)):
                c.setdefault(k, v)
            c["estilo"] = "mono" if tema["regras"]["numero_mono"] else "display"
        elif t == "lista":
            for k, v in (("titulo", ""), ("marcador", "numero"), ("cor", cor)):
                c.setdefault(k, v)
        elif t == "tela":
            p = _dentro(proj, c["arquivo"])
            c["video"] = p.suffix.lower() in EXT_VID
            c.setdefault("moldura", "celular")
            c.setdefault("label", "")
            c.setdefault("kenburns", not c["video"])
            c.setdefault("dur", _duracao(p) if c["video"] else 3.0)
        elif t == "endcard":
            for k in ("cta", "tagline", "url"):
                c.setdefault(k, tema["endcard"][k])
            c.setdefault("cor", cor)
        c.setdefault("dur", None)
    return d


def _css_vars(tema: dict) -> str:
    c, f = tema["cores"], tema["fontes"]
    v = {"tinta": c["tinta"], "acento": c["acento"], "sobre": c["sobre"], "marca-texto": c["marca_texto"],
         "risco": c["risco"], "manchas": c["manchas"], "fundo-claro": c["fundo"]["claro"],
         "fundo-escuro": c["fundo"]["escuro"], "fundo-marca": c["fundo"]["marca"],
         "pill-borda": tema["pill"]["borda"], "pill-texto": tema["pill"]["texto"]}
    for est in ESTILOS:
        v[f"{est}-familia"] = f'"{f[est]["familia"]}"'
        v[f"{est}-peso"] = str(f[est]["peso"])
        v[f"{est}-estilo"] = f[est].get("estilo", "normal")
    return ":root{" + "".join(f"--k-{k}:{val};" for k, val in v.items()) + "}"


def _tema_js(tema: dict) -> dict:
    a = tema["assinatura"]
    return {"acento": tema["cores"]["acento"],
            "assinatura": {"tipo": a["tipo"],
                           "src": f"kit/tema/{Path(a['arquivo']).name}" if a["tipo"] == "icone" else None},
            "wordmark": tema["fixos"]["wordmark"], "wordmark_fonte": tema["fixos"]["wordmark_fonte"],
            "barra": bool(tema["fixos"]["barra"]), "grao": float(tema["fixos"]["grao"]),
            "endcard_marca": tema["endcard"]["marca"], "url": tema["endcard"]["url"]}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add motion/temas ui/motion.py ui/test_motion.py
git commit -m "feat(motion): temas Anotus/Campeio, validação e resolução de papéis"
```

---

### Task 3: Kit núcleo + `montar` (frase, endcard, fade, fixos, cues, layout)

**Files:**
- Create: `motion/kit/kit.css`, `motion/kit/kit.js`
- Modify: `ui/motion.py`
- Test: `ui/test_motion.py`

**Interfaces:**
- Consumes: everything from T2.
- Produces:
  - Python: `montar(proj: Path, lang: str | None = None, motion_dir: Path = MOTION) -> dict`. `ok` → `{"ok": True, "duracao", "cenas": [{"id", "ini", "dur"}], "erros": [], "index", "cues"}`; não-ok → `{"ok": False, "erros": [{"id", "motivo"}]}`. Escreve `<proj>/motion[.<lang>]/{index.html, tempos.json, .motion, kit/, midia/}` e `<proj>/cues[.<lang>].json`. `tempos.json` = `{"duracao", "cenas": [{"id", "ini", "dur", "min", "saida"}]}`.
  - Helpers: `_html(d, tema, customs, tempos)`, `_preparar(comp, proj, d, tema, motion_dir)`, `_medir(index) -> dict`, `_lang(lang) -> str`.
  - JS: `window.KIT = {custom(fn), montar(), F, FPS}`; `window.__kit = {duracao, cenas, cues, erros, ir(t)}`; `window.__timelines.main`. O contexto `c` passado aos tipos e ao custom tem `{tl, layer, el, tema, ini, t0, F, cue, C}`, e `c.C` = `{palavras, letras, mascara, fade, marcaTexto, risco, assinatura}` (T4 acrescenta `contador`, `kenBurns`). As funções `TIPOS[tipo](c, cena)` devolvem o instante absoluto (s) em que a última entrada termina.

- [ ] **Step 1: Write the failing tests**

Append to `ui/test_motion.py`:
```python
pw = pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="sem playwright")


def _proj(tmp_path, dados, nome="proj"):
    p = tmp_path / nome
    p.mkdir(exist_ok=True)
    (p / "cenas.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return p


@pw
def test_montar_gera_composicao_tempos_e_cues(tmp_path):
    p = _proj(tmp_path, _cenas())
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    html = (p / "motion" / "index.html").read_text(encoding="utf-8")
    assert html.count('class="clip cena"') == 2 and "cdn." not in html
    c1, c2 = r["cenas"]
    assert c1["ini"] == 0 and abs(c2["ini"] - (c1["dur"] - 0.3)) < 1e-3   # sobreposição do fade
    assert abs(r["duracao"] - (c2["ini"] + c2["dur"])) < 0.04
    assert f'data-duration="{r["duracao"]:.3f}"' in html
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"rise", "whoosh-reveal", "sting-endcard", "pop-dourado", "click-pill"} <= sons
    assert (p / "motion" / ".motion").is_file() and (p / "motion" / "kit" / "vendor" / "gsap.min.js").is_file()


@pw
def test_montar_campeio_mesmo_json(tmp_path):
    d = _cenas(marca="campeio")
    r = motion.montar(_proj(tmp_path, d))
    assert r["ok"], r["erros"]


@pw
def test_montar_dur_abaixo_do_minimo(tmp_path):
    d = _cenas()
    d["cenas"][0]["dur"] = 0.5
    r = motion.montar(_proj(tmp_path, d))
    assert not r["ok"] and any(e["id"] == "c01" and "abaixo do mínimo" in e["motivo"] for e in r["erros"])


@pw
def test_montar_linha_longa_estoura(tmp_path):
    d = _cenas()
    d["cenas"][0]["linhas"][1]["t"] = "inconstitucionalissimamente"
    r = motion.montar(_proj(tmp_path, d))
    assert not r["ok"]
    assert any(e["id"] == "c01" and ("estoura" in e["motivo"] or "safe area" in e["motivo"]) for e in r["erros"])


@pw
def test_montar_fonte_fallback(tmp_path):
    md = tmp_path / "m"
    shutil.copytree(motion.MOTION / "kit", md / "kit")
    (md / "temas").mkdir()
    t = json.loads((motion.MOTION / "temas" / "anotus.json").read_text(encoding="utf-8"))
    t["fontes"]["display"]["familia"] = "K Inexistente"
    (md / "temas" / "anotus.json").write_text(json.dumps(t), encoding="utf-8")
    r = motion.montar(_proj(tmp_path, _cenas()), motion_dir=md)
    assert any("fonte em fallback (K Inexistente)" in e["motivo"] for e in r["erros"]), r


def test_montar_nao_apaga_pasta_alheia(tmp_path):
    p = _proj(tmp_path, _cenas())
    (p / "motion").mkdir()
    (p / "motion" / "meu.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não foi criado"):
        motion.montar(p)
    assert (p / "motion" / "meu.txt").exists()


def test_montar_erro_de_schema_nao_gera_nada(tmp_path):
    d = _cenas()
    d["cenas"][0]["tipo"] = "xpto"
    p = _proj(tmp_path, d)
    r = motion.montar(p)
    assert not r["ok"] and r["erros"][0]["id"] == "c01" and not (p / "motion").exists()


def test_montar_lang_invalido(tmp_path):
    with pytest.raises(ValueError, match="lang inválido"):
        motion.montar(_proj(tmp_path, _cenas()), "../x")


@pw
def test_montar_lang_usa_pastas_proprias(tmp_path):
    p = _proj(tmp_path, _cenas())
    d = _cenas()
    d["cenas"][0]["linhas"][0]["t"] = "Stop"
    (p / "cenas.en.json").write_text(json.dumps(d), encoding="utf-8")
    assert motion.montar(p)["ok"] and motion.montar(p, "en")["ok"]
    assert (p / "motion.en" / "index.html").exists() and (p / "cues.en.json").exists() and (p / "cues.json").exists()
    assert '"Stop"' in (p / "motion.en" / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ui/test_motion.py -q -k montar`
Expected: FAIL with `AttributeError: module 'motion' has no attribute 'montar'`

- [ ] **Step 3: Write `motion/kit/kit.css`**

```css
/* Kit de motion: base visual. Fontes OFL em fonts/ (licenças em fonts/OFL-*.txt).
   Famílias com nome próprio ("K ...") porque o HyperFrames remapeia nomes conhecidos. */
@font-face { font-family: "K Fraunces"; src: url("fonts/Fraunces.ttf"); font-weight: 100 900; font-style: normal; }
@font-face { font-family: "K Fraunces"; src: url("fonts/Fraunces-Italic.ttf"); font-weight: 100 900; font-style: italic; }
@font-face { font-family: "K Inter"; src: url("fonts/Inter.ttf"); font-weight: 100 900; }
@font-face { font-family: "K Archivo"; src: url("fonts/Archivo.ttf"); font-weight: 100 900; }
@font-face { font-family: "K Plex Mono"; src: url("fonts/IBMPlexMono-Medium.ttf"); font-weight: 500; }
@font-face { font-family: "K Plex Mono"; src: url("fonts/IBMPlexMono-SemiBold.ttf"); font-weight: 600; }

* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000; }
#root { position: relative; width: 1080px; height: 1920px; overflow: hidden; }

.cena { position: absolute; inset: 0; overflow: hidden; visibility: hidden; }
.k-fundo { position: absolute; inset: 0; overflow: hidden; }
.k-mancha { position: absolute; width: 900px; height: 900px; border-radius: 50%;
  background: radial-gradient(closest-side, var(--k-manchas), transparent); opacity: .6; }
.k-conteudo { position: absolute; left: 80px; top: 180px; width: 920px; height: 1480px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; text-align: center; }

.k-display { font-family: var(--k-display-familia); font-weight: var(--k-display-peso); font-style: var(--k-display-estilo); font-size: 210px; }
.k-punch { font-family: var(--k-punch-familia); font-weight: var(--k-punch-peso); font-style: var(--k-punch-estilo); font-size: 96px; letter-spacing: -0.02em; }
.k-corpo { font-family: var(--k-corpo-familia); font-weight: var(--k-corpo-peso); font-style: var(--k-corpo-estilo); font-size: 56px; }
.k-mono { font-family: var(--k-mono-familia); font-weight: var(--k-mono-peso); font-style: var(--k-mono-estilo); font-size: 48px; }
.k-cor-tinta { color: var(--k-tinta); }
.k-cor-acento { color: var(--k-acento); }
.k-cor-sobre { color: var(--k-sobre); }

.k-linha { white-space: nowrap; line-height: 1.08; }
.k-bloco { position: relative; display: inline-block; z-index: 0; }
.k-txt { display: inline-block; }
.k-mascara { display: inline-block; overflow: hidden; vertical-align: bottom; padding: 0 .04em; }
.k-mascara > span, .k-letra { display: inline-block; }
.k-com-marca::after { content: ""; position: absolute; left: -0.06em; right: -0.06em; bottom: 0.1em; height: 0.42em;
  background: var(--k-marca-texto); transform: scaleX(var(--k-marca, 0)); transform-origin: left center; z-index: -1; }
.k-risco { position: absolute; left: -0.02em; right: -0.02em; top: 56%; height: 0.05em; min-height: 8px;
  border-radius: 99px; background: var(--k-risco); transform: scaleX(0); transform-origin: left center; }
.k-ponto { display: inline-block; width: .15em; height: .15em; border-radius: 50%; background: var(--k-acento); margin-left: .04em; }
.k-icone { display: inline-block; height: .55em; width: auto; margin-left: .08em; border-radius: 22%; vertical-align: baseline; }

.k-numero { font-size: 260px; line-height: 1; font-variant-numeric: tabular-nums; }
.k-lista { align-items: stretch; text-align: left; gap: 28px; }
.k-lista-titulo { text-align: center; margin-bottom: 18px; }
.k-item { display: flex; align-items: baseline; gap: 28px; white-space: normal; line-height: 1.2; }
.k-marcador { flex: none; min-width: 1.6em; color: var(--k-acento); }

.k-midia { position: absolute; object-fit: cover; }
.k-moldura { position: absolute; pointer-events: none; }
.k-celular { border: 8px solid #fff; border-radius: 44px; box-shadow: 0 30px 80px rgba(0,0,0,.25); }
.k-janela { background: #fff; border-radius: 24px; box-shadow: 0 30px 80px rgba(0,0,0,.25); overflow: hidden; }
.k-barra-janela { height: 56px; background: #E9EDE2; display: flex; align-items: center; gap: 12px; padding: 0 20px; }
.k-bolinha { width: 16px; height: 16px; border-radius: 50%; }
.k-url-janela { margin: 0 auto; background: #fff; border-radius: 99px; padding: 6px 22px;
  font-family: var(--k-mono-familia); font-weight: var(--k-mono-peso); font-size: 20px; color: #3D5435; }
.k-pill { position: absolute; left: 0; right: 0; top: 104px; margin: 0 auto; width: max-content; display: flex; align-items: center; gap: 14px;
  background: #fff; border: 2px solid var(--k-pill-borda); border-radius: 999px; padding: 14px 30px; color: var(--k-pill-texto);
  font-family: var(--k-punch-familia); font-weight: 700; font-size: 30px; white-space: nowrap; }
.k-pill i { width: 16px; height: 16px; border-radius: 50%; background: var(--k-acento); }

.k-endcard-marca { font-size: 150px; }
.k-tagline { font-size: 44px; opacity: .9; }
.k-cta { display: inline-block; background: var(--k-acento); color: var(--k-sobre); border-radius: 999px; padding: 26px 56px;
  font-family: var(--k-punch-familia); font-weight: var(--k-punch-peso); font-size: 44px; margin-top: 24px; }
.k-url { font-family: var(--k-mono-familia); font-weight: var(--k-mono-peso); font-size: 30px; opacity: .7; }

#k-brilho { position: absolute; inset: 0; width: 1080px; height: 1920px; pointer-events: none; }
#k-fixos { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
#k-grao { position: absolute; left: -50%; top: -50%; width: 200%; height: 200%; opacity: 0;
  background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"); }
.k-wordmark { position: absolute; left: 0; right: 0; top: 1790px; text-align: center; opacity: 0; visibility: hidden; }
#k-wm-claro { color: var(--k-tinta); }
#k-wm-escuro { color: var(--k-sobre); }
#k-barra { position: absolute; left: 0; top: 0; width: 1080px; height: 4px; background: var(--k-acento);
  transform-origin: left center; transform: scaleX(0); }
```

- [ ] **Step 4: Write `motion/kit/kit.js` (núcleo)**

```js
/* Kit de motion do video_editor: monta reels a partir de window.__KIT_DADOS
   (gerado por ui/motion.py) numa timeline GSAP que o HyperFrames renderiza.
   Trechos adaptados dos blocos grain-overlay, bottom-up-letters, inline-highlight
   e sdf-iris do catálogo HyperFrames (Apache License 2.0, © HeyGen). */
(() => {
  "use strict";
  const FPS = 30;
  const F = (n) => n / FPS;
  const quadro = (s) => Math.ceil(s * FPS - 1e-6) / FPS;
  const r3 = (s) => Math.round(s * 1000) / 1000;
  const customs = {};
  const cues = [];
  const pintores = [];   // (tempo) => void, chamados a cada seek: estado em função do tempo, nunca acumulado

  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const cue = (t, som, ganho_db = -6) => cues.push({ t: r3(t), som, ganho_db });

  // ---------- entradas de texto: (tl, alvo, t) -> instante em que terminam
  function palavras(tl, alvo, t) {
    const ws = alvo.textContent.split(/\s+/).filter(Boolean);
    alvo.textContent = "";
    const spans = ws.map((w, i) => {
      const m = el("span", "k-mascara");
      const s = el("span", null, w);
      m.appendChild(s);
      alvo.appendChild(m);
      if (i < ws.length - 1) alvo.appendChild(document.createTextNode(" "));
      return s;
    });
    tl.fromTo(spans, { yPercent: 110 }, { yPercent: 0, duration: F(14), ease: "expo.out", stagger: F(6) }, t);
    return t + F(14) + F(6) * (spans.length - 1);
  }

  function letras(tl, alvo, t) {
    const chars = Array.from(alvo.textContent);
    alvo.textContent = "";
    const spans = chars.map((ch) => {
      const s = el("span", "k-letra", ch === " " ? " " : ch);
      alvo.appendChild(s);
      return s;
    });
    tl.fromTo(spans, { opacity: 0, y: 90, scale: 0.6 },
      { opacity: 1, y: 0, scale: 1, duration: F(14), ease: "back.out(1.7)", stagger: F(2) }, t);
    return t + F(14) + F(2) * (spans.length - 1);
  }

  function mascara(tl, alvo, t) {
    tl.fromTo(alvo, { clipPath: "inset(-20% 100% -20% -10%)" },
      { clipPath: "inset(-20% -10% -20% -10%)", duration: F(18), ease: "power3.out" }, t);
    return t + F(18);
  }

  function fade(tl, alvo, t) {
    tl.fromTo(alvo, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: F(18), ease: "power3.out" }, t);
    return t + F(18);
  }

  // ---------- destaques: (tl, bloco, t, tema) -> instante em que terminam
  function marcaTexto(tl, bloco, t) {
    bloco.classList.add("k-com-marca");
    tl.fromTo(bloco, { "--k-marca": 0 }, { "--k-marca": 1, duration: F(14), ease: "power3.out" }, t);
    return t + F(14);
  }

  function risco(tl, bloco, t) {
    const r = el("i", "k-risco");
    bloco.appendChild(r);
    tl.fromTo(r, { scaleX: 0 }, { scaleX: 1, duration: F(8), ease: "power3.out" }, t);
    return t + F(8);
  }

  function assinaturaEl(tema) {
    if (tema.assinatura.tipo === "icone") {
      const i = el("img", "k-icone");
      i.src = tema.assinatura.src;
      return i;
    }
    return el("span", "k-ponto");
  }

  function assinatura(tl, bloco, t, tema) {
    const s = assinaturaEl(tema);
    bloco.appendChild(s);
    tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: F(1) }, t);
    tl.fromTo(s, { y: -900 }, { y: 0, duration: F(8), ease: "power2.in" }, t)
      .to(s, { y: -110, duration: F(4), ease: "power2.out" }, t + F(8))
      .to(s, { y: 0, duration: F(3), ease: "power2.in" }, t + F(12))
      .to(s, { y: -35, duration: F(1.5), ease: "power2.out" }, t + F(15))
      .to(s, { y: 0, duration: F(1.5), ease: "power2.in" }, t + F(16.5));
    cue(t + F(8), "pop-dourado");
    return t + F(18);
  }

  const ANIM = { palavras, letras, mascara, fade };
  const DESTAQUE = { "marca-texto": marcaTexto, risco, assinatura };

  // ---------- tipos de cena: (c, cena) -> instante em que a última entrada termina
  function linhas(c, lista, t) {
    let cur = t;
    lista.forEach((ln, i) => {
      const div = el("div", `k-linha k-${ln.estilo} k-cor-${ln.cor}`);
      div.dataset.kTexto = "";
      const bloco = el("span", "k-bloco");
      const txt = el("span", "k-txt", ln.t);
      bloco.appendChild(txt);
      div.appendChild(bloco);
      c.el.appendChild(div);
      const ini = ln.em != null ? Math.max(cur, c.t0 + ln.em) : cur;
      if (ln.anim === "palavras" && i === 0) cue(ini, "rise");
      if (ln.anim === "letras" || ln.anim === "mascara") cue(ini, "whoosh-reveal");
      let fim = ANIM[ln.anim](c.tl, txt, ini);
      for (const d of ln.destaque) fim = DESTAQUE[d](c.tl, bloco, fim - F(2), c.tema);
      cur = fim - F(4);
    });
    return cur + F(4);
  }

  const frase = (c, cena) => linhas(c, cena.linhas, c.t0);

  function endcard(c, cena) {
    let t = c.t0;
    cue(t, "sting-endcard");
    const marca = el("div", `k-linha k-display k-endcard-marca k-cor-${cena.cor}`);
    marca.dataset.kTexto = "";
    const bloco = el("span", "k-bloco");
    const txt = el("span", "k-txt", c.tema.endcard_marca);
    bloco.appendChild(txt);
    marca.appendChild(bloco);
    c.el.appendChild(marca);
    t = mascara(c.tl, txt, t);
    t = assinatura(c.tl, bloco, t - F(4), c.tema);
    const tag = el("div", `k-linha k-corpo k-tagline k-cor-${cena.cor}`, cena.tagline);
    tag.dataset.kTexto = "";
    c.el.appendChild(tag);
    t = fade(c.tl, tag, t - F(6));
    const cta = el("div", "k-linha k-cta", cena.cta);
    cta.dataset.kTexto = "";
    c.el.appendChild(cta);
    c.tl.fromTo(cta, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: F(14), ease: "back.out(2)" }, t);
    cue(t, "click-pill");
    t += F(14);
    const url = el("div", `k-linha k-url k-cor-${cena.cor}`, cena.url);
    url.dataset.kTexto = "";
    c.el.appendChild(url);
    return fade(c.tl, url, t - F(4));
  }

  function custom(c, cena) {
    const fn = customs[cena.id];
    if (!fn) throw new Error("cena custom não chamou KIT.custom(...)");
    const fim = fn(c);
    if (typeof fim !== "number" || !isFinite(fim)) throw new Error("KIT.custom precisa devolver o instante de fim (número)");
    return fim;
  }

  const TIPOS = { frase, endcard };
  const COMP = { palavras, letras, mascara, fade, marcaTexto, risco, assinatura };

  // ---------- transições: entrada da cena nova sobre a anterior
  const TRANS = {
    fade: (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d, ease: "power1.inOut" }, t),
  };

  // ---------- fundo, manchas, grão
  function fundo(c, cena) {
    const f = el("div", "k-fundo");
    f.style.background = `var(--k-fundo-${cena.fundo})`;
    c.layer.prepend(f);
    if (cena.fundo !== "claro") return;
    const a = el("div", "k-mancha");
    const b = el("div", "k-mancha");
    Object.assign(a.style, { left: "-260px", top: "240px" });
    Object.assign(b.style, { left: "480px", top: "1120px" });
    f.append(a, b);
    c.tl.fromTo(a, { x: 0, y: 0 }, { x: 140, y: 90, duration: 6, ease: "sine.inOut" }, c.ini);
    c.tl.fromTo(b, { x: 0, y: 0 }, { x: -160, y: -120, duration: 6, ease: "sine.inOut" }, c.ini);
  }

  function grao(tema) {
    const g = document.getElementById("k-grao");
    g.style.opacity = String(tema.grao);
    if (!tema.grao) return;
    pintores.push((tempo) => {
      const n = Math.floor((tempo * FPS) / 2);
      const r = (k) => { const x = Math.sin(n * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); };
      g.style.transform = `translate(${((r(1) - 0.5) * 20).toFixed(2)}%, ${((r(2) - 0.5) * 20).toFixed(2)}%)`;
    });
  }

  // ---------- montagem
  function montar() {
    const D = window.__KIT_DADOS;
    const tema = D.tema;
    const tl = gsap.timeline({ paused: true });
    const erros = [];
    const cenas = [];
    const wmClaro = document.getElementById("k-wm-claro");
    const wmEscuro = document.getElementById("k-wm-escuro");
    const barra = document.getElementById("k-barra");
    for (const w of [wmClaro, wmEscuro]) {
      w.textContent = tema.wordmark;
      w.classList.add(`k-${tema.wordmark_fonte}`);
      w.style.fontSize = "52px";
    }
    grao(tema);
    let ini = 0;
    D.cenas.forEach((cena, i) => {
      const layer = document.getElementById(cena.id);
      const entra = i > 0 ? D.cenas[i - 1].saida : null;
      const c = { tl, layer, el: layer.querySelector(".k-conteudo"), tema, ini,
        t0: ini + (entra ? entra.dur : 0) + F(4), F, cue, C: COMP };
      fundo(c, cena);
      let fim;
      try {
        fim = cena.tipo === "custom" ? custom(c, cena) : TIPOS[cena.tipo](c, cena);
      } catch (e) {
        erros.push({ id: cena.id, motivo: String((e && e.message) || e) });
        fim = c.t0;
      }
      const saida = cena.saida ? cena.saida.dur : 0;
      const min = quadro(fim - ini + (cena.tipo === "endcard" ? 1.2 : 0.8) + saida);
      let dur = min;
      if (cena.dur != null) {
        dur = quadro(cena.dur);
        if (dur + 1e-6 < min) erros.push({ id: cena.id, motivo: `dur ${cena.dur}s abaixo do mínimo ${min.toFixed(2)}s` });
      }
      tl.set(layer, { visibility: "visible" }, ini).set(layer, { visibility: "hidden" }, ini + dur);
      if (entra) TRANS[entra.transicao](tl, layer, ini, entra.dur, tema);
      const claro = cena.fundo === "claro";
      tl.set(wmClaro, { autoAlpha: cena.fixos && claro ? 0.55 : 0 }, ini);
      tl.set(wmEscuro, { autoAlpha: cena.fixos && !claro ? 0.55 : 0 }, ini);
      if (tema.barra) tl.set(barra, { autoAlpha: cena.fixos ? 1 : 0 }, ini);
      cenas.push({ id: cena.id, ini: r3(ini), dur: r3(dur), min: r3(min), saida });
      ini += dur - saida;
    });
    const total = quadro(ini);
    if (tema.barra) tl.fromTo(barra, { scaleX: 0 }, { scaleX: 1, duration: total, ease: "none" }, 0);
    tl.to({}, { duration: 0 }, total);
    const pintar = () => { const t = tl.time(); for (const p of pintores) p(t); };
    tl.eventCallback("onUpdate", pintar);
    window.__timelines = window.__timelines || {};
    window.__timelines.main = tl;
    window.__kit = {
      duracao: r3(total), cenas, erros,
      cues: cues.slice().sort((a, b) => a.t - b.t),
      ir: (t) => { tl.seek(t, false); pintar(); },
    };
    tl.seek(0, false);
    pintar();
  }

  window.KIT = {
    custom: (fn) => { customs[document.currentScript.closest(".cena").id] = fn; },
    montar, F, FPS,
  };
})();
```

- [ ] **Step 5: Implement `montar` in `ui/motion.py`**

Update the imports to:
```python
import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
```
Append:
```python
MARCADOR_DIR = ".motion"   # só pasta com este arquivo pode ser apagada pelo montar
LANG_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2})?")

HTML = """<!doctype html>
<html lang="pt-BR" data-resolution="portrait">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080, height=1920">
<link rel="stylesheet" href="kit/kit.css">
<style>{css}</style>
<script src="kit/vendor/gsap.min.js"></script>
<script src="kit/kit.js"></script>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="1080" data-height="1920" data-fps="30">
{cenas}
<canvas id="k-brilho" class="clip" width="1080" height="1920" data-start="0" data-duration="{dur}" data-track-index="900"></canvas>
<div id="k-fixos" class="clip" data-start="0" data-duration="{dur}" data-track-index="901"><div id="k-grao"></div><div id="k-wm-claro" class="k-wordmark"></div><div id="k-wm-escuro" class="k-wordmark"></div><div id="k-barra"></div></div>
</div>
<script>window.__KIT_DADOS = {dados};</script>
<script>KIT.montar();</script>
</body>
</html>
"""

JS_MEDIR = """([id, safe]) => {
  const [x0, y0, x1, y1] = safe, out = [];
  for (const e of document.querySelectorAll(`#${id} [data-k-texto]`)) {
    const r = e.getBoundingClientRect();
    const txt = e.textContent.trim().slice(0, 40);
    if (e.scrollWidth > e.clientWidth + 1) out.push(`linha estoura a largura: "${txt}"`);
    else if (r.left < x0 - 1 || r.right > x1 + 1 || r.top < y0 - 1 || r.bottom > y1 + 1)
      out.push(`texto fora da safe area: "${txt}"`);
    const fam = getComputedStyle(e).fontFamily.split(",")[0].trim().replace(/["']/g, "");
    const ok = [...document.fonts].some((f) => f.family.replace(/["']/g, "") === fam && f.status === "loaded");
    if (!ok) out.push(`fonte em fallback (${fam}): "${txt}"`);
  }
  return out;
}"""


def _lang(lang) -> str:
    if lang is None:
        return ""
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"lang inválido: {lang!r}")
    return f".{lang}"


def _attrs(t: dict, track: int) -> str:
    return f'data-start="{t["ini"]:.3f}" data-duration="{t["dur"]:.3f}" data-track-index="{track}"'


def _html(d: dict, tema: dict, customs: dict, tempos: dict | None) -> str:
    por_id = {c["id"]: c for c in (tempos or {}).get("cenas", [])}
    total = (tempos or {}).get("duracao", 1)
    partes = []
    for i, c in enumerate(d["cenas"]):
        t = por_id.get(c["id"], {"ini": 0, "dur": 1})
        inner = '<div class="k-conteudo"></div>'
        if c["tipo"] == "tela":
            src = f'midia/{c["id"]}{c["_ext"]}'
            if c["video"]:
                inner += f'<video class="k-midia clip" src="{src}" muted playsinline {_attrs(t, 100 + i)}></video>'
            else:
                inner += f'<img class="k-midia" src="{src}" alt="">'
        elif c["tipo"] == "custom":
            inner += customs[c["id"]]
        partes.append(f'<div id="{c["id"]}" class="clip cena" {_attrs(t, i)}>{inner}</div>')
    cenas_js = [{k: v for k, v in c.items() if not k.startswith("_")} for c in d["cenas"]]
    dados = json.dumps({"tema": _tema_js(tema), "cenas": cenas_js}, ensure_ascii=False).replace("</", "<\\/")
    return HTML.format(css=_css_vars(tema), dur=f"{total:.3f}", cenas="\n".join(partes), dados=dados)


def _preparar(comp: Path, proj: Path, d: dict, tema: dict, motion_dir: Path) -> None:
    if comp.exists():
        if not (comp / MARCADOR_DIR).is_file():
            raise ValueError(f"{comp} existe e não foi criado pelo motion.py (renomeie ou apague à mão)")
        shutil.rmtree(comp)
    shutil.copytree(motion_dir / "kit", comp / "kit")
    (comp / MARCADOR_DIR).write_text("gerado por ui/motion.py montar\n", encoding="utf-8")
    if tema["assinatura"]["tipo"] == "icone":
        a = motion_dir / "temas" / tema["assinatura"]["arquivo"]
        (comp / "kit" / "tema").mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, comp / "kit" / "tema" / a.name)
    for c in d["cenas"]:
        if c["tipo"] == "tela":
            src = _dentro(proj, c["arquivo"])
            c["_ext"] = src.suffix.lower()
            (comp / "midia").mkdir(exist_ok=True)
            shutil.copy2(src, comp / "midia" / f"{c['id']}{c['_ext']}")


def _medir(index: Path) -> dict:
    from playwright.sync_api import TimeoutError as PwTimeout
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        try:
            pg = b.new_page(viewport={"width": W, "height": H})
            js = []
            pg.on("pageerror", lambda ex: js.append(str(ex)))
            pg.goto(index.resolve().as_uri())
            try:
                pg.wait_for_function("window.__kit !== undefined", timeout=20000)
            except PwTimeout:
                raise RuntimeError("kit não montou: " + ("; ".join(js) or "sem erro de JS (timeout)")) from None
            pg.evaluate("document.fonts.ready.then(() => true)")
            kit = pg.evaluate("({duracao: __kit.duracao, cenas: __kit.cenas, cues: __kit.cues, erros: __kit.erros})")
            layout = []
            for c in kit["cenas"]:
                pg.evaluate("t => __kit.ir(t)", max(c["ini"], c["ini"] + c["dur"] - c["saida"] - 0.02))
                layout += [{"id": c["id"], "motivo": m} for m in pg.evaluate(JS_MEDIR, [c["id"], list(SAFE)])]
            return {**kit, "layout": layout, "js": js}
        finally:
            b.close()


def montar(proj: Path, lang: str | None = None, motion_dir: Path = MOTION) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    cj = proj / f"cenas{suf}.json"
    if not cj.is_file():
        raise ValueError(f"não existe: {cj}")
    try:
        dados = json.loads(cj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise ValueError(f"{cj.name} inválido: {ex}") from None
    erros = validar(dados, proj)
    if erros:
        return {"ok": False, "erros": erros}
    tema = carregar_tema(dados.get("marca"), motion_dir)
    d = resolver(dados, tema, proj)
    comp = proj / f"motion{suf}"
    _preparar(comp, proj, d, tema, motion_dir)
    customs = {c["id"]: _dentro(proj, c["html"]).read_text(encoding="utf-8")
               for c in d["cenas"] if c["tipo"] == "custom"}
    index = comp / "index.html"
    index.write_text(_html(d, tema, customs, None), encoding="utf-8")
    m = _medir(index)
    erros = [{"id": "kit", "motivo": j} for j in m["js"]] + m["erros"] + m["layout"]
    if erros:
        return {"ok": False, "erros": erros}
    index.write_text(_html(d, tema, customs, m), encoding="utf-8")
    pipeline.atomic_write_json(comp / "tempos.json", {"duracao": m["duracao"], "cenas": m["cenas"]})
    cues = proj / f"cues{suf}.json"
    pipeline.atomic_write_json(cues, m["cues"])
    return {"ok": True, "duracao": m["duracao"], "erros": [], "index": str(index), "cues": str(cues),
            "cenas": [{"id": c["id"], "ini": c["ini"], "dur": c["dur"]} for c in m["cenas"]]}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS. If `test_montar_fonte_fallback` fails because Chromium reports the K family as loaded anyway, check in the page that `[...document.fonts]` lists the `@font-face`. The test's family does not exist in `kit.css`, so `some(...)` must be `false`. Do not loosen the test.

- [ ] **Step 7: Visual sanity check (manual, one time)**

Run:
```bash
python -c "import sys; sys.path.insert(0,'ui'); import motion, json, pathlib, tempfile; p=pathlib.Path(tempfile.mkdtemp())/'p'; p.mkdir(); (p/'cenas.json').write_text(json.dumps({'marca':'anotus','cenas':[{'id':'c01','tipo':'frase','linhas':[{'t':'Pare de'},{'t':'decorar.','estilo':'display','anim':'letras','destaque':['marca-texto','risco']}]},{'id':'c02','tipo':'endcard'}]}),encoding='utf-8'); print(motion.montar(p)); print(p)"
```
Open the printed `<p>/motion/index.html` in Playwright. Run `__kit.ir(1.6)` and take a screenshot, then `__kit.ir(<duracao-0.1>)` and take another. Look at both images (Read). Check: real Fraunces italic, highlighter behind the word, strike over the word, lavender background with blobs, wordmark at the bottom, end card with dot, CTA and url. Fix `kit.css`/`kit.js` if anything is wrong.

- [ ] **Step 8: Commit**

```bash
git add motion/kit/kit.css motion/kit/kit.js ui/motion.py ui/test_motion.py
git commit -m "feat(motion): kit núcleo (frase, endcard, fade, fixos) e montar com medida de layout"
```

---

### Task 4: Tipos `numero`, `lista`, `tela`, custom e transições `wipe`/`iris`

**Files:**
- Modify: `motion/kit/kit.js`
- Test: `ui/test_motion.py`

**Interfaces:**
- Consumes: T3 kit (`el`, `cue`, `pintores`, `F`, `palavras`, `fade`, `assinaturaEl`, `TIPOS`, `TRANS`, `COMP`).
- Produces: `TIPOS = { frase, endcard, numero, lista, tela }`; `TRANS = { fade, wipe, iris }`; `COMP` passa a incluir `contador(tl, alvo, t, {de, valor, formato, prefixo, sufixo})` e `kenBurns(tl, alvo, t, d)`.

- [ ] **Step 1: Write the failing tests**

Append to `ui/test_motion.py`:
```python
CUSTOM = """<div class="k-linha k-display k-cor-tinta" data-k-texto><span class="k-txt" id="{id}-t">custom</span></div>
<script>
KIT.custom((c) => {{
  const alvo = c.layer.querySelector("#{id}-t");
  c.el.appendChild(alvo.parentElement);
  return c.C.mascara(c.tl, alvo, c.t0);
}});
</script>
"""


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _midia(p: Path):
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(p / "tela.png"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-pix_fmt", "yuv420p", str(p / "clip.mp4"))


def _todos(marca):
    return {"marca": marca, "cenas": [
        {"id": "c01", "tipo": "numero", "valor": 1250, "legenda": "usuários", "saida": {"transicao": "wipe", "dur": 0.4}},
        {"id": "c02", "tipo": "lista", "titulo": "Três passos", "itens": ["Grifar", "Revisar", "Lembrar"],
         "saida": {"transicao": "iris", "dur": 0.47}},
        {"id": "c03", "tipo": "tela", "arquivo": "tela.png", "label": "Busca"},
        {"id": "c04", "tipo": "tela", "arquivo": "clip.mp4", "moldura": "browser"},
        {"id": "c05", "tipo": "lista", "itens": ["um", "dois"], "marcador": "assinatura"},
        {"id": "c06", "tipo": "custom", "html": "c06.html", "dur": 2.5},
        {"id": "c07", "tipo": "endcard"}]}


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
@pytest.mark.parametrize("marca", ["anotus", "campeio"])
def test_todos_os_tipos_montam(tmp_path, marca):
    p = _proj(tmp_path, _todos(marca))
    _midia(p)
    (p / "c06.html").write_text(CUSTOM.format(id="c06"), encoding="utf-8")
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    assert abs(r["cenas"][3]["dur"] - 3.0) < 0.04          # tela com vídeo: dur = duração do arquivo
    assert abs(r["cenas"][2]["dur"] - 3.0) < 0.04          # tela com imagem: 3 s
    html = (p / "motion" / "index.html").read_text(encoding="utf-8")
    assert '<video class="k-midia clip" src="midia/c04.mp4"' in html and (p / "motion" / "midia" / "c03.png").is_file()
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"tick", "click-pill", "rise", "sting-endcard"} <= sons


@pw
def test_custom_sem_registro_vira_erro(tmp_path):
    d = _cenas()
    d["cenas"].insert(1, {"id": "c05", "tipo": "custom", "html": "c05.html", "dur": 2})
    p = _proj(tmp_path, d)
    (p / "c05.html").write_text("<div>nada</div>", encoding="utf-8")
    r = motion.montar(p)
    assert any(e["id"] == "c05" and "KIT.custom" in e["motivo"] for e in r["erros"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ui/test_motion.py -q -k "todos or custom_sem"`
Expected: `test_custom_sem_registro_vira_erro` PASSES already, because the custom path is in T3. `test_todos_os_tipos_montam` FAILS with a kit error like `TIPOS[cena.tipo] is not a function`, reported as `{"id": "c01", ...}`.

- [ ] **Step 3: Add the code to `motion/kit/kit.js`**

Insert right after the `fade` function:
```js
  function contador(tl, alvo, t, o) {
    const fmt = new Intl.NumberFormat(o.formato);
    const ease = gsap.parseEase("power3.out");
    const d = F(45);
    const pinta = (tempo) => {
      const p = Math.min(1, Math.max(0, (tempo - t) / d));
      alvo.textContent = `${o.prefixo}${fmt.format(Math.round(o.de + (o.valor - o.de) * ease(p)))}${o.sufixo}`;
    };
    pintores.push(pinta);
    pinta(t + d);   // texto final no DOM para a medida de layout
    cue(t, "tick");
    return t + d;
  }

  function kenBurns(tl, alvo, t, d) {
    tl.fromTo(alvo, { scale: 1 }, { scale: 1.06, duration: Math.max(d, F(1)), ease: "sine.inOut", immediateRender: false }, t);
    return t;
  }
```

Insert right after the `endcard` function:
```js
  function numero(c, cena) {
    const n = el("div", `k-linha k-numero k-${cena.estilo} k-cor-${cena.cor}`);
    n.dataset.kTexto = "";
    c.el.appendChild(n);
    fade(c.tl, n, c.t0);
    let fim = contador(c.tl, n, c.t0, cena);
    if (cena.legenda) {
      const l = el("div", `k-linha k-corpo k-legenda k-cor-${cena.cor}`, cena.legenda);
      l.dataset.kTexto = "";
      c.el.appendChild(l);
      fim = fade(c.tl, l, fim - F(20));
    }
    return fim;
  }

  function lista(c, cena) {
    c.el.classList.add("k-lista");
    let t = c.t0;
    if (cena.titulo) {
      const h = el("div", `k-linha k-punch k-lista-titulo k-cor-${cena.cor}`);
      h.dataset.kTexto = "";
      const tx = el("span", "k-txt", cena.titulo);
      h.appendChild(tx);
      c.el.appendChild(h);
      cue(t, "rise");
      t = palavras(c.tl, tx, t) - F(4);
    }
    cena.itens.forEach((item, i) => {
      const row = el("div", `k-item k-corpo k-cor-${cena.cor}`);
      row.dataset.kTexto = "";
      const m = el("span", "k-marcador k-mono");
      if (cena.marcador === "numero") m.textContent = String(i + 1).padStart(2, "0");
      else if (cena.marcador === "check") m.textContent = "✓";
      else m.appendChild(assinaturaEl(c.tema));
      row.append(m, el("span", null, item));
      c.el.appendChild(row);
      c.tl.fromTo(row, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: F(14), ease: "power3.out" }, t);
      if (i === 0 && !cena.titulo) cue(t, "rise");
      t += F(10);
    });
    return t + F(4);
  }

  const MOLDURA = { celular: [100, 178, 880, 1564], browser: [60, 560, 960, 600], nenhuma: [0, 0, 1080, 1920] };
  const px = (e, [x, y, w, h]) => Object.assign(e.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });

  function tela(c, cena) {
    const m = c.layer.querySelector(".k-midia");
    px(m, MOLDURA[cena.moldura]);
    const grupo = [m];
    if (cena.moldura === "celular") {
      m.style.borderRadius = "36px";
      const b = el("div", "k-moldura k-celular");
      px(b, [92, 170, 896, 1580]);
      c.layer.appendChild(b);
      grupo.push(b);
    } else if (cena.moldura === "browser") {
      m.style.objectPosition = "top";
      m.style.borderRadius = "0 0 24px 24px";
      const j = el("div", "k-moldura k-janela");
      px(j, [60, 504, 960, 656]);
      const barra = el("div", "k-barra-janela");
      for (const cor of ["#A32D14", "#E8CE9A", "#6D8B5C"]) {
        const b = el("i", "k-bolinha");
        b.style.background = cor;
        barra.appendChild(b);
      }
      barra.appendChild(el("span", "k-url-janela", c.tema.url));
      j.appendChild(barra);
      c.layer.insertBefore(j, m);
      grupo.push(j);
    }
    c.tl.fromTo(grupo, { opacity: 0, scale: 0.96 }, { opacity: 1, scale: 1, duration: F(18), ease: "power3.out" }, c.t0);
    let fim = c.t0 + F(18);
    if (cena.kenburns) kenBurns(c.tl, m, fim, cena.dur - (fim - c.ini));
    if (cena.label) {
      const p = el("div", "k-pill");
      p.append(el("i"), el("span", null, cena.label));
      c.layer.appendChild(p);
      c.tl.fromTo(p, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: F(14), ease: "back.out(2)" }, c.t0 + F(8));
      cue(c.t0 + F(8), "click-pill");
      fim = Math.max(fim, c.t0 + F(22));
    }
    return fim;
  }

  const rgb = (hex) => {
    const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  };

  // brilho da íris: anel em WebGL (shader do bloco sdf-iris, só o anel) desenhado em função do tempo
  function brilho(t, d, cor) {
    const cv = document.getElementById("k-brilho");
    if (!cv._k) {
      const gl = cv.getContext("webgl", { preserveDrawingBuffer: true, premultipliedAlpha: true });
      const sh = (src, tipo) => { const s = gl.createShader(tipo); gl.shaderSource(s, src); gl.compileShader(s); return s; };
      const prog = gl.createProgram();
      gl.attachShader(prog, sh("attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}", gl.VERTEX_SHADER));
      gl.attachShader(prog, sh(
        "precision highp float;uniform float r;uniform float env;uniform vec3 cor;" +
        "void main(){float d=distance(gl_FragCoord.xy,vec2(540.,960.));" +
        "float a=(exp(-abs(d-r)/14.)+.45*exp(-abs(d-r-28.)/26.))*env*.85;a=clamp(a,0.,1.);" +
        "gl_FragColor=vec4(cor*a,a);}", gl.FRAGMENT_SHADER));
      gl.linkProgram(prog);
      gl.useProgram(prog);
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "a");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      const ease = gsap.parseEase("power2.inOut");
      const uR = gl.getUniformLocation(prog, "r");
      const uE = gl.getUniformLocation(prog, "env");
      const uC = gl.getUniformLocation(prog, "cor");
      const k = { lista: [] };
      cv._k = k;
      pintores.push((tempo) => {
        gl.viewport(0, 0, 1080, 1920);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        const b = k.lista.find((x) => tempo > x.t && tempo < x.t + x.d);
        if (!b) return;
        const q = (tempo - b.t) / b.d;
        gl.uniform1f(uR, ease(q) * 1110);
        gl.uniform1f(uE, 4 * q * (1 - q));
        gl.uniform3fv(uC, b.cor);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      });
    }
    cv._k.lista.push({ t, d, cor: rgb(cor) });
  }
```

Replace:
```js
  const TIPOS = { frase, endcard };
  const COMP = { palavras, letras, mascara, fade, marcaTexto, risco, assinatura };
```
with:
```js
  const TIPOS = { frase, endcard, numero, lista, tela };
  const COMP = { palavras, letras, mascara, fade, marcaTexto, risco, assinatura, contador, kenBurns };
```

Replace the `TRANS` object with:
```js
  const TRANS = {
    fade: (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d, ease: "power1.inOut" }, t),
    wipe: (tl, cam, t, d) => tl.fromTo(cam, { clipPath: "inset(0% 100% 0% 0%)" },
      { clipPath: "inset(0% 0% 0% 0%)", duration: d, ease: "power3.inOut" }, t),
    iris: (tl, cam, t, d, tema) => {
      tl.fromTo(cam, { clipPath: "circle(0px at 50% 50%)" },
        { clipPath: "circle(1110px at 50% 50%)", duration: d, ease: "power2.inOut" }, t);
      brilho(t, d, tema.acento);
    },
  };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add motion/kit/kit.js ui/test_motion.py
git commit -m "feat(motion): tipos numero, lista, tela e transições wipe/iris com brilho"
```

---

### Task 5: `render`, `folha` e CLI

**Files:**
- Modify: `ui/motion.py`
- Test: `ui/test_motion.py`

**Interfaces:**
- Consumes: `montar`, `_lang`, `tempos.json` (T3).
- Produces:
  - `render(proj, rascunho=False, lang=None, motion_dir=MOTION) -> dict` (`{"ok": True, "video", "duracao"}`, or the not-ok `montar` result);
  - `folha(proj, lang=None) -> dict` (`{"png", "frames": [{"id", "rotulo", "t"}]}`);
  - helpers `_executar(cmd, cwd, env, linha) -> (rc, ultimas)`, `_pct(linha) -> float | None`, `_progresso(proj, fase, pct, eta)`, `_probe(p) -> dict`, `_finalizar(tmp, dst, duracao) -> dict`, `_hf_bin(motion_dir)`, `_velho(index, fontes) -> bool`, `_fontes(proj, cj, motion_dir) -> list[Path]`;
  - CLI `python ui/motion.py montar|render|folha <proj> [--lang xx] [--rascunho]`.

- [ ] **Step 1: Write the failing tests**

Append to `ui/test_motion.py`:
```python
ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _montado(tmp_path, dur=2.0, suf=""):
    p = tmp_path / "proj"
    (p / f"motion{suf}").mkdir(parents=True, exist_ok=True)
    (p / "ui").mkdir(exist_ok=True)
    (p / "ui" / "state.json").write_text(json.dumps({"aprovacoes": {"x": 1}}), encoding="utf-8")
    (p / f"motion{suf}" / "index.html").write_text("<html></html>", encoding="utf-8")
    (p / f"motion{suf}" / "tempos.json").write_text(json.dumps(
        {"duracao": dur, "cenas": [{"id": "c01", "ini": 0, "dur": dur / 2, "min": 1, "saida": 0.3},
                                   {"id": "c02", "ini": dur / 2 - 0.3, "dur": dur / 2 + 0.3, "min": 1, "saida": 0}]}),
        encoding="utf-8")
    return p


def _fake_hf(dur, pix="yuv420p", rng="tv", rc=0, cmds=None):
    def run(cmd, cwd, env, linha):
        if cmds is not None:
            cmds.append((cmd, env))
        if rc:
            return rc, ["boom: chrome caiu"]
        for i in (10, 50, 100):
            linha(f"\x1b[32mRendering\x1b[0m {i}%")
        _ff("-f", "lavfi", "-i", f"color=c=gray:s=1080x1920:r=30:d={dur}", "-pix_fmt", pix,
            "-color_range", rng, str(cmd[cmd.index("-o") + 1]))
        return 0, ["ok"]
    return run


@pytest.fixture
def sem_hf(monkeypatch):
    monkeypatch.setattr(motion, "_hf_bin", lambda md: None)
    monkeypatch.setattr(motion, "_velho", lambda idx, fontes: False)


def test_pct():
    assert motion._pct("Rendering 42%") == 42.0
    assert motion._pct("frame 15/150") == 10.0
    assert motion._pct("nada aqui") is None


def test_render_sem_node_modules(tmp_path):
    with pytest.raises(RuntimeError, match="npm ci"):
        motion.render(_montado(tmp_path), motion_dir=tmp_path / "m")


@ffmpeg
def test_render_confere_e_preserva_state(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    cmds = []
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, cmds=cmds))
    r = motion.render(p)
    assert r["ok"] and (p / "video.mp4").is_file()
    cmd, env = cmds[0]
    assert cmd[cmd.index("--fps") + 1] == "30" and cmd[cmd.index("-q") + 1] == "looks"
    assert cmd[cmd.index("--crf") + 1] == "18" and env["HYPERFRAMES_NO_TELEMETRY"] == "1"
    st = json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))
    assert st["aprovacoes"] == {"x": 1} and st["render"]["fase"] == "pronto" and st["render"]["pct"] == 100


@ffmpeg
def test_render_corrige_range_pc(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, pix="yuvj420p", rng="pc"))
    motion.render(p)
    pr = motion._probe(p / "video.mp4")
    assert pr["pix_fmt"] == "yuv420p" and pr["range"] == "tv"


@ffmpeg
def test_render_frames_errados_falha(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path, dur=3.0)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0))
    with pytest.raises(RuntimeError, match="frames"):
        motion.render(p)
    assert not (p / "video.mp4").exists()


@ffmpeg
def test_render_rascunho_e_lang(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path, suf=".en")
    cmds = []
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, cmds=cmds))
    motion.render(p, rascunho=True, lang="en")
    cmd = cmds[0][0]
    assert cmd[cmd.index("-q") + 1] == "draft" and cmd[cmd.index("render") + 1].endswith("motion.en")
    assert (p / "video_rascunho.en.mp4").is_file()


def test_render_falha_mostra_saida(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, rc=1))
    with pytest.raises(RuntimeError, match="chrome caiu"):
        motion.render(p)
    assert json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))["render"]["fase"] == "falha"


@ffmpeg
def test_folha(tmp_path):
    p = _montado(tmp_path, dur=4.0)
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=4", "-pix_fmt", "yuv420p", str(p / "video.mp4"))
    r = motion.folha(p)
    assert Path(r["png"]).is_file()
    assert [f["rotulo"] for f in r["frames"]] == ["entrada", "final", "saida", "entrada", "final"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ui/test_motion.py -q -k "render or folha or pct"`
Expected: FAIL with `AttributeError: module 'motion' has no attribute '_pct'`

- [ ] **Step 3: Implement in `ui/motion.py`**

Update imports to:
```python
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
```
Append:
```python
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
FRAMES_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
ENV_HF = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HF_CLI_TELEMETRY_DISABLED": "1",
          "HYPERFRAMES_SKIP_SKILLS": "1"}


def _hf_bin(motion_dir: Path) -> None:
    if not (motion_dir / "node_modules" / "hyperframes").is_dir():
        raise RuntimeError(f"hyperframes não instalado: rodar `npm ci` em {motion_dir}")


def _fontes(proj: Path, cj: Path, motion_dir: Path) -> list[Path]:
    fs = [cj, *(motion_dir / "kit").rglob("*")]
    d = pipeline.read_json(cj, {})
    if isinstance(d, dict):
        if isinstance(d.get("marca"), str):
            fs.append(motion_dir / "temas" / f"{d['marca']}.json")
        for c in d.get("cenas") if isinstance(d.get("cenas"), list) else []:
            if isinstance(c, dict):
                fs += [proj / c[k] for k in ("arquivo", "html") if isinstance(c.get(k), str)]
    return fs


def _velho(index: Path, fontes: list[Path]) -> bool:
    if not index.is_file():
        return True
    m = index.stat().st_mtime
    return any(f.is_file() and f.stat().st_mtime > m for f in fontes)


def _pct(linha: str) -> float | None:
    linha = ANSI.sub("", linha)
    m = PCT_RE.search(linha)
    if m:
        return min(100.0, float(m.group(1)))
    m = FRAMES_RE.search(linha)
    if m and int(m.group(2)) > 0:
        return min(100.0, 100 * int(m.group(1)) / int(m.group(2)))
    return None


def _progresso(proj: Path, fase: str, pct=None, eta=None) -> None:
    st = proj / "ui" / "state.json"
    if not st.parent.is_dir():
        return
    atual = pipeline.read_json(st, {})       # merge: preserva chaves alheias (ex.: aprovacoes)
    if not isinstance(atual, dict):
        atual = {}
    atual["render"] = {"fase": fase, "pct": pct, "eta": eta}
    pipeline.atomic_write_json(st, atual)


def _executar(cmd: list[str], cwd: Path, env: dict, linha) -> tuple[int, list[str]]:
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    ultimas: list[str] = []
    for ln in p.stdout:
        ln = ln.rstrip()
        ultimas = (ultimas + [ANSI.sub("", ln)])[-20:]
        linha(ln)
    return p.wait(), ultimas


def _probe(p: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,pix_fmt,color_range,nb_frames", "-of", "json", str(p)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"w": s["width"], "h": s["height"], "fps": float(num) / float(den), "pix_fmt": s.get("pix_fmt"),
            "range": s.get("color_range", "unknown"), "frames": int(s.get("nb_frames") or 0)}


def _finalizar(tmp: Path, dst: Path, duracao: float) -> dict:
    pr = _probe(tmp)
    if pr["pix_fmt"] == "yuvj420p" or pr["range"] == "pc":
        conv = tmp.with_name(tmp.stem + ".tv.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                        "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-c:v", "libx264", "-crf", "18",
                        "-preset", "medium", "-profile:v", "high", "-color_range", "tv", "-an",
                        "-movflags", "+faststart", str(conv)], check=True)
        os.replace(conv, tmp)
        pr = _probe(tmp)
    esperado = round(duracao * FPS)
    problemas = []
    if (pr["w"], pr["h"]) != (W, H):
        problemas.append(f"dimensão {pr['w']}x{pr['h']}")
    if abs(pr["fps"] - FPS) > 0.01:
        problemas.append(f"fps {pr['fps']:.3f}")
    if pr["pix_fmt"] != "yuv420p":
        problemas.append(f"pix_fmt {pr['pix_fmt']}")
    if pr["frames"] and abs(pr["frames"] - esperado) > 1:
        problemas.append(f"{pr['frames']} frames (esperado {esperado})")
    if problemas:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("vídeo fora do esperado: " + ", ".join(problemas))
    os.replace(tmp, dst)
    return pr


def render(proj: Path, rascunho: bool = False, lang: str | None = None, motion_dir: Path = MOTION) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    _hf_bin(motion_dir)
    comp = proj / f"motion{suf}"
    if _velho(comp / "index.html", _fontes(proj, proj / f"cenas{suf}.json", motion_dir)):
        r = montar(proj, lang, motion_dir)
        if not r["ok"]:
            return r
    tempos = pipeline.read_json(comp / "tempos.json", None)
    if not tempos:
        raise RuntimeError(f"{comp / 'tempos.json'} ausente: rodar montar")
    nome = f"video_rascunho{suf}.mp4" if rascunho else f"video{suf}.mp4"
    dst = proj / nome
    tmp = proj / f".{nome}.hf.mp4"
    cmd = [shutil.which("npx") or "npx", "--no-install", "hyperframes", "render", str(comp.resolve()),
           "-o", str(tmp.resolve()), "--format", "mp4", "--fps", str(FPS),
           "-q", "draft" if rascunho else "looks", "--crf", "28" if rascunho else "18"]
    inicio, ultimo = time.time(), [-1]

    def linha(ln):
        pct = _pct(ln)
        if pct is not None and int(pct) != ultimo[0]:
            ultimo[0] = int(pct)
            eta = round((time.time() - inicio) * (100 - pct) / pct) if pct > 0 else None
            _progresso(proj, "render", round(pct, 1), eta)

    _progresso(proj, "render", 0, None)
    rc, ultimas = _executar(cmd, motion_dir, {**os.environ, **ENV_HF}, linha)
    if rc != 0 or not tmp.is_file():
        _progresso(proj, "falha")
        raise RuntimeError("hyperframes render falhou:\n" + "\n".join(ultimas))
    _progresso(proj, "conferindo", 100, 0)
    try:
        _finalizar(tmp, dst, tempos["duracao"])
    except RuntimeError:
        _progresso(proj, "falha")
        raise
    _progresso(proj, "pronto", 100, 0)
    return {"ok": True, "video": str(dst), "duracao": tempos["duracao"]}


def folha(proj: Path, lang: str | None = None) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    video = next((v for v in (proj / f"video{suf}.mp4", proj / f"video_rascunho{suf}.mp4") if v.is_file()), None)
    if video is None:
        raise ValueError("sem video.mp4 nem video_rascunho.mp4: rodar render")
    tempos = pipeline.read_json(proj / f"motion{suf}" / "tempos.json", None)
    if not tempos:
        raise ValueError("tempos.json ausente: rodar montar")
    fim = tempos["duracao"] - 1 / FPS
    pontos = []
    for c in tempos["cenas"]:
        pontos.append((c["id"], "entrada", c["ini"] + min(0.6, c["dur"] / 3)))
        pontos.append((c["id"], "final", c["ini"] + c["dur"] - c["saida"] - 0.1))
        if c["saida"]:
            pontos.append((c["id"], "saida", c["ini"] + c["dur"] - c["saida"] / 2))
    pontos = [(i, r, max(0.0, min(t, fim))) for i, r, t in pontos]
    tmpd = proj / "qc" / f".folha{suf}"
    shutil.rmtree(tmpd, ignore_errors=True)
    tmpd.mkdir(parents=True)
    cols = 6
    linhas = -(-len(pontos) // cols)
    for k in range(cols * linhas):
        dst = str(tmpd / f"f_{k:03d}.png")
        if k < len(pontos):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{pontos[k][2]:.3f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=270:480", dst], check=True)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=270x480",
                            "-frames:v", "1", dst], check=True)
    png = proj / "qc" / f"folha{suf}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmpd / "f_%03d.png"),
                    "-vf", f"tile={cols}x{linhas}:padding=6:color=white", "-frames:v", "1", str(png)], check=True)
    shutil.rmtree(tmpd)
    return {"png": str(png), "frames": [{"id": i, "rotulo": r, "t": round(t, 3)} for i, r, t in pontos]}


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="kit de motion (HyperFrames)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("montar", "render", "folha"):
        p = sub.add_parser(nome)
        p.add_argument("proj")
        p.add_argument("--lang")
        if nome == "render":
            p.add_argument("--rascunho", action="store_true")
    ns = ap.parse_args()
    try:
        if ns.cmd == "montar":
            out = montar(Path(ns.proj), ns.lang)
        elif ns.cmd == "render":
            out = render(Path(ns.proj), ns.rascunho, ns.lang)
        else:
            out = folha(Path(ns.proj), ns.lang)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("ok", True) else 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS (all)

- [ ] **Step 5: Real smoke render (manual, needs `motion/node_modules`)**

Run:
```bash
python -c "import sys; sys.path.insert(0,'ui'); import motion, json, pathlib, tempfile; p=pathlib.Path(tempfile.mkdtemp())/'p'; p.mkdir(); (p/'cenas.json').write_text(json.dumps({'marca':'anotus','cenas':[{'id':'c01','tipo':'frase','linhas':[{'t':'Pare de'},{'t':'decorar.','estilo':'display','anim':'letras','destaque':['marca-texto','risco']}],'saida':{'transicao':'iris','dur':0.47}},{'id':'c02','tipo':'numero','valor':1250,'legenda':'usuários'},{'id':'c03','tipo':'endcard'}]}),encoding='utf-8'); print(motion.render(p)); print(motion.folha(p))"
```
Expected: `{"ok": true, ...}` and a `folha.png`. Look at the folha image (Read). Check: the iris with a gold ring at the transition, the counter on its final number, the real fonts, and the wordmark. If HyperFrames' progress output doesn't match `_pct` (state stuck at 0 until the end), record one real progress line in a comment next to `PCT_RE` and adjust the regex. Rendering still has to work without progress.

- [ ] **Step 6: Commit**

```bash
git add ui/motion.py ui/test_motion.py
git commit -m "feat(motion): render via hyperframes travado, conferência ffprobe, folha e CLI"
```

---

### Task 6: Amostras + teste golden (com revisão visual)

**Files:**
- Create: `motion/amostras/projeto/cenas.json`, `motion/amostras/projeto/c07.html`, `motion/amostras/ref/*.png` (gerados)
- Test: `ui/test_motion_golden.py`

**Interfaces:**
- Consumes: `motion.render`, `motion._probe`, `tempos.json`.
- Produces: golden opt-in via `MOTION_GOLDEN=1` (comparar) / `MOTION_GOLDEN=atualizar` (regravar).

- [ ] **Step 1: Write the samples**

`motion/amostras/projeto/cenas.json`:
```json
{
  "marca": "anotus",
  "aspecto": "9:16",
  "cenas": [
    {"id": "c01", "tipo": "frase", "linhas": [
      {"t": "Pare de", "estilo": "punch"},
      {"t": "decorar ação.", "estilo": "display", "anim": "letras", "destaque": ["marca-texto", "risco"]}],
     "saida": {"transicao": "iris", "dur": 0.47}},
    {"id": "c02", "tipo": "frase", "fundo": "marca", "linhas": [
      {"t": "Comece a", "estilo": "punch"},
      {"t": "entender", "estilo": "display", "anim": "mascara", "cor": "acento", "destaque": ["assinatura"]}],
     "saida": {"transicao": "wipe", "dur": 0.4}},
    {"id": "c03", "tipo": "numero", "valor": 1250, "legenda": "alunos aprovados"},
    {"id": "c04", "tipo": "lista", "titulo": "Três passos", "itens": ["Grifar o essencial", "Revisar no dia certo", "Lembrar na prova"]},
    {"id": "c05", "tipo": "tela", "arquivo": "tela.png", "label": "Busca"},
    {"id": "c06", "tipo": "tela", "arquivo": "clip.mp4", "moldura": "browser"},
    {"id": "c07", "tipo": "custom", "html": "c07.html", "dur": 2.5},
    {"id": "c08", "tipo": "endcard"}
  ]
}
```

`motion/amostras/projeto/c07.html`:
```html
<div class="k-linha k-display k-cor-tinta" data-k-texto><span class="k-txt" id="c07-t">custom</span></div>
<script>
KIT.custom((c) => {
  const alvo = c.layer.querySelector("#c07-t");
  c.el.appendChild(alvo.parentElement);
  return c.C.mascara(c.tl, alvo, c.t0);
});
</script>
```

- [ ] **Step 2: Write the golden test**

`ui/test_motion_golden.py`:
```python
"""Golden do kit: renderiza motion/amostras nas duas marcas e compara frames com
motion/amostras/ref/. Lento e opt-in: MOTION_GOLDEN=1 (comparar) ou
MOTION_GOLDEN=atualizar (regravar referências — revisar as imagens antes de commitar).
Upgrade do hyperframes só com este teste passando."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import motion

MODO = os.environ.get("MOTION_GOLDEN")
AMOSTRAS = motion.MOTION / "amostras"
REF = AMOSTRAS / "ref"
pytestmark = pytest.mark.skipif(
    not MODO or not (motion.MOTION / "node_modules" / "hyperframes").is_dir() or shutil.which("ffmpeg") is None,
    reason="golden opt-in (MOTION_GOLDEN) e precisa de motion/node_modules")


def _ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def _psnr(a: Path, b: Path) -> float:
    r = subprocess.run(["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "psnr", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"average:(inf|[\d.]+)", r.stderr)
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


def _luma_faixa(png: Path, crop: str) -> float:
    r = subprocess.run(["ffmpeg", "-i", str(png), "-vf", f"crop={crop},signalstats,metadata=print",
                        "-f", "null", "-"], capture_output=True, text=True)
    lo = float(re.search(r"YMIN=([\d.]+)", r.stderr).group(1))
    hi = float(re.search(r"YMAX=([\d.]+)", r.stderr).group(1))
    return hi - lo


def _frame(video: Path, t: float, dst: Path) -> Path:
    _ff("-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dst))
    return dst


@pytest.mark.parametrize("marca", ["anotus", "campeio"])
def test_golden(tmp_path, marca):
    p = tmp_path / marca
    shutil.copytree(AMOSTRAS / "projeto", p)
    d = json.loads((p / "cenas.json").read_text(encoding="utf-8"))
    d["marca"] = marca
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(p / "tela.png"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-pix_fmt", "yuv420p", str(p / "clip.mp4"))
    r = motion.render(p)
    assert r["ok"], r
    video = p / "video.mp4"
    tempos = json.loads((p / "motion" / "tempos.json").read_text(encoding="utf-8"))
    cenas = {c["id"]: c for c in tempos["cenas"]}

    # Review Focus 1: contador e grão mudam com o tempo (pintores rodam no seek do HyperFrames)
    c3 = cenas["c03"]
    a = _frame(video, c3["ini"] + 0.7, tmp_path / "cont-a.png")
    b = _frame(video, c3["ini"] + 1.1, tmp_path / "cont-b.png")
    assert _psnr(a, b) < 40, "contador/grão parados entre dois instantes"
    # Review Focus 2: vídeo dentro da moldura browser aparece (não fica preto)
    c6 = cenas["c06"]
    v = _frame(video, c6["ini"] + c6["dur"] - c6["saida"] - 0.1, tmp_path / "video.png")
    assert _luma_faixa(v, "960:600:60:560") > 50, "clipe da cena tela não apareceu"

    REF.mkdir(parents=True, exist_ok=True)
    ruins = []
    for c in tempos["cenas"]:
        pts = [("final", c["ini"] + c["dur"] - c["saida"] - 0.05)]
        if c["saida"]:
            pts.append(("saida", c["ini"] + c["dur"] - c["saida"] / 2))
        for rot, t in pts:
            png = _frame(video, t, tmp_path / f"{marca}-{c['id']}-{rot}.png")
            ref = REF / png.name
            if MODO == "atualizar":
                shutil.copy2(png, ref)
                continue
            assert ref.exists(), f"sem referência {ref.name}: rodar MOTION_GOLDEN=atualizar"
            if (val := _psnr(png, ref)) < 35:
                ruins.append(f"{png.name}: {val:.1f} dB")
    assert not ruins, ruins
```

- [ ] **Step 3: Generate the references**

Run (Git Bash): `MOTION_GOLDEN=atualizar python -m pytest ui/test_motion_golden.py -q`
Expected: PASS (2 passed), with `motion/amostras/ref/*.png` created.
If the Review Focus asserts fail (static counter, or black video):
- Static counter: the cause is HyperFrames seeking with callbacks suppressed. Move the `pintores` call into a tween that is always active. Add `tl.to(window, { duration: total, ease: "none", onUpdate: pintar }, 0)` before `tl.to({}, { duration: 0 }, total)` in `montar()`. Then rerun.
- Black video: check in the HyperFrames docs (`npx hyperframes docs` or the repo README) how a nested `<video>` should be declared. Adjust `_html`.

- [ ] **Step 4: Visual review of the references (mandatory)**

Look at each `motion/amostras/ref/*.png` (Read). Write the checklist in your report:
- Fonts: Fraunces italic in the Anotus display, and Archivo in Campeio. Never a generic serif or sans.
- Accents: "ação" renders correctly.
- Highlighter behind the word and strike crossing it.
- Iris mid-transition: purple/green circle with a thin ring in the accent colour, and no brownish band.
- Wipe left to right.
- Counter: final value "1.250" in Anotus; in Campeio, in mono.
- List with "01 02 03" markers.
- Phone frame with a pill on top, and browser window with 3 dots and URL.
- End card: brand, signature (dot or icon), tagline, CTA pill and url.
- Wordmark in the footer, and no wordmark on the end card.
- Campeio: progress bar at the top.

Anything wrong gets fixed in `kit.css`/`kit.js`. Then regenerate the references and look again.

- [ ] **Step 5: Confirm comparison mode**

Run: `MOTION_GOLDEN=1 python -m pytest ui/test_motion_golden.py -q`
Expected: PASS (determinism: same render gives PSNR ≥ 35 dB)

Run: `python -m pytest ui/test_motion.py ui/test_motion_golden.py -q`
Expected: the unit tests PASS and the golden is SKIPPED (no env).

- [ ] **Step 6: Commit**

```bash
git add motion/amostras ui/test_motion_golden.py motion/kit
git commit -m "test(motion): amostras e golden das duas marcas (opt-in MOTION_GOLDEN)"
```

---

### Task 7: Dublagem: `localiza.py` lê e aplica `cenas.json`

**Files:**
- Modify: `ui/localiza.py` (`extrair` ~85-119, `aplicar` ~178-243)
- Test: `ui/test_localiza.py`

**Interfaces:**
- Consumes: formato `cenas.json` (T2).
- Produces:
  - `localiza.extrair([...cenas.json], saida)` grava textos com `contextos: ["cenas"]`;
  - `localiza.aplicar(textos, "cenas.json", "cenas.<lang>.json")` grava o JSON traduzido e devolve `{substituicoes, arquivos, nao_encontrados}`.

- [ ] **Step 1: Write the failing tests**

Append to `ui/test_localiza.py`:
```python
CENAS = {"marca": "anotus", "cenas": [
    {"id": "c01", "tipo": "frase", "linhas": [{"t": "Pare de", "estilo": "punch"}, {"t": "decorar.", "estilo": "display"}]},
    {"id": "c02", "tipo": "lista", "titulo": "Três passos", "itens": ["Grifar", "Revisar"]},
    {"id": "c03", "tipo": "endcard", "cta": "Teste grátis", "url": "anotus.app"}]}


def test_extrair_cenas_json(tmp_path):
    c = _arq(tmp_path, "cenas.json", json.dumps(CENAS, ensure_ascii=False))
    t = localiza.extrair([c], tmp_path / "dub" / "textos.json")["textos"]
    assert set(t) == {"Pare de", "decorar.", "Três passos", "Grifar", "Revisar", "Teste grátis", "anotus.app"}
    assert t["Grifar"]["contextos"] == ["cenas"] and t["Grifar"]["arquivos"] == ["cenas.json"]
    assert "punch" not in t and "anotus" not in t      # só campos de texto, nunca enums/marca


def test_aplicar_cenas_json(tmp_path):
    c = _arq(tmp_path, "cenas.json", json.dumps(CENAS, ensure_ascii=False))
    tx = tmp_path / "textos.json"
    localiza.extrair([c], tx)
    d = json.loads(tx.read_text(encoding="utf-8"))
    trad = {"Pare de": "Stop", "decorar.": "memorizing.", "Três passos": "Three steps", "Grifar": "Highlight",
            "Revisar": "Review", "Teste grátis": "Free trial", "anotus.app": "="}
    for k, v in d["textos"].items():
        v["trad"] = trad[k]
    tx.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = localiza.aplicar(tx, c, tmp_path / "cenas.en.json")
    out = json.loads((tmp_path / "cenas.en.json").read_text(encoding="utf-8"))
    assert out["cenas"][0]["linhas"][0] == {"t": "Stop", "estilo": "punch"}
    assert out["cenas"][1]["itens"] == ["Highlight", "Review"] and out["cenas"][2]["url"] == "anotus.app"
    assert r["nao_encontrados"] == [] and r["substituicoes"] == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ui/test_localiza.py -q -k cenas`
Expected: FAIL. `extrair` tries to parse the JSON as TSX and returns other texts, or no texts.

- [ ] **Step 3: Implement**

In `ui/localiza.py`, after `EXT_EXTRAIR = {...}`, add:
```python
CAMPOS_CENAS = ("titulo", "legenda", "label", "cta", "tagline", "url", "prefixo", "sufixo")


def _textos_cenas(dados):
    """(container, chave) de cada texto visível de um cenas.json do kit de motion."""
    cenas = dados.get("cenas") if isinstance(dados, dict) else None
    for c in cenas if isinstance(cenas, list) else []:
        if not isinstance(c, dict):
            continue
        for ln in c.get("linhas") if isinstance(c.get("linhas"), list) else []:
            if isinstance(ln, dict) and isinstance(ln.get("t"), str):
                yield ln, "t"
        itens = c.get("itens")
        if isinstance(itens, list):
            for k, v in enumerate(itens):
                if isinstance(v, str):
                    yield itens, k
        for k in CAMPOS_CENAS:
            if isinstance(c.get(k), str):
                yield c, k


def _de_cenas(txt: str) -> list:
    return [(o[k], "cenas") for o, k in _textos_cenas(json.loads(txt)) if LETRA.search(o[k])]


def _aplicar_cenas(origem: Path, destino: Path, ativos: dict) -> dict:
    if destino.is_dir():
        raise ValueError(f"destino é uma pasta (origem é arquivo): {destino}")
    dados = json.loads(origem.read_text(encoding="utf-8"))
    contagem = {k: 0 for k in ativos}
    for o, k in list(_textos_cenas(dados)):
        n = _norm(o[k])
        if n in ativos:
            o[k] = str(ativos[n]["trad"]).strip()
            contagem[n] += 1
    pipeline.atomic_write_json(destino, dados)
    return {"substituicoes": sum(contagem.values()), "arquivos": [str(destino)],
            "nao_encontrados": [ativos[k].get("id", k) for k, n in contagem.items() if n == 0]}
```
In `extrair`, replace:
```python
        brutos = _de_html(txt) if arq.suffix.lower() in (".html", ".htm") else _de_tsx(txt)
```
with:
```python
        suf = arq.suffix.lower()
        brutos = _de_html(txt) if suf in (".html", ".htm") else _de_cenas(txt) if suf == ".json" else _de_tsx(txt)
```
In `aplicar`, right after the line `raise ValueError("destino não pode ser a origem, ficar dentro dela nem contê-la")`, insert:
```python
    # chave normalizada: chave editada à mão com espaço extra/&nbsp; ainda casa
    # (chave vazia após normalizar viraria alternativa "" no regex e casaria em todo lugar)
    ativos = {_norm(k): v for k, v in tx.items() if _norm(k) and str(v["trad"]).strip() != "="}
    if origem.is_file() and origem.suffix.lower() == ".json":
        return _aplicar_cenas(origem, destino, ativos)
```
Then delete the old block further down (the two comment lines and the `ativos = ...` line) that sits just before `contagem = {k: 0 for k in ativos}`. That way `ativos` is defined only once.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest ui/test_localiza.py -q`
Expected: PASS (all, including the previous ones)

- [ ] **Step 5: Commit**

```bash
git add ui/localiza.py ui/test_localiza.py
git commit -m "feat(localiza): extrair/aplicar textos de cenas.json do kit de motion"
```

---

### Task 8: Protocolo: eventos, receitas, CLAUDE.md e spec

**Files:**
- Modify: `ui/eventos.py:21-22`, `Formatos/padrao-ads.md`, `Formatos/dublagem.md`, `edit/shorts/campeio/BRAND.md` (fora do git: editar mesmo assim, não commitar), `CLAUDE.md`, `docs/superpowers/specs/2026-10-08-motion-kit-design.md`
- Test: `ui/test_eventos.py` (suite existente)

**Interfaces:**
- Consumes: CLI from T5, `cenas.json` from T2–T4.
- Produces: assunto de decisão `motion`; receitas apontando para `ui/motion.py`.

- [ ] **Step 1: Add the `motion` decision subject**

In `ui/eventos.py`, replace:
```python
ASSUNTOS = ("provedor", "trilha", "sfx", "broll", "corte", "grade", "zoom", "overlay",
            "legenda", "conceito", "clipe", "thumbnail", "render", "outro")
```
with:
```python
ASSUNTOS = ("provedor", "trilha", "sfx", "broll", "corte", "grade", "zoom", "overlay",
            "legenda", "conceito", "clipe", "thumbnail", "render", "motion", "outro")
```
Run: `python -m pytest ui/test_eventos.py -q`
Expected: PASS

- [ ] **Step 2: `Formatos/padrao-ads.md`**

Replace the block from `**Motion graphics** (100% determinístico, sem GSAP/Remotion):` through item `3. Montagem: ...` with:
```markdown
**Motion graphics** (kit HyperFrames em `motion/`, CLI `ui/motion.py`; spec `docs/superpowers/specs/2026-10-08-motion-kit-design.md`):
1. Do `roteiro.md` aprovado, escrever `edit/shorts/<marca>/<tema>/cenas.json`: `{"marca": "anotus|campeio", "cenas": [...]}`,
   tipos `frase | numero | lista | tela | endcard | custom`. Só papéis: `fundo` claro/escuro/marca, `estilo`
   display/punch/corpo/mono, `cor` tinta/acento/sobre, `destaque` marca-texto/risco/assinatura, `saida`
   `{transicao: fade|wipe|iris, dur}` (padrão: fade 0,3 s). Tempo é automático; `dur`/`em` só para casar com fala ou trilha.
   Exemplo completo: `motion/amostras/projeto/cenas.json`.
2. `python ui/motion.py montar edit/shorts/<marca>/<tema>` → corrigir até `ok` (erros vêm com o id da cena: safe area,
   linha que estoura, fonte em fallback, `dur` abaixo do mínimo). Grava `cues.json` e a pasta gerada `motion/` (não editar à mão).
3. `python ui/motion.py render <proj> --rascunho` → `python ui/motion.py folha <proj>` (QC rápido) → ajustar `cenas.json` →
   `python ui/motion.py render <proj>` → `video.mp4` mudo 1080x1920@30.
4. Fora do catálogo: `{"id": "cNN", "tipo": "custom", "html": "cenas/cNN.html", "dur": s}` — fragmento HTML com
   `<script>KIT.custom((c) => { ...; return fim; })</script>` usando `c.C` (palavras, letras, mascara, fade, marcaTexto,
   risco, assinatura, contador, kenBurns), `c.tl`, `c.t0`, `c.cue`. Custom repetido em 2+ vídeos vira tipo no kit
   (`motion/kit/kit.js`) e decisão `motion` no log.
5. Primeira vez na máquina: `cd motion && npm ci`.
```
Replace the line starting with `- Cada \`anim.html\` exporta \`cues.json\` ao lado:` and its continuation with:
```markdown
- `motion.py montar` grava `cues.json` ao lado: `[{"t": 1.23, "som": "pop-dourado", "ganho_db": -6}]`, a partir dos eventos
  do kit (assinatura = `pop-dourado`, letras/máscara = `whoosh-reveal`, pill/CTA = `click-pill`, end card = `sting-endcard`,
  contador = `tick`, palavras subindo = `rise`). Ajuste fino: editar o `cues.json` depois do `montar` final.
```
In "Cenas por IA", replace the item `- Montagem por ffmpeg (sem \`<video>\` no \`anim.html\`, que é só motion por \`seek\`):` and its command line with:
```markdown
- Montagem: o clipe aprovado entra como cena `{"tipo": "tela", "arquivo": "broll/cand/c01-ia1.mp4", "moldura": "nenhuma"}`
  (ou `celular`/`browser`); `dur` padrão = duração do arquivo.
```
In "QC antes de entregar", item 1, replace it with:
```markdown
1. `python ui/motion.py folha <proj>` (entrada, estado final e meio da transição de cada cena) + frames nas bordas de cena.
```
At the end of "Técnica de produção", before **Encode padrão**, add:
```markdown
**Ads legados (capture.js)**: os vídeos de antes do kit (`anim.html` + `window.seek` + Playwright) continuam como estão;
só para manutenção deles. Vídeo novo = kit.
```

- [ ] **Step 3: `Formatos/dublagem.md`**

In step 5, replace the line starting with `Ads: \`python ui/localiza.py extrair edit/shorts/<marca>/<tema>/anim.html` with:
```markdown
   Ads (kit): `python ui/localiza.py extrair edit/shorts/<marca>/<tema>/cenas.json --saida edit/shorts/<marca>/<tema>/dub/<lang>/textos.json`
   (+ os `cenas/*.html` de cenas custom, se houver). Ads legados: o mesmo com `anim.html`.
```
In step 11, replace the `Ads:` item with:
```markdown
11. Ads (kit): `python ui/localiza.py aplicar edit/shorts/<marca>/<tema>/dub/<lang>/textos.json edit/shorts/<marca>/<tema>/cenas.json edit/shorts/<marca>/<tema>/cenas.<lang>.json`
    (`nao_encontrados` não vazio → como no passo 9); `python ui/motion.py montar <proj> --lang <lang>` (estouro de texto
    traduzido vira erro com o id da cena → encurtar a tradução); `python ui/motion.py render <proj> --lang <lang>` →
    `video.<lang>.mp4` + `cues.<lang>.json`; SFX/trilha como em `padrao-ads.md` → `…-<lang>.mp4`.
    Ads legados (`anim.html`): `aplicar` para `anim.<lang>.html` + `localiza.py checar` (comparar com o original) + captura antiga.
```

- [ ] **Step 4: `edit/shorts/campeio/BRAND.md`**

Replace the section `## Técnica (igual anotus, ...)` and its 4 items with:
```markdown
## Técnica
Kit de motion: tema `motion/temas/campeio.json` (paleta, Archivo/IBM Plex Mono, ícone como assinatura, barra de
progresso). Fluxo em `Formatos/padrao-ads.md` › Motion graphics. Este arquivo continua a fonte da identidade;
mudou aqui → atualizar o tema.
```
(This file is gitignored and is not committed. It's a local edit for whoever operates the pipeline.)

- [ ] **Step 5: `CLAUDE.md`**

After the paragraph that starts with `Shorts: \`Formatos/padrao-youtube-shorts.md\``, add:
```markdown
Motion de reel/ad: só via `python ui/motion.py` (kit HyperFrames em `motion/`, `cenas.json` por vídeo); cena
`custom` repetida em 2+ vídeos vira tipo no kit. Upgrade do hyperframes só com `MOTION_GOLDEN=1` passando.
```

- [ ] **Step 6: Align the spec with the plan's adjustments**

In `docs/superpowers/specs/2026-10-08-motion-kit-design.md`, apply the 7 "Ajustes ao spec" from this plan:
- **Estrutura:** remove `componentes.js`, `transicoes/` and `cenas/`, replacing them with `kit.js` + `kit.css`. `amostras/projeto/`.
- **`montar` item 2:** single composition, scenes as `.clip` of the root.
- **Campos:** `estilo` display/punch/corpo/mono and `cor` tinta/acento/sobre. In `tela`, the `label` is the pill. `tema.fixos` has no pill, and `transicao_padrao` = `{transicao, dur}`.
- **CLI:** `--lang` instead of `--cenas`. `--rascunho` = draft quality in 1080x1920.
- **Env:** telemetry turned off.
- **`dur` de `tela`:** 3 s for an image; for a video, the length of the file.

- [ ] **Step 7: Final run and commit**

Run: `python -m pytest ui -q`
Expected: PASS (golden skipped without env)

```bash
git add ui/eventos.py Formatos/padrao-ads.md Formatos/dublagem.md CLAUDE.md docs/superpowers/specs/2026-10-08-motion-kit-design.md
git commit -m "docs(motion): receitas, dublagem e protocolo apontando para o kit; spec alinhado ao plano"
```
