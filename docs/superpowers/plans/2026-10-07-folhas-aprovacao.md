# Folhas de aprovação (6b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aba "Aprovação" que mostra b-roll, clipes, conceitos e overlays como folhas clicáveis e envia a resposta textual (`ok` + exceções) no `waiting_reply` aberto.

**Architecture:** `ui/folha.py` (stdlib) normaliza os artefatos (`broll.json`, `clips/clips.json`, `conceitos.json`, `overlays/folha.json`) e gera os frames dos overlays com ffmpeg. `ui/server.py` expõe `/api/folha` e libera mídias de candidatos/overlays em `/api/file`. `ui/static/folha.js` desenha a folha do pedido mais antigo com campo `folha`, guarda a seleção por `pid:qid` e monta a resposta com funções puras por tipo; envio via `sendReply` existente.

**Tech Stack:** Python 3 stdlib, FastAPI, ffmpeg, JS vanilla (scripts clássicos com globais), pytest, Python Playwright.

**Spec:** `docs/superpowers/specs/2026-10-07-folhas-aprovacao-design.md`

## Global Constraints

- Nada copiado do OpenMontage (AGPL) — reescrita própria.
- Módulos `ui/*.py`: stdlib apenas; `sys.path.insert(0, str(Path(__file__).parent))` antes de `import pipeline`; CLI com JSON UTF-8 no stdout; exit 0 ok / 1 validação (`ValueError`) / 2 execução.
- Subprocess sempre com lista de args, `timeout`, `_run` injetável.
- A UI nunca escreve artefato do pipeline: a folha só envia texto via `/api/reply` (`sendReply(qid, texto, 'proj')`).
- Tipos de folha: `broll | clips | conceitos | overlays` (campo `folha` do pedido da fila).
- Sintaxe de resposta: `ok` sozinho = tudo como proposto; `ok ` + tokens = exceções valem, resto aprovado. Tokens: `bNN:k`, `bNN:não`; `cNN:não`, `cNN:nota N`, `cNN:x=N`, `cNN:legenda`, `cNN:sem-legenda`; `oNN:não`, `oNN: <texto>`; conceitos: `X` | `produzir: A B` | `ajuste: <texto>`.
- Crop real dos clipes: `crop=608:1080:{x}:0` sobre quadro 1920x1080; `x` 0–1312, passo 2; `x_padrao` 636.
- Todo texto vindo de artefato/pedido renderizado em HTML passa por `escapeHtml`.
- Testes: `cd ui && python -m pytest -q` (fixtures `fake_root` de `ui/test_pipeline.py`; smoke `ui_url`/`page` de `ui/test_ui_smoke.py`).
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nunca matar processos que não sejam seus; nunca escrever em projetos reais sob `edit/`.

## Review Focus

1. Pedido respondido pela fila (não pela folha) enquanto a aba Aprovação está aberta → aba some e volta ao Board, sem erro. Teste em Task 3 (`test_folha_some_quando_respondida_pela_fila`).
2. Usuário troca de aba (ou projeto) e volta → seleção e comentário continuam. Teste em Task 3 (`test_folha_selecao_sobrevive_troca_de_aba`).
3. Artefato ausente para a folha pedida → aba mostra "folha indisponível — responda pela fila" com o motivo, sem quebrar. Teste em Task 3 (`test_folha_indisponivel`).
4. Mídia de candidato com nome hostil (`../`) → 400, nunca serve arquivo fora do projeto. Teste em Task 2 (`test_file_midia_traversal`).
5. Overlay cujo `.mov` não existe ou ffmpeg falha → item com `png: null` + `erro`, demais overlays seguem. Teste em Task 1 (`test_overlays_arquivo_ausente_e_ffmpeg_falha`).

---

### Task 1: `ui/folha.py` — normalização dos artefatos + frames de overlays

**Files:**
- Create: `ui/folha.py`
- Test: `ui/test_folha.py`

**Interfaces:**
- Consumes: `pipeline.atomic_write_json(path, obj)`.
- Produces:
  - `TIPOS: tuple` = `("broll", "clips", "conceitos", "overlays")`
  - `ler(proj: Path, tipo: str) -> dict` (shapes abaixo; `ValueError` com motivo curto)
    - broll → `{"momentos": [{"id","t_in","t_out","termo","modo","status","escolhido","candidatos":[{"rotulo","fonte","tipo","arq","dur","licenca","autor"}]}]}`
    - clips → `{"x_padrao": int, "clipes": [{"id","slug","nota","gancho","ranges":[{"t_in","t_out"}],"x","legenda","plataformas","dur"}]}`
    - conceitos → `{"conceitos": [{"id","ideia","mantem","muda","custo","horas","exige_ia","animatic"}]}`
    - overlays → `{"overlays": [{"id","arquivo","t","dur","png","erro"}]}`
  - `overlays(proj: Path, _run=None) -> dict` (mesmo shape de overlays; grava `overlays/oNN.png` e `overlays/folha.json`)
  - CLI: `python ui/folha.py ler <proj> <tipo>` | `python ui/folha.py overlays <proj>`

- [ ] **Step 1: Write the failing tests** — `ui/test_folha.py`

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

import folha
from test_pipeline import fake_root  # noqa: F401 — fixture reexport


@pytest.fixture
def proj(fake_root):
    return fake_root / "edit-fake"


