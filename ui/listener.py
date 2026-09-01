"""Escuta da UI: toca heartbeats e anuncia pedidos pending novos (1 linha por pedido).

Rodar via monitor persistente da sessão Claude (skill /edit-video):
cada linha PENDING é um pedido novo pra executar conforme o CLAUDE.md.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"video-use", "ui", "bruto", "Export", "assets", "docs", "Formatos", ".git",
        ".superpowers", ".ui-runtime", ".claude"}
seen = set()


def projects():
    out = []
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*"):
        for d in ROOT.glob(depth):
            if not d.is_dir() or d.relative_to(ROOT).parts[0] in SKIP:
                continue
            if (d / "edl.json").exists() or (d / "ui").is_dir() \
                    or (d / "preview.mp4").exists() or (d / "final.mp4").exists():
                out.append(d)
    return out


while True:
    try:
        queues = []
        for proj in projects():
            ui = proj / "ui"
            ui.mkdir(exist_ok=True)
            (ui / "heartbeat").touch()
            queues.append((proj.relative_to(ROOT).as_posix(), ui / "queue.json"))
        queues.append(("_global", ROOT / ".ui-runtime" / "queue.json"))
        for pid, qf in queues:
            if not qf.exists():
                continue
            try:
                entries = json.loads(qf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for e in entries:
                if e.get("status") != "pending":
                    continue
                key = (pid, e.get("id"), e.get("reply") or "")
                if key in seen:
                    continue
                seen.add(key)
                reply = f" reply={e['reply']!r}" if e.get("reply") else ""
                print(f"PENDING {pid} id={e.get('id')} type={e.get('type')} "
                      f"target={e.get('target')} text={e.get('text')!r}{reply}",
                      flush=True)
    except Exception as exc:  # nunca morrer silenciosamente
        print(f"LISTENER-ERROR {exc!r}", flush=True)
        time.sleep(10)
    time.sleep(3)
