# Video Editor UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Painel web local tipo Premiere (player + timeline + fila de instruções) que observa os artefatos do pipeline video-use e envia pedidos para o Claude da sessão do terminal.

**Architecture:** FastAPI (`ui/server.py`) serve uma página estática (JS puro, sem build) e uma API REST+SSE sobre os arquivos do pipeline (`edl.json`, transcripts, `zooms.json`, `master.srt`, `preview.mp4`). A UI só escreve em `ui/queue.json`, `ui/state.json` (por projeto) e `Formatos/*.md`. Claude escuta as filas por file-watch e executa FIFO.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pytest+httpx (testes), ffmpeg/ffprobe (waveform), HTML/CSS/JS puro com canvas para a timeline.

**Spec:** `docs/superpowers/specs/2026-09-01-video-editor-ui-design.md`

## Global Constraints

- Servidor escuta somente `127.0.0.1`, porta `8765`.
- UI NUNCA escreve `edl.json`/vídeos — apenas `ui/queue.json`, `ui/state.json`, `Formatos/*.md`.
- Escritas JSON são atômicas (tmp + `os.replace`).
- Nenhum framework/build no frontend; um `index.html`, um `app.js`, um `style.css`.
- IDs de projeto = caminho relativo POSIX a partir da raiz `video_editor/` (ex.: `edit-the-goat`, `edit/shorts/campeio`), sempre via query param `id`.
- Timeline usa tempo do BRUTO; player usa tempo de saída; mapeamento via ranges do EDL.
- Comandos de terminal com prefixo `rtk` (CLAUDE.md global do usuário).
- Todo commit neste repo: mensagens em pt-BR, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Schemas reais (lidos do projeto `edit-the-goat`)

- `edl.json`: `{version, sources: {MAIN: "F:\\...\\bruto\\arquivo.mkv"}, ranges: [{source, start, end}], grade: "<ffmpeg filter>", total_duration_s, overlays: [{file, mode, start_in_output, duration}]}` — `start/end` em segundos no tempo do bruto; `start_in_output` no tempo de saída.
- `transcripts/<stem>.json` (Scribe): `{text, words: [{text, start, end, type: "word"|"spacing", speaker_id}], audio_duration_secs}`.
- `zooms.json`: array de floats, paralelo a `ranges` (fator de zoom por segmento; `1.0` = sem zoom).
- `master.srt`: SRT padrão, tempos no eixo de SAÍDA.

## File Structure

- `ui/requirements.txt` — fastapi, uvicorn, pytest, httpx
- `ui/pipeline.py` — leitura dos artefatos: descoberta de projetos, EDL, frases, SRT, estado, fila, mapeamento de tempo. Sem FastAPI — puro, testável.
- `ui/waveform.py` — picos de áudio via ffmpeg + cache
- `ui/server.py` — FastAPI: rotas REST, vídeo com range, SSE, static
- `ui/static/index.html`, `ui/static/style.css`, `ui/static/app.js` — frontend
- `ui/test_pipeline.py`, `ui/test_server.py` — testes
- `CLAUDE.md` (raiz) — protocolo da fila para sessões Claude

---

### Task 1: Núcleo de leitura do pipeline (`ui/pipeline.py`)

**Files:**
- Create: `ui/requirements.txt`, `ui/pipeline.py`
- Test: `ui/test_pipeline.py`

**Interfaces:**
- Produces:
  - `ROOT: Path` — raiz do projeto (pai de `ui/`)
  - `find_projects(root: Path) -> list[dict]` — `[{id, name, has_preview, has_final}]`
  - `project_dir(root: Path, pid: str) -> Path` — valida e resolve id (403 se escapar da raiz)
  - `load_project(root: Path, pid: str) -> dict` — payload completo (ver Step 3)
  - `phrases_from_transcript(tr: dict, gap: float = 0.5) -> list[dict]` — `[{start, end, text}]`
  - `parse_srt(text: str) -> list[dict]` — `[{start, end, text}]` (segundos, eixo de saída)
  - `atomic_write_json(path: Path, obj) -> None`
  - `read_json(path: Path, default) -> Any`
  - `claude_online(proj: Path) -> bool` — heartbeat < 10s

- [ ] **Step 1: requirements**

`ui/requirements.txt`:
```
fastapi
uvicorn
pytest
httpx
```
Instalar: `rtk pip install -r ui/requirements.txt`

- [ ] **Step 2: Teste falhando — fixture de projeto fake + descoberta/frases/SRT**

