"""Leitura dos artefatos do pipeline video-use. Sem dependência de FastAPI."""
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {"video-use", "ui", "bruto", "Export", "assets", "docs",
             "Formatos", ".git"}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def find_projects(root: Path) -> list[dict]:
    out = []
    for depth in ("*/edl.json", "*/*/edl.json", "*/*/*/edl.json"):
        for edl in sorted(root.glob(depth)):
            rel = edl.parent.relative_to(root).as_posix()
            if rel.split("/")[0] in SKIP_DIRS:
                continue
            out.append({
                "id": rel,
                "name": edl.parent.name,
                "has_preview": (edl.parent / "preview.mp4").exists(),
                "has_final": (edl.parent / "final.mp4").exists(),
            })
    return out


def project_dir(root: Path, pid: str) -> Path:
    p = (root / pid).resolve()
    if root.resolve() not in p.parents:
        raise ValueError(f"id inválido: {pid}")
    return p


def phrases_from_transcript(tr: dict, gap: float = 0.5) -> list[dict]:
    words = [w for w in tr.get("words", []) if w.get("type") == "word"]
    phrases, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= gap:
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return [{"start": ph[0]["start"], "end": ph[-1]["end"],
             "text": " ".join(w["text"].strip() for w in ph)} for ph in phrases]


_SRT_TIME = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[dict]:
    subs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                subs.append({
                    "start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                    "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                    "text": "\n".join(lines[i + 1:]).strip(),
                })
                break
    return subs


def claude_online(proj: Path) -> bool:
    hb = proj / "ui" / "heartbeat"
    try:
        return time.time() - hb.stat().st_mtime < 10
    except OSError:
        return False


def _load_transcript(proj: Path, edl: dict) -> dict:
    tdir = proj / "transcripts"
    if not tdir.is_dir():
        return {}
    main = edl.get("sources", {}).get("MAIN", "")
    stem = Path(main).stem if main else ""
    cand = tdir / f"{stem}.json"
    files = [cand] if cand.exists() else sorted(tdir.glob("*.json"))
    return read_json(files[0], {}) if files else {}


def load_project(root: Path, pid: str) -> dict:
    proj = project_dir(root, pid)
    edl = read_json(proj / "edl.json", {"ranges": [], "sources": {},
                                       "overlays": []})
    tr = _load_transcript(proj, edl)
    srt_path = proj / "master.srt"
    srt = parse_srt(srt_path.read_text(encoding="utf-8")) \
        if srt_path.exists() else []
    ranges = edl.get("ranges", [])
    source_duration = max(
        [tr.get("audio_duration_secs", 0.0)] +
        [r["end"] for r in ranges] or [0.0])
    return {
        "id": pid,
        "edl": edl,
        "zooms": read_json(proj / "zooms.json", []),
        "phrases": phrases_from_transcript(tr) if tr else [],
        "srt": srt,
        "state": read_json(proj / "ui" / "state.json", {}),
        "queue": read_json(proj / "ui" / "queue.json", []),
        "claude_online": claude_online(proj),
        "source_duration": source_duration,
        "has_preview": (proj / "preview.mp4").exists(),
        "has_final": (proj / "final.mp4").exists(),
    }
