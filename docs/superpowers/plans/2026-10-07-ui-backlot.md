# UI Backlot (6a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biblioteca de projetos + board de etapas ao vivo (log de eventos por projeto) na UI local, com o editor atual virando aba.

**Architecture:** `ui/eventos.py` (stdlib) lê etapas do front-matter das receitas e um log append-only `ui/eventos.jsonl` por projeto, derivando o "quadro" (status por etapa, atual, custo por intervalo a partir de `costs.jsonl`). `ui/server.py` expõe `/api/library`, `/api/quadro`, `/api/capa`. Frontend vira SPA por hash (`#/`, `#/p/<id>/<aba>`) em scripts clássicos (`app.js` + `library.js` + `board.js`) com tema "Estúdio escuro".

**Tech Stack:** Python 3 stdlib, FastAPI (já usado), ffmpeg/ffprobe, JS vanilla, pytest, Python Playwright (chromium já instalado).

**Spec:** `docs/superpowers/specs/2026-10-07-ui-backlot-design.md`

## Global Constraints

- Nada copiado do OpenMontage (AGPL) — reescrita própria.
- Módulos `ui/*.py`: stdlib apenas; `sys.path.insert(0, str(Path(__file__).parent))` antes de `import pipeline`; CLI com JSON UTF-8 no stdout; exit 0 ok / 1 validação (`ValueError`) / 2 execução.
- Subprocess sempre com lista de args (nunca shell); injetável para teste.
- `ts` dos eventos = `datetime.now(timezone.utc).isoformat()`; comparação sempre como `datetime` aware.
- `eventos.jsonl` é só acréscimo: um `write` de `json.dumps(..., ensure_ascii=False) + "\n"` em modo `"a"`, UTF-8. Nunca reescrever.
- Id de etapa: `[a-z0-9-]+`. Status válidos no log: `inicio | fim | espera | pulada | falha`. Status derivados: `pendente | andamento | fim | espera | pulada | falha`.
- Tokens de cor (`:root`): `--bg #0e0e10`, `--panel #151518`, `--border #232328`, `--text #e8e6e3`, `--text-dim #77757d`, `--accent #f0b24a`, `--ok #5fd38a`, `--pending #f0b24a`, `--fail #e05252`. Fontes Inter + JetBrains Mono via Google Fonts `<link>`.
- UI nunca edita `edl.json`; nenhuma rota nova escreve fora de `<proj>/ui/`.
- Testes rodam com `cd ui && python -m pytest -q` (os testes vivem em `ui/test_*.py`, fixture `fake_root` de `ui/test_pipeline.py`).
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nunca matar processos que não sejam seus (nada de `taskkill /IM python.exe`).

## Review Focus

1. Projeto cujo `state.json` não é objeto (lista, lixo) ou não existe → biblioteca e quadro não quebram (`formato: null`, etapas vazias). Teste em Task 1 (`test_quadro_state_invalido`) e Task 3 (`test_library_projeto_sem_formato`).
2. Etapa reiniciada depois de `fim` (Claude refaz cortes) → status `andamento`, `fim: null`, custo conta só do novo `inicio`. Teste em Task 1 (`test_quadro_reinicio_apos_fim`).
3. Id de projeto com `/` (`edit/shorts/anotus/x`) navega e volta pelo hash sem perder a barra. Teste em Task 6 (smoke com projeto aninhado).
4. Usuário digitando resposta no Board enquanto o SSE recarrega → texto não some. Coberto pela guarda em `renderBoard` (Task 7) e verificado no smoke (`test_board_reply_sobrevive_reload`).
5. Capa: vídeo existe mas ffmpeg ausente/falha → cai para a próxima fonte sem 500. Teste em Task 4 (`test_capa_ffmpeg_falha_cai_no_animatic`).

---

### Task 1: `ui/eventos.py` — etapas, log, quadro, CLI

**Files:**
- Create: `ui/eventos.py`
- Test: `ui/test_eventos.py`

**Interfaces:**
- Consumes: `pipeline.ROOT`, `pipeline.read_json(path, default)`; `budget._linhas(path)` (gera dicts válidos de um jsonl), `budget._fin(v)` (número finito ou None).
- Produces:
  - `STATUS: set[str]` = `{"inicio","fim","espera","pulada","falha"}`
  - `etapas_de(formato: str | None, root: Path | None = None) -> list[dict]` — itens `{"id": str, "rotulo": str, "opcional": bool}`
  - `formato_de(proj: Path) -> str | None`
  - `registrar(proj: Path, etapa: str, status: str, nota: str | None = None, root: Path | None = None) -> dict`
  - `ler(proj: Path) -> list[dict]` — eventos `tipo == "etapa"` válidos, ordem do arquivo
  - `quadro(proj: Path, root: Path | None = None, agora: datetime | None = None) -> dict` — `{"formato", "sem_historico", "etapas", "fora_da_receita", "atual"}`; cada etapa `{"id","rotulo","opcional","status","inicio","fim","nota","custo_usd"}`
  - CLI: `python ui/eventos.py [--root R] etapa <proj> <etapa> <status> [--nota N]` e `python ui/eventos.py [--root R] quadro <proj>`

- [ ] **Step 1: Write the failing tests**

`ui/test_eventos.py`:

```python
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import eventos
from test_pipeline import fake_root  # fixture reexport

RECEITA = """---
etapas: roteiro?=Roteiro, transcricao=transcrição, cortes, render
---
# Formato: teste
"""


@pytest.fixture
def root(fake_root: Path) -> Path:
    (fake_root / "Formatos" / "teste.md").write_text(RECEITA, encoding="utf-8")
    proj = fake_root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    return fake_root


def _proj(root):
    return root / "edit-fake"


def _ev(proj, etapa, status, ts, nota=None, tipo="etapa"):
    linha = {"ts": ts, "tipo": tipo, "etapa": etapa, "status": status}
    if nota:
        linha["nota"] = nota
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def _custo(proj, ts, usd):
    with (proj / "ui" / "costs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "provedor": "x", "unidades": 1, "usd": usd, "creditos": 0}) + "\n")


T = lambda m: f"2026-10-07T10:{m:02d}:00+00:00"   # noqa: E731


def test_etapas_de_front_matter(root):
    assert eventos.etapas_de("teste", root) == [
        {"id": "roteiro", "rotulo": "Roteiro", "opcional": True},
        {"id": "transcricao", "rotulo": "transcrição", "opcional": False},
        {"id": "cortes", "rotulo": "cortes", "opcional": False},
        {"id": "render", "rotulo": "render", "opcional": False},
    ]


def test_etapas_de_sem_front_matter_ou_inexistente(root):
    assert eventos.etapas_de("padrao-youtube", root) == []   # "# receita", sem front-matter
    assert eventos.etapas_de("nao-existe", root) == []
    assert eventos.etapas_de(None, root) == []
    assert eventos.etapas_de("../x", root) == []


def test_etapas_de_ignora_id_invalido_e_duplicado(root):
    (root / "Formatos" / "t2.md").write_text(
        "---\netapas: a, B ruim, a, c-1\n---\n", encoding="utf-8")
    assert [e["id"] for e in eventos.etapas_de("t2", root)] == ["a", "c-1"]


def test_registrar_valido_faz_append(root):
    proj = _proj(root)
    e = eventos.registrar(proj, "cortes", "inicio", nota="vai", root=root)
    assert e["etapa"] == "cortes" and e["status"] == "inicio" and e["tipo"] == "etapa"
    assert datetime.fromisoformat(e["ts"]).tzinfo is not None
    eventos.registrar(proj, "cortes", "fim", root=root)
    linhas = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2 and "nota" not in json.loads(linhas[1])


@pytest.mark.parametrize("etapa,status", [("inventada", "inicio"), ("cortes", "acabou")])
def test_registrar_invalido_nao_escreve(root, etapa, status):
    proj = _proj(root)
    with pytest.raises(ValueError):
        eventos.registrar(proj, etapa, status, root=root)
    assert not (proj / "ui" / "eventos.jsonl").exists()


def test_registrar_formato_sem_etapas(root):
    proj = _proj(root)
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "padrao-youtube"}), encoding="utf-8")
    with pytest.raises(ValueError, match="sem etapas"):
        eventos.registrar(proj, "cortes", "inicio", root=root)


def test_registrar_projeto_inexistente(root):
    with pytest.raises(ValueError, match="projeto"):
        eventos.registrar(root / "nao-tem", "cortes", "inicio", root=root)


def test_ler_ignora_corrompidas_e_outros_tipos(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write("{quebrado\n")
        f.write(json.dumps({"ts": "não é data", "tipo": "etapa", "etapa": "x", "status": "fim"}) + "\n")
        f.write(json.dumps({"ts": T(1), "tipo": "etapa", "etapa": "x", "status": "talvez"}) + "\n")
        f.write("[1, 2]\n")
    _ev(proj, "cortes", "fim", T(2))
    _ev(proj, "x", "fim", T(3), tipo="decisao")
    assert [e["status"] for e in eventos.ler(proj)] == ["inicio", "fim"]


def test_quadro_sem_historico(root):
    q = eventos.quadro(_proj(root), root=root)
    assert q["formato"] == "teste" and q["sem_historico"] is True and q["atual"] is None
    assert [e["status"] for e in q["etapas"]] == ["pendente"] * 4
    assert q["fora_da_receita"] == []


def test_quadro_status_e_atual(root):
    proj = _proj(root)
    _ev(proj, "roteiro", "pulada", T(0))
    _ev(proj, "transcricao", "inicio", T(1))
    _ev(proj, "transcricao", "fim", T(5), nota="12 min")
    _ev(proj, "cortes", "inicio", T(6))
    q = eventos.quadro(proj, root=root, agora=datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc))
    st = {e["id"]: e for e in q["etapas"]}
    assert st["roteiro"]["status"] == "pulada"
    assert st["transcricao"]["status"] == "fim" and st["transcricao"]["fim"] == T(5)
    assert st["transcricao"]["nota"] == "12 min"
    assert st["cortes"]["status"] == "andamento" and st["cortes"]["fim"] is None
    assert st["render"]["status"] == "pendente"
    assert q["atual"] == "cortes" and q["sem_historico"] is False


def test_quadro_espera_vira_atual_sem_andamento(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "inicio", T(0))
    _ev(proj, "transcricao", "espera", T(1))
    q = eventos.quadro(proj, root=root)
    assert q["atual"] == "transcricao"
    assert q["etapas"][1]["status"] == "espera"


def test_quadro_falha(root):
    proj = _proj(root)
    _ev(proj, "render", "inicio", T(0))
    _ev(proj, "render", "falha", T(1), nota="ffmpeg")
    e = eventos.quadro(proj, root=root)["etapas"][3]
    assert e["status"] == "falha" and e["nota"] == "ffmpeg"


def test_quadro_reinicio_apos_fim(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    _ev(proj, "cortes", "fim", T(5))
    _ev(proj, "cortes", "inicio", T(10))
    _custo(proj, T(2), 1.0)     # do 1º intervalo: não conta mais
    _custo(proj, T(12), 0.25)
    agora = datetime(2026, 10, 7, 10, 20, tzinfo=timezone.utc)
    e = eventos.quadro(proj, root=root, agora=agora)["etapas"][2]
    assert e["status"] == "andamento" and e["inicio"] == T(10) and e["fim"] is None
    assert e["custo_usd"] == 0.25


def test_quadro_custo_por_intervalo(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "inicio", T(0))
    _ev(proj, "transcricao", "fim", T(5))
    _custo(proj, T(3), 0.48)       # dentro
    _custo(proj, T(5), 0.02)       # na borda: dentro
    _custo(proj, T(9), 2.0)        # fora de qualquer etapa
    with (proj / "ui" / "costs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": T(4), "usd": "NaN?"}) + "\n")   # inválido: ignorado
    e = eventos.quadro(proj, root=root)["etapas"][1]
    assert e["custo_usd"] == 0.5


def test_quadro_fora_da_receita(root):
    proj = _proj(root)
    _ev(proj, "legado", "fim", T(0))
    q = eventos.quadro(proj, root=root)
    assert [e["id"] for e in q["fora_da_receita"]] == ["legado"]
    assert q["fora_da_receita"][0]["rotulo"] == "legado"
    assert q["fora_da_receita"][0]["inicio"] is None and q["fora_da_receita"][0]["custo_usd"] == 0.0


def test_quadro_state_invalido(root):
    proj = _proj(root)
    (proj / "ui" / "state.json").write_text("[1, 2]", encoding="utf-8")
    q = eventos.quadro(proj, root=root)
    assert q["formato"] is None and q["etapas"] == []


def _cli(root, *a):
    cli = str(Path(eventos.__file__))
    return subprocess.run([sys.executable, cli, "--root", str(root), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_etapa_e_quadro(root):
    proj = str(_proj(root))
    r = _cli(root, "etapa", proj, "cortes", "inicio", "--nota", "começo")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["nota"] == "começo"
    r = _cli(root, "quadro", proj)
    assert r.returncode == 0 and json.loads(r.stdout)["atual"] == "cortes"


def test_cli_validacao_exit_1(root):
    r = _cli(root, "etapa", str(_proj(root)), "inventada", "inicio")
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && python -m pytest test_eventos.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eventos'`

