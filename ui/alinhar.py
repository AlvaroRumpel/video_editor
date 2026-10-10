"""Alinhamento palavra a palavra: áudio da cena (faster-whisper, local) × texto do roteiro.
Saída: tempo de cada token do ROTEIRO (não da transcrição) em <proj>/<lang>/palavras.json,
para os beats do modo documental dispararem na palavra dita."""
import difflib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

MIN_CASADAS = 0.7
NUM = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
       "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
       "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
       "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
       "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
       "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500,
       "quinhentas": 500, "seiscentos": 600, "seiscentas": 600, "setecentos": 700, "setecentas": 700,
       "oitocentos": 800, "oitocentas": 800, "novecentos": 900, "novecentas": 900}
FIM_FRASE = re.compile(r"[.!?…]['\"”»)]*$")
PAUSA = re.compile(r"[.!?…,;:]['\"”»)]*$")
_MODELOS: dict = {}


def _base(w: str) -> str:
    s = unicodedata.normalize("NFD", w.lower())
    return re.sub(r"[^\w]", "", "".join(ch for ch in s if unicodedata.category(ch) != "Mn"))


def _normaliza(palavras) -> list[dict]:
    """[(bruta, a, b)] → [{"w", "a", "b", "fim"}]: base + números juntados ('trezentas e quarenta e uma' → '341',
    '3 mil' → '3000'). Não junta através de pontuação. `fim` = token termina frase."""
    seq = []
    for bruta, a, b in palavras:
        w = _base(bruta)
        if w:
            seq.append({"w": w, "a": a, "b": b, "pausa": bool(PAUSA.search(bruta.strip())),
                        "fim": bool(FIM_FRASE.search(bruta.strip()))})
    out, i = [], 0
    while i < len(seq):
        w = seq[i]["w"]
        if not (w in NUM or w.isdigit() or w == "mil"):
            out.append({k: seq[i][k] for k in ("w", "a", "b", "fim")})
            i += 1
            continue
        total, cur, j = 0, 0, i
        while j < len(seq):
            t = seq[j]["w"]
            if j > i and seq[j - 1]["pausa"]:
                break
            if t in NUM:
                cur += NUM[t]
            elif t.isdigit() and j == i:
                cur += int(t)
            elif t == "mil":
                total += max(cur, 1) * 1000
                cur = 0
            elif t == "e" and j > i and j + 1 < len(seq) and seq[j + 1]["w"] in NUM and not seq[j]["pausa"]:
                pass
            else:
                break
            j += 1
        out.append({"w": str(total + cur), "a": seq[i]["a"], "b": seq[j - 1]["b"], "fim": seq[j - 1]["fim"]})
        i = j
    return out


def tokens(texto: str) -> list[dict]:
    n = _normaliza([(w, k, k) for k, w in enumerate(texto.split())])
    return [{"w": t["w"], "frase": k == 0 or n[k - 1]["fim"]} for k, t in enumerate(n)]


def casar(texto: str, transcricao) -> list[dict]:
    rot = _normaliza([(w, k, k) for k, w in enumerate(texto.split())])
    tra = _normaliza(transcricao)
    A, B = [t["w"] for t in rot], [t["w"] for t in tra]
    tempos: list = [None] * len(A)
    for i, j, n in difflib.SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks():
        for k in range(n):
            tempos[i + k] = (float(tra[j + k]["a"]), float(tra[j + k]["b"]))
    casadas = sum(t is not None for t in tempos)
    if not A or casadas / len(A) < MIN_CASADAS:
        raise ValueError(f"só {casadas}/{len(A)} palavras casadas com a fala (mín. {MIN_CASADAS:.0%}): "
                         f"áudio truncado ou texto mudou depois do TTS")
    k = 0
    while k < len(A):                  # palavras sem par: tempo dividido entre as vizinhas casadas
        if tempos[k] is not None:
            k += 1
            continue
        j = k
        while j < len(A) and tempos[j] is None:
            j += 1
        ini = tempos[k - 1][1] if k > 0 else float(tra[0]["a"])
        fim = tempos[j][0] if j < len(A) else float(tra[-1]["b"])
        passo = max(fim - ini, 0.0) / (j - k)
        for m in range(k, j):
            tempos[m] = (ini + passo * (m - k), ini + passo * (m - k + 1))
        k = j
    return [{"w": A[i], "s": round(tempos[i][0], 3), "e": round(tempos[i][1], 3)} for i in range(len(A))]


def nomes(texto: str) -> str:
    """Palavras com maiúscula do roteiro (nomes próprios e inícios de frase), sem repetir: vocabulário para o
    whisper. Não passar o texto inteiro: como initial_prompt ele vira "fala anterior" e o modelo pula trechos."""
    return ", ".join(sorted(set(re.findall(r"\b[A-ZÀ-Ý][\wÀ-ÿ'-]*", texto or ""))))


def transcrever(mp3: Path, lang: str, modelo: str = "small", prompt: str | None = None) -> list:
    """prompt: texto esperado (o roteiro da cena) para o whisper reconhecer nomes próprios."""
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper não instalado: pip install -r ui/requirements.txt") from None
    # decodifica com ffmpeg: faster_whisper.decode_audio quebra com o `av` instalado
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if modelo not in _MODELOS:
        try:
            _MODELOS[modelo] = WhisperModel(modelo, device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001 — download/rede: mensagem acionável
            raise RuntimeError(f"modelo whisper '{modelo}' indisponível ({e}); na 1ª vez precisa de rede "
                               f"para baixar ~460 MB: rode `python ui/narrado.py alinhar <proj>` com internet") from None
    segs, _ = _MODELOS[modelo].transcribe(a, language=lang, word_timestamps=True, initial_prompt=prompt)
    return [(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or [])]


def alinhar(proj: Path, lang: str, _transcrever=None) -> dict:
    import narrado   # import tardio: narrado importa alinhar
    proj = Path(proj)
    ep, st = narrado.ler(proj), narrado.estado(proj, lang)
    dst = narrado._dir(proj, lang) / "palavras.json"
    cache = pipeline.read_json(dst, {})
    cache = cache if isinstance(cache, dict) else {}
    faltam = [c["id"] for c in ep["cenas"] if not st.get(c["id"])]
    if faltam:
        raise ValueError(f"rode tts antes: sem áudio em {', '.join(faltam)}")
    tr, feitas = _transcrever or transcrever, []
    for c in ep["cenas"]:
        s = st[c["id"]]
        if cache.get(c["id"], {}).get("hash") == s["hash"]:
            continue
        try:
            texto = narrado._loc(c["texto"], lang)
            try:
                pal = casar(texto, tr(proj / s["audio"], lang))
            except ValueError:   # nome próprio mal ouvido: repete com os nomes como vocabulário
                pal = casar(texto, tr(proj / s["audio"], lang, prompt=nomes(texto)))
        except ValueError as e:
            raise ValueError(f"{c['id']}: {e}") from None
        cache[c["id"]] = {"hash": s["hash"], "palavras": pal}
        pipeline.atomic_write_json(dst, cache)
        feitas.append(c["id"])
    return {"ok": True, "alinhadas": feitas}
