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


def test_biblioteca_card_abre_projeto(page, ui_url):
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card")
    assert page.locator(".lib-card").count() == 2
    card = page.locator(".lib-card", has_text="edit-fake")
    assert card.locator(".lib-dots i").count() == 3
    assert "cortes" in card.locator(".lib-atual").inner_text()
    card.click()
    page.wait_for_function("location.hash.startsWith('#/p/edit-fake/')")
    page.wait_for_function("document.body.dataset.route === 'project'")
    page.click("#btn-back")
    page.wait_for_function("document.body.dataset.route === 'library'")


def test_biblioteca_filtros(page, ui_url):
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card")
    page.fill("#lib-busca", "raw")
    page.wait_for_function("document.querySelectorAll('.lib-card').length === 1")
    page.fill("#lib-busca", "")
    page.click(".lib-chip[data-formato=teste]")
    page.wait_for_function("document.querySelectorAll('.lib-card').length === 1")
    assert "edit-fake" in page.locator(".lib-card").inner_text()


def test_biblioteca_projeto_aninhado(page, ui_url, fake_root):
    aninhado = fake_root / "edit" / "shorts" / "marca" / "proj-x" / "ui"
    aninhado.mkdir(parents=True)
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".lib-card >> text=marca/proj-x")
    page.click(".lib-card >> text=marca/proj-x")
    page.wait_for_function("document.body.dataset.route === 'project'")
    assert "edit%2Fshorts%2Fmarca%2Fproj-x" in page.evaluate("location.hash")
    page.wait_for_function("document.getElementById('proj-name').textContent === 'marca/proj-x'")


def test_biblioteca_poll_preserva_rascunho_de_resposta(page, ui_url, fake_root):
    (fake_root / "edit-fake" / "ui" / "queue.json").write_text(json.dumps([
        {"id": 1, "type": "instrucao", "text": "x", "status": "waiting_reply", "resultado": "pergunta?"}]),
        encoding="utf-8")
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.wait_for_selector(".queue-reply-input")
    page.fill(".queue-reply-input", "rascunho")
    page.evaluate("loadLibrary()")   # o mesmo que o poll de 5s faz
    page.wait_for_timeout(500)
    assert page.input_value(".queue-reply-input") == "rascunho"
    assert page.evaluate("document.activeElement.classList.contains('queue-reply-input')")
