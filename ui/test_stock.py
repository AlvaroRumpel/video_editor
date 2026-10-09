# ui/test_stock.py
import json
import os
import shutil
import sys
import subprocess
from pathlib import Path
import pytest
import stock

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def mp4(tmp_path) -> bytes:
    p = tmp_path / "src.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast", str(p))
    return p.read_bytes()


@pytest.fixture
def jpg(tmp_path) -> bytes:
    p = tmp_path / "src.jpg"
    _ff("-f", "lavfi", "-i", "testsrc=s=2560x1440:d=1", "-frames:v", "1", str(p))
    return p.read_bytes()


PEXELS_VIDEOS = {"videos": [
    {"id": 1, "duration": 12, "width": 1920, "height": 1080, "url": "https://www.pexels.com/video/1/",
     "user": {"name": "Ana"}, "video_files": [
         {"width": 1280, "height": 720, "link": "https://cdn/1-720.mp4", "file_type": "video/mp4"},
         {"width": 1920, "height": 1080, "link": "https://cdn/1-1080.mp4", "file_type": "video/mp4"},
         {"width": 3840, "height": 2160, "link": "https://cdn/1-4k.mp4", "file_type": "video/mp4"}]},
    {"id": 2, "duration": 45, "width": 1920, "height": 1080, "url": "https://www.pexels.com/video/2/",
     "user": {"name": "Bo"}, "video_files": [{"width": 1920, "height": 1080, "link": "https://cdn/2.mp4", "file_type": "video/mp4"}]},
    {"id": 3, "duration": 8, "width": 640, "height": 360, "url": "https://www.pexels.com/video/3/",
     "user": {"name": "Cy"}, "video_files": [{"width": 640, "height": 360, "link": "https://cdn/3.mp4", "file_type": "video/mp4"}]},
    {"id": 4, "duration": 8, "width": 1080, "height": 1920, "url": "https://www.pexels.com/video/4/",
     "user": {"name": "Di"}, "video_files": [{"width": 1080, "height": 1920, "link": "https://cdn/4.mp4", "file_type": "video/mp4"}]},
]}
PIXABAY_VIDEOS = {"hits": [
    {"id": 77, "duration": 10, "pageURL": "https://pixabay.com/videos/77/", "user": "Eve",
     "videos": {"large": {"url": "https://cdn/77-l.mp4", "width": 1920, "height": 1080},
                "medium": {"url": "https://cdn/77-m.mp4", "width": 1280, "height": 720}}}]}
PEXELS_FOTOS = {"photos": [
    {"id": 9, "width": 4000, "height": 2667, "url": "https://www.pexels.com/photo/9/",
     "photographer": "Fi", "src": {"original": "https://cdn/9.jpg", "large2x": "https://cdn/9-2x.jpg"}},
    {"id": 10, "width": 1200, "height": 800, "url": "https://www.pexels.com/photo/10/",
     "photographer": "Gu", "src": {"original": "https://cdn/10.jpg", "large2x": "https://cdn/10-2x.jpg"}},
]}


def _fetch_factory(mp4, jpg, extra=None):
    chamadas = []
    def fetch(url, headers=None):
        chamadas.append((url, headers or {}))
        if extra and url in extra:
            return extra[url]
        if "api.pexels.com/videos" in url:
            return 200, json.dumps(PEXELS_VIDEOS).encode(), {}
        if "api.pexels.com/v1" in url:
            return 200, json.dumps(PEXELS_FOTOS).encode(), {}
        if "pixabay.com/api/videos" in url:
            return 200, json.dumps(PIXABAY_VIDEOS).encode(), {}
        if url.endswith(".mp4"):
            return 200, mp4, {}
        if url.endswith(".jpg"):
            return 200, jpg, {}
        return 404, b"", {}
    fetch.chamadas = chamadas
    return fetch


@pytest.fixture
def chaves(monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "PK", "pixabay": "XK", "unsplash": ""})


