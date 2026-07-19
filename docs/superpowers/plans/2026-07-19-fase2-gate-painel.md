# Fase 2 — Portão 1-clique + Painel "Para publicar" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono aprova/rejeita itens da fila com 1 clique a partir do digest (rotas `/gate` na app web CheckAL, servida no Polaris) e vê/copia os posts pendentes num painel novo da Sala de Controlo.

**Architecture:** Parte A (repo `checkal-polaris`): módulo novo `app/web/gate.py` no padrão dos routers existentes (`/confirmar` do consentimento é o análogo direto), template `gate.html` a estender `base.html`, config `CHECKAL_GATE_BASE_URL` fail-closed, `maestro-gate-token` passa a devolver `url`, unit systemd `checkal-web.service` (uvicorn 127.0.0.1:8600). Parte B (projeto `Dashboard_Polaris`): função `fila_pendentes()` read-only em `app/checkal.py` (padrão de `detalhe()`, sem cache), rota `GET /api/checkal/fila`, painel com expansor + botão copiar em `app.js`. A BD do CheckAL continua estritamente read-only para o dashboard; as escritas vivem só nas rotas `/gate` do CheckAL.

**Tech Stack:** FastAPI + Jinja2 (já usados), sqlite3 read-only, vanilla JS. Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-07-19-enxame-editor-comunicador-publicador-design.md` §5, §8.
**Auditoria:** app web = fábrica `criar_app()` em `checkal/app/web/app.py`; templates partilhados via `app/web/marca.py` (`templates`); análogo GET+estado = `consentimento.py` `/confirmar` + `confirma.html`; análogo POST Form = `remover.py`; `config.BASE_URL` existe (localhost:8000 default) mas o gate usa base própria; a app web NÃO corre em lado nenhum hoje; Telegram envia texto simples (URLs cruas auto-linkam; markdown não renderiza).

**REGRAS DE SEGURANÇA (invioláveis neste plano):**
1. O endpoint do dashboard NUNCA devolve `token_aprovacao` (SELECT de colunas explícitas, nunca `ri.*`).
2. O gate não tem sessão/login: o token É a credencial. GET só mostra; POST revalida o token e decide.
3. Comparação de token passa a constant-time (`secrets.compare_digest`).
4. `decidido_por='dono'` sempre; autor≠aprovador continua imposto por `fila._decidir` + CHECK na BD.

---

### Task 1: Config `GATE_BASE_URL` + hardening constant-time do token

**Files:**
- Modify: `checkal/app/config.py` (secção de URLs, junto de `BASE_URL`/`SITE_URL`)
- Modify: `checkal/app/swarm/fila.py` (`_decidir`, ~linha 219)
- Test: `checkal/tests/test_swarm_fila.py` (acrescentar no fim)

- [ ] **Step 1: Testes primeiro** — no fim de `test_swarm_fila.py` (usa a fixture/padrões existentes do ficheiro; lê o topo antes):

```python
def test_gate_base_url_default_vazio_fail_closed():
    import app.config as config
    assert config.GATE_BASE_URL == ""


def test_decidir_compara_token_constant_time(bd_ou_fixture_equivalente):
    # Comportamento preservado: token errado → TokenInvalido; token certo → decide.
    # (adapta o seed ao padrão do ficheiro: item pendente + gerar_token)
    ...
```

Nota ao implementador: o segundo teste pode já existir em substância (token errado → TokenInvalido); se sim, NÃO dupliques — basta o primeiro teste + verificação de que os existentes continuam verdes após o hardening. O objetivo do hardening não é observável em teste funcional (timing); o teste guarda apenas a não-regressão.

- [ ] **Step 2: Ver falhar** — `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_swarm_fila.py -q` → FAIL (`AttributeError: GATE_BASE_URL`).

- [ ] **Step 3: Implementar**

`config.py`, junto de `BASE_URL`:

```python
# Portão 1-clique (fase 2): base URL pública das rotas /gate. Fail-closed:
# vazio ⇒ o maestro-gate-token não compõe URL e o digest cai para instrução
# manual. Em produção no Polaris: https://polaris.tail2f0d3e.ts.net:8443
# (tailscale funnel na porta 8443 — ver HANDOFF fase 2).
GATE_BASE_URL = _env("CHECKAL_GATE_BASE_URL", "")
```

`fila.py` `_decidir` — trocar a comparação simples por constant-time (import `secrets` já existe no módulo):

```python
    if (not token or not item.token_aprovacao
            or not secrets.compare_digest(token, item.token_aprovacao)):
        raise TokenInvalido("token de aprovação ausente ou inválido")
