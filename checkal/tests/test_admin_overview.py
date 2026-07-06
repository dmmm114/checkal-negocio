"""Testes do overview + leads do painel admin — app.web.admin.dashboard_overview.

SPEC-FASE1-DASHBOARD §dashboard. O painel é do DONO e só do dono (todas as rotas
sob `requer_admin`). Estas são as duas primeiras secções do WF3:

  GET /admin (overview):
    - nº de clientes ATIVOS (estado == 'ativo'; cancelados/dunning NÃO contam);
    - MRR estimado a partir de `config.PLANOS` (preço ÷ meses, por cliente ativo);
    - nº de alertas ENVIADOS (`enviado_em` preenchido; os pendentes não contam);
    - nº de opt-outs (lista de supressão);
    - nº de leads POR ESTADO (pendente/confirmado/removido);
    - último varrimento (o mais recente por `iniciado_em`).

  GET /admin/leads:
    - lista dos prospects consent-first por estado (email + contexto operacional).

Contrato verificado (o que o SPEC exige, "Testa: cada página 200 com os números
certos de dados semeados; sem sessão → bloqueado; zero PII indevida"):
  * autenticado → 200 com os números EXATOS dos dados semeados;
  * sem sessão → bloqueado (303 para /admin/login), em ambas as rotas;
  * minimização: o overview mostra CONTAGENS, nunca os emails dos leads
    (a PII dos leads só aparece na secção /admin/leads, onde é necessária à operação).

Isolamento (igual a test_consentimento.py): BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; app FastAPI montada com o router de auth + o de
overview; `TestClient`. A sessão obtém-se pelo login real (POST /admin/login com a
password injetada por monkeypatch, lida a cada chamada). LIVE-GATED: só lê a BD, não
toca a rede. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

_PASSWORD = "segredo-do-dono-42"


# --------------------------------------------------------------------------
#  Fixtures: BD SQLite temporária + password + TestClient (auth + overview)
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_admin.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def password(monkeypatch):
    """Injeta a password do dono (lida a cada verificação; default sob pytest recusa tudo)."""
    monkeypatch.setattr(config, "ADMIN_PASSWORD", _PASSWORD)
    return _PASSWORD


@pytest.fixture()
def app_(bd, password):
    from app.web.admin import auth, dashboard_overview

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(dashboard_overview.router)
    return app


@pytest.fixture()
def anon(app_):
    """Cliente SEM sessão (não segue redirects — queremos assertar o 303→login)."""
    return TestClient(app_, follow_redirects=False)


@pytest.fixture()
def client(app_):
    """Cliente AUTENTICADO: faz login real (o cookie assinado fica no jar)."""
    c = TestClient(app_, follow_redirects=False)
    r = c.post("/admin/login", data={"password": _PASSWORD})
    assert r.status_code == 303  # sanidade: entrou
    return c


# --------------------------------------------------------------------------
#  Semear a BD com dados de contagem conhecida
# --------------------------------------------------------------------------
def _semear() -> None:
    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        # Clientes: 3 ATIVOS (2 anual + 1 trienal) + 1 cancelado (NÃO conta) ------
        s.add_all([
            models.Cliente(email="c1@ex.pt", plano="anual", estado="ativo", criado_em=agora),
            models.Cliente(email="c2@ex.pt", plano="anual", estado="ativo", criado_em=agora),
            models.Cliente(email="c3@ex.pt", plano="trienal", estado="ativo", criado_em=agora),
            models.Cliente(email="c4@ex.pt", plano="anual", estado="cancelado", criado_em=agora),
        ])
        # Alertas: 2 ENVIADOS + 1 na fila (enviado_em None → NÃO conta) -----------
        s.add_all([
            models.Alerta(cliente_id=1, conteudo="a", enviado_em=agora),
            models.Alerta(cliente_id=2, conteudo="b", enviado_em=agora),
            models.Alerta(cliente_id=3, conteudo="c", enviado_em=None),
        ])
        # Opt-outs: 3 -------------------------------------------------------------
        s.add_all([
            models.OptOut(email="o1@ex.pt", origem="formulario", criado_em=agora),
            models.OptOut(email="o2@ex.pt", origem="formulario", criado_em=agora),
            models.OptOut(email="o3@ex.pt", origem="email_1clique", criado_em=agora),
        ])
        # Leads: 2 pendentes + 1 confirmado + 1 removido --------------------------
        s.add_all([
            models.Lead(email="pend1@ex.pt", estado="pendente", consent_alertas=True, criado_em=agora),
            models.Lead(email="pend2@ex.pt", estado="pendente", consent_alertas=True, criado_em=agora),
            models.Lead(email="conf@ex.pt", estado="confirmado", consent_alertas=True, criado_em=agora),
            models.Lead(email="rem@ex.pt", estado="removido", consent_alertas=True, criado_em=agora),
        ])
        # Varrimentos: o mais recente é o "último" mostrado ----------------------
        s.add_all([
            models.Varrimento(
                iniciado_em=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                concluido_em=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                estado="parcial", total_registos=100,
            ),
            models.Varrimento(
                iniciado_em=datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc),
                concluido_em=datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc),
                estado="ok", total_registos=12345,
            ),
        ])


def _metrica(corpo: str, nome: str) -> str:
    """Extrai o valor renderizado de `data-metrica="<nome>">VALOR<`."""
    m = re.search(rf'data-metrica="{re.escape(nome)}"[^>]*>([^<]*)<', corpo)
    assert m is not None, f'métrica {nome!r} não encontrada no HTML'
    return m.group(1).strip()


# ==========================================================================
#  Sem sessão → bloqueado (303 para o login) — ambas as rotas
# ==========================================================================
def test_overview_sem_sessao_bloqueia(anon):
    r = anon.get("/admin")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_leads_sem_sessao_bloqueia(anon):
    r = anon.get("/admin/leads")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_overview_sem_sessao_nao_da_200(anon):
    assert anon.get("/admin").status_code != 200


# ==========================================================================
#  GET /admin (overview) — 200 com os números certos dos dados semeados
# ==========================================================================
def test_overview_200_e_chrome_da_marca(client):
    _semear()
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # chrome da marca + nav do painel
    assert "CheckAL" in corpo
    assert "/static/brand.css" in corpo
    assert 'href="/admin/leads"' in corpo    # nav para a secção de leads
    assert "/admin/logout" in corpo          # sair


def test_overview_conta_clientes_ativos(client):
    _semear()
    corpo = client.get("/admin").text
    # 3 ativos (o cancelado não conta)
    assert _metrica(corpo, "clientes_ativos") == "3"


def test_overview_mrr_estimado_de_planos(client):
    _semear()
    corpo = client.get("/admin").text
    # 2×(49/12) + 119/36 = 11,4722… → 11,47 (€, formato pt)
    valor = _metrica(corpo, "mrr")
    assert "11,47" in valor


def test_overview_conta_alertas_enviados(client):
    _semear()
    corpo = client.get("/admin").text
    # 2 enviados; o da fila (enviado_em None) não conta
    assert _metrica(corpo, "alertas_enviados") == "2"


def test_overview_conta_optouts(client):
    _semear()
    corpo = client.get("/admin").text
    assert _metrica(corpo, "opt_outs") == "3"


def test_overview_conta_leads_por_estado(client):
    _semear()
    corpo = client.get("/admin").text
    assert _metrica(corpo, "leads_pendente") == "2"
    assert _metrica(corpo, "leads_confirmado") == "1"
    assert _metrica(corpo, "leads_removido") == "1"


def test_overview_mostra_ultimo_varrimento(client):
    _semear()
    corpo = client.get("/admin").text
    bloco = _metrica(corpo, "ultimo_varrimento")
    # o mais recente (05/07/2026, estado ok) — nunca o antigo (01/06/2026)
    assert "05/07/2026" in bloco
    assert "ok" in bloco
    assert "01/06/2026" not in corpo


def test_overview_sem_varrimentos_nao_rebenta(client):
    # BD vazia (sem semear): overview responde 200 mesmo sem varrimentos/clientes
    r = client.get("/admin")
    assert r.status_code == 200
    assert _metrica(r.text, "clientes_ativos") == "0"


# ==========================================================================
#  Minimização (SPEC): o overview mostra CONTAGENS, nunca os emails dos leads
# ==========================================================================
def test_overview_nao_expoe_emails_de_leads(client):
    _semear()
    corpo = client.get("/admin").text
    assert "pend1@ex.pt" not in corpo
    assert "conf@ex.pt" not in corpo


# ==========================================================================
#  GET /admin/leads — 200 com os prospects por estado
# ==========================================================================
def test_leads_200_lista_prospects_por_estado(client):
    _semear()
    r = client.get("/admin/leads")
    assert r.status_code == 200
    corpo = r.text
    # cada lead semeado aparece (email é necessário à operação do dono)
    for email in ("pend1@ex.pt", "pend2@ex.pt", "conf@ex.pt", "rem@ex.pt"):
        assert email in corpo
    # os três estados consent-first aparecem
    assert "pendente" in corpo
    assert "confirmado" in corpo
    assert "removido" in corpo


def test_leads_contagens_por_estado(client):
    _semear()
    corpo = client.get("/admin/leads").text
    assert _metrica(corpo, "leads_pendente") == "2"
    assert _metrica(corpo, "leads_confirmado") == "1"
    assert _metrica(corpo, "leads_removido") == "1"


def test_leads_vazio_nao_rebenta(client):
    r = client.get("/admin/leads")
    assert r.status_code == 200
    assert _metrica(r.text, "leads_pendente") == "0"


# ==========================================================================
#  Unidade: o cálculo de MRR vem de config.PLANOS (não hard-coded no template)
# ==========================================================================
def test_mrr_estimado_helper(bd):
    from app.web.admin import dashboard_overview as d

    _semear()
    with db.get_session() as s:
        mrr = d.mrr_estimado(s)
    esperado = round(2 * (49.0 / 12) + 119.0 / 36, 2)
    assert mrr == esperado
