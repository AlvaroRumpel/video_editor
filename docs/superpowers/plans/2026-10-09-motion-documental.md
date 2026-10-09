# Motion documental sincronizado à fala — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vídeo narrado 16:9 com motion que segue a fala palavra a palavra (mapa de época com câmera, rotas, contadores, palavras cinéticas, transições ligadas), vinheta de abertura, tela final de 20 s, trilha com ducking e SFX.

**Architecture:** `ui/alinhar.py` dá o tempo de cada palavra do roteiro (faster-whisper local + casamento com o texto). `narrado.py` valida a direção (`mapa`, `fundo`, `beats` no `episodio.json`), resolve cada beat para segundos e escreve `cenas.<lang>.json` em `"modo": "doc"` com cenas `doc`, `vinheta` e `telafinal`. O kit ganha ganchos de registro (`KIT.tipo`, `KIT.transicao`, `KIT.pintor`, `KIT.cue`) e um módulo novo `motion/kit/doc.js` que implementa palco com câmera, beats e transições como pintores (estado em função do tempo). `audio.py` sintetiza o kit de SFX e ganha realce de trilha por trecho.

**Tech Stack:** Python 3.14 (stdlib, Pillow, numpy via faster-whisper), faster-whisper `small` int8 CPU, ffmpeg, HyperFrames 0.8.141 + GSAP 3.14.2 (Chromium headless), pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-motion-documental-design.md` (branch `feat/motion-documental`). Spike de referência (HTML do teste B, descartável): `C:\Users\alvar\AppData\Local\Temp\claude\D--Projetos-dark-videos\c6d3c4fb-d375-4b2e-9e8e-226965265828\scratchpad\spike\b\index.html`.

## Global Constraints

- Custo zero: nada de API paga; faster-whisper roda local; SFX sintetizados; trilha da YouTube Audio Library baixada pelo usuário.
- Cena sem `beats` renderiza como hoje; reels/ads (`kit.js` sem `"modo": "doc"`) não mudam de comportamento.
- Tudo que depende do tempo no kit é **pintor** (`KIT.pintor(fn)`, chamado a cada seek) — nunca `onUpdate` (o seek do HyperFrames suprime eventos).
- Todo `fromTo` que começa depois de t=0 usa `immediateRender: false` (exceto opacidade de entrada da camada na transição, que deve valer desde o início).
- Ritmo: trecho > 6 s de fala sem beat nem troca de cena = aviso no rascunho, erro no render final.
- Loudness final −14 LUFS integrado, true peak ≤ −1 dBTP (`loudnorm=I=-14:TP=-1:LRA=11`, já usado em `audio.mix_trilha`).
- Alinhamento com < 70% das palavras casadas numa cena = erro com o id da cena.
- Licenças de imagem aceitas: as de `narrado.licenca_ok` (PD, CC0, CC BY, CC BY-SA).
- True crime: sem beat ilustrativo de violência (regra de direção, não de código).
- Textos visíveis nos beats seguem `{"pt": ...}` (resolvidos por `narrado._loc`).
- IDs de cena seguem `c[0-9]{2,}`; vinheta = `c900`, tela final = `c901`.
- Rodar testes a partir de `D:\Projetos\video_editor`: `python -m pytest ui/<arquivo>.py -q`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; prefixar git com `rtk`.

## Review Focus

1. Palavra do `em` que aparece mais de uma vez na cena (ex.: "de", "água") → o beat cai na ocorrência certa; `"água#2"` pega a segunda. Teste no Task 2.
2. Texto da cena editado depois do `alinhar` → `escrever_cenas` recusa com "rode alinhar" em vez de animar com tempos velhos. Teste no Task 8.
3. Número dito por extenso e transcrito de outro jeito ("mil seiscentos e vinte e nove" × "1629", "3.000" × "três mil") → mesmo token nos dois lados. Teste no Task 1.
4. Texto de beat longo (citação, rótulo) estourando a safe area 16:9 → `montar` devolve erro de layout em vez de vídeo cortado. Teste no Task 5.
5. Episódio sem `vinheta_apos` ou sem `mapa` → sem vinheta, tela final sem mapa ao fundo, render não quebra. Teste no Task 8.

---

### Task 1: `ui/alinhar.py` — tokens, números e casamento texto × transcrição

**Files:**
- Create: `ui/alinhar.py`
- Create: `ui/test_alinhar.py`
- Modify: `ui/requirements.txt` (acrescentar `faster-whisper`)

**Interfaces:**
- Produces:
  - `alinhar.tokens(texto: str) -> list[dict]` — `[{"w": str, "frase": bool}]`; `w` normalizado (minúsculas, sem acento/pontuação, números juntados em dígitos); `frase` = token começa frase.
  - `alinhar.casar(texto: str, transcricao: list[tuple[str, float, float]]) -> list[dict]` — `[{"w", "s", "e"}]`, um por token de `tokens(texto)`, mesma ordem e tamanho. `ValueError` se < 70% casado.
  - `alinhar.transcrever(mp3: Path, lang: str, modelo: str = "small") -> list[tuple[str, float, float]]`
  - `alinhar.alinhar(proj: Path, lang: str, _transcrever=None) -> dict` — grava `<proj>/<lang>/palavras.json` = `{"cNN": {"hash": str, "palavras": [{"w","s","e"}]}}`; devolve `{"ok": True, "alinhadas": [ids]}`.

- [ ] **Step 1: Escrever os testes**

`ui/test_alinhar.py`:
```python
import json
from pathlib import Path

import pytest

import alinhar


def ws(texto):
    return [t["w"] for t in alinhar.tokens(texto)]


def test_tokens_normaliza_e_marca_frases():
    t = alinhar.tokens("Em junho de 1629, cerca de trezentas pessoas. Muitas morreram.")
    assert [x["w"] for x in t] == ["em", "junho", "de", "1629", "cerca", "de", "300", "pessoas", "muitas", "morreram"]
    assert [x["frase"] for x in t] == [True, False, False, False, False, False, False, False, True, False]


@pytest.mark.parametrize("texto, esperado", [
    ("trezentas e quarenta e uma pessoas", ["341", "pessoas"]),
    ("a uns três mil quilômetros", ["a", "uns", "3000", "quilometros"]),
    ("mil seiscentos e vinte e nove", ["1629"]),
    ("3.000 km", ["3000", "km"]),
    ("em 1628. 341 pessoas", ["em", "1628", "341", "pessoas"]),   # não junta através da frase
    ("cinco e meia", ["5", "e", "meia"]),                          # "e" sem número depois não junta
])
def test_numeros(texto, esperado):
    assert ws(texto) == esperado


def test_casar_extenso_x_digitos():
    tr = [("cerca", 0.0, 0.2), ("de", 0.2, 0.3), ("300", 0.3, 0.6), ("pessoas", 0.6, 1.0), ("a", 1.0, 1.1),
          ("uns", 1.1, 1.3), ("3", 1.3, 1.4), ("mil", 1.4, 1.6), ("quilômetros.", 1.6, 2.2)]
    r = alinhar.casar("cerca de trezentas pessoas a uns três mil quilômetros", tr)
    assert [x["w"] for x in r] == ["cerca", "de", "300", "pessoas", "a", "uns", "3000", "quilometros"]
    assert (r[2]["s"], r[2]["e"]) == (0.3, 0.6)
    assert (r[6]["s"], r[6]["e"]) == (1.3, 1.6)


def test_casar_interpola_palavra_omitida():
    tr = [("cerca", 0.0, 0.2), ("300", 0.6, 0.9), ("pessoas", 0.9, 1.2)]      # whisper perdeu o "de"
    r = alinhar.casar("cerca de trezentas pessoas", tr)
    assert r[1]["w"] == "de" and 0.2 <= r[1]["s"] < r[1]["e"] <= 0.6


def test_casar_poucas_casadas_e_erro():
    with pytest.raises(ValueError, match="casadas"):
        alinhar.casar("o navio bateu no recife", [("bom", 0, 1), ("dia", 1, 2)])


def _proj(tmp_path):
    p = tmp_path / "ep"
    (p / "pt" / "audio").mkdir(parents=True)
    ep = {"id": "ep", "marca": "dark-historia", "titulo": {"pt": "x"}, "cenas": [
        {"id": "c01", "texto": {"pt": "Cerca de trezentas pessoas."}, "fontes": []},
        {"id": "c02", "texto": {"pt": "Ilhas sem água."}, "fontes": []}]}
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    st = {c: {"hash": f"h{c}", "audio": f"pt/audio/{c}.mp3", "dur": 2.0} for c in ("c01", "c02")}
    (p / "pt" / "narracao.json").write_text(json.dumps(st), encoding="utf-8")
    for c in ("c01", "c02"):
        (p / "pt" / "audio" / f"{c}.mp3").write_bytes(b"x")
    return p


def test_alinhar_grava_e_usa_cache(tmp_path):
    p = _proj(tmp_path)
    chamadas = []
    falas = {"c01.mp3": [("cerca", 0, .2), ("de", .2, .3), ("300", .3, .6), ("pessoas.", .6, 1)],
             "c02.mp3": [("ilhas", 0, .3), ("sem", .3, .5), ("água.", .5, .9)]}

    def stub(mp3, lang):
        chamadas.append(Path(mp3).name)
        return falas[Path(mp3).name]
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == ["c01", "c02"]
    d = json.loads((p / "pt" / "palavras.json").read_text(encoding="utf-8"))
    assert d["c01"]["hash"] == "hc01" and d["c01"]["palavras"][2] == {"w": "300", "s": 0.3, "e": 0.6}
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == []          # cache
    st = json.loads((p / "pt" / "narracao.json").read_text(encoding="utf-8"))
    st["c02"]["hash"] = "novo"
    (p / "pt" / "narracao.json").write_text(json.dumps(st), encoding="utf-8")
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == ["c02"]
    assert chamadas == ["c01.mp3", "c02.mp3", "c02.mp3"]


def test_alinhar_sem_tts_e_erro(tmp_path):
    p = _proj(tmp_path)
    (p / "pt" / "narracao.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="rode tts.*c01"):
        alinhar.alinhar(p, "pt", _transcrever=lambda m, l: [])


def test_alinhar_erro_cita_a_cena(tmp_path):
    p = _proj(tmp_path)
    with pytest.raises(ValueError, match="c01"):
        alinhar.alinhar(p, "pt", _transcrever=lambda m, l: [("nada", 0, 1)])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_alinhar.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'alinhar'`)

- [ ] **Step 3: Implementar `ui/alinhar.py`**

```python
"""Alinhamento palavra a palavra: áudio da cena (faster-whisper, local) × texto do roteiro.
Saída: tempo de cada token do ROTEIRO (não da transcrição) em <proj>/<lang>/palavras.json,
para os beats do modo documental dispararem na palavra dita."""
import difflib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

MIN_CASADAS = 0.7
NUM = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
       "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
       "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
       "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
       "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
       "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500,
       "quinhentas": 500, "seiscentos": 600, "seiscentas": 600, "setecentos": 700, "setecentas": 700,
       "oitocentos": 800, "oitocentas": 800, "novecentos": 900, "novecentas": 900}
FIM_FRASE = re.compile(r"[.!?…]['\"”»)]*$")
PAUSA = re.compile(r"[.!?…,;:]['\"”»)]*$")
_MODELOS: dict = {}


def _base(w: str) -> str:
    s = unicodedata.normalize("NFD", w.lower())
    return re.sub(r"[^\w]", "", "".join(ch for ch in s if unicodedata.category(ch) != "Mn"))


def _normaliza(palavras) -> list[dict]:
    """[(bruta, a, b)] → [{"w", "a", "b", "fim"}]: base + números juntados ('trezentas e quarenta e uma' → '341',
    '3 mil' → '3000'). Não junta através de pontuação. `fim` = token termina frase."""
    seq = []
    for bruta, a, b in palavras:
        w = _base(bruta)
        if w:
            seq.append({"w": w, "a": a, "b": b, "pausa": bool(PAUSA.search(bruta.strip())),
                        "fim": bool(FIM_FRASE.search(bruta.strip()))})
    out, i = [], 0
    while i < len(seq):
        w = seq[i]["w"]
        if not (w in NUM or w.isdigit() or w == "mil"):
            out.append({k: seq[i][k] for k in ("w", "a", "b", "fim")})
            i += 1
            continue
        total, cur, j = 0, 0, i
        while j < len(seq):
            t = seq[j]["w"]
            if j > i and seq[j - 1]["pausa"]:
                break
            if t in NUM:
                cur += NUM[t]
            elif t.isdigit() and j == i:
                cur += int(t)
            elif t == "mil":
                total += max(cur, 1) * 1000
                cur = 0
            elif t == "e" and j > i and j + 1 < len(seq) and seq[j + 1]["w"] in NUM and not seq[j]["pausa"]:
                pass
            else:
                break
            j += 1
        out.append({"w": str(total + cur), "a": seq[i]["a"], "b": seq[j - 1]["b"], "fim": seq[j - 1]["fim"]})
        i = j
    return out


def tokens(texto: str) -> list[dict]:
    n = _normaliza([(w, k, k) for k, w in enumerate(texto.split())])
    return [{"w": t["w"], "frase": k == 0 or n[k - 1]["fim"]} for k, t in enumerate(n)]


def casar(texto: str, transcricao) -> list[dict]:
    rot = _normaliza([(w, k, k) for k, w in enumerate(texto.split())])
    tra = _normaliza(transcricao)
    A, B = [t["w"] for t in rot], [t["w"] for t in tra]
    tempos: list = [None] * len(A)
    for i, j, n in difflib.SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks():
        for k in range(n):
            tempos[i + k] = (float(tra[j + k]["a"]), float(tra[j + k]["b"]))
    casadas = sum(t is not None for t in tempos)
    if not A or casadas / len(A) < MIN_CASADAS:
        raise ValueError(f"só {casadas}/{len(A)} palavras casadas com a fala (mín. {MIN_CASADAS:.0%}): "
                         f"áudio truncado ou texto mudou depois do TTS")
    k = 0
    while k < len(A):                  # palavras sem par: tempo dividido entre as vizinhas casadas
        if tempos[k] is not None:
            k += 1
            continue
        j = k
        while j < len(A) and tempos[j] is None:
            j += 1
        ini = tempos[k - 1][1] if k > 0 else float(tra[0]["a"])
        fim = tempos[j][0] if j < len(A) else float(tra[-1]["b"])
        passo = max(fim - ini, 0.0) / (j - k)
        for m in range(k, j):
            tempos[m] = (ini + passo * (m - k), ini + passo * (m - k + 1))
        k = j
    return [{"w": A[i], "s": round(tempos[i][0], 3), "e": round(tempos[i][1], 3)} for i in range(len(A))]


