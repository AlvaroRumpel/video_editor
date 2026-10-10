import json
from pathlib import Path

import pytest

import alinhar


def ws(texto):
    return [t["w"] for t in alinhar.tokens(texto)]


def test_tokens_normaliza_e_marca_frases():
    t = alinhar.tokens("Em junho de 1629, cerca de trezentas pessoas. Muitas morreram.")
    assert [x["w"] for x in t] == ["em", "junho", "de", "1629", "cerca", "de", "300", "pessoas", "muitas", "morreram"]
    assert [x["frase"] for x in t] == [True, False, False, False, False, False, False, False, True, False]


@pytest.mark.parametrize("texto, esperado", [
    ("trezentas e quarenta e uma pessoas", ["341", "pessoas"]),
    ("a uns três mil quilômetros", ["a", "uns", "3000", "quilometros"]),
    ("mil seiscentos e vinte e nove", ["1629"]),
    ("3.000 km", ["3000", "km"]),
    ("em 1628. 341 pessoas", ["em", "1628", "341", "pessoas"]),   # não junta através da frase
    ("cinco e meia", ["5", "e", "meia"]),                          # "e" sem número depois não junta
])
def test_numeros(texto, esperado):
    assert ws(texto) == esperado


def test_casar_extenso_x_digitos():
    tr = [("cerca", 0.0, 0.2), ("de", 0.2, 0.3), ("300", 0.3, 0.6), ("pessoas", 0.6, 1.0), ("a", 1.0, 1.1),
          ("uns", 1.1, 1.3), ("3", 1.3, 1.4), ("mil", 1.4, 1.6), ("quilômetros.", 1.6, 2.2)]
    r = alinhar.casar("cerca de trezentas pessoas a uns três mil quilômetros", tr)
    assert [x["w"] for x in r] == ["cerca", "de", "300", "pessoas", "a", "uns", "3000", "quilometros"]
    assert (r[2]["s"], r[2]["e"]) == (0.3, 0.6)
    assert (r[6]["s"], r[6]["e"]) == (1.3, 1.6)


def test_casar_interpola_palavra_omitida():
    tr = [("cerca", 0.0, 0.2), ("300", 0.6, 0.9), ("pessoas", 0.9, 1.2)]      # whisper perdeu o "de"
    r = alinhar.casar("cerca de trezentas pessoas", tr)
    assert r[1]["w"] == "de" and 0.2 <= r[1]["s"] < r[1]["e"] <= 0.6


def test_casar_poucas_casadas_e_erro():
    with pytest.raises(ValueError, match="casadas"):
        alinhar.casar("o navio bateu no recife", [("bom", 0, 1), ("dia", 1, 2)])


def _proj(tmp_path):
    p = tmp_path / "ep"
    (p / "pt" / "audio").mkdir(parents=True)
    ep = {"id": "ep", "marca": "dark-historia", "titulo": {"pt": "x"}, "cenas": [
        {"id": "c01", "texto": {"pt": "Cerca de trezentas pessoas."}, "fontes": []},
        {"id": "c02", "texto": {"pt": "Ilhas sem água."}, "fontes": []}]}
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    st = {c: {"hash": f"h{c}", "audio": f"pt/audio/{c}.mp3", "dur": 2.0} for c in ("c01", "c02")}
    (p / "pt" / "narracao.json").write_text(json.dumps(st), encoding="utf-8")
    for c in ("c01", "c02"):
        (p / "pt" / "audio" / f"{c}.mp3").write_bytes(b"x")
    return p


def test_alinhar_grava_e_usa_cache(tmp_path):
    p = _proj(tmp_path)
    chamadas = []
    falas = {"c01.mp3": [("cerca", 0, .2), ("de", .2, .3), ("300", .3, .6), ("pessoas.", .6, 1)],
             "c02.mp3": [("ilhas", 0, .3), ("sem", .3, .5), ("água.", .5, .9)]}

    def stub(mp3, lang, prompt=None):
        chamadas.append(Path(mp3).name)
        return falas[Path(mp3).name]
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == ["c01", "c02"]
    d = json.loads((p / "pt" / "palavras.json").read_text(encoding="utf-8"))
    assert d["c01"]["hash"] == "hc01" and d["c01"]["palavras"][2] == {"w": "300", "s": 0.3, "e": 0.6}
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == []          # cache
    st = json.loads((p / "pt" / "narracao.json").read_text(encoding="utf-8"))
    st["c02"]["hash"] = "novo"
    (p / "pt" / "narracao.json").write_text(json.dumps(st), encoding="utf-8")
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == ["c02"]
    assert chamadas == ["c01.mp3", "c02.mp3", "c02.mp3"]


def test_alinhar_sem_tts_e_erro(tmp_path):
    p = _proj(tmp_path)
    (p / "pt" / "narracao.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="rode tts.*c01"):
        alinhar.alinhar(p, "pt", _transcrever=lambda m, l, prompt=None: [])


def test_alinhar_erro_cita_a_cena(tmp_path):
    p = _proj(tmp_path)
    with pytest.raises(ValueError, match="c01"):
        alinhar.alinhar(p, "pt", _transcrever=lambda m, l, prompt=None: [("nada", 0, 1)])


def test_nomes_pega_palavras_com_maiuscula_sem_repetir():
    assert alinhar.nomes("Ethel Le Neve foi absolvida. Crippen e Ethel. Em 1910.") == "Crippen, Em, Ethel, Le, Neve"


def test_alinhar_repete_com_nomes_so_quando_casamento_falha(tmp_path):
    p = _proj(tmp_path)
    chamadas = []
    boa = {"c01.mp3": [("cerca", 0, .2), ("de", .2, .3), ("300", .3, .6), ("pessoas.", .6, 1)],
           "c02.mp3": [("ilhas", 0, .3), ("sem", .3, .5), ("água.", .5, .9)]}

    def stub(mp3, lang, prompt=None):
        n = Path(mp3).name
        chamadas.append((n, prompt))
        if n == "c02.mp3" and prompt is None:
            return [("nada", 0, 1)]                      # 1ª tentativa ruim só na c02
        return boa[n]
    assert alinhar.alinhar(p, "pt", _transcrever=stub)["alinhadas"] == ["c01", "c02"]
    ep = json.loads((p / "episodio.json").read_text(encoding="utf-8"))
    assert chamadas == [("c01.mp3", None), ("c02.mp3", None), ("c02.mp3", alinhar.nomes(ep["cenas"][1]["texto"]["pt"]))]
