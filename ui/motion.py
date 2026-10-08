"""Kit de motion (HyperFrames): cenas.json → composição → vídeo dos reels/ads.

montar: valida, gera <proj>/motion[.<lang>]/ (kit copiado + index.html), mede no
Chromium (duração, sons, layout) e grava cues[.<lang>].json.
render: hyperframes de motion/node_modules → video[.<lang>].mp4 conferido no ffprobe.
folha: contact sheet de QC a partir do vídeo."""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = pipeline.ROOT
MOTION = ROOT / "motion"
FPS = 30
W, H = 1080, 1920
SAFE = (80, 180, 1000, 1660)  # x0, y0, x1, y1

TIPOS = ("frase", "numero", "lista", "tela", "endcard", "custom")
FUNDOS = ("claro", "escuro", "marca")
ESTILOS = ("display", "punch", "corpo", "mono")
ANIMS = ("palavras", "letras", "mascara", "fade")
CORES = ("tinta", "acento", "sobre")
DESTAQUES = ("marca-texto", "risco", "assinatura")
TRANSICOES = ("fade", "wipe", "iris")
MOLDURAS = ("celular", "browser", "nenhuma")
MARCADORES = ("numero", "assinatura", "check")
EXT_IMG = (".png", ".jpg", ".jpeg")
EXT_VID = (".mp4",)
ID_RE = re.compile(r"c\d{2,}")
MARCA_RE = re.compile(r"[a-z0-9-]+")
FUNDO_PADRAO = {"frase": "claro", "numero": "claro", "lista": "claro", "tela": "claro",
                "endcard": "marca", "custom": "claro"}
TEMA_CHAVES = (
    "cores.tinta", "cores.acento", "cores.sobre", "cores.marca_texto", "cores.risco", "cores.manchas",
    "cores.fundo.claro", "cores.fundo.escuro", "cores.fundo.marca",
    "fontes.display.familia", "fontes.display.peso", "fontes.punch.familia", "fontes.punch.peso",
    "fontes.corpo.familia", "fontes.corpo.peso", "fontes.mono.familia", "fontes.mono.peso",
    "assinatura.tipo", "fixos.wordmark", "fixos.wordmark_fonte", "fixos.barra", "fixos.grao",
    "endcard.marca", "endcard.tagline", "endcard.cta", "endcard.url", "pill.borda", "pill.texto",
    "transicao_padrao.transicao", "transicao_padrao.dur", "regras.numero_mono")

def _pega(d, caminho: str):
    for k in caminho.split("."):
        if not isinstance(d, dict) or k not in d:
            raise KeyError(caminho)
        d = d[k]
    return d

def carregar_tema(marca, motion_dir: Path = MOTION) -> dict:
    if not isinstance(marca, str) or not MARCA_RE.fullmatch(marca):
        raise ValueError(f"marca inválida: {marca!r}")
    p = motion_dir / "temas" / f"{marca}.json"
    if not p.is_file():
        raise ValueError(f"tema não existe: {p}")
    tema = json.loads(p.read_text(encoding="utf-8"))
    for ch in TEMA_CHAVES:
        try:
            _pega(tema, ch)
        except KeyError:
            raise ValueError(f"tema {marca}: falta {ch}") from None
    if tema["assinatura"]["tipo"] == "icone" and \
            not (motion_dir / "temas" / tema["assinatura"].get("arquivo", "-")).is_file():
        raise ValueError(f"tema {marca}: arquivo do ícone da assinatura não existe")
    return tema

def _dentro(proj: Path, rel) -> Path | None:
    """Arquivo relativo ao projeto, existente e sem escapar dele."""
    if not isinstance(rel, str) or not rel:
        return None
    p = (Path(proj) / rel).resolve()
    return p if p.is_relative_to(Path(proj).resolve()) and p.is_file() else None

def _num(v, minimo=0.0) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= minimo

def _str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""

def _cor(c, e):
    if "cor" in c and c["cor"] not in CORES:
        e(f"cor inválida: {c['cor']!r}")