def transcrever(mp3: Path, lang: str, modelo: str = "small") -> list:
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper não instalado: pip install -r ui/requirements.txt") from None
    # decodifica com ffmpeg: faster_whisper.decode_audio quebra com o `av` instalado
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if modelo not in _MODELOS:
        try:
            _MODELOS[modelo] = WhisperModel(modelo, device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001 — download/rede: mensagem acionável
            raise RuntimeError(f"modelo whisper '{modelo}' indisponível ({e}); na 1ª vez precisa de rede "
                               f"para baixar ~460 MB: rode `python ui/narrado.py alinhar <proj>` com internet") from None
    segs, _ = _MODELOS[modelo].transcribe(a, language=lang, word_timestamps=True)
    return [(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or [])]


def alinhar(proj: Path, lang: str, _transcrever=None) -> dict:
    import narrado   # import tardio: narrado importa alinhar
    proj = Path(proj)
    ep, st = narrado.ler(proj), narrado.estado(proj, lang)
    dst = narrado._dir(proj, lang) / "palavras.json"
    cache = pipeline.read_json(dst, {})
    cache = cache if isinstance(cache, dict) else {}
    faltam = [c["id"] for c in ep["cenas"] if not st.get(c["id"])]
    if faltam:
        raise ValueError(f"rode tts antes: sem áudio em {', '.join(faltam)}")
    tr, feitas = _transcrever or transcrever, []
    for c in ep["cenas"]:
        s = st[c["id"]]
        if cache.get(c["id"], {}).get("hash") == s["hash"]:
            continue
        try:
            pal = casar(narrado._loc(c["texto"], lang), tr(proj / s["audio"], lang))
        except ValueError as e:
            raise ValueError(f"{c['id']}: {e}") from None
        cache[c["id"]] = {"hash": s["hash"], "palavras": pal}
        pipeline.atomic_write_json(dst, cache)
        feitas.append(c["id"])
    return {"ok": True, "alinhadas": feitas}
```

Em `ui/requirements.txt`, acrescentar a linha:
```
faster-whisper
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_alinhar.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
rtk git add ui/alinhar.py ui/test_alinhar.py ui/requirements.txt
rtk git commit -m "feat(alinhar): tempo de cada palavra do roteiro via faster-whisper local

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `narrado.py` — validar direção e resolver beats em segundos

**Files:**
- Modify: `ui/narrado.py` (imports, constantes, `validar`, novas `_v_arquivo`, `_acha`, `_v_direcao`, `resolver_beats`, `ritmo`)
- Test: `ui/test_narrado.py` (acrescentar no fim)

**Interfaces:**
- Consumes: `alinhar.tokens(texto) -> [{"w","frase"}]`; `palavras.json` no formato do Task 1.
- Produces:
  - `narrado.FAZ: dict[str, tuple[str, ...]]` (campos obrigatórios por beat).
  - `narrado.validar(ep, proj, lang, visuais=True)` passa a validar `mapa`, `vinheta_apos`, `fundo`, `beats` (só quando `visuais=True`).
  - `narrado.resolver_beats(c: dict, lang: str, palavras: dict) -> list[dict]` — beats localizados com `"s"` (segundos desde o início da fala da cena); `palavras` ganha `"ts"`; itens/marcos com `em` ganham `"s"`.
  - `narrado.ritmo(cid: str, beats: list[dict], dur: float) -> list[str]` — avisos de trecho > `RITMO_MAX`.

- [ ] **Step 1: Escrever os testes** (acrescentar em `ui/test_narrado.py`)

```python
def _ep_doc():
    ep = _ep()
    ep["mapa"] = {"src": "assets/foto.png", "fonte_url": "https://commons.wikimedia.org/wiki/File:M.jpg",
                  "licenca": "CC0", "credito": "Blaeu, 1650", "pontos": {"cabo": [100, 900], "abrolhos": [1300, 700]}}
    ep["vinheta_apos"] = "c01"
    ep["cenas"][0]["texto"]["pt"] = "Em junho de 1629, cerca de trezentas pessoas chegaram. Não havia água. Nem água doce."
    ep["cenas"][0]["fundo"] = {"tipo": "mapa"}
    ep["cenas"][0]["beats"] = [
        {"em": "junho", "faz": "data", "t": {"pt": "Junho 1629"}},
        {"faz": "rota", "de": "cabo", "para": "abrolhos", "navio": True},
        {"em": "trezentas", "faz": "contador", "valor": 300, "legenda": {"pt": "sobreviventes"}, "pontos": True},
        {"faz": "palavras", "palavras": ["não", "havia", "água"], "risco": "água"},
        {"em": "água#2", "faz": "ponto", "ponto": "abrolhos", "rotulo": {"pt": "Abrolhos"}}]
    return ep


def _palavras(ep, lang="pt"):
    """palavras.json falso: token k começa em k * 0.5 s."""
    import alinhar
    out = {}
    for c in ep["cenas"]:
        n = len(alinhar.tokens(narrado._loc(c["texto"], lang)))
        out[c["id"]] = {"hash": "h", "palavras": [{"w": "x", "s": k * 0.5, "e": k * 0.5 + 0.4} for k in range(n)]}
    return out


def test_validar_doc_ok(tmp_path):
    p = _proj(tmp_path, _ep_doc())
    assert narrado.validar(narrado.ler(p), p, "pt") == []


@pytest.mark.parametrize("mut, trecho", [
    (lambda e: e["cenas"][0]["beats"].append({"faz": "explodir"}), "faz desconhecido"),
    (lambda e: e["cenas"][0]["beats"].append({"faz": "ponto", "ponto": "batavia"}), "ponto 'batavia' não existe"),
    (lambda e: e["cenas"][0]["beats"].append({"em": "baleia", "faz": "data", "t": {"pt": "x"}}), "palavra 'baleia'"),
    (lambda e: e["cenas"][0]["beats"].append({"faz": "contador", "valor": 9000, "pontos": True}), "pontos só com valor"),
    (lambda e: e["cenas"][0]["beats"].append({"faz": "rota", "de": "cabo"}), "rota precisa de para"),
    (lambda e: e.pop("mapa"), "fundo mapa sem 'mapa'"),
    (lambda e: e.__setitem__("vinheta_apos", "c77"), "vinheta_apos"),
    (lambda e: e["cenas"][0].__setitem__("fundo", {"tipo": "video"}), "fundo.tipo inválido"),
    (lambda e: e["mapa"].__setitem__("licenca", "CC BY-NC"), "licença não aceita"),
])
def test_validar_doc_erros(tmp_path, mut, trecho):
    ep = _ep_doc()
    mut(ep)
    p = _proj(tmp_path, ep)
    erros = narrado.validar(narrado.ler(p), p, "pt")
    assert any(trecho in e["motivo"] for e in erros), erros


def test_resolver_beats_em_frase_palavras_e_ocorrencia():
    ep = _ep_doc()
    b = narrado.resolver_beats(ep["cenas"][0], "pt", _palavras(ep))
    # tokens: em junho de 1629 cerca de 300 pessoas chegaram | nao havia agua | nem agua doce
    assert b[0]["s"] == 0.5 and b[0]["t"] == "Junho 1629"            # "junho" = token 1, texto localizado
    assert b[1]["s"] == 4.5                                           # sem em: início da frase seguinte (token 9)
    assert b[2]["s"] == 3.0 and b[2]["legenda"] == "sobreviventes"   # "trezentas" → "300" = token 6
    assert b[3]["s"] == 4.5 and b[3]["ts"] == [4.5, 5.0, 5.5]        # frase seguinte (token 9) e cada palavra
    assert b[4]["s"] == 6.5                                           # "água#2" = token 13


def test_ritmo_aponta_trecho_parado():
    assert narrado.ritmo("c01", [{"s": 1.0}, {"s": 3.0}], 12.0) == ["c01: 3.0–12.0 s sem beat"]
    assert narrado.ritmo("c01", [{"s": 1.0, "ts": [4.0, 7.0]}], 10.0) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_narrado.py -q -k "doc or resolver_beats or ritmo"`
Expected: FAIL (`AttributeError: module 'narrado' has no attribute 'resolver_beats'` e erros de validação ausentes)

- [ ] **Step 3: Implementar**

Em `ui/narrado.py`, junto aos imports do topo (depois de `import audio  # noqa: E402`):
```python
import alinhar  # noqa: E402
```
Depois de `VISUAIS = (...)`:
```python
FAZ = {"camera": (), "rota": ("de", "para"), "ponto": ("ponto",), "contador": ("valor",), "data": ("t",),
       "rotulo": ("nome",), "palavras": ("palavras",), "citacao": ("t", "autor"), "lista": ("itens",),
       "linha_tempo": ("marcos",), "inserto": ("src", "fonte_url", "licenca", "credito"), "selo": ()}
FUNDOS_DOC = ("mapa", "imagem", "escuro")
RITMO_MAX = 6.0   # s de fala sem beat nem troca de cena
```
Funções novas (antes de `def validar`):
```python
def _v_arquivo(d: dict, proj: Path, err) -> None:
    """Imagem de arquivo (src no projeto + licença aceita + fonte_url + credito)."""
    if motion._dentro(proj, d.get("src")) is None:
        err(f"src não encontrado no projeto: {d.get('src')!r}")
    if not licenca_ok(d.get("licenca")):
        err(f"licença não aceita: {d.get('licenca')!r} (PD, CC0, CC BY, CC BY-SA)")
    if not motion._str(d.get("fonte_url")) or not motion._str(d.get("credito")):
        err("arquivo precisa de fonte_url e credito")


def _acha(ws: list[str], palavra: str, depois: int = 0) -> int | None:
    """Índice do token `palavra` (aceita 'água#2' = 2ª ocorrência) em ws, a partir de `depois`."""
    base, _, n = str(palavra).partition("#")
    alvo = alinhar.tokens(base)
    if not alvo:
        return None
    vez = int(n) if n.isdigit() else 1
    for k in range(depois, len(ws)):
        if ws[k] == alvo[0]["w"]:
            vez -= 1
            if vez == 0:
                return k
    return None


def _v_direcao(ep: dict, c: dict, proj: Path, lang: str, e) -> None:
    mapa = ep.get("mapa") if isinstance(ep.get("mapa"), dict) else {}
    pontos = mapa.get("pontos") if isinstance(mapa.get("pontos"), dict) else {}
    i = c["id"]
    f = c.get("fundo")
    if f is not None:
        t = f.get("tipo") if isinstance(f, dict) else None
        if t not in FUNDOS_DOC:
            e(i, f"fundo.tipo inválido: {t!r} ({'|'.join(FUNDOS_DOC)})")
        elif t == "mapa" and not pontos:
            e(i, "fundo mapa sem 'mapa' com pontos no episódio")
        elif t == "imagem":
            _v_arquivo(f, proj, lambda m: e(i, "fundo: " + m))
    ws = [t["w"] for t in alinhar.tokens(_loc(c.get("texto"), lang) or "")]
    beats = c.get("beats")
    if beats is None:
        return
    if not isinstance(beats, list):
        e(i, "beats precisa ser lista")
        return
    for k, b in enumerate(beats, 1):
        q = f"{i} beat {k}"
        if not isinstance(b, dict) or b.get("faz") not in FAZ:
            e(q, f"faz desconhecido: {(b.get('faz') if isinstance(b, dict) else b)!r} ({'|'.join(FAZ)})")
            continue
        for campo in FAZ[b["faz"]]:
            if campo not in b:
                e(q, f"{b['faz']} precisa de {campo}")
        for nome in [b.get(x) for x in ("de", "para", "ponto")] + list(b.get("via", [])):
            if nome is not None and nome not in pontos:
                e(q, f"ponto {nome!r} não existe no mapa")
        sub = [x for x in (b.get("itens") or []) + (b.get("marcos") or []) if isinstance(x, dict)]
        for w in [b.get("em")] + [x.get("em") for x in sub] + list(b.get("palavras") or []):
            if w and _acha(ws, w) is None:
                e(q, f"palavra {w!r} não está no texto da cena")
        if b["faz"] == "contador" and b.get("pontos") and not (
                isinstance(b.get("valor"), int) and not isinstance(b["valor"], bool) and 0 < b["valor"] <= 500):
            e(q, "pontos só com valor inteiro entre 1 e 500")
        if b["faz"] == "inserto":
            _v_arquivo(b, proj, lambda m, q=q: e(q, m))
```
Em `validar`, logo após a linha `achados = _achados(proj)` / bloco `if achados is None:` acrescentar:
```python
    if visuais and "mapa" in ep:
        m = ep["mapa"]
        if not isinstance(m, dict) or not isinstance(m.get("pontos"), dict) or not m["pontos"] or not all(
                isinstance(v, list) and len(v) == 2 and all(motion._num(x) for x in v) for v in m["pontos"].values()):
            e("mapa", "mapa precisa de pontos {nome: [x, y]} em pixels do arquivo")
        if isinstance(m, dict):
            _v_arquivo(m, proj, lambda msg: e("mapa", msg))
    ids = {c.get("id") for c in cenas if isinstance(c, dict)}
    if "vinheta_apos" in ep and ep["vinheta_apos"] not in ids:
        e("raiz", f"vinheta_apos aponta para cena inexistente: {ep['vinheta_apos']!r}")
```
E dentro do laço das cenas, imediatamente depois de `if not visuais: continue`:
```python
        _v_direcao(ep, c, proj, lang, e)
```
Funções de resolução (depois de `validar`):
```python
def resolver_beats(c: dict, lang: str, palavras: dict) -> list[dict]:
    """Beats da cena localizados, com "s" = segundos desde o início da fala da cena.
    Sem "em": início da frase seguinte à do beat anterior (1º beat: início da fala)."""
    toks = alinhar.tokens(_loc(c["texto"], lang))
    ws = [t["w"] for t in toks]
    pal = palavras[c["id"]]["palavras"]
    frases = [k for k, t in enumerate(toks) if t["frase"]]
    out, ult = [], -1
    for b in c.get("beats", []):
        b = _loc(copy.deepcopy(b), lang)
        if b.get("em"):
            k = _acha(ws, b["em"])
        elif ult < 0:
            k = 0
        else:
            k = next((f for f in frases if f > ult), ult)
        b["s"], ult = pal[k]["s"], k
        if b["faz"] == "palavras":
            ts, d = [], k
            for w in b["palavras"]:
                d = _acha(ws, w, d)
                ts.append(pal[d]["s"])
                d += 1
            b["ts"] = ts
        for lst in ("itens", "marcos"):
            for it in b.get(lst) or []:
                if isinstance(it, dict) and it.get("em"):
                    it["s"] = pal[_acha(ws, it["em"])]["s"]
        out.append(b)
    return out


def ritmo(cid: str, beats: list[dict], dur: float) -> list[str]:
    ts = sorted({0.0, float(dur), *(b["s"] for b in beats), *(t for b in beats for t in b.get("ts", []))})
    return [f"{cid}: {a:.1f}–{b:.1f} s sem beat" for a, b in zip(ts, ts[1:]) if b - a > RITMO_MAX]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_narrado.py -q`
Expected: PASS (inclusive os testes antigos)

- [ ] **Step 5: Commit**

```bash
rtk git add ui/narrado.py ui/test_narrado.py
rtk git commit -m "feat(narrado): valida direção (mapa, fundo, beats) e resolve beats na palavra dita

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: ganchos do kit + `motion.py` em modo doc + esqueleto `doc.js`

**Files:**
- Modify: `motion/kit/kit.js` (registro de tipos/transições/pintores; `c.fala`, `c.cena`, `c.entra`; camada anterior na transição)
- Create: `motion/kit/doc.js` (esqueleto com `doc`, `vinheta`, `telafinal` mínimos)
- Modify: `ui/motion.py` (`TIPOS`, `TRANSICOES`, `FUNDO_PADRAO`, `VALIDA_TIPO`, `validar` (modo/mapa), `_tema_js` (tagline), `_preparar` (mídias doc), `HTML` + `_html` (doc.js e mapa))
- Test: `ui/test_motion.py` (acrescentar)

**Interfaces:**
- Produces (JS): `KIT.tipo(nome, fn(c, cena) -> number)`, `KIT.transicao(nome, fn(tl, cam, t, d, tema, anterior))`, `KIT.pintor(fn(t))`, `KIT.cue(t, som, ganho_db=-6)`. Objeto `c` ganha `fala` (instante absoluto em que a fala da cena começa = `ini + dur da transição de entrada`), `cena`, `entra` (nome da transição de entrada ou `null`).
- Produces (cenas.json, modo doc): `{"marca", "aspecto": "16:9", "modo": "doc", "mapa": {"arquivo", "pontos", "w", "h"}?, "cenas": [...]}`; cena `{"id", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "mapa"|"imagem"|"escuro", "arquivo"?}, "beats": [...]}`; `{"tipo": "vinheta", "titulo": str}`; `{"tipo": "telafinal", "textos": {"prox", "inscreva", "video"}}`. Transições aceitas: `fade|wipe|iris|mergulho|recuo|corte`.
- `window.__KIT_DADOS.mapa` e `__KIT_DADOS.tema.tagline` disponíveis no JS.

- [ ] **Step 1: Escrever os testes** (acrescentar em `ui/test_motion.py`)

```python
def _doc(tmp_path):
    p = tmp_path / "doc"
    (p / "assets").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1600x1200:d=1",
                    "-frames:v", "1", str(p / "assets" / "mapa.png")], check=True)
    d = {"marca": "dark-historia", "aspecto": "16:9", "modo": "doc",
         "mapa": {"arquivo": "assets/mapa.png", "pontos": {"a": [200, 900], "b": [1300, 500]}, "w": 1600, "h": 1200},
         "cenas": [
             {"id": "c01", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "mapa"}, "beats": [], "dur": 3,
              "dur_piso": True, "saida": {"transicao": "mergulho", "dur": 0.6}},
             {"id": "c02", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "imagem", "arquivo": "assets/mapa.png"},
              "beats": [], "dur": 3, "dur_piso": True, "saida": {"transicao": "fade", "dur": 0.3}},
             {"id": "c900", "tipo": "vinheta", "fundo": "escuro", "titulo": "Teste", "dur": 4, "dur_piso": True,
              "saida": {"transicao": "corte", "dur": 0.1}},
             {"id": "c901", "tipo": "telafinal", "fundo": "escuro", "dur": 3, "dur_piso": True,
              "textos": {"prox": "Próxima história", "inscreva": "inscreva-se", "video": "próximo vídeo"}}]}
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p, d


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_validar_doc(tmp_path):
    p, d = _doc(tmp_path)
    assert motion.validar(d, p) == []
    d["cenas"][0]["palco"] = {"tipo": "imagem", "arquivo": "assets/nao.png"}
    d["modo"] = "zz"
    erros = {x["motivo"] for x in motion.validar(d, p)}
    assert any("modo inválido" in m for m in erros) and any("palco" in m for m in erros)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_validar_doc_mapa_obrigatorio(tmp_path):
    p, d = _doc(tmp_path)
    d.pop("mapa")
    assert any("mapa" in x["motivo"] for x in motion.validar(d, p))


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_montar_doc_copia_midias_e_carrega_doc_js(tmp_path):
    p, _ = _doc(tmp_path)
    r = motion.montar(p)
    assert r["ok"], r
    comp = p / "motion"
    html = (comp / "index.html").read_text(encoding="utf-8")
    assert '<script src="kit/doc.js"></script>' in html and (comp / "kit" / "doc.js").is_file()
    assert (comp / "assets" / "mapa.png").is_file()
    assert [c["id"] for c in r["cenas"]] == ["c01", "c02", "c900", "c901"]