- [ ] **Step 3: Write the implementation**

`ui/eventos.py`:

```python
"""Etapas da receita + log de eventos por projeto (<proj>/ui/eventos.jsonl).

Etapas vêm do front-matter de Formatos/<formato>.md:
    ---
    etapas: roteiro?=Roteiro, transcricao=transcrição, cortes
    ---
O log é só acréscimo; o quadro (status por etapa, atual, custo) é derivado."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import budget  # noqa: E402
import pipeline  # noqa: E402

STATUS = {"inicio", "fim", "espera", "pulada", "falha"}
ID_RE = re.compile(r"[a-z0-9-]+")
FORMATO_RE = re.compile(r"[\w\-]+")
FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def etapas_de(formato, root=None) -> list[dict]:
    root = root or pipeline.ROOT
    if not formato or not FORMATO_RE.fullmatch(formato):
        return []
    try:
        txt = (root / "Formatos" / f"{formato}.md").read_text(encoding="utf-8-sig")
    except OSError:
        return []
    m = FM_RE.match(txt)
    if not m:
        return []
    for ln in m.group(1).splitlines():
        k, _, v = ln.partition(":")
        if k.strip() == "etapas":
            break
    else:
        return []
    out, vistos = [], set()
    for item in v.split(","):
        id_, _, rot = item.strip().partition("=")
        id_ = id_.strip()
        opcional = id_.endswith("?")
        id_ = id_.rstrip("?")
        if not ID_RE.fullmatch(id_) or id_ in vistos:
            continue
        vistos.add(id_)
        out.append({"id": id_, "rotulo": rot.strip() or id_, "opcional": opcional})
    return out


def formato_de(proj: Path):
    st = pipeline.read_json(proj / "ui" / "state.json", {})
    f = st.get("formato") if isinstance(st, dict) else None
    return f if isinstance(f, str) else None


def _dt(s):
    try:
        d = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def registrar(proj: Path, etapa: str, status: str, nota=None, root=None) -> dict:
    root = root or pipeline.ROOT
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    if status not in STATUS:
        raise ValueError(f"status inválido: {status} (use {', '.join(sorted(STATUS))})")
    formato = formato_de(proj)
    ids = [e["id"] for e in etapas_de(formato, root)]
    if not ids:
        raise ValueError(f"formato sem etapas: {formato}")
    if etapa not in ids:
        raise ValueError(f"etapa '{etapa}' não está na receita {formato}: {', '.join(ids)}")
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "etapa",
          "etapa": etapa, "status": status}
    if nota:
        ev["nota"] = str(nota)
    path = proj / "ui" / "eventos.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro, uma escrita
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def ler(proj: Path) -> list[dict]:
    try:
        texto = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in texto.splitlines():
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba o quadro
        if (not isinstance(e, dict) or e.get("tipo") != "etapa"
                or not isinstance(e.get("etapa"), str) or not e["etapa"]
                or e.get("status") not in STATUS or _dt(e.get("ts")) is None):
            continue
        if not isinstance(e.get("nota"), str):
            e.pop("nota", None)
        out.append(e)
    return out


def _custos(proj: Path) -> list[tuple]:
    out = []
    for l in budget._linhas(proj / "ui" / "costs.jsonl"):
        t, u = _dt(l.get("ts")), budget._fin(l.get("usd", 0))
        if t is not None and u is not None:
            out.append((t, u))
    return out


def _resumo(item: dict, evs: list[dict], custos: list[tuple], agora: datetime) -> dict:
    if not evs:
        return {**item, "status": "pendente", "inicio": None, "fim": None,
                "nota": None, "custo_usd": 0.0}
    ult = evs[-1]["status"]
    status = "andamento" if ult == "inicio" else ult
    idx = max((i for i, e in enumerate(evs) if e["status"] == "inicio"), default=None)
    inicio = evs[idx]["ts"] if idx is not None else None
    depois = evs[idx + 1:] if idx is not None else evs
    fims = [e["ts"] for e in depois if e["status"] == "fim"]
    fim = fims[-1] if fims else None
    nota = next((e["nota"] for e in reversed(evs) if e.get("nota")), None)
    custo = 0.0
    if inicio:
        a, b = _dt(inicio), (_dt(fim) if fim else agora)
        custo = round(sum(u for t, u in custos if a <= t <= b), 4)
    return {**item, "status": status, "inicio": inicio, "fim": fim,
            "nota": nota, "custo_usd": custo}


def quadro(proj: Path, root=None, agora=None) -> dict:
    root = root or pipeline.ROOT
    agora = agora or datetime.now(timezone.utc)
    formato = formato_de(proj)
    receita = etapas_de(formato, root)
    evs = ler(proj)
    por: dict[str, list] = {}
    for e in evs:
        por.setdefault(e["etapa"], []).append(e)
    custos = _custos(proj)
    etapas = [_resumo(i, por.get(i["id"], []), custos, agora) for i in receita]
    ids = {i["id"] for i in receita}
    fora = [_resumo({"id": k, "rotulo": k, "opcional": False}, v, custos, agora)
            for k, v in por.items() if k not in ids]
    todas = etapas + fora
    andamento = [e for e in todas if e["status"] == "andamento"]
    espera = [e for e in todas if e["status"] == "espera"]
    if andamento:
        atual = max(andamento, key=lambda e: _dt(e["inicio"]))["id"]
    elif espera:
        atual = max(espera, key=lambda e: _dt(por[e["id"]][-1]["ts"]))["id"]
    else:
        atual = None
    return {"formato": formato, "sem_historico": not evs, "etapas": etapas,
            "fora_da_receita": fora, "atual": atual}


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="etapas e eventos do projeto")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("etapa")
    p.add_argument("proj"); p.add_argument("etapa"); p.add_argument("status")
    p.add_argument("--nota")
    p = sub.add_parser("quadro")
    p.add_argument("proj")
    ns = ap.parse_args()
    root = Path(ns.root)
    try:
        if ns.cmd == "etapa":
            out = registrar(Path(ns.proj), ns.etapa, ns.status, nota=ns.nota, root=root)
        else:
            out = quadro(Path(ns.proj), root=root)
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && python -m pytest test_eventos.py -q`
Expected: all PASS. Then full suite: `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/eventos.py ui/test_eventos.py
git commit -m "feat(eventos): etapas do front-matter, log append-only e quadro derivado"
```

---

### Task 2: Etapas nas receitas + protocolo no CLAUDE.md

**Files:**
- Modify: `Formatos/padrao-youtube-longo.md`, `Formatos/padrao-youtube-shorts.md`, `Formatos/padrao-ads.md`, `Formatos/pauta.md`, `Formatos/thumbnail.md`, `Formatos/referencia.md`, `CLAUDE.md`
- Test: `ui/test_eventos.py` (append)

**Interfaces:**
- Consumes: `eventos.etapas_de(formato, root)` (Task 1), `pipeline.ROOT`.
- Produces: front-matter `etapas:` nas 5 receitas de projeto; seção "Etapas" no `CLAUDE.md`.

- [ ] **Step 1: Write the failing test** (append to `ui/test_eventos.py`)

```python
import pipeline

ESPERADO = {
    "padrao-youtube-longo": ["roteiro", "transcricao", "cortes", "fatos", "visual", "audio", "legenda", "render", "entrega"],
    "padrao-youtube-shorts": ["transcricao", "candidatos", "aprovacao", "render", "draft"],
    "padrao-ads": ["referencia", "pesquisa", "roteiro", "producao", "audio", "render", "qc"],
    "pauta": ["pesquisa", "pauta", "aprovacao"],
    "thumbnail": ["frame", "recorte", "composicao", "variacoes"],
}


@pytest.mark.parametrize("formato,ids", ESPERADO.items())
def test_receitas_reais_declaram_etapas(formato, ids):
    etapas = eventos.etapas_de(formato, pipeline.ROOT)
    assert [e["id"] for e in etapas] == ids
    assert all(e["rotulo"] for e in etapas)


def test_receitas_reais_tem_mapa_de_etapas():
    for formato in ESPERADO:
        txt = (pipeline.ROOT / "Formatos" / f"{formato}.md").read_text(encoding="utf-8")
        assert "> Etapas:" in txt, formato
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && python -m pytest test_eventos.py -q -k receitas_reais`
Expected: FAIL (listas vazias / sem "> Etapas:").

- [ ] **Step 3: Add front-matter + mapa a cada receita**

Inserir **no topo absoluto** de cada arquivo (antes do `#` título) o front-matter, e **logo abaixo do título `#`** o bloco `> Etapas:`. Conteúdo exato:

