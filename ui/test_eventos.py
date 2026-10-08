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
                             "shorts", "thumbnail", "dublagem"],
    "padrao-youtube-shorts": ["transcricao", "candidatos", "aprovacao", "render", "draft"],
    "padrao-ads": ["referencia", "pesquisa", "roteiro", "producao", "audio", "render", "qc", "dublagem"],
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


UTC = timezone.utc


def _linha_raw(proj, obj):
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write((obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)) + "\n")


def test_registrar_decisao_valida(root):
    proj = _proj(root)
    d = eventos.registrar_decisao(proj, "trilha", "Phoenix2026", etapa="cortes", alternativas=["A", "B"],
                                  motivo="calma", custo_usd=0.4, confianca="alta", root=root)
    assert d["tipo"] == "decisao" and d["assunto"] == "trilha" and d["escolha"] == "Phoenix2026"
    assert d["alternativas"] == ["A", "B"] and d["motivo"] == "calma" and d["etapa"] == "cortes"
    assert d["custo_usd"] == 0.4 and d["confianca"] == "alta"
    assert datetime.fromisoformat(d["ts"]).tzinfo is not None
    gravada = json.loads((proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert gravada == d


def test_registrar_decisao_minima(root):
    d = eventos.registrar_decisao(_proj(root), "outro", "  x  ", root=root)
    assert d["escolha"] == "x" and d["alternativas"] == [] and d["motivo"] == ""
    assert "etapa" not in d and "custo_usd" not in d and "confianca" not in d


@pytest.mark.parametrize("kw", [
    {"assunto": "nada"}, {"escolha": "   "}, {"etapa": "inventada"}, {"confianca": "talvez"},
    {"custo_usd": float("nan")}, {"custo_usd": -1}, {"custo_usd": True}, {"custo_usd": "x"},
    {"alternativas": "a,b"},
])
def test_registrar_decisao_invalida(root, kw):
    args = {"assunto": "trilha", "escolha": "x", **kw}
    assunto, escolha = args.pop("assunto"), args.pop("escolha")
    with pytest.raises(ValueError):
        eventos.registrar_decisao(_proj(root), assunto, escolha, root=root, **args)
    assert not (_proj(root) / "ui" / "eventos.jsonl").exists()


def test_registrar_decisao_etapa_em_formato_sem_etapas(root):
    proj = _proj(root)
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "padrao-youtube"}), encoding="utf-8")
    with pytest.raises(ValueError, match="etapa"):
        eventos.registrar_decisao(proj, "corte", "x", etapa="cortes", root=root)
    eventos.registrar_decisao(proj, "corte", "x", root=root)   # sem etapa: ok


def test_registrar_decisao_projeto_inexistente(root):
    with pytest.raises(ValueError, match="projeto"):
        eventos.registrar_decisao(root / "nao-tem", "trilha", "x", root=root)


def test_registrar_resposta(root):
    proj = _proj(root)
    r = eventos.registrar_resposta(proj, 7, "ok b01:2")
    assert r["tipo"] == "resposta" and r["qid"] == 7 and r["texto"] == "ok b01:2"
    assert eventos.ler(proj, "resposta") == [r]
    with pytest.raises(ValueError):
        eventos.registrar_resposta(root / "nao-tem", 1, "x")


