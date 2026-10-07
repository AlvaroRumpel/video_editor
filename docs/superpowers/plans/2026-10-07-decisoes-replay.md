# Decisões + linha do tempo/replay (6c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar decisões do Claude no `eventos.jsonl` e mostrá-las no Board, numa aba "Linha do tempo" com replay e numa página "Decisões" entre projetos.

**Architecture:** `ui/eventos.py` ganha o tipo `decisao` (CLI), o tipo `resposta` (gravado pelo servidor no `/api/reply`), leitura multi-tipo, `quadro(ate=)` com decisões por etapa, `linha()` (eventos + custos em ordem, com um quadro resumido por evento) e `decisoes()` (varre projetos). O servidor expõe `/api/linha` e `/api/decisoes`. O frontend ganha decisões nos cards do Board (`board.js`), `linha.js` (aba) e `decisoes.js` (rota `#/decisoes`).

**Tech Stack:** Python 3 stdlib, FastAPI, JS vanilla (scripts clássicos com globais), pytest, Python Playwright.

**Spec:** `docs/superpowers/specs/2026-10-07-decisoes-replay-design.md`

## Global Constraints

- Nada copiado do OpenMontage (AGPL).
- Módulos `ui/*.py`: stdlib; `sys.path.insert` antes de `import pipeline`; CLI JSON UTF-8, exit 0 / 1 (`ValueError`) / 2.
- `eventos.jsonl` é só acréscimo: um `write` de `json.dumps(..., ensure_ascii=False) + "\n"` em modo `"a"`; `ts` = `datetime.now(timezone.utc).isoformat()`; comparações sempre como `datetime` aware.
- `ASSUNTOS` = `provedor, trilha, sfx, broll, corte, grade, zoom, overlay, legenda, conceito, clipe, thumbnail, render, outro`. `CONFIANCAS` = `alta, media, baixa`.
- Decisão: `escolha` texto não vazio (strip); `alternativas` lista de textos (default `[]`); `motivo` texto (default `""`); `etapa` opcional validada contra a receita; `custo_usd` opcional finito ≥ 0 (bool rejeitado); `confianca` opcional. Campos opcionais omitidos não são gravados.
- Resposta: `{"ts","tipo":"resposta","qid","texto"}`, gravada só para projeto (nunca `_global`); falha ao gravar não falha o reply.
- A UI nunca escreve artefato do pipeline; o único escritor novo do log é o `/api/reply`.
- Todo texto vindo do log/artefato renderizado em HTML passa por `escapeHtml`.
- Testes: `cd ui && python -m pytest -q`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nunca matar processos que não sejam seus; nunca escrever em projetos reais sob `edit/`.

## Review Focus

1. Log com tipos misturados e linhas antigas/estranhas (assunto desconhecido, alternativas não-lista, custo negativo) → nada quebra; assunto vira `outro`, campos ruins somem. Teste em Task 1 (`test_ler_todos_os_tipos`).
2. Board redesenhado por SSE com uma decisão expandida → continua expandida. Teste em Task 4 (`test_board_decisao_expandida_sobrevive_reload`).
3. Filtro da linha do tempo que esconde tudo → scrubber desabilitado, sem erro de JS. Teste em Task 5 (`test_linha_filtro_vazio`).
4. Projeto sem nenhum evento → aba mostra "sem histórico"; página Decisões sem decisões mostra "nenhuma decisão registrada". Testes em Task 5 e Task 6.
5. Resposta enviada pela fila global (`_global`) → não grava em projeto nenhum. Teste em Task 3 (`test_reply_global_nao_grava_resposta`).

---

### Task 1: `eventos.py` — decisão, resposta, leitura multi-tipo, `quadro(ate=)` com decisões

**Files:**
- Modify: `ui/eventos.py`
- Test: `ui/test_eventos.py` (append; usa fixtures/helpers existentes `root`, `_proj`, `_ev`, `_custo`, `T`)

**Interfaces:**
- Consumes: `budget._linhas`, `budget._fin`, `pipeline.ROOT`; funções existentes `etapas_de`, `formato_de`, `_dt`, `_resumo`, `_custos`.
- Produces:
  - `ASSUNTOS: tuple`, `CONFIANCAS: tuple`
  - `registrar_decisao(proj, assunto, escolha, etapa=None, alternativas=(), motivo="", custo_usd=None, confianca=None, root=None) -> dict`
  - `registrar_resposta(proj, qid, texto) -> dict`
  - `ler(proj, tipo="etapa") -> list[dict]` (`tipo=None` = todos)
  - `quadro(proj, root=None, agora=None, ate=None) -> dict` — etapas e `fora_da_receita` ganham `"decisoes": [...]`; chave nova `"decisoes_soltas": [...]`; `sem_historico` = nenhum evento válido de qualquer tipo.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_eventos.py`)

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_eventos.py -q`
Expected: FAIL (`AttributeError: module 'eventos' has no attribute 'registrar_decisao'` etc.).

- [ ] **Step 3: Implement** (`ui/eventos.py`)

3a. Junto de `STATUS`, adicionar:

```python
TIPOS_EVENTO = ("etapa", "decisao", "resposta")
ASSUNTOS = ("provedor", "trilha", "sfx", "broll", "corte", "grade", "zoom", "overlay",
            "legenda", "conceito", "clipe", "thumbnail", "render", "outro")
CONFIANCAS = ("alta", "media", "baixa")
```

3b. Adicionar `_append` e fazer `registrar` usá-lo (troca as 4 linhas finais de escrita de `registrar` por `_append(proj, ev)`):

```python
def _append(proj: Path, ev: dict) -> dict:
    path = proj / "ui" / "eventos.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:   # append puro, uma escrita
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev
```

3c. Novas funções de escrita (após `registrar`):

```python
def registrar_decisao(proj: Path, assunto: str, escolha: str, etapa=None, alternativas=(),
                      motivo="", custo_usd=None, confianca=None, root=None) -> dict:
    root = root or pipeline.ROOT
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    if assunto not in ASSUNTOS:
        raise ValueError(f"assunto inválido: {assunto} (use {', '.join(ASSUNTOS)})")
    escolha = str(escolha or "").strip()
    if not escolha:
        raise ValueError("escolha vazia")
    if etapa:
        formato = formato_de(proj)
        ids = [e["id"] for e in etapas_de(formato, root)]
        if etapa not in ids:
            raise ValueError(f"etapa '{etapa}' não está na receita {formato}: {', '.join(ids) or 'sem etapas'}")
    if confianca is not None and confianca not in CONFIANCAS:
        raise ValueError(f"confiança inválida: {confianca} (use {', '.join(CONFIANCAS)})")
    custo = None
    if custo_usd is not None:
        custo = budget._fin(custo_usd)
        if custo is None or custo < 0:
            raise ValueError(f"custo inválido: {custo_usd!r}")
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "decisao", "assunto": assunto,
          "escolha": escolha, "alternativas": [str(a) for a in alternativas], "motivo": str(motivo or "")}
    if etapa:
        ev["etapa"] = etapa
    if custo is not None:
        ev["custo_usd"] = float(custo)
    if confianca:
        ev["confianca"] = confianca
    return _append(proj, ev)


def registrar_resposta(proj: Path, qid, texto) -> dict:
    if not proj.is_dir():
        raise ValueError(f"projeto não existe: {proj}")
    return _append(proj, {"ts": datetime.now(timezone.utc).isoformat(), "tipo": "resposta",
                          "qid": qid, "texto": str(texto or "")})
```

3d. Substituir `ler` por validação multi-tipo:

```python
def _valido(e):
    """Evento normalizado ou None. Tipo/linha desconhecidos são ignorados."""
    if not isinstance(e, dict) or _dt(e.get("ts")) is None:
        return None
    t = e.get("tipo")
    if t == "etapa":
        if not isinstance(e.get("etapa"), str) or not e["etapa"] or e.get("status") not in STATUS:
            return None
        if not isinstance(e.get("nota"), str):
            e.pop("nota", None)
        return e
    if t == "decisao":
        if not isinstance(e.get("assunto"), str) or not isinstance(e.get("escolha"), str) or not e["escolha"]:
            return None
        if e["assunto"] not in ASSUNTOS:
            e["assunto"] = "outro"
        alts = e.get("alternativas")
        e["alternativas"] = [str(a) for a in alts] if isinstance(alts, list) else []
        if not isinstance(e.get("motivo"), str):
            e["motivo"] = ""
        if not isinstance(e.get("etapa"), str) or not e.get("etapa"):
            e.pop("etapa", None)
        if "custo_usd" in e:
            c = budget._fin(e["custo_usd"])
            if c is None or c < 0:
                e.pop("custo_usd")
        if e.get("confianca") not in CONFIANCAS:
            e.pop("confianca", None)
        return e
    if t == "resposta":
        if "qid" not in e:
            return None
        if not isinstance(e.get("texto"), str):
            e["texto"] = ""
        return e
    return None


def ler(proj: Path, tipo="etapa") -> list[dict]:
    """Eventos válidos em ordem do arquivo; tipo=None = todos os tipos."""
    try:
        texto = (proj / "ui" / "eventos.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in texto.splitlines():
        try:
            e = _valido(json.loads(raw))
        except json.JSONDecodeError:
            continue   # linha corrompida não derruba o quadro
        if e is not None and (tipo is None or e["tipo"] == tipo):
            out.append(e)
    return out
```

3e. Substituir `quadro`:

```python
def quadro(proj: Path, root=None, agora=None, ate=None) -> dict:
    root = root or pipeline.ROOT
    agora = agora or ate or datetime.now(timezone.utc)
    formato = formato_de(proj)
    receita = etapas_de(formato, root)
    todos = ler(proj, None)
    custos = _custos(proj)
    if ate is not None:
        todos = [e for e in todos if _dt(e["ts"]) <= ate]
        custos = [(t, u) for t, u in custos if t <= ate]
    evs = [e for e in todos if e["tipo"] == "etapa"]
    por: dict[str, list] = {}
    for e in evs:
        por.setdefault(e["etapa"], []).append(e)
    etapas = [_resumo(i, por.get(i["id"], []), custos, agora) for i in receita]
    ids = {i["id"] for i in receita}
    fora = [_resumo({"id": k, "rotulo": k, "opcional": False}, v, custos, agora)
            for k, v in por.items() if k not in ids]
    todas = etapas + fora
    decs = [e for e in todos if e["tipo"] == "decisao"]
    com_card = {e["id"] for e in todas}
    for e in todas:
        e["decisoes"] = [d for d in decs if d.get("etapa") == e["id"]]
    soltas = [d for d in decs if d.get("etapa") not in com_card]
    andamento = [e for e in todas if e["status"] == "andamento"]
    espera = [e for e in todas if e["status"] == "espera"]
    if andamento:
        atual = max(andamento, key=lambda e: _dt(e["inicio"]))["id"]
    elif espera:
        atual = max(espera, key=lambda e: _dt(por[e["id"]][-1]["ts"]))["id"]
    else:
        atual = None
    return {"formato": formato, "sem_historico": not todos, "etapas": etapas,
            "fora_da_receita": fora, "atual": atual, "decisoes_soltas": soltas}
```

- [ ] **Step 4: Run tests**

Run: `cd ui && python -m pytest test_eventos.py test_server.py -q` → all PASS (os testes do 6a continuam passando: `ler(proj)` segue só com etapas). Depois `cd ui && python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add ui/eventos.py ui/test_eventos.py
git commit -m "feat(eventos): decisões, respostas, leitura multi-tipo e quadro(ate=) com decisões por etapa"
```

---

### Task 2: `eventos.py` — `linha()`, `decisoes()`, CLI e protocolo no CLAUDE.md

**Files:**
- Modify: `ui/eventos.py` (funções novas + CLI), `CLAUDE.md`
- Test: `ui/test_eventos.py` (append)

**Interfaces:**
- Consumes (Task 1): `ler(proj, tipo)`, `quadro(proj, root, ate=)`, `registrar_decisao`, `ASSUNTOS`, `CONFIANCAS`; `pipeline.find_projects(root)`, `pipeline.project_dir(root, pid)`.
- Produces:
  - `linha(proj, root=None) -> {"eventos": [...], "quadros": [...]}` — eventos = todos os do log + custos (`{"ts","tipo":"custo","provedor","usd","nota"}`), ordem por `ts` (estável: log antes de custos no empate), cada um com `custo_acum`; `quadros[i]` = `{"etapas": [{"id","rotulo","status"}], "atual"}` de `quadro(ate=ts_i)`.
  - `decisoes(root=None, assunto=None) -> {"decisoes": [...], "frequentes": [...]}` — itens `{"projeto","nome","ts","etapa","assunto","escolha","alternativas","motivo","custo_usd","confianca"}` por `ts` desc; `frequentes` = `[{"escolha","n"}]` (só com `assunto`; n desc, empate alfabético); assunto inválido → `ValueError`; projeto que falhar na leitura é pulado.
  - CLI: `decisao <proj> <assunto> <escolha> [--etapa] [--alt ...] [--motivo] [--custo] [--confianca]`, `linha <proj>`, `decisoes [--assunto]`.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_eventos.py`)

```python
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
```

(`_cli`, `pipeline` e `_ev`/`_custo`/`T` já existem em `ui/test_eventos.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_eventos.py -q -k "linha or decisoes or protocolo_decisoes or cli_decisao"` → FAIL.

- [ ] **Step 3: Implement** (`ui/eventos.py`, após `quadro`; `from collections import Counter` no topo)

```python
def linha(proj: Path, root=None) -> dict:
    """Tudo do projeto em ordem (log + custos), cada item com custo acumulado e
    o estado das etapas naquele instante (para o replay)."""
    root = root or pipeline.ROOT
    itens = [dict(e) for e in ler(proj, None)]
    for l in budget._linhas(proj / "ui" / "costs.jsonl"):
        t, u = _dt(l.get("ts")), budget._fin(l.get("usd", 0))
        if t is None or u is None:
            continue
        itens.append({"ts": l["ts"], "tipo": "custo", "provedor": str(l.get("provedor") or ""),
                      "usd": u, "nota": str(l.get("nota") or "")})
    itens.sort(key=lambda e: _dt(e["ts"]))   # estável: log (anexado antes) vem antes do custo no empate
    acum, quadros = 0.0, []
    for e in itens:
        if e["tipo"] == "custo":
            acum += e["usd"]
        e["custo_acum"] = round(acum, 4)
        # ponytail: um quadro por evento relê o log (O(n²)); trocar por varredura incremental se o log passar de milhares de linhas
        q = quadro(proj, root=root, ate=_dt(e["ts"]))
        quadros.append({"etapas": [{"id": x["id"], "rotulo": x["rotulo"], "status": x["status"]} for x in q["etapas"]],
                        "atual": q["atual"]})
    return {"eventos": itens, "quadros": quadros}


def decisoes(root=None, assunto=None) -> dict:
    root = root or pipeline.ROOT
    if assunto is not None and assunto not in ASSUNTOS:
        raise ValueError(f"assunto inválido: {assunto}")
    out = []
    for p in pipeline.find_projects(root):
        try:
            proj = pipeline.project_dir(root, p["id"])
            for d in ler(proj, "decisao"):
                if assunto and d["assunto"] != assunto:
                    continue
                out.append({"projeto": p["id"], "nome": p["name"], "ts": d["ts"], "etapa": d.get("etapa"),
                            "assunto": d["assunto"], "escolha": d["escolha"], "alternativas": d["alternativas"],
                            "motivo": d["motivo"], "custo_usd": d.get("custo_usd"), "confianca": d.get("confianca")})
        except Exception:  # noqa: BLE001 — projeto ilegível não derruba a página
            continue
    out.sort(key=lambda d: _dt(d["ts"]), reverse=True)
    freq = []
    if assunto:
        cont = Counter(d["escolha"] for d in out)
        freq = [{"escolha": k, "n": n} for k, n in sorted(cont.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"decisoes": out, "frequentes": freq}
```

CLI — no bloco `__main__`, adicionar os subparsers e os ramos:

```python
    p = sub.add_parser("decisao")
    p.add_argument("proj"); p.add_argument("assunto"); p.add_argument("escolha")
    p.add_argument("--etapa"); p.add_argument("--alt", action="append", default=[])
    p.add_argument("--motivo", default=""); p.add_argument("--custo", type=float)
    p.add_argument("--confianca")
    p = sub.add_parser("linha")
    p.add_argument("proj")
    p = sub.add_parser("decisoes")
    p.add_argument("--assunto")
```

e trocar o `if ns.cmd == "etapa": ... else: ...` por:

```python
        if ns.cmd == "etapa":
            out = registrar(Path(ns.proj), ns.etapa, ns.status, nota=ns.nota, root=root)
        elif ns.cmd == "decisao":
            out = registrar_decisao(Path(ns.proj), ns.assunto, ns.escolha, etapa=ns.etapa, alternativas=ns.alt,
                                    motivo=ns.motivo, custo_usd=ns.custo, confianca=ns.confianca, root=root)
        elif ns.cmd == "linha":
            out = linha(Path(ns.proj), root=root)
        elif ns.cmd == "decisoes":
            out = decisoes(root, assunto=ns.assunto)
        else:
            out = quadro(Path(ns.proj), root=root)
```

- [ ] **Step 4: CLAUDE.md**

4a. Na seção "Etapas (board da UI)", trocar a linha
`- Abriu \`waiting_reply\` dentro dela: \`... <id> espera\`.`
por
`- Abriu \`waiting_reply\` dentro dela: \`... <id> espera --nota "<pergunta curta>"\` (a nota é a pergunta na linha do tempo).`

4b. Inserir, logo antes de `## Orçamento (ações pagas)`:

```markdown
## Decisões (linha do tempo da UI)

Registrar só escolhas entre alternativas reais que mudam resultado ou custo
(provedor, trilha, candidato de b-roll, x do clipe, grade, conceito, corte
polêmico). Escolha óbvia sem alternativa não entra. Teto ~30 por projeto.

`python ui/eventos.py decisao <proj> <assunto> "<escolha>" --etapa <id> --alt "<alternativa>" ... --motivo "<por quê>" [--custo <usd estimado>] [--confianca alta|media|baixa]`

`assunto` ∈ provedor, trilha, sfx, broll, corte, grade, zoom, overlay,
legenda, conceito, clipe, thumbnail, render, outro (fora da lista → `outro`
e explicar no motivo). `--etapa` precisa estar na receita (ou omitir).
Respostas do usuário entram sozinhas no log (o servidor grava no `/api/reply`).
```

- [ ] **Step 5: Run tests**

Run: `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/eventos.py ui/test_eventos.py CLAUDE.md
git commit -m "feat(eventos): linha do tempo com quadros por evento, decisões entre projetos, CLI e protocolo"
```

---

### Task 3: Servidor — `/api/linha`, `/api/decisoes`, resposta no `/api/reply`

**Files:**
- Modify: `ui/server.py`
- Test: `ui/test_server.py` (append; imports no topo)

**Interfaces:**
- Consumes (Tasks 1–2): `eventos.linha(proj, root=)`, `eventos.decisoes(root, assunto=)`, `eventos.ASSUNTOS`, `eventos.registrar_resposta(proj, qid, texto)`; `/api/quadro` já devolve `eventos.quadro` (agora com `decisoes`/`decisoes_soltas`).
- Produces: `GET /api/linha?id=`, `GET /api/decisoes?assunto=` (vazio = todos; inválido → 400); `/api/reply` grava `resposta` no projeto.

- [ ] **Step 1: Write the failing tests** (append to `ui/test_server.py`)

```python
def _receita_teste(root):
    (root / "Formatos" / "teste.md").write_text("---\netapas: transcricao=transcrição, cortes\n---\n", encoding="utf-8")
    ui = root / "edit-fake" / "ui"
    ui.mkdir(parents=True, exist_ok=True)
    (ui / "state.json").write_text(json.dumps({"formato": "teste"}), encoding="utf-8")
    return root / "edit-fake"


def test_linha_route(client, fake_root):
    proj = _receita_teste(fake_root)
    eventos.registrar(proj, "cortes", "inicio", root=fake_root)
    eventos.registrar_decisao(proj, "corte", "c1", etapa="cortes", root=fake_root)
    d = client.get("/api/linha", params={"id": "edit-fake"}).json()
    assert [e["tipo"] for e in d["eventos"]] == ["etapa", "decisao"] and len(d["quadros"]) == 2
    assert client.get("/api/linha", params={"id": "../x"}).status_code == 400


def test_decisoes_route(client, fake_root):
    proj = _receita_teste(fake_root)
    eventos.registrar_decisao(proj, "trilha", "Phoenix2026", root=fake_root)
    r = client.get("/api/decisoes")
    assert r.status_code == 200 and r.json()["decisoes"][0]["escolha"] == "Phoenix2026"
    r = client.get("/api/decisoes", params={"assunto": "trilha"})
    assert r.json()["frequentes"] == [{"escolha": "Phoenix2026", "n": 1}]
    assert client.get("/api/decisoes", params={"assunto": ""}).status_code == 200
    assert client.get("/api/decisoes", params={"assunto": "nada"}).status_code == 400


def test_quadro_route_traz_decisoes(client, fake_root):
    proj = _receita_teste(fake_root)
    eventos.registrar_decisao(proj, "corte", "c1", etapa="cortes", root=fake_root)
    eventos.registrar_decisao(proj, "outro", "solta", root=fake_root)
    q = client.get("/api/quadro", params={"id": "edit-fake"}).json()
    assert [d["escolha"] for d in q["etapas"][1]["decisoes"]] == ["c1"]
    assert [d["escolha"] for d in q["decisoes_soltas"]] == ["solta"]


def _fila(path, qid=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": qid, "status": "waiting_reply", "text": "x"}]), encoding="utf-8")


def test_reply_grava_resposta(client, fake_root):
    _fila(fake_root / "edit-fake" / "ui" / "queue.json")
    r = client.post("/api/reply", params={"id": "edit-fake"}, json={"qid": 5, "text": "ok b01:2"})
    assert r.status_code == 200
    resp = eventos.ler(fake_root / "edit-fake", "resposta")
    assert [(e["qid"], e["texto"]) for e in resp] == [(5, "ok b01:2")]


def test_reply_global_nao_grava_resposta(client, fake_root):
    _fila(fake_root / ".ui-runtime" / "queue.json")
    assert client.post("/api/reply", params={"id": "_global"}, json={"qid": 5, "text": "ok"}).status_code == 200
    assert not (fake_root / ".ui-runtime" / "eventos.jsonl").exists()
    assert eventos.ler(fake_root / "edit-fake", "resposta") == []


def test_reply_log_falhando_nao_quebra(client, fake_root, monkeypatch):
    _fila(fake_root / "edit-fake" / "ui" / "queue.json")

    def quebra(*a, **k):
        raise OSError("disco cheio")

    monkeypatch.setattr(eventos, "registrar_resposta", quebra)
    r = client.post("/api/reply", params={"id": "edit-fake"}, json={"qid": 5, "text": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && python -m pytest test_server.py -q -k "linha_route or decisoes_route or traz_decisoes or resposta or log_falhando"` → FAIL.

- [ ] **Step 3: Implement** (`ui/server.py`)

Após `/api/quadro`:

```python
@app.get("/api/linha")
def linha_route(request: Request, id: str):
    return eventos.linha(_proj(request, id), root=_root(request))


@app.get("/api/decisoes")
def decisoes_route(request: Request, assunto: str | None = None):
    assunto = assunto or None
    if assunto is not None and assunto not in eventos.ASSUNTOS:
        raise HTTPException(400, "assunto inválido")
    return eventos.decisoes(_root(request), assunto=assunto)
```

Em `reply`, logo após `pipeline.atomic_write_json(qpath, queue)` e antes de `return e`:

```python
            if id != "_global":   # resposta entra na linha do tempo do projeto; log nunca derruba o reply
                try:
                    eventos.registrar_resposta(qpath.parent.parent, e["id"], e["reply"])
                except Exception:  # noqa: BLE001
                    pass
```

- [ ] **Step 4: Run tests** — `cd ui && python -m pytest -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/server.py ui/test_server.py
git commit -m "feat(ui): /api/linha, /api/decisoes e resposta do usuário na linha do tempo"
```

---

### Task 4: Decisões nos cards do Board

**Files:**
- Modify: `ui/static/board.js` (`boardCard`, `renderBoard`, função nova `decisaoHtml`), `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `S.quadro.etapas[].decisoes`, `S.quadro.fora_da_receita[].decisoes`, `S.quadro.decisoes_soltas` (Task 1 via `/api/quadro`); globais `escapeHtml`, `fmtUSD`.
- Produces: `decisaoHtml(d) -> string` (global; `<details class="dec" data-k="<ts>|<assunto>">`).

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def _decisao_raw(proj, ts, assunto, escolha, **kw):
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "tipo": "decisao", "assunto": assunto, "escolha": escolha, **kw},
                           ensure_ascii=False) + "\n")


def test_board_decisoes_no_card(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "tirar gaguejo", etapa="cortes",
                 alternativas=["manter"], motivo="ritmo", confianca="media", custo_usd=0.4)
    _decisao_raw(proj, "2026-10-07T10:07:00+00:00", "outro", "decisão solta")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes details.dec")
    dec = page.locator("#card-cortes details.dec")
    assert "tirar gaguejo" in dec.inner_text() and "manter" in dec.inner_text()
    assert not page.locator("#card-cortes .dec-mot").is_visible()
    dec.locator("summary").click()
    assert page.locator("#card-cortes .dec-mot").is_visible()
    assert "ritmo" in page.locator("#card-cortes .dec-mot").inner_text()
    assert "decisão solta" in page.locator("#card-outros").inner_text()


def test_board_decisao_expandida_sobrevive_reload(page, ui_url, fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "c1", etapa="cortes", motivo="m")
    page.goto(ui_url + "/#/p/edit-fake/board", wait_until="domcontentloaded")
    page.wait_for_selector("#card-cortes details.dec summary")
    page.click("#card-cortes details.dec summary")
    (proj / "ui" / "state.json").write_text(json.dumps({"formato": "teste", "x": 2}), encoding="utf-8")   # SSE
    page.wait_for_timeout(2000)
    assert page.locator("#card-cortes .dec-mot").is_visible()
```

- [ ] **Step 2: Run to verify they fail** — `cd ui && python -m pytest test_ui_smoke.py -q -k board_decis` → FAIL.

- [ ] **Step 3: board.js**

3a. Adicionar (antes de `boardCard`):

```js
// decisão do Claude: resumo na linha, motivo/custo ao expandir (<details> nativo)
function decisaoHtml(d) {
  const alt = d.alternativas && d.alternativas.length
    ? ` <span class="dim">(vs ${escapeHtml(d.alternativas.join(', '))})</span>` : '';
  const conf = d.confianca
    ? ` <span class="conf conf-${escapeHtml(d.confianca)}" title="confiança ${escapeHtml(d.confianca)}">●</span>` : '';
  const custo = d.custo_usd != null ? ` <span class="mono">${fmtUSD(d.custo_usd)}</span>` : '';
  return `<details class="dec" data-k="${escapeHtml(d.ts + '|' + d.assunto)}">
      <summary><span class="tag">${escapeHtml(d.assunto)}</span> ${escapeHtml(d.escolha)}${alt}${conf}</summary>
      <div class="dec-mot">${escapeHtml(d.motivo || 'sem motivo registrado')}${custo}</div>
    </details>`;
}
```

3b. Em `boardCard`, no template retornado, logo após `${linhas}` (antes de `${perg}`), inserir `${(e.decisoes || []).map(decisaoHtml).join('')}`.

3c. Em `renderBoard`:
- antes de montar `html` (logo após a linha que lê `foco`), guardar os abertos:
  ```js
  const abertos = new Set([...box.querySelectorAll('details.dec[open]')].map(d => d.dataset.k));
  ```
- trocar o bloco do card "outros":
  ```js
  const soltas = q.decisoes_soltas || [];
  if (outros.length || soltas.length) html += `<div class="board-card" id="card-outros"><div class="bc-head"><span class="bc-rot">outros</span></div>` +
    outros.map(t => `<div class="info-line">${escapeHtml(t)}</div>`).join('') + soltas.map(decisaoHtml).join('') + '</div>';
  ```
- logo após `box.innerHTML = ...`, restaurar:
  ```js
  box.querySelectorAll('details.dec').forEach(d => { if (abertos.has(d.dataset.k)) d.open = true; });
  ```

- [ ] **Step 4: CSS** (append to `ui/static/style.css`)

```css
/* ---- decisões ---- */
.dec { font-size: 12px; }
.dec summary { cursor: pointer; list-style: none; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.dec summary::-webkit-details-marker { display: none; }
.dec summary::before { content: '◆'; color: var(--accent); font-size: 9px; }
.dec-mot { padding: 4px 0 2px 15px; color: var(--text-dim); display: flex; gap: 8px; }
.conf { font-size: 10px; }
.conf-alta { color: var(--ok); }
.conf-media { color: var(--accent); }
.conf-baixa { color: var(--fail); }
```

- [ ] **Step 5: Run tests** — `cd ui && python -m pytest test_ui_smoke.py -q` → all PASS; full suite → PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/static/board.js ui/static/style.css ui/test_ui_smoke.py
git commit -m "feat(ui): decisões do Claude nos cards do Board"
```

---

### Task 5: Aba "Linha do tempo" com replay

**Files:**
- Create: `ui/static/linha.js`
- Modify: `ui/static/index.html` (aba, pane, script), `ui/static/app.js` (`TABS`, `renderAll`, `renderTab`), `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `GET /api/linha` (Task 3: `{eventos: [{ts, tipo, ..., custo_acum}], quadros: [{etapas: [{id, rotulo, status}], atual}]}`); globais `S`, `el`, `getJSON`, `escapeHtml`, `fmtUSD`, `fmtHora` (board.js).
- Produces: `renderLinha(forcar: bool)`, aba `linha` (`#tab-linha`), DOM `#linha-scrub`, `#linha-play`, `#linha-vel`, `#linha-mini .step`, `#linha-custo`, `.linha-item[data-k]`, chips `[data-tipo]` / `[data-assunto]`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def _linha_fixture(fake_root):
    proj = fake_root / "edit-fake"
    _decisao_raw(proj, "2026-10-07T10:06:00+00:00", "corte", "tirar gaguejo", etapa="cortes")
    (proj / "ui" / "costs.jsonl").write_text(json.dumps(
        {"ts": "2026-10-07T10:07:00+00:00", "provedor": "elevenlabs_scribe", "usd": 0.5, "creditos": 0}) + "\n",
        encoding="utf-8")
    with (proj / "ui" / "eventos.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-07T10:08:00+00:00", "tipo": "resposta", "qid": 1, "texto": "ok"}) + "\n")
    return proj


def _scrub(page, v):
    page.eval_on_selector("#linha-scrub",
                          f"el => {{ el.value = {v}; el.dispatchEvent(new Event('input', {{bubbles: true}})); }}")


def test_linha_replay(page, ui_url, fake_root):
    _linha_fixture(fake_root)     # eventos: transcricao fim 10:00, cortes inicio 10:05, decisão 10:06, custo 10:07, resposta 10:08
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    assert page.locator(".linha-item").count() == 5
    _scrub(page, 0)
    assert "st-pendente" in page.locator("#linha-mini .step").nth(1).get_attribute("class")
    assert page.locator("#linha-custo").inner_text() == "acumulado US$ 0.00"
    _scrub(page, 4)
    assert "st-andamento" in page.locator("#linha-mini .step").nth(1).get_attribute("class")
    assert page.locator("#linha-custo").inner_text() == "acumulado US$ 0.50"
    assert "cur" in page.locator(".linha-item[data-k='4']").get_attribute("class")
    page.click(".linha-item[data-k='2']")
    assert page.locator("#linha-scrub").input_value() == "2"
    _scrub(page, 0)
    page.click("#linha-play")
    page.wait_for_function("document.querySelector('#linha-scrub').value === '4'", timeout=6000)
    page.wait_for_function("document.querySelector('#linha-play').textContent === '▶'", timeout=3000)   # parou no fim


