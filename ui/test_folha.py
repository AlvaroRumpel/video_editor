import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import folha
import pipeline
from test_pipeline import fake_root  # noqa: F401 — fixture reexport


@pytest.fixture
def proj(fake_root):
    return fake_root / "edit-fake"


def _w(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


BROLL = {"momentos": [
    {"id": "b01", "t_in": 42, "t_out": 45, "termo": "gavel", "modo": "cut-in", "status": "proposto",
     "escolhido": "b01-2",
     "candidatos": [{"fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4", "dur": 6, "licenca": "Pexels License", "autor": "Ana"},
                    {"fonte": "pixabay", "tipo": "video", "arq": "broll/cand/b.mp4", "dur": 8}]},
    {"id": "b02", "t_in": 75, "t_out": 78, "termo": "court", "modo": "janela", "status": "proposto",
     "candidatos": [{"fonte": "pexels", "tipo": "foto", "arq": "broll/cand/c.jpg"}]},
    {"id": "b03", "status": "aprovado", "candidatos": []},
]}


def test_ler_broll(proj):
    _w(proj / "broll.json", BROLL)
    d = folha.ler(proj, "broll")
    assert [m["id"] for m in d["momentos"]] == ["b01", "b02"]          # só propostos
    m1, m2 = d["momentos"]
    assert m1["escolhido"] == "b01-2" and m2["escolhido"] == "b02-1"    # default = 1º rótulo
    assert m1["candidatos"][0] == {"rotulo": "b01-1", "fonte": "pexels", "tipo": "video", "arq": "broll/cand/a.mp4",
                                   "dur": 6.0, "licenca": "Pexels License", "autor": "Ana"}
    assert m2["candidatos"][0]["tipo"] == "foto" and m2["candidatos"][0]["dur"] == 0.0


def test_ler_broll_escolhido_invalido_vira_primeiro(proj):
    b = json.loads(json.dumps(BROLL))
    b["momentos"][0]["escolhido"] = "b01-9"
    _w(proj / "broll.json", b)
    assert folha.ler(proj, "broll")["momentos"][0]["escolhido"] == "b01-1"


CLIPS = {"x_padrao": 640, "clipes": [
    {"id": "c01", "slug": "zero", "status": "proposto", "nota": 4, "gancho": "Zero inscritos",
     "ranges": [{"t_in": 10.0, "t_out": 20.0, "beat": "hook"}, {"t_in": 30.0, "t_out": 35.5}], "x": 700,
     "legenda": True, "plataformas": ["shorts", "reels"]},
    {"id": "c02", "slug": "dois", "status": "proposto", "gancho": "g", "ranges": [{"t_in": 1, "t_out": 2}]},
    {"id": "c03", "slug": "tres", "status": "vetado", "ranges": [{"t_in": 1, "t_out": 2}]},
]}


def test_ler_clips(proj):
    _w(proj / "clips" / "clips.json", CLIPS)
    d = folha.ler(proj, "clips")
    assert d["x_padrao"] == 640 and [c["id"] for c in d["clipes"]] == ["c01", "c02"]
    c1, c2 = d["clipes"]
    assert c1["ranges"] == [{"t_in": 10.0, "t_out": 20.0}, {"t_in": 30.0, "t_out": 35.5}]
    assert c1["dur"] == 15.5 and c1["x"] == 700 and c1["legenda"] is True
    assert c1["plataformas"] == ["shorts", "reels"] and c1["nota"] == 4
    assert c2["x"] == 640 and c2["legenda"] is False and c2["nota"] is None and c2["plataformas"] == []


def test_ler_clips_x_nulo_e_invalido(proj):
    _w(proj / "clips" / "clips.json", {"x_padrao": None, "clipes": [
        {"id": "c01", "status": "proposto", "x": None, "ranges": [{"t_in": 0, "t_out": 1}]}]})
    d = folha.ler(proj, "clips")
    assert d["x_padrao"] == 636 and d["clipes"][0]["x"] == 636
    _w(proj / "clips" / "clips.json", {"x_padrao": 600, "clipes": [
        {"id": "c01", "status": "proposto", "x": None, "ranges": [{"t_in": 0, "t_out": 1}]}]})
    assert folha.ler(proj, "clips")["clipes"][0]["x"] == 600
    for doc in ({"x_padrao": "abc", "clipes": []},
                {"clipes": [{"id": "c01", "status": "proposto", "x": [1], "ranges": [{"t_in": 0, "t_out": 1}]}]}):
        _w(proj / "clips" / "clips.json", doc)
        with pytest.raises(ValueError, match="x"):
            folha.ler(proj, "clips")


def test_ler_clips_x_padrao_default(proj):
    _w(proj / "clips" / "clips.json", {"clipes": [{"id": "c01", "status": "proposto", "ranges": [{"t_in": 0, "t_out": 1}]}]})
    d = folha.ler(proj, "clips")
    assert d["x_padrao"] == 636 and d["clipes"][0]["x"] == 636


@pytest.mark.parametrize("clipe,motivo", [
    ({"id": "c01", "status": "proposto"}, "sem ranges"),
    ({"id": "c01", "status": "proposto", "ranges": [{"t_in": 1}]}, "range"),
    ({"status": "proposto", "ranges": []}, "sem id"),
])
def test_ler_clips_invalido(proj, clipe, motivo):
    _w(proj / "clips" / "clips.json", {"clipes": [clipe]})
    with pytest.raises(ValueError, match=motivo):
        folha.ler(proj, "clips")


def test_ler_conceitos(proj):
    (proj / "animatic-A.png").write_bytes(b"\x89PNG")
    _w(proj / "conceitos.json", {"conceitos": [
        {"id": "A", "ideia": "mesmo mecanismo", "mantem": "ritmo", "muda": "tema", "custo": "US$ 0,40",
         "horas": 2, "exige_ia": False, "animatic": "animatic-A.png"},
        {"id": "B", "ideia": "outro", "exige_ia": True, "animatic": "animatic-B.png"},   # png não existe
        {"id": "C", "animatic": "../fora.png"}]})
    d = folha.ler(proj, "conceitos")
    a, b, c = d["conceitos"]
    assert a == {"id": "A", "ideia": "mesmo mecanismo", "mantem": "ritmo", "muda": "tema", "custo": "US$ 0,40",
                 "horas": 2, "exige_ia": False, "animatic": "animatic-A.png"}
    assert b["animatic"] is None and b["exige_ia"] is True and b["mantem"] == ""
    assert c["animatic"] is None


def test_ler_null_vira_texto_vazio(proj):
    _w(proj / "conceitos.json", {"conceitos": [{"id": "A", "ideia": None, "mantem": None, "muda": None, "custo": None}]})
    a = folha.ler(proj, "conceitos")["conceitos"][0]
    assert a["ideia"] == a["mantem"] == a["muda"] == a["custo"] == ""
    _w(proj / "broll.json", {"momentos": [{"id": "b01", "status": "proposto", "termo": None, "modo": None,
                                           "candidatos": [{"fonte": None, "tipo": None, "arq": None, "licenca": None, "autor": None}]}]})
    m = folha.ler(proj, "broll")["momentos"][0]
    assert m["termo"] == m["modo"] == "" and m["candidatos"][0]["tipo"] == "video"
    assert all(m["candidatos"][0][k] == "" for k in ("fonte", "arq", "licenca", "autor"))
    _w(proj / "clips" / "clips.json", {"clipes": [{"id": "c01", "status": "proposto", "slug": None, "gancho": None,
                                                   "plataformas": "shorts", "ranges": [{"t_in": 0, "t_out": 1}]}]})
    c = folha.ler(proj, "clips")["clipes"][0]
    assert c["slug"] == c["gancho"] == "" and c["plataformas"] == ["shorts"]
    (proj / "overlays").mkdir()
    _w(proj / "overlays" / "folha.json", {"overlays": [{"id": "o01", "arquivo": None}]})
    assert folha.ler(proj, "overlays")["overlays"][0]["arquivo"] == ""


def test_ler_clips_x_infinito(proj):
    (proj / "clips").mkdir()
    (proj / "clips" / "clips.json").write_text('{"x_padrao": Infinity, "clipes": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="x_padrao"):
        folha.ler(proj, "clips")


def test_ler_overlays(proj):
    (proj / "overlays").mkdir()
    (proj / "overlays" / "o01.png").write_bytes(b"\x89PNG")
    _w(proj / "overlays" / "folha.json", {"overlays": [
        {"id": "o01", "arquivo": "a.mov", "t": 1.5, "dur": 3, "png": "overlays/o01.png"},
        {"id": "o02", "arquivo": "b.mov", "t": 9, "dur": 2, "png": "overlays/o02.png", "erro": None},
        {"id": "o03", "arquivo": "c.mov", "t": 12, "dur": 2, "png": "../x.png"}]})
    d = folha.ler(proj, "overlays")
    assert d["overlays"][0] == {"id": "o01", "arquivo": "a.mov", "t": 1.5, "dur": 3.0, "png": "overlays/o01.png", "erro": None}
    assert d["overlays"][1]["png"] is None and d["overlays"][2]["png"] is None


@pytest.mark.parametrize("tipo,arq", [("broll", "broll.json"), ("clips", "clips/clips.json"),
                                      ("conceitos", "conceitos.json"), ("overlays", "overlays/folha.json")])
def test_ler_ausente_e_invalido(proj, tipo, arq):
    with pytest.raises(ValueError, match="não encontrado"):
        folha.ler(proj, tipo)
    (proj / arq).parent.mkdir(parents=True, exist_ok=True)
    (proj / arq).write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="inválido"):
        folha.ler(proj, tipo)
    (proj / arq).write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="inválido"):
        folha.ler(proj, tipo)


