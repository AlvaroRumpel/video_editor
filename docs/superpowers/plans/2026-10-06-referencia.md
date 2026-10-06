# Vídeo de referência — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ui/referencia.py` baixa (yt-dlp/arquivo) e analisa um vídeo de referência (cortes, keyframes, áudio, fala), gera animatics de roteiros de conceito; servidor/UI ganham o tipo `referencia` e servem os PNGs; receita `Formatos/referencia.md` fixa o fluxo A/B/C.

**Architecture:** Módulo no molde de `stock.py` (stdlib + ffmpeg por subprocess; `_run` injetável para yt-dlp; Playwright Python importado tarde só em `animatic`). Transcrição fica na receita (video-use, orçamento). UI reaproveita `/api/file`, o modal Docs e o padrão das linhas de estado.

**Tech Stack:** Python 3 stdlib, ffmpeg 9 (`scdet`, `ebur128`, `silencedetect`, `astats`, `tile`, `drawtext`), `yt_dlp` (instalação do usuário), `playwright` (já instalado), pytest, JS vanilla.

**Spec:** `docs/superpowers/specs/2026-10-06-referencia-design.md`

## Global Constraints

- Nunca copiar código do OpenMontage. `video-use/` não é alterado. `bruto/` é ignorado pelo git (referências nunca commitadas).
- Sem dependência nova no `requirements.txt`; `yt_dlp` e `playwright` importados tarde, com erro explícito se ausentes.
- `baixar` URL: `[sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--write-info-json", "--no-playlist", "-o", "<dst>/<slug>.%(ext)s", url]`; stderr com `login`/`cookies`/`rate-limit` → erro "baixe à mão em bruto/ref/ e passe o arquivo".
- `cortes`: `scdet=t=<limiar>` (padrão 10), sempre inclui `0.0`, dedupe < 0,2 s.
- `keyframes`: < 4 cortes → tempos a cada 2 s; frame em `t + 0.1`; tiles 320×568; `tile=6xR`; rótulo `t=12.4s`.
- `audio`: `lufs` por `ebur128`; `fala_pct` por `highpass=f=200,lowpass=f=3400,silencedetect=n=-35dB:d=0.3`; `musica` = RMS de `bandreject=f=1000:w=2600` > −40 dB.
- `analise.json` com as chaves do spec; `fala: null` sem transcript.
- `animatic`: 540×960 CSS, `deviceScaleFactor=2`, paleta Anotus (`#F3F2FA`, `#2B215C`, `#D4A017`, Fraunces/Inter com fallback), máx. 8 cenas, `tile=4x2`, saída `dst_png`.
- Servidor: tipo `referencia` (`target = {origem, marca, nome, briefing}`; 400 sem `origem` ou `nome`); `/api/brutos-ref`; `FILE_NAME = ^(broll|ref)/[\w\-]+\.png$|^animatic-[A-Z]\.png$`, path resolvido dentro do projeto.
- CLI: JSON stdout UTF-8; exit 0 / 1 validação / 2 execução.
- Testes: mídia sintética em `tmp_path`, `_run` injetado, nunca rede; `skipif` sem ffmpeg; `animatic` `skipif` sem Playwright/chromium.

## Review Focus

1. URL de playlist ou canal (não um vídeo) → `baixar` passa `--no-playlist` e o slug cai no hash; não explode (teste na Task 1).
2. Vídeo sem faixa de áudio em `audio()` → devolve `{"lufs": null, "fala_pct": 0.0, "musica": false}` sem exceção (teste na Task 2).
3. Vídeo de 3 s (menor que a janela de keyframes) → `keyframes` gera ≥ 1 tile, não grade vazia (teste na Task 2).
4. Roteiro com mais de 8 cenas → `animatic` usa as 8 primeiras e avisa (teste na Task 3).
5. Nome de arquivo `animatic-a.png` (minúsculo) ou `ref/../x.png` no `/api/file` → 400 (teste na Task 4).

---

### Task 1: `referencia.py` — `slug_de` e `baixar`

**Files:**
- Create: `ui/referencia.py`
- Test: `ui/test_referencia.py`

