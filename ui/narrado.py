"""Vídeo narrado (canal dark): episodio.json (cenas com texto, fontes e visual) →
TTS por cena (Google Cloud ou ElevenLabs) → cenas.<lang>.json do kit de motion em 16:9 → render →
voz mixada nos tempos medidos → <proj>/<lang>/final.mp4 + final.srt.
Substitui o fluxo bruto/*.mkv quando não há gravação."""
import base64
import copy
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audio  # noqa: E402
import budget  # noqa: E402
import dublagem  # noqa: E402
import motion  # noqa: E402
import pesquisa  # noqa: E402
import pipeline  # noqa: E402
import alinhar  # noqa: E402

LANG_RE = re.compile(r"[a-z]{2}")
PAUSA = 0.4            # respiro depois da fala de cada cena
VINHETA_DUR = 4.0
TELAFINAL_DUR = 20.0
TEXTOS_FIM = {"pt": {"prox": "Próxima história", "inscreva": "inscreva-se", "video": "próximo vídeo"},
              "en": {"prox": "Next story", "inscreva": "subscribe", "video": "next video"}}
SFX_DIR = pipeline.ROOT / "motion" / "sfx"
MAX_CHARS_CENA = 5000  # acima disso é erro de colagem, não cena
VISUAIS = ("arquivo", "motion", "ia")
FAZ = {"camera": (), "rota": ("de", "para"), "ponto": ("ponto",), "contador": ("valor",), "data": ("t",),
       "rotulo": ("nome",), "palavras": ("palavras",), "citacao": ("t", "autor"), "lista": ("itens",),
       "linha_tempo": ("marcos",), "inserto": ("src", "fonte_url", "licenca", "credito"), "selo": (),
       "acao": ("modelo",)}
FUNDOS_DOC = ("mapa", "imagem", "escuro")
MODELOS_ACAO = {"olha": ("ator", "alvo"), "fala": ("ator", "alvo"), "telegrama": (), "le": ("ator",),
                "aponta": ("ator", "alvo"), "sobe_a_bordo": ("ator",), "anda": ("ator", "para")}
TRAJES = ("capitao", "inspetor", "medico", "secretaria", "menino", "marinheiro", "civil")
LADOS_ACAO = ("esq", "centro", "dir")
DUR_ACAO = {"olha": 3.2, "fala": 3.6, "telegrama": 3.8, "le": 3.2, "aponta": 2.8, "sobe_a_bordo": 4.0, "anda": 3.0}   # = DUR de acoes.js
DUR_MIN_ACAO = {"sobe_a_bordo": 3.0, "anda": 2.6}
RITMO_MAX = 6.0   # s de fala sem beat nem troca de cena
GOOGLE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
GOOGLE_MAX_BYTES = 5000           # limite do Google por requisição (texto em UTF-8)
PROVEDORES = {"elevenlabs": "elevenlabs_tts", "google": "google_tts"}   # provedor → chave do precos.json
ENV_FILE = pipeline.ROOT / "video-use" / ".env"
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


def _v_arquivo(d: dict, proj: Path, err) -> None:
    """Imagem de arquivo (src no projeto + licença aceita + fonte_url + credito)."""
    if not motion._rel_ok(d.get("src")):
        err(f"src precisa ser caminho relativo sem '..': {d.get('src')!r}")
    elif motion._dentro(proj, d.get("src")) is None:
        err(f"src não encontrado no projeto: {d.get('src')!r}")
    if not licenca_ok(d.get("licenca")):
        err(f"licença não aceita: {d.get('licenca')!r} (PD, CC0, CC BY, CC BY-SA)")
    if not motion._str(d.get("fonte_url")) or not motion._str(d.get("credito")):
        err("arquivo precisa de fonte_url e credito")


def _acha(ws: list[str], palavra: str, depois: int = 0) -> int | None:
    """Índice do token `palavra` (aceita 'água#2' = 2ª ocorrência) em ws, a partir de `depois`."""
    base, _, n = str(palavra).partition("#")
    alvo = alinhar.tokens(base)
    if not alvo:
        return None
    vez = int(n) if n.isdigit() else 1
    for k in range(depois, len(ws)):
        if ws[k] == alvo[0]["w"]:
            vez -= 1
            if vez == 0:
                return k
    return None


def _acha_frase(ws: list[str], palavras: list[str], depois: int = 0) -> list[int] | None:
    """Índices dos tokens de `palavras` como trecho CONTÍGUO de ws, a partir de `depois` (1ª ocorrência)."""
    alvo = []
    for w in palavras:
        t = alinhar.tokens(str(w))
        if not t:
            return None
        alvo.append(t[0]["w"])
    for k in range(depois, len(ws) - len(alvo) + 1):
        if ws[k:k + len(alvo)] == alvo:
            return list(range(k, k + len(alvo)))
    return None


def _inicios(c: dict, lang: str) -> list:
    """Token de início de cada beat (regra única de validar e resolver_beats): `em` → _acha;
    sem `em`: 1º beat = 0, depois início da frase seguinte ao beat anterior (ou o mesmo token).
    None quando `em` não está no texto ou o beat é inválido."""
    toks = alinhar.tokens(_loc(c.get("texto"), lang) or "")
    ws = [t["w"] for t in toks]
    frases = [k for k, t in enumerate(toks) if t["frase"]]
    out, ult = [], -1
    for b in c.get("beats") or []:
        if not isinstance(b, dict):
            out.append(None)
            continue
        if b.get("em"):
            k = _acha(ws, _loc(b["em"], lang) if isinstance(b["em"], dict) else b["em"])
        elif ult < 0:
            k = 0
        else:
            k = next((f for f in frases if f > ult), ult)
        if k is not None:
            ult = k
        out.append(k)
    return out


def _com_frase(b: dict, lang: str) -> dict:
    """Beat `palavras` com `frase`: `palavras` passa a ser as palavras da frase, como escritas (validar e resolver)."""
    fr = _loc(b["frase"], lang)
    return {**b, "palavras": fr.split() if isinstance(fr, str) else fr}