@pw
def test_montar_sem_modo_doc_nao_carrega_doc_js(tmp_path):
    p = _proj(tmp_path, _cenas())
    assert motion.montar(p)["ok"]
    assert "doc.js" not in (p / "motion" / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_motion.py -q -k doc`
Expected: FAIL (`tipo desconhecido: 'doc'`)

- [ ] **Step 3: Implementar o lado Python** (`ui/motion.py`)

Trocar as constantes:
```python
TIPOS = ("frase", "numero", "lista", "tela", "endcard", "custom", "doc", "vinheta", "telafinal")
TRANSICOES = ("fade", "wipe", "iris", "mergulho", "recuo", "corte")
PALCOS = ("mapa", "imagem", "escuro")
```
Em `FUNDO_PADRAO` acrescentar `"doc": "escuro", "vinheta": "escuro", "telafinal": "escuro"`.

Validadores novos (antes de `VALIDA_TIPO`):
```python
def _v_doc(c, proj, e):
    p = c.get("palco")
    if not isinstance(p, dict) or p.get("tipo") not in PALCOS:
        return e(f"palco inválido: {p!r} ({'|'.join(PALCOS)})")
    if p["tipo"] == "imagem" and _dentro(proj, p.get("arquivo")) is None:
        e(f"palco: arquivo não encontrado no projeto: {p.get('arquivo')!r}")
    if not isinstance(c.get("beats", []), list):
        e("beats precisa ser lista")
    for b in c.get("beats", []):
        if isinstance(b, dict) and b.get("faz") == "inserto" and _dentro(proj, b.get("arquivo")) is None:
            e(f"inserto: arquivo não encontrado no projeto: {b.get('arquivo')!r}")

def _v_vinheta(c, proj, e):
    if not isinstance(c.get("titulo", ""), str):
        e("titulo precisa ser texto")

def _v_telafinal(c, proj, e):
    t = c.get("textos", {})
    if not isinstance(t, dict) or not all(isinstance(t.get(k, ""), str) for k in ("prox", "inscreva", "video")):
        e("textos precisa de prox, inscreva e video (texto)")
```
`VALIDA_TIPO` passa a incluir `"doc": _v_doc, "vinheta": _v_vinheta, "telafinal": _v_telafinal`.

Em `validar`, trocar a mensagem da saída para listar as transições:
```python
                e(i, f"saida precisa de transicao ({'|'.join(TRANSICOES)}) e dur em (0, 2]")
```
e, logo depois do bloco do `aspecto`, acrescentar:
```python
    if dados.get("modo") not in (None, "doc"):
        e("raiz", f"modo inválido: {dados.get('modo')!r} (doc)")
    if dados.get("modo") == "doc":
        usa_mapa = any(isinstance(c, dict) and isinstance(c.get("palco"), dict) and c["palco"].get("tipo") == "mapa"
                       for c in dados.get("cenas") or [])
        m = dados.get("mapa")
        if usa_mapa and (not isinstance(m, dict) or _dentro(proj, m.get("arquivo")) is None
                         or not isinstance(m.get("pontos"), dict) or not _num(m.get("w")) or not _num(m.get("h"))):
            e("raiz", "palco mapa precisa de mapa {arquivo, pontos, w, h} com arquivo no projeto")
```
Em `_tema_js`, acrescentar ao dicionário devolvido:
```python
            "tagline": tema["endcard"]["tagline"],
```
Em `_preparar`, no fim:
```python
    if d.get("modo") == "doc":   # mapa, palcos e insertos: copiados no mesmo caminho relativo
        rels = {d["mapa"]["arquivo"]} if d.get("mapa") else set()
        for c in d["cenas"]:
            if isinstance(c.get("palco"), dict) and c["palco"].get("arquivo"):
                rels.add(c["palco"]["arquivo"])
            rels |= {b["arquivo"] for b in c.get("beats", []) if b.get("faz") == "inserto"}
        for rel in rels:
            dst = comp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_dentro(proj, rel), dst)
```
No `HTML`, trocar a linha `<script src="kit/kit.js"></script>` por:
```
<script src="kit/kit.js"></script>{extra}
```
Em `_html`, montar `dados` com o mapa e passar `extra`:
```python
    dados = json.dumps({"tema": _tema_js(tema), "cenas": cenas_js, "largura": a["w"], "altura": a["h"],
                        "mapa": d.get("mapa")}, ensure_ascii=False).replace("</", "<\\/")
    extra = '\n<script src="kit/doc.js"></script>' if d.get("modo") == "doc" else ""
    return HTML.format(css=_css_vars(tema), dur=f"{total:.3f}", cenas="\n".join(partes), dados=dados,
                       w=a["w"], h=a["h"], asp=d["aspecto"], res="landscape" if a["w"] > a["h"] else "portrait",
                       extra=extra)
```

- [ ] **Step 4: Implementar os ganchos em `motion/kit/kit.js`**

Em `montar`, trocar a criação de `c`:
```js
      const c = { tl, layer, el: layer.querySelector(".k-conteudo"), tema, ini, W: D.largura || 1080, H: D.altura || 1920,
        t0: ini + (entra ? entra.dur : 0) + F(4), F, cue, C: COMP,
        fala: ini + (entra ? entra.dur : 0), cena, entra: entra ? entra.transicao : null };
```
Trocar a chamada da transição:
```js
      if (entra) TRANS[entra.transicao](tl, layer, ini, entra.dur, tema, i > 0 ? document.getElementById(D.cenas[i - 1].id) : null);
```
Trocar o `window.KIT = {...}`:
```js
  window.KIT = {
    _cena: null,
    custom: (fn) => {
      const id = window.KIT._cena;
      customs[id] = fn;
      customsVezes[id] = (customsVezes[id] || 0) + 1;
    },
    tipo: (nome, fn) => { TIPOS[nome] = fn; },
    transicao: (nome, fn) => { TRANS[nome] = fn; },
    pintor: (fn) => { pintores.push(fn); },
    cue,
    montar, F, FPS,
  };
```

- [ ] **Step 5: Criar o esqueleto `motion/kit/doc.js`**

```js
/* Modo documental (vídeo narrado 16:9): palco com câmera (mapa de época ou imagem), beats
   sincronizados à fala, transições ligadas (mergulho/recuo/corte), vinheta e tela final.
   Carregado depois do kit.js quando o cenas.json traz "modo": "doc".
   Tudo que depende do tempo é pintor (KIT.pintor), nunca onUpdate. */
(() => {
  "use strict";
  KIT.tipo("doc", (c) => c.t0 + 0.1);
  KIT.tipo("vinheta", (c) => c.t0 + 0.1);
  KIT.tipo("telafinal", (c) => c.t0 + 0.1);
  for (const n of ["mergulho", "recuo", "corte"])
    KIT.transicao(n, (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d }, t));
})();
```

- [ ] **Step 6: Rodar e ver passar**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS (inclusive os testes antigos de reels)

- [ ] **Step 7: Commit**

```bash
rtk git add ui/motion.py ui/test_motion.py motion/kit/kit.js motion/kit/doc.js
rtk git commit -m "feat(motion): modo doc no cenas.json e ganchos de registro no kit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `doc.js` — palco, câmera viva e camada de clima

**Files:**
- Modify: `motion/kit/doc.js` (substitui o esqueleto do tipo `doc`; mantém vinheta/telafinal/transições do esqueleto por enquanto)
- Test: `ui/test_motion.py` (acrescentar)

**Interfaces:**
- Consumes: ganchos do Task 3; `c.fala`, `c.entra`, `cena.palco`, `cena.beats[*].s`, `__KIT_DADOS.mapa`.
- Produces (internos do doc.js, usados nos Tasks 5–7): `W`, `H`, `el`, `svg`, `texto`, `clamp`, `easeIO`, `easeOut`, `fmt`, `iniciarFx() -> {raiz, flash}`, `construirCam(ini, moves)`, `camAt(cam, t) -> {x,y,s}`, `BEATS` (objeto `faz -> fn(ctx, b, i) -> number`), `ctx = {c, cena, hud, g, pts, base, beats, fim, ancoras, palco, cam}`; `c.layer._doc = {mergulho(t, d)}`. Cada beat recebe `b.at` (absoluto), `b.ats` (absolutos de `ts`), `itens/marcos[*].at`.

- [ ] **Step 1: Escrever o teste** (acrescentar em `ui/test_motion.py`)

```python
@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_doc_camera_move_entre_quadros(tmp_path):
    from playwright.sync_api import sync_playwright
    p, d = _doc(tmp_path)
    d["cenas"][0]["beats"] = [{"faz": "camera", "para": "b", "zoom": 2.0, "s": 0.5}]
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert motion.montar(p)["ok"]
    with sync_playwright() as pw_:
        b = pw_.chromium.launch(args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((p / "motion" / "index.html").resolve().as_uri())
        pg.wait_for_function("window.__kit !== undefined")
        tr = lambda t: pg.evaluate("t => { __kit.ir(t); return document.querySelector('#c01 .d-cam').style.transform; }", t)
        a, m, z = tr(0.1), tr(1.0), tr(2.5)
        b.close()
    assert a != m != z and "scale" in z
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_motion.py -q -k camera_move`
Expected: FAIL (`.d-cam` inexistente → `TypeError`/`None`)

- [ ] **Step 3: Implementar** — substituir `motion/kit/doc.js` inteiro por:

```js
/* Modo documental (vídeo narrado 16:9): palco com câmera (mapa de época ou imagem), beats
   sincronizados à fala, transições ligadas (mergulho/recuo/corte), vinheta e tela final.
   Carregado depois do kit.js quando o cenas.json traz "modo": "doc".
   Tudo que depende do tempo é pintor (KIT.pintor), nunca onUpdate. */
(() => {
  "use strict";
  const W = 1920, H = 1080, DERIVA = 0.006, SAIDA = 0.35;
  const easeIO = gsap.parseEase("power2.inOut");
  const easeOut = gsap.parseEase("power3.out");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const fmt = new Intl.NumberFormat("pt-BR");
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const svg = (tag, attrs) => {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const texto = (e) => { e.dataset.kTexto = ""; return e; };

  const CSS = `
