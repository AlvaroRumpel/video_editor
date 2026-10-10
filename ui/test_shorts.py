import json

import pytest

import shorts


def _ep_dir(tmp_path, durs=(10.0, 10.0, 10.0, 10.0), lista=None):
    p = tmp_path / "001-x"
    (p / "assets").mkdir(parents=True)
    (p / "pt" / "audio").mkdir(parents=True)
    (p / "assets" / "a.png").write_bytes(b"x")
    (p / "pesquisa.md").write_text("pesq", encoding="utf-8")
    cenas = [{"id": f"c0{i}", "texto": {"pt": f"Texto {i}."}, "fontes": ["F1"],
              "visual": {"tipo": "motion", "cena": {}}, "beats": [{"faz": "camera"}]} for i in range(1, len(durs) + 1)]
    ep = {"id": "001-x", "marca": "dark-historia", "titulo": {"pt": "T"}, "cenas": cenas,
          "vinheta_apos": "c01", "titulo_curto": {"pt": "V"}}
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    st, pal = {}, {}
    for c, d in zip(cenas, durs):
        (p / "pt" / "audio" / f"{c['id']}.mp3").write_bytes(b"mp3")
        st[c["id"]] = {"hash": "h", "voz": "v", "audio": f"pt/audio/{c['id']}.mp3", "dur": d}
        pal[c["id"]] = {"hash": "h", "palavras": []}
    (p / "pt" / "narracao.json").write_text(json.dumps(st), encoding="utf-8")
    (p / "pt" / "palavras.json").write_text(json.dumps(pal), encoding="utf-8")
    lista = lista if lista is not None else [{"id": "s01", "cenas": ["c01", "c02"],
                                              "titulo": {"pt": "Gancho"}, "descricao": {"pt": "Resumo."}}]
    (p / "shorts.json").write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
    return p


def test_validar_ok_e_duracao(tmp_path):
    p = _ep_dir(tmp_path)
    assert shorts.validar(p, "pt") == []
    st = json.loads((p / "pt" / "narracao.json").read_text(encoding="utf-8"))
    assert shorts.duracao(shorts.ler(p)[0], st) == pytest.approx(10 + 10 + 2 * 0.4 + shorts.TELA_FINAL_DUR)


def test_ler_exige_arquivo_e_lista(tmp_path):
    p = _ep_dir(tmp_path)
    (p / "shorts.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="shorts.json"):
        shorts.ler(p)
    (p / "shorts.json").unlink()
    with pytest.raises(ValueError, match="shorts.json"):
        shorts.ler(p)


@pytest.mark.parametrize("mut, sid, trecho", [
    (lambda l: l[0].update(id="short1"), "short1", "id inválido"),
    (lambda l: l.append(dict(l[0])), "s01", "id duplicado"),
    (lambda l: l[0].update(cenas=[]), "s01", "cenas"),
    (lambda l: l[0].update(cenas=["c01", "c77"]), "s01", "c77 não existe"),
    (lambda l: l[0].update(cenas=["c01", "c01"]), "s01", "cena repetida"),
    (lambda l: l[0]["titulo"].update(pt="  "), "s01", "titulo.pt"),
    (lambda l: l[0].pop("descricao"), "s01", "descricao.pt"),
    (lambda l: l[0].update(cenas=["c01", "c02", "c03", "c04", "c01x"]), "s01", "não existe"),
])
def test_validar_erros(tmp_path, mut, sid, trecho):
    lista = [{"id": "s01", "cenas": ["c01", "c02"], "titulo": {"pt": "Gancho"}, "descricao": {"pt": "Resumo."}}]
    mut(lista)
    p = _ep_dir(tmp_path, lista=lista)
    erros = shorts.validar(p, "pt")
    assert any(e["id"] == sid and trecho in e["motivo"] for e in erros), erros


def test_validar_recusa_mais_de_60s(tmp_path):
    p = _ep_dir(tmp_path, durs=(30.0, 30.0, 5.0, 5.0))
    erros = shorts.validar(p, "pt")
    assert any(e["id"] == "s01" and "60" in e["motivo"] and "s" in e["motivo"] for e in erros), erros


def test_validar_audio_ausente(tmp_path):
    p = _ep_dir(tmp_path)
    (p / "pt" / "audio" / "c02.mp3").unlink()
    erros = shorts.validar(p, "pt")
    assert any(e["id"] == "s01" and "c02" in e["motivo"] and "tts" in e["motivo"] for e in erros), erros


def test_montar_gera_mini_episodio_vertical(tmp_path):
    p = _ep_dir(tmp_path)
    d = shorts.montar(p, "s01", "pt")
    assert d == p / "shorts" / "s01"
    ep = json.loads((d / "episodio.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in ep["cenas"]] == ["c01", "c02"]
    assert ep["aspecto"] == "9:16" and ep["tela_final_dur"] == shorts.TELA_FINAL_DUR
    assert ep["titulo"] == {"pt": "Gancho"} and ep["marca"] == "dark-historia"
    assert "vinheta_apos" not in ep and "titulo_curto" not in ep
    st = json.loads((d / "pt" / "narracao.json").read_text(encoding="utf-8"))
    assert sorted(st) == ["c01", "c02"]
    assert sorted(json.loads((d / "pt" / "palavras.json").read_text(encoding="utf-8"))) == ["c01", "c02"]
    assert sorted(x.name for x in (d / "pt" / "audio").iterdir()) == ["c01.mp3", "c02.mp3"]
    assert (d / "assets" / "a.png").read_bytes() == b"x" and (d / "pesquisa.md").is_file()


def test_montar_mantem_mapa_e_atores(tmp_path):
    p = _ep_dir(tmp_path)
    ep = json.loads((p / "episodio.json").read_text(encoding="utf-8"))
    ep["mapa"], ep["atores"] = {"src": "assets/a.png", "pontos": {"x": [1, 2]}}, {"capitao": {"traje": "capitao"}}
    (p / "episodio.json").write_text(json.dumps(ep), encoding="utf-8")
    novo = json.loads((shorts.montar(p, "s01", "pt") / "episodio.json").read_text(encoding="utf-8"))
    assert novo["mapa"] == ep["mapa"] and novo["atores"] == ep["atores"]


def test_montar_idempotente_nao_apaga_saidas(tmp_path):
    p = _ep_dir(tmp_path)
    d = shorts.montar(p, "s01", "pt")
    (d / "pt" / "final.mp4").write_bytes(b"video")
    shorts.montar(p, "s01", "pt")
    assert (d / "pt" / "final.mp4").read_bytes() == b"video"


def test_montar_recusa_short_invalido_e_desconhecido(tmp_path):
    p = _ep_dir(tmp_path, durs=(30.0, 30.0, 5.0, 5.0))
    with pytest.raises(ValueError, match="60"):
        shorts.montar(p, "s01", "pt")
    with pytest.raises(ValueError, match="s09"):
        shorts.montar(p, "s09", "pt")


def test_renderizar_chama_narrado_no_projeto_derivado(tmp_path, monkeypatch):
    p = _ep_dir(tmp_path)
    chamadas = []
    monkeypatch.setattr(shorts.narrado, "render",
                        lambda proj, lang, rascunho=False, trilha=None: chamadas.append((proj, lang, rascunho, trilha))
                        or {"ok": True, "video": str(proj / lang / "final.mp4")})
    r = shorts.renderizar(p, "s01", "pt", rascunho=True, trilha="t.mp3")
    assert chamadas == [(p / "shorts" / "s01", "pt", True, "t.mp3")] and r["ok"]
