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
    (lambda d: d.update(aspecto="16:9"), "raiz", "aspecto"),
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
@pytest.mark.parametrize("marca", ["anotus", "campeio"])
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
