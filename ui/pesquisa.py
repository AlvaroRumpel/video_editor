"""Pesquisa: parser do pesquisa.md, classificação de fontes, validação,
snapshot e extração heurística de fatos. Não busca na web — a busca é da
sessão (WebSearch). Sem FastAPI."""
import json
import re
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
