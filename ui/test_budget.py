import json
from pathlib import Path
import pytest
import budget
from test_pipeline import fake_root  # fixture reexport


@pytest.fixture
def root(fake_root: Path) -> Path:
    (fake_root / "ui").mkdir(exist_ok=True)
    (fake_root / "ui" / "precos.json").write_text(json.dumps({
        "fal_kling": {"unidade": "clipe", "usd": 0.28, "creditos": 0},
        "elevenlabs_sfx": {"unidade": "efeito", "usd": 0.0, "creditos": 200},
    }), encoding="utf-8")
    return fake_root


def test_ler_budget_defaults(root):
    b = budget.ler_budget(root)
    assert b["teto_mensal_usd"] == 30.0
    assert b["tetos_projeto"] == {}


def test_ler_budget_merge(root):
    (root / ".ui-runtime").mkdir()
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"teto_projeto_usd": 9}), encoding="utf-8")
    b = budget.ler_budget(root)
    assert b["teto_projeto_usd"] == 9 and b["teto_mensal_usd"] == 30.0


def test_estimar(root):
    assert budget.estimar(root, "fal_kling", 5) == {"usd": 1.4, "creditos": 0}
    assert budget.estimar(root, "elevenlabs_sfx", 2) == {"usd": 0.0, "creditos": 400}
    assert budget.estimar(root, "nao_existe", 1) is None


def test_registrar_e_gasto_projeto(root):
    proj = root / "edit-fake"
    budget.registrar(proj, "fal_kling", 2, usd=0.5, aprovacao=123, nota="teste", root=root)
    budget.registrar(proj, "elevenlabs_sfx", 1, root=root)   # sem usd => estimativa
    linhas = (proj / "ui" / "costs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    l0 = json.loads(linhas[0])
    assert l0["usd"] == 0.5 and l0["aprovacao"] == 123 and l0["ts"][:4].isdigit()
    assert budget.gasto_projeto(proj) == {"usd": 0.5, "creditos": 200}


def test_gasto_projeto_ignora_linha_corrompida(root):
    proj = root / "edit-fake"
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "costs.jsonl").write_text(
        '{"ts":"2026-10-01T00:00:00+00:00","usd":1,"creditos":0}\n'
        'lixo\n\n', encoding="utf-8")
    assert budget.gasto_projeto(proj, "2026-10") == {"usd": 1.0, "creditos": 0}


def test_gasto_mes_soma_projetos_e_ignora_outros_meses(root):
    a = root / "edit-fake" / "ui"
    b = root / "edit-raw" / "ui"
    a.mkdir(exist_ok=True)
    (a / "costs.jsonl").write_text(
        '{"ts":"2026-10-02T00:00:00+00:00","usd":1.5,"creditos":10}\n'
        '{"ts":"2026-09-30T23:59:59+00:00","usd":9,"creditos":9}\n', encoding="utf-8")
    (b / "costs.jsonl").write_text(
        '{"ts":"2026-10-05T00:00:00+00:00","usd":0.25,"creditos":0}\n', encoding="utf-8")
    assert budget.gasto_mes(root, "2026-10") == {"usd": 1.75, "creditos": 10}


def _proj(root):
    return root / "edit-fake"


def test_autorizar_ok(root):
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)
    assert d["status"] == "ok" and d["estimativa"]["usd"] == 0.28


def test_autorizar_precisa_aprovacao_por_acao(root):
    d = budget.autorizar(root, _proj(root), "fal_kling", 3)   # 0.84 > 0.5
    assert d["status"] == "precisa_aprovacao" and "0.5" in d["motivo"]


def test_autorizar_bloqueado_teto_projeto(root):
    budget.registrar(_proj(root), "fal_kling", 1, usd=4.9, root=root)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)   # 4.9+0.28 > 5
    assert d["status"] == "bloqueado" and "projeto" in d["motivo"]


def test_autorizar_bloqueado_teto_mensal(root):
    (root / ".ui-runtime").mkdir()
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"teto_mensal_usd": 1, "teto_projeto_usd": 50}), encoding="utf-8")
    budget.registrar(root / "edit-raw", "fal_kling", 1, usd=0.9, root=root)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)
    assert d["status"] == "bloqueado" and "mensal" in d["motivo"]


def test_autorizar_aprovacao_libera(root):
    budget.registrar(_proj(root), "fal_kling", 1, usd=4.9, root=root)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1, aprovacao=777)
    assert d["status"] == "ok"


def test_autorizar_provedor_desconhecido(root):
    d = budget.autorizar(root, _proj(root), "xyz", 1)
    assert d["status"] == "bloqueado" and "preço" in d["motivo"]


def test_autorizar_cota_acaba(root):
    saldo = {"usados": 9900, "limite": 10000, "restante": 100, "reset_ts": 0}
    d = budget.autorizar(root, _proj(root), "elevenlabs_sfx", 1, saldo=saldo)  # 200 > 100
    assert d["status"] == "precisa_aprovacao" and "cota" in d["motivo"]


def test_autorizar_cota_desconhecida(root):
    d = budget.autorizar(root, _proj(root), "elevenlabs_sfx", 1, saldo=None)
    assert d["status"] == "precisa_aprovacao" and "desconhecido" in d["motivo"]


def test_saldo_elevenlabs_cache_e_fetch(root, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    chamadas = []

    def fake(key):
        chamadas.append(key)
        return {"character_count": 10, "character_limit": 100,
                "next_character_count_reset_unix": 1}
    s = budget.saldo_elevenlabs(root, _fetch=fake)
    assert s == {"usados": 10, "limite": 100, "restante": 90, "reset_ts": 1}
    s2 = budget.saldo_elevenlabs(root, _fetch=fake)   # cache: não chama de novo
    assert s2 == s and chamadas == ["k"]


def test_saldo_elevenlabs_sem_chave(root, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "")
    assert budget.saldo_elevenlabs(root, _fetch=lambda k: {}) is None