def test_buscar_pexels_filtra_e_baixa(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg)
    dst = tmp_path / "proj" / "broll" / "cand"
    r = stock.buscar("courthouse", "video", ["pexels"], 3, dst, _fetch=fetch)
    ids = [c["id"] for c in r["candidatos"]]
    assert ids == ["1"]                                  # 2 longo, 3 pequeno, 4 vertical
    c = r["candidatos"][0]
    assert c["fonte"] == "pexels" and c["autor"] == "Ana" and c["tipo"] == "video"
    assert c["dur"] == 12 and c["largura"] == 1920 and c["licenca"] == "Pexels License"
    assert c["arq"] == "broll/cand/pexels-1.mp4" and (dst / "pexels-1.mp4").exists()
    assert json.loads((dst / "pexels-1.json").read_text(encoding="utf-8"))["url"] == "https://www.pexels.com/video/1/"
    baixados = [u for u, _ in fetch.chamadas if u.endswith(".mp4")]
    assert baixados == ["https://cdn/1-1080.mp4"]        # menor variante >= 1920
    api = [h for u, h in fetch.chamadas if "api.pexels.com" in u][0]
    assert api.get("Authorization") == "PK"


def test_buscar_pixabay_e_n_por_fonte(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg)
    r = stock.buscar("court", "video", ["pexels", "pixabay"], 1, tmp_path / "c", _fetch=fetch)
    assert [c["fonte"] for c in r["candidatos"]] == ["pexels", "pixabay"]
    px = r["candidatos"][1]
    assert px["id"] == "77" and px["autor"] == "Eve" and px["licenca"] == "Pixabay Content License"
    assert [u for u, _ in fetch.chamadas if "77" in u and u.endswith(".mp4")] == ["https://cdn/77-l.mp4"]


def test_buscar_fotos_pexels(tmp_path, mp4, jpg, chaves):
    r = stock.buscar("court", "foto", ["pexels"], 3, tmp_path / "c", _fetch=_fetch_factory(mp4, jpg))
    assert [c["id"] for c in r["candidatos"]] == ["9"]   # 10 tem largura < 1920
    assert r["candidatos"][0]["tipo"] == "foto" and r["candidatos"][0]["arq"].endswith("pexels-9.jpg")


def test_buscar_sem_chave_pula(tmp_path, mp4, jpg, monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "", "pixabay": "", "unsplash": ""})
    fetch = _fetch_factory(mp4, jpg)
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("pexels" in a and "chave" in a for a in r["avisos"])
    assert fetch.chamadas == []


def test_buscar_corpo_vazio_descarta(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={"https://cdn/1-1080.mp4": (200, b"", {})})
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("vazio" in a for a in r["avisos"])
    assert not (tmp_path / "c" / "pexels-1.mp4").exists()


def test_chaves_env(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "abc")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr(stock, "_ler_env", lambda: {})
    k = stock.chaves()
    assert k["pexels"] == "abc" and k["pixabay"] == ""


def test_download_gigante_descarta(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={"https://cdn/1-1080.mp4": (200, b"x" * (stock.MAX_DOWNLOAD + 1), {})})
    r = stock.buscar("x", "video", ["pexels"], 3, tmp_path / "c", _fetch=fetch)
    assert r["candidatos"] == [] and any("150 MB" in a for a in r["avisos"])
    assert not (tmp_path / "c" / "pexels-1.mp4").exists()


def test_aviso_nao_vaza_chave(tmp_path, mp4, jpg, chaves):
    fetch = _fetch_factory(mp4, jpg, extra={})
    base = fetch
    def f(url, headers=None):
        if "pixabay.com/api/videos" in url:
            return 500, b"", {}
        return base(url, headers)
    r = stock.buscar("x", "video", ["pixabay"], 3, tmp_path / "c", _fetch=f)
    assert any("pixabay.com/api/videos/" in a for a in r["avisos"])
    assert not any("XK" in a for a in r["avisos"])


UNSPLASH = {"results": [{"id": "u1", "width": 5000, "height": 3000, "links": {"html": "https://unsplash.com/photos/u1"},
                         "user": {"name": "Hal"}, "urls": {"full": "https://cdn/u1.jpg", "regular": "https://cdn/u1-r.jpg"}}]}
ARCHIVE_SEARCH = {"response": {"docs": [{"identifier": "courtfilm"}]}}
ARCHIVE_META = {"metadata": {"title": "Court film", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/",
                             "creator": "Prelinger"},
                "files": [{"name": "court.mp4", "format": "MPEG4", "size": "5000000", "width": "1920", "height": "1080", "length": "20.5"},
                          {"name": "big.mp4", "format": "MPEG4", "size": "900000000", "width": "1920", "height": "1080", "length": "20"}]}