`ui/test_pipeline.py`:
```python
import json
from pathlib import Path
import pytest
import pipeline


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    proj = tmp_path / "edit-fake"
    proj.mkdir()
    edl = {
        "version": 1,
        "sources": {"MAIN": str(tmp_path / "bruto" / "fake.mkv")},
        "ranges": [
            {"source": "MAIN", "start": 1.0, "end": 3.0},
            {"source": "MAIN", "start": 5.0, "end": 8.0},
        ],
        "grade": "", "total_duration_s": 10.0, "overlays": [],
    }
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    (proj / "zooms.json").write_text("[1.0, 1.05]", encoding="utf-8")
    tdir = proj / "transcripts"
    tdir.mkdir()
    words = [
        {"text": "Oi", "start": 1.0, "end": 1.2, "type": "word"},
        {"text": " ", "start": 1.2, "end": 1.25, "type": "spacing"},
        {"text": "gente", "start": 1.25, "end": 1.6, "type": "word"},
        # gap de 0.9s => quebra de frase
        {"text": "Agora", "start": 2.5, "end": 2.9, "type": "word"},
    ]
    (tdir / "fake.json").write_text(
        json.dumps({"text": "Oi gente Agora", "words": words,
                    "audio_duration_secs": 10.0}), encoding="utf-8")
    (proj / "master.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nOi gente\n\n"
        "2\n00:00:02,000 --> 00:00:04,500\nAgora\n", encoding="utf-8")
    (proj / "preview.mp4").write_bytes(b"\x00" * 16)
    (tmp_path / "bruto").mkdir()
    (tmp_path / "Formatos").mkdir()
    (tmp_path / "Formatos" / "padrao-youtube.md").write_text("# receita",
                                                             encoding="utf-8")
    return tmp_path


def test_find_projects(fake_root):
    projs = pipeline.find_projects(fake_root)
    assert projs == [{"id": "edit-fake", "name": "edit-fake",
                      "has_preview": True, "has_final": False}]


def test_project_dir_rejects_escape(fake_root):
    with pytest.raises(ValueError):
        pipeline.project_dir(fake_root, "../fora")


def test_phrases_split_on_gap(fake_root):
    tr = json.loads((fake_root / "edit-fake" / "transcripts" /
                     "fake.json").read_text(encoding="utf-8"))
    ph = pipeline.phrases_from_transcript(tr)
    assert [p["text"] for p in ph] == ["Oi gente", "Agora"]
    assert ph[0]["start"] == 1.0 and ph[0]["end"] == 1.6


def test_parse_srt(fake_root):
    srt = (fake_root / "edit-fake" / "master.srt").read_text(encoding="utf-8")
    subs = pipeline.parse_srt(srt)
    assert subs[1] == {"start": 2.0, "end": 4.5, "text": "Agora"}


def test_load_project_payload(fake_root):
    p = pipeline.load_project(fake_root, "edit-fake")
    assert len(p["edl"]["ranges"]) == 2
    assert p["zooms"] == [1.0, 1.05]
    assert p["phrases"][0]["text"] == "Oi gente"
    assert p["state"] == {}
    assert p["queue"] == []
    assert p["claude_online"] is False
    assert p["source_duration"] == 10.0
```

- [ ] **Step 2b: Rodar e ver falhar**

Run: `cd ui && rtk test "pytest test_pipeline.py -q"`
Expected: FAIL — `ModuleNotFoundError: pipeline` / funções ausentes.

- [ ] **Step 3: Implementar `ui/pipeline.py`**

```python
"""Leitura dos artefatos do pipeline video-use. Sem dependência de FastAPI."""
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {"video-use", "ui", "bruto", "Export", "assets", "docs",
             "Formatos", ".git"}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def find_projects(root: Path) -> list[dict]:
    out = []
    for depth in ("*/edl.json", "*/*/edl.json", "*/*/*/edl.json"):
        for edl in sorted(root.glob(depth)):
            rel = edl.parent.relative_to(root).as_posix()
            if rel.split("/")[0] in SKIP_DIRS:
                continue
            out.append({
                "id": rel,
                "name": edl.parent.name,
                "has_preview": (edl.parent / "preview.mp4").exists(),
                "has_final": (edl.parent / "final.mp4").exists(),
            })
    return out


def project_dir(root: Path, pid: str) -> Path:
    p = (root / pid).resolve()
    if root.resolve() not in p.parents:
        raise ValueError(f"id inválido: {pid}")
    return p


def phrases_from_transcript(tr: dict, gap: float = 0.5) -> list[dict]:
    words = [w for w in tr.get("words", []) if w.get("type") == "word"]
    phrases, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= gap:
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return [{"start": ph[0]["start"], "end": ph[-1]["end"],
             "text": " ".join(w["text"].strip() for w in ph)} for ph in phrases]


_SRT_TIME = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[dict]:
    subs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                subs.append({
                    "start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                    "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                    "text": "\n".join(lines[i + 1:]).strip(),
                })
                break
    return subs


def claude_online(proj: Path) -> bool:
    hb = proj / "ui" / "heartbeat"
    try:
        return time.time() - hb.stat().st_mtime < 10
    except OSError:
        return False


def _load_transcript(proj: Path, edl: dict) -> dict:
    tdir = proj / "transcripts"
    if not tdir.is_dir():
        return {}
    main = edl.get("sources", {}).get("MAIN", "")
    stem = Path(main).stem if main else ""
    cand = tdir / f"{stem}.json"
    files = [cand] if cand.exists() else sorted(tdir.glob("*.json"))
    return read_json(files[0], {}) if files else {}


def load_project(root: Path, pid: str) -> dict:
    proj = project_dir(root, pid)
    edl = read_json(proj / "edl.json", {"ranges": [], "sources": {},
                                       "overlays": []})
    tr = _load_transcript(proj, edl)
    srt_path = proj / "master.srt"
    srt = parse_srt(srt_path.read_text(encoding="utf-8")) \
        if srt_path.exists() else []
    ranges = edl.get("ranges", [])
    source_duration = max(
        [tr.get("audio_duration_secs", 0.0)] +
        [r["end"] for r in ranges] or [0.0])
    return {
        "id": pid,
        "edl": edl,
        "zooms": read_json(proj / "zooms.json", []),
        "phrases": phrases_from_transcript(tr) if tr else [],
        "srt": srt,
        "state": read_json(proj / "ui" / "state.json", {}),
        "queue": read_json(proj / "ui" / "queue.json", []),
        "claude_online": claude_online(proj),
        "source_duration": source_duration,
        "has_preview": (proj / "preview.mp4").exists(),
        "has_final": (proj / "final.mp4").exists(),
    }
```

- [ ] **Step 4: Rodar testes**

