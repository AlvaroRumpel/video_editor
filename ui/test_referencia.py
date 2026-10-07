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


pytest_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def video3cortes(tmp_path) -> Path:
    """9 s vertical: vermelho 0–3, verde-lima 3–6 (luma ≠ vermelho; scdet é por luma), azul 6–9; áudio tom 1 kHz."""
    p = tmp_path / "ref.mp4"
    _ff("-f", "lavfi", "-i", "color=c=red:s=540x960:r=30:d=3", "-f", "lavfi", "-i", "color=c=lime:s=540x960:r=30:d=3",
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
