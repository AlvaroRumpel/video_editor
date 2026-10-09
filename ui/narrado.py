"""Vídeo narrado (canal dark): episodio.json (cenas com texto, fontes e visual) →
TTS ElevenLabs por cena → cenas.<lang>.json do kit de motion em 16:9 → render →
voz mixada nos tempos medidos → <proj>/<lang>/final.mp4 + final.srt.
Substitui o fluxo bruto/*.mkv quando não há gravação."""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audio  # noqa: E402
import budget  # noqa: E402
import dublagem  # noqa: E402
import motion  # noqa: E402
import pesquisa  # noqa: E402
import pipeline  # noqa: E402

LANG_RE = re.compile(r"[a-z]{2}")
PAUSA = 0.4            # respiro depois da fala de cada cena
MAX_CHARS_CENA = 5000  # acima disso é erro de colagem, não cena
VISUAIS = ("arquivo", "motion", "ia")
LICENCA_RE = re.compile(
    r"^(public domain|domínio público|pd|pd-[\w.-]+|cc0|cc[ -]by(?:[ -]sa)?(?:[ -][\d.]+)?"
    r"|https?://creativecommons\.org/(?:publicdomain/(?:mark|zero)/[\d.]+|licenses/by(?:-sa)?/[\d.]+)/?)$",
    re.I)


def ler(proj: Path) -> dict:
    p = Path(proj) / "episodio.json"
    try:
        ep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise ValueError(f"{p} ausente ou inválido: {ex}") from None
    if not isinstance(ep, dict):
        raise ValueError(f"{p} não é um objeto")
    return ep


def licenca_ok(s) -> bool:
    return isinstance(s, str) and bool(LICENCA_RE.match(s.strip()))


def _loc(v, lang):
    """{"pt": "...", "en": "..."} → texto do idioma; recursivo em listas e objetos comuns.
    ponytail: objeto só com chaves de 2 letras é tratado como tradução; nenhum campo do kit é assim hoje."""
    if isinstance(v, dict):
        if v and all(isinstance(k, str) and LANG_RE.fullmatch(k) for k in v):
            return v.get(lang)
        return {k: _loc(x, lang) for k, x in v.items()}
    if isinstance(v, list):
        return [_loc(x, lang) for x in v]
    return v


def _achados(proj: Path) -> set | None:
    p = Path(proj) / "pesquisa.md"
    if not p.is_file():
        return None
    return {a["id"] for a in pesquisa.parse_pesquisa(p.read_text(encoding="utf-8-sig"))["achados"]}


def validar(ep: dict, proj: Path, lang: str) -> list[dict]:
    erros = []

    def e(i, m):
        erros.append({"id": i, "motivo": m})

    if not motion._str(ep.get("marca")):
        e("raiz", "falta marca (tema do motion)")
    if not motion._str(_loc(ep.get("titulo"), lang)):
        e("raiz", f"falta titulo.{lang}")
    cenas = ep.get("cenas")
    if not isinstance(cenas, list) or not cenas:
        e("raiz", "cenas vazio")
        return erros
    achados = _achados(proj)
    if achados is None:
        e("raiz", "falta pesquisa.md")
    vistos = set()
    for n, c in enumerate(cenas):
        i = c.get("id") if isinstance(c, dict) else None
        if not isinstance(i, str) or not motion.ID_RE.fullmatch(i):
            e(f"#{n}", f"id inválido: {i!r} (use cNN)")
            continue
        if i in vistos:
            e(i, "id duplicado")
        vistos.add(i)
        txt = _loc(c.get("texto"), lang)
        if not motion._str(txt):
            e(i, f"falta texto.{lang}")
        elif len(txt) > MAX_CHARS_CENA:
            e(i, f"texto.{lang} com {len(txt)} caracteres (máx. {MAX_CHARS_CENA}): dividir a cena")
        f = c.get("fontes")
        if not isinstance(f, list):
            e(i, "fontes precisa ser lista (vazia só em gancho/CTA)")
        elif achados is not None:
            for x in sorted(set(map(str, f)) - achados):
                e(i, f"fonte [{x}] não existe no pesquisa.md")
        v = c.get("visual") if isinstance(c.get("visual"), dict) else {}
        t = v.get("tipo")
        if t in ("arquivo", "ia"):
            if motion._dentro(proj, v.get("src")) is None:
                e(i, f"src não encontrado no projeto: {v.get('src')!r}")
            if t == "arquivo":
                if not licenca_ok(v.get("licenca")):
                    e(i, f"licença não aceita: {v.get('licenca')!r} (PD, CC0, CC BY, CC BY-SA)")
                if not motion._str(v.get("fonte_url")) or not motion._str(v.get("credito")):
                    e(i, "arquivo precisa de fonte_url e credito")
        elif t == "motion":
            if not isinstance(v.get("cena"), dict):
                e(i, "motion precisa de cena (objeto do kit)")
        else:
            e(i, f"visual.tipo inválido: {t!r} ({'|'.join(VISUAIS)})")
    return erros


