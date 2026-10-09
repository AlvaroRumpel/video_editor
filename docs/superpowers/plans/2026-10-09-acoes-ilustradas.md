# Ações ilustradas e frase conectada Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Beat `acao` (vinhetas animadas de atores em silhueta de gravura) e campo `frase` no beat `palavras` (texto na tela é frase conectada da fala), prontos para o episódio 002 (Crippen).

**Architecture:** Validação e resolução de tempos em `ui/narrado.py` (Python, TDD). Renderização em `motion/kit/doc.js` (layout da frase) e num arquivo novo `motion/kit/acoes.js` (rig SVG + GSAP, um modelo por ação), carregado só quando o cenas.json tem beats `acao`. HyperFrames renderiza; nada de Remotion, Lottie ou IA.

**Tech Stack:** Python 3 + pytest, JS (GSAP 3 do `motion/kit/vendor`, HyperFrames 0.8.141), Playwright (já usado por `motion.py` para medir), ffmpeg ≥ 7 (SFX sintetizado).

**Spec:** `docs/superpowers/specs/2026-10-09-acoes-ilustradas-design.md`

## Global Constraints

- Repositório: `D:\Projetos\video_editor`, branch `main`. Rodar testes na raiz: `python -m pytest ui/test_narrado.py -q` (111 passam hoje).
- Custo zero; sem dependência nova (nada de npm/pip novo).
- Tudo que depende do tempo é timeline GSAP ou `KIT.pintor`, nunca `onUpdate`; `fromTo` de algo que começa depois de 0 leva `immediateRender: false` (armadilha do 001).
- Textos visíveis em beats seguem `{"pt": ..., "en": ...}` (dublagem) e usam `texto(el(...))` do `doc.js`.
- Vocabulário de `acao` é fechado e **sem violência** (sem arma, golpe, sangue, corpo). Modelo novo = mudança no kit.
- 001 já publicado não muda: `palavras` com lista continua válido; nenhum `episodio.json` existente quebra.
- Commits em português, uma linha de assunto, terminando com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- `frase` com pontuação e maiúsculas ("Ilha, sem água.") casa com os tokens da fala. (Task 2)
- `frase` localizada: texto EN diferente do PT valida e resolve em cada idioma. (Task 2)
- Episódio sem `atores` com beat `acao`: erro claro, não `KeyError`. (Task 1)
- `anda` com `de` igual a `para`: erro claro, sem animação de comprimento zero. (Task 1)
- Texto de `acao` longo demais para o balão: erro de validação (máx. 40 caracteres). (Task 1)

---

## File Structure

- Modify `ui/narrado.py`: constantes `MODELOS_ACAO`, `TRAJES`; `_v_acao`, `_com_frase`, validação de `atores`; `resolver_beats` (frase); `_cenas_doc` (atores); `avisos_direcao`.
- Modify `ui/motion.py`: `_html` (atores nos dados, `acoes.js` condicional), `_medir`/`montar` (marcas de QC), `folha` (quadros das ações).
- Modify `motion/kit/doc.js`: layout do modo frase em `BEATS.palavras`.
- Create `motion/kit/acoes.js`: rig, atores, modelos, `BEATS.acao`.
- Create `ui/kitframe.py`: quadro PNG de um instante do kit montado (ferramenta de QC).
- Create `motion/amostras/acoes/cenas.json`: amostra com todos os modelos.
- Modify `ui/audio.py`: SFX `morse`. Regenerar `motion/sfx/morse.wav`.
- Modify `ui/test_narrado.py`, `ui/test_motion.py`, `ui/test_audio.py` (se existir teste de `SONS`): testes.
- No repo `dark_videos`: `Formatos/dark-historia.md` (regras `frase` e `acao`).

---

### Task 1: Validar `atores` e beat `acao`

**Files:**
- Modify: `ui/narrado.py` (constantes ~linha 35, `_v_direcao` ~linha 130-200, `validar` ~linha 215)
- Test: `ui/test_narrado.py` (acrescentar no fim)

**Interfaces:**
- Produces: `narrado.MODELOS_ACAO: dict[str, tuple[str, ...]]` (modelo → campos obrigatórios), `narrado.TRAJES: tuple[str, ...]`, `narrado.LADOS_ACAO = ("esq", "centro", "dir")`, `narrado._v_acao(b, ep, lang, e)`.
- Consumes: `_ep_doc()`, `_proj()`, `narrado.validar(ep, proj, lang)` (já existem em `test_narrado.py`).

- [ ] **Step 1: Escrever os testes que falham**

```python
def _ep_acoes():
    ep = _ep_doc()
    ep["atores"] = {"kendall": {"traje": "capitao", "nome": {"pt": "Capitão Kendall"}},
                    "casal": {"traje": ["medico", "menino"]}}
    ep["cenas"][0]["beats"].append(
        {"em": "chegaram", "faz": "acao", "modelo": "olha", "ator": "kendall", "alvo": "casal"})
    return ep


def test_validar_acao_ok(tmp_path):
    p = _proj(tmp_path, _ep_acoes())
    assert narrado.validar(narrado.ler(p), p, "pt") == []


@pytest.mark.parametrize("mut, trecho", [
    (lambda b: b.update(modelo="explodir"), "modelo desconhecido"),
    (lambda b: b.update(ator="fulano"), "ator 'fulano' não existe em atores"),
    (lambda b: b.pop("alvo"), "olha precisa de alvo"),
    (lambda b: b.update(lado="cima"), "lado"),
    (lambda b: b.update(escala=2), "escala"),
    (lambda b: b.update(dur=20), "dur"),
    (lambda b: b.update(texto={"pt": "x" * 41}), "40 caracteres"),
])
def test_validar_acao_erros(tmp_path, mut, trecho):
    ep = _ep_acoes()
    mut(ep["cenas"][0]["beats"][-1])
    p = _proj(tmp_path, ep)
    assert any(trecho in e["motivo"] for e in narrado.validar(narrado.ler(p), p, "pt"))


def test_validar_acao_sem_atores_no_episodio(tmp_path):
    ep = _ep_acoes()
    del ep["atores"]
    p = _proj(tmp_path, ep)
    assert any("ator 'kendall' não existe em atores" in e["motivo"] for e in narrado.validar(narrado.ler(p), p, "pt"))


def test_validar_anda_de_igual_a_para(tmp_path):
    ep = _ep_acoes()
    ep["cenas"][0]["beats"][-1].update(modelo="anda", de="esq", para="esq")
    del ep["cenas"][0]["beats"][-1]["alvo"]
    p = _proj(tmp_path, ep)
    assert any("de e para iguais" in e["motivo"] for e in narrado.validar(narrado.ler(p), p, "pt"))


@pytest.mark.parametrize("traje", ["pirata", [], ["civil"] * 4, 7])
def test_validar_atores_traje_invalido(tmp_path, traje):
    ep = _ep_acoes()
    ep["atores"]["kendall"]["traje"] = traje
    p = _proj(tmp_path, ep)
    assert any("traje" in e["motivo"] for e in narrado.validar(narrado.ler(p), p, "pt"))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_narrado.py -q -k "acao or anda or atores"`
Expected: FAIL (`faz desconhecido: 'acao'` e afins).

- [ ] **Step 3: Implementar**

Em `ui/narrado.py`, junto de `FAZ` (linha ~35): adicionar `"acao": ("modelo",)` ao dict `FAZ` e, abaixo de `FUNDOS_DOC`:

```python
MODELOS_ACAO = {"olha": ("ator", "alvo"), "fala": ("ator", "alvo"), "telegrama": (), "le": ("ator",),
                "aponta": ("ator", "alvo"), "sobe_a_bordo": ("ator",), "anda": ("ator", "para")}
TRAJES = ("capitao", "inspetor", "medico", "secretaria", "menino", "marinheiro", "civil")
LADOS_ACAO = ("esq", "centro", "dir")
```

Antes de `_v_direcao`, a função:

