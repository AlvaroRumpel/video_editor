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
TERMINAIS = {"fim", "falha", "pulada"}   # fecham o ciclo da etapa
TIPOS_EVENTO = ("etapa", "decisao", "resposta")
ASSUNTOS = ("provedor", "trilha", "sfx", "broll", "corte", "grade", "zoom", "overlay",
            "legenda", "conceito", "clipe", "thumbnail", "render", "outro")
CONFIANCAS = ("alta", "media", "baixa")
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


def _append(proj: Path, ev: dict) -> dict:
    path = proj / "ui" / "eventos.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro, uma escrita
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


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
    return _append(proj, ev)


def registrar_decisao(proj: Path, assunto: str, escolha: str, etapa=None, alternativas=(),
                      motivo="", custo_usd=None, confianca=None, root=None) -> dict:
    root = root or pipeline.ROOT
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    if assunto not in ASSUNTOS:
        raise ValueError(f"assunto inválido: {assunto} (use {', '.join(ASSUNTOS)})")
    escolha = str(escolha or "").strip()
    if not escolha:
        raise ValueError("escolha vazia")
    if etapa:
        formato = formato_de(proj)
        ids = [e["id"] for e in etapas_de(formato, root)]
        if etapa not in ids:
            raise ValueError(f"etapa '{etapa}' não está na receita {formato}: {', '.join(ids) or 'sem etapas'}")
    if confianca is not None and confianca not in CONFIANCAS:
        raise ValueError(f"confiança inválida: {confianca} (use {', '.join(CONFIANCAS)})")
    custo = None
    if custo_usd is not None:
        custo = budget._fin(custo_usd)
        if custo is None or custo < 0:
            raise ValueError(f"custo inválido: {custo_usd!r}")
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "decisao", "assunto": assunto,
          "escolha": escolha, "alternativas": [str(a) for a in alternativas], "motivo": str(motivo or "")}
    if etapa:
        ev["etapa"] = etapa
    if custo is not None:
        ev["custo_usd"] = float(custo)
    if confianca:
        ev["confianca"] = confianca
    return _append(proj, ev)


def registrar_resposta(proj: Path, qid, texto) -> dict:
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    return _append(proj, {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "resposta",
                          "qid": qid, "texto": str(texto or "")})


def _valido(e):
    """Evento normalizado ou None. Tipo/linha desconhecidos são ignorados."""
    if not isinstance(e, dict) or _dt(e.get("ts")) is None:
        return None
    t = e.get("tipo")
    if t == "etapa":
        if not isinstance(e.get("etapa"), str) or not e["etapa"] or e.get("status") not in STATUS:
            return None
        if not isinstance(e.get("nota"), str):
            e.pop("nota", None)
        return e
    if t == "decisao":
        if not isinstance(e.get("assunto"), str) or not isinstance(e.get("escolha"), str) or not e["escolha"]:
            return None
        if e["assunto"] not in ASSUNTOS:
            e["assunto"] = "outro"
        alts = e.get("alternativas")
        e["alternativas"] = [str(a) for a in alts] if isinstance(alts, list) else []
        if not isinstance(e.get("motivo"), str):
            e["motivo"] = ""
        if not isinstance(e.get("etapa"), str) or not e.get("etapa"):
            e.pop("etapa", None)
        if "custo_usd" in e:
            c = budget._fin(e["custo_usd"])
            if c is None or c < 0:
                e.pop("custo_usd")
        if e.get("confianca") not in CONFIANCAS:
            e.pop("confianca", None)
        return e
    if t == "resposta":
        if "qid" not in e:
            return None
        if not isinstance(e.get("texto"), str):
            e["texto"] = ""
        return e
    return None


def ler(proj: Path, tipo="etapa") -> list[dict]:
    """Eventos válidos em ordem do arquivo; tipo=None = todos os tipos."""
    try:
        texto = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in texto.splitlines():
        try:
            e = _valido(json.loads(raw))
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba o quadro
        if e is not None and (tipo is None or e["tipo"] == tipo):
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
    ciclo = None   # 1º inicio do ciclo atual: retomar após `espera` não zera início/custo
    if idx is not None:
        term = max((i for i, e in enumerate(evs[:idx]) if e["status"] in TERMINAIS), default=-1)
        ciclo = next(i for i in range(term + 1, idx + 1) if evs[i]["status"] == "inicio")
    inicio = evs[ciclo]["ts"] if ciclo is not None else None
    depois = evs[idx + 1:] if idx is not None else evs
    fims = [e["ts"] for e in depois if e["status"] == "fim"]
    fim = fims[-1] if fims else None
    nota = next((e["nota"] for e in reversed(evs[ciclo or 0:]) if e.get("nota")), None)
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


def quadro(proj: Path, root=None, agora=None, ate=None) -> dict:
    root = root or pipeline.ROOT
    agora = agora or ate or datetime.now(timezone.utc)
    formato = formato_de(proj)
    receita = etapas_de(formato, root)
    todos = ler(proj, None)
    custos = _custos(proj)
    if ate is not None:
        todos = [e for e in todos if _dt(e["ts"]) <= ate]
        custos = [(t, u) for t, u in custos if t <= ate]
    evs = [e for e in todos if e["tipo"] == "etapa"]
    por: dict[str, list] = {}
    for e in evs:
        por.setdefault(e["etapa"], []).append(e)
    etapas = [_resumo(i, por.get(i["id"], []), custos, agora) for i in receita]
    ids = {i["id"] for i in receita}
    fora = [_resumo({"id": k, "rotulo": k, "opcional": False}, v, custos, agora)
            for k, v in por.items() if k not in ids]
    todas = etapas + fora
    decs = [e for e in todos if e["tipo"] == "decisao"]
    com_card = {e["id"] for e in todas}
    for e in todas:
        e["decisoes"] = [d for d in decs if d.get("etapa") == e["id"]]
    soltas = [d for d in decs if d.get("etapa") not in com_card]
    andamento = [e for e in todas if e["status"] == "andamento"]
    espera = [e for e in todas if e["status"] == "espera"]
    if andamento:
        atual = max(andamento, key=lambda e: _dt(e["inicio"]))["id"]
    elif espera:
        atual = max(espera, key=lambda e: _dt(por[e["id"]][-1]["ts"]))["id"]
    else:
        atual = None
    return {"formato": formato, "sem_historico": not todos, "etapas": etapas,
            "fora_da_receita": fora, "atual": atual, "decisoes_soltas": soltas}


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