def cenas_motion(ep: dict, lang: str, duracoes: dict, tema: dict) -> dict:
    """dur de cada cena = entrada (saída da anterior) + fala + PAUSA + própria saída: voz nunca acelera."""
    out, entra = [], 0.0
    cenas = ep["cenas"]
    for n, c in enumerate(cenas):
        v = c["visual"]
        if v["tipo"] == "motion":
            k = _loc(copy.deepcopy(v["cena"]), lang)
        else:
            k = {"tipo": "tela", "arquivo": v["src"], "moldura": "nenhuma", "kenburns": True}
            label = _loc(c.get("overlay"), lang)
            if label:
                k["label"] = label
        k = {"id": c["id"], **k}
        saida = 0.0 if n == len(cenas) - 1 else (k.get("saida") or tema["transicao_padrao"])["dur"]
        k["dur"] = round(entra + duracoes[c["id"]] + PAUSA + saida, 3)
        out.append(k)
        entra = saida
    return {"marca": ep["marca"], "aspecto": "16:9", "cenas": out}


def _dir(proj: Path, lang: str) -> Path:
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"idioma inválido: {lang!r} (2 letras minúsculas, ex.: pt)")
    return Path(proj) / lang


def estado(proj: Path, lang: str) -> dict:
    st = pipeline.read_json(_dir(proj, lang) / "narracao.json", {})
    return st if isinstance(st, dict) else {}


def tts(proj, lang, voice_id, root=None, aprovacao=None, _fetch=None) -> dict:
    """mp3 por cena só onde texto ou voz mudou. Valida e autoriza antes; registra o gasto mesmo se parar no meio."""
    root = Path(root or pipeline.ROOT)
    proj = Path(proj)
    if not motion._str(voice_id):
        raise ValueError("voice_id vazio: configurar canal/idiomas.json")
    ep = ler(proj)
    erros = validar(ep, proj, lang)
    if erros:
        return {"status": "invalido", "erros": erros}
    st = estado(proj, lang)
    pend = []
    for c in ep["cenas"]:
        txt = _loc(c["texto"], lang).strip()
        h = dublagem._hash(voice_id, txt)
        s = st.get(c["id"], {})
        if s.get("hash") != h or not (proj / s.get("audio", "-")).is_file():
            pend.append((c["id"], txt, h))
    if not pend:
        return {"status": "ok", "geradas": [], "caracteres": 0}
    chars = sum(len(t) for _, t, _ in pend)
    a = budget.autorizar(root, proj, "elevenlabs_tts", chars, aprovacao=aprovacao)
    if a["status"] != "ok":
        return {**a, "caracteres": chars, "pendentes": len(pend)}
    key = budget._chave_elevenlabs()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY ausente")
    fetch = _fetch or audio._fetch_elevenlabs
    url = dublagem.TTS_URL.format(voice_id=voice_id)
    pasta = _dir(proj, lang) / "audio"
    pasta.mkdir(parents=True, exist_ok=True)
    geradas, usados, erro = [], 0, None
    try:
        for cid, txt, h in pend:
            try:
                dados = fetch(key, url, {"text": txt, "model_id": dublagem.MODELO_TTS})
            except RuntimeError as ex:
                erro = str(ex)
                break
            usados += len(txt)          # crédito gasto no fetch: conta antes de gravar
            (pasta / f"{cid}.mp3").write_bytes(dados)
            rel = f"{lang}/audio/{cid}.mp3"
            st[cid] = {"hash": h, "audio": rel, "dur": round(audio.duracao(proj / rel), 3)}
            geradas.append(cid)
    finally:
        try:
            if usados:
                budget.registrar(proj, "elevenlabs_tts", usados, aprovacao=aprovacao,
                                 nota=f"narração {lang}: {len(geradas)} cenas", root=root)
        finally:
            pipeline.atomic_write_json(_dir(proj, lang) / "narracao.json", st)
    if erro:
        raise RuntimeError(f"TTS parou após {len(geradas)} cenas: {erro}")
    return {"status": "ok", "geradas": geradas, "caracteres": usados}
