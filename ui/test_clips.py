import json
import shutil
import subprocess
from pathlib import Path
import pytest
import clips


def _w(text, start, end, type_="word"):
    return {"text": text, "start": start, "end": end, "type": type_}


def _tr(frases_, t0=0.0, gap=1.0, dur_palavra=0.25):
    """transcript sintético: cada frase vira palavras; gap entre frases."""
    words, t = [], t0
    for f in frases_:
        for w in f.split():
            words.append(_w(w, round(t, 3), round(t + dur_palavra - 0.05, 3)))
            words.append(_w(" ", round(t + dur_palavra - 0.05, 3), round(t + dur_palavra, 3), "spacing"))
            t += dur_palavra
        t += gap
    return {"words": words, "audio_duration_secs": t}


def test_words_out_drift():
    tr = _tr(["um dois tres", "quatro cinco"], gap=2.0)        # 2ª frase começa em 0.75+2.0 = 2.75
    edl = {"ranges": [{"start": 0.0, "end": 0.8}, {"start": 2.7, "end": 4.0}]}
    out = clips.words_out(edl, tr, real=[0.9, 1.3])          # 1º segmento codificou 0.9 (drift +0.1)
    assert [o["w"] for o in out] == ["um", "dois", "tres", "quatro", "cinco"]
    assert out[3]["t"] == round(2.75 - 2.7 + 0.9, 3)         # deslocado pela duração REAL
    assert all(o["w"] != " " for o in out)                    # spacing ignorado


def test_frases_pausa_e_pontuacao():
    tr = _tr(["eu criei um SaaS.", "foi zero assinantes", "e dai"], gap=0.3)
    words = [{"t": w["start"], "e": w["end"], "w": w["text"]} for w in tr["words"] if w["type"] == "word"]
    fr = clips.frases(words, pausa=0.6)
    assert [f["texto"] for f in fr] == ["eu criei um SaaS.", "foi zero assinantes e dai"]   # '.' quebra; gap 0.3 não
    tr2 = _tr(["um dois", "tres quatro"], gap=0.7)
    words2 = [{"t": w["start"], "e": w["end"], "w": w["text"]} for w in tr2["words"] if w["type"] == "word"]
    assert len(clips.frases(words2)) == 2                                                   # pausa 0.7 quebra


def _words_from(tr):
    return [{"t": w["start"], "e": w["end"], "w": w["text"]} for w in tr["words"] if w["type"] == "word"]


def test_candidatos_acha_trecho_forte():
    enchimento = ["isso aqui é um detalhe menor que a gente vê depois"] * 6          # ~16 s, dêitico, sem gancho
    forte = ["Você sabe por que eu perdi 10 mil reais em duas semanas?"] + \
            ["a resposta é simples e eu vou explicar agora com calma"] * 7 + ["e foi assim que eu aprendi."]
    tr = _tr(enchimento + forte + enchimento, gap=0.9)
    words = _words_from(tr)
    c = clips.candidatos(words, n=5)
    assert c, "nenhum candidato"
    top = c[0]
    assert top["texto"].startswith("Você sabe por que")
    assert top["texto"].endswith("aprendi.")
    assert 25 <= top["t_out"] - top["t_in"] <= 60
    assert "pergunta" in top["motivos"] and "número" in top["motivos"]
    assert all(25 - 0.2 <= x["t_out"] - x["t_in"] <= 60 + 0.2 for x in c)
    # bordas com padding sentadas em palavra
    assert any(abs(top["t_in"] + clips.PAD_IN - w["t"]) < 1e-6 for w in words)
    assert any(abs(top["t_out"] - clips.PAD_OUT - w["e"]) < 1e-6 for w in words)


def test_candidatos_dedupe_e_curto():
    tr = _tr(["uma frase curta só."], gap=1.0)
    assert clips.candidatos(_words_from(tr)) == []
    tr2 = _tr(["frase de teste numero um aqui vai."] * 12, gap=0.7)        # várias janelas sobrepostas
    c = clips.candidatos(_words_from(tr2), n=20)
    for a in c:
        for b in c:
            if a is b: continue
            inter = max(0, min(a["t_out"], b["t_out"]) - max(a["t_in"], b["t_in"]))
            assert inter / min(a["t_out"] - a["t_in"], b["t_out"] - b["t_in"]) <= 0.6 + 1e-9


def test_candidatos_espalha_no_tempo():
    bloco = lambda t0: _words_from(_tr(["uma frase de teste sem gancho nenhum vai"], t0=t0))
    words = bloco(0.0) + bloco(60.0) + bloco(660.0)
    c = clips.candidatos(words, n=2, min_s=1, max_s=20)
    assert [round(x["t_in"]) for x in c] == [0, 660]
    assert not any("perto" in m for m in c[0]["motivos"])


