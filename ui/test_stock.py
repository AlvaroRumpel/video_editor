# ui/test_stock.py
import json
import shutil
import subprocess
from pathlib import Path
import pytest
import stock

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def mp4(tmp_path) -> bytes:
    p = tmp_path / "src.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast", str(p))
    return p.read_bytes()


@pytest.fixture
def jpg(tmp_path) -> bytes:
    p = tmp_path / "src.jpg"
    _ff("-f", "lavfi", "-i", "testsrc=s=2560x1440:d=1", "-frames:v", "1", str(p))
    return p.read_bytes()


PEXELS_VIDEOS = {"videos": [
    {"id": 1, "duration": 12, "width": 1920, "height": 1080, "url": "https://www.pexels.com/video/1/",
     "user": {"name": "Ana"}, "video_files": [
         {"width": 1280, "height": 720, "link": "https://cdn/1-720.mp4", "file_type": "video/mp4"},
         {"width": 1920, "height": 1080, "link": "https://cdn/1-1080.mp4", "file_type": "video/mp4"},
         {"width": 3840, "height": 2160, "link": "https://cdn/1-4k.mp4", "file_type": "video/mp4"}]},
    {"id": 2, "duration": 45, "width": 1920, "height": 1080, "url": "https://www.pexels.com/video/2/",
     "user": {"name": "Bo"}, "video_files": [{"width": 1920, "height": 1080, "link": "https://cdn/2.mp4", "file_type": "video/mp4"}]},
    {"id": 3, "duration": 8, "width": 640, "height": 360, "url": "https://www.pexels.com/video/3/",
     "user": {"name": "Cy"}, "video_files": [{"width": 640, "height": 360, "link": "https://cdn/3.mp4", "file_type": "video/mp4"}]},
    {"id": 4, "duration": 8, "width": 1080, "height": 1920, "url": "https://www.pexels.com/video/4/",
     "user": {"name": "Di"}, "video_files": [{"width": 1080, "height": 1920, "link": "https://cdn/4.mp4", "file_type": "video/mp4"}]},
]}
PIXABAY_VIDEOS = {"hits": [
    {"id": 77, "duration": 10, "pageURL": "https://pixabay.com/videos/77/", "user": "Eve",
     "videos": {"large": {"url": "https://cdn/77-l.mp4", "width": 1920, "height": 1080},
                "medium": {"url": "https://cdn/77-m.mp4", "width": 1280, "height": 720}}}]}
PEXELS_FOTOS = {"photos": [
    {"id": 9, "width": 4000, "height": 2667, "url": "https://www.pexels.com/photo/9/",
     "photographer": "Fi", "src": {"original": "https://cdn/9.jpg", "large2x": "https://cdn/9-2x.jpg"}},
    {"id": 10, "width": 1200, "height": 800, "url": "https://www.pexels.com/photo/10/",
     "photographer": "Gu", "src": {"original": "https://cdn/10.jpg", "large2x": "https://cdn/10-2x.jpg"}},
]}


def _fetch_factory(mp4, jpg, extra=None):
    chamadas = []
    def fetch(url, headers=None):
        chamadas.append((url, headers or {}))
        if extra and url in extra:
            return extra[url]
        if "api.pexels.com/videos" in url:
            return 200, json.dumps(PEXELS_VIDEOS).encode(), {}
        if "api.pexels.com/v1" in url:
            return 200, json.dumps(PEXELS_FOTOS).encode(), {}
        if "pixabay.com/api/videos" in url:
            return 200, json.dumps(PIXABAY_VIDEOS).encode(), {}
        if url.endswith(".mp4"):
            return 200, mp4, {}
        if url.endswith(".jpg"):
            return 200, jpg, {}
        return 404, b"", {}
    fetch.chamadas = chamadas
    return fetch


@pytest.fixture
def chaves(monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "PK", "pixabay": "XK", "unsplash": ""})


def test_buscar_pexels_filtra_e_baixa(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg)
    dst = tmp_path / "proj" / "broll" / "cand"
    r = stock.buscar("courthouse", "video", ["pexels"], 3, dst, _fetch=fetch)
    ids = [c["id"] for c in r["candidatos"]]
    assert ids == ["1"]                                  # 2 longo, 3 pequeno, 4 vertical
    c = r["candidatos"][0]
    assert c["fonte"] == "pexels" and c["autor"] == "Ana" and c["tipo"] == "video"
    assert c["dur"] == 12 and c["largura"] == 1920 and c["licenca"] == "Pexels License"
    assert c["arq"] == "broll/cand/pexels-1.mp4" and (dst / "pexels-1.mp4").exists()
    assert json.loads((dst / "pexels-1.json").read_text(encoding="utf-8"))["url"] == "https://www.pexels.com/video/1/"
    baixados = [u for u, _ in fetch.chamadas if u.endswith(".mp4")]
    assert baixados == ["https://cdn/1-1080.mp4"]        # menor variante >= 1920
    api = [h for u, h in fetch.chamadas if "api.pexels.com" in u][0]
    assert api.get("Authorization") == "PK"


def test_buscar_pixabay_e_n_por_fonte(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg)
    r = stock.buscar("court", "video", ["pexels", "pixabay"], 1, tmp_path / "c", _fetch=fetch)
    assert [c["fonte"] for c in r["candidatos"]] == ["pexels", "pixabay"]
    px = r["candidatos"][1]
    assert px["id"] == "77" and px["autor"] == "Eve" and px["licenca"] == "Pixabay Content License"
    assert [u for u, _ in fetch.chamadas if "77" in u and u.endswith(".mp4")] == ["https://cdn/77-l.mp4"]


def test_buscar_fotos_pexels(tmp_path, mp4, jpg, chaves):
    r = stock.buscar("court", "foto", ["pexels"], 3, tmp_path / "c", _fetch=_fetch_factory(mp4, jpg))
    assert [c["id"] for c in r["candidatos"]] == ["9"]   # 10 tem largura < 1920
    assert r["candidatos"][0]["tipo"] == "foto" and r["candidatos"][0]["arq"].endswith("pexels-9.jpg")


def test_buscar_sem_chave_pula(tmp_path, mp4, jpg, monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "", "pixabay": "", "unsplash": ""})
    fetch = _fetch_factory(mp4, jpg)
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("pexels" in a and "chave" in a for a in r["avisos"])
    assert fetch.chamadas == []


def test_buscar_corpo_vazio_descarta(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={"https://cdn/1-1080.mp4": (200, b"", {})})
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("vazio" in a for a in r["avisos"])
    assert not (tmp_path / "c" / "pexels-1.mp4").exists()


def test_chaves_env(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "abc")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr(stock, "_ler_env", lambda: {})
    k = stock.chaves()
    assert k["pexels"] == "abc" and k["pixabay"] == ""


def test_download_gigante_descarta(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={"https://cdn/1-1080.mp4": (200, b"x" * (stock.MAX_DOWNLOAD + 1), {})})
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("150 MB" in a for a in r["avisos"])
    assert not (tmp_path / "c" / "pexels-1.mp4").exists()


def test_aviso_nao_vaza_chave(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={})
    base = fetch
    def f(url, headers=None):
        if "pixabay.com/api/videos" in url:
            return 500, b"", {}
        return base(url, headers)
    r = stock.buscar("x", "video", ["pixabay"], 3, tmp_path / "c", _fetch=f)
    assert any("pixabay.com/api/videos/" in a for a in r["avisos"])
    assert not any("XK" in a for a in r["avisos"])
