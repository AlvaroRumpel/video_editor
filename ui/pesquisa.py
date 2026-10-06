"""Pesquisa: parser do pesquisa.md, classificação de fontes, validação,
snapshot e extração heurística de fatos. Não busca na web — a busca é da
sessão (WebSearch). Sem FastAPI."""
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import pipeline

ROOT = pipeline.ROOT

ACHADO_RE = re.compile(
    r"^- \[(F\d+)\]\s+(?P<fato>.+?)\s+—\s+fonte:\s+(?P<fonte>.+?)\s+\((?P<tipo>[^)]+)\)"
    r"\s+—\s+(?P<url>\S+)\s+—\s+acesso\s+(?P<acesso>\d{4}-\d{2}-\d{2})\s*$")
SECOES = {"achados": "## Achados", "angulos": "## Ângulos", "riscos": "## Riscos",
          "rejeitadas": "## Fontes rejeitadas"}


def carregar_fontes(root: Path) -> dict:
    return pipeline.read_json(root / "ui" / "fontes.json", {"oficial": [], "doutrina": []})


def _casa(host: str, padrao: str) -> bool:
    if padrao.startswith("*."):
        return host.endswith(padrao[1:])
    return host == padrao or host.endswith("." + padrao)


def classificar(url: str, fontes: dict) -> str:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "inspiracao"
    for tipo in ("oficial", "doutrina"):
        if any(_casa(host, p) for p in fontes.get(tipo, [])):
            return tipo
    return "inspiracao"


def parse_pesquisa(texto: str) -> dict:
    out = {"achados": [], "angulos": [], "riscos": [], "rejeitadas": [], "malformados": []}
    secao = None
    for n, raw in enumerate(texto.splitlines(), 1):
        linha = raw.rstrip()
        if linha.startswith("## "):
            secao = next((k for k, v in SECOES.items() if linha.strip() == v), None)
            continue
        if secao is None or not linha.strip():
            continue
        if secao == "achados":
            if linha.startswith("- "):
                m = ACHADO_RE.match(linha)
                if m:
                    out["achados"].append({"id": m.group(1), "fato": m["fato"], "fonte": m["fonte"],
                                           "tipo": m["tipo"], "url": m["url"], "acesso": m["acesso"],
                                           "trecho": "", "linha": n})
                else:
                    out["malformados"].append({"linha": n, "texto": linha})
            elif linha.lstrip().startswith(">") and out["achados"]:
                out["achados"][-1]["trecho"] = (out["achados"][-1]["trecho"] + " "
                                                + linha.lstrip()[1:].strip()).strip()
        elif linha.startswith("- "):
            out[secao].append(linha[2:].strip())
    return out


REF_RE = re.compile(r"\[(F\d+)\]")
TITULO_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
MAX_SNAP = 2 * 1024 * 1024


