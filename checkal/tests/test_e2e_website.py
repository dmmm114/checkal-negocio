"""E2E do WEBSITE consent-first (WIRE — SPEC-FASE1-WEB §Wire).

Exercita a app COMPOSTA (`app.web.app.criar_app`) de ponta a ponta, pelo caminho
real de um titular, com todos os routers montados por `criar_app` (landing +
verificação + páginas + consentimento + remover + selo + webhook), StaticFiles
incluído:

    1. GET /                     landing consent-first (200 HTML, o widget presente);
    2. GET /api/verificar?q=     verificação pública do AL semeado (só dados do
                                 estabelecimento — nunca contactos do titular);
    3. POST /inscrever           consent-first: grava o Lead 'pendente' + a PROVA
                                 (texto+versão, timestamp, IP) e dispara o double
                                 opt-in (mock injetado — LIVE-GATED) → 303 /obrigado;
    4. GET /confirmar?token=     ativa o Lead ('pendente' → 'confirmado');
    5. GET /remover?e=           opt-out de 1 clique: grava `optouts` + marca o Lead
                                 'removido' (o loop de compliance fecha);
    6. GET /selo/{nr}            página pública do selo — 200, ZERO PII do titular.

DISCIPLINA (inviolável): **LIVE-GATED.** BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; o enviador é um DUPLO injetado em
`envio.obter_enviador` — nada toca a rede. Isolamento igual a test_consentimento.py /
test_selo.py. Português. Escrito ANTES do wire (TDD).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.envio as envio
import app.models as models

# AL semeado (dados públicos) + PII do titular que NUNCA pode sair na vista pública.
_NR = 100031
_NOME_AL = "Casa das Flores"
_CONCELHO = "Lagos"
_DISTRITO = "Faro"
_MODALIDADE = "Apartamento"

_NIF = "513029591"
_EMAIL_TITULAR = "dono.privado@exemplo.pt"
_TITULAR = "João Titular Silva"
_TELEFONE = "289111222"
_TELEMOVEL = "912333444"

# O interessado que se inscreve (consent-first) — distinto do titular do RNAL.
_LEAD_EMAIL = "interessado@exemplo.pt"


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_web.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=_NR,
            data_registo=date(2019, 7, 16),
            nome_alojamento=_NOME_AL,
            modalidade=_MODALIDADE,
            concelho=_CONCELHO,
            distrito=_DISTRITO,
            freguesia="São Sebastião",
            titular_tipo="singular",
            titular_nome=_TITULAR,
            nif=_NIF,
            email=_EMAIL_TITULAR,
            telefone=_TELEFONE,
            telemovel=_TELEMOVEL,
            hash_campos="h1",
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def enviados(monkeypatch):
    """Injeta um enviador FALSO no seam `envio.obter_enviador` (LIVE-GATED — sem rede)."""
    capturados: list[dict] = []

    def _fake(**kw):
        capturados.append(kw)
        return SimpleNamespace(id="email_test_1")

    monkeypatch.setattr(envio, "obter_enviador", lambda: _fake)
    return capturados


@pytest.fixture()
def client(bd):
    from app.web.app import criar_app

    return TestClient(criar_app())


def _leads() -> list[models.Lead]:
    with db.get_session() as s:
        return s.query(models.Lead).all()


def _optouts() -> list[str]:
    with db.get_session() as s:
        return [o.email for o in s.query(models.OptOut).all()]


# ==========================================================================
#  A jornada completa, num único fluxo (a ordem importa)
# ==========================================================================
def test_jornada_consent_first_ponta_a_ponta(client, enviados):
    # 1) Landing consent-first: 200 HTML com o widget e o funil ligados.
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    home = r.text
    assert "CheckAL" in home
    assert "/api/verificar" in home          # o widget consulta a vista pública
    assert "/inscrever" in home              # o form consent-first faz POST aqui

    # 2) Verificação pública do AL semeado: só dados do estabelecimento.
    r = client.get("/api/verificar", params={"q": str(_NR)})
    assert r.status_code == 200
    vv = r.json()
    assert vv["encontrado"] is True
    assert vv["nr_registo"] == _NR
    assert vv["nome_alojamento"] == _NOME_AL
    assert vv["estado"] == "ativo"
    # a vista pública NUNCA devolve contactos do titular
    for sensivel in (_NIF, _EMAIL_TITULAR, _TITULAR, _TELEFONE, _TELEMOVEL):
        assert sensivel not in r.text

    # 3) Inscrição consent-first: grava o Lead + a PROVA e dispara o double opt-in.
    r = client.post(
        "/inscrever",
        data={
            "email": _LEAD_EMAIL,
            "consentimento": "on",
            "nr_registo": str(_NR),
            "concelho": _CONCELHO,
        },
        headers={"X-Forwarded-For": "203.0.113.7"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/obrigado"

    leads = _leads()
    assert len(leads) == 1
    lead = leads[0]
    assert lead.email == _LEAD_EMAIL
    assert lead.estado == "pendente"
    assert lead.nr_registo == _NR
    assert lead.concelho == _CONCELHO
    # a PROVA de consentimento (RGPD art. 7/1): texto+versão, quando e de onde
    assert lead.consentimento_texto_versao
    assert lead.consentimento_em is not None
    assert lead.ip == "203.0.113.7"
    assert lead.token_confirmacao

    # double opt-in disparado (mock) — um envio com a ligação /confirmar?token=
    assert len(enviados) == 1
    assert enviados[0]["para"] == _LEAD_EMAIL
    assert f"/confirmar?token={lead.token_confirmacao}" in enviados[0]["html"]

    # /obrigado é servido (double opt-in pendente)
    r = client.get("/obrigado")
    assert r.status_code == 200
    assert "confirma" in r.text.lower()

    # 4) Confirmação (double opt-in): ativa o Lead.
    token = lead.token_confirmacao
    r = client.get("/confirmar", params={"token": token})
    assert r.status_code == 200
    assert _leads()[0].estado == "confirmado"

    # 5) Opt-out de 1 clique: grava a supressão e marca o Lead 'removido'.
    r = client.get("/remover", params={"e": _LEAD_EMAIL})
    assert r.status_code == 200
    assert any(p in r.text.lower() for p in ("removido", "removemos", "fora da lista"))
    assert _optouts() == [_LEAD_EMAIL]
    assert _leads()[0].estado == "removido"

    # o loop de compliance fecha: o email gravado exclui o contacto no núcleo
    from app.compliance import optout
    assert optout.deve_excluir(_LEAD_EMAIL, lista_dgc=[], log_optout=_optouts())


# ==========================================================================
#  Selo público — 200 e ZERO PII do titular (fronteira RGPD reforçada no wire)
# ==========================================================================
def test_selo_publico_200_sem_pii(client):
    r = client.get(f"/selo/{_NR}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # a página afirma o selo e a monitorização, com dados PÚBLICOS do estabelecimento
    assert "AL Verificado" in corpo
    assert "AL Monitorizado" in corpo
    assert _NOME_AL in corpo
    assert _CONCELHO in corpo
    assert str(_NR) in corpo
    # usa o selo da marca (SVG) e o chrome do site (estende base.html)
    assert "<svg" in corpo
    assert "/static/brand.css" in corpo
    # ZERO PII do titular — nem chave nem valor
    for sensivel in (_NIF, _EMAIL_TITULAR, _TITULAR, _TELEFONE, _TELEMOVEL):
        assert sensivel not in corpo, f"PII do titular vazou no selo público: {sensivel}"


def test_selo_publico_desaparecido_nunca_mostra_coral(bd, monkeypatch):
    """Um AL que saiu do RNAL usa o selo SUSPENSO (cinza) — nunca o coral 🔴 (SPEC)."""
    from datetime import datetime, timezone

    from app.web.app import criar_app
    from app.web import marca

    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=200500,
            nome_alojamento="Vivenda Mar",
            concelho="Porto",
            desaparecido_em=datetime(2026, 6, 1, tzinfo=timezone.utc),
            hash_campos="h2",
        ))
    c = TestClient(criar_app())
    r = c.get("/selo/200500")
    assert r.status_code == 200
    assert "AL Monitorizado" in r.text
    # o coral (🔴) NUNCA aparece no selo público
    assert marca.COR_CORAL not in r.text


def test_selo_publico_inexistente_404(client):
    assert client.get("/selo/99999999").status_code == 404


# ==========================================================================
#  Composição — todos os routers do WF1 estão montados por criar_app
# ==========================================================================
def test_criar_app_monta_todos_os_routers():
    from app.web.app import criar_app

    caminhos = {getattr(r, "path", None) for r in criar_app().routes}
    for esperado in (
        "/", "/saude", "/api/verificar", "/webhooks/stripe",
        "/precos", "/privacidade", "/termos", "/obrigado",
        "/inscrever", "/confirmar", "/remover", "/selo/{nr_registo}",
    ):
        assert esperado in caminhos, f"router em falta na composição do WF1: {esperado}"