`Formatos/padrao-youtube-longo.md`:
```
---
etapas: roteiro?=roteiro, transcricao=transcrição, cortes, fatos, visual, audio=áudio, legenda, render, entrega
---
```
Bloco (abaixo de `# Formato: Padrão YouTube — vídeo longo (horizontal)`):
```
> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> roteiro = §0.0 (pular se não houve pedido `roteiro`) · transcricao = §0.1 + `transcribe.py` do §1 ·
> cortes = §2 (+ `plan_cuts.py`/`verify_text.py` do §1) · fatos = §1.1 · visual = §3, §4, §5, §5.1 ·
> audio = §0.3 + §8.1 · legenda = §7 · render = `rezoom.py` → `recomposite.py` do §1 + §6/§6.1 + §8 ·
> entrega = §9 + §0 (export).
```

`Formatos/padrao-youtube-shorts.md`:
```
---
etapas: transcricao=transcrição, candidatos, aprovacao=aprovação, render, draft=draft Publora
---
```
Bloco:
```
> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> transcricao = Método 1 · candidatos = Método 2–4 · aprovacao = Método 5 (`espera` no waiting_reply) ·
> render = Método 6 · draft = Método 7–8.
```

`Formatos/padrao-ads.md`:
```
---
etapas: referencia?=referência, pesquisa, roteiro, producao=produção, audio=áudio, render, qc=QC
---
```
Bloco:
```
> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> referencia = fluxo `Formatos/referencia.md` (pular quando não veio de referência) ·
> pesquisa = "Pesquisa e roteiro" 1–5 · roteiro = "Pesquisa e roteiro" 6–7 ·
> producao = "Técnica de produção" (motion, footage, encode) · audio = SFX + trilha ·
> render = montagem final · qc = "QC antes de entregar" + "Entrega".
```

`Formatos/pauta.md`:
```
---
etapas: pesquisa, pauta, aprovacao=aprovação
---
```
Bloco:
```
> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> pesquisa = passos 1–2 · pauta = passo 3 · aprovacao = passos 4–5.
```
E no mesmo arquivo, trocar o trecho `(criar \`ui/\` nele para aparecer na UI)` por
`(criar \`ui/\` e \`ui/state.json\` = \`{"formato": "pauta"}\` nele para aparecer na UI e o log de etapas validar)`.

`Formatos/thumbnail.md`:
```
---
etapas: frame, recorte, composicao=composição, variacoes=variações
---
```
Bloco:
```
> Etapas (`python ui/eventos.py etapa <proj> <id> inicio|fim|espera|pulada|falha [--nota]`):
> frame = "Escolha do frame" · recorte = "Recorte (rembg)" · composicao = "Composição" · variacoes = "Variações" + "Entrega".
```

`Formatos/padrao-youtube-longo.md` §0.0 passo 1: trocar `1. Criar \`edit/<slug>/ui/\` (projeto aparece como "não iniciado").` por
`1. Criar \`edit/<slug>/ui/\` e \`ui/state.json\` = \`{"formato": "padrao-youtube-longo"}\` (projeto aparece como "não iniciado"); \`eventos.py etapa ... roteiro inicio\`.`

`Formatos/referencia.md` (sem front-matter — não é formato de projeto): logo abaixo do título, adicionar:
```
> Etapas: o projeto é `padrao-ads`; todo este fluxo é a etapa `referencia` —
> `python ui/eventos.py etapa <proj> referencia inicio` logo após o passo 0,
> `... espera` no passo 6, `... fim --nota "escolhido X"` no passo 7.
```

- [ ] **Step 4: CLAUDE.md — seção "Etapas"**

Inserir antes de `## Orçamento (ações pagas)`:

```markdown
## Etapas (board da UI)

Cada receita declara `etapas:` no front-matter e um mapa `> Etapas:` no topo.
Registrar no log do projeto (a UI acende a trilha ao vivo):

- Começou etapa: `python ui/eventos.py etapa <proj> <id> inicio`.
- Concluiu: `python ui/eventos.py etapa <proj> <id> fim --nota "<resumo curto>"`.
- Abriu `waiting_reply` dentro dela: `... <id> espera`.
- Etapa opcional que não vai rodar: `... <id> pulada`. Erro: `... <id> falha --nota "<motivo>"`.
- exit 1 (etapa/status inválido, formato sem etapas) → conferir o front-matter
  da receita e o `formato` do `state.json`; nunca inventar id.
- Custo por etapa sai sozinho do `costs.jsonl` (intervalo início→fim).
```

- [ ] **Step 5: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS (incl. `test_receitas_reais_*`).

- [ ] **Step 6: Commit**

```bash
git add Formatos CLAUDE.md ui/test_eventos.py
git commit -m "docs(etapas): front-matter de etapas nas receitas e protocolo no CLAUDE.md"
```

---

### Task 3: Servidor — `/api/quadro`, `/api/library`, `has_edl`, SSE de eventos

**Files:**
- Modify: `ui/server.py` (imports; nova seção após `/api/global-queue`; `WATCH`)
- Modify: `ui/pipeline.py` (`load_project`: chave `has_edl`)
- Test: `ui/test_server.py` (append)

**Interfaces:**
- Consumes: `eventos.quadro(proj, root=root)` (Task 1); `pipeline.find_projects(root)`, `pipeline.project_dir(root, pid)`, `pipeline.claude_online(proj)`, `pipeline.read_json`; `budget.gasto_projeto(proj)` → `{"usd", "creditos"}`; `_mtime(p)` (já em server.py).
- Produces:
  - `GET /api/quadro?id=` → dict de `eventos.quadro`.
  - `GET /api/library` → lista de `{id, name, started, has_preview, has_final, formato, etapas:[{id,rotulo,status}], atual:{id,rotulo,status}|null, sem_historico, pendencias, fila, custo_usd, claude_online, atividade}` ordenada por atividade desc.
  - `load_project(...)["has_edl"]: bool`.
  - SSE `mtimes.eventos`.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_server.py`)

```python
import os
import eventos


def _receita_e_state(root, proj_rel="edit-fake"):
    (root / "Formatos" / "teste.md").write_text(
        "---\netapas: transcricao=transcrição, cortes\n---\n# t\n", encoding="utf-8")
    ui = root / proj_rel / "ui"
    ui.mkdir(parents=True, exist_ok=True)
    (ui / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    return root / proj_rel


def test_quadro_route(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    q = client.get("/api/quadro", params={"id": "edit-fake"}).json()
    assert q["atual"] == "cortes" and [e["id"] for e in q["etapas"]] == ["transcricao", "cortes"]
    assert client.get("/api/quadro", params={"id": "../x"}).status_code == 400


def test_project_has_edl(client):
    assert client.get("/api/project", params={"id": "edit-fake"}).json()["has_edl"] is True
    assert client.get("/api/project", params={"id": "edit-raw"}).json()["has_edl"] is False


def test_library_com_log(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "transcricao", "fim", root=fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": 1, "status": "waiting_reply", "text": "aprova?"},
        {"id": 2, "status": "done", "text": "x"},
        {"id": 3, "status": "pending", "text": "y"}]), encoding="utf-8")
    (proj / "ui" / "costs.jsonl").write_text(
        json.dumps({"ts": "2026-10-07T10:00:00+00:00", "usd": 0.48, "creditos": 0}) + "\n", encoding="utf-8")
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    p = lib["edit-fake"]
    assert p["formato"] == "teste" and p["sem_historico"] is False
    assert p["etapas"] == [{"id": "transcricao", "rotulo": "transcrição", "status": "fim"},
                           {"id": "cortes", "rotulo": "cortes", "status": "andamento"}]
    assert p["atual"] == {"id": "cortes", "rotulo": "cortes", "status": "andamento"}
    assert p["pendencias"] == 1 and [e["id"] for e in p["fila"]] == [1, 3]
    assert p["custo_usd"] == 0.48
    assert p["atividade"] and p["name"] == "edit-fake"


def test_library_projeto_sem_formato(client):
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    raw = lib["edit-raw"]
    assert raw["formato"] is None and raw["etapas"] == [] and raw["atual"] is None
    assert raw["sem_historico"] is True and raw["pendencias"] == 0


def test_library_ordena_por_atividade(client, fake_root):
    velho = fake_root / "edit-fake"
    for p in [velho / "edl.json", velho / "preview.mp4", *velho.glob("ui/*")]:
        os.utime(p, (1_000_000, 1_000_000))
    (fake_root / "edit-raw" / "ui" / "queue.json").write_text("[]", encoding="utf-8")   # mais novo
    ids = [p["id"] for p in client.get("/api/library").json()]
    assert ids.index("edit-raw") < ids.index("edit-fake")


def test_library_projeto_ilegivel_nao_quebra(client, monkeypatch):
    real = eventos.quadro

    def quebra(proj, root=None, agora=None):
        if proj.name == "edit-fake":
            raise RuntimeError("boom")
        return real(proj, root=root, agora=agora)

    monkeypatch.setattr(eventos, "quadro", quebra)
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    assert lib["edit-fake"]["etapas"] == [] and lib["edit-fake"]["name"] == "edit-fake"
    assert "edit-raw" in lib


def test_events_vigia_eventos(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1])
    assert snap["mtimes"]["eventos"] is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_server.py -q -k "quadro or has_edl or library or vigia"`
Expected: FAIL (404 nas rotas novas, `KeyError: 'has_edl'`, `KeyError: 'eventos'`).

- [ ] **Step 3: Implement**

`ui/pipeline.py`, em `load_project`, dentro do dict retornado, logo após `"has_final": ...`:

```python
        "has_edl": (proj / "edl.json").exists(),
```

`ui/server.py` — imports: adicionar `import eventos` junto de `import budget`. Em `WATCH`, adicionar `"eventos": "ui/eventos.jsonl"`:

```python
WATCH = {"edl": "edl.json", "queue": "ui/queue.json",
         "state": "ui/state.json", "preview": "preview.mp4",
         "final": "final.mp4", "costs": "ui/costs.jsonl",
         "eventos": "ui/eventos.jsonl"}
```

Após a rota `/api/global-queue`, adicionar:

```python
@app.get("/api/quadro")
def quadro_route(request: Request, id: str):
    return eventos.quadro(_proj(request, id), root=_root(request))


FILA_ATIVA = {"pending", "executing", "waiting_reply"}


def _fila_ativa(proj: Path) -> list:
    q = pipeline.read_json(proj / "ui" / "queue.json", [])
    if not isinstance(q, list):
        return []
    return [e for e in q if isinstance(e, dict) and e.get("status") in FILA_ATIVA]


def _atividade(proj: Path) -> float:
    cands = [*(proj / "ui").glob("*"), proj / "edl.json", proj / "preview.mp4", proj / "final.mp4"]
    ms = [m for m in map(_mtime, cands) if m is not None]
    return max(ms) if ms else 0.0


