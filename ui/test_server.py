import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import eventos
import server
import server as server_mod
from test_pipeline import fake_root  # fixture reexport


@pytest.fixture
def client(fake_root):
    server.app.state.root = fake_root
    return TestClient(server.app)


def test_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "edit-fake"


def test_project_payload(client):
    r = client.get("/api/project", params={"id": "edit-fake"})
    assert r.status_code == 200
    assert len(r.json()["edl"]["ranges"]) == 2


def test_project_bad_id(client):
    assert client.get("/api/project",
                      params={"id": "../x"}).status_code == 400


def test_video_range(client):
    r = client.get("/api/video", params={"id": "edit-fake",
                                         "kind": "preview"},
                   headers={"Range": "bytes=0-7"})
    assert r.status_code == 206
    assert len(r.content) == 8


def test_video_missing(client):
    assert client.get("/api/video", params={"id": "edit-fake",
                                            "kind": "final"}).status_code == 404


def test_formats_and_brutos(client, fake_root):
    (fake_root / "Formatos" / "thumbnail.md").write_text("# interna",
                                                         encoding="utf-8")
    fm = client.get("/api/formats").json()
    assert fm[0]["name"] == "padrao-youtube"
    assert "thumbnail" not in [f["name"] for f in fm]
    assert client.get("/api/brutos").json() == []


def test_queue_post_and_read(client):
    r = client.post("/api/queue", params={"id": "edit-fake"},
                    json={"type": "instrucao", "target": 1,
                          "text": "estica corte 1"})
    assert r.status_code == 200
    entry = r.json()
    assert entry["status"] == "pending" and entry["id"]
    q = client.get("/api/project", params={"id": "edit-fake"}).json()["queue"]
    assert q[0]["text"] == "estica corte 1"


def test_queue_rejects_bad_type(client):
    assert client.post("/api/queue", params={"id": "edit-fake"},
                       json={"type": "hack", "text": "x"}).status_code == 400


def test_reply(client):
    qid = client.post("/api/queue", params={"id": "edit-fake"},
                      json={"type": "render", "text": "preview"}).json()["id"]
    r = client.post("/api/reply", params={"id": "edit-fake"},
                    json={"qid": qid, "text": "sim, pode"})
    assert r.status_code == 200
    q = client.get("/api/project", params={"id": "edit-fake"}).json()["queue"]
    entry = next(e for e in q if e["id"] == qid)
    assert entry["reply"] == "sim, pode" and entry["status"] == "pending"


def test_reply_consome_folha(client, fake_root):
    qid = client.post("/api/queue", params={"id": "edit-fake"},
                      json={"type": "instrucao", "text": "escolher"}).json()["id"]
    qpath = fake_root / "edit-fake" / "ui" / "queue.json"
    q = json.loads(qpath.read_text(encoding="utf-8"))
    for e in q:
        if e["id"] == qid:
            e.update(status="waiting_reply", folha="conceitos")
    qpath.write_text(json.dumps(q), encoding="utf-8")
    r = client.post("/api/reply", params={"id": "edit-fake"}, json={"qid": qid, "text": "A"})
    assert r.status_code == 200 and "folha" not in r.json()
    entry = next(e for e in json.loads(qpath.read_text(encoding="utf-8")) if e["id"] == qid)
    assert entry["reply"] == "A" and entry["status"] == "pending" and "folha" not in entry


def test_state_merge(client):
    client.post("/api/state", params={"id": "edit-fake"},
                json={"formato": "padrao-youtube"})
    client.post("/api/state", params={"id": "edit-fake"},
                json={"aprovacoes": [0]})
    st = client.get("/api/project", params={"id": "edit-fake"}).json()["state"]
    assert st == {"formato": "padrao-youtube", "aprovacoes": [0]}


def test_format_save(client, fake_root):
    r = client.put("/api/format", params={"name": "padrao-youtube"},
                   json={"content": "# nova receita"})
    assert r.status_code == 200
    assert (fake_root / "Formatos" / "padrao-youtube.md").read_text(
        encoding="utf-8") == "# nova receita"


def test_format_name_sanitized(client):
    assert client.put("/api/format", params={"name": "../evil"},
                      json={"content": "x"}).status_code == 400


