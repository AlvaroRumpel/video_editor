import json
import subprocess
import sys
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
        "mixed_provider": {"unidade": "item", "usd": 0.6, "creditos": 200},
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


def _aprova(root, id_, reply="pode", global_=False):
    q = (root / ".ui-runtime" / "queue.json") if global_ else (_proj(root) / "ui" / "queue.json")
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps([{"id": id_, "status": "pending", "reply": reply}]), encoding="utf-8")


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
    _aprova(root, 777)
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


def test_autorizar_teto_projeto_aninhado(root):
    """Nested project uses full relative path as key in tetos_projeto."""
    proj = root / "edit" / "shorts" / "marca" / "proj"
    (proj / "ui").mkdir(parents=True, exist_ok=True)
    (root / ".ui-runtime").mkdir()
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"tetos_projeto": {"edit/shorts/marca/proj": 50}}), encoding="utf-8")
    # Spend 4.9
    budget.registrar(proj, "fal_kling", 1, usd=4.9, root=root)
    # Should be OK: 4.9+0.28 = 5.18 < 50 (custom ceiling, not default 5)
    d = budget.autorizar(root, proj, "fal_kling", 1)
    assert d["status"] == "ok"


def test_autorizar_mensal_bloqueia_projeto(root):
    """Monthly ceiling is checked first and blocks before project ceiling."""
    (root / ".ui-runtime").mkdir()
    # Both ceilings exceeded: monthly=1, project=1
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"teto_mensal_usd": 1, "teto_projeto_usd": 1}), encoding="utf-8")
    # Spend 0.9 in edit-fake project
    proj = _proj(root)
    budget.registrar(proj, "fal_kling", 1, usd=0.9, root=root)
    # Try to authorize 1 clip (0.28): 0.9+0.28 > 1 for both monthly and project
    # Monthly check should fire first
    d = budget.autorizar(root, proj, "fal_kling", 1)
    assert d["status"] == "bloqueado" and "mensal" in d["motivo"]


def test_autorizar_cota_antes_usd_check(root):
    """Credit check happens before USD approval threshold check."""
    saldo = {"usados": 0, "limite": 1000, "restante": 100, "reset_ts": 0}
    # mixed_provider: usd 0.6, creditos 200
    # 0.6 > 0.5 (would need approval for USD)
    # but 200 > 100 (restante) so should fail on quota first
    d = budget.autorizar(root, _proj(root), "mixed_provider", 1, saldo=saldo)
    assert d["status"] == "precisa_aprovacao" and "cota" in d["motivo"]


def test_autorizar_aprovacao_ignora_mensal_e_cota(root):
    """Approval overrides both monthly block and quota shortfall."""
    (root / ".ui-runtime").mkdir()
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"teto_mensal_usd": 1, "teto_projeto_usd": 50}), encoding="utf-8")
    # Spend 0.9 to exceed monthly limit
    budget.registrar(root / "edit-raw", "fal_kling", 1, usd=0.9, root=root)
    # Insufficient quota: restante 50, creditos 200
    saldo = {"usados": 0, "limite": 250, "restante": 50, "reset_ts": 0}
    # Autorizando 1 elevenlabs_sfx (0 USD, 200 creditos): hits both blocks without approval
    _aprova(root, 999, global_=True)
    d = budget.autorizar(root, _proj(root), "elevenlabs_sfx", 1, aprovacao=999, saldo=saldo)
    assert d["status"] == "ok"


def test_autorizar_saldo_suficiente_ok(root):
    """Sufficient saldo and within limits falls through to ok."""
    saldo = {"usados": 0, "limite": 1000, "restante": 1000, "reset_ts": 0}
    d = budget.autorizar(root, _proj(root), "elevenlabs_sfx", 1, saldo=saldo)
    assert d["status"] == "ok" and "dentro dos limites" in d["motivo"]