def test_eu_sozinho_nao_e_gancho():
    words = _words_from(_tr(["eu fiz meu trabalho comigo mesmo hoje"]))
    _, motivos = clips._score(words, 0, len(words) - 1, 1.0)
    assert "primeira pessoa" not in motivos


def _clips(words, **over):
    """clips.json mínimo com 1 clipe aprovado de ~30 s sentado em palavras."""
    t_in = words[0]["t"] - clips.PAD_IN
    fim = next(w for w in words if w["e"] - words[0]["t"] >= 30)
    base = {"fonte": "Export/x.mp4", "meta_n": 3, "x_padrao": 636, "clipes": [
        {"id": "c01", "slug": "um", "nota": 5, "gancho": "g", "ranges": [{"t_in": t_in, "t_out": fim["e"] + clips.PAD_OUT, "beat": "HOOK"}],
         "x": 636, "legenda": False, "plataformas": ["shorts"], "status": "aprovado"}]}
    base["clipes"][0].update(over)
    return base


@pytest.fixture
def words60():
    return _words_from(_tr(["palavra " * 9 + "fim."] * 12, gap=0.5))     # ~60 s


def test_validar_ok(words60):
    assert clips.validar(_clips(words60), words60)["ok"]


def test_validar_borda_e_duracao(words60):
    c = _clips(words60); c["clipes"][0]["ranges"][0]["t_in"] += 0.2          # fora da palavra
    r = clips.validar(c, words60); assert not r["ok"] and any("c01" in e and "palavra" in e for e in r["erros"])
    c = _clips(words60)
    c["clipes"][0]["ranges"][0]["t_out"] = c["clipes"][0]["ranges"][0]["t_in"] + 0.0 + 70 + clips.PAD_IN + clips.PAD_OUT
    c["clipes"][0]["plataformas"] = ["shorts", "reels"]
    r = clips.validar(c, words60)
    assert any("shorts" in e and "60" in e for e in r["erros"]) and not any("reels" in e for e in r["erros"])


def test_validar_sobreposicao_duplicata_x_meta(words60):
    c = _clips(words60)
    r0 = c["clipes"][0]["ranges"][0]
    c["clipes"][0]["ranges"].append({"t_in": r0["t_in"] + 5, "t_out": r0["t_out"], "beat": "X"})
    assert any("sobrep" in e for e in clips.validar(c, words60)["erros"])
    c = _clips(words60)
    dup = json.loads(json.dumps(c["clipes"][0])); dup["id"] = "c02"; dup["slug"] = "dois"
    c["clipes"].append(dup)
    assert any("comum" in e for e in clips.validar(c, words60)["erros"])
    c = _clips(words60, x=637)
    assert any("x" in e and "par" in e for e in clips.validar(c, words60)["erros"])
    c = _clips(words60); c["meta_n"] = 0
    for k in range(3):
        d = json.loads(json.dumps(c["clipes"][0])); d["id"] = f"c0{k + 2}"; d["slug"] = f"s{k}"
        d["ranges"][0]["t_in"] += 0.0; c["clipes"].append(d)
    assert any("meta" in e for e in clips.validar(c, words60)["erros"])


def test_validar_sem_ranges_ou_invertido(words60):
    c = _clips(words60, ranges=[])
    r = clips.validar(c, words60); assert not r["ok"] and any("c01" in e and "ranges" in e for e in r["erros"])
    c = _clips(words60); r0 = c["clipes"][0]["ranges"][0]; r0["t_in"], r0["t_out"] = r0["t_out"], r0["t_in"]
    r = clips.validar(c, words60); assert any("c01" in e and "t_out" in e for e in r["erros"])


@pytest.mark.parametrize("rs", [[{"t_in": "x"}], [None], [{"t_in": 1}]])
def test_validar_range_malformado_nao_levanta(words60, rs):
    r = clips.validar(_clips(words60, ranges=rs, nota="alta"), words60)
    assert not r["ok"] and any("c01" in e for e in r["erros"])


def test_edl_gera_dirs_srt_md(tmp_path, words60):
    proj = tmp_path / "proj"; proj.mkdir()
    export = tmp_path / "Export" / "x - horizontal.mp4"; export.parent.mkdir(); export.write_bytes(b"0")
    c = _clips(words60, plataformas=["shorts", "reels", "tiktok"], legenda=False)
    r = clips.edl(c, proj, export, words60)
    assert sorted(r["gerados"]) == ["clips/01-um-reels", "clips/01-um-shorts", "clips/01-um-tiktok"]
    e = json.loads((proj / "clips" / "01-um-shorts" / "edl.json").read_text(encoding="utf-8"))
    assert e["grade"] == "crop=608:1080:636:0,scale=1080:1920:flags=lanczos"
    assert e["sources"]["EXPORT"] == str(export.resolve()) and e["ranges"][0]["quote"].startswith("palavra")
    assert "subtitles" not in e
    et = json.loads((proj / "clips" / "01-um-tiktok" / "edl.json").read_text(encoding="utf-8"))
    assert et["subtitles"] == "legenda.srt" and (proj / "clips" / "01-um-tiktok" / "legenda.srt").exists()
    srt = (proj / "clips" / "01-um-tiktok" / "legenda.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,") and "-->" in srt
    md = (proj / "clips.md").read_text(encoding="utf-8")
    assert "| c01 |" in md and (proj / "clips" / "clips.md").exists()