.d-palco{position:absolute;inset:0;overflow:hidden;transform-origin:50% 50%}
.d-cam{position:absolute;left:0;top:0;transform-origin:0 0}
.d-img{position:absolute;inset:0;background-size:cover;background-position:center;filter:sepia(.35) contrast(1.1) brightness(.8)}
.d-mapa{position:absolute;inset:0;background-size:100% 100%;filter:sepia(.45) saturate(.55) contrast(1.05) brightness(.62)}
.d-cam svg{position:absolute;left:0;top:0;overflow:visible}
.d-rota{fill:none;stroke:var(--k-acento);stroke-width:6;stroke-linecap:round}
.d-ping{fill:none;stroke:#C0392B;stroke-width:5}
.d-ponto{fill:#C0392B}
.d-hud{position:absolute;inset:0;pointer-events:none}
.d-hud>*{opacity:0}
.t{color:var(--k-sobre);text-shadow:0 2px 18px rgba(0,0,0,.9),0 0 4px rgba(0,0,0,.8)}
.d-chip{position:absolute;padding:10px 20px;background:rgba(11,10,8,.85);border-left:4px solid #C0392B;font:600 26px var(--k-corpo-familia);letter-spacing:.08em;white-space:nowrap;text-transform:uppercase}
.d-data{position:absolute;left:120px;top:90px}
.d-data .m{font:600 32px var(--k-corpo-familia);letter-spacing:.4em;color:var(--k-acento);text-transform:uppercase}
.d-data .a{font:600 140px/1 var(--k-display-familia)}
.d-painel{position:absolute;right:120px;top:200px;width:560px;padding:32px 36px;background:rgba(11,10,8,.88);border-top:4px solid var(--k-acento)}
.d-painel .v{font:500 140px/1 var(--k-mono-familia)}
.d-painel .l{font:italic 400 38px var(--k-display-familia);color:#cdbf9f;margin:6px 0 20px}
.d-pontos{display:grid;grid-template-columns:repeat(25,16px);gap:5px}
.d-pontos i{width:16px;height:16px;border-radius:50%;background:var(--k-acento);opacity:.12}
.d-rotulo{position:absolute;left:120px;bottom:120px;padding-left:22px;border-left:4px solid var(--k-acento)}
.d-rotulo .n{font:600 56px var(--k-display-familia)}
.d-rotulo .p{font:600 24px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:6px}
.d-palavras{position:absolute;left:120px;right:120px;bottom:130px;text-align:center;font:800 110px var(--k-corpo-familia);text-transform:uppercase}
.d-palavras span{display:inline-block;margin:0 20px;position:relative;opacity:0}
.d-risco{position:absolute;left:-10px;right:-10px;top:52%;height:12px;background:#C0392B;transform:scaleX(0);transform-origin:left}
.d-veu{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.d-citacao{position:absolute;left:240px;right:240px;top:300px;text-align:center}
.d-citacao .q{font:italic 400 66px/1.25 var(--k-display-familia)}
.d-citacao .a{font:600 26px var(--k-corpo-familia);letter-spacing:.2em;color:var(--k-acento);text-transform:uppercase;margin-top:28px}
.d-lista{position:absolute;left:160px;top:220px;width:1100px}
.d-lista .i{font:500 48px var(--k-corpo-familia);padding:14px 0 14px 24px;border-left:3px solid var(--k-acento);margin-bottom:14px;background:rgba(11,10,8,.6);opacity:0}
.d-linha{position:absolute;left:160px;right:160px;top:640px;height:3px;background:var(--k-acento)}
.d-marco{position:absolute;top:-14px;width:30px;height:30px;margin-left:-15px;border-radius:50%;border:3px solid var(--k-acento);background:#0b0a08;opacity:0}
.d-marco .d{position:absolute;top:-76px;left:50%;transform:translateX(-50%);font:500 40px var(--k-mono-familia);white-space:nowrap}
.d-marco .x{position:absolute;top:44px;left:50%;transform:translateX(-50%);font:italic 400 30px var(--k-display-familia);color:#cdbf9f;white-space:nowrap}
.d-cursor{position:absolute;top:-10px;left:0;width:22px;height:22px;margin-left:-11px;border-radius:50%;background:#C0392B}
.d-inserto{position:absolute;inset:0;background-size:cover;background-position:center;filter:sepia(.3) contrast(1.1) brightness(.78);opacity:0}
.d-selo{position:absolute}
.d-fx{position:absolute;inset:0;pointer-events:none}
.d-vin{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,0) 50%,rgba(0,0,0,.8) 100%)}
.d-flick{position:absolute;inset:0;background:#000;opacity:0}
.d-flash{position:absolute;inset:0;background:#fff6e0;opacity:0}
.d-papel{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,#3a3125 0%,#1d1912 60%,#0e0d0b 100%)}
.d-marca{position:absolute;left:0;right:0;top:690px;text-align:center;font:500 44px var(--k-mono-familia);letter-spacing:.5em;clip-path:inset(0 100% 0 0)}
.d-titulo{position:absolute;left:200px;right:200px;top:770px;text-align:center;font:italic 400 64px var(--k-display-familia);opacity:0}
.d-guia{position:absolute;border:2px solid rgba(184,134,43,.45);opacity:0}
.d-guia .g{position:absolute;left:0;right:0;bottom:-52px;text-align:center;font:600 22px var(--k-corpo-familia);letter-spacing:.2em;color:rgba(237,230,214,.6);text-transform:uppercase}
.d-prox{position:absolute;left:0;right:0;top:130px;text-align:center;font:italic 600 76px var(--k-display-familia);opacity:0}
.d-tag{position:absolute;left:0;right:0;bottom:110px;text-align:center;font:500 30px var(--k-corpo-familia);letter-spacing:.15em;color:#cdbf9f;opacity:0}`;
  document.head.appendChild(el("style", null, CSS));

  // ---------- camada de clima (uma vez, dentro de #k-fixos, abaixo do grão do kit)
  let fx = null;
  function iniciarFx() {
    if (fx) return fx;
    const host = document.getElementById("k-fixos");
    const raiz = el("div", "d-fx"), flick = el("div", "d-flick"), flash = el("div", "d-flash");
    raiz.append(el("div", "d-vin"), flick, flash);
    host.prepend(raiz);
    KIT.pintor((t) => {
      const r = Math.sin(Math.floor(t * 12) * 12.9898) * 43758.5453;
      flick.style.opacity = ((r - Math.floor(r)) * 0.07).toFixed(3);
    });
    fx = { raiz, flash };
    return fx;
  }

  // ---------- câmera: movimentos (t, d, x, y, s) a partir de um estado inicial + deriva lenta
  function camAt(cam, t) {
    let cur = cam.ini, t0 = 0;
    for (const m of cam.ms) {
      if (t < m.t) break;
      const e = easeIO(Math.min(1, (t - m.t) / m.d));
      cur = { x: m.de.x + (m.x - m.de.x) * e, y: m.de.y + (m.y - m.de.y) * e, s: m.de.s + (m.s - m.de.s) * e };
      t0 = m.t + m.d;
    }
    return { x: cur.x, y: cur.y, s: cur.s * (1 + DERIVA * Math.max(0, t - Math.max(t0, cam.t0))) };
  }
  function construirCam(ini, moves, t0) {
    const cam = { ini, ms: [], t0 };
    for (const m of moves.slice().sort((a, b) => a.t - b.t)) cam.ms.push({ ...m, de: camAt(cam, m.t) });
    return cam;
  }

  const BEATS = { camera: (ctx, b) => b.at };

  KIT.tipo("doc", (c, cena) => {
    iniciarFx();
    const D = window.__KIT_DADOS, mapa = D.mapa, p = cena.palco || { tipo: "escuro" };
    const palco = el("div", "d-palco"), cam = el("div", "d-cam"), hud = el("div", "d-hud");
    palco.appendChild(cam);
    c.layer.append(palco, hud);
    let dims, pts = {};
    if (p.tipo === "mapa") {
      dims = { mw: mapa.w, mh: mapa.h, base: Math.max(W / mapa.w, H / mapa.h) };
      const m = el("div", "d-mapa");
      m.style.backgroundImage = `url("${mapa.arquivo}")`;
      cam.appendChild(m);
      pts = mapa.pontos;
    } else {
      dims = { mw: W, mh: H, base: 1 };
      if (p.tipo === "imagem") {
        const m = el("div", "d-img");
        m.style.backgroundImage = `url("${p.arquivo}")`;
        cam.appendChild(m);
      }
    }
    Object.assign(cam.style, { width: `${dims.mw}px`, height: `${dims.mh}px` });
    const g = svg("svg", { width: dims.mw, height: dims.mh, viewBox: `0 0 ${dims.mw} ${dims.mh}` });
    cam.appendChild(g);
    const fim = c.ini + cena.dur - (cena.saida ? cena.saida.dur : 0);
    const abs = (s) => (s == null ? null : c.fala + s);
    const beats = (cena.beats || []).map((b) => ({
      ...b, at: abs(b.s), ats: (b.ts || []).map(abs),
      itens: (b.itens || []).map((x) => ({ ...x, at: abs(x.s) })),
      marcos: (b.marcos || []).map((x) => ({ ...x, at: abs(x.s) })),
    }));
    // câmera
    const nomeDe = (b) => [b.para, b.ponto, b.de].find((n) => n && pts[n]);
    const primeiro = beats.map(nomeDe).find(Boolean);
    let ini;
    if (p.tipo === "mapa") {
      const [x0, y0] = primeiro ? pts[primeiro] : [dims.mw / 2, dims.mh / 2];
      ini = c.entra === "recuo" ? { x: x0, y: y0, s: 3.2 } : (window.__docCamMapa || { x: x0, y: y0, s: 1.2 });
    } else ini = { x: W / 2, y: H / 2, s: 1.08 };
    const moves = [];
    if (p.tipo === "mapa" && c.entra === "recuo") moves.push({ t: c.ini, d: 1.0, x: ini.x, y: ini.y, s: 1.15 });
    let alvo = null;
    for (const b of beats) {
      if (b.faz === "camera" && p.tipo === "mapa" && pts[b.para]) {
        moves.push({ t: b.at, d: b.dur || 1.6, x: pts[b.para][0], y: pts[b.para][1], s: b.zoom || 1.6 });
      } else if (b.faz === "camera" && b.area) {
        const [ax, ay, aw, ah] = b.area;
        moves.push({ t: b.at, d: b.dur || 1.6, x: (ax + aw / 2) * W, y: (ay + ah / 2) * H, s: clamp(1 / Math.max(aw, ah), 1, 3) });
        alvo = [(ax + aw / 2) * W, (ay + ah / 2) * H];
      } else if (b.faz === "rota" && p.tipo === "mapa" &&
                 !beats.some((o) => o.faz === "camera" && Math.abs(o.at - b.at) < 0.05)) {
        moves.push({ t: b.at, d: b.dur || 2.0, x: pts[b.para][0], y: pts[b.para][1], s: b.zoom || 1.35 });
      }
      if (nomeDe(b)) alvo = pts[nomeDe(b)];
    }
    const camera = construirCam(ini, moves, c.ini);
    const ancoras = [];   // [elemento, x, y, dx, dy]: overlay preso a um ponto do palco
    KIT.pintor((t) => {
      if (t < c.ini - 0.05 || t > c.ini + cena.dur + 0.05) return;
      const st = camAt(camera, t), sc = dims.base * st.s;
      const tx = clamp(W / 2 - st.x * sc, W - dims.mw * sc, 0), ty = clamp(H / 2 - st.y * sc, H - dims.mh * sc, 0);
      cam.style.transform = `translate(${tx.toFixed(2)}px,${ty.toFixed(2)}px) scale(${sc.toFixed(5)})`;
      for (const [e, x, y, dx, dy] of ancoras) {
        e.style.left = `${(tx + x * sc + dx).toFixed(1)}px`;
        e.style.top = `${(ty + y * sc + dy).toFixed(1)}px`;
      }
    });
    if (p.tipo === "mapa") window.__docCamMapa = camAt(camera, fim);
    c.layer._doc = {
      mergulho: (t, d) => {
        const de = camAt(camera, t), [x, y] = alvo || [de.x, de.y];
        camera.ms.push({ t, d, x, y, s: de.s * 4, de });
      },
    };
    const ctx = { c, cena, hud, g, pts, base: dims.base, beats, fim, ancoras, palco, cam };
    let ultimo = c.t0;
    beats.forEach((b, i) => {
      const f = BEATS[b.faz];
      if (!f) throw new Error(`beat desconhecido: ${b.faz}`);
      ultimo = Math.max(ultimo, f(ctx, b, i));
    });
    return ultimo;
  });

  KIT.tipo("vinheta", (c) => c.t0 + 0.1);
  KIT.tipo("telafinal", (c) => c.t0 + 0.1);
  for (const n of ["mergulho", "recuo", "corte"])
    KIT.transicao(n, (tl, cam, t, d) => tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d }, t));

  window.__doc = { W, H, el, svg, texto, clamp, easeIO, easeOut, fmt, iniciarFx, camAt, BEATS, SAIDA };
})();
```
(`window.__doc` só expõe os internos para depuração no console; os Tasks 5–7 editam este mesmo arquivo.)

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_motion.py -q -k doc`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add motion/kit/doc.js ui/test_motion.py
rtk git commit -m "feat(doc.js): palco com câmera viva (mapa/imagem) e camada de clima

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `doc.js` — beats

**Files:**
- Modify: `motion/kit/doc.js` (substituir a linha `const BEATS = { camera: (ctx, b) => b.at };` pelo bloco abaixo)
- Test: `ui/test_motion.py` (acrescentar)

**Interfaces:**
- Consumes: `ctx` e `b.at/b.ats/itens[*].at/marcos[*].at` do Task 4.
- Produces: `BEATS[faz]` para `camera, ponto, rota, contador, data, rotulo, palavras, citacao, lista, linha_tempo, inserto, selo`; cues `ping, whoosh, tique, carimbo, impacto` (nomes usados pelo kit de SFX do Task 9); `seloSvg(tamanho) -> {s, aneis}` (usado no Task 7).

- [ ] **Step 1: Escrever os testes** (acrescentar em `ui/test_motion.py`)

```python
BEATS_TODOS = [
    {"faz": "data", "t": "Junho 1629", "s": 0.2},
    {"faz": "rota", "de": "a", "para": "b", "navio": True, "km": 3000, "s": 0.4},
    {"faz": "ponto", "ponto": "b", "rotulo": "Abrolhos", "s": 1.0},
    {"faz": "contador", "valor": 300, "legenda": "sobreviventes", "pontos": True, "s": 1.2},
    {"faz": "rotulo", "nome": "Jeronimus Cornelisz", "papel": "subcomerciante", "s": 1.4},
    {"faz": "palavras", "palavras": ["ilhas", "sem", "água"], "risco": "água", "s": 1.6, "ts": [1.6, 1.8, 2.0]},
    {"faz": "selo", "s": 2.4},
]


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_doc_todos_os_beats_montam_com_cues(tmp_path):
    p, d = _doc(tmp_path)
    d["cenas"][0]["beats"] = BEATS_TODOS
    d["cenas"][1]["beats"] = [
        {"faz": "camera", "area": [0.5, 0.2, 0.3, 0.3], "s": 0.1},
        {"faz": "citacao", "t": "Uma história incrível", "autor": "Kieran Hosty", "s": 0.3},
        {"faz": "lista", "itens": [{"t": "Crânio", "s": 0.6}, {"t": "Clava"}], "s": 0.5},
        {"faz": "linha_tempo", "marcos": [{"data": "1628", "t": "partida"}, {"data": "1629", "t": "naufrágio"}], "s": 1.0},
        {"faz": "inserto", "arquivo": "assets/mapa.png", "s": 1.5}]
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = motion.montar(p)
    assert r["ok"], r
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"ping", "whoosh", "tique", "carimbo", "impacto"} <= sons


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_doc_citacao_longa_estoura_safe_area(tmp_path):
    p, d = _doc(tmp_path)
    d["cenas"][1]["beats"] = [{"faz": "citacao", "t": "palavra " * 120, "autor": "x", "s": 0.2}]
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = motion.montar(p)
    assert not r["ok"] and any("safe area" in e["motivo"] for e in r["erros"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_motion.py -q -k "todos_os_beats or citacao_longa"`
Expected: FAIL (`beat desconhecido: data`)

- [ ] **Step 3: Implementar** — em `motion/kit/doc.js`, trocar `const BEATS = { camera: (ctx, b) => b.at };` por:

```js
  // ---------- beats: (ctx, b, i) -> instante em que a entrada termina
  const SLOT = { data: "canto", contador: "painel", rotulo: "rotulo", palavras: "centro", citacao: "centro",
                 lista: "centro", linha_tempo: "centro", selo: "centro" };
  const fora = (ctx, b) => {   // sai quando o próximo beat do mesmo slot entra, ou no fim da cena
    const prox = ctx.beats.find((o) => o.at > b.at + 0.01 && SLOT[o.faz] && SLOT[o.faz] === SLOT[b.faz]);
    return Math.min(prox ? prox.at - 0.1 : ctx.fim, ctx.fim) - SAIDA;
  };
  const sai = (ctx, e, b) => ctx.c.tl.to(e, { opacity: 0, duration: SAIDA }, fora(ctx, b));
  const IN = (tl, e, t, de = { y: 20 }) =>
    tl.fromTo(e, { opacity: 0, ...de }, { opacity: 1, x: 0, y: 0, duration: 0.45, ease: "power3.out", immediateRender: false }, t);
  const mostra = (tl, e, t) => tl.fromTo(e, { opacity: 0 }, { opacity: 1, duration: 0.01, immediateRender: false }, t);

  function caminho(P) {
    if (P.length === 2) {
      const [[x1, y1], [x2, y2]] = P, mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      return `M${x1} ${y1} Q${mx - (y2 - y1) * 0.2} ${my + (x2 - x1) * 0.2} ${x2} ${y2}`;
    }
    let d = `M${P[0][0]} ${P[0][1]}`;
    for (let i = 0; i < P.length - 1; i++) {
      const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
      d += ` C${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6}` +
           ` ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]} ${p2[1]}`;
    }
    return d;
  }

  function seloSvg(tam) {
    const s = svg("svg", { viewBox: "0 0 240 240", width: tam, height: tam });
    const a1 = svg("circle", { cx: 120, cy: 120, r: 112, fill: "none", stroke: "#8C2F1B", "stroke-width": 10 });
    const a2 = svg("circle", { cx: 120, cy: 120, r: 96, fill: "none", stroke: "#8C2F1B", "stroke-width": 3 });
    const k = svg("text", { x: 120, y: 162, "text-anchor": "middle", "font-family": "K Fraunces", "font-style": "italic",
                            "font-weight": 600, "font-size": 132, fill: "#cdbf9f" });
    k.textContent = "K";
    s.append(a1, a2, k);
    return { s, aneis: [a1, a2] };
  }

  const BEATS = {
    camera: (ctx, b) => b.at,

    ponto(ctx, b) {
      const [x, y] = ctx.pts[b.ponto], { tl } = ctx.c, r = 13 / ctx.base;
      const dot = svg("circle", { cx: x, cy: y, r, class: "d-ponto", opacity: 0 });
      const ping = svg("circle", { cx: x, cy: y, r, class: "d-ping", opacity: 0, "vector-effect": "non-scaling-stroke" });
      ctx.g.append(ping, dot);
      tl.fromTo(dot, { attr: { opacity: 0 } }, { attr: { opacity: 1 }, duration: 0.1, immediateRender: false }, b.at);
      for (const k of [0, 0.7])
        tl.fromTo(ping, { attr: { r, opacity: 1 } }, { attr: { r: r * 6, opacity: 0 }, duration: 0.9, ease: "power2.out",
                  immediateRender: false }, b.at + k);
      if (b.rotulo) {
        const chip = el("div", "d-chip t", b.rotulo);
        ctx.hud.appendChild(chip);
        ctx.ancoras.push([chip, x, y, -40, -70]);
        IN(tl, chip, b.at + 0.1, { x: -16 });
      }
      KIT.cue(b.at, "ping");
      return b.at + 0.6;
    },

    rota(ctx, b) {
      const P = [b.de, ...(b.via || []), b.para].map((n) => ctx.pts[n]);
      const path = svg("path", { d: caminho(P), class: "d-rota", "vector-effect": "non-scaling-stroke" });
      ctx.g.insertBefore(path, ctx.g.firstChild);
      const L = path.getTotalLength(), dur = b.dur || 2.0, t0 = b.at;
      path.setAttribute("stroke-dasharray", `0 ${L}`);
      const nav = b.navio ? svg("path", { d: "M-26 6 L26 6 L18 18 L-18 18 Z M-2 6 L-2 -30 L22 2 Z M-6 6 L-6 -22 L-24 2 Z",
                                          fill: "#EDE6D6", opacity: 0 }) : null;
      if (nav) ctx.g.appendChild(nav);
      let km = null;
      if (b.km) {
        km = el("div", "d-chip t");
        km.style.borderLeftColor = "var(--k-acento)";
        ctx.hud.appendChild(km);
        const meio = path.getPointAtLength(L / 2);
        ctx.ancoras.push([km, meio.x, meio.y, 30, -24]);
        IN(ctx.c.tl, km, t0, { x: 0 });
      }
      KIT.pintor((t) => {
        const p = easeIO(clamp((t - t0) / dur, 0, 1));
        path.setAttribute("stroke-dasharray", `${(p * L).toFixed(1)} ${L}`);
        if (nav) {
          const q = path.getPointAtLength(p * L);
          nav.setAttribute("transform", `translate(${q.x},${q.y}) scale(${(1.4 / ctx.base).toFixed(3)})`);
          nav.setAttribute("opacity", t >= t0 && p < 1 ? 1 : 0);
        }
        if (km) km.textContent = `${fmt.format(Math.round(p * b.km))} km`;
      });
      KIT.cue(t0, "whoosh", -10);
      return t0 + 0.5;
    },

    contador(ctx, b) {
      const { tl } = ctx.c, pn = el("div", "d-painel t"), dur = 0.9;
      const v = texto(el("div", "v")), l = texto(el("div", "l", b.legenda || ""));
      pn.append(v, l);
      const dots = [];
      if (b.pontos) {
        const gr = el("div", "d-pontos");
        for (let i = 0; i < b.valor; i++) dots.push(gr.appendChild(el("i")));
        pn.appendChild(gr);
      }
      ctx.hud.appendChild(pn);
      IN(tl, pn, b.at - 0.12, { x: 60 });
      sai(ctx, pn, b);
      const pre = b.prefixo || "", suf = b.sufixo || "";
      KIT.pintor((t) => {
        const p = easeOut(clamp((t - b.at) / dur, 0, 1)), n = Math.round(dots.length * p);
        v.textContent = `${pre}${fmt.format(Math.round(b.valor * p))}${suf}`;
        dots.forEach((d, i) => { d.style.opacity = i < n ? "1" : ".12"; });
      });
      v.textContent = `${pre}${fmt.format(b.valor)}${suf}`;
      KIT.cue(b.at, "tique");
      return b.at + dur;
    },

    data(ctx, b) {
      const pal = String(b.t).trim().split(/\s+/), ano = pal.pop(), { tl } = ctx.c;
      const box = el("div", "d-data t"), m = texto(el("div", "m", pal.join(" "))), a = texto(el("div", "a", ano));
      box.append(m, a);
      ctx.hud.appendChild(box);
      mostra(tl, box, b.at);
      tl.fromTo(m, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out", immediateRender: false }, b.at);
      tl.fromTo(a, { opacity: 0, scale: 1.35, transformOrigin: "left center" },
                { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(2)", immediateRender: false }, b.at + 0.3);
      sai(ctx, box, b);
      KIT.cue(b.at + 0.3, "carimbo");
      return b.at + 0.65;
    },

    rotulo(ctx, b) {
      const box = el("div", "d-rotulo t");
      box.appendChild(texto(el("div", "n", b.nome)));
      if (b.papel) box.appendChild(texto(el("div", "p", b.papel)));
      ctx.hud.appendChild(box);
      IN(ctx.c.tl, box, b.at, { x: -30 });
      sai(ctx, box, b);
      KIT.cue(b.at, "whoosh", -12);
      return b.at + 0.45;
    },

    palavras(ctx, b) {
      const box = el("div", "d-palavras t"), { tl } = ctx.c;
      const ats = b.ats.length ? b.ats : b.palavras.map((_, i) => b.at + i * 0.3);
      const limpa = (w) => String(w).replace(/#\d+$/, "");
      mostra(tl, box, b.at);
      b.palavras.forEach((w, i) => {
        const s = texto(el("span", null, limpa(w)));
        box.appendChild(s);
        tl.fromTo(s, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.22, ease: "back.out(2.5)", immediateRender: false }, ats[i]);
        KIT.cue(ats[i], "tique", -12);
        if (b.risco && limpa(b.risco) === limpa(w)) {
          const r = el("b", "d-risco");
          s.appendChild(r);
          const tr = ats[ats.length - 1] + 0.3;
          tl.fromTo(r, { scaleX: 0 }, { scaleX: 1, duration: 0.25, ease: "power2.out", immediateRender: false }, tr);
          KIT.cue(tr, "impacto", -8);
        }
      });
      ctx.hud.appendChild(box);
      sai(ctx, box, b);
      return ats[ats.length - 1] + 0.25;
    },

    citacao(ctx, b) {
      const veu = el("div", "d-veu"), box = el("div", "d-citacao t"), { tl } = ctx.c;
      box.append(texto(el("div", "q", `“${b.t}”`)), texto(el("div", "a", b.autor)));
      ctx.hud.append(veu, box);
      tl.fromTo(veu, { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, b.at);
      IN(tl, box, b.at + 0.1);
      sai(ctx, veu, b);
      sai(ctx, box, b);
      KIT.cue(b.at, "whoosh", -10);
      return b.at + 0.55;
    },

    lista(ctx, b) {
      const box = el("div", "d-lista t"), { tl } = ctx.c;
      mostra(tl, box, b.at);
      let fim = b.at;
      b.itens.forEach((it, i) => {
        const r = texto(el("div", "i", it.t));
        box.appendChild(r);
        const t = it.at != null ? it.at : b.at + i * 0.5;
        tl.fromTo(r, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out", immediateRender: false }, t);
        KIT.cue(t, "tique", -10);
        fim = Math.max(fim, t + 0.35);
      });
      ctx.hud.appendChild(box);
      sai(ctx, box, b);
      return fim;
    },

    linha_tempo(ctx, b) {
      const ln = el("div", "d-linha t"), cur = el("div", "d-cursor"), { tl } = ctx.c, n = b.marcos.length;
      ln.appendChild(cur);
      tl.fromTo(ln, { opacity: 0, scaleX: 0, transformOrigin: "left center" },
                { opacity: 1, scaleX: 1, duration: 0.6, ease: "power3.inOut", immediateRender: false }, b.at);
      let fim = b.at + 0.6;
      b.marcos.forEach((m, i) => {
        const x = n === 1 ? 50 : 8 + (i / (n - 1)) * 84;   // 8–92%: rótulos das pontas dentro da safe area
        const mk = el("div", "d-marco");
        mk.style.left = `${x}%`;
        mk.append(texto(el("div", "d", m.data)), texto(el("div", "x", m.t || "")));
        ln.appendChild(mk);
        const t = m.at != null ? m.at : b.at + 0.6 + i * 0.8;
        tl.fromTo(mk, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.3, immediateRender: false }, t);
        tl.to(cur, { left: `${x}%`, duration: 0.4, ease: "power2.inOut" }, t - 0.1);
        KIT.cue(t, "tique", -10);
        fim = Math.max(fim, t + 0.3);
      });
      ctx.hud.appendChild(ln);
      sai(ctx, ln, b);
      return fim;
    },

    inserto(ctx, b) {
      const im = el("div", "d-inserto"), { tl } = ctx.c;
      im.style.backgroundImage = `url("${b.arquivo}")`;
      ctx.palco.appendChild(im);
      tl.fromTo(im, { opacity: 0, scale: 1.12 }, { opacity: 1, scale: 1.04, duration: 0.6, ease: "power2.out", immediateRender: false }, b.at);
      tl.to(im, { scale: 1.0, duration: Math.max(0.1, ctx.fim - b.at - 0.6), ease: "none" }, b.at + 0.6);
      KIT.cue(b.at, "whoosh", -10);
      return b.at + 0.6;
    },

    selo(ctx, b) {
      const box = el("div", "d-selo"), { tl } = ctx.c;
      Object.assign(box.style, { left: `${W / 2 - 130}px`, top: "300px", width: "260px", height: "260px" });
      box.appendChild(seloSvg(260).s);
      ctx.hud.appendChild(box);
      tl.fromTo(box, { opacity: 0, scale: 1.8 }, { opacity: 1, scale: 1, duration: 0.35, ease: "power4.in", immediateRender: false }, b.at);
      tl.to(box, { scale: 1.08, duration: 0.25, yoyo: true, repeat: 3, ease: "sine.inOut" }, b.at + 0.5);
      sai(ctx, box, b);
      KIT.cue(b.at + 0.35, "carimbo");
      return b.at + 0.6;
    },
  };
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add motion/kit/doc.js ui/test_motion.py
rtk git commit -m "feat(doc.js): beats (rota, ponto, contador, data, rótulo, palavras, citação, lista, linha do tempo, inserto, selo)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `doc.js` — transições ligadas (mergulho, recuo, corte)

**Files:**
- Modify: `motion/kit/doc.js` (trocar o laço `for (const n of ["mergulho", "recuo", "corte"]) ...` pelo bloco abaixo)
- Test: `ui/test_motion.py` (acrescentar)

**Interfaces:**
- Consumes: `c.layer._doc.mergulho(t, d)` (Task 4), `iniciarFx().flash`, `.d-palco`.
- Produces: transições `mergulho`, `recuo`, `corte`; cues `clarao`, `whoosh`.

- [ ] **Step 1: Escrever o teste**

```python
@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_doc_mergulho_aproxima_o_mapa_e_da_clarao(tmp_path):
    from playwright.sync_api import sync_playwright
    p, d = _doc(tmp_path)
    d["cenas"][0]["beats"] = [{"faz": "ponto", "ponto": "b", "s": 0.3}]
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = motion.montar(p)
    assert r["ok"], r
    c2 = next(c for c in r["cenas"] if c["id"] == "c02")
    with sync_playwright() as pw_:
        b = pw_.chromium.launch(args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((p / "motion" / "index.html").resolve().as_uri())
        pg.wait_for_function("window.__kit !== undefined")
        escala = lambda t: pg.evaluate("t => { __kit.ir(t); const m = document.querySelector('#c01 .d-cam').style.transform;"
                                       " return parseFloat(m.match(/scale\\(([\\d.]+)\\)/)[1]); }", t)
        antes, durante = escala(c2["ini"] - 0.3), escala(c2["ini"] + 0.5)
        flash = pg.evaluate("t => { __kit.ir(t); return +getComputedStyle(document.querySelector('.d-flash')).opacity; }",
                            c2["ini"] + 0.6 * 0.45)
        b.close()
    assert durante > antes * 1.8 and flash > 0.5
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert "clarao" in sons
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_motion.py -q -k mergulho`
Expected: FAIL (escala não cresce; sem cue `clarao`)

- [ ] **Step 3: Implementar** — substituir o laço do esqueleto por:

```js
  // ---------- transições ligadas (entrada da cena nova; `ant` = camada da cena anterior)
  KIT.transicao("mergulho", (tl, cam, t, d, tema, ant) => {
    const meio = t + d * 0.45, flash = iniciarFx().flash;
    if (ant && ant._doc) ant._doc.mergulho(t - 0.1, d * 0.55 + 0.1);
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d * 0.4 }, meio);
    tl.fromTo(flash, { opacity: 0 }, { opacity: 0.85, duration: 0.1, immediateRender: false }, meio - 0.05)
      .to(flash, { opacity: 0, duration: 0.45 }, meio + 0.05);
    const palco = cam.querySelector(".d-palco");
    if (palco) tl.fromTo(palco, { scale: 1.7 }, { scale: 1, duration: 1.1, ease: "power3.out", immediateRender: false }, meio);
    KIT.cue(meio, "clarao", -8);
  });
  KIT.transicao("recuo", (tl, cam, t, d, tema, ant) => {
    const pp = ant && ant.querySelector(".d-palco");
    if (pp) tl.to(pp, { scale: 0.8, opacity: 0, duration: d, ease: "power2.in" }, t);
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: d * 0.6 }, t + d * 0.4);
    KIT.cue(t, "whoosh", -8);
  });
  KIT.transicao("corte", (tl, cam, t, d) => {
    tl.fromTo(cam, { opacity: 0 }, { opacity: 1, duration: 0.01 }, t + d * 0.5);
    KIT.cue(t, "whoosh", -10);
  });
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add motion/kit/doc.js ui/test_motion.py
rtk git commit -m "feat(doc.js): transições ligadas mergulho, recuo e corte

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `doc.js` — vinheta de abertura e tela final

**Files:**
- Modify: `motion/kit/doc.js` (trocar as duas linhas `KIT.tipo("vinheta", ...)` e `KIT.tipo("telafinal", ...)`)
- Test: `ui/test_motion.py` (acrescentar)

**Interfaces:**
- Consumes: `seloSvg` (Task 5), `iniciarFx`, `__KIT_DADOS.mapa`, `c.tema.tagline` (Task 3), `cena.titulo`, `cena.textos`.
- Produces: tipos `vinheta` (molde de ~4 s) e `telafinal` (molde de 20 s com quadros-guia nas posições dos elementos finais do YouTube); cues `carimbo`, `maquina`, `whoosh`.

- [ ] **Step 1: Escrever o teste**

```python
@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_doc_vinheta_e_tela_final(tmp_path):
    from playwright.sync_api import sync_playwright
    p, _ = _doc(tmp_path)
    r = motion.montar(p)
    assert r["ok"], r
    v = next(c for c in r["cenas"] if c["id"] == "c900")
    f = next(c for c in r["cenas"] if c["id"] == "c901")
    with sync_playwright() as pw_:
        b = pw_.chromium.launch(args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((p / "motion" / "index.html").resolve().as_uri())
        pg.wait_for_function("window.__kit !== undefined")
        op = lambda t, sel: pg.evaluate("([t, s]) => { __kit.ir(t); return +getComputedStyle(document.querySelector(s)).opacity; }", [t, sel])
        tit = op(v["ini"] + 2.5, "#c900 .d-titulo")
        guias = op(f["ini"] + 2.0, "#c901 .d-guia")
        textos = pg.evaluate("() => [...document.querySelectorAll('#c901 .g')].map(e => e.textContent)")
        b.close()
    assert tit > 0.9 and guias > 0.9 and textos == ["inscreva-se", "próximo vídeo"]
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"carimbo", "maquina"} <= sons
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_motion.py -q -k vinheta`
Expected: FAIL (`.d-titulo` inexistente)

- [ ] **Step 3: Implementar** — substituir as duas linhas do esqueleto por:

```js
  // ---------- abertura: selo K carimba no papel, anéis se desenham, marca datilografada, título
  KIT.tipo("vinheta", (c, cena) => {
    iniciarFx();
    const { tl } = c, t0 = c.ini + 0.1, sai = c.ini + cena.dur - 0.6;
    const palco = el("div", "d-palco");
    palco.appendChild(el("div", "d-papel"));
    c.layer.appendChild(palco);
    const box = el("div", "d-selo");
    Object.assign(box.style, { left: `${W / 2 - 160}px`, top: "300px", width: "320px", height: "320px", opacity: "0" });
    const { s, aneis } = seloSvg(320);
    box.appendChild(s);
    const marca = texto(el("div", "d-marca t", "KRYVANTIS")), tit = texto(el("div", "d-titulo t", cena.titulo || ""));
    palco.append(box, marca, tit);
    tl.fromTo(box, { opacity: 0, scale: 2.4 }, { opacity: 1, scale: 1, duration: 0.35, ease: "power4.in", immediateRender: false }, t0);
    tl.fromTo(palco, { x: -8 }, { x: 0, duration: 0.25, ease: "elastic.out(1,0.3)", immediateRender: false }, t0 + 0.35);
    for (let i = 0; i < 18; i++) {   // poeira do impacto
      const d = el("i"), a = (i / 18) * Math.PI * 2, r = 180 + (i % 3) * 60;
      Object.assign(d.style, { position: "absolute", left: `${W / 2}px`, top: "460px", width: "6px", height: "6px",
                               borderRadius: "50%", background: "#cdbf9f", opacity: "0" });
      palco.appendChild(d);
      tl.fromTo(d, { opacity: 0.8, x: 0, y: 0 }, { opacity: 0, x: Math.cos(a) * r, y: Math.sin(a) * r * 0.6, duration: 0.9,
                ease: "power2.out", immediateRender: false }, t0 + 0.35);
    }
    for (const a of aneis) {
      const L = 2 * Math.PI * Number(a.getAttribute("r"));
      a.setAttribute("stroke-dasharray", L);
      a.setAttribute("stroke-dashoffset", L);
      tl.fromTo(a, { attr: { "stroke-dashoffset": L } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.6, ease: "power2.inOut",
                immediateRender: false }, t0 + 0.4);
    }
    tl.fromTo(marca, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.7, ease: "steps(9)",
              immediateRender: false }, t0 + 0.9);
    tl.fromTo(tit, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out", immediateRender: false }, t0 + 1.6);
    tl.to(palco, { scale: 5, opacity: 0, duration: 0.5, ease: "power3.in", transformOrigin: "50% 42%" }, sai);
    KIT.cue(t0 + 0.35, "carimbo");
    KIT.cue(t0 + 0.9, "maquina");
    KIT.cue(sai, "whoosh");
    return t0 + 2.1;
  });

  // ---------- tela final (20 s): quadros-guia nas posições dos elementos finais do YouTube
  KIT.tipo("telafinal", (c, cena) => {
    iniciarFx();
    const { tl } = c, t0 = c.ini + 0.2, D = window.__KIT_DADOS, tx = cena.textos || {};
    const palco = el("div", "d-palco");
    c.layer.appendChild(palco);
    if (D.mapa) {
      const m = el("div", "d-img");
      Object.assign(m.style, { backgroundImage: `url("${D.mapa.arquivo}")`, filter: "blur(16px) sepia(.5) brightness(.32)",
                               transform: "scale(1.1)" });
      palco.appendChild(m);
    }
    const prox = texto(el("div", "d-prox t", tx.prox || ""));
    const ins = el("div", "d-guia");
    Object.assign(ins.style, { left: "330px", top: "330px", width: "340px", height: "340px", borderRadius: "50%" });
    ins.appendChild(el("div", "g", tx.inscreva || ""));
    const vid = el("div", "d-guia");
    Object.assign(vid.style, { left: "870px", top: "320px", width: "720px", height: "405px" });
    vid.appendChild(el("div", "g", tx.video || ""));
    const tag = texto(el("div", "d-tag t", c.tema.tagline || ""));
    palco.append(prox, ins, vid, tag);
    [prox, ins, vid, tag].forEach((e, i) =>
      tl.fromTo(e, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.6, ease: "power3.out", immediateRender: false }, t0 + i * 0.2));
    KIT.cue(t0, "whoosh", -10);
    return t0 + 1.4;
  });
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_motion.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add motion/kit/doc.js ui/test_motion.py
rtk git commit -m "feat(doc.js): vinheta de abertura com selo e tela final de 20 s

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `narrado.py` — cenas do modo doc, alinhar no CLI, render com SFX/trilha e créditos

**Files:**
- Modify: `ui/narrado.py` (`cenas_motion` → despacha `_cenas_doc`; `_palco`, `_beat_kit`, `_transicao`, `_cenas_doc`, `_palavras`, `escrever_cenas`, `_voz`, `render`, `descricao`, CLI `alinhar`)
- Test: `ui/test_narrado.py` (acrescentar)

**Interfaces:**
- Consumes: `resolver_beats`, `ritmo`, `RITMO_MAX` (Task 2); `alinhar.alinhar` (Task 1); `audio.mix_sfx(video, cues, sfx_dir, dst)`; `audio.mix_trilha(video, trilha, dst, ..., realces=[(ini, fim)])` e `audio.sfx_kit(dst_dir) -> list[Path]` (Task 9 — este task chama os dois; os testes deste task os substituem por stubs com `monkeypatch`).
- Produces:
  - `narrado.modo_doc(ep) -> bool`
  - `narrado.cenas_motion(ep, lang, duracoes, tema, palavras=None) -> dict` (modo doc quando há beats)
  - `narrado.render(...)` no modo doc: exige `alinhar` em dia; ritmo (aviso no rascunho, erro no final); exige `--trilha` no final; mixa SFX pelos cues e trilha com realce na vinheta e na tela final; devolve `"avisos"`.
  - CLI: `python ui/narrado.py alinhar <proj> [--lang pt]`.

- [ ] **Step 1: Escrever os testes** (acrescentar em `ui/test_narrado.py`)

```python
def test_cenas_motion_doc_vinheta_telafinal_transicoes():
    ep = _ep_doc()
    ep["cenas"][1]["fundo"] = {"tipo": "imagem", "src": "assets/foto.png", "fonte_url": "https://x", "licenca": "CC0",
                               "credito": "x"}
    ep["cenas"][1]["beats"] = [{"faz": "rotulo", "nome": {"pt": "Pelsaert"}}]
    tema = motion.carregar_tema("dark-historia")
    d = narrado.cenas_motion(ep, "pt", {"c01": 9.0, "c02": 3.0}, tema, _palavras(ep))
    assert d["modo"] == "doc" and d["mapa"] == {"arquivo": "assets/foto.png", "pontos": ep["mapa"]["pontos"]}
    assert [c["id"] for c in d["cenas"]] == ["c01", "c900", "c02", "c901"]
    c01, vin, c02, fim = d["cenas"]
    assert c01["tipo"] == "doc" and c01["palco"] == {"tipo": "mapa"} and c01["beats"][2]["s"] == 3.0
    assert vin["tipo"] == "vinheta" and vin["titulo"] == ep["titulo"]["pt"]
    assert c02["palco"] == {"tipo": "imagem", "arquivo": "assets/foto.png"}
    assert fim["tipo"] == "telafinal" and fim["textos"]["inscreva"] == "inscreva-se" and "saida" not in fim
    assert c01["saida"]["transicao"] == "fade" and vin["saida"]["transicao"] == "fade"
    assert c01["dur"] == round(9.0 + narrado.PAUSA + 0.3, 3)               # sem entrada, saída 0.3
    assert vin["dur"] == round(0.3 + narrado.VINHETA_DUR + 0.3, 3) and fim["dur"] == round(0.3 + narrado.TELAFINAL_DUR, 3)


def test_transicao_automatica():
    k = lambda t: {"tipo": "doc", "palco": {"tipo": t}}
    assert narrado._transicao(k("mapa"), k("imagem"))["transicao"] == "mergulho"
    assert narrado._transicao(k("imagem"), k("mapa"))["transicao"] == "recuo"
    assert narrado._transicao(k("imagem"), k("imagem"))["transicao"] == "corte"
    assert narrado._transicao(k("escuro"), {"tipo": "vinheta"})["transicao"] == "fade"


def test_cenas_motion_doc_sem_vinheta_nem_mapa():
    ep = _ep_doc()
    ep.pop("vinheta_apos")
    ep.pop("mapa")
    ep["cenas"][0]["fundo"] = {"tipo": "escuro"}
    ep["cenas"][0]["beats"] = [{"faz": "rotulo", "nome": {"pt": "x"}}]
    d = narrado.cenas_motion(ep, "pt", {"c01": 2.0, "c02": 2.0}, motion.carregar_tema("dark-historia"), _palavras(ep))
    assert [c["id"] for c in d["cenas"]] == ["c01", "c02", "c901"] and "mapa" not in d


def test_cena_motion_antiga_segue_no_modo_doc():
    ep = _ep_doc()
    d = narrado.cenas_motion(ep, "pt", {"c01": 9.0, "c02": 3.0}, motion.carregar_tema("dark-historia"), _palavras(ep))
    c02 = next(c for c in d["cenas"] if c["id"] == "c02")
    assert c02["tipo"] == "frase"           # cena motion antiga, sem beats, segue como era


def test_escrever_cenas_doc_exige_alinhar_em_dia(tmp_path, root, mp3):
    p = _proj(tmp_path, _ep_doc())
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    with pytest.raises(ValueError, match="rode alinhar"):
        narrado.escrever_cenas(p, "pt")
    st = narrado.estado(p, "pt")
    pal = _palavras(narrado.ler(p))
    for cid in pal:
        pal[cid]["hash"] = st[cid]["hash"]
    pal["c02"]["hash"] = "velho"                       # texto mudou depois do alinhar
    (p / "pt" / "palavras.json").write_text(json.dumps(pal), encoding="utf-8")
    with pytest.raises(ValueError, match="rode alinhar.*c02"):
        narrado.escrever_cenas(p, "pt")


def _alinhado(p):
    st = narrado.estado(p, "pt")
    pal = _palavras(narrado.ler(p))
    for cid in pal:
        pal[cid]["hash"] = st[cid]["hash"]
    (p / "pt" / "palavras.json").write_text(json.dumps(pal), encoding="utf-8")


@ffmpeg
def test_render_doc_sfx_trilha_realces_e_ritmo(tmp_path, root, mp3, monkeypatch):
    p = _proj(tmp_path, _ep_doc())
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    _alinhado(p)
    chamadas = {}

    def fake_render(proj, rascunho=False, lang=None, motion_dir=None):
        r = _fake_render(proj, rascunho, lang, motion_dir)
        (proj / f"cues.{lang}.json").write_text(json.dumps([{"t": 0.5, "som": "ping", "ganho_db": -6}]), encoding="utf-8")
        return r
    monkeypatch.setattr(motion, "render", fake_render)
    monkeypatch.setattr(audio, "sfx_kit", lambda d: [], raising=False)   # existe só após o Task 9
    monkeypatch.setattr(audio, "mix_sfx", lambda v, cues, d, dst: (chamadas.setdefault("sfx", cues), shutil.copy2(v, dst))[1])
    monkeypatch.setattr(audio, "mix_trilha", lambda v, t, dst, realces=(): (chamadas.setdefault("realces", realces),
                                                                            shutil.copy2(v, dst))[1])
    with pytest.raises(ValueError, match="trilha"):
        narrado.render(p, "pt")                                   # final sem trilha
    r = narrado.render(p, "pt", rascunho=True)
    assert r["ok"] and Path(chamadas["sfx"]).name == "cues.pt.json"
    tempos = json.loads((p / "motion.pt" / "tempos.json").read_text(encoding="utf-8"))
    esperado = [(c["ini"], round(c["ini"] + c["dur"], 3)) for c in tempos["cenas"] if c["id"] in ("c900", "c901")]
    trilha = tmp_path / "t.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=100:d=2", str(trilha)], check=True)
    r = narrado.render(p, "pt", rascunho=True, trilha=trilha)
    assert chamadas["realces"] == esperado
    assert all("sem beat" in a for a in r["avisos"])              # c02 (fala de teste) sem beats → aviso, não erro