def test_new_project(client, fake_root):
    r = client.post("/api/new-project",
                    json={"bruto": "video.mkv", "formato": "padrao-youtube",
                          "nome": "meu-video"})
    assert r.status_code == 200
    gq = client.get("/api/global-queue").json()
    assert gq[0]["type"] == "novo-projeto"
    assert gq[0]["target"]["bruto"] == "video.mkv"


def test_reply_global(client, fake_root):
    r = client.post("/api/new-project",
                    json={"bruto": "video.mkv", "formato": "padrao-youtube",
                          "nome": "outro-video"})
    qid = r.json()["id"]
    rr = client.post("/api/reply", params={"id": "_global"},
                     json={"qid": qid, "text": "pode sim"})
    assert rr.status_code == 200
    gq = client.get("/api/global-queue").json()
    entry = next(e for e in gq if e["id"] == qid)
    assert entry["reply"] == "pode sim" and entry["status"] == "pending"


def test_events_first_snapshot(client):
    with client.stream("GET", "/api/events",
                       params={"id": "edit-fake", "max_events": 1}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        for line in r.iter_lines():
            if line.startswith("data:"):
                import json as _json
                snap = _json.loads(line[5:])
                assert "mtimes" in snap and "claude_online" in snap
                break


def test_cancel(client):
    qid = client.post("/api/queue", params={"id": "edit-fake"},
                      json={"type": "instrucao", "text": "x"}).json()["id"]
    r = client.post("/api/cancel", params={"id": "edit-fake"},
                    json={"qid": qid})
    assert r.status_code == 200 and r.json()["status"] == "cancelado"
    # cancelar de novo -> 409 (não está mais pending)
    assert client.post("/api/cancel", params={"id": "edit-fake"},
                       json={"qid": qid}).status_code == 409
    assert client.post("/api/cancel", params={"id": "edit-fake"},
                       json={"qid": 1}).status_code == 404


def test_new_project_sem_bruto(client):
    # sem bruto e sem descricao -> 400
    assert client.post("/api/new-project",
                       json={"bruto": None, "formato": "padrao-ads",
                             "nome": "reel-x", "descricao": ""}).status_code == 400
    r = client.post("/api/new-project",
                    json={"bruto": None, "formato": "padrao-ads", "nome": "reel-x",
                          "descricao": "reel sobre feature Y",
                          "fontes": "F:/proj/anotus, https://anotus.app"})
    assert r.status_code == 200
    tg = r.json()["target"]
    assert tg["bruto"] is None and tg["descricao"] == "reel sobre feature Y"
    assert "anotus" in tg["fontes"]


def test_activity(client, fake_root):
    assert client.get("/api/activity").json() == {}
    act = fake_root / ".ui-runtime" / "activity.json"
    act.parent.mkdir(exist_ok=True)
    act.write_text('{"atual": "renderizando 3/5", "anterior": "cortes", '
                   '"ts": "2026-09-01T22:00:00+00:00"}', encoding="utf-8")
    a = client.get("/api/activity").json()
    assert a["atual"] == "renderizando 3/5" and a["anterior"] == "cortes"


def test_budget_get(client, fake_root, monkeypatch):
    monkeypatch.setattr(server.budget, "saldo_elevenlabs", lambda root: None)
    r = client.get("/api/budget")
    assert r.status_code == 200
    j = r.json()
    assert j["budget"]["teto_mensal_usd"] == 30.0
    assert j["gasto_mes"] == {"usd": 0.0, "creditos": 0}
    assert "elevenlabs" in j


def test_budget_put_merge(client, fake_root):
    (fake_root / ".ui-runtime").mkdir()
    (fake_root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"tetos_projeto": {"edit-fake": 12}}), encoding="utf-8")
    r = client.put("/api/budget", json={"teto_mensal_usd": 40})
    assert r.status_code == 200
    saved = json.loads((fake_root / ".ui-runtime" / "budget.json").read_text(encoding="utf-8"))
    assert saved["teto_mensal_usd"] == 40 and saved["tetos_projeto"] == {"edit-fake": 12}