def avisos_direcao(ep: dict, lang: str) -> list[str]:
    out = []
    for c in ep.get("cenas") or []:
        for b in c.get("beats") or []:
            if isinstance(b, dict) and b.get("faz") == "palavras" and "frase" not in b:
                pal = _loc(b.get("palavras"), lang)
                if isinstance(pal, list) and len(pal) < 4:
                    out.append(f"{c['id']}: palavras soltas ({' '.join(map(str, pal))}); prefira frase da fala")
    return out


def _v_acao(b: dict, ep: dict, lang: str, e) -> None:
    m = b.get("modelo")
    if m not in MODELOS_ACAO:
        return e(f"modelo desconhecido: {m!r} ({'|'.join(MODELOS_ACAO)})")
    atores = ep.get("atores") if isinstance(ep.get("atores"), dict) else {}
    for campo in MODELOS_ACAO[m]:
        if campo not in b:
            e(f"{m} precisa de {campo}")
    for campo in ("ator", "alvo"):
        if campo in b and not (isinstance(b[campo], str) and b[campo] in atores):
            e(f"{campo} {b[campo]!r} não existe em atores")
    if b.get("lado", "dir") not in LADOS_ACAO:
        e(f"lado inválido: {b.get('lado')!r} ({'|'.join(LADOS_ACAO)})")
    for campo in ("de", "para"):
        if campo in b and b[campo] not in LADOS_ACAO:
            e(f"{campo} precisa ser {'|'.join(LADOS_ACAO)}")
    if m == "anda" and b.get("de", "esq") == b.get("para"):
        e("anda com de e para iguais")
    esc = b.get("escala", 1)
    if isinstance(esc, bool) or not isinstance(esc, (int, float)) or not 0.6 <= esc <= 1.2:
        e("escala precisa estar entre 0,6 e 1,2")
    d = b.get("dur")
    if d is not None and (isinstance(d, bool) or not isinstance(d, (int, float)) or not 1 <= d <= 8):
        e("dur precisa estar entre 1 e 8 s")
    elif d is not None and d < DUR_MIN_ACAO.get(m, 0):
        e(f"dur mínima de {m}: {DUR_MIN_ACAO[m]} s")
    t = _loc(b.get("texto"), lang)
    if isinstance(t, str) and len(t) > 40:
        e("texto da ação com até 40 caracteres")


def _v_direcao(ep: dict, c: dict, proj: Path, lang: str, e) -> None:
    mapa = ep.get("mapa") if isinstance(ep.get("mapa"), dict) else {}
    pontos = mapa.get("pontos") if isinstance(mapa.get("pontos"), dict) else {}
    i = c["id"]
    f = c.get("fundo")
    no_mapa = isinstance(f, dict) and f.get("tipo") == "mapa"
    if f is not None:
        t = f.get("tipo") if isinstance(f, dict) else None
        if t not in FUNDOS_DOC:
            e(i, f"fundo.tipo inválido: {t!r} ({'|'.join(FUNDOS_DOC)})")
        elif t == "mapa" and not pontos:
            e(i, "fundo mapa sem 'mapa' com pontos no episódio")
        elif t == "imagem":
            _v_arquivo(f, proj, lambda m: e(i, "fundo: " + m))
    ws = [t["w"] for t in alinhar.tokens(_loc(c.get("texto"), lang) or "")]
    beats = c.get("beats")
    if beats is None:
        return
    if not isinstance(beats, list):
        e(i, "beats precisa ser lista")
        return
    ini = _inicios(c, lang)
    for k, b in enumerate(beats, 1):
        q = f"{i} beat {k}"
        if not isinstance(b, dict) or b.get("faz") not in FAZ:
            e(q, f"faz desconhecido: {(b.get('faz') if isinstance(b, dict) else b)!r} ({'|'.join(FAZ)})")
            continue
        if isinstance(b.get("palavras"), dict):     # {"pt": [...], "en": [...]}, como em resolver_beats
            b = {**b, "palavras": _loc(b["palavras"], lang)}
        if b["faz"] == "palavras" and "frase" in b:
            if not isinstance(_loc(b["frase"], lang), str):
                e(q, "frase precisa ser texto")
                continue
            b = _com_frase(b, lang)
            if len(b["palavras"]) > 10:
                e(q, "frase com mais de 10 palavras (use citacao)")
                continue
            b["_frase"] = True
        for campo in FAZ[b["faz"]]:
            if campo not in b:
                e(q, f"{b['faz']} precisa de {campo}")
        if b["faz"] == "acao":
            _v_acao(b, ep, lang, lambda m, q=q: e(q, m))
        tipo_ruim = [x for x in ("itens", "marcos", "palavras", "via") if x in b and not isinstance(b[x], list)]
        tipo_ruim += [x for x in ("de", "para", "ponto") if x in b and not isinstance(b[x], str)]
        tipo_ruim += [x for x in ("palavras", "via") if isinstance(b.get(x), list) and not all(isinstance(w, str) for w in b[x])]
        tipo_ruim += [x for x in ("itens", "marcos") if isinstance(b.get(x), list)
                      and not all(isinstance(w, (str, dict)) for w in b[x])]
        if tipo_ruim:
            for x in dict.fromkeys(tipo_ruim):
                e(q, f"{x} com tipo inválido (listas: itens, marcos, palavras, via; textos: de, para, ponto)")
            continue
        if (b["faz"] in ("rota", "ponto") or (b["faz"] == "camera" and "para" in b)) and not no_mapa:
            e(q, f"{b['faz']} só em cena com fundo mapa")
        for nome in ([] if b["faz"] == "acao" else [b.get(x) for x in ("de", "para", "ponto")] + b.get("via", [])):
            if nome is not None and nome not in pontos:
                e(q, f"ponto {nome!r} não existe no mapa")
        sub = [x for x in (b.get("itens") or []) + (b.get("marcos") or []) if isinstance(x, dict)]
        for w in [b.get("em")] + [x.get("em") for x in sub]:
            w = _loc(w, lang)
            if w and _acha(ws, w) is None:
                e(q, f"palavra {w!r} não está no texto da cena")
        d, ks = ini[k - 1], []
        for w in (b.get("palavras") or []) if d is not None else []:
            d = _acha(ws, w, d)
            if d is None:
                e(q, f"palavra {w!r} não está no texto da cena (na ordem do beat)")
                break
            ks.append(d)
            d += 1
        if b.get("_frase") and len(ks) == len(b["palavras"]) and ini[k - 1] is not None                 and _acha_frase(ws, b["palavras"], ini[k - 1]) is None:
            e(q, "frase precisa ser trecho contíguo da fala")
        if b["faz"] == "contador" and b.get("pontos") and not (
                isinstance(b.get("valor"), int) and not isinstance(b["valor"], bool) and 0 < b["valor"] <= 500):
            e(q, "pontos só com valor inteiro entre 1 e 500")
        if b["faz"] == "inserto":
            _v_arquivo(b, proj, lambda m, q=q: e(q, m))


