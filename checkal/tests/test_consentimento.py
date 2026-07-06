"""Testes do consent-first — app.web.consentimento (SPEC-FASE1-WEB §consentimento).

Garante o contrato do funil de inscrição consent-first, o coração RGPD da FASE 1:

  POST /inscrever:
    - só inscreve com email VÁLIDO **e** checkbox de consentimento marcada;
    - cria um Lead 'pendente' e **grava a PROVA** (texto+versão do consentimento,
      timestamp e IP de origem) — o registo de que o titular consentiu (art. 7/1 RGPD);
    - dispara o **double opt-in** pelo seam `envio.obter_enviador` (LIVE-GATED,
      injetado nos testes) — o email leva a ligação `/confirmar?token=`;
    - redireciona para `/obrigado` (303);
    - SEM checkbox / SEM email / email inválido → NÃO inscreve (nada gravado, nada enviado).

  GET /confirmar?token=:
    - ativa o Lead ('pendente' → 'confirmado') e mostra a página de confirmação;
    - token desconhecido → não rebenta (página de ligação inválida).

Isolamento igual ao test_verificar.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; a app FastAPI é montada só com o router em teste e
exercida com `fastapi.testclient.TestClient`. O enviador é um duplo — SEM rede.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.envio as envio
import app.models as models


# --------------------------------------------------------------------------
#  Fixtures: BD SQLite temporária + enviador falso + TestClient (só o router)
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_consent.db'}"
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
def enviados(monkeypatch):
    """Injeta um enviador FALSO no seam `envio.obter_enviador` e devolve a lista de envios.

    Sob modo de teste o seam real devolve `None` (LIVE-GATED) — aqui substituímo-lo
    por um *callable* que apenas captura os kwargs de cada envio (nada toca a rede).
    """
    capturados: list[dict] = []

    def _fake(**kw):
        capturados.append(kw)
        return SimpleNamespace(id="email_test_1")

    monkeypatch.setattr(envio, "obter_enviador", lambda: _fake)
    return capturados


@pytest.fixture()
def client(bd):
    from app.web import consentimento

    app = FastAPI()
    app.include_router(consentimento.router)
    return TestClient(app)


def _leads() -> list[models.Lead]:
    with db.get_session() as s:
        return s.query(models.Lead).all()


# --------------------------------------------------------------------------
#  POST /inscrever — grava a prova + dispara double opt-in
# --------------------------------------------------------------------------
def test_inscricao_grava_prova_e_dispara_double_opt_in(client, enviados):
    r = client.post(
        "/inscrever",
        data={
            "email": "dono@exemplo.pt",
            "consentimento": "on",
            "nr_registo": "100031",
            "concelho": "Faro",
        },
        headers={"X-Forwarded-For": "203.0.113.7"},
        follow_redirects=False,
    )
    # redireciona para /obrigado (303 See Other)
    assert r.status_code == 303
    assert r.headers["location"] == "/obrigado"

    # Lead 'pendente' com a PROVA de consentimento gravada
    leads = _leads()
    assert len(leads) == 1
    lead = leads[0]
    assert lead.email == "dono@exemplo.pt"
    assert lead.estado == "pendente"
    assert lead.nr_registo == 100031
    assert lead.concelho == "Faro"
    assert lead.consentimento_texto_versao  # texto+versão do consentimento gravados
    assert lead.consentimento_em is not None  # timestamp da prova
    assert lead.ip == "203.0.113.7"           # IP de origem (X-Forwarded-For)
    assert lead.token_confirmacao             # token do double opt-in

    # double opt-in disparado (um único envio, com a ligação de confirmação)
    assert len(enviados) == 1
    msg = enviados[0]
    assert msg["para"] == "dono@exemplo.pt"
    corpo = msg["html"]
    assert f"/confirmar?token={lead.token_confirmacao}" in corpo


def test_inscricao_tolera_sufixo_al_no_nr(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "on", "nr_registo": "100031/AL"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _leads()[0].nr_registo == 100031


def test_inscricao_sem_nr_nem_concelho_grava_none(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "sim"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    lead = _leads()[0]
    assert lead.nr_registo is None
    assert lead.concelho is None


def test_ip_cai_para_o_host_do_cliente_sem_forwarded_for(client, enviados):
    client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "on"},
        follow_redirects=False,
    )
    # sem X-Forwarded-For, o IP é o host do cliente (TestClient = 'testclient')
    assert _leads()[0].ip == "testclient"


# --------------------------------------------------------------------------
#  POST /inscrever — recusa sem consentimento / sem email / email inválido
# --------------------------------------------------------------------------
def test_sem_consentimento_nao_inscreve(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "a@b.pt"},  # checkbox ausente (não marcada)
        follow_redirects=False,
    )
    assert r.status_code == 400              # não redireciona para /obrigado
    assert _leads() == []                    # nada gravado
    assert enviados == []                    # nada enviado


def test_consentimento_vazio_nao_inscreve(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": ""},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert _leads() == []
    assert enviados == []


def test_sem_email_nao_inscreve(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "", "consentimento": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert _leads() == []
    assert enviados == []


def test_email_invalido_nao_inscreve(client, enviados):
    r = client.post(
        "/inscrever",
        data={"email": "isto-nao-e-email", "consentimento": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert _leads() == []
    assert enviados == []


# --------------------------------------------------------------------------
#  LIVE-GATED: sem enviador (seam devolve None) ainda grava o Lead
# --------------------------------------------------------------------------
def test_inscricao_sem_enviador_ainda_grava_lead(client, monkeypatch):
    # seam real devolve None sob modo de teste — o request não deve rebentar
    monkeypatch.setattr(envio, "obter_enviador", lambda: None)
    r = client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert len(_leads()) == 1
    assert _leads()[0].estado == "pendente"


# --------------------------------------------------------------------------
#  GET /confirmar?token= — ativa o Lead
# --------------------------------------------------------------------------
def test_confirmar_ativa_o_lead(client, enviados):
    client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "on"},
        follow_redirects=False,
    )
    token = _leads()[0].token_confirmacao

    r = client.get("/confirmar", params={"token": token})
    assert r.status_code == 200
    assert "confirmad" in r.text.lower()   # página de confirmação renderizada
    assert _leads()[0].estado == "confirmado"


def test_confirmar_e_idempotente(client, enviados):
    client.post(
        "/inscrever",
        data={"email": "a@b.pt", "consentimento": "on"},
        follow_redirects=False,
    )
    token = _leads()[0].token_confirmacao

    r1 = client.get("/confirmar", params={"token": token})
    r2 = client.get("/confirmar", params={"token": token})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert _leads()[0].estado == "confirmado"


def test_confirmar_token_desconhecido_nao_rebenta(client):
    r = client.get("/confirmar", params={"token": "token-que-nao-existe"})
    # não é uma exceção 500: página de ligação inválida
    assert r.status_code in (200, 404)
    assert "checkal" in r.text.lower()


def test_confirmar_sem_token_nao_rebenta(client):
    r = client.get("/confirmar")
    assert r.status_code in (200, 400, 404, 422)