def test_budget_put_rejeita_invalido(client, fake_root):
    assert client.put("/api/budget", json={"teto_mensal_usd": "abc"}).status_code == 400
    assert client.put("/api/budget", json={"teto_projeto_usd": -1}).status_code == 400
    assert client.put("/api/budget", json={"tetos_projeto": {"x": "y"}}).status_code == 400
    assert not (fake_root / ".ui-runtime" / "budget.json").exists()


def test_budget_put_infinity_400(client):
    r = client.put("/api/budget", content='{"teto_mensal_usd": Infinity}',
                   headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_budget_put_null_remove_override(client, fake_root):
    (fake_root / ".ui-runtime").mkdir()
    bp = fake_root / ".ui-runtime" / "budget.json"
    bp.write_text(json.dumps({"tetos_projeto": {"edit-fake": 12, "edit-raw": 7}}), encoding="utf-8")
    r = client.put("/api/budget", json={"tetos_projeto": {"edit-fake": None}})
    assert r.status_code == 200
    assert json.loads(bp.read_text(encoding="utf-8"))["tetos_projeto"] == {"edit-raw": 7}


def test_project_tem_custos(client, fake_root):
    (fake_root / "edit-fake" / "ui").mkdir(exist_ok=True)
    (fake_root / "edit-fake" / "ui" / "costs.jsonl").write_text(
        '{"ts":"2099-01-01T00:00:00+00:00","usd":2.5,"creditos":3}\n', encoding="utf-8")
    j = client.get("/api/project", params={"id": "edit-fake"}).json()
    assert j["custos"] == {"usd": 2.5, "creditos": 3}
    assert j["teto_projeto"] == 5.0


def test_events_inclui_costs_e_budget(client):
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1].strip())
    assert "costs" in snap["mtimes"] and "budget" in snap["mtimes"]


def test_docs_lista_e_renderiza(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "pesquisa.md").write_text("# P\n\n- [F1] x\n", encoding="utf-8")
    (proj / "nota.txt").write_text("nao", encoding="utf-8")
    (proj / "X.MD").write_text("# up", encoding="utf-8")
    (proj / "bom.md").write_bytes(b"# B".join([bytes([0xEF, 0xBB, 0xBF]), b""]))
    r = client.get("/api/docs", params={"id": "edit-fake"})
    assert sorted(d["name"] for d in r.json()) == ["bom.md", "pesquisa.md"]
    assert "<h1>B</h1>" in client.get("/api/doc", params={"id": "edit-fake", "name": "bom.md"}).json()["html"]
    r = client.get("/api/doc", params={"id": "edit-fake", "name": "pesquisa.md"})
    assert r.status_code == 200 and "<h1>P</h1>" in r.json()["html"]


def test_doc_nome_invalido(client, fake_root):
    for nome in ("../x.md", "a/b.md", "a\\b.md", "x.txt", ".md"):
        assert client.get("/api/doc", params={"id": "edit-fake", "name": nome}).status_code == 400
    assert client.get("/api/doc", params={"id": "edit-fake", "name": "nao.md"}).status_code == 404


def test_new_project_roteiro_e_pauta(client, fake_root):
    r = client.post("/api/new-project", json={"formato": "roteiro", "nome": "Prazos", "descricao": "tema prazos",
                                              "duracao_min": 8, "publico": "estudantes"})
    e = r.json()
    assert e["type"] == "roteiro" and e["target"] == {"tema": "tema prazos", "duracao_min": 8, "publico": "estudantes", "nome": "Prazos"}
    r = client.post("/api/new-project", json={"formato": "pauta", "marca": "anotus", "mes": "2026-11"})
    e = r.json()
    assert e["type"] == "pauta" and e["target"] == {"marca": "anotus", "mes": "2026-11"}
    assert client.post("/api/new-project", json={"formato": "pauta"}).status_code == 400
    assert client.post("/api/new-project", json={"formato": "roteiro", "descricao": "t"}).status_code == 400
    q = json.loads((fake_root / ".ui-runtime" / "queue.json").read_text(encoding="utf-8"))
    assert [x["type"] for x in q] == ["roteiro", "pauta"]


def test_queue_aceita_roteiro_pauta(client):
    assert "roteiro" in server.QUEUE_TYPES and "pauta" in server.QUEUE_TYPES
    assert "referencia" in server.HIDDEN_FORMATS


