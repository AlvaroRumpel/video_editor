"""Shorts verticais: <ep>/shorts.json → mini-episódio 9:16 em <ep>/shorts/<sid>/ → narrado.render.
Short = cenas inteiras e consecutivas do longo: reaproveita áudio, palavras e assets, sem novo TTS."""
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import narrado  # noqa: E402
import pipeline  # noqa: E402

MAX_SEG = 60.0
TELA_FINAL_DUR = 3.0
SID_RE = re.compile(r"s\d{2}")


def ler(ep_dir) -> list[dict]:
    d = pipeline.read_json(Path(ep_dir) / "shorts.json", None)
    if not isinstance(d, list) or not d:
        raise ValueError(f"{Path(ep_dir) / 'shorts.json'} ausente, ilegível ou vazio (lista de shorts)")
    return d


def duracao(short: dict, st: dict) -> float:
    return sum(st[c]["dur"] + narrado.PAUSA for c in short["cenas"]) + TELA_FINAL_DUR


def validar(ep_dir, lang: str) -> list[dict]:
    ep_dir = Path(ep_dir)
    erros = []

    def e(i, m):
        erros.append({"id": i, "motivo": m})

    ids = {c["id"] for c in narrado.ler(ep_dir)["cenas"]}
    st = narrado.estado(ep_dir, lang)
    vistos = set()
    for s in ler(ep_dir):
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not SID_RE.fullmatch(sid):
            e(str(sid), f"id inválido: {sid!r} (s01, s02, ...)")
            continue
        if sid in vistos:
            e(sid, "id duplicado")
            continue
        vistos.add(sid)
        cenas = s.get("cenas")
        if not isinstance(cenas, list) or not cenas:
            e(sid, "cenas precisa ser lista não vazia")
            continue
        for c in dict.fromkeys(cenas):
            if c not in ids:
                e(sid, f"cena {c} não existe no episodio.json")
        if len(set(cenas)) != len(cenas):
            e(sid, "cena repetida")
        for campo in ("titulo", "descricao"):
            v = s.get(campo)
            if not isinstance(v, dict) or not isinstance(v.get(lang), str) or not v[lang].strip():
                e(sid, f"falta {campo}.{lang}")
        if any(c not in ids for c in cenas):
            continue
        sem_audio = [c for c in cenas if not (st.get(c) and (ep_dir / st[c].get("audio", "-")).is_file())]
        if sem_audio:
            e(sid, f"áudio ausente em {', '.join(sem_audio)}: rode tts/alinhar do episódio")
            continue
        total = duracao(s, st)
        if total > MAX_SEG:
            e(sid, f"duração {total:.1f} s passa de {MAX_SEG:.0f} s: tire uma cena")
    return erros


def _clonar(src: Path, dst: Path) -> None:
    """Hard link quando der (sem duplicar disco), cópia senão; sobrescreve."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _clonar_pasta(src: Path, dst: Path) -> None:
    for f in src.rglob("*"):
        if f.is_file():
            _clonar(f, dst / f.relative_to(src))


def montar(ep_dir, sid: str, lang: str) -> Path:
    """Cria/atualiza <ep>/shorts/<sid>/ (projeto narrado 9:16). Nunca apaga saídas de render já feitas."""
    ep_dir = Path(ep_dir)
    lista = ler(ep_dir)
    short = next((s for s in lista if isinstance(s, dict) and s.get("id") == sid), None)
    if short is None:
        raise ValueError(f"short {sid!r} não está no shorts.json")
    erros = [x for x in validar(ep_dir, lang) if x["id"] == sid]
    if erros:
        raise ValueError("; ".join(f"{x['id']}: {x['motivo']}" for x in erros))
    ep = narrado.ler(ep_dir)
    por_id = {c["id"]: c for c in ep["cenas"]}
    derivado = {k: ep[k] for k in ("marca", "mapa", "atores") if k in ep}
    derivado.update(id=f"{ep.get('id', ep_dir.name)}-{sid}", titulo=short["titulo"], aspecto="9:16",
                    tela_final_dur=TELA_FINAL_DUR, cenas=[por_id[c] for c in short["cenas"]])
    dst = ep_dir / "shorts" / sid
    dst.mkdir(parents=True, exist_ok=True)
    pipeline.atomic_write_json(dst / "episodio.json", derivado)
    _clonar(ep_dir / "pesquisa.md", dst / "pesquisa.md")
    if (ep_dir / "assets").is_dir():
        _clonar_pasta(ep_dir / "assets", dst / "assets")
    st, pal = narrado.estado(ep_dir, lang), pipeline.read_json(ep_dir / lang / "palavras.json", {})
    pipeline.atomic_write_json(dst / lang / "narracao.json", {c: st[c] for c in short["cenas"]})
    pipeline.atomic_write_json(dst / lang / "palavras.json", {c: pal[c] for c in short["cenas"] if c in pal})
    for c in short["cenas"]:
        _clonar(ep_dir / st[c]["audio"], dst / st[c]["audio"])
    return dst


def renderizar(ep_dir, sid: str, lang: str, rascunho: bool = False, trilha=None) -> dict:
    return narrado.render(montar(ep_dir, sid, lang), lang, rascunho, trilha)


if __name__ == "__main__":
    import argparse
    import subprocess
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="shorts 9:16 a partir do episódio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validar")
    v.add_argument("ep")
    r = sub.add_parser("render")
    r.add_argument("ep")
    r.add_argument("sid", help="s01, s02... ou 'todos'")
    r.add_argument("--rascunho", action="store_true")
    r.add_argument("--trilha")
    for sp in (v, r):
        sp.add_argument("--lang", default="pt")
    ns = ap.parse_args()
    try:
        if ns.cmd == "validar":
            erros = validar(ns.ep, ns.lang)
            out, code = {"ok": not erros, "erros": erros}, (0 if not erros else 1)
        else:
            sids = [s["id"] for s in ler(ns.ep)] if ns.sid == "todos" else [ns.sid]
            out = [renderizar(ns.ep, s, ns.lang, ns.rascunho, ns.trilha) for s in sids]
            code = 0 if all(x.get("ok") for x in out) else 1
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as ex:
        print(json.dumps({"erro": f"{type(ex).__name__}: {ex}"}, ensure_ascii=False))
        sys.exit(4)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)
