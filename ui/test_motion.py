import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import motion


def test_kit_tem_vendor_fontes_e_icone():
    k = motion.MOTION / "kit"
    for f in ("vendor/gsap.min.js", "fonts/Fraunces.ttf", "fonts/Fraunces-Italic.ttf", "fonts/Inter.ttf",
              "fonts/Archivo.ttf", "fonts/IBMPlexMono-Medium.ttf", "fonts/IBMPlexMono-SemiBold.ttf"):
        assert (k / f).stat().st_size > 10_000, f
    assert (motion.MOTION / "temas" / "campeio" / "icone.png").stat().st_size > 1_000
    pkg = json.loads((motion.MOTION / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"] == {"gsap": "3.14.2", "hyperframes": "0.8.141"}

def _cenas(**extra):
    d = {"marca": "anotus", "aspecto": "9:16", "cenas": [
        {"id": "c01", "tipo": "frase", "linhas": [
            {"t": "Pare de", "estilo": "punch"},
            {"t": "decorar.", "estilo": "display", "anim": "letras", "destaque": ["marca-texto", "risco"]}]},
        {"id": "c02", "tipo": "endcard"}]}
    d.update(extra)
    return d

def test_temas_carregam_e_diferem():
    a, c = motion.carregar_tema("anotus"), motion.carregar_tema("campeio")
    assert a["cores"]["acento"] != c["cores"]["acento"]

def test_tema_inexistente_e_marca_invalida():
    with pytest.raises(ValueError, match="tema não existe"):
        motion.carregar_tema("nada")
    with pytest.raises(ValueError, match="marca inválida"):
        motion.carregar_tema("../x")

def test_tema_sem_chave(tmp_path):
    (tmp_path / "temas").mkdir()
    t = json.loads((motion.MOTION / "temas" / "anotus.json").read_text(encoding="utf-8"))
    del t["cores"]["acento"]
    (tmp_path / "temas" / "x.json").write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(ValueError, match="falta cores.acento"):
        motion.carregar_tema("x", tmp_path)

def test_validar_ok(tmp_path):
    assert motion.validar(_cenas(), tmp_path) == []

@pytest.mark.parametrize("mut, cid, trecho", [
    (lambda d: d["cenas"][0].update(tipo="xpto"), "c01", "tipo desconhecido"),
    (lambda d: d["cenas"][1].update(id="c01"), "c01", "id duplicado"),
    (lambda d: d["cenas"][0].update(id="cena1"), "#0", "id inválido"),
    (lambda d: d["cenas"][0]["linhas"][1].update(destaque=["neon"]), "c01", "destaque inválido"),
    (lambda d: d["cenas"][0]["linhas"][0].update(estilo="serif"), "c01", "estilo inválido"),
    (lambda d: d["cenas"][0]["linhas"][0].update(t=" "), "c01", "falta t"),
    (lambda d: d["cenas"].append({"id": "c03", "tipo": "custom", "html": "x.html"}), "c03", "html não encontrado"),
    (lambda d: d["cenas"].append({"id": "c03", "tipo": "custom", "html": "x.html"}), "c03", "custom precisa de dur"),
    (lambda d: d["cenas"][1].update(saida={"transicao": "fade", "dur": 0.3}), "c02", "última cena"),
    (lambda d: d["cenas"][0].update(saida={"transicao": "zoom", "dur": 0.3}), "c01", "saida precisa"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "tela", "arquivo": "../fora.png"}), "c09", "arquivo não encontrado"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "lista", "itens": ["a"] * 7}), "c09", "no máximo 6"),
    (lambda d: d["cenas"].insert(1, {"id": "c09", "tipo": "numero", "valor": "mil"}), "c09", "valor precisa"),
    (lambda d: d.update(aspecto="4:3"), "raiz", "aspecto"),
])
def test_validar_erros(tmp_path, mut, cid, trecho):
    d = _cenas()
    mut(d)
    erros = motion.validar(d, tmp_path)
    assert any(e["id"] == cid and trecho in e["motivo"] for e in erros), erros