Run: `cd ui && rtk test "pytest test_pipeline.py -q"`
Expected: PASS (6 testes).

- [ ] **Step 5: Commit**

```bash
rtk git add ui/requirements.txt ui/pipeline.py ui/test_pipeline.py
rtk git commit -m "feat(ui): núcleo de leitura do pipeline"
```

---

### Task 2: Waveform (`ui/waveform.py`)

**Files:**
- Create: `ui/waveform.py`
- Test: `ui/test_pipeline.py` (append)

**Interfaces:**
- Consumes: `pipeline.atomic_write_json`, `pipeline.read_json`
- Produces: `get_waveform(proj: Path, source: str, n: int = 4000) -> dict` — `{"duration": float, "peaks": [float 0..1]}`; cache em `<proj>/ui/cache/waveform.json` invalidado por mtime+tamanho do source.

- [ ] **Step 1: Teste falhando (gera WAV sintético com ffmpeg)**

Append em `ui/test_pipeline.py`:
```python
import shutil
import subprocess
import waveform


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_waveform_peaks(tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2", str(src)], check=True)
    proj = tmp_path / "p"
    proj.mkdir()
    wf = waveform.get_waveform(proj, str(src), n=100)
    assert abs(wf["duration"] - 2.0) < 0.1
    assert len(wf["peaks"]) == 100
    assert max(wf["peaks"]) > 0.5
    # segunda chamada vem do cache (arquivo existe)
    assert (proj / "ui" / "cache" / "waveform.json").exists()
```

Run: `cd ui && rtk test "pytest test_pipeline.py -q"` → FAIL (`ModuleNotFoundError: waveform`).

- [ ] **Step 2: Implementar `ui/waveform.py`**

```python
"""Picos de áudio para a timeline. ffmpeg -> s16le mono 8kHz -> buckets."""
import subprocess
from array import array
from pathlib import Path

from pipeline import atomic_write_json, read_json

RATE = 8000


def get_waveform(proj: Path, source: str, n: int = 4000) -> dict:
    cache = proj / "ui" / "cache" / "waveform.json"
    src = Path(source)
    try:
        key = f"{src.stat().st_mtime_ns}:{src.stat().st_size}:{n}"
    except OSError:
        return {"duration": 0.0, "peaks": []}
    cached = read_json(cache, {})
    if cached.get("key") == key:
        return cached
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0",
         "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    duration = len(samples) / RATE
    peaks = []
    if samples:
        step = max(1, len(samples) // n)
        for i in range(0, len(samples), step):
            chunk = samples[i:i + step]
            peaks.append(max(abs(s) for s in chunk) / 32768)
        peaks = peaks[:n]
    out = {"key": key, "duration": duration, "peaks": peaks}
    atomic_write_json(cache, out)
    return out
```

- [ ] **Step 3: Rodar testes** — `cd ui && rtk test "pytest test_pipeline.py -q"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add ui/waveform.py ui/test_pipeline.py
rtk git commit -m "feat(ui): waveform com cache"
```

---

### Task 3: Servidor FastAPI — leitura (`ui/server.py`)

**Files:**
- Create: `ui/server.py`
- Test: `ui/test_server.py`

**Interfaces:**
- Consumes: tudo de `pipeline.py` e `waveform.py`
- Produces (rotas GET):
  - `GET /api/projects`, `GET /api/project?id=`, `GET /api/waveform?id=`
  - `GET /api/video?id=&kind=preview|final` — `FileResponse` (range nativo)
  - `GET /api/formats` — `[{name, content}]`; `GET /api/brutos` — `[nome, ...]`
  - `GET /` — `static/index.html`
  - Módulo expõe `app` (FastAPI) e `ROOT` sobrescrevível em teste via `app.state.root`

- [ ] **Step 1: Teste falhando**

`ui/test_server.py`:
```python
import pytest
from fastapi.testclient import TestClient

import server
from test_pipeline import fake_root  # fixture reexport


@pytest.fixture
def client(fake_root):
    server.app.state.root = fake_root
    return TestClient(server.app)


def test_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "edit-fake"


def test_project_payload(client):
    r = client.get("/api/project", params={"id": "edit-fake"})
    assert r.status_code == 200
    assert len(r.json()["edl"]["ranges"]) == 2


def test_project_bad_id(client):
    assert client.get("/api/project",
                      params={"id": "../x"}).status_code == 400


def test_video_range(client):
    r = client.get("/api/video", params={"id": "edit-fake",
                                         "kind": "preview"},
                   headers={"Range": "bytes=0-7"})
    assert r.status_code == 206
    assert len(r.content) == 8


def test_video_missing(client):
    assert client.get("/api/video", params={"id": "edit-fake",
                                            "kind": "final"}).status_code == 404


def test_formats_and_brutos(client):
    fm = client.get("/api/formats").json()
    assert fm[0]["name"] == "padrao-youtube"
    assert client.get("/api/brutos").json() == []
```

Run: `cd ui && rtk test "pytest test_server.py -q"` → FAIL.

- [ ] **Step 2: Implementar `ui/server.py` (parte leitura)**