def _curta(e):
    return {k: e[k] for k in ("id", "rotulo", "status")}


@app.get("/api/library")
def library(request: Request):
    root = _root(request)
    out = []
    for p in pipeline.find_projects(root):
        item = {**p, "formato": None, "etapas": [], "atual": None, "sem_historico": True,
                "pendencias": 0, "fila": [], "custo_usd": 0.0, "claude_online": False,
                "atividade": None, "_ts": 0.0}
        try:
            proj = pipeline.project_dir(root, p["id"])
            q = eventos.quadro(proj, root=root)
            fila = _fila_ativa(proj)
            atual = next((e for e in q["etapas"] + q["fora_da_receita"] if e["id"] == q["atual"]), None)
            ts = _atividade(proj)
            item.update(
                formato=q["formato"], etapas=[_curta(e) for e in q["etapas"]],
                atual=_curta(atual) if atual else None, sem_historico=q["sem_historico"],
                pendencias=sum(e["status"] == "waiting_reply" for e in fila), fila=fila,
                custo_usd=budget.gasto_projeto(proj)["usd"],
                claude_online=pipeline.claude_online(proj), _ts=ts,
                atividade=datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None)
        except Exception:  # noqa: BLE001 — projeto ilegível não derruba a biblioteca
            pass
        out.append(item)
    out.sort(key=lambda i: i["_ts"], reverse=True)
    for i in out:
        del i["_ts"]
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/server.py ui/pipeline.py ui/test_server.py
git commit -m "feat(ui): /api/library, /api/quadro, has_edl e SSE de eventos"
```

---

### Task 4: Servidor — `/api/capa`

**Files:**
- Modify: `ui/server.py` (imports `os`, `subprocess`; nova rota após `/api/library`)
- Test: `ui/test_server.py` (append)

**Interfaces:**
- Consumes: `_proj(request, id)`, `FileResponse`, `HTTPException`.
- Produces: `GET /api/capa?id=` → PNG/JPEG ou 404; módulo expõe `server._run` (= `subprocess.run`, monkeypatchável) e `server._frame(video: Path, dst: Path) -> None`.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_server.py`)

```python
import subprocess
import server as server_mod


def _fake_run_ok(calls):
    def run(args, **kw):
        calls.append(args[0])
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 0, stdout="10.0\n", stderr="")
        Path(args[-1]).write_bytes(b"\xff\xd8JPEGFAKE")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return run


def _fake_run_falha(args, **kw):
    raise FileNotFoundError("ffmpeg")


def test_capa_thumbnail_primeiro(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    (fake_root / "edit-fake" / "thumbnail-b.png").write_bytes(b"\x89PNGb")
    (fake_root / "edit-fake" / "thumbnail-a.png").write_bytes(b"\x89PNGa")
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.status_code == 200 and r.content == b"\x89PNGa" and calls == []


def test_capa_frame_do_video_com_cache(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    r = client.get("/api/capa", params={"id": "edit-fake"})   # fixture tem preview.mp4
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert (fake_root / "edit-fake" / "ui" / "capa.jpg").exists()
    assert calls == ["ffprobe", "ffmpeg"]
    client.get("/api/capa", params={"id": "edit-fake"})      # cache válido: não roda de novo
    assert calls == ["ffprobe", "ffmpeg"]


def test_capa_refaz_se_video_mais_novo(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    proj = fake_root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "capa.jpg").write_bytes(b"velha")
    os.utime(proj / "ui" / "capa.jpg", (1_000_000, 1_000_000))
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.content == b"\xff\xd8JPEGFAKE" and calls == ["ffprobe", "ffmpeg"]


def test_capa_ffmpeg_falha_cai_no_animatic(client, fake_root, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    (fake_root / "edit-fake" / "animatic-A.png").write_bytes(b"\x89PNGanim")
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.status_code == 200 and r.content == b"\x89PNGanim"


def test_capa_sheet_de_ref(client, fake_root, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    (fake_root / "edit-raw" / "ref").mkdir()
    (fake_root / "edit-raw" / "ref" / "sheet.png").write_bytes(b"\x89PNGsheet")
    assert client.get("/api/capa", params={"id": "edit-raw"}).content == b"\x89PNGsheet"


def test_capa_sem_fonte_404(client, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    assert client.get("/api/capa", params={"id": "edit-raw"}).status_code == 404
    assert client.get("/api/capa", params={"id": "../x"}).status_code == 400
```

(`Path` já está disponível? Se `test_server.py` não importa `Path`, adicionar `from pathlib import Path` no topo.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_server.py -q -k capa`
Expected: FAIL (`AttributeError: module 'server' has no attribute '_run'` / 404).

- [ ] **Step 3: Implement** (em `ui/server.py`; adicionar `import os` e `import subprocess` aos imports)

```python
_run = subprocess.run   # injetável nos testes


def _frame(video: Path, dst: Path) -> None:
    """Frame a 10% da duração → dst (jpg, 640 de largura). Escreve atômico."""
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(video)],
               capture_output=True, text=True, check=True, timeout=30)
    dur = float(out.stdout.strip())
    tmp = dst.with_name("capa.tmp.jpg")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur * 0.1:.2f}", "-i", str(video),
          "-frames:v", "1", "-vf", "scale=640:-2", str(tmp)],
         capture_output=True, check=True, timeout=30)
    os.replace(tmp, dst)


@app.get("/api/capa")
def capa(request: Request, id: str):
    proj = _proj(request, id)
    base = proj.resolve()

    def ok(p: Path) -> bool:
        return p.is_file() and p.resolve().is_relative_to(base)

    thumbs = [p for p in sorted(proj.glob("thumbnail*.png")) if ok(p)]
    if thumbs:
        return FileResponse(thumbs[0], media_type="image/png")
    cache = proj / "ui" / "capa.jpg"
    for nome in ("final.mp4", "preview.mp4"):
        video = proj / nome
        if not ok(video):
            continue
        if ok(cache) and cache.stat().st_mtime >= video.stat().st_mtime:
            return FileResponse(cache, media_type="image/jpeg")
        try:
            cache.parent.mkdir(exist_ok=True)
            _frame(video, cache)
            return FileResponse(cache, media_type="image/jpeg")
        except (OSError, ValueError, subprocess.SubprocessError):
            continue   # ffmpeg ausente/falhou: próxima fonte
    for rel in ("animatic-A.png", "ref/sheet.png"):
        p = proj / rel
        if ok(p):
            return FileResponse(p, media_type="image/png")
    raise HTTPException(404, "sem capa")
```

- [ ] **Step 4: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/server.py ui/test_server.py
git commit -m "feat(ui): /api/capa com thumbnail, frame do vídeo em cache, animatic e sheet"
```

---

### Task 5: Shell da SPA — rotas, abas, Docs/Custos em aba, tema Estúdio escuro

**Files:**
- Modify: `ui/static/index.html` (reescrita completa abaixo)
- Modify: `ui/static/app.js` (trechos listados)
- Modify: `ui/static/style.css` (tokens + layout novo)
- Create: `ui/static/library.js` e `ui/static/board.js` como **stubs** (preenchidos nas Tasks 6 e 7)
- Create: `ui/test_ui_smoke.py`

**Interfaces:**
- Consumes: `/api/project` (`has_edl`), `/api/quadro`, `/api/docs`, `/api/doc`, `/api/file`, `/api/budget` (Tasks 3–4 + existentes).
- Produces (globais JS usados nas Tasks 6–7):
  - `parseHash() -> {route:'library'} | {route:'project', pid, tab|null}`
  - `hashFor(pid, tab) -> string`, `goTab(tab)`, `route()`
  - `STATUS_LABEL` (mapa status → texto), `fmtUSD(v)`, `escapeHtml(s)`, `getJSON`, `postJSON`, `sendReply(qid, text, scope)`, `renderQueue()`, `renderBudget()`
  - `S.quadro`, `S.lib` (definido em `library.js`), `S.scrollTo`
  - Funções esperadas de `library.js`: `startLibrary()`, `stopLibrary()`, `loadLibrary()`; de `board.js`: `renderStepper()`, `renderBoard()`.
  - DOM: `#library-view`, `#project-view`, `#stepper`, `#tabs a[data-tab]`, `#tab-board|edicao|docs|custos`, `body[data-route][data-tab]`.
- Smoke fixture `ui_url(fake_root)` em `ui/test_ui_smoke.py` para Tasks 6–7.

- [ ] **Step 1: Write the failing smoke test** — `ui/test_ui_smoke.py`

```python
"""Smoke da UI no chromium (Playwright). Pula se o chromium não estiver disponível."""
import json
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

import server  # noqa: E402
from test_pipeline import fake_root  # noqa: E402,F401 — fixture reexport

RECEITA = "---\netapas: transcricao=transcrição, cortes, render\n---\n# t\n"


def _porta():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture
def ui_url(fake_root):
    (fake_root / "Formatos" / "teste.md").write_text(RECEITA, encoding="utf-8")
    ui = fake_root / "edit-fake" / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    (ui / "eventos.jsonl").write_text(
        json.dumps({"ts": "2026-10-07T10:00:00+00:00", "tipo": "etapa", "etapa": "transcricao", "status": "fim"}) + "\n" +
        json.dumps({"ts": "2026-10-07T10:05:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "inicio"}) + "\n",
        encoding="utf-8")
    server.app.state.root = fake_root
    port = _porta()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture
def page(ui_url):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"chromium indisponível: {e}")
        pg = b.new_page()
        pg.route("https://fonts.googleapis.com/**", lambda r: r.abort())
        pg.route("https://fonts.gstatic.com/**", lambda r: r.abort())
        yield pg
        b.close()


def test_rota_projeto_abas(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/edicao", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.route === 'project'")
    assert page.locator("#player").is_visible()
    assert page.locator("#timeline").is_visible()
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("location.hash === '#/p/edit-fake/custos'")
    assert page.locator("#tab-custos").is_visible()
    assert not page.locator("#timeline").is_visible()
    page.click("#tabs a[data-tab=docs]")
    page.wait_for_function("location.hash === '#/p/edit-fake/docs'")
    assert page.locator("#tab-docs").is_visible()


def test_aba_lembrada_e_edicao_desabilitada(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/custos", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    page.goto(ui_url + "/#/p/edit-fake", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-fake/custos'")
    page.goto(ui_url + "/#/p/edit-raw/edicao", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-raw/board'")   # sem edl.json
    assert "off" in page.locator("#tabs a[data-tab=edicao]").get_attribute("class")


def test_hash_vazio_vai_para_biblioteca(page, ui_url):
    page.goto(ui_url + "/", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.route === 'library'")
    assert page.locator("#library-view").is_visible()
    assert not page.locator("#project-view").is_visible()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && python -m pytest test_ui_smoke.py -q`
Expected: FAIL (no `body.dataset.route`), or SKIP if chromium indisponível — se pular, instalar com `python -m playwright install chromium` e repetir (precisa rodar de verdade).