def _v_frase(c, proj, e):
    linhas = c.get("linhas")
    if not isinstance(linhas, list) or not linhas:
        return e("linhas vazio")
    for k, ln in enumerate(linhas, 1):
        if not isinstance(ln, dict) or not _str(ln.get("t")):
            e(f"linha {k}: falta t")
            continue
        if ln.get("estilo", "punch") not in ESTILOS:
            e(f"linha {k}: estilo inválido: {ln['estilo']!r}")
        if ln.get("anim", "palavras") not in ANIMS:
            e(f"linha {k}: anim inválida: {ln['anim']!r}")
        if ln.get("cor", "tinta") not in CORES:
            e(f"linha {k}: cor inválida: {ln['cor']!r}")
        d = ln.get("destaque", [])
        if not isinstance(d, list) or any(x not in DESTAQUES for x in d) or len(set(d)) != len(d):
            e(f"linha {k}: destaque inválido: {d!r}")
        if "em" in ln and not _num(ln["em"]):
            e(f"linha {k}: em precisa ser número >= 0")

def _v_numero(c, proj, e):
    if not _num(c.get("valor"), float("-inf")):
        e("valor precisa ser número")
    if "de" in c and not _num(c["de"], float("-inf")):
        e("de precisa ser número")
    for k in ("formato", "prefixo", "sufixo", "legenda"):
        if k in c and not isinstance(c[k], str):
            e(f"{k} precisa ser texto")
    _cor(c, e)

def _v_lista(c, proj, e):
    itens = c.get("itens")
    if not isinstance(itens, list) or not itens or not all(_str(x) for x in itens):
        e("itens precisa ser lista de textos")
    elif len(itens) > 6:
        e("no máximo 6 itens")
    if c.get("marcador", "numero") not in MARCADORES:
        e(f"marcador inválido: {c['marcador']!r}")
    if "titulo" in c and not isinstance(c["titulo"], str):
        e("titulo precisa ser texto")
    _cor(c, e)

def _v_tela(c, proj, e):
    p = _dentro(proj, c.get("arquivo"))
    if p is None:
        e(f"arquivo não encontrado no projeto: {c.get('arquivo')!r}")
    elif p.suffix.lower() not in EXT_IMG + EXT_VID:
        e(f"formato não suportado: {p.suffix} (png, jpg, mp4)")
    if c.get("moldura", "celular") not in MOLDURAS:
        e(f"moldura inválida: {c['moldura']!r}")
    if "label" in c and not isinstance(c["label"], str):
        e("label precisa ser texto")
    if "kenburns" in c and not isinstance(c["kenburns"], bool):
        e("kenburns precisa ser true/false")

def _v_endcard(c, proj, e):
    for k in ("cta", "tagline", "url"):
        if k in c and not _str(c[k]):
            e(f"{k} precisa ser texto")
    _cor(c, e)

def _v_custom(c, proj, e):
    p = _dentro(proj, c.get("html"))
    if p is None or p.suffix.lower() not in (".html", ".htm"):
        e(f"html não encontrado no projeto: {c.get('html')!r}")
    if "dur" not in c:
        e("custom precisa de dur")

VALIDA_TIPO = {"frase": _v_frase, "numero": _v_numero, "lista": _v_lista, "tela": _v_tela,
               "endcard": _v_endcard, "custom": _v_custom}

def validar(dados, proj: Path) -> list[dict]:
    if not isinstance(dados, dict):
        return [{"id": "raiz", "motivo": "cenas.json não é um objeto"}]
    erros = []

    def e(i, m):
        erros.append({"id": i, "motivo": m})

    if dados.get("aspecto", "9:16") != "9:16":
        e("raiz", "aspecto: só 9:16 na v1")
    cenas = dados.get("cenas")
    if not isinstance(cenas, list) or not cenas:
        e("raiz", "cenas vazio")
        return erros
    vistos = set()
    for n, c in enumerate(cenas):
        if not isinstance(c, dict):
            e(f"#{n}", "cena não é objeto")
            continue
        i = c.get("id")
        if not isinstance(i, str) or not ID_RE.fullmatch(i):
            e(f"#{n}", f"id inválido: {i!r} (use cNN)")
            continue
        if i in vistos:
            e(i, "id duplicado")
        vistos.add(i)
        tipo = c.get("tipo")
        if tipo not in TIPOS:
            e(i, f"tipo desconhecido: {tipo!r}")
            continue
        if "fundo" in c and c["fundo"] not in FUNDOS:
            e(i, f"fundo inválido: {c['fundo']!r}")
        if "dur" in c and not (_num(c["dur"]) and c["dur"] > 0):
            e(i, "dur precisa ser número > 0")
        if "fixos" in c and not isinstance(c["fixos"], bool):
            e(i, "fixos precisa ser true/false")
        if "saida" in c:
            s = c["saida"]
            if n == len(cenas) - 1:
                e(i, "última cena não tem saida")
            elif not isinstance(s, dict) or s.get("transicao") not in TRANSICOES \
                    or not (_num(s.get("dur")) and 0 < s["dur"] <= 2):
                e(i, "saida precisa de transicao (fade|wipe|iris) e dur em (0, 2]")
        VALIDA_TIPO[tipo](c, proj, lambda m, i=i: e(i, m))
    return erros

