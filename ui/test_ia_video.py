import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import budget
import ia_video
import stock
from test_pipeline import fake_root  # noqa: F401 — fixture reexport

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")

FILA = ia_video.FILA
CFG = {"modelos": {
    "quadro": {"id": "fal-ai/flux/schnell", "provedor": "fal_quadro", "entrada": {"output_format": "png"}},
    "video": {"id": "fal-ai/kling/i2v", "provedor": "fal_video", "segundos": 5, "entrada": {"duration": "5"}},
    "video_top": {"id": "fal-ai/veo/i2v", "provedor": "fal_video_top", "segundos": 4, "entrada": {"duration": "4s"}}},
    "estilos": {"padrao": "neutral tones", "anotus": "purple accents"}}
PRECOS = {"fal_quadro": {"unidade": "imagem", "usd": 0.006, "creditos": 0},
          "fal_video": {"unidade": "segundo", "usd": 0.07, "creditos": 0},
          "fal_video_top": {"unidade": "segundo", "usd": 0.4, "creditos": 0}}

def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)

@pytest.fixture
def root(fake_root, monkeypatch):
    (fake_root / "ui").mkdir(exist_ok=True)
    (fake_root / "ui" / "ia.json").write_text(json.dumps(CFG), encoding="utf-8")
    (fake_root / "ui" / "precos.json").write_text(json.dumps(PRECOS), encoding="utf-8")
    monkeypatch.setenv("FAL_KEY", "k-teste")
    monkeypatch.setattr(ia_video, "_dormir", lambda s: None)
    return fake_root

@pytest.fixture(scope="module")
def midia(tmp_path_factory):
    d = tmp_path_factory.mktemp("midia")
    _ff("-f", "lavfi", "-i", "testsrc=s=1280x720:d=1", "-frames:v", "1", str(d / "q.png"))
    _ff("-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=5", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(d / "v.mp4"))
    return {"png": (d / "q.png").read_bytes(), "mp4": (d / "v.mp4").read_bytes()}

class FakeFal:
    """Fila do fal em memória. POST = envio; GET .../status = poll; GET .../requests/<id> = resultado;
    GET https://cdn/... = mídia. `erros` = {request_id: mensagem} → COMPLETED com error."""

    def __init__(self, midia, polls=2, erros=None, falhas_cdn=0, ao_enviar=None):
        self.midia, self.polls, self.erros = midia, polls, erros or {}
        self.falhas_cdn, self.ao_enviar = falhas_cdn, ao_enviar
        self.chamadas, self.contagem = [], {}

    def envios(self):
        return [c for c in self.chamadas if c[0] == "POST"]

    def status(self):
        return [c for c in self.chamadas if c[1].endswith("/status")]

    def cdn(self):
        return [c for c in self.chamadas if c[1].startswith("https://cdn/")]

    def __call__(self, metodo, url, headers, corpo):
        body = json.loads(corpo) if corpo else None
        self.chamadas.append((metodo, url, body, headers))
        if url.startswith("https://cdn/"):
            if self.falhas_cdn:
                self.falhas_cdn -= 1
                return 500, b"", {}
            return 200, self.midia["mp4" if url.endswith(".mp4") else "png"], {}
        if metodo == "POST":
            rid = f"r{len(self.envios()) - 1}"
            if self.ao_enviar:
                self.ao_enviar(url, body)
            base = f"{url}/requests/{rid}"
            return 200, json.dumps({"request_id": rid, "status_url": base + "/status",
                                    "response_url": base}).encode(), {}
        rid = url.split("/requests/")[1].split("/")[0]
        if url.endswith("/status"):
            n = self.contagem[url] = self.contagem.get(url, 0) + 1
            if n < self.polls:
                return 200, json.dumps({"status": "IN_PROGRESS"}).encode(), {}
            st = {"status": "COMPLETED"}
            if rid in self.erros:
                st["error"] = self.erros[rid]
            return 200, json.dumps(st).encode(), {}
        if "flux" in url:
            n = next(c for c in reversed(self.envios()) if "flux" in c[1])[2]["num_images"]
            return 200, json.dumps({"images": [{"url": f"https://cdn/img{k}.png"} for k in range(n)]}).encode(), {}
        return 200, json.dumps({"video": {"url": "https://cdn/v.mp4"}}).encode(), {}

def test_config_valida(root):
    assert ia_video.config(root)["modelos"]["video"]["segundos"] == 5
    ruim = json.loads(json.dumps(CFG)); del ruim["modelos"]["video"]["segundos"]
    (root / "ui" / "ia.json").write_text(json.dumps(ruim), encoding="utf-8")
    with pytest.raises(ValueError, match="video.segundos"):
        ia_video.config(root)
    (root / "ui" / "ia.json").unlink()
    with pytest.raises(ValueError, match="ia.json"):
        ia_video.config(root)

def test_config_real_do_repo_e_valida():
    cfg = ia_video.config(ia_video.ROOT)
    precos = json.loads((ia_video.ROOT / "ui" / "precos.json").read_text(encoding="utf-8"))
    for k in ("quadro", "video", "video_top"):
        assert cfg["modelos"][k]["provedor"] in precos

