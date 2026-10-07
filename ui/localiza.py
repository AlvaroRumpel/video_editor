"""Textos na tela: extrai strings visíveis de anim.html / .tsx, aplica traduções
em cópias localizadas (só entre delimitadores) e checa estouro de layout (Playwright)."""
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

LETRA = re.compile(r"[^\W\d_]")
PALAVRA = re.compile(r"[^\W\d_]{2}")
JSX_TEXTO = re.compile(r">([^<>{}]*)<")
LITERAL = re.compile(r"""(["'])((?:(?!\1)[^\\\n])+)\1""")
TOKEN_CSS = re.compile(r"^[a-z0-9:\-\[\]./#]+$")
CODIGO = re.compile(r"&&|\|\||=>|==|;")
EXT_TEXTO = {".html", ".htm", ".tsx", ".jsx", ".ts", ".js"}


def _norm(s: str) -> str:
    return " ".join(s.split())


class _Visiveis(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignora = 0
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "title"):
            self.ignora += 1
        for k, v in attrs:
            if k in ("alt", "title") and v and LETRA.search(v):
                self.out.append(v)

    def handle_startendtag(self, tag, attrs):
        for k, v in attrs:
            if k in ("alt", "title") and v and LETRA.search(v):
                self.out.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title") and self.ignora:
            self.ignora -= 1

    def handle_data(self, data):
        if not self.ignora and LETRA.search(data):
            self.out.append(data)


def _de_html(txt: str) -> list:
    p = _Visiveis()
    p.feed(txt)
    return p.out


def _parece_css(s: str) -> bool:
    """'flex items-center' sim; 'reconhecer com saber' não (precisa de token com -, : ou dígito)."""
    toks = s.split()
    return all(TOKEN_CSS.match(t) for t in toks) and any(re.search(r"[-:\d]", t) for t in toks)


def _literal_ok(s: str) -> bool:
    # PALAVRA: 2+ letras seguidas — descarta path SVG ("M7 10v11H4a1 ...")
    return (" " in s.strip() and PALAVRA.search(s) and not _parece_css(s)
            and "/" not in s and "\\" not in s and not s.startswith(("http", "www.")))


def _de_tsx(txt: str) -> list:
    out = [m.group(1) for m in JSX_TEXTO.finditer(txt)
           if LETRA.search(m.group(1)) and not CODIGO.search(m.group(1))]
    # ponytail: heurística de texto JSX/literal; o Claude marca "=" no que for código
    out += [m.group(2) for m in LITERAL.finditer(txt) if _literal_ok(m.group(2))]
    return out


def extrair(arquivos, saida) -> dict:
    saida = Path(saida)
    atual = pipeline.read_json(saida, {})
    textos = (atual.get("textos") if isinstance(atual, dict) else None) or {}
    ids = [int(v["id"][1:]) for v in textos.values() if isinstance(v, dict) and re.fullmatch(r"t\d+", str(v.get("id", "")))]
    prox = max(ids, default=0) + 1
    vistos = {}
    for arq in map(Path, arquivos):
        txt = arq.read_text(encoding="utf-8")
        brutos = _de_html(txt) if arq.suffix.lower() in (".html", ".htm") else _de_tsx(txt)
        for b in brutos:
            k = _norm(b)
            if not k or k in vistos and arq.name in vistos[k]:
                continue
            vistos.setdefault(k, []).append(arq.name)
    novos = {}
    for k, arqs in vistos.items():
        v = textos.get(k) if isinstance(textos.get(k), dict) else None
        if v:
            novos[k] = {"id": v.get("id"), "trad": v.get("trad"), "arquivos": sorted(set(v.get("arquivos", [])) | set(arqs))}
        else:
            novos[k] = {"id": f"t{prox:02d}", "trad": None, "arquivos": arqs}
            prox += 1
    for k, v in textos.items():          # textos antigos que sumiram dos arquivos continuam (histórico)
        novos.setdefault(k, v)
    out = {"textos": novos}
    saida.parent.mkdir(parents=True, exist_ok=True)
    pipeline.atomic_write_json(saida, out)
    return out


def _esc_texto(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _curvas(s: str, q: str) -> str:
    """Troca a aspa delimitadora dentro da tradução por aspas curvas (vale em JS e em atributo JSX/HTML)."""
    abre, fecha = ("“", "”") if q == '"' else ("‘", "’")
    out, aberta = [], False
    for ch in s:
        if ch == q:
            out.append(fecha if aberta else abre)
            aberta = not aberta
        else:
            out.append(ch)
    return "".join(out)


def aplicar(textos_json, origem, destino) -> dict:
    tx = (json.loads(Path(textos_json).read_text(encoding="utf-8")).get("textos") or {})
    faltam = [v.get("id", k) for k, v in tx.items() if not (isinstance(v, dict) and str(v.get("trad") or "").strip())]
    if faltam:
        raise ValueError(f"textos sem tradução: {', '.join(faltam)}")
    origem, destino = Path(origem).resolve(), Path(destino).resolve()
    if destino == origem or destino.is_relative_to(origem):
        raise ValueError("destino não pode ser a origem nem ficar dentro dela")
    if destino.is_dir():
        shutil.rmtree(destino)
    if origem.is_dir():
        shutil.copytree(origem, destino)
        arquivos = [p for p in destino.rglob("*") if p.suffix.lower() in EXT_TEXTO]
    else:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
        arquivos = [destino]
    pares = sorted(((k, str(v["trad"]).strip()) for k, v in tx.items() if str(v["trad"]).strip() != "="),
                   key=lambda kv: -len(kv[0]))
    contagem = {k: 0 for k, _ in pares}
    for arq in arquivos:
        s = arq.read_text(encoding="utf-8")
        antes = s
        for orig, trad in pares:
            corpo = r"\s+".join(map(re.escape, orig.split()))
            s, n1 = re.subn(r"(>\s*)" + corpo + r"(\s*<)", lambda m: m.group(1) + _esc_texto(trad) + m.group(2), s)
            s, n2 = re.subn(r"([\"'])" + corpo + r"\1",
                            lambda m: m.group(1) + _curvas(trad, m.group(1)) + m.group(1), s)
            contagem[orig] += n1 + n2
        if s != antes:
            arq.write_text(s, encoding="utf-8")
    return {"substituicoes": sum(contagem.values()), "arquivos": [str(a) for a in arquivos],
            "nao_encontrados": [tx[k]["id"] for k, n in contagem.items() if n == 0]}


JS_ESTOURO = """() => {
  const W = innerWidth, H = innerHeight, out = [];
  for (const e of document.querySelectorAll('body *')) {
    if (![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const corta = e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1;
    const fora = r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1;
    if (corta || fora) {
      const cls = typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).join('.') : '';
      out.push({ seletor: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + cls, texto: e.textContent.trim().slice(0, 60) });
    }
  }
  return out;
}"""


def checar(html, frames: int = 8, total: int = 900, largura: int = 540, altura: int = 960) -> dict:
    from playwright.sync_api import sync_playwright
    estouros, vistos = [], set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": largura, "height": altura})
            pg.goto(Path(html).resolve().as_uri())
            pg.wait_for_function("window.READY === true", timeout=15000)
            n = max(1, frames)
            for i in range(n):
                f = round(i * (total - 1) / max(n - 1, 1))
                pg.evaluate("f => window.seek && window.seek(f)", f)
                for e in pg.evaluate(JS_ESTOURO):
                    chave = (e["seletor"], e["texto"])
                    if chave not in vistos:
                        vistos.add(chave)
                        estouros.append({"frame": f, **e})
        finally:
            b.close()
    return {"ok": not estouros, "estouros": estouros}


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="textos na tela")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extrair"); p.add_argument("arquivos", nargs="+"); p.add_argument("--saida", required=True)
    p = sub.add_parser("aplicar"); p.add_argument("textos"); p.add_argument("origem"); p.add_argument("destino")
    p = sub.add_parser("checar"); p.add_argument("html"); p.add_argument("--frames", type=int, default=8)
    p.add_argument("--total", type=int, default=900)
    ns = ap.parse_args()
    try:
        if ns.cmd == "extrair":
            d = extrair(ns.arquivos, ns.saida)
            out, code = {"textos": len(d["textos"]), "saida": ns.saida}, 0
        elif ns.cmd == "aplicar":
            out, code = aplicar(ns.textos, ns.origem, ns.destino), 0
        else:
            out = checar(ns.html, frames=ns.frames, total=ns.total)
            code = 0 if out["ok"] else 1
    except ValueError as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False)); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