- [ ] **Step 3: Rewrite `ui/static/index.html`**

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>video_editor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body data-route="library" data-tab="board">
<header>
  <span class="only-library brand">video_editor</span>
  <button class="only-library" id="btn-new" title="Criar projeto novo">+ Novo vídeo</button>
  <button class="only-library" id="btn-formats" title="Ver e editar as receitas de formato">Formatos</button>
  <a class="only-project back" id="btn-back" href="#/" title="Voltar à biblioteca">←</a>
  <span class="only-project proj-name" id="proj-name"></span>
  <select class="only-project" id="format-select" title="Formato/receita que o Claude segue neste projeto"></select>
  <span class="only-project mono" id="proj-cost" title="Gasto total do projeto"></span>
  <span class="spacer"></span>
  <div id="render-progress" hidden><div id="render-bar"></div><span id="render-label"></span></div>
  <button class="only-project" id="btn-render-preview" title="Enfileira render de preview (rápido, 720p)">Render Preview</button>
  <button class="only-project" id="btn-render-final" title="Enfileira render final (qualidade completa)">Render Final</button>
  <button id="budget-badge" class="budget" title="Gasto / teto. Clique pra ver o mês e editar tetos"><span id="budget-bar"></span><span id="budget-label">US$ —</span></button>
  <span id="claude-status" class="offline" title="Fica verde quando uma sessão do Claude está escutando a fila">Claude offline</span>
</header>
<main>
  <aside id="queue-pane">
    <div class="pane-title">Fila</div>
    <div id="activity-box" hidden>
      <div id="activity-now"><span class="dot"></span><span id="activity-now-text"></span></div>
      <div id="activity-prev" hidden>✓ <span id="activity-prev-text"></span></div>
    </div>
    <div id="queue-panel"></div>
    <div id="instruction-pane" class="only-project">
      <div id="instr-context">instrução geral</div>
      <textarea id="instr-text" placeholder="o que fazer..."></textarea>
      <button id="instr-send" title="Enviar instrução pro Claude (Ctrl+Enter). Ctrl+Z cancela o último pedido">Enviar</button>
    </div>
  </aside>
  <section id="library-view" class="only-library">
    <div id="lib-filters">
      <div id="lib-chips"></div>
      <input type="search" id="lib-busca" placeholder="buscar projeto...">
    </div>
    <div id="lib-grid"></div>
  </section>
  <section id="project-view" class="only-project">
    <div id="stepper"></div>
    <nav id="tabs">
      <a data-tab="board">Board</a><a data-tab="edicao">Edição</a><a data-tab="docs">Docs</a><a data-tab="custos">Custos</a>
    </nav>
    <div id="tab-board" class="tab-pane"></div>
    <div id="tab-edicao" class="tab-pane">
      <section id="player-pane">
        <div id="stage">
          <video id="player" controls title="Espaço = play/pause"></video>
          <div id="no-preview" hidden>sem preview — peça um render</div>
        </div>
      </section>
      <aside id="side-pane">
        <div class="pane-title">Cortes</div>
        <div id="cut-list" title="Clique num corte pra ver o trecho no player"></div>
      </aside>
    </div>
    <div id="tab-docs" class="tab-pane"></div>
    <div id="tab-custos" class="tab-pane"></div>
  </section>
</main>
<footer class="only-edicao">
  <canvas id="timeline" title="Clique num clipe = preview; roda do mouse = zoom; arrastar fundo = pan; arrastar borda de clipe (com zoom) = ajuste fino ±2s"></canvas>
</footer>
<div id="modal" hidden></div>
<script src="app.js"></script>
<script src="library.js"></script>
<script src="board.js"></script>
</body>
</html>
```

Stubs (substituídos nas Tasks 6–7):

`ui/static/library.js`:
```js
// Biblioteca (#/) — preenchida na Task 6
S.lib = { items: [] };
function startLibrary() {}
function stopLibrary() {}
function loadLibrary() {}
```

`ui/static/board.js`:
```js
// Board + stepper — preenchidos na Task 7
function renderStepper() {}
function renderBoard() {}
```

- [ ] **Step 4: Edit `ui/static/app.js`**

4a. Logo após a definição de `escapeHtml` (topo do arquivo), adicionar:

```js
const TABS = ['board', 'edicao', 'docs', 'custos'];
const STATUS_LABEL = { pendente: 'pendente', andamento: 'em andamento', fim: 'ok',
  espera: 'esperando você', pulada: 'pulada', falha: 'falha' };
const hashFor = (pid, tab) => `#/p/${encodeURIComponent(pid)}/${tab}`;