def test_ler_broll_sem_candidatos(proj):
    _w(proj / "broll.json", {"momentos": [{"id": "b01", "status": "proposto"}]})
    with pytest.raises(ValueError, match="sem candidatos"):
        folha.ler(proj, "broll")


def test_ler_tipo_invalido(proj):
    with pytest.raises(ValueError, match="tipo"):
        folha.ler(proj, "nada")


def _fake_run(calls, falha_em=None):
    def run(args, **kw):
        calls.append(args)
        if falha_em is not None and len(calls) == falha_em:
            raise subprocess.CalledProcessError(1, args)
        Path(args[-1]).write_bytes(b"\x89PNGfake")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
    return run


def _edl_com_overlays(proj, overlays):
    edl = json.loads((proj / "edl.json").read_text(encoding="utf-8"))
    edl["overlays"] = overlays
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")


def _mtime(path: Path, delta: float):
    st = (path.parent / "edl.json").stat().st_mtime + delta
    os.utime(path, (st, st))


def test_overlays_sobre_preview(proj):
    (proj / "anim").mkdir()
    (proj / "anim" / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "anim/A.mov", "start_in_output": 4.0, "duration": 2.0}])
    _mtime(proj / "preview.mp4", +10)                                    # render mais novo que o edl
    calls = []
    d = folha.overlays(proj, _run=_fake_run(calls))
    assert d["overlays"] == [{"id": "o01", "arquivo": "anim/A.mov", "t": 4.0, "dur": 2.0, "png": "overlays/o01.png", "erro": None}]
    args = calls[0]
    assert args[0] == "ffmpeg" and args.count("-i") == 1                 # só o base: overlay já queimado
    assert args[args.index("-i") + 1] == str(proj / "preview.mp4")
    assert "5.000" in args                                                # base em t + dur/2
    assert not any("A.mov" in a for a in args)
    assert json.loads((proj / "overlays" / "folha.json").read_text(encoding="utf-8")) == d


