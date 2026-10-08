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


def test_folha_broll_candidato_ia(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _broll_fixture(proj)
    (proj / "broll" / "cand" / "b01-ia1.png").write_bytes(b"x")
    b = json.loads((proj / "broll.json").read_text(encoding="utf-8"))
    b["momentos"][0]["candidatos"].append({"fonte": "ia", "tipo": "foto", "arq": "broll/cand/b01-ia1.png",
                                           "prompt": "gavel on desk", "custo_est": 0.35})
    (proj / "broll.json").write_text(json.dumps(b), encoding="utf-8")
    _pedido_folha(proj, "broll")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-row")
    cand = page.locator(".fl-row[data-m=b01] .fl-cand[data-k='3']")
    assert "ia · foto · ~US$0,35" in cand.inner_text()
    assert cand.get_attribute("title") == "gavel on desk"
    assert page.locator(".fl-row[data-m=b01] .fl-cand[data-k='1']").get_attribute("title") is None
    cand.click()
    assert page.locator("#fl-resp").inner_text() == "ok b01:3"


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


def test_folha_clips(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "clips").mkdir()
    (proj / "clips" / "clips.json").write_text(json.dumps({"x_padrao": 636, "clipes": [
        {"id": "c01", "slug": "a", "status": "proposto", "nota": 4, "gancho": "Zero inscritos", "x": 636,
         "legenda": False, "plataformas": ["shorts"], "ranges": [{"t_in": 1, "t_out": 3}]},
        {"id": "c02", "slug": "b", "status": "proposto", "nota": 3, "gancho": "Canal deletado",
         "plataformas": ["reels"], "ranges": [{"t_in": 5, "t_out": 7}]},
        {"id": "c03", "slug": "c", "status": "proposto", "nota": 2, "gancho": "g", "ranges": [{"t_in": 8, "t_out": 9}]}]}),
        encoding="utf-8")
    _pedido_folha(proj, "clips")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-clip")
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.click(".fl-clip[data-c=c01] [data-nota='3']")
    page.eval_on_selector(".fl-clip[data-c=c02] .fl-x",
                          "el => { el.value = 700; el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.click(".fl-clip[data-c=c02] .fl-legenda")
    page.click(".fl-clip[data-c=c03] .fl-veto")
    assert page.locator("#fl-resp").inner_text() == "ok c01:nota 3 c02:x=700 c02:legenda c03:não"
    assert page.locator(".fl-clip[data-c=c02] .fl-xv").inner_text() == "700"
    tr = page.eval_on_selector(".fl-clip[data-c=c02] .fl-916 video", "v => v.style.transform")
    assert tr.startswith("translateX(-")
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok c01:nota 3 c02:x=700 c02:legenda c03:não"


def test_folha_conceitos(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    (proj / "conceitos.json").write_text(json.dumps({"conceitos": [
        {"id": "A", "ideia": "mesmo mecanismo", "custo": "US$ 0,40", "horas": 2, "animatic": "animatic-A.png"},
        {"id": "B", "ideia": "mesmo tema", "exige_ia": True},
        {"id": "C", "ideia": "o contrário"}]}), encoding="utf-8")
    _pedido_folha(proj, "conceitos")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-col")
    assert page.locator("#fl-enviar").is_disabled()
    assert "exige IA" in page.locator(".fl-col[data-cc=B]").inner_text()
    page.click(".fl-col[data-cc=B] input[name=fl-um]")
    assert page.locator("#fl-resp").inner_text() == "B"
    page.click(".fl-varios-cb")
    page.click(".fl-col[data-cc=C] .fl-mult-cb")
    page.click(".fl-col[data-cc=A] .fl-mult-cb")
    assert page.locator("#fl-resp").inner_text() == "produzir: A C"
    page.fill(".fl-ajuste", "  mais\n  curto ")                         # vira uma linha só
    assert page.locator("#fl-resp").inner_text() == "ajuste: mais curto"
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    q = _queue(proj)[0]
    assert q["reply"] == "ajuste: mais curto" and "folha" not in q          # resposta consome a folha


def test_folha_overlays(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "overlays").mkdir()
    (proj / "overlays" / "o01.png").write_bytes(b"\x89PNG")
    (proj / "overlays" / "folha.json").write_text(json.dumps({"overlays": [
        {"id": "o01", "arquivo": "anim/A.mov", "t": 4, "dur": 2, "png": "overlays/o01.png"},
        {"id": "o02", "arquivo": "anim/B.mov", "t": 30, "dur": 3, "png": None, "erro": "arquivo do overlay não encontrado"},
        {"id": "o03", "arquivo": "anim/C.mov", "t": 60, "dur": 1, "png": None}]}), encoding="utf-8")
    _pedido_folha(proj, "overlays")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-ov")
    assert "não encontrado" in page.locator(".fl-ov[data-o=o02]").inner_text()
    page.click(".fl-ov[data-o=o01] .fl-veto")
    page.fill(".fl-ov[data-o=o03] .fl-otexto", "cor âmbar")
    assert page.locator("#fl-resp").inner_text() == "ok o01:não o03: cor âmbar"
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    assert _queue(proj)[0]["reply"] == "ok o01:não o03: cor âmbar"


def _decisao_raw(proj, ts, assunto, escolha, **kw):
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "tipo": "decisao", "assunto": assunto, "escolha": escolha, **kw},
                           ensure_ascii=False) + "\n")