```python
def _v_acao(b: dict, ep: dict, lang: str, e) -> None:
    m = b.get("modelo")
    if m not in MODELOS_ACAO:
        return e(f"modelo desconhecido: {m!r} ({'|'.join(MODELOS_ACAO)})")
    atores = ep.get("atores") if isinstance(ep.get("atores"), dict) else {}
    for campo in MODELOS_ACAO[m]:
        if campo not in b:
            e(f"{m} precisa de {campo}")
    for campo in ("ator", "alvo"):
        if campo in b and b[campo] not in atores:
            e(f"{campo} {b[campo]!r} não existe em atores")
    if b.get("lado", "dir") not in LADOS_ACAO:
        e(f"lado inválido: {b.get('lado')!r} ({'|'.join(LADOS_ACAO)})")
    for campo in ("de", "para"):
        if campo in b and b[campo] not in LADOS_ACAO:
            e(f"{campo} precisa ser {'|'.join(LADOS_ACAO)}")
    if b.get("de") is not None and b.get("de") == b.get("para"):
        e("anda com de e para iguais")
    esc = b.get("escala", 1)
    if isinstance(esc, bool) or not isinstance(esc, (int, float)) or not 0.6 <= esc <= 1.2:
        e("escala precisa estar entre 0,6 e 1,2")
    d = b.get("dur")
    if d is not None and (isinstance(d, bool) or not isinstance(d, (int, float)) or not 1 <= d <= 8):
        e("dur precisa estar entre 1 e 8 s")
    t = _loc(b.get("texto"), lang)
    if isinstance(t, str) and len(t) > 40:
        e("texto da ação com até 40 caracteres")
```

Em `_v_direcao`, logo depois do laço `for campo in FAZ[b["faz"]]` (que exige `modelo`), acrescentar:

```python
        if b["faz"] == "acao":
            _v_acao(b, ep, lang, lambda m, q=q: e(q, m))
```

e trocar a linha que checa pontos do mapa (`for nome in [b.get(x) for x in ("de", "para", "ponto")] + b.get("via", []):`) por:

```python
        for nome in ([] if b["faz"] == "acao" else [b.get(x) for x in ("de", "para", "ponto")] + b.get("via", [])):
```

(`anda` usa `de`/`para` como lado, não como ponto do mapa.)

Em `validar`, antes do laço `for n, c in enumerate(cenas):`, acrescentar:

```python
    at = ep.get("atores")
    if at is not None:
        if not isinstance(at, dict):
            e("atores", "atores precisa ser objeto {nome: {traje}}")
        else:
            for nome, a in at.items():
                tj = a.get("traje") if isinstance(a, dict) else None
                lista = tj if isinstance(tj, list) else [tj]
                if not 1 <= len(lista) <= 3 or not all(x in TRAJES for x in lista):
                    e("atores", f"{nome}: traje inválido {tj!r} ({'|'.join(TRAJES)}; lista de até 3)")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_narrado.py -q`
Expected: tudo passa (111 antigos + novos).

- [ ] **Step 5: Commit**

```bash
git add ui/narrado.py ui/test_narrado.py
git commit -m "feat(narrado): valida atores e beat acao"
```

---

### Task 2: `frase` no beat `palavras` (validar, resolver, aviso)

**Files:**
- Modify: `ui/narrado.py` (`_v_direcao` bloco de `palavras`, `resolver_beats`, `render` retorno, nova `avisos_direcao`)
- Test: `ui/test_narrado.py`

**Interfaces:**
- Produces: `narrado._com_frase(b, lang) -> dict` (beat com `palavras` = palavras da frase, em ordem); `narrado.avisos_direcao(ep, lang) -> list[str]`; beat resolvido mantém `frase` (str localizada) e ganha `palavras` (lista com as palavras da frase como escritas) e `ts`.
- Consumes: `_acha`, `_loc`, `_ach`, `_inicios`, `alinhar.tokens`.

- [ ] **Step 1: Escrever os testes que falham**

```python
def _com_beat(ep, beat):
    ep["cenas"][0]["beats"].append(beat)
    return ep


def test_frase_valida_e_resolve(tmp_path):
    ep = _com_beat(_ep_doc(), {"em": "não", "faz": "palavras", "frase": "Não havia água.", "risco": "água"})
    p = _proj(tmp_path, ep)
    assert narrado.validar(narrado.ler(p), p, "pt") == []
    b = narrado.resolver_beats(ep["cenas"][0], "pt", _palavras(ep))[-1]
    assert b["palavras"] == ["Não", "havia", "água."] and len(b["ts"]) == 3 and b["ts"] == sorted(b["ts"])


def test_frase_com_pontuacao_e_caixa_casa_tokens(tmp_path):
    ep = _com_beat(_ep_doc(), {"em": "Em", "faz": "palavras", "frase": "EM junho, de 1629"})
    p = _proj(tmp_path, ep)
    assert narrado.validar(narrado.ler(p), p, "pt") == []


@pytest.mark.parametrize("frase, trecho", [
    ("junho 1629 chegaram", "contígu"),                       # pula "de" e "cerca"
    ("não havia ouro", "não está no texto"),
    (" ".join(["havia"] * 11), "mais de 10 palavras"),
])
def test_frase_erros(tmp_path, frase, trecho):
    ep = _com_beat(_ep_doc(), {"faz": "palavras", "frase": frase})
    p = _proj(tmp_path, ep)
    assert any(trecho in e["motivo"] for e in narrado.validar(narrado.ler(p), p, "pt"))


def test_frase_localizada(tmp_path):
    ep = _ep_doc_en(["no", "water"])
    ep["cenas"][0]["beats"][0] = {"faz": "palavras", "frase": {"pt": "Não havia água", "en": "There was no water"}}
    p = _proj(tmp_path, ep)
    assert narrado.validar(narrado.ler(p), p, "pt") == []
    b = narrado.resolver_beats(ep["cenas"][0], "en", _palavras(ep, "en"))[0]
    assert b["palavras"] == ["There", "was", "no", "water"]


def test_aviso_palavras_soltas():
    ep = _ep_doc()                                              # tem {"palavras": ["não", "havia", "água"]}
    ep["cenas"][0]["beats"].append({"faz": "palavras", "palavras": ["água"]})
    av = narrado.avisos_direcao(ep, "pt")
    assert len(av) == 2 and all("palavras soltas" in a for a in av) and not narrado.avisos_direcao(
        _com_beat(_ep_doc(), {"faz": "palavras", "frase": "Não havia água"}) and {"cenas": []}, "pt")
```

Atenção: `_ep_doc_en` existe em `test_narrado.py` (linha ~600); ler o corpo dele antes de reutilizar e ajustar o texto EN da cena para conter "There was no water" (a cena EN dele já tem "no water"; acrescentar o texto necessário ao dicionário `texto["en"]` no teste).

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_narrado.py -q -k "frase or palavras_soltas"`
Expected: FAIL.

- [ ] **Step 3: Implementar**

Antes de `_v_direcao`:

```python
def _com_frase(b: dict, lang: str) -> dict:
    """Beat `palavras` com `frase`: `palavras` passa a ser as palavras da frase, como escritas (validar e resolver)."""
    fr = _loc(b["frase"], lang)
    return {**b, "palavras": fr.split() if isinstance(fr, str) else fr}


def avisos_direcao(ep: dict, lang: str) -> list[str]:
    out = []
    for c in ep.get("cenas") or []:
        for b in c.get("beats") or []:
            if isinstance(b, dict) and b.get("faz") == "palavras" and "frase" not in b:
                pal = _loc(b.get("palavras"), lang)
                if isinstance(pal, list) and len(pal) < 4:
                    out.append(f"{c['id']}: palavras soltas ({' '.join(map(str, pal))}); prefira frase da fala")
    return out
```

Em `_v_direcao`, logo depois do bloco `if isinstance(b.get("palavras"), dict): ...` (localização de lista) e antes de `for campo in FAZ[...]`:

```python
        if b["faz"] == "palavras" and "frase" in b:
            if not isinstance(_loc(b["frase"], lang), str):
                e(q, "frase precisa ser texto")
                continue
            b = _com_frase(b, lang)
            if len(b["palavras"]) > 10:
                e(q, "frase com mais de 10 palavras (use citacao)")
                continue
            b["_frase"] = True