def test_edl_legenda_opcional_e_so_aprovados(tmp_path, words60):
    proj = tmp_path / "p"; proj.mkdir(); export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    c = _clips(words60, legenda=True, plataformas=["shorts"])
    vet = json.loads(json.dumps(c["clipes"][0])); vet.update(id="c02", slug="dois", status="vetado")
    c["clipes"].append(vet)
    r = clips.edl(c, proj, export, words60)
    assert r["gerados"] == ["clips/01-um-shorts"]
    assert (proj / "clips" / "01-um-shorts" / "legenda.srt").exists()


def test_srt_clipe_tempo_relativo(words60):
    c = _clips(words60)
    c["clipes"][0]["ranges"] = [{"t_in": 30.0 - clips.PAD_IN, "t_out": 40.0, "beat": "A"},
                                {"t_in": 0.0, "t_out": 5.0, "beat": "B"}]
    # ajustar bordas para palavras reais
    w30 = min(words60, key=lambda w: abs(w["t"] - 30)); w40 = min(words60, key=lambda w: abs(w["e"] - 40))
    w0 = words60[0]; w5 = min(words60, key=lambda w: abs(w["e"] - 5))
    c["clipes"][0]["ranges"] = [{"t_in": w30["t"] - clips.PAD_IN, "t_out": w40["e"] + clips.PAD_OUT, "beat": "A"},
                                {"t_in": w0["t"] - clips.PAD_IN, "t_out": w5["e"] + clips.PAD_OUT, "beat": "B"}]
    srt = clips.srt_clipe(c["clipes"][0], words60)
    blocos = srt.strip().split("\n\n")
    assert blocos[0].split("\n")[1].startswith("00:00:00,0")            # 1º cue começa em ~0 (relativo ao clipe)
    ultimo = blocos[-1].split("\n")[1].split(" --> ")[1]
    assert ultimo < "00:00:16,000"                                        # ~10 s + ~5 s


import sys
pytest_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or not clips.RENDER.exists(), reason="sem ffmpeg/render.py")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest_ffmpeg
def test_render_real_preview(tmp_path, words60):
    export = tmp_path / "Export" / "x - horizontal.mp4"; export.parent.mkdir()
    _ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=60:d=62", "-f", "lavfi", "-i", "sine=f=440:r=48000:d=62",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(export))
    proj = tmp_path / "proj"; proj.mkdir()
    c = _clips(words60, plataformas=["shorts"])
    clips.edl(c, proj, export, words60)
    r = clips.render(c, proj, tmp_path / "out", preview=True)
    assert r["erros"] == [] and r["renderizados"] == ["01-um-shorts.mp4"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(tmp_path / "out" / "01-um-shorts.mp4")], capture_output=True, text=True).stdout.strip()
    assert probe == "1080,1920"


def test_render_erro_isolado(tmp_path, words60):
    proj = tmp_path / "p"; proj.mkdir(); export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    c = _clips(words60, plataformas=["shorts", "reels"])
    c["clipes"][0]["ranges"][0]["t_out"] = words60[-1]["e"] + clips.PAD_OUT       # ~60 s: ok shorts e reels
    clips.edl(c, proj, export, words60)
    chamadas = []
    def run(cmd):
        chamadas.append(cmd)
        class R: returncode = 1 if "reels" in " ".join(cmd) else 0; stderr = "boom"
        return R()
    r = clips.render(c, proj, tmp_path / "out", _run=run)
    assert r["renderizados"] == ["01-um-shorts.mp4"] and any("reels" in e and "boom" in e for e in r["erros"])
    assert len(chamadas) == 2 and all("--preview" not in cmd for cmd in chamadas)


