"""Vídeo por IA (fal.ai): quadros texto→imagem como candidatos do broll.json,
imagem→vídeo dos aprovados, sob orçamento. Sem FastAPI. HTTP por urllib
(_fetch injetável); duração via stock.duracao (ffprobe)."""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import budget  # noqa: E402
import pipeline  # noqa: E402
import stock  # noqa: E402

ROOT = pipeline.ROOT
FILA = "https://queue.fal.run/"
POLL_S = 5.0
TIMEOUT_S = 600.0
MAX_IMG = 8 * 1024 * 1024
TAMANHO = {"16:9": "landscape_16_9", "9:16": "portrait_16_9"}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
EXIT = {"ok": 0, "precisa_aprovacao": 2, "bloqueado": 3}
_dormir = time.sleep

def chave() -> str:
    return os.environ.get("FAL_KEY") or stock._ler_env().get("FAL_KEY", "")

def config(root: Path) -> dict:
    cfg = pipeline.read_json(Path(root) / "ui" / "ia.json", None)
    if not isinstance(cfg, dict):
        raise ValueError("ui/ia.json ausente ou inválido")
    mods = cfg.get("modelos") if isinstance(cfg.get("modelos"), dict) else {}
    for k in ("quadro", "video", "video_top"):
        m = mods.get(k)
        if not isinstance(m, dict) or not m.get("id") or not m.get("provedor"):
            raise ValueError(f"ui/ia.json: modelos.{k} sem id/provedor")
        if k != "quadro":
            s = m.get("segundos")
            if not isinstance(s, (int, float)) or isinstance(s, bool) or s <= 0:
                raise ValueError(f"ui/ia.json: modelos.{k}.segundos inválido")
    est = cfg.get("estilos")
    if not isinstance(est, dict) or "padrao" not in est:
        raise ValueError("ui/ia.json: estilos.padrao ausente")
    return cfg

def marca(proj: Path, root: Path) -> str | None:
    """edit/shorts/<marca>/<proj> → <marca>; resto → None (mesma regra de dublagem.voz)."""
    try:
        partes = Path(proj).resolve().relative_to(Path(root).resolve()).parts
    except ValueError:
        return None
    return partes[2] if len(partes) >= 4 and partes[:2] == ("edit", "shorts") else None

def prompt_final(cfg: dict, prompt: str, estilo: str | None) -> str:
    est = cfg["estilos"].get(estilo or "padrao") or cfg["estilos"]["padrao"]
    return f"{prompt.strip()}, {est}" if est else prompt.strip()

def _fetch_http(metodo: str, url: str, headers: dict, corpo: bytes | None):
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, str(e).encode(), {}

def _espera_s(h: dict) -> float:
    try:
        return min(float(h.get("Retry-After") or 5), 60.0)
    except ValueError:
        return 5.0

def _req(metodo: str, url: str, key: str, corpo=None, _fetch=None) -> dict:
    """JSON da fila do fal; 429/5xx/rede → espera Retry-After (máx. 60 s) e tenta 1 vez."""
    fetch = _fetch or _fetch_http
    hdr = {"Authorization": f"Key {key}", "Content-Type": "application/json", "User-Agent": stock.UA}
    dados = None if corpo is None else json.dumps(corpo).encode()
    for tentativa in (1, 2):
        st, b, h = fetch(metodo, url, hdr, dados)
        if (st == 0 or st == 429 or st >= 500) and tentativa == 1:
            _dormir(_espera_s(h))
            continue
        break
    if not 200 <= st < 300:
        raise RuntimeError(f"fal HTTP {st}: {b[:300].decode('utf-8', 'replace')}")
    try:
        return json.loads(b)
    except json.JSONDecodeError:
        raise RuntimeError(f"fal: resposta não-JSON de {stock._url_segura(url)}")

def _baixar(url: str, dst: Path, _fetch=None) -> Path:
    """Mídia do CDN do fal — sem Authorization (a chave só vai para a fila)."""
    st, b, _ = (_fetch or _fetch_http)("GET", url, {"User-Agent": stock.UA}, None)
    if st != 200 or not b:
        raise RuntimeError(f"fal: download falhou (HTTP {st}) {stock._url_segura(url)}")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    tmp.write_bytes(b)
    os.replace(tmp, dst)
    return dst

def _enviar(endpoint: str, entrada: dict, key: str, _fetch=None) -> dict:
    r = _req("POST", FILA + endpoint, key, entrada, _fetch)
    if not (r.get("request_id") and r.get("status_url") and r.get("response_url")):
        raise RuntimeError("fal: envio sem request_id/status_url/response_url")
    return {"id": r["request_id"], "modelo": endpoint,
            "status_url": r["status_url"], "response_url": r["response_url"]}