```

No laço que ordena as palavras (`for w in (b.get("palavras") or []) if d is not None else []:`), registrar os índices e checar contiguidade; substituir o bloco por:

```python
        d, ks = ini[k - 1], []
        for w in (b.get("palavras") or []) if d is not None else []:
            d = _acha(ws, w, d)
            if d is None:
                e(q, f"palavra {w!r} não está no texto da cena (na ordem do beat)")
                break
            ks.append(d)
            d += 1
        if b.get("_frase") and ks and ks != list(range(ks[0], ks[0] + len(ks))):
            e(q, "frase precisa ser trecho contíguo da fala")
```

Em `resolver_beats`, logo depois de `b["s"] = pal[k]["s"]`, antes do `if b["faz"] == "palavras":`:

```python
        if b["faz"] == "palavras" and "frase" in b:
            b["palavras"] = b["frase"].split()
```

Em `render` (função que monta o retorno, ~linha 718): antes do `return {"ok": True, ...}`, calcular `soltas = avisos_direcao(ep, lang) if doc else []` e devolver `"avisos": avisos + soltas` (avisos de direção não bloqueiam o render final; só o ritmo bloqueia).

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_narrado.py -q`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add ui/narrado.py ui/test_narrado.py
git commit -m "feat(narrado): frase conectada no beat palavras e aviso de palavras soltas"
```

---

### Task 3: Ligar atores e `acoes.js` ao render, marcas de QC na folha

**Files:**
- Modify: `ui/narrado.py` (`_cenas_doc`)
- Modify: `ui/motion.py` (`_html` ~linha 416-422, `_medir` ~linha 485-500, `montar` ~linha 530-545, `folha` ~linha 700)
- Create: `motion/kit/acoes.js` (esqueleto mínimo, completado nas Tasks 5-7)
- Test: `ui/test_narrado.py`, `ui/test_motion.py`

**Interfaces:**
- Produces: `cenas.json` com `"atores"` (localizado); `window.__KIT_DADOS.atores`; `kit/acoes.js` incluído quando algum beat é `acao`; `tempos.json` com `"marcas": [{"id", "rotulo", "t"}]` (t absoluto em s); `folha` ganha um quadro por marca. `window.__marcas` (lista) é onde `acoes.js` registra.
- Consumes: `window.__doc` (`BEATS`, `el`, `svg`, `texto`) já exportado por `doc.js`.

- [ ] **Step 1: Escrever os testes que falham**

Em `ui/test_narrado.py`:

```python
def test_cenas_doc_leva_atores_localizados():
    ep = _ep_acoes()
    d = narrado.cenas_motion(ep, "pt", {"c01": 9.0, "c02": 3.0}, motion.carregar_tema("dark-historia"), _palavras(ep))
    assert d["atores"]["kendall"]["nome"] == "Capitão Kendall" and d["atores"]["casal"]["traje"] == ["medico", "menino"]
    assert any(b["faz"] == "acao" for b in d["cenas"][0]["beats"])
```

Em `ui/test_motion.py` (mesmo padrão dos `test_montar_*`; reaproveitar o helper de projeto que eles usam e o marcador `pw`):

```python
def test_html_carrega_acoes_js_so_com_acao():
    com = {"modo": "doc", "cenas": [{"id": "c01", "tipo": "doc", "beats": [{"faz": "acao", "modelo": "telegrama", "s": 1}]}]}
    sem = {"modo": "doc", "cenas": [{"id": "c01", "tipo": "doc", "beats": [{"faz": "data", "t": "x", "s": 1}]}]}
    assert "kit/acoes.js" in motion._tem_acoes_js(com) and "kit/acoes.js" not in motion._tem_acoes_js(sem)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest ui/test_narrado.py ui/test_motion.py -q -k "atores or acoes_js"`
Expected: FAIL (`KeyError: 'atores'`, `AttributeError: _tem_acoes_js`).

- [ ] **Step 3: Implementar**

`ui/narrado.py`, em `_cenas_doc`, depois do bloco `if ep.get("mapa"):`:

```python
    if ep.get("atores"):
        d["atores"] = _loc(copy.deepcopy(ep["atores"]), lang)
```

`ui/motion.py`: acima de `_html`:

```python
def _tem_acoes_js(d: dict) -> str:
    """<script> extra do kit para o modo doc: doc.js sempre, acoes.js só com beats `acao`."""
    if d.get("modo") != "doc":
        return ""
    s = '\n<script src="kit/doc.js"></script>'
    if any(b.get("faz") == "acao" for c in d["cenas"] for b in c.get("beats", [])):
        s += '\n<script src="kit/acoes.js"></script>'
    return s
```

e em `_html` trocar a linha `extra = '\n<script src="kit/doc.js"></script>' if d.get("modo") == "doc" else ""` por `extra = _tem_acoes_js(d)`; no `json.dumps({...})` de `dados`, acrescentar `"atores": d.get("atores")` ao lado de `"mapa"`.

Em `_medir`, depois de `kit = pg.evaluate(...)`, antes do laço `layout`:

```python
            marcas = pg.evaluate("window.__marcas || []")
```

e no `return {**kit, "layout": layout, "js": js}` incluir `"marcas": marcas`. Em `montar`, onde grava `tempos.json`, trocar o dict por `{"duracao": ..., "aspecto": ..., "cenas": ..., "marcas": m["marcas"]}`.

Em `folha`, depois do laço que monta `pontos` por cena e antes do `pontos = [(i, r, max(...))]`:

```python
    for mk in tempos.get("marcas", []):
        pontos.append((mk["id"], mk["rotulo"], mk["t"]))
```

Criar `motion/kit/acoes.js` com o esqueleto (será completado depois):

```js
/* Ações ilustradas (beat "acao"): vinhetas animadas de atores em silhueta de gravura sobre o palco da cena.
   Carregado depois do doc.js quando o cenas.json traz beats "acao". Tudo que depende do tempo é timeline GSAP. */
