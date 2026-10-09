"""B-roll de stock: busca em bancos gratuitos, contact sheet, ranqueamento
opcional (CLIP), overlays prontos e merge no edl.json, créditos.
Sem FastAPI. ffmpeg por subprocess; HTTP por urllib (_fetch injetável)."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline

ROOT = pipeline.ROOT
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) video_editor/1.0"
MAX_DOWNLOAD = 150 * 1024 * 1024


def _ler_env() -> dict:
    out = {}
    try:
        for ln in (ROOT / "video-use" / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            if k.strip():
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def chaves() -> dict:
    env = _ler_env()
    def pega(nome):
        return os.environ.get(nome) or env.get(nome, "")
    return {"pexels": pega("PEXELS_API_KEY"), "pixabay": pega("PIXABAY_API_KEY"),
            "unsplash": pega("UNSPLASH_ACCESS_KEY")}


def _fetch_url(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(MAX_DOWNLOAD + 1), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(e.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, b"", {}


def _url_segura(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _json(fetch, url, headers=None):
    """GET + JSON; 429 → espera Retry-After (≤ 60 s) uma vez. Devolve (obj|None, aviso|None)."""
    status, corpo, h = fetch(url, headers)
    if status == 429:
        ra = next((v for k_, v in h.items() if k_.lower() == "retry-after"), "5")
        try:
            espera = min(60, int(str(ra).strip()))
        except ValueError:
            espera = 5
        time.sleep(espera)
        status, corpo, h = fetch(url, headers)
        if status == 429:
            return None, f"429 persistente em {_url_segura(url)}"
    if not (200 <= status < 300):
        return None, f"HTTP {status} em {_url_segura(url)}"
    try:
        return json.loads(corpo.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError) as e:
        return None, f"resposta inválida de {_url_segura(url)}: {e}"


def _variante(arquivos: list[dict], chave_w="width", chave_url="link") -> dict | None:
    """menor variante com largura >= 1920; senão >= 1280."""
    ok = sorted((a for a in arquivos if a.get(chave_w)), key=lambda a: a[chave_w])
    for minimo in (1920, 1280):
        for a in ok:
            if a[chave_w] >= minimo:
                return a
    return None


def _pexels(termo, tipo, n, k, fetch):
    if not k.get("pexels"):
        return [], "pexels: sem chave (PEXELS_API_KEY)"
    h = {"Authorization": k["pexels"]}
    q = urllib.parse.quote(termo)
    if tipo == "video":
        d, av = _json(fetch, f"https://api.pexels.com/videos/search?query={q}&per_page={n * 3}&orientation=landscape", h)
        if d is None:
            return [], av
        out = []
        for v in d.get("videos", []):
            var = _variante([f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"])
            if not var:
                continue
            out.append({"fonte": "pexels", "id": str(v["id"]), "autor": v.get("user", {}).get("name", ""),
                        "url": v.get("url", ""), "licenca": "Pexels License", "tipo": "video",
                        "dur": float(v.get("duration", 0)), "largura": var["width"], "altura": var["height"],
                        "download_url": var["link"], "ext": "mp4"})
        return out, None
    d, av = _json(fetch, f"https://api.pexels.com/v1/search?query={q}&per_page={n * 3}&orientation=landscape", h)
    if d is None:
        return [], av
    return [{"fonte": "pexels", "id": str(p["id"]), "autor": p.get("photographer", ""), "url": p.get("url", ""),
             "licenca": "Pexels License", "tipo": "foto", "dur": 0.0, "largura": p.get("width", 0),
             "altura": p.get("height", 0), "download_url": p["src"]["large2x"], "ext": "jpg"}
            for p in d.get("photos", []) if p.get("src", {}).get("large2x")], None


def _pixabay(termo, tipo, n, k, fetch):
    if not k.get("pixabay"):
        return [], "pixabay: sem chave (PIXABAY_API_KEY)"
    q = urllib.parse.quote(termo)
    if tipo == "video":
        d, av = _json(fetch, f"https://pixabay.com/api/videos/?key={k['pixabay']}&q={q}&per_page={max(3, n * 3)}")
        if d is None:
            return [], av
        out = []
        for v in d.get("hits", []):
            vs = [{"width": x.get("width", 0), "height": x.get("height", 0), "link": x.get("url", "")}
                  for x in v.get("videos", {}).values()]
            var = _variante(vs)
            if not var:
                continue
            out.append({"fonte": "pixabay", "id": str(v["id"]), "autor": v.get("user", ""), "url": v.get("pageURL", ""),
                        "licenca": "Pixabay Content License", "tipo": "video", "dur": float(v.get("duration", 0)),
                        "largura": var["width"], "altura": var["height"], "download_url": var["link"], "ext": "mp4"})
        return out, None
    d, av = _json(fetch, f"https://pixabay.com/api/?key={k['pixabay']}&q={q}&image_type=photo&orientation=horizontal&per_page={max(3, n * 3)}")
    if d is None:
        return [], av
    return [{"fonte": "pixabay", "id": str(p["id"]), "autor": p.get("user", ""), "url": p.get("pageURL", ""),
             "licenca": "Pixabay Content License", "tipo": "foto", "dur": 0.0, "largura": p.get("imageWidth", 0),
             "altura": p.get("imageHeight", 0), "download_url": p.get("largeImageURL", ""), "ext": "jpg"}
            for p in d.get("hits", [])], None


def _unsplash(termo, tipo, n, k, fetch):
    if tipo != "foto":
        return [], None
    if not k.get("unsplash"):
        return [], "unsplash: sem chave (UNSPLASH_ACCESS_KEY)"
    d, av = _json(fetch, f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(termo)}&per_page={n * 3}&orientation=landscape",
                  {"Authorization": f"Client-ID {k['unsplash']}", "Accept-Version": "v1"})
    if d is None:
        return [], av
    return [{"fonte": "unsplash", "id": str(p["id"]), "autor": p.get("user", {}).get("name", ""),
             "url": p.get("links", {}).get("html", ""), "licenca": "Unsplash License (crédito obrigatório)",
             "tipo": "foto", "dur": 0.0, "largura": p.get("width", 0), "altura": p.get("height", 0),
             "download_url": p.get("urls", {}).get("full", ""), "ext": "jpg",
             "_download_location": p.get("links", {}).get("download_location", "")} for p in d.get("results", [])], None


def _segundos(s) -> float:
    """'20.5', '01:02' ou '00:01:02.5' → segundos; ilegível → 0."""
    try:
        t = 0.0
        for parte in str(s or 0).split(":"):
            t = t * 60 + float(parte)
        return t
    except ValueError:
        return 0.0


def _archive(termo, tipo, n, k, fetch):
    if tipo != "video":
        return [], None
    q = urllib.parse.quote(f"({termo}) AND mediatype:movies")
    d, av = _json(fetch, f"https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&rows={n * 2}&output=json")
    if d is None:
        return [], av
    out, avisos = [], []
    for doc in d.get("response", {}).get("docs", []):
        ident = doc.get("identifier")
        m, av2 = _json(fetch, f"https://archive.org/metadata/{ident}")
        if m is None:
            continue
        meta = m.get("metadata", {})
        if not meta.get("licenseurl"):
            avisos.append(f"archive-{ident}: sem licenseurl, ignorado"); continue
        for f in m.get("files", []):
            if not str(f.get("name", "")).lower().endswith(".mp4") or int(f.get("size", 0) or 0) > 100 * 1024 * 1024:
                continue
            out.append({"fonte": "archive", "id": ident, "autor": meta.get("creator", ""),
                        "url": f"https://archive.org/details/{ident}", "licenca": meta["licenseurl"],
                        "tipo": "video", "dur": _segundos(f.get("length")), "largura": int(f.get("width", 0) or 0),
                        "altura": int(f.get("height", 0) or 0),
                        "download_url": f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}", "ext": "mp4"})
            break
    return out, "; ".join(avisos) or None


def _wikimedia(termo, tipo, n, k, fetch):
    ft = "video" if tipo == "video" else "bitmap"
    base = "https://commons.wikimedia.org/w/api.php"
    d, av = _json(fetch, f"{base}?action=query&list=search&srsearch={urllib.parse.quote(termo + ' filetype:' + ft)}&srnamespace=6&srlimit={n * 3}&format=json")
    if d is None:
        return [], av
    titulos = [s["title"] for s in d.get("query", {}).get("search", [])]
    if not titulos:
        return [], None
    i, av = _json(fetch, f"{base}?action=query&titles={urllib.parse.quote('|'.join(titulos))}&prop=imageinfo&iiprop=url|size|extmetadata&format=json")
    if i is None:
        return [], av
    out = []
    for pg in i.get("query", {}).get("pages", {}).values():
        for info in pg.get("imageinfo", []):
            if not info.get("url"):
                continue
            ext = info["url"].rsplit(".", 1)[-1].lower()
            em = info.get("extmetadata", {})
            out.append({"fonte": "wikimedia", "id": pg["title"].replace("File:", ""), "autor": html.unescape(re.sub(r"<[^>]+>", "", em.get("Artist", {}).get("value", ""))).strip() or "(autor não informado)",
                        "url": info.get("descriptionurl", ""), "licenca": em.get("LicenseShortName", {}).get("value", "ver página"),
                        "tipo": tipo, "dur": float(info.get("duration", 0) or 0), "largura": info.get("width", 0),
                        "altura": info.get("height", 0), "download_url": info["url"], "ext": ext})
    return out, None


FONTES = {"pexels": _pexels, "pixabay": _pixabay, "unsplash": _unsplash, "archive": _archive, "wikimedia": _wikimedia}


def _filtrar(c: dict, tipo: str, largura_min: int = 1920) -> bool:
    if c["tipo"] != tipo or not c.get("download_url"):
        return False
    if tipo == "video":
        return c["largura"] >= 1280 and 3 <= c["dur"] <= 30 and c["largura"] > c.get("altura", 0)
    return c["largura"] >= largura_min


def _rel(dst_dir: Path, nome: str) -> str:
    partes = dst_dir.as_posix().split("/")
    if partes[-2:] == ["broll", "cand"]:
        return f"broll/cand/{nome}"
    return (dst_dir / nome).as_posix()


def buscar(termo: str, tipo: str, fontes: list[str], n: int, dst_dir: Path, _fetch=None,
           largura_min: int = 1920) -> dict:
    fetch = _fetch or _fetch_url
    k = chaves()
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out, avisos = [], []
    for nome in fontes:
        fn = FONTES.get(nome)
        if not fn:
            avisos.append(f"{nome}: fonte desconhecida"); continue
        try:
            cands, av = fn(termo, tipo, n, k, fetch)
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            avisos.append(f"{nome}: resposta inesperada ({type(e).__name__}: {e})"); continue
        if av:
            avisos.append(av)
        baixados = 0
        for c in cands:
            if baixados >= n or not _filtrar(c, tipo, largura_min):
                continue
            status, corpo, _ = fetch(c["download_url"], None)
            if len(corpo) > MAX_DOWNLOAD:
                avisos.append(f"{nome}-{c['id']}: arquivo > 150 MB, descartado"); continue
            if not (200 <= status < 300) or not corpo:
                avisos.append(f"{nome}-{c['id']}: download {status} ({'corpo vazio' if not corpo else 'falhou'})"); continue
            if c.get("_download_location"):       # Unsplash exige avisar o download
                fetch(c["_download_location"], {"Authorization": f"Client-ID {k['unsplash']}"})
            arq = f"{nome}-{re.sub(r'[^\w\-.]+', '_', c['id'])}.{c['ext']}"
            (dst_dir / arq).write_bytes(corpo)
            meta = {kk: v for kk, v in c.items() if kk not in ("download_url", "ext", "altura", "_download_location")}
            meta["arq"] = _rel(dst_dir, arq)
            meta["score"] = None
            (dst_dir / f"{Path(arq).stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            out.append(meta); baixados += 1
    return {"candidatos": out, "avisos": avisos}


FONTE = Path("C:/Windows/Fonts/arial.ttf")


def _ff(args: list[str]) -> str:
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-y", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ({r.returncode}): {r.stderr[-800:]}")
    return r.stderr


def duracao(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def ler_broll(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _rotulo(txt: str) -> str:
    return txt.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _frame(arq: Path, dst_png: Path, rotulo: str, pos: float = 0.3):
    args = []
    if arq.suffix.lower() in (".mp4", ".webm", ".mov"):
        args += ["-ss", f"{max(0.0, duracao(arq) * pos):.3f}"]
    fonte = f":fontfile='{FONTE.as_posix().replace(':', chr(92) + ':')}'" if FONTE.exists() else ""
    vf = (f"scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2,"
          f"drawtext=text='{_rotulo(rotulo)}'{fonte}:x=6:y=h-22:fontsize=16:fontcolor=white:box=1:boxcolor=black@0.6")
    _ff([*args, "-i", str(arq), "-frames:v", "1", "-vf", vf, str(dst_png)])


def sheet(broll_json: Path, dst_png: Path, proj: Path) -> dict:
    b = ler_broll(broll_json)
    moms = b.get("momentos", [])
    cols = max((len(m.get("candidatos", [])) for m in moms), default=0)
    if not moms or not cols:
        raise ValueError("broll.json sem momentos/candidatos")
    tmp = Path(dst_png).with_suffix(".tiles"); tmp.mkdir(parents=True, exist_ok=True)
    tiles = []
    try:
        for m in moms:
            cands = m.get("candidatos", [])
            for k in range(cols):
                png = tmp / f"{m['id']}-{k}.png"
                if k < len(cands):
                    c = cands[k]
                    rot = f"{m['id']}-{k + 1} · {c['fonte']} · {c['dur']:.0f}s" if c["tipo"] == "video" else f"{m['id']}-{k + 1} · {c['fonte']} · foto"
                    _frame(proj / c["arq"], png, rot)
                else:
                    _ff(["-f", "lavfi", "-i", "color=c=black:s=480x270", "-frames:v", "1", str(png)])
                tiles.append(png)
        lista = tmp / "lista.txt"  # concat resolve relativo ao dir da lista → absoluto, aspas escapadas
        lista.write_text("".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n" for p in tiles),
                         encoding="utf-8")
        _ff(["-f", "concat", "-safe", "0", "-i", str(lista), "-vf", f"tile={cols}x{len(moms)}", "-frames:v", "1", str(dst_png)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"png": str(dst_png), "linhas": len(moms), "colunas": cols}


SLOT = (1032, 190, 850, 584)
ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]


def _cand_por_rotulo(m: dict, rotulo: str | None):
    """'b01-2' → candidatos[1]; None → None."""
    if not rotulo:
        return None
    try:
        pre, n = rotulo.rsplit("-", 1)
        k = int(n) - 1
        if k < 0 or pre != m["id"]:
            return None
        return m["candidatos"][k]
    except (ValueError, IndexError, KeyError):
        return None


def _overlay(m: dict, c: dict, proj: Path) -> tuple[Path, list[str]]:
    avisos = []
    trecho = float(m["t_out"]) - float(m["t_in"])
    src = proj / c["arq"]
    out_dir = proj / "broll" / "out"; out_dir.mkdir(parents=True, exist_ok=True)
    modo = m.get("modo", "cutin")
    al = ":alpha=1" if modo == "janela" else ""
    fade = f"fade=t=in:d=0.25{al},fade=t=out:st={max(trecho - 0.25, 0):.3f}:d=0.25{al}"
    if c["tipo"] == "video":
        dur = duracao(src)
        off = float(m.get("offset") or 0.0)
        if off + trecho > dur:
            off = max(0.0, dur - trecho); avisos.append(f"{m['id']}: offset ajustado para {off:.2f}s (fonte tem {dur:.1f}s)")
        entrada = ["-ss", f"{off:.3f}", "-t", f"{trecho:.3f}", "-i", str(src)]
        base = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=60"
    else:
        frames = int(round(trecho * 60))
        entrada = ["-i", str(src)]
        base = (f"scale=1920:1080:force_original_aspect_ratio=increase:out_range=tv,crop=1920:1080,"
                f"zoompan=z='min(zoom+0.0004,1.08)':d={frames}:s=1920x1080:fps=60,trim=duration={trecho:.3f}")
    if modo == "janela":
        x, y, w, h = SLOT
        vf = (f"[0:v]{base},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=rgba,{fade}[win];"
              f"color=c=black@0:s=1920x1080:r=60:d={trecho:.3f},format=rgba[bg];[bg][win]overlay={x}:{y}:format=auto,trim=duration={trecho:.3f}[out]")
        dst = out_dir / f"{m['id']}.mov"
        _ff([*entrada, "-filter_complex", vf, "-map", "[out]", "-c:v", "qtrle", "-pix_fmt", "argb", "-an", "-t", f"{trecho:.3f}", str(dst)])
    else:
        dst = out_dir / f"{m['id']}.mp4"
        _ff([*entrada, "-vf", f"{base},{fade}", *ENC, "-t", f"{trecho:.3f}", str(dst)])
    return dst, avisos


def _cruza(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def preparar(broll_json: Path, edl_json: Path, proj: Path) -> dict:
    b = ler_broll(broll_json)
    edl = pipeline.read_json(Path(edl_json), None)
    if edl is None:
        return {"ok": False, "gerados": [], "avisos": [], "erros": [f"edl.json ilegível: {edl_json}"]}
    fixos = [o for o in edl.get("overlays", []) if not str(o.get("file", "")).startswith("broll/out/")]
    erros, avisos, novos, gerados = [], [], [], []
    for m in b.get("momentos", []):
        if m.get("status") != "aprovado":
            continue
        t_in, t_out = float(m["t_in"]), float(m["t_out"])
        if t_out <= t_in:
            erros.append(f"{m['id']}: t_out ({t_out}) <= t_in ({t_in})"); continue
        c = _cand_por_rotulo(m, m.get("escolhido"))
        if m.get("escolhido") and c is None:
            erros.append(f"{m['id']}: escolhido '{m['escolhido']}' não existe nos candidatos"); continue
        if c is None:
            if not m.get("candidatos"):
                erros.append(f"{m['id']}: aprovado sem candidatos"); continue
            c = m["candidatos"][0]; avisos.append(f"{m['id']}: sem escolhido — usando o primeiro candidato")
        for o in fixos:
            o0 = float(o["start_in_output"]); o1 = o0 + float(o["duration"])
            if _cruza(t_in, t_out, o0, o1):
                erros.append(f"{m['id']}: conflita com overlay {o['file']} ({o0:.1f}–{o1:.1f}s)")
        if c["tipo"] == "video":
            dur = duracao(proj / c["arq"])
            if dur < t_out - t_in:
                erros.append(f"{m['id']}: fonte tem {dur:.1f}s < trecho {t_out - t_in:.1f}s — escolha outro candidato"); continue
        novos.append((m, c))
    for i, (ma, _) in enumerate(novos):
        for mb, _ in novos[i + 1:]:
            if _cruza(float(ma["t_in"]), float(ma["t_out"]), float(mb["t_in"]), float(mb["t_out"])):
                erros.append(f"{ma['id']} e {mb['id']} se sobrepõem")
    if erros:
        return {"ok": False, "gerados": [], "avisos": avisos, "erros": erros}
    if not novos:
        avisos.append("0 aprovados — overlays de b-roll removidos do EDL")
    ovs = []
    for m, c in novos:
        dst, av = _overlay(m, c, proj); avisos += av
        rel = dst.relative_to(proj).as_posix()
        gerados.append(rel)
        ovs.append({"file": rel, "start_in_output": float(m["t_in"]), "duration": round(float(m["t_out"]) - float(m["t_in"]), 3)})
    edl = pipeline.read_json(Path(edl_json), None)        # reler antes de gravar
    if edl is None:
        return {"ok": False, "gerados": gerados, "avisos": avisos, "erros": ["edl.json ilegível na releitura — overlays gerados mas não gravados"]}
    edl["overlays"] = [o for o in edl.get("overlays", []) if not str(o.get("file", "")).startswith("broll/out/")] + ovs
    pipeline.atomic_write_json(Path(edl_json), edl)
    return {"ok": True, "gerados": gerados, "avisos": avisos, "erros": []}


EXIGE_CREDITO = ("unsplash", "wikimedia")


def _exige_credito(c: dict) -> bool:
    lic = c.get("licenca", "")
    return (c["fonte"] in EXIGE_CREDITO or "crédito" in lic.lower() or lic.startswith("CC BY")
            or "creativecommons.org/licenses/by" in lic)


DIVULGACAO = ("\n## Divulgação\n\nEste vídeo usa clipes gerados por IA com aparência realista: no YouTube Studio "
              "marcar \"Conteúdo alterado ou sintético\" = Sim; no Instagram ativar o rótulo de IA.\n")


def creditos(broll_json: Path, dst_md: Path) -> dict:
    b = ler_broll(broll_json)
    linhas, desc, ia = [], [], 0
    for m in b.get("momentos", []):
        if m.get("status") != "aprovado":
            continue
        c = _cand_por_rotulo(m, m.get("escolhido")) or (m.get("candidatos") or [None])[0]
        if not c:
            continue
        if c.get("fonte") == "ia":
            ia += not (c.get("asset") and c.get("tipo") != "video")   # asset da marca parado = foto real
            linhas.append(f"- {m['id']} · {c.get('licenca') or 'gerado por IA'}")
            continue
        linhas.append(f"- {m['id']} · {c['fonte']} · {c['autor']} · {c['url']} · {c['licenca']}")
        if _exige_credito(c):
            desc.append(f"{c['autor']} — {c['url']} ({c['licenca']})")
    md = ("# Créditos de b-roll\n\n" + "\n".join(linhas) + "\n\n## Para a descrição\n\n"
          + ("\n".join(desc) if desc else "(nenhum crédito obrigatório)") + "\n" + (DIVULGACAO if ia else ""))
    Path(dst_md).write_text(md, encoding="utf-8")
    return {"usados": len(linhas), "com_credito": len(desc)}


def ranquear(broll_json: Path, proj: Path) -> dict:
    try:
        import torch
        import open_clip
        from PIL import Image
    except Exception as e:   # ImportError ou None em sys.modules
        return {"ok": False, "motivo": f"CLIP não instalado ({type(e).__name__}); pip install -r ui/requirements-clip.txt"}
    modelo, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
    tok = open_clip.get_tokenizer("ViT-B-32")
    modelo.eval()
    b = ler_broll(broll_json)
    tmp = Path(proj) / "broll" / ".rank"; tmp.mkdir(parents=True, exist_ok=True)
    n = pulados = 0
    with torch.no_grad():
        for m in b.get("momentos", []):
            if m.get("escolhido"):
                pulados += 1; continue
            txt = modelo.encode_text(tok([m.get("termo") or m.get("frase", "")]))
            txt = txt / txt.norm(dim=-1, keepdim=True)
            for i, c in enumerate(m.get("candidatos", [])):
                src = Path(proj) / c["arq"]
                frames = []
                if c["tipo"] == "video":
                    for pos in (0.1, 0.5, 0.9):
                        png = tmp / f"{m['id']}-{i}-{pos}.png"
                        _ff(["-ss", f"{duracao(src) * pos:.3f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=224:-2", str(png)])
                        frames.append(png)
                else:
                    frames.append(src)
                imgs = torch.stack([pre(Image.open(f).convert("RGB")) for f in frames])
                emb = modelo.encode_image(imgs); emb = emb / emb.norm(dim=-1, keepdim=True)
                c["score"] = round(float((emb @ txt.T).mean()), 4); n += 1
            m["candidatos"].sort(key=lambda c: -(c.get("score") or 0))
    for p in tmp.glob("*.png"): p.unlink()
    tmp.rmdir()
    pipeline.atomic_write_json(Path(broll_json), b)
    return {"ok": True, "ranqueados": n, "pulados": pulados}


def _cli(ns):
    if ns.cmd == "buscar":
        return buscar(ns.termo, ns.tipo, [f.strip() for f in ns.fontes.split(",")], ns.n, Path(ns.dst),
                      largura_min=ns.largura_min), 0
    if ns.cmd == "sheet":
        return sheet(Path(ns.broll), Path(ns.png), Path(ns.proj)), 0
    if ns.cmd == "ranquear":
        return ranquear(Path(ns.broll), Path(ns.proj)), 0
    if ns.cmd == "preparar":
        r = preparar(Path(ns.broll), Path(ns.edl), Path(ns.proj)); return r, (0 if r["ok"] else 1)
    return creditos(Path(ns.broll), Path(ns.md)), 0


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="b-roll de stock")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("buscar"); p.add_argument("termo"); p.add_argument("--tipo", choices=["video", "foto"], default="video")
    p.add_argument("--fontes", default="pexels,pixabay"); p.add_argument("--n", type=int, default=3); p.add_argument("--dst", required=True)
    p.add_argument("--largura-min", type=int, default=1920)
    p = sub.add_parser("sheet"); p.add_argument("broll"); p.add_argument("png"); p.add_argument("proj")
    p = sub.add_parser("ranquear"); p.add_argument("broll"); p.add_argument("proj")
    p = sub.add_parser("preparar"); p.add_argument("broll"); p.add_argument("edl"); p.add_argument("proj")
    p = sub.add_parser("creditos"); p.add_argument("broll"); p.add_argument("md")
    ns = ap.parse_args()
    try:
        out, code = _cli(ns)
    except Exception as e:
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)