def _w(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


BROLL = {"momentos": [
    {"id": "b01", "t_in": 42, "t_out": 45, "termo": "gavel", "modo": "cut-in", "status": "proposto",
     "escolhido": "b01-2",
     "candidatos": [{"fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4", "dur": 6, "licenca": "Pexels License", "autor": "Ana"},
                    {"fonte": "pixabay", "tipo": "video", "arq": "broll/cand/b.mp4", "dur": 8}]},
    {"id": "b02", "t_in": 75, "t_out": 78, "termo": "court", "modo": "janela", "status": "proposto",
     "candidatos": [{"fonte": "pexels", "tipo": "foto", "arq": "broll/cand/c.jpg"}]},
    {"id": "b03", "status": "aprovado", "candidatos": []},
]}


def test_ler_broll(proj):
    _w(proj / "broll.json", BROLL)
    d = folha.ler(proj, "broll")
    assert [m["id"] for m in d["momentos"]] == ["b01", "b02"]          # só propostos
    m1, m2 = d["momentos"]
    assert m1["escolhido"] == "b01-2" and m2["escolhido"] == "b02-1"    # default = 1º rótulo
    assert m1["candidatos"][0] == {"rotulo": "b01-1", "fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4",
                                   "dur": 6.0, "licenca": "Pexels License", "autor": "Ana"}
    assert m2["candidatos"][0]["tipo"] == "foto" and m2["candidatos"][0]["dur"] == 0.0


def test_ler_broll_escolhido_invalido_vira_primeiro(proj):
    b = json.loads(json.dumps(BROLL))
    b["momentos"][0]["escolhido"] = "b01-9"
    _w(proj / "broll.json", b)
    assert folha.ler(proj, "broll")["momentos"][0]["escolhido"] == "b01-1"


CLIPS = {"x_padrao": 640, "clipes": [
    {"id": "c01", "slug": "zero", "status": "proposto", "nota": 4, "gancho": "Zero inscritos",
     "ranges": [{"t_in": 10.0, "t_out": 20.0, "beat": "hook"}, {"t_in": 30.0, "t_out": 35.5}], "x": 700,
     "legenda": True, "plataformas": ["shorts", "reels"]},
    {"id": "c02", "slug": "dois", "status": "proposto", "gancho": "g", "ranges": [{"t_in": 1, "t_out": 2}]},
    {"id": "c03", "slug": "tres", "status": "vetado", "ranges": [{"t_in": 1, "t_out": 2}]},
]}


def test_ler_clips(proj):
    _w(proj / "clips" / "clips.json", CLIPS)
    d = folha.ler(proj, "clips")
    assert d["x_padrao"] == 640 and [c["id"] for c in d["clipes"]] == ["c01", "c02"]
    c1, c2 = d["clipes"]
    assert c1["ranges"] == [{"t_in": 10.0, "t_out": 20.0}, {"t_in": 30.0, "t_out": 35.5}]
    assert c1["dur"] == 15.5 and c1["x"] == 700 and c1["legenda"] is True
    assert c1["plataformas"] == ["shorts", "reels"] and c1["nota"] == 4
    assert c2["x"] == 640 and c2["legenda"] is False and c2["nota"] is None and c2["plataformas"] == []


def test_ler_clips_x_padrao_default(proj):
    _w(proj / "clips" / "clips.json", {"clipes": [{"id": "c01", "status": "proposto", "ranges": [{"t_in": 0, "t_out": 1}]}]})
    d = folha.ler(proj, "clips")
    assert d["x_padrao"] == 636 and d["clipes"][0]["x"] == 636


@pytest.mark.parametrize("clipe,motivo", [
    ({"id": "c01", "status": "proposto"}, "sem ranges"),
    ({"id": "c01", "status": "proposto", "ranges": [{"t_in": 1}]}, "range"),
    ({"status": "proposto", "ranges": []}, "sem id"),
])
def test_ler_clips_invalido(proj, clipe, motivo):
    _w(proj / "clips" / "clips.json", {"clipes": [clipe]})
    with pytest.raises(ValueError, match=motivo):
        folha.ler(proj, "clips")


def test_ler_conceitos(proj):
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    _w(proj / "conceitos.json", {"conceitos": [
        {"id": "A", "ideia": "mesmo mecanismo", "mantem": "ritmo", "muda": "tema", "custo": "US$ 0,40",
         "horas": 2, "exige_ia": False, "animatic": "animatic-A.png"},
        {"id": "B", "ideia": "outro", "exige_ia": True, "animatic": "animatic-B.png"},   # png não existe
        {"id": "C", "animatic": "../fora.png"}]})
    d = folha.ler(proj, "conceitos")
    a, b, c = d["conceitos"]
    assert a == {"id": "A", "ideia": "mesmo mecanismo", "mantem": "ritmo", "muda": "tema", "custo": "US$ 0,40",
                 "horas": 2, "exige_ia": False, "animatic": "animatic-A.png"}
    assert b["animatic"] is None and b["exige_ia"] is True and b["mantem"] == ""
    assert c["animatic"] is None


def test_ler_overlays(proj):
    (proj / "overlays").mkdir()
    (proj / "overlays" / "o01.png").write_bytes(b"\x89PNG")
    _w(proj / "overlays" / "folha.json", {"overlays": [
        {"id": "o01", "arquivo": "a.mov", "t": 1.5, "dur": 3, "png": "overlays/o01.png"},
        {"id": "o02", "arquivo": "b.mov", "t": 9, "dur": 2, "png": "overlays/o02.png", "erro": None},
        {"id": "o03", "arquivo": "c.mov", "t": 12, "dur": 2, "png": "../x.png"}]})
    d = folha.ler(proj, "overlays")
    assert d["overlays"][0] == {"id": "o01", "arquivo": "a.mov", "t": 1.5, "dur": 3.0, "png": "overlays/o01.png", "erro": None}
    assert d["overlays"][1]["png"] is None and d["overlays"][2]["png"] is None


@pytest.mark.parametrize("tipo,arq", [("broll", "broll.json"), ("clips", "clips/clips.json"),
                                      ("conceitos", "conceitos.json"), ("overlays", "overlays/folha.json")])
def test_ler_ausente_e_invalido(proj, tipo, arq):
    with pytest.raises(ValueError, match="não encontrado"):
        folha.ler(proj, tipo)
    (proj / arq).parent.mkdir(parents=True, exist_ok=True)
    (proj / arq).write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="inválido"):
        folha.ler(proj, tipo)
    (proj / arq).write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="inválido"):
        folha.ler(proj, tipo)


def test_ler_broll_sem_candidatos(proj):
    _w(proj / "broll.json", {"momentos": [{"id": "b01", "status": "proposto"}]})
    with pytest.raises(ValueError, match="sem candidatos"):
        folha.ler(proj, "broll")


def test_ler_tipo_invalido(proj):
    with pytest.raises(ValueError, match="tipo"):
        folha.ler(proj, "nada")


def _fake_run(calls, falha_em=None):
    def run(args, **kw):
        calls.append(args)
        if falha_em is not None and len(calls) == falha_em:
            raise subprocess.CalledProcessError(1, args)
        Path(args[-1]).write_bytes(b"\x89PNGfake")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
    return run


def _edl_com_overlays(proj, overlays):
    edl = json.loads((proj / "edl.json").read_text(encoding="utf-8"))
    edl["overlays"] = overlays
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")


def test_overlays_sobre_preview(proj):
    (proj / "anim").mkdir()
    (proj / "anim" / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "anim/A.mov", "start_in_output": 4.0, "duration": 2.0}])
    calls = []
    d = folha.overlays(proj, _run=_fake_run(calls))
    assert d["overlays"] == [{"id": "o01", "arquivo": "anim/A.mov", "t": 4.0, "dur": 2.0, "png": "overlays/o01.png", "erro": None}]
    args = calls[0]
    assert args[0] == "ffmpeg" and str(proj / "preview.mp4") in args     # fixture tem preview.mp4
    assert args[args.index(str(proj / "preview.mp4")) - 1] == "-i"
    assert "5.000" in args                                                # base em t + dur/2
    assert json.loads((proj / "overlays" / "folha.json").read_text(encoding="utf-8")) == d


def test_overlays_sem_video_base_usa_preto(proj):
    (proj / "preview.mp4").unlink()
    (proj / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 0, "duration": 1}])
    calls = []
    folha.overlays(proj, _run=_fake_run(calls))
    assert "lavfi" in calls[0] and any("color=c=black" in a for a in calls[0])


def test_overlays_arquivo_ausente_e_ffmpeg_falha(proj):
    for n in ("A.mov", "C.mov"):
        (proj / n).write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 0, "duration": 1},
                             {"file": "B.mov", "start_in_output": 5, "duration": 1},
                             {"file": "C.mov", "start_in_output": 9, "duration": 1}])
    calls = []
    d = folha.overlays(proj, _run=_fake_run(calls, falha_em=2))     # 2ª chamada (C.mov) falha
    o1, o2, o3 = d["overlays"]
    assert o1["png"] == "overlays/o01.png" and o1["erro"] is None
    assert o2["png"] is None and "não encontrado" in o2["erro"]
    assert o3["png"] is None and o3["erro"].startswith("ffmpeg")
    assert len(calls) == 2


def test_overlays_edl_sem_overlays(proj):
    d = folha.overlays(proj, _run=_fake_run([]))
    assert d == {"overlays": []}
    assert (proj / "overlays" / "folha.json").exists()


