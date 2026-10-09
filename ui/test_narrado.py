import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import audio
import budget
import motion
import narrado
import pipeline

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
                  "kenburns": True, "label": "Sibéria, 1908", "dur": 3.85, "dur_piso": True}     # 0 + 3.0 + 0.4 + 0.45
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
    ep["cenas"][0]["fontes"] = ["F9"]                       # erro de texto/fonte bloqueia TTS
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


def _tempos():
    return {"duracao": 6.4, "aspecto": "16:9", "cenas": [
        {"id": "c01", "ini": 0.0, "dur": 4.0, "min": 1, "saida": 0.6},
        {"id": "c02", "ini": 3.4, "dur": 3.0, "min": 1, "saida": 0}]}


def test_offsets_comecam_depois_da_transicao():
    assert narrado.offsets(_tempos()) == {"c01": 0.0, "c02": 4.0}


def test_srt_divide_texto_no_tempo_da_fala_utf8():
    ep = _ep()
    ep["cenas"][1]["texto"]["pt"] = ("Ninguém viu a explosão — nem os caçadores evenques, "
                                    "que só falariam dela anos depois, \"com medo\".")
    st = {"c01": {"dur": 2.0}, "c02": {"dur": 3.0}}
    s = narrado.srt(ep, "pt", _tempos(), st)
    blocos = [b for b in s.strip().split("\n\n")]
    assert blocos[0].startswith("1\n00:00:00,000 --> 00:00:02,000\nEm 1908")
    assert "\n00:00:04,000 --> " in blocos[1] and "caçadores" in s and "\"com medo\"" in s
    assert blocos[-1].split("\n")[1].endswith("00:00:07,000")             # 4.0 + 3.0
    assert all(len(l) <= 42 for b in blocos for l in b.split("\n")[2:])


def test_escrever_cenas_exige_tts_de_todas(tmp_path):
    p = _proj(tmp_path)
    (p / "pt").mkdir()
    (p / "pt" / "narracao.json").write_text(json.dumps({"c01": {"dur": 2.0, "audio": "pt/audio/c01.mp3"}}),
                                            encoding="utf-8")
    with pytest.raises(ValueError, match="rode tts.*c02"):
        narrado.escrever_cenas(p, "pt")


def _fake_render(proj, rascunho=False, lang=None, motion_dir=None):
    d = json.loads((proj / f"cenas.{lang}.json").read_text(encoding="utf-8"))
    ini, cenas = 0.0, []
    for k, c in enumerate(d["cenas"]):
        s = 0.6 if k < len(d["cenas"]) - 1 else 0
        cenas.append({"id": c["id"], "ini": round(ini, 3), "dur": c["dur"], "min": 1, "saida": s})
        ini += c["dur"] - s
    pipeline.atomic_write_json(proj / f"motion.{lang}" / "tempos.json",
                               {"duracao": round(ini, 3), "aspecto": "16:9", "cenas": cenas})
    v = proj / f"video{'_rascunho' if rascunho else ''}.{lang}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=1920x1080:r=30:d={ini:.3f}",
                    "-pix_fmt", "yuv420p", str(v)], check=True)
    return {"ok": True, "video": str(v), "duracao": round(ini, 3)}


@ffmpeg
def test_render_mixa_voz_e_gera_srt(tmp_path, root, mp3, monkeypatch):
    p = _proj(tmp_path)
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    monkeypatch.setattr(motion, "render", _fake_render)
    r = narrado.render(p, "pt")
    assert r["ok"] and Path(r["video"]) == p / "pt" / "final.mp4"
    tempos = json.loads((p / "motion.pt" / "tempos.json").read_text(encoding="utf-8"))
    assert abs(audio.duracao(Path(r["video"])) - tempos["duracao"]) < 0.1
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                              "-of", "json", r["video"]], capture_output=True, text=True, check=True).stdout
    s = json.loads(streams)["streams"]
    assert {x["codec_type"] for x in s} == {"video", "audio"}
    assert any(x.get("width") == 1920 and x.get("height") == 1080 for x in s)
    assert (p / "pt" / "final.srt").read_text(encoding="utf-8").startswith("1\n00:00:00,000")