def test_board_decisoes_no_card(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "tirar gaguejo", etapa="cortes",
                 alternativas=["manter"], motivo="ritmo", confianca="media", custo_usd=0.4)
    _decisao_raw(proj, "2026-10-07T10:07:00+00:00", "outro", "decisão solta")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes details.dec")
    dec = page.locator("#card-cortes details.dec")
    assert "tirar gaguejo" in dec.inner_text() and "manter" in dec.inner_text()
    assert not page.locator("#card-cortes .dec-mot").is_visible()
    dec.locator("summary").click()
    assert page.locator("#card-cortes .dec-mot").is_visible()
    assert "ritmo" in page.locator("#card-cortes .dec-mot").inner_text()
    assert "decisão solta" in page.locator("#card-outros").inner_text()


def test_board_decisao_expandida_sobrevive_reload(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "c1", etapa="cortes", motivo="m")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes details.dec summary")
    page.click("#card-cortes details.dec summary")
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste", "x": 2}), encoding="utf-8")   # SSE
    page.wait_for_timeout(2000)
    assert page.locator("#card-cortes .dec-mot").is_visible()


def _linha_fixture(fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "tirar gaguejo", etapa="cortes")
    (proj / "ui" / "costs.jsonl").write_text(json.dumps(
        {"ts": "2026-10-07T10:07:00+00:00", "provedor": "elevenlabs_scribe", "usd": 0.5, "creditos": 0}) + "\n",
        encoding="utf-8")
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:08:00+00:00", "tipo": "resposta", "qid": 1, "texto": "ok"}) + "\n")
    return proj


def _scrub(page, v):
    page.eval_on_selector("#linha-scrub",
                          f"el => {{ el.value = {v}; el.dispatchEvent(new Event('input', {{bubbles: true}})); }}")


def test_linha_replay(page, ui_url, fake_root):
    _linha_fixture(fake_root)     # eventos: transcricao fim 10:00, cortes inicio 10:05, decisão 10:06, custo 10:07, resposta 10:08
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    assert page.locator(".linha-item").count() == 5
    _scrub(page, 0)
    assert "st-pendente" in page.locator("#linha-mini .step").nth(1).get_attribute("class")
    assert page.locator("#linha-custo").inner_text() == "acumulado US$ 0.00"
    _scrub(page, 4)
    assert "st-andamento" in page.locator("#linha-mini .step").nth(1).get_attribute("class")
    assert page.locator("#linha-custo").inner_text() == "acumulado US$ 0.50"
    assert "cur" in page.locator(".linha-item[data-k='4']").get_attribute("class")
    page.click(".linha-item[data-k='2']")
    assert page.locator("#linha-scrub").input_value() == "2"
    _scrub(page, 0)
    page.click("#linha-play")
    page.wait_for_function("document.querySelector('#linha-scrub').value === '4'", timeout=6000)
    page.wait_for_function("document.querySelector('#linha-play').textContent === '▶'", timeout=3000)   # parou no fim