```python
"""Servidor da UI do video_editor. Roda: python ui/server.py"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import pipeline
import waveform as wf

app = FastAPI()
app.state.root = pipeline.ROOT
STATIC = Path(__file__).parent / "static"


def _root(request: Request) -> Path:
    return request.app.state.root


def _proj(request: Request, pid: str) -> Path:
    try:
        return pipeline.project_dir(_root(request), pid)
    except ValueError:
        raise HTTPException(400, "id inválido")


@app.get("/api/projects")
def projects(request: Request):
    return pipeline.find_projects(_root(request))


@app.get("/api/project")
def project(request: Request, id: str):
    _proj(request, id)
    return pipeline.load_project(_root(request), id)


@app.get("/api/waveform")
def waveform_route(request: Request, id: str):
    proj = _proj(request, id)
    edl = pipeline.read_json(proj / "edl.json", {})
    src = edl.get("sources", {}).get("MAIN")
    if not src:
        return {"duration": 0.0, "peaks": []}
    return wf.get_waveform(proj, src)


@app.get("/api/video")
def video(request: Request, id: str, kind: str = "preview"):
    if kind not in ("preview", "final"):
        raise HTTPException(400, "kind inválido")
    path = _proj(request, id) / f"{kind}.mp4"
    if not path.exists():
        raise HTTPException(404, f"sem {kind}.mp4")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/formats")
def formats(request: Request):
    fdir = _root(request) / "Formatos"
    return [{"name": p.stem, "content": p.read_text(encoding="utf-8")}
            for p in sorted(fdir.glob("*.md"))]


@app.get("/api/brutos")
def brutos(request: Request):
    bdir = _root(request) / "bruto"
    exts = {".mp4", ".mkv", ".mov", ".webm"}
    return sorted(p.name for p in bdir.glob("*")
                  if p.suffix.lower() in exts) if bdir.is_dir() else []


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
```

Criar `ui/static/index.html` placeholder mínimo para o mount não falhar:
```html
<title>video_editor</title>
```

Nota: `TestClient` do FastAPI emula range requests via Starlette — `FileResponse` responde 206 nativamente.

- [ ] **Step 3: Rodar testes** — `cd ui && rtk test "pytest -q"` → PASS (todos).

- [ ] **Step 4: Commit**

```bash
rtk git add ui/server.py ui/test_server.py ui/static/index.html
rtk git commit -m "feat(ui): API de leitura + vídeo com range"
```

---

### Task 4: Servidor — escrita (fila, estado, formatos, novo projeto)

**Files:**
- Modify: `ui/server.py`
- Modify: `.gitignore` (adicionar `.ui-runtime/`)
- Test: `ui/test_server.py` (append)

**Interfaces:**
- Produces:
  - `POST /api/queue?id=` body `{type, target?, text}` → entry criado `{id, ts, type, target, text, status: "pending", resultado: null, reply: null}`; `type` ∈ `instrucao|render|borda|veto`
  - `POST /api/reply?id=` body `{qid, text}` → seta `reply` e volta status para `pending` (Claude relê)
  - `POST /api/state?id=` body dict → shallow-merge em `ui/state.json`
  - `PUT /api/format?name=` body `{content}` → salva `Formatos/<name>.md` (basename only)
  - `POST /api/new-project` body `{bruto, formato, nome}` → entry `{type: "novo-projeto", ...}` em `<root>/.ui-runtime/queue.json` (fila global)
- Fila global: projeto pseudo `_global`; `GET /api/project?id=_global` não existe — UI lê via `GET /api/global-queue`.

- [ ] **Step 1: Testes falhando (append `ui/test_server.py`)**

```python
def test_queue_post_and_read(client):
    r = client.post("/api/queue", params={"id": "edit-fake"},
                    json={"type": "instrucao", "target": 1,
                          "text": "estica corte 1"})
    assert r.status_code == 200
    entry = r.json()
    assert entry["status"] == "pending" and entry["id"]
    q = client.get("/api/project", params={"id": "edit-fake"}).json()["queue"]
    assert q[0]["text"] == "estica corte 1"


def test_queue_rejects_bad_type(client):
    assert client.post("/api/queue", params={"id": "edit-fake"},
                       json={"type": "hack", "text": "x"}).status_code == 400


def test_reply(client):
    qid = client.post("/api/queue", params={"id": "edit-fake"},
                      json={"type": "render", "text": "preview"}).json()["id"]
    r = client.post("/api/reply", params={"id": "edit-fake"},
                    json={"qid": qid, "text": "sim, pode"})
    assert r.status_code == 200
    q = client.get("/api/project", params={"id": "edit-fake"}).json()["queue"]
    entry = next(e for e in q if e["id"] == qid)
    assert entry["reply"] == "sim, pode" and entry["status"] == "pending"


def test_state_merge(client):
    client.post("/api/state", params={"id": "edit-fake"},
                json={"formato": "padrao-youtube"})
    client.post("/api/state", params={"id": "edit-fake"},
                json={"aprovacoes": [0]})
    st = client.get("/api/project", params={"id": "edit-fake"}).json()["state"]
    assert st == {"formato": "padrao-youtube", "aprovacoes": [0]}


def test_format_save(client, fake_root):
    r = client.put("/api/format", params={"name": "padrao-youtube"},
                   json={"content": "# nova receita"})
    assert r.status_code == 200
    assert (fake_root / "Formatos" / "padrao-youtube.md").read_text(
        encoding="utf-8") == "# nova receita"


def test_format_name_sanitized(client):
    assert client.put("/api/format", params={"name": "../evil"},
                      json={"content": "x"}).status_code == 400


def test_new_project(client, fake_root):
    r = client.post("/api/new-project",
                    json={"bruto": "video.mkv", "formato": "padrao-youtube",
                          "nome": "meu-video"})
    assert r.status_code == 200
    gq = client.get("/api/global-queue").json()
    assert gq[0]["type"] == "novo-projeto"
    assert gq[0]["target"]["bruto"] == "video.mkv"
```

Run: `cd ui && rtk test "pytest test_server.py -q"` → FAIL.

- [ ] **Step 2: Implementar (append em `ui/server.py`, antes do `app.mount`)**