WIKI_SEARCH = {"query": {"search": [{"title": "File:Gavel.webm"}]}}
WIKI_INFO = {"query": {"pages": {"1": {"title": "File:Gavel.webm", "imageinfo": [
    {"url": "https://upload.wikimedia.org/x/Gavel.webm", "width": 1920, "height": 1080, "duration": 9.0,
     "descriptionurl": "https://commons.wikimedia.org/wiki/File:Gavel.webm",
     "extmetadata": {"Artist": {"value": "Ivo"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}


def _fetch2(mp4, jpg):
    chamadas = []
    def fetch(url, headers=None):
        chamadas.append((url, headers or {}))
        if "api.unsplash.com" in url: return 200, json.dumps(UNSPLASH).encode(), {}
        if "advancedsearch.php" in url: return 200, json.dumps(ARCHIVE_SEARCH).encode(), {}
        if "archive.org/metadata/" in url: return 200, json.dumps(ARCHIVE_META).encode(), {}
        if "list=search" in url: return 200, json.dumps(WIKI_SEARCH).encode(), {}
        if "prop=imageinfo" in url: return 200, json.dumps(WIKI_INFO).encode(), {}
        if url.endswith((".mp4", ".webm")): return 200, mp4, {}
        if url.endswith(".jpg"): return 200, jpg, {}
        return 404, b"", {}
    fetch.chamadas = chamadas
    return fetch


def test_unsplash_foto(tmp_path, mp4, jpg, monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "", "pixabay": "", "unsplash": "UK"})
    fetch = _fetch2(mp4, jpg)
    r = stock.buscar("gavel", "foto", ["unsplash"], 2, tmp_path / "c", _fetch=fetch)
    c = r["candidatos"][0]
    assert c["fonte"] == "unsplash" and c["autor"] == "Hal" and c["licenca"] == "Unsplash License (crédito obrigatório)"
    assert c["url"] == "https://unsplash.com/photos/u1"
    assert [h for u, h in fetch.chamadas if "api.unsplash.com" in u][0]["Authorization"] == "Client-ID UK"


def test_archive_video_pula_grande(tmp_path, mp4, jpg, chaves):
    r = stock.buscar("court", "video", ["archive"], 3, tmp_path / "c", _fetch=_fetch2(mp4, jpg))
    assert [c["id"] for c in r["candidatos"]] == ["courtfilm"]
    c = r["candidatos"][0]
    assert c["dur"] == 20.5 and c["autor"] == "Prelinger" and "publicdomain" in c["licenca"]
    assert c["arq"].endswith("archive-courtfilm.mp4")


def test_wikimedia_video(tmp_path, mp4, jpg, chaves):
    r = stock.buscar("gavel", "video", ["wikimedia"], 3, tmp_path / "c", _fetch=_fetch2(mp4, jpg))
    c = r["candidatos"][0]
    assert c["fonte"] == "wikimedia" and c["id"] == "Gavel.webm" and c["licenca"] == "CC BY-SA 4.0" and c["autor"] == "Ivo"
    assert c["arq"].endswith("archive-courtfilm.mp4") is False and c["arq"].endswith(".webm")


def test_429_retry_uma_vez(tmp_path, mp4, jpg, chaves, monkeypatch):
    monkeypatch.setattr(stock.time, "sleep", lambda s: None)
    vezes = {"n": 0}
    def fetch(url, headers=None):
        if "api.pexels.com" in url:
            vezes["n"] += 1
            if vezes["n"] == 1:
                return 429, b"", {"Retry-After": "1"}
            return 200, json.dumps(PEXELS_VIDEOS).encode(), {}
        return 200, mp4, {}
    r = stock.buscar("x", "video", ["pexels"], 1, tmp_path / "c", _fetch=fetch)
    assert vezes["n"] == 2 and len(r["candidatos"]) == 1


def test_resposta_malformada_continua(tmp_path, mp4, jpg, chaves):
    def fetch(url, headers=None):
        if "api.pexels.com" in url: return 200, b"{nope", {}
        if "pixabay.com/api/videos" in url: return 200, json.dumps(PIXABAY_VIDEOS).encode(), {}
        return 200, mp4, {}
    r = stock.buscar("x", "video", ["pexels", "pixabay"], 1, tmp_path / "c", _fetch=fetch)
    assert [c["fonte"] for c in r["candidatos"]] == ["pixabay"]
    assert any("inválida" in a for a in r["avisos"])


def _broll(proj: Path, mp4: bytes, jpg: bytes, n_mom=2, n_cand=2):
    cand = proj / "broll" / "cand"; cand.mkdir(parents=True, exist_ok=True)
    moms = []
    for i in range(n_mom):
        cs = []
        for k in range(n_cand):
            nome = f"m{i}-{k}.mp4" if k == 0 else f"m{i}-{k}.jpg"
            (cand / nome).write_bytes(mp4 if k == 0 else jpg)
            cs.append({"arq": f"broll/cand/{nome}", "fonte": "pexels", "id": f"{i}{k}", "autor": "A", "url": "https://x/",
                       "licenca": "Pexels License", "tipo": "video" if k == 0 else "foto", "dur": 6.0 if k == 0 else 0.0,
                       "largura": 1920, "score": None})
        moms.append({"id": f"b0{i + 1}", "t_in": 10.0 + 30 * i, "t_out": 13.0 + 30 * i, "modo": "cutin",
                     "frase": "x", "termo": "y", "fontes": ["pexels"], "candidatos": cs,
                     "escolhido": None, "offset": 0.0, "status": "proposto"})
    p = proj / "broll.json"
    p.write_text(json.dumps({"momentos": moms}), encoding="utf-8")
    return p


def _dim(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,pix_fmt", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return s["width"], s["height"], s["r_frame_rate"], s.get("pix_fmt")


def test_sheet_grade(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"
    bj = _broll(proj, mp4, jpg)
    r = stock.sheet(bj, proj / "broll" / "sheet.png", proj)
    assert r["linhas"] == 2 and r["colunas"] == 2
    w, h, _, _ = _dim(proj / "broll" / "sheet.png")
    assert (w, h) == (960, 540)


def test_sheet_caminhos_relativos(tmp_path, mp4, jpg, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _broll(tmp_path / "proj", mp4, jpg)
    stock.sheet(Path("proj/broll.json"), Path("proj/broll/sheet.png"), Path("proj"))
    assert (tmp_path / "proj" / "broll" / "sheet.png").is_file()
    assert not (tmp_path / "proj" / "broll" / "sheet.tiles").exists()


def _edl(proj: Path, overlays=None):
    e = {"version": 1, "sources": {"MAIN": "x.mkv"}, "ranges": [], "grade": "", "total_duration_s": 100.0,
         "overlays": overlays or [{"file": "animations/remotion/out/Opening.mov", "start_in_output": 0.0, "duration": 5.5}]}
    p = proj / "edl.json"; p.write_text(json.dumps(e), encoding="utf-8"); return p


def _aprova(bj: Path, **por_id):
    b = json.loads(bj.read_text(encoding="utf-8"))
    for m in b["momentos"]:
        if m["id"] in por_id:
            m["status"] = "aprovado"; m["escolhido"] = por_id[m["id"]]
    bj.write_text(json.dumps(b), encoding="utf-8")


def test_preparar_cutin_e_merge(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    _aprova(bj, b01="b01-1")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] and r["gerados"] == ["broll/out/b01.mp4"]
    out = proj / "broll" / "out" / "b01.mp4"
    w, h, fps, _ = _dim(out)
    assert (w, h) == (1920, 1080) and fps == "60/1"
    assert abs(stock.duracao(out) - 3.0) < 0.05
    assert subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True).stdout.strip() == ""
    e = json.loads(edl.read_text(encoding="utf-8"))
    assert e["overlays"][0]["file"].endswith("Opening.mov")                      # preservado
    assert {"file": "broll/out/b01.mp4", "start_in_output": 10.0, "duration": 3.0} in e["overlays"]
    r2 = stock.preparar(bj, edl, proj)                                           # idempotente: substitui, não duplica
    e = json.loads(edl.read_text(encoding="utf-8"))
    assert sum(1 for o in e["overlays"] if o["file"].startswith("broll/out/")) == 1


def test_preparar_janela_alpha_e_foto(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0]["modo"] = "janela"; b["momentos"][1]["modo"] = "foto"
    bj.write_text(json.dumps(b), encoding="utf-8")
    _aprova(bj, b01="b01-1", b02="b02-2")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] and sorted(r["gerados"]) == ["broll/out/b01.mov", "broll/out/b02.mp4"]
    _, _, _, pix = _dim(proj / "broll" / "out" / "b01.mov")
    assert pix in ("argb", "rgba", "bgra")
    assert abs(stock.duracao(proj / "broll" / "out" / "b02.mp4") - 3.0) < 0.1
    assert _dim(proj / "broll" / "out" / "b02.mp4")[3] == "yuv420p"


def test_preparar_conflito_nao_escreve(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    edl = _edl(proj, [{"file": "animations/remotion/out/X.mov", "start_in_output": 11.0, "duration": 4.0}])
    _aprova(bj, b01="b01-1")
    antes = edl.read_text(encoding="utf-8")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] is False and any("b01" in e and "X.mov" in e for e in r["erros"])
    assert edl.read_text(encoding="utf-8") == antes


def test_preparar_validacoes(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0].update(status="aprovado", escolhido="nao-existe")
    b["momentos"][1].update(status="aprovado", escolhido=None, t_out=40.0, t_in=45.0)
    bj.write_text(json.dumps(b), encoding="utf-8")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] is False
    assert any("b01" in e and "escolhido" in e for e in r["erros"])
    assert any("b02" in e and "t_out" in e for e in r["erros"])


def test_preparar_sem_escolhido_usa_primeiro_e_offset_curto(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0].update(status="aprovado", escolhido=None, offset=5.5)    # fonte tem 6 s, trecho 3 s
    b["momentos"][1]["status"] = "vetado"
    bj.write_text(json.dumps(b), encoding="utf-8")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] and r["gerados"] == ["broll/out/b01.mp4"]
    assert any("b01" in a and "primeiro candidato" in a for a in r["avisos"])
    assert any("offset" in a for a in r["avisos"])
    assert abs(stock.duracao(proj / "broll" / "out" / "b01.mp4") - 3.0) < 0.05


def test_creditos(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0]["candidatos"][0].update(fonte="unsplash", licenca="Unsplash License (crédito obrigatório)", autor="Hal", url="https://unsplash.com/photos/u1")
    b["momentos"][0].update(status="aprovado", escolhido="b01-1")
    b["momentos"][1].update(status="aprovado", escolhido="b02-1")
    bj.write_text(json.dumps(b), encoding="utf-8")
    r = stock.creditos(bj, proj / "creditos.md")
    md = (proj / "creditos.md").read_text(encoding="utf-8")
    assert r == {"usados": 2, "com_credito": 1}
    assert "b01 · unsplash · Hal · https://unsplash.com/photos/u1" in md
    assert "## Para a descrição" in md and "Hal" in md.split("## Para a descrição")[1]
    assert "## Divulgação" not in md


def test_creditos_ia_divulgacao(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0]["candidatos"][0].update(fonte="ia", autor="", url="", modelo_video="fal-ai/kling",
                                             licenca="gerado por IA (fal/fal-ai/kling)")
    b["momentos"][0].update(status="aprovado", escolhido="b01-1")
    b["momentos"][1].update(status="aprovado", escolhido="b02-1")
    bj.write_text(json.dumps(b), encoding="utf-8")
    r = stock.creditos(bj, proj / "creditos.md")
    md = (proj / "creditos.md").read_text(encoding="utf-8")
    assert r == {"usados": 2, "com_credito": 0}
    assert "- b01 · gerado por IA (fal/fal-ai/kling)" in md
    assert "## Divulgação" in md and "sintético" in md
    assert "fal" not in md.split("## Para a descrição")[1].split("## Divulgação")[0]


def test_creditos_asset_still_sem_divulgacao(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0]["candidatos"][0].update(fonte="ia", asset=True, tipo="foto", autor="", url="",
                                             licenca="asset da marca animado por IA")
    b["momentos"][0].update(status="aprovado", escolhido="b01-1")
    bj.write_text(json.dumps(b), encoding="utf-8")
    stock.creditos(bj, proj / "creditos.md")
    md = (proj / "creditos.md").read_text(encoding="utf-8")
    assert "- b01 · asset da marca animado por IA" in md
    assert "## Divulgação" not in md


def test_preparar_releitura_falha_nao_apaga_edl(tmp_path, mp4, jpg, monkeypatch):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    _aprova(bj, b01="b01-1")
    antes = edl.read_text(encoding="utf-8")
    orig = stock.pipeline.read_json; n = {"i": 0}
    def rj(p, d):
        if Path(p) == edl:
            n["i"] += 1
            if n["i"] == 2: return None               # 1ª leitura ok, releitura falha
        return orig(p, d)
    monkeypatch.setattr(stock.pipeline, "read_json", rj)
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] is False and any("releitura" in e for e in r["erros"])
    assert edl.read_text(encoding="utf-8") == antes


def test_preparar_fonte_curta_e_rotulo_invalido(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0].update(status="aprovado", escolhido="b01-1", t_out=18.0)   # 8 s > fonte 6 s
    bj.write_text(json.dumps(b), encoding="utf-8")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] is False and r["gerados"] == [] and any("b01" in e and "fonte tem" in e for e in r["erros"])
    for rot in ("b01-0", "b02-1"):
        b["momentos"][0].update(escolhido=rot, t_out=13.0); bj.write_text(json.dumps(b), encoding="utf-8")
        r = stock.preparar(bj, edl, proj)
        assert r["ok"] is False and any("não existe" in e for e in r["erros"]), rot


def test_ranquear_sem_clip(tmp_path, mp4, jpg, monkeypatch):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    antes = bj.read_text(encoding="utf-8")
    monkeypatch.setitem(sys.modules, "open_clip", None)   # import falha
    r = stock.ranquear(bj, proj)
    assert r["ok"] is False and "CLIP" in r["motivo"]
    assert bj.read_text(encoding="utf-8") == antes


def test_cli_ranquear_e_preparar_conflito(tmp_path, mp4, jpg, monkeypatch):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    exe = [sys.executable, str(Path(stock.__file__))]
    r = subprocess.run([*exe, "ranquear", str(bj), str(proj)], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": str(Path(stock.__file__).parent)})
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] in (True, False)
    edl = _edl(proj, [{"file": "animations/remotion/out/X.mov", "start_in_output": 11.0, "duration": 4.0}])
    _aprova(bj, b01="b01-1")
    r = subprocess.run([*exe, "preparar", str(bj), str(edl), str(proj)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False
    r = subprocess.run([*exe, "sheet", str(tmp_path / "nao.json"), str(tmp_path / "x.png"), str(proj)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "erro" in json.loads(r.stdout)


def test_creditos_archive_cc_by_url(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg)
    b = json.loads(bj.read_text(encoding="utf-8"))
    b["momentos"][0]["candidatos"][0].update(fonte="archive", autor="Pre", url="https://archive.org/details/x",
                                             licenca="https://creativecommons.org/licenses/by/4.0/")
    b["momentos"][0].update(status="aprovado", escolhido="b01-1")
    bj.write_text(json.dumps(b), encoding="utf-8")
    assert stock.creditos(bj, proj / "c.md") == {"usados": 1, "com_credito": 1}
    assert "Pre" in (proj / "c.md").read_text(encoding="utf-8").split("## Para a descrição")[1]


def test_archive_sem_licenseurl_ignora(tmp_path, mp4, jpg, chaves):
    meta = {"metadata": {"creator": "X"}, "files": ARCHIVE_META["files"]}
    base = _fetch2(mp4, jpg)
    def f(url, headers=None):
        return (200, json.dumps(meta).encode(), {}) if "archive.org/metadata/" in url else base(url, headers)
    r = stock.buscar("court", "video", ["archive"], 3, tmp_path / "c", _fetch=f)
    assert r["candidatos"] == [] and "archive-courtfilm: sem licenseurl, ignorado" in r["avisos"]


def test_tolerancia_itens_e_fontes(tmp_path, mp4, jpg, chaves, monkeypatch):
    fotos = {"photos": [{"id": 1, "width": 4000, "height": 2000}, PEXELS_FOTOS["photos"][0]]}
    base = _fetch_factory(mp4, jpg)
    def f(url, headers=None):
        return (200, json.dumps(fotos).encode(), {}) if "api.pexels.com/v1" in url else base(url, headers)
    r = stock.buscar("x", "foto", ["pexels"], 3, tmp_path / "c", _fetch=f)
    assert [c["id"] for c in r["candidatos"]] == ["9"]
    assert stock._segundos("00:00:20.5") == 20.5 and stock._segundos("01:02") == 62 and stock._segundos("x") == 0
    def quebra(*a): raise KeyError("id")
    monkeypatch.setitem(stock.FONTES, "pexels", quebra)
    r = stock.buscar("x", "video", ["pexels", "pixabay"], 1, tmp_path / "d", _fetch=base)
    assert any(a.startswith("pexels: resposta inesperada (KeyError") for a in r["avisos"])
    assert [c["fonte"] for c in r["candidatos"]] == ["pixabay"]


def test_archive_length_hhmmss(tmp_path, mp4, jpg, chaves):
    meta = {"metadata": {"licenseurl": "https://x/", "creator": "P"},
            "files": [{"name": "a.mp4", "size": "10", "width": "1920", "height": "1080", "length": "00:00:20.5"}]}
    base = _fetch2(mp4, jpg)
    def f(url, headers=None):
        return (200, json.dumps(meta).encode(), {}) if "archive.org/metadata/" in url else base(url, headers)
    assert stock.buscar("c", "video", ["archive"], 1, tmp_path / "c", _fetch=f)["candidatos"][0]["dur"] == 20.5


def test_unsplash_download_location(tmp_path, mp4, jpg, monkeypatch):
    monkeypatch.setattr(stock, "chaves", lambda: {"pexels": "", "pixabay": "", "unsplash": "UK"})
    u = {"results": [{**UNSPLASH["results"][0], "links": {"html": "h", "download_location": "https://api.unsplash.com/photos/u1/download"}}]}
    base = _fetch2(mp4, jpg)
    def f(url, headers=None):
        return (200, json.dumps(u).encode(), {}) if "search/photos" in url else base(url, headers)
    calls = []
    def g(url, headers=None):
        calls.append((url, headers or {})); return f(url, headers)
    r = stock.buscar("g", "foto", ["unsplash"], 1, tmp_path / "c", _fetch=g)
    urls = [u_ for u_, _ in calls]
    assert urls.index("https://api.unsplash.com/photos/u1/download") > urls.index("https://cdn/u1.jpg")
    assert dict(calls[-1][1]) == {"Authorization": "Client-ID UK"}
    assert "_download_location" not in r["candidatos"][0]
    assert "_download_location" not in (tmp_path / "c" / "unsplash-u1.json").read_text(encoding="utf-8")


def test_preparar_zero_aprovados_e_sobreposicao(tmp_path, mp4, jpg):
    proj = tmp_path / "proj"; bj = _broll(proj, mp4, jpg); edl = _edl(proj)
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] and any("0 aprovados" in a for a in r["avisos"])
    b = json.loads(bj.read_text(encoding="utf-8")); b["momentos"][1].update(t_in=11.0, t_out=14.0)
    bj.write_text(json.dumps(b), encoding="utf-8")
    _aprova(bj, b01="b01-1", b02="b02-1")
    r = stock.preparar(bj, edl, proj)
    assert r["ok"] is False and "b01 e b02 se sobrepõem" in r["erros"]


def test_wikimedia_autor_unescape(tmp_path, mp4, jpg, chaves):
    import copy
    info = copy.deepcopy(WIKI_INFO)
    em = info["query"]["pages"]["1"]["imageinfo"][0]["extmetadata"]
    em["Artist"]["value"] = '<a href="x">Jo &amp; Co</a>'
    base = _fetch2(mp4, jpg)
    def f(url, headers=None):
        return (200, json.dumps(info).encode(), {}) if "prop=imageinfo" in url else base(url, headers)
    assert stock.buscar("g", "video", ["wikimedia"], 1, tmp_path / "c", _fetch=f)["candidatos"][0]["autor"] == "Jo & Co"
    em["Artist"]["value"] = "<br>"
    assert stock.buscar("g", "video", ["wikimedia"], 1, tmp_path / "d", _fetch=f)["candidatos"][0]["autor"] == "(autor não informado)"


def test_filtrar_largura_min_para_arquivo_historico():
    c = {"tipo": "foto", "download_url": "https://x/y.jpg", "largura": 1400}
    assert not stock._filtrar(c, "foto")
    assert stock._filtrar(c, "foto", 1200)