def _cli(*a):
    return subprocess.run([sys.executable, str(Path(folha.__file__)), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli(proj):
    _w(proj / "broll.json", BROLL)
    r = _cli("ler", str(proj), "broll")
    assert r.returncode == 0 and json.loads(r.stdout)["momentos"][0]["id"] == "b01"
    r = _cli("ler", str(proj), "clips")
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_folha.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'folha'`.

- [ ] **Step 3: Implement** — `ui/folha.py`

```python
"""Folhas de aprovação: normaliza artefatos do pipeline para a UI e gera os
frames dos overlays (overlays/oNN.png + overlays/folha.json). Só leitura nos
artefatos; a decisão volta ao Claude como texto pela fila."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

TIPOS = ("broll", "clips", "conceitos", "overlays")
X_PADRAO = 636
ANIMATIC_RE = re.compile(r"animatic-[A-Z]\.png")
OVERLAY_PNG_RE = re.compile(r"overlays/o\d{2,3}\.png")


def _json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"{path.name} não encontrado")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} inválido: {e.msg}")
    if not isinstance(d, dict):
        raise ValueError(f"{path.name} inválido: esperado objeto")
    return d


def _itens(d: dict, chave: str, nome: str) -> list:
    v = d.get(chave)
    if not isinstance(v, list):
        raise ValueError(f"{nome} inválido: '{chave}' ausente")
    for i, it in enumerate(v):
        if not isinstance(it, dict) or not it.get("id"):
            raise ValueError(f"{nome}: item {i} sem id")
    return v


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"número inválido: {v!r}")


def _broll(proj: Path) -> dict:
    d = _json(proj / "broll.json")
    out = []
    for m in _itens(d, "momentos", "broll.json"):
        if m.get("status") != "proposto":
            continue
        cands = m.get("candidatos")
        if not isinstance(cands, list):
            raise ValueError(f"broll.json: {m['id']} sem candidatos")
        cs = [{"rotulo": f"{m['id']}-{k + 1}", "fonte": c.get("fonte", ""), "tipo": c.get("tipo", "video"),
               "arq": c.get("arq", ""), "dur": _f(c.get("dur")), "licenca": c.get("licenca", ""),
               "autor": c.get("autor", "")}
              for k, c in enumerate(cands) if isinstance(c, dict)]
        rotulos = [c["rotulo"] for c in cs]
        esc = m.get("escolhido") if m.get("escolhido") in rotulos else (rotulos[0] if rotulos else None)
        out.append({"id": m["id"], "t_in": _f(m.get("t_in")), "t_out": _f(m.get("t_out")),
                    "termo": m.get("termo", ""), "modo": m.get("modo", ""), "status": "proposto",
                    "escolhido": esc, "candidatos": cs})
    return {"momentos": out}


def _ranges(c: dict) -> list:
    rs = c.get("ranges")
    if not isinstance(rs, list) or not rs:
        raise ValueError(f"clips.json: {c['id']} sem ranges")
    try:
        return [{"t_in": float(r["t_in"]), "t_out": float(r["t_out"])} for r in rs]
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"clips.json: {c['id']} com range malformado")


def _clips(proj: Path) -> dict:
    d = _json(proj / "clips" / "clips.json")
    xp = int(d.get("x_padrao", X_PADRAO))
    out = []
    for c in _itens(d, "clipes", "clips.json"):
        if c.get("status") != "proposto":
            continue
        rs = _ranges(c)
        out.append({"id": c["id"], "slug": c.get("slug", ""), "nota": c.get("nota"), "gancho": c.get("gancho", ""),
                    "ranges": rs, "x": int(c.get("x", xp)), "legenda": bool(c.get("legenda")),
                    "plataformas": list(c.get("plataformas") or []),
                    "dur": round(sum(r["t_out"] - r["t_in"] for r in rs), 3)})
    return {"x_padrao": xp, "clipes": out}


def _conceitos(proj: Path) -> dict:
    d = _json(proj / "conceitos.json")
    out = []
    for c in _itens(d, "conceitos", "conceitos.json"):
        an = c.get("animatic")
        ok = isinstance(an, str) and ANIMATIC_RE.fullmatch(an) and (proj / an).is_file()
        out.append({"id": str(c["id"]), "ideia": c.get("ideia", ""), "mantem": c.get("mantem", ""),
                    "muda": c.get("muda", ""), "custo": str(c.get("custo", "")), "horas": c.get("horas"),
                    "exige_ia": bool(c.get("exige_ia")), "animatic": an if ok else None})
    return {"conceitos": out}


def _overlays_ler(proj: Path) -> dict:
    d = _json(proj / "overlays" / "folha.json")
    out = []
    for o in _itens(d, "overlays", "folha.json"):
        png = o.get("png")
        ok = isinstance(png, str) and OVERLAY_PNG_RE.fullmatch(png) and (proj / png).is_file()
        out.append({"id": o["id"], "arquivo": o.get("arquivo", ""), "t": _f(o.get("t")), "dur": _f(o.get("dur")),
                    "png": png if ok else None, "erro": o.get("erro")})
    return {"overlays": out}


LEITORES = {"broll": _broll, "clips": _clips, "conceitos": _conceitos, "overlays": _overlays_ler}


def ler(proj: Path, tipo: str) -> dict:
    if tipo not in LEITORES:
        raise ValueError(f"tipo inválido: {tipo} (use {', '.join(TIPOS)})")
    return LEITORES[tipo](Path(proj))


def overlays(proj: Path, _run=None) -> dict:
    """Frame no meio de cada overlay do edl.json, composto sobre o vídeo base
    (final.mp4, senão preview.mp4, senão fundo preto) no mesmo tempo de saída."""
    run = _run or subprocess.run
    proj = Path(proj)
    edl = _json(proj / "edl.json")
    base = next((proj / n for n in ("final.mp4", "preview.mp4") if (proj / n).is_file()), None)
    dst = proj / "overlays"
    dst.mkdir(exist_ok=True)
    itens = []
    for i, o in enumerate(edl.get("overlays") or [], 1):
        oid = f"o{i:02d}"
        arq = str(o.get("file", "")) if isinstance(o, dict) else ""
        t0 = _f(o.get("start_in_output")) if isinstance(o, dict) else 0.0
        dur = _f(o.get("duration")) if isinstance(o, dict) else 0.0
        item = {"id": oid, "arquivo": arq, "t": t0, "dur": dur, "png": None, "erro": None}
        src = proj / arq
        if not arq or not src.is_file():
            item["erro"] = "arquivo do overlay não encontrado"
            itens.append(item)
            continue
        meio = dur / 2
        entrada = (["-ss", f"{t0 + meio:.3f}", "-i", str(base)] if base
                   else ["-f", "lavfi", "-i", "color=c=black:s=1920x1080"])
        png = dst / f"{oid}.png"
        args = ["ffmpeg", "-y", "-loglevel", "error", *entrada, "-ss", f"{meio:.3f}", "-i", str(src),
                "-filter_complex", "[0:v]scale=1920:1080[b];[b][1:v]overlay=(W-w)/2:(H-h)/2,scale=640:-2",
                "-frames:v", "1", str(png)]
        try:
            run(args, capture_output=True, check=True, timeout=60)
            item["png"] = f"overlays/{oid}.png"
        except (OSError, subprocess.SubprocessError) as e:
            item["erro"] = f"ffmpeg: {type(e).__name__}"
        itens.append(item)
    out = {"overlays": itens}
    pipeline.atomic_write_json(dst / "folha.json", out)
    return out


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="folhas de aprovação")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ler"); p.add_argument("proj"); p.add_argument("tipo")
    p = sub.add_parser("overlays"); p.add_argument("proj")
    ns = ap.parse_args()
    try:
        out = ler(Path(ns.proj), ns.tipo) if ns.cmd == "ler" else overlays(Path(ns.proj))
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False))
```

- [ ] **Step 4: Run tests**

Run: `cd ui && python -m pytest test_folha.py -q` → all PASS; then `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/folha.py ui/test_folha.py
git commit -m "feat(folha): normalização de b-roll, clipes, conceitos e overlays + frames de overlays"
```

---

### Task 2: Servidor — `/api/folha` e mídias em `/api/file`

**Files:**
- Modify: `ui/server.py` (import `folha`; `MIDIA`/`TIPO_MIDIA` junto de `FILE_NAME`; rota `file_`; rota nova após `/api/quadro`)
- Test: `ui/test_server.py` (append; imports no topo)

**Interfaces:**
- Consumes: `folha.TIPOS`, `folha.ler(proj, tipo)` (Task 1); `_proj`.
- Produces: `GET /api/folha?id=&tipo=` → dict de `folha.ler` | 400 tipo inválido | 422 `{"detail": motivo}`; `GET /api/file?id=&name=broll/cand/<arq>` e `name=overlays/oNN.png` com media type pelo sufixo.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_server.py`; `import folha` no topo)

```python
def test_folha_route(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "conceitos.json").write_text(json.dumps({"conceitos": [{"id": "A", "ideia": "x"}]}), encoding="utf-8")
    r = client.get("/api/folha", params={"id": "edit-fake", "tipo": "conceitos"})
    assert r.status_code == 200 and r.json()["conceitos"][0]["id"] == "A"


def test_folha_route_erros(client):
    assert client.get("/api/folha", params={"id": "edit-fake", "tipo": "nada"}).status_code == 400
    r = client.get("/api/folha", params={"id": "edit-fake", "tipo": "broll"})
    assert r.status_code == 422 and "não encontrado" in r.json()["detail"]
    assert client.get("/api/folha", params={"id": "../x", "tipo": "broll"}).status_code == 400


@pytest.mark.parametrize("nome,tipo", [("broll/cand/pexels-1.mp4", "video/mp4"),
                                       ("broll/cand/unsplash-2.jpg", "image/jpeg"),
                                       ("overlays/o01.png", "image/png")])
def test_file_midia(client, fake_root, nome, tipo):
    p = fake_root / "edit-fake" / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"0123456789")
    r = client.get("/api/file", params={"id": "edit-fake", "name": nome})
    assert r.status_code == 200 and r.headers["content-type"].startswith(tipo) and r.content == b"0123456789"


def test_file_midia_range(client, fake_root):
    p = fake_root / "edit-fake" / "broll" / "cand" / "v.mp4"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"0123456789")
    r = client.get("/api/file", params={"id": "edit-fake", "name": "broll/cand/v.mp4"}, headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.content == b"0123"


@pytest.mark.parametrize("nome", ["broll/cand/../../x.mp4", "broll/cand/a.exe", "overlays/x.png",
                                  "overlays/../broll/sheet.png", "broll/cand/sub/a.mp4"])
def test_file_midia_traversal(client, nome):
    assert client.get("/api/file", params={"id": "edit-fake", "name": nome}).status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_server.py -q -k "folha or midia"`
Expected: FAIL (404 em `/api/folha`; 400 nas mídias).

- [ ] **Step 3: Implement** (`ui/server.py`)

Import: adicionar `import folha` junto de `import eventos`.

Logo abaixo de `FILE_NAME = ...`:

```python
MIDIA = re.compile(r"^broll/cand/[\w\-.]+\.(mp4|webm|jpg|jpeg|png)$|^overlays/o\d{2,3}\.png$")
TIPO_MIDIA = {".mp4": "video/mp4", ".webm": "video/webm", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".png": "image/png"}
```

Rota `file_` passa a ser:

```python
@app.get("/api/file")
def file_(request: Request, id: str, name: str):
    if not (FILE_NAME.fullmatch(name) or MIDIA.fullmatch(name)):
        raise HTTPException(400, "nome inválido")
    proj = _proj(request, id)
    path = proj / name
    if not path.resolve().is_relative_to(proj.resolve()):
        raise HTTPException(400, "nome inválido")
    if not path.is_file():
        raise HTTPException(404, "arquivo não encontrado")
    return FileResponse(path, media_type=TIPO_MIDIA.get(path.suffix.lower(), "image/png"))
```

Após a rota `/api/quadro`:

```python
@app.get("/api/folha")
def folha_route(request: Request, id: str, tipo: str):
    if tipo not in folha.TIPOS:
        raise HTTPException(400, "tipo inválido")
    proj = _proj(request, id)
    try:
        return folha.ler(proj, tipo)
    except ValueError as e:
        raise HTTPException(422, str(e))
```

Atenção: `MIDIA` permite `.` no nome do arquivo, mas não `/` — `broll/cand/../../x.mp4` falha no regex; mesmo assim a checagem `is_relative_to` continua.

- [ ] **Step 4: Run tests**

Run: `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/server.py ui/test_server.py
git commit -m "feat(ui): /api/folha e mídias de candidatos/overlays em /api/file"
```

---

### Task 3: Aba Aprovação + núcleo da folha + folha de b-roll

**Files:**
- Create: `ui/static/folha.js`
- Modify: `ui/static/index.html` (aba, pane, script), `ui/static/app.js` (`FOLHAS`, `TABS`, `renderAll`, `renderTabs`, `renderTab`), `ui/static/board.js` (`boardCard`), `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `GET /api/folha`, `/api/file` (Task 2); globais de app.js: `S`, `el`, `api`, `escapeHtml`, `fmtMSS`, `hashFor`, `goTab`, `saveTab`, `sendReply(qid, text, 'proj')` (rejeita se HTTP !ok; em sucesso recarrega o projeto).
- Produces (usados na Task 4):
  - `FOLHAS` (app.js) = `['broll', 'clips', 'conceitos', 'overlays']`
  - `FOLHA_TIPOS` (folha.js) — registro por tipo: `{ sel(d) -> s, html(d) -> string, marca(box, d, s), clique?(e, d, s) -> bool, entrada?(e, d, s) -> bool, resposta(d, s) -> string }`
  - `okMais(tokens: string[]) -> string`, `midia(arq) -> URL`, `resposta(tipo, d, s) -> string`, `pedidoFolha() -> pedido|null`, `renderFolha()`, `atualizaFolha()`
  - DOM: `#tab-aprovacao`, `#tabs a[data-tab=aprovacao]`, `#fl-resp`, `#fl-coment`, `#fl-enviar`, `.fl-erro`, `.board-folha`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def _pedido_folha(proj, folha, qid=9, resultado="aprova?"):
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": qid, "status": "waiting_reply", "type": "instrucao", "text": "x",
         "resultado": resultado, "folha": folha}]), encoding="utf-8")


def _broll_fixture(proj):
    cand = proj / "broll" / "cand"
    cand.mkdir(parents=True)
    for n in ("a.mp4", "b.mp4", "c.jpg"):
        (cand / n).write_bytes(b"x")
    (proj / "broll.json").write_text(json.dumps({"momentos": [
        {"id": "b01", "t_in": 42, "t_out": 45, "termo": "gavel", "modo": "cut-in", "status": "proposto",
         "candidatos": [{"fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4", "dur": 6},
                        {"fonte": "pixabay", "tipo": "video", "arq": "broll/cand/b.mp4", "dur": 8}]},
        {"id": "b02", "t_in": 75, "t_out": 78, "termo": "court", "modo": "janela", "status": "proposto",
         "candidatos": [{"fonte": "pexels", "tipo": "foto", "arq": "broll/cand/c.jpg"}]}]}), encoding="utf-8")


def _queue(proj):
    return json.loads((proj / "ui" / "queue.json").read_text(encoding="utf-8"))


def test_folha_broll(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    assert page.locator("#tabs a[data-tab=aprovacao]").is_visible()
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.click(".fl-row[data-m=b01] .fl-cand[data-k='2']")
    page.click(".fl-row[data-m=b02] .fl-veto")
    assert page.locator("#fl-resp").inner_text() == "ok b01:2 b02:não"
    page.fill("#fl-coment", "valeu")
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    q = _queue(proj)
    assert q[0]["reply"] == "ok b01:2 b02:não\nvaleu" and q[0]["status"] == "pending"
    assert not page.locator("#tabs a[data-tab=aprovacao]").is_visible()


def test_folha_ausente_esconde_aba(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-fake/board'")
    assert not page.locator("#tabs a[data-tab=aprovacao]").is_visible()


def test_folha_link_no_board(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-folha")
    assert page.locator("#card-cortes .board-reply-input").count() == 0
    page.click("#card-cortes .board-folha")
    page.wait_for_function("document.body.dataset.tab === 'aprovacao'")
    page.wait_for_selector(".fl-row")


def test_folha_indisponivel(page, ui_url, fake_root):
    _pedido_folha(fake_root / "edit-fake", "clips")        # sem clips/clips.json
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-erro")
    txt = page.locator(".fl-erro").inner_text()
    assert "folha indisponível" in txt and "não encontrado" in txt
    assert "aprova?" in page.locator("#tab-aprovacao").inner_text()


def test_folha_selecao_sobrevive_troca_de_aba(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    page.click(".fl-row[data-m=b01] .fl-cand[data-k='2']")
    page.fill("#fl-coment", "rascunho")
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste", "x": 1}), encoding="utf-8")   # SSE
    page.wait_for_timeout(1500)
    page.click("#tabs a[data-tab=aprovacao]")
    page.wait_for_function("document.body.dataset.tab === 'aprovacao'")
    assert page.locator("#fl-resp").inner_text() == "ok b01:2"
    assert page.locator("#fl-coment").input_value() == "rascunho"


def test_folha_some_quando_respondida_pela_fila(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    page.fill(".queue-reply-input", "ok")
    page.click(".queue-reply-send")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_ui_smoke.py -q -k folha`
Expected: FAIL (timeouts — aba/folha não existem).

- [ ] **Step 3: index.html**

Em `<nav id="tabs">`, logo após `<a data-tab="edicao">Edição</a>`, inserir `<a data-tab="aprovacao" hidden>Aprovação ❓</a>`.
Após `<div id="tab-custos" class="tab-pane"></div>`, inserir `<div id="tab-aprovacao" class="tab-pane"></div>`.
Após `<script src="board.js"></script>`, inserir `<script src="folha.js"></script>`.

- [ ] **Step 4: app.js**

4a. Trocar `const TABS = ['board', 'edicao', 'docs', 'custos'];` por:

```js
const TABS = ['board', 'edicao', 'aprovacao', 'docs', 'custos'];
const FOLHAS = ['broll', 'clips', 'conceitos', 'overlays'];   // campo `folha` do pedido waiting_reply
```

4b. Em `renderAll`, logo após o bloco do fallback de `edicao` (o `if (body.dataset.tab === 'edicao' && !S.proj.has_edl) {...}`), inserir:

```js
  if (body.dataset.tab === 'aprovacao' && !pedidoFolha()) {   // sem folha aberta: volta ao Board
    body.dataset.tab = 'board';
    saveTab(S.pid, 'board');
    history.replaceState(null, '', hashFor(S.pid, 'board'));
  }
```

e, junto das outras chamadas por aba no fim de `renderAll` (após `if (tab === 'custos') renderCustosTab();`):

```js
  if (tab === 'aprovacao') renderFolha();
```

4c. Em `renderTabs`, dentro do `forEach`, acrescentar:

```js
    if (a.dataset.tab === 'aprovacao') a.hidden = !pedidoFolha();
```

4d. Em `renderTab`, acrescentar o ramo (antes do ramo de `edicao`):

```js
  else if (tab === 'aprovacao') { if (pedidoFolha()) renderFolha(); else goTab('board'); }
```

- [ ] **Step 5: board.js** — em `boardCard`, trocar a construção de `perg` por:

```js
  const pergunta = pedido ? escapeHtml(pedido.resultado || pedido.text || '') : '';
  const perg = !pedido ? ''
    : FOLHAS.includes(pedido.folha)
      ? `<div class="board-pergunta">
          <div class="board-q">${pergunta}</div>
          <a class="board-folha" href="${hashFor(S.pid, 'aprovacao')}">abrir folha ›</a>
        </div>`
      : `<div class="board-pergunta">
          <div class="board-q">${pergunta}</div>
          <textarea class="board-reply-input" data-pid="${escapeHtml(S.pid)}" data-qid="${pedido.id}" rows="2" placeholder="responder... (Enter envia, Ctrl+Enter quebra linha)"></textarea>
          <button class="board-reply-send" data-qid="${pedido.id}">Enviar</button>
        </div>`;
```

- [ ] **Step 6: Create `ui/static/folha.js`**

```js
// Folhas de aprovação (aba "Aprovação"): mostram o artefato do pedido waiting_reply com `folha`
// e montam a resposta textual (`ok` + exceções). A UI não escreve artefato: só responde a fila.
// Cada tipo registra em FOLHA_TIPOS: { sel(d), html(d), marca(box, d, s), clique?(e, d, s), entrada?(e, d, s), resposta(d, s) }.
const FOLHA_TIPOS = {};
const folhaSel = {};   // `${pid}:${qid}` → seleção + comentário (sobrevive a redesenho e troca de aba)
let folhaAtual = { key: null, tipo: null, qid: null, dados: null, erro: null };

function pedidoFolha() {
  return ((S.proj && S.proj.queue) || [])
    .filter(e => e.status === 'waiting_reply' && FOLHAS.includes(e.folha))
    .sort((a, b) => a.id - b.id)[0] || null;
}

const midia = arq => api('/api/file', { id: S.pid, name: arq });
const okMais = toks => (toks.length ? 'ok ' + toks.join(' ') : 'ok');

function resposta(tipo, d, s) {   // pura
  const T = FOLHA_TIPOS[tipo];
  return T && d && s ? T.resposta(d, s) : '';
}

async function renderFolha() {
  const box = el('tab-aprovacao');
  const p = pedidoFolha();
  if (!p) { box.innerHTML = ''; box.dataset.key = ''; return; }
  const key = `${S.pid}:${p.id}`;
  if (box.dataset.key === key) return;   // já desenhada: SSE não apaga vídeo, seleção nem comentário
  box.dataset.key = key;
  folhaAtual = { key, tipo: p.folha, qid: p.id, dados: null, erro: null };
  box.innerHTML = '<div class="dim fl-carregando">carregando folha…</div>';
  try {
    const r = await fetch(api('/api/folha', { id: S.pid, tipo: p.folha }));
    if (folhaAtual.key !== key) return;
    if (r.ok) folhaAtual.dados = await r.json();
    else folhaAtual.erro = (await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`;
  } catch (e) {
    if (folhaAtual.key !== key) return;
    folhaAtual.erro = String(e);
  }
  desenhaFolha(box, p);
}

function desenhaFolha(box, p) {
  const { key, tipo, dados, erro } = folhaAtual;
  const T = FOLHA_TIPOS[tipo];
  const cab = `<div class="fl-cab"><span class="tag">${escapeHtml(tipo)}</span>
    <span class="fl-perg">${escapeHtml(p.resultado || p.text || '')}</span></div>`;
  if (erro || !T) {
    box.innerHTML = cab + `<div class="fl-erro">folha indisponível — responda pela fila
      <div class="dim">${escapeHtml(erro || 'tipo desconhecido')}</div></div>`;
    return;
  }
  if (!folhaSel[key]) folhaSel[key] = { ...T.sel(dados), coment: '' };
  box.innerHTML = cab + `<div class="fl-corpo fl-${tipo}">${T.html(dados)}</div>
    <div class="fl-rodape">
      <div class="mono" id="fl-resp"></div>
      <textarea id="fl-coment" rows="2" placeholder="comentário (opcional)"></textarea>
      <button id="fl-enviar">Enviar</button>
    </div>`;
  el('fl-coment').value = folhaSel[key].coment || '';
  atualizaFolha();
}

function atualizaFolha() {
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (!T || !s || !el('fl-resp')) return;
  T.marca(el('tab-aprovacao'), dados, s);
  const r = resposta(tipo, dados, s);
  el('fl-resp').textContent = r || '—';
  el('fl-enviar').disabled = !r;
}

function enviaFolha() {
  const { key, tipo, dados, qid } = folhaAtual;
  const s = folhaSel[key];
  const r = resposta(tipo, dados, s);
  if (!r) return;
  const coment = (s.coment || '').trim();
  el('fl-enviar').disabled = true;
  sendReply(qid, coment ? r + '\n' + coment : r, 'proj')
    .then(() => { delete folhaSel[key]; })
    .catch(e => {   // falhou: seleção e comentário continuam em folhaSel
      console.warn(e);
      if (el('fl-enviar')) el('fl-enviar').disabled = false;
    });
}

el('tab-aprovacao').addEventListener('click', e => {
  if (e.target.closest('#fl-enviar')) { enviaFolha(); return; }
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (T && s && T.clique && T.clique(e, dados, s)) atualizaFolha();
});

el('tab-aprovacao').addEventListener('input', e => {
  const { key, tipo, dados } = folhaAtual;
  const T = FOLHA_TIPOS[tipo], s = folhaSel[key];
  if (!s) return;
  if (e.target.id === 'fl-coment') { s.coment = e.target.value; return; }
  if (T && T.entrada && T.entrada(e, dados, s)) atualizaFolha();
});

// vídeo candidato toca no hover
el('tab-aprovacao').addEventListener('mouseover', e => {
  const v = e.target.closest('.fl-cand video');
  if (v) v.play().catch(() => {});
});
el('tab-aprovacao').addEventListener('mouseout', e => {
  const v = e.target.closest('.fl-cand video');
  if (v) v.pause();
});

// ---- b-roll: momento × candidatos ----
const kDe = rot => (rot ? +String(rot).split('-').pop() : 1);
const falta = "this.parentNode.classList.add('fl-falta')";

FOLHA_TIPOS.broll = {
  sel: d => ({ m: Object.fromEntries(d.momentos.map(m => [m.id, { k: kDe(m.escolhido), prop: kDe(m.escolhido), veto: false }])) }),
  html: d => d.momentos.map(m => `<div class="fl-row" data-m="${escapeHtml(m.id)}">
      <div class="fl-lab"><b>${escapeHtml(m.id)}</b><span class="mono">${fmtMSS(m.t_in)}</span>
        <span>${escapeHtml(m.termo)}</span><span class="dim">${escapeHtml(m.modo)}</span></div>
      <div class="fl-cands">${m.candidatos.map((c, i) => `<div class="fl-cand" data-k="${i + 1}">
        ${c.tipo === 'video'
          ? `<video muted loop preload="metadata" src="${midia(c.arq)}" onerror="${falta}"></video>`
          : `<img alt="" src="${midia(c.arq)}" onerror="${falta}">`}
        <span class="fl-leg">${i + 1} · ${escapeHtml(c.fonte)} · ${c.tipo === 'video' ? Math.round(c.dur) + 's' : 'foto'}${c.licenca ? ' · ' + escapeHtml(c.licenca) : ''}</span>
      </div>`).join('')}</div>
      <button class="fl-veto">vetar</button>
    </div>`).join('') || '<div class="dim">nenhum momento proposto</div>',
  marca: (box, d, s) => box.querySelectorAll('.fl-row').forEach(r => {
    const x = s.m[r.dataset.m];
    r.classList.toggle('vetado', x.veto);
    r.querySelectorAll('.fl-cand').forEach(c => c.classList.toggle('sel', !x.veto && +c.dataset.k === x.k));
    r.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
  }),
  clique: (e, d, s) => {
    const r = e.target.closest('.fl-row');
    if (!r) return false;
    const x = s.m[r.dataset.m];
    if (e.target.closest('.fl-veto')) { x.veto = !x.veto; return true; }
    const c = e.target.closest('.fl-cand');
    if (!c) return false;
    x.k = +c.dataset.k; x.veto = false;
    return true;
  },
  resposta: (d, s) => okMais(d.momentos.flatMap(m => {
    const x = s.m[m.id];
    return x.veto ? [`${m.id}:não`] : x.k !== x.prop ? [`${m.id}:${x.k}`] : [];
  })),
};
```

- [ ] **Step 7: CSS** (append to `ui/static/style.css`)

```css
/* ---- folhas de aprovação ---- */
body[data-tab="aprovacao"] #tab-aprovacao { display: flex; flex-direction: column; }
#tab-aprovacao { padding: 0; }
.fl-cab { display: flex; gap: 10px; align-items: baseline; padding: 12px 14px 8px; }
.fl-perg { color: var(--text); }
.fl-corpo { flex: 1 1 0; min-height: 0; overflow: auto; padding: 4px 14px 14px; }
.fl-rodape { display: grid; grid-template-columns: 1fr minmax(160px, 30%) auto; gap: 10px; align-items: center;
  padding: 10px 14px; border-top: 1px solid var(--border); background: rgba(240, 178, 74, .06); }
#fl-resp { color: var(--accent); word-break: break-word; }
#fl-coment { resize: vertical; padding: 6px; }
#fl-enviar { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
#fl-enviar:disabled { opacity: .4; }
.fl-erro { margin: 20px 14px; padding: 14px; border: 1px dashed var(--border); border-radius: 8px; }
.fl-carregando { padding: 20px 14px; }
.fl-falta { background: repeating-linear-gradient(45deg, #1b1b20 0 8px, #222228 8px 16px); }
.vetado { opacity: .45; }
.fl-veto { align-self: center; }
.vetado .fl-veto { color: var(--fail); border-color: var(--fail); }

.fl-row { display: grid; grid-template-columns: 120px 1fr auto; gap: 10px; align-items: center;
  padding: 8px 0; border-bottom: 1px solid var(--border); }
.fl-lab { display: grid; gap: 2px; font-size: 12px; }
.fl-cands { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
.fl-cand { position: relative; aspect-ratio: 16 / 9; background: var(--panel-2); border-radius: 6px; overflow: hidden;
  cursor: pointer; outline: 2px solid transparent; }
.fl-cand.sel { outline-color: var(--accent); }
.fl-cand video, .fl-cand img { width: 100%; height: 100%; object-fit: cover; display: block; }
.fl-leg { position: absolute; left: 0; right: 0; bottom: 0; padding: 3px 6px; font-size: 10px;
  background: linear-gradient(transparent, #000c); color: #ddd; }

.board-folha { color: var(--accent); text-decoration: none; font-weight: 600; justify-self: start; }
```

- [ ] **Step 8: Run tests**

Run: `cd ui && python -m pytest test_ui_smoke.py -q` → all PASS; full `cd ui && python -m pytest -q` → all PASS. Screenshot da folha de b-roll do fixture salvo ao lado do report.

- [ ] **Step 9: Commit**

```bash
git add ui/static ui/test_ui_smoke.py
git commit -m "feat(ui): aba Aprovação com folha de b-roll, resposta ok+exceções e link no board"
```

---

### Task 4: Folhas de clipes, conceitos e overlays

**Files:**
- Modify: `ui/static/folha.js` (append), `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes (Task 3): `FOLHA_TIPOS`, `okMais`, `midia`, `falta`, `escapeHtml`, `fmtMSS`, `api`, `S.proj.has_final`; dados de `/api/folha` (shapes da Task 1).
- Produces: `FOLHA_TIPOS.clips`, `FOLHA_TIPOS.conceitos`, `FOLHA_TIPOS.overlays`, `tocaClipe(card, clipe)`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def test_folha_clips(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "clips").mkdir()
    (proj / "clips" / "clips.json").write_text(json.dumps({"x_padrao": 636, "clipes": [
        {"id": "c01", "slug": "a", "status": "proposto", "nota": 4, "gancho": "Zero inscritos", "x": 636,
         "legenda": False, "plataformas": ["shorts"], "ranges": [{"t_in": 1, "t_out": 3}]},
        {"id": "c02", "slug": "b", "status": "proposto", "nota": 3, "gancho": "Canal deletado",
         "plataformas": ["reels"], "ranges": [{"t_in": 5, "t_out": 7}]},
        {"id": "c03", "slug": "c", "status": "proposto", "nota": 2, "gancho": "g", "ranges": [{"t_in": 8, "t_out": 9}]}]}),
        encoding="utf-8")
    _pedido_folha(proj, "clips")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-clip")
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.click(".fl-clip[data-c=c01] [data-nota='3']")
    page.eval_on_selector(".fl-clip[data-c=c02] .fl-x",
                          "el => { el.value = 700; el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.click(".fl-clip[data-c=c02] .fl-legenda")
    page.click(".fl-clip[data-c=c03] .fl-veto")
    assert page.locator("#fl-resp").inner_text() == "ok c01:nota 3 c02:x=700 c02:legenda c03:não"
    assert page.locator(".fl-clip[data-c=c02] .fl-xv").inner_text() == "700"
    tr = page.eval_on_selector(".fl-clip[data-c=c02] .fl-916 video", "v => v.style.transform")
    assert tr.startswith("translateX(-")
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok c01:nota 3 c02:x=700 c02:legenda c03:não"


def test_folha_conceitos(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    (proj / "conceitos.json").write_text(json.dumps({"conceitos": [
        {"id": "A", "ideia": "mesmo mecanismo", "custo": "US$ 0,40", "horas": 2, "animatic": "animatic-A.png"},
        {"id": "B", "ideia": "mesmo tema", "exige_ia": True},
        {"id": "C", "ideia": "o contrário"}]}), encoding="utf-8")
    _pedido_folha(proj, "conceitos")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-col")
    assert page.locator("#fl-enviar").is_disabled()
    assert "exige IA" in page.locator(".fl-col[data-cc=B]").inner_text()
    page.click(".fl-col[data-cc=B] input[name=fl-um]")
    assert page.locator("#fl-resp").inner_text() == "B"
    page.click(".fl-varios-cb")
    page.click(".fl-col[data-cc=C] .fl-mult-cb")
    page.click(".fl-col[data-cc=A] .fl-mult-cb")
    assert page.locator("#fl-resp").inner_text() == "produzir: A C"
    page.fill(".fl-ajuste", "mais curto")
    assert page.locator("#fl-resp").inner_text() == "ajuste: mais curto"
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ajuste: mais curto"


def test_folha_overlays(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "overlays").mkdir()
    (proj / "overlays" / "o01.png").write_bytes(b"\x89PNG")
    (proj / "overlays" / "folha.json").write_text(json.dumps({"overlays": [
        {"id": "o01", "arquivo": "anim/A.mov", "t": 4, "dur": 2, "png": "overlays/o01.png"},
        {"id": "o02", "arquivo": "anim/B.mov", "t": 30, "dur": 3, "png": None, "erro": "arquivo do overlay não encontrado"},
        {"id": "o03", "arquivo": "anim/C.mov", "t": 60, "dur": 1, "png": None}]}), encoding="utf-8")
    _pedido_folha(proj, "overlays")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-ov")
    assert "não encontrado" in page.locator(".fl-ov[data-o=o02]").inner_text()
    page.click(".fl-ov[data-o=o01] .fl-veto")
    page.fill(".fl-ov[data-o=o03] .fl-otexto", "cor âmbar")
    assert page.locator("#fl-resp").inner_text() == "ok o01:não o03: cor âmbar"
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok o01:não o03: cor âmbar"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_ui_smoke.py -q -k "clips or conceitos or overlays"`
Expected: FAIL (`.fl-erro` "tipo desconhecido" no lugar da folha → timeout).

- [ ] **Step 3: Append to `ui/static/folha.js`**

```js
// ---- clipes: caixa 9:16 com o recorte real (crop 608x1080 em x do quadro 1920x1080) ----
const ALTURA_916 = 320;
const ESC_916 = ALTURA_916 / 1080;

function tocaClipe(card, c) {
  const v = card.querySelector('.fl-916 video');
  if (!v.paused) { v.pause(); return; }
  let i = 0;
  v.currentTime = c.ranges[0].t_in;
  v.ontimeupdate = () => {
    if (v.currentTime < c.ranges[i].t_out) return;
    i += 1;
    if (i >= c.ranges.length) { v.pause(); v.ontimeupdate = null; return; }
    v.currentTime = c.ranges[i].t_in;
  };
  v.play().catch(() => {});
}

FOLHA_TIPOS.clips = {
  sel: d => ({ c: Object.fromEntries(d.clipes.map(c => [c.id, { veto: false, nota: c.nota, x: c.x, legenda: c.legenda }])) }),
  html: d => {
    const src = api('/api/video', { id: S.pid, kind: S.proj.has_final ? 'final' : 'preview' });
    return d.clipes.map(c => `<div class="fl-clip" data-c="${escapeHtml(c.id)}">
        <div class="fl-916" title="clique: tocar/pausar o clipe"><video muted preload="metadata" src="${src}" onerror="${falta}"></video></div>
        <div class="fl-ganch">${escapeHtml(c.gancho)}</div>
        <div class="mono dim">${escapeHtml(c.id)} · ${fmtMSS(c.dur)} · ${escapeHtml(c.plataformas.join(', '))}</div>
        <div class="fl-nota">${[1, 2, 3, 4, 5].map(n => `<button data-nota="${n}" title="nota ${n}">★</button>`).join('')}</div>
        <label class="fl-xl">x <input type="range" class="fl-x" min="0" max="1312" step="2"> <span class="mono fl-xv"></span></label>
        <label><input type="checkbox" class="fl-legenda"> legenda</label>
        <button class="fl-veto">vetar</button>
      </div>`).join('') || '<div class="dim">nenhum clipe proposto</div>';
  },
  marca: (box, d, s) => box.querySelectorAll('.fl-clip').forEach(k => {
    const x = s.c[k.dataset.c];
    k.classList.toggle('vetado', x.veto);
    k.querySelectorAll('.fl-nota button').forEach(b => b.classList.toggle('on', +b.dataset.nota <= (x.nota || 0)));
    const r = k.querySelector('.fl-x');
    if (+r.value !== x.x) r.value = x.x;
    k.querySelector('.fl-xv').textContent = x.x;
    k.querySelector('.fl-legenda').checked = x.legenda;
    k.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
    k.querySelector('.fl-916 video').style.transform = `translateX(${-x.x * ESC_916}px)`;
  }),
  clique: (e, d, s) => {
    const k = e.target.closest('.fl-clip');
    if (!k) return false;
    const x = s.c[k.dataset.c];
    const n = e.target.closest('[data-nota]');
    if (n) { x.nota = +n.dataset.nota; return true; }
    if (e.target.closest('.fl-veto')) { x.veto = !x.veto; return true; }
    if (e.target.classList.contains('fl-legenda')) { x.legenda = e.target.checked; return true; }
    if (e.target.closest('.fl-916')) tocaClipe(k, d.clipes.find(c => c.id === k.dataset.c));
    return false;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-x')) return false;
    s.c[e.target.closest('.fl-clip').dataset.c].x = +e.target.value;
    return true;
  },
  resposta: (d, s) => okMais(d.clipes.flatMap(c => {
    const x = s.c[c.id];
    if (x.veto) return [`${c.id}:não`];
    const t = [];
    if (x.nota !== c.nota) t.push(`${c.id}:nota ${x.nota}`);
    if (x.x !== c.x) t.push(`${c.id}:x=${x.x}`);
    if (x.legenda !== c.legenda) t.push(`${c.id}:${x.legenda ? 'legenda' : 'sem-legenda'}`);
    return t;
  })),
};

// ---- conceitos A/B/C ----
FOLHA_TIPOS.conceitos = {
  sel: () => ({ um: null, varios: false, marcados: [], ajuste: '' }),
  html: d => `<label class="fl-varios"><input type="checkbox" class="fl-varios-cb"> produzir vários</label>
    <div class="fl-cols">${d.conceitos.map(c => `<div class="fl-col" data-cc="${escapeHtml(c.id)}">
        ${c.animatic ? `<img class="fl-anim" alt="animatic ${escapeHtml(c.id)}" title="clique: ampliar" src="${midia(c.animatic)}">`
                     : '<div class="fl-anim fl-falta"></div>'}
        <h4>${escapeHtml(c.id)}</h4>
        <p>${escapeHtml(c.ideia)}</p>
        <dl><dt>mantém</dt><dd>${escapeHtml(c.mantem)}</dd><dt>muda</dt><dd>${escapeHtml(c.muda)}</dd>
          <dt>custo</dt><dd class="mono">${escapeHtml(c.custo)}</dd><dt>horas</dt><dd class="mono">${escapeHtml(c.horas ?? '')}</dd></dl>
        ${c.exige_ia ? '<span class="tag espera">exige IA</span>' : ''}
        <label class="fl-um"><input type="radio" name="fl-um" value="${escapeHtml(c.id)}"> escolher</label>
        <label class="fl-mult"><input type="checkbox" class="fl-mult-cb" value="${escapeHtml(c.id)}"> produzir</label>
      </div>`).join('')}</div>
    <label class="fl-ajuste-l">ajuste <textarea class="fl-ajuste" rows="2" placeholder="em vez de escolher, pedir mudança"></textarea></label>`,
  marca: (box, d, s) => {
    box.querySelector('.fl-varios-cb').checked = s.varios;
    box.querySelectorAll('.fl-um').forEach(l => { l.hidden = s.varios; });
    box.querySelectorAll('.fl-mult').forEach(l => { l.hidden = !s.varios; });
    box.querySelectorAll('input[name=fl-um]').forEach(r => { r.checked = r.value === s.um; });
    box.querySelectorAll('.fl-mult-cb').forEach(c => { c.checked = s.marcados.includes(c.value); });
    box.querySelectorAll('.fl-col').forEach(c => c.classList.toggle('sel',
      s.varios ? s.marcados.includes(c.dataset.cc) : c.dataset.cc === s.um));
    const a = box.querySelector('.fl-ajuste');
    if (a.value !== s.ajuste) a.value = s.ajuste;
  },
  clique: (e, d, s) => {
    const t = e.target;
    if (t.tagName === 'IMG' && t.classList.contains('fl-anim')) { t.classList.toggle('grande'); return false; }
    if (t.classList.contains('fl-varios-cb')) { s.varios = t.checked; return true; }
    if (t.name === 'fl-um') { s.um = t.value; return true; }
    if (t.classList.contains('fl-mult-cb')) {
      s.marcados = t.checked ? [...new Set([...s.marcados, t.value])] : s.marcados.filter(v => v !== t.value);
      return true;
    }
    return false;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-ajuste')) return false;
    s.ajuste = e.target.value;
    return true;
  },
  resposta: (d, s) => {
    if (s.ajuste.trim()) return 'ajuste: ' + s.ajuste.trim();
    if (s.varios) return s.marcados.length >= 2 ? 'produzir: ' + [...s.marcados].sort().join(' ') : (s.marcados[0] || '');
    return s.um || '';
  },
};

// ---- overlays: frame de cada overlay do edl.json ----
FOLHA_TIPOS.overlays = {
  sel: d => ({ o: Object.fromEntries(d.overlays.map(o => [o.id, { veto: false, texto: '' }])) }),
  html: d => (d.overlays.length ? `<div class="fl-grade">${d.overlays.map(o => `<div class="fl-ov" data-o="${escapeHtml(o.id)}">
        ${o.png ? `<img alt="" src="${midia(o.png)}" onerror="this.classList.add('fl-falta')">`
                : `<div class="fl-falta fl-ovph">${escapeHtml(o.erro || 'sem frame')}</div>`}
        <div class="mono dim">${escapeHtml(o.id)} · ${fmtMSS(o.t)} · ${o.dur.toFixed(1)}s</div>
        <div class="fl-arq dim">${escapeHtml(o.arquivo)}</div>
        <button class="fl-veto">vetar</button>
        <input type="text" class="fl-otexto" placeholder="pedir mudança...">
      </div>`).join('')}</div>` : '<div class="dim">nenhum overlay</div>'),
  marca: (box, d, s) => box.querySelectorAll('.fl-ov').forEach(k => {
    const x = s.o[k.dataset.o];
    k.classList.toggle('vetado', x.veto);
    k.querySelector('.fl-veto').textContent = x.veto ? 'vetado' : 'vetar';
    const t = k.querySelector('.fl-otexto');
    t.disabled = x.veto;
    if (t.value !== x.texto) t.value = x.texto;
  }),
  clique: (e, d, s) => {
    const k = e.target.closest('.fl-ov');
    if (!k || !e.target.closest('.fl-veto')) return false;
    const x = s.o[k.dataset.o];
    x.veto = !x.veto;
    return true;
  },
  entrada: (e, d, s) => {
    if (!e.target.classList.contains('fl-otexto')) return false;
    s.o[e.target.closest('.fl-ov').dataset.o].texto = e.target.value;
    return true;
  },
  resposta: (d, s) => okMais(d.overlays.flatMap(o => {
    const x = s.o[o.id];
    return x.veto ? [`${o.id}:não`] : x.texto.trim() ? [`${o.id}: ${x.texto.trim()}`] : [];
  })),
};
```

- [ ] **Step 4: CSS** (append to `ui/static/style.css`)

```css
.fl-corpo.fl-clips { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; align-content: start; }
.fl-clip { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px; display: grid; gap: 6px; justify-items: start; }
.fl-916 { position: relative; width: calc(320px * 608 / 1080); height: 320px; overflow: hidden; border-radius: 6px; background: #000; cursor: pointer; justify-self: center; }
.fl-916 video { position: absolute; top: 0; left: 0; height: 100%; width: auto; }
.fl-ganch { font-weight: 600; }
.fl-nota button { background: none; border: none; padding: 0 2px; color: #3a3a42; font-size: 16px; }
.fl-nota button.on { color: var(--accent); }
.fl-xl { display: flex; gap: 6px; align-items: center; }

.fl-varios { display: inline-flex; gap: 6px; margin: 4px 0 10px; }
.fl-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.fl-col { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px; display: grid; gap: 6px; align-content: start; }
.fl-col.sel { border-color: var(--accent); }
.fl-col h4 { margin: 0; font-size: 18px; }
.fl-col p { margin: 0; }
.fl-col dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; margin: 0; font-size: 12px; }
.fl-col dt { color: var(--text-dim); }
.fl-col dd { margin: 0; }
.fl-anim { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 6px; cursor: zoom-in; }
.fl-anim.grande { position: fixed; inset: 4vh 4vw; width: 92vw; height: 92vh; object-fit: contain; z-index: 50;
  background: #000e; cursor: zoom-out; aspect-ratio: auto; }
.fl-ajuste-l { display: grid; gap: 4px; margin-top: 12px; }
.fl-ajuste { resize: vertical; padding: 6px; }

.fl-grade { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.fl-ov { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 8px; display: grid; gap: 5px; }
.fl-ov img, .fl-ovph { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 5px; }
.fl-ovph { display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--text-dim); }
.fl-arq { font-size: 11px; word-break: break-all; }
.fl-otexto { padding: 4px 6px; }
```

- [ ] **Step 5: Run tests**

Run: `cd ui && python -m pytest test_ui_smoke.py -q` → all PASS; full suite → all PASS. Screenshot das três folhas do fixture ao lado do report.

- [ ] **Step 6: Commit**

```bash
git add ui/static/folha.js ui/static/style.css ui/test_ui_smoke.py
git commit -m "feat(ui): folhas de clipes (recorte 9:16), conceitos A/B/C e overlays"
```

---

### Task 5: Receitas + CLAUDE.md (protocolo `folha` e `ok` + exceções)

**Files:**
- Modify: `CLAUDE.md`, `Formatos/padrao-youtube-longo.md`, `Formatos/padrao-youtube-shorts.md`, `Formatos/referencia.md`
- Test: `ui/test_folha.py` (append)

**Interfaces:**
- Consumes: `pipeline.ROOT`.
- Produces: texto de protocolo que o Claude segue.

- [ ] **Step 1: Write the failing test** (append to `ui/test_folha.py`; `import pipeline` no topo)

```python
import pipeline


def _txt(rel):
    return (pipeline.ROOT / rel).read_text(encoding="utf-8")


def test_protocolo_folhas_documentado():
    claude = _txt("CLAUDE.md")
    assert '"folha"' in claude and "ok` + exceções" in claude
    longo = _txt("Formatos/padrao-youtube-longo.md")
    assert 'folha: "broll"' in longo and 'folha: "overlays"' in longo
    assert "python ui/folha.py overlays" in longo and "§5.2" in longo
    assert 'folha: "clips"' in _txt("Formatos/padrao-youtube-shorts.md")
    ref = _txt("Formatos/referencia.md")
    assert "conceitos.json" in ref and 'folha: "conceitos"' in ref
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && python -m pytest test_folha.py -q -k protocolo` → FAIL.

- [ ] **Step 3: CLAUDE.md** — no item 4 do "Ciclo de um pedido" (o que começa com `4. Pedido grande/ambíguo`), acrescentar ao fim do item, como novas linhas indentadas do mesmo item:

```markdown
   Aprovação com folha visual (b-roll, clipes, conceitos, overlays): gravar no
   pedido `"folha": "broll" | "clips" | "conceitos" | "overlays"` junto com a
   pergunta — a UI mostra a aba Aprovação e devolve a resposta no formato
   `ok` + exceções: `ok` = tudo como proposto; `ok b03:2 b05:não` = as
   exceções valem e o resto fica aprovado como proposto. Resposta só com
   tokens (sem `ok`) continua válida.
```

- [ ] **Step 4: `Formatos/padrao-youtube-longo.md`**

4a. No `> Etapas` do topo, trocar `visual = §3, §4, §5, §5.1 ·` por `visual = §3, §4, §5, §5.1, §5.2 ·`.

4b. §5.1 passo 5 — substituir o passo inteiro (as linhas que começam em `5. \`waiting_reply\`: "b-roll: N momentos` até `` `status = aprovado|vetado`. ``) por:

```markdown
5. `waiting_reply` com `folha: "broll"` no pedido: "b-roll: N momentos — aprove na aba
   Aprovação (ou Docs › broll/sheet.png)". Resposta = `ok` + exceções (`ok b03:2 b05:não`):
   exceção vale, o resto fica aprovado com o `escolhido` proposto. Aplicar:
   `escolhido = "bNN-k"`, `status = aprovado|vetado`.
```

4c. Inserir nova seção logo antes de `## 6. Deriva de timeline (a armadilha)`:

```markdown
## 5.2 Aprovação dos overlays (folha)

Antes do render final, com overlays Remotion e b-roll já no `edl.json`:

1. `python ui/folha.py overlays edit/<proj>` → `overlays/oNN.png` (frame do meio de cada
   overlay sobre o vídeo base no mesmo tempo) + `overlays/folha.json`.
2. `waiting_reply` com `folha: "overlays"`: "overlays: N — aprove na aba Aprovação".
3. Resposta `ok` + exceções: `oNN:não` = remover o overlay do `edl.json`;
   `oNN: <texto>` = refazer o overlay conforme o texto (re-render Remotion) e repetir o passo 1
   só se algo mudou.

---
```

- [ ] **Step 5: `Formatos/padrao-youtube-shorts.md`** — no passo 5, trocar o trecho
`→ \`waiting_reply\`: "clipes: N propostos — ver Docs › clips.md. responda \`ok\`,`
`   ou \`c03:não c05:nota 3 c07:x=700 c02:sem-legenda\`".`
por:

```markdown
   → `waiting_reply` com `folha: "clips"`: "clipes: N propostos — aprove na aba Aprovação
   (ou Docs › clips.md)". Resposta `ok` + exceções, ex. `ok c03:não c05:nota 3 c07:x=700 c02:sem-legenda`
   (também `cNN:legenda`).
```

(Manter o resto do passo — "Aplicar a resposta ..." — como está.)

- [ ] **Step 6: `Formatos/referencia.md`**

6a. Passo 4: ao fim do passo, acrescentar a linha indentada:

```markdown
   Escrever também `conceitos.json` = `{"conceitos": [{"id": "A", "ideia", "mantem", "muda",
   "custo" (texto, ex. "US$ 0,40 + 600 créditos"), "horas", "exige_ia" (bool),
   "animatic": "animatic-A.png"}, ...]}` — é o que a folha de conceitos mostra.
```

6b. Passo 6: trocar `6. \`waiting_reply\`: "referência analisada — ver Docs › conceitos.md, animatic-A/B/C.png.` por
`6. \`waiting_reply\` com \`folha: "conceitos"\`: "referência analisada — escolha na aba Aprovação (ou Docs › conceitos.md, animatic-A/B/C.png).`
(manter a linha seguinte com as respostas aceitas).

- [ ] **Step 7: Run tests**

Run: `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md Formatos ui/test_folha.py
git commit -m "docs(folhas): protocolo folha + ok/exceções nas receitas, passo de overlays, conceitos.json"
```
