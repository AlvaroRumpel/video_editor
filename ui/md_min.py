"""Markdown mínimo → HTML, tudo escapado. Sem HTML embutido, sem imagens."""
import html
import re

_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*([^*]+)\*"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
]


def _inline(s: str) -> str:
    s = html.escape(s, quote=True)
    for rx, rep in _INLINE:
        s = rx.sub(rep, s)
    return s


def render(texto: str) -> str:
    out, lista, tabela = [], None, []

    def fecha_lista():
        nonlocal lista
        if lista:
            out.append(f"</{lista}>"); lista = None

    def fecha_tabela():
        nonlocal tabela
        if tabela:
            linhas = [l for l in tabela if not re.fullmatch(r"\|?[\s:\-|]+\|?", l)]
            cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
            if linhas:
                h = "".join(f"<th>{_inline(c)}</th>" for c in cells(linhas[0]))
                b = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(l)) + "</tr>" for l in linhas[1:])
                out.append(f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>")
            tabela = []

    for raw in texto.splitlines():
        l = raw.rstrip()
        if l.lstrip().startswith("|"):
            fecha_lista(); tabela.append(l); continue
        fecha_tabela()
        m = re.match(r"^(#{1,3})\s+(.*)$", l)
        if m:
            fecha_lista(); out.append(f"<h{len(m.group(1))}>{_inline(m.group(2))}</h{len(m.group(1))}>"); continue
        if l.startswith("<!--") and l.endswith("-->"):
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", l)
        if m:
            if lista != "ul": fecha_lista(); out.append("<ul>"); lista = "ul"
            out.append(f"<li>{_inline(m.group(1))}</li>"); continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", l)
        if m:
            if lista != "ol": fecha_lista(); out.append("<ol>"); lista = "ol"
            out.append(f"<li>{_inline(m.group(1))}</li>"); continue
        if l.lstrip().startswith(">"):
            fecha_lista(); out.append(f"<blockquote>{_inline(l.lstrip()[1:].strip())}</blockquote>"); continue
        if not l.strip():
            fecha_lista(); continue
        fecha_lista(); out.append(f"<p>{_inline(l)}</p>")
    fecha_lista(); fecha_tabela()
    return "\n".join(out)