```python
import re
import time
from datetime import datetime, timezone

QUEUE_TYPES = {"instrucao", "render", "borda", "veto"}


def _append_queue(qpath, entry):
    queue = pipeline.read_json(qpath, [])
    queue.append(entry)
    pipeline.atomic_write_json(qpath, queue)
    return entry


def _make_entry(type_, target, text):
    return {"id": int(time.time() * 1000),
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": type_, "target": target, "text": text,
            "status": "pending", "resultado": None, "reply": None}


@app.post("/api/queue")
def queue_post(request: Request, id: str, body: dict):
    if body.get("type") not in QUEUE_TYPES:
        raise HTTPException(400, "type inválido")
    proj = _proj(request, id)
    entry = _make_entry(body["type"], body.get("target"),
                        body.get("text", ""))
    return _append_queue(proj / "ui" / "queue.json", entry)


@app.post("/api/reply")
def reply(request: Request, id: str, body: dict):
    qpath = _proj(request, id) / "ui" / "queue.json"
    queue = pipeline.read_json(qpath, [])
    for e in queue:
        if e["id"] == body.get("qid"):
            e["reply"] = body.get("text", "")
            e["status"] = "pending"
            pipeline.atomic_write_json(qpath, queue)
            return e
    raise HTTPException(404, "pedido não encontrado")


@app.post("/api/state")
def state_post(request: Request, id: str, body: dict):
    spath = _proj(request, id) / "ui" / "state.json"
    st = pipeline.read_json(spath, {})
    st.update(body)
    pipeline.atomic_write_json(spath, st)
    return st


@app.put("/api/format")
def format_put(request: Request, name: str, body: dict):
    if not re.fullmatch(r"[\w\-]+", name):
        raise HTTPException(400, "nome inválido")
    path = _root(request) / "Formatos" / f"{name}.md"
    path.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True}


@app.post("/api/new-project")
def new_project(request: Request, body: dict):
    entry = _make_entry("novo-projeto",
                        {"bruto": body.get("bruto"),
                         "formato": body.get("formato"),
                         "nome": body.get("nome")}, body.get("nome", ""))
    qpath = _root(request) / ".ui-runtime" / "queue.json"
    return _append_queue(qpath, entry)


@app.get("/api/global-queue")
def global_queue(request: Request):
    return pipeline.read_json(_root(request) / ".ui-runtime" / "queue.json",
                              [])
```

Adicionar ao `.gitignore` na raiz:
```
.ui-runtime/
```

- [ ] **Step 3: Rodar** — `cd ui && rtk test "pytest -q"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add ui/server.py ui/test_server.py .gitignore
rtk git commit -m "feat(ui): fila, estado, formatos e novo projeto"
```

---

### Task 5: SSE (`GET /api/events`)

**Files:**
- Modify: `ui/server.py`
- Test: `ui/test_server.py` (append)

**Interfaces:**
- Produces: `GET /api/events?id=` — `text/event-stream`; a cada ~1s emite
  `data: {"mtimes": {edl, queue, state, preview, final}, "claude_online": bool}\n\n`
  somente quando algo mudou (primeiro evento sempre emitido). Cliente diffa e recarrega o que mudou.

- [ ] **Step 1: Teste falhando (append)**

```python
def test_events_first_snapshot(client):
    with client.stream("GET", "/api/events",
                       params={"id": "edit-fake"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        for line in r.iter_lines():
            if line.startswith("data:"):
                import json as _json
                snap = _json.loads(line[5:])
                assert "mtimes" in snap and "claude_online" in snap
                break
```

Run: `cd ui && rtk test "pytest test_server.py -q"` → FAIL (404).

- [ ] **Step 2: Implementar (append em `ui/server.py`)**

```python
import asyncio
import json as _json
from fastapi.responses import StreamingResponse

WATCH = {"edl": "edl.json", "queue": "ui/queue.json",
         "state": "ui/state.json", "preview": "preview.mp4",
         "final": "final.mp4"}


def _snapshot(proj):
    mtimes = {}
    for key, rel in WATCH.items():
        try:
            mtimes[key] = (proj / rel).stat().st_mtime
        except OSError:
            mtimes[key] = None
    return {"mtimes": mtimes, "claude_online": pipeline.claude_online(proj)}


@app.get("/api/events")
async def events(request: Request, id: str):
    proj = _proj(request, id)

    async def gen():
        last = None
        while True:
            if await request.is_disconnected():
                return
            snap = _snapshot(proj)
            if snap != last:
                yield f"data: {_json.dumps(snap)}\n\n"
                last = snap
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 3: Rodar** — `cd ui && rtk test "pytest -q"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add ui/server.py ui/test_server.py
rtk git commit -m "feat(ui): SSE de mudanças de arquivo"
```

---

### Task 6: Frontend — casca, player, seletor de projeto

**Files:**
- Modify: `ui/static/index.html`
- Create: `ui/static/style.css`, `ui/static/app.js`

**Interfaces:**
- Consumes: `GET /api/projects`, `/api/project`, `/api/video`, SSE `/api/events`
- Produces (JS globais usados nas tasks 7-9): objeto `S` (estado da página: `S.pid`, `S.proj`, `S.wave`, `S.selected`), funções `loadProject(pid)`, `refresh(keys)`, `el(id)`, `outToSrc(t)`, `srcToOut(t)` (mapeamento definido na Task 7 — aqui stub identidade).

- [ ] **Step 1: `index.html`**

```html
<title>video_editor</title>
<link rel="stylesheet" href="style.css">
<header>
  <select id="proj-select"></select>
  <select id="format-select"></select>
  <button id="btn-new">Novo vídeo</button>
  <button id="btn-formats">Formatos</button>
  <span class="spacer"></span>
  <div id="render-progress" hidden><div id="render-bar"></div><span id="render-label"></span></div>
  <button id="btn-render-preview">Render Preview</button>
  <button id="btn-render-final">Render Final</button>
  <span id="claude-status" class="offline">Claude offline</span>
