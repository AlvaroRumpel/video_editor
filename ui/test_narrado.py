import json
from pathlib import Path

import pytest
from PIL import Image

import motion
import narrado

ACHADO = ("- [F1] Explosão de 1908 derrubou 80 milhões de árvores — fonte: Smithsonian Magazine (secundaria)"
          " — https://www.smithsonianmag.com/x — acesso 2026-10-08\n  > trecho\n")


def _ep():
    return {"id": "001-teste", "marca": "dark-historia", "titulo": {"pt": "O mistério de Tunguska"},
            "cenas": [
                {"id": "c01", "texto": {"pt": "Em 1908, algo explodiu sobre a Sibéria."}, "fontes": ["F1"],
                 "visual": {"tipo": "arquivo", "src": "assets/foto.png",
                            "fonte_url": "https://commons.wikimedia.org/wiki/File:X.jpg",
                            "licenca": "Public domain", "credito": "Leonid Kulik, 1927"},
                 "overlay": {"pt": "Sibéria, 1908"}},
                {"id": "c02", "texto": {"pt": "Ninguém viu a explosão de perto."}, "fontes": [],
                 "visual": {"tipo": "motion", "cena": {"tipo": "frase", "fundo": "escuro",
                                                      "linhas": [{"t": {"pt": "Ninguém viu."}, "estilo": "punch"}]}}}]}


def _proj(tmp_path, ep=None):
    p = tmp_path / "001-teste"
    (p / "assets").mkdir(parents=True)
    Image.new("RGB", (1600, 1000), "gray").save(p / "assets" / "foto.png")
    (p / "pesquisa.md").write_text("## Achados\n\n" + ACHADO, encoding="utf-8")
    (p / "episodio.json").write_text(json.dumps(ep or _ep(), ensure_ascii=False), encoding="utf-8")
    return p


def test_validar_ok(tmp_path):
    p = _proj(tmp_path)
    assert narrado.validar(narrado.ler(p), p, "pt") == []


@pytest.mark.parametrize("s, ok", [
    ("Public domain", True), ("PD-US", True), ("CC0", True), ("CC BY 2.0", True), ("CC BY-SA 4.0", True),
    ("http://creativecommons.org/publicdomain/mark/1.0/", True),
    ("https://creativecommons.org/licenses/by-sa/4.0/", True),
    ("CC BY-NC 4.0", False), ("CC BY-ND 2.0", False),
    ("https://creativecommons.org/licenses/by-nc/4.0/", False), ("ver página", False), ("", False), (None, False)])
def test_licenca_ok(s, ok):
    assert narrado.licenca_ok(s) is ok


@pytest.mark.parametrize("mut, cid, trecho", [
    (lambda e: e["cenas"][0].update(id="cena1"), "#0", "id inválido"),
    (lambda e: e["cenas"][1].update(id="c01"), "c01", "id duplicado"),
    (lambda e: e["cenas"][0]["texto"].update(pt="  "), "c01", "falta texto.pt"),
    (lambda e: e["cenas"][0]["texto"].update(pt="a" * 5001), "c01", "5000"),
    (lambda e: e["cenas"][0].update(fontes=["F9"]), "c01", "[F9] não existe"),
    (lambda e: e["cenas"][0].pop("fontes"), "c01", "fontes precisa ser lista"),
    (lambda e: e["cenas"][0]["visual"].update(licenca="CC BY-NC 4.0"), "c01", "licença não aceita"),
    (lambda e: e["cenas"][0]["visual"].update(src="assets/nada.png"), "c01", "src não encontrado"),
    (lambda e: e["cenas"][0]["visual"].pop("credito"), "c01", "fonte_url e credito"),
    (lambda e: e["cenas"][1]["visual"].pop("cena"), "c02", "motion precisa de cena"),
    (lambda e: e["cenas"][1]["visual"].update(tipo="video"), "c02", "visual.tipo inválido"),
    (lambda e: e.pop("marca"), "raiz", "falta marca"),
    (lambda e: e["titulo"].pop("pt"), "raiz", "falta titulo.pt"),
])
def test_validar_erros(tmp_path, mut, cid, trecho):
    ep = _ep()
    mut(ep)
    p = _proj(tmp_path, ep)
    erros = narrado.validar(narrado.ler(p), p, "pt")
    assert any(e["id"] == cid and trecho in e["motivo"] for e in erros), erros


def test_validar_sem_pesquisa(tmp_path):
    p = _proj(tmp_path)
    (p / "pesquisa.md").unlink()
    assert any(e["motivo"] == "falta pesquisa.md" for e in narrado.validar(narrado.ler(p), p, "pt"))


def test_ler_ausente(tmp_path):
    with pytest.raises(ValueError, match="episodio.json"):
        narrado.ler(tmp_path)


def test_loc():
    v = {"tipo": "frase", "linhas": [{"t": {"pt": "Oi", "en": "Hi"}, "em": 1.0}]}
    assert narrado._loc(v, "en") == {"tipo": "frase", "linhas": [{"t": "Hi", "em": 1.0}]}
    assert narrado._loc({"pt": "x"}, "en") is None


def test_cenas_motion_duracoes_e_tipos():
    tema = motion.carregar_tema("dark-historia")          # fade 0.45
    d = narrado.cenas_motion(_ep(), "pt", {"c01": 3.0, "c02": 2.0}, tema)
    assert d["marca"] == "dark-historia" and d["aspecto"] == "16:9"
    c1, c2 = d["cenas"]
    assert c1 == {"id": "c01", "tipo": "tela", "arquivo": "assets/foto.png", "moldura": "nenhuma",
                  "kenburns": True, "label": "Sibéria, 1908", "dur": 3.85}     # 0 + 3.0 + 0.4 + 0.45
    assert c2["tipo"] == "frase" and c2["linhas"][0]["t"] == "Ninguém viu."
    assert c2["dur"] == 2.85                                                    # 0.45 + 2.0 + 0.4 + 0


def test_cenas_motion_valida_no_kit(tmp_path):
    p = _proj(tmp_path)
    d = narrado.cenas_motion(narrado.ler(p), "pt", {"c01": 3.0, "c02": 2.0}, motion.carregar_tema("dark-historia"))
    assert motion.validar(d, p, "pt") == []
