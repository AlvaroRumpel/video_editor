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
