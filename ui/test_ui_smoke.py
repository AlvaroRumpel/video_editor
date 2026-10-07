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


def test_stepper_e_board(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#stepper .step")
    steps = page.locator("#stepper .step")
    assert steps.count() == 3
    assert "st-fim" in steps.nth(0).get_attribute("class")
    assert "st-andamento" in steps.nth(1).get_attribute("class")
    assert page.locator("#card-cortes").is_visible()
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    steps.nth(2).click()
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert page.locator("#card-render").is_visible()


def test_board_espera_mostra_pedido(page, ui_url, fake_root):
    ui = fake_root / "edit-fake" / "ui"
    with (ui / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    (ui / "queue.json").write_text(json.dumps([
        {"id": 7, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "aprova os cortes?"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-pergunta")
    assert "aprova os cortes?" in page.locator("#card-cortes").inner_text()
    page.fill("#card-cortes .board-reply-input", "ok")
    page.click("#card-cortes .board-reply-send")
    page.wait_for_function("!document.querySelector('#card-cortes .board-reply-input')")
    q = json.loads((ui / "queue.json").read_text(encoding="utf-8"))
    assert q[0]["reply"] == "ok" and q[0]["status"] == "pending"


def test_board_reply_sobrevive_reload(page, ui_url, fake_root):
    ui = fake_root / "edit-fake" / "ui"
    with (ui / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    (ui / "queue.json").write_text(json.dumps([
        {"id": 7, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "?"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-reply-input")
    page.fill("#card-cortes .board-reply-input", "digitando")
    (ui / "state.json").write_text(json.dumps({"formato": "teste", "x": 1}), encoding="utf-8")   # dispara SSE
    page.wait_for_timeout(2500)
    assert page.locator("#card-cortes .board-reply-input").input_value() == "digitando"


def test_board_info_no_card_da_etapa(page, ui_url, fake_root):
    (fake_root / "Formatos" / "teste.md").write_text(
        "---\netapas: transcricao, audio, cortes\n---\n", encoding="utf-8")
    (fake_root / "edit-fake" / "ui" / "state.json").write_text(json.dumps(
        {"formato": "teste", "audio": {"denoise": "forte"}, "clips": {"aprovados": [1, 2]}}), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-audio")
    assert "denoise forte" in page.locator("#card-audio").inner_text()
    assert "2 aprovados" in page.locator("#card-outros").inner_text()   # sem etapa candidatos


def test_board_rascunho_sobrevive_troca_de_aba(page, ui_url, fake_root):
    ui = fake_root / "edit-fake" / "ui"
    with (ui / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    (ui / "queue.json").write_text(json.dumps([
        {"id": 7, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "?"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-reply-input")
    page.fill("#card-cortes .board-reply-input", "linha1")
    page.press("#card-cortes .board-reply-input", "Control+Enter")
    page.type("#card-cortes .board-reply-input", "linha2")
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    (ui / "state.json").write_text(json.dumps({"formato": "teste", "x": 2}), encoding="utf-8")   # SSE fora do board
    page.wait_for_timeout(1500)
    page.click("#tabs a[data-tab=board]")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert page.locator("#card-cortes .board-reply-input").input_value() == "linha1\nlinha2"


def test_board_falha_sem_duracao_crescente(page, ui_url, fake_root):
    with (fake_root / "edit-fake" / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "falha"}) + "\n")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes.st-falha")
    tempo = page.locator("#card-cortes .bc-head .mono.dim").inner_text()
    assert tempo and "·" not in tempo   # só a hora de início


def _pedido_folha(proj, folha, qid=9, resultado="aprova?"):
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": qid, "status": "waiting_reply", "type": "instrucao", "text": "x",
         "resultado": resultado, "folha": folha}]), encoding="utf-8")


def _broll_fixture(proj):
    cand = proj / "broll" / "cand"
    cand.mkdir(parents=True)
    for n in ("a.mp4", "b.mp4", "c.jpg"):
        (cand / n).write_bytes(b"x")
    (proj / "broll.json").write_text(json.dumps({"momentos": [
        {"id": "b01", "t_in": 42, "t_out": 45, "termo": "gavel", "modo": "cut-in", "status": "proposto",
         "candidatos": [{"fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4", "dur": 6},
                        {"fonte": "pixabay", "tipo": "video", "arq": "broll/cand/b.mp4", "dur": 8}]},
        {"id": "b02", "t_in": 75, "t_out": 78, "termo": "court", "modo": "janela", "status": "proposto",
         "candidatos": [{"fonte": "pexels", "tipo": "foto", "arq": "broll/cand/c.jpg"}]}]}), encoding="utf-8")


def _queue(proj):
    return json.loads((proj / "ui" / "queue.json").read_text(encoding="utf-8"))


def test_folha_broll(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    assert page.locator("#tabs a[data-tab=aprovacao]").is_visible()
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.click(".fl-row[data-m=b01] .fl-cand[data-k='2']")
    page.click(".fl-row[data-m=b02] .fl-veto")
    assert page.locator("#fl-resp").inner_text() == "ok b01:2 b02:não"
    page.fill("#fl-coment", "valeu")
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    q = _queue(proj)
    assert q[0]["reply"] == "ok b01:2 b02:não\nvaleu" and q[0]["status"] == "pending"
    assert not page.locator("#tabs a[data-tab=aprovacao]").is_visible()


def test_folha_ausente_esconde_aba(page, ui_url):
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_function("location.hash === '#/p/edit-fake/board'")
    assert not page.locator("#tabs a[data-tab=aprovacao]").is_visible()


def test_folha_link_no_board(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:06:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "espera"}) + "\n")
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes .board-folha")
    assert page.locator("#card-cortes .board-reply-input").count() == 0
    page.click("#card-cortes .board-folha")
    page.wait_for_function("document.body.dataset.tab === 'aprovacao'")
    page.wait_for_selector(".fl-row")


def test_folha_indisponivel(page, ui_url, fake_root):
    _pedido_folha(fake_root / "edit-fake", "clips")        # sem clips/clips.json
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-erro")
    txt = page.locator(".fl-erro").inner_text()
    assert "folha indisponível" in txt and "não encontrado" in txt
    assert "aprova?" in page.locator("#tab-aprovacao").inner_text()


def test_folha_selecao_sobrevive_troca_de_aba(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    page.click(".fl-row[data-m=b01] .fl-cand[data-k='2']")
    page.fill("#fl-coment", "rascunho")
    page.click("#tabs a[data-tab=custos]")
    page.wait_for_function("document.body.dataset.tab === 'custos'")
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste", "x": 1}), encoding="utf-8")   # SSE
    page.wait_for_timeout(1500)
    page.click("#tabs a[data-tab=aprovacao]")
    page.wait_for_function("document.body.dataset.tab === 'aprovacao'")
    assert page.locator("#fl-resp").inner_text() == "ok b01:2"
    assert page.locator("#fl-coment").input_value() == "rascunho"


def test_folha_some_quando_respondida_pela_fila(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    page.fill(".queue-reply-input", "ok")
    page.click(".queue-reply-send")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok"


def test_folha_mesmo_pedido_reaberto_redesenha(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    page.click(".fl-row[data-m=b02] .fl-veto")
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    b = json.loads((proj / "broll.json").read_text(encoding="utf-8"))
    b["momentos"] = b["momentos"][:1]                      # Claude refaz o artefato e pergunta de novo
    (proj / "broll.json").write_text(json.dumps(b), encoding="utf-8")
    _pedido_folha(proj, "broll", resultado="e agora?")
    page.wait_for_selector("#tabs a[data-tab=aprovacao]:not([hidden])")
    page.click("#tabs a[data-tab=aprovacao]")
    page.wait_for_function("document.querySelectorAll('.fl-row').length === 1")
    assert page.locator("#fl-resp").inner_text() == "ok"
    assert "e agora?" in page.locator(".fl-perg").inner_text()