def test_validar_tela_fora_do_projeto(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (tmp_path / "fora.png").write_bytes(b"x")
    d = _cenas()
    d["cenas"].insert(1, {"id": "c09", "tipo": "tela", "arquivo": "../fora.png"})
    assert any(e["id"] == "c09" for e in motion.validar(d, proj))

def test_resolver_defaults_e_temas(tmp_path):
    d = _cenas()
    a = motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)
    c = motion.resolver(d, motion.carregar_tema("campeio"), tmp_path)
    l0 = a["cenas"][0]["linhas"][0]
    assert (l0["anim"], l0["cor"], l0["destaque"], l0["em"]) == ("palavras", "tinta", [], None)
    assert a["cenas"][0]["saida"] == {"transicao": "fade", "dur": 0.3}
    assert a["cenas"][1]["saida"] is None and a["cenas"][1]["fixos"] is False
    assert a["cenas"][1]["fundo"] == "marca" and a["cenas"][1]["cor"] == "sobre"
    assert a["cenas"][1]["cta"] != c["cenas"][1]["cta"]
    assert d["cenas"][0]["linhas"][0] == {"t": "Pare de", "estilo": "punch"}  # não muta a entrada

def test_resolver_saida_alinhada_a_quadro(tmp_path):
    d = _cenas()
    d["cenas"][0]["saida"] = {"transicao": "iris", "dur": 0.47}
    r = motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)
    assert r["cenas"][0]["saida"]["dur"] == round(14 / 30, 6)

def test_resolver_numero_mono_por_tema(tmp_path):
    d = {"marca": "x", "cenas": [{"id": "c01", "tipo": "numero", "valor": 1250}]}
    assert motion.resolver(d, motion.carregar_tema("anotus"), tmp_path)["cenas"][0]["estilo"] == "display"
    assert motion.resolver(d, motion.carregar_tema("campeio"), tmp_path)["cenas"][0]["estilo"] == "mono"

def test_css_vars_e_tema_js():
    css = motion._css_vars(motion.carregar_tema("campeio"))
    assert "--k-fundo-marca:linear-gradient" in css and '--k-mono-familia:"K Plex Mono"' in css
    assert "--k-display-tamanho:160px" in css
    assert "--k-display-tamanho:210px" in motion._css_vars(motion.carregar_tema("anotus"))
    tj = motion._tema_js(motion.carregar_tema("campeio"))
    assert tj["assinatura"] == {"tipo": "icone", "src": "kit/tema/icone.png"} and tj["barra"] is True


pw = pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="sem playwright")


def _proj(tmp_path, dados, nome="proj"):
    p = tmp_path / nome
    p.mkdir(exist_ok=True)
    (p / "cenas.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return p


@pw
def test_montar_gera_composicao_tempos_e_cues(tmp_path):
    p = _proj(tmp_path, _cenas())
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    html = (p / "motion" / "index.html").read_text(encoding="utf-8")
    assert html.count('class="clip cena"') == 2 and "cdn." not in html
    c1, c2 = r["cenas"]
    assert c1["ini"] == 0 and abs(c2["ini"] - (c1["dur"] - 0.3)) < 1e-3   # sobreposição do fade
    assert abs(r["duracao"] - (c2["ini"] + c2["dur"])) < 0.04
    assert f'data-duration="{r["duracao"]:.3f}"' in html
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"rise", "whoosh-reveal", "sting-endcard", "pop-dourado", "click-pill"} <= sons
    assert (p / "motion" / ".motion").is_file() and (p / "motion" / "kit" / "vendor" / "gsap.min.js").is_file()


@pw
def test_montar_campeio_mesmo_json(tmp_path):
    d = _cenas(marca="campeio")
    r = motion.montar(_proj(tmp_path, d))
    assert r["ok"], r["erros"]