</header>
<main>
  <section id="player-pane">
    <video id="player" controls></video>
    <div id="no-preview" hidden>sem preview — peça um render</div>
  </section>
  <aside id="side-pane">
    <div id="cut-list"></div>
    <div id="instruction-pane">
      <div id="instr-context">instrução geral</div>
      <textarea id="instr-text" placeholder="o que fazer..."></textarea>
      <button id="instr-send">Enviar</button>
    </div>
    <div id="queue-panel"></div>
  </aside>
</main>
<footer>
  <canvas id="timeline"></canvas>
</footer>
<div id="modal" hidden></div>
<script src="app.js"></script>
```

- [ ] **Step 2: `style.css` — tema escuro tipo Premiere**

Grid: `header` fixo, `main` = `player 1fr | aside 320px`, `footer` = timeline 220px. Paleta: fundo `#1e1e1e`, painéis `#252526`, bordas `#3c3c3c`, destaque `#4f8cff`, aprovado `#4caf50`, pendente `#e6a23c`, falha `#e05252`. Fonte system-ui 13px. (Escrever CSS completo — ~120 linhas — sem framework.)

- [ ] **Step 3: `app.js` — base**

```javascript
const S = { pid: null, proj: null, wave: null, selected: null, es: null };
const el = id => document.getElementById(id);
const api = (path, params = {}) => {
  const u = new URL(path, location.origin);
  Object.entries(params).forEach(([k, v]) => u.searchParams.set(k, v));
  return u;
};
const getJSON = async (path, params) => (await fetch(api(path, params))).json();
const postJSON = (path, params, body) =>
  fetch(api(path, params), { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });

// stubs — Task 7 troca pelo mapeamento real via EDL
let outToSrc = t => t, srcToOut = t => t;

async function loadProjects() {
  const projs = await getJSON('/api/projects');
  const sel = el('proj-select');
  sel.innerHTML = projs.map(p =>
    `<option value="${p.id}">${p.name}</option>`).join('');
  sel.onchange = () => loadProject(sel.value);
  if (projs.length) loadProject(localStorage.lastPid || projs[0].id);
}

async function loadProject(pid) {
  S.pid = pid; localStorage.lastPid = pid;
  S.proj = await getJSON('/api/project', { id: pid });
  S.wave = await getJSON('/api/waveform', { id: pid });
  const v = el('player');
  el('no-preview').hidden = S.proj.has_preview;
  if (S.proj.has_preview)
    v.src = api('/api/video', { id: pid, kind: 'preview' });
  renderAll();          // definida nas tasks 7-9
  connectSSE(pid);
}

function connectSSE(pid) {
  if (S.es) S.es.close();
  S.es = new EventSource(api('/api/events', { id: pid }));
  let last = null;
  S.es.onmessage = async ev => {
    const snap = JSON.parse(ev.data);
    el('claude-status').className = snap.claude_online ? 'online' : 'offline';
    el('claude-status').textContent =
      snap.claude_online ? 'Claude escutando' : 'Claude offline';
    if (last) {
      const changed = Object.keys(snap.mtimes)
        .filter(k => snap.mtimes[k] !== last.mtimes[k]);
      if (changed.length) await loadProject(pid);   // recarrega tudo (simples)
    }
    last = snap;
  };
}

function renderAll() { /* preenchida nas próximas tasks */ }

loadProjects();
```

`// ponytail: SSE change => full reload do payload; granular só se ficar lento.`

- [ ] **Step 4: Verificação com Playwright (skill example-skills:webapp-testing)**

Subir servidor: `python ui/server.py` (background). Abrir `http://127.0.0.1:8765` com Playwright: screenshot; conferir dropdown lista `edit` e `edit-the-goat`, player carrega preview do projeto real, badge "Claude offline" visível. Sem erros no console.

- [ ] **Step 5: Commit**

```bash
rtk git add ui/static
rtk git commit -m "feat(ui): casca da página, player e seletor de projeto"
```

---

### Task 7: Frontend — timeline canvas (tracks V/A/T/FX, zoom/pan, playhead)

**Files:**
- Modify: `ui/static/app.js`, `ui/static/style.css`

**Interfaces:**
- Consumes: `S.proj` (edl.ranges, zooms, phrases, srt, overlays), `S.wave`
- Produces:
  - `outToSrc(t)` / `srcToOut(t)` reais (usadas pelo playhead e Task 8)
  - `renderTimeline()` — desenha tudo; chamada por `renderAll()`
  - `view = {t0, pxPerSec}` — janela visível; wheel = zoom, drag fundo = pan
  - `hitSegment(x, y) -> {index, edge: null|'start'|'end'} | null`

- [ ] **Step 1: Mapeamento de tempo (substituir stubs)**

```javascript
function buildTimeMap() {
  const ranges = S.proj.edl.ranges;
  let acc = 0;
  const map = ranges.map(r => {
    const seg = { srcStart: r.start, srcEnd: r.end,
                  outStart: acc, outEnd: acc + (r.end - r.start) };
    acc = seg.outEnd;
    return seg;
  });
  outToSrc = t => {
    for (const s of map)
      if (t <= s.outEnd) return s.srcStart + Math.max(0, t - s.outStart);
    return map.length ? map[map.length - 1].srcEnd : t;
  };
  srcToOut = t => {
    for (const s of map) {
      if (t < s.srcStart) return s.outStart;      // gap: fim do anterior
      if (t <= s.srcEnd) return s.outStart + (t - s.srcStart);
    }
    return map.length ? map[map.length - 1].outEnd : t;
  };
  return map;
}
```