@ffmpeg
def test_render_rascunho_nao_sobrescreve_final(tmp_path, root, mp3, monkeypatch):
    p = _proj(tmp_path)
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    monkeypatch.setattr(motion, "render", _fake_render)
    r = narrado.render(p, "pt", rascunho=True)
    assert Path(r["video"]).name == "final_rascunho.mp4" and not (p / "pt" / "final.mp4").exists()


def test_thumb_1280x720_com_acentos(tmp_path):
    ep = _ep()
    ep["thumb_texto"] = {"pt": "A explosão que ninguém viu — Sibéria, 1908"}
    p = _proj(tmp_path, ep)
    r = narrado.thumb(p, "pt", "assets/foto.png")
    im = Image.open(r["png"])
    assert im.size == (1280, 720) and len(r["linhas"]) <= 3


def test_thumb_imagem_fora_do_projeto(tmp_path):
    p = _proj(tmp_path)
    with pytest.raises(ValueError, match="imagem"):
        narrado.thumb(p, "pt", "../fora.png")


def test_descricao_fontes_creditos_e_ia(tmp_path):
    ep = _ep()
    ep["descricao"] = {"pt": "Em 1908, uma explosão derrubou uma floresta inteira."}
    ep["cenas"].append({"id": "c03", "texto": {"pt": "Imagine a cena."}, "fontes": ["F1"],
                        "visual": {"tipo": "ia", "src": "assets/ia.png", "prompt": "floresta caída"}})
    p = _proj(tmp_path, ep)
    Image.new("RGB", (1600, 1000)).save(p / "assets" / "ia.png")
    r = narrado.descricao(p, "pt")
    md = (p / "pt" / "descricao.md").read_text(encoding="utf-8")
    assert r == {"fontes": 1, "creditos": 1, "ia": True}
    assert md.startswith("Em 1908") and "[F1] Smithsonian Magazine — https://www.smithsonianmag.com/x" in md
    assert "Leonid Kulik, 1927 — https://commons.wikimedia.org/wiki/File:X.jpg (Public domain)" in md
    assert "Conteúdo alterado ou sintético" in md


def test_cli_validar_codigo_de_saida(tmp_path):
    ep = _ep()
    ep["cenas"][0]["visual"]["licenca"] = "ver página"
    p = _proj(tmp_path, ep)
    script = Path(narrado.__file__)
    r = subprocess.run([sys.executable, str(script), "validar", str(p)], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 1 and "licença não aceita" in r.stdout


# --- revisão final ---

@ffmpeg
def test_tts_antes_dos_visuais(tmp_path, root, mp3):
    ep = _ep()
    ep["cenas"][0]["visual"] = {"tipo": "arquivo"}          # só sugestão: imagem ainda não escolhida
    p = _proj(tmp_path, ep)
    r = narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    assert r["status"] == "ok" and r["geradas"] == ["c01", "c02"]


@ffmpeg
def test_render_recusa_audio_velho_apos_editar_texto(tmp_path, root, mp3):
    p = _proj(tmp_path)
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    ep = narrado.ler(p)
    ep["cenas"][1]["texto"]["pt"] = "Texto novo depois do gate."
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="rode tts.*c02"):
        narrado.escrever_cenas(p, "pt")


@ffmpeg
def test_render_revalida_visuais(tmp_path, root, mp3):
    p = _proj(tmp_path)
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    ep = narrado.ler(p)
    ep["cenas"][0]["visual"]["licenca"] = "CC BY-NC 4.0"
    (p / "episodio.json").write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="licença não aceita"):
        narrado.escrever_cenas(p, "pt")


@ffmpeg
def test_escrever_cenas_retrato_usa_contain(tmp_path, root, mp3):
    p = _proj(tmp_path)
    Image.new("RGB", (800, 1200), "gray").save(p / "assets" / "foto.png")      # jornal em pé
    narrado.tts(p, "pt", "voz1", root=root, _fetch=_fetch(mp3, []))
    d = json.loads(narrado.escrever_cenas(p, "pt").read_text(encoding="utf-8"))
    assert d["cenas"][0]["ajuste"] == "contain" and d["cenas"][0]["dur_piso"] is True
    Image.new("RGB", (1600, 1000), "gray").save(p / "assets" / "foto.png")     # paisagem
    d = json.loads(narrado.escrever_cenas(p, "pt").read_text(encoding="utf-8"))
    assert "ajuste" not in d["cenas"][0]


