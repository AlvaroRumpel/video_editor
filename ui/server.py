"""Servidor da UI do video_editor. Roda: python ui/server.py"""
from pathlib import Path
import math
import os
import re
import subprocess
import time
import asyncio
import json as _json
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import budget
import eventos
import folha
import md_min
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


def _mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


@app.get("/api/docs")
def docs(request: Request, id: str):
    proj = _proj(request, id)
    out = [{"name": p.name, "mtime": m}
           for p, m in ((p, _mtime(p)) for p in sorted(proj.glob("*.md")) if p.suffix == ".md")
           if m is not None]
    out += [{"name": f"broll/{p.name}", "mtime": m}
            for p, m in ((p, _mtime(p)) for p in sorted((proj / "broll").glob("*.png")))
            if m is not None]
    out += [{"name": f"ref/{p.name}", "mtime": m}
            for p, m in ((p, _mtime(p)) for p in sorted((proj / "ref").glob("*.png")))
            if m is not None]
    # glob é case-insensitive no Windows; a regex garante animatic-[A-Z].png
    out += [{"name": p.name, "mtime": m}
            for p, m in ((p, _mtime(p)) for p in sorted(proj.glob("animatic-?.png"))
                         if FILE_NAME.fullmatch(p.name))
            if m is not None]
    return out


@app.get("/api/doc")
def doc(request: Request, id: str, name: str):
    if not DOC_NAME.fullmatch(name) or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "nome inválido")
    proj = _proj(request, id)
    path = proj / name
    if path.resolve().parent != proj.resolve():
        raise HTTPException(400, "nome inválido")
    if not path.is_file():
        raise HTTPException(404, "doc não encontrado")
    return {"name": name, "html": md_min.render(path.read_text(encoding="utf-8-sig", errors="replace"))}


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


@app.get("/api/formats")
def formats(request: Request):
    fdir = _root(request) / "Formatos"
    return [{"name": p.stem, "content": p.read_text(encoding="utf-8")}
            for p in sorted(fdir.glob("*.md")) if p.stem not in HIDDEN_FORMATS]


@app.get("/api/brutos")
def brutos(request: Request):
    bdir = _root(request) / "bruto"
    exts = {".mp4", ".mkv", ".mov", ".webm"}
    return sorted(p.name for p in bdir.glob("*")
                  if p.suffix.lower() in exts) if bdir.is_dir() else []


@app.get("/api/brutos-ref")
def brutos_ref(request: Request):
    d = _root(request) / "bruto" / "ref"
    return sorted(p.name for p in d.glob("*.mp4")) if d.is_dir() else []


HIDDEN_FORMATS = {"thumbnail", "pauta", "referencia"}  # receitas internas, fora do dropdown
QUEUE_TYPES = {"instrucao", "render", "borda", "veto", "roteiro", "pauta", "referencia"}
DOC_NAME = re.compile(r"^[\w\-. ]+\.md$")
FILE_NAME = re.compile(r"^(broll|ref)/[\w\-]+\.png$|^animatic-[A-Z]\.png$")
MIDIA = re.compile(r"^broll/cand/[\w\-.]+\.(mp4|webm|jpg|jpeg|png)$|^overlays/o\d{2,3}\.png$")
TIPO_MIDIA = {".mp4": "video/mp4", ".webm": "video/webm", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".png": "image/png"}


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
    if id == "_global":
        qpath = _root(request) / ".ui-runtime" / "queue.json"
    else:
        qpath = _proj(request, id) / "ui" / "queue.json"
    queue = pipeline.read_json(qpath, [])
    for e in queue:
        if e["id"] == body.get("qid"):
            e["reply"] = body.get("text", "")
            e["status"] = "pending"
            e.pop("folha", None)   # qualquer resposta consome a folha; o Claude regrava se perguntar de novo
            pipeline.atomic_write_json(qpath, queue)
            if id != "_global":   # resposta entra na linha do tempo do projeto; log nunca derruba o reply
                try:
                    eventos.registrar_resposta(qpath.parent.parent, e["id"], e["reply"])
                except Exception:  # noqa: BLE001
                    pass
            return e
    raise HTTPException(404, "pedido não encontrado")