def test_events_inclui_docs(client, fake_root):
    (fake_root / "edit-fake" / "x.md").write_text("a", encoding="utf-8")
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1].strip())
    assert snap["mtimes"]["docs"] is not None


def test_docs_tolera_md_sumido(client, fake_root, monkeypatch):
    import pathlib
    proj = fake_root / "edit-fake"
    (proj / "ok.md").write_text("a", encoding="utf-8")
    (proj / "sumiu.md").write_text("b", encoding="utf-8")
    orig = pathlib.Path.stat

    def stat(self, *a, **k):
        if self.name == "sumiu.md":
            raise OSError("vanished")
        return orig(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "stat", stat)
    r = client.get("/api/docs", params={"id": "edit-fake"})
    assert r.status_code == 200 and [d["name"] for d in r.json()] == ["ok.md"]
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1].strip())
    assert snap["mtimes"]["docs"] is not None


def test_file_png_broll(client, fake_root):
    d = fake_root / "edit-fake" / "broll"; d.mkdir()
    (d / "sheet.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    r = client.get("/api/file", params={"id": "edit-fake", "name": "broll/sheet.png"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")
    for nome in ("broll/../x.png", "sheet.png", "broll/a.md", "broll/sub/a.png", "broll/x.PNG"):
        assert client.get("/api/file", params={"id": "edit-fake", "name": nome}).status_code == 400
    assert client.get("/api/file", params={"id": "edit-fake", "name": "broll/nao.png"}).status_code == 404


def test_docs_lista_sheet(client, fake_root):
    d = fake_root / "edit-fake" / "broll"; d.mkdir()
    (d / "sheet.png").write_bytes(b"\x89PNG")
    (fake_root / "edit-fake" / "a.md").write_text("# a", encoding="utf-8")
    nomes = [x["name"] for x in client.get("/api/docs", params={"id": "edit-fake"}).json()]
    assert nomes == ["a.md", "broll/sheet.png"]


def test_new_project_referencia(client, fake_root):
    r = client.post("/api/new-project", json={"formato": "referencia", "origem": "https://www.youtube.com/shorts/x",
                                              "marca": " Anotus ", "nome": "Prazos", "descricao": "briefing"})
    e = r.json()
    assert e["type"] == "referencia" and e["target"] == {"origem": "https://www.youtube.com/shorts/x", "marca": "anotus",
                                                           "nome": "Prazos", "briefing": "briefing"}
    assert client.post("/api/new-project", json={"formato": "referencia", "nome": "x"}).status_code == 400
    assert client.post("/api/new-project", json={"formato": "referencia", "origem": "a.mp4"}).status_code == 400
    assert "referencia" in server.QUEUE_TYPES


def test_brutos_ref(client, fake_root):
    d = fake_root / "bruto" / "ref"; d.mkdir(parents=True)
    (d / "b.mp4").write_bytes(b"0"); (d / "a.mp4").write_bytes(b"0"); (d / "a.json").write_text("{}", encoding="utf-8")
    assert client.get("/api/brutos-ref").json() == ["a.mp4", "b.mp4"]


def test_file_ref_e_animatic(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "ref").mkdir(); (proj / "ref" / "sheet.png").write_bytes(b"\x89PNG")
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    assert client.get("/api/file", params={"id": "edit-fake", "name": "ref/sheet.png"}).status_code == 200
    assert client.get("/api/file", params={"id": "edit-fake", "name": "animatic-A.png"}).status_code == 200
    for nome in ("ref/../x.png", "animatic-a.png", "animatic-AB.png", "ref/x.PNG", "conceitos.png"):
        assert client.get("/api/file", params={"id": "edit-fake", "name": nome}).status_code == 400
    nomes = [x["name"] for x in client.get("/api/docs", params={"id": "edit-fake"}).json()]
    assert "ref/sheet.png" in nomes and "animatic-A.png" in nomes


