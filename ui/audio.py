"""Áudio: denoise, trilha com ducking, SFX por cues, geração ElevenLabs.
Sem FastAPI. ffmpeg por subprocess; HTTP por urllib (_fetch injetável)."""
import json
import re
import subprocess
from pathlib import Path

import pipeline

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
ROOT = pipeline.ROOT


def _ff(args: list[str]) -> str:
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-y", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ({r.returncode}): {r.stderr[-800:]}")
    return r.stderr


def duracao(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def rms_db(path: Path, inicio: float, fim: float, filtro: str = "") -> float:
    """RMS geral (dB) da janela [inicio, fim). `filtro` entra antes do astats."""
    cadeia = f"atrim={inicio}:{fim},asetpts=PTS-STARTPTS," + (filtro + "," if filtro else "") \
        + "astats=measure_perchannel=none:measure_overall=RMS_level"
    err = _ff(["-i", str(path), "-af", cadeia, "-f", "null", "-"])
    m = re.search(r"RMS level dB:\s*(-?[\d.]+|-inf)", err)
    if not m:
        raise RuntimeError("astats sem RMS: " + err[-400:])
    return -120.0 if m.group(1) == "-inf" else float(m.group(1))


def medir_ruido(src: Path) -> float:
    """RMS (dB) do primeiro trecho silencioso (< -40 dB por >= 0.4 s); sem silêncio, 0-0.5 s."""
    err = _ff(["-i", str(src), "-af", "silencedetect=n=-40dB:d=0.4", "-f", "null", "-"])
    m = re.search(r"silence_start:\s*([\d.]+)", err)
    ini = float(m.group(1)) if m else 0.0
    return rms_db(src, ini, ini + 0.4 if m else 0.5)


def denoise(src: Path, dst: Path, forte: bool = False) -> Path:
    if forte:
        modelo = ROOT / "assets" / "rnnoise" / "std.rnnn"
        if not modelo.exists():
            raise FileNotFoundError(f"modelo RNNoise ausente: {modelo}")
        af = f"arnndn=m={modelo.as_posix()}"
    else:
        af = "afftdn=nf=-25:nt=w"
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff(["-i", str(src), "-af", af, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst
