import json
import re
import shutil
import subprocess
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