def test_cli_autorizar_e_registrar(root):
    proj = _proj(root)
    cli = str(Path(budget.__file__))
    def run(*a):
        return subprocess.run([sys.executable, cli, "--root", str(root), *a],
                              capture_output=True, text=True)
    r = run("autorizar", str(proj), "fal_kling", "1")
    assert r.returncode == 0 and json.loads(r.stdout)["status"] == "ok"
    assert run("autorizar", str(proj), "fal_kling", "3").returncode == 2
    r = run("registrar", str(proj), "fal_kling", "1", "--usd", "0.3")
    assert r.returncode == 0 and json.loads(r.stdout)["usd"] == 0.3
    assert budget.gasto_projeto(proj)["usd"] == 0.3


def test_autorizar_aprovacao_desconhecida_ou_sem_reply(root):
    budget.registrar(_proj(root), "fal_kling", 1, usd=4.9, root=root)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1, aprovacao=5)
    assert d["status"] == "bloqueado" and "não encontrada" in d["motivo"]
    _aprova(root, 5, reply="")
    assert budget.autorizar(root, _proj(root), "fal_kling", 1, aprovacao=5)["status"] == "bloqueado"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_registrar_rejeita_usd_invalido(root, bad):
    with pytest.raises(ValueError):
        budget.registrar(_proj(root), "fal_kling", 1, usd=bad, root=root)
    with pytest.raises(ValueError):
        budget.registrar(_proj(root), "fal_kling", 1, creditos=bad, root=root)


@pytest.mark.parametrize("bad", [0, -2, float("nan"), float("inf")])
def test_unidades_invalidas(root, bad):
    with pytest.raises(ValueError):
        budget.autorizar(root, _proj(root), "fal_kling", bad)
    with pytest.raises(ValueError):
        budget.registrar(_proj(root), "fal_kling", bad, root=root)


def test_projeto_inexistente(root):
    with pytest.raises(ValueError, match="projeto não existe"):
        budget.registrar(root / "typo", "fal_kling", 1, root=root)
    with pytest.raises(ValueError, match="projeto não existe"):
        budget.autorizar(root, root / "typo", "fal_kling", 1)
    assert not (root / "typo").exists()


def test_gasto_projeto_ignora_valores_invalidos(root):
    proj = _proj(root)
    (proj / "ui").mkdir(exist_ok=True)
    (proj / "ui" / "costs.jsonl").write_text(
        '{"usd": NaN}\n{"usd": null}\n123\n[]\n{"usd": Infinity}\n'
        '{"usd": 1, "creditos": 2}\n', encoding="utf-8")
    assert budget.gasto_projeto(proj) == {"usd": 1.0, "creditos": 2}


def test_saldo_cache_parcial_nao_quebra(root, monkeypatch):
    monkeypatch.setattr(budget, "_chave_elevenlabs", lambda: "")
    (root / ".ui-runtime").mkdir(exist_ok=True)
    (root / ".ui-runtime" / "quota.json").write_text(
        '{"elevenlabs": {"lido_em": 999999999999}}', encoding="utf-8")
    assert budget.saldo_elevenlabs(root) is None
    (root / ".ui-runtime" / "quota.json").write_text('[1]', encoding="utf-8")
    assert budget.saldo_elevenlabs(root) is None


def test_saldo_falha_e_cacheada(root, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    n = []

    def ruim(key):
        n.append(1)
        raise OSError("fora")
    assert budget.saldo_elevenlabs(root, _fetch=ruim) is None
    assert budget.saldo_elevenlabs(root, _fetch=ruim) is None
    assert len(n) == 1


def test_cli_erro_json(root):
    cli = str(Path(budget.__file__))
    r = subprocess.run([sys.executable, cli, "--root", str(root), "registrar",
                        str(root / "typo"), "fal_kling", "1"], capture_output=True, text=True)
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)
    r = subprocess.run([sys.executable, cli, "--root", str(root), "registrar",
                        str(_proj(root)), "fal_kling", "1", "--usd", "nan"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "erro" in json.loads(r.stdout)
