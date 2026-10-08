import json
import subprocess
import sys
from pathlib import Path

import pytest

import localiza

HTML = """<!doctype html><html><head><title>t</title><style>.a{color:red}</style>
<script>const msg = "não-extrair";</script></head><body>
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
    assert "<p>Anotus</p>" in out and 'const msg = "não-extrair"' in out
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
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx"], saida)
    _traduz(saida, {})
    localiza.aplicar(saida, src, dst)                                # 1ª vez: cria com a marca
    assert (dst / localiza.MARCA).is_file()
    (dst / "velho.tsx").write_text("x", encoding="utf-8")
    localiza.aplicar(saida, src, dst)                                # saída anterior: substitui
    assert not (dst / "velho.tsx").exists() and (dst / "goat.tsx").exists() and (dst / localiza.MARCA).is_file()


def test_aplicar_recusa_pasta_alheia(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _arq(src, "goat.tsx", TSX)
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx", h], saida)
    _traduz(saida, {})
    alheia = tmp_path / "alheia"
    alheia.mkdir()
    (alheia / "importante.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não foi criado pelo localiza"):
        localiza.aplicar(saida, src, alheia)                         # pasta → pasta alheia
    with pytest.raises(ValueError, match="pasta"):
        localiza.aplicar(saida, h, alheia)                           # arquivo → pasta existente
    assert [p.name for p in alheia.iterdir()] == ["importante.txt"]


def test_aplicar_nbsp_atributo_e_chave_editada(tmp_path):
    h = _arq(tmp_path, "a.html", '<p>Fecha&nbsp;o&#160;caderno&nbsp;</p><img alt="logo da marca">'
                                 '<script>x.alt="logo da marca"; data-title="logo da marca"</script>'
                                 '<i data-title="logo da marca"></i>')
    saida = tmp_path / "textos.json"
    t = localiza.extrair([h], saida)["textos"]
    assert set(t) == {"Fecha o caderno", "logo da marca"}
    d = json.loads(saida.read_text(encoding="utf-8"))
    d["textos"]["  Fecha   o caderno "] = {**d["textos"].pop("Fecha o caderno"), "trad": "Cierra el cuaderno"}
    d["textos"]["logo da marca"].update(trad="logo de la marca", contextos=["atributo"])   # literal JS fica
    d["textos"][" &nbsp; "] = {"id": "t99", "trad": "LIXO"}                 # chave vazia: ignorada
    saida.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = localiza.aplicar(saida, h, tmp_path / "b.html")
    out = (tmp_path / "b.html").read_text(encoding="utf-8")
    assert "<p>Cierra el cuaderno&nbsp;</p>" in out and '<img alt="logo de la marca">' in out
    assert 'x.alt="logo da marca"; data-title="logo da marca"' in out      # script intacto
    assert '<i data-title="logo da marca">' in out                          # data-title não é title
    assert r["nao_encontrados"] == [] and r["substituicoes"] == 2


def test_extrair_pasta_recursiva(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    _arq(src, "goat.tsx", TSX)
    _arq(src / "sub", "anim.html", HTML)
    _arq(src, "util.ts", 'const x = "não é tela aqui";')
    t = localiza.extrair([src], tmp_path / "textos.json")["textos"]
    assert "feito por Álvaro" in t and "Fecha o caderno" in t and "não é tela aqui" not in t


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


HTML_CTX = """<html><head><style>.caderno{color:red}</style></head><body>
<p class="caderno" id="caderno" data-x="caderno">caderno</p>
<script>el.classList.add("caderno"); el.innerHTML = "<b>caderno</b>"; const t = "Reler o resumo três vezes".split(" ");</script>
</body></html>"""


def test_html_contextos(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML_CTX)
    saida = tmp_path / "textos.json"
    t = localiza.extrair([h], saida)["textos"]
    assert {k: v["contextos"] for k, v in t.items()} == {"caderno": ["texto"], "Reler o resumo três vezes": ["script"]}
    _traduz(saida, {"caderno": "cuaderno", "Reler o resumo três vezes": "Releer el resumen tres veces"})
    r = localiza.aplicar(saida, h, tmp_path / "anim.es.html")
    out = (tmp_path / "anim.es.html").read_text(encoding="utf-8")
    assert '<p class="caderno" id="caderno" data-x="caderno">cuaderno</p>' in out
    assert '.caderno{color:red}' in out and 'classList.add("caderno")' in out
    assert '"Releer el resumen tres veces".split(" ")' in out and r["substituicoes"] == 2
    assert out == HTML_CTX.replace('"caderno">caderno<', '"caderno">cuaderno<').replace("Reler o resumo três vezes", "Releer el resumen tres veces")


def test_aplicar_sem_cascata(tmp_path):
    h = _arq(tmp_path, "a.html", "<p>tá bom</p><p>ok</p>")
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    _traduz(saida, {"tá bom": "ok", "ok": "vale"})
    r = localiza.aplicar(saida, h, tmp_path / "a.es.html")
    assert (tmp_path / "a.es.html").read_text(encoding="utf-8") == "<p>ok</p><p>vale</p>"
    assert r["substituicoes"] == 2


def test_aplicar_origem_inexistente_nao_apaga_destino(tmp_path):
    h = _arq(tmp_path, "a.html", "<p>ok</p>")
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    _traduz(saida, {})
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="origem"):
        localiza.aplicar(saida, tmp_path / "nao_existe", dst)
    assert (dst / "f.txt").exists()


def test_aplicar_escapes_e_quebra_de_linha(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _arq(src, "goat.tsx", TSX)
    saida = tmp_path / "textos.json"
    localiza.extrair([src / "goat.tsx"], saida)
    _traduz(saida, {"feito por Álvaro": "hecho {por} Álvaro", "Seu cérebro confunde": "Tu cerebro \\ confunde"})
    localiza.aplicar(saida, src, tmp_path / "src.es")
    out = (tmp_path / "src.es" / "goat.tsx").read_text(encoding="utf-8")
    assert "<h1>hecho &#123;por&#125; Álvaro</h1>" in out and 'title="Tu cerebro \\\\ confunde"' in out
    _traduz(saida, {"feito por Álvaro": "hecho\npor"})
    with pytest.raises(ValueError, match="t01"):
        localiza.aplicar(saida, src, tmp_path / "src.es2")


def test_aplicar_entrada_malformada(tmp_path):
    saida = _arq(tmp_path, "textos.json", json.dumps({"textos": {"quebrado": "x"}}))
    h = _arq(tmp_path, "a.html", "<p>ok</p>")
    with pytest.raises(ValueError, match="quebrado"):
        localiza.aplicar(saida, h, tmp_path / "b.html")


def test_aplicar_textos_antigos_sem_contextos(tmp_path):
    h = _arq(tmp_path, "anim.html", HTML)
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    _traduz(saida, {"Fecha o caderno": "Cierra el cuaderno", "logo da marca": "logo de la marca"})
    d = json.loads(saida.read_text(encoding="utf-8"))
    for v in d["textos"].values():
        del v["contextos"]
    saida.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = localiza.aplicar(saida, h, tmp_path / "anim.es.html")
    assert r["substituicoes"] == 2 and r["nao_encontrados"] == []


def test_aplicar_preserva_fim_de_linha(tmp_path):
    h = tmp_path / "a.html"
    h.write_bytes("<p>tá bom</p>\n<p>ok</p>\n".encode())
    saida = tmp_path / "textos.json"
    localiza.extrair([h], saida)
    _traduz(saida, {"tá bom": "vale"})
    localiza.aplicar(saida, h, tmp_path / "b.html")
    assert (tmp_path / "b.html").read_bytes() == "<p>vale</p>\n<p>ok</p>\n".encode()