def test_linha_filtros(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    for t in ("etapa", "pergunta", "resposta", "custo"):
        page.click(f".linha-filtros [data-tipo={t}]")
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 1")
    assert "tirar gaguejo" in page.locator(".linha-item").inner_text()
    assert page.locator(".linha-filtros [data-assunto=corte]").is_visible()


def test_linha_filtro_vazio(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    for t in ("etapa", "decisao", "pergunta", "resposta", "custo"):
        page.click(f".linha-filtros [data-tipo={t}]")
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 0")
    assert page.locator("#linha-scrub").is_disabled()
    page.click("#linha-play")       # sem eventos visíveis: não quebra
    assert page.locator("#linha-play").inner_text() == "▶"


def test_linha_sem_historico(page, ui_url):
    page.goto(ui_url + "/#/p/edit-raw/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-vazio")
    assert "sem histórico" in page.locator("#tab-linha").inner_text()


def _play_e_sai(page, sair):
    _scrub(page, 0)
    page.click("#linha-play")
    sair()
    page.wait_for_timeout(1500)      # > 2 ticks: se o timer vazasse, o scrub avançaria
    page.goto(page.url.split("#")[0] + "#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    v = page.locator("#linha-scrub").input_value()
    assert page.locator("#linha-play").inner_text() == "▶"
    page.wait_for_timeout(1300)
    assert page.locator("#linha-scrub").input_value() == v and int(v) < 4


def test_linha_play_para_ao_sair(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    _play_e_sai(page, lambda: page.click("#tabs a[data-tab=board]"))
    _play_e_sai(page, lambda: page.evaluate("location.hash = '#/'"))


def test_linha_troca_de_projeto(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    page.evaluate("location.hash = '#/p/edit-raw/linha'")
    page.wait_for_selector(".linha-vazio")
    assert "sem histórico" in page.locator("#tab-linha").inner_text()
    assert page.locator(".linha-item").count() == 0


def test_linha_troca_de_projeto_com_falha(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    page.route("**/api/linha?id=edit-raw*", lambda r: r.abort())
    page.evaluate("location.hash = '#/p/edit-raw/linha'")
    page.wait_for_function("document.querySelector('#tab-linha').innerText.includes('linha indisponível')")
    assert page.locator(".linha-item").count() == 0
    page.evaluate("location.hash = '#/p/edit-fake/linha'")     # volta: não fica preso no placeholder
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 5")


def test_linha_atualiza_por_sse(page, ui_url, fake_root):
    proj = _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    assert page.locator(".linha-item").count() == 5
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:09:00+00:00", "tipo": "etapa", "etapa": "cortes", "status": "fim"}) + "\n")
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 6", timeout=6000)
    (fake_root / "Formatos" / "teste2.md").write_text(RECEITA.replace("transcrição", "TRANSCR"), encoding="utf-8")
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste2"}), encoding="utf-8")   # mesmo nº de eventos
    page.wait_for_function("document.querySelector('#linha-mini').innerText.includes('TRANSCR')", timeout=6000)


def test_pagina_decisoes_claude_online(page, ui_url, fake_root):
    (fake_root / "edit-fake" / "ui" / "heartbeat").touch()
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelector('#claude-status').textContent === 'Claude escutando'")


def test_pagina_decisoes(page, ui_url, fake_root):
    fake, raw = fake_root / "edit-fake", fake_root / "edit-raw"
    _decisao_raw(fake, "2026-10-07T10:01:00+00:00", "trilha", "Phoenix2026", motivo="calma", confianca="alta")
    _decisao_raw(fake, "2026-10-07T10:02:00+00:00", "corte", "tirar gaguejo")
    _decisao_raw(raw, "2026-10-07T10:03:00+00:00", "trilha", "Phoenix2026")
    _decisao_raw(raw, "2026-10-07T10:04:00+00:00", "trilha", "Incredulity", custo_usd=0.1)
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.click("#btn-decisoes")
    page.wait_for_function("document.body.dataset.route === 'decisoes'")
    page.wait_for_selector(".dec-tab tbody tr")
    assert page.locator(".dec-tab tbody tr").count() == 4
    assert not page.locator("#library-view").is_visible()
    page.click("#dec-chips [data-assunto=trilha]")
    page.wait_for_function("document.querySelectorAll('.dec-tab tbody tr').length === 3")
    assert "Phoenix2026 ×2" in page.locator("#dec-freq").inner_text()
    page.fill("#dec-busca", "incred")
    page.wait_for_function("document.querySelectorAll('.dec-tab tbody tr').length === 1")
    page.click(".dec-tab tbody tr a")
    page.wait_for_function("location.hash === '#/p/edit-raw/linha'")
    page.wait_for_function("document.body.dataset.route === 'project'")


def test_pagina_decisoes_vazia(page, ui_url):
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_selector(".dec-vazio")
    assert "nenhuma decisão registrada" in page.locator("#decisoes-view").inner_text()
    page.click("#decisoes-voltar")
    page.wait_for_function("document.body.dataset.route === 'library'")


def test_pagina_decisoes_fila_viva(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": 1, "type": "instrucao", "text": "pergunta do projeto", "status": "waiting_reply", "resultado": "?"}]),
        encoding="utf-8")
    rt = fake_root / ".ui-runtime"
    rt.mkdir(exist_ok=True)
    (rt / "queue.json").write_text(json.dumps([
        {"id": 2, "type": "novo-projeto", "text": "projeto global", "status": "pending"}]), encoding="utf-8")
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_selector(".queue-reply-input")
    fila = page.locator("#queue-panel").inner_text()
    assert "[edit-fake] pergunta do projeto" in fila and "[novo] projeto global" in fila
    page.fill(".queue-reply-input", "sim")
    page.click(".queue-reply-send")
    page.wait_for_function("!document.querySelector('.queue-reply-input')")
    assert _queue(proj)[0]["reply"] == "sim"


def test_pagina_decisoes_busca_sem_resultado(page, ui_url, fake_root):
    _decisao_raw(fake_root / "edit-fake", "2026-10-07T10:01:00+00:00", "trilha", "Phoenix2026")
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_selector(".dec-tab tbody tr")
    page.fill("#dec-busca", "zzz")
    page.wait_for_selector(".dec-vazio")
    assert "nada encontrado" in page.locator("#decisoes-view").inner_text()


def test_pagina_decisoes_descarta_resposta_atrasada(page, ui_url, fake_root):
    fake = fake_root / "edit-fake"
    _decisao_raw(fake, "2026-10-07T10:01:00+00:00", "trilha", "Phoenix2026")
    _decisao_raw(fake, "2026-10-07T10:02:00+00:00", "corte", "tirar gaguejo")
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_selector(".dec-tab tbody tr")

    def lenta(r):
        if "assunto=trilha" in r.request.url:
            page.wait_for_timeout(1500)
        r.continue_()
    page.route("**/api/decisoes?assunto=*", lenta)
    page.click("#dec-chips [data-assunto=trilha]")
    page.click("#dec-chips [data-assunto=corte]")
    page.wait_for_timeout(2500)
    assert page.locator(".dec-tab tbody tr").count() == 1
    assert "tirar gaguejo" in page.locator(".dec-tab").inner_text()


def test_folha_traducao(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    d = proj / "dub" / "es"
    d.mkdir(parents=True)
    (d / "dublagem.json").write_text(json.dumps({"lang": "es", "frases": [
        {"id": "f001", "t_in": 0.0, "t_out": 2.0, "orig": "oi gente", "trad": "hola gente"},
        {"id": "f002", "t_in": 2.5, "t_out": 3.0, "orig": "tudo bem", "trad": "todo bien"}]}), encoding="utf-8")
    (d / "textos.json").write_text(json.dumps({"textos": {
        "Fecha o caderno": {"id": "t01", "trad": "Cierra el cuaderno", "arquivos": ["anim.html"]}}}), encoding="utf-8")
    (proj / "ui" / "queue.json").write_text(json.dumps([
        {"id": 9, "status": "waiting_reply", "type": "instrucao", "text": "x", "resultado": "revise a tradução",
         "folha": "traducao", "lang": "es"}]), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/aprovacao", wait_until="domcontentloaded")
    page.wait_for_selector(".fl-tr")
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.fill(".fl-tr[data-i=f001] .fl-tr-trad", " hola   gente ")          # só espaço: não é edição
    assert page.locator("#fl-resp").inner_text() == "ok"
    page.fill(".fl-tr[data-i=f002] .fl-tr-trad", "todo   muy bien")
    page.fill(".fl-tr[data-i=t01] .fl-tr-trad", "Cierra tu cuaderno")
    assert page.locator("#fl-resp").inner_text() == "ok\nf002: todo muy bien\nt01: Cierra tu cuaderno"
    page.fill(".fl-tr[data-i=f001] .fl-tr-trad", "hola a todos los que están viendo este video ahora mismo")
    assert "estoura" in page.locator(".fl-tr[data-i=f001] .fl-tr-tempo").get_attribute("class")
    page.fill(".fl-tr[data-i=t01] .fl-tr-trad", "")                         # esvaziado = `t01: `
    page.click("#fl-enviar")
    page.wait_for_function("document.body.dataset.tab === 'board'")
    q = json.loads((proj / "ui" / "queue.json").read_text(encoding="utf-8"))
    assert q[0]["reply"].startswith("ok\nf001: hola a todos") and q[0]["status"] == "pending"
    assert q[0]["reply"].endswith("\nf002: todo muy bien\nt01: ")


def test_board_info_dub(page, ui_url, fake_root):
    (fake_root / "Formatos" / "teste.md").write_text(
        "---\netapas: transcricao, cortes, dublagem\n---\n", encoding="utf-8")
    (fake_root / "edit-fake" / "ui" / "state.json").write_text(json.dumps(
        {"formato": "teste", "dub": {"idiomas": {"es": {"etapa": "pronto"}, "en": {"etapa": "tts"}}}}), encoding="utf-8")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-dublagem")
    assert "dub: en tts · es pronto" in page.locator("#card-dublagem").inner_text()
