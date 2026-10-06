import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
import audio

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def voz(tmp_path) -> Path:
    """8 s: tom 1 kHz ligado 1 s / desligado 1 s, mais ruído branco a ~-50 dB."""
    p = tmp_path / "voz.wav"
    _ff("-f", "lavfi", "-i", "aevalsrc=0.3*sin(2*PI*1000*t)*gt(mod(t\\,2)\\,1):s=48000:d=8",
        "-f", "lavfi", "-i", "anoisesrc=a=0.003:c=white:r=48000:d=8",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[a]", "-map", "[a]",
        "-ac", "1", "-c:a", "pcm_s16le", str(p))
    return p


@pytest.fixture
def trilha(tmp_path) -> Path:
    """3 s de tom 100 Hz (mais curta que o vídeo: força loop)."""
    p = tmp_path / "trilha.wav"
    _ff("-f", "lavfi", "-i", "sine=f=100:r=48000:d=3", "-ac", "2", "-c:a", "pcm_s16le", str(p))
    return p


@pytest.fixture
def video(tmp_path, voz) -> Path:
    """8 s de vídeo cinza com a voz como áudio."""
    p = tmp_path / "video.mp4"
    _ff("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=8", "-i", str(voz),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(p))
    return p


def test_duracao(voz):
    assert abs(audio.duracao(voz) - 8.0) < 0.05


def test_rms_db_janelas(voz):
    assert audio.rms_db(voz, 1.0, 2.0) > audio.rms_db(voz, 0.0, 1.0) + 20


def test_medir_ruido(voz):
    r = audio.medir_ruido(voz)
    assert -56 < r < -44     # anoisesrc a=0.003 ≈ -50 dB RMS


def test_denoise_leve_reduz_ruido(voz, tmp_path):
    dst = tmp_path / "limpo.wav"
    out = audio.denoise(voz, dst)
    assert out == dst and dst.exists()
    assert abs(audio.duracao(dst) - audio.duracao(voz)) < 0.05
    assert audio.rms_db(dst, 0.0, 1.0) < audio.rms_db(voz, 0.0, 1.0) - 6


def test_denoise_forte_sem_modelo(voz, tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "ROOT", tmp_path)   # sem assets/rnnoise aqui
    with pytest.raises(FileNotFoundError):
        audio.denoise(voz, tmp_path / "x.wav", forte=True)


def test_denoise_forte_reduz_ruido(voz, tmp_path):
    if not (audio.ROOT / "assets" / "rnnoise" / "std.rnnn").exists():
        pytest.skip("modelo RNNoise não baixado")
    dst = tmp_path / "forte.wav"
    audio.denoise(voz, dst, forte=True)
    assert audio.rms_db(dst, 0.0, 1.0) < audio.rms_db(voz, 0.0, 1.0) - 6


def test_denoise_forte_escapa_dois_pontos(voz, tmp_path, monkeypatch):
    modelo = tmp_path / "assets" / "rnnoise" / "std.rnnn"
    modelo.parent.mkdir(parents=True)
    modelo.write_bytes(b"x")
    monkeypatch.setattr(audio, "ROOT", tmp_path)
    capt = []
    monkeypatch.setattr(audio, "_ff", lambda args: capt.append(args) or "")
    audio.denoise(voz, tmp_path / "o.wav", forte=True)
    af = capt[0][capt[0].index("-af") + 1]
    assert "\\:" in af
    assert re.search(r"(?<!\\):", af.split("m=", 1)[1]) is None


BP100 = "bandpass=f=100:w=40"   # isola a trilha (100 Hz) da voz (1 kHz)


def test_mix_trilha_duck_loop_loudness(video, trilha, tmp_path):
    dst = tmp_path / "mix.mp4"
    audio.mix_trilha(video, trilha, dst)
    assert abs(audio.duracao(dst) - audio.duracao(video)) < 0.1     # loop cobre os 8 s
    com_fala = audio.rms_db(dst, 3.0, 4.0, BP100)    # voz ligada em 3-4 s
    sem_fala = audio.rms_db(dst, 4.2, 4.9, BP100)    # voz desligada em 4-5 s
    assert com_fala < sem_fala - 3                   # ducking atua
    assert audio.rms_db(dst, 6.5, 7.5, BP100) > -60  # trilha ainda presente após o loop de 3 s
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(dst)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "h264"                           # -c:v copy


def test_mix_trilha_nivel_mais_baixo(video, trilha, tmp_path):
    a = tmp_path / "a.mp4"; b = tmp_path / "b.mp4"
    audio.mix_trilha(video, trilha, a, nivel_db=-18)
    audio.mix_trilha(video, trilha, b, nivel_db=-24)
    assert audio.rms_db(b, 4.2, 4.9, BP100) < audio.rms_db(a, 4.2, 4.9, BP100) - 3