def _receita_e_state(root, proj_rel="edit-fake"):
    (root / "Formatos" / "teste.md").write_text(
        "---\netapas: transcricao=transcrição, cortes\n---\n# t\n", encoding="utf-8")
    ui = root / proj_rel / "ui"
    ui.mkdir(parents=True, exist_ok=True)
    (ui / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    return root / proj_rel


def test_quadro_route(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    q = client.get("/api/quadro", params={"id": "edit-fake"}).json()
    assert q["atual"] == "cortes" and [e["id"] for e in q["etapas"]] == ["transcricao", "cortes"]
    assert client.get("/api/quadro", params={"id": "../x"}).status_code == 400


def test_project_has_edl(client):
    assert client.get("/api/project", params={"id": "edit-fake"}).json()["has_edl"] is True
    assert client.get("/api/project", params={"id": "edit-raw"}).json()["has_edl"] is False


def test_library_com_log(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "transcricao", "fim", root=fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": 1, "status": "waiting_reply", "text": "aprova?"},
        {"id": 2, "status": "done", "text": "x"},
        {"id": 3, "status": "pending", "text": "y"}]), encoding="utf-8")
    (proj / "ui" / "costs.jsonl").write_text(
        json.dumps({"ts": "2026-10-07T10:00:00+00:00", "usd": 0.48, "creditos": 0}) + "\n", encoding="utf-8")
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    p = lib["edit-fake"]
    assert p["formato"] == "teste" and p["sem_historico"] is False
    assert p["etapas"] == [{"id": "transcricao", "rotulo": "transcrição", "status": "fim"},
                           {"id": "cortes", "rotulo": "cortes", "status": "andamento"}]
    assert p["atual"] == {"id": "cortes", "rotulo": "cortes", "status": "andamento"}
    assert p["pendencias"] == 1 and [e["id"] for e in p["fila"]] == [1, 3]
    assert p["custo_usd"] == 0.48
    assert p["atividade"] and p["name"] == "edit-fake"


def test_library_projeto_sem_formato(client):
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    raw = lib["edit-raw"]
    assert raw["formato"] is None and raw["etapas"] == [] and raw["atual"] is None
    assert raw["sem_historico"] is True and raw["pendencias"] == 0


def test_library_ordena_por_atividade(client, fake_root):
    velho = fake_root / "edit-fake"
    for p in [velho / "edl.json", velho / "preview.mp4", *velho.glob("ui/*")]:
        os.utime(p, (1_000_000, 1_000_000))
    (fake_root / "edit-raw" / "ui" / "queue.json").write_text("[]", encoding="utf-8")   # mais novo
    ids = [p["id"] for p in client.get("/api/library").json()]
    assert ids.index("edit-raw") < ids.index("edit-fake")


def test_library_heartbeat_e_capa_nao_mudam_atividade(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    for p in [proj / "edl.json", proj / "preview.mp4", *proj.glob("ui/*")]:
        os.utime(p, (1_000_000, 1_000_000))
    antes = {p["id"]: p for p in client.get("/api/library").json()}["edit-fake"]
    (proj / "ui" / "heartbeat").touch()
    (proj / "ui" / "capa.jpg").write_bytes(b"jpg")
    depois = {p["id"]: p for p in client.get("/api/library").json()}["edit-fake"]
    assert depois["atividade"] == antes["atividade"]
    assert depois["capa_v"] == antes["capa_v"] == 1_000_000   # preview.mp4
    (proj / "thumbnail.png").write_bytes(b"png")
    assert {p["id"]: p for p in client.get("/api/library").json()}["edit-fake"]["capa_v"] > 1_000_000


def test_library_projeto_ilegivel_nao_quebra(client, monkeypatch):
    real = eventos.quadro

    def quebra(proj, root=None, agora=None):
        if proj.name == "edit-fake":
            raise RuntimeError("boom")
        return real(proj, root=root, agora=agora)

    monkeypatch.setattr(eventos, "quadro", quebra)
    lib = {p["id"]: p for p in client.get("/api/library").json()}
    assert lib["edit-fake"]["etapas"] == [] and lib["edit-fake"]["name"] == "edit-fake"
    assert "edit-raw" in lib


def test_events_vigia_eventos(client, fake_root):
    proj = _receita_e_state(fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1])
    assert snap["mtimes"]["eventos"] is not None


def _fake_run_ok(calls):
    def run(args, **kw):
        calls.append(args[0])
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 0, stdout="10.0\n", stderr="")
        Path(args[-1]).write_bytes(b"\xff\xd8JPEGFAKE")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return run


def _fake_run_falha(args, **kw):
    raise FileNotFoundError("ffmpeg")


