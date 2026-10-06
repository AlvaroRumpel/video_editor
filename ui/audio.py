"""Áudio: denoise, trilha com ducking, SFX por cues, geração ElevenLabs.
Sem FastAPI. ffmpeg por subprocess; HTTP por urllib (_fetch injetável)."""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import budget
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
        # Escapar ':' e envolver em quotes para ffmpeg aceitar de qualquer cwd
        af = f"arnndn=m='{modelo.as_posix().replace(':', r'\:')}'"
    else:
        af = "afftdn=nf=-25:nt=w"
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff(["-i", str(src), "-af", af, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst


AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def _ratio(duck_db: float) -> float:
    # ponytail: assume voz ~12 dB acima do threshold; ratio dá o duck pedido nesse caso.
    d = min(abs(duck_db), 11.0)
    return 12.0 / (12.0 - d)


def mix_trilha(video: Path, trilha: Path, dst: Path, nivel_db: float = -18.0,
               duck_db: float = -8.0, fade_s: float = 1.5) -> Path:
    dur = duracao(video)
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    graph = (
        f"[0:a]{fmt},asplit=2[voz][sc];"
        f"[1:a]aloop=loop=-1:size=2000000000,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,{fmt},"
        f"volume={nivel_db}dB,afade=t=in:d={fade_s},afade=t=out:st={max(dur - fade_s, 0):.3f}:d={fade_s}[tr];"
        f"[tr][sc]sidechaincompress=threshold=0.05:ratio={_ratio(duck_db):.3f}:attack=200:release=800[duck];"
        f"[voz][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11[out]"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff(["-i", str(video), "-i", str(trilha), "-filter_complex", graph,
         "-map", "0:v", "-map", "[out]", "-c:v", "copy", *AAC, "-movflags", "+faststart", str(dst)])
    return dst


def _tem_audio(path: Path) -> bool:
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def mix_sfx(video: Path, cues, sfx_dir: Path, dst: Path) -> Path:
    if isinstance(cues, (str, Path)):
        cues = json.loads(Path(cues).read_text(encoding="utf-8"))
    if not cues:
        raise ValueError("cues vazio")
    entradas = []
    for c in cues:
        p = sfx_dir / f"{c['som']}.wav"
        if not p.exists():
            raise ValueError(f"SFX não encontrado: {c['som']} ({p})")
        entradas.append((p, float(c["t"]), float(c.get("ganho_db", 0))))
    dur = duracao(video)
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    args = ["-i", str(video)]
    n_inputs = 1
    partes = []
    if _tem_audio(video):
        partes.append(f"[0:a]{fmt}[base]")
    else:
        args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        n_inputs += 1
        partes.append(f"[1:a]{fmt}[base]")
    rotulos = ["[base]"]
    for i, (p, t, g) in enumerate(entradas):
        args += ["-i", str(p)]
        ms = int(round(t * 1000))
        partes.append(f"[{n_inputs}:a]{fmt},adelay={ms}|{ms},volume={g}dB[s{i}]")
        n_inputs += 1
        rotulos.append(f"[s{i}]")
    partes.append("".join(rotulos) + f"amix=inputs={len(rotulos)}:duration=first:normalize=0[out]")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff([*args, "-filter_complex", ";".join(partes), "-map", "0:v", "-map", "[out]",
         "-c:v", "copy", *AAC, "-movflags", "+faststart", str(dst)])
    return dst


ELEVEN_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"
ELEVEN_MUSIC_URL = "https://api.elevenlabs.io/v1/music"


def _fetch_elevenlabs(key: str, url: str, body: dict) -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {e.read()[:300]!r}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"ElevenLabs inacessível: {e}") from e


def _gerar(root: Path, proj: Path, provedor: str, url: str, body: dict, dst: Path,
           prompt: str, aprovacao, _fetch) -> dict:
    budget._existe(proj)
    d = budget.autorizar(root, proj, provedor, 1, aprovacao=aprovacao)
    if d["status"] != "ok":
        return d
    key = budget._chave_elevenlabs()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY ausente")
    dados = (_fetch or _fetch_elevenlabs)(key, url, body)
    # fetch ok = créditos já consumidos: registrar antes de converter
    budget.registrar(proj, provedor, 1, aprovacao=aprovacao, nota=prompt[:80], root=root)
    bruto = dst.with_suffix(dst.suffix + ".bin")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        bruto.write_bytes(dados)
        _ff(["-i", str(bruto), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    except Exception:
        dst.unlink(missing_ok=True)
        raise
    finally:
        bruto.unlink(missing_ok=True)
    return {"status": "ok", "path": str(dst), "estimativa": d["estimativa"]}


def gerar_sfx(root: Path, proj: Path, prompt: str, dur_s: float, dst: Path,
              aprovacao=None, _fetch=None) -> dict:
    return _gerar(root, proj, "elevenlabs_sfx", ELEVEN_SFX_URL,
                  {"text": prompt, "duration_seconds": float(dur_s)}, dst, prompt, aprovacao, _fetch)


def gerar_musica(root: Path, proj: Path, prompt: str, dur_s: float, dst: Path,
                 aprovacao=None, _fetch=None) -> dict:
    return _gerar(root, proj, "elevenlabs_music", ELEVEN_MUSIC_URL,
                  {"prompt": prompt, "music_length_ms": int(round(dur_s * 1000))},
                  dst, prompt, aprovacao, _fetch)


EXIT = {"ok": 0, "precisa_aprovacao": 2, "bloqueado": 3}


def _cli(ns, root: Path):
    if ns.cmd == "medir-ruido":
        return {"ruido_db": medir_ruido(Path(ns.src))}, 0
    if ns.cmd == "denoise":
        return {"path": str(denoise(Path(ns.src), Path(ns.dst), forte=ns.forte))}, 0
    if ns.cmd == "mix-trilha":
        return {"path": str(mix_trilha(Path(ns.video), Path(ns.trilha), Path(ns.dst),
                                       nivel_db=ns.nivel, duck_db=ns.duck))}, 0
    if ns.cmd == "mix-sfx":
        return {"path": str(mix_sfx(Path(ns.video), Path(ns.cues), Path(ns.sfx_dir), Path(ns.dst)))}, 0
    fn = gerar_sfx if ns.cmd == "gerar-sfx" else gerar_musica
    d = fn(root, Path(ns.proj), ns.prompt, ns.dur, Path(ns.dst), aprovacao=ns.aprovacao)
    return d, EXIT[d["status"]]


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="áudio do video_editor")
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("medir-ruido"); p.add_argument("src")
    p = sub.add_parser("denoise"); p.add_argument("src"); p.add_argument("dst"); p.add_argument("--forte", action="store_true")
    p = sub.add_parser("mix-trilha"); p.add_argument("video"); p.add_argument("trilha"); p.add_argument("dst")
    p.add_argument("--nivel", type=float, default=-18.0); p.add_argument("--duck", type=float, default=-8.0)
    p = sub.add_parser("mix-sfx"); p.add_argument("video"); p.add_argument("cues"); p.add_argument("sfx_dir"); p.add_argument("dst")
    for nome in ("gerar-sfx", "gerar-musica"):
        p = sub.add_parser(nome); p.add_argument("proj"); p.add_argument("prompt")
        p.add_argument("dur", type=float); p.add_argument("dst"); p.add_argument("--aprovacao", type=int)
    ns = ap.parse_args()
    try:
        out, code = _cli(ns, Path(ns.root))
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