- [ ] **Step 2: Desenho do canvas**

`renderTimeline()`: canvas full-width, DPR-aware. Tracks (topo→base): régua de tempo (ticks adaptativos ao zoom), **V** — retângulos dos ranges no eixo do bruto (gaps aparentes; selecionado = borda azul; aprovado = verde; pedido pendente naquele segmento = laranja), **A** — waveform (peaks → linhas verticais), **T** — frases (`phrases`) como caixinhas com texto truncado, **FX** — zoom≠1.0 por segmento + overlays (mapear `start_in_output`→src via `outToSrc`) + blocos do SRT (mapear igualmente). Playhead: linha vermelha em `srcToOut⁻¹` — i.e. `outToSrc(player.currentTime)`; `requestAnimationFrame` enquanto tocando.

- [ ] **Step 3: Interação básica**

- wheel no canvas: zoom em torno do cursor (`pxPerSec *= 1.1^±1`, clamp 1..2000)
- drag no fundo: pan (`t0 -= dx/pxPerSec`)
- clique em segmento: `S.selected = index`, atualiza `#instr-context` (“sobre corte #N”), lista lateral destaca
- clique fora de segmento (gap ou régua): `player.currentTime = srcToOut(tClicado)`; clique em gap posiciona no fim do segmento anterior (o `srcToOut` já faz isso)
- `hitSegment`: retorna `edge` quando o x está a ≤5px da borda de um segmento (usado na Task 8)

- [ ] **Step 4: Verificar com Playwright**

Abrir projeto `edit-the-goat`; screenshot da timeline; conferir: número de blocos V == `ranges.length`, waveform visível, frases na track T, playhead se move ao dar play. Zoom com wheel muda densidade dos ticks.

- [ ] **Step 5: Commit**

```bash
rtk git add ui/static
rtk git commit -m "feat(ui): timeline canvas com tracks e mapeamento de tempo"
```

---

### Task 8: Frontend — lista de cortes, instruções, 👍👎, arrastar bordas

**Files:**
- Modify: `ui/static/app.js`, `ui/static/style.css`

**Interfaces:**
- Consumes: `POST /api/queue`, `POST /api/state`, `hitSegment`, `S.selected`
- Produces: `renderCutList()`, `sendInstruction()`, chamadas em `renderAll()`

- [ ] **Step 1: Lista de cortes**

`renderCutList()`: para cada range, linha `#N  mm:ss–mm:ss  [👍] [👎]`; clique na linha seleciona + `player.currentTime = srcToOut(range.start)`. 👍: adiciona index em `state.aprovacoes` via `POST /api/state` (toggle); linha verde. 👎: `POST /api/queue {type:'veto', target: N, text:'revisar/remover corte #N'}`; linha laranja enquanto pedido pendente.

- [ ] **Step 2: Campo de instrução**

`sendInstruction()`: `POST /api/queue {type:'instrucao', target: S.selected, text}`; contexto do formato vai implícito (Claude lê `state.formato`). Enter com Ctrl envia. Limpa campo, painel de fila atualiza otimista.

- [ ] **Step 3: Arrastar bordas**

pointerdown com `hitSegment(...).edge` ≠ null → captura; pointermove mostra ghost (linha tracejada + delta em ms); pointerup → se |delta| ≥ 30ms:
```javascript
postJSON('/api/queue', { id: S.pid }, {
  type: 'borda',
  target: { seg: i, edge, delta_ms: Math.round(delta * 1000) },
  text: `${edge === 'start' ? 'início' : 'fim'} do corte #${i} ${delta > 0 ? '+' : ''}${Math.round(delta * 1000)}ms`,
});
```
Segmento fica laranja (pendente) até o pedido sair de `pending/executing`.

- [ ] **Step 4: Verificar com Playwright**

Clicar segmento na lista → player pula e timeline destaca. Enviar instrução → aparece no painel de fila como pendente e `ui/queue.json` do projeto contém o entry. Arrastar borda → entry `borda` com `delta_ms` correto.

- [ ] **Step 5: Commit**

```bash
rtk git add ui/static
rtk git commit -m "feat(ui): lista de cortes, instruções e ajuste de bordas"
```

---

### Task 9: Frontend — fila viva, render, formatos, novo vídeo

**Files:**
- Modify: `ui/static/app.js`, `ui/static/style.css`

**Interfaces:**
- Consumes: `S.proj.queue`, `S.proj.state.render`, `/api/reply`, `/api/formats`, `PUT /api/format`, `/api/brutos`, `/api/new-project`
- Produces: `renderQueue()`, `renderProgress()`, modal de formatos, modal novo vídeo

- [ ] **Step 1: Painel de fila**

`renderQueue()`: entries em ordem reversa; ícone por status (⏳ pending, ▶ executing, ❓ waiting_reply, ✅ done, ❌ failed); `resultado` como subtexto. `waiting_reply`: mostra a pergunta (`resultado`) + input + botão que chama `POST /api/reply`.

- [ ] **Step 2: Render + progresso**

Botões Render Preview/Final: `POST /api/queue {type:'render', text:'preview'|'final'}`. `renderProgress()`: se `state.render` existe e `pct < 100`, mostra barra no header com `fase` + `pct` + `eta` (formato `m:ss`); some quando concluído.

- [ ] **Step 3: Dropdown de formato + aba Formatos**

Dropdown: opções de `/api/formats`; mudança → `POST /api/state {formato}`. Botão "Formatos" abre modal: lista à esquerda, `<textarea>` com o markdown à direita (edição crua, sem preview render — YAGNI), botão salvar → `PUT /api/format`.

- [ ] **Step 4: Modal Novo vídeo**

Botão abre modal: select de `/api/brutos`, select de formato, input nome → `POST /api/new-project`. Confirmação: "pedido enviado — Claude vai iniciar a edição".

- [ ] **Step 5: Verificar com Playwright + servidor real**

Simular Claude: editar `queue.json` na mão (status `executing` → `done`) e conferir painel atualizando via SSE em ≤2s. Escrever `state.json` com `{"render": {"fase": "concat", "pct": 40, "eta": 120}}` → barra aparece. Salvar formato pelo modal → arquivo muda no disco.

- [ ] **Step 6: Commit**

```bash
rtk git add ui/static
rtk git commit -m "feat(ui): fila viva, progresso de render, formatos e novo vídeo"
```

---

### Task 10: Protocolo Claude (`CLAUDE.md` raiz) + runbook de escuta

**Files:**
- Create: `CLAUDE.md` (raiz do repo)

**Interfaces:**
- Consumes: schema da fila (Task 4)
- Produces: doc que qualquer sessão Claude lê para atuar como executor da fila

- [ ] **Step 1: Escrever `CLAUDE.md`**

Conteúdo (completo):

```markdown
# video_editor — protocolo da UI

