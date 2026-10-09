"""Quadro do kit montado: python ui/kitframe.py <proj> <t> <dst.png> [--lang pt]
Roda motion.montar, abre motion/index.html, vai ao instante t (s) e salva o PNG."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import motion  # noqa: E402


def quadro(proj: Path, t: float, dst: Path, lang: str | None = None) -> Path:
    r = motion.montar(proj, lang)
    if not r["ok"]:
        raise RuntimeError(json.dumps(r["erros"], ensure_ascii=False))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        try:
            pg = b.new_page(viewport={"width": 1920, "height": 1080})
            pg.goto(Path(r["index"]).resolve().as_uri())
            pg.wait_for_function("window.__kit !== undefined", timeout=20000)
            pg.evaluate("document.fonts.ready.then(() => true)")
            pg.evaluate("t => __kit.ir(t)", t)
            pg.screenshot(path=str(dst))
        finally:
            b.close()
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("proj"); ap.add_argument("t", type=float); ap.add_argument("dst"); ap.add_argument("--lang")
    ns = ap.parse_args()
    print(quadro(Path(ns.proj), ns.t, Path(ns.dst), ns.lang))