```

- [ ] **Step 4: Verde + suite** — `.venv/bin/python -m pytest -p no:warnings 2>&1 | tail -1` → tudo verde.
- [ ] **Step 5: Commit** — `git add checkal/app/config.py checkal/app/swarm/fila.py checkal/tests/test_swarm_fila.py && git commit -m "feat(gate): CHECKAL_GATE_BASE_URL fail-closed + compare_digest no token"`

---

### Task 2: Rotas `/gate` + template

**Files:**
- Create: `checkal/app/web/gate.py`
- Create: `checkal/app/web/templates/gate.html`
- Modify: `checkal/app/web/app.py` (incluir o router)
- Test: `checkal/tests/test_gate_web.py` (novo)

- [ ] **Step 1: Testes primeiro** — `tests/test_gate_web.py`, no padrão de `test_e2e_website.py` (app composta `criar_app()` + BD SQLite temporária via monkeypatch de `db.engine`/`db.SessionLocal` — copia a fixture de lá e simplifica). Casos:

```python
"""Portão 1-clique — rotas /gate/{item_id} (fase 2). TDD."""
# fixtures: bd temporária + client = TestClient(criar_app())
# seed helper: cria RevisaoItem pendente via fila.enfileirar (peça POST_SOCIAL
# conforme — reutiliza o texto _POST_OK de test_manage_editor_comunicador) e
# token = fila.gerar_token(s, item.id)


def test_gate_get_token_valido_mostra_item(client_e_seed):
    r = client.get(f"/gate/{item_id}?token={token}")
    assert r.status_code == 200
    assert "post_grupo" in r.text            # tipo visível
    assert "Aprovar" in r.text and "Rejeitar" in r.text


def test_gate_get_token_errado_pagina_invalida(client_e_seed):
    r = client.get(f"/gate/{item_id}?token=errado")
    assert r.status_code == 200              # página de estado, não 500
    assert "inválida" in r.text.lower() or "invalido" in r.text.lower()
    assert "Aprovar" not in r.text           # sem botões de decisão


def test_gate_post_aprovar_decide_e_regista(client_e_seed):
    r = client.post(f"/gate/{item_id}/aprovar", data={"token": token})
    assert r.status_code == 200
    # BD: item aprovado + linha em aprovacoes com decidido_por='dono'
    # e token reutilizado já não decide:
    r2 = client.post(f"/gate/{item_id}/rejeitar", data={"token": token})
    assert "inválida" in r2.text.lower() or "invalido" in r2.text.lower()


def test_gate_post_rejeitar_decide(client_e_seed_novo_item): ...


def test_gate_item_inexistente_pagina_invalida():
    r = client.get("/gate/99999?token=x")
    assert r.status_code == 200 and "Aprovar" not in r.text
