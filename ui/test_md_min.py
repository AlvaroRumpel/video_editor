import md_min


def test_render_basico():
    h = md_min.render("# T\n\ntexto **b** *i* `c`\n\n- a\n- b\n\n1. um\n2. dois\n\n> cit\n\n[l](https://x.y) [j](javascript:1)\n")
    assert "<h1>T</h1>" in h and "<strong>b</strong>" in h and "<em>i</em>" in h and "<code>c</code>" in h
    assert "<ul><li>a</li><li>b</li></ul>" in h.replace("\n", "")
    assert "<ol><li>um</li><li>dois</li></ol>" in h.replace("\n", "")
    assert "<blockquote>" in h
    assert '<a href="https://x.y"' in h and "href=\"javascript" not in h and "[j](javascript:1)" in h


def test_render_tabela():
    h = md_min.render("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in h and "<th>a</th>" in h and "<td>2</td>" in h


def test_render_escapa_html():
    h = md_min.render("<script>alert(1)</script> & <b>x</b>")
    assert "<script>" not in h and "&lt;script&gt;" in h and "&amp;" in h and "<b>" not in h
