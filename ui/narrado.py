"""Vídeo narrado (canal dark): episodio.json (cenas com texto, fontes e visual) →
TTS ElevenLabs por cena → cenas.<lang>.json do kit de motion em 16:9 → render →
voz mixada nos tempos medidos → <proj>/<lang>/final.mp4 + final.srt.
Substitui o fluxo bruto/*.mkv quando não há gravação."""
import copy
import json
import re
import subprocess
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
        k["dur_piso"] = True     # fala curta: o kit estica até o mínimo da animação; a voz segue os tempos medidos
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
    erros = validar(ep, proj, lang, visuais=False)
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
            st[cid] = {"hash": h, "voz": voice_id, "audio": rel, "dur": round(audio.duracao(proj / rel), 3)}
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
    d = cenas_motion(ep, lang, {k: v["dur"] for k, v in st.items()}, motion.carregar_tema(ep["marca"]))
    from PIL import Image
    for k in d["cenas"]:
        if k["tipo"] == "tela" and Path(k["arquivo"]).suffix.lower() in motion.EXT_IMG:
            with Image.open(proj / k["arquivo"]) as im:
                w, h = im.size
            if w / h < 1.2:
                k["ajuste"] = "contain"     # retrato/jornal: inteiro sobre fundo desfocado, sem corte
    dst = proj / f"cenas.{lang}.json"
    pipeline.atomic_write_json(dst, d)
    return dst


def _ff(args: list) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _voz(proj: Path, lang: str, tempos: dict, st: dict) -> Path:
    off, ins, fs = offsets(tempos), [], []
    for k, c in enumerate(tempos["cenas"]):
        ins += ["-i", str(proj / st[c["id"]]["audio"])]
        fs.append(f"[{k}:a]aresample=48000,adelay={int(round(off[c['id']] * 1000))}:all=1[a{k}]")
    n = len(tempos["cenas"])
    graph = (";".join(fs) + ";" + "".join(f"[a{k}]" for k in range(n))
             + f"amix=inputs={n}:normalize=0,apad,atrim=0:{tempos['duracao']:.3f}[out]")
    dst = _dir(proj, lang) / "narracao.wav"
    _ff([*ins, "-filter_complex", graph, "-map", "[out]", "-ac", "2", str(dst)])
    return dst


def render(proj, lang: str, rascunho: bool = False, trilha=None) -> dict:
    proj = Path(proj)
    ep = ler(proj)
    escrever_cenas(proj, lang)
    r = motion.render(proj, rascunho, lang)
    if not r.get("ok"):
        return r
    tempos = pipeline.read_json(proj / f"motion.{lang}" / "tempos.json", None)
    if not tempos:
        raise RuntimeError(f"motion.{lang}/tempos.json ilegível após render")
    st = estado(proj, lang)
    voz = _voz(proj, lang, tempos, st)
    out = _dir(proj, lang) / ("final_rascunho.mp4" if rascunho else "final.mp4")
    if trilha:
        tmp = out.with_name(f".{out.stem}.voz.mp4")
        _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy", *audio.AAC, str(tmp)])
        try:
            audio.mix_trilha(tmp, Path(trilha), out)          # ducking + loudnorm −14
        finally:
            tmp.unlink(missing_ok=True)
    else:
        _ff(["-i", r["video"], "-i", str(voz), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-af", "loudnorm=I=-14:TP=-1:LRA=11", *audio.AAC, "-movflags", "+faststart", str(out)])
    legenda = out.with_suffix(".srt")
    legenda.write_text(srt(ep, lang, tempos, st), encoding="utf-8")
    return {"ok": True, "video": str(out), "srt": str(legenda), "duracao": tempos["duracao"]}


FONTE_THUMB = pipeline.ROOT / "motion" / "kit" / "fonts" / "Archivo.ttf"
DIVULGACAO_IA = ("Divulgação: este vídeo usa imagens geradas por IA. "
                 "No YouTube Studio: \"Conteúdo alterado ou sintético\" = Sim.")


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


def descricao(proj, lang: str) -> dict:
    proj = Path(proj)
    ep = ler(proj)
    achados = {a["id"]: a for a in pesquisa.parse_pesquisa(
        (proj / "pesquisa.md").read_text(encoding="utf-8-sig"))["achados"]}
    usadas = sorted({str(f) for c in ep["cenas"] for f in c.get("fontes", [])},
                    key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    fontes = [f"[{i}] {achados[i]['fonte']} — {achados[i]['url']}" for i in usadas if i in achados]
    creditos, vistos = [], set()
    for c in ep["cenas"]:
        v = c["visual"]
        if v["tipo"] == "arquivo" and v["src"] not in vistos:
            vistos.add(v["src"])
            creditos.append(f"{v['credito']} — {v['fonte_url']} ({v['licenca']})")
    ia = any(c["visual"]["tipo"] == "ia" for c in ep["cenas"])
    partes = [_loc(ep.get("descricao"), lang) or "", "Fontes:\n" + "\n".join(fontes),
              "Imagens:\n" + "\n".join(creditos)] + ([DIVULGACAO_IA] if ia else [])
    dst = _dir(proj, lang) / "descricao.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n\n".join(p for p in partes if p).strip() + "\n", encoding="utf-8")
    return {"fontes": len(fontes), "creditos": len(creditos), "ia": ia}


EXIT = {"ok": 0, "invalido": 1, "precisa_aprovacao": 2, "bloqueado": 3}


def _cli(ns):
    p = Path(ns.proj)
    if ns.cmd == "validar":
        erros = validar(ler(p), p, ns.lang)
        return {"ok": not erros, "erros": erros}, (0 if not erros else 1)
    if ns.cmd == "tts":
        r = tts(p, ns.lang, ns.voz, root=Path(ns.root), aprovacao=ns.aprovacao)
        return r, EXIT.get(r["status"], 4)
    if ns.cmd == "render":
        r = render(p, ns.lang, ns.rascunho, ns.trilha)
        return r, (0 if r.get("ok") else 1)
    if ns.cmd == "thumb":
        return thumb(p, ns.lang, ns.img), 0
    return descricao(p, ns.lang), 0


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="vídeo narrado: episodio.json → TTS por cena → motion 16:9")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("validar", "tts", "render", "thumb", "descricao"):
        sp = sub.add_parser(nome)
        sp.add_argument("proj")
        sp.add_argument("--lang", default="pt")
        if nome == "tts":
            sp.add_argument("--voz", required=True)
            sp.add_argument("--aprovacao", type=int)
        if nome == "render":
            sp.add_argument("--rascunho", action="store_true")
            sp.add_argument("--trilha")
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