def test_descricao_inclui_creditos_de_mapa_fundo_e_inserto(tmp_path):
    ep = _ep_doc()
    ep["cenas"][1]["beats"] = [{"faz": "inserto", "src": "assets/foto.png", "fonte_url": "https://ins",
                                "licenca": "CC BY 4.0", "credito": "Museu"}]
    p = _proj(tmp_path, ep)
    narrado.descricao(p, "pt")
    txt = (p / "pt" / "descricao.md").read_text(encoding="utf-8")
    assert "Blaeu, 1650" in txt and "Museu — https://ins (CC BY 4.0)" in txt
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_narrado.py -q -k "doc or transicao or overlay or descricao_inclui"`
Expected: FAIL (`cenas_motion() takes 4 positional arguments but 5 were given` etc.)

- [ ] **Step 3: Implementar**

Constantes (perto de `PAUSA`):
```python
VINHETA_DUR = 4.0
TELAFINAL_DUR = 20.0
TEXTOS_FIM = {"pt": {"prox": "Próxima história", "inscreva": "inscreva-se", "video": "próximo vídeo"},
              "en": {"prox": "Next story", "inscreva": "subscribe", "video": "next video"}}
SFX_DIR = pipeline.ROOT / "motion" / "sfx"
```
Funções (antes de `cenas_motion`):
```python
def modo_doc(ep: dict) -> bool:
    return any(c.get("beats") for c in ep.get("cenas", []))


