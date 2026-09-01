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


def test_formats_and_brutos(client):
    fm = client.get("/api/formats").json()
    assert fm[0]["name"] == "padrao-youtube"
    assert client.get("/api/brutos").json() == []
