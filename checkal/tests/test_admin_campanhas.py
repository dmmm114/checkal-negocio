"""Testes do painel de campanhas + compliance — app.web.admin.dashboard_campanhas.

Contrato (SPEC-FASE1-DASHBOARD §campanhas/§compliance + task WF3):

  GET /admin/campanhas  (sob requer_admin):
    - gatilhos → segmentos (cold_email / carta / suprimidos / descartados) com os
      NÚMEROS certos a partir de dados semeados;
    - a **fila de aprovação** do cold com o botão "Disparar" **DESATIVADO** e um
      aviso a explicar o porquê (parecer RGPD) enquanto `config.pode_enviar_frio_global()`
      for False — e ATIVO quando (e só quando) o portão abre;
    - NENHUM disparo real: não há POST/endpoint que envie (a página é read-first).

  GET /admin/compliance  (sob requer_admin):
    - log de opt-outs (`OptOut`) + proveniências (prova do canal frio) +
      consentimentos (`Lead`: texto+versão, timestamp, IP) — a prova para a CNPD;
    - exportação CSV (consentimentos + opt-outs) — **só autenticado** (sem sessão
      → redireciona ao login e NÃO vaza PII).

Isolamento igual aos restantes testes web: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; app FastAPI montada com o router de auth + o router do
dashboard; autenticação real (POST /admin/login com `config.ADMIN_PASSWORD`
injetada). LIVE-GATED: nada toca a rede; o portão frio nasce fechado (modo de teste).
Escrito ANTES da implementação (TDD).
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
#  Fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_admin_camp.db'}"
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
    monkeypatch.setattr(config, "ADMIN_PASSWORD", _PASSWORD)
    return _PASSWORD


@pytest.fixture()
def app(bd, password):
    from app.web.admin import auth
    from app.web.admin import dashboard_campanhas

    application = FastAPI()
    application.include_router(auth.router)
    application.include_router(dashboard_campanhas.router)
    return application


@pytest.fixture()
def anon(app):
    """Cliente SEM sessão (não segue redirects — para assertar o 303→login)."""
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def client(app):
    """Cliente autenticado como o dono (cookie de sessão assinado no jar)."""
    c = TestClient(app, follow_redirects=False)
    r = c.post("/admin/login", data={"password": _PASSWORD})
    assert r.status_code == 303  # entrou
    return c


# --------------------------------------------------------------------------
#  Semeadura determinística
# --------------------------------------------------------------------------
def _semear() -> None:
    """Três registos + eventos 'novo' + opt-outs + um Lead com prova de consentimento.

      1001 — coletiva (NIF 5) com email genérico  → candidato COLD
      1002 — singular (NIF 2) com email pessoal    → canal CARTA
      1003 — coletiva (NIF 6) com email genérico   → COLD mas OPT-OUT → SUPRIMIDO
    """
    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=1001, titular_tipo="coletiva", titular_nome="Empresa A Lda",
            nif="500000000", email="reservas@empresa-a.pt", concelho="Lisboa",
            endereco="Av. A 1", cod_postal="1000-001", nome_alojamento="AL A",
        ))
        s.add(models.Registo(
            nr_registo=1002, titular_tipo="singular", titular_nome="João Silva",
            nif="200000000", email="joao.silva@gmail.com", concelho="Porto",
            endereco="Rua B 2", cod_postal="4000-002", nome_alojamento="AL B",
        ))
        s.add(models.Registo(
            nr_registo=1003, titular_tipo="coletiva", titular_nome="Empresa C Lda",
            nif="600000000", email="geral@empresa-c.pt", concelho="Faro",
            endereco="Rua C 3", cod_postal="8000-003", nome_alojamento="AL C",
        ))
        s.flush()
        for nr in (1001, 1002, 1003):
            s.add(models.EventoRegisto(nr_registo=nr, tipo="novo", detetado_em=agora, processado=False))
        # Opt-outs (já normalizados — minúsculas)
        s.add(models.OptOut(email="geral@empresa-c.pt", origem="formulario", criado_em=agora))
        s.add(models.OptOut(email="outro@x.pt", origem="email_1clique", criado_em=agora))
        # Lead consent-first com a PROVA (texto+versão, quando, IP)
        s.add(models.Lead(
            email="interessado@gmail.com", nr_registo=1001, concelho="Lisboa",
            consent_alertas=True, consent_ofertas=False,
            consentimento_texto_versao="[v2026-07-06] alertas: Autorizo a Cosmic Oasis...",
            consentimento_em=agora, ip="203.0.113.7", estado="confirmado",
            token_confirmacao="tok-abc-123", criado_em=agora,
        ))


def _metrica(html: str, nome: str) -> int:
    m = re.search(rf'data-metrica="{nome}"[^>]*>\s*(\d+)', html)
    assert m, f"métrica {nome!r} ausente da página"
    return int(m.group(1))


def _botao_disparar(html: str) -> str | None:
    m = re.search(r"<button[^>]*data-disparar[^>]*>", html, re.S)
    return m.group(0) if m else None


# ==========================================================================
#  /admin/campanhas — autenticação
# ==========================================================================
def test_campanhas_sem_sessao_redireciona_login(anon):
    _semear()
    r = anon.get("/admin/campanhas")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # nada de dados operacionais no corpo do redirect
    assert "reservas@empresa-a.pt" not in r.text


# ==========================================================================
#  /admin/campanhas — gatilhos → segmentos (dados certos)
# ==========================================================================
def test_campanhas_segmentos_com_numeros_certos(client):
    _semear()
    r = client.get("/admin/campanhas")
    assert r.status_code == 200
    body = r.text

    # três eventos 'novo'
    assert _metrica(body, "novos") == 3
    # segmentos: A→cold, B→carta, C→suprimido (opt-out)
    assert _metrica(body, "cold") == 1
    assert _metrica(body, "carta") == 1
    assert _metrica(body, "suprimidos") == 1

    # a fila de cold mostra a coletiva endereçável…
    assert "reservas@empresa-a.pt" in body
    assert "1001" in body
    # …e NUNCA o singular (carta, email não materializado) nem o suprimido (opt-out)
    assert "joao.silva@gmail.com" not in body
    assert "geral@empresa-c.pt" not in body


# ==========================================================================
#  /admin/campanhas — botão de disparo DESATIVADO sob gate fechado
# ==========================================================================
def test_botao_disparar_desativado_sob_gate_fechado(client):
    _semear()
    # o portão nasce fechado sob pytest (CHECKAL_MODO_TESTE=True)
    assert config.pode_enviar_frio_global() is False

    r = client.get("/admin/campanhas")
    assert r.status_code == 200
    body = r.text

    botao = _botao_disparar(body)
    assert botao is not None, "a fila de aprovação do cold devia ter o botão Disparar"
    assert "disabled" in botao, "o botão Disparar tem de estar DESATIVADO sob gate fechado"

    # o aviso explica o porquê (parecer RGPD)
    assert "parecer" in body.lower()


def test_botao_disparar_ativa_quando_o_portao_abre(client, monkeypatch):
    """Prova que o estado do botão é DERIVADO de config.pode_enviar_frio_global()
    (não é hardcoded): com o portão aberto, o botão deixa de estar desativado."""
    _semear()
    monkeypatch.setattr(config, "pode_enviar_frio_global", lambda: True)

    r = client.get("/admin/campanhas")
    assert r.status_code == 200
    botao = _botao_disparar(r.text)
    assert botao is not None
    assert "disabled" not in botao


def test_campanhas_nao_tem_disparo_real(client):
    """Read-first: não existe endpoint que ENVIE — um POST à página é 405."""
    _semear()
    r = client.post("/admin/campanhas")
    assert r.status_code == 405


# ==========================================================================
#  /admin/compliance — provas para a CNPD
# ==========================================================================
def test_compliance_sem_sessao_redireciona_login(anon):
    _semear()
    r = anon.get("/admin/compliance")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    assert "interessado@gmail.com" not in r.text


def test_compliance_mostra_optouts_proveniencias_e_consentimentos(client):
    _semear()
    r = client.get("/admin/compliance")
    assert r.status_code == 200
    body = r.text

    # opt-outs (lista de supressão)
    assert "geral@empresa-c.pt" in body
    assert "outro@x.pt" in body

    # proveniências (prova do canal frio — lookup dirigido, não scraping)
    assert "rnal:email_generico_publicado" in body
    assert "reservas@empresa-a.pt" in body

    # consentimentos (Lead): email + texto/versão + IP
    assert "interessado@gmail.com" in body
    assert "[v2026-07-06]" in body
    assert "203.0.113.7" in body


# ==========================================================================
#  /admin/compliance — exportação CSV (só autenticado)
# ==========================================================================
def test_export_consentimentos_csv_autenticado(client):
    _semear()
    r = client.get("/admin/compliance/consentimentos.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    corpo = r.text
    assert "interessado@gmail.com" in corpo
    assert "203.0.113.7" in corpo
    assert "[v2026-07-06]" in corpo


def test_export_optouts_csv_autenticado(client):
    _semear()
    r = client.get("/admin/compliance/optouts.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    corpo = r.text
    assert "geral@empresa-c.pt" in corpo
    assert "outro@x.pt" in corpo


def test_export_csv_sem_sessao_bloqueado_e_nao_vaza_pii(anon):
    _semear()
    r = anon.get("/admin/compliance/consentimentos.csv")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # a PII NÃO viaja para um não-autenticado
    assert "interessado@gmail.com" not in r.text
    assert "203.0.113.7" not in r.text

    r2 = anon.get("/admin/compliance/optouts.csv")
    assert r2.status_code == 303
    assert "geral@empresa-c.pt" not in r2.text
