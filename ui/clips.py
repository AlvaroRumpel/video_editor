"""Clip Factory: palavras na timeline do export, candidatos a Short por
heurística, validação do clips.json curado, EDLs por clipe×plataforma e
render via render.py. Sem FastAPI."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = pipeline.ROOT
RENDER = ROOT / "video-use" / "helpers" / "render.py"
PAD_IN, PAD_OUT = 0.050, 0.080
PONT_FIM = (".", "!", "?")


def words_out(edl: dict, transcript: dict, real: list[float]) -> list[dict]:
    words = [w for w in transcript.get("words", []) if w.get("type") == "word"]
    out, offset = [], 0.0
    for idx, r in enumerate(edl.get("ranges", [])):
        s, e = float(r["start"]), float(r["end"])
        for w in words:
            if w["start"] >= s - 0.01 and w["end"] <= e + 0.01:
                out.append({"t": round(w["start"] - s + offset, 3), "e": round(w["end"] - s + offset, 3),
                            "w": w["text"].strip()})
        offset += float(real[idx]) if idx < len(real) else (e - s)
    out.sort(key=lambda x: x["t"])
    return out


def frases(words: list[dict], pausa: float = 0.6) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and (w["t"] - words[cur[-1]]["e"] >= pausa or words[cur[-1]]["w"].endswith(PONT_FIM)):
            out.append(cur); cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return [{"t": words[ix[0]]["t"], "e": words[ix[-1]]["e"],
             "texto": " ".join(words[i]["w"] for i in ix), "palavras": ix} for ix in out]
