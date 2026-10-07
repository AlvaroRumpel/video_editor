import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import eventos
import pipeline
from test_pipeline import fake_root  # fixture reexport

RECEITA = """---
etapas: roteiro?=Roteiro, transcricao=transcrição, cortes, render
---
# Formato: teste
"""


@pytest.fixture
def root(fake_root: Path) -> Path:
    (fake_root / "Formatos" / "teste.md").write_text(RECEITA, encoding="utf-8")
    proj = fake_root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    return fake_root


def _proj(root):
    return root / "edit-fake"


def _ev(proj, etapa, status, ts, nota=None, tipo="etapa"):
    linha = {"ts": ts, "tipo": tipo, "etapa": etapa, "status": status}
    if nota:
        linha["nota"] = nota
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def _custo(proj, ts, usd):
    with (proj / "ui" / "costs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "provedor": "x", "unidades": 1, "usd": usd, "creditos": 0}) + "\n")


T = lambda m: f"2026-10-07T10:{m:02d}:00+00:00"   # noqa: E731


def test_etapas_de_front_matter(root):
    assert eventos.etapas_de("teste", root) == [
        {"id": "roteiro", "rotulo": "Roteiro", "opcional": True},
        {"id": "transcricao", "rotulo": "transcrição", "opcional": False},
        {"id": "cortes", "rotulo": "cortes", "opcional": False},
        {"id": "render", "rotulo": "render", "opcional": False},
    ]


def test_etapas_de_sem_front_matter_ou_inexistente(root):
    assert eventos.etapas_de("padrao-youtube", root) == []   # "# receita", sem front-matter
    assert eventos.etapas_de("nao-existe", root) == []
    assert eventos.etapas_de(None, root) == []
    assert eventos.etapas_de("../x", root) == []


def test_etapas_de_ignora_id_invalido_e_duplicado(root):
    (root / "Formatos" / "t2.md").write_text(
        "---\netapas: a, B ruim, a, c-1\n---\n", encoding="utf-8")
    assert [e["id"] for e in eventos.etapas_de("t2", root)] == ["a", "c-1"]


def test_registrar_valido_faz_append(root):
    proj = _proj(root)
    e = eventos.registrar(proj, "cortes", "inicio", nota="vai", root=root)
    assert e["etapa"] == "cortes" and e["status"] == "inicio" and e["tipo"] == "etapa"
    assert datetime.fromisoformat(e["ts"]).tzinfo is not None
    eventos.registrar(proj, "cortes", "fim", root=root)
    linhas = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2 and "nota" not in json.loads(linhas[1])


@pytest.mark.parametrize("etapa,status", [("inventada", "inicio"), ("cortes", "acabou")])
def test_registrar_invalido_nao_escreve(root, etapa, status):
    proj = _proj(root)
    with pytest.raises(ValueError):
        eventos.registrar(proj, etapa, status, root=root)
    assert not (proj / "ui" / "eventos.jsonl").exists()


def test_registrar_formato_sem_etapas(root):
    proj = _proj(root)
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "padrao-youtube"}), encoding="utf-8")
    with pytest.raises(ValueError, match="sem etapas"):
        eventos.registrar(proj, "cortes", "inicio", root=root)


def test_registrar_projeto_inexistente(root):
    with pytest.raises(ValueError, match="projeto"):
        eventos.registrar(root / "nao-tem", "cortes", "inicio", root=root)


def test_ler_ignora_corrompidas_e_outros_tipos(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write("{quebrado\n")
        f.write(json.dumps({"ts": "não é data", "tipo": "etapa", "etapa": "x", "status": "fim"}) + "\n")
        f.write(json.dumps({"ts": T(1), "tipo": "etapa", "etapa": "x", "status": "talvez"}) + "\n")
        f.write("[1, 2]\n")
    _ev(proj, "cortes", "fim", T(2))
    _ev(proj, "x", "fim", T(3), tipo="decisao")
    assert [e["status"] for e in eventos.ler(proj)] == ["inicio", "fim"]


def test_quadro_sem_historico(root):
    q = eventos.quadro(_proj(root), root=root)
    assert q["formato"] == "teste" and q["sem_historico"] is True and q["atual"] is None
    assert [e["status"] for e in q["etapas"]] == ["pendente"] * 4
    assert q["fora_da_receita"] == []


def test_quadro_status_e_atual(root):
    proj = _proj(root)
    _ev(proj, "roteiro", "pulada", T(0))
    _ev(proj, "transcricao", "inicio", T(1))
    _ev(proj, "transcricao", "fim", T(5), nota="12 min")
    _ev(proj, "cortes", "inicio", T(6))
    q = eventos.quadro(proj, root=root, agora=datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc))
    st = {e["id"]: e for e in q["etapas"]}
    assert st["roteiro"]["status"] == "pulada"
    assert st["transcricao"]["status"] == "fim" and st["transcricao"]["fim"] == T(5)
    assert st["transcricao"]["nota"] == "12 min"
    assert st["cortes"]["status"] == "andamento" and st["cortes"]["fim"] is None
    assert st["render"]["status"] == "pendente"
    assert q["atual"] == "cortes" and q["sem_historico"] is False