(() => {
  "use strict";
  const { BEATS } = window.__doc;
  BEATS.acao = () => { throw new Error("acao: modelos ainda não implementados"); };
})();
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest ui/test_narrado.py ui/test_motion.py -q`
Expected: tudo passa (testes com playwright/ffmpeg só se o ambiente tiver; `node --check motion/kit/acoes.js` também deve passar).

- [ ] **Step 5: Commit**

```bash
git add ui/narrado.py ui/motion.py motion/kit/acoes.js ui/test_narrado.py ui/test_motion.py
git commit -m "feat(motion): atores nos dados do kit, acoes.js condicional e marcas de QC na folha"
```

---

### Task 4: Ferramenta de quadro + layout do modo frase em `doc.js`

**Files:**
- Create: `ui/kitframe.py`
- Modify: `motion/kit/doc.js` (CSS `.d-palavras` ~linha 63-66, `BEATS.palavras` ~linha 273-295)
- Create: `motion/amostras/frase/cenas.json`

**Interfaces:**
- Produces: `python ui/kitframe.py <proj> <t> <dst.png> [--lang L]` (monta se preciso e salva PNG 1920×1080 do instante absoluto `t`). Beat `palavras` com `frase` (string) renderiza a frase inteira em até 2 linhas, palavras entrando em `ats`, fonte 110→64 px conforme o tamanho, `risco` e `destaque` (lista) em cor de acento.
- Consumes: kit montado em `<proj>/motion/index.html` por `motion.montar`.

- [ ] **Step 1: Criar a ferramenta de quadro**

```python
"""Quadro do kit montado: python ui/kitframe.py <proj> <t> <dst.png> [--lang pt]
Roda motion.montar, abre motion/index.html, vai ao instante t (s) e salva o PNG."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import motion  # noqa: E402


def quadro(proj: Path, t: float, dst: Path, lang: str | None = None) -> Path:
    r = motion.montar(proj, lang)
    if not r["ok"]:
        raise RuntimeError(json.dumps(r["erros"], ensure_ascii=False))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        try:
            pg = b.new_page(viewport={"width": 1920, "height": 1080})
            pg.goto(Path(r["index"]).resolve().as_uri())
            pg.wait_for_function("window.__kit !== undefined", timeout=20000)
            pg.evaluate("document.fonts.ready.then(() => true)")
            pg.evaluate("t => __kit.ir(t)", t)
            pg.screenshot(path=str(dst))
        finally:
            b.close()
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("proj"); ap.add_argument("t", type=float); ap.add_argument("dst"); ap.add_argument("--lang")
    ns = ap.parse_args()
    print(quadro(Path(ns.proj), ns.t, Path(ns.dst), ns.lang))
```

- [ ] **Step 2: Amostra de frase**

`motion/amostras/frase/cenas.json` (palco escuro, sem arquivos):

```json
{"marca": "dark-historia", "aspecto": "16:9", "modo": "doc",
 "cenas": [{"id": "c01", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "escuro"}, "dur": 9, "dur_piso": true,
  "beats": [{"faz": "palavras", "frase": "Ordenou que todos fossem para a mesma ilha", "risco": "mesma",
             "palavras": ["Ordenou", "que", "todos", "fossem", "para", "a", "mesma", "ilha"],
             "ts": [0.5, 0.9, 1.2, 1.6, 2.0, 2.2, 2.4, 2.9], "s": 0.5}]}]}
```

- [ ] **Step 3: Rodar a amostra e ver o estado atual (layout de uma linha, vai estourar)**

Run: `python ui/kitframe.py motion/amostras/frase 4 C:/Users/alvar/AppData/Local/Temp/frase_antes.png`
Expected: PNG com as 8 palavras numa linha só, cortando nas bordas (ou erro de layout do `montar`). Abrir o PNG para confirmar.

- [ ] **Step 4: Implementar o modo frase em `doc.js`**

CSS (junto de `.d-palavras`):

```css
.d-palavras.f{display:flex;flex-wrap:wrap;justify-content:center;align-content:center;row-gap:6px;left:200px;right:200px;top:380px;min-height:220px}
.d-palavras.f span{margin:0 12px}
.d-palavras.f b.hl{color:var(--k-acento)}
```

Em `BEATS.palavras`, no início da função (depois de `const limpa`), definir o modo frase e o tamanho da fonte; trocar `const box = el("div", "d-palavras t" + ...)` e o corpo para:

```js
    palavras(ctx, b) {
      const frase = typeof b.frase === "string";
      const box = el("div", "d-palavras t" + (frase ? " f" : "") + (ctx.beats.some((o) => o.faz === "contador") ? " c" : "")), { tl } = ctx.c;
      if (frase) box.style.fontSize = `${b.palavras.length <= 4 ? 110 : b.palavras.length <= 7 ? 84 : 64}px`;
      const ats = b.ats.length ? b.ats : b.palavras.map((_, i) => b.at + i * 0.3);
      const limpa = (w) => String(w).replace(/#\d+$/, "").replace(/[^\p{L}\p{N}']/gu, "").toLowerCase();
      const marca = new Set([b.risco, ...(b.destaque || [])].filter(Boolean).map(limpa));
      mostra(tl, box, b.at);
      b.palavras.forEach((w, i) => {
        const s = texto(el("span", null, String(w).replace(/#\d+$/, "")));
        if (frase && marca.has(limpa(w))) s.classList.add("hl");
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
      const fimP = ats[ats.length - 1] + (b.risco ? 0.55 : 0.25);
      sai(ctx, box, b, fimP);
      return ats[ats.length - 1] + 0.25;
    },
```

Ajuste: `.hl` é classe no próprio `span` (não `b.hl`); trocar o CSS por `.d-palavras.f span.hl{color:var(--k-acento)}`. O `limpa` novo mantém o comportamento antigo para as listas do 001 (o `risco` de "água" casa igual); conferir com `python -m pytest ui/test_motion.py -q` e, se houver, o golden: `MOTION_GOLDEN=1 python -m pytest ui/test_motion_golden.py -q` (opt-in, só se o ambiente já roda).

- [ ] **Step 5: Ver o resultado**

Run: `python ui/kitframe.py motion/amostras/frase 4 C:/Users/alvar/AppData/Local/Temp/frase_depois.png`
Expected: frase em 2 linhas centralizadas, "mesma" em acento e sublinhada, tudo dentro da tela. Abrir o PNG. Se estourar a largura, reduzir os tamanhos de fonte (110/84/64) até caber.

- [ ] **Step 6: Commit**

```bash
git add ui/kitframe.py motion/kit/doc.js motion/amostras/frase/cenas.json
git commit -m "feat(motion): layout de frase conectada e ferramenta de quadro"
```

---

### Task 5: Rig de atores + modelos `olha` e `fala`

**Files:**
- Modify: `motion/kit/acoes.js` (substituir o esqueleto)
- Create: `motion/amostras/acoes/cenas.json`

**Interfaces:**
- Produces: `window.__doc.BEATS.acao(ctx, b)`; funções internas `figura(parent, traje, defsId)`, `pose(tl, f, p, t, d, ease)`, `elenco(S, nome, x, dir)`, `palco(ctx, b, dur)`, `MODELOS`, `DUR`. Contrato de pose: chaves `tr` (tronco, graus), `ca` (cabeça), `bd`/`be` (`[ombro, cotovelo]`), `pd`/`pe` (pernas). Figuras olham para a direita; `dir = -1` espelha.
- Consumes: `window.__KIT_DADOS.atores` (`{nome: {traje: str|[str], nome?: str}}`), `ctx` do `doc.js` (`ctx.c.tl`, `ctx.hud`, `ctx.cena.id`), `KIT.cue`, `KIT.pintor`.

- [ ] **Step 1: Amostra com `olha` e `fala`**

`motion/amostras/acoes/cenas.json`:

```json
{"marca": "dark-historia", "aspecto": "16:9", "modo": "doc",
 "atores": {"kendall": {"traje": "capitao", "nome": "Capitão Kendall"},
            "dew": {"traje": "inspetor"},
            "casal": {"traje": ["medico", "menino"]}},
 "cenas": [{"id": "c01", "tipo": "doc", "fundo": "escuro", "palco": {"tipo": "escuro"}, "dur": 24, "dur_piso": true,
  "beats": [
   {"faz": "acao", "modelo": "olha", "ator": "kendall", "alvo": "casal", "lado": "esq", "s": 0.5},
   {"faz": "acao", "modelo": "fala", "ator": "dew", "alvo": "casal", "texto": "Doutor Crippen?", "lado": "dir", "s": 5}]}]}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python ui/kitframe.py motion/amostras/acoes 2 C:/Users/alvar/AppData/Local/Temp/a.png`
Expected: erro "acao: modelos ainda não implementados".

- [ ] **Step 3: Implementar `acoes.js` (rig, palco, `olha`, `fala`)**

Substituir o conteúdo de `motion/kit/acoes.js` por:

```js
/* Ações ilustradas (beat "acao"): vinhetas animadas de atores em silhueta de gravura sobre o palco da cena.
   Carregado depois do doc.js quando o cenas.json traz beats "acao". Tudo que depende do tempo é timeline GSAP. */
(() => {
  "use strict";
  const { el, svg, texto, BEATS } = window.__doc;
  const TINTA = "#d9cdb0", PRETO = "#15120f", ACENTO = "var(--k-acento)";
  const VW = 560, VH = 360, CHAO = 300, BX = 700, BY = 450;
  const POS = { esq: 130, centro: 280, dir: 430 };
  const LADO = { esq: { left: "100px" }, centro: { left: "610px" }, dir: { right: "100px" } };
  const DUR = { olha: 3.2, fala: 3.6, telegrama: 3.8, le: 3.2, aponta: 2.8, sobe_a_bordo: 4.0, anda: 3.0 };
  let uid = 0;

  const CSS = `
.a-box{position:absolute;bottom:70px;background:radial-gradient(ellipse at 50% 62%,rgba(11,10,8,.78),rgba(11,10,8,0) 72%)}
.a-box svg{position:absolute;inset:0;overflow:visible}
.a-balao{position:absolute;max-width:46%;padding:10px 18px;background:rgba(21,18,15,.94);border:1.5px solid ${TINTA};
  font:italic 400 32px/1.2 var(--k-display-familia);color:#efe6cf;opacity:0}
.a-rot{position:absolute;font:600 22px var(--k-corpo-familia);letter-spacing:.18em;color:var(--k-acento);text-transform:uppercase;
  transform:translateX(-50%);white-space:nowrap;opacity:0}
.a-tira{position:absolute;left:50%;transform:translateX(-50%);padding:8px 18px;background:${TINTA};color:${PRETO};
  font:600 26px var(--k-mono-familia);letter-spacing:.12em;text-transform:uppercase;white-space:nowrap;opacity:0}`;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: CSS }));

  const P = (pai, d, o = {}) => {
    const p = svg("path", { d, fill: o.fill || "none", stroke: o.stroke === undefined ? TINTA : o.stroke,
      "stroke-width": o.w || 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" });
    if (o.op != null) p.setAttribute("opacity", o.op);
    pai.appendChild(p);
    return p;
  };
  const G = (pai, tr) => { const g = svg("g"); if (tr) g.setAttribute("transform", tr); pai.appendChild(g); return g; };

  // ---------- figuras: silhueta de gravura (contorno creme, fundo quase preto, hachura no lado da sombra)
  const TRAJES = {
    capitao:    { chapeu: "M-10 -25Q0 -35 10 -25L11 -21L-11 -21ZM-12 -21L15 -21", bainha: 34, botoes: true },
    inspetor:   { chapeu: "M-9 -22Q-9 -37 0 -37Q9 -37 9 -22ZM-15 -22L15 -22", bainha: 52 },
    medico:     { chapeu: "M-9 -22Q-9 -36 0 -36Q9 -36 9 -22ZM-14 -22L14 -22", bainha: 34, colete: true },
    secretaria: { chapeu: "M-8 -22Q0 -32 8 -22ZM-18 -22Q0 -28 18 -22", bainha: 62, saia: true },
    menino:     { chapeu: "M-10 -23Q0 -33 10 -23L16 -21L-10 -21Z", bainha: 22, escala: 0.82 },
    marinheiro: { chapeu: "M-10 -22Q0 -30 10 -22ZM-10 -22L10 -22", bainha: 34 },
    civil:      { chapeu: "M-9 -22Q-10 -33 0 -34Q10 -33 9 -22Z", bainha: 34 },
  };

  function figura(pai, traje, hach) {
    const T = TRAJES[traje], f = { traje };
    f.mov = G(pai);
    const flip = G(f.mov); f.flip = flip;
    f.bob = G(flip);
    const esc = G(f.bob, `scale(${T.escala || 1})`);
    const perna = (x) => {
      const w = G(esc, `translate(${x} -92)`), i = G(w);
      P(i, "M-4 0L-4 86L-5 90L8 90L5 86L4 0Z", { fill: PRETO });
      return i;
    };
    f.pernaE = perna(-6); f.pernaD = perna(6);
    f.tronco = G(G(esc, "translate(0 -92)"));
    const braco = (x) => {
      const o = G(f.tronco, `translate(${x} -52)`), a = G(o), c = G(a, "translate(0 30)"), d = G(c);
      P(a, "M-3.5 0L-3 30L3 30L3.5 0Z", { fill: PRETO });
      P(d, "M-3 0L-2.5 28L2.5 28L3 0Z", { fill: PRETO });
      d.appendChild(svg("circle", { cx: 0, cy: 30, r: 3.2, fill: PRETO, stroke: TINTA, "stroke-width": 1.2 }));
      return [a, c, o];
    };
    const [beA, beC, beO] = braco(-15);
    f.be = [beA, beC];
    const B = T.bainha;
    const corpo = T.saia ? `M-30 ${B}L-14 -50Q-11 -59 0 -59Q11 -59 14 -50L30 ${B}Z` : `M-17 ${B}L-15 -50Q-12 -59 0 -59Q12 -59 15 -50L17 ${B}Z`;
    P(f.tronco, corpo, { fill: PRETO });
    P(f.tronco, T.saia ? `M-30 ${B}L-14 -50Q-11 -59 0 -59L0 ${B}Z` : `M-17 ${B}L-15 -50Q-12 -59 0 -59L0 ${B}Z`,
      { fill: `url(#${hach})`, stroke: null });
    if (T.colete) P(f.tronco, "M-5 -55L0 -22L5 -55Z", { w: 1.1 });
    if (T.botoes) for (const [x, y] of [[-4, -40], [-4, -28], [4, -40], [4, -28]]) f.tronco.appendChild(svg("circle", { cx: x, cy: y, r: 1.3, fill: TINTA }));
    const [bdA, bdC] = braco(15);
    f.bd = [bdA, bdC];
    f.cabeca = G(f.tronco, "translate(0 -60)");
    f.cabeca.appendChild(svg("ellipse", { cx: 0, cy: -16, rx: 9, ry: 11, fill: PRETO, stroke: TINTA, "stroke-width": 1.6 }));
    P(f.cabeca, "M0 -27A9 11 0 0 0 0 -5Z", { fill: `url(#${hach})`, stroke: null });
    P(f.cabeca, "M8.6 -17L13 -13.5L8.6 -12", { w: 1.3 });
    P(f.cabeca, T.chapeu, { fill: PRETO });
    for (const e of [f.pernaE, f.pernaD, f.tronco, f.cabeca, ...f.be, ...f.bd, f.bob, f.flip]) gsap.set(e, { transformOrigin: "0 0" });
    return f;
  }

  const ALVO = (f) => ({ tr: [f.tronco], ca: [f.cabeca], bd: f.bd, be: f.be, pd: [f.pernaD], pe: [f.pernaE] });
  function pose(tl, f, p, t, d = 0.5, ease = "power2.inOut") {
    const A = ALVO(f);
    for (const k in p) [].concat(p[k]).forEach((v, i) => tl.to(A[k][i], { rotation: v, duration: d, ease }, t));
  }
  function respira(tl, figs, t, dur) {
    for (const f of figs) tl.to(f.bob, { y: -0.9, duration: 1.6, yoyo: true, repeat: Math.ceil(dur / 1.6), ease: "sine.inOut" }, t);
  }
  function passos(tl, f, t, dur, n) {
    const d = dur / (n * 2);
    for (let i = 0; i < n * 2; i++) {
      const s = i % 2 ? 1 : -1;
      pose(tl, f, { pd: 22 * s, pe: -22 * s, bd: [-14 * s, 8], be: [14 * s, 8] }, t + i * d, d, "sine.inOut");
      tl.to(f.bob, { y: i % 2 ? 0 : -2.5, duration: d, ease: "sine.inOut" }, t + i * d);
    }
    pose(tl, f, { pd: 0, pe: 0, bd: [0, 0], be: [0, 0] }, t + dur, 0.3);
  }

  // ---------- vinheta: caixa sobre o palco, com véu, chão e filtro de tremor de gravura
  function palco(ctx, b, dur) {
    const n = ++uid, esc = b.escala || 1, { tl } = ctx.c;
    const box = el("div", "a-box");
    Object.assign(box.style, LADO[b.lado || "dir"], { width: `${BX * esc}px`, height: `${BY * esc}px` });
    const g = svg("svg", { viewBox: `0 0 ${VW} ${VH}`, width: "100%", height: "100%" });
    const defs = svg("defs");
    const pat = svg("pattern", { id: `h${n}`, width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    pat.appendChild(svg("line", { x1: 0, y1: 0, x2: 0, y2: 4, stroke: TINTA, "stroke-width": 0.7, opacity: 0.5 }));
    const turb = svg("feTurbulence", { type: "fractalNoise", baseFrequency: 0.03, numOctaves: 1, seed: 1 });
    const filt = svg("filter", { id: `t${n}`, x: "-5%", y: "-5%", width: "110%", height: "110%" });
    filt.append(turb, svg("feDisplacementMap", { in: "SourceGraphic", scale: 1.2 }));
    defs.append(pat, filt);
    g.appendChild(defs);
    const cena = G(g);
    cena.setAttribute("filter", `url(#t${n})`);
    P(cena, `M20 ${CHAO}H540`, { w: 1.2, op: 0.55 });
    P(cena, `M60 ${CHAO + 8}H200M260 ${CHAO + 8}H430`, { w: 0.8, op: 0.3 });
    box.appendChild(g);
    ctx.hud.appendChild(box);
    KIT.pintor((t) => turb.setAttribute("seed", String(Math.floor(t * 12) % 9)));
    tl.fromTo(box, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out", immediateRender: false }, b.at);
    tl.to(box, { opacity: 0, duration: 0.35 }, b.at + dur - 0.35);
    return { box, g: cena, tl, at: b.at, dur, hach: `h${n}`, esc };
  }

  // ator (ou grupo) em x do chão, olhando para a direita (dir = 1) ou esquerda (dir = -1)
  function elenco(S, nome, x, dir) {
    const a = window.__KIT_DADOS.atores[nome], trajes = [].concat(a.traje);
    const figs = trajes.map((tj, i) => {
      const f = figura(S.g, tj, S.hach);
      f.flip.setAttribute("transform", `scale(${dir} 1)`);
      gsap.set(f.mov, { x: x + i * 34 * -dir, y: CHAO });
      return f;
    });
    if (a.nome) {
      const r = texto(el("div", "a-rot", a.nome));
      r.style.left = `${(x / VW) * 100}%`;
      r.style.top = `${((CHAO + 16) / VH) * 100}%`;
      S.box.appendChild(r);
      S.tl.fromTo(r, { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, S.at + 0.5);
    }
    respira(S.tl, figs, S.at, S.dur);
    return figs;
  }

  // traço que se desenha entre dois pontos (curva leve)
  function traco(S, x1, y1, x2, y2, t, dur) {
    const p = P(S.g, `M${x1} ${y1}Q${(x1 + x2) / 2} ${Math.min(y1, y2) - 18} ${x2} ${y2}`, { stroke: ACENTO, w: 1.8 });
    const L = p.getTotalLength();
    p.setAttribute("stroke-dasharray", L);
    p.setAttribute("stroke-dashoffset", L);
    S.tl.fromTo(p, { attr: { "stroke-dashoffset": L } }, { attr: { "stroke-dashoffset": 0 }, duration: dur, ease: "power2.inOut", immediateRender: false }, t);
    return p;
  }

  function balao(S, x, txt, t) {
    const b = texto(el("div", "a-balao", txt || "…"));
    b.style.left = `${Math.max(2, (x / VW) * 100 - 8)}%`;
    b.style.top = "4%";
    S.box.appendChild(b);
    S.tl.fromTo(b, { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)", immediateRender: false }, t);
    S.tl.to(b, { opacity: 0, duration: 0.3 }, S.at + S.dur - 0.7);
    return b;
  }

  const MODELOS = {
    olha(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at;
      pose(S.tl, A, { ca: 14 }, t, 0.01);
      pose(S.tl, A, { ca: -8 }, t + 0.7, 0.25, "power3.out");
      pose(S.tl, B[0], { ca: 5 }, t + 0.9, 0.5);
      const y = CHAO - 168;
      traco(S, POS.esq + 14, y, POS.dir - 14, y, t + 0.9, 0.7);
      const ex = svg("text", { x: POS.esq, y: y - 34, "text-anchor": "middle", fill: ACENTO, "font-size": 40, "font-weight": 700,
        "font-family": "var(--k-display-familia)" });
      ex.textContent = "!";
      ex.style.transformBox = "fill-box";
      ex.style.transformOrigin = "50% 100%";
      S.g.appendChild(ex);
      S.tl.fromTo(ex, { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(3)", immediateRender: false }, t + 1.3);
      KIT.cue(t + 1.3, "ping", -10);
    },
    fala(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at;
      const gesto = (t0) => {
        pose(S.tl, A, { bd: [-55, -35], tr: 3 }, t0, 0.3, "power2.out");
        pose(S.tl, A, { bd: [-18, -10], tr: 0 }, t0 + 0.55, 0.4);
      };
      gesto(t + 0.8); gesto(t + 1.8);
      pose(S.tl, B[0], { ca: 4 }, t + 0.7, 0.5);
      balao(S, POS.esq, b.texto, t + 0.7);
      KIT.cue(t + 0.7, "tique", -10);
    },
  };

  BEATS.acao = (ctx, b) => {
    const f = MODELOS[b.modelo];
    if (!f) throw new Error(`acao: modelo sem implementação: ${b.modelo}`);
    const dur = b.dur || DUR[b.modelo];
    const S = palco(ctx, b, dur);
    f(S, b);
    (window.__marcas = window.__marcas || []).push({ id: ctx.cena.id, rotulo: `acao ${b.modelo}`, t: b.at + 1.4 });
    return b.at + dur;
  };
})();
```

- [ ] **Step 4: Ver os quadros**

Run (um por ação, no momento do gesto):
`python ui/kitframe.py motion/amostras/acoes 2.5 C:/Users/alvar/AppData/Local/Temp/olha.png` e `python ui/kitframe.py motion/amostras/acoes 8 C:/Users/alvar/AppData/Local/Temp/fala.png`
Expected: no `olha`, capitão à esquerda olhando o casal à direita, linha de visão em acento e "!" sobre o capitão; no `fala`, inspetor à esquerda com balão "Doutor Crippen?" e o casal à direita. Abrir os PNGs. Ajustar posições/escala se algo estiver cortado ou sobreposto; as coordenadas do rig são o ponto de ajuste (`TRAJES`, `POS`, `CHAO`).

- [ ] **Step 5: Commit**

```bash
git add motion/kit/acoes.js motion/amostras/acoes/cenas.json
git commit -m "feat(motion): rig de atores e ações olha e fala"
```

---

### Task 6: Modelo `telegrama` + SFX `morse`

**Files:**
- Modify: `motion/kit/acoes.js` (acrescentar em `MODELOS`)
- Modify: `ui/audio.py` (dict `SONS`)
- Create (gerado): `motion/sfx/morse.wav`
- Modify: `motion/amostras/acoes/cenas.json`
- Test: `ui/test_audio.py` (se existir; senão em `ui/test_motion.py`)

**Interfaces:**
- Produces: `MODELOS.telegrama(S, b)` (campo opcional `texto`), SFX `morse` (cue).

- [ ] **Step 1: Teste do SFX que falha**

```python
def test_sfx_kit_tem_morse(tmp_path):
    import audio
    audio.sfx_kit(tmp_path)
    assert (tmp_path / "morse.wav").stat().st_size > 1000
```

Run: `python -m pytest ui/test_audio.py -q -k morse` (criar o arquivo com `import pytest` se não existir) → FAIL (arquivo ausente).

- [ ] **Step 2: Implementar o SFX**

Em `SONS` de `ui/audio.py`:

```python
    "morse": "sine=f=820:d=1.2,volume=0.35,apulsator=mode=square:hz=6:amount=1,afade=t=out:st=1.0:d=0.2",
```

Rodar `python ui/audio.py sfx-kit` (gera/atualiza `motion/sfx/*.wav`, inclusive `morse.wav`) e o teste → PASS. Conferir com `ffprobe motion/sfx/morse.wav` que dura ~1,2 s.

- [ ] **Step 3: Beat na amostra e ver falhar**

Acrescentar em `beats` de `motion/amostras/acoes/cenas.json`:
`{"faz": "acao", "modelo": "telegrama", "texto": "Suspeitos a bordo", "lado": "centro", "s": 9.5}`
Run: `python ui/kitframe.py motion/amostras/acoes 11 C:/Users/alvar/AppData/Local/Temp/tele.png`
Expected: erro "modelo sem implementação: telegrama".

- [ ] **Step 4: Implementar `telegrama`**

Dentro de `MODELOS`, depois de `fala`:

```js
    telegrama(S, b) {
      const t = S.at, g = S.g, tl = S.tl;
      P(g, `M120 ${CHAO}V120M105 150H135M110 182H130`, { w: 1.8 });
      g.appendChild(svg("circle", { cx: 120, cy: 117, r: 3.5, fill: PRETO, stroke: TINTA, "stroke-width": 1.4 }));
      [18, 32, 46].forEach((r, i) => {
        const a = P(g, `M${120 + r * 0.7} ${117 - r * 0.7}A${r} ${r} 0 0 1 ${120 + r * 0.7} ${117 + r * 0.7}`, { stroke: ACENTO, w: 1.8 });
        tl.fromTo(a, { opacity: 0 }, { opacity: 1, duration: 0.2, yoyo: true, repeat: 5, immediateRender: false }, t + 0.3 + i * 0.18);
        tl.set(a, { opacity: 0 }, t + 2.0);
      });
      // destino: prédio simples com janelas que acendem quando o telegrama chega
      P(g, `M440 ${CHAO}V190H520V${CHAO}M432 190L480 160L528 190`, { fill: PRETO, w: 1.6 });
      const jan = [0, 1, 2].map((i) => {
        const r = svg("rect", { x: 452 + i * 22, y: 214, width: 12, height: 18, fill: PRETO, stroke: TINTA, "stroke-width": 1.2 });
        g.appendChild(r);
        return r;
      });
      const env = G(g);
      env.appendChild(svg("rect", { x: -11, y: -8, width: 22, height: 16, fill: TINTA, stroke: PRETO, "stroke-width": 1.2 }));
      P(env, "M-11 -8L0 2L11 -8", { stroke: PRETO, w: 1.4 });
      gsap.set(env, { x: 140, y: 205, opacity: 0 });
      tl.set(env, { opacity: 1 }, t + 1.0);
      tl.to(env, { x: 470, duration: 1.4, ease: "power1.inOut" }, t + 1.0);
      tl.to(env, { y: 160, duration: 0.7, ease: "sine.out" }, t + 1.0);
      tl.to(env, { y: 205, duration: 0.7, ease: "sine.in" }, t + 1.7);
      tl.to(env, { opacity: 0, scale: 0.6, duration: 0.2 }, t + 2.4);
      jan.forEach((j, i) => tl.to(j, { fill: "#efe6cf", duration: 0.15 }, t + 2.5 + i * 0.12));
      if (b.texto) {
        const tira = texto(el("div", "a-tira", b.texto));
        tira.style.top = "84%";
        S.box.appendChild(tira);
        tl.fromTo(tira, { opacity: 0, clipPath: "inset(0 100% 0 0)" },
          { opacity: 1, clipPath: "inset(0 0% 0 0)", duration: 0.8, ease: "steps(14)", immediateRender: false }, t + 2.5);
        tl.to(tira, { opacity: 0, duration: 0.3 }, S.at + S.dur - 0.7);
      }
      KIT.cue(t + 0.2, "morse", -10);
      KIT.cue(t + 2.5, "ping", -8);
    },
```

- [ ] **Step 5: Ver os quadros**

Run: `python ui/kitframe.py motion/amostras/acoes 10.6 C:/Users/alvar/AppData/Local/Temp/tele1.png` e `... 12.2 ...tele2.png`
Expected: antena com arcos de sinal e envelope no meio do voo (10.6 s); janelas acesas e tira "SUSPEITOS A BORDO" (12.2 s). Abrir os PNGs e corrigir sobreposições (a tira usa `left:50%`).

- [ ] **Step 6: Commit**

```bash
git add ui/audio.py ui/test_audio.py motion/sfx/morse.wav motion/kit/acoes.js motion/amostras/acoes/cenas.json
git commit -m "feat(motion): ação telegrama e sfx morse"
```

---

### Task 7: Modelos `le`, `aponta`, `anda` e `sobe_a_bordo`

**Files:**
- Modify: `motion/kit/acoes.js` (acrescentar em `MODELOS`)
- Modify: `motion/amostras/acoes/cenas.json`

**Interfaces:**
- Consumes: `elenco`, `pose`, `passos`, `traco`, `balao`, `POS`, `CHAO`, `P`, `G` da Task 5.
- Produces: `MODELOS.le` (`ator`, `texto` opcional), `MODELOS.aponta` (`ator`, `alvo`), `MODELOS.anda` (`ator`, `de` padrão `esq`, `para`), `MODELOS.sobe_a_bordo` (`ator`).

- [ ] **Step 1: Beats de amostra**

Acrescentar em `beats` da amostra (e subir `dur` da cena para 40):

```json
   {"faz": "acao", "modelo": "le", "ator": "dew", "texto": "Procurado: Crippen", "lado": "esq", "s": 14},
   {"faz": "acao", "modelo": "aponta", "ator": "kendall", "alvo": "casal", "lado": "dir", "s": 18.5},
   {"faz": "acao", "modelo": "anda", "ator": "dew", "de": "esq", "para": "dir", "lado": "centro", "s": 22},
   {"faz": "acao", "modelo": "sobe_a_bordo", "ator": "dew", "lado": "esq", "s": 26.5}
```

Run: `python ui/kitframe.py motion/amostras/acoes 15.5 C:/Users/alvar/AppData/Local/Temp/le.png`
Expected: erro "modelo sem implementação: le".

- [ ] **Step 2: Implementar os quatro modelos** (dentro de `MODELOS`, depois de `telegrama`)

```js
    le(S, b) {
      const [A] = elenco(S, b.ator, POS.centro, 1), t = S.at, tl = S.tl, x = POS.centro;
      pose(tl, A, { bd: [-72, -85], be: [-58, -95], ca: 14 }, t + 0.4, 0.6);
      const folha = G(S.g, `translate(${x + 30} ${CHAO - 178}) rotate(-8)`);
      P(folha, "M0 0H46V58H0Z", { fill: TINTA, stroke: PRETO, w: 1 });
      const linhas = [10, 22, 34, 46].map((y) => P(folha, `M6 ${y}H${y === 46 ? 28 : 40}`, { stroke: PRETO, w: 1.4 }));
      tl.fromTo(folha, { opacity: 0 }, { opacity: 1, duration: 0.3, immediateRender: false }, t + 0.7);
      linhas.forEach((l, i) => tl.fromTo(l, { opacity: 0 }, { opacity: 1, duration: 0.2, immediateRender: false }, t + 1.2 + i * 0.35));
      if (b.texto) balao(S, x - 40, b.texto, t + 1.6);
      KIT.cue(t + 0.7, "tique", -10);
    },
    aponta(S, b) {
      const [A] = elenco(S, b.ator, POS.esq, 1), B = elenco(S, b.alvo, POS.dir, -1), t = S.at, tl = S.tl;
      pose(tl, A, { bd: [-84, -4], tr: 4, ca: -4 }, t + 0.5, 0.4, "power2.out");
      pose(tl, B[0], { ca: 6 }, t + 0.9, 0.5);
      const anel = svg("ellipse", { cx: POS.dir, cy: CHAO + 2, rx: 30, ry: 6, fill: "none", stroke: ACENTO, "stroke-width": 1.8 });
      anel.style.transformBox = "fill-box";
      anel.style.transformOrigin = "50% 50%";
      S.g.appendChild(anel);
      tl.fromTo(anel, { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1.4, duration: 0.7, repeat: 2, ease: "power2.out", immediateRender: false }, t + 0.9);
      tl.set(anel, { opacity: 0 }, t + 3.0);
      const seta = P(S.g, `M${POS.dir} ${CHAO - 205}V${CHAO - 186}M${POS.dir - 7} ${CHAO - 194}L${POS.dir} ${CHAO - 186}L${POS.dir + 7} ${CHAO - 194}`,
        { stroke: ACENTO, w: 2.2 });
      tl.fromTo(seta, { opacity: 0, y: -8 }, { opacity: 1, y: 0, duration: 0.35, ease: "bounce.out", immediateRender: false }, t + 1.0);
      KIT.cue(t + 0.9, "tique", -10);
    },
    anda(S, b) {
      const de = POS[b.de || "esq"], para = POS[b.para], dir = para >= de ? 1 : -1, t = S.at, tl = S.tl;
      const [A] = elenco(S, b.ator, de, dir);
      const dist = Math.abs(para - de), dur = Math.min(S.dur - 1, Math.max(1.6, dist / 70));
      tl.to(A.mov, { x: para, duration: dur, ease: "none" }, t + 0.5);
      passos(tl, A, t + 0.5, dur, Math.max(2, Math.round(dist / 44)));
    },
    sobe_a_bordo(S, b) {
      const [A] = elenco(S, b.ator, 90, 1), t = S.at, tl = S.tl, g = S.g, topo = CHAO - 70;
      P(g, `M360 ${topo}H545L525 ${CHAO}H378Z`, { fill: PRETO, w: 1.6 });
      P(g, `M385 ${topo}V${topo - 26}M440 ${topo}V${topo - 26}M495 ${topo}V${topo - 26}M385 ${topo - 26}H525`, { w: 1.2 });
      P(g, `M120 ${CHAO}L360 ${topo}`, { w: 2.4 });
      for (let i = 1; i < 7; i++) P(g, `M${120 + i * 34} ${CHAO - i * 10 - 4}V${CHAO - i * 10 + 4}`, { w: 1.2, op: 0.7 });
      const dur = Math.min(S.dur - 1.6, 2.4);
      tl.to(A.mov, { x: 345, y: topo, duration: dur, ease: "none" }, t + 0.5);
      tl.to(A.flip, { rotation: -6, duration: 0.01 }, t + 0.5);
      passos(tl, A, t + 0.5, dur, 5);
      pose(tl, A, { bd: [-150, -120] }, t + 0.5 + dur + 0.1, 0.35, "power2.out");
      pose(tl, A, { bd: [0, 0] }, t + 0.5 + dur + 0.8, 0.35);
      KIT.cue(t + 0.5 + dur, "tique", -10);
    },
```

Nota: `A.flip` já tem o atributo `transform="scale(1 1)"`; GSAP `rotation` sobrescreve o transform do elemento. Se a inclinação distorcer o flip, trocar por rotação do `A.tronco` (`pose(tl, A, { tr: 6 }, ...)`) e remover a linha do `A.flip`.

- [ ] **Step 3: Ver os quadros**

Run, um por modelo: `python ui/kitframe.py motion/amostras/acoes <t> C:/Users/alvar/AppData/Local/Temp/<m>.png` com t = 16 (le), 20 (aponta), 23.5 (anda, meio da caminhada), 29 (sobe_a_bordo).
Expected: `le` com folha entre as mãos e linhas de texto; `aponta` com braço estendido, anel e seta no alvo; `anda` com o inspetor deslocado do lado esquerdo e pernas alternadas; `sobe_a_bordo` com figura na prancha, casco à direita. Abrir os PNGs; ajustar ângulos/posições (principalmente a posição da folha em `le` e a inclinação em `sobe_a_bordo`).

- [ ] **Step 4: Rodar a suíte**

Run: `python -m pytest ui -q -x`
Expected: tudo passa (testes com playwright/ffmpeg incluídos quando o ambiente tem).

- [ ] **Step 5: Commit**

```bash
git add motion/kit/acoes.js motion/amostras/acoes/cenas.json
git commit -m "feat(motion): ações le, aponta, anda e sobe_a_bordo"
```

---

### Task 8: Render real da amostra, golden e documentação

**Files:**
- Modify: `ui/test_motion.py` (teste de montagem da amostra com ações)
- Modify: `motion/amostras/` referências golden (se `MOTION_GOLDEN` rodar no ambiente)
- Modify (repo `dark_videos`): `Formatos/dark-historia.md`

- [ ] **Step 1: Teste de montagem da amostra**

Em `ui/test_motion.py`, no padrão dos outros `test_montar_*` (usar o mesmo marcador `pw` e copiar a amostra para `tmp_path`):

```python
@pw
def test_montar_amostra_acoes_gera_marcas_e_sem_erro_de_js(tmp_path):
    proj = tmp_path / "acoes"
    shutil.copytree(motion.MOTION / "amostras" / "acoes", proj)
    r = motion.montar(proj)
    assert r["ok"], r["erros"]
    tempos = json.loads((proj / "motion" / "tempos.json").read_text(encoding="utf-8"))
    assert {m["rotulo"] for m in tempos["marcas"]} == {"acao olha", "acao fala", "acao telegrama", "acao le",
                                                       "acao aponta", "acao anda", "acao sobe_a_bordo"}
```

Run: `python -m pytest ui/test_motion.py -q -k amostra_acoes` → PASS.

- [ ] **Step 2: Render de verdade pelo HyperFrames**

Run: `python ui/motion.py render motion/amostras/acoes --rascunho` e, com o `video_rascunho.mp4` gerado, `python ui/motion.py folha motion/amostras/acoes`.
Expected: `video` gerado sem erro e `qc/folha.png` com um quadro por ação. Abrir a folha e confirmar que o estilo de gravura (hachura, tremor) aparece no vídeo e não só no screenshot. Não commitar o vídeo (regra: nunca commitar mídia): adicionar ao `.gitignore` se necessário e conferir com `git status`.

- [ ] **Step 3: Golden (opt-in)**

Se `MOTION_GOLDEN=1 python -m pytest ui/test_motion_golden.py -q` roda no ambiente e continua verde, seguir; se o golden das amostras existentes mudou por causa de `limpa` em `palavras` (Task 4), investigar antes de regravar.

- [ ] **Step 4: Documentar a regra no repo do canal**

No `D:\Projetos\dark_videos\Formatos\dark-historia.md`, na seção "5c. Direção (beats)", acrescentar:

```markdown
- Texto na tela é **frase da fala**: use `{"faz": "palavras", "frase": "trecho literal da narração"}` (até 10 palavras, contíguo, `risco`/`destaque` só nas palavras-chave). Lista de palavras soltas gera aviso.
- Ações e diálogos viram `{"em": "<palavra>", "faz": "acao", "modelo": "olha|fala|telegrama|le|aponta|sobe_a_bordo|anda", ...}`; atores em `episodio.json` → `atores`. Vinhetas curtas sobre o fundo da cena; sem violência (vocabulário fechado). Spec: `D:/Projetos/video_editor/docs/superpowers/specs/2026-10-09-acoes-ilustradas-design.md`.
```

Commit nesse repo: `git add Formatos/dark-historia.md && git commit -m "docs(formato): frase conectada e acoes ilustradas"`.

- [ ] **Step 5: Commit no video_editor**

```bash
git add ui/test_motion.py
git commit -m "test(motion): montagem da amostra com todas as ações"
```

---

## Self-Review

**Spec coverage:** frase (A) → Tasks 2 e 4; beat `acao` + vocabulário de 7 modelos → Tasks 1, 5, 6, 7; atores/trajes → Tasks 1 e 5; estilo (hachura, tremor 12 fps, respiração, sem bounce) → Task 5 (`figura`, `palco`, `respira`); `RITMO_MAX` conta `acao` (ela tem `s`, entra no `ts` de `ritmo` sem mudança) → coberto pelos testes existentes de ritmo; folha de QC → Task 3; SFX `morse` → Task 6; sem violência por vocabulário fechado → Task 1; regra de direção → Task 8; 001 intocado → Global Constraints + golden na Task 8. Lacuna deliberada: golden de cada modelo (spec) vira a amostra montada + quadros inspecionados, porque o golden é opt-in e visual.

**Placeholders:** nenhum "TBD"; ajustes visuais (posição da folha, inclinação) estão nomeados com o ponto exato de ajuste.

**Consistência de tipos:** `MODELOS_ACAO` (Python) e `MODELOS` (JS) têm os mesmos 7 nomes; `DUR` cobre os 7; campos `ator`/`alvo`/`de`/`para`/`texto`/`lado`/`escala`/`dur` iguais no validador, na amostra e no JS; `window.__marcas` ↔ `_medir` ↔ `tempos.json["marcas"]` ↔ `folha`.
