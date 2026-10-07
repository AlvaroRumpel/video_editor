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


def _ff(args: list[str]) -> str:
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-y", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ({r.returncode}): {r.stderr[-800:]}")
    return r.stderr


def _probe(path: Path, sel: str, entries: str) -> str:
    return subprocess.run([FFPROBE, "-v", "error", "-select_streams", sel, "-show_entries", entries, "-of", "csv=p=0",
                           str(path)], capture_output=True, text=True).stdout.strip()


def duracao(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def dims(path: Path) -> tuple[int, int]:
    w, h = _probe(path, "v:0", "stream=width,height").split(",")[:2]
    return int(w), int(h)


def _tem_audio(path: Path) -> bool:
    return bool(_probe(path, "a", "stream=index"))


def cortes(video: Path, limiar: float = 10) -> list[float]:
    err = _ff(["-i", str(video), "-vf", f"scdet=t={limiar}", "-an", "-f", "null", "-"])
    ts = [float(m) for m in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", err)]
    out = [0.0]
    for t in sorted(ts):
        if t - out[-1] >= 0.2:
            out.append(round(t, 3))
    return out


def _rotulo(s: str) -> str:
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


FONTE = Path("C:/Windows/Fonts/arial.ttf")


def keyframes(video: Path, tempos: list[float], dst_png: Path, max_n: int = 24) -> dict:
    dur = duracao(video)
    if len(tempos) < 4:
        tempos = [float(t) for t in range(0, int(dur), 2)] or [0.0]
    tempos = [t for t in tempos if t < dur][:max_n] or [0.0]
    tmp = Path(dst_png).with_suffix(".tiles"); tmp.mkdir(parents=True, exist_ok=True)
    ff = f",drawtext=fontfile='{_rotulo(FONTE.as_posix())}':" if FONTE.exists() else ",drawtext="
    pngs = []
    for i, t in enumerate(tempos):
        png = tmp / f"k_{i:03d}.png"
        vf = (f"scale=320:568:force_original_aspect_ratio=decrease,pad=320:568:(ow-iw)/2:(oh-ih)/2"
              f"{ff}text='{_rotulo(f't={t:.1f}s')}':x=6:y=h-24:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6")
        _ff(["-ss", f"{min(t + 0.1, max(dur - 0.05, 0)):.3f}", "-i", str(video), "-frames:v", "1", "-vf", vf, str(png)])
        pngs.append(png)
    cols = min(6, len(pngs)); rows = -(-len(pngs) // cols)
    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{p.as_posix()}'\n" for p in pngs), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", str(lista), "-vf", f"tile={cols}x{rows}:color=black", "-frames:v", "1", str(dst_png)])
    shutil.rmtree(tmp, ignore_errors=True)
    return {"png": str(dst_png), "n": len(pngs), "colunas": cols, "linhas": rows}


def audio(video: Path) -> dict:
    if not _tem_audio(video):
        return {"lufs": None, "fala_pct": 0.0, "musica": False}
    dur = duracao(video)
    err = _ff(["-i", str(video), "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    m = re.search(r"I:\s*(-?[\d.]+) LUFS", err)
    lufs = float(m.group(1)) if m else None
    err = _ff(["-i", str(video), "-vn", "-af", "highpass=f=200,lowpass=f=3400,silencedetect=n=-35dB:d=0.3", "-f", "null", "-"])
    sil = sum(float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", err))
    fala_pct = round(max(0.0, 1 - sil / dur), 3) if dur else 0.0
    err = _ff(["-i", str(video), "-vn", "-af", "bandreject=f=1000:t=h:w=2600,astats=measure_perchannel=none:measure_overall=RMS_level",
               "-f", "null", "-"])
    m = re.search(r"RMS level dB:\s*(-?[\d.]+|-inf)", err)
    rms = -120.0 if not m or m.group(1) == "-inf" else float(m.group(1))
    return {"lufs": lufs, "fala_pct": fala_pct, "musica": rms > -40.0}


def fala(transcript: dict) -> dict:
    ws = [w for w in transcript.get("words", []) if w.get("type") == "word"]
    if not ws:
        return {"wps": 0.0, "pausas_por_min": 0.0, "gancho_2s": "", "cta": "", "dur_fala": 0.0}
    t0, t1 = ws[0]["start"], ws[-1]["end"]
    dur = max(t1 - t0, 0.001)
    pausas = sum(1 for a, b in zip(ws, ws[1:]) if b["start"] - a["end"] >= 0.5)
    fr = pipeline.phrases_from_transcript(transcript)
    return {"wps": round(len(ws) / dur, 2), "pausas_por_min": round(pausas * 60 / dur, 1),
            "gancho_2s": " ".join(w["text"].strip() for w in ws if w["start"] < t0 + 2.0),
            "cta": " ".join(f["text"] for f in fr[-2:]), "dur_fala": round(dur, 2)}


def analisar(video: Path, proj: Path, transcript_json: Path | None = None) -> dict:
    video = Path(video); proj = Path(proj)
    ref = proj / "ref"; ref.mkdir(parents=True, exist_ok=True)
    dur = duracao(video); w, h = dims(video)
    cs = cortes(video)
    keyframes(video, cs, ref / "sheet.png")
    tr = None
    if transcript_json:
        tr = json.loads(Path(transcript_json).read_text(encoding="utf-8-sig"))
    try:
        rel = video.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        rel = str(video)
    a = {"video": rel, "dur": round(dur, 2), "largura": w, "altura": h,
         "fala": fala(tr) if tr else None, "cortes": cs,
         "plano_medio_s": round(dur / max(len(cs), 1), 2), "cortes_por_min": round(len(cs) * 60 / dur, 1) if dur else 0,
         "audio": audio(video), "sheet": "ref/sheet.png",
         "transcript": str(transcript_json) if transcript_json else None}
    pipeline.atomic_write_json(ref / "analise.json", a)
    return a
