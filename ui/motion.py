"""Kit de motion (HyperFrames): cenas.json → composição → vídeo dos reels/ads.

montar: valida, gera <proj>/motion[.<lang>]/ (kit copiado + index.html), mede no
Chromium (duração, sons, layout) e grava cues[.<lang>].json.
render: hyperframes de motion/node_modules → video[.<lang>].mp4 conferido no ffprobe.
folha: contact sheet de QC a partir do vídeo."""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
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


MARCADOR_DIR = ".motion"   # só pasta com este arquivo pode ser apagada pelo montar
LANG_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2})?")

HTML = """<!doctype html>
<html lang="pt-BR" data-resolution="portrait">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080, height=1920">
<link rel="stylesheet" href="kit/kit.css">
<style>{css}</style>
<script src="kit/vendor/gsap.min.js"></script>
<script src="kit/kit.js"></script>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="1080" data-height="1920" data-fps="30">
{cenas}
<canvas id="k-brilho" class="clip" width="1080" height="1920" data-start="0" data-duration="{dur}" data-track-index="900"></canvas>
<div id="k-fixos" class="clip" data-start="0" data-duration="{dur}" data-track-index="901"><div id="k-grao"></div><div id="k-wm-claro" class="k-wordmark"></div><div id="k-wm-escuro" class="k-wordmark"></div><div id="k-barra"></div></div>
</div>
<script>window.__KIT_DADOS = {dados};</script>
<script>KIT.montar();</script>
</body>
</html>
"""

JS_MEDIR = """([id, safe]) => {
  const [x0, y0, x1, y1] = safe, out = [];
  for (const e of document.querySelectorAll(`#${id} [data-k-texto]`)) {
    const r = e.getBoundingClientRect();
    const txt = e.textContent.trim().slice(0, 40);
    const tx = e.querySelector(".k-txt") || e;   // decoração (marca-texto/risco) sai um pouco da caixa: não conta
    if (Math.max(tx.scrollWidth, tx.getBoundingClientRect().width) > e.clientWidth + 1) out.push(`linha estoura a largura: "${txt}"`);
    else if (r.left < x0 - 1 || r.right > x1 + 1 || r.top < y0 - 1 || r.bottom > y1 + 1)
      out.push(`texto fora da safe area: "${txt}"`);
    const fam = getComputedStyle(e).fontFamily.split(",")[0].trim().replace(/["']/g, "");
    const ok = [...document.fonts].some((f) => f.family.replace(/["']/g, "") === fam && f.status === "loaded");
    if (!ok) out.push(`fonte em fallback (${fam}): "${txt}"`);
  }
  return out;
}"""


def _lang(lang) -> str:
    if lang is None:
        return ""
    if not isinstance(lang, str) or not LANG_RE.fullmatch(lang):
        raise ValueError(f"lang inválido: {lang!r}")
    return f".{lang}"


def _attrs(t: dict, track: int) -> str:
    return f'data-start="{t["ini"]:.3f}" data-duration="{t["dur"]:.3f}" data-track-index="{track}"'


def _html(d: dict, tema: dict, customs: dict, tempos: dict | None) -> str:
    por_id = {c["id"]: c for c in (tempos or {}).get("cenas", [])}
    total = (tempos or {}).get("duracao", 1)
    partes = []
    for i, c in enumerate(d["cenas"]):
        t = por_id.get(c["id"], {"ini": 0, "dur": 1})
        inner = '<div class="k-conteudo"></div>'
        if c["tipo"] == "tela":
            src = f'midia/{c["id"]}{c["_ext"]}'
            if c["video"]:
                inner += f'<video class="k-midia clip" src="{src}" muted playsinline {_attrs(t, 100 + i)}></video>'
            else:
                inner += f'<img class="k-midia" src="{src}" alt="">'
        elif c["tipo"] == "custom":
            inner += customs[c["id"]]
        partes.append(f'<div id="{c["id"]}" class="clip cena" {_attrs(t, i)}>{inner}</div>')
    cenas_js = [{k: v for k, v in c.items() if not k.startswith("_")} for c in d["cenas"]]
    dados = json.dumps({"tema": _tema_js(tema), "cenas": cenas_js}, ensure_ascii=False).replace("</", "<\\/")
    return HTML.format(css=_css_vars(tema), dur=f"{total:.3f}", cenas="\n".join(partes), dados=dados)


