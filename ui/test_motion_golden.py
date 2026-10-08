"""Golden do kit: renderiza motion/amostras nas duas marcas e compara frames com
motion/amostras/ref/. Lento e opt-in: MOTION_GOLDEN=1 (comparar) ou
MOTION_GOLDEN=atualizar (regravar referências — revisar as imagens antes de commitar).
Upgrade do hyperframes só com este teste passando."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import motion

MODO = os.environ.get("MOTION_GOLDEN")
AMOSTRAS = motion.MOTION / "amostras"
REF = AMOSTRAS / "ref"
pytestmark = pytest.mark.skipif(
    not MODO or not (motion.MOTION / "node_modules" / "hyperframes").is_dir() or shutil.which("ffmpeg") is None,
    reason="golden opt-in (MOTION_GOLDEN) e precisa de motion/node_modules")


def _ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def _psnr(a: Path, b: Path) -> float:
    r = subprocess.run(["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "psnr", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"average:(inf|[\d.]+)", r.stderr)
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


def _luma_faixa(png: Path, crop: str) -> float:
    r = subprocess.run(["ffmpeg", "-i", str(png), "-vf", f"crop={crop},signalstats,metadata=print",
                        "-f", "null", "-"], capture_output=True, text=True)
    lo = float(re.search(r"YMIN=([\d.]+)", r.stderr).group(1))
    hi = float(re.search(r"YMAX=([\d.]+)", r.stderr).group(1))
    return hi - lo


NUMERO = "crop=920:360:80:760"   # w:h:x:y, contém os dígitos do número da cena c03 (y~780-990)
MARGEM_DB = 5                    # contador em movimento tem de ficar >= 5 dB abaixo do piso de "só grão"


def _frame(video: Path, t: float, dst: Path, crop: str | None = None) -> Path:
    _ff("-ss", f"{t:.3f}", "-i", str(video), *(["-vf", crop] if crop else []), "-frames:v", "1", str(dst))
    return dst


@pytest.mark.parametrize("marca", ["anotus", "campeio"])
def test_golden(tmp_path, marca):
    p = tmp_path / marca
    shutil.copytree(AMOSTRAS / "projeto", p)
    d = json.loads((p / "cenas.json").read_text(encoding="utf-8"))
    d["marca"] = marca
    (p / "cenas.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(p / "tela.png"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-pix_fmt", "yuv420p", str(p / "clip.mp4"))
    r = motion.render(p)
    assert r["ok"], r
    video = p / "video.mp4"
    tempos = json.loads((p / "motion" / "tempos.json").read_text(encoding="utf-8"))
    cenas = {c["id"]: c for c in tempos["cenas"]}

    # Review Focus 1: contador e grão mudam com o tempo (pintores rodam no seek do HyperFrames).
    # Compara só a região do número (grão sozinho não basta: PSNR de grão vs grão fica alto).
    c3 = cenas["c03"]
    fim = c3["ini"] + c3["dur"] - c3["saida"] - 0.05
    a = _frame(video, c3["ini"] + 0.7, tmp_path / "cont-a.png", NUMERO)
    b = _frame(video, c3["ini"] + 1.1, tmp_path / "cont-b.png", NUMERO)
    f = _frame(video, fim, tmp_path / "cont-f.png", NUMERO)
    # piso: dois quadros de uma cena já assentada (c04, lista) na mesma região, só o grão varia
    c4 = cenas["c04"]
    fim4 = c4["ini"] + c4["dur"] - c4["saida"] - 0.05
    s1 = _frame(video, fim4 - 0.3, tmp_path / "piso-1.png", NUMERO)
    s2 = _frame(video, fim4, tmp_path / "piso-2.png", NUMERO)
    lim = _psnr(s1, s2) - MARGEM_DB
    assert _psnr(a, b) < lim, f"contador parado entre +0,7 s e +1,1 s ({_psnr(a, b):.1f} dB, piso {lim:.1f})"
    assert _psnr(a, f) < lim, f"contador em +0,7 s já igual ao valor final ({_psnr(a, f):.1f} dB, piso {lim:.1f})"
    # Review Focus 2: vídeo dentro da moldura browser aparece (não fica preto)
    c6 = cenas["c06"]
    v = _frame(video, c6["ini"] + c6["dur"] - c6["saida"] - 0.1, tmp_path / "video.png")
    assert _luma_faixa(v, "960:600:60:560") > 50, "clipe da cena tela não apareceu"

    REF.mkdir(parents=True, exist_ok=True)
    ruins = []
    for c in tempos["cenas"]:
        pts = [("final", c["ini"] + c["dur"] - c["saida"] - 0.05)]
        if c["saida"]:
            pts.append(("saida", c["ini"] + c["dur"] - c["saida"] / 2))
        for rot, t in pts:
            png = _frame(video, t, tmp_path / f"{marca}-{c['id']}-{rot}.png")
            ref = REF / png.name
            if MODO == "atualizar":
                shutil.copy2(png, ref)
                continue
            assert ref.exists(), f"sem referência {ref.name}: rodar MOTION_GOLDEN=atualizar"
            if (val := _psnr(png, ref)) < 35:
                ruins.append(f"{png.name}: {val:.1f} dB")
    assert not ruins, ruins