# --- Google Cloud TTS ---

VOZ_G = "pt-BR-Chirp3-HD-Charon"


def _fetch_g(mp3, chamadas):
    def f(key, url, body):
        chamadas.append((key, url, body))
        return mp3
    return f


@ffmpeg
def test_tts_google_envia_voz_registra_e_renderiza(tmp_path, root, mp3, monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "gkey")
    p, ch = _proj(tmp_path), []
    r = narrado.tts(p, "pt", VOZ_G, root=root, _fetch=_fetch_g(mp3, ch), provedor="google")
    assert r["status"] == "ok" and r["geradas"] == ["c01", "c02"]
    key, url, body = ch[0]
    assert key == "gkey" and url == narrado.GOOGLE_URL
    assert body["voice"] == {"languageCode": "pt-BR", "name": VOZ_G}
    assert body["input"] == {"text": "Em 1908, algo explodiu sobre a Sibéria."}
    assert body["audioConfig"]["audioEncoding"] == "MP3"
    assert narrado.estado(p, "pt")["c01"]["voz"] == f"google:{VOZ_G}"
    custos = [json.loads(l) for l in (p / "ui" / "costs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert custos[-1]["provedor"] == "google_tts" and custos[-1]["usd"] > 0
    narrado.escrever_cenas(p, "pt")                     # hash com provedor bate na hora do render


def test_tts_google_recusa_cena_acima_de_5000_bytes(tmp_path, root, mp3, monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "gkey")
    ep = _ep()
    ep["cenas"][0]["texto"]["pt"] = "ã" * 2600            # 2.600 caracteres, 5.200 bytes
    p, ch = _proj(tmp_path, ep), []
    r = narrado.tts(p, "pt", VOZ_G, root=root, _fetch=_fetch_g(mp3, ch), provedor="google")
    assert r["status"] == "invalido" and ch == []
    assert any(e["id"] == "c01" and "5000 bytes" in e["motivo"] for e in r["erros"])


@ffmpeg
def test_tts_trocar_provedor_regenera(tmp_path, root, mp3, monkeypatch):
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "gkey")
    p = _proj(tmp_path)
    narrado.tts(p, "pt", VOZ_G, root=root, _fetch=_fetch(mp3, []))
    r = narrado.tts(p, "pt", VOZ_G, root=root, _fetch=_fetch_g(mp3, []), provedor="google")
    assert r["geradas"] == ["c01", "c02"]


def test_tts_google_sem_chave(tmp_path, root, mp3, monkeypatch):
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    monkeypatch.setattr(narrado, "ENV_FILE", tmp_path / "nada.env")
    p = _proj(tmp_path)
    with pytest.raises(RuntimeError, match="GOOGLE_TTS_API_KEY"):
        narrado.tts(p, "pt", VOZ_G, root=root, _fetch=_fetch_g(mp3, []), provedor="google")


def test_tts_provedor_desconhecido(tmp_path, root):
    with pytest.raises(ValueError, match="provedor"):
        narrado.tts(_proj(tmp_path), "pt", "x", root=root, provedor="polly")


def test_fetch_google_usa_header_e_decodifica(monkeypatch):
    import base64
    import io
    visto = {}

    def urlopen(req, timeout):
        visto["req"] = req
        return io.BytesIO(json.dumps({"audioContent": base64.b64encode(b"ID3audio").decode()}).encode())
    monkeypatch.setattr(narrado.urllib.request, "urlopen", urlopen)
    out = narrado._fetch_google("gkey", narrado.GOOGLE_URL, {"input": {"text": "oi"}})
    req = visto["req"]
    assert out == b"ID3audio" and req.get_header("X-goog-api-key") == "gkey" and "gkey" not in req.full_url