def _preparar(comp: Path, proj: Path, d: dict, tema: dict, motion_dir: Path) -> None:
    if comp.exists():
        if not (comp / MARCADOR_DIR).is_file():
            raise ValueError(f"{comp} existe e não foi criado pelo motion.py (renomeie ou apague à mão)")
        shutil.rmtree(comp)
    shutil.copytree(motion_dir / "kit", comp / "kit")
    (comp / MARCADOR_DIR).write_text("gerado por ui/motion.py montar\n", encoding="utf-8")
    if tema["assinatura"]["tipo"] == "icone":
        a = motion_dir / "temas" / tema["assinatura"]["arquivo"]
        (comp / "kit" / "tema").mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, comp / "kit" / "tema" / a.name)
    for c in d["cenas"]:
        if c["tipo"] == "tela":
            src = _dentro(proj, c["arquivo"])
            c["_ext"] = src.suffix.lower()
            (comp / "midia").mkdir(exist_ok=True)
            shutil.copy2(src, comp / "midia" / f"{c['id']}{c['_ext']}")


def _medir(index: Path) -> dict:
    from playwright.sync_api import TimeoutError as PwTimeout
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        try:
            pg = b.new_page(viewport={"width": W, "height": H})
            js = []
            pg.on("pageerror", lambda ex: js.append(str(ex)))
            pg.goto(index.resolve().as_uri())
            try:
                pg.wait_for_function("window.__kit !== undefined", timeout=20000)
            except PwTimeout:
                raise RuntimeError("kit não montou: " + ("; ".join(js) or "sem erro de JS (timeout)")) from None
            pg.evaluate("document.fonts.ready.then(() => true)")
            kit = pg.evaluate("({duracao: __kit.duracao, cenas: __kit.cenas, cues: __kit.cues, erros: __kit.erros})")
            layout = []
            for c in kit["cenas"]:
                pg.evaluate("t => __kit.ir(t)", max(c["ini"], c["ini"] + c["dur"] - c["saida"] - 0.02))
                layout += [{"id": c["id"], "motivo": m} for m in pg.evaluate(JS_MEDIR, [c["id"], list(SAFE)])]
            return {**kit, "layout": layout, "js": js}
        finally:
            b.close()


def montar(proj: Path, lang: str | None = None, motion_dir: Path = MOTION) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    cj = proj / f"cenas{suf}.json"
    if not cj.is_file():
        raise ValueError(f"não existe: {cj}")
    try:
        dados = json.loads(cj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise ValueError(f"{cj.name} inválido: {ex}") from None
    erros = validar(dados, proj)
    if erros:
        return {"ok": False, "erros": erros}
    tema = carregar_tema(dados.get("marca"), motion_dir)
    d = resolver(dados, tema, proj)
    comp = proj / f"motion{suf}"
    _preparar(comp, proj, d, tema, motion_dir)
    customs = {c["id"]: _dentro(proj, c["html"]).read_text(encoding="utf-8")
               for c in d["cenas"] if c["tipo"] == "custom"}
    index = comp / "index.html"
    index.write_text(_html(d, tema, customs, None), encoding="utf-8")
    m = _medir(index)
    erros = [{"id": "kit", "motivo": j} for j in m["js"]] + m["erros"] + m["layout"]
    if erros:
        return {"ok": False, "erros": erros}
    index.write_text(_html(d, tema, customs, m), encoding="utf-8")
    pipeline.atomic_write_json(comp / "tempos.json", {"duracao": m["duracao"], "cenas": m["cenas"]})
    cues = proj / f"cues{suf}.json"
    pipeline.atomic_write_json(cues, m["cues"])
    return {"ok": True, "duracao": m["duracao"], "erros": [], "index": str(index), "cues": str(cues),
            "cenas": [{"id": c["id"], "ini": c["ini"], "dur": c["dur"]} for c in m["cenas"]]}


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
FRAMES_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
ENV_HF = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HF_CLI_TELEMETRY_DISABLED": "1",
          "HYPERFRAMES_SKIP_SKILLS": "1"}


def _hf_bin(motion_dir: Path) -> None:
    if not (motion_dir / "node_modules" / "hyperframes").is_dir():
        raise RuntimeError(f"hyperframes não instalado: rodar `npm ci` em {motion_dir}")


def _fontes(proj: Path, cj: Path, motion_dir: Path) -> list[Path]:
    fs = [cj, *(motion_dir / "kit").rglob("*")]
    d = pipeline.read_json(cj, {})
    if isinstance(d, dict):
        if isinstance(d.get("marca"), str):
            fs.append(motion_dir / "temas" / f"{d['marca']}.json")
        for c in d.get("cenas") if isinstance(d.get("cenas"), list) else []:
            if isinstance(c, dict):
                fs += [proj / c[k] for k in ("arquivo", "html") if isinstance(c.get(k), str)]
    return fs


def _velho(index: Path, fontes: list[Path]) -> bool:
    if not index.is_file():
        return True
    m = index.stat().st_mtime
    return any(f.is_file() and f.stat().st_mtime > m for f in fontes)


def _pct(linha: str) -> float | None:
    linha = ANSI.sub("", linha)
    m = PCT_RE.search(linha)
    if m:
        return min(100.0, float(m.group(1)))
    m = FRAMES_RE.search(linha)
    if m and int(m.group(2)) > 0:
        return min(100.0, 100 * int(m.group(1)) / int(m.group(2)))
    return None


def _progresso(proj: Path, fase: str, pct=None, eta=None) -> None:
    st = proj / "ui" / "state.json"
    if not st.parent.is_dir():
        return
    atual = pipeline.read_json(st, {})       # merge: preserva chaves alheias (ex.: aprovacoes)
    if not isinstance(atual, dict):
        atual = {}
    atual["render"] = {"fase": fase, "pct": pct, "eta": eta}
    pipeline.atomic_write_json(st, atual)


def _executar(cmd: list[str], cwd: Path, env: dict, linha) -> tuple[int, list[str]]:
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    ultimas: list[str] = []
    for ln in p.stdout:
        ln = ln.rstrip()
        ultimas = (ultimas + [ANSI.sub("", ln)])[-20:]
        linha(ln)
    return p.wait(), ultimas


def _probe(p: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,pix_fmt,color_range,nb_frames", "-of", "json", str(p)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"w": s["width"], "h": s["height"], "fps": float(num) / float(den), "pix_fmt": s.get("pix_fmt"),
            "range": s.get("color_range", "unknown"), "frames": int(s.get("nb_frames") or 0)}


def _finalizar(tmp: Path, dst: Path, duracao: float) -> dict:
    pr = _probe(tmp)
    if pr["pix_fmt"] == "yuvj420p" or pr["range"] == "pc":
        conv = tmp.with_name(tmp.stem + ".tv.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                        "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-c:v", "libx264", "-crf", "18",
                        "-preset", "medium", "-profile:v", "high", "-color_range", "tv", "-colorspace", "bt709",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-an",
                        "-movflags", "+faststart", str(conv)], check=True)
        os.replace(conv, tmp)
        pr = _probe(tmp)
    esperado = round(duracao * FPS)
    problemas = []
    if (pr["w"], pr["h"]) != (W, H):
        problemas.append(f"dimensão {pr['w']}x{pr['h']}")
    if abs(pr["fps"] - FPS) > 0.01:
        problemas.append(f"fps {pr['fps']:.3f}")
    if pr["pix_fmt"] != "yuv420p":
        problemas.append(f"pix_fmt {pr['pix_fmt']}")
    if pr["frames"] and abs(pr["frames"] - esperado) > 1:
        problemas.append(f"{pr['frames']} frames (esperado {esperado})")
    if problemas:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("vídeo fora do esperado: " + ", ".join(problemas))
    os.replace(tmp, dst)
    return pr


