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