@pytest.fixture
def sfx_dir(tmp_path) -> Path:
    d = tmp_path / "sfx"; d.mkdir()
    _ff("-f", "lavfi", "-i", "sine=f=2000:r=48000:d=0.5", "-ac", "2", "-c:a", "pcm_s16le", str(d / "pop.wav"))
    return d


@pytest.fixture
def video_mudo(tmp_path) -> Path:
    p = tmp_path / "mudo.mp4"
    _ff("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=6",
        "-c:v", "libx264", "-preset", "ultrafast", "-an", str(p))
    return p


BP2K = "bandpass=f=2000:w=200"


def test_mix_sfx_video_mudo(video_mudo, sfx_dir, tmp_path):
    dst = tmp_path / "sfx.mp4"
    audio.mix_sfx(video_mudo, [{"t": 2.0, "som": "pop", "ganho_db": -3}], sfx_dir, dst)
    assert abs(audio.duracao(dst) - 6.0) < 0.1
    assert audio.rms_db(dst, 2.0, 2.4, BP2K) > audio.rms_db(dst, 0.5, 1.5, BP2K) + 20


def test_mix_sfx_video_com_audio_e_cues_em_arquivo(video, sfx_dir, tmp_path):
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps([{"t": 0.2, "som": "pop"}]), encoding="utf-8")
    dst = tmp_path / "sfx2.mp4"
    audio.mix_sfx(video, cues, sfx_dir, dst)
    assert audio.rms_db(dst, 0.2, 0.6, BP2K) > audio.rms_db(dst, 1.0, 1.4, BP2K) + 20
    assert audio.rms_db(dst, 1.0, 2.0) > -40        # voz original preservada (ligada em 1-2 s)


def test_mix_sfx_som_inexistente(video_mudo, sfx_dir, tmp_path, monkeypatch):
    chamado = []
    monkeypatch.setattr(audio, "_ff", lambda args: chamado.append(args))
    with pytest.raises(ValueError, match="nao-existe"):
        audio.mix_sfx(video_mudo, [{"t": 1, "som": "nao-existe"}], sfx_dir, tmp_path / "x.mp4")
    assert chamado == []


import budget
from test_pipeline import fake_root  # fixture reexport


@pytest.fixture
def root(fake_root: Path) -> Path:
    (fake_root / "ui").mkdir(exist_ok=True)
    (fake_root / "ui" / "precos.json").write_text(json.dumps({
        "elevenlabs_sfx": {"unidade": "efeito", "usd": 0.0, "creditos": 100},
        "elevenlabs_music": {"unidade": "faixa", "usd": 0.0, "creditos": 500},
    }), encoding="utf-8")
    return fake_root


def _wav_bytes(tmp_path) -> bytes:
    p = tmp_path / "resp.wav"
    _ff("-f", "lavfi", "-i", "sine=f=500:r=44100:d=1", "-c:a", "pcm_s16le", str(p))
    return p.read_bytes()