def validar(ep: dict, proj: Path, lang: str, visuais: bool = True) -> list[dict]:
    """visuais=False: só texto e fontes (TTS roda antes de escolher as imagens)."""
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
    if ep.get("aspecto", "16:9") not in motion.ASPECTOS:
        e("raiz", f"aspecto inválido: {ep.get('aspecto')!r} (9:16 ou 16:9)")
    td = ep.get("tela_final_dur")
    if td is not None and not (motion._num(td) and 1 <= td <= TELAFINAL_DUR):
        e("raiz", f"tela_final_dur inválido: {td!r} (1 a {TELAFINAL_DUR:g} s)")
    if visuais and "mapa" in ep:
        m = ep["mapa"]
        if not isinstance(m, dict) or not isinstance(m.get("pontos"), dict) or not m["pontos"] or not all(
                isinstance(v, list) and len(v) == 2 and all(motion._num(x) for x in v) for v in m["pontos"].values()):
            e("mapa", "mapa precisa de pontos {nome: [x, y]} em pixels do arquivo")
        if isinstance(m, dict):
            _v_arquivo(m, proj, lambda msg: e("mapa", msg))
    at = ep.get("atores")
    if at is not None:
        if not isinstance(at, dict):
            e("atores", "atores precisa ser objeto {nome: {traje}}")
        else:
            for nome, a in at.items():
                tj = a.get("traje") if isinstance(a, dict) else None
                lista = tj if isinstance(tj, list) else [tj]
                if not 1 <= len(lista) <= 3 or not all(x in TRAJES for x in lista):
                    e("atores", f"{nome}: traje inválido {tj!r} ({'|'.join(TRAJES)}; lista de até 3)")
    ids = {c.get("id") for c in cenas if isinstance(c, dict)}
    if "vinheta_apos" in ep and ep["vinheta_apos"] not in ids:
        e("raiz", f"vinheta_apos aponta para cena inexistente: {ep['vinheta_apos']!r}")
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
        if not visuais:
            continue
        _v_direcao(ep, c, proj, lang, e)
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


def _ach(ws, w, c, depois=0):
    k = _acha(ws, w, depois)
    if k is None:
        raise ValueError(f"{c['id']}: palavra {w!r} não encontrada no texto (rode validar)")
    return k


def resolver_beats(c: dict, lang: str, palavras: dict) -> list[dict]:
    """Beats da cena localizados, com "s" = segundos desde o início da fala da cena.
    Sem "em": início da frase seguinte à do beat anterior (1º beat: início da fala)."""
    ws = [t["w"] for t in alinhar.tokens(_loc(c["texto"], lang))]
    pal = palavras[c["id"]]["palavras"]
    out = []
    for b, k in zip(c.get("beats", []), _inicios(c, lang)):
        b = _loc(copy.deepcopy(b), lang)
        if k is None:
            raise ValueError(f"{c['id']}: palavra {b.get('em')!r} não encontrada no texto (rode validar)")
        b["s"] = pal[k]["s"]
        if b["faz"] == "palavras" and "frase" in b:
            b["palavras"] = b["frase"].split()
            idx = _acha_frase(ws, b["palavras"], k)
            if idx is None:
                raise ValueError(f"{c['id']}: frase {b['frase']!r} não é trecho contíguo da fala (rode validar)")
            b["s"] = pal[idx[0]]["s"]
            b["ts"] = [pal[i]["s"] for i in idx]
        elif b["faz"] == "palavras":
            ts, d = [], k
            for w in b["palavras"]:
                d = _ach(ws, w, c, d)
                ts.append(pal[d]["s"])
                d += 1
            b["ts"] = ts
        for lst in ("itens", "marcos"):
            for it in b.get(lst) or []:
                if isinstance(it, dict) and it.get("em"):
                    it["s"] = pal[_ach(ws, it["em"], c)]["s"]
        out.append(b)
    return out


def ritmo(cid: str, beats: list[dict], dur: float) -> list[str]:
    sub = [x["s"] for b in beats for k in ("itens", "marcos") for x in b.get(k) or [] if isinstance(x, dict) and "s" in x]
    ts = sorted({0.0, float(dur), *(b["s"] for b in beats), *(t for b in beats for t in b.get("ts", [])), *sub})
    return [f"{cid}: {a:.1f}–{b:.1f} s sem beat" for a, b in zip(ts, ts[1:]) if b - a > RITMO_MAX]