def test_chave_env_e_arquivo(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "do-env")
    assert ia_video.chave() == "do-env"
    monkeypatch.delenv("FAL_KEY")
    monkeypatch.setattr(stock, "_ler_env", lambda: {"FAL_KEY": "do-arquivo"})
    assert ia_video.chave() == "do-arquivo"

def test_marca(root):
    assert ia_video.marca(root / "edit" / "shorts" / "anotus" / "x", root) == "anotus"
    assert ia_video.marca(root / "edit-fake", root) is None

def test_prompt_final():
    assert ia_video.prompt_final(CFG, " gavel ", None) == "gavel, neutral tones"
    assert ia_video.prompt_final(CFG, "gavel", "anotus") == "gavel, purple accents"
    assert ia_video.prompt_final(CFG, "gavel", "nao-existe") == "gavel, neutral tones"

def test_req_retry_429(root, monkeypatch):
    dormiu = []
    monkeypatch.setattr(ia_video, "_dormir", dormiu.append)
    respostas = [(429, b"", {"Retry-After": "2"}), (200, b'{"ok": 1}', {})]
    vistos = []
    def fetch(metodo, url, headers, corpo):
        vistos.append(headers); return respostas.pop(0)
    assert ia_video._req("GET", FILA + "x", "k1", None, fetch) == {"ok": 1}
    assert dormiu == [2.0]
    assert vistos[0]["Authorization"] == "Key k1"

def test_req_4xx_nao_repete_e_5xx_repete_uma_vez(root):
    n = []
    def f422(*a):
        n.append(1); return 422, b'{"detail": "prompt bloqueado"}', {}
    with pytest.raises(RuntimeError, match="fal HTTP 422.*prompt bloqueado"):
        ia_video._req("POST", FILA + "x", "k", {"a": 1}, f422)
    assert len(n) == 1
    n.clear()
    def f503(*a):
        n.append(1); return 503, b"", {"Retry-After": "domingo"}
    with pytest.raises(RuntimeError, match="fal HTTP 503"):
        ia_video._req("GET", FILA + "x", "k", None, f503)
    assert len(n) == 2

def test_enviar_e_esperar(root, midia):
    fake = FakeFal(midia, polls=2)
    req = ia_video._enviar("fal-ai/kling/i2v", {"prompt": "x"}, "k", fake)
    assert req["id"] == "r0" and req["modelo"] == "fal-ai/kling/i2v"
    assert req["status_url"].endswith("/requests/r0/status")
    assert fake.envios()[0][1] == FILA + "fal-ai/kling/i2v"
    assert ia_video._esperar(req, "k", fake) == ("ok", "")
    assert len(fake.status()) == 2

def test_esperar_erro_e_timeout(root, midia, monkeypatch):
    fake = FakeFal(midia, polls=1, erros={"r0": "content policy"})
    req = ia_video._enviar("fal-ai/kling/i2v", {}, "k", fake)
    assert ia_video._esperar(req, "k", fake) == ("falha", "content policy")
    monkeypatch.setattr(ia_video, "TIMEOUT_S", 15.0)
    fake = FakeFal(midia, polls=99)
    req = ia_video._enviar("fal-ai/kling/i2v", {}, "k", fake)
    assert ia_video._esperar(req, "k", fake) == ("pendente", "")
    assert len(fake.status()) == 3

def test_baixar_sem_chave(root, midia, tmp_path):
    fake = FakeFal(midia, falhas_cdn=1)
    dst = tmp_path / "a" / "v.mp4"
    with pytest.raises(RuntimeError, match="download"):
        ia_video._baixar("https://cdn/v.mp4", dst, fake)
    assert not dst.exists()
    assert ia_video._baixar("https://cdn/v.mp4", dst, fake) == dst
    assert dst.read_bytes() == midia["mp4"]
    assert all("Authorization" not in c[3] for c in fake.cdn())


def _broll(proj, *moms):
    proj.mkdir(parents=True, exist_ok=True)
    base = {"t_in": 10.0, "t_out": 13.0, "modo": "cutin", "frase": "x", "termo": "gavel",
            "candidatos": [{"arq": "broll/cand/st-1.mp4", "fonte": "pexels", "tipo": "video", "dur": 6.0,
                            "autor": "A", "url": "https://x/", "licenca": "Pexels License"}],
            "escolhido": None, "offset": 0.0, "status": "proposto"}
    bj = proj / "broll.json"
    lista = [{**json.loads(json.dumps(base)), "id": "b01"}]
    lista += [{**json.loads(json.dumps(base)), **m} for m in moms]
    bj.write_text(json.dumps({"momentos": lista}), encoding="utf-8")
    return bj


def _ler(bj):
    return json.loads(bj.read_text(encoding="utf-8"))


def _mom(bj, mid):
    return next(m for m in _ler(bj)["momentos"] if m["id"] == mid)