def _esperar(req: dict, key: str, _fetch=None) -> tuple[str, str]:
    """('ok', '') | ('falha', erro) | ('pendente', '') — falha do fal = COMPLETED com `error`."""
    for _ in range(max(1, int(TIMEOUT_S / POLL_S))):
        s = _req("GET", req["status_url"], key, None, _fetch)
        if s.get("status") == "COMPLETED":
            return ("falha", str(s["error"])) if s.get("error") else ("ok", "")
        _dormir(POLL_S)
    return "pendente", ""


def _ler(bj: Path) -> dict:
    try:
        d = stock.ler_broll(bj)
    except OSError:
        raise ValueError(f"broll.json não encontrado: {bj}")
    except json.JSONDecodeError as e:
        raise ValueError(f"broll.json inválido: {e.msg}")
    if not isinstance(d, dict) or not isinstance(d.get("momentos"), list):
        raise ValueError("broll.json sem 'momentos'")
    return d


def _momento(d: dict, mid: str) -> dict:
    for m in d["momentos"]:
        if isinstance(m, dict) and m.get("id") == mid:
            return m
    raise ValueError(f"momento {mid} não existe no broll.json")


def _atualizar(bj: Path, mid: str, fn) -> None:
    """Relê o broll.json do disco, aplica fn só no momento `mid` e grava atômico."""
    d = _ler(bj)
    fn(_momento(d, mid))
    pipeline.atomic_write_json(bj, d)


def _proximo_k(proj: Path, mid: str) -> int:
    cand = Path(proj) / "broll" / "cand"
    k = 1
    while any(cand.glob(f"{mid}-ia{k}.*")):
        k += 1
    return k


def _modelo_key(m: dict) -> str:
    return "video_top" if m.get("modelo") == "video_top" else "video"


def _custo(root: Path, cfg: dict, modelo_key: str):
    mm = cfg["modelos"][modelo_key]
    est = budget.estimar(root, mm["provedor"], mm["segundos"])
    return est["usd"] if est else None


def _cand_ia(arq: str, prompt: str, estilo, aspecto: str, custo, licenca: str) -> dict:
    return {"arq": arq, "fonte": "ia", "tipo": "foto", "prompt": prompt, "estilo": estilo,
            "aspecto": aspecto, "custo_est": custo, "licenca": licenca, "autor": "", "url": "",
            "id": Path(arq).stem, "dur": 0.0, "largura": 0}


def quadros(root: Path, proj: Path, mid: str, prompt: str, estilo: str | None = None, n: int = 3,
            aspecto: str = "16:9", aprovacao=None, _fetch=None) -> dict:
    root, proj = Path(root), Path(proj)
    if aspecto not in TAMANHO:
        raise ValueError(f"aspecto inválido: {aspecto} (use 16:9 ou 9:16)")
    if not 1 <= int(n) <= 4:
        raise ValueError("n deve ser de 1 a 4")
    cfg = config(root)
    bj = proj / "broll.json"
    m = _momento(_ler(bj), mid)
    key = chave()
    if not key:
        raise ValueError("FAL_KEY ausente em video-use/.env")
    mq = cfg["modelos"]["quadro"]
    d = budget.autorizar(root, proj, mq["provedor"], n, aprovacao=aprovacao)
    if d["status"] != "ok":
        return d
    mc = marca(proj, root)
    estilo = estilo or (mc if mc in cfg["estilos"] else "padrao")
    req = _enviar(mq["id"], {**mq.get("entrada", {}), "prompt": prompt_final(cfg, prompt, estilo),
                             "image_size": TAMANHO[aspecto], "num_images": int(n)}, key, _fetch)
    estado, erro = _esperar(req, key, _fetch)
    if estado != "ok":
        # ponytail: quadro em timeout não é retomado (centavos); animar retoma, que é o caro
        raise RuntimeError(f"fal: quadros {estado}: {erro or 'tempo esgotado'}")
    budget.registrar(proj, mq["provedor"], n, aprovacao=aprovacao, nota=f"{mid} quadros"[:80], root=root)
    res = _req("GET", req["response_url"], key, None, _fetch)
    urls = [i["url"] for i in res.get("images") or [] if isinstance(i, dict) and i.get("url")]
    if not urls:
        raise RuntimeError("fal: resultado sem images")
    custo = _custo(root, cfg, _modelo_key(m))
    novos, k = [], _proximo_k(proj, mid)
    for url in urls[:int(n)]:
        dst = _baixar(url, proj / "broll" / "cand" / f"{mid}-ia{k}.png", _fetch)
        novos.append(_cand_ia(dst.relative_to(proj).as_posix(), prompt, estilo, aspecto, custo,
                              f"gerado por IA (fal/{mq['id']})"))
        k += 1
    _atualizar(bj, mid, lambda mm: mm.setdefault("candidatos", []).extend(novos))
    return {"status": "ok", "candidatos": [c["arq"] for c in novos], "estimativa": d["estimativa"]}


