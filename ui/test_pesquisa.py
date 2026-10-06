import json
from pathlib import Path
import pytest
import pesquisa

EXEMPLO = """# Pesquisa — prazo recursal
<!-- gerado: 2026-10-06 · formato: ads -->

## Pergunta
Qual o prazo da apelação?

## Achados
- [F1] O prazo da apelação é de 15 dias úteis — fonte: CPC art. 1003 §5º (lei) — https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2015/lei/l13105.htm — acesso 2026-10-06
  > § 5º Excetuados os embargos de declaração, o prazo para interpor os recursos e para responder-lhes é de 15 (quinze) dias.
- [F2] Prazos processuais contam-se em dias úteis — fonte: CPC art. 219 (lei) — https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2015/lei/l13105.htm — acesso 2026-10-06
  > Na contagem de prazo em dias, estabelecido por lei ou pelo juiz, computar-se-ão somente os dias úteis.
- isto não é um achado válido

## Ângulos
- Vídeo X já fez "5 prazos" — https://blog.exemplo.com/prazos (inspiração)
- Falta: contagem em feriado local

## Riscos
- Prazo em juizado especial é diferente

## Fontes rejeitadas
- https://blog.qualquer.com/prazo — sem autoria
"""


@pytest.fixture
def fontes():
    return {"oficial": ["planalto.gov.br", "stf.jus.br", "*.jus.br", "*.gov.br"],
            "doutrina": ["editorajuspodivm.com.br"]}


def test_parse_achados(tmp_path):
    p = pesquisa.parse_pesquisa(EXEMPLO)
    assert [a["id"] for a in p["achados"]] == ["F1", "F2"]
    a = p["achados"][0]
    assert a["fato"].startswith("O prazo da apelação")
    assert a["fonte"] == "CPC art. 1003 §5º" and a["tipo"] == "lei"
    assert a["url"].startswith("https://www.planalto.gov.br/")
    assert a["acesso"] == "2026-10-06" and a["trecho"].startswith("§ 5º")
    assert a["linha"] == 8
    assert p["malformados"] == [{"linha": 12, "texto": "- isto não é um achado válido"}]
    assert len(p["angulos"]) == 2 and len(p["riscos"]) == 1 and len(p["rejeitadas"]) == 1


def test_parse_sem_secoes():
    p = pesquisa.parse_pesquisa("# nada\n")
    assert p == {"achados": [], "angulos": [], "riscos": [], "rejeitadas": [], "malformados": []}


@pytest.mark.parametrize("url,esperado", [
    ("https://www.planalto.gov.br/ccivil_03/x.htm", "oficial"),
    ("https://portal.stf.jus.br/x", "oficial"),
    ("https://www.tjsp.jus.br/x", "oficial"),
    ("https://www.editorajuspodivm.com.br/livro", "doutrina"),
    ("https://blog.exemplo.com/prazos", "inspiracao"),
    ("nao-e-url", "inspiracao"),
])
def test_classificar(fontes, url, esperado):
    assert pesquisa.classificar(url, fontes) == esperado


def test_carregar_fontes(tmp_path):
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps({"oficial": ["a.gov.br"], "doutrina": []}), encoding="utf-8")
    assert pesquisa.carregar_fontes(tmp_path)["oficial"] == ["a.gov.br"]


def _fetch_ok(url):
    return (200, b"<html><title>ok</title>" + b"x" * 10)


@pytest.fixture
def md(tmp_path, fontes):
    (tmp_path / "ui").mkdir(exist_ok=True)
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps(fontes), encoding="utf-8")
    p = tmp_path / "pesquisa.md"
    p.write_text(EXEMPLO, encoding="utf-8")
    return p


def test_validar_ok_e_malformado(md, tmp_path):
    r = pesquisa.validar(md, root=tmp_path, hoje="2026-10-10", _fetch=_fetch_ok)
    assert r["ok"] is False
    assert any("linha 12" in e and "malformado" in e for e in r["erros"])
    assert len(r["erros"]) == 1


def test_validar_url_404_e_inspiracao(tmp_path, fontes):
    (tmp_path / "ui").mkdir(exist_ok=True)
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps(fontes), encoding="utf-8")
    p = tmp_path / "p.md"
    p.write_text("## Achados\n- [F1] fato — fonte: Blog (dado) — https://blog.x.com/a — acesso 2026-10-01\n"
                 "- [F2] fato — fonte: CPC (lei) — https://www.planalto.gov.br/b — acesso 2026-10-01\n",
                 encoding="utf-8")
    def fetch(url):
        return (404, b"") if url.endswith("/b") else (200, b"ok")
    r = pesquisa.validar(p, root=tmp_path, hoje="2026-10-02", _fetch=fetch)
    assert any("F1" in e and "inspiracao" in e for e in r["erros"])
    assert any("F2" in e and "404" in e for e in r["erros"])


def test_validar_redirect_aceito_e_avisos(tmp_path, fontes):
    (tmp_path / "ui").mkdir(exist_ok=True)
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps(fontes), encoding="utf-8")
    p = tmp_path / "p.md"
    p.write_text("## Achados\n- [F1] fato — fonte: CPC (lei) — https://www.planalto.gov.br/b — acesso 2026-01-01\n",
                 encoding="utf-8")
    r = pesquisa.validar(p, root=tmp_path, hoje="2026-10-06", _fetch=lambda u: (301, b""))
    assert r["ok"] is True
    assert any("180 dias" in a for a in r["avisos"]) and any("trecho vazio" in a for a in r["avisos"])


def test_validar_duplicado_e_referencia(tmp_path, fontes):
    (tmp_path / "ui").mkdir(exist_ok=True)
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps(fontes), encoding="utf-8")
    p = tmp_path / "p.md"
    p.write_text("## Achados\n- [F1] a — fonte: CPC (lei) — https://www.planalto.gov.br/a — acesso 2026-10-01\n"
                 "- [F1] b — fonte: CPC (lei) — https://www.planalto.gov.br/b — acesso 2026-10-01\n", encoding="utf-8")
    rot = tmp_path / "roteiro.md"
    rot.write_text("## Cenas\n1. prazo de 15 dias [F1]\n2. outra coisa [F9]\n", encoding="utf-8")
    r = pesquisa.validar(p, roteiro=rot, root=tmp_path, hoje="2026-10-02", _fetch=_fetch_ok)
    assert any("duplicado" in e and "F1" in e for e in r["erros"])
    assert any("F9" in e and "roteiro.md" in e for e in r["erros"])


def test_snapshot(md, tmp_path):
    big = (200, b"<title>T</title>" + b"y" * (3 * 1024 * 1024))
    out = pesquisa.snapshot(md, tmp_path / "fontes", _fetch=lambda u: big)
    assert (tmp_path / "fontes" / "F1.html").stat().st_size <= 2 * 1024 * 1024
    idx = json.loads((tmp_path / "fontes" / "index.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in idx] == ["F1", "F2"] and idx[0]["titulo"] == "T"
    assert out == idx