def test_quadros(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj)
    fake = FakeFal(midia, polls=1)
    r = ia_video.quadros(root, proj, "b01", "gavel on desk", _fetch=fake)
    assert r["status"] == "ok"
    assert r["candidatos"] == [f"broll/cand/b01-ia{k}.png" for k in (1, 2, 3)]
    assert all((proj / a).read_bytes() == midia["png"] for a in r["candidatos"])
    cs = _mom(bj, "b01")["candidatos"]
    assert len(cs) == 4 and cs[0]["fonte"] == "pexels"
    c = cs[1]
    assert (c["fonte"], c["tipo"], c["estilo"], c["aspecto"]) == ("ia", "foto", "padrao", "16:9")
    assert c["custo_est"] == 0.35 and c["prompt"] == "gavel on desk"
    assert c["licenca"] == "gerado por IA (fal/fal-ai/flux/schnell)" and c["autor"] == "" and c["url"] == ""
    body = fake.envios()[0][2]
    assert body == {"output_format": "png", "prompt": "gavel on desk, neutral tones",
                    "image_size": "landscape_16_9", "num_images": 3}
    assert budget.gasto_projeto(proj)["usd"] == 0.018


def test_quadros_numeracao_continua(root, midia):
    proj = root / "edit-fake"; _broll(proj)
    ia_video.quadros(root, proj, "b01", "a", n=1, _fetch=FakeFal(midia, polls=1))
    r = ia_video.quadros(root, proj, "b01", "b", n=1, _fetch=FakeFal(midia, polls=1))
    assert r["candidatos"] == ["broll/cand/b01-ia2.png"]


def test_quadros_marca_e_vertical(root, midia):
    proj = root / "edit" / "shorts" / "anotus" / "x"; bj = _broll(proj)
    fake = FakeFal(midia, polls=1)
    ia_video.quadros(root, proj, "b01", "gavel", n=1, aspecto="9:16", _fetch=fake)
    body = fake.envios()[0][2]
    assert body["prompt"] == "gavel, purple accents" and body["image_size"] == "portrait_16_9"
    assert _mom(bj, "b01")["candidatos"][1]["estilo"] == "anotus"


def test_quadros_precisa_aprovacao_nao_envia(root, midia):
    (root / ".ui-runtime").mkdir(exist_ok=True)
    (root / ".ui-runtime" / "budget.json").write_text(json.dumps({"aprovar_acima_usd": 0.001}), encoding="utf-8")
    proj = root / "edit-fake"; bj = _broll(proj)
    fake = FakeFal(midia, polls=1)
    r = ia_video.quadros(root, proj, "b01", "gavel", _fetch=fake)
    assert r["status"] == "precisa_aprovacao" and fake.chamadas == []
    assert len(_mom(bj, "b01")["candidatos"]) == 1
    assert not (proj / "ui" / "costs.jsonl").exists()


def test_quadros_validacoes(root, midia, monkeypatch):
    proj = root / "edit-fake"; _broll(proj)
    with pytest.raises(ValueError, match="b09"):
        ia_video.quadros(root, proj, "b09", "x", _fetch=FakeFal(midia))
    with pytest.raises(ValueError, match="aspecto"):
        ia_video.quadros(root, proj, "b01", "x", aspecto="4:3", _fetch=FakeFal(midia))
    with pytest.raises(ValueError, match="n "):
        ia_video.quadros(root, proj, "b01", "x", n=9, _fetch=FakeFal(midia))
    monkeypatch.delenv("FAL_KEY")
    monkeypatch.setattr(stock, "_ler_env", lambda: {})
    with pytest.raises(ValueError, match="FAL_KEY"):
        ia_video.quadros(root, proj, "b01", "x", _fetch=FakeFal(midia))


def test_quadros_erro_do_fal_nao_registra(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj)
    with pytest.raises(RuntimeError, match="nsfw"):
        ia_video.quadros(root, proj, "b01", "x", _fetch=FakeFal(midia, polls=1, erros={"r0": "nsfw"}))
    assert not (proj / "ui" / "costs.jsonl").exists()
    assert len(_mom(bj, "b01")["candidatos"]) == 1


def test_asset(root, midia, tmp_path):
    proj = root / "edit-fake"; bj = _broll(proj)
    src = tmp_path / "tela.png"; src.write_bytes(midia["png"])
    r = ia_video.asset(root, proj, "b01", src, "slow push in on the screen")
    assert r == {"status": "ok", "candidato": "broll/cand/b01-ia1.png"}
    assert (proj / r["candidato"]).read_bytes() == midia["png"]
    c = _mom(bj, "b01")["candidatos"][1]
    assert c["asset"] is True and c["fonte"] == "ia" and c["prompt"] == "slow push in on the screen"
    assert c["custo_est"] == 0.35
    assert not (proj / "ui" / "costs.jsonl").exists()
    txt = tmp_path / "x.txt"; txt.write_text("x")
    with pytest.raises(ValueError, match="imagem"):
        ia_video.asset(root, proj, "b01", txt, "x")
    with pytest.raises(ValueError, match="não existe"):
        ia_video.asset(root, proj, "b01", tmp_path / "nada.png", "x")
