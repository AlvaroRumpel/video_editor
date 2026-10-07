"""Dublagem: frases na timeline do export, tradução (preenchida pelo Claude)
validada contra glossário e tempo, TTS ElevenLabs por frase (cache + orçamento),
encaixe no tempo, remix e exports por idioma. Artefato: <proj>/dub/<lang>/dublagem.json."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import clips  # noqa: E402
import pipeline  # noqa: E402

LANG_RE = re.compile(r"[a-z]{2}")
CPS = {"es": 15.0, "en": 14.0}
CPS_PADRAO = 14.0
FOLGA = 1.15
MAX_FATOR = 1.25
MAX_FRASE_S = 12.0
PAUSA = 0.35
CAMPOS_TTS = ("trad", "audio", "hash", "dur", "fator", "estado")


def _dir(proj, lang) -> Path:
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"idioma inválido: {lang!r} (use 2 letras minúsculas, ex.: es)")
    return Path(proj) / "dub" / lang


def _ler(proj, lang) -> dict:
    p = _dir(proj, lang) / "dublagem.json"
    d = pipeline.read_json(p, None)
    if not isinstance(d, dict) or not isinstance(d.get("frases"), list):
        raise ValueError(f"{p} ausente ou inválido — rode `frases` antes")
    return d


def _gravar(proj, lang, d: dict) -> None:
    pipeline.atomic_write_json(_dir(proj, lang) / "dublagem.json", d)


def _quebra(words: list, ix: list) -> list:
    """Índices de uma frase → frases de no máx. MAX_FRASE_S (corta na palavra mais perto do meio)."""
    if len(ix) < 2 or words[ix[-1]]["e"] - words[ix[0]]["t"] <= MAX_FRASE_S:
        return [ix]
    meio = (words[ix[0]]["t"] + words[ix[-1]]["e"]) / 2
    k = min(range(1, len(ix)), key=lambda j: abs(words[ix[j]]["t"] - meio))
    return _quebra(words, ix[:k]) + _quebra(words, ix[k:])


def frases(proj, lang, words: list) -> dict:
    """Cria/atualiza dublagem.json; preserva tradução/áudio de frases com mesmo id e mesmo texto."""
    d_dir = _dir(proj, lang)
    antigo = pipeline.read_json(d_dir / "dublagem.json", {})
    antigo = antigo if isinstance(antigo, dict) else {}
    velhas = {(f.get("id"), f.get("orig")): f for f in antigo.get("frases") or [] if isinstance(f, dict)}
    out, preservadas = [], 0
    for fr in clips.frases(words, pausa=PAUSA):
        for ix in _quebra(words, fr["palavras"]):
            fid = f"f{len(out) + 1:03d}"
            orig = " ".join(words[i]["w"] for i in ix)
            f = {"id": fid, "t_in": words[ix[0]]["t"], "t_out": words[ix[-1]]["e"], "orig": orig,
                 "trad": None, "audio": None, "hash": None, "dur": None, "fator": None, "estado": "nova"}
            v = velhas.get((fid, orig))
            if v and v.get("trad"):
                f.update({k: v.get(k) for k in CAMPOS_TTS})
                preservadas += 1
            out.append(f)
    d_dir.mkdir(parents=True, exist_ok=True)
    _gravar(proj, lang, {"lang": lang, "voz": antigo.get("voz"), "frases": out})
    return {"frases": len(out), "preservadas": preservadas}


def _glossario(root) -> dict:
    g = pipeline.read_json(Path(root) / "ui" / "glossario.json", {})
    return g if isinstance(g, dict) else {}


def _tem(texto: str, termo: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(termo) + r"(?!\w)", texto, re.I) is not None


def validar(proj, lang, root=None) -> dict:
    root = root or pipeline.ROOT
    d = _ler(proj, lang)
    g = _glossario(root)
    cps = CPS.get(lang, CPS_PADRAO)
    erros, longas = [], []
    for f in d["frases"]:
        trad = (f.get("trad") or "").strip()
        if not trad:
            erros.append(f"{f['id']}: sem tradução")
            continue
        for termo, alvo in g.items():
            if not _tem(f.get("orig") or "", termo):
                continue
            esperado = termo if alvo == "manter" else (alvo.get(lang) if isinstance(alvo, dict) else None)
            if esperado and not _tem(trad, esperado):
                erros.append(f"{f['id']}: glossário — '{termo}' deve virar '{esperado}'")
        slot = float(f["t_out"]) - float(f["t_in"])
        est = len(trad) / cps
        if slot > 0 and est > FOLGA * slot:
            longas.append({"id": f["id"], "slot": round(slot, 2), "estimativa": round(est, 2)})
    return {"ok": not erros and not longas, "erros": erros, "longas": longas}


def voz(proj, root=None) -> dict:
    """Voz do projeto (state.json.dub.voz) > marca (edit/shorts/<marca>/…) > padrao."""
    root = Path(root or pipeline.ROOT)
    st = pipeline.read_json(Path(proj) / "ui" / "state.json", {})
    v = (st.get("dub") or {}).get("voz") if isinstance(st, dict) else None
    if isinstance(v, dict) and v.get("voice_id"):
        return v
    vozes = pipeline.read_json(root / "ui" / "vozes.json", {})
    vozes = vozes if isinstance(vozes, dict) else {}
    try:
        partes = Path(proj).resolve().relative_to(root.resolve()).parts
    except ValueError:
        partes = ()
    marca = partes[2] if len(partes) >= 4 and partes[:2] == ("edit", "shorts") else None
    for k in ([marca] if marca else []) + ["padrao"]:
        v = vozes.get(k)
        if isinstance(v, dict) and v.get("voice_id"):
            return v
    raise ValueError("sem voz: configure ui/vozes.json (padrao/marca) ou state.json.dub.voz")


def _ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _linhas(texto: str, largura: int = 42) -> list:
    linhas, cur = [], ""
    for p in texto.split():
        if cur and len(cur) + 1 + len(p) > largura:
            linhas.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        linhas.append(cur)
    return linhas


def srt(proj, lang) -> str:
    cues = []
    for f in _ler(proj, lang)["frases"]:
        trad = (f.get("trad") or "").strip()
        if not trad:
            continue
        ls = _linhas(trad)
        blocos = [ls[i:i + 2] for i in range(0, len(ls), 2)]
        total = sum(len(" ".join(b)) for b in blocos)
        t, span = float(f["t_in"]), float(f["t_out"]) - float(f["t_in"])
        for b in blocos:
            dt = span * len(" ".join(b)) / total
            cues.append((t, t + dt, "\n".join(b)))
            t += dt
    return "".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(cues, 1))


def words(proj, lang) -> list:
    """Pseudo-palavras traduzidas espalhadas no tempo de cada frase (formato de words_out)."""
    out = []
    for f in _ler(proj, lang)["frases"]:
        ps = (f.get("trad") or "").split()
        if not ps:
            continue
        span, total, t = float(f["t_out"]) - float(f["t_in"]), sum(len(p) for p in ps), float(f["t_in"])
        for p in ps:
            dt = span * len(p) / total
            out.append({"t": round(t, 3), "e": round(t + dt, 3), "w": p})
            t += dt
    pipeline.atomic_write_json(_dir(proj, lang) / "words.json", out)
    return out


def _abs(proj: Path, caminho: str) -> str:
    p = Path(caminho)
    return str(p if p.is_absolute() else (proj / p).resolve())


def edl(proj, lang) -> dict:
    """Copia edl.json para dub/<lang>/ com caminhos absolutos e overlays localizados quando existirem."""
    proj = Path(proj)
    e = pipeline.read_json(proj / "edl.json", None)
    if not isinstance(e, dict):
        raise ValueError("edl.json ausente ou inválido")
    e["sources"] = {k: _abs(proj, v) for k, v in (e.get("sources") or {}).items()}
    if e.get("subtitles"):
        e["subtitles"] = _abs(proj, e["subtitles"])
    trocados, mantidos = [], []
    for o in e.get("overlays") or []:
        f = str(o.get("file", ""))
        loc = f.replace("animations/remotion/out/", f"animations/remotion/out_{lang}/", 1)
        if loc != f and (proj / loc).is_file():
            o["file"] = _abs(proj, loc)
            trocados.append(o["file"])
        else:
            o["file"] = _abs(proj, f)
            mantidos.append(o["file"])
    _dir(proj, lang).mkdir(parents=True, exist_ok=True)
    pipeline.atomic_write_json(_dir(proj, lang) / "edl.json", e)
    return {"trocados": trocados, "mantidos": mantidos}


def _cli(ns, root: Path):
    proj = Path(ns.proj)
    if ns.cmd == "frases":
        ws = json.loads(Path(ns.words).read_text(encoding="utf-8-sig"))
        return frases(proj, ns.lang, ws), 0
    if ns.cmd == "validar":
        r = validar(proj, ns.lang, root=root)
        return r, (0 if r["ok"] else 1)
    if ns.cmd == "srt":
        s = srt(proj, ns.lang)
        Path(ns.saida).write_text(s, encoding="utf-8")
        return {"srt": ns.saida, "cues": s.count(" --> ")}, 0
    if ns.cmd == "words":
        return {"palavras": len(words(proj, ns.lang))}, 0
    if ns.cmd == "edl":
        return edl(proj, ns.lang), 0
    raise ValueError(f"comando desconhecido: {ns.cmd}")


def _parser():
    import argparse
    ap = argparse.ArgumentParser(description="dublagem e tradução")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frases"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--words", required=True)
    for c in ("validar", "words", "edl"):
        p = sub.add_parser(c); p.add_argument("proj"); p.add_argument("lang")
    p = sub.add_parser("srt"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--saida", required=True)
    return ap, sub


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap, _ = _parser()
    ns = ap.parse_args()
    try:
        out, code = _cli(ns, Path(ns.root))
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
