"""Dublagem: frases na timeline do export, tradução (preenchida pelo Claude)
validada contra glossário e tempo, TTS ElevenLabs por frase (cache + orçamento),
encaixe no tempo, remix e exports por idioma. Artefato: <proj>/dub/<lang>/dublagem.json."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audio  # noqa: E402
import budget  # noqa: E402
import clips  # noqa: E402
import pipeline  # noqa: E402

LANG_RE = re.compile(r"[a-z]{2}")
CPS = {"es": 15.0, "en": 14.0}
CPS_PADRAO = 14.0
FOLGA = 1.15
MAX_FATOR = 1.25
MAX_FRASE_S = 12.0
PAUSA = 0.35
CAMPOS_TTS = ("trad", "audio", "hash", "dur", "fator", "estado")
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
MODELO_TTS = "eleven_multilingual_v2"
SR = 48000
EXIT_ORCAMENTO = {"ok": 0, "precisa_aprovacao": 2, "bloqueado": 3}


def _dir(proj, lang) -> Path:
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"idioma inválido: {lang!r} (use 2 letras minúsculas, ex.: es)")
    return Path(proj) / "dub" / lang


def _ler(proj, lang) -> dict:
    p = _dir(proj, lang) / "dublagem.json"
    d = pipeline.read_json(p, None)
    if not isinstance(d, dict) or not isinstance(d.get("frases"), list):
        raise ValueError(f"{p} ausente ou inválido — rode `frases` antes")
    return d


def _gravar(proj, lang, d: dict) -> None:
    pipeline.atomic_write_json(_dir(proj, lang) / "dublagem.json", d)


def _quebra(words: list, ix: list) -> list:
    """Índices de uma frase → frases de no máx. MAX_FRASE_S (corta na palavra mais perto do meio)."""
    if len(ix) < 2 or words[ix[-1]]["e"] - words[ix[0]]["t"] <= MAX_FRASE_S:
        return [ix]
    meio = (words[ix[0]]["t"] + words[ix[-1]]["e"]) / 2
    k = min(range(1, len(ix)), key=lambda j: abs(words[ix[j]]["t"] - meio))
    return _quebra(words, ix[:k]) + _quebra(words, ix[k:])


def frases(proj, lang, words: list) -> dict:
    """Cria/atualiza dublagem.json; preserva tradução/áudio de frases com mesmo id e mesmo texto."""
    d_dir = _dir(proj, lang)
    antigo = pipeline.read_json(d_dir / "dublagem.json", {})
    antigo = antigo if isinstance(antigo, dict) else {}
    velhas = {(f.get("id"), f.get("orig")): f for f in antigo.get("frases") or [] if isinstance(f, dict)}
    out, preservadas = [], 0
    for fr in clips.frases(words, pausa=PAUSA):
        for ix in _quebra(words, fr["palavras"]):
            fid = f"f{len(out) + 1:03d}"
            orig = " ".join(words[i]["w"] for i in ix)
            f = {"id": fid, "t_in": words[ix[0]]["t"], "t_out": words[ix[-1]]["e"], "orig": orig,
                 "trad": None, "audio": None, "hash": None, "dur": None, "fator": None, "estado": "nova"}
            v = velhas.get((fid, orig))
            if v and v.get("trad"):
                f.update({k: v.get(k) for k in CAMPOS_TTS})
                preservadas += 1
            out.append(f)
    d_dir.mkdir(parents=True, exist_ok=True)
    _gravar(proj, lang, {"lang": lang, "voz": antigo.get("voz"), "frases": out})
    return {"frases": len(out), "preservadas": preservadas}


def _glossario(root) -> dict:
    g = pipeline.read_json(Path(root) / "ui" / "glossario.json", {})
    return g if isinstance(g, dict) else {}


def _tem(texto: str, termo: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(termo) + r"(?!\w)", texto, re.I) is not None


def validar(proj, lang, root=None) -> dict:
    root = root or pipeline.ROOT
    d = _ler(proj, lang)
    g = _glossario(root)
    cps = CPS.get(lang, CPS_PADRAO)
    erros, longas = [], []
    for f in d["frases"]:
        trad = (f.get("trad") or "").strip()
        if not trad:
            erros.append(f"{f['id']}: sem tradução")
            continue
        for termo, alvo in g.items():
            if not _tem(f.get("orig") or "", termo):
                continue
            esperado = termo if alvo == "manter" else (alvo.get(lang) if isinstance(alvo, dict) else None)
            if esperado and not _tem(trad, esperado):
                erros.append(f"{f['id']}: glossário — '{termo}' deve virar '{esperado}'")
        slot = float(f["t_out"]) - float(f["t_in"])
        est = len(trad) / cps
        if slot > 0 and est > FOLGA * slot:
            longas.append({"id": f["id"], "slot": round(slot, 2), "estimativa": round(est, 2)})
    return {"ok": not erros and not longas, "erros": erros, "longas": longas}


def voz(proj, root=None) -> dict:
    """Voz do projeto (state.json.dub.voz) > marca (edit/shorts/<marca>/…) > padrao."""
    root = Path(root or pipeline.ROOT)
    st = pipeline.read_json(Path(proj) / "ui" / "state.json", {})
    v = (st.get("dub") or {}).get("voz") if isinstance(st, dict) else None
    if isinstance(v, dict) and v.get("voice_id"):
        return v
    vozes = pipeline.read_json(root / "ui" / "vozes.json", {})
    vozes = vozes if isinstance(vozes, dict) else {}
    try:
        partes = Path(proj).resolve().relative_to(root.resolve()).parts
    except ValueError:
        partes = ()
    marca = partes[2] if len(partes) >= 4 and partes[:2] == ("edit", "shorts") else None
    for k in ([marca] if marca else []) + ["padrao"]:
        v = vozes.get(k)
        if isinstance(v, dict) and v.get("voice_id"):
            return v
    raise ValueError("sem voz: configure ui/vozes.json (padrao/marca) ou state.json.dub.voz")


def _ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _linhas(texto: str, largura: int = 42) -> list:
    linhas, cur = [], ""
    for p in texto.split():
        if cur and len(cur) + 1 + len(p) > largura:
            linhas.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        linhas.append(cur)
    return linhas


def srt(proj, lang) -> str:
    cues = []
    for f in _ler(proj, lang)["frases"]:
        trad = (f.get("trad") or "").strip()
        if not trad:
            continue
        ls = _linhas(trad)
        blocos = [ls[i:i + 2] for i in range(0, len(ls), 2)]
        total = sum(len(" ".join(b)) for b in blocos)
        t, span = float(f["t_in"]), float(f["t_out"]) - float(f["t_in"])
        for b in blocos:
            dt = span * len(" ".join(b)) / total
            cues.append((t, t + dt, "\n".join(b)))
            t += dt
    return "".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(cues, 1))


def words(proj, lang) -> list:
    """Pseudo-palavras traduzidas espalhadas no tempo de cada frase (formato de words_out)."""
    out = []
    for f in _ler(proj, lang)["frases"]:
        ps = (f.get("trad") or "").split()
        if not ps:
            continue
        span, total, t = float(f["t_out"]) - float(f["t_in"]), sum(len(p) for p in ps), float(f["t_in"])
        for p in ps:
            dt = span * len(p) / total
            out.append({"t": round(t, 3), "e": round(t + dt, 3), "w": p})
            t += dt
    pipeline.atomic_write_json(_dir(proj, lang) / "words.json", out)
    return out


def _abs(proj: Path, caminho: str) -> str:
    p = Path(caminho)
    return str(p if p.is_absolute() else (proj / p).resolve())


def edl(proj, lang) -> dict:
    """Copia edl.json para dub/<lang>/ com caminhos absolutos e overlays localizados quando existirem."""
    proj = Path(proj)
    e = pipeline.read_json(proj / "edl.json", None)
    if not isinstance(e, dict):
        raise ValueError("edl.json ausente ou inválido")
    e["sources"] = {k: _abs(proj, v) for k, v in (e.get("sources") or {}).items()}
    if e.get("subtitles"):
        e["subtitles"] = _abs(proj, e["subtitles"])
    trocados, mantidos = [], []
    for o in e.get("overlays") or []:
        f = str(o.get("file", ""))
        loc = f.replace("animations/remotion/out/", f"animations/remotion/out_{lang}/", 1)
        if loc != f and (proj / loc).is_file():
            o["file"] = _abs(proj, loc)
            trocados.append(o["file"])
        else:
            o["file"] = _abs(proj, f)
            mantidos.append(o["file"])
    _dir(proj, lang).mkdir(parents=True, exist_ok=True)
    pipeline.atomic_write_json(_dir(proj, lang) / "edl.json", e)
    return {"trocados": trocados, "mantidos": mantidos}


def _hash(voice_id: str, trad: str) -> str:
    return hashlib.sha1(f"{voice_id}\n{trad}".encode("utf-8")).hexdigest()


def tts(proj, lang, root=None, aprovacao=None, _fetch=None) -> dict:
    """Gera mp3 das frases traduzidas que mudaram (texto ou voz). Autoriza antes; registra o gerado."""
    root = Path(root or pipeline.ROOT)
    proj = Path(proj)
    d = _ler(proj, lang)
    v = voz(proj, root)
    pend = [f for f in d["frases"] if (f.get("trad") or "").strip() and (
        f.get("hash") != _hash(v["voice_id"], f["trad"].strip())
        or not f.get("audio") or not (proj / f["audio"]).is_file())]
    if not pend:
        return {"status": "ok", "geradas": [], "caracteres": 0}
    chars = sum(len(f["trad"].strip()) for f in pend)
    a = budget.autorizar(root, proj, "elevenlabs_tts", chars, aprovacao=aprovacao)
    if a["status"] != "ok":
        return {**a, "caracteres": chars, "pendentes": len(pend)}
    key = budget._chave_elevenlabs()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY ausente")
    fetch = _fetch or audio._fetch_elevenlabs
    url = TTS_URL.format(voice_id=v["voice_id"])
    dd = _dir(proj, lang)
    geradas, usados, erro = [], 0, None
    try:
        for f in pend:
            trad = f["trad"].strip()
            try:
                dados = fetch(key, url, {"text": trad, "model_id": MODELO_TTS})
            except RuntimeError as e:
                erro = str(e)
                break
            (dd / f"{f['id']}.mp3").write_bytes(dados)
            f.update(audio=f"dub/{lang}/{f['id']}.mp3", hash=_hash(v["voice_id"], trad),
                     dur=None, fator=None, estado="gerada")
            geradas.append(f["id"])
            usados += len(trad)
    finally:
        d["voz"] = v
        _gravar(proj, lang, d)
        if usados:   # créditos já consumidos: registrar mesmo se o lote parou
            budget.registrar(proj, "elevenlabs_tts", usados, aprovacao=aprovacao,
                             nota=f"dublagem {lang}: {len(geradas)} frases", root=root)
    if erro:
        raise RuntimeError(f"TTS parou após {len(geradas)} frases: {erro}")
    return {"status": "ok", "geradas": geradas, "caracteres": usados}


def _dur(path: Path, run) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True, timeout=60)
    return float(r.stdout.strip())


def encaixar(proj, lang, dur_total: float, _run=None) -> dict:
    """Mede cada frase, acelera até MAX_FATOR, posiciona em t_in num voz.wav (48 kHz mono) do tamanho do export."""
    run = _run or subprocess.run
    proj = Path(proj)
    d = _ler(proj, lang)
    dd = _dir(proj, lang)
    tmp = dd / "_encaixe"
    tmp.mkdir(parents=True, exist_ok=True)
    buf = bytearray(int(dur_total * SR) * 2)
    res = {"encaixadas": [], "aceleradas": [], "estouradas": []}
    try:
        for f in d["frases"]:
            src = proj / f["audio"] if f.get("audio") else None
            if not src or not src.is_file():
                continue
            slot = float(f["t_out"]) - float(f["t_in"])
            dur = _dur(src, run)
            fator = dur / slot if slot > 0 else float("inf")
            f["dur"], f["fator"] = round(dur, 3), round(fator, 3)
            if fator > MAX_FATOR:
                f["estado"] = "estoura"
                res["estouradas"].append(f["id"])
                continue
            wav = tmp / f"{f['id']}.wav"
            af = ["-af", f"atempo={fator:.4f}"] if fator > 1 else []
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *af,
                 "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                capture_output=True, check=True, timeout=120)
            with wave.open(str(wav), "rb") as w:
                pcm = w.readframes(w.getnframes())
            ini = int(float(f["t_in"]) * SR) * 2
            if ini < len(buf):
                fim = min(ini + len(pcm), len(buf))
                buf[ini:fim] = pcm[:fim - ini]
            f["estado"] = "encaixada"
            (res["aceleradas"] if fator > 1 else res["encaixadas"]).append(f["id"])
        with wave.open(str(dd / "voz.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(buf))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _gravar(proj, lang, d)
    return res


def _trilha(proj: Path, root: Path, trilha=None):
    """Trilha explícita, ou state.json.audio.trilha (caminho, ou nome em assets/music/)."""
    if trilha:
        return Path(trilha)
    st = pipeline.read_json(proj / "ui" / "state.json", {})
    nome = ((st.get("audio") or {}).get("trilha") if isinstance(st, dict) else None) or ""
    if not nome:
        return None
    for cand in (Path(nome), root / nome, proj / nome):
        if cand.is_file():
            return cand
    achados = sorted((root / "assets" / "music").glob(f"{Path(nome).stem}.*"))
    return achados[0] if achados else None


def mixar(proj, lang, export, nome, root=None, video=None, saida=None, trilha=None) -> dict:
    """voz.wav (+ trilha com ducking) sobre a imagem de `video` (ou do export) → mp4, m4a e srt em Export/."""
    root = Path(root or pipeline.ROOT)
    proj = Path(proj)
    dd = _dir(proj, lang)
    voz_wav = dd / "voz.wav"
    if not voz_wav.is_file():
        raise ValueError("voz.wav ausente — rode `encaixar` antes")
    saida = Path(saida or root / "Export")
    video = Path(video or export)
    st = pipeline.read_json(proj / "ui" / "state.json", {})
    a = (st.get("audio") or {}) if isinstance(st, dict) else {}
    tp = _trilha(proj, root, trilha)
    base = dd / "_base.mp4"
    mp4 = saida / f"{nome} - {lang}.mp4"
    try:
        audio._atomico(base, ["-i", str(video), "-i", str(voz_wav), "-map", "0:v", "-map", "1:a",
                              "-c:v", "copy", *audio.AAC, "-shortest"])
        if tp:
            audio.mix_trilha(base, tp, mp4, nivel_db=float(a.get("nivel_db", -18.0)),
                             duck_db=float(a.get("duck_db", -8.0)))
        else:
            audio._atomico(mp4, ["-i", str(base), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                                 "-af", "loudnorm=I=-14:TP=-1:LRA=11", *audio.AAC, "-movflags", "+faststart"])
    finally:
        base.unlink(missing_ok=True)
    m4a = saida / f"{nome} - {lang}.m4a"
    audio._atomico(m4a, ["-i", str(mp4), "-vn", "-c:a", "copy"])
    srt_path = saida / f"{nome} - {lang}.srt"
    srt_path.write_text(srt(proj, lang), encoding="utf-8")
    return {"mp4": str(mp4), "m4a": str(m4a), "srt": str(srt_path), "trilha": str(tp) if tp else None}


def _cli(ns, root: Path):
    proj = Path(ns.proj)
    if ns.cmd == "frases":
        ws = json.loads(Path(ns.words).read_text(encoding="utf-8-sig"))
        return frases(proj, ns.lang, ws), 0
    if ns.cmd == "validar":
        r = validar(proj, ns.lang, root=root)
        return r, (0 if r["ok"] else 1)
    if ns.cmd == "srt":
        s = srt(proj, ns.lang)
        Path(ns.saida).write_text(s, encoding="utf-8")
        return {"srt": ns.saida, "cues": s.count(" --> ")}, 0
    if ns.cmd == "words":
        return {"palavras": len(words(proj, ns.lang))}, 0
    if ns.cmd == "edl":
        return edl(proj, ns.lang), 0
    if ns.cmd == "tts":
        r = tts(proj, ns.lang, root=root, aprovacao=ns.aprovacao)
        return r, EXIT_ORCAMENTO.get(r["status"], 2)
    if ns.cmd == "encaixar":
        return encaixar(proj, ns.lang, audio.duracao(Path(ns.export))), 0
    if ns.cmd == "mixar":
        return mixar(proj, ns.lang, Path(ns.export), ns.nome, root=root, video=ns.video,
                     saida=ns.saida, trilha=ns.trilha), 0
    raise ValueError(f"comando desconhecido: {ns.cmd}")


def _parser():
    import argparse
    ap = argparse.ArgumentParser(description="dublagem e tradução")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frases"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--words", required=True)
    for c in ("validar", "words", "edl"):
        p = sub.add_parser(c); p.add_argument("proj"); p.add_argument("lang")
    p = sub.add_parser("srt"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--saida", required=True)
    p = sub.add_parser("tts"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--aprovacao", type=int)
    p = sub.add_parser("encaixar"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--export", required=True)
    p = sub.add_parser("mixar"); p.add_argument("proj"); p.add_argument("lang"); p.add_argument("--export", required=True)
    p.add_argument("--nome", required=True); p.add_argument("--video"); p.add_argument("--saida"); p.add_argument("--trilha")
    return ap, sub


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap, _ = _parser()
    ns = ap.parse_args()
    try:
        out, code = _cli(ns, Path(ns.root))
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