def render(proj: Path, rascunho: bool = False, lang: str | None = None, motion_dir: Path = MOTION) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    _hf_bin(motion_dir)
    comp = proj / f"motion{suf}"
    if _velho(comp / "index.html", _fontes(proj, proj / f"cenas{suf}.json", motion_dir)):
        r = montar(proj, lang, motion_dir)
        if not r["ok"]:
            return r
    tempos = pipeline.read_json(comp / "tempos.json", None)
    if not tempos:
        raise RuntimeError(f"{comp / 'tempos.json'} ausente: rodar montar")
    nome = f"video_rascunho{suf}.mp4" if rascunho else f"video{suf}.mp4"
    dst = proj / nome
    tmp = proj / f".{nome}.hf.mp4"
    cmd = [shutil.which("npx") or "npx", "--no-install", "hyperframes", "render", str(comp.resolve()),
           "-o", str(tmp.resolve()), "--format", "mp4", "--fps", str(FPS),
           "-q", "draft" if rascunho else "looks", "--crf", "28" if rascunho else "18"]
    inicio, ultimo = time.time(), [-1]

    def linha(ln):
        pct = _pct(ln)
        if pct is not None and int(pct) != ultimo[0]:
            ultimo[0] = int(pct)
            eta = round((time.time() - inicio) * (100 - pct) / pct) if pct > 0 else None
            _progresso(proj, "render", round(pct, 1), eta)

    _progresso(proj, "render", 0, None)
    rc, ultimas = _executar(cmd, motion_dir, {**os.environ, **ENV_HF}, linha)
    if rc != 0 or not tmp.is_file():
        _progresso(proj, "falha")
        raise RuntimeError("hyperframes render falhou:\n" + "\n".join(ultimas))
    _progresso(proj, "conferindo", 100, 0)
    try:
        _finalizar(tmp, dst, tempos["duracao"])
    except RuntimeError:
        _progresso(proj, "falha")
        raise
    _progresso(proj, "pronto", 100, 0)
    return {"ok": True, "video": str(dst), "duracao": tempos["duracao"]}


def folha(proj: Path, lang: str | None = None) -> dict:
    proj = Path(proj)
    suf = _lang(lang)
    video = next((v for v in (proj / f"video{suf}.mp4", proj / f"video_rascunho{suf}.mp4") if v.is_file()), None)
    if video is None:
        raise ValueError("sem video.mp4 nem video_rascunho.mp4: rodar render")
    tempos = pipeline.read_json(proj / f"motion{suf}" / "tempos.json", None)
    if not tempos:
        raise ValueError("tempos.json ausente: rodar montar")
    fim = tempos["duracao"] - 1 / FPS
    pontos = []
    for c in tempos["cenas"]:
        pontos.append((c["id"], "entrada", c["ini"] + min(0.6, c["dur"] / 3)))
        pontos.append((c["id"], "final", c["ini"] + c["dur"] - c["saida"] - 0.1))
        if c["saida"]:
            pontos.append((c["id"], "saida", c["ini"] + c["dur"] - c["saida"] / 2))
    pontos = [(i, r, max(0.0, min(t, fim))) for i, r, t in pontos]
    tmpd = proj / "qc" / f".folha{suf}"
    shutil.rmtree(tmpd, ignore_errors=True)
    tmpd.mkdir(parents=True)
    cols = 6
    linhas = -(-len(pontos) // cols)
    for k in range(cols * linhas):
        dst = str(tmpd / f"f_{k:03d}.png")
        if k < len(pontos):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{pontos[k][2]:.3f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=270:480", dst], check=True)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=270x480",
                            "-frames:v", "1", dst], check=True)
    png = proj / "qc" / f"folha{suf}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmpd / "f_%03d.png"),
                    "-vf", f"tile={cols}x{linhas}:padding=6:color=white", "-frames:v", "1", str(png)], check=True)
    shutil.rmtree(tmpd)
    return {"png": str(png), "frames": [{"id": i, "rotulo": r, "t": round(t, 3)} for i, r, t in pontos]}


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="kit de motion (HyperFrames)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("montar", "render", "folha"):
        p = sub.add_parser(nome)
        p.add_argument("proj")
        p.add_argument("--lang")
        if nome == "render":
            p.add_argument("--rascunho", action="store_true")
    ns = ap.parse_args()
    try:
        if ns.cmd == "montar":
            out = montar(Path(ns.proj), ns.lang)
        elif ns.cmd == "render":
            out = render(Path(ns.proj), ns.rascunho, ns.lang)
        else:
            out = folha(Path(ns.proj), ns.lang)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("ok", True) else 1)