@app.post("/api/cancel")
def cancel(request: Request, id: str, body: dict):
    if id == "_global":
        qpath = _root(request) / ".ui-runtime" / "queue.json"
    else:
        qpath = _proj(request, id) / "ui" / "queue.json"
    queue = pipeline.read_json(qpath, [])
    for e in queue:
        if e["id"] == body.get("qid"):
            if e["status"] not in ("pending", "waiting_reply"):
                raise HTTPException(409, f"pedido já {e['status']}")
            e["status"] = "cancelado"
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
    formato = body.get("formato")
    qpath = _root(request) / ".ui-runtime" / "queue.json"
    if formato == "roteiro":
        tema = (body.get("descricao") or "").strip()
        if not tema:
            raise HTTPException(400, "roteiro exige tema (descrição)")
        if not (body.get("nome") or "").strip():
            raise HTTPException(400, "roteiro exige nome")
        return _append_queue(qpath, _make_entry("roteiro",
            {"tema": tema, "duracao_min": body.get("duracao_min"), "publico": body.get("publico", ""),
             "nome": body.get("nome", "")}, body.get("nome") or tema[:60]))
    if formato == "referencia":
        origem = (body.get("origem") or "").strip(); nome = (body.get("nome") or "").strip()
        if not origem or not nome:
            raise HTTPException(400, "referência exige origem (URL ou arquivo) e nome")
        return _append_queue(qpath, _make_entry("referencia",
            {"origem": origem, "marca": (body.get("marca") or "anotus").strip().lower(), "nome": nome,
             "briefing": (body.get("descricao") or "").strip()}, f"referência: {nome}"))
    if formato == "pauta":
        if not body.get("marca") or not body.get("mes"):
            raise HTTPException(400, "pauta exige marca e mês")
        return _append_queue(qpath, _make_entry("pauta",
            {"marca": body["marca"], "mes": body["mes"]}, f"pauta {body['marca']} {body['mes']}"))
    if not body.get("bruto") and not (body.get("descricao") or "").strip():
        raise HTTPException(400, "sem bruto exige descrição")
    entry = _make_entry("novo-projeto",
                        {"bruto": body.get("bruto"),
                         "formato": body.get("formato"),
                         "nome": body.get("nome"),
                         "descricao": body.get("descricao", ""),
                         "fontes": body.get("fontes", "")}, body.get("nome", ""))
    return _append_queue(qpath, entry)


@app.get("/api/activity")
def activity(request: Request):
    """O que o Claude está fazendo agora (escrito pela sessão executora)."""
    return pipeline.read_json(_root(request) / ".ui-runtime" / "activity.json",
                              {})


@app.get("/api/global-queue")
def global_queue(request: Request):
    return pipeline.read_json(_root(request) / ".ui-runtime" / "queue.json",
                              [])


@app.get("/api/quadro")
def quadro_route(request: Request, id: str):
    return eventos.quadro(_proj(request, id), root=_root(request))


@app.get("/api/linha")
def linha_route(request: Request, id: str):
    return eventos.linha(_proj(request, id), root=_root(request))


@app.get("/api/decisoes")
def decisoes_route(request: Request, assunto: str | None = None):
    assunto = assunto or None
    if assunto is not None and assunto not in eventos.ASSUNTOS:
        raise HTTPException(400, "assunto inválido")
    return eventos.decisoes(_root(request), assunto=assunto)


@app.get("/api/folha")
def folha_route(request: Request, id: str, tipo: str, lang: str | None = None):
    if tipo not in folha.TIPOS:
        raise HTTPException(400, "tipo inválido")
    proj = _proj(request, id)
    try:
        return folha.ler(proj, tipo, lang=lang)
    except ValueError as e:
        raise HTTPException(422, str(e))


FILA_ATIVA = {"pending", "executing", "waiting_reply"}


def _fila_ativa(proj: Path) -> list:
    q = pipeline.read_json(proj / "ui" / "queue.json", [])
    if not isinstance(q, list):
        return []
    return [e for e in q if isinstance(e, dict) and e.get("status") in FILA_ATIVA]


_NAO_ATIVIDADE = {"heartbeat", "capa.jpg", "capa.tmp.jpg"}   # escuta/cache de capa não são atividade
CAPA_FONTES = ("final.mp4", "preview.mp4", "animatic-A.png", "ref/sheet.png")


def _max_mtime(cands) -> float:
    ms = [m for m in map(_mtime, cands) if m is not None]
    return max(ms) if ms else 0.0