def asset(root: Path, proj: Path, mid: str, arquivo: Path, movimento: str) -> dict:
    """Asset da marca (foto/print/mockup) como quadro IA, sem gerar imagem nem gastar."""
    root, proj, src = Path(root), Path(proj), Path(arquivo)
    ext = src.suffix.lower()
    if ext not in MIME:
        raise ValueError(f"asset precisa ser imagem (png/jpg/webp): {src.name}")
    if not src.is_file():
        raise ValueError(f"asset não existe: {src}")
    cfg = config(root)
    bj = proj / "broll.json"
    m = _momento(_ler(bj), mid)
    dst = proj / "broll" / "cand" / f"{mid}-ia{_proximo_k(proj, mid)}{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    c = _cand_ia(dst.relative_to(proj).as_posix(), movimento, None, "", _custo(root, cfg, _modelo_key(m)),
                 "asset da marca animado por IA")
    c["asset"] = True
    _atualizar(bj, mid, lambda mm: mm.setdefault("candidatos", []).append(c))
    return {"status": "ok", "candidato": c["arq"]}


def _alvos(d: dict, ids=None):
    """Aprovados cujo escolhido é quadro IA ainda não animado (modo foto nunca anima)."""
    for m in d.get("momentos", []):
        if not isinstance(m, dict) or m.get("status") != "aprovado" or m.get("modo") == "foto":
            continue
        if ids and m.get("id") not in ids:
            continue
        c = stock._cand_por_rotulo(m, m.get("escolhido"))
        if c is None and not m.get("escolhido") and m.get("candidatos"):
            c = m["candidatos"][0]          # mesma regra do stock.preparar
        if c and c.get("fonte") == "ia" and c.get("tipo") == "foto":
            yield m, c


def estimar(root: Path, proj: Path, ids=None) -> dict:
    root, proj = Path(root), Path(proj)
    cfg = config(root)
    itens = []
    for m, c in _alvos(_ler(proj / "broll.json"), ids):
        if (c.get("fal_req") or {}).get("pago"):
            continue
        mk = _modelo_key(m)
        itens.append({"id": m["id"], "modelo": mk, "usd": _custo(root, cfg, mk) or 0.0})
    tot = round(sum(i["usd"] for i in itens), 4)
    return {"itens": itens, "usd": tot,
            "texto": f"animar {len(itens)} clipe(s) ≈ US${tot:.2f}".replace(".", ",")}


def _animar_um(root: Path, cfg: dict, proj: Path, bj: Path, m: dict, c: dict, key: str,
               aprovacao, _fetch) -> tuple[str, float]:
    mm = cfg["modelos"][_modelo_key(m)]
    quadro = c["arq"]

    def salva(**campos):   # relê o broll.json e atualiza só este candidato (casado pelo arq do quadro)
        def f(mom):
            for cc in mom.get("candidatos", []):
                if isinstance(cc, dict) and cc.get("arq") == quadro:
                    for k, v in campos.items():
                        if v is None:
                            cc.pop(k, None)
                        else:
                            cc[k] = v
                    return
            raise ValueError(f"{m['id']}: candidato {quadro} sumiu do broll.json")
        _atualizar(bj, m["id"], f)

    req = c.get("fal_req")
    if not req:
        img = proj / quadro
        if img.stat().st_size > MAX_IMG:
            raise ValueError(f"{m['id']}: quadro > 8 MB, reduza a imagem")
        uri = f"data:{MIME.get(img.suffix.lower(), 'image/png')};base64," + base64.b64encode(img.read_bytes()).decode()
        prompt = (c.get("prompt") or "") if c.get("asset") else prompt_final(cfg, c.get("prompt") or "", c.get("estilo"))
        req = _enviar(mm["id"], {**mm.get("entrada", {}), "prompt": prompt, "image_url": uri}, key, _fetch)
        req.update(provedor=mm["provedor"], segundos=mm["segundos"])
        salva(fal_req=req)                  # antes do poll: queda aqui → próximo animar só faz poll
    usd = 0.0
    if not req.get("pago"):
        estado, erro = _esperar(req, key, _fetch)
        if estado == "pendente":
            return "pendente", 0.0
        if estado == "falha":
            salva(fal_req=None)
            raise RuntimeError(f"fal: {erro}")
        usd = budget.registrar(proj, req["provedor"], req["segundos"], aprovacao=aprovacao,
                               nota=f"{m['id']} {req['modelo']}"[:80], root=root)["usd"]
        req = {**req, "pago": True}
        salva(fal_req=req)                  # pago: nunca registrar de novo
    if not req.get("resultado_url"):
        res = _req("GET", req["response_url"], key, None, _fetch)
        url = res["video"].get("url") if isinstance(res.get("video"), dict) else None
        if not url:
            raise RuntimeError("fal: resultado sem video.url")
        req = {**req, "resultado_url": url}
        salva(fal_req=req)
    mp4 = Path(quadro).with_suffix(".mp4")
    _baixar(req["resultado_url"], proj / mp4, _fetch)
    salva(arq=mp4.as_posix(), tipo="video", dur=round(stock.duracao(proj / mp4), 3), quadro=quadro,
          modelo_video=req["modelo"], licenca=f"gerado por IA (fal/{req['modelo']})", fal_req=None)
    return "feito", usd