def _duracao(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out.strip()), 3)

def _quadro(s: float) -> float:
    return round(round(s * FPS) / FPS, 6)

def resolver(dados: dict, tema: dict, proj: Path) -> dict:
    d = copy.deepcopy(dados)
    cenas = d["cenas"]
    for n, c in enumerate(cenas):
        t = c["tipo"]
        c.setdefault("fundo", FUNDO_PADRAO[t])
        c.setdefault("fixos", t != "endcard")
        cor = "tinta" if c["fundo"] == "claro" else "sobre"
        if n < len(cenas) - 1:
            s = c.get("saida") or tema["transicao_padrao"]
            c["saida"] = {"transicao": s["transicao"], "dur": _quadro(s["dur"])}
        else:
            c["saida"] = None
        if t == "frase":
            for ln in c["linhas"]:
                ln.setdefault("estilo", "punch")
                ln.setdefault("anim", "palavras")
                ln.setdefault("cor", cor)
                ln.setdefault("destaque", [])
                ln.setdefault("em", None)
        elif t == "numero":
            for k, v in (("de", 0), ("formato", "pt-BR"), ("prefixo", ""), ("sufixo", ""), ("legenda", ""), ("cor", cor)):
                c.setdefault(k, v)
            c["estilo"] = "mono" if tema["regras"]["numero_mono"] else "display"
        elif t == "lista":
            for k, v in (("titulo", ""), ("marcador", "numero"), ("cor", cor)):
                c.setdefault(k, v)
        elif t == "tela":
            p = _dentro(proj, c["arquivo"])
            c["video"] = p.suffix.lower() in EXT_VID
            c.setdefault("moldura", "celular")
            c.setdefault("label", "")
            c.setdefault("kenburns", not c["video"])
            c.setdefault("dur", _duracao(p) if c["video"] else 3.0)
        elif t == "endcard":
            for k in ("cta", "tagline", "url"):
                c.setdefault(k, tema["endcard"][k])
            c.setdefault("cor", cor)
        c.setdefault("dur", None)
    return d

def _css_vars(tema: dict) -> str:
    c, f = tema["cores"], tema["fontes"]
    v = {"tinta": c["tinta"], "acento": c["acento"], "sobre": c["sobre"], "marca-texto": c["marca_texto"],
         "risco": c["risco"], "manchas": c["manchas"], "fundo-claro": c["fundo"]["claro"],
         "fundo-escuro": c["fundo"]["escuro"], "fundo-marca": c["fundo"]["marca"],
         "pill-borda": tema["pill"]["borda"], "pill-texto": tema["pill"]["texto"]}
    for est in ESTILOS:
        v[f"{est}-familia"] = f'"{f[est]["familia"]}"'
        v[f"{est}-peso"] = str(f[est]["peso"])
        v[f"{est}-estilo"] = f[est].get("estilo", "normal")
    return ":root{" + "".join(f"--k-{k}:{val};" for k, val in v.items()) + "}"

def _tema_js(tema: dict) -> dict:
    a = tema["assinatura"]
    return {"acento": tema["cores"]["acento"],
            "assinatura": {"tipo": a["tipo"],
                           "src": f"kit/tema/{Path(a['arquivo']).name}" if a["tipo"] == "icone" else None},
            "wordmark": tema["fixos"]["wordmark"], "wordmark_fonte": tema["fixos"]["wordmark_fonte"],
            "barra": bool(tema["fixos"]["barra"]), "grao": float(tema["fixos"]["grao"]),
            "endcard_marca": tema["endcard"]["marca"], "url": tema["endcard"]["url"]}
