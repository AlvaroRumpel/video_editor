import pytest
from fastapi.testclient import TestClient

import server
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
