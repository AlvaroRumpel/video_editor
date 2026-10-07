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
