"""Shorts verticais: <ep>/shorts.json → mini-episódio 9:16 em <ep>/shorts/<sid>/ → narrado.render.
Short = cenas inteiras e consecutivas do longo: reaproveita áudio, palavras e assets, sem novo TTS."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import narrado  # noqa: E402
import pipeline  # noqa: E402

MAX_SEG = 60.0
TELA_FINAL_DUR = 3.0
SID_RE = re.compile(r"s\d{2}")


def ler(ep_dir) -> list[dict]:
    d = pipeline.read_json(Path(ep_dir) / "shorts.json", None)
    if not isinstance(d, list) or not d:
        raise ValueError(f"{Path(ep_dir) / 'shorts.json'} ausente, ilegível ou vazio (lista de shorts)")
    return d


def duracao(short: dict, st: dict) -> float:
    return sum(st[c]["dur"] + narrado.PAUSA for c in short["cenas"]) + TELA_FINAL_DUR


def validar(ep_dir, lang: str) -> list[dict]:
    ep_dir = Path(ep_dir)
    erros = []

    def e(i, m):
        erros.append({"id": i, "motivo": m})

    ids = {c["id"] for c in narrado.ler(ep_dir)["cenas"]}
    st = narrado.estado(ep_dir, lang)
    vistos = set()
    for s in ler(ep_dir):
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not SID_RE.fullmatch(sid):
            e(str(sid), f"id inválido: {sid!r} (s01, s02, ...)")
            continue
        if sid in vistos:
            e(sid, "id duplicado")
            continue
        vistos.add(sid)
        cenas = s.get("cenas")
        if not isinstance(cenas, list) or not cenas:
            e(sid, "cenas precisa ser lista não vazia")
            continue
        for c in dict.fromkeys(cenas):
            if c not in ids:
                e(sid, f"cena {c} não existe no episodio.json")
        if len(set(cenas)) != len(cenas):
            e(sid, "cena repetida")
        for campo in ("titulo", "descricao"):
            v = s.get(campo)
            if not isinstance(v, dict) or not isinstance(v.get(lang), str) or not v[lang].strip():
                e(sid, f"falta {campo}.{lang}")
        if any(c not in ids for c in cenas):
            continue
        sem_audio = [c for c in cenas if not (st.get(c) and (ep_dir / st[c].get("audio", "-")).is_file())]
        if sem_audio:
            e(sid, f"áudio ausente em {', '.join(sem_audio)}: rode tts/alinhar do episódio")
            continue
        total = duracao(s, st)
        if total > MAX_SEG:
            e(sid, f"duração {total:.1f} s passa de {MAX_SEG:.0f} s: tire uma cena")
    return erros