@pw
def test_montar_dur_abaixo_do_minimo(tmp_path):
    d = _cenas()
    d["cenas"][0]["dur"] = 0.5
    r = motion.montar(_proj(tmp_path, d))
    assert not r["ok"] and any(e["id"] == "c01" and "abaixo do mínimo" in e["motivo"] for e in r["erros"])


@pw
def test_montar_linha_longa_estoura(tmp_path):
    d = _cenas()
    d["cenas"][0]["linhas"][1]["t"] = "inconstitucionalissimamente"
    r = motion.montar(_proj(tmp_path, d))
    assert not r["ok"]
    assert any(e["id"] == "c01" and ("estoura" in e["motivo"] or "safe area" in e["motivo"]) for e in r["erros"])


@pw
def test_montar_fonte_fallback(tmp_path):
    md = tmp_path / "m"
    shutil.copytree(motion.MOTION / "kit", md / "kit")
    (md / "temas").mkdir()
    t = json.loads((motion.MOTION / "temas" / "anotus.json").read_text(encoding="utf-8"))
    t["fontes"]["display"]["familia"] = "K Inexistente"
    (md / "temas" / "anotus.json").write_text(json.dumps(t), encoding="utf-8")
    r = motion.montar(_proj(tmp_path, _cenas()), motion_dir=md)
    assert any("fonte em fallback (K Inexistente)" in e["motivo"] for e in r["erros"]), r


def test_montar_nao_apaga_pasta_alheia(tmp_path):
    p = _proj(tmp_path, _cenas())
    (p / "motion").mkdir()
    (p / "motion" / "meu.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não foi criado"):
        motion.montar(p)
    assert (p / "motion" / "meu.txt").exists()


def test_montar_erro_de_schema_nao_gera_nada(tmp_path):
    d = _cenas()
    d["cenas"][0]["tipo"] = "xpto"
    p = _proj(tmp_path, d)
    r = motion.montar(p)
    assert not r["ok"] and r["erros"][0]["id"] == "c01" and not (p / "motion").exists()


def test_montar_lang_invalido(tmp_path):
    with pytest.raises(ValueError, match="lang inválido"):
        motion.montar(_proj(tmp_path, _cenas()), "../x")


@pw
def test_montar_lang_usa_pastas_proprias(tmp_path):
    p = _proj(tmp_path, _cenas())
    d = _cenas()
    d["cenas"][0]["linhas"][0]["t"] = "Stop"
    d["cenas"][1].update(cta="Try it", tagline="Study smarter", url="anotus.app/en")
    (p / "cenas.en.json").write_text(json.dumps(d), encoding="utf-8")
    assert motion.montar(p)["ok"] and motion.montar(p, "en")["ok"]
    assert (p / "motion.en" / "index.html").exists() and (p / "cues.en.json").exists() and (p / "cues.json").exists()
    assert '"Stop"' in (p / "motion.en" / "index.html").read_text(encoding="utf-8")