**Interfaces:**
- Produces:
  - `slug_de(origem: str) -> str`
  - `baixar(origem: str, dst_dir: Path, _run=None) -> dict` (`_run(cmd) -> CompletedProcess`-like com `returncode`, `stderr`)
  - `_tem_modulo(nome) -> bool`

- [ ] **Step 1: Testes que falham**

```python
# ui/test_referencia.py
import json
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
import referencia


@pytest.mark.parametrize("origem,esperado", [
    ("https://www.youtube.com/shorts/AbC-12_xyz", "AbC-12_xyz"),
    ("https://www.instagram.com/reel/CxYz123abc/?utm=1", "CxYz123abc"),
    ("https://www.tiktok.com/@user/video/7301234567890123456", "7301234567890123456"),
])
def test_slug_de_urls(origem, esperado):
    assert referencia.slug_de(origem) == esperado


def test_slug_de_arquivo_e_url_desconhecida(tmp_path):
    assert referencia.slug_de(str(tmp_path / "Meu Vídeo (1).MP4")) == "meu-video-1"
    s = referencia.slug_de("https://example.com/watch?v=abc&list=xyz")
    assert s.startswith("ref-") and len(s) == 12


def test_baixar_arquivo_local(tmp_path):
    src = tmp_path / "Reel Teste.mp4"; src.write_bytes(b"\x00" * 10)
    dst = tmp_path / "ref"
    r = referencia.baixar(str(src), dst)
    assert (dst / "reel-teste.mp4").read_bytes() == b"\x00" * 10
    meta = json.loads((dst / "reel-teste.json").read_text(encoding="utf-8"))
    assert meta["origem"] == "arquivo" and meta["plataforma"] == "arquivo" and r["slug"] == "reel-teste"
    assert "baixado_em" in meta


def test_baixar_url_monta_comando_e_le_info(tmp_path, monkeypatch):
    monkeypatch.setattr(referencia, "_tem_modulo", lambda n: True)
    dst = tmp_path / "ref"
    chamadas = []
    def run(cmd):
        chamadas.append(cmd)
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "AbC-12_xyz.mp4").write_bytes(b"v")
        (dst / "AbC-12_xyz.info.json").write_text(json.dumps({
            "uploader": "Fulano", "title": "Título", "duration": 31.2, "upload_date": "20260901",
            "webpage_url": "https://www.youtube.com/shorts/AbC-12_xyz", "extractor_key": "Youtube"}), encoding="utf-8")
        class R: returncode = 0; stderr = ""; stdout = ""
        return R()
    r = referencia.baixar("https://www.youtube.com/shorts/AbC-12_xyz", dst, _run=run)
    cmd = chamadas[0]
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"] and "--no-playlist" in cmd and "--write-info-json" in cmd
    assert any(a.endswith("AbC-12_xyz.%(ext)s") for a in cmd) and cmd[-1].startswith("https://")
    meta = json.loads((dst / "AbC-12_xyz.json").read_text(encoding="utf-8"))
    assert meta == {"origem": "url", "url": "https://www.youtube.com/shorts/AbC-12_xyz", "plataforma": "Youtube",
                    "autor": "Fulano", "titulo": "Título", "dur": 31.2, "publicado": "2026-09-01",
                    "baixado_em": meta["baixado_em"], "slug": "AbC-12_xyz", "arquivo": "AbC-12_xyz.mp4"}
    assert r["arquivo"] == "AbC-12_xyz.mp4"


def test_baixar_playlist_e_login(tmp_path, monkeypatch):
    monkeypatch.setattr(referencia, "_tem_modulo", lambda n: True)
    def run_login(cmd):
        class R: returncode = 1; stderr = "ERROR: [Instagram] login required (cookies)"; stdout = ""
        return R()
    with pytest.raises(RuntimeError, match="baixe à mão"):
        referencia.baixar("https://www.instagram.com/reel/CxYz123abc/", tmp_path / "ref", _run=run_login)
    def run_ok(cmd):
        d = tmp_path / "ref"; d.mkdir(exist_ok=True)
        slug = referencia.slug_de("https://www.youtube.com/playlist?list=PL123")
        (d / f"{slug}.mp4").write_bytes(b"v")
        class R: returncode = 0; stderr = ""; stdout = ""
        return R()
    r = referencia.baixar("https://www.youtube.com/playlist?list=PL123", tmp_path / "ref", _run=run_ok)
    assert r["slug"].startswith("ref-")                 # sem info.json → metadados mínimos, sem exceção


def test_baixar_sem_ytdlp(tmp_path, monkeypatch):
    monkeypatch.setattr(referencia, "_tem_modulo", lambda n: False)
    with pytest.raises(RuntimeError, match="pip install yt-dlp"):
        referencia.baixar("https://www.youtube.com/shorts/x", tmp_path / "ref", _run=lambda c: None)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_referencia.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'referencia'`

