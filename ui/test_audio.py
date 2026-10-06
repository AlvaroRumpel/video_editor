import json
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
