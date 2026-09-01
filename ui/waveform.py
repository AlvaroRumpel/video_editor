"""Picos de áudio para a timeline. ffmpeg -> s16le mono 8kHz -> buckets."""
import subprocess
from array import array
from pathlib import Path

from pipeline import atomic_write_json, read_json

RATE = 8000


def get_waveform(proj: Path, source: str, n: int = 4000) -> dict:
    cache = proj / "ui" / "cache" / "waveform.json"
    src = Path(source)
    try:
        key = f"{src.stat().st_mtime_ns}:{src.stat().st_size}:{n}"
    except OSError:
        return {"duration": 0.0, "peaks": []}
    cached = read_json(cache, {})
    if cached.get("key") == key:
        return cached
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0",
         "-ac", "1", "-ar", str(RATE), "-af", "volume=4.1", "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    duration = len(samples) / RATE
    peaks = []
    if samples:
        step = max(1, len(samples) // n)
        for i in range(0, len(samples), step):
            chunk = samples[i:i + step]
            peaks.append(max(abs(s) for s in chunk) / 32768)
        peaks = peaks[:n]
    out = {"key": key, "duration": duration, "peaks": peaks}
    atomic_write_json(cache, out)
    return out
