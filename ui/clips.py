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


GANCHO_RE = {
    "pergunta": re.compile(r"\?"),
    "número": re.compile(r"\b\d+([.,]\d+)?\b|\b(mil|milh[ãa]o|milh[õo]es)\b", re.I),
    "primeira pessoa": re.compile(r"\b(eu|minha|meu|comigo)\b", re.I),
    "absoluto": re.compile(r"\b(sempre|nunca|todo|toda|todos|ningu[ée]m|nada)\b", re.I),
}
DEITICO_RE = re.compile(r"\b(isso|esse|essa|aqui|aquilo|ele|ela|disso|desse|dessa)\b", re.I)


def _texto(words, i0, i1):
    return " ".join(w["w"] for w in words[i0:i1 + 1])


def _score(words, i0, i1, fr_fim_pausa: float) -> tuple[float, list[str]]:
    t0, t1 = words[i0]["t"], words[i1]["e"]
    dur = t1 - t0
    ini = " ".join(w["w"] for w in words[i0:i1 + 1] if w["t"] < t0 + 3.0)
    motivos, g = [], 0.0
    for nome, rx in GANCHO_RE.items():
        if rx.search(ini):
            motivos.append(nome); g += 0.5
    gancho = min(1.0, g)
    fim = words[i1]["w"].endswith(PONT_FIM)
    fechamento = 1.0 if (fim and fr_fim_pausa >= 0.8) else 0.6 if fim else 0.2
    if fim: motivos.append("fecha em ponto")
    wps = (i1 - i0 + 1) / dur if dur else 0
    densidade = 1.0 if 2.0 <= wps <= 3.5 else max(0.0, 1.0 - abs(wps - 2.75) / 2.75)
    ini2 = " ".join(w["w"] for w in words[i0:i1 + 1] if w["t"] < t0 + 2.0)
    autonomia = 0.0 if DEITICO_RE.search(ini2) else 1.0
    if autonomia: motivos.append("autônomo")
    return round(0.35 * gancho + 0.25 * fechamento + 0.20 * densidade + 0.20 * autonomia, 4), motivos


def candidatos(words: list[dict], n: int = 20, min_s: float = 25, max_s: float = 60) -> list[dict]:
    fr = frases(words)
    if not fr:
        return []
    janelas = []
    for a in range(len(fr)):
        # começa só após pausa, após pontuação final (ou no início)
        if a > 0 and fr[a]["t"] - fr[a - 1]["e"] < 0.3 and not words[fr[a - 1]["palavras"][-1]]["w"].endswith(PONT_FIM):
            continue
        for b in range(a, len(fr)):
            dur = fr[b]["e"] - fr[a]["t"]
            if dur > max_s: break
            if dur < min_s: continue
            i0, i1 = fr[a]["palavras"][0], fr[b]["palavras"][-1]
            pausa_fim = (fr[b + 1]["t"] - fr[b]["e"]) if b + 1 < len(fr) else 9.9
            sc, motivos = _score(words, i0, i1, pausa_fim)
            if a > 0: motivos.insert(0, "pausa antes")
            janelas.append({"t_in": round(words[i0]["t"] - PAD_IN, 3), "t_out": round(words[i1]["e"] + PAD_OUT, 3),
                            "texto": _texto(words, i0, i1), "score": sc, "motivos": motivos})
    janelas.sort(key=lambda j: -j["score"])
    out = []
    for j in janelas:
        dj = j["t_out"] - j["t_in"]
        if any((min(j["t_out"], o["t_out"]) - max(j["t_in"], o["t_in"])) / min(dj, o["t_out"] - o["t_in"]) > 0.6
               for o in out):
            continue
        out.append(j)
        if len(out) >= n: break
    return out