def sobrepostas(cid: str, beats: list[dict]) -> list[str]:
    """Avisa quando duas `acao` ocupam o mesmo lado ao mesmo tempo (duração = dur ou padrão do modelo)."""
    ac = sorted((b for b in beats if b.get("faz") == "acao" and b.get("modelo") in DUR_ACAO), key=lambda b: b["s"])
    out = []
    for i, a in enumerate(ac):
        fim = a["s"] + (a.get("dur") or DUR_ACAO[a["modelo"]])
        for b in ac[i + 1:]:
            if b["s"] < fim and a.get("lado", "dir") == b.get("lado", "dir"):
                out.append(f"{cid}: acao {a['modelo']} e {b['modelo']} sobrepostas no lado {a.get('lado', 'dir')}")
    return out


def modo_doc(ep: dict) -> bool:
    cenas = ep.get("cenas")
    return isinstance(cenas, list) and any(isinstance(c, dict) and c.get("beats") for c in cenas)


def _palco(c: dict) -> dict | None:
    f = c.get("fundo")
    if f:
        return {"tipo": "imagem", "arquivo": f["src"]} if f["tipo"] == "imagem" else {"tipo": f["tipo"]}
    v = c["visual"]
    return {"tipo": "imagem", "arquivo": v["src"]} if v["tipo"] in ("arquivo", "ia") else None


def _beat_kit(b: dict) -> dict:
    k = {key: v for key, v in b.items() if key != "em"}
    if k["faz"] == "inserto":
        k["arquivo"] = k.pop("src")
        for x in ("fonte_url", "licenca", "credito"):
            k.pop(x, None)
    for lst in ("itens", "marcos"):
        if lst in k:
            k[lst] = [{"t": x} if isinstance(x, str) else {kk: vv for kk, vv in x.items() if kk != "em"} for x in k[lst]]
    return k


def _transicao(a: dict, b: dict) -> dict:
    if a["tipo"] == "vinheta":          # a saída em zoom da vinheta pede 0.6 s de sobreposição
        return {"transicao": "fade", "dur": 0.6}
    pa = a.get("palco", {}).get("tipo") if a["tipo"] == "doc" else a["tipo"]
    pb = b.get("palco", {}).get("tipo") if b["tipo"] == "doc" else b["tipo"]
    if pa == "mapa" and pb == "imagem":
        return {"transicao": "mergulho", "dur": 0.6}
    if pa == "imagem" and pb == "mapa":
        return {"transicao": "recuo", "dur": 0.6}
    if pa == pb == "imagem":
        return {"transicao": "corte", "dur": 0.1}
    return {"transicao": "fade", "dur": 0.3}


def _cenas_doc(ep: dict, lang: str, duracoes: dict, palavras: dict) -> dict:
    lista = []
    for c in ep["cenas"]:
        p = _palco(c)
        if p is None and not c.get("beats"):
            k = _loc(copy.deepcopy(c["visual"]["cena"]), lang)          # cartão motion antigo
        else:
            beats = [_beat_kit(b) for b in resolver_beats(c, lang, palavras)] if c.get("beats") else []
            label = _loc(c.get("overlay"), lang)
            if label and not any(b["faz"] == "rotulo" for b in beats):
                beats.append({"faz": "rotulo", "nome": label, "s": 0.3})
            k = {"tipo": "doc", "fundo": "escuro", "palco": p or {"tipo": "escuro"}, "beats": beats}
        k = {"id": c["id"], **k, "_fala": duracoes[c["id"]], "_saida": c.get("saida")}
        lista.append(k)
        if c["id"] == ep.get("vinheta_apos"):
            titulo = _loc(ep.get("titulo_curto"), lang) or _loc(ep.get("titulo"), lang) or ""
            lista.append({"id": "c900", "tipo": "vinheta", "fundo": "escuro", "titulo": titulo, "_fala": None})
    lista.append({"id": "c901", "tipo": "telafinal", "fundo": "escuro",
                  "textos": TEXTOS_FIM.get(lang, TEXTOS_FIM["pt"]), "_fala": None})
    for n, k in enumerate(lista[:-1]):
        k["saida"] = k.get("_saida") or _transicao(k, lista[n + 1])
    tela = ep.get("tela_final_dur", TELAFINAL_DUR)
    for n, k in enumerate(lista):
        entra = lista[n - 1]["saida"]["dur"] if n else 0.0
        sai = k["saida"]["dur"] if "saida" in k else 0.0
        fala = k.pop("_fala")
        k.pop("_saida", None)
        corpo = fala + PAUSA if fala is not None else (VINHETA_DUR if k["tipo"] == "vinheta" else tela)
        k["dur"], k["dur_piso"] = round(entra + corpo + sai, 3), True
    d = {"marca": ep["marca"], "aspecto": ep.get("aspecto", "16:9"), "modo": "doc", "cenas": lista}
    if ep.get("mapa"):
        d["mapa"] = {"arquivo": ep["mapa"]["src"], "pontos": ep["mapa"]["pontos"]}
    if ep.get("atores"):
        d["atores"] = _loc(copy.deepcopy(ep["atores"]), lang)
    return d


def cenas_motion(ep: dict, lang: str, duracoes: dict, tema: dict, palavras: dict | None = None) -> dict:
    """dur de cada cena = entrada (saída da anterior) + fala + PAUSA + própria saída: voz nunca acelera."""
    if modo_doc(ep):
        return _cenas_doc(ep, lang, duracoes, palavras or {})
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
        k["dur_piso"] = True     # fala curta: o kit estica até o mínimo da animação; a voz segue os tempos medidos
        out.append(k)
        entra = saida
    return {"marca": ep["marca"], "aspecto": ep.get("aspecto", "16:9"), "cenas": out}


def _dir(proj: Path, lang: str) -> Path:
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"idioma inválido: {lang!r} (2 letras minúsculas, ex.: pt)")
    return Path(proj) / lang


def estado(proj: Path, lang: str) -> dict:
    st = pipeline.read_json(_dir(proj, lang) / "narracao.json", {})
    return st if isinstance(st, dict) else {}