def test_overlays_preview_desatualizado_usa_preto(proj):
    (proj / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 4.0, "duration": 2.0}])
    _mtime(proj / "preview.mp4", -10)                                    # render mais velho que o edl
    calls = []
    folha.overlays(proj, _run=_fake_run(calls))
    args = calls[0]
    assert "lavfi" in args and str(proj / "preview.mp4") not in args
    assert str(proj / "A.mov") in args and "1.000" in args
    assert any("overlay=0:0" in a for a in args)                          # como o render.py: 0:0, sem centralizar


def test_overlays_final_velho_nao_esconde_preview_novo(proj):
    (proj / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 4.0, "duration": 2.0}])
    (proj / "final.mp4").write_bytes(b"mp4")
    _mtime(proj / "final.mp4", -10)
    _mtime(proj / "preview.mp4", +10)
    calls = []
    folha.overlays(proj, _run=_fake_run(calls))
    assert calls[0][calls[0].index("-i") + 1] == str(proj / "preview.mp4")


def test_overlays_sem_video_base_usa_preto(proj):
    (proj / "preview.mp4").unlink()
    (proj / "A.mov").write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 0, "duration": 1}])
    calls = []
    folha.overlays(proj, _run=_fake_run(calls))
    assert "lavfi" in calls[0] and any("color=c=black" in a for a in calls[0])


def test_overlays_arquivo_ausente_e_ffmpeg_falha(proj):
    for n in ("A.mov", "C.mov"):
        (proj / n).write_bytes(b"mov")
    _edl_com_overlays(proj, [{"file": "A.mov", "start_in_output": 0, "duration": 1},
                             {"file": "B.mov", "start_in_output": 5, "duration": 1},
                             {"file": "C.mov", "start_in_output": 9, "duration": 1}])
    calls = []
    d = folha.overlays(proj, _run=_fake_run(calls, falha_em=2))     # 2ª chamada (C.mov) falha
    o1, o2, o3 = d["overlays"]
    assert o1["png"] == "overlays/o01.png" and o1["erro"] is None
    assert o2["png"] is None and "não encontrado" in o2["erro"]
    assert o3["png"] is None and o3["erro"].startswith("ffmpeg")
    assert len(calls) == 2


