import json
import subprocess
import sys
from pathlib import Path

import pytest

import dublagem
from test_pipeline import fake_root  # noqa: F401 — fixture reexport


@pytest.fixture
def root(fake_root):
    (fake_root / "ui").mkdir(exist_ok=True)
    (fake_root / "ui" / "glossario.json").write_text(json.dumps({
        "Anotus": "manter", "súmula": {"es": "súmula", "en": "binding precedent"}}), encoding="utf-8")
    (fake_root / "ui" / "vozes.json").write_text(json.dumps({
        "padrao": {"voice_id": "VPAD", "nome": "padrão"}, "anotus": {"voice_id": "VANO", "nome": "anotus"}}),
        encoding="utf-8")
    return fake_root


def _proj(root):
    return root / "edit-fake"


def _words(*frases, gap=1.0, dur=0.3):
    """palavras sintéticas na timeline do export: cada frase separada por `gap`."""
    out, t = [], 0.0
    for f in frases:
        for w in f.split():
            out.append({"t": round(t, 3), "e": round(t + dur - 0.05, 3), "w": w})
            t += dur
        t += gap
    return out


def _dub(proj, lang="es"):
    return json.loads((proj / "dub" / lang / "dublagem.json").read_text(encoding="utf-8"))


def _set_trad(proj, trads, lang="es"):
    d = _dub(proj, lang)
    for f in d["frases"]:
        if f["id"] in trads:
            f["trad"] = trads[f["id"]]
    (proj / "dub" / lang / "dublagem.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_frases_quebra_por_pausa_e_pontuacao(root):
    proj = _proj(root)
    r = dublagem.frases(proj, "es", _words("oi gente tudo bem.", "hoje vamos falar", "de súmula"))
    assert r == {"frases": 3, "preservadas": 0}
    d = _dub(proj)
    assert d["lang"] == "es" and [f["orig"] for f in d["frases"]] == ["oi gente tudo bem.", "hoje vamos falar", "de súmula"]
    f = d["frases"][0]
    assert f["id"] == "f001" and f["t_in"] == 0.0 and f["t_out"] == 1.15 and f["trad"] is None and f["estado"] == "nova"


def test_frases_quebra_longas(root):
    proj = _proj(root)
    longa = " ".join(f"p{i}" for i in range(60))          # 60 × 0.3 s = 18 s sem pausa
    dublagem.frases(proj, "es", _words(longa))
    fs = _dub(proj)["frases"]
    assert len(fs) == 2 and all(f["t_out"] - f["t_in"] <= dublagem.MAX_FRASE_S for f in fs)
    assert " ".join(f["orig"] for f in fs) == longa


def test_frases_preserva_trad(root):
    proj = _proj(root)
    ws = _words("oi gente", "tudo bem")
    dublagem.frases(proj, "es", ws)
    _set_trad(proj, {"f001": "hola gente", "f002": "todo bien"})
    ws2 = _words("oi gente", "tudo certo")
    r = dublagem.frases(proj, "es", ws2)
    fs = _dub(proj)["frases"]
    assert fs[0]["trad"] == "hola gente" and fs[1]["trad"] is None and r["preservadas"] == 1


def test_lang_invalido(root):
    with pytest.raises(ValueError, match="idioma"):
        dublagem.frases(_proj(root), "ES", _words("oi"))


def test_validar(root):
    proj = _proj(root)
    dublagem.frases(proj, "es", _words("o Anotus resume súmula", "tchau", "muito obrigado", dur=0.6))
    _set_trad(proj, {"f001": "el anotador resume la jurisprudencia",
                     "f003": "muchísimas gracias a todos por ver este video hasta el final de verdad"})
    r = dublagem.validar(proj, "es", root=root)
    assert not r["ok"]
    assert any("f002" in e and "sem tradução" in e for e in r["erros"])
    assert any("f001" in e and "Anotus" in e for e in r["erros"])
    assert any("f001" in e and "súmula" in e for e in r["erros"])
    assert [l["id"] for l in r["longas"]] == ["f003"]
    _set_trad(proj, {"f001": "Anotus resume la súmula", "f002": "chau", "f003": "muchas gracias"})
    assert dublagem.validar(proj, "es", root=root) == {"ok": True, "erros": [], "longas": []}


def test_validar_sem_frases(root):
    with pytest.raises(ValueError, match="frases"):
        dublagem.validar(_proj(root), "es", root=root)


def test_voz_resolucao(root):
    proj = _proj(root)
    assert dublagem.voz(proj, root=root)["voice_id"] == "VPAD"
    marca = root / "edit" / "shorts" / "anotus" / "ad1"
    (marca / "ui").mkdir(parents=True)
    assert dublagem.voz(marca, root=root)["voice_id"] == "VANO"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "state.json").write_text(json.dumps({"dub": {"voz": {"voice_id": "VPROJ", "nome": "x"}}}),
                                            encoding="utf-8")
    assert dublagem.voz(proj, root=root)["voice_id"] == "VPROJ"
    (root / "ui" / "vozes.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="vozes.json"):
        dublagem.voz(root / "edit-raw", root=root)


def test_srt(root):
    proj = _proj(root)
    dublagem.frases(proj, "es", _words("oi gente", "tudo bem"))
    _set_trad(proj, {"f001": "hola a todos los que están viendo este video que es muy largo de verdad",
                     "f002": None})
    s = dublagem.srt(proj, "es")
    blocos = [b for b in s.strip().split("\n\n") if b]
    assert blocos[0].startswith("1\n00:00:00,000 --> ")
    assert all(len(l) <= 42 for b in blocos for l in b.split("\n")[2:])
    assert all(len(b.split("\n")[2:]) <= 2 for b in blocos)
    assert blocos[-1].split("\n")[1].endswith("00:00:00,550")   # f002 sem tradução não entra


def test_words(root):
    proj = _proj(root)
    dublagem.frases(proj, "es", _words("oi gente"))
    _set_trad(proj, {"f001": "hola gente"})
    w = dublagem.words(proj, "es")
    assert [x["w"] for x in w] == ["hola", "gente"]
    assert w[0]["t"] == 0.0 and w[-1]["e"] == 0.55
    assert json.loads((proj / "dub" / "es" / "words.json").read_text(encoding="utf-8")) == w


def test_edl_troca_overlay_localizado(root):
    proj = _proj(root)
    edl = json.loads((proj / "edl.json").read_text(encoding="utf-8"))
    edl["overlays"] = [{"file": "animations/remotion/out/A.mov", "start_in_output": 1, "duration": 2},
                       {"file": "animations/remotion/out/B.mov", "start_in_output": 4, "duration": 2}]
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    (proj / "animations" / "remotion" / "out_es").mkdir(parents=True)
    (proj / "animations" / "remotion" / "out_es" / "A.mov").write_bytes(b"x")
    r = dublagem.edl(proj, "es")
    assert len(r["trocados"]) == 1 and len(r["mantidos"]) == 1
    e = json.loads((proj / "dub" / "es" / "edl.json").read_text(encoding="utf-8"))
    assert e["overlays"][0]["file"] == str((proj / "animations/remotion/out_es/A.mov").resolve())
    assert e["overlays"][1]["file"] == str((proj / "animations/remotion/out/B.mov").resolve())


def test_edl_caminhos_absolutos(root):
    proj = _proj(root)
    edl = json.loads((proj / "edl.json").read_text(encoding="utf-8"))
    edl["sources"] = {"MAIN": "../bruto/fake.mkv"}
    edl["subtitles"] = "master.srt"
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    dublagem.edl(proj, "es")
    e = json.loads((proj / "dub" / "es" / "edl.json").read_text(encoding="utf-8"))
    assert Path(e["sources"]["MAIN"]).is_absolute() and e["sources"]["MAIN"] == str((proj / "../bruto/fake.mkv").resolve())
    assert e["subtitles"] == str((proj / "master.srt").resolve())


def _cli(root, *a):
    return subprocess.run([sys.executable, str(Path(dublagem.__file__)), "--root", str(root), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_frases_validar(root, tmp_path):
    proj = _proj(root)
    wp = tmp_path / "w.json"
    wp.write_text(json.dumps(_words("oi gente")), encoding="utf-8")
    r = _cli(root, "frases", str(proj), "es", "--words", str(wp))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["frases"] == 1
    r = _cli(root, "validar", str(proj), "es")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False
    assert _cli(root, "frases", str(proj), "XX", "--words", str(wp)).returncode == 1
