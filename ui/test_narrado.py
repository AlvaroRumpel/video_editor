import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import budget
import motion
import narrado

ACHADO = ("- [F1] Explosão de 1908 derrubou 80 milhões de árvores — fonte: Smithsonian Magazine (secundaria)"
          " — https://www.smithsonianmag.com/x — acesso 2026-10-08\n  > trecho\n")


def _ep():
    return {"id": "001-teste", "marca": "dark-historia", "titulo": {"pt": "O mistério de Tunguska"},
            "cenas": [
                {"id": "c01", "texto": {"pt": "Em 1908, algo explodiu sobre a Sibéria."}, "fontes": ["F1"],
                 "visual": {"tipo": "arquivo", "src": "assets/foto.png",
                            "fonte_url": "https://commons.wikimedia.org/wiki/File:X.jpg",
                            "licenca": "Public domain", "credito": "Leonid Kulik, 1927"},
                 "overlay": {"pt": "Sibéria, 1908"}},
                {"id": "c02", "texto": {"pt": "Ninguém viu a explosão de perto."}, "fontes": [],
                 "visual": {"tipo": "motion", "cena": {"tipo": "frase", "fundo": "escuro",
                                                      "linhas": [{"t": {"pt": "Ninguém viu."}, "estilo": "punch"}]}}}]}


def _proj(tmp_path, ep=None):
    p = tmp_path / "001-teste"
    (p / "assets").mkdir(parents=True)
    Image.new("RGB", (1600, 1000), "gray").save(p / "assets" / "foto.png")
    (p / "pesquisa.md").write_text("## Achados\n\n" + ACHADO, encoding="utf-8")
    (p / "episodio.json").write_text(json.dumps(ep or _ep(), ensure_ascii=False), encoding="utf-8")
    return p


def test_validar_ok(tmp_path):
    p = _proj(tmp_path)
    assert narrado.validar(narrado.ler(p), p, "pt") == []


@pytest.mark.parametrize("s, ok", [
    ("Public domain", True), ("PD-US", True), ("CC0", True), ("CC BY 2.0", True), ("CC BY-SA 4.0", True),
    ("http://creativecommons.org/publicdomain/mark/1.0/", True),
    ("https://creativecommons.org/licenses/by-sa/4.0/", True),
    ("CC BY-NC 4.0", False), ("CC BY-ND 2.0", False),
    ("https://creativecommons.org/licenses/by-nc/4.0/", False), ("ver página", False), ("", False), (None, False)])
def test_licenca_ok(s, ok):
    assert narrado.licenca_ok(s) is ok


@pytest.mark.parametrize("mut, cid, trecho", [
    (lambda e: e["cenas"][0].update(id="cena1"), "#0", "id inválido"),
    (lambda e: e["cenas"][1].update(id="c01"), "c01", "id duplicado"),
    (lambda e: e["cenas"][0]["texto"].update(pt="  "), "c01", "falta texto.pt"),
    (lambda e: e["cenas"][0]["texto"].update(pt="a" * 5001), "c01", "5000"),
    (lambda e: e["cenas"][0].update(fontes=["F9"]), "c01", "[F9] não existe"),
    (lambda e: e["cenas"][0].pop("fontes"), "c01", "fontes precisa ser lista"),
    (lambda e: e["cenas"][0]["visual"].update(licenca="CC BY-NC 4.0"), "c01", "licença não aceita"),
    (lambda e: e["cenas"][0]["visual"].update(src="assets/nada.png"), "c01", "src não encontrado"),
    (lambda e: e["cenas"][0]["visual"].pop("credito"), "c01", "fonte_url e credito"),
    (lambda e: e["cenas"][1]["visual"].pop("cena"), "c02", "motion precisa de cena"),
    (lambda e: e["cenas"][1]["visual"].update(tipo="video"), "c02", "visual.tipo inválido"),
    (lambda e: e.pop("marca"), "raiz", "falta marca"),
    (lambda e: e["titulo"].pop("pt"), "raiz", "falta titulo.pt"),
])
def test_validar_erros(tmp_path, mut, cid, trecho):
    ep = _ep()
    mut(ep)
    p = _proj(tmp_path, ep)
    erros = narrado.validar(narrado.ler(p), p, "pt")
    assert any(e["id"] == cid and trecho in e["motivo"] for e in erros), erros


def test_validar_sem_pesquisa(tmp_path):
    p = _proj(tmp_path)
    (p / "pesquisa.md").unlink()
    assert any(e["motivo"] == "falta pesquisa.md" for e in narrado.validar(narrado.ler(p), p, "pt"))


def test_ler_ausente(tmp_path):
    with pytest.raises(ValueError, match="episodio.json"):
        narrado.ler(tmp_path)


