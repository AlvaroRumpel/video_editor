import json

import motion


def test_kit_tem_vendor_fontes_e_icone():
    k = motion.MOTION / "kit"
    for f in ("vendor/gsap.min.js", "fonts/Fraunces.ttf", "fonts/Fraunces-Italic.ttf", "fonts/Inter.ttf",
              "fonts/Archivo.ttf", "fonts/IBMPlexMono-Medium.ttf", "fonts/IBMPlexMono-SemiBold.ttf"):
        assert (k / f).stat().st_size > 10_000, f
    assert (motion.MOTION / "temas" / "campeio" / "icone.png").stat().st_size > 1_000
    pkg = json.loads((motion.MOTION / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"] == {"gsap": "3.14.2", "hyperframes": "0.8.141"}
