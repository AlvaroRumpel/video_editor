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
