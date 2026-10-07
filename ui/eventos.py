"""Etapas da receita + log de eventos por projeto (<proj>/ui/eventos.jsonl).

Etapas vêm do front-matter de Formatos/<formato>.md:
    ---
    etapas: roteiro?=Roteiro, transcricao=transcrição, cortes
    ---
O log é só acréscimo; o quadro (status por etapa, atual, custo) é derivado."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import budget  # noqa: E402
import pipeline  # noqa: E402

STATUS = {"inicio", "fim", "espera", "pulada", "falha"}
ID_RE = re.compile(r"[a-z0-9-]+")
FORMATO_RE = re.compile(r"[\w\-]+")
FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def etapas_de(formato, root=None) -> list[dict]:
    root = root or pipeline.ROOT
    if not formato or not FORMATO_RE.fullmatch(formato):
        return []
    try:
        txt = (root / "Formatos" / f"{formato}.md").read_text(encoding="utf-8-sig")
    except OSError:
        return []
    m = FM_RE.match(txt)
    if not m:
        return []
    for ln in m.group(1).splitlines():
        k, _, v = ln.partition(":")
        if k.strip() == "etapas":
            break
    else:
        return []
    out, vistos = [], set()
    for item in v.split(","):
        id_, _, rot = item.strip().partition("=")
        id_ = id_.strip()
        opcional = id_.endswith("?")
        id_ = id_.rstrip("?")
        if not ID_RE.fullmatch(id_) or id_ in vistos:
            continue
        vistos.add(id_)
        out.append({"id": id_, "rotulo": rot.strip() or id_, "opcional": opcional})
    return out


def formato_de(proj: Path):
    st = pipeline.read_json(proj / "ui" / "state.json", {})
    f = st.get("formato") if isinstance(st, dict) else None
    return f if isinstance(f, str) else None


def _dt(s):
    try:
        d = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def registrar(proj: Path, etapa: str, status: str, nota=None, root=None) -> dict:
    root = root or pipeline.ROOT
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    if status not in STATUS:
        raise ValueError(f"status inválido: {status} (use {', '.join(sorted(STATUS))})")
    formato = formato_de(proj)
    ids = [e["id"] for e in etapas_de(formato, root)]
    if not ids:
        raise ValueError(f"formato sem etapas: {formato}")
    if etapa not in ids:
        raise ValueError(f"etapa '{etapa}' não está na receita {formato}: {', '.join(ids)}")
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "etapa",
          "etapa": etapa, "status": status}
    if nota:
        ev["nota"] = str(nota)
    path = proj / "ui" / "eventos.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro, uma escrita
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def ler(proj: Path) -> list[dict]:
    try:
        texto = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in texto.splitlines():
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba o quadro
        if (not isinstance(e, dict) or e.get("tipo") != "etapa"
                or not isinstance(e.get("etapa"), str) or not e["etapa"]
                or e.get("status") not in STATUS or _dt(e.get("ts")) is None):
            continue
        if not isinstance(e.get("nota"), str):
            e.pop("nota", None)
        out.append(e)
    return out


def _custos(proj: Path) -> list[tuple]:
    out = []
    for l in budget._linhas(proj / "ui" / "costs.jsonl"):
        t, u = _dt(l.get("ts")), budget._fin(l.get("usd", 0))
        if t is not None and u is not None:
            out.append((t, u))
    return out


def _resumo(item: dict, evs: list[dict], custos: list[tuple], agora: datetime) -> dict:
    if not evs:
        return {**item, "status": "pendente", "inicio": None, "fim": None,
                "nota": None, "custo_usd": 0.0}
    ult = evs[-1]["status"]
    status = "andamento" if ult == "inicio" else ult
    idx = max((i for i, e in enumerate(evs) if e["status"] == "inicio"), default=None)
    inicio = evs[idx]["ts"] if idx is not None else None
    depois = evs[idx + 1:] if idx is not None else evs
    fims = [e["ts"] for e in depois if e["status"] == "fim"]
    fim = fims[-1] if fims else None
    nota = next((e["nota"] for e in reversed(evs[idx or 0:]) if e.get("nota")), None)
    custo = 0.0
    if inicio:
        if fim:
            b = _dt(fim)
        elif status == "andamento":
            b = agora
        else:
            b = _dt(evs[-1]["ts"])   # falha/pulada/espera: fecha no último evento
        a = _dt(inicio)
        custo = round(sum(u for t, u in custos if a <= t <= b), 4)
    return {**item, "status": status, "inicio": inicio, "fim": fim,
            "nota": nota, "custo_usd": custo}


def quadro(proj: Path, root=None, agora=None) -> dict:
    root = root or pipeline.ROOT
    agora = agora or datetime.now(timezone.utc)
    formato = formato_de(proj)
    receita = etapas_de(formato, root)
    evs = ler(proj)
    por: dict[str, list] = {}
    for e in evs:
        por.setdefault(e["etapa"], []).append(e)
    custos = _custos(proj)
    etapas = [_resumo(i, por.get(i["id"], []), custos, agora) for i in receita]
    ids = {i["id"] for i in receita}
    fora = [_resumo({"id": k, "rotulo": k, "opcional": False}, v, custos, agora)
            for k, v in por.items() if k not in ids]
    todas = etapas + fora
    andamento = [e for e in todas if e["status"] == "andamento"]
    espera = [e for e in todas if e["status"] == "espera"]
    if andamento:
        atual = max(andamento, key=lambda e: _dt(e["inicio"]))["id"]
    elif espera:
        atual = max(espera, key=lambda e: _dt(por[e["id"]][-1]["ts"]))["id"]
    else:
        atual = None
    return {"formato": formato, "sem_historico": not evs, "etapas": etapas,
            "fora_da_receita": fora, "atual": atual}


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="etapas e eventos do projeto")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("etapa")
    p.add_argument("proj"); p.add_argument("etapa"); p.add_argument("status")
    p.add_argument("--nota")
    p = sub.add_parser("quadro")
    p.add_argument("proj")
    ns = ap.parse_args()
    root = Path(ns.root)
    try:
        if ns.cmd == "etapa":
            out = registrar(Path(ns.proj), ns.etapa, ns.status, nota=ns.nota, root=root)
        else:
            out = quadro(Path(ns.proj), root=root)
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False))
