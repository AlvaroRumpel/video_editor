"""Kit de motion (HyperFrames): cenas.json → composição → vídeo dos reels/ads.

montar: valida, gera <proj>/motion[.<lang>]/ (kit copiado + index.html), mede no
Chromium (duração, sons, layout) e grava cues[.<lang>].json.
render: hyperframes de motion/node_modules → video[.<lang>].mp4 conferido no ffprobe.
folha: contact sheet de QC a partir do vídeo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = pipeline.ROOT
MOTION = ROOT / "motion"
FPS = 30
W, H = 1080, 1920
SAFE = (80, 180, 1000, 1660)  # x0, y0, x1, y1
