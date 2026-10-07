"""Vídeo de referência: download (yt-dlp/arquivo), análise (cortes, keyframes,
áudio, fala) e animatic de roteiros de conceito. Sem FastAPI."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = pipeline.ROOT
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
URL_IDS = [re.compile(r"youtube\.com/shorts/([\w\-]+)"), re.compile(r"youtu\.be/([\w\-]+)"),
           re.compile(r"[?&]v=([\w\-]+)"), re.compile(r"instagram\.com/(?:reel|p)/([\w\-]+)"),
           re.compile(r"tiktok\.com/.*/video/(\d+)")]


def _tem_modulo(nome: str) -> bool:
    return importlib.util.find_spec(nome) is not None


def _sanitizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-") or "ref"


def slug_de(origem: str) -> str:
    if origem.startswith(("http://", "https://")):
        for rx in URL_IDS:
            m = rx.search(origem)
            if m and not re.search(r"[?&]list=", origem):
                return m.group(1)
        return "ref-" + hashlib.sha1(origem.encode()).hexdigest()[:8]
    return _sanitizar(Path(origem).stem)


def _run_padrao(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def baixar(origem: str, dst_dir: Path, _run=None) -> dict:
    run = _run or _run_padrao
    dst_dir = Path(dst_dir); dst_dir.mkdir(parents=True, exist_ok=True)
    slug = slug_de(origem)
    agora = datetime.now().isoformat(timespec="seconds")
    if origem.startswith(("http://", "https://")):
        if not _tem_modulo("yt_dlp"):
            raise RuntimeError("yt-dlp não instalado: pip install yt-dlp")
        cmd = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
               "--write-info-json", "--no-playlist", "-o", str(dst_dir / f"{slug}.%(ext)s"), origem]
        r = run(cmd)
        err = (r.stderr or "")
        if r.returncode != 0:
            if re.search(r"login|cookies|rate.?limit|sign in", err, re.I):
                raise RuntimeError("plataforma exige login — baixe à mão em bruto/ref/ e passe o arquivo")
            raise RuntimeError(f"yt-dlp falhou ({r.returncode}): {err[-300:]}")
        if not (dst_dir / f"{slug}.mp4").is_file():
            raise RuntimeError(f"yt-dlp não gerou {slug}.mp4 — verifique a URL")
        info = pipeline.read_json(dst_dir / f"{slug}.info.json", {})
        pub = str(info.get("upload_date") or "")
        meta = {"origem": "url", "url": info.get("webpage_url") or origem, "plataforma": info.get("extractor_key", ""),
                "autor": info.get("uploader", ""), "titulo": info.get("title", ""), "dur": info.get("duration"),
                "publicado": f"{pub[:4]}-{pub[4:6]}-{pub[6:8]}" if len(pub) == 8 else "",
                "baixado_em": agora, "slug": slug, "arquivo": f"{slug}.mp4"}
    else:
        src = Path(origem)
        if not src.is_file():
            raise ValueError(f"arquivo não existe: {src}")
        shutil.copyfile(src, dst_dir / f"{slug}.mp4")
        meta = {"origem": "arquivo", "url": "", "plataforma": "arquivo", "autor": "", "titulo": src.stem,
                "dur": None, "publicado": "", "baixado_em": agora, "slug": slug, "arquivo": f"{slug}.mp4"}
    (dst_dir / f"{slug}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta
