# Controle de orçamento — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda ação paga passa por `budget.autorizar` antes e `budget.registrar` depois; a UI mostra gasto/teto por projeto e do mês e recebe pedidos de aprovação pela fila existente.

**Architecture:** Módulo puro `ui/budget.py` (sem FastAPI) lê/grava `.ui-runtime/budget.json`, `ui/precos.json`, `<proj>/ui/costs.jsonl` e cache `.ui-runtime/quota.json`. `server.py` expõe `GET/PUT /api/budget` e injeta `custos` em `load_project`. `app.js` desenha selo no header e resumo do mês. Um CLI em `budget.py` serve a sessão Claude a partir do shell.

**Tech Stack:** Python 3 stdlib (`json`, `urllib`), FastAPI + TestClient (já instalados), pytest, JS vanilla.

**Spec:** `docs/superpowers/specs/2026-10-06-orcamento-design.md`

## Global Constraints

- Nunca copiar código do OpenMontage (AGPL); tudo escrito do zero.
- `video-use/` não é alterado.
- Escrita em JSON: reler do disco antes, `pipeline.atomic_write_json`; `costs.jsonl` é append puro.
- Sem dependência nova em `ui/requirements.txt` (HTTP via `urllib`).
- Padrões iniciais: `teto_mensal_usd 30`, `teto_projeto_usd 5`, `aprovar_acima_usd 0.5`.
- Chave ElevenLabs: env `ELEVENLABS_API_KEY` ou `video-use/.env`.
- Textos de UI em português, mesmo estilo dos existentes.

## Review Focus

1. `costs.jsonl` com linha corrompida/vazia → ignorar a linha, não derrubar a UI (teste na Task 1).
2. `precos.json` sem o provedor pedido → `autorizar` devolve `bloqueado` com motivo "preço desconhecido", nunca `ok` silencioso (teste na Task 2).
3. API ElevenLabs fora do ar / sem chave → `saldo_elevenlabs` devolve `None` e `autorizar` trata como "saldo desconhecido" = `precisa_aprovacao` para provedores em créditos (teste na Task 2).
4. `PUT /api/budget` com valor não numérico ou negativo → 400, arquivo intacto (teste na Task 3).
5. Virada de mês: linha com `ts` de setembro não entra no total de outubro mesmo que esteja no mesmo arquivo (teste na Task 1).

---

### Task 1: `budget.py` — preços, registro e somas

**Files:**
- Create: `ui/budget.py`
- Create: `ui/precos.json`
- Test: `ui/test_budget.py`

**Interfaces:**
- Produces:
  - `DEFAULTS = {"teto_mensal_usd": 30.0, "teto_projeto_usd": 5.0, "aprovar_acima_usd": 0.5, "tetos_projeto": {}}`
  - `ler_budget(root: Path) -> dict` (DEFAULTS mesclado com `.ui-runtime/budget.json`)
  - `precos(root: Path) -> dict` (lê `root/ui/precos.json`)
  - `estimar(root, provedor: str, unidades: float) -> dict | None` → `{"usd": float, "creditos": int}`; `None` se provedor desconhecido
  - `registrar(proj: Path, provedor, unidades, usd=None, creditos=None, aprovacao=None, nota="") -> dict` (linha gravada; `usd`/`creditos` ausentes = estimativa)
  - `gasto_projeto(proj: Path, ano_mes: str | None = None) -> dict` → `{"usd", "creditos"}`
  - `gasto_mes(root: Path, ano_mes: str | None = None) -> dict`
  - `_ano_mes_atual() -> str` ("YYYY-MM", UTC)

- [ ] **Step 1: Criar `ui/precos.json`**

```json
{
  "elevenlabs_scribe": {"unidade": "min_audio", "usd": 0.0, "creditos": 0,
                        "nota": "free: creditos/min medido na 1a rodada (saldo antes/depois)"}
}
```

- [ ] **Step 2: Escrever testes que falham**

```python
# ui/test_budget.py
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
    budget.registrar(proj, "fal_kling", 2, usd=0.5, aprovacao=123, nota="teste")
    budget.registrar(proj, "elevenlabs_sfx", 1)   # sem usd => estimativa
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
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_budget.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'budget'`

- [ ] **Step 4: Implementar `ui/budget.py`**

```python
"""Orçamento: tetos, estimativa, registro e autorização de gastos.
Sem FastAPI. Arquivos: .ui-runtime/budget.json, ui/precos.json,
<proj>/ui/costs.jsonl, .ui-runtime/quota.json (cache do saldo ElevenLabs)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pipeline

DEFAULTS = {"teto_mensal_usd": 30.0, "teto_projeto_usd": 5.0,
            "aprovar_acima_usd": 0.5, "tetos_projeto": {}}


def _ano_mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ler_budget(root: Path) -> dict:
    b = dict(DEFAULTS)
    b.update(pipeline.read_json(root / ".ui-runtime" / "budget.json", {}))
    return b


def precos(root: Path) -> dict:
    return pipeline.read_json(root / "ui" / "precos.json", {})


def estimar(root: Path, provedor: str, unidades: float):
    p = precos(root).get(provedor)
    if not p:
        return None
    return {"usd": round(p.get("usd", 0.0) * unidades, 4),
            "creditos": int(round(p.get("creditos", 0) * unidades))}


def registrar(proj: Path, provedor: str, unidades: float, usd=None,
              creditos=None, aprovacao=None, nota: str = "") -> dict:
    root = proj.parent if (proj.parent / "ui" / "precos.json").exists() \
        else pipeline.ROOT
    est = estimar(root, provedor, unidades) or {"usd": 0.0, "creditos": 0}
    linha = {"ts": datetime.now(timezone.utc).isoformat(),
             "provedor": provedor, "unidades": unidades,
             "usd": est["usd"] if usd is None else float(usd),
             "creditos": est["creditos"] if creditos is None else int(creditos),
             "aprovacao": aprovacao, "nota": nota}
    path = proj / "ui" / "costs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha


def _linhas(path: Path):
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in texto.splitlines():
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba a UI


def gasto_projeto(proj: Path, ano_mes: str | None = None) -> dict:
    usd = 0.0
    cred = 0
    for l in _linhas(proj / "ui" / "costs.jsonl"):
        if ano_mes and not str(l.get("ts", "")).startswith(ano_mes):
            continue
        usd += float(l.get("usd", 0))
        cred += int(l.get("creditos", 0))
    return {"usd": round(usd, 4), "creditos": cred}


def gasto_mes(root: Path, ano_mes: str | None = None) -> dict:
    ano_mes = ano_mes or _ano_mes_atual()
    usd = 0.0
    cred = 0
    for p in pipeline.find_projects(root):
        g = gasto_projeto(pipeline.project_dir(root, p["id"]), ano_mes)
        usd += g["usd"]
        cred += g["creditos"]
    return {"usd": round(usd, 4), "creditos": cred}
```

Nota: `registrar` resolve o root pelo pai do projeto quando os testes usam
`tmp_path`; em produção os projetos ficam em `edit/...`, então cai em
`pipeline.ROOT`. Se `find_projects` não listar `edit-raw` (sem edl) confira
o teste `test_find_projects` em `test_pipeline.py`: ele lista projetos com
`ui/`, então `edit-raw` entra.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd ui && python -m pytest test_budget.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add ui/budget.py ui/precos.json ui/test_budget.py
git commit -m "feat(budget): preços, registro em costs.jsonl e somas por projeto/mês"
```

---

### Task 2: `autorizar` + saldo ElevenLabs

**Files:**
- Modify: `ui/budget.py`
- Test: `ui/test_budget.py`

**Interfaces:**
- Consumes: Task 1 (`ler_budget`, `estimar`, `gasto_projeto`, `gasto_mes`).
- Produces:
  - `saldo_elevenlabs(root, max_idade_s=300, _fetch=None) -> dict | None` → `{"usados", "limite", "restante", "reset_ts"}`; `None` sem chave/erro. `_fetch` é injeção para teste (callable que devolve o JSON da API).
  - `autorizar(root, proj, provedor, unidades, aprovacao=None, saldo=None) -> dict` → `{"status": "ok"|"precisa_aprovacao"|"bloqueado", "motivo": str, "estimativa": {...}}`. `saldo` opcional sobrescreve a leitura da API (teste e CLI).

- [ ] **Step 1: Testes que falham**

```python
# acrescentar em ui/test_budget.py
def _proj(root):
    return root / "edit-fake"


def test_autorizar_ok(root):
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)
    assert d["status"] == "ok" and d["estimativa"]["usd"] == 0.28


def test_autorizar_precisa_aprovacao_por_acao(root):
    d = budget.autorizar(root, _proj(root), "fal_kling", 3)   # 0.84 > 0.5
    assert d["status"] == "precisa_aprovacao" and "0.5" in d["motivo"]


def test_autorizar_bloqueado_teto_projeto(root):
    budget.registrar(_proj(root), "fal_kling", 1, usd=4.9)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)   # 4.9+0.28 > 5
    assert d["status"] == "bloqueado" and "projeto" in d["motivo"]


def test_autorizar_bloqueado_teto_mensal(root):
    (root / ".ui-runtime").mkdir()
    (root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"teto_mensal_usd": 1, "teto_projeto_usd": 50}), encoding="utf-8")
    budget.registrar(root / "edit-raw", "fal_kling", 1, usd=0.9)
    d = budget.autorizar(root, _proj(root), "fal_kling", 1)
    assert d["status"] == "bloqueado" and "mensal" in d["motivo"]


def test_autorizar_aprovacao_libera(root):
    budget.registrar(_proj(root), "fal_kling", 1, usd=4.9)
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_budget.py -v -k "autorizar or saldo"`
Expected: FAIL com `AttributeError: module 'budget' has no attribute 'autorizar'`

- [ ] **Step 3: Implementar**

```python
# acrescentar em ui/budget.py (após gasto_mes)
import os
import time
import urllib.request

ELEVEN_SUB_URL = "https://api.elevenlabs.io/v1/user/subscription"


def _chave_elevenlabs() -> str:
    v = os.environ.get("ELEVENLABS_API_KEY", "")
    if v:
        return v
    env = pipeline.ROOT / "video-use" / ".env"
    try:
        for ln in env.read_text(encoding="utf-8").splitlines():
            k, _, val = ln.partition("=")
            if k.strip() == "ELEVENLABS_API_KEY":
                return val.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _fetch_elevenlabs(key: str) -> dict:
    req = urllib.request.Request(ELEVEN_SUB_URL, headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def saldo_elevenlabs(root: Path, max_idade_s: int = 300, _fetch=None):
    qpath = root / ".ui-runtime" / "quota.json"
    cache = pipeline.read_json(qpath, {}).get("elevenlabs")
    if cache and time.time() - cache.get("lido_em", 0) < max_idade_s:
        return {k: cache[k] for k in ("usados", "limite", "restante", "reset_ts")}
    key = _chave_elevenlabs()
    if not key:
        return None
    try:
        d = (_fetch or _fetch_elevenlabs)(key)
        usados = int(d["character_count"])
        limite = int(d["character_limit"])
    except Exception:
        return None
    saldo = {"usados": usados, "limite": limite, "restante": limite - usados,
             "reset_ts": d.get("next_character_count_reset_unix", 0)}
    q = pipeline.read_json(qpath, {})          # reler antes de gravar
    q["elevenlabs"] = {**saldo, "lido_em": time.time()}
    pipeline.atomic_write_json(qpath, q)
    return saldo


def _decisao(status, motivo, est):
    return {"status": status, "motivo": motivo, "estimativa": est}


def autorizar(root: Path, proj: Path, provedor: str, unidades: float,
              aprovacao=None, saldo="auto") -> dict:
    est = estimar(root, provedor, unidades)
    if est is None:
        return _decisao("bloqueado", f"preço desconhecido para {provedor}", None)
    if aprovacao is not None:
        return _decisao("ok", f"aprovado pelo pedido {aprovacao}", est)
    b = ler_budget(root)
    pid = proj.name
    teto_proj = float(b["tetos_projeto"].get(pid, b["teto_projeto_usd"]))
    mes = gasto_mes(root)["usd"]
    if mes + est["usd"] > float(b["teto_mensal_usd"]):
        return _decisao("bloqueado",
                        f"teto mensal: {mes:.2f} + {est['usd']:.2f} > {b['teto_mensal_usd']}", est)
    gp = gasto_projeto(proj)["usd"]
    if gp + est["usd"] > teto_proj:
        return _decisao("bloqueado",
                        f"teto do projeto: {gp:.2f} + {est['usd']:.2f} > {teto_proj}", est)
    if est["creditos"] > 0:
        if saldo == "auto":
            saldo = saldo_elevenlabs(root)
        if saldo is None:
            return _decisao("precisa_aprovacao", "saldo ElevenLabs desconhecido", est)
        if est["creditos"] > saldo["restante"]:
            return _decisao("precisa_aprovacao",
                            f"cota ElevenLabs acaba: restam {saldo['restante']} créditos, "
                            f"ação usa {est['creditos']}", est)
    if est["usd"] > float(b["aprovar_acima_usd"]):
        return _decisao("precisa_aprovacao",
                        f"acima de {b['aprovar_acima_usd']} US$: estimativa {est['usd']:.2f}", est)
    return _decisao("ok", "dentro dos limites", est)
```

Ajuste: o teste `test_autorizar_cota_desconhecida` passa `saldo=None`
explicitamente; a sentinela `"auto"` distingue "não informado" de "sem saldo".

- [ ] **Step 4: Rodar e ver passar**

Run: `cd ui && python -m pytest test_budget.py -v`
Expected: 16 PASS

- [ ] **Step 5: Commit**

```bash
git add ui/budget.py ui/test_budget.py
git commit -m "feat(budget): autorizar com tetos, aprovação por ação e cota ElevenLabs"
```

---

### Task 3: Servidor — `/api/budget` e custos no projeto

**Files:**
- Modify: `ui/server.py` (após `activity`, ~linha 185; `WATCH`/`_snapshot` ~linha 195)
- Modify: `ui/pipeline.py:123-147` (`load_project`)
- Test: `ui/test_server.py`

**Interfaces:**
- Consumes: Task 1/2 (`ler_budget`, `gasto_mes`, `gasto_projeto`, `saldo_elevenlabs`).
- Produces:
  - `GET /api/budget` → `{"budget": {...}, "mes": "YYYY-MM", "gasto_mes": {"usd","creditos"}, "elevenlabs": {...}|null}`
  - `PUT /api/budget` body com qualquer subconjunto de `teto_mensal_usd`, `teto_projeto_usd`, `aprovar_acima_usd`, `tetos_projeto` → budget mesclado.
  - `load_project` passa a ter `"custos": {"usd","creditos"}` e `"teto_projeto": float`.
  - Snapshot SSE ganha `mtimes.costs` e `mtimes.budget`.

- [ ] **Step 1: Testes que falham**

```python
# acrescentar em ui/test_server.py
import json


def test_budget_get(client, fake_root):
    r = client.get("/api/budget")
    assert r.status_code == 200
    j = r.json()
    assert j["budget"]["teto_mensal_usd"] == 30.0
    assert j["gasto_mes"] == {"usd": 0.0, "creditos": 0}
    assert "elevenlabs" in j


def test_budget_put_merge(client, fake_root):
    (fake_root / ".ui-runtime").mkdir()
    (fake_root / ".ui-runtime" / "budget.json").write_text(
        json.dumps({"tetos_projeto": {"edit-fake": 12}}), encoding="utf-8")
    r = client.put("/api/budget", json={"teto_mensal_usd": 40})
    assert r.status_code == 200
    saved = json.loads((fake_root / ".ui-runtime" / "budget.json").read_text(encoding="utf-8"))
    assert saved["teto_mensal_usd"] == 40 and saved["tetos_projeto"] == {"edit-fake": 12}


def test_budget_put_rejeita_invalido(client, fake_root):
    assert client.put("/api/budget", json={"teto_mensal_usd": "abc"}).status_code == 400
    assert client.put("/api/budget", json={"teto_projeto_usd": -1}).status_code == 400
    assert client.put("/api/budget", json={"tetos_projeto": {"x": "y"}}).status_code == 400
    assert not (fake_root / ".ui-runtime" / "budget.json").exists()


def test_project_tem_custos(client, fake_root):
    (fake_root / "edit-fake" / "ui").mkdir(exist_ok=True)
    (fake_root / "edit-fake" / "ui" / "costs.jsonl").write_text(
        '{"ts":"2099-01-01T00:00:00+00:00","usd":2.5,"creditos":3}\n', encoding="utf-8")
    j = client.get("/api/project", params={"id": "edit-fake"}).json()
    assert j["custos"] == {"usd": 2.5, "creditos": 3}
    assert j["teto_projeto"] == 5.0


def test_events_inclui_costs_e_budget(client):
    r = client.get("/api/events", params={"id": "edit-fake", "max_events": 1})
    snap = json.loads(r.text.split("data: ", 1)[1].strip())
    assert "costs" in snap["mtimes"] and "budget" in snap["mtimes"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_server.py -v -k "budget or custos or events_inclui"`
Expected: FAIL (404 em `/api/budget`, `KeyError: 'custos'`, `KeyError: 'costs'`)

- [ ] **Step 3: Implementar em `pipeline.py`**

```python
# topo de ui/pipeline.py, após os imports: NADA (budget importa pipeline; evitar ciclo)
# em load_project, antes do return:
    import budget   # import local: budget.py importa pipeline
    b = budget.ler_budget(root)
    ...
    return {
        ... (chaves existentes) ...,
        "custos": budget.gasto_projeto(proj),
        "teto_projeto": float(b["tetos_projeto"].get(pid, b["teto_projeto_usd"])),
    }
```

- [ ] **Step 4: Implementar em `server.py`**

```python
# import no topo
import budget

# após a rota activity
BUDGET_NUM = ("teto_mensal_usd", "teto_projeto_usd", "aprovar_acima_usd")


def _num_ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


@app.get("/api/budget")
def budget_get(request: Request):
    root = _root(request)
    return {"budget": budget.ler_budget(root), "mes": budget._ano_mes_atual(),
            "gasto_mes": budget.gasto_mes(root),
            "elevenlabs": budget.saldo_elevenlabs(root)}


@app.put("/api/budget")
def budget_put(request: Request, body: dict):
    for k in BUDGET_NUM:
        if k in body and not _num_ok(body[k]):
            raise HTTPException(400, f"{k} inválido")
    tp = body.get("tetos_projeto")
    if tp is not None and (not isinstance(tp, dict)
                           or not all(_num_ok(v) for v in tp.values())):
        raise HTTPException(400, "tetos_projeto inválido")
    path = _root(request) / ".ui-runtime" / "budget.json"
    cur = pipeline.read_json(path, {})      # reler antes de gravar
    for k in BUDGET_NUM:
        if k in body:
            cur[k] = body[k]
    if tp is not None:
        cur.setdefault("tetos_projeto", {}).update(tp)
    pipeline.atomic_write_json(path, cur)
    return budget.ler_budget(_root(request))
```

Em `WATCH` acrescentar `"costs": "ui/costs.jsonl"`. Em `_snapshot`, na tupla
de arquivos do `.ui-runtime`, acrescentar `("budget", "budget.json")`.

- [ ] **Step 5: Rodar tudo**

Run: `cd ui && python -m pytest -v`
Expected: todos PASS (os existentes + 5 novos)

- [ ] **Step 6: Commit**

```bash
git add ui/server.py ui/pipeline.py ui/test_server.py
git commit -m "feat(ui): GET/PUT /api/budget, custos no payload do projeto, SSE observa costs/budget"
```

---

### Task 4: UI — selo de custo no header e resumo do mês

**Files:**
- Modify: `ui/static/index.html:9-12` (header)
- Modify: `ui/static/app.js` (`loadProjectInner` ~74, `renderAll` ~588, seção após `renderProgress` ~690)
- Modify: `ui/static/style.css` (após `#render-label`)

**Interfaces:**
- Consumes: `/api/budget`, `S.proj.custos`, `S.proj.teto_projeto`.
- Produces: `S.budget`, `renderBudget()`, `openBudgetModal()`.

- [ ] **Step 1: HTML** — inserir antes de `#claude-status`:

```html
  <button id="budget-badge" class="budget" title="Gasto do projeto / teto. Clique pra ver o mês e editar tetos"><span id="budget-bar"></span><span id="budget-label">US$ —</span></button>
```

- [ ] **Step 2: CSS** — após `#render-label { ... }`:

```css
#budget-badge {
  position: relative;
  width: 150px;
  height: 18px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0;
  cursor: pointer;
  font-size: 11px;
  color: var(--fg);
  overflow: hidden;
}
#budget-bar {
  position: absolute; inset: 0; width: 0%;
  background: rgba(76, 175, 80, 0.35);
}
#budget-badge.warn #budget-bar { background: rgba(224, 82, 82, 0.45); }
#budget-label { position: relative; line-height: 18px; }
.budget-modal label { display: block; margin: 6px 0; }
.budget-modal input { width: 80px; }
```

- [ ] **Step 3: JS** — em `loadProjectInner`, após `S.activity = ...`:

```js
  S.budget = await getJSON('/api/budget');
```

Em `renderAll`, após `renderProgress();`: `renderBudget();`

Após `renderProgress` (antes de `requestRender`):

```js
const fmtUSD = v => `US$ ${(v || 0).toFixed(2)}`;

function renderBudget() {
  const c = S.proj.custos || { usd: 0, creditos: 0 };
  const teto = S.proj.teto_projeto || 0;
  const pct = teto ? Math.min(100, c.usd / teto * 100) : 0;
  const badge = el('budget-badge');
  badge.className = 'budget' + (pct >= 80 ? ' warn' : '');
  el('budget-bar').style.width = `${pct}%`;
  el('budget-label').textContent = `${fmtUSD(c.usd)} / ${fmtUSD(teto)}`;
}

function openBudgetModal() {
  const b = S.budget || {}; const bb = b.budget || {}; const m = b.gasto_mes || {};
  const ev = b.elevenlabs;
  const cota = ev ? `${ev.usados.toLocaleString('pt-BR')} / ${ev.limite.toLocaleString('pt-BR')} créditos` : 'saldo indisponível';
  el('modal').innerHTML = `
    <div class="modal-box budget-modal">
      <h3>Orçamento</h3>
      <div>Mês ${escapeHtml(b.mes || '')}: <b>${fmtUSD(m.usd)}</b> / ${fmtUSD(bb.teto_mensal_usd)} · ElevenLabs ${cota}</div>
      <div>Projeto atual: <b>${fmtUSD((S.proj.custos || {}).usd)}</b> / ${fmtUSD(S.proj.teto_projeto)}</div>
      <label>Teto mensal (US$) <input type="number" min="0" step="0.5" id="b-mensal" value="${bb.teto_mensal_usd}"></label>
      <label>Teto padrão por projeto (US$) <input type="number" min="0" step="0.5" id="b-proj" value="${bb.teto_projeto_usd}"></label>
      <label>Teto deste projeto (US$) <input type="number" min="0" step="0.5" id="b-este" value="${S.proj.teto_projeto}"></label>
      <label>Pedir aprovação acima de (US$) <input type="number" min="0" step="0.1" id="b-acima" value="${bb.aprovar_acima_usd}"></label>
      <button id="b-save">Salvar</button> <button id="modal-close">Fechar</button>
    </div>`;
  el('modal').hidden = false;
  el('modal-close').onclick = () => { el('modal').hidden = true; };
  el('b-save').onclick = () => {
    const body = {
      teto_mensal_usd: +el('b-mensal').value,
      teto_projeto_usd: +el('b-proj').value,
      aprovar_acima_usd: +el('b-acima').value,
      tetos_projeto: { [S.pid.split('/').pop()]: +el('b-este').value },
    };
    putJSON('/api/budget', {}, body).then(() => { el('modal').hidden = true; loadProject(S.pid); });
  };
}

el('budget-badge').addEventListener('click', openBudgetModal);
```

Verifique como o modal existente fecha (procure `modal-close` ou `el('modal').hidden = true` perto da linha 709) e reutilize a mesma classe/caixa (`modal-box` ou a que estiver em uso) em vez de inventar outra.

Nota: `tetos_projeto` é chaveado por `proj.name` (último segmento do id) para
bater com `autorizar`, que usa `proj.name`.

- [ ] **Step 4: Verificar no navegador**

Run: `python ui/server.py` e abrir http://127.0.0.1:8765. Checar: selo
mostra `US$ 0.00 / 5.00`; clique abre modal; salvar teto deste projeto = 12
→ selo vira `/ 12.00`; `.ui-runtime/budget.json` tem `tetos_projeto`. Criar
`edit/<proj>/ui/costs.jsonl` à mão com uma linha `{"ts":"<agora ISO>","usd":4.5,"creditos":0}` → selo fica vermelho sem F5 (SSE).

- [ ] **Step 5: Commit**

```bash
git add ui/static/index.html ui/static/app.js ui/static/style.css
git commit -m "feat(ui): selo de gasto/teto no header e modal de orçamento do mês"
```

---

### Task 5: CLI para a sessão + protocolo no CLAUDE.md e receitas

**Files:**
- Modify: `ui/budget.py` (bloco `__main__`)
- Modify: `CLAUDE.md`
- Modify: `Formatos/padrao-youtube-longo.md` (seção "1. Pipeline"), `Formatos/padrao-youtube-shorts.md` (seção "Método"), `Formatos/padrao-ads.md` (seção "Técnica de produção")
- Test: `ui/test_budget.py`

**Interfaces:**
- Produces CLI:
  - `python ui/budget.py autorizar <proj_dir> <provedor> <unidades> [--aprovacao QID]` → imprime JSON da decisão; exit 0 se `ok`, 2 se `precisa_aprovacao`, 3 se `bloqueado`.
  - `python ui/budget.py registrar <proj_dir> <provedor> <unidades> [--usd X] [--creditos N] [--aprovacao QID] [--nota "..."]` → imprime a linha gravada.
  - `python ui/budget.py saldo` → JSON do saldo ElevenLabs ou `null`.

- [ ] **Step 1: Teste que falha**

```python
# acrescentar em ui/test_budget.py
import subprocess, sys


def test_cli_autorizar_e_registrar(root):
    proj = _proj(root)
    r = subprocess.run([sys.executable, str(Path(budget.__file__)), "autorizar",
                        str(proj), "fal_kling", "1", "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["status"] == "ok"
    r = subprocess.run([sys.executable, str(Path(budget.__file__)), "autorizar",
                        str(proj), "fal_kling", "3", "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(Path(budget.__file__)), "registrar",
                        str(proj), "fal_kling", "1", "--usd", "0.3", "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["usd"] == 0.3
    assert budget.gasto_projeto(proj)["usd"] == 0.3
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ui && python -m pytest test_budget.py -v -k cli`
Expected: FAIL (returncode ≠ 0, stdout vazio)

- [ ] **Step 3: Implementar o CLI** (final de `ui/budget.py`)

```python
if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="orçamento do video_editor")
    ap.add_argument("--root", default=str(pipeline.ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("autorizar")
    a.add_argument("proj"); a.add_argument("provedor"); a.add_argument("unidades", type=float)
    a.add_argument("--aprovacao", type=int)
    r = sub.add_parser("registrar")
    r.add_argument("proj"); r.add_argument("provedor"); r.add_argument("unidades", type=float)
    r.add_argument("--usd", type=float); r.add_argument("--creditos", type=int)
    r.add_argument("--aprovacao", type=int); r.add_argument("--nota", default="")
    sub.add_parser("saldo")
    ns = ap.parse_args()
    root = Path(ns.root)
    if ns.cmd == "autorizar":
        d = autorizar(root, Path(ns.proj), ns.provedor, ns.unidades, aprovacao=ns.aprovacao)
        print(json.dumps(d, ensure_ascii=False))
        sys.exit({"ok": 0, "precisa_aprovacao": 2, "bloqueado": 3}[d["status"]])
    if ns.cmd == "registrar":
        print(json.dumps(registrar(Path(ns.proj), ns.provedor, ns.unidades, usd=ns.usd,
                                   creditos=ns.creditos, aprovacao=ns.aprovacao,
                                   nota=ns.nota), ensure_ascii=False))
    if ns.cmd == "saldo":
        print(json.dumps(saldo_elevenlabs(root)))
```

`registrar` precisa aceitar `root` para o CLI com `--root`: trocar a
heurística de `registrar` da Task 1 por parâmetro `root: Path | None = None`
(default `pipeline.ROOT`); no CLI passar `root=root`; nos testes da Task 1
passar `root=root` também (atualizar as chamadas `budget.registrar(...)` dos
testes com `root=root` — a fixture se chama `root`). Remover a linha
`root = proj.parent if ...` da Task 1.

- [ ] **Step 4: Rodar tudo**

Run: `cd ui && python -m pytest -v`
Expected: todos PASS

- [ ] **Step 5: CLAUDE.md** — acrescentar seção antes de "## Regras":

```markdown
## Orçamento (ações pagas)

Antes de QUALQUER ação que gaste dinheiro ou cota (ElevenLabs, stock pago,
vídeo por IA...):

1. `python ui/budget.py autorizar <proj> <provedor> <unidades>`.
2. exit 2 (`precisa_aprovacao`) ou 3 (`bloqueado`) → pedido `waiting_reply`
   na fila com `resultado` = motivo + estimativa ("gerar 5 clipes Kling ≈
   US$1,40 — aprova?"). Esperar `reply` afirmativo; repetir o passo 1 com
   `--aprovacao <id do pedido>`.
3. Executar.
4. `python ui/budget.py registrar <proj> <provedor> <unidades> [--usd real]
   [--aprovacao <id>]`.

Provedores e preços: `ui/precos.json` (provedor novo = entrada nova antes de
usar). Transcrição Scribe: registrar `elevenlabs_scribe` com minutos do áudio
após `transcribe.py`; na primeira rodada, medir `python ui/budget.py saldo`
antes/depois e anotar `creditos` por minuto em `precos.json`.
```

- [ ] **Step 6: Receitas** — em cada um dos três `Formatos/*.md`, na etapa
de transcrição (longo e shorts) ou na primeira etapa paga (ads: SFX/trilha
quando existirem), uma linha:

```markdown
> Ação paga: seguir "Orçamento" do CLAUDE.md (`budget.py autorizar` antes, `registrar` depois).
```

- [ ] **Step 7: Commit**

```bash
git add ui/budget.py ui/test_budget.py CLAUDE.md Formatos/padrao-youtube-longo.md Formatos/padrao-youtube-shorts.md Formatos/padrao-ads.md
git commit -m "feat(budget): CLI autorizar/registrar/saldo e protocolo de orçamento no CLAUDE.md"
```

---

## Self-review

- **Cobertura do spec:** arquivos (T1/T2), módulo e regras de `autorizar` (T2), servidor e SSE (T3), UI (T4), Scribe por fora + CLAUDE.md + receitas (T5), testes listados no spec (T1–T3; `PUT` merge em T3). Fora de escopo mantido.
- **Placeholders:** nenhum.
- **Tipos:** `registrar(proj, provedor, unidades, usd, creditos, aprovacao, nota, root)` — assinatura final definida na T5 e usada nos testes da T1 (atualizar conforme nota). `autorizar(root, proj, provedor, unidades, aprovacao, saldo)` igual em T2/T5. `tetos_projeto` chaveado por `proj.name` em T2 e T4.
- **Review Focus:** 1 → `test_gasto_projeto_ignora_linha_corrompida` (T1); 2 → `test_autorizar_provedor_desconhecido` (T2); 3 → `test_autorizar_cota_desconhecida` + `test_saldo_elevenlabs_sem_chave` (T2); 4 → `test_budget_put_rejeita_invalido` (T3); 5 → `test_gasto_mes_soma_projetos_e_ignora_outros_meses` (T1).
