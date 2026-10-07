import json
import subprocess
import sys
from pathlib import Path

import pytest

import localiza

HTML = """<!doctype html><html><head><title>t</title><style>.a{color:red}</style>
<script>const msg = "não extrair isto";</script></head><body>
<div class="t1">TE DÁ A SENSAÇÃO
   DE QUE VOCÊ SABE</div><span>e é só sensação.</span>
<img alt="logo da marca" src="x.png"><p>Fecha o caderno</p><p>Anotus</p><p>123</p>
</body></html>"""

TSX = """export const A = () => (<div className="flex items-center">
  <h1>feito por Álvaro</h1>
  <Lower title="Seu cérebro confunde" sub={"reconhecer com saber"} />
  {x > 0 && y < 2}
  <img src="/public/logo.png" />
  <a href="https://exemplo.com/pagina boa">ok</a>
</div>);"""


def _arq(tmp, nome, txt):
    p = tmp / nome
    p.write_text(txt, encoding="utf-8")
    return p


def test_extrair_html(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    d = localiza.extrair([h], tmp_path / "textos.json")
    t = d["textos"]
    assert set(t) == {"TE DÁ A SENSAÇÃO DE QUE VOCÊ SABE", "e é só sensação.", "logo da marca", "Fecha o caderno", "Anotus"}
    assert t["Fecha o caderno"]["trad"] is None and t["Fecha o caderno"]["arquivos"] == ["anim.html"]
    assert [v["id"] for v in t.values()] == ["t01", "t02", "t03", "t04", "t05"]


def test_extrair_tsx(tmp_path):
    x = _arq(tmp_path, "goat.tsx", TSX)
    t = localiza.extrair([x], tmp_path / "textos.json")["textos"]
    assert "feito por Álvaro" in t and "Seu cérebro confunde" in t and "reconhecer com saber" in t
    assert "flex items-center" not in t and "/public/logo.png" not in t
    assert not any("https://" in k for k in t) and not any("&&" in k for k in t)


def test_extrair_mescla_preserva_trad(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    d = json.loads(saida.read_text(encoding="utf-8"))
    d["textos"]["Fecha o caderno"]["trad"] = "Cierra el cuaderno"
    saida.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    h.write_text(HTML.replace("Fecha o caderno", "Fecha o caderno</p><p>Novo texto aqui"), encoding="utf-8")
    t = localiza.extrair([h], saida)["textos"]
    assert t["Fecha o caderno"]["trad"] == "Cierra el cuaderno" and t["Fecha o caderno"]["id"] == "t04"
    assert t["Novo texto aqui"]["id"] == "t06"


def _traduz(saida, mapa):
    d = json.loads(saida.read_text(encoding="utf-8"))
    for k, v in d["textos"].items():
        v["trad"] = mapa.get(k, "=")
    saida.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_aplicar_html(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    _traduz(saida, {"TE DÁ A SENSAÇÃO DE QUE VOCÊ SABE": "TE DA LA SENSACIÓN DE QUE SABES",
                    "e é só sensação.": "y es solo sensación.", "logo da marca": "logo de la marca",
                    "Fecha o caderno": "Cierra el cuaderno <ya>"})
    r = localiza.aplicar(saida, h, tmp_path / "anim.es.html")
    out = (tmp_path / "anim.es.html").read_text(encoding="utf-8")
    assert "TE DA LA SENSACIÓN DE QUE SABES" in out and "y es solo sensación." in out
    assert 'alt="logo de la marca"' in out and "Cierra el cuaderno &lt;ya&gt;" in out
    assert "<p>Anotus</p>" in out and 'const msg = "não extrair isto"' in out
    assert r["substituicoes"] == 4 and r["nao_encontrados"] == []
    assert h.read_text(encoding="utf-8") == HTML                    # origem intacta


def test_aplicar_tsx_escapa_aspas(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _arq(src, "goat.tsx", TSX)
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx"], saida)
    _traduz(saida, {"Seu cérebro confunde": 'Tu cerebro "confunde"', "feito por Álvaro": "hecho por Álvaro"})
    localiza.aplicar(saida, src, tmp_path / "src.es")
    out = (tmp_path / "src.es" / "goat.tsx").read_text(encoding="utf-8")
    assert 'title="Tu cerebro “confunde”"' in out and "<h1>hecho por Álvaro</h1>" in out


def test_aplicar_falta_traducao(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    with pytest.raises(ValueError, match="t01"):
        localiza.aplicar(saida, h, tmp_path / "anim.es.html")
    assert not (tmp_path / "anim.es.html").exists()


def test_aplicar_destino_perigoso(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _arq(src, "goat.tsx", TSX)
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx"], saida)
    _traduz(saida, {})
    for destino in (src, src / "sub", tmp_path):
        with pytest.raises(ValueError, match="destino"):
            localiza.aplicar(saida, src, destino)
    assert (src / "goat.tsx").read_text(encoding="utf-8") == TSX


def test_aplicar_substitui_destino_existente(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _arq(src, "goat.tsx", TSX)
    dst = tmp_path / "src.es"
    dst.mkdir()
    (dst / "velho.tsx").write_text("x", encoding="utf-8")
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx"], saida)
    _traduz(saida, {})
    localiza.aplicar(saida, src, dst)
    assert not (dst / "velho.tsx").exists() and (dst / "goat.tsx").exists()


ANIM_ESTOURO = """<!doctype html><html><body style="margin:0">
<div id="caixa" style="width:100px;white-space:nowrap;overflow:hidden">texto muito comprido que estoura a caixa</div>
<div id="ok" style="width:400px">curto</div>
<script>window.seek = f => {}; window.READY = true;</script></body></html>"""


def _chromium_ok():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chromium_ok(), reason="chromium indisponível")
def test_checar_estouro(tmp_path):
    h = _arq(tmp_path, "anim.html", ANIM_ESTOURO)
    r = localiza.checar(h, frames=2, total=10)
    assert r["ok"] is False
    assert [e["seletor"] for e in r["estouros"]] == ["div#caixa"]
    assert r["estouros"][0]["texto"].startswith("texto muito")


def _cli(*a):
    return subprocess.run([sys.executable, str(Path(localiza.__file__)), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    r = _cli("extrair", str(h), "--saida", str(saida))
    assert r.returncode == 0 and json.loads(r.stdout)["textos"] == 5
    r = _cli("aplicar", str(saida), str(h), str(tmp_path / "x.html"))
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)


def test_extrair_tsx_ignora_svg_path(tmp_path):
    x = _arq(tmp_path, "i.tsx", '<path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3z" />')
    assert localiza.extrair([x], tmp_path / "textos.json")["textos"] == {}
