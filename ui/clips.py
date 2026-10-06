"""Clip Factory: palavras na timeline do export, candidatos a Short por
heurística, validação do clips.json curado, EDLs por clipe×plataforma e
render via render.py. Sem FastAPI."""
import json
import os
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
    fechamento = 1.0 if (fim and fr_fim_pausa >= 0.3) else 0.6 if fim else 0.2
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
    out = []
    restantes = sorted(janelas, key=lambda j: -j["score"])
    while restantes and len(out) < n:
        melhor = None  # (score_eff, j, k)
        for j in restantes:
            dj = j["t_out"] - j["t_in"]
            if any((min(j["t_out"], o["t_out"]) - max(j["t_in"], o["t_in"])) / min(dj, o["t_out"] - o["t_in"]) > 0.6
                   for o in out):
                continue
            k = sum(1 for o in out if abs(o["t_in"] - j["t_in"]) <= 180)
            eff = j["score"] - 0.05 * k
            if melhor is None or eff > melhor[0]:
                melhor = (eff, j, k)
        if melhor is None: break
        _, j, k = melhor
        if k: j["motivos"].append(f"perto de {k} aceitos")
        out.append(j); restantes.remove(j)
    return out


PLATAFORMAS = {"shorts": (20, 60), "reels": (20, 90), "tiktok": (20, 60)}
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
TOL = 0.005
STATUS = {"proposto", "aprovado", "vetado"}


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pares(c: dict) -> list[tuple[float, float]]:
    """(t_in, t_out) só dos ranges bem formados."""
    out = []
    for r in c.get("ranges") or []:
        try:
            out.append((float(r["t_in"]), float(r["t_out"])))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def dur_clipe(c: dict) -> float:
    return sum(to - ti for ti, to in _pares(c))


def _aprovados(clips: dict) -> list[dict]:
    aps = [c for c in clips.get("clipes", []) if c.get("status") == "aprovado"]
    return sorted(aps, key=lambda c: (-_num(c.get("nota")), min((ti for ti, _ in _pares(c)), default=0)))


def _em_palavra(t: float, words, borda: str) -> bool:
    if borda == "in":
        return any(abs((t + PAD_IN) - w["t"]) <= TOL for w in words)
    return any(abs((t - PAD_OUT) - w["e"]) <= TOL for w in words)


def _palavras_de(c: dict, words) -> set[str]:
    out = set()
    for ti, to in _pares(c):
        out |= {f"{w['t']}:{w['w']}" for w in words if w["t"] >= ti and w["e"] <= to}
    return out


def validar(clips: dict, words: list[dict]) -> dict:
    erros, avisos, slugs, ids = [], [], set(), set()
    for c in clips.get("clipes", []):
        cid = c.get("id", "?")
        if cid in ids:
            erros.append(f"{cid}: id repetido")
        ids.add(cid)
        if c.get("status") not in STATUS:
            erros.append(f"{cid}: status inválido {c.get('status')!r}")
        if not SLUG_RE.match(str(c.get("slug", ""))):
            erros.append(f"{cid}: slug inválido {c.get('slug')!r}")
        if c.get("slug") in slugs:
            erros.append(f"{cid}: slug repetido {c['slug']}")
        slugs.add(c.get("slug"))
        x = c.get("x", clips.get("x_padrao", 636))
        if not isinstance(x, int) or x % 2 or not 0 <= x <= 1312:
            erros.append(f"{cid}: x deve ser par entre 0 e 1312 (x={x})")
        rs = c.get("ranges") or []
        if not rs:
            erros.append(f"{cid}: sem ranges"); continue
        pares = _pares(c)
        if len(pares) != len(rs):
            erros.append(f"{cid}: range malformado em ranges"); continue
        for ti, to in pares:
            if to <= ti:
                erros.append(f"{cid}: t_out ({to}) <= t_in ({ti})"); continue
            if not _em_palavra(ti, words, "in"):
                erros.append(f"{cid}: t_in {ti} não está em fronteira de palavra")
            if not _em_palavra(to, words, "out"):
                erros.append(f"{cid}: t_out {to} não está em fronteira de palavra")
        for i in range(len(pares)):
            for j in range(i + 1, len(pares)):
                a, b = pares[i], pares[j]
                if a[0] < b[1] and b[0] < a[1]:
                    erros.append(f"{cid}: ranges {i} e {j} se sobrepõem")
        d = dur_clipe(c)
        plats = c.get("plataformas")
        if not plats:
            erros.append(f"{cid}: sem plataformas"); continue
        if not isinstance(plats, list):
            erros.append(f"{cid}: plataformas deve ser lista"); continue
        for p in plats:
            if p not in PLATAFORMAS:
                erros.append(f"{cid}: plataforma desconhecida {p}"); continue
            lo, hi = PLATAFORMAS[p]
            if not lo <= d <= hi:
                erros.append(f"{cid}: {d:.1f}s fora de {lo}–{hi}s para {p}")
    aps = _aprovados(clips)
    meta = int(_num(clips.get("meta_n")))
    if len(aps) > meta + 2:
        erros.append(f"{len(aps)} aprovados > meta_n + 2 ({meta + 2})")
    for i in range(len(aps)):
        for j in range(i + 1, len(aps)):
            pa, pb = _palavras_de(aps[i], words), _palavras_de(aps[j], words)
            if pa and pb and len(pa & pb) / min(len(pa), len(pb)) > 0.5:
                erros.append(f"{aps[i]['id']} e {aps[j]['id']}: > 50% de palavras em comum")
    return {"ok": not erros, "erros": erros, "avisos": avisos}