def test_ler_todos_os_tipos(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    _linha_raw(proj, {"ts": T(1), "tipo": "decisao", "assunto": "xyz", "escolha": "e1",
                      "alternativas": "não-lista", "custo_usd": -1, "confianca": "talvez", "motivo": 3})
    _linha_raw(proj, {"ts": T(2), "tipo": "decisao", "assunto": "trilha"})              # sem escolha
    _linha_raw(proj, {"ts": T(3), "tipo": "resposta", "texto": "x"})                    # sem qid
    _linha_raw(proj, {"ts": T(4), "tipo": "outra", "x": 1})
    _linha_raw(proj, "{quebrado")
    _linha_raw(proj, {"ts": T(5), "tipo": "resposta", "qid": 9, "texto": None})
    todos = eventos.ler(proj, None)
    assert [e["tipo"] for e in todos] == ["etapa", "decisao", "resposta"]
    d = todos[1]
    assert d["assunto"] == "outro" and d["alternativas"] == [] and d["motivo"] == ""
    assert "custo_usd" not in d and "confianca" not in d
    assert todos[2]["texto"] == ""
    assert [e["tipo"] for e in eventos.ler(proj)] == ["etapa"]          # default continua só etapa


def test_quadro_ate(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "inicio", T(0))
    _ev(proj, "transcricao", "fim", T(5))
    _ev(proj, "cortes", "inicio", T(10))
    _custo(proj, T(3), 0.2)
    _custo(proj, T(12), 0.3)
    q = eventos.quadro(proj, root=root, ate=datetime(2026, 10, 7, 10, 6, tzinfo=UTC))
    st = {e["id"]: e for e in q["etapas"]}
    assert st["transcricao"]["status"] == "fim" and st["transcricao"]["custo_usd"] == 0.2
    assert st["cortes"]["status"] == "pendente" and q["atual"] is None
    q2 = eventos.quadro(proj, root=root, ate=datetime(2026, 10, 7, 10, 13, tzinfo=UTC))
    c = {e["id"]: e for e in q2["etapas"]}["cortes"]
    assert c["status"] == "andamento" and c["custo_usd"] == 0.3          # agora = ate
    assert eventos.quadro(proj, root=root, ate=datetime(2026, 10, 7, 9, 0, tzinfo=UTC))["sem_historico"] is True


def test_quadro_ate_naive_vale_utc(root):
    proj = _proj(root)
    _ev(proj, "cortes", "inicio", T(0))
    q = eventos.quadro(proj, root=root, ate=datetime(2026, 10, 7, 10, 1))
    assert {e["id"]: e["status"] for e in q["etapas"]}["cortes"] == "andamento"
    assert eventos.quadro(proj, root=root, ate=datetime(2026, 10, 7, 9, 0))["sem_historico"] is True


def test_ler_rejeita_escolha_so_espaco(root):
    proj = _proj(root)
    _linha_raw(proj, {"ts": T(1), "tipo": "decisao", "assunto": "corte", "escolha": "   "})
    _linha_raw(proj, {"ts": T(2), "tipo": "decisao", "assunto": "corte", "escolha": "c1"})
    assert [d["escolha"] for d in eventos.ler(proj, "decisao")] == ["c1"]


def test_quadro_decisoes_por_etapa(root):
    proj = _proj(root)
    _ev(proj, "velha", "fim", T(0))                                        # fora da receita
    _linha_raw(proj, {"ts": T(1), "tipo": "decisao", "assunto": "corte", "escolha": "c1", "etapa": "cortes"})
    _linha_raw(proj, {"ts": T(2), "tipo": "decisao", "assunto": "outro", "escolha": "solta"})
    _linha_raw(proj, {"ts": T(3), "tipo": "decisao", "assunto": "grade", "escolha": "g", "etapa": "legado"})
    _linha_raw(proj, {"ts": T(4), "tipo": "decisao", "assunto": "outro", "escolha": "v", "etapa": "velha"})
    _linha_raw(proj, {"ts": T(5), "tipo": "decisao", "assunto": "corte", "escolha": "c2", "etapa": "cortes"})
    q = eventos.quadro(proj, root=root)
    cortes = {e["id"]: e for e in q["etapas"]}["cortes"]
    assert [d["escolha"] for d in cortes["decisoes"]] == ["c1", "c2"]
    assert {e["id"]: e for e in q["etapas"]}["render"]["decisoes"] == []
    assert [d["escolha"] for d in q["fora_da_receita"][0]["decisoes"]] == ["v"]
    assert [d["escolha"] for d in q["decisoes_soltas"]] == ["solta", "g"]


def test_quadro_so_decisoes_tem_historico(root):
    proj = _proj(root)
    _linha_raw(proj, {"ts": T(1), "tipo": "decisao", "assunto": "corte", "escolha": "c1"})
    assert eventos.quadro(proj, root=root)["sem_historico"] is False


def test_linha_ordem_custos_e_quadros(root):
    proj = _proj(root)
    _ev(proj, "transcricao", "fim", T(0))
    _ev(proj, "cortes", "inicio", T(5))
    _linha_raw(proj, {"ts": T(6), "tipo": "decisao", "assunto": "corte", "escolha": "c1", "etapa": "cortes"})
    _linha_raw(proj, {"ts": T(8), "tipo": "resposta", "qid": 3, "texto": "ok"})
    _custo(proj, T(5), 0.5)          # empate com o inicio de cortes: vem depois dele
    _custo(proj, T(7), 0.25)
    d = eventos.linha(proj, root=root)
    evs = d["eventos"]
    assert [e["tipo"] for e in evs] == ["etapa", "etapa", "custo", "decisao", "custo", "resposta"]
    assert [e["custo_acum"] for e in evs] == [0.0, 0.0, 0.5, 0.5, 0.75, 0.75]
    assert evs[2] == {"ts": T(5), "tipo": "custo", "provedor": "x", "usd": 0.5, "nota": "", "custo_acum": 0.5}
    assert len(d["quadros"]) == len(evs)
    q0 = {e["id"]: e["status"] for e in d["quadros"][0]["etapas"]}
    assert q0["transcricao"] == "fim" and q0["cortes"] == "pendente"
    assert d["quadros"][1]["atual"] == "cortes"
    assert d["quadros"][0]["etapas"][1] == {"id": "transcricao", "rotulo": "transcrição", "status": "fim"}


def test_linha_300_eventos_rapida(root):
    import time
    proj = _proj(root)
    base = datetime(2026, 10, 7, tzinfo=UTC)
    ids = ["transcricao", "cortes", "render"]
    for i in range(300):
        ts = (base + timedelta(seconds=i)).isoformat()
        if i % 3 == 2:
            _custo(proj, ts, 0.01)
        else:
            _ev(proj, ids[i % 3], "inicio" if i % 2 else "fim", ts)
    t0 = time.perf_counter()
    d = eventos.linha(proj, root=root)
    assert time.perf_counter() - t0 < 1.0
    assert len(d["eventos"]) == len(d["quadros"]) == 300
    ultimo = eventos.quadro(proj, root=root, ate=base + timedelta(seconds=299))
    assert d["quadros"][-1]["atual"] == ultimo["atual"]
    assert [e["status"] for e in d["quadros"][-1]["etapas"]] == [e["status"] for e in ultimo["etapas"]]


def test_linha_vazia(root):
    assert eventos.linha(_proj(root), root=root) == {"eventos": [], "quadros": []}


def _dec(proj, ts, assunto, escolha, **kw):
    (proj / "ui").mkdir(parents=True, exist_ok=True)
    _linha_raw(proj, {"ts": ts, "tipo": "decisao", "assunto": assunto, "escolha": escolha, **kw})


def test_decisoes_entre_projetos(root):
    fake, raw = root / "edit-fake", root / "edit-raw"
    _dec(fake, T(1), "trilha", "Phoenix2026", alternativas=["Incredulity"], motivo="calma", confianca="alta")
    _dec(fake, T(2), "corte", "tirar gaguejo")
    _dec(raw, T(3), "trilha", "Phoenix2026")
    _dec(raw, T(4), "trilha", "Incredulity", custo_usd=0.1)
    d = eventos.decisoes(root)
    assert [x["escolha"] for x in d["decisoes"]] == ["Incredulity", "Phoenix2026", "tirar gaguejo", "Phoenix2026"]
    assert d["frequentes"] == []
    primeiro = d["decisoes"][-1]
    assert primeiro == {"projeto": "edit-fake", "nome": "edit-fake", "ts": T(1), "etapa": None, "assunto": "trilha",
                        "escolha": "Phoenix2026", "alternativas": ["Incredulity"], "motivo": "calma",
                        "custo_usd": None, "confianca": "alta"}
    t = eventos.decisoes(root, assunto="trilha")
    assert len(t["decisoes"]) == 3
    assert t["frequentes"] == [{"escolha": "Phoenix2026", "n": 2}, {"escolha": "Incredulity", "n": 1}]
    with pytest.raises(ValueError):
        eventos.decisoes(root, assunto="nada")


def test_decisoes_projeto_ilegivel_pulado(root, monkeypatch):
    _dec(root / "edit-raw", T(3), "trilha", "Phoenix2026")
    real = eventos.ler

    def quebra(proj, tipo="etapa"):
        if proj.name == "edit-fake":
            raise RuntimeError("boom")
        return real(proj, tipo)

    monkeypatch.setattr(eventos, "ler", quebra)
    assert [x["projeto"] for x in eventos.decisoes(root)["decisoes"]] == ["edit-raw"]


def test_cli_decisao_linha_decisoes(root):
    proj = str(_proj(root))
    r = _cli(root, "decisao", proj, "trilha", "Phoenix2026", "--etapa", "cortes", "--alt", "A", "--alt", "B",
             "--motivo", "calma", "--custo", "0.4", "--confianca", "media")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["alternativas"] == ["A", "B"] and d["custo_usd"] == 0.4 and d["confianca"] == "media"
    assert _cli(root, "decisao", proj, "nada", "x").returncode == 1
    r = _cli(root, "linha", proj)
    assert r.returncode == 0 and json.loads(r.stdout)["eventos"][0]["tipo"] == "decisao"
    r = _cli(root, "decisoes", "--assunto", "trilha")
    assert r.returncode == 0 and json.loads(r.stdout)["frequentes"] == [{"escolha": "Phoenix2026", "n": 1}]


def test_protocolo_decisoes_documentado():
    txt = (pipeline.ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Decisões" in txt and "python ui/eventos.py decisao" in txt
    assert 'espera --nota "<pergunta curta>"' in txt
    for a in eventos.ASSUNTOS:
        assert a in txt
