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