```

- [ ] **Step 2: Ver falhar** (404 nas rotas).

- [ ] **Step 3: Implementar `gate.py`** (padrão de `consentimento.py`/`remover.py` — lê-os primeiro):

```python
"""Portão 1-clique do dono — GET mostra, POST decide (fase 2 do enxame).

Sem sessão/login: o token gerado pelo MAESTRO (maestro-gate-token) é a
credencial. GET nunca decide; POST revalida o token via fila._decidir
(constant-time) e escreve a decisão + linha em `aprovacoes`. Autor≠aprovador
continua imposto a jusante. Página noindex."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.swarm import fila
from app.web.marca import templates

router = APIRouter()
roteador = router


def _carregar_item(item_id: int):
    import app.models_swarm as ms
    import app.db as db
    s = db.SessionLocal()
    try:
        return s.get(ms.RevisaoItem, item_id), s
    except Exception:
        s.close()
        raise


def _render(request, *, estado: str, item=None, mensagem: str = ""):
    return templates.TemplateResponse(
        request=request, name="gate.html",
        context={"estado": estado, "item": item, "mensagem": mensagem},
    )


@router.get("/gate/{item_id}", response_class=HTMLResponse)
def gate_ver(request: Request, item_id: int, token: str = ""):
    import secrets as _secrets
    item, s = _carregar_item(item_id)
    try:
        if (item is None or item.estado != "pendente" or not token
                or not item.token_aprovacao
                or not _secrets.compare_digest(token, item.token_aprovacao)):
            return _render(request, estado="invalido")
        return _render(request, estado="pendente", item=item)
    finally:
        s.rollback(); s.close()


def _decidir_web(request, item_id: int, token: str, acao: str):
    try:
        with fila.sessao_governacao() as s:
            fn = fila.aprovar if acao == "aprovado" else fila.rejeitar
            fn(s, item_id, token=token, decidido_por="dono")
    except (fila.TokenInvalido, fila.AutorNaoAprova):
        return _render(request, estado="invalido")
    return _render(request, estado=acao)


@router.post("/gate/{item_id}/aprovar", response_class=HTMLResponse)
def gate_aprovar(request: Request, item_id: int, token: str = Form("")):
    return _decidir_web(request, item_id, token, "aprovado")


@router.post("/gate/{item_id}/rejeitar", response_class=HTMLResponse)
def gate_rejeitar(request: Request, item_id: int, token: str = Form("")):
    return _decidir_web(request, item_id, token, "rejeitado")
```

(Ajusta `_carregar_item`/sessões ao padrão real dos módulos vizinhos — o que importa preservar: GET read-only com rollback; POST via `fila.sessao_governacao()`; nunca expor `token_aprovacao` no HTML além do hidden input do form.)

- [ ] **Step 4: Template `gate.html`** — estende `base.html` (lê `confirma.html` e copia a estrutura de blocos/classes):

```html
{% extends "base.html" %}
{% block title %}Aprovação · CheckAL{% endblock %}
{% block meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}
{% block content %}
<section class="seccao seccao--estreita">
  {% if estado == "pendente" %}
    <h1>Item #{{ item.id }} · {{ item.tipo }}</h1>
    <p class="meta">agente: {{ item.agente_origem }} · risco: {{ item.risco }} (camada {{ item.camada_risco }})</p>
    <p>{{ item.resumo }}</p>
    <form method="post" action="/gate/{{ item.id }}/aprovar" style="display:inline">
      <input type="hidden" name="token" value="{{ request.query_params.get('token','') }}">
      <button class="btn btn--acao" type="submit">✓ Aprovar</button>
    </form>
    <form method="post" action="/gate/{{ item.id }}/rejeitar" style="display:inline">
      <input type="hidden" name="token" value="{{ request.query_params.get('token','') }}">
      <button class="btn" type="submit">✗ Rejeitar</button>
    </form>
  {% elif estado == "aprovado" %}
    <div class="estado estado--ok"><h1>Aprovado ✓</h1><p>Decisão registada. Podes fechar esta página.</p></div>
  {% elif estado == "rejeitado" %}
    <div class="estado"><h1>Rejeitado</h1><p>Decisão registada. O item não será executado.</p></div>
  {% else %}
    <div class="estado"><h1>Ligação inválida</h1><p>Este link de aprovação expirou, já foi usado, ou o item já foi decidido.</p></div>
  {% endif %}
</section>
{% endblock %}
```

(Confere os nomes reais dos blocos/classes em `base.html`/`confirma.html` e ajusta.)

- [ ] **Step 5: Registar em `app.py`** — `from app.web import gate` + `app.include_router(gate.router)` junto dos outros.
- [ ] **Step 6: Verde + suite completa.**
- [ ] **Step 7: Commit** — `feat(gate): rotas /gate/{item_id} GET/POST + template (portão 1-clique)`

---

### Task 3: `maestro-gate-token` devolve URL + prompt do maestro

**Files:**
- Modify: `checkal/manage.py` (`_cmd_maestro_gate_token`, ~linha 418)
- Modify: `checkal/prompts/maestro.txt` + `agentes-polaris/prompts/maestro.txt` (idênticos)
- Test: `checkal/tests/test_manage_editor_comunicador.py` (acrescentar)

- [ ] **Step 1: Testes primeiro**:

```python
def test_gate_token_sem_base_url_nao_tem_url(bd, capsys, monkeypatch):
    monkeypatch.setattr(config, "GATE_BASE_URL", "")
    # seed: item pendente na fila (via comunicador enfileirar, reutiliza _POST_OK)
    ...
    assert manage.main(["maestro-gate-token", "--fila-id", str(item_id)]) == 0
    dados = _json_out(capsys)
    assert "token" in dados and "url" not in dados


def test_gate_token_com_base_url_compoe_url(bd, capsys, monkeypatch):
    monkeypatch.setattr(config, "GATE_BASE_URL", "https://exemplo.ts.net:8443")
    ...
    dados = _json_out(capsys)
    assert dados["url"] == f"https://exemplo.ts.net:8443/gate/{item_id}?token={dados['token']}"
```

- [ ] **Step 2: Ver falhar.** **Step 3: Implementar** — em `_cmd_maestro_gate_token`, depois de obter o token:

```python
    saida = {"fila_id": args.fila_id, "token": token}
    if config.GATE_BASE_URL:
        saida["url"] = f"{config.GATE_BASE_URL.rstrip('/')}/gate/{args.fila_id}?token={token}"
    _print_json(saida)
```

(Preserva o tratamento de erros existente do handler.)

- [ ] **Step 4: Prompt do maestro (as DUAS árvores, byte-idênticas no fim):** na secção do digest onde diz "1 linha + [Aprovar]/[Rejeitar] link", substituir por: "1 linha de resumo e, na linha seguinte, o `url` devolvido por maestro-gate-token EM CRU (sem markdown — o Telegram auto-linka URLs cruas e não renderiza markdown). Se o subcomando não devolver `url` (portão web por configurar), escreve `aprovação manual: item <id>` em vez de link."
- [ ] **Step 5: Verde + suite + diff vazio entre árvores.**
- [ ] **Step 6: Commit** — `feat(gate): maestro-gate-token compõe URL do portão; digest com URLs cruas`

---

### Task 4: Servir a app web no Polaris (unit + instalador + handoff)

**Files:**
- Create: `deploy/systemd/checkal-web.service` (+ variante normalizada em `deploy/polaris/units/` — espelha o padrão da árvore, sem comentários)
- Modify: `deploy/polaris/instalar.sh`
- Create: `docs/superpowers/plans/2026-07-19-fase2-HANDOFF.md`

- [ ] **Step 1: Verificar pré-requisito** — `ls /home/diogo/checkal-polaris/checkal/.venv/bin/uvicorn`. Se não existir: verifica se `uvicorn` está em `requirements.txt`; se estiver, instala no venv (`.venv/bin/pip install uvicorn`) e reporta; se não estiver, reporta BLOCKED (não adivinhes versões).

- [ ] **Step 2: `deploy/systemd/checkal-web.service`:**

```ini
# Portão 1-clique + páginas públicas do CheckAL — uvicorn local (127.0.0.1:8600).
# Exposição via tailscale (funnel 8443) é passo manual do dono — HANDOFF fase 2.
[Unit]
Description=CheckAL Web — portão de aprovação (uvicorn 127.0.0.1:8600)
After=network.target

[Service]
User=diogo
Group=diogo
WorkingDirectory=/home/diogo/checkal-polaris/checkal
EnvironmentFile=/home/diogo/checkal-polaris/deploy/polaris/agente.env
ExecStart=/home/diogo/checkal-polaris/checkal/.venv/bin/uvicorn app.web.app:criar_app --factory --host 127.0.0.1 --port 8600
Restart=on-failure
RestartSec=5
MemoryMax=768M
CPUQuota=50%
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Variante em `deploy/polaris/units/`** no padrão normalizado da árvore (sem comentários, Description curta).
- [ ] **Step 4: `instalar.sh`** — secção nova antes do `echo "OK…"`: `systemctl enable --now checkal-web.service` com comentário `# Portão 1-clique (fase 2) — só local (127.0.0.1:8600); exposição tailscale é manual`.
- [ ] **Step 5: Smoke local SEM systemd** (não instales units): `cd /home/diogo/checkal-polaris/checkal && timeout 10 .venv/bin/uvicorn app.web.app:criar_app --factory --host 127.0.0.1 --port 8601 & sleep 3 && curl -s http://127.0.0.1:8601/saude && curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8601/gate/1?token=x"` → espera `{"ok": …}` do /saude e `200` (página inválida) do /gate. Mata o processo no fim.
- [ ] **Step 6: HANDOFF fase 2** (`docs/superpowers/plans/2026-07-19-fase2-HANDOFF.md`):

```markdown
# Fase 2 — passos manuais do dono

1. Instalar/ativar o serviço web: `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
2. Expor o portão via tailscale funnel na porta 8443 (coexiste com o Agent OS no 443):
   `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8600`
   (para fechar: `sudo tailscale funnel --https=8443 off`)
3. No `deploy/polaris/agente.env`: `CHECKAL_GATE_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443`
   (sem isto o digest cai para "aprovação manual" — fail-closed, nada parte)
4. Teste ponta-a-ponta: `python manage.py maestro-gate-token --fila-id <id de um item pendente>`
   → abre o `url` no telemóvel → Aprovar/Rejeitar.
Nota de segurança: o funnel expõe a app CheckAL INTEIRA, incluindo /admin.
Antes de abrir o funnel, confirma que o login admin está protegido (ADMIN_PASSWORD/
SECRET_KEY definidos no agente.env). Se preferires não expor publicamente, usa
`sudo tailscale serve --bg --https=8443 http://127.0.0.1:8600` (só tailnet — o
telemóvel precisa do Tailscale instalado). O gate em si é seguro por token.
```

- [ ] **Step 7: Commit** — `feat(gate): checkal-web.service (uvicorn 8600) + instalador + handoff fase 2`

---

### Task 5: Dashboard — `fila_pendentes()` + rota `/api/checkal/fila`

**Files (projeto Dashboard_Polaris — NÃO é git; ler `agent-os/CLAUDE.md` primeiro):**
- Modify: `agent-os/app/checkal.py` (função nova a seguir a `detalhe()`)
- Modify: `agent-os/app/main.py` (rota na secção checkal read-only, ~linha 478)

- [ ] **Step 1: Implementar `fila_pendentes()`** (padrão de `detalhe()`: sem cache, `_connect()`, `db_ok`):

```python
def fila_pendentes() -> dict:
    """Itens 'pendente' da fila de revisão com corpo completo (join ao evento).

    Para o painel "Para publicar". READ-ONLY. NUNCA devolve token_aprovacao —
    esse token é a credencial do portão 1-clique do CheckAL; expô-lo aqui
    permitiria forjar aprovações a partir de qualquer sessão do dashboard.
    """
    out: dict = {"generated_at": _agora_iso(), "db_ok": True, "itens": []}
    try:
        con = _connect()
    except sqlite3.Error as e:
        out["db_ok"] = False; out["db_error"] = str(e); return out
    try:
        rows = con.execute(
            """
            SELECT ri.id, ri.tipo, ri.risco, ri.camada_risco, ri.agente_origem,
                   ri.resumo, ri.criado_em, e.payload
              FROM revisao_itens ri
              LEFT JOIN eventos_agente e
                ON ri.ref_tipo = 'evento_agente'
               AND e.id = CAST(ri.ref_id AS INTEGER)
             WHERE ri.estado = 'pendente'
             ORDER BY ri.id DESC
             LIMIT 50
            """
        ).fetchall()
        for r in rows:
            corpo, extra = None, {}
            if r["payload"]:
                try:
                    payload = json.loads(r["payload"])
                    corpo = payload.get("corpo_texto")
                    if corpo is None and isinstance(payload.get("artigo"), dict):
                        a = payload["artigo"]
                        partes = [a.get("titulo", "")]
                        for sec in a.get("seccoes", []):
                            partes += [f"## {sec.get('h2','')}", sec.get("corpo_md", "")]
                        corpo = "\n\n".join(p for p in partes if p)
                        extra["slug"] = a.get("slug")
                    extra["grupo_alvo"] = payload.get("grupo_alvo")
                    extra["fonte_url"] = payload.get("fonte_url")
                except (ValueError, TypeError):
                    pass
            out["itens"].append({
                "id": r["id"], "tipo": r["tipo"], "risco": r["risco"],
                "camada_risco": r["camada_risco"],
                "agente_origem": r["agente_origem"], "resumo": r["resumo"],
                "criado_em": r["criado_em"],
                "corpo": (corpo or "")[:100_000] or None,
                **{k: v for k, v in extra.items() if v},
            })
    except sqlite3.Error as e:
        out["db_ok"] = False; out["db_error"] = str(e)
    finally:
        con.close()
    return out
```

(Adapta `_agora_iso()` ao helper real do ficheiro; `json`/`sqlite3` já importados — confirma.)

- [ ] **Step 2: Rota em `main.py`** (secção checkal read-only):

```python
@app.get("/api/checkal/fila")
async def api_checkal_fila():
    return await asyncio.to_thread(checkal.fila_pendentes)
```

- [ ] **Step 3: Sanity** — `python3 -m py_compile` nos dois; depois no deployment (após Task 6 copiar) valida com chamada direta.
- [ ] **Step 4:** sem commit (não é git). Regista os ficheiros no report.

---

### Task 6: Dashboard — painel "Para publicar" + copiar + deploy

**Files:**
- Modify: `agent-os/app/static/app.js` (painel em `viewCheckal`, helper de clipboard)
- Modify: `agent-os/CLAUDE.md` (menção TETO_CENTS 2500→4000 desatualizada — corrige ao passar)
- Deploy: copiar `checkal.py`, `main.py`, `app.js` para `/home/diogo/agent-os/app/` + restart pela regra do `agent-os/CLAUDE.md`

- [ ] **Step 1: Helper de clipboard** (novo, junto dos helpers no topo do app.js):

```javascript
async function copiarTexto(btn, texto){
  let ok = false;
  try { await navigator.clipboard.writeText(texto); ok = true; }
  catch(_){
    const ta = document.createElement('textarea');
    ta.value = texto; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { ok = document.execCommand('copy'); } catch(_){}
    ta.remove();
  }
  const orig = [...btn.childNodes];
  btn.textContent = ok ? '✓ copiado' : 'falhou';
  setTimeout(() => btn.replaceChildren(...orig), 1600);
}
```

- [ ] **Step 2: Painel em `viewCheckal`** — card novo entre o KPI strip e a grelha de agentes, só quando `d.kpis.fila_pendente > 0` (fetch a `/api/checkal/fila` via `api()` dentro do render; cada item: linha `.tl-item` com emoji do agente, chip do tipo, resumo, expansor `.exp-btn`/`.md-clip` com o `corpo` completo e o botão `Copiar` a chamar `copiarTexto(btn, item.corpo)`; itens sem corpo mostram o resumo + nota "sem corpo disponível"; para `post_grupo` mostra também `grupo_alvo` se existir). Segue os padrões exatos do card do digest (linhas ~1356-1377) e das linhas de pendentes do detalhe (~1146-1160) — substitui lá a nota "Aprovar/rejeitar chega na fase 2" por "aprovação: link do digest".
- [ ] **Step 3: `node --check app/static/app.js`.**
- [ ] **Step 4: Deploy** — copiar os 3 ficheiros para `/home/diogo/agent-os/app/` (+static), restart EXATO pela regra (matar só o python real; `AGENTOS_HOME=… setsid … -m app.serve`), confirmar porta 8100 + log limpo.
- [ ] **Step 5: Verificação funcional** — no deployment: `venv/bin/python -c "from app import checkal; import json; print(json.dumps(checkal.fila_pendentes())[:400])"` → `db_ok: true`, `itens: []` (fila vazia hoje) e SEM a string `token` no output. Grep de segurança: `venv/bin/python -c "from app import checkal; assert 'token_aprovacao' not in str(checkal.fila_pendentes())"`.

---

### Task 7: Verificação final da fase 2

- [ ] Suite CheckAL completa verde; smoke do gate com uvicorn temporário (Task 4 Step 5 repetido pós-tudo); dashboard live com 6 agentes + endpoint fila; commit de eventuais retoques; revisão final de conjunto (subagente); atualizar `PROGRESSO-REDESIGN.md` do Dashboard_Polaris se o padrão da casa o pedir (verifica o cabeçalho do ficheiro).
