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


import budget


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def tts_root(root, monkeypatch):
    (root / "ui" / "precos.json").write_text(json.dumps({
        "elevenlabs_tts": {"unidade": "caractere", "usd": 0.0001, "creditos": 0}}), encoding="utf-8")
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    return root


def _fetch_ok(calls):
    def f(key, url, body):
        calls.append((url, body["text"]))
        return b"ID3fake-mp3-" + body["text"].encode("utf-8")
    return f


def _custos(proj):
    p = proj / "ui" / "costs.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_tts_gera_e_registra(tts_root):
    proj = _proj(tts_root)
    dublagem.frases(proj, "es", _words("oi gente", "tudo bem"))
    _set_trad(proj, {"f001": "hola gente", "f002": "todo bien"})
    calls = []
    r = dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok(calls))
    assert r["status"] == "ok" and r["geradas"] == ["f001", "f002"] and r["caracteres"] == 19
    assert calls[0][0] == "https://api.elevenlabs.io/v1/text-to-speech/VPAD?output_format=mp3_44100_128"
    d = _dub(proj)
    assert d["voz"]["voice_id"] == "VPAD"
    f = d["frases"][0]
    assert f["audio"] == "dub/es/f001.mp3" and f["estado"] == "gerada" and len(f["hash"]) == 40
    assert (proj / "dub" / "es" / "f001.mp3").read_bytes().startswith(b"ID3")
    c = _custos(proj)
    assert len(c) == 1 and c[0]["provedor"] == "elevenlabs_tts" and c[0]["unidades"] == 19


def test_tts_cache_e_troca_de_voz(tts_root):
    proj = _proj(tts_root)
    dublagem.frases(proj, "es", _words("oi gente", "tudo bem"))
    _set_trad(proj, {"f001": "hola gente", "f002": "todo bien"})
    dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok([]))
    calls = []
    assert dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok(calls))["geradas"] == []
    _set_trad(proj, {"f002": "todo muy bien"})
    assert dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok(calls))["geradas"] == ["f002"]
    (proj / "ui" / "state.json").write_text(json.dumps({"dub": {"voz": {"voice_id": "OUTRA", "nome": "o"}}}),
                                            encoding="utf-8")
    assert dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok(calls))["geradas"] == ["f001", "f002"]
    assert calls[-1][0].startswith("https://api.elevenlabs.io/v1/text-to-speech/OUTRA")


def test_tts_orcamento_negado(tts_root):
    proj = _proj(tts_root)
    dublagem.frases(proj, "es", _words("oi gente"))
    _set_trad(proj, {"f001": "x" * 6000})                        # 6000 × 0.0001 = 0.60 > aprovar_acima 0.5
    calls = []
    r = dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok(calls))
    assert r["status"] == "precisa_aprovacao" and r["caracteres"] == 6000 and calls == []
    assert _custos(proj) == [] and _dub(proj)["frases"][0]["audio"] is None


def test_tts_erro_no_meio(tts_root):
    proj = _proj(tts_root)
    dublagem.frases(proj, "es", _words("um", "dois", "tres"))
    _set_trad(proj, {"f001": "uno", "f002": "dos", "f003": "tres"})

    def falha_na_segunda(key, url, body):
        if body["text"] == "dos":
            raise RuntimeError("ElevenLabs HTTP 500")
        return b"ID3" + body["text"].encode()

    with pytest.raises(RuntimeError, match="1 frases"):
        dublagem.tts(proj, "es", root=tts_root, _fetch=falha_na_segunda)
    fs = _dub(proj)["frases"]
    assert fs[0]["estado"] == "gerada" and fs[1]["audio"] is None
    assert [c["unidades"] for c in _custos(proj)] == [3]


def test_tts_sem_voz(tts_root):
    proj = _proj(tts_root)
    (tts_root / "ui" / "vozes.json").write_text("{}", encoding="utf-8")
    dublagem.frases(proj, "es", _words("oi"))
    _set_trad(proj, {"f001": "hola"})
    with pytest.raises(ValueError, match="vozes.json"):
        dublagem.tts(proj, "es", root=tts_root, _fetch=_fetch_ok([]))


def _tom(path, dur):
    _ff("-f", "lavfi", "-i", f"sine=f=440:r=48000:d={dur}", "-ac", "1", str(path))


def test_encaixar_real(root):
    proj = _proj(root)
    dublagem.frases(proj, "es", _words("a b c d", "e f g h", "i j k l", gap=1.0))   # slots de 1.15 s
    d = _dub(proj)
    durs = {"f001": 0.8, "f002": 1.3, "f003": 2.0}                                # ≤1 · ~1.13× · ~1.74×
    for f in d["frases"]:
        _tom(proj / "dub" / "es" / f"{f['id']}.wav", durs[f["id"]])
        f["audio"] = f"dub/es/{f['id']}.wav"
        f["trad"] = "x"
    (proj / "dub" / "es" / "dublagem.json").write_text(json.dumps(d), encoding="utf-8")
    r = dublagem.encaixar(proj, "es", dur_total=6.0)
    assert r == {"encaixadas": ["f001"], "aceleradas": ["f002"], "estouradas": ["f003"]}
    import wave
    with wave.open(str(proj / "dub" / "es" / "voz.wav"), "rb") as w:
        assert w.getframerate() == 48000 and w.getnchannels() == 1
        assert abs(w.getnframes() / 48000 - 6.0) < 0.01
    fs = {f["id"]: f for f in _dub(proj)["frases"]}
    assert fs["f003"]["estado"] == "estoura" and fs["f002"]["estado"] == "encaixada"
    assert 1.0 < fs["f002"]["fator"] <= dublagem.MAX_FATOR
    assert not (proj / "dub" / "es" / "_encaixe").exists()


def test_mixar_real(root, tmp_path):
    proj = _proj(root)
    export = tmp_path / "final.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=f=300:r=48000:d=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(export))
    dublagem.frases(proj, "es", _words("oi gente"))
    _set_trad(proj, {"f001": "hola gente"})
    _tom(proj / "dub" / "es" / "voz.wav", 3)
    saida = tmp_path / "Export"
    r = dublagem.mixar(proj, "es", export, "Meu video", root=root, saida=saida)
    assert r["trilha"] is None
    for ext in ("mp4", "m4a", "srt"):
        assert (saida / f"Meu video - es.{ext}").exists()
    trilha = tmp_path / "t.wav"
    _tom(trilha, 5)
    r = dublagem.mixar(proj, "es", export, "Meu video", root=root, saida=saida, trilha=trilha)
    assert r["trilha"] == str(trilha)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                            str(saida / "Meu video - es.mp4")], capture_output=True, text=True).stdout.split()
    assert probe.count("video") == 1 and probe.count("audio") == 1


def test_mixar_sem_voz(root, tmp_path):
    dublagem.frases(_proj(root), "es", _words("oi"))
    with pytest.raises(ValueError, match="voz.wav"):
        dublagem.mixar(_proj(root), "es", tmp_path / "x.mp4", "n", root=root, saida=tmp_path)


def test_cli_tts_exit_codes(tts_root, monkeypatch):
    proj = _proj(tts_root)
    dublagem.frases(proj, "es", _words("oi"))
    _set_trad(proj, {"f001": "x" * 6000})
    r = _cli(tts_root, "tts", str(proj), "es")
    assert r.returncode == 2 and json.loads(r.stdout)["status"] == "precisa_aprovacao"
