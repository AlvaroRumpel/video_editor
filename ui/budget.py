"""Orçamento: tetos, estimativa, registro e autorização de gastos.
Sem FastAPI. Arquivos: .ui-runtime/budget.json, ui/precos.json,
<proj>/ui/costs.jsonl, .ui-runtime/quota.json (cache do saldo ElevenLabs)."""
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pipeline

DEFAULTS = {"teto_mensal_usd": 30.0, "teto_projeto_usd": 5.0,
            "aprovar_acima_usd": 0.5, "tetos_projeto": {}}


def _ano_mes_atual() -> str:
    # a virada do mês é em UTC
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ler_budget(root: Path) -> dict:
    b = dict(DEFAULTS)
    b.update(pipeline.read_json(root / ".ui-runtime" / "budget.json", {}))
    return b


def precos(root: Path) -> dict:
    return pipeline.read_json(root / "ui" / "precos.json", {})


def _num(v, nome: str, minimo: float = 0.0) -> float:
    """Número finito >= minimo, senão ValueError (nan/inf desligariam os tetos)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} inválido: {v!r}")
    if not math.isfinite(f) or f < minimo:
        raise ValueError(f"{nome} inválido: {v!r}")
    return f


def _unidades(v) -> float:
    u = _num(v, "unidades")
    if u <= 0:
        raise ValueError(f"unidades inválido: {v!r}")
    return u


def _existe(proj: Path) -> None:
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")


def estimar(root: Path, provedor: str, unidades: float):
    unidades = _unidades(unidades)
    p = precos(root).get(provedor)
    if not p:
        return None
    return {"usd": round(p.get("usd", 0.0) * unidades, 4),
            "creditos": int(round(p.get("creditos", 0) * unidades))}


def registrar(proj: Path, provedor: str, unidades: float, usd=None,
              creditos=None, aprovacao=None, nota: str = "", root: Path | None = None) -> dict:
    root = root or pipeline.ROOT
    _existe(proj)
    unidades = _unidades(unidades)
    usd = None if usd is None else _num(usd, "usd")
    creditos = None if creditos is None else int(_num(creditos, "creditos"))
    est = estimar(root, provedor, unidades) or {"usd": 0.0, "creditos": 0}
    linha = {"ts": datetime.now(timezone.utc).isoformat(),
             "provedor": provedor, "unidades": unidades,
             "usd": est["usd"] if usd is None else usd,
             "creditos": est["creditos"] if creditos is None else creditos,
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
            l = json.loads(raw)
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba a UI
        if isinstance(l, dict):
            yield l


def _fin(v):
    """Número finito (não bool) ou None."""
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return v if ok else None


def gasto_projeto(proj: Path, ano_mes: str | None = None) -> dict:
    usd = 0.0
    cred = 0
    for l in _linhas(proj / "ui" / "costs.jsonl"):
        if ano_mes and not str(l.get("ts", "")).startswith(ano_mes):
            continue
        u, c = _fin(l.get("usd", 0)), _fin(l.get("creditos", 0))
        if u is None or c is None:
            continue   # linha com valor inválido não entra na soma
        usd += u
        cred += int(c)
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


ELEVEN_SUB_URL = "https://api.elevenlabs.io/v1/user/subscription"


def _chave_elevenlabs() -> str:
    v = os.environ.get("ELEVENLABS_API_KEY", "")
    if v:
        return v
    env = pipeline.ROOT / "video-use" / ".env"
    try:
        for ln in env.read_text(encoding="utf-8").splitlines():
            k, _, val = ln.partition("=")
            if k.strip() == "ELEVENLABS_API_KEY":
                return val.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _fetch_elevenlabs(key: str) -> dict:
    req = urllib.request.Request(ELEVEN_SUB_URL, headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _gravar_quota(qpath: Path, entrada: dict) -> None:
    q = pipeline.read_json(qpath, {})          # reler antes de gravar
    if not isinstance(q, dict):
        q = {}
    q["elevenlabs"] = entrada
    pipeline.atomic_write_json(qpath, q)


def saldo_elevenlabs(root: Path, max_idade_s: int = 300, _fetch=None):
    qpath = root / ".ui-runtime" / "quota.json"
    try:
        cache = pipeline.read_json(qpath, {}).get("elevenlabs")
        if cache and cache.get("erro") and time.time() - cache["lido_em"] < 60:
            return None   # falha recente: não repete o timeout a cada carga
        if cache and not cache.get("erro") and time.time() - cache["lido_em"] < max_idade_s:
            return {k: cache[k] for k in ("usados", "limite", "restante", "reset_ts")}
    except Exception:
        pass   # cache ilegível: busca de novo
    key = _chave_elevenlabs()
    if not key:
        return None
    try:
        d = (_fetch or _fetch_elevenlabs)(key)
        usados = int(d["character_count"])
        limite = int(d["character_limit"])
    except Exception:
        _gravar_quota(qpath, {"erro": True, "lido_em": time.time()})
        return None
    saldo = {"usados": usados, "limite": limite, "restante": limite - usados,
             "reset_ts": d.get("next_character_count_reset_unix", 0)}
    _gravar_quota(qpath, {**saldo, "lido_em": time.time()})
    return saldo


def _decisao(status, motivo, est):
    return {"status": status, "motivo": motivo, "estimativa": est}


def _aprovacao_valida(root: Path, proj: Path, aprovacao) -> bool:
    """Pedido com esse id e `reply` não vazio no queue do projeto ou global."""
    for q in (proj / "ui" / "queue.json", root / ".ui-runtime" / "queue.json"):
        fila = pipeline.read_json(q, [])
        for e in fila if isinstance(fila, list) else []:
            if (isinstance(e, dict) and e.get("id") == aprovacao
                    and isinstance(e.get("reply"), str) and e["reply"].strip()):
                return True
    return False


def autorizar(root: Path, proj: Path, provedor: str, unidades: float,
              aprovacao=None, saldo="auto") -> dict:
    _existe(proj)
    est = estimar(root, provedor, unidades)
    if est is None:
        return _decisao("bloqueado", f"preço desconhecido para {provedor}", None)
    if aprovacao is not None:
        if not _aprovacao_valida(root, proj, aprovacao):
            return _decisao("bloqueado",
                            f"aprovação {aprovacao} não encontrada ou sem resposta", est)
        return _decisao("ok", f"aprovado pelo pedido {aprovacao}", est)
    b = ler_budget(root)
    pid = proj.resolve().relative_to(root.resolve()).as_posix()
    teto_proj = float(b["tetos_projeto"].get(pid, b["teto_projeto_usd"]))
    mes = gasto_mes(root)["usd"]
    if mes + est["usd"] > float(b["teto_mensal_usd"]):
        return _decisao("bloqueado",
                        f"teto mensal: {mes:.2f} + {est['usd']:.2f} > {b['teto_mensal_usd']}", est)
    gp = gasto_projeto(proj)["usd"]
    if gp + est["usd"] > teto_proj:
        return _decisao("bloqueado",
                        f"teto do projeto: {gp:.2f} + {est['usd']:.2f} > {teto_proj}", est)
    if est["creditos"] > 0:
        if saldo == "auto":
            saldo = saldo_elevenlabs(root)
        if saldo is None:
            return _decisao("precisa_aprovacao", "saldo ElevenLabs desconhecido", est)
        if est["creditos"] > saldo["restante"]:
            return _decisao("precisa_aprovacao",
                            f"cota ElevenLabs acaba: restam {saldo['restante']} créditos, "
                            f"ação usa {est['creditos']}", est)
    if est["usd"] > float(b["aprovar_acima_usd"]):
        return _decisao("precisa_aprovacao",
                        f"acima de {b['aprovar_acima_usd']} US$: estimativa {est['usd']:.2f}", est)
    return _decisao("ok", "dentro dos limites", est)


def _cli(ns, root):
    import sys
    if ns.cmd == "autorizar":
        d = autorizar(root, Path(ns.proj), ns.provedor, ns.unidades, aprovacao=ns.aprovacao)
        print(json.dumps(d, ensure_ascii=False))
        sys.exit({"ok": 0, "precisa_aprovacao": 2, "bloqueado": 3}[d["status"]])
    if ns.cmd == "registrar":
        print(json.dumps(registrar(Path(ns.proj), ns.provedor, ns.unidades, usd=ns.usd,
                                   creditos=ns.creditos, aprovacao=ns.aprovacao,
                                   nota=ns.nota, root=root), ensure_ascii=False))
    if ns.cmd == "saldo":
        print(json.dumps(saldo_elevenlabs(root)))


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="orçamento do video_editor")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("autorizar")
    a.add_argument("proj"); a.add_argument("provedor"); a.add_argument("unidades", type=float)
    a.add_argument("--aprovacao", type=int)
    r = sub.add_parser("registrar")
    r.add_argument("proj"); r.add_argument("provedor"); r.add_argument("unidades", type=float)
    r.add_argument("--usd", type=float); r.add_argument("--creditos", type=int)
    r.add_argument("--aprovacao", type=int); r.add_argument("--nota", default="")
    sub.add_parser("saldo")
    ns = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(ns.root)
    try:
        _cli(ns, root)
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False))
        sys.exit(1)