def animar(root: Path, proj: Path, ids=None, aprovacao=None, _fetch=None) -> dict:
    root, proj = Path(root), Path(proj)
    cfg = config(root)
    bj = proj / "broll.json"
    alvos = list(_alvos(_ler(bj), ids))
    faltam = [m["id"] for m, c in alvos if not (proj / c["arq"]).is_file()]
    if faltam:
        raise ValueError(f"quadro ausente no disco: {', '.join(faltam)}")
    if not alvos:
        return {"status": "ok", "feitos": [], "falhas": [], "pendentes": [], "usd": 0.0}
    key = chave()
    if not key:
        raise ValueError("FAL_KEY ausente em video-use/.env")
    seg = {}
    for m, c in alvos:
        if not c.get("fal_req"):           # já enviados foram autorizados na rodada anterior
            mm = cfg["modelos"][_modelo_key(m)]
            seg[mm["provedor"]] = seg.get(mm["provedor"], 0) + mm["segundos"]
    for prov, s in seg.items():
        d = budget.autorizar(root, proj, prov, s, aprovacao=aprovacao)
        if d["status"] != "ok":
            return d
    out = {"status": "ok", "feitos": [], "falhas": [], "pendentes": [], "usd": 0.0}
    for m, c in alvos:
        try:
            estado, usd = _animar_um(root, cfg, proj, bj, m, c, key, aprovacao, _fetch)
        except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
            out["falhas"].append({"id": m["id"], "erro": str(e)})
            continue
        out["feitos" if estado == "feito" else "pendentes"].append(m["id"])
        out["usd"] = round(out["usd"] + usd, 4)
    return out


def _cli(ns, root: Path):
    if ns.cmd == "quadros":
        d = quadros(root, Path(ns.proj), ns.mid, ns.prompt, estilo=ns.estilo, n=ns.n,
                    aspecto=ns.aspecto, aprovacao=ns.aprovacao)
        return d, EXIT[d["status"]]
    if ns.cmd == "asset":
        return asset(root, Path(ns.proj), ns.mid, Path(ns.arquivo), ns.movimento), 0
    if ns.cmd == "estimar":
        return estimar(root, Path(ns.proj)), 0
    ids = [i.strip() for i in ns.ids.split(",") if i.strip()] if ns.ids else None
    d = animar(root, Path(ns.proj), ids=ids, aprovacao=ns.aprovacao)
    if d["status"] == "ok" and d["falhas"] and not d["feitos"] and not d["pendentes"]:
        return d, 1
    return d, EXIT[d["status"]]


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="vídeo por IA (fal) do video_editor")
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("quadros"); p.add_argument("proj"); p.add_argument("mid"); p.add_argument("prompt")
    p.add_argument("--estilo"); p.add_argument("--n", type=int, default=3)
    p.add_argument("--aspecto", default="16:9"); p.add_argument("--aprovacao", type=int)
    p = sub.add_parser("asset"); p.add_argument("proj"); p.add_argument("mid")
    p.add_argument("arquivo"); p.add_argument("movimento")
    p = sub.add_parser("estimar"); p.add_argument("proj")
    p = sub.add_parser("animar"); p.add_argument("proj"); p.add_argument("--ids")
    p.add_argument("--aprovacao", type=int)
    ns = ap.parse_args()
    try:
        out, code = _cli(ns, Path(ns.root))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
