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


import subprocess, sys


def _tr(frases):
    """transcript sintético: cada frase vira palavras com gap 1 s entre frases."""
    words, t = [], 0.0
    for f in frases:
        for w in f.split():
            words.append({"text": w, "start": t, "end": t + 0.2, "type": "word"}); t += 0.25
        t += 1.0
    return {"words": words}


def test_extrair_fatos():
    tr = _tr(["eu acho que vale a pena estudar cedo",
              "o prazo da apelação é de 15 dias",
              "isso está no art. 1003 do CPC",
              "todo recurso precisa de preparo sempre"])
    out = pesquisa.extrair_fatos(tr)
    assert [o["gatilho"] for o in out] == ["numero", "lei", "absoluto"]
    assert out[0]["trecho"].startswith("o prazo") and out[0]["t"] > 0


def test_extrair_fatos_simbolos():
    out = pesquisa.extrair_fatos(_tr(["o § 3 prevê isso", "subiu 15% no ano", "caiu 20 por cento"]))
    assert [o["gatilho"] for o in out] == ["lei", "numero", "numero"]


def test_extrair_fatos_vazio():
    assert pesquisa.extrair_fatos({}) == [] and pesquisa.extrair_fatos({"words": []}) == []


def test_cli_validar_e_extrair(md, tmp_path):
    exe = [sys.executable, str(Path(pesquisa.__file__))]
    r = subprocess.run([*exe, "--root", str(tmp_path), "validar", str(md), "--sem-rede"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False
    trp = tmp_path / "t.json"
    trp.write_text(json.dumps(_tr(["o prazo é de 15 dias"])), encoding="utf-8")
    r = subprocess.run([*exe, "extrair-fatos", str(trp)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and json.loads(r.stdout)[0]["gatilho"] == "numero"
    r = subprocess.run([*exe, "validar", str(tmp_path / "nao-existe.md")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "erro" in json.loads(r.stdout)


# ---- correções da revisão final ----
import urllib.error
import urllib.request


def test_fetch_ua_head_get_e_erro(monkeypatch):
    vistos = []

    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b"corpo"

    def fake(req, timeout=0):
        vistos.append((req.get_method(), req.get_header("User-agent"), req.get_header("Accept")))
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 405, "x", {}, None)
        return R()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert pesquisa._fetch_url("https://a.gov.br/x") == (200, b"corpo")
    assert [v[0] for v in vistos] == ["HEAD", "GET"]
    assert vistos[0][1].startswith("Mozilla/5.0") and vistos[0][2].startswith("text/html")

    def boom(req, timeout=0):
        raise urllib.error.URLError("reset")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert pesquisa._fetch_url("https://b.gov.br/y") == (0, b"")
    assert "reset" in pesquisa.ULTIMO_ERRO["https://b.gov.br/y"]


def _p(tmp_path, fontes, texto):
    (tmp_path / "ui").mkdir(exist_ok=True)
    (tmp_path / "ui" / "fontes.json").write_text(json.dumps(fontes), encoding="utf-8")
    p = tmp_path / "p.md"
    p.write_bytes(texto.encode("utf-8-sig"))
    return p


ACH = "- [F1] a — fonte: CPC (lei) — https://www.planalto.gov.br/a — acesso 2026-10-01\n"


def test_validar_status0_mostra_motivo(tmp_path, fontes):
    p = _p(tmp_path, fontes, "## Achados\n" + ACH)
    pesquisa.ULTIMO_ERRO["https://www.planalto.gov.br/a"] = "reset"
    r = pesquisa.validar(p, root=tmp_path, hoje="2026-10-02", _fetch=lambda u: (0, b""))
    assert any("sem resposta (reset)" in e for e in r["erros"])


def test_validar_cache_por_url(tmp_path, fontes):
    p = _p(tmp_path, fontes, "## Achados\n" + ACH + ACH.replace("F1", "F2"))
    n = []
    pesquisa.validar(p, root=tmp_path, hoje="2026-10-02", _fetch=lambda u: (n.append(u), (200, b""))[1])
    assert len(n) == 1


def test_bom_heading_variante_e_vazio(tmp_path, fontes):
    p = _p(tmp_path, fontes, "# t\n## Achados (1)\n" + ACH)
    assert pesquisa.validar(p, root=tmp_path, hoje="2026-10-02", _fetch=_fetch_ok)["ok"] is True
    p = _p(tmp_path, fontes, "# t\n## Achados\n")
    r = pesquisa.validar(p, root=tmp_path, hoje="2026-10-02", _fetch=_fetch_ok)
    assert r["ok"] is False and any("nenhum achado" in e for e in r["erros"])


def test_roteiro_afirmacao_sem_ref(tmp_path, fontes):
    p = _p(tmp_path, fontes, "## Achados\n" + ACH)
    rot = tmp_path / "roteiro.md"
    rot.write_text("# prazo de 15 dias\n1. o prazo é de 15 dias\n2. eu acho que vale a pena\n"
                   "3. o prazo é de 15 dias [F1]\nsfx: 15 dias\n```\nprazo de 15 dias\n```\n"
                   '```json\n{"cues": []}\n```\n', encoding="utf-8")
    r = pesquisa.validar(p, roteiro=rot, root=tmp_path, hoje="2026-10-02", _fetch=_fetch_ok)
    assert [e for e in r["erros"] if "sem [F#]" in e] == [
        "roteiro.md linha 2: afirmação verificável sem [F#]: 1. o prazo é de 15 dias"]


def test_snapshot_nao_sobrescreve_com_falha(md, tmp_path):
    d = tmp_path / "fontes"
    pesquisa.snapshot(md, d, _fetch=lambda u: (200, b"bom"))
    out = pesquisa.snapshot(md, d, _fetch=lambda u: (0, b""))
    assert (d / "F1.html").read_bytes() == b"bom"
    assert out[0]["salvo"] is False and out[0]["status"] == 0


def test_classificar_camadas_do_canal():
    f = {"primaria": ["loc.gov", "*.jus.br"], "secundaria": ["bbc.com"]}
    assert pesquisa.classificar("https://chroniclingamerica.loc.gov/x", f) == "primaria"
    assert pesquisa.classificar("https://www.tjsp.jus.br/a", f) == "primaria"
    assert pesquisa.classificar("https://www.bbc.com/a", f) == "secundaria"
    assert pesquisa.classificar("https://www.reddit.com/r/TrueCrime/x", f) == "inspiracao"


def test_validar_com_fontes_do_canal(tmp_path):
    md = tmp_path / "pesquisa.md"
    md.write_text("## Achados\n\n- [F1] Fato — fonte: Reddit (relato) — https://www.reddit.com/r/x — acesso 2026-10-08\n"
                  "  > trecho\n", encoding="utf-8")
    fj = tmp_path / "fontes.json"
    fj.write_text(json.dumps({"primaria": ["loc.gov"], "secundaria": ["bbc.com"]}), encoding="utf-8")
    r = pesquisa.validar(md, fontes_path=fj, _fetch=lambda u, *a: (200, b""), hoje="2026-10-08")
    assert any("inspiracao" in e and "primaria/secundaria" in e for e in r["erros"])