UI local: `python ui/server.py` → http://127.0.0.1:8765

## Papel do Claude na sessão

Quando o usuário pedir para "escutar a UI":
1. Tocar `edit/<proj>/ui/heartbeat` (arquivo vazio, re-touch a cada ciclo de
   escuta; UI considera online se mtime < 10s).
2. Monitorar `edit/*/ui/queue.json`, `edit/shorts/*/ui/queue.json` e
   `.ui-runtime/queue.json` (fila global de novo-projeto).
3. Pedido `pending` mais antigo primeiro (FIFO, um por vez).

## Ciclo de um pedido

1. Marcar `status: "executing"` (reescrever o queue.json atômico).
2. Ler `ui/state.json` → `formato` = receita em `Formatos/<formato>.md`;
   seguir a receita.
3. Tipos:
   - `instrucao` — texto livre; `target` = índice do corte ou null (geral).
   - `veto` — `target` = índice do corte; revisar/remover.
   - `borda` — `target` = `{seg, edge: start|end, delta_ms}`; ajustar range
     no edl.json respeitando limites de palavra (regras do video-use).
   - `render` — `text` = `preview`|`final`; rodar render.py escrevendo
     progresso em `state.json` → `{"render": {"fase", "pct", "eta"}}`.
   - `novo-projeto` — `target` = `{bruto, formato, nome}`; renomear bruto
     (memória "renomear-bruto"), criar dir de edição, iniciar pipeline.
4. Pedido grande/ambíguo → `status: "waiting_reply"` + pergunta em
   `resultado`. UI devolve resposta em `reply` e volta status a `pending`.
5. Fim: `status: "done"` + nota curta em `resultado`, ou `"failed"` + motivo.

## Regras

- Confirmação de estratégia do video-use continua valendo (via waiting_reply).
- UI nunca edita edl.json; toda mutação passa por aqui.
- Progresso de render: atualizar `state.json` por segmento concluído.
```

- [ ] **Step 2: Commit**

```bash
rtk git add CLAUDE.md
rtk git commit -m "docs: protocolo da fila UI<->Claude"
```

---

### Task 11: Verificação ponta-a-ponta com projeto real

**Files:** nenhum novo — validação.

- [ ] **Step 1:** `rtk test "pytest ui -q"` → todos PASS.
- [ ] **Step 2:** Subir `python ui/server.py`; Playwright em `edit-the-goat`: screenshot geral (player + timeline + lista); conferir waveform do bruto real gerada e cacheada em `edit-the-goat/ui/cache/waveform.json`.
- [ ] **Step 3:** Fluxo híbrido real: enviar instrução pela UI → nesta sessão Claude, ler `queue.json`, marcar `executing`→`done` → conferir painel refletindo em ≤2s.
- [ ] **Step 4:** Screenshot final para o usuário aprovar visual.
- [ ] **Step 5: Commit final**

```bash
rtk git add -A
rtk git commit -m "chore: verificação ponta-a-ponta da UI"
```

---

## Self-review (feito na escrita)

- **Cobertura da spec:** layout (T6-9), eixos de tempo (T7), fila/FIFO/waiting_reply (T4,T9,T10), heartbeat/offline (T1,T5,T6), render/progresso (T9,T10), formatos view+edit+dropdown (T3,T4,T9), novo vídeo (T4,T9), waveform+cache (T2), SSE (T5), erros (404 preview → T3/T6; failed → T9), testes (T1-T5), Playwright (T6-T9,T11). Filmstrip: fora de escopo v1 (spec).
- **Placeholders:** CSS da T6 e desenho da T7 descritos por comportamento com valores concretos (paleta, alturas, regras de hit) — código canvas completo fica a cargo do executor seguindo as funções/contratos definidos; contratos (`outToSrc`, `srcToOut`, `hitSegment`, `view`) têm código/assinaturas reais.
- **Consistência de tipos:** `target` de `borda` = `{seg, edge, delta_ms}` em T8=T10; entry da fila idêntico em T4=T9=T10; `state.render` = `{fase, pct, eta}` em T9=T10.
```