def test_loc():
    v = {"tipo": "frase", "linhas": [{"t": {"pt": "Oi", "en": "Hi"}, "em": 1.0}]}
    assert narrado._loc(v, "en") == {"tipo": "frase", "linhas": [{"t": "Hi", "em": 1.0}]}
    assert narrado._loc({"pt": "x"}, "en") is None


def test_cenas_motion_duracoes_e_tipos():
    tema = motion.carregar_tema("dark-historia")          # fade 0.45
    d = narrado.cenas_motion(_ep(), "pt", {"c01": 3.0, "c02": 2.0}, tema)
    assert d["marca"] == "dark-historia" and d["aspecto"] == "16:9"
    c1, c2 = d["cenas"]
    assert c1 == {"id": "c01", "tipo": "tela", "arquivo": "assets/foto.png", "moldura": "nenhuma",
                  "kenburns": True, "label": "Sibéria, 1908", "dur": 3.85}     # 0 + 3.0 + 0.4 + 0.45
    assert c2["tipo"] == "frase" and c2["linhas"][0]["t"] == "Ninguém viu."
    assert c2["dur"] == 2.85                                                    # 0.45 + 2.0 + 0.4 + 0


def test_cenas_motion_valida_no_kit(tmp_path):
    p = _proj(tmp_path)
    d = narrado.cenas_motion(narrado.ler(p), "pt", {"c01": 3.0, "c02": 2.0}, motion.carregar_tema("dark-historia"))
    assert motion.validar(d, p, "pt") == []


ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


@pytest.fixture(scope="module")
def mp3(tmp_path_factory):
    p = tmp_path_factory.mktemp("a") / "s.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1.5",
                    "-c:a", "libmp3lame", str(p)], check=True)
    return p.read_bytes()


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "ve"
    (r / "ui").mkdir(parents=True)
    shutil.copy(Path(narrado.__file__).parent / "precos.json", r / "ui" / "precos.json")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "teste")
    monkeypatch.setattr(budget, "saldo_elevenlabs", lambda root, **k: {"usados": 0, "limite": 10**6,
                                                                        "restante": 10**6, "reset_ts": 0})
    return r


def _fetch(mp3, chamadas):
    def f(key, url, body):
        chamadas.append(body["text"])
        return mp3
    return f


@ffmpeg
def test_tts_gera_cacheia_e_registra(tmp_path, root, mp3):
    p, ch = _proj(tmp_path), []
    r = narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))
    assert r["status"] == "ok" and r["geradas"] == ["c01", "c02"] and len(ch) == 2
    st = narrado.estado(p, "pt")
    assert st["c01"]["audio"] == "pt/audio/c01.mp3" and abs(st["c01"]["dur"] - 1.5) < 0.1
    assert budget.gasto_projeto(p)["creditos"] == r["caracteres"]
    assert narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))["geradas"] == []   # cache
    assert len(ch) == 2


@ffmpeg
def test_tts_regenera_so_a_cena_editada(tmp_path, root, mp3):
    p, ch = _proj(tmp_path), []
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))
    ep = narrado.ler(p)
    ep["cenas"][1]["texto"]["pt"] = "Ninguém, de fato, viu a explosão."
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    r = narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))
    assert r["geradas"] == ["c02"] and ch[-1] == "Ninguém, de fato, viu a explosão."


def test_tts_invalido_nao_gasta(tmp_path, root, mp3):
    ep = _ep()
    ep["cenas"][0]["visual"]["licenca"] = "CC BY-NC 4.0"
    p, ch = _proj(tmp_path, ep), []
    r = narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))
    assert r["status"] == "invalido" and ch == []


def test_tts_orcamento_bloqueado_nao_gasta(tmp_path, root, mp3, monkeypatch):
    p, ch = _proj(tmp_path), []
    monkeypatch.setattr(budget, "autorizar", lambda *a, **k: {"status": "bloqueado", "motivo": "teto"})
    r = narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, ch))
    assert r["status"] == "bloqueado" and ch == []


@ffmpeg
def test_tts_falha_no_meio_registra_o_gasto(tmp_path, root, mp3):
    p = _proj(tmp_path)
    n = []

    def f(key, url, body):
        n.append(1)
        if len(n) == 2:
            raise RuntimeError("ElevenLabs HTTP 500")
        return mp3
    with pytest.raises(RuntimeError, match="após 1 cenas"):
        narrado.tts(p, "pt", "voz1", root=root, _fetch=f)
    assert list(narrado.estado(p, "pt")) == ["c01"] and budget.gasto_projeto(p)["creditos"] > 0
