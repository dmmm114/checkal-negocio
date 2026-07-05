"""Testes da verificação pública consent-first — app.web.verificar (SPEC-FDS2.md §verificar).

Garante o contrato do widget:
  - hit por nº de registo (tolera o sufixo "/AL");
  - hit por nome, case-insensitive;
  - estado derivado (`ativo` vs `desaparecido`);
  - miss devolve `encontrado=False` (nunca 404);
  - CONSENT-FIRST: nenhum campo de titular (NIF, email, telefone, nome do titular)
    sai no JSON — nem como chave nem como valor.

Isolamento igual ao test_models.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; a app FastAPI é montada só com o router em teste e
exercida com `fastapi.testclient.TestClient`. SEM rede, SEM I/O externo.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models

# Valores sensíveis do titular — NUNCA devem aparecer na resposta pública.
_NIF = "513029591"
_EMAIL_TITULAR = "geral@sul.pt"
_TITULAR = "Alojamentos Sul, Lda"
_TELEFONE = "289000000"
_TELEMOVEL = "910000000"


# --------------------------------------------------------------------------
#  Fixtures: BD SQLite temporária semeada + TestClient com só o router em teste
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_verificar.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        # AL ativo, com TODOS os campos de titular preenchidos (para provar que não vazam)
        s.add(models.Registo(
            nr_registo=100031,
            data_registo=date(2019, 7, 16),
            nome_alojamento="Casa do Sol",
            concelho="Faro",
            distrito="Faro",
            titular_tipo="coletiva",
            titular_nome=_TITULAR,
            nif=_NIF,
            email=_EMAIL_TITULAR,
            telefone=_TELEFONE,
            telemovel=_TELEMOVEL,
            hash_campos="h1",
        ))
        # AL desaparecido (desaparecido_em preenchido)
        s.add(models.Registo(
            nr_registo=200500,
            data_registo=date(2020, 1, 2),
            nome_alojamento="Vivenda Mar",
            concelho="Porto",
            desaparecido_em=datetime(2026, 6, 1, tzinfo=timezone.utc),
            hash_campos="h2",
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def client(bd):
    from app.web import verificar
    app = FastAPI()
    app.include_router(verificar.router)
    return TestClient(app)


# --------------------------------------------------------------------------
#  Hits: por nº de registo e por nome
# --------------------------------------------------------------------------
def test_hit_por_nr(client):
    r = client.get("/api/verificar", params={"q": "100031"})
    assert r.status_code == 200
    dados = r.json()
    assert dados["encontrado"] is True
    assert dados["nr_registo"] == 100031
    assert dados["nome_alojamento"] == "Casa do Sol"
    assert dados["concelho"] == "Faro"
    assert dados["estado"] == "ativo"
    assert dados["data_registo"] == "2019-07-16"


def test_hit_por_nr_com_sufixo_al(client):
    # o utilizador copia "100031/AL" tal como aparece no RNAL
    r = client.get("/api/verificar", params={"q": "100031/AL"})
    dados = r.json()
    assert dados["encontrado"] is True
    assert dados["nr_registo"] == 100031


def test_hit_por_nome_case_insensitive(client):
    r = client.get("/api/verificar", params={"q": "casa DO sol"})
    dados = r.json()
    assert dados["encontrado"] is True
    assert dados["nr_registo"] == 100031
    assert dados["estado"] == "ativo"


def test_estado_desaparecido(client):
    r = client.get("/api/verificar", params={"q": "200500"})
    dados = r.json()
    assert dados["encontrado"] is True
    assert dados["estado"] == "desaparecido"


# --------------------------------------------------------------------------
#  Misses
# --------------------------------------------------------------------------
def test_miss_devolve_nao_encontrado(client):
    r = client.get("/api/verificar", params={"q": "99999999"})
    assert r.status_code == 200
    dados = r.json()
    assert dados["encontrado"] is False
    assert dados["nr_registo"] is None
    assert dados["nome_alojamento"] is None


def test_q_vazio_nao_encontrado(client):
    r = client.get("/api/verificar", params={"q": "   "})
    assert r.status_code == 200
    assert r.json()["encontrado"] is False


# --------------------------------------------------------------------------
#  CONSENT-FIRST: nenhum dado de titular sai no JSON
# --------------------------------------------------------------------------
def test_nao_expoe_dados_do_titular(client):
    r = client.get("/api/verificar", params={"q": "100031"})
    dados = r.json()

    # nenhuma chave de titular na resposta
    for proibida in ("nif", "email", "telefone", "telemovel", "titular_nome", "titular_tipo"):
        assert proibida not in dados, f"chave proibida no JSON: {proibida}"

    # nenhum valor sensível no corpo bruto (nem sequer serializado por engano)
    corpo = r.text
    for sensivel in (_NIF, _EMAIL_TITULAR, _TITULAR, _TELEFONE, _TELEMOVEL):
        assert sensivel not in corpo, f"valor de titular vazou no corpo: {sensivel}"

    # a resposta é EXATAMENTE a lista branca de campos públicos
    assert set(dados) == {
        "encontrado", "nr_registo", "nome_alojamento", "concelho", "estado", "data_registo",
    }