def _palco(c: dict) -> dict | None:
    f = c.get("fundo")
    if f:
        return {"tipo": "imagem", "arquivo": f["src"]} if f["tipo"] == "imagem" else {"tipo": f["tipo"]}
    v = c["visual"]
    return {"tipo": "imagem", "arquivo": v["src"]} if v["tipo"] in ("arquivo", "ia") else None


def _beat_kit(b: dict) -> dict:
    k = {key: v for key, v in b.items() if key != "em"}
    if k["faz"] == "inserto":
        k["arquivo"] = k.pop("src")
        for x in ("fonte_url", "licenca", "credito"):
            k.pop(x, None)
    for lst in ("itens", "marcos"):
        if lst in k:
            k[lst] = [{"t": x} if isinstance(x, str) else {kk: vv for kk, vv in x.items() if kk != "em"} for x in k[lst]]
    return k


def _transicao(a: dict, b: dict) -> dict:
    pa = a.get("palco", {}).get("tipo") if a["tipo"] == "doc" else a["tipo"]
    pb = b.get("palco", {}).get("tipo") if b["tipo"] == "doc" else b["tipo"]
    if pa == "mapa" and pb == "imagem":
        return {"transicao": "mergulho", "dur": 0.6}
    if pa == "imagem" and pb == "mapa":
        return {"transicao": "recuo", "dur": 0.6}
    if pa == pb == "imagem":
        return {"transicao": "corte", "dur": 0.1}
    return {"transicao": "fade", "dur": 0.3}


