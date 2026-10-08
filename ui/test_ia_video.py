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


def _quadro(bj, midia, mid="b01", **mom):
    """Põe um quadro IA aprovado como escolhido do momento `mid`."""
    proj = bj.parent
    d = _ler(bj)
    m = next(x for x in d["momentos"] if x["id"] == mid)
    arq = f"broll/cand/{mid}-ia1.png"
    (proj / arq).parent.mkdir(parents=True, exist_ok=True)
    (proj / arq).write_bytes(midia["png"])
    m["candidatos"].append({"arq": arq, "fonte": "ia", "tipo": "foto", "prompt": "gavel", "estilo": "padrao",
                            "custo_est": 0.35, "licenca": "gerado por IA (fal/fal-ai/flux/schnell)",
                            "autor": "", "url": "", "dur": 0.0, "largura": 0})
    m.update(status="aprovado", escolhido=f"{mid}-{len(m['candidatos'])}", **mom)
    bj.write_text(json.dumps(d), encoding="utf-8")
    return arq


def _custos(proj):
    p = proj / "ui" / "costs.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _budget(root, **b):
    (root / ".ui-runtime").mkdir(exist_ok=True)
    (root / ".ui-runtime" / "budget.json").write_text(json.dumps(b), encoding="utf-8")


def test_animar_feliz(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    fake = FakeFal(midia, polls=2)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r == {"status": "ok", "feitos": ["b01"], "falhas": [], "pendentes": [], "usd": 0.35}
    (metodo, url, body, _), = fake.envios()
    assert url == FILA + "fal-ai/kling/i2v"
    assert body["image_url"].startswith("data:image/png;base64,")
    assert body["prompt"] == "gavel, neutral tones" and body["duration"] == "5"
    c = _mom(bj, "b01")["candidatos"][1]
    assert c["arq"] == "broll/cand/b01-ia1.mp4" and c["tipo"] == "video"
    assert c["quadro"] == "broll/cand/b01-ia1.png" and c["modelo_video"] == "fal-ai/kling/i2v"
    assert abs(c["dur"] - 5.0) < 0.2 and "fal_req" not in c
    assert [l["provedor"] for l in _custos(proj)] == ["fal_video"] and _custos(proj)[0]["usd"] == 0.35
    assert fake.cdn() and all("Authorization" not in h for *_, h in fake.cdn())
    assert stock.preparar(bj, proj / "edl.json", proj)["ok"]


def test_animar_retoma_sem_reenviar(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    d = _ler(bj)
    base = FILA + "fal-ai/kling/i2v/requests/r9"
    d["momentos"][0]["candidatos"][1]["fal_req"] = {"id": "r9", "modelo": "fal-ai/kling/i2v",
        "status_url": base + "/status", "response_url": base, "provedor": "fal_video", "segundos": 5}
    bj.write_text(json.dumps(d), encoding="utf-8")
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"] and fake.envios() == []
    assert len(_custos(proj)) == 1


def test_timeout_pendente_depois_conclui(root, midia, monkeypatch):
    monkeypatch.setattr(ia_video, "TIMEOUT_S", 15.0)
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    fake = FakeFal(midia, polls=99)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["pendentes"] == ["b01"] and r["feitos"] == [] and r["usd"] == 0.0
    assert _mom(bj, "b01")["candidatos"][1]["fal_req"]["id"] == "r0"
    assert _custos(proj) == []
    fake.polls = 1
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"] and len(fake.envios()) == 1
    assert len(_custos(proj)) == 1


def test_falha_do_fal_nao_registra(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    r = ia_video.animar(root, proj, _fetch=FakeFal(midia, polls=1, erros={"r0": "content policy"}))
    assert r["feitos"] == [] and r["falhas"][0]["id"] == "b01" and "content policy" in r["falhas"][0]["erro"]
    c = _mom(bj, "b01")["candidatos"][1]
    assert "fal_req" not in c and c["tipo"] == "foto"
    assert _custos(proj) == []


def test_download_falha_depois_de_pago(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    fake = FakeFal(midia, polls=1, falhas_cdn=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["falhas"][0]["id"] == "b01" and "download" in r["falhas"][0]["erro"]
    req = _mom(bj, "b01")["candidatos"][1]["fal_req"]
    assert req["pago"] is True and req["resultado_url"] == "https://cdn/v.mp4"
    assert len(_custos(proj)) == 1
    polls_antes = len(fake.status())
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"] and r["usd"] == 0.0
    assert len(fake.envios()) == 1 and len(fake.status()) == polls_antes
    assert len(_custos(proj)) == 1


def test_lote_uma_falha_outra_ok(root, midia):
    _budget(root, aprovar_acima_usd=5)
    proj = root / "edit-fake"; bj = _broll(proj, {"id": "b02", "t_in": 40.0, "t_out": 43.0})
    _quadro(bj, midia, "b01"); _quadro(bj, midia, "b02")
    r = ia_video.animar(root, proj, _fetch=FakeFal(midia, polls=1, erros={"r0": "nsfw"}))
    assert r["feitos"] == ["b02"] and [f["id"] for f in r["falhas"]] == ["b01"]
    assert len(_custos(proj)) == 1


def test_filtro_foto_e_stock(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj, {"id": "b02", "t_in": 40.0, "t_out": 43.0})
    _quadro(bj, midia, "b01", modo="foto")
    d = _ler(bj); d["momentos"][1].update(status="aprovado", escolhido="b02-1")
    bj.write_text(json.dumps(d), encoding="utf-8")
    fake = FakeFal(midia)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r == {"status": "ok", "feitos": [], "falhas": [], "pendentes": [], "usd": 0.0}
    assert fake.chamadas == []


def test_top_usa_veo_e_aprovacao(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia, modelo="video_top")
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["status"] == "precisa_aprovacao" and fake.chamadas == []      # 4 s × 0.40 = 1.60 > 0.5
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "queue.json").write_text(json.dumps([{"id": 7, "status": "pending", "reply": "ok"}]),
                                            encoding="utf-8")
    r = ia_video.animar(root, proj, aprovacao=7, _fetch=fake)
    assert r["feitos"] == ["b01"]
    assert fake.envios()[0][1] == FILA + "fal-ai/veo/i2v" and fake.envios()[0][2]["duration"] == "4s"
    (l,) = _custos(proj)
    assert l["provedor"] == "fal_video_top" and l["aprovacao"] == 7 and l["usd"] == 1.6


def test_estimar(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj, {"id": "b02", "t_in": 40.0, "t_out": 43.0})
    _quadro(bj, midia, "b01"); _quadro(bj, midia, "b02", modelo="video_top")
    e = ia_video.estimar(root, proj)
    assert e["usd"] == 1.95 and e["texto"] == "animar 2 clipe(s) ≈ US$1,95"
    assert e["itens"] == [{"id": "b01", "modelo": "video", "usd": 0.35},
                          {"id": "b02", "modelo": "video_top", "usd": 1.6}]
    assert ia_video.estimar(root, proj, ids=["b01"])["usd"] == 0.35


def test_merge_preserva_candidato_novo(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    def ao_enviar(url, body):      # alguém grava no broll.json enquanto o fal trabalha
        d = _ler(bj)
        d["momentos"][0]["candidatos"].append({"arq": "broll/cand/extra.jpg", "fonte": "pexels", "tipo": "foto"})
        bj.write_text(json.dumps(d), encoding="utf-8")
    ia_video.animar(root, proj, _fetch=FakeFal(midia, polls=1, ao_enviar=ao_enviar))
    arqs = [c["arq"] for c in _mom(bj, "b01")["candidatos"]]
    assert arqs == ["broll/cand/st-1.mp4", "broll/cand/b01-ia1.mp4", "broll/cand/extra.jpg"]


def test_quadro_ausente_e_grande(root, midia, monkeypatch):
    proj = root / "edit-fake"; bj = _broll(proj); arq = _quadro(bj, midia)
    monkeypatch.setattr(ia_video, "MAX_IMG", 10)
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert "8 MB" in r["falhas"][0]["erro"] and fake.envios() == []
    (proj / arq).unlink()
    with pytest.raises(ValueError, match="b01"):
        ia_video.animar(root, proj, _fetch=fake)


def _cli(root, *args):
    r = subprocess.run([sys.executable, str(Path(ia_video.__file__)), "--root", str(root), *args],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout)


def test_cli(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); _quadro(bj, midia)
    code, out = _cli(root, "estimar", str(proj))
    assert code == 0 and out["usd"] == 0.35
    code, out = _cli(root, "quadros", str(proj), "b09", "x")
    assert code == 1 and "b09" in out["erro"]
    _budget(root, aprovar_acima_usd=0.001)
    code, out = _cli(root, "quadros", str(proj), "b01", "x", "--n", "2")
    assert code == 2 and out["status"] == "precisa_aprovacao"
    code, out = _cli(root, "animar", str(proj), "--ids", "b07")
    assert code == 0 and out["feitos"] == []


def test_post_nao_repete_em_5xx_mas_repete_em_429(root):
    n = []
    def f503(*a):
        n.append(1); return 503, b"", {}
    with pytest.raises(RuntimeError, match="fal HTTP 503"):
        ia_video._req("POST", FILA + "x", "k", {"a": 1}, f503)
    assert len(n) == 1
    respostas = [(429, b"", {"Retry-After": "1"}), (200, b'{"ok": 1}', {})]
    assert ia_video._req("POST", FILA + "x", "k", {"a": 1}, lambda *a: respostas.pop(0)) == {"ok": 1}


def test_salva_falha_apos_envio_nao_reenvia(root, midia, monkeypatch):
    proj = root / "edit-fake"; bj = _broll(proj); arq = _quadro(bj, midia)
    real = ia_video._atualizar
    def quebra(bj_, mid, fn):
        raise PermissionError("broll.json aberto")
    monkeypatch.setattr(ia_video, "_atualizar", quebra)
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["falhas"][0]["id"] == "b01" and len(fake.envios()) == 1
    assert (proj / (arq + ".fal.json")).exists()
    monkeypatch.setattr(ia_video, "_atualizar", real)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"] and len(fake.envios()) == 1
    assert len(_custos(proj)) == 1
    assert not (proj / (arq + ".fal.json")).exists()


def test_registro_nao_duplica_se_salvar_pago_falha(root, midia, monkeypatch):
    proj = root / "edit-fake"; bj = _broll(proj); arq = _quadro(bj, midia)
    real = ia_video._atualizar
    estado = {"quebrou": False}
    def quebra_no_pago(bj_, mid, fn):
        d = _ler(bj_)
        fn(next(m for m in d["momentos"] if m["id"] == mid))
        c = next(c for c in d["momentos"][0]["candidatos"] if c.get("fonte") == "ia")
        if (c.get("fal_req") or {}).get("pago") and not estado["quebrou"]:
            estado["quebrou"] = True
            raise PermissionError("broll.json aberto")
        real(bj_, mid, fn)
    monkeypatch.setattr(ia_video, "_atualizar", quebra_no_pago)
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["falhas"] and len(_custos(proj)) == 1
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"] and len(fake.envios()) == 1
    assert len(_custos(proj)) == 1


def test_lote_dois_modelos_pede_aprovacao(root, midia):
    _budget(root, aprovar_acima_usd=2)
    proj = root / "edit-fake"; bj = _broll(proj, {"id": "b02", "t_in": 40.0, "t_out": 43.0})
    _quadro(bj, midia, "b01"); _quadro(bj, midia, "b02", modelo="video_top")
    fake = FakeFal(midia, polls=1)
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["status"] == "precisa_aprovacao" and r["estimativa"]["usd"] == 1.95 and fake.chamadas == []
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "queue.json").write_text(json.dumps([{"id": 8, "reply": "ok"}]), encoding="utf-8")
    r = ia_video.animar(root, proj, aprovacao=8, _fetch=fake)
    assert sorted(r["feitos"]) == ["b01", "b02"]


def test_quadro_ausente_nao_bloqueia_item_pago(root, midia):
    proj = root / "edit-fake"; bj = _broll(proj); arq = _quadro(bj, midia)
    fake = FakeFal(midia, polls=1, falhas_cdn=1)
    ia_video.animar(root, proj, _fetch=fake)          # pago, download falhou
    (proj / arq).unlink()
    r = ia_video.animar(root, proj, _fetch=fake)
    assert r["feitos"] == ["b01"]