def test_cli(tmp_path, words60):
    exe = [sys.executable, str(Path(clips.__file__))]
    wo = tmp_path / "w.json"; wo.write_text(json.dumps(words60), encoding="utf-8")
    cj = tmp_path / "c.json"; cj.write_text(json.dumps(_clips(words60, x=637)), encoding="utf-8")
    r = subprocess.run([*exe, "validar", str(cj), str(wo)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False
    r = subprocess.run([*exe, "candidatos", str(wo), str(tmp_path / "cand.json"), "--n", "3"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and isinstance(json.loads(r.stdout), list)
    r = subprocess.run([*exe, "validar", str(tmp_path / "nao.json"), str(wo)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "erro" in json.loads(r.stdout)


def test_validar_plataformas_id_status(words60):
    for v in (None, [], "shorts"):
        c = _clips(words60, plataformas=v)
        assert any("plataformas" in e for e in clips.validar(c, words60)["erros"])
    c = _clips(words60, status="ok")
    assert any("status inválido" in e for e in clips.validar(c, words60)["erros"])
    c = _clips(words60); c["clipes"].append(dict(c["clipes"][0], slug="dois", status="vetado"))
    assert any("id repetido" in e for e in clips.validar(c, words60)["erros"])


def test_zero_aprovados(tmp_path, words60):
    proj = tmp_path / "p"; proj.mkdir(); export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    c = _clips(words60, status="proposto")
    assert clips.edl(c, proj, export, words60)["avisos"]
    r = clips.render(c, proj, tmp_path / "out", _run=lambda cmd: pytest.fail("não deve rodar"))
    assert r["renderizados"] == [] and "0 clipes aprovados" in r["erros"][0]
    with pytest.raises(FileNotFoundError):
        clips.edl(c, proj, tmp_path / "nao.mp4", words60)


@pytest.mark.parametrize("preview", [False, True])
def test_render_remove_obsoletos(tmp_path, words60, preview):
    proj = tmp_path / "p"; proj.mkdir(); export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    c = _clips(words60); out = tmp_path / "out"; out.mkdir(); (out / "stale.mp4").write_bytes(b"0"); (out / "99-velho-shorts.mp4").write_bytes(b"0")
    clips.edl(c, proj, export, words60)
    class R: returncode = 0; stderr = ""
    r = clips.render(c, proj, out, preview=preview, _run=lambda cmd: R())
    assert (out / "stale.mp4").exists()
    assert (out / "99-velho-shorts.mp4").exists() == preview
    assert r["removidos"] == ([] if preview else ["99-velho-shorts.mp4"])


def test_srt_fecha_antes_de_1_2s():
    ws = [{"t": 0.0, "e": 0.5, "w": "a"}, {"t": 0.6, "e": 1.1, "w": "b"}, {"t": 1.2, "e": 1.7, "w": "c"}]
    c = {"ranges": [{"t_in": 0.0, "t_out": 2.0}]}
    srt = clips.srt_clipe(c, ws)
    assert "\na b\n" in srt and "\nc\n" in srt


def test_edl_pasta_por_idioma(tmp_path, words60):
    proj = tmp_path / "proj"; proj.mkdir()
    export = tmp_path / "x - es.mp4"; export.write_bytes(b"0")
    c = _clips(words60, plataformas=["shorts"], legenda=True)
    r = clips.edl(c, proj, export, words60, pasta="clips/es")
    assert r["gerados"] == ["clips/es/01-um-shorts"]
    assert (proj / "clips" / "es" / "01-um-shorts" / "edl.json").exists()
    assert (proj / "clips" / "es" / "01-um-shorts" / "legenda.srt").exists()
    assert not (proj / "clips" / "01-um-shorts").exists()


def test_render_pasta_por_idioma(tmp_path, words60):
    proj = tmp_path / "p"; proj.mkdir(); export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    c = _clips(words60, plataformas=["shorts"])
    clips.edl(c, proj, export, words60, pasta="clips/es")
    vistos = []

    def run(cmd):
        vistos.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    r = clips.render(c, proj, tmp_path / "out", preview=True, _run=run, pasta="clips/es")
    assert r["erros"] == [] and str(proj / "clips" / "es" / "01-um-shorts" / "edl.json") in vistos[0]


def test_cli_edl_lang(tmp_path, words60):
    import sys
    proj = tmp_path / "p"; proj.mkdir()
    (proj / "dub" / "es").mkdir(parents=True)
    (proj / "dub" / "es" / "words.json").write_text(json.dumps(words60), encoding="utf-8")
    export = tmp_path / "e.mp4"; export.write_bytes(b"0")
    cj = tmp_path / "clips.json"; cj.write_text(json.dumps(_clips(words60, plataformas=["shorts"])), encoding="utf-8")
    r = subprocess.run([sys.executable, str(Path(clips.__file__)), "edl", str(cj), str(proj), str(export), "--lang", "es"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["gerados"] == ["clips/es/01-um-shorts"]


def test_cli_lang_invalido(tmp_path, words60):
    import sys
    cj = tmp_path / "clips.json"; cj.write_text("{}", encoding="utf-8")
    r = subprocess.run([sys.executable, str(Path(clips.__file__)), "edl", str(cj), str(tmp_path), str(tmp_path / "e.mp4"), "--lang", "../x"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "ValueError" in r.stdout