CUSTOM = """<div class="k-linha k-display k-cor-tinta" data-k-texto><span class="k-txt" id="{id}-t">custom</span></div>
<script>
KIT.custom((c) => {{
  const alvo = c.layer.querySelector("#{id}-t");
  c.el.appendChild(alvo.parentElement);
  return c.C.mascara(c.tl, alvo, c.t0);
}});
</script>
"""


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _midia(p: Path):
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(p / "tela.png"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-pix_fmt", "yuv420p", str(p / "clip.mp4"))


def _todos(marca):
    return {"marca": marca, "cenas": [
        {"id": "c01", "tipo": "numero", "valor": 1250, "legenda": "usuários", "saida": {"transicao": "wipe", "dur": 0.4}},
        {"id": "c02", "tipo": "lista", "titulo": "Três passos", "itens": ["Grifar", "Revisar", "Lembrar"],
         "saida": {"transicao": "iris", "dur": 0.47}},
        {"id": "c03", "tipo": "tela", "arquivo": "tela.png", "label": "Busca"},
        {"id": "c04", "tipo": "tela", "arquivo": "clip.mp4", "moldura": "browser"},
        {"id": "c05", "tipo": "lista", "itens": ["um", "dois"], "marcador": "assinatura"},
        {"id": "c06", "tipo": "custom", "html": "c06.html", "dur": 2.5},
        {"id": "c07", "tipo": "endcard"}]}


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
@pytest.mark.parametrize("marca", ["anotus", "campeio", "dark-historia"])
def test_todos_os_tipos_montam(tmp_path, marca):
    p = _proj(tmp_path, _todos(marca))
    _midia(p)
    (p / "c06.html").write_text(CUSTOM.format(id="c06"), encoding="utf-8")
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    assert abs(r["cenas"][3]["dur"] - 3.0) < 0.04          # tela com vídeo: dur = duração do arquivo
    assert abs(r["cenas"][2]["dur"] - 3.0) < 0.04          # tela com imagem: 3 s
    html = (p / "motion" / "index.html").read_text(encoding="utf-8")
    assert '<video class="k-midia clip" src="midia/c04.mp4"' in html and (p / "motion" / "midia" / "c03.png").is_file()
    sons = {c["som"] for c in json.loads((p / "cues.json").read_text(encoding="utf-8"))}
    assert {"tick", "click-pill", "rise", "sting-endcard"} <= sons


@pw
def test_custom_sem_registro_vira_erro(tmp_path):
    d = _cenas()
    d["cenas"].insert(1, {"id": "c05", "tipo": "custom", "html": "c05.html", "dur": 2})
    p = _proj(tmp_path, d)
    (p / "c05.html").write_text("<div>nada</div>", encoding="utf-8")
    r = motion.montar(p)
    assert any(e["id"] == "c05" and "KIT.custom" in e["motivo"] for e in r["erros"])


@pw
def test_custom_erro_cai_na_cena_certa(tmp_path):
    # 1ª custom não registra nada, 2ª registra: o erro vai só para a 1ª (mapa por id, não por ordem)
    d = _cenas()
    d["cenas"].insert(1, {"id": "c05", "tipo": "custom", "html": "c05.html", "dur": 2})
    d["cenas"].insert(2, {"id": "c06", "tipo": "custom", "html": "c06.html", "dur": 3})
    p = _proj(tmp_path, d)
    (p / "c05.html").write_text("<div>nada</div>", encoding="utf-8")
    (p / "c06.html").write_text(CUSTOM.format(id="c06"), encoding="utf-8")
    r = motion.montar(p)
    assert [e["id"] for e in r["erros"] if "KIT.custom" in e["motivo"]] == ["c05"]
    assert not any(e["id"] == "c06" for e in r["erros"]), r["erros"]


@pw
def test_custom_registrado_duas_vezes_vira_erro(tmp_path):
    d = _cenas()
    d["cenas"].insert(1, {"id": "c05", "tipo": "custom", "html": "c05.html", "dur": 2})
    p = _proj(tmp_path, d)
    html = CUSTOM.format(id="c05")
    (p / "c05.html").write_text(html + html.split("</div>", 1)[1], encoding="utf-8")
    r = motion.montar(p)
    assert any(e["id"] == "c05" and "2x" in e["motivo"] for e in r["erros"])


def _abrir(index, fn, w=1080, h=1920):
    """Abre o index.html com os args padrão do Chromium e roda fn(pagina)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        try:
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.set_default_timeout(15000)
            pg.goto(index.resolve().as_uri())
            pg.wait_for_function("window.__kit !== undefined", timeout=20000)
            return fn(pg)
        finally:
            b.close()


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_brilho_so_aparece_durante_a_iris(tmp_path):
    p = _proj(tmp_path, _todos("campeio"))
    _midia(p)
    (p / "c06.html").write_text(CUSTOM.format(id="c06"), encoding="utf-8")
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    ini = r["cenas"][2]["ini"]    # c03 entra por íris (saída da c02, 0,47 s)

    def vis(pg, t):
        pg.evaluate("t => __kit.ir(t)", t)
        return pg.evaluate("getComputedStyle(document.getElementById('k-brilho')).visibility")
    v = _abrir(p / "motion" / "index.html", lambda pg: [vis(pg, 1.0), vis(pg, ini + 0.2), vis(pg, ini + 1.0)])
    assert v == ["hidden", "visible", "hidden"]


@pw
def test_painters_rodam_com_suppress_events(tmp_path):
    d = {"marca": "anotus", "cenas": [{"id": "c01", "tipo": "numero", "valor": 1250}]}
    p = _proj(tmp_path, d)
    r = motion.montar(p)
    assert r["ok"], r["erros"]

    def texto(pg, t):
        pg.evaluate("t => { __timelines.main.totalTime(t, true); }", t)
        return pg.evaluate("document.querySelector('#c01 .k-numero').textContent")
    a, b, fim = _abrir(p / "motion" / "index.html", lambda pg: [texto(pg, 0.2), texto(pg, 0.4), texto(pg, 1.5)])
    assert a != b and fim == "1.250"


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_kenburns_fica_dentro_da_moldura(tmp_path):
    d = {"marca": "anotus", "cenas": [{"id": "c01", "tipo": "tela", "arquivo": "tela.png"}]}
    p = _proj(tmp_path, d)
    _midia(p)
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    c = r["cenas"][0]

    def medir(pg):
        pg.evaluate("t => __kit.ir(t)", c["ini"] + c["dur"] - 0.05)
        return pg.evaluate("""(() => {
          const cx = document.querySelector('#c01 .k-midia-caixa'), r = cx.getBoundingClientRect();
          return {ov: getComputedStyle(cx).overflow, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom,
                  img: cx.querySelector('img') !== null};
        })()""")
    m = _abrir(p / "motion" / "index.html", medir)
    assert m["ov"] == "hidden" and m["img"]
    assert m["x0"] >= 92 and m["y0"] >= 170 and m["x1"] <= 988 and m["y1"] <= 1750


ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _montado(tmp_path, dur=2.0, suf=""):
    p = tmp_path / "proj"
    (p / f"motion{suf}").mkdir(parents=True, exist_ok=True)
    (p / "ui").mkdir(exist_ok=True)
    (p / "ui" / "state.json").write_text(json.dumps({"aprovacoes": {"x": 1}}), encoding="utf-8")
    (p / f"motion{suf}" / "index.html").write_text("<html></html>", encoding="utf-8")
    (p / f"motion{suf}" / "tempos.json").write_text(json.dumps(
        {"duracao": dur, "cenas": [{"id": "c01", "ini": 0, "dur": dur / 2, "min": 1, "saida": 0.3},
                                   {"id": "c02", "ini": dur / 2 - 0.3, "dur": dur / 2 + 0.3, "min": 1, "saida": 0}]}),
        encoding="utf-8")
    return p


def _fake_hf(dur, pix="yuv420p", rng="tv", rc=0, cmds=None, tam="1080x1920"):
    def run(cmd, cwd, env, linha):
        if cmds is not None:
            cmds.append((cmd, env))
        if rc:
            return rc, ["boom: chrome caiu"]
        for i in (10, 50, 100):
            linha(f"\x1b[32mRendering\x1b[0m {i}%")
        _ff("-f", "lavfi", "-i", f"color=c=gray:s={tam}:r=30:d={dur}", "-pix_fmt", pix,
            "-color_range", rng, str(cmd[cmd.index("-o") + 1]))
        return 0, ["ok"]
    return run


@pytest.fixture
def sem_hf(monkeypatch):
    monkeypatch.setattr(motion, "_hf_bin", lambda md: None)
    monkeypatch.setattr(motion, "_velho", lambda idx, fontes: False)


def test_pct():
    assert motion._pct("Rendering 42%") == 42.0
    assert motion._pct("frame 15/150") == 10.0
    assert motion._pct("nada aqui") is None


def test_render_sem_node_modules(tmp_path):
    with pytest.raises(RuntimeError, match="npm ci"):
        motion.render(_montado(tmp_path), motion_dir=tmp_path / "m")


@ffmpeg
def test_render_confere_e_preserva_state(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    cmds = []
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, cmds=cmds))
    r = motion.render(p)
    assert r["ok"] and (p / "video.mp4").is_file()
    cmd, env = cmds[0]
    assert cmd[cmd.index("--fps") + 1] == "30" and cmd[cmd.index("-q") + 1] == "looks"
    assert cmd[cmd.index("--crf") + 1] == "18" and env["HYPERFRAMES_NO_TELEMETRY"] == "1"
    st = json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))
    assert st["aprovacoes"] == {"x": 1} and st["render"]["fase"] == "pronto" and st["render"]["pct"] == 100


@ffmpeg
def test_render_corrige_range_pc(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, pix="yuvj420p", rng="pc"))
    motion.render(p)
    pr = motion._probe(p / "video.mp4")
    assert pr["pix_fmt"] == "yuv420p" and pr["range"] == "tv"


@ffmpeg
def test_render_frames_errados_falha(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path, dur=3.0)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0))
    with pytest.raises(RuntimeError, match="frames"):
        motion.render(p)
    assert not (p / "video.mp4").exists()


@ffmpeg
def test_render_rascunho_e_lang(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path, suf=".en")
    cmds = []
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, cmds=cmds))
    motion.render(p, rascunho=True, lang="en")
    cmd = cmds[0][0]
    assert cmd[cmd.index("-q") + 1] == "draft" and cmd[cmd.index("render") + 1].endswith("motion.en")
    assert (p / "video_rascunho.en.mp4").is_file()


def test_render_falha_mostra_saida(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, rc=1))
    with pytest.raises(RuntimeError, match="chrome caiu"):
        motion.render(p)
    assert json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))["render"]["fase"] == "falha"


@ffmpeg
def test_folha(tmp_path):
    p = _montado(tmp_path, dur=4.0)
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=4", "-pix_fmt", "yuv420p", str(p / "video.mp4"))
    r = motion.folha(p)
    assert Path(r["png"]).is_file()
    assert [f["rotulo"] for f in r["frames"]] == ["entrada", "final", "saida", "entrada", "final"]


def test_progresso_estado_ilegivel_nao_sobrescreve(tmp_path):
    p = _montado(tmp_path)
    st = p / "ui" / "state.json"
    st.write_bytes(b'{"aprovacoes": {"x": 1}, ')
    antes = st.read_bytes()
    motion._progresso(p, "render", 10)
    assert st.read_bytes() == antes


def test_render_tmp_velho_nao_vira_video(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    (p / ".video.mp4.hf.mp4").write_bytes(b"sobra")
    monkeypatch.setattr(motion, "_executar", lambda cmd, cwd, env, linha: (0, ["ok"]))
    with pytest.raises(RuntimeError, match="falhou"):
        motion.render(p)
    assert not (p / "video.mp4").exists() and not (p / ".video.mp4.hf.mp4").exists()


def test_render_erro_ffmpeg_na_conferencia_marca_falha(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)

    def run(cmd, cwd, env, linha):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"x")
        return 0, []

    def probe(_):
        raise subprocess.CalledProcessError(1, "ffprobe")

    monkeypatch.setattr(motion, "_executar", run)
    monkeypatch.setattr(motion, "_probe", probe)
    with pytest.raises(subprocess.CalledProcessError):
        motion.render(p)
    assert json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))["render"]["fase"] == "falha"
    assert not (p / ".video.mp4.hf.mp4").exists()


def test_validar_endcard_em_lang_exige_textos(tmp_path):
    d = _cenas()
    erros = motion.validar(d, tmp_path, lang="en")
    assert any(e["id"] == "c02" and "cta, tagline e url" in e["motivo"] for e in erros), erros
    d["cenas"][1].update(cta="Try it", tagline="Study smarter", url="anotus.app/en")
    assert motion.validar(d, tmp_path, lang="en") == []
    assert motion.validar(_cenas(), tmp_path) == []          # sem lang: herda do tema


def test_resolver_numero_formato_segue_lang(tmp_path):
    d = _cenas()
    d["cenas"].insert(1, {"id": "c09", "tipo": "numero", "valor": 1250})
    t = motion.carregar_tema("anotus")
    assert motion.resolver(d, t, tmp_path, lang="en")["cenas"][1]["formato"] == "en"
    assert motion.resolver(d, t, tmp_path)["cenas"][1]["formato"] == "pt-BR"


def test_validar_rejeita_infinito_e_id_nao_ascii(tmp_path):
    d = _cenas()
    d["cenas"][0]["dur"] = float("inf")
    assert any(e["id"] == "c01" and "dur" in e["motivo"] for e in motion.validar(d, tmp_path))
    d = _cenas()
    d["cenas"][0]["id"] = "c٠١"
    assert any("id inválido" in e["motivo"] for e in motion.validar(d, tmp_path))


def test_preparar_remove_marcador_por_ultimo(tmp_path, monkeypatch):
    comp = tmp_path / "motion"
    comp.mkdir()
    (comp / ".motion").write_text("x", encoding="utf-8")
    (comp / "a").mkdir()
    (comp / "a" / "f.txt").write_text("x", encoding="utf-8")
    real, vistos = shutil.rmtree, []

    def rm(p, *a, **k):
        vistos.append((Path(p).name, (comp / ".motion").is_file()))
        raise OSError("travado")
    monkeypatch.setattr(shutil, "rmtree", rm)
    with pytest.raises(OSError):
        motion._preparar(comp, tmp_path, {"cenas": []}, motion.carregar_tema("anotus"), motion.MOTION)
    assert vistos == [("a", True)] and (comp / ".motion").is_file()   # marcador sobrevive ao travamento
    monkeypatch.setattr(shutil, "rmtree", real)


def test_render_erro_de_os_marca_falha(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)

    def run(cmd, cwd, env, linha):
        raise FileNotFoundError("npx")
    monkeypatch.setattr(motion, "_executar", run)
    with pytest.raises(OSError):
        motion.render(p)
    r = json.loads((p / "ui" / "state.json").read_text(encoding="utf-8"))["render"]
    assert r["fase"] == "falha" and r["pct"] == 0


def test_render_sem_tempos_remonta(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    (p / "motion" / "tempos.json").unlink()
    chamado = []
    monkeypatch.setattr(motion, "montar", lambda *a, **k: chamado.append(a) or {"ok": False, "erros": ["x"]})
    assert motion.render(p)["ok"] is False and chamado


@ffmpeg
def test_folha_usa_o_mais_novo_e_recusa_velho(tmp_path):
    import os
    p = _montado(tmp_path, dur=4.0)
    idx = p / "motion" / "index.html"
    os.utime(idx, (1000, 1000))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=4", "-pix_fmt", "yuv420p", str(p / "video_rascunho.mp4"))
    (p / "video.mp4").write_bytes(b"lixo")                    # video.mp4 inválido, mas o rascunho é mais novo
    os.utime(p / "video.mp4", (2000, 2000))
    os.utime(p / "video_rascunho.mp4", (3000, 3000))
    assert Path(motion.folha(p)["png"]).is_file()
    os.utime(idx, (4000, 4000))                               # montar depois dos vídeos
    with pytest.raises(ValueError, match="mais velho"):
        motion.folha(p)


def test_validar_aspecto(tmp_path):
    assert motion.validar(_cenas(aspecto="16:9"), tmp_path) == []
    erros = motion.validar(_cenas(aspecto="4:3"), tmp_path)
    assert any(e["id"] == "raiz" and "aspecto" in e["motivo"] for e in erros)


def test_tema_dark_historia_carrega():
    t = motion.carregar_tema("dark-historia")
    assert t["transicao_padrao"]["transicao"] == "fade"


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_montar_16x9_foto_tela_cheia_com_label(tmp_path):
    d = {"marca": "dark-historia", "aspecto": "16:9", "cenas": [
        {"id": "c01", "tipo": "tela", "arquivo": "foto.png", "moldura": "nenhuma", "label": "Sibéria, 1908", "dur": 4.0},
        {"id": "c02", "tipo": "frase", "fundo": "escuro", "linhas": [{"t": "Ninguém viu a explosão."}]}]}
    p = _proj(tmp_path, d)
    _ff("-f", "lavfi", "-i", "testsrc2=s=1600x1000:d=1", "-frames:v", "1", str(p / "foto.png"))
    r = motion.montar(p)
    assert r["ok"], r["erros"]
    html = (p / "motion" / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1920" data-height="1080"' in html and 'data-aspecto="16:9"' in html
    assert json.loads((p / "motion" / "tempos.json").read_text(encoding="utf-8"))["aspecto"] == "16:9"

    def medir(pg):
        pg.evaluate("t => __kit.ir(t)", 3.0)
        return pg.evaluate("""(() => { const r = document.querySelector('#c01 .k-midia-caixa').getBoundingClientRect();
          return [r.left, r.top, r.width, r.height]; })()""")
    assert _abrir(p / "motion" / "index.html", medir, 1920, 1080) == [0, 0, 1920, 1080]


def test_render_16x9_confere_dimensao(tmp_path, sem_hf, monkeypatch):
    p = _montado(tmp_path)
    t = p / "motion" / "tempos.json"
    d = json.loads(t.read_text(encoding="utf-8"))
    d["aspecto"] = "16:9"
    t.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0, tam="1920x1080"))
    assert motion.render(p)["ok"]
    monkeypatch.setattr(motion, "_executar", _fake_hf(2.0))           # retrato com tempos 16:9 = erro
    with pytest.raises(RuntimeError, match="dimensão 1080x1920"):
        motion.render(p)


@pw
def test_dur_piso_estica_ate_o_minimo(tmp_path):
    d = _cenas()
    d["cenas"][0].update(dur=0.5, dur_piso=True)
    r = motion.montar(_proj(tmp_path, d))
    assert r["ok"], r["erros"]
    assert r["cenas"][0]["dur"] > 0.5


def test_validar_dur_piso_e_ajuste(tmp_path):
    d = _cenas()
    d["cenas"][0]["dur_piso"] = "sim"
    d["cenas"].insert(1, {"id": "c09", "tipo": "tela", "arquivo": "x.png", "ajuste": "esticar"})
    (tmp_path / "x.png").write_bytes(b"\x89PNG")
    motivos = [e["motivo"] for e in motion.validar(d, tmp_path)]
    assert "dur_piso precisa ser true/false" in motivos and any("ajuste inválido" in m for m in motivos)


@pw
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
def test_tela_contain_com_fundo_desfocado(tmp_path):
    d = {"marca": "dark-historia", "aspecto": "16:9", "cenas": [
        {"id": "c01", "tipo": "tela", "arquivo": "jornal.png", "moldura": "nenhuma", "ajuste": "contain", "dur": 3.0}]}
    p = _proj(tmp_path, d)
    _ff("-f", "lavfi", "-i", "testsrc2=s=800x1200:d=1", "-frames:v", "1", str(p / "jornal.png"))
    r = motion.montar(p)
    assert r["ok"], r["erros"]

    def medir(pg):
        pg.evaluate("t => __kit.ir(t)", 2.0)
        return pg.evaluate("""(() => { const cx = document.querySelector('#c01 .k-midia-caixa');
          return {fit: getComputedStyle(cx.querySelector('img.k-midia:not(.k-midia-fundo)')).objectFit,
                  fundo: cx.querySelectorAll('img.k-midia-fundo').length}; })()""")
    assert _abrir(p / "motion" / "index.html", medir, 1920, 1080) == {"fit": "contain", "fundo": 1}
