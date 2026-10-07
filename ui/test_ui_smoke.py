"""Smoke da UI no chromium (Playwright). Pula se o chromium não estiver disponível."""
import json
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

import server  # noqa: E402
from test_pipeline import fake_root  # noqa: E402,F401 — fixture reexport

RECEITA = "---\netapas: transcricao=transcrição, cortes, render\n---\n# t\n"


def _porta():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture
def ui_url(fake_root):
    (fake_root / "Formatos" / "teste.md").write_text(RECEITA, encoding="utf-8")
    ui = fake_root / "edit-fake" / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    (ui / "eventos.jsonl").write_text(
        json.dumps({"ts": "2026-10-07T10:00:00+00:00", "tipo": "etapa", "etapa": "transcricao", "status": "fim"}) + "\n" +
        json.dumps({"ts": "2026-10-07T10:05:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "inicio"}) + "\n",
        encoding="utf-8")
    server.app.state.root = fake_root
    port = _porta()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture
def page(ui_url):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"chromium indisponível: {e}")
        pg = b.new_page()
        pg.route("https://fonts.googleapis.com/**", lambda r: r.abort())
        pg.route("https://fonts.gstatic.com/**", lambda r: r.abort())
        yield pg
        b.close()


def test_rota_projeto_abas(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/edicao", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.route === 'project'")
    assert page.locator("#player").is_visible()
    assert page.locator("#timeline").is_visible()
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("location.hash === '#/p/edit-fake/custos'")
    assert page.locator("#tab-custos").is_visible()
    assert not page.locator("#timeline").is_visible()
    page.click("#tabs a[data-tab=docs]")
    page.wait_for_function("location.hash === '#/p/edit-fake/docs'")
    assert page.locator("#tab-docs").is_visible()


def test_aba_lembrada_e_edicao_desabilitada(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/custos", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    page.goto(ui_url + "/#/p/edit-fake", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-fake/custos'")
    page.goto(ui_url + "/#/p/edit-raw/edicao", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-raw/board'")   # sem edl.json
    assert "off" in page.locator("#tabs a[data-tab=edicao]").get_attribute("class")


def test_hash_vazio_vai_para_biblioteca(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_function("document.body.dataset.route === 'project'")
    page.evaluate("location.hash = '#/'")
    page.wait_for_function("document.body.dataset.route === 'library'")
    assert page.locator("#library-view").is_visible()
    assert not page.locator("#project-view").is_visible()