def _fetch_url(url: str, metodo: str | None = None) -> tuple[int, bytes]:
    """metodo=None: HEAD com fallback GET (corpo vazio no HEAD); "GET": só GET com corpo."""
    for m in ((metodo,) if metodo else ("HEAD", "GET")):
        try:
            req = urllib.request.Request(url, method=m, headers={"User-Agent": "video_editor/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:   # segue redirects
                return r.status, (r.read(MAX_SNAP + 1) if m == "GET" else b"")
        except urllib.error.HTTPError as e:
            if m == "HEAD" and e.code in (403, 405):
                continue
            return e.code, b""
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return 0, b""
    return 0, b""


def _refs(path: Path) -> set[str]:
    return set(REF_RE.findall(path.read_text(encoding="utf-8")))


def validar(md_path: Path, roteiro: Path | None = None, fatos: Path | None = None,
            root: Path = ROOT, hoje: str | None = None, _fetch=None) -> dict:
    fontes = carregar_fontes(root)
    fetch = _fetch or _fetch_url
    hoje_d = date.fromisoformat(hoje) if hoje else date.today()
    p = parse_pesquisa(md_path.read_text(encoding="utf-8"))
    erros, avisos = [], []
    for m in p["malformados"]:
        erros.append(f"linha {m['linha']}: achado malformado: {m['texto'][:60]}")
    vistos = set()
    for a in p["achados"]:
        if a["id"] in vistos:
            erros.append(f"{a['id']} duplicado (linha {a['linha']})")
        vistos.add(a["id"])
        if not a["url"].startswith("http"):
            erros.append(f"{a['id']}: sem URL")
            continue
        if classificar(a["url"], fontes) == "inspiracao":
            erros.append(f"{a['id']}: fonte classificada como inspiracao ({a['url']}) — fato exige oficial/doutrina")
        status, _ = fetch(a["url"])
        if not (200 <= status < 400):
            erros.append(f"{a['id']}: URL respondeu {status} ({a['url']})")
        try:
            if (hoje_d - date.fromisoformat(a["acesso"])).days > 180:
                avisos.append(f"{a['id']}: acesso há mais de 180 dias ({a['acesso']})")
        except ValueError:
            erros.append(f"{a['id']}: data de acesso inválida ({a['acesso']})")
        if not a["trecho"]:
            avisos.append(f"{a['id']}: trecho vazio")
    for nome, path in (("roteiro.md", roteiro), ("fatos.md", fatos)):
        if path:
            for ref in sorted(_refs(path) - vistos):
                erros.append(f"{nome}: referência [{ref}] não existe em {md_path.name}")
    return {"ok": not erros, "erros": erros, "avisos": avisos}


def snapshot(md_path: Path, dir: Path, _fetch=None) -> list[dict]:
    p = parse_pesquisa(md_path.read_text(encoding="utf-8"))
    dir.mkdir(parents=True, exist_ok=True)
    idx = []
    for a in p["achados"]:
        status, corpo = _fetch(a["url"]) if _fetch else _fetch_url(a["url"], "GET")
        corpo = corpo[:MAX_SNAP]
        (dir / f"{a['id']}.html").write_bytes(corpo)
        m = TITULO_RE.search(corpo)
        titulo = m.group(1).decode("utf-8", "replace").strip() if m else ""
        idx.append({"id": a["id"], "url": a["url"], "status": status, "titulo": titulo,
                    "salvo_em": datetime.now().isoformat(timespec="seconds")})
    (dir / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return idx


GATILHOS = [
    ("lei", re.compile(r"\b(art\.?|artigo|lei\s*n[ºo.]?|s[úu]mula|inciso|§|par[áa]grafo)\b", re.I)),
    ("numero", re.compile(r"\b\d+([.,]\d+)?\s*(%|dias?|anos?|meses|horas?|reais|mil|milh[õo]es|vezes)\b", re.I)),
    ("absoluto", re.compile(r"\b(sempre|nunca|todos?|todas?|proibido|vedado|obrigat[óo]ri[oa])\b", re.I)),
]


def extrair_fatos(tr: dict) -> list[dict]:
    out = []
    for ph in pipeline.phrases_from_transcript(tr or {}):
        for nome, rx in GATILHOS:
            if rx.search(ph["text"]):
                out.append({"t": round(ph["start"], 2), "trecho": ph["text"], "gatilho": nome})
                break
    return out


def _cli(ns, root: Path):
    if ns.cmd == "validar":
        fetch = (lambda u, *a: (200, b"")) if ns.sem_rede else None
        r = validar(Path(ns.md), roteiro=Path(ns.roteiro) if ns.roteiro else None,
                    fatos=Path(ns.fatos) if ns.fatos else None, root=root, _fetch=fetch)
        return r, (0 if r["ok"] else 1)
    if ns.cmd == "snapshot":
        return snapshot(Path(ns.md), Path(ns.dir)), 0
    tr = json.loads(Path(ns.transcript).read_text(encoding="utf-8"))
    return extrair_fatos(tr), 0


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="pesquisa do video_editor")
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validar"); p.add_argument("md"); p.add_argument("--roteiro"); p.add_argument("--fatos")
    p.add_argument("--sem-rede", action="store_true")
    p = sub.add_parser("snapshot"); p.add_argument("md"); p.add_argument("dir")
    p = sub.add_parser("extrair-fatos"); p.add_argument("transcript")
    ns = ap.parse_args()
    try:
        out, code = _cli(ns, Path(ns.root))
    except Exception as e:   # execução (arquivo ausente, JSON inválido...)
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