def _palavras(proj: Path, lang: str, ep: dict, st: dict) -> dict:
    pal = pipeline.read_json(_dir(proj, lang) / "palavras.json", {})
    velhas = [c["id"] for c in ep["cenas"] if pal.get(c["id"], {}).get("hash") != st.get(c["id"], {}).get("hash")]
    if velhas:
        raise ValueError(f"rode alinhar antes: palavras ausentes ou desatualizadas em {', '.join(velhas)}")
    return pal


def _chave(nome: str) -> str:
    v = os.environ.get(nome, "")
    if v:
        return v
    try:
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, val = ln.partition("=")
            if k.strip() == nome:
                return val.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _fetch_google(key: str, url: str, body: dict) -> bytes:
    """Chave no header (nunca na URL); resposta traz o áudio em base64."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"X-Goog-Api-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return base64.b64decode(json.loads(r.read())["audioContent"])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google TTS HTTP {e.code}: {e.read()[:300]!r}") from e
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        raise RuntimeError(f"Google TTS falhou: {e}") from e


TRATAMENTO_CHAVES = ("tom", "graves_db", "agudos_db")


def _checa_tratamento(tr) -> None:
    if tr is None:
        return
    if not isinstance(tr, dict):
        raise ValueError("tratamento precisa ser objeto")
    for k, v in tr.items():
        if k not in TRATAMENTO_CHAVES:
            raise ValueError(f"tratamento: chave desconhecida {k!r} ({', '.join(TRATAMENTO_CHAVES)})")
        if not motion._num(v, float("-inf")) or abs(v) > (6 if k == "tom" else 12):
            raise ValueError(f"tratamento: {k} inválido: {v!r} (tom ±6 semitons, dB ±12)")


def _filtro(tr: dict) -> str:
    """Voz de narrador: tom (semitons, sem mudar a duração), EQ e compressão leve."""
    f = ["aresample=48000"]
    tom = tr.get("tom", 0)
    if tom:
        r = 2 ** (tom / 12)
        f += [f"asetrate=48000*{r:.6f}", "aresample=48000", f"atempo={1 / r:.6f}"]
    if tr.get("graves_db"):
        f.append(f"bass=g={tr['graves_db']}:f=140:w=0.8")
    if tr.get("agudos_db"):
        f.append(f"treble=g={tr['agudos_db']}:f=7000")
    f.append("acompressor=threshold=-22dB:ratio=3:attack=8:release=180:makeup=2")
    return ",".join(f)


def perfil(path: Path, lang: str) -> dict:
    """Configuração de voz do idioma no canal (canal/idiomas.json) → kwargs do tts."""
    d = pipeline.read_json(Path(path), {})
    c = d.get(lang) if isinstance(d, dict) else None
    if not isinstance(c, dict) or not motion._str(c.get("voz")):
        raise ValueError(f"{path}: idioma {lang} sem 'voz' configurada")
    return {"voice_id": c["voz"], "provedor": c.get("provedor", "elevenlabs"),
            "velocidade": c.get("velocidade"), "tratamento": c.get("tratamento")}


def tts(proj, lang, voice_id, root=None, aprovacao=None, _fetch=None, provedor="elevenlabs",
        velocidade=None, tratamento=None) -> dict:
    """mp3 por cena só onde texto, voz ou provedor mudou. Valida e autoriza antes; registra o gasto mesmo se parar no meio."""
    root = Path(root or pipeline.ROOT)
    proj = Path(proj)
    if provedor not in PROVEDORES:
        raise ValueError(f"provedor desconhecido: {provedor!r} ({'|'.join(PROVEDORES)})")
    if not motion._str(voice_id):
        raise ValueError("voz vazia: configurar canal/idiomas.json")
    if velocidade is not None and (provedor != "google" or not motion._num(velocidade) or not 0.25 <= velocidade <= 2):
        raise ValueError(f"velocidade inválida: {velocidade!r} (só no google, entre 0.25 e 2)")
    _checa_tratamento(tratamento)
    voz = voice_id if provedor == "elevenlabs" else f"{provedor}:{voice_id}"   # entra no hash do cache
    if velocidade is not None or tratamento:
        voz += "|" + json.dumps({"v": velocidade, "t": tratamento}, sort_keys=True)
    ep = ler(proj)
    erros = validar(ep, proj, lang, visuais=False)
    if provedor == "google":
        erros += [{"id": c["id"], "motivo": f"texto.{lang} passa de {GOOGLE_MAX_BYTES} bytes (limite do Google): dividir a cena"}
                  for c in ep.get("cenas", []) if isinstance(c, dict)
                  and len((_loc(c.get("texto"), lang) or "").strip().encode("utf-8")) > GOOGLE_MAX_BYTES]
    if erros:
        return {"status": "invalido", "erros": erros}
    st = estado(proj, lang)
    pend = []
    for c in ep["cenas"]:
        txt = _loc(c["texto"], lang).strip()
        h = dublagem._hash(voz, txt)
        s = st.get(c["id"], {})
        if s.get("hash") != h or not (proj / s.get("audio", "-")).is_file():
            pend.append((c["id"], txt, h))
    if not pend:
        return {"status": "ok", "geradas": [], "caracteres": 0}
    chars = sum(len(t) for _, t, _ in pend)
    a = budget.autorizar(root, proj, PROVEDORES[provedor], chars, aprovacao=aprovacao)
    if a["status"] != "ok":
        return {**a, "caracteres": chars, "pendentes": len(pend)}
    if provedor == "google":
        key, nome_chave = _chave("GOOGLE_TTS_API_KEY"), "GOOGLE_TTS_API_KEY"
        fetch, url = _fetch or _fetch_google, GOOGLE_URL
        corpo = lambda txt: {"input": {"text": txt},     # noqa: E731
                             "voice": {"languageCode": "-".join(voice_id.split("-")[:2]), "name": voice_id},
                             "audioConfig": {"audioEncoding": "MP3",
                                             **({"speakingRate": velocidade} if velocidade is not None else {})}}
    else:
        key, nome_chave = budget._chave_elevenlabs(), "ELEVENLABS_API_KEY"
        fetch, url = _fetch or audio._fetch_elevenlabs, dublagem.TTS_URL.format(voice_id=voice_id)
        corpo = lambda txt: {"text": txt, "model_id": dublagem.MODELO_TTS}   # noqa: E731
    if not key:
        raise RuntimeError(f"{nome_chave} ausente (ambiente ou video-use/.env)")
    pasta = _dir(proj, lang) / "audio"
    pasta.mkdir(parents=True, exist_ok=True)
    geradas, usados, erro = [], 0, None
    try:
        for cid, txt, h in pend:
            try:
                dados = fetch(key, url, corpo(txt))
            except RuntimeError as ex:
                erro = str(ex)
                break
            usados += len(txt)          # crédito gasto no fetch: conta antes de gravar
            if tratamento:
                cru = pasta / f"{cid}.cru.mp3"
                cru.write_bytes(dados)
                try:
                    _ff(["-i", str(cru), "-af", _filtro(tratamento), "-c:a", "libmp3lame", "-q:a", "2",
                         str(pasta / f"{cid}.mp3")])
                finally:
                    cru.unlink(missing_ok=True)
            else:
                (pasta / f"{cid}.mp3").write_bytes(dados)
            rel = f"{lang}/audio/{cid}.mp3"
            st[cid] = {"hash": h, "voz": voz, "audio": rel, "dur": round(audio.duracao(proj / rel), 3)}
            geradas.append(cid)
    finally:
        try:
            if usados:
                budget.registrar(proj, PROVEDORES[provedor], usados, aprovacao=aprovacao,
                                 nota=f"narração {lang}: {len(geradas)} cenas", root=root)
        finally:
            pipeline.atomic_write_json(_dir(proj, lang) / "narracao.json", st)
    if erro:
        raise RuntimeError(f"TTS parou após {len(geradas)} cenas: {erro}")
    return {"status": "ok", "geradas": geradas, "caracteres": usados}


def offsets(tempos: dict) -> dict:
    """Fala de cada cena começa quando a transição de entrada termina."""
    out, entra = {}, 0.0
    for c in tempos["cenas"]:
        out[c["id"]] = round(c["ini"] + entra, 3)
        entra = c["saida"] or 0.0
    return out


def srt(ep: dict, lang: str, tempos: dict, st: dict) -> str:
    """Blocos de até 2 linhas de 42 caracteres; tempo da fala da cena dividido pelo tamanho de cada bloco."""
    off, blocos = offsets(tempos), []
    for c in ep["cenas"]:
        linhas = dublagem._linhas(" ".join(_loc(c["texto"], lang).split()))
        partes = ["\n".join(linhas[k:k + 2]) for k in range(0, len(linhas), 2)]
        total = sum(len(b) for b in partes)
        t, dur = off[c["id"]], st[c["id"]]["dur"]
        for b in partes:
            d = dur * len(b) / total
            blocos.append((t, t + d, b))
            t += d
    return "".join(f"{n}\n{dublagem._ts(a)} --> {dublagem._ts(b)}\n{txt}\n\n"
                   for n, (a, b, txt) in enumerate(blocos, 1))


def escrever_cenas(proj: Path, lang: str) -> Path:
    proj = Path(proj)
    ep = ler(proj)
    erros = validar(ep, proj, lang)
    if erros:
        raise ValueError("episódio inválido: " + "; ".join(f"{e['id']}: {e['motivo']}" for e in erros))
    st = estado(proj, lang)

    def em_dia(c) -> bool:          # áudio existe e é do texto/voz atuais
        s = st.get(c["id"])
        return (bool(s) and (proj / s.get("audio", "-")).is_file()
                and s.get("hash") == dublagem._hash(s.get("voz", ""), _loc(c["texto"], lang).strip()))
    faltam = [c["id"] for c in ep["cenas"] if not em_dia(c)]
    if faltam:
        raise ValueError(f"rode tts antes: áudio ausente ou desatualizado em {', '.join(faltam)}")
    pal = _palavras(proj, lang, ep, st) if modo_doc(ep) else None
    d = cenas_motion(ep, lang, {k: v["dur"] for k, v in st.items()}, motion.carregar_tema(ep["marca"]), pal)
    from PIL import Image
    if d.get("mapa"):
        with Image.open(proj / d["mapa"]["arquivo"]) as im:
            d["mapa"]["w"], d["mapa"]["h"] = im.size
    def razao(arq):
        with Image.open(proj / arq) as im:
            w, h = im.size
        return w / h
    for k in d["cenas"]:
        if k["tipo"] == "tela" and Path(k["arquivo"]).suffix.lower() in motion.EXT_IMG:
            if razao(k["arquivo"]) < 1.2:
                k["ajuste"] = "contain"     # retrato/jornal: inteiro sobre fundo desfocado, sem corte
        if k["tipo"] == "doc":              # palco imagem e insertos: retrato/jornal e panorama inteiros
            for x in [k["palco"]] + [b for b in k["beats"] if b["faz"] == "inserto"]:
                if x.get("arquivo") and not 1.2 <= razao(x["arquivo"]) <= 2.2:
                    x["ajuste"] = "contain"
    dst = proj / f"cenas.{lang}.json"
    pipeline.atomic_write_json(dst, d)
    return dst


def _ff(args: list) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _voz(proj: Path, lang: str, tempos: dict, st: dict) -> Path:
    off, ins, fs = offsets(tempos), [], []
    cenas = [c for c in tempos["cenas"] if c["id"] in st]
    for k, c in enumerate(cenas):
        ins += ["-i", str(proj / st[c["id"]]["audio"])]
        fs.append(f"[{k}:a]aresample=48000,adelay={int(round(off[c['id']] * 1000))}:all=1[a{k}]")
    n = len(cenas)
    graph = (";".join(fs) + ";" + "".join(f"[a{k}]" for k in range(n))
             + f"amix=inputs={n}:normalize=0,apad,atrim=0:{tempos['duracao']:.3f}[out]")
    dst = _dir(proj, lang) / "narracao.wav"
    _ff([*ins, "-filter_complex", graph, "-map", "[out]", "-ac", "2", str(dst)])
    return dst


def render(proj, lang: str, rascunho: bool = False, trilha=None) -> dict:
    proj = Path(proj)
    if trilha and not Path(trilha).is_file():
        raise ValueError(f"trilha não encontrada: {trilha}")
    escrever_cenas(proj, lang)          # valida, confere tts e alinhar antes de resolver beats
    ep = ler(proj)
    doc, avisos, soltas = modo_doc(ep), [], []
    if doc:
        st0 = estado(proj, lang)
        pal = _palavras(proj, lang, ep, st0)
        for c in ep["cenas"]:
            beats = resolver_beats(c, lang, pal) if c.get("beats") else []
            avisos += ritmo(c["id"], beats, st0[c["id"]]["dur"])
            soltas += sobrepostas(c["id"], beats)
        if avisos and not rascunho:
            raise ValueError("ritmo: " + "; ".join(avisos))
        if not trilha and not rascunho:
            raise ValueError("render final do modo doc exige --trilha (canal/trilhas/)")
        if not trilha:
            avisos.append("rascunho sem trilha")
    r = motion.render(proj, rascunho, lang)
    if not r.get("ok"):
        return r
    tempos = pipeline.read_json(proj / f"motion.{lang}" / "tempos.json", None)
    if not tempos:
        raise RuntimeError(f"motion.{lang}/tempos.json ilegível após render")
    st = estado(proj, lang)
    voz = _voz(proj, lang, tempos, st)
    out = _dir(proj, lang) / ("final_rascunho.mp4" if rascunho else "final.mp4")
    tmp = out.with_name(f".{out.stem}.voz.mp4")
    tmp2 = out.with_name(f".{out.stem}.sfx.mp4")
    if not doc:          # episódio sem beats: caminho original
        if trilha:
            try:
                _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy", *audio.AAC, str(tmp)])
                audio.mix_trilha(tmp, Path(trilha), out)          # ducking + loudnorm −14
            finally:
                tmp.unlink(missing_ok=True)
        else:
            _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                 "-af", "loudnorm=I=-14:TP=-1:LRA=11", *audio.AAC, "-movflags", "+faststart", str(out)])
    else:
        try:
            _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy", *audio.AAC, str(tmp)])
            base = tmp
            cues = proj / f"cues.{lang}.json"
            if cues.is_file() and json.loads(cues.read_text(encoding="utf-8")):
                if not SFX_DIR.is_dir():
                    audio.sfx_kit(SFX_DIR)
                audio.mix_sfx(tmp, cues, SFX_DIR, tmp2)
                base = tmp2
            if trilha:
                realces = [(c["ini"], round(c["ini"] + c["dur"], 3)) for c in tempos["cenas"] if c["id"] in ("c900", "c901")]
                audio.mix_trilha(base, Path(trilha), out, **({"realces": realces} if realces else {}))
            else:
                _ff(["-i", str(base), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                     "-af", "loudnorm=I=-14:TP=-1:LRA=11", *audio.AAC, "-movflags", "+faststart", str(out)])
        finally:
            tmp.unlink(missing_ok=True)
            tmp2.unlink(missing_ok=True)
    legenda = out.with_suffix(".srt")
    legenda.write_text(srt(ep, lang, tempos, st), encoding="utf-8")
    return {"ok": True, "video": str(out), "srt": str(legenda), "duracao": tempos["duracao"],
            "avisos": avisos + soltas + (avisos_direcao(ep, lang) if doc else [])}


FONTE_THUMB = pipeline.ROOT / "motion" / "kit" / "fonts" / "Archivo.ttf"
DIVULGACAO_IA = ("Divulgação: este vídeo usa imagens geradas por IA. "
                 "No YouTube Studio: \"Conteúdo alterado ou sintético\" = Sim.")
DIVULGACAO_IA_EN = ("Disclosure: this video uses AI-generated images. "
                    "YouTube Studio: \"Altered or synthetic content\" = Yes.")
TITULOS_DESC = {"pt": ("Fontes:", "Imagens:", "Música:"), "en": ("Sources:", "Images:", "Music:")}


def _quebra(draw, txt: str, fonte, largura: int) -> list:
    linhas, cur = [], ""
    for p in txt.split():
        teste = f"{cur} {p}".strip()
        if cur and draw.textlength(teste, font=fonte) > largura:
            linhas.append(cur)
            cur = p
        else:
            cur = teste
    return linhas + ([cur] if cur else [])


def thumb(proj, lang: str, img: str) -> dict:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    proj = Path(proj)
    ep = ler(proj)
    src = motion._dentro(proj, img)
    if src is None:
        raise ValueError(f"imagem não encontrada no projeto: {img!r}")
    txt = _loc(ep.get("thumb_texto"), lang) or _loc(ep.get("titulo"), lang) or ""
    base = ImageOps.fit(Image.open(src).convert("RGB"), (1280, 720))
    sombra = Image.linear_gradient("L").resize((1280, 720)).point(lambda v: int(v * 0.85))
    base.paste(Image.new("RGB", (1280, 720), "black"), (0, 0), sombra)   # escurece para baixo, onde vai o texto
    d = ImageDraw.Draw(base)
    tam = 104
    while True:                                   # diminui até caber em 3 linhas
        fonte = ImageFont.truetype(str(FONTE_THUMB), tam)
        linhas = _quebra(d, txt.upper(), fonte, 1160)
        if len(linhas) <= 3 or tam <= 56:
            break
        tam -= 8
    y = 720 - 60 - len(linhas) * int(tam * 1.05)
    for ln in linhas:
        d.text((60, y), ln, font=fonte, fill="#EDE6D6", stroke_width=6, stroke_fill="black")
        y += int(tam * 1.05)
    dst = _dir(proj, lang) / "thumb.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    base.save(dst)
    return {"png": str(dst), "linhas": linhas, "tamanho": tam}


def _ids(ids: list) -> str:
    """["F1","F2","F3","F7"] -> "F1–F3, F7" (runs consecutivas viram intervalo)."""
    runs = []   # [id inicial, último nº, nº inicial]
    for i in ids:
        n = int(i[1:]) if i[1:].isdigit() else None
        if runs and n is not None and runs[-1][1] == n - 1:
            runs[-1][1] = n
        else:
            runs.append([i, n, n])
    return ", ".join(r[0] if r[1] == r[2] else f"{r[0]}–F{r[1]}" for r in runs)


def descricao(proj, lang: str, trilhas=None) -> dict:
    proj = Path(proj)
    ep = ler(proj)
    achados = {a["id"]: a for a in pesquisa.parse_pesquisa(
        (proj / "pesquisa.md").read_text(encoding="utf-8-sig"))["achados"]}
    usadas = sorted({str(f) for c in ep["cenas"] for f in c.get("fontes", [])},
                    key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    grupos = {}   # (fonte, url) -> ids; uma linha por URL
    for i in usadas:
        if i in achados:
            grupos.setdefault((achados[i]["fonte"], achados[i]["url"]), []).append(i)
    fontes = [f"[{_ids(ids)}] {f} — {u}" for (f, u), ids in grupos.items()]
    creditos = []

    def credita(d):
        if d and d.get("src") and d.get("credito"):
            lic = d["licenca"]
            linha = (f"{d['credito']} — {d['fonte_url']}" if lic in d["credito"]
                     else f"{d['credito']} ({lic}) — {d['fonte_url']}")
            if linha not in creditos:
                creditos.append(linha)
    credita(ep.get("mapa"))
    for c in ep["cenas"]:
        if c["visual"]["tipo"] == "arquivo":
            credita(c["visual"])
        credita(c.get("fundo") if isinstance(c.get("fundo"), dict) and c["fundo"].get("tipo") == "imagem" else None)
        for b in c.get("beats") or []:
            if b.get("faz") == "inserto":
                credita(b)
    ia = any(c["visual"]["tipo"] == "ia" for c in ep["cenas"])
    t_fontes, t_imagens, t_musica = TITULOS_DESC.get(lang, TITULOS_DESC["pt"])
    musica = []
    if trilhas:   # ponytail: lista todas as faixas; o render usa uma só
        musica = [f["atribuicao"] for f in json.loads(Path(trilhas).read_text(encoding="utf-8-sig"))["faixas"]
                  if f.get("atribuicao")]
    partes = [_loc(ep.get("descricao"), lang) or "", t_fontes + "\n" + "\n".join(fontes),
              t_imagens + "\n" + "\n".join(creditos)]
    if ia:
        partes.append(DIVULGACAO_IA_EN if lang == "en" else DIVULGACAO_IA)
    if musica:
        partes.append(t_musica + "\n" + "\n\n".join(musica))
    dst = _dir(proj, lang) / "descricao.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    txt = "\n\n".join(p for p in partes if p).strip() + "\n"
    if len(txt.encode("utf-8")) > 5000:   # limite do YouTube; último recurso: URL do Commons vira "commons: File:x"
        txt = re.sub(r"https://commons\.wikimedia\.org/wiki/(File:\S+)", r"commons: \1", txt)
    dst.write_text(txt, encoding="utf-8")
    return {"fontes": len(fontes), "creditos": len(creditos), "ia": ia}


EXIT = {"ok": 0, "invalido": 1, "precisa_aprovacao": 2, "bloqueado": 3}


def _cli(ns):
    p = Path(ns.proj)
    if ns.cmd == "validar":
        erros = validar(ler(p), p, ns.lang)
        return {"ok": not erros, "erros": erros}, (0 if not erros else 1)
    if ns.cmd == "tts":
        cfg = perfil(Path(ns.perfil), ns.lang) if ns.perfil else {"voice_id": ns.voz, "provedor": ns.provedor}
        if not cfg["voice_id"]:
            raise ValueError("informe --perfil canal/idiomas.json ou --voz")
        r = tts(p, ns.lang, root=Path(ns.root), aprovacao=ns.aprovacao, **cfg)
        return r, EXIT.get(r["status"], 4)
    if ns.cmd == "alinhar":
        return alinhar.alinhar(p, ns.lang), 0
    if ns.cmd == "render":
        r = render(p, ns.lang, ns.rascunho, ns.trilha)
        return r, (0 if r.get("ok") else 1)
    if ns.cmd == "thumb":
        return thumb(p, ns.lang, ns.img), 0
    return descricao(p, ns.lang, ns.trilhas), 0


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="vídeo narrado: episodio.json → TTS por cena → motion 16:9")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("validar", "tts", "alinhar", "render", "thumb", "descricao"):
        sp = sub.add_parser(nome)
        sp.add_argument("proj")
        sp.add_argument("--lang", default="pt")
        if nome == "tts":
            sp.add_argument("--perfil", help="canal/idiomas.json: provedor, voz, velocidade e tratamento do idioma")
            sp.add_argument("--voz")
            sp.add_argument("--provedor", choices=sorted(PROVEDORES), default="elevenlabs")
            sp.add_argument("--aprovacao", type=int)
        if nome == "render":
            sp.add_argument("--rascunho", action="store_true")
            sp.add_argument("--trilha")
        if nome == "descricao":
            sp.add_argument("--trilhas", help="canal/trilhas.json: credita a atribuição das faixas")
        if nome == "thumb":
            sp.add_argument("--img", required=True)
    ns = ap.parse_args()
    try:
        out, code = _cli(ns)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        sys.exit(4)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)
