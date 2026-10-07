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
        alvo = dst_dir / f"{slug}.mp4"
        if src.resolve().parent != dst_dir.resolve():
            shutil.copyfile(src, alvo)
        elif src.name != alvo.name:                  # já em bruto/ref/ (baixado à mão) → só renomeia
            os.replace(src, alvo)
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


def _lista_concat(pngs: list[Path], lista: Path) -> None:
    """concat demuxer resolve relativo ao dir da lista → caminho absoluto, aspas escapadas."""
    lista.write_text("".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n" for p in pngs),
                     encoding="utf-8")


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
    try:
        for i, t in enumerate(tempos):
            png = tmp / f"k_{i:03d}.png"
            vf = (f"scale=320:568:force_original_aspect_ratio=decrease,pad=320:568:(ow-iw)/2:(oh-ih)/2"
                  f"{ff}text='{_rotulo(f't={t:.1f}s')}':x=6:y=h-24:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6")
            _ff(["-ss", f"{min(t + 0.1, max(dur - 0.05, 0)):.3f}", "-i", str(video), "-frames:v", "1", "-vf", vf, str(png)])
            pngs.append(png)
        cols = min(6, len(pngs)); rows = -(-len(pngs) // cols)
        lista = tmp / "lista.txt"; _lista_concat(pngs, lista)
        _ff(["-f", "concat", "-safe", "0", "-i", str(lista), "-vf", f"tile={cols}x{rows}:color=black", "-frames:v", "1", str(dst_png)])
    finally:
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
         "plano_medio_s": round(dur / max(len(cs), 1), 2), "cortes_por_min": round((len(cs) - 1) * 60 / dur, 1) if dur else 0,
         "audio": audio(video), "sheet": "ref/sheet.png",
         "transcript": str(transcript_json) if transcript_json else None}
    pipeline.atomic_write_json(ref / "analise.json", a)
    return a


CENA_RE = re.compile(r"^\s*(\d+)\.\s+(.*?)\s*$")
REF_RE = re.compile(r"\s*\[F\d+\]")
PALETAS = {"anotus": {"fundo": "#F3F2FA", "tinta": "#2B215C", "acento": "#D4A017", "pill": "#4A3D8F", "serif": "Fraunces, Georgia, serif", "sans": "Inter, 'Segoe UI', sans-serif", "marca": "Anotus"},
           "neutra": {"fundo": "#F5F5F5", "tinta": "#222222", "acento": "#666666", "pill": "#444444", "serif": "Georgia, serif", "sans": "'Segoe UI', sans-serif", "marca": ""}}


def cenas_de(roteiro_md: Path) -> list[dict]:
    texto = Path(roteiro_md).read_text(encoding="utf-8-sig")
    out, dentro = [], False
    for ln in texto.splitlines():
        if ln.startswith("## "):
            dentro = ln.strip().lower().startswith("## cenas"); continue
        if not dentro:
            continue
        m = CENA_RE.match(ln)
        if m:
            out.append({"n": int(m.group(1)), "texto": REF_RE.sub("", m.group(2)).strip(), "sfx": None}); continue
        s = ln.strip()
        if s.lower().startswith("sfx:") and out:
            out[-1]["sfx"] = s[4:].strip()
    return out


def _html_cena(c: dict, total: int, pal: dict) -> str:
    import html
    marca = f"<div class='wm'>{html.escape(pal['marca'])}<span class='dot'></span></div>" if pal["marca"] else ""
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<link rel="preconnect" href="https://fonts.gstatic.com"><link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,600;0,700;1,700&family=Inter:wght@500;700;900&display=swap" rel="stylesheet"><style>
html,body{{margin:0;width:540px;height:960px;background:{pal['fundo']};font-family:{pal['sans']};}}
.pill{{position:absolute;top:26px;left:50%;transform:translateX(-50%);padding:6px 14px;border-radius:999px;background:#fff;border:1px solid #B9B3E6;color:{pal['pill']};font-weight:700;font-size:14px}}
.pill::before{{content:'';display:inline-block;width:8px;height:8px;border-radius:50%;background:{pal['acento']};margin-right:8px}}
.txt{{position:absolute;left:40px;right:40px;top:50%;transform:translateY(-50%);font-family:{pal['serif']};font-weight:700;font-size:40px;line-height:1.15;color:{pal['tinta']}}}
.sfx{{position:absolute;left:40px;bottom:90px;font-size:14px;color:{pal['pill']};opacity:.8}}
.wm{{position:absolute;bottom:40px;left:50%;transform:translateX(-50%);font-family:{pal['serif']};font-style:italic;font-size:26px;color:{pal['tinta']};opacity:.55}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:{pal['acento']};margin-left:2px}}
</style></head><body>
<div class='pill'>cena {c['n']} / {total}</div>
<div class='txt'>{html.escape(c['texto'][:120])}</div>
{f"<div class='sfx'>sfx: {html.escape(c['sfx'])}</div>" if c.get('sfx') else ''}
{marca}
</body></html>"""


def animatic(roteiro_md: Path, dst_png: Path, marca: str = "anotus") -> dict:
    cenas = cenas_de(roteiro_md)
    if not cenas:
        raise ValueError("roteiro sem cenas (## Cenas com itens numerados)")
    avisos = []
    if len(cenas) > 8:
        avisos.append(f"{len(cenas)} cenas — animatic usa as 8 primeiras"); cenas = cenas[:8]
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError(f"playwright não instalado ({type(e).__name__}): pip install playwright && playwright install chromium")
    marca = (marca or "anotus").strip().lower()
    pal = PALETAS.get(marca, PALETAS["neutra"])
    tmp = Path(dst_png).with_suffix(".cenas"); tmp.mkdir(parents=True, exist_ok=True)
    pngs = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=2).new_page()
            for i, c in enumerate(cenas):
                pg.set_content(_html_cena(c, len(cenas), pal))
                pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(50)
                png = tmp / f"c_{i:02d}.png"; pg.screenshot(path=str(png)); pngs.append(png)
            b.close()
        lista = tmp / "lista.txt"; _lista_concat(pngs, lista)
        _ff(["-f", "concat", "-safe", "0", "-i", str(lista), "-vf", "scale=270:480,tile=4x2:color=black", "-frames:v", "1", str(dst_png)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"png": str(dst_png), "cenas": len(cenas), "avisos": avisos}


def _cli(ns):
    if ns.cmd == "analisar":
        return analisar(Path(ns.video), Path(ns.proj), Path(ns.transcript) if ns.transcript else None), 0
    try:
        if ns.cmd == "baixar":
            return baixar(ns.origem, Path(ns.dst_dir)), 0
        return animatic(Path(ns.roteiro), Path(ns.dst), marca=ns.marca), 0
    except ValueError as e:
        return {"erro": str(e)}, 1


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="vídeo de referência")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("baixar"); p.add_argument("origem"); p.add_argument("dst_dir")
    p = sub.add_parser("analisar"); p.add_argument("video"); p.add_argument("proj"); p.add_argument("--transcript")
    p = sub.add_parser("animatic"); p.add_argument("roteiro"); p.add_argument("dst"); p.add_argument("--marca", default="anotus")
    ns = ap.parse_args()
    try:
        out, code = _cli(ns)
    except Exception as e:
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
