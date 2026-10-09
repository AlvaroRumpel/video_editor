"""Ponta a ponta com HyperFrames real e TTS falso. Lento e opt-in: NARRADO_E2E=1."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import budget
import motion
import narrado

pytestmark = pytest.mark.skipif(
    not os.environ.get("NARRADO_E2E") or not (motion.MOTION / "node_modules" / "hyperframes").is_dir()
    or shutil.which("ffmpeg") is None, reason="e2e opt-in (NARRADO_E2E=1) e precisa de motion/node_modules")


def test_episodio_minimo_vira_final_1920x1080_com_voz(tmp_path, monkeypatch):
    p = tmp_path / "001-e2e"
    (p / "assets").mkdir(parents=True)
    Image.new("RGB", (1600, 1000), (90, 80, 60)).save(p / "assets" / "foto.png")
    (p / "pesquisa.md").write_text(
        "## Achados\n\n- [F1] Fato — fonte: BBC (secundaria) — https://www.bbc.com/x — acesso 2026-10-08\n  > t\n",
        encoding="utf-8")
    ep = {"id": "001-e2e", "marca": "dark-historia", "titulo": {"pt": "Teste"}, "cenas": [
        {"id": "c01", "texto": {"pt": "Primeira cena."}, "fontes": ["F1"],
         "visual": {"tipo": "arquivo", "src": "assets/foto.png", "fonte_url": "https://x", "licenca": "CC0",
                    "credito": "Autor"}, "overlay": {"pt": "Sibéria, 1908"}},
        {"id": "c02", "texto": {"pt": "Segunda cena."}, "fontes": [],
         "visual": {"tipo": "motion", "cena": {"tipo": "frase", "fundo": "escuro",
                                              "linhas": [{"t": {"pt": "Ninguém viu."}}]}}}]}
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    som = tmp_path / "s.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=2", "-c:a", "libmp3lame", str(som)],
                   check=True)
    root = tmp_path / "ve"
    (root / "ui").mkdir(parents=True)
    shutil.copy(Path(narrado.__file__).parent / "precos.json", root / "ui" / "precos.json")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "teste")
    monkeypatch.setattr(budget, "saldo_elevenlabs", lambda root, **k: {"usados": 0, "limite": 10**6,
                                                                        "restante": 10**6, "reset_ts": 0})
    assert narrado.tts(p, "pt", "v", root=root, _fetch=lambda k, u, b: som.read_bytes())["status"] == "ok"
    r = narrado.render(p, "pt", rascunho=True)
    assert r["ok"], r
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                          "-of", "json", r["video"]], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"]
    assert any(x.get("width") == 1920 and x.get("height") == 1080 for x in s)
    assert any(x["codec_type"] == "audio" for x in s)
    keep = os.environ.get("NARRADO_E2E_KEEP")      # copiar o vídeo para inspeção visual
    if keep:
        shutil.copy(r["video"], keep)