def _cenas_doc(ep: dict, lang: str, duracoes: dict, palavras: dict) -> dict:
    lista = []
    for c in ep["cenas"]:
        p = _palco(c)
        if p is None and not c.get("beats"):
            k = _loc(copy.deepcopy(c["visual"]["cena"]), lang)          # cartão motion antigo
        else:
            beats = [_beat_kit(b) for b in resolver_beats(c, lang, palavras)] if c.get("beats") else []
            label = _loc(c.get("overlay"), lang)
            if label and not any(b["faz"] == "rotulo" for b in beats):
                beats.append({"faz": "rotulo", "nome": label, "s": 0.3})
            k = {"tipo": "doc", "fundo": "escuro", "palco": p or {"tipo": "escuro"}, "beats": beats}
        k = {"id": c["id"], **k, "_fala": duracoes[c["id"]], "_saida": c.get("saida")}
        lista.append(k)
        if c["id"] == ep.get("vinheta_apos"):
            titulo = _loc(ep.get("titulo_curto"), lang) or _loc(ep.get("titulo"), lang) or ""
            lista.append({"id": "c900", "tipo": "vinheta", "fundo": "escuro", "titulo": titulo, "_fala": None})
    lista.append({"id": "c901", "tipo": "telafinal", "fundo": "escuro",
                  "textos": TEXTOS_FIM.get(lang, TEXTOS_FIM["pt"]), "_fala": None})
    for n, k in enumerate(lista[:-1]):
        k["saida"] = k.get("_saida") or _transicao(k, lista[n + 1])
    for n, k in enumerate(lista):
        entra = lista[n - 1]["saida"]["dur"] if n else 0.0
        sai = k["saida"]["dur"] if "saida" in k else 0.0
        fala = k.pop("_fala")
        k.pop("_saida", None)
        corpo = fala + PAUSA if fala is not None else (VINHETA_DUR if k["tipo"] == "vinheta" else TELAFINAL_DUR)
        k["dur"], k["dur_piso"] = round(entra + corpo + sai, 3), True
    d = {"marca": ep["marca"], "aspecto": "16:9", "modo": "doc", "cenas": lista}
    if ep.get("mapa"):
        d["mapa"] = {"arquivo": ep["mapa"]["src"], "pontos": ep["mapa"]["pontos"]}
    return d
```
Trocar a assinatura e o começo de `cenas_motion`:
```python
def cenas_motion(ep: dict, lang: str, duracoes: dict, tema: dict, palavras: dict | None = None) -> dict:
    """dur de cada cena = entrada (saída da anterior) + fala + PAUSA + própria saída: voz nunca acelera."""
    if modo_doc(ep):
        return _cenas_doc(ep, lang, duracoes, palavras or {})
    out, entra = [], 0.0
```
Função `_palavras` (depois de `estado`):
```python
def _palavras(proj: Path, lang: str, ep: dict, st: dict) -> dict:
    pal = pipeline.read_json(_dir(proj, lang) / "palavras.json", {})
    velhas = [c["id"] for c in ep["cenas"] if pal.get(c["id"], {}).get("hash") != st.get(c["id"], {}).get("hash")]
    if velhas:
        raise ValueError(f"rode alinhar antes: palavras ausentes ou desatualizadas em {', '.join(velhas)}")
    return pal
```
Em `escrever_cenas`, trocar a linha `d = cenas_motion(...)` por:
```python
    pal = _palavras(proj, lang, ep, st) if modo_doc(ep) else None
    d = cenas_motion(ep, lang, {k: v["dur"] for k, v in st.items()}, motion.carregar_tema(ep["marca"]), pal)
    if d.get("mapa"):
        from PIL import Image
        with Image.open(proj / d["mapa"]["arquivo"]) as im:
            d["mapa"]["w"], d["mapa"]["h"] = im.size
```
(manter o `from PIL import Image` e o laço do `contain` que já existem logo abaixo.)

Em `_voz`, trocar o laço para ignorar cenas sem fala:
```python
    off, ins, fs = offsets(tempos), [], []
    cenas = [c for c in tempos["cenas"] if c["id"] in st]
    for k, c in enumerate(cenas):
        ins += ["-i", str(proj / st[c["id"]]["audio"])]
        fs.append(f"[{k}:a]aresample=48000,adelay={int(round(off[c['id']] * 1000))}:all=1[a{k}]")
    n = len(cenas)
```
Substituir `render` inteiro:
```python
def render(proj, lang: str, rascunho: bool = False, trilha=None) -> dict:
    proj = Path(proj)
    ep = ler(proj)
    doc, avisos = modo_doc(ep), []
    if doc:
        st0 = estado(proj, lang)
        pal = _palavras(proj, lang, ep, st0)
        for c in ep["cenas"]:
            beats = resolver_beats(c, lang, pal) if c.get("beats") else []
            avisos += ritmo(c["id"], beats, st0[c["id"]]["dur"])
        if avisos and not rascunho:
            raise ValueError("ritmo: " + "; ".join(avisos))
        if not trilha and not rascunho:
            raise ValueError("render final do modo doc exige --trilha (canal/trilhas/)")
    escrever_cenas(proj, lang)
    r = motion.render(proj, rascunho, lang)
    if not r.get("ok"):
        return r
    tempos = pipeline.read_json(proj / f"motion.{lang}" / "tempos.json", None)
    if not tempos:
        raise RuntimeError(f"motion.{lang}/tempos.json ilegível após render")
    st = estado(proj, lang)
    voz = _voz(proj, lang, tempos, st)
    out = _dir(proj, lang) / ("final_rascunho.mp4" if rascunho else "final.mp4")
    tmp = out.with_name(f".{out.stem}.voz.mp4")
    tmp2 = out.with_name(f".{out.stem}.sfx.mp4")
    try:
        _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy", *audio.AAC, str(tmp)])
        base = tmp
        cues = proj / f"cues.{lang}.json"
        if doc and cues.is_file() and json.loads(cues.read_text(encoding="utf-8")):
            if not SFX_DIR.is_dir():
                audio.sfx_kit(SFX_DIR)
            audio.mix_sfx(tmp, cues, SFX_DIR, tmp2)
            base = tmp2
        if trilha:
            realces = [(c["ini"], round(c["ini"] + c["dur"], 3)) for c in tempos["cenas"] if c["id"] in ("c900", "c901")]
            audio.mix_trilha(base, Path(trilha), out, realces=realces)        # ducking + realce + loudnorm −14
        else:
            _ff(["-i", str(base), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                 "-af", "loudnorm=I=-14:TP=-1:LRA=11", *audio.AAC, "-movflags", "+faststart", str(out)])
    finally:
        tmp.unlink(missing_ok=True)
        tmp2.unlink(missing_ok=True)
    legenda = out.with_suffix(".srt")
    legenda.write_text(srt(ep, lang, tempos, st), encoding="utf-8")
    return {"ok": True, "video": str(out), "srt": str(legenda), "duracao": tempos["duracao"], "avisos": avisos}
```
Em `descricao`, trocar o laço de créditos por:
```python
    creditos = []

    def credita(d):
        if d and d.get("src") and d.get("credito"):
            linha = f"{d['credito']} — {d['fonte_url']} ({d['licenca']})"
            if linha not in creditos:
                creditos.append(linha)
    credita(ep.get("mapa"))
    for c in ep["cenas"]:
        if c["visual"]["tipo"] == "arquivo":
            credita(c["visual"])
        credita(c.get("fundo") if isinstance(c.get("fundo"), dict) and c["fundo"].get("tipo") == "imagem" else None)
        for b in c.get("beats") or []:
            if b.get("faz") == "inserto":
                credita(b)
```
No `_cli`, antes de `if ns.cmd == "render":`:
```python
    if ns.cmd == "alinhar":
        return alinhar.alinhar(p, ns.lang), 0
```
No bloco `__main__`, trocar a tupla de subcomandos:
```python
    for nome in ("validar", "tts", "alinhar", "render", "thumb", "descricao"):
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_narrado.py -q`
Expected: PASS (inclusive os antigos: `test_render_mixa_voz_e_gera_srt` segue no caminho sem doc)

- [ ] **Step 5: Commit**

```bash
rtk git add ui/narrado.py ui/test_narrado.py
rtk git commit -m "feat(narrado): cenas do modo doc, vinheta/tela final, alinhar no CLI, render com SFX e realce de trilha

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `audio.py` — kit de SFX sintetizado e realce da trilha

**Files:**
- Modify: `ui/audio.py` (`SONS`, `ALIASES`, `sfx_kit`, `mix_trilha(..., realces=())`, CLI `sfx-kit`)
- Test: `ui/test_audio.py` (acrescentar)
- Create (gerado e commitado): `motion/sfx/*.wav`

**Interfaces:**
- Produces: `audio.sfx_kit(dst: Path) -> list[Path]` (gera `whoosh, impacto, ping, tique, maquina, carimbo, clarao` + aliases dos cues antigos do kit: `tick, rise, whoosh-reveal, pop-dourado, click-pill, sting-endcard`); `audio.mix_trilha(video, trilha, dst, nivel_db=-18.0, duck_db=-8.0, fade_s=1.5, realces=(), realce_db=8.0)`.

- [ ] **Step 1: Escrever os testes** (acrescentar em `ui/test_audio.py`)

```python
def test_sfx_kit_gera_todos_os_sons(tmp_path):
    feitos = audio.sfx_kit(tmp_path / "sfx")
    nomes = {p.stem for p in feitos}
    assert {"whoosh", "impacto", "ping", "tique", "maquina", "carimbo", "clarao",
            "tick", "rise", "whoosh-reveal", "pop-dourado", "click-pill", "sting-endcard"} <= nomes
    for p in feitos:
        assert 0.01 < audio.duracao(p) < 1.6, p.name
        assert audio.rms_db(p, 0, audio.duracao(p)) > -45, p.name     # não é silêncio


def test_mix_trilha_realce_sobe_a_trilha_no_trecho(video, trilha, tmp_path):
    dst = tmp_path / "mix.mp4"
    audio.mix_trilha(video, trilha, dst, realces=[(4.0, 5.0)])
    com = audio.rms_db(dst, 4.2, 4.9, BP100)        # voz desligada em 4–5 s, com realce
    sem = audio.rms_db(dst, 6.2, 6.9, BP100)        # voz desligada em 6–7 s, sem realce
    assert com > sem + 5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_audio.py -q -k "sfx_kit or realce"`
Expected: FAIL (`AttributeError: module 'audio' has no attribute 'sfx_kit'` / `unexpected keyword argument 'realces'`)

- [ ] **Step 3: Implementar**

Em `ui/audio.py`, depois de `ROOT = pipeline.ROOT`:
```python
# SFX sintetizados (lavfi): sem custo nem licença. Volume baixo: o mix aplica ganho_db de cada cue.
SONS = {
    "whoosh": "anoisesrc=d=0.6:c=pink:a=0.6,highpass=f=300,lowpass=f=2800,afade=t=in:d=0.25,afade=t=out:st=0.3:d=0.3",
    "impacto": "sine=f=55:d=0.6,volume=1.6,afade=t=out:st=0.05:d=0.55",
    "ping": "sine=f=1320:d=0.8,volume=0.5,afade=t=out:st=0.02:d=0.78:curve=exp",
    "tique": "sine=f=2000:d=0.03,volume=0.5,afade=t=out:st=0.005:d=0.025",
    "maquina": "anoisesrc=d=0.04:c=white:a=0.8,highpass=f=2000,afade=t=out:st=0.005:d=0.035",
    "carimbo": "anoisesrc=d=0.25:c=brown:a=1,lowpass=f=400,volume=2,afade=t=out:st=0.02:d=0.23",
    "clarao": "anoisesrc=d=0.5:c=white:a=0.4,highpass=f=4000,afade=t=in:d=0.05,afade=t=out:st=0.1:d=0.4",
}
ALIASES = {"tick": "tique", "rise": "whoosh", "whoosh-reveal": "whoosh", "pop-dourado": "ping",
           "click-pill": "maquina", "sting-endcard": "impacto"}   # cues dos tipos antigos do kit


def sfx_kit(dst: Path) -> list[Path]:
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    feitos = []
    for nome, grafo in SONS.items():
        p = dst / f"{nome}.wav"
        _ff(["-f", "lavfi", "-i", grafo, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(p)])
        feitos.append(p)
    for nome, origem in ALIASES.items():
        p = dst / f"{nome}.wav"
        p.write_bytes((dst / f"{origem}.wav").read_bytes())
        feitos.append(p)
    return feitos
```
Trocar `mix_trilha`:
```python
def mix_trilha(video: Path, trilha: Path, dst: Path, nivel_db: float = -18.0,
               duck_db: float = -8.0, fade_s: float = 1.5, realces=(), realce_db: float = 8.0) -> Path:
    dur = duracao(video)
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    realce = ""
    if realces:   # trilha sobe nos trechos sem fala (vinheta, tela final)
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in realces)
        realce = f",volume=volume='if({expr},{10 ** (realce_db / 20):.4f},1)':eval=frame"
    graph = (
        f"[0:a]{fmt},asplit=2[voz][sc];"
        f"[1:a]aloop=loop=-1:size=2000000000,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,{fmt},"
        f"volume={nivel_db}dB{realce},afade=t=in:d={fade_s},afade=t=out:st={max(dur - fade_s, 0):.3f}:d={fade_s}[tr];"
        f"[tr][sc]sidechaincompress=threshold=0.05:ratio={_ratio(duck_db):.3f}:attack=200:release=800[duck];"
        f"[voz][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11[out]"
    )
    return _atomico(dst, ["-i", str(video), "-i", str(trilha), "-filter_complex", graph,
                          "-map", "0:v", "-map", "[out]", "-c:v", "copy", *AAC, "-movflags", "+faststart"])
```
No CLI de `audio.py` (onde ficam os `sub.add_parser`), acrescentar o subcomando e o despacho, seguindo o padrão dos existentes:
```python
    p = sub.add_parser("sfx-kit"); p.add_argument("dst", nargs="?", default=str(ROOT / "motion" / "sfx"))
```
e no despacho:
```python
    if ns.cmd == "sfx-kit":
        return {"sons": [str(x) for x in sfx_kit(Path(ns.dst))]}, 0
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_audio.py -q`
Expected: PASS

