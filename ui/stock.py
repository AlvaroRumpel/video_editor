"""B-roll de stock: busca em bancos gratuitos, contact sheet, ranqueamento
opcional (CLIP), overlays prontos e merge no edl.json, créditos.
Sem FastAPI. ffmpeg por subprocess; HTTP por urllib (_fetch injetável)."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

import pipeline

ROOT = pipeline.ROOT
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) video_editor/1.0"
MAX_DOWNLOAD = 150 * 1024 * 1024


def _ler_env() -> dict:
    out = {}
    try:
        for ln in (ROOT / "video-use" / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            if k.strip():
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def chaves() -> dict:
    env = _ler_env()
    def pega(nome):
        return os.environ.get(nome) or env.get(nome, "")
    return {"pexels": pega("PEXELS_API_KEY"), "pixabay": pega("PIXABAY_API_KEY"),
            "unsplash": pega("UNSPLASH_ACCESS_KEY")}


def _fetch_url(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(MAX_DOWNLOAD + 1), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(e.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, b"", {}


def _json(fetch, url, headers=None):
    """GET + JSON; 429 → espera Retry-After (≤ 60 s) uma vez. Devolve (obj|None, aviso|None)."""
    status, corpo, h = fetch(url, headers)
    if status == 429:
        espera = min(60, int((h.get("Retry-After") or "5").strip() or 5))
        time.sleep(espera)
        status, corpo, h = fetch(url, headers)
        if status == 429:
            return None, f"429 persistente em {url}"
    if not (200 <= status < 300):
        return None, f"HTTP {status} em {url}"
    try:
        return json.loads(corpo.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError) as e:
        return None, f"resposta inválida de {url}: {e}"


def _variante(arquivos: list[dict], chave_w="width", chave_url="link") -> dict | None:
    """menor variante com largura >= 1920; senão >= 1280."""
    ok = sorted((a for a in arquivos if a.get(chave_w)), key=lambda a: a[chave_w])
    for minimo in (1920, 1280):
        for a in ok:
            if a[chave_w] >= minimo:
                return a
    return None


def _pexels(termo, tipo, n, k, fetch):
    if not k.get("pexels"):
        return [], "pexels: sem chave (PEXELS_API_KEY)"
    h = {"Authorization": k["pexels"]}
    q = urllib.parse.quote(termo)
    if tipo == "video":
        d, av = _json(fetch, f"https://api.pexels.com/videos/search?query={q}&per_page={n * 3}&orientation=landscape", h)
        if d is None:
            return [], av
        out = []
        for v in d.get("videos", []):
            var = _variante([f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"])
            if not var:
                continue
            out.append({"fonte": "pexels", "id": str(v["id"]), "autor": v.get("user", {}).get("name", ""),
                        "url": v.get("url", ""), "licenca": "Pexels License", "tipo": "video",
                        "dur": float(v.get("duration", 0)), "largura": var["width"], "altura": var["height"],
                        "download_url": var["link"], "ext": "mp4"})
        return out, None
    d, av = _json(fetch, f"https://api.pexels.com/v1/search?query={q}&per_page={n * 3}&orientation=landscape", h)
    if d is None:
        return [], av
    return [{"fonte": "pexels", "id": str(p["id"]), "autor": p.get("photographer", ""), "url": p.get("url", ""),
             "licenca": "Pexels License", "tipo": "foto", "dur": 0.0, "largura": p.get("width", 0),
             "altura": p.get("height", 0), "download_url": p["src"]["large2x"], "ext": "jpg"}
            for p in d.get("photos", [])], None


def _pixabay(termo, tipo, n, k, fetch):
    if not k.get("pixabay"):
        return [], "pixabay: sem chave (PIXABAY_API_KEY)"
    q = urllib.parse.quote(termo)
    if tipo == "video":
        d, av = _json(fetch, f"https://pixabay.com/api/videos/?key={k['pixabay']}&q={q}&per_page={max(3, n * 3)}")
        if d is None:
            return [], av
        out = []
        for v in d.get("hits", []):
            vs = [{"width": x.get("width", 0), "height": x.get("height", 0), "link": x.get("url", "")}
                  for x in v.get("videos", {}).values()]
            var = _variante(vs)
            if not var:
                continue
            out.append({"fonte": "pixabay", "id": str(v["id"]), "autor": v.get("user", ""), "url": v.get("pageURL", ""),
                        "licenca": "Pixabay Content License", "tipo": "video", "dur": float(v.get("duration", 0)),
                        "largura": var["width"], "altura": var["height"], "download_url": var["link"], "ext": "mp4"})
        return out, None
    d, av = _json(fetch, f"https://pixabay.com/api/?key={k['pixabay']}&q={q}&image_type=photo&orientation=horizontal&per_page={max(3, n * 3)}")
    if d is None:
        return [], av
    return [{"fonte": "pixabay", "id": str(p["id"]), "autor": p.get("user", ""), "url": p.get("pageURL", ""),
             "licenca": "Pixabay Content License", "tipo": "foto", "dur": 0.0, "largura": p.get("imageWidth", 0),
             "altura": p.get("imageHeight", 0), "download_url": p.get("largeImageURL", ""), "ext": "jpg"}
            for p in d.get("hits", [])], None


FONTES = {"pexels": _pexels, "pixabay": _pixabay}


def _filtrar(c: dict, tipo: str) -> bool:
    if c["tipo"] != tipo or not c.get("download_url"):
        return False
    if tipo == "video":
        return c["largura"] >= 1280 and 3 <= c["dur"] <= 30 and c["largura"] > c.get("altura", 0)
    return c["largura"] >= 1920


def _rel(dst_dir: Path, nome: str) -> str:
    partes = dst_dir.as_posix().split("/")
    if partes[-2:] == ["broll", "cand"]:
        return f"broll/cand/{nome}"
    return (dst_dir / nome).as_posix()


def buscar(termo: str, tipo: str, fontes: list[str], n: int, dst_dir: Path, _fetch=None) -> dict:
    fetch = _fetch or _fetch_url
    k = chaves()
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out, avisos = [], []
    for nome in fontes:
        fn = FONTES.get(nome)
        if not fn:
            avisos.append(f"{nome}: fonte desconhecida"); continue
        cands, av = fn(termo, tipo, n, k, fetch)
        if av:
            avisos.append(av)
        baixados = 0
        for c in cands:
            if baixados >= n or not _filtrar(c, tipo):
                continue
            status, corpo, _ = fetch(c["download_url"], None)
            if not (200 <= status < 300) or not corpo:
                avisos.append(f"{nome}-{c['id']}: download {status} ({'corpo vazio' if not corpo else 'falhou'})"); continue
            arq = f"{nome}-{re.sub(r'[^\w\-.]+', '_', c['id'])}.{c['ext']}"
            (dst_dir / arq).write_bytes(corpo)
            meta = {kk: v for kk, v in c.items() if kk not in ("download_url", "ext", "altura")}
            meta["arq"] = _rel(dst_dir, arq)
            meta["score"] = None
            (dst_dir / f"{Path(arq).stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            out.append(meta); baixados += 1
    return {"candidatos": out, "avisos": avisos}