def test_overlays_edl_sem_overlays(proj):
    d = folha.overlays(proj, _run=_fake_run([]))
    assert d == {"overlays": []}
    assert (proj / "overlays" / "folha.json").exists()


def _cli(*a):
    return subprocess.run([sys.executable, str(Path(folha.__file__)), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli(proj):
    _w(proj / "broll.json", BROLL)
    r = _cli("ler", str(proj), "broll")
    assert r.returncode == 0 and json.loads(r.stdout)["momentos"][0]["id"] == "b01"
    r = _cli("ler", str(proj), "clips")
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)


def _txt(rel):
    return (pipeline.ROOT / rel).read_text(encoding="utf-8")


def test_protocolo_folhas_documentado():
    claude = _txt("CLAUDE.md")
    assert '"folha"' in claude and "ok` + exceções" in claude
    longo = _txt("Formatos/padrao-youtube-longo.md")
    assert 'folha: "broll"' in longo and 'folha: "overlays"' in longo
    assert "python ui/folha.py overlays" in longo and "§5.2" in longo
    assert 'folha: "clips"' in _txt("Formatos/padrao-youtube-shorts.md")
    ref = _txt("Formatos/referencia.md")
    assert "conceitos.json" in ref and '"folha": "conceitos"' in ref
    assert "ui/queue.json" in ref and "aguardando escolha" in ref
    assert "fila do projeto" in claude


def _dub_fixture(proj, lang="es", textos=True):
    d = proj / "dub" / lang
    d.mkdir(parents=True)
    (d / "dublagem.json").write_text(json.dumps({"lang": lang, "frases": [
        {"id": "f001", "t_in": 0.0, "t_out": 2.0, "orig": "oi gente", "trad": "hola gente"},
        {"id": "f002", "t_in": 2.5, "t_out": 3.0, "orig": "tudo bem", "trad": None}]}), encoding="utf-8")
    if textos:
        (d / "textos.json").write_text(json.dumps({"textos": {
            "Fecha o caderno": {"id": "t01", "trad": "Cierra el cuaderno", "arquivos": ["anim.html"]}}}),
            encoding="utf-8")


def test_ler_traducao(proj):
    _dub_fixture(proj)
    d = folha.ler(proj, "traducao")
    assert d["lang"] == "es" and d["cps"] == 15.0
    assert d["frases"][0] == {"id": "f001", "t_in": 0.0, "t_out": 2.0, "orig": "oi gente", "trad": "hola gente",
                              "slot": 2.0, "estimativa": 0.67}
    assert d["frases"][1]["trad"] == "" and d["frases"][1]["estimativa"] == 0.0
    assert d["textos"] == [{"id": "t01", "orig": "Fecha o caderno", "trad": "Cierra el cuaderno", "arquivos": ["anim.html"]}]


def test_ler_traducao_idiomas(proj):
    with pytest.raises(ValueError, match="não encontrado"):
        folha.ler(proj, "traducao")
    _dub_fixture(proj, "es", textos=False)
    _dub_fixture(proj, "en", textos=False)
    with pytest.raises(ValueError, match="vários idiomas"):
        folha.ler(proj, "traducao")
    assert folha.ler(proj, "traducao", lang="en")["lang"] == "en"
    assert folha.ler(proj, "traducao", lang="en")["textos"] == []
    with pytest.raises(ValueError, match="idioma"):
        folha.ler(proj, "traducao", lang="../x")
    with pytest.raises(ValueError, match="não encontrado"):
        folha.ler(proj, "traducao", lang="pt")


def test_ler_traducao_so_tela(proj):
    """ad sem narração: só textos.json; lang="" (rota) = não informado; pasta fora de [a-z]{2} ignorada."""
    d = proj / "dub" / "es"
    d.mkdir(parents=True)
    (d / "textos.json").write_text(json.dumps({"textos": {
        "Fecha o caderno": {"id": "t01", "trad": "Cierra el cuaderno", "arquivos": ["anim.html"]},
        "sem id": {"trad": "x"}}}), encoding="utf-8")
    (proj / "dub" / "_tmp").mkdir()
    (proj / "dub" / "_tmp" / "textos.json").write_text("{}", encoding="utf-8")
    r = folha.ler(proj, "traducao", lang="")
    assert r["lang"] == "es" and r["frases"] == [] and [t["id"] for t in r["textos"]] == ["t01"]