def test_linha_filtros(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    for t in ("etapa", "pergunta", "resposta", "custo"):
        page.click(f".linha-filtros [data-tipo={t}]")
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 1")
    assert "tirar gaguejo" in page.locator(".linha-item").inner_text()
    assert page.locator(".linha-filtros [data-assunto=corte]").is_visible()


def test_linha_filtro_vazio(page, ui_url, fake_root):
    _linha_fixture(fake_root)
    page.goto(ui_url + "/#/p/edit-fake/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-item")
    for t in ("etapa", "decisao", "pergunta", "resposta", "custo"):
        page.click(f".linha-filtros [data-tipo={t}]")
    page.wait_for_function("document.querySelectorAll('.linha-item').length === 0")
    assert page.locator("#linha-scrub").is_disabled()
    page.click("#linha-play")       # sem eventos visíveis: não quebra
    assert page.locator("#linha-play").inner_text() == "▶"


def test_linha_sem_historico(page, ui_url):
    page.goto(ui_url + "/#/p/edit-raw/linha", wait_until="domcontentloaded")
    page.wait_for_selector(".linha-vazio")
    assert "sem histórico" in page.locator("#tab-linha").inner_text()
```

- [ ] **Step 2: Run to verify they fail** — `cd ui && python -m pytest test_ui_smoke.py -q -k linha` → FAIL.

- [ ] **Step 3: index.html** — em `<nav id="tabs">`, após `<a data-tab="custos">Custos</a>`, inserir `<a data-tab="linha">Linha do tempo</a>`; após o pane `tab-aprovacao` (ou `tab-custos`), inserir `<div id="tab-linha" class="tab-pane"></div>`; após `<script src="folha.js"></script>`, inserir `<script src="linha.js"></script>`.

- [ ] **Step 4: app.js**
- `const TABS = [...]` ganha `'linha'` no fim.
- Em `renderAll`, junto das chamadas por aba: `if (tab === 'linha') renderLinha(true);`
- Em `renderTab`, novo ramo: `else if (tab === 'linha') renderLinha(true);`

- [ ] **Step 5: Create `ui/static/linha.js`**

```js
// Aba "Linha do tempo": eventos do projeto em ordem (etapas, decisões, perguntas, respostas, custos)
// com filtros e replay — o servidor manda um quadro resumido por evento, o cliente só indexa.
const LINHA_TIPOS = ['etapa', 'decisao', 'pergunta', 'resposta', 'custo'];
const LINHA_ROT = { etapa: 'etapas', decisao: 'decisões', pergunta: 'perguntas', resposta: 'respostas', custo: 'custos' };
const LINHA_ICO = { etapa: '▸', decisao: '◆', pergunta: '❓', resposta: '↩', custo: '$' };
const LINHA_STATUS = { inicio: 'início', fim: 'fim', espera: 'espera', pulada: 'pulada', falha: 'falha' };
let linhaDados = { pid: null, eventos: [], quadros: [] };
const linhaFiltro = { tipos: new Set(LINHA_TIPOS), assunto: null };
let linhaPos = 0, linhaTimer = null, linhaVel = 1;

const tipoLinha = e => (e.tipo === 'etapa' && e.status === 'espera' && e.nota ? 'pergunta' : e.tipo);

function textoLinha(e) {
  const t = tipoLinha(e);
  if (t === 'custo') return `${e.provedor} · ${fmtUSD(e.usd)}${e.nota ? ' · ' + e.nota : ''}`;
  if (t === 'resposta') return `você: ${e.texto}`;
  if (t === 'decisao') return `${e.assunto} · ${e.escolha}${e.alternativas.length ? ' (vs ' + e.alternativas.join(', ') + ')' : ''}${e.motivo ? ' — ' + e.motivo : ''}`;
  if (t === 'pergunta') return `${e.etapa} · ${e.nota}`;
  return `${e.etapa} · ${LINHA_STATUS[e.status] || e.status}${e.nota ? ' — ' + e.nota : ''}`;
}

function visiveis() {
  return linhaDados.eventos.map((_, i) => i).filter(i => {
    const e = linhaDados.eventos[i], t = tipoLinha(e);
    return linhaFiltro.tipos.has(t) && (t !== 'decisao' || !linhaFiltro.assunto || e.assunto === linhaFiltro.assunto);
  });
}

async function renderLinha(forcar) {
  const pid = S.pid;
  if (forcar || linhaDados.pid !== pid) {
    let d;
    try { d = await getJSON('/api/linha', { id: pid }); } catch (e) { console.warn('linha falhou', e); return; }
    if (S.pid !== pid) return;
    if (linhaDados.pid !== pid) { pausaLinha(); linhaPos = 0; }
    linhaDados = { pid, eventos: d.eventos || [], quadros: d.quadros || [] };
  }
  desenhaLinha();
}

function desenhaLinha() {
  const box = el('tab-linha');
  const evs = linhaDados.eventos;
  if (!evs.length) { box.innerHTML = '<div class="dim linha-vazio">sem histórico</div>'; return; }
  const vis = visiveis();
  linhaPos = Math.min(linhaPos, Math.max(vis.length - 1, 0));
  const assuntos = [...new Set(evs.filter(e => e.tipo === 'decisao').map(e => e.assunto))].sort();
  const chipsAssunto = linhaFiltro.tipos.has('decisao') && assuntos.length
    ? '<span class="dim">assunto:</span>' + ['', ...assuntos].map(a =>
      `<button class="lib-chip${(linhaFiltro.assunto || '') === a ? ' on' : ''}" data-assunto="${escapeHtml(a)}">${escapeHtml(a || 'todos')}</button>`).join('')
    : '';
  box.innerHTML = `<div class="linha-topo">
      <div class="linha-ctl">
        <button id="linha-play">${linhaTimer ? '⏸' : '▶'}</button>
        <button id="linha-vel" class="mono">${linhaVel}×</button>
        <input type="range" id="linha-scrub" min="0" max="${Math.max(vis.length - 1, 0)}" value="${linhaPos}"${vis.length ? '' : ' disabled'}>
        <span class="mono" id="linha-custo"></span>
      </div>
      <div id="linha-mini" class="linha-mini"></div>
      <div class="linha-filtros">${LINHA_TIPOS.map(t =>
        `<button class="lib-chip${linhaFiltro.tipos.has(t) ? ' on' : ''}" data-tipo="${t}">${LINHA_ICO[t]} ${LINHA_ROT[t]}</button>`).join('')}${chipsAssunto}</div>
    </div>
    <ol class="linha-lista">${vis.map((i, k) => {
      const e = evs[i], t = tipoLinha(e);
      return `<li class="linha-item lt-${t}" data-k="${k}">
          <span class="mono dim" title="${escapeHtml(new Date(e.ts).toLocaleString('pt-BR'))}">${fmtHora(e.ts)}</span>
          <span class="linha-ico">${LINHA_ICO[t]}</span><span>${escapeHtml(textoLinha(e))}</span></li>`;
    }).join('')}</ol>`;
  marcaLinha();
}

function marcaLinha() {
  const vis = visiveis();
  const box = el('tab-linha');
  if (!el('linha-scrub')) return;
  if (!vis.length) { el('linha-custo').textContent = ''; el('linha-mini').innerHTML = ''; return; }
  const i = vis[linhaPos];
  const q = linhaDados.quadros[i] || { etapas: [], atual: null };
  el('linha-scrub').value = linhaPos;
  el('linha-custo').textContent = 'acumulado ' + fmtUSD(linhaDados.eventos[i].custo_acum);
  el('linha-mini').innerHTML = q.etapas.map(e =>
    `<span class="step st-${e.status}${e.id === q.atual ? ' atual' : ''}">${escapeHtml(e.rotulo)}</span>`).join('');
  box.querySelectorAll('.linha-item').forEach(li => li.classList.toggle('cur', +li.dataset.k === linhaPos));
  const cur = box.querySelector('.linha-item.cur');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function tocaLinha() {
  if (!visiveis().length) return;
  if (linhaPos >= visiveis().length - 1) linhaPos = 0;
  linhaTimer = setInterval(() => {
    if (linhaPos >= visiveis().length - 1 || document.body.dataset.tab !== 'linha') { pausaLinha(); return; }
    linhaPos += 1;
    marcaLinha();
  }, 600 / linhaVel);
  if (el('linha-play')) el('linha-play').textContent = '⏸';
  marcaLinha();
}

function pausaLinha() {
  clearInterval(linhaTimer);
  linhaTimer = null;
  if (el('linha-play')) el('linha-play').textContent = '▶';
}

el('tab-linha').addEventListener('click', e => {
  const t = e.target;
  if (t.id === 'linha-play') { if (linhaTimer) pausaLinha(); else tocaLinha(); return; }
  if (t.id === 'linha-vel') {
    linhaVel = linhaVel === 1 ? 2 : 1;
    t.textContent = linhaVel + '×';
    if (linhaTimer) { pausaLinha(); tocaLinha(); }
    return;
  }
  const chip = t.closest('[data-tipo],[data-assunto]');
  if (chip) {
    if (chip.dataset.tipo) {
      const s = linhaFiltro.tipos, k = chip.dataset.tipo;
      if (s.has(k)) s.delete(k); else s.add(k);
    } else {
      linhaFiltro.assunto = chip.dataset.assunto || null;
    }
    linhaPos = 0;
    desenhaLinha();
    return;
  }
  const li = t.closest('.linha-item');
  if (li) { linhaPos = +li.dataset.k; marcaLinha(); }
});

el('tab-linha').addEventListener('input', e => {
  if (e.target.id === 'linha-scrub') { linhaPos = +e.target.value; marcaLinha(); }
});
```

- [ ] **Step 6: CSS** (append to `ui/static/style.css`)

```css
/* ---- linha do tempo ---- */
body[data-tab="linha"] #tab-linha { display: flex; flex-direction: column; }
#tab-linha { padding: 0; }
.linha-topo { padding: 10px 14px; border-bottom: 1px solid var(--border); display: grid; gap: 8px; flex-shrink: 0; }
.linha-ctl { display: flex; gap: 8px; align-items: center; }
#linha-scrub { flex: 1; accent-color: var(--accent); }
#linha-custo { color: var(--accent); min-width: 150px; text-align: right; }
.linha-mini { display: flex; gap: 3px; }
.linha-mini .step.atual { outline: 1px solid var(--accent); }
.linha-filtros { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.linha-lista { list-style: none; margin: 0; padding: 6px 14px 20px; overflow: auto; flex: 1 1 0; min-height: 0; }
.linha-item { display: grid; grid-template-columns: 52px 18px 1fr; gap: 6px; padding: 4px 6px; border-radius: 5px; cursor: pointer; }
.linha-item:hover { background: var(--panel); }
.linha-item.cur { background: rgba(240, 178, 74, .12); outline: 1px solid rgba(240, 178, 74, .4); }
.linha-ico { text-align: center; color: var(--text-dim); }
.lt-decisao .linha-ico { color: var(--accent); }
.lt-pergunta .linha-ico, .lt-resposta .linha-ico { color: var(--ok); }
.linha-vazio { padding: 30px 14px; }
```

- [ ] **Step 7: Run tests** — `cd ui && python -m pytest test_ui_smoke.py -q` → all PASS; full suite → PASS. Screenshot da aba no fixture ao lado do report.

- [ ] **Step 8: Commit**

```bash
git add ui/static ui/test_ui_smoke.py
git commit -m "feat(ui): aba Linha do tempo com filtros e replay (scrubber, play, estado das etapas, custo acumulado)"
```

---

### Task 6: Página "Decisões" entre projetos

**Files:**
- Create: `ui/static/decisoes.js`
- Modify: `ui/static/index.html` (botão, cabeçalho, seção, script), `ui/static/app.js` (`parseHash`, `route`, função `saiDoProjeto`), `ui/static/style.css` (append)
- Test: `ui/test_ui_smoke.py` (append)

**Interfaces:**
- Consumes: `GET /api/decisoes[?assunto=]` (Task 3); globais `S`, `el`, `getJSON`, `escapeHtml`, `fmtUSD`, `hashFor`, `stopLibrary`, `renderBudget`, `renderQueue`.
- Produces: rota `#/decisoes` (`body[data-route="decisoes"]`), `renderDecisoesPage()`, DOM `#btn-decisoes`, `#decisoes-view`, `#dec-chips [data-assunto]`, `#dec-busca`, `#dec-freq`, `#dec-tabela`.

- [ ] **Step 1: Write the failing smoke tests** (append to `ui/test_ui_smoke.py`)

```python
def test_pagina_decisoes(page, ui_url, fake_root):
    fake, raw = fake_root / "edit-fake", fake_root / "edit-raw"
    _decisao_raw(fake, "2026-10-07T10:01:00+00:00", "trilha", "Phoenix2026", motivo="calma", confianca="alta")
    _decisao_raw(fake, "2026-10-07T10:02:00+00:00", "corte", "tirar gaguejo")
    _decisao_raw(raw, "2026-10-07T10:03:00+00:00", "trilha", "Phoenix2026")
    _decisao_raw(raw, "2026-10-07T10:04:00+00:00", "trilha", "Incredulity", custo_usd=0.1)
    page.goto(ui_url + "/#/", wait_until="domcontentloaded")
    page.click("#btn-decisoes")
    page.wait_for_function("document.body.dataset.route === 'decisoes'")
    page.wait_for_selector(".dec-tab tbody tr")
    assert page.locator(".dec-tab tbody tr").count() == 4
    assert not page.locator("#library-view").is_visible()
    page.click("#dec-chips [data-assunto=trilha]")
    page.wait_for_function("document.querySelectorAll('.dec-tab tbody tr').length === 3")
    assert "Phoenix2026 ×2" in page.locator("#dec-freq").inner_text()
    page.fill("#dec-busca", "incred")
    page.wait_for_function("document.querySelectorAll('.dec-tab tbody tr').length === 1")
    page.click(".dec-tab tbody tr a")
    page.wait_for_function("location.hash === '#/p/edit-raw/linha'")
    page.wait_for_function("document.body.dataset.route === 'project'")


def test_pagina_decisoes_vazia(page, ui_url):
    page.goto(ui_url + "/#/decisoes", wait_until="domcontentloaded")
    page.wait_for_selector(".dec-vazio")
    assert "nenhuma decisão registrada" in page.locator("#decisoes-view").inner_text()
    page.click("#decisoes-voltar")
    page.wait_for_function("document.body.dataset.route === 'library'")
```

- [ ] **Step 2: Run to verify they fail** — `cd ui && python -m pytest test_ui_smoke.py -q -k pagina_decisoes` → FAIL.

- [ ] **Step 3: index.html**
- No `<header>`, após `<button class="only-library" id="btn-formats" ...>`, inserir:
  `<button class="only-library" id="btn-decisoes" title="Decisões do Claude em todos os projetos">Decisões</button>`
  `<a class="only-decisoes back" id="decisoes-voltar" href="#/" title="Voltar à biblioteca">←</a>`
  `<span class="only-decisoes proj-name">Decisões</span>`
- Em `<main>`, após a `<section id="library-view" ...>...</section>`, inserir:
  ```html
  <section id="decisoes-view" class="only-decisoes">
    <div id="dec-filtros"><div id="dec-chips"></div><input type="search" id="dec-busca" placeholder="buscar escolha, motivo, projeto..."></div>
    <div id="dec-freq"></div>
    <div id="dec-tabela"></div>
  </section>
  ```
- Após `<script src="linha.js"></script>`, inserir `<script src="decisoes.js"></script>`.

- [ ] **Step 4: app.js**

4a. Em `parseHash`, primeira linha: `if (location.hash === '#/decisoes') return { route: 'decisoes' };`

4b. Extrair o desmonte do projeto do ramo `library` de `route()` para uma função e usá-la nos dois ramos:

```js
function saiDoProjeto() {
  if (S.es) { S.es.close(); S.es = null; }
  S.pid = null; S.proj = null; S.quadro = null; S.selected = null;
  el('instr-context').textContent = 'instrução geral';
  const v = el('player');
  v.pause(); if (v.getAttribute('src')) v.removeAttribute('src');
  el('render-progress').hidden = true;   // progresso é por projeto
}
```

Em `route()`, o ramo `library` fica:

```js
  if (r.route === 'library') {
    body.dataset.route = 'library';
    saiDoProjeto();
    renderBudget();
    startLibrary();
    return;
  }
  if (r.route === 'decisoes') {
    body.dataset.route = 'decisoes';
    saiDoProjeto();
    stopLibrary();
    renderBudget();
    renderDecisoesPage();
    return;
  }
```

- [ ] **Step 5: Create `ui/static/decisoes.js`**

```js
// Página "Decisões" (#/decisoes): decisões do Claude em todos os projetos; filtro por assunto
// (o servidor devolve as escolhas mais frequentes) e busca no cliente.
const decEstado = { assunto: null, busca: '', assuntos: [], dados: { decisoes: [], frequentes: [] } };

async function renderDecisoesPage() {
  try {
    const todos = await getJSON('/api/decisoes');
    decEstado.assuntos = [...new Set(todos.decisoes.map(d => d.assunto))].sort();
    decEstado.dados = decEstado.assunto ? await getJSON('/api/decisoes', { assunto: decEstado.assunto }) : todos;
  } catch (e) {
    console.warn('decisões falhou', e);
    decEstado.assuntos = [];
    decEstado.dados = { decisoes: [], frequentes: [] };
  }
  if (document.body.dataset.route !== 'decisoes') return;
  desenhaDecisoes();
}

function desenhaDecisoes() {
  const { assunto, busca, dados } = decEstado;
  el('dec-chips').innerHTML = ['', ...decEstado.assuntos].map(a =>
    `<button class="lib-chip${(assunto || '') === a ? ' on' : ''}" data-assunto="${escapeHtml(a)}">${escapeHtml(a || 'todos')}</button>`).join('');
  el('dec-freq').innerHTML = assunto && dados.frequentes.length
    ? `<div class="dec-freq"><span class="dim">escolhas mais frequentes · ${escapeHtml(assunto)}:</span> ${
      dados.frequentes.map(f => `<span class="tag">${escapeHtml(f.escolha)} ×${f.n}</span>`).join(' ')}</div>`
    : '';
  const b = busca.toLowerCase();
  const linhas = dados.decisoes.filter(d =>
    !b || [d.escolha, d.motivo, d.nome, d.projeto].join(' ').toLowerCase().includes(b));
  el('dec-tabela').innerHTML = linhas.length
    ? `<table class="dec-tab"><thead><tr><th>projeto</th><th>data</th><th>etapa</th><th>assunto</th><th>escolha</th>
        <th>alternativas</th><th>motivo</th><th>conf.</th><th>US$</th></tr></thead><tbody>${linhas.map(d => `<tr>
        <td><a href="${hashFor(d.projeto, 'linha')}">${escapeHtml(d.nome)}</a></td>
        <td class="mono">${escapeHtml(new Date(d.ts).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }))}</td>
        <td>${escapeHtml(d.etapa || '')}</td><td>${escapeHtml(d.assunto)}</td><td><b>${escapeHtml(d.escolha)}</b></td>
        <td class="dim">${escapeHtml(d.alternativas.join(', '))}</td><td>${escapeHtml(d.motivo)}</td>
        <td>${d.confianca ? `<span class="conf conf-${escapeHtml(d.confianca)}">●</span> ${escapeHtml(d.confianca)}` : ''}</td>
        <td class="mono">${d.custo_usd != null ? fmtUSD(d.custo_usd) : ''}</td></tr>`).join('')}</tbody></table>`
    : '<div class="dim dec-vazio">nenhuma decisão registrada</div>';
}

el('dec-chips').addEventListener('click', e => {
  const b = e.target.closest('[data-assunto]');
  if (!b) return;
  decEstado.assunto = b.dataset.assunto || null;
  renderDecisoesPage();
});
el('dec-busca').addEventListener('input', e => {
  decEstado.busca = e.target.value.trim();
  desenhaDecisoes();
});
el('btn-decisoes').addEventListener('click', () => { location.hash = '#/decisoes'; });
```

- [ ] **Step 6: CSS** (append to `ui/static/style.css`)

```css
/* ---- página decisões ---- */
body[data-route="decisoes"] .only-project,
body[data-route="decisoes"] .only-library { display: none !important; }
body:not([data-route="decisoes"]) .only-decisoes { display: none !important; }
#decisoes-view { overflow: auto; display: flex; flex-direction: column; min-height: 0; padding: 0 16px 24px; }
#dec-filtros { display: flex; gap: 10px; align-items: center; padding: 12px 0 6px; flex-wrap: wrap; }
#dec-chips { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
#dec-busca { width: 260px; padding: 5px 10px; border-radius: 99px; }
.dec-freq { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding: 6px 0 10px; }
.dec-tab { border-collapse: collapse; width: 100%; font-size: 12px; }
.dec-tab th, .dec-tab td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
.dec-tab th { color: var(--text-dim); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.dec-tab a { color: var(--accent); text-decoration: none; }
.dec-vazio { padding: 30px 0; }
```

- [ ] **Step 7: Run tests** — `cd ui && python -m pytest test_ui_smoke.py -q` → all PASS; full suite → PASS.

- [ ] **Step 8: Commit**

```bash
git add ui/static ui/test_ui_smoke.py
git commit -m "feat(ui): página Decisões com filtro por assunto, escolhas frequentes e link para a linha do tempo"
```