def _atividade(proj: Path) -> float:
    ui = [p for p in (proj / "ui").glob("*") if p.name not in _NAO_ATIVIDADE]
    return _max_mtime([*ui, proj / "edl.json", proj / "preview.mp4", proj / "final.mp4"])


def _capa_v(proj: Path) -> float:
    """Versão da capa: só muda quando uma fonte da capa muda."""
    return _max_mtime([*proj.glob("thumbnail*.png"), *(proj / r for r in CAPA_FONTES)])


def _curta(e):
    return {k: e[k] for k in ("id", "rotulo", "status")}


@app.get("/api/library")
def library(request: Request):
    root = _root(request)
    out = []
    for p in pipeline.find_projects(root):
        item = {**p, "formato": None, "etapas": [], "atual": None, "sem_historico": True,
                "pendencias": 0, "fila": [], "custo_usd": 0.0, "claude_online": False,
                "atividade": None, "capa_v": 0, "_ts": 0.0}
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
                claude_online=pipeline.claude_online(proj), _ts=ts, capa_v=_capa_v(proj),
                atividade=datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None)
        except Exception:  # noqa: BLE001 — projeto ilegível não derruba a biblioteca
            pass
        out.append(item)
    out.sort(key=lambda i: i["_ts"], reverse=True)
    for i in out:
        del i["_ts"]
    return out


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


BUDGET_NUM = ("teto_mensal_usd", "teto_projeto_usd", "aprovar_acima_usd")


def _num_ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


@app.get("/api/budget")
def budget_get(request: Request):
    root = _root(request)
    return {"budget": budget.ler_budget(root), "mes": budget._ano_mes_atual(),
            "gasto_mes": budget.gasto_mes(root),
            "elevenlabs": budget.saldo_elevenlabs(root)}


@app.put("/api/budget")
def budget_put(request: Request, body: dict):
    for k in BUDGET_NUM:
        if k in body and not _num_ok(body[k]):
            raise HTTPException(400, f"{k} inválido")
    tp = body.get("tetos_projeto")
    if tp is not None and (not isinstance(tp, dict)
                           or not all(v is None or _num_ok(v) for v in tp.values())):
        raise HTTPException(400, "tetos_projeto inválido")
    path = _root(request) / ".ui-runtime" / "budget.json"
    cur = pipeline.read_json(path, {})      # reler antes de gravar
    for k in BUDGET_NUM:
        if k in body:
            cur[k] = body[k]
    if tp is not None:
        cur_tp = cur.setdefault("tetos_projeto", {})
        for k, v in tp.items():
            if v is None:
                cur_tp.pop(k, None)   # null remove o teto próprio do projeto
            else:
                cur_tp[k] = v
    pipeline.atomic_write_json(path, cur)
    return budget.ler_budget(_root(request))


WATCH = {"edl": "edl.json", "queue": "ui/queue.json",
         "state": "ui/state.json", "preview": "preview.mp4",
         "final": "final.mp4", "costs": "ui/costs.jsonl",
         "eventos": "ui/eventos.jsonl"}


def _snapshot(proj, root):
    mtimes = {}
    for key, rel in WATCH.items():
        try:
            mtimes[key] = (proj / rel).stat().st_mtime
        except OSError:
            mtimes[key] = None
    mds = [m for m in map(_mtime, proj.glob("*.md")) if m is not None]
    mtimes["docs"] = max(mds) if mds else None
    for key, rel in (("global_queue", "queue.json"),
                     ("activity", "activity.json"),
                     ("budget", "budget.json")):
        try:  # fila global + atividade: refletem ao vivo na UI
            mtimes[key] = (root / ".ui-runtime" / rel).stat().st_mtime
        except OSError:
            mtimes[key] = None
    return {"mtimes": mtimes, "claude_online": pipeline.claude_online(proj)}


@app.get("/api/events")
async def events(request: Request, id: str, max_events: int = 0):
    proj = _proj(request, id)

    async def gen():
        last = None
        count = 0
        while True:
            if await request.is_disconnected():
                return
            snap = _snapshot(proj, _root(request))
            if snap != last:
                yield f"data: {_json.dumps(snap)}\n\n"
                last = snap
                count += 1
                if max_events > 0 and count >= max_events:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"  # sempre revalidar JS/CSS
    return resp


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