- [ ] **Step 3: Implementar**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd ui && python -m pytest test_referencia.py -v`
Expected: 8 PASS (parametrize conta 3)

- [ ] **Step 5: Commit**

```bash
git add ui/referencia.py ui/test_referencia.py
git commit -m "feat(referencia): slug e download por yt-dlp ou arquivo local"
```

---

### Task 2: `cortes`, `keyframes`, `audio`, `fala`, `analisar`

**Files:**
- Modify: `ui/referencia.py`
- Test: `ui/test_referencia.py`

**Interfaces:**
- Consumes: `pipeline.phrases_from_transcript`.
- Produces: `_ff(args) -> str`, `duracao(path) -> float`, `dims(path) -> (w, h)`, `cortes(video, limiar=10) -> list[float]`, `keyframes(video, tempos, dst_png, max_n=24) -> dict` (`{"png","n","colunas","linhas"}`), `audio(video) -> dict`, `fala(transcript) -> dict`, `analisar(video, proj, transcript_json=None) -> dict`.

- [ ] **Step 1: Testes que falham**

```python
# acrescentar em ui/test_referencia.py
pytest_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def video3cortes(tmp_path) -> Path:
    """9 s vertical: vermelho 0–3, verde 3–6, azul 6–9; áudio tom 1 kHz."""
    p = tmp_path / "ref.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=540x960:r=30:d=3", "-f", "lavfi", "-i", "color=c=green:s=540x960:r=30:d=3",
        "-f", "lavfi", "-i", "color=c=blue:s=540x960:r=30:d=3", "-f", "lavfi", "-i", "sine=f=1000:r=48000:d=9",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(p))
    return p


@pytest_ffmpeg
def test_cortes(video3cortes):
    c = referencia.cortes(video3cortes)
    assert c[0] == 0.0 and len(c) == 3
    assert abs(c[1] - 3.0) < 0.15 and abs(c[2] - 6.0) < 0.15


@pytest_ffmpeg
def test_keyframes_grade(video3cortes, tmp_path):
    r = referencia.keyframes(video3cortes, [0.0, 3.0, 6.0], tmp_path / "s.png")
    assert (r["colunas"], r["linhas"], r["n"]) == (5, 1, 5)          # < 4 cortes → a cada 2 s: 0,2,4,6,8
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(tmp_path / "s.png")], capture_output=True, text=True).stdout.strip()
    assert out == "1600,568"
    r2 = referencia.keyframes(video3cortes, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0], tmp_path / "s2.png")
    assert (r2["colunas"], r2["linhas"], r2["n"]) == (6, 2, 7)


@pytest_ffmpeg
def test_keyframes_video_curto(tmp_path):
    p = tmp_path / "c.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=540x960:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast", str(p))
    r = referencia.keyframes(p, [0.0], tmp_path / "c.png")
    assert r["n"] >= 1


@pytest_ffmpeg
def test_audio_tom_vs_ruido(tmp_path, video3cortes):
    a = referencia.audio(video3cortes)
    assert a["musica"] is False and a["fala_pct"] > 0.9 and a["lufs"] is not None
    p = tmp_path / "ruido.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=540x960:r=30:d=6", "-f", "lavfi", "-i", "sine=f=1000:r=48000:d=6",
        "-f", "lavfi", "-i", "anoisesrc=a=0.1:c=white:r=48000:d=6:seed=1",
        "-filter_complex", "[1:a][2:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(p))
    assert referencia.audio(p)["musica"] is True
    mudo = tmp_path / "mudo.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=540x960:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast", "-an", str(mudo))
    assert referencia.audio(mudo) == {"lufs": None, "fala_pct": 0.0, "musica": False}


