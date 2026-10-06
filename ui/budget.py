"""Orçamento: tetos, estimativa, registro e autorização de gastos.
Sem FastAPI. Arquivos: .ui-runtime/budget.json, ui/precos.json,
<proj>/ui/costs.jsonl, .ui-runtime/quota.json (cache do saldo ElevenLabs)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pipeline

DEFAULTS = {"teto_mensal_usd": 30.0, "teto_projeto_usd": 5.0,
            "aprovar_acima_usd": 0.5, "tetos_projeto": {}}


def _ano_mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ler_budget(root: Path) -> dict:
    b = dict(DEFAULTS)
    b.update(pipeline.read_json(root / ".ui-runtime" / "budget.json", {}))
    return b


def precos(root: Path) -> dict:
    return pipeline.read_json(root / "ui" / "precos.json", {})


def estimar(root: Path, provedor: str, unidades: float):
    p = precos(root).get(provedor)
    if not p:
        return None
    return {"usd": round(p.get("usd", 0.0) * unidades, 4),
            "creditos": int(round(p.get("creditos", 0) * unidades))}


def registrar(proj: Path, provedor: str, unidades: float, usd=None,
              creditos=None, aprovacao=None, nota: str = "", root: Path | None = None) -> dict:
    root = root or pipeline.ROOT
    est = estimar(root, provedor, unidades) or {"usd": 0.0, "creditos": 0}
    linha = {"ts": datetime.now(timezone.utc).isoformat(),
             "provedor": provedor, "unidades": unidades,
             "usd": est["usd"] if usd is None else float(usd),
             "creditos": est["creditos"] if creditos is None else int(creditos),
             "aprovacao": aprovacao, "nota": nota}
    path = proj / "ui" / "costs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha


def _linhas(path: Path):
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in texto.splitlines():
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba a UI


def gasto_projeto(proj: Path, ano_mes: str | None = None) -> dict:
    usd = 0.0
    cred = 0
    for l in _linhas(proj / "ui" / "costs.jsonl"):
        if ano_mes and not str(l.get("ts", "")).startswith(ano_mes):
            continue
        usd += float(l.get("usd", 0))
        cred += int(l.get("creditos", 0))
    return {"usd": round(usd, 4), "creditos": cred}


def gasto_mes(root: Path, ano_mes: str | None = None) -> dict:
    ano_mes = ano_mes or _ano_mes_atual()
    usd = 0.0
    cred = 0
    for p in pipeline.find_projects(root):
        g = gasto_projeto(pipeline.project_dir(root, p["id"]), ano_mes)
        usd += g["usd"]
        cred += g["creditos"]
    return {"usd": round(usd, 4), "creditos": cred}
