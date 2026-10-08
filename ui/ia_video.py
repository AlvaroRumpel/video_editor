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