REFRAME = "crop=608:1080:{x}:0,scale=1080:1920:flags=lanczos"


def _ts(seg: float) -> str:
    ms = int(round(seg * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_clipe(c: dict, words: list[dict]) -> str:
    """cues de 1–3 palavras (≤ 1,2 s), tempo relativo ao clipe (ranges somados na ordem do clipe)."""
    cues, offset = [], 0.0
    for r in c.get("ranges", []):
        ti, to = float(r["t_in"]), float(r["t_out"])
        ws = [w for w in words if w["t"] >= ti and w["e"] <= to]
        grupo = []

        def fecha():
            cues.append((grupo[0]["t"] - ti + offset, grupo[-1]["e"] - ti + offset, " ".join(g["w"] for g in grupo)))
            grupo.clear()
        for w in ws:
            if grupo and w["e"] - grupo[0]["t"] > 1.2:
                fecha()
            grupo.append(w)
            if len(grupo) == 3 or w["w"].endswith(PONT_FIM):
                fecha()
        if grupo:
            fecha()
        offset += to - ti
    return "".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(cues, 1))


def _quote(r: dict, words) -> str:
    return " ".join(w["w"] for w in words if w["t"] >= float(r["t_in"]) and w["e"] <= float(r["t_out"]))[:120]


def edl(clips: dict, proj: Path, export: Path, words: list[dict]) -> dict:
    proj = Path(proj); export = Path(export)
    if not export.exists():
        raise FileNotFoundError(f"export não existe: {export}")
    export = export.resolve()
    gerados, linhas = [], []
    for n, c in enumerate(_aprovados(clips), 1):
        x = c.get("x", clips.get("x_padrao", 636))
        for plat in c.get("plataformas", []):
            d = proj / "clips" / f"{n:02d}-{c['slug']}-{plat}"
            d.mkdir(parents=True, exist_ok=True)
            e = {"version": 1, "sources": {"EXPORT": str(export)},
                 "ranges": [{"source": "EXPORT", "start": float(r["t_in"]), "end": float(r["t_out"]),
                             "beat": r.get("beat", ""), "quote": _quote(r, words)} for r in c["ranges"]],
                 "grade": REFRAME.format(x=x), "overlays": []}
            if c.get("legenda") or plat == "tiktok":
                (d / "legenda.srt").write_text(srt_clipe(c, words), encoding="utf-8")
                e["subtitles"] = "legenda.srt"
            pipeline.atomic_write_json(d / "edl.json", e)
            gerados.append(f"clips/{d.name}")
    for c in clips.get("clipes", []):
        linhas.append(f"| {c.get('id')} | {c.get('nota') or '-'} | {dur_clipe(c):.0f}s | {str(c.get('gancho', ''))[:60]} | "
                      f"{', '.join(c.get('plataformas', []))} | {c.get('status')} |")
    md = ("# Clipes\n\n| id | nota | dur | gancho | plataformas | status |\n|---|---|---|---|---|---|\n"
          + "\n".join(linhas) + "\n")
    (proj / "clips").mkdir(parents=True, exist_ok=True)
    (proj / "clips" / "clips.md").write_text(md, encoding="utf-8")
    (proj / "clips.md").write_text(md, encoding="utf-8")
    res = {"gerados": gerados, "md": md}
    if not _aprovados(clips):
        res["avisos"] = ["0 aprovados — só clips.md gerado"]
    return res


def _run_padrao(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def render(clips: dict, proj: Path, export_dir: Path, preview: bool = False, _run=None) -> dict:
    run = _run or _run_padrao
    proj = Path(proj); export_dir = Path(export_dir); export_dir.mkdir(parents=True, exist_ok=True)
    ok, erros, esperados = [], [], set()
    aps = _aprovados(clips)
    if not aps:
        return {"renderizados": [], "erros": ["0 clipes aprovados — aplique a resposta da aprovação (status: aprovado) antes de renderizar"]}
    for n, c in enumerate(aps, 1):
        for plat in c.get("plataformas", []):
            nome = f"{n:02d}-{c['slug']}-{plat}"
            esperados.add(f"{nome}.mp4")
            edl_path = proj / "clips" / nome / "edl.json"
            if not edl_path.exists():
                erros.append(f"{nome}: edl.json não existe (rode `edl` antes)"); continue
            cmd = [sys.executable, str(RENDER), str(edl_path), "-o", str(export_dir / f"{nome}.mp4")]
            if preview: cmd.append("--preview")
            r = run(cmd)
            if r.returncode != 0:
                erros.append(f"{nome}: render falhou ({r.returncode}): {str(r.stderr)[-400:]}")
            else:
                ok.append(f"{nome}.mp4")
    removidos = []
    if not preview:
        for f in sorted(export_dir.glob("*.mp4")):
            if f.name not in esperados:
                f.unlink(); removidos.append(f.name)
    return {"renderizados": ok, "erros": erros, "removidos": removidos}


def _ler(p): return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def _cli(ns):
    if ns.cmd == "words-out":
        out = words_out(_ler(ns.edl), _ler(ns.transcript), _ler(ns.real))
        pipeline.atomic_write_json(Path(ns.out), out); return {"palavras": len(out), "fim": out[-1]["e"] if out else 0}, 0
    if ns.cmd == "candidatos":
        c = candidatos(_ler(ns.words), n=ns.n)
        pipeline.atomic_write_json(Path(ns.out), c); return c, 0
    if ns.cmd == "validar":
        r = validar(_ler(ns.clips), _ler(ns.words)); return r, (0 if r["ok"] else 1)
    if ns.cmd == "edl":
        c = _ler(ns.clips); w = _ler(Path(ns.proj) / "clips" / "words_out.json")
        return edl(c, Path(ns.proj), Path(ns.export), w), 0
    r = render(_ler(ns.clips), Path(ns.proj), Path(ns.export_dir), preview=ns.preview)
    return r, (0 if not r["erros"] else 2)


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Clip Factory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("words-out"); p.add_argument("edl"); p.add_argument("transcript"); p.add_argument("real"); p.add_argument("out")
    p = sub.add_parser("candidatos"); p.add_argument("words"); p.add_argument("out"); p.add_argument("--n", type=int, default=20)
    p = sub.add_parser("validar"); p.add_argument("clips"); p.add_argument("words")
    p = sub.add_parser("edl"); p.add_argument("clips"); p.add_argument("proj"); p.add_argument("export")
    p = sub.add_parser("render"); p.add_argument("clips"); p.add_argument("proj"); p.add_argument("export_dir"); p.add_argument("--preview", action="store_true")
    ns = ap.parse_args()
    try:
        out, code = _cli(ns)
    except Exception as e:
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