def _tr(frases, gap=0.6):
    words, t = [], 0.0
    for f in frases:
        for w in f.split():
            words.append({"text": w, "start": round(t, 3), "end": round(t + 0.2, 3), "type": "word"}); t += 0.25
        t += gap
    return {"words": words}


def test_fala():
    tr = _tr(["Você sabe por que isso acontece?", "a resposta é simples", "me segue pra mais", "link na bio"])
    f = referencia.fala(tr)
    assert f["gancho_2s"].startswith("Você sabe por que")
    assert f["cta"].endswith("link na bio") and "me segue" in f["cta"]
    assert 2.5 < f["wps"] < 4.5 and f["pausas_por_min"] > 0 and f["dur_fala"] > 3


@pytest_ffmpeg
def test_analisar(video3cortes, tmp_path):
    proj = tmp_path / "proj"
    tr = tmp_path / "t.json"; tr.write_text(json.dumps(_tr(["oi gente", "tchau"])), encoding="utf-8")
    a = referencia.analisar(video3cortes, proj, tr)
    salvo = json.loads((proj / "ref" / "analise.json").read_text(encoding="utf-8"))
    assert salvo == a and set(a) >= {"video", "dur", "largura", "altura", "fala", "cortes", "plano_medio_s",
                                     "cortes_por_min", "audio", "sheet", "transcript"}
    assert (a["largura"], a["altura"]) == (540, 960) and (proj / "ref" / "sheet.png").exists()
    assert referencia.analisar(video3cortes, proj)["fala"] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_referencia.py -v -k "cortes or keyframes or audio or fala or analisar"`
Expected: FAIL

- [ ] **Step 3: Implementar**

```python
# acrescentar em ui/referencia.py
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
    ts = [float(m) for m in re.findall(r"lavfi\.scd\.time=([\d.]+)", err)]
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
    ff = f",drawtext=fontfile='{_rotulo(FONTE.as_posix())}'" if FONTE.exists() else ",drawtext="
    pngs = []
    for i, t in enumerate(tempos):
        png = tmp / f"k_{i:03d}.png"
        vf = (f"scale=320:568:force_original_aspect_ratio=decrease,pad=320:568:(ow-iw)/2:(oh-ih)/2"
              f"{ff}:text='{_rotulo(f't={t:.1f}s')}':x=6:y=h-24:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6")
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
    err = _ff(["-i", str(video), "-vn", "-af", "bandreject=f=1000:w=2600,astats=measure_perchannel=none:measure_overall=RMS_level",
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
```

Se o `ebur128` não imprimir `I:` com `framelog=quiet` no ffmpeg 9, use `ebur128=peak=none` e procure a linha `Integrated loudness:` seguida de `I: -14.2 LUFS`.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd ui && python -m pytest test_referencia.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add ui/referencia.py ui/test_referencia.py
git commit -m "feat(referencia): cortes (scdet), keyframes, áudio (ebur128/banda de voz), fala e analise.json"
```

---

### Task 3: `cenas_de`, `animatic` e CLI

**Files:**
- Modify: `ui/referencia.py`
- Test: `ui/test_referencia.py`

**Interfaces:**
- Produces: `cenas_de(roteiro_md: Path) -> list[{"n","texto","sfx"}]`, `animatic(roteiro_md, dst_png, marca="anotus") -> {"png","cenas","avisos"}`, CLI `baixar | analisar | animatic`.

- [ ] **Step 1: Testes que falham**

```python
# acrescentar em ui/test_referencia.py
ROTEIRO = """# Roteiro — teste
<!-- formato: ads -->

## Hook (≤ 2 s)
Você perde prazo?

## Cenas
1. Tela: "Prazo é de 15 dias úteis" [F1]
   sfx: pop-dourado
2. Flashcard aparece com a regra
3. Pergunta na tela: e o recesso?

## CTA
Teste grátis — link na bio
"""


def test_cenas_de(tmp_path):
    p = tmp_path / "r.md"; p.write_text(ROTEIRO, encoding="utf-8")
    c = referencia.cenas_de(p)
    assert [x["n"] for x in c] == [1, 2, 3]
    assert c[0]["texto"].startswith('Tela: "Prazo') and c[0]["sfx"] == "pop-dourado" and c[1]["sfx"] is None
    assert "[F1]" not in c[0]["texto"]
    p2 = tmp_path / "vazio.md"; p2.write_text("# nada\n", encoding="utf-8")
    assert referencia.cenas_de(p2) == []


def _tem_chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(); b.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(shutil.which("ffmpeg") is None or not _tem_chromium(), reason="sem ffmpeg/chromium")
def test_animatic(tmp_path):
    p = tmp_path / "roteiro-A.md"; p.write_text(ROTEIRO, encoding="utf-8")
    r = referencia.animatic(p, tmp_path / "animatic-A.png")
    assert r["cenas"] == 3 and (tmp_path / "animatic-A.png").exists()
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(tmp_path / "animatic-A.png")], capture_output=True, text=True).stdout.strip()
    assert out == "1080,960"


@pytest.mark.skipif(shutil.which("ffmpeg") is None or not _tem_chromium(), reason="sem ffmpeg/chromium")
def test_animatic_mais_de_8_cenas(tmp_path):
    md = "## Cenas\n" + "".join(f"{i}. cena {i}\n" for i in range(1, 11))
    p = tmp_path / "r.md"; p.write_text(md, encoding="utf-8")
    r = referencia.animatic(p, tmp_path / "a.png")
    assert r["cenas"] == 8 and any("8" in a for a in r["avisos"])


def test_animatic_sem_cenas(tmp_path):
    p = tmp_path / "r.md"; p.write_text("# x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sem cenas"):
        referencia.animatic(p, tmp_path / "a.png")


def test_cli(tmp_path):
    exe = [sys.executable, str(Path(referencia.__file__))]
    r = subprocess.run([*exe, "analisar", str(tmp_path / "nao.mp4"), str(tmp_path / "p")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "erro" in json.loads(r.stdout)
    p = tmp_path / "r.md"; p.write_text("# x\n", encoding="utf-8")
    r = subprocess.run([*exe, "animatic", str(p), str(tmp_path / "a.png")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "sem cenas" in json.loads(r.stdout)["erro"]
    src = tmp_path / "v.mp4"; src.write_bytes(b"0")
    r = subprocess.run([*exe, "baixar", str(src), str(tmp_path / "ref")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and json.loads(r.stdout)["slug"] == "v"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_referencia.py -v -k "cenas or animatic or cli"`
Expected: FAIL

- [ ] **Step 3: Implementar**

```python
# acrescentar em ui/referencia.py
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
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
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
    pal = PALETAS.get(marca, PALETAS["neutra"])
    tmp = Path(dst_png).with_suffix(".cenas"); tmp.mkdir(parents=True, exist_ok=True)
    pngs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=2).new_page()
        for i, c in enumerate(cenas):
            pg.set_content(_html_cena(c, len(cenas), pal)); pg.wait_for_timeout(100)
            png = tmp / f"c_{i:02d}.png"; pg.screenshot(path=str(png)); pngs.append(png)
        b.close()
    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{p.as_posix()}'\n" for p in pngs), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", str(lista), "-vf", "scale=270:480,tile=4x2:color=black", "-frames:v", "1", str(dst_png)])
    shutil.rmtree(tmp, ignore_errors=True)
    return {"png": str(dst_png), "cenas": len(cenas), "avisos": avisos}


def _cli(ns):
    if ns.cmd == "baixar":
        return baixar(ns.origem, Path(ns.dst_dir)), 0
    if ns.cmd == "analisar":
        return analisar(Path(ns.video), Path(ns.proj), Path(ns.transcript) if ns.transcript else None), 0
    try:
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
```

`baixar` com `ValueError` (arquivo inexistente) também deve sair com 1: trate `ValueError` no `_cli` do `baixar` da mesma forma que no `animatic`.

- [ ] **Step 4: Rodar tudo**

Run: `cd ui && python -m pytest test_referencia.py -v` e depois `python -m pytest -q`
Expected: todos PASS (animatic `skip` se chromium ausente — nesta máquina o Playwright está instalado; rode `playwright install chromium` se o teste pular)

- [ ] **Step 5: Commit**

```bash
git add ui/referencia.py ui/test_referencia.py
git commit -m "feat(referencia): cenas do roteiro, animatic via Playwright e CLI"
```

---

### Task 4: Servidor + UI — tipo `referencia`, `/api/brutos-ref`, `/api/file` para `ref/` e `animatic-`, linha de estado

**Files:**
- Modify: `ui/server.py` (`QUEUE_TYPES` ~127, `FILE_NAME` ~129, `brutos` ~119, `new_project` ~208, `docs` lista PNGs), `ui/test_server.py`, `ui/static/app.js` (`openNewProjectModal` ~895–940, `renderAll` ~602, após `renderClipsInfo` ~721), `ui/static/index.html` (após `#clips-info`)

- [ ] **Step 1: Testes do servidor que falham**

```python
# acrescentar em ui/test_server.py
def test_new_project_referencia(client, fake_root):
    r = client.post("/api/new-project", json={"formato": "referencia", "origem": "https://www.youtube.com/shorts/x",
                                              "marca": "anotus", "nome": "Prazos", "descricao": "briefing"})
    e = r.json()
    assert e["type"] == "referencia" and e["target"] == {"origem": "https://www.youtube.com/shorts/x", "marca": "anotus",
                                                           "nome": "Prazos", "briefing": "briefing"}
    assert client.post("/api/new-project", json={"formato": "referencia", "nome": "x"}).status_code == 400
    assert client.post("/api/new-project", json={"formato": "referencia", "origem": "a.mp4"}).status_code == 400
    assert "referencia" in server.QUEUE_TYPES


def test_brutos_ref(client, fake_root):
    d = fake_root / "bruto" / "ref"; d.mkdir(parents=True)
    (d / "b.mp4").write_bytes(b"0"); (d / "a.mp4").write_bytes(b"0"); (d / "a.json").write_text("{}", encoding="utf-8")
    assert client.get("/api/brutos-ref").json() == ["a.mp4", "b.mp4"]


def test_file_ref_e_animatic(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "ref").mkdir(); (proj / "ref" / "sheet.png").write_bytes(b"\x89PNG")
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    assert client.get("/api/file", params={"id": "edit-fake", "name": "ref/sheet.png"}).status_code == 200
    assert client.get("/api/file", params={"id": "edit-fake", "name": "animatic-A.png"}).status_code == 200
    for nome in ("ref/../x.png", "animatic-a.png", "animatic-AB.png", "ref/x.PNG", "conceitos.png"):
        assert client.get("/api/file", params={"id": "edit-fake", "name": nome}).status_code == 400
    nomes = [x["name"] for x in client.get("/api/docs", params={"id": "edit-fake"}).json()]
    assert "ref/sheet.png" in nomes and "animatic-A.png" in nomes
```

- [ ] **Step 2: Implementar no servidor**

```python
QUEUE_TYPES = {"instrucao", "render", "borda", "veto", "roteiro", "pauta", "referencia"}
FILE_NAME = re.compile(r"^(broll|ref)/[\w\-]+\.png$|^animatic-[A-Z]\.png$")


@app.get("/api/brutos-ref")
def brutos_ref(request: Request):
    d = _root(request) / "bruto" / "ref"
    return sorted(p.name for p in d.glob("*.mp4")) if d.is_dir() else []
```

Em `file_`: resolver `path = proj / name` (o nome já é relativo validado) e exigir `path.resolve().is_relative_to(proj.resolve())` (Python ≥ 3.9) em vez de `parent == proj/broll`. Em `docs`: além de `broll/*.png`, listar `ref/*.png` (prefixo `ref/`) e `animatic-?.png` da raiz. Em `new_project`, antes de `pauta`:

```python
    if formato == "referencia":
        origem = (body.get("origem") or "").strip(); nome = (body.get("nome") or "").strip()
        if not origem or not nome:
            raise HTTPException(400, "referência exige origem (URL ou arquivo) e nome")
        return _append_queue(qpath, _make_entry("referencia",
            {"origem": origem, "marca": body.get("marca", ""), "nome": nome,
             "briefing": (body.get("descricao") or "").strip()}, f"referência: {nome}"))
```

- [ ] **Step 3: UI**

`index.html`: `<div id="ref-info" class="info-line" hidden></div>` após `#clips-info`.

`app.js` — opção no select: `<option value="referencia">referência (Reel/Short → conceitos de ad)</option>`; campos:

```html
      <label class="so-ref">URL da referência<input type="text" id="new-ref-url" placeholder="https://www.instagram.com/reel/..."></label>
      <label class="so-ref">ou arquivo em bruto/ref<select id="new-ref-arquivo"><option value="">—</option></select></label>
      <label class="so-ref">Marca<input type="text" id="new-ref-marca" placeholder="anotus"></label>
```

Em `ajustaCampos`: `const isRef = f === 'referencia';` → esconder bruto/fontes (`sel.closest('label').hidden = isRot || isPauta || isRef;` etc.), mostrar `.so-ref` só quando `isRef`, placeholder da descrição `'briefing: o que o ad precisa dizer'`; ao abrir o modal, popular `#new-ref-arquivo` com `getJSON('/api/brutos-ref')`. No `new-send`:

```js
    else if (formato === 'referencia') {
      body.origem = el('new-ref-url').value.trim() || (el('new-ref-arquivo').value ? 'bruto/ref/' + el('new-ref-arquivo').value : '');
      body.marca = el('new-ref-marca').value.trim();
      if (!body.origem || !body.nome) return; }
```

`renderRefInfo` após `renderClipsInfo`:

```js
function renderRefInfo() {
  const r = S.proj.state && S.proj.state.ref;
  const box = el('ref-info');
  if (!r) { box.hidden = true; return; }
  const n = Array.isArray(r.conceitos) ? r.conceitos.length : (r.conceitos ?? 0);
  box.textContent = `ref: ${n} conceitos` + (r.escolhido ? ` · escolhido ${r.escolhido}` : '') +
    (r.produzidos && r.produzidos.length ? ` · produzidos ${r.produzidos.join(', ')}` : '');
  box.hidden = false;
}
```
e `renderRefInfo();` em `renderAll` após `renderClipsInfo();`. Docs modal: já renderiza `.png` por `/api/file` — nada a mudar. Verificar no navegador (servidor em background, parar só o PID): Novo vídeo → `referencia` mostra URL/arquivo/marca; enviar cria entrada; `state.json` de teste com `{"ref": {"conceitos": 3, "escolhido": "B"}}` → linha aparece; reverter.

- [ ] **Step 4: Rodar a suíte e commitar**

Run: `cd ui && python -m pytest -q` → todos PASS.

```bash
git add ui/server.py ui/test_server.py ui/static/app.js ui/static/index.html
git commit -m "feat(ui): tipo referencia na fila, /api/brutos-ref, /api/file para ref/ e animatic-*, linha de estado"
```

---

### Task 5: Receita `Formatos/referencia.md` e CLAUDE.md

**Files:**
- Create: `Formatos/referencia.md`
- Modify: `ui/server.py` (`HIDDEN_FORMATS` ganha `"referencia"`), `CLAUDE.md` (bullet em "## Ciclo de um pedido" item 3 após `pauta`; frase em "## Fontes")

- [ ] **Step 1: `Formatos/referencia.md`**

```markdown
# Vídeo de referência → conceitos de ad (interno; pedido `referencia`)

Entrada: `target = {origem, marca, nome, briefing}`. Projeto: `edit/shorts/<slug-do-nome>/` com `ui/`.
Referência é inspiração de **mecanismo** (ritmo, estrutura, gancho), nunca cópia
de texto, visual ou música. `conceitos.md` registra URL e autor.

1. `python ui/referencia.py baixar "<origem>" bruto/ref` → `bruto/ref/<slug>.mp4` + `.json`.
   URL com login (Instagram) → erro "baixe à mão": pedir pela fila (`waiting_reply`) que o
   usuário coloque o arquivo em `bruto/ref/` e passe o nome.
2. Transcrição (paga): `python ui/budget.py autorizar edit/shorts/<proj> elevenlabs_scribe <minutos>`
   → `python video-use/helpers/transcribe.py bruto/ref/<slug>.mp4 --out edit/shorts/<proj>/transcripts/`
   (conferir a flag de saída no `transcribe.py --help`) → `python ui/budget.py registrar ...`.
3. `python ui/referencia.py analisar bruto/ref/<slug>.mp4 edit/shorts/<proj> --transcript edit/shorts/<proj>/transcripts/<slug>.json`.
4. Ler `ref/sheet.png` (texto na tela, enquadramento, cor), `ref/analise.json`, o briefing e
   `edit/shorts/<marca>/PAUTA.md` → `conceitos.md` no formato do spec (tabela A/B/C: ideia ·
   mantém · muda · custo créditos/R$ via `ui/precos.json` · horas · exige IA · roteiro · animatic).
   Três ângulos fixos: **A** mesmo mecanismo, outro tema; **B** mesmo tema, outro mecanismo;
   **C** o contrário do original. Cada conceito → `roteiro-X.md` no formato de ads
   (`## Hook`, `## Cenas` numeradas com `sfx:` opcional, `## CTA`, `## Cues`). Fato citado →
   `pesquisa.md` + `python ui/pesquisa.py validar edit/shorts/<proj>/pesquisa.md --roteiro edit/shorts/<proj>/roteiro-X.md`.
5. `python ui/referencia.py animatic edit/shorts/<proj>/roteiro-A.md edit/shorts/<proj>/animatic-A.png --marca <marca>` (B, C idem).
6. `waiting_reply`: "referência analisada — ver Docs › conceitos.md, animatic-A/B/C.png.
   responda `A` | `B` | `C` | `ajuste: ...` | `produzir: A B`".
7. Escolhido: copiar `roteiro-X.md` → `roteiro.md`; `state.json.ref = {"conceitos": 3, "escolhido": "X", "produzidos": []}`
   (merge); seguir `Formatos/padrao-ads.md` a partir de "Técnica de produção".
   `produzir: A B` → cada um em `edit/shorts/<proj>/<X>/` com `ui/`, `state.json.ref.produzidos += [X]`.
```

- [ ] **Step 2: `HIDDEN_FORMATS`** → `{"thumbnail", "pauta", "referencia"}`; teste em `test_server.py`: `assert "referencia" in server.HIDDEN_FORMATS`.

- [ ] **Step 3: CLAUDE.md** — após o bullet `pauta`:

```markdown
   - `referencia` — `target` = `{origem, marca, nome, briefing}`; fila global;
     seguir `Formatos/referencia.md` (baixar → analisar → conceitos A/B/C + animatic → escolha).
```

Ao fim de "## Fontes": `Vídeo de referência (Reel/Short) = inspiração de mecanismo, nunca cópia; URL e autor ficam em conceitos.md. Download só via ui/referencia.py (yt-dlp ou arquivo em bruto/ref/).`

- [ ] **Step 4: Rodar a suíte e commitar**

Run: `cd ui && python -m pytest -q` → todos PASS.

```bash
git add Formatos/referencia.md ui/server.py ui/test_server.py CLAUDE.md
git commit -m "docs(referencia): receita do fluxo referência→conceitos, tipo na fila do CLAUDE.md"
```

---

## Self-review

- **Cobertura do spec:** artefatos (T1 json/mp4, T2 analise/sheet, T3 animatic, receita T5 para conceitos/roteiros), módulo completo (T1–T3), CLI (T3), servidor/UI (T4), receita + CLAUDE.md + `HIDDEN_FORMATS` (T5), orçamento (receita passo 2), testes do spec mapeados em T1–T4.
- **Placeholders:** nenhum.
- **Tipos:** `baixar(origem, dst_dir, _run) -> dict` com `slug`/`arquivo` (T1, usado na receita); `analisar(video, proj, transcript_json)` T2/T3-CLI/receita; `animatic(roteiro_md, dst_png, marca)` T3/receita; `FILE_NAME` regex igual em T4 e spec; `target` da fila igual em T4/T5/CLAUDE.md.
- **Review Focus:** 1 → `test_baixar_playlist_e_login` (T1); 2 → `test_audio_tom_vs_ruido` (mudo) (T2); 3 → `test_keyframes_video_curto` (T2); 4 → `test_animatic_mais_de_8_cenas` (T3); 5 → `test_file_ref_e_animatic` (T4).