def test_quadro_espera_vira_atual_sem_andamento(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "inicio", T(0))
    _ev(proj, "transcricao", "espera", T(1))
    q = eventos.quadro(proj, root=root)
    assert q["atual"] == "transcricao"
    assert q["etapas"][1]["status"] == "espera"


def test_quadro_falha(root):
    proj = _proj(root)
    _ev(proj, "render", "inicio", T(0))
    _ev(proj, "render", "falha", T(1), nota="ffmpeg")
    e = eventos.quadro(proj, root=root)["etapas"][3]
    assert e["status"] == "falha" and e["nota"] == "ffmpeg"


def test_quadro_reinicio_apos_fim(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    _ev(proj, "cortes", "fim", T(5), nota="12 min")
    _ev(proj, "cortes", "inicio", T(10))
    _custo(proj, T(2), 1.0)     # do 1º intervalo: não conta mais
    _custo(proj, T(12), 0.25)
    agora = datetime(2026, 10, 7, 10, 20, tzinfo=timezone.utc)
    e = eventos.quadro(proj, root=root, agora=agora)["etapas"][2]
    assert e["status"] == "andamento" and e["inicio"] == T(10) and e["fim"] is None
    assert e["custo_usd"] == 0.25
    assert e["nota"] is None   # nota do ciclo anterior não vaza


def test_quadro_retoma_apos_espera(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    _ev(proj, "cortes", "espera", T(2), nota="aprova?")
    _ev(proj, "cortes", "inicio", T(4))
    _ev(proj, "cortes", "fim", T(6), nota="ok")
    _custo(proj, T(1), 1.0)
    _custo(proj, T(5), 0.25)
    e = eventos.quadro(proj, root=root)["etapas"][2]
    assert e["status"] == "fim" and e["inicio"] == T(0) and e["fim"] == T(6)
    assert e["custo_usd"] == 1.25 and e["nota"] == "ok"


def test_quadro_custo_por_intervalo(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "inicio", T(0))
    _ev(proj, "transcricao", "fim", T(5))
    _custo(proj, T(3), 0.48)       # dentro
    _custo(proj, T(5), 0.02)       # na borda: dentro
    _custo(proj, T(9), 2.0)        # fora de qualquer etapa
    with (proj / "ui" / "costs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": T(4), "usd": "NaN?"}) + "\n")   # inválido: ignorado
    e = eventos.quadro(proj, root=root)["etapas"][1]
    assert e["custo_usd"] == 0.5


def test_quadro_custo_falha_fecha_janela(root):
    proj = _proj(root)
    _ev(proj, "render", "inicio", T(0))
    _ev(proj, "render", "falha", T(5))
    _custo(proj, T(3), 0.4)        # dentro
    _custo(proj, T(8), 9.0)        # depois da falha: fora
    agora = datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc)
    e = eventos.quadro(proj, root=root, agora=agora)["etapas"][3]
    assert e["status"] == "falha" and e["custo_usd"] == 0.4


def test_quadro_fora_da_receita(root):
    proj = _proj(root)
    _ev(proj, "legado", "fim", T(0))
    q = eventos.quadro(proj, root=root)
    assert [e["id"] for e in q["fora_da_receita"]] == ["legado"]
    assert q["fora_da_receita"][0]["rotulo"] == "legado"
    assert q["fora_da_receita"][0]["inicio"] is None and q["fora_da_receita"][0]["custo_usd"] == 0.0


def test_quadro_state_invalido(root):
    proj = _proj(root)
    (proj / "ui" / "state.json").write_text("[1, 2]", encoding="utf-8")
    q = eventos.quadro(proj, root=root)
    assert q["formato"] is None and q["etapas"] == []


def _cli(root, *a):
    cli = str(Path(eventos.__file__))
    return subprocess.run([sys.executable, cli, "--root", str(root), *a],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_etapa_e_quadro(root):
    proj = str(_proj(root))
    r = _cli(root, "etapa", proj, "cortes", "inicio", "--nota", "começo")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["nota"] == "começo"
    r = _cli(root, "quadro", proj)
    assert r.returncode == 0 and json.loads(r.stdout)["atual"] == "cortes"


def test_cli_validacao_exit_1(root):
    r = _cli(root, "etapa", str(_proj(root)), "inventada", "inicio")
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)


ESPERADO = {
    "padrao-youtube-longo": ["roteiro", "transcricao", "cortes", "fatos", "visual", "audio", "legenda", "render", "entrega",
                             "shorts", "thumbnail"],
    "padrao-youtube-shorts": ["transcricao", "candidatos", "aprovacao", "render", "draft"],
    "padrao-ads": ["referencia", "pesquisa", "roteiro", "producao", "audio", "render", "qc"],
    "pauta": ["pesquisa", "pauta", "aprovacao"],
    "thumbnail": ["frame", "recorte", "composicao", "variacoes"],
}


@pytest.mark.parametrize("formato,ids", ESPERADO.items())
def test_receitas_reais_declaram_etapas(formato, ids):
    etapas = eventos.etapas_de(formato, pipeline.ROOT)
    assert [e["id"] for e in etapas] == ids
    assert all(e["rotulo"] for e in etapas)


def test_receitas_reais_tem_mapa_de_etapas():
    for formato in ESPERADO:
        txt = (pipeline.ROOT / "Formatos" / f"{formato}.md").read_text(encoding="utf-8")
        assert "> Etapas" in txt, formato