- [ ] **Step 5: Gerar o kit no repositório e commitar**

Run: `python ui/audio.py sfx-kit`
Expected: JSON com 13 caminhos em `motion/sfx/`.

```bash
rtk git add ui/audio.py ui/test_audio.py motion/sfx
rtk git commit -m "feat(audio): kit de SFX sintetizado e realce da trilha por trecho

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: amostra golden do modo doc

**Files:**
- Create: `motion/amostras/doc/cenas.json`, `motion/amostras/doc/assets/mapa.png` (gerado), `motion/amostras/doc/assets/foto.png` (gerado)
- Modify: `ui/test_motion_golden.py` (acrescentar `test_golden_doc`)
- Create (gerado): `motion/amostras/ref/doc-*.png`

**Interfaces:**
- Consumes: tudo dos Tasks 3–7; `motion.render`.

- [ ] **Step 1: Criar a amostra**

Gerar as imagens (a partir de `D:\Projetos\video_editor`):
```bash
mkdir -p motion/amostras/doc/assets
ffmpeg -v error -y -f lavfi -i "testsrc2=s=1600x1200:d=1" -frames:v 1 motion/amostras/doc/assets/mapa.png
ffmpeg -v error -y -f lavfi -i "mandelbrot=s=1920x1080" -frames:v 1 motion/amostras/doc/assets/foto.png
```
`motion/amostras/doc/cenas.json`:
```json
{"marca": "dark-historia", "aspecto": "16:9", "modo": "doc",
 "mapa": {"arquivo": "assets/mapa.png", "pontos": {"cabo": [120, 1100], "abrolhos": [1300, 800], "batavia": [1250, 300]},
          "w": 1600, "h": 1200},
 "cenas": [
  {"id": "c01", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "mapa"}, "dur": 6, "dur_piso": true,
   "saida": {"transicao": "mergulho", "dur": 0.6},
   "beats": [{"faz": "data", "t": "Junho 1629", "s": 0.3},
             {"faz": "rota", "de": "cabo", "para": "abrolhos", "navio": true, "s": 0.8},
             {"faz": "ponto", "ponto": "abrolhos", "rotulo": "Houtman Abrolhos", "s": 2.8},
             {"faz": "contador", "valor": 300, "legenda": "sobreviventes", "pontos": true, "s": 3.2}]},
  {"id": "c02", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "imagem", "arquivo": "assets/foto.png"}, "dur": 4,
   "dur_piso": true, "saida": {"transicao": "recuo", "dur": 0.6},
   "beats": [{"faz": "camera", "area": [0.4, 0.3, 0.3, 0.3], "s": 0.2},
             {"faz": "palavras", "palavras": ["ilhas", "sem", "água"], "risco": "água", "s": 1.0, "ts": [1.0, 1.3, 1.5]}]},
  {"id": "c03", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "mapa"}, "dur": 4, "dur_piso": true,
   "saida": {"transicao": "fade", "dur": 0.3},
   "beats": [{"faz": "rota", "de": "abrolhos", "para": "batavia", "km": 3000, "s": 0.4}]},
  {"id": "c900", "tipo": "vinheta", "fundo": "escuro", "titulo": "O massacre do Batavia", "dur": 4, "dur_piso": true,
   "saida": {"transicao": "fade", "dur": 0.3}},
  {"id": "c901", "tipo": "telafinal", "fundo": "escuro", "dur": 3, "dur_piso": true,
   "textos": {"prox": "Próxima história", "inscreva": "inscreva-se", "video": "próximo vídeo"}}]}
```

- [ ] **Step 2: Escrever o teste** (acrescentar em `ui/test_motion_golden.py`)

```python
def test_golden_doc(tmp_path):
    p = tmp_path / "doc"
    shutil.copytree(AMOSTRAS / "doc", p)
    r = motion.render(p)
    assert r["ok"], r
    video = p / "video.mp4"
    tempos = json.loads((p / "motion" / "tempos.json").read_text(encoding="utf-8"))
    cenas = {c["id"]: c for c in tempos["cenas"]}
    # câmera nunca parada: dois quadros de c01 no mesmo trecho sem beat diferem além do grão
    c1 = cenas["c01"]
    a = _frame(video, c1["ini"] + 4.4, tmp_path / "cam-a.png")
    b = _frame(video, c1["ini"] + 5.3, tmp_path / "cam-b.png")
    assert _psnr(a, b) < 32, "câmera parada em c01"   # calibrar com o piso de grão (padrão do test_golden) se ficar instável
    REF.mkdir(parents=True, exist_ok=True)
    ruins = []
    marcos = [("c01", 1.5), ("c01", 4.0), ("c02", 0.6), ("c02", 2.2), ("c03", 2.0), ("c900", 2.5), ("c901", 2.0)]
    for cid, dt in marcos:
        png = _frame(video, cenas[cid]["ini"] + dt, tmp_path / f"doc-{cid}-{dt}.png")
        ref = REF / png.name
        if MODO == "atualizar":
            shutil.copy2(png, ref)
            continue
        assert ref.exists(), f"sem referência {ref.name}: rodar MOTION_GOLDEN=atualizar"
        if (val := _psnr(png, ref)) < 35:
            ruins.append(f"{png.name}: {val:.1f} dB")
    assert not ruins, ruins
```

- [ ] **Step 3: Gerar referências e revisar**

Run: `MOTION_GOLDEN=atualizar python -m pytest ui/test_motion_golden.py -q -k doc` (PowerShell: `$env:MOTION_GOLDEN="atualizar"; python -m pytest ui/test_motion_golden.py -q -k doc`)
Expected: PASS; 7 arquivos `motion/amostras/ref/doc-*.png`. Abrir cada PNG (Read) e conferir: data no canto, rota dourada e navio, chip "Houtman Abrolhos" junto ao ponto, painel 300 com pontos, palavras com risco em "água", régua "3.000 km", selo K com "KRYVANTIS" e título, quadros-guia da tela final. Se algum estiver errado, corrigir o `doc.js` e regerar.

- [ ] **Step 4: Rodar em modo comparação**

Run: `MOTION_GOLDEN=1 python -m pytest ui/test_motion_golden.py -q`
Expected: PASS (inclusive o golden antigo dos reels)

- [ ] **Step 5: Commit**

```bash
rtk git add motion/amostras/doc motion/amostras/ref/doc-*.png ui/test_motion_golden.py
rtk git commit -m "test(golden): amostra do modo doc com mapa, beats, transições, vinheta e tela final

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: receita e documentação do canal (repo `D:\Projetos\dark_videos`)

**Files:**
- Modify: `D:\Projetos\dark_videos\Formatos\dark-historia.md`
- Create: `D:\Projetos\dark_videos\canal\trilhas.json`
- Modify: `D:\Projetos\dark_videos\.gitignore` (acrescentar `canal/trilhas/`)

- [ ] **Step 1: Atualizar a receita**

No frontmatter, trocar a lista de etapas por:
```
etapas: [pauta, pesquisa, roteiro, humanizer, gate1, tts, alinhar, direcao, visuais, render, gate2, pacote]
```
e a linha de etapas do topo por:
```
> Etapas: pauta → pesquisa → roteiro → humanizer → **Gate 1** → tts → alinhar → direção → visuais → render → **Gate 2** → pacote
```
Depois da seção `## 5. TTS`, inserir:
```markdown
## 5b. Alinhar
`python $VE/ui/narrado.py alinhar $EP` → `$EP/pt/palavras.json` (tempo de cada palavra; faster-whisper local, grátis; 1ª vez baixa ~460 MB).
Erro "só N/M palavras casadas" numa cena: ouvir o mp3 da cena; texto mudou depois do TTS → rodar tts de novo.

## 5c. Direção (beats)
No `episodio.json`:
- `mapa`: mapa de época (licença aceita, mesmo formato de `visual.arquivo` com `src`) + `pontos` {nome: [x, y]} em pixels do arquivo original.
- `vinheta_apos`: id da última cena do gancho (a vinheta entra depois dela). `titulo_curto` (≤ 5 palavras) para a vinheta.
- Por cena: `fundo` (`mapa` | `imagem` com src/licença | `escuro`) e `beats` (vocabulário no spec do motor:
  `docs/superpowers/specs/2026-10-09-motion-documental-design.md` no video_editor; `selo` = selo K pulsando, usado na chamada final).
- Regras: todo dado dito em voz ganha beat na palavra (`em`); nenhum trecho > 6 s sem beat (o render final recusa);
  violência nunca vira beat ilustrativo; números de mortos entram como `contador`.
- Chamada final: `{"em": "inscreva", "faz": "selo"}` + `{"em": "referências", "faz": "lista", "itens": [nomes das fontes do pesquisa.md]}`.
- Validar: `python $VE/ui/narrado.py validar $EP` → `ok: true`.
```
Na seção `## 7. Render`, trocar os passos por:
```markdown
1. Rascunho: `python $VE/ui/narrado.py render $EP --rascunho [--trilha canal/trilhas/<faixa>]` → resultado traz `avisos` de ritmo.
2. Folha de QC: `python $VE/ui/motion.py folha $EP --lang pt` → olhar `$EP/qc/folha.pt.png`.
3. Final: `python $VE/ui/narrado.py render $EP --trilha canal/trilhas/<faixa>` (trilha obrigatória; ritmo sem avisos) → `$EP/pt/final.mp4` + `final.srt`.
```
Na seção `## 9. Pacote e upload`, acrescentar:
```markdown
- Trilha com atribuição (`canal/trilhas.json`): colar a linha `atribuicao` no fim da `descricao.md`.
- Depois do upload, no YouTube Studio: elementos finais nos quadros-guia da tela final (inscrever = círculo à esquerda; vídeo = retângulo à direita).
```

- [ ] **Step 2: Criar `canal/trilhas.json`**

```json
{"faixas": [], "nota": "Preencher com {arquivo, licenca, atribuicao} de cada faixa baixada da YouTube Audio Library para canal/trilhas/ (fora do git)."}
```

- [ ] **Step 3: `.gitignore`**

Acrescentar a linha:
```
canal/trilhas/
```

- [ ] **Step 4: Commit (no repo dark_videos)**

```bash
cd /d/Projetos/dark_videos
rtk git add Formatos/dark-historia.md canal/trilhas.json .gitignore
rtk git commit -m "docs(receita): etapas alinhar e direção (beats), trilha e tela final

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: aceite — direção do 001 Batavia e rascunho para o Gate 2

**Files:**
- Modify: `D:\Projetos\dark_videos\episodios\001-batavia\episodio.json` (mídia não vai pro git; o json vai)
- Create: `D:\Projetos\dark_videos\episodios\001-batavia\assets\mapa.jpg` (não commitado)

- [ ] **Step 1: Mapa do episódio**

Baixar "B26055967G - Mar di India.jpg" (Commons, CC0, Janssonius 1650) em largura 3840 para `assets/mapa.jpg` e preencher:
```json
"mapa": {"src": "assets/mapa.jpg", "fonte_url": "https://commons.wikimedia.org/wiki/File:B26055967G_-_Mar_di_India.jpg",
         "licenca": "CC0", "credito": "Johannes Janssonius, Mar di India (c. 1650)",
         "pontos": {"cabo": [120, 2920], "abrolhos": [2636, 2196], "batavia": [2554, 1540], "west_wallabi": [2600, 2160],
                    "long_island": [2650, 2205]}},
"vinheta_apos": "c03",
"titulo_curto": {"pt": "O massacre do Batavia"}
```
(Conferir `west_wallabi`/`long_island` visualmente com um recorte do mapa; nesta escala os três pontos dos Abrolhos ficam a poucos pixels — usar o mesmo ponto com rótulos diferentes é aceitável.)

- [ ] **Step 2: Escrever os beats das 43 cenas**

Regras do Task 11 (seção 5c). Referência obrigatória para as cenas do gancho e de dados:
- c01 (`fundo` mapa): `data` em "junho" ("Junho 1629"); `rota` cabo→abrolhos com navio no início da 1ª frase; `contador` 300 "sobreviventes" com pontos em "trezentas"; `rota` abrolhos→batavia com `km` 3000 em "três".
- c05: `contador` 341 "a bordo" com pontos em "341"; c16: `rota` abrolhos→batavia `km` 3000; c21: `rota` abrolhos→west_wallabi `km` 8; c25: `contador` 100 prefixo "+"; c34: `contador` 115.
- c13 (`imagem` pl2_ilha): `{"faz": "palavras", "palavras": ["rio", "nem", "fonte"], "risco": "fonte"}` (palavras do texto da cena; o validador confere).
- c09: `rotulo` "Jeronimus Cornelisz" / "subcomerciante da VOC"; c27: `rotulo` "Wiebbe Hayes" / "soldado"; c15: `rotulo` "Francisco Pelsaert" / "comandante".
- c04 / c11 / c32: `data` com a data dita.
- c37 / c38: `lista` com `em` por item; c41: `citacao`; c43: `selo` em "inscreva" + `lista` de fontes em "referências".
- Cenas de gravura: `camera` com `area` no detalhe citado (ex.: c15 no escaler) para nada ficar parado.

Run: `python D:/Projetos/video_editor/ui/narrado.py validar episodios/001-batavia` → `ok: true`.

- [ ] **Step 3: Alinhar e render rascunho**

```bash
python D:/Projetos/video_editor/ui/narrado.py alinhar episodios/001-batavia
python D:/Projetos/video_editor/ui/narrado.py render episodios/001-batavia --rascunho
```
Expected: `ok: true`; `avisos` vazio (se houver, acrescentar beats nas cenas citadas e repetir). Gerar a folha de QC e olhar.

- [ ] **Step 4: Gate 2**

Passar ao usuário o caminho de `episodios/001-batavia/pt/final_rascunho.mp4`. Final (com `--trilha`) só depois da trilha baixada e do "ok".

- [ ] **Step 5: Commit (dark_videos, só o json)**

```bash
cd /d/Projetos/dark_videos
rtk git add episodios/001-batavia/episodio.json episodios/001-batavia/pesquisa.md pauta/ideias.md
rtk git commit -m "feat(001): direção do Batavia (mapa, beats, vinheta)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
