"""Folhas de aprovação: normaliza artefatos do pipeline para a UI e gera os
frames dos overlays (overlays/oNN.png + overlays/folha.json). Só leitura nos
artefatos; a decisão volta ao Claude como texto pela fila."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

TIPOS = ("broll", "clips", "conceitos", "overlays")
X_PADRAO = 636
ANIMATIC_RE = re.compile(r"animatic-[A-Z]\.png")
OVERLAY_PNG_RE = re.compile(r"overlays/o\d{2,3}\.png")


def _json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"{path.name} não encontrado")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} inválido: {e.msg}")
    if not isinstance(d, dict):
        raise ValueError(f"{path.name} inválido: esperado objeto")
    return d


def _itens(d: dict, chave: str, nome: str) -> list:
    v = d.get(chave)
    if not isinstance(v, list):
        raise ValueError(f"{nome} inválido: '{chave}' ausente")
    for i, it in enumerate(v):
        if not isinstance(it, dict) or not it.get("id"):
            raise ValueError(f"{nome}: item {i} sem id")
    return v


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"número inválido: {v!r}")


def _broll(proj: Path) -> dict:
    d = _json(proj / "broll.json")
    out = []
    for m in _itens(d, "momentos", "broll.json"):
        if m.get("status") != "proposto":
            continue
        cands = m.get("candidatos")
        if not isinstance(cands, list):
            raise ValueError(f"broll.json: {m['id']} sem candidatos")
        cs = [{"rotulo": f"{m['id']}-{k + 1}", "fonte": c.get("fonte", ""), "tipo": c.get("tipo", "video"),
               "arq": c.get("arq", ""), "dur": _f(c.get("dur")), "licenca": c.get("licenca", ""),
               "autor": c.get("autor", "")}
              for k, c in enumerate(cands) if isinstance(c, dict)]
        rotulos = [c["rotulo"] for c in cs]
        esc = m.get("escolhido") if m.get("escolhido") in rotulos else (rotulos[0] if rotulos else None)
        out.append({"id": m["id"], "t_in": _f(m.get("t_in")), "t_out": _f(m.get("t_out")),
                    "termo": m.get("termo", ""), "modo": m.get("modo", ""), "status": "proposto",
                    "escolhido": esc, "candidatos": cs})
    return {"momentos": out}


def _ranges(c: dict) -> list:
    rs = c.get("ranges")
    if not isinstance(rs, list) or not rs:
        raise ValueError(f"clips.json: {c['id']} sem ranges")
    try:
        return [{"t_in": float(r["t_in"]), "t_out": float(r["t_out"])} for r in rs]
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"clips.json: {c['id']} com range malformado")


def _clips(proj: Path) -> dict:
    d = _json(proj / "clips" / "clips.json")
    xp = int(d.get("x_padrao", X_PADRAO))
    out = []
    for c in _itens(d, "clipes", "clips.json"):
        if c.get("status") != "proposto":
            continue
        rs = _ranges(c)
        out.append({"id": c["id"], "slug": c.get("slug", ""), "nota": c.get("nota"), "gancho": c.get("gancho", ""),
                    "ranges": rs, "x": int(c.get("x", xp)), "legenda": bool(c.get("legenda")),
                    "plataformas": list(c.get("plataformas") or []),
                    "dur": round(sum(r["t_out"] - r["t_in"] for r in rs), 3)})
    return {"x_padrao": xp, "clipes": out}


def _conceitos(proj: Path) -> dict:
    d = _json(proj / "conceitos.json")
    out = []
    for c in _itens(d, "conceitos", "conceitos.json"):
        an = c.get("animatic")
        ok = isinstance(an, str) and ANIMATIC_RE.fullmatch(an) and (proj / an).is_file()
        out.append({"id": str(c["id"]), "ideia": c.get("ideia", ""), "mantem": c.get("mantem", ""),
                    "muda": c.get("muda", ""), "custo": str(c.get("custo", "")), "horas": c.get("horas"),
                    "exige_ia": bool(c.get("exige_ia")), "animatic": an if ok else None})
    return {"conceitos": out}


def _overlays_ler(proj: Path) -> dict:
    d = _json(proj / "overlays" / "folha.json")
    out = []
    for o in _itens(d, "overlays", "folha.json"):
        png = o.get("png")
        ok = isinstance(png, str) and OVERLAY_PNG_RE.fullmatch(png) and (proj / png).is_file()
        out.append({"id": o["id"], "arquivo": o.get("arquivo", ""), "t": _f(o.get("t")), "dur": _f(o.get("dur")),
                    "png": png if ok else None, "erro": o.get("erro")})
    return {"overlays": out}


LEITORES = {"broll": _broll, "clips": _clips, "conceitos": _conceitos, "overlays": _overlays_ler}


def ler(proj: Path, tipo: str) -> dict:
    if tipo not in LEITORES:
        raise ValueError(f"tipo inválido: {tipo} (use {', '.join(TIPOS)})")
    return LEITORES[tipo](Path(proj))


def overlays(proj: Path, _run=None) -> dict:
    """Frame no meio de cada overlay do edl.json, composto sobre o vídeo base
    (final.mp4, senão preview.mp4, senão fundo preto) no mesmo tempo de saída."""
    run = _run or subprocess.run
    proj = Path(proj)
    edl = _json(proj / "edl.json")
    base = next((proj / n for n in ("final.mp4", "preview.mp4") if (proj / n).is_file()), None)
    dst = proj / "overlays"
    dst.mkdir(exist_ok=True)
    itens = []
    for i, o in enumerate(edl.get("overlays") or [], 1):
        oid = f"o{i:02d}"
        arq = str(o.get("file", "")) if isinstance(o, dict) else ""
        t0 = _f(o.get("start_in_output")) if isinstance(o, dict) else 0.0
        dur = _f(o.get("duration")) if isinstance(o, dict) else 0.0
        item = {"id": oid, "arquivo": arq, "t": t0, "dur": dur, "png": None, "erro": None}
        src = proj / arq
        if not arq or not src.is_file():
            item["erro"] = "arquivo do overlay não encontrado"
            itens.append(item)
            continue
        meio = dur / 2
        entrada = (["-ss", f"{t0 + meio:.3f}", "-i", str(base)] if base
                   else ["-f", "lavfi", "-i", "color=c=black:s=1920x1080"])
        png = dst / f"{oid}.png"
        args = ["ffmpeg", "-y", "-loglevel", "error", *entrada, "-ss", f"{meio:.3f}", "-i", str(src),
                # setpts zera os dois relógios: sem isso o fundo lavfi sai sem o overlay
                "-filter_complex", "[0:v]scale=1920:1080,setpts=PTS-STARTPTS[b];[1:v]setpts=PTS-STARTPTS[o];"
                                   "[b][o]overlay=(W-w)/2:(H-h)/2,scale=640:-2",
                "-frames:v", "1", str(png)]
        try:
            run(args, capture_output=True, check=True, timeout=60)
            item["png"] = f"overlays/{oid}.png"
        except (OSError, subprocess.SubprocessError) as e:
            item["erro"] = f"ffmpeg: {type(e).__name__}"
        itens.append(item)
    out = {"overlays": itens}
    pipeline.atomic_write_json(dst / "folha.json", out)
    return out


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="folhas de aprovação")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ler"); p.add_argument("proj"); p.add_argument("tipo")
    p = sub.add_parser("overlays"); p.add_argument("proj")
    ns = ap.parse_args()
    try:
        out = ler(Path(ns.proj), ns.tipo) if ns.cmd == "ler" else overlays(Path(ns.proj))
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False))