def test_gerar_sfx_ok(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    saldo = {"usados": 0, "limite": 10000, "restante": 10000, "reset_ts": 0}
    monkeypatch.setattr(budget, "saldo_elevenlabs", lambda *a, **k: saldo)
    chamadas = []
    def fetch(key, url, body):
        chamadas.append((key, url, body)); return _wav_bytes(tmp_path)
    proj = root / "edit-fake"
    dst = tmp_path / "pop.wav"
    r = audio.gerar_sfx(root, proj, "pop curto e seco", 0.8, dst, _fetch=fetch)
    assert r["status"] == "ok" and Path(r["path"]) == dst and dst.exists()
    assert chamadas[0][0] == "k" and "sound-generation" in chamadas[0][1]
    assert chamadas[0][2] == {"text": "pop curto e seco", "duration_seconds": 0.8}
    assert abs(audio.duracao(dst) - 1.0) < 0.05           # convertido pra WAV 48k
    assert budget.gasto_projeto(proj) == {"usd": 0.0, "creditos": 100}


def test_gerar_musica_body(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    monkeypatch.setattr(budget, "saldo_elevenlabs",
                        lambda *a, **k: {"usados": 0, "limite": 10000, "restante": 10000, "reset_ts": 0})
    chamadas = []
    def fetch(key, url, body):
        chamadas.append((url, body)); return _wav_bytes(tmp_path)
    r = audio.gerar_musica(root, root / "edit-fake", "piano calmo", 30, tmp_path / "m.wav", _fetch=fetch)
    assert r["status"] == "ok"
    assert chamadas[0][0].endswith("/v1/music")
    assert chamadas[0][1] == {"prompt": "piano calmo", "music_length_ms": 30000}


def test_gerar_sfx_bloqueado_nao_busca(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "saldo_elevenlabs", lambda *a, **k: None)   # saldo desconhecido
    chamadas = []
    r = audio.gerar_sfx(root, root / "edit-fake", "x", 1, tmp_path / "x.wav",
                        _fetch=lambda *a: chamadas.append(a) or b"")
    assert r["status"] == "precisa_aprovacao" and chamadas == []
    assert not (tmp_path / "x.wav").exists()
    assert not (root / "edit-fake" / "ui" / "costs.jsonl").exists()


def test_cli_medir_ruido(voz):
    r = subprocess.run([sys.executable, str(Path(audio.__file__)), "medir-ruido", str(voz)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and -56 < json.loads(r.stdout)["ruido_db"] < -44


def test_cli_gerar_sfx_projeto_inexistente(root, tmp_path):
    r = subprocess.run([sys.executable, str(Path(audio.__file__)), "--root", str(root),
                        "gerar-sfx", str(root / "nao-existe"), "x", "1", str(tmp_path / "x.wav")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)


def test_gerar_sfx_conversao_falha_registra_gasto(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    monkeypatch.setattr(budget, "saldo_elevenlabs",
                        lambda *a, **k: {"usados": 0, "limite": 10000, "restante": 10000, "reset_ts": 0})
    proj, dst = root / "edit-fake", tmp_path / "x.wav"
    with pytest.raises(RuntimeError):
        audio.gerar_sfx(root, proj, "x", 1, dst, _fetch=lambda *a: b"not audio")
    assert not dst.exists()
    assert budget.gasto_projeto(proj)["creditos"] == 100


def test_gerar_sfx_fetch_falha_nao_registra(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    monkeypatch.setattr(budget, "saldo_elevenlabs",
                        lambda *a, **k: {"usados": 0, "limite": 10000, "restante": 10000, "reset_ts": 0})
    def fetch(*a):
        raise RuntimeError("ElevenLabs HTTP 429")
    proj, dst = root / "edit-fake", tmp_path / "x.wav"
    with pytest.raises(RuntimeError, match="429"):
        audio.gerar_sfx(root, proj, "x", 1, dst, _fetch=fetch)
    assert not dst.exists()
    assert not (proj / "ui" / "costs.jsonl").exists()


@pytest.fixture
def duas_faixas(tmp_path, voz) -> Path:
    """Faixa 0: tom 1 kHz alto contínuo (jogo); faixa 1: a voz (mic)."""
    p = tmp_path / "obs.mkv"
    _ff("-f", "lavfi", "-i", "sine=f=1000:r=48000:d=8", "-i", str(voz),
        "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le", str(p))
    return p


def test_medir_ruido_track(duas_faixas, tmp_path):
    assert -56 < audio.medir_ruido(duas_faixas, track=1) < -44
    assert audio.medir_ruido(duas_faixas, track=0) > -30
    dst = tmp_path / "t1.wav"
    audio.denoise(duas_faixas, dst, track=1)
    assert audio.rms_db(dst, 0.0, 1.0) < -44
    assert audio.rms_db(duas_faixas, 0.0, 1.0, track=0) > audio.rms_db(duas_faixas, 0.0, 1.0, track=1) + 30


def test_mix_trilha_dst_igual_video(video, trilha):
    audio.mix_trilha(video, trilha, video)
    assert audio.rms_db(video, 6.5, 7.5, BP100) > -60
    assert not video.with_name(video.stem + ".tmp.mp4").exists()


def test_mix_trilha_falha_preserva_dst(video, tmp_path):
    antes = video.read_bytes()
    with pytest.raises(RuntimeError):
        audio.mix_trilha(video, tmp_path / "nao-existe.wav", video)
    assert video.read_bytes() == antes
    assert not video.with_name(video.stem + ".tmp.mp4").exists()


@pytest.mark.parametrize("cue", [{"som": "pop"}, {"t": 1}, {"t": -1, "som": "pop"}])
def test_mix_sfx_cue_invalido(video_mudo, sfx_dir, tmp_path, monkeypatch, cue):
    chamado = []
    monkeypatch.setattr(audio, "_ff", lambda args: chamado.append(args))
    with pytest.raises(ValueError):
        audio.mix_sfx(video_mudo, [cue], sfx_dir, tmp_path / "x.mp4")
    assert chamado == []


def test_gerar_sfx_registrar_falha_mantem_bytes(root, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "k")
    monkeypatch.setattr(budget, "saldo_elevenlabs",
                        lambda *a, **k: {"usados": 0, "limite": 10000, "restante": 10000, "reset_ts": 0})
    def boom(*a, **k):
        raise OSError("disco")
    monkeypatch.setattr(budget, "registrar", boom)
    dst = tmp_path / "x.wav"
    with pytest.raises(OSError):
        audio.gerar_sfx(root, root / "edit-fake", "x", 1, dst, _fetch=lambda *a: b"pago")
    assert dst.with_suffix(".wav.bin").read_bytes() == b"pago"