def test_capa_thumbnail_primeiro(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    (fake_root / "edit-fake" / "thumbnail-b.png").write_bytes(b"\x89PNGb")
    (fake_root / "edit-fake" / "thumbnail-a.png").write_bytes(b"\x89PNGa")
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.status_code == 200 and r.content == b"\x89PNGa" and calls == []


def test_capa_frame_do_video_com_cache(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    r = client.get("/api/capa", params={"id": "edit-fake"})   # fixture tem preview.mp4
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert (fake_root / "edit-fake" / "ui" / "capa.jpg").exists()
    assert calls == ["ffprobe", "ffmpeg"]
    client.get("/api/capa", params={"id": "edit-fake"})      # cache válido: não roda de novo
    assert calls == ["ffprobe", "ffmpeg"]


def test_capa_refaz_se_video_mais_novo(client, fake_root, monkeypatch):
    calls = []
    monkeypatch.setattr(server_mod, "_run", _fake_run_ok(calls))
    proj = fake_root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "capa.jpg").write_bytes(b"velha")
    os.utime(proj / "ui" / "capa.jpg", (1_000_000, 1_000_000))
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.content == b"\xff\xd8JPEGFAKE" and calls == ["ffprobe", "ffmpeg"]


def test_capa_ffmpeg_falha_cai_no_animatic(client, fake_root, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    (fake_root / "edit-fake" / "animatic-A.png").write_bytes(b"\x89PNGanim")
    r = client.get("/api/capa", params={"id": "edit-fake"})
    assert r.status_code == 200 and r.content == b"\x89PNGanim"


def test_capa_sheet_de_ref(client, fake_root, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    (fake_root / "edit-raw" / "ref").mkdir()
    (fake_root / "edit-raw" / "ref" / "sheet.png").write_bytes(b"\x89PNGsheet")
    assert client.get("/api/capa", params={"id": "edit-raw"}).content == b"\x89PNGsheet"


def test_capa_sem_fonte_404(client, monkeypatch):
    monkeypatch.setattr(server_mod, "_run", _fake_run_falha)
    assert client.get("/api/capa", params={"id": "edit-raw"}).status_code == 404
    assert client.get("/api/capa", params={"id": "../x"}).status_code == 400


def test_folha_route(client, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "conceitos.json").write_text(json.dumps({"conceitos": [{"id": "A", "ideia": "x"}]}), encoding="utf-8")
    r = client.get("/api/folha", params={"id": "edit-fake", "tipo": "conceitos"})
    assert r.status_code == 200 and r.json()["conceitos"][0]["id"] == "A"


def test_folha_route_erros(client):
    assert client.get("/api/folha", params={"id": "edit-fake", "tipo": "nada"}).status_code == 400
    r = client.get("/api/folha", params={"id": "edit-fake", "tipo": "broll"})
    assert r.status_code == 422 and "não encontrado" in r.json()["detail"]
    assert client.get("/api/folha", params={"id": "../x", "tipo": "broll"}).status_code == 400


@pytest.mark.parametrize("nome,tipo", [("broll/cand/pexels-1.mp4", "video/mp4"),
                                       ("broll/cand/unsplash-2.jpg", "image/jpeg"),
                                       ("overlays/o01.png", "image/png")])
def test_file_midia(client, fake_root, nome, tipo):
    p = fake_root / "edit-fake" / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"0123456789")
    r = client.get("/api/file", params={"id": "edit-fake", "name": nome})
    assert r.status_code == 200 and r.headers["content-type"].startswith(tipo) and r.content == b"0123456789"


def test_file_midia_range(client, fake_root):
    p = fake_root / "edit-fake" / "broll" / "cand" / "v.mp4"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"0123456789")
    r = client.get("/api/file", params={"id": "edit-fake", "name": "broll/cand/v.mp4"}, headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.content == b"0123"


@pytest.mark.parametrize("nome", ["broll/cand/../../x.mp4", "broll/cand/a.exe", "overlays/x.png",
                                  "overlays/../broll/sheet.png", "broll/cand/sub/a.mp4"])
def test_file_midia_traversal(client, nome):
    assert client.get("/api/file", params={"id": "edit-fake", "name": nome}).status_code == 400