function parseHash() {
  const m = location.hash.match(/^#\/p\/([^/]+)(?:\/([a-z]+))?$/);
  if (!m) return { route: 'library' };
  return { route: 'project', pid: decodeURIComponent(m[1]), tab: TABS.includes(m[2]) ? m[2] : null };
}

function lastTab(pid) { try { return localStorage.getItem('tab:' + pid); } catch { return null; } }
function saveTab(pid, tab) { try { localStorage.setItem('tab:' + pid, tab); } catch { /* sem storage */ } }

function goTab(tab) {
  const h = hashFor(S.pid, tab);
  if (location.hash === h) route(); else location.hash = h;
}

async function route() {
  const r = parseHash();
  const body = document.body;
  if (r.route === 'library') {
    body.dataset.route = 'library';
    if (S.es) { S.es.close(); S.es = null; }
    S.pid = null; S.proj = null; S.quadro = null; S.selected = null;
    const v = el('player');
    v.pause(); if (v.getAttribute('src')) v.removeAttribute('src');
    renderBudget();
    startLibrary();
    return;
  }
  stopLibrary();
  let tab = r.tab || lastTab(r.pid) || 'board';
  if (!TABS.includes(tab)) tab = 'board';
  if (r.tab !== tab) { history.replaceState(null, '', hashFor(r.pid, tab)); }
  const prev = body.dataset.tab;
  body.dataset.route = 'project';
  body.dataset.tab = tab;
  saveTab(r.pid, tab);
  if (S.pid !== r.pid || !S.proj) await loadProject(r.pid);
  else renderTab(tab, prev);
}

window.addEventListener('hashchange', route);
```

4b. **Apagar** as funções `refreshProjectList` e `loadProjects` inteiras.

4c. Substituir `loadProject` e `loadProjectInner` por:

```js
async function loadProject(pid) {
  try {
    await loadProjectInner(pid);
  } catch (err) {   // servidor reiniciando etc.: tenta de novo em 2s se ainda estamos nele
    console.warn('loadProject falhou, retry em 2s', err);
    setTimeout(() => { if (parseHash().pid === pid) loadProject(pid); }, 2000);
  }
}

async function loadProjectInner(pid) {
  const r = await fetch(api('/api/project', { id: pid }));
  if (r.status === 400 || r.status === 404) { location.hash = '#/'; return; }
  const proj = await r.json();
  const [wave, quadro, gq, act, bud] = await Promise.all([
    getJSON('/api/waveform', { id: pid }), getJSON('/api/quadro', { id: pid }),
    getJSON('/api/global-queue'), getJSON('/api/activity'),
    getJSON('/api/budget').catch(() => null)]);
  if (parseHash().pid !== pid) return;   // usuário saiu do projeto durante o load
  const novo = S.pid !== pid;
  S.pid = pid; S.proj = proj; S.wave = wave; S.quadro = quadro;
  S.globalQueue = gq; S.activity = act; S.budget = bud;
  if (novo) { S.selected = null; S.docsPid = null; }
  const v = el('player');
  el('no-preview').hidden = S.proj.has_preview;
  if (S.proj.has_preview)
    v.src = api('/api/video', { id: pid, kind: 'preview' });
  else if (v.getAttribute('src')) v.removeAttribute('src');
  renderAll();
  if (novo || !S.es) connectSSE(pid);
}
```

4d. Em `connectSSE`, trocar a linha
`if (changed.includes('docs') && S.docsOpen && !el('modal').hidden) openDocsModal();`
por
`if (changed.includes('docs') && document.body.dataset.tab === 'docs') renderDocsTab();`

4e. Substituir `renderAll` por:

```js
function renderAll() {
  if (!S.proj) return;
  const body = document.body;
  if (body.dataset.tab === 'edicao' && !S.proj.has_edl) {   // sem edl.json: Edição desabilitada
    body.dataset.tab = 'board';
    history.replaceState(null, '', hashFor(S.pid, 'board'));
  }
  buildTimeMap();
  initTimelineOnce();
  if (S.pid !== lastFitPid) { fitView(); lastFitPid = S.pid; }
  renderHeader();
  renderTabs();
  renderStepper();
  renderCutList();
  renderTimeline();
  renderQueue();
  renderProgress();
  renderBudget();
  const tab = body.dataset.tab;
  if (tab === 'board') renderBoard();
  if (tab === 'custos') renderCustosTab();
  if (tab === 'docs' && S.docsPid !== S.pid) { S.docsPid = S.pid; renderDocsTab(); }
  if (S.formats) renderFormatSelect(); else loadFormats().then(renderFormatSelect);
}

function renderHeader() {
  el('proj-name').textContent = S.pid.split('/').slice(-2).join('/');
  el('proj-cost').textContent = fmtUSD((S.proj.custos || {}).usd);
}

function renderTabs() {
  const tab = document.body.dataset.tab;
  document.querySelectorAll('#tabs a').forEach(a => {
    a.href = hashFor(S.pid, a.dataset.tab);
    a.classList.toggle('on', a.dataset.tab === tab);
    a.classList.toggle('off', a.dataset.tab === 'edicao' && !(S.proj && S.proj.has_edl));
  });
}

function renderTab(tab, prev) {
  renderTabs();
  if (tab === 'board') renderBoard();
  else if (tab === 'custos') renderCustosTab();
  else if (tab === 'docs') { S.docsPid = S.pid; renderDocsTab(); }
  else if (tab === 'edicao' && prev !== 'edicao')
    requestAnimationFrame(() => { fitView(); renderTimeline(); });
}
```

4f. Em `renderAll` antigo havia chamadas `renderAudioInfo(); renderBrollInfo(); renderClipsInfo(); renderRefInfo();` — já removidas pelo 4e. **Apagar** as funções `renderAudioInfo`, `renderBrollInfo`, `renderClipsInfo`, `renderRefInfo` (a Task 7 recria a lógica como `info*` puras em `board.js`).

4g. Em `renderQueue`, substituir a primeira linha de `projEntries` e o `prefix`:

```js
  const projEntries = S.proj
    ? (S.proj.queue || []).map(e => ({ ...e, _scope: 'proj' }))
    : (S.lib.items || []).flatMap(p => (p.fila || []).map(e => ({ ...e, _scope: p.id, _nome: p.name })));
```
e
```js
    const prefix = e._scope === 'global' ? '[novo] ' : e._nome ? `[${escapeHtml(e._nome)}] ` : '';
```
e nos dois `data-scope="${e._scope}"` usar `data-scope="${escapeHtml(e._scope)}"`.

4h. Substituir `sendReply` e o listener de clique do `queue-panel`:

```js
function sendReply(qid, text, scope) {
  const pid = scope === 'global' ? '_global' : scope === 'proj' ? S.pid : scope;
  return postJSON('/api/reply', { id: pid }, { qid, text })
    .then(() => (S.pid ? loadProject(S.pid) : loadLibrary()));
}

el('queue-panel').addEventListener('click', e => {
  const btn = e.target.closest('.queue-reply-send');
  if (!btn) return;
  const input = btn.closest('.queue-reply').querySelector('.queue-reply-input');
  const text = input.value.trim();
  if (text) sendReply(+btn.dataset.qid, text, btn.dataset.scope);
});
```

4i. Substituir `renderBudget`:

```js
function renderBudget() {
  let usd, teto;
  if (S.proj) { usd = (S.proj.custos || {}).usd || 0; teto = S.proj.teto_projeto || 0; }
  else {
    const b = S.budget || {};
    usd = (b.gasto_mes || {}).usd || 0; teto = (b.budget || {}).teto_mensal_usd || 0;
  }
  const pct = teto ? Math.min(100, usd / teto * 100) : 0;
  el('budget-badge').className = 'budget' + (pct >= 80 ? ' warn' : '');
  el('budget-bar').style.width = `${pct}%`;
  el('budget-label').textContent = `${fmtUSD(usd)} / ${fmtUSD(teto)}`;
}
```

4j. Em `openBudgetModal`, tornar as linhas do projeto condicionais (na biblioteca `S.proj` é null). Substituir as duas linhas de template
`<div>Projeto atual: ...</div>` e `<label>Teto deste projeto ...</label>` por:

```js
      ${S.proj ? `<div>Projeto atual: <b>${fmtUSD((S.proj.custos || {}).usd)}</b> / ${fmtUSD(S.proj.teto_projeto)}</div>` : ''}
```
e
```js
      ${S.proj ? `<label>Teto deste projeto (US$) <input type="number" min="0" step="0.5" id="b-este" value="${S.proj.teto_projeto ?? ''}"></label>` : ''}
```
e trocar `const inicialEste = el('b-este').value;` por `const inicialEste = S.proj ? el('b-este').value : null;`, o bloco do teto próprio por:
```js
    if (S.proj) {
      const este = el('b-este').value;
      if (este !== inicialEste)   // só fixa/remove o teto próprio se o campo mudou
        body.tetos_projeto = { [S.pid]: este === '' ? null : +este };
    }
```
e `closeModal(); loadProject(S.pid);` por `closeModal(); if (S.pid) loadProject(S.pid); else getJSON('/api/budget').then(b => { S.budget = b; renderBudget(); });`.

4k. **Apagar** `openDocsModal` e a linha `el('btn-docs').addEventListener('click', openDocsModal);`. Adicionar:

```js
async function renderDocsTab() {
  const pid = S.pid;
  const docs = await getJSON('/api/docs', { id: pid });
  if (S.pid !== pid) return;
  const box = el('tab-docs');
  box.innerHTML = `<div class="docs-body">
      <div class="modal-formats-list">${docs.map(d =>
        `<div class="modal-formats-item" data-name="${escapeHtml(d.name)}">${escapeHtml(d.name)}</div>`).join('')
        || '<div class="modal-docs-empty">nenhum doc no projeto</div>'}</div>
      <div class="modal-docs-view" id="docs-view"></div>
    </div>`;
  const show = async name => {
    S.docsName = name;
    if (name.endsWith('.png')) {
      el('docs-view').innerHTML = '<img style="max-width:100%" src="' + api('/api/file', { id: pid, name }) + '">';
    } else {
      const d = await getJSON('/api/doc', { id: pid, name });
      el('docs-view').innerHTML = d.html;   // servidor já escapou tudo
    }
    box.querySelectorAll('.modal-formats-item').forEach(it =>
      it.classList.toggle('active', it.dataset.name === name));
  };
  box.querySelectorAll('.modal-formats-item').forEach(it =>
    it.addEventListener('click', () => show(it.dataset.name)));
  const ini = docs.find(d => d.name === S.docsName) || docs[0];
  if (ini) show(ini.name);
}

function renderCustosTab() {
  const c = S.proj.custos || { usd: 0, creditos: 0 };
  const q = S.quadro || { etapas: [], fora_da_receita: [] };
  const linhas = q.etapas.concat(q.fora_da_receita).filter(e => e.custo_usd > 0);
  const soma = linhas.reduce((s, e) => s + e.custo_usd, 0);
  const resto = Math.max(0, (c.usd || 0) - soma);
  const temResto = resto > 0.00005;
  el('tab-custos').innerHTML = `<div class="custos">
      <div class="custos-total">Projeto: <b class="mono">${fmtUSD(c.usd)}</b> / <span class="mono">${fmtUSD(S.proj.teto_projeto)}</span> · <span class="mono">${c.creditos || 0}</span> créditos</div>
      <table class="custos-tab"><thead><tr><th>etapa</th><th>US$</th></tr></thead><tbody>
        ${linhas.map(e => `<tr><td>${escapeHtml(e.rotulo)}</td><td class="mono">${fmtUSD(e.custo_usd)}</td></tr>`).join('')}
        ${temResto ? `<tr><td class="dim">fora de etapa</td><td class="mono">${fmtUSD(resto)}</td></tr>` : ''}
      </tbody></table>
      ${linhas.length || temResto ? '' : '<div class="dim">nenhum gasto ainda</div>'}
      <button id="custos-tetos">Editar tetos</button>
    </div>`;
  el('custos-tetos').onclick = openBudgetModal;
}
```

4l. Na última linha do arquivo, trocar `loadProjects();` por:

```js
window.addEventListener('DOMContentLoaded', route);   // depois de library.js e board.js
```

4m. `S.docsOpen` deixa de ser usado fora de `closeModal` — manter a linha em `closeModal` (inofensiva).

- [ ] **Step 5: Edit `ui/static/style.css`**

5a. Trocar o bloco `:root { ... }` por:

```css
:root {
  --bg: #0e0e10;
  --panel: #151518;
  --panel-2: #1b1b20;
  --border: #232328;
  --accent: #f0b24a;
  --ok: #5fd38a;
  --pending: #f0b24a;
  --fail: #e05252;
  --text: #e8e6e3;
  --text-dim: #77757d;
  --mono: 'JetBrains Mono', ui-monospace, monospace;
}
```

5b. Em `body`: trocar `font: 13px/1.4 system-ui, -apple-system, sans-serif;` por `font: 13px/1.45 Inter, system-ui, -apple-system, sans-serif;`. Em `button, select, textarea, input`: trocar `border-radius: 3px;` por `border-radius: 6px;`.

5c. Em `main`: trocar `grid-template-columns: minmax(220px, 280px) 1fr minmax(260px, 320px);` por `grid-template-columns: minmax(220px, 280px) 1fr;`.

5d. Em `#stage`: trocar a linha `width: min(...)` por
`width: min(100%, calc((100vh - 44px - 84px - 220px - 40px) * 16 / 9), 1100px);`

5e. Em `#activity-box`: `background: rgba(240, 178, 74, 0.07); border: 1px solid rgba(240, 178, 74, 0.25); border-radius: 8px;`.

5f. Em `#instruction-pane`: trocar `border-bottom: 1px solid var(--border);` por `border-top: 1px solid var(--border);` (agora fica no pé da coluna da fila).

5g. Acrescentar ao fim do arquivo:

```css
/* ---- shell Backlot ---- */
.mono { font-family: var(--mono); font-size: 12px; }
.dim { color: var(--text-dim); }

body[data-route="library"] .only-project,
body[data-route="project"] .only-library { display: none !important; }
body:not([data-route="project"][data-tab="edicao"]) { grid-template-rows: 44px 1fr; }
body:not([data-route="project"][data-tab="edicao"]) .only-edicao { display: none !important; }

header .brand { font-weight: 700; letter-spacing: .02em; }
header .back { color: var(--text); text-decoration: none; font-size: 18px; padding: 0 4px; }
header .proj-name { font-weight: 700; font-size: 14px; }

#library-view, #project-view { overflow: hidden; display: flex; flex-direction: column; min-height: 0; }

#stepper { display: flex; gap: 4px; padding: 10px 14px 6px; align-items: center; flex-shrink: 0; flex-wrap: wrap; }
#tabs { display: flex; gap: 2px; padding: 0 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
#tabs a { padding: 6px 12px; color: var(--text-dim); text-decoration: none; border-bottom: 2px solid transparent; cursor: pointer; }
#tabs a.on { color: var(--text); border-color: var(--accent); }
#tabs a.off { opacity: .35; pointer-events: none; }

.tab-pane { display: none; flex: 1 1 0; min-height: 0; overflow: auto; }
body[data-tab="board"] #tab-board,
body[data-tab="docs"] #tab-docs,
body[data-tab="custos"] #tab-custos { display: block; }
body[data-tab="edicao"] #tab-edicao { display: grid; grid-template-columns: 1fr minmax(260px, 320px); overflow: hidden; }

#tab-board, #tab-custos { padding: 12px 14px; }
.docs-body { display: grid; grid-template-columns: 220px 1fr; height: 100%; }
.docs-body .modal-formats-list { border-right: 1px solid var(--border); overflow: auto; }
.docs-body .modal-docs-view { padding: 12px 18px; overflow: auto; }

.custos { display: grid; gap: 12px; max-width: 560px; }
.custos-tab { border-collapse: collapse; width: 100%; }
.custos-tab th, .custos-tab td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.custos-tab th { color: var(--text-dim); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.custos button { justify-self: start; }
```

- [ ] **Step 6: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS (smoke incluso; `test_rota_projeto_abas`, `test_aba_lembrada_e_edicao_desabilitada`, `test_hash_vazio_vai_para_biblioteca`). Abrir também `python ui/server.py` e conferir manualmente `http://127.0.0.1:8765/#/p/<um projeto real>/edicao`: player + timeline + cortes funcionando, instrução no pé da fila.

- [ ] **Step 7: Commit**

```bash
git add ui/static ui/test_ui_smoke.py
git commit -m "feat(ui): shell SPA com rotas por hash, abas Board/Edição/Docs/Custos e tema Estúdio escuro"
```

---

### Task 6: Biblioteca (`library.js`)

**Files:**
- Modify: `ui/static/library.js` (substitui o stub)
- Modify: `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `GET /api/library` (Task 3), `GET /api/capa` (Task 4), `GET /api/global-queue`, `GET /api/activity`, `GET /api/budget`; globais `S`, `el`, `getJSON`, `escapeHtml`, `fmtUSD`, `STATUS_LABEL`, `renderQueue`, `renderBudget` (Task 5).
- Produces: `S.lib = {items, formato, soEsperando, busca, key}`, `startLibrary()`, `stopLibrary()`, `loadLibrary()`, `renderLibrary()`, `sigla(formato)`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def test_biblioteca_card_abre_projeto(page, ui_url):
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card")
    assert page.locator(".lib-card").count() == 2
    card = page.locator(".lib-card", has_text="edit-fake")
    assert card.locator(".lib-dots i").count() == 3
    assert "cortes" in card.locator(".lib-atual").inner_text()
    card.click()
    page.wait_for_function("location.hash.startsWith('#/p/edit-fake/')")
    page.wait_for_function("document.body.dataset.route === 'project'")
    page.click("#btn-back")
    page.wait_for_function("document.body.dataset.route === 'library'")


def test_biblioteca_filtros(page, ui_url):
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card")
    page.fill("#lib-busca", "raw")
    page.wait_for_function("document.querySelectorAll('.lib-card').length === 1")
    page.fill("#lib-busca", "")
    page.click(".lib-chip[data-formato=teste]")
    page.wait_for_function("document.querySelectorAll('.lib-card').length === 1")
    assert "edit-fake" in page.locator(".lib-card").inner_text()


def test_biblioteca_projeto_aninhado(page, ui_url, fake_root):
    aninhado = fake_root / "edit" / "shorts" / "marca" / "proj-x" / "ui"
    aninhado.mkdir(parents=True)
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card >> text=marca/proj-x")
    page.click(".lib-card >> text=marca/proj-x")
    page.wait_for_function("document.body.dataset.route === 'project'")
    assert "edit%2Fshorts%2Fmarca%2Fproj-x" in page.evaluate("location.hash")
    assert page.locator("#proj-name").inner_text() == "marca/proj-x"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_ui_smoke.py -q -k biblioteca`
Expected: FAIL (timeout esperando `.lib-card`).

- [ ] **Step 3: Implement `ui/static/library.js`**

```js
// Biblioteca (#/): grade de projetos, filtros, poll de 5s enquanto visível.
S.lib = { items: [], formato: null, soEsperando: false, busca: '', key: null };
let libTimer = null;

const SIGLA = { 'padrao-youtube-longo': 'YT', 'padrao-youtube-shorts': 'SH', 'padrao-ads': 'AD',
  pauta: 'PA', referencia: 'RF', thumbnail: 'TH' };
const sigla = f => SIGLA[f] || (f || '?').slice(0, 2).toUpperCase();

function startLibrary() {
  S.lib.key = null;   // força redesenho ao voltar
  loadLibrary();
  if (!libTimer) libTimer = setInterval(loadLibrary, 5000);
  getJSON('/api/budget').then(b => { S.budget = b; if (!S.proj) renderBudget(); }).catch(() => {});
}

function stopLibrary() {
  clearInterval(libTimer);
  libTimer = null;
}

async function loadLibrary() {
  try {
    const [items, gq, act] = await Promise.all([
      getJSON('/api/library'), getJSON('/api/global-queue'), getJSON('/api/activity')]);
    if (document.body.dataset.route !== 'library') return;
    S.lib.items = items; S.globalQueue = gq; S.activity = act;
    renderLibrary();
    renderQueue();
  } catch (e) {
    console.warn('biblioteca falhou', e);
  }
}

function libCard(p) {
  const href = '#/p/' + encodeURIComponent(p.id);
  const v = encodeURIComponent(p.atividade || '');
  const capa = `/api/capa?id=${encodeURIComponent(p.id)}&v=${v}`;
  const dots = p.etapas.map(e =>
    `<i class="st-${e.status}" title="${escapeHtml(e.rotulo)} · ${STATUS_LABEL[e.status] || e.status}"></i>`).join('');
  const atual = p.atual ? `${escapeHtml(p.atual.rotulo)} · ${STATUS_LABEL[p.atual.status] || p.atual.status}`
    : !p.etapas.length ? 'sem etapas' : p.sem_historico ? 'sem histórico' : 'parado';
  return `<a class="lib-card" href="${href}">
      <div class="lib-capa"><span class="lib-sigla">${sigla(p.formato)}</span>
        <img src="${capa}" alt="" loading="lazy" onerror="this.remove()"></div>
      <div class="lib-info">
        <div class="lib-nome">${escapeHtml(p.name)}</div>
        <div class="lib-meta"><span class="tag">${escapeHtml(p.formato || 'sem formato')}</span>
          ${p.pendencias ? `<span class="tag espera">❓ ${p.pendencias}</span>` : ''}
          <span class="spacer"></span><span class="mono dim">${fmtUSD(p.custo_usd)}</span></div>
        <div class="lib-dots">${dots}</div>
        <div class="lib-atual dim">${atual}</div>
      </div>
    </a>`;
}

function renderLibrary() {
  const L = S.lib;
  const online = L.items.some(p => p.claude_online);
  el('claude-status').className = online ? 'online' : 'offline';
  el('claude-status').textContent = online ? 'Claude escutando' : 'Claude offline';
  const formatos = [...new Set(L.items.map(p => p.formato).filter(Boolean))].sort();
  const busca = L.busca.toLowerCase();
  const vis = L.items.filter(p => (!L.formato || p.formato === L.formato)
    && (!L.soEsperando || p.pendencias > 0)
    && (!busca || p.name.toLowerCase().includes(busca)));
  const key = JSON.stringify([formatos, L.formato, L.soEsperando, vis]);
  if (key === L.key) return;   // nada mudou: não redesenha (sem piscar capa)
  L.key = key;
  el('lib-chips').innerHTML =
    `<button class="lib-chip${!L.formato ? ' on' : ''}" data-formato="">todos</button>` +
    formatos.map(f => `<button class="lib-chip${L.formato === f ? ' on' : ''}" data-formato="${escapeHtml(f)}">${escapeHtml(f)}</button>`).join('') +
    `<button class="lib-chip espera${L.soEsperando ? ' on' : ''}" data-esperando="1">❓ esperando você</button>`;
  el('lib-grid').innerHTML = vis.length ? vis.map(libCard).join('')
    : '<div class="lib-vazio dim">nenhum projeto</div>';
}

el('lib-chips').addEventListener('click', e => {
  const b = e.target.closest('.lib-chip');
  if (!b) return;
  if (b.dataset.esperando) S.lib.soEsperando = !S.lib.soEsperando;
  else S.lib.formato = b.dataset.formato || null;
  renderLibrary();
});

el('lib-busca').addEventListener('input', e => {
  S.lib.busca = e.target.value.trim();
  renderLibrary();
});
```

- [ ] **Step 4: CSS** (append to `ui/static/style.css`)

```css
/* ---- biblioteca ---- */
#lib-filters { display: flex; gap: 10px; align-items: center; padding: 12px 16px 4px; flex-wrap: wrap; flex-shrink: 0; }
#lib-chips { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
#lib-busca { width: 220px; padding: 5px 10px; border-radius: 99px; }
.lib-chip { border-radius: 99px; padding: 3px 11px; font-size: 12px; color: var(--text-dim); background: var(--panel); }
.lib-chip.on { color: var(--bg); background: var(--accent); border-color: var(--accent); }
#lib-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; padding: 12px 16px 24px; overflow: auto; align-content: start; }
.lib-card { display: block; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; color: var(--text); text-decoration: none; transition: border-color .15s; }
.lib-card:hover { border-color: var(--accent); }
.lib-capa { position: relative; aspect-ratio: 16 / 9; background: var(--panel-2); display: flex; align-items: center; justify-content: center; }
.lib-capa img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.lib-sigla { font: 700 22px var(--mono); color: var(--text-dim); letter-spacing: .08em; }
.lib-info { padding: 10px 12px 12px; display: grid; gap: 6px; }
.lib-nome { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lib-meta { display: flex; gap: 6px; align-items: center; }
.lib-meta .spacer { flex: 1; }
.tag { background: var(--panel-2); color: var(--text-dim); border-radius: 99px; padding: 1px 8px; font-size: 11px; }
.tag.espera { background: rgba(240, 178, 74, .15); color: var(--accent); }
.lib-dots { display: flex; gap: 4px; }
.lib-dots i { width: 8px; height: 8px; border-radius: 50%; background: #2a2a30; }
.lib-dots i.st-fim { background: var(--ok); }
.lib-dots i.st-andamento { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
.lib-dots i.st-espera { background: transparent; box-shadow: inset 0 0 0 2px var(--accent); }
.lib-dots i.st-falha { background: var(--fail); }
.lib-dots i.st-pulada { background: #2a2a30; opacity: .4; }
.lib-atual { font-size: 12px; }
.lib-vazio { padding: 40px; }
```

- [ ] **Step 5: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS. Conferir manualmente `http://127.0.0.1:8765/#/` com os projetos reais (capas, filtros, fila com `[nome]`, selo de orçamento do mês).

- [ ] **Step 6: Commit**

```bash
git add ui/static/library.js ui/static/style.css ui/test_ui_smoke.py
git commit -m "feat(ui): biblioteca de projetos com capa, etapas, pendências e filtros"
```

---

### Task 7: Stepper + Board (`board.js`)

**Files:**
- Modify: `ui/static/board.js` (substitui o stub)
- Modify: `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `S.quadro` (shape de `eventos.quadro`, Task 1), `S.proj.state`, `S.proj.queue`; globais `el`, `escapeHtml`, `fmtUSD`, `fmtMSS`, `STATUS_LABEL`, `goTab`, `sendReply` (Task 5).
- Produces: `renderStepper()`, `renderBoard()`, `infoAudio(st)`, `infoBroll(st)`, `infoClips(st)`, `infoRef(st)` (cada uma → string, `''` se nada), `S.scrollTo`, `S.boardScrolled`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def test_stepper_e_board(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#stepper .step")
    steps = page.locator("#stepper .step")
    assert steps.count() == 3
    assert "st-fim" in steps.nth(0).get_attribute("class")
    assert "st-andamento" in steps.nth(1).get_attribute("class")
    assert page.locator("#card-cortes").is_visible()
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    steps.nth(2).click()
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert page.locator("#card-render").is_visible()


def test_board_espera_mostra_pedido(page, ui_url, fake_root):
    ui = fake_root / "edit-fake" / "ui"
    with (ui / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    (ui / "queue.json").write_text(json.dumps([
        {"id": 7, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "aprova os cortes?"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-pergunta")
    assert "aprova os cortes?" in page.locator("#card-cortes").inner_text()
    page.fill("#card-cortes .board-reply-input", "ok")
    page.click("#card-cortes .board-reply-send")
    page.wait_for_function("!document.querySelector('#card-cortes .board-reply-input')")
    q = json.loads((ui / "queue.json").read_text(encoding="utf-8"))
    assert q[0]["reply"] == "ok" and q[0]["status"] == "pending"


def test_board_reply_sobrevive_reload(page, ui_url, fake_root):
    ui = fake_root / "edit-fake" / "ui"
    with (ui / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    (ui / "queue.json").write_text(json.dumps([
        {"id": 7, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "?"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-reply-input")
    page.fill("#card-cortes .board-reply-input", "digitando")
    (ui / "state.json").write_text(json.dumps({"formato": "teste", "x": 1}), encoding="utf-8")   # dispara SSE
    page.wait_for_timeout(2500)
    assert page.locator("#card-cortes .board-reply-input").input_value() == "digitando"


def test_board_info_no_card_da_etapa(page, ui_url, fake_root):
    (fake_root / "Formatos" / "teste.md").write_text(
        "---\netapas: transcricao, audio, cortes\n---\n", encoding="utf-8")
    (fake_root / "edit-fake" / "ui" / "state.json").write_text(json.dumps(
        {"formato": "teste", "audio": {"denoise": "forte"}, "clips": {"aprovados": [1, 2]}}), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-audio")
    assert "denoise forte" in page.locator("#card-audio").inner_text()
    assert "2 aprovados" in page.locator("#card-outros").inner_text()   # sem etapa candidatos
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_ui_smoke.py -q -k "stepper or board"`
Expected: FAIL (timeout esperando `#stepper .step`).

- [ ] **Step 3: Implement `ui/static/board.js`**

```js
// Stepper + Board do projeto. Dados: S.quadro (eventos.quadro) + S.proj.

function infoAudio(st) {
  const a = st.audio;
  if (!a) return '';
  const partes = [];
  if (a.trilha) partes.push(`trilha ${a.trilha} · ${a.nivel_db ?? -18} dB · duck ${a.duck_db ?? -8} dB`);
  if (a.denoise) partes.push(`denoise ${a.denoise}`);
  if (a.ruido_db != null) partes.push(`ruído ${Number(a.ruido_db).toFixed(0)} dB`);
  return partes.length ? 'áudio: ' + partes.join(' · ') : '';
}

const cnt = v => Array.isArray(v) ? v.length : (v ?? 0);

function infoBroll(st) {
  const b = st.broll;
  if (!b) return '';
  const fontes = Object.entries(b.fontes || {}).map(([k, v]) => `${k} ${v}`).join(', ');
  return `b-roll: ${cnt(b.aprovados)}/${cnt(b.momentos)} aprovados${fontes ? ' · ' + fontes : ''}`;
}

function infoClips(st) {
  const c = st.clips;
  if (!c) return '';
  return `clips: ${cnt(c.aprovados)} aprovados · ${cnt(c.renderizados)} renderizados · ${cnt(c.publora_drafts)} drafts`;
}

function infoRef(st) {
  const r = st.ref;
  if (!r) return '';
  return `ref: ${cnt(r.conceitos)} conceitos` + (r.escolhido ? ` · escolhido ${r.escolhido}` : '') +
    (r.produzidos && r.produzidos.length ? ` · produzidos ${r.produzidos.join(', ')}` : '');
}

const INFO_SLOT = [['audio', infoAudio], ['visual', infoBroll], ['candidatos', infoClips], ['referencia', infoRef]];

function renderStepper() {
  const q = S.quadro;
  const box = el('stepper');
  if (!q || !q.etapas.length) { box.innerHTML = '<span class="step-tag">sem etapas</span>'; return; }
  box.innerHTML = q.etapas.map(e =>
    `<button class="step st-${e.status}" data-etapa="${escapeHtml(e.id)}" title="${STATUS_LABEL[e.status] || e.status}">` +
    `${e.status === 'espera' ? '❓ ' : ''}${escapeHtml(e.rotulo)}</button>`).join('') +
    (q.sem_historico ? '<span class="step-tag">sem histórico</span>' : '');
}

el('stepper').addEventListener('click', e => {
  const b = e.target.closest('.step');
  if (!b) return;
  S.scrollTo = b.dataset.etapa;
  goTab('board');
});

const fmtHora = ts => ts ? new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';
const fmtDur = (a, b) => a ? fmtMSS(((b ? new Date(b) : new Date()) - new Date(a)) / 1000) : '';

function boardCard(e, infos, pedido, fora) {
  const tempo = e.inicio ? `${fmtHora(e.inicio)}${e.fim ? '–' + fmtHora(e.fim) : ''} · ${fmtDur(e.inicio, e.fim)}`
    : e.fim ? fmtHora(e.fim) : '';
  const linhas = (infos[e.id] || []).map(t => `<div class="info-line">${escapeHtml(t)}</div>`).join('');
  const perg = pedido ? `<div class="board-pergunta">
      <div class="board-q">${escapeHtml(pedido.resultado || pedido.text || '')}</div>
      <textarea class="board-reply-input" data-qid="${pedido.id}" rows="2" placeholder="responder... (Enter envia)"></textarea>
      <button class="board-reply-send" data-qid="${pedido.id}">Enviar</button>
    </div>` : '';
  return `<div class="board-card st-${e.status}" id="card-${escapeHtml(e.id)}">
      <div class="bc-head"><span class="bc-rot">${escapeHtml(e.rotulo)}</span>
        <span class="bc-status">${STATUS_LABEL[e.status] || e.status}</span>
        ${fora ? '<span class="tag">fora da receita</span>' : ''}
        <span class="spacer"></span><span class="mono dim">${tempo}</span>
        <span class="mono">${e.custo_usd > 0 ? fmtUSD(e.custo_usd) : ''}</span></div>
      ${e.nota ? `<div class="bc-nota">${escapeHtml(e.nota)}</div>` : ''}
      ${linhas}${perg}
    </div>`;
}

function renderBoard() {
  const box = el('tab-board');
  const foco = document.activeElement;
  if (box.contains(foco) && foco.tagName === 'TEXTAREA') return;   // não apagar o que o usuário digita
  const q = S.quadro || { etapas: [], fora_da_receita: [], atual: null };
  const st = (S.proj && S.proj.state) || {};
  const ids = new Set(q.etapas.map(e => e.id));
  const infos = {}, outros = [];
  for (const [slot, fn] of INFO_SLOT) {
    const t = fn(st);
    if (!t) continue;
    if (ids.has(slot)) (infos[slot] = infos[slot] || []).push(t); else outros.push(t);
  }
  const pedido = ((S.proj && S.proj.queue) || [])
    .filter(e => e.status === 'waiting_reply').sort((a, b) => a.id - b.id)[0];
  const todas = q.etapas.concat(q.fora_da_receita);
  const atualEspera = todas.find(e => e.id === q.atual && e.status === 'espera');
  const alvo = (atualEspera || todas.find(e => e.status === 'espera') || {}).id;
  let html = q.etapas.map(e => boardCard(e, infos, e.id === alvo ? pedido : null, false)).join('');
  html += q.fora_da_receita.map(e => boardCard(e, infos, e.id === alvo ? pedido : null, true)).join('');
  if (outros.length) html += `<div class="board-card" id="card-outros"><div class="bc-head"><span class="bc-rot">outros</span></div>` +
    outros.map(t => `<div class="info-line">${escapeHtml(t)}</div>`).join('') + '</div>';
  box.innerHTML = html || '<div class="board-vazio dim">sem etapas — o formato deste projeto não declara etapas</div>';
  let alvoScroll = null;
  if (S.scrollTo) { alvoScroll = S.scrollTo; S.scrollTo = null; }
  else if (S.boardScrolled !== S.pid) { S.boardScrolled = S.pid; alvoScroll = q.atual; }
  const c = alvoScroll && document.getElementById('card-' + alvoScroll);
  if (c) c.scrollIntoView({ block: 'center' });
}

function boardReply(input) {
  const text = input.value.trim();
  if (!text) return;
  input.blur();   // libera a guarda de foco para o redesenho pós-envio
  sendReply(+input.dataset.qid, text, 'proj');
}

el('tab-board').addEventListener('click', e => {
  const b = e.target.closest('.board-reply-send');
  if (b) boardReply(b.closest('.board-pergunta').querySelector('.board-reply-input'));
});
el('tab-board').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.ctrlKey || !e.target.classList.contains('board-reply-input')) return;
  e.preventDefault();
  boardReply(e.target);
});
```

Observação: após `sendReply`, o pedido sai de `waiting_reply` (vira `pending`), então o redesenho do Board não mostra mais o campo — é o que o smoke `test_board_espera_mostra_pedido` verifica.

- [ ] **Step 4: CSS** (append to `ui/static/style.css`)

```css
/* ---- stepper + board ---- */
.step { flex: 1 1 0; min-width: 70px; padding: 5px 6px; font-size: 10px; letter-spacing: .05em; text-transform: uppercase;
  background: var(--panel-2); color: var(--text-dim); border: 1px solid transparent; border-radius: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step.st-fim { background: #16261c; color: var(--ok); }
.step.st-andamento { background: #2c2210; color: var(--accent); box-shadow: 0 0 0 1px rgba(240, 178, 74, .35), 0 0 12px rgba(240, 178, 74, .18); }
.step.st-espera { background: transparent; color: var(--accent); border-color: var(--accent); }
.step.st-falha { background: #2a1414; color: var(--fail); }
.step.st-pulada { text-decoration: line-through; opacity: .5; }
.step-tag { font-size: 11px; color: var(--text-dim); padding: 0 8px; }

.board-card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; display: grid; gap: 6px; }
.board-card.st-andamento { border-color: rgba(240, 178, 74, .45); }
.board-card.st-espera { border-color: var(--accent); }
.board-card.st-falha { border-color: rgba(224, 82, 82, .5); }
.board-card.st-pendente, .board-card.st-pulada { opacity: .6; }
.bc-head { display: flex; gap: 8px; align-items: baseline; }
.bc-head .spacer { flex: 1; }
.bc-rot { font-weight: 600; }
.bc-status { font-size: 11px; color: var(--text-dim); }
.board-card.st-fim .bc-status { color: var(--ok); }
.board-card.st-andamento .bc-status, .board-card.st-espera .bc-status { color: var(--accent); }
.board-card.st-falha .bc-status { color: var(--fail); }
.bc-nota { color: var(--text-dim); }
.board-pergunta { display: grid; gap: 6px; background: rgba(240, 178, 74, .06); border-radius: 6px; padding: 8px; }
.board-pergunta textarea { resize: vertical; padding: 6px; }
.board-pergunta button { justify-self: start; }
.board-vazio { padding: 30px 0; }
```

- [ ] **Step 5: Run tests**

Run: `cd ui && python -m pytest -q`
Expected: all PASS. Conferir manualmente: registrar eventos num projeto real
(`python ui/eventos.py etapa edit/<proj> cortes inicio`) e ver o stepper acender sem F5.

- [ ] **Step 6: Commit**

```bash
git add ui/static/board.js ui/static/style.css ui/test_ui_smoke.py
git commit -m "feat(ui): stepper e board de etapas com custo, nota, infos e resposta inline"
```
