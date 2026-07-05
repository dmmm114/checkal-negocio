"""Testes FDS 2 do esquema ORM — extensões *aditivas* a app.models (SPEC-FDS2.md §models).

Cobre o contrato aditivo do FDS 2, sem quebrar o FDS 1:
  - tabela `webhook_eventos` (idempotência de webhooks Stripe por `event.id`);
  - colunas novas em `clientes`: stripe_session_id, ix_fatura_id, ix_atcud, ix_permalink;
  - idempotência: a reentrega do mesmo `event.id` (PK duplicada) é rejeitada;
  - config: flags/mapas FDS 2 (modo de teste, nome da taxa IVA, mapas Stripe).

Isolamento igual ao test_models.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`. SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models


# --------------------------------------------------------------------------
#  Fixture: BD SQLite temporária, isolada, com o esquema criado
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_fds2.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


# --------------------------------------------------------------------------
#  webhook_eventos — nova tabela + idempotência por event_id (PK)
# --------------------------------------------------------------------------
def test_init_db_cria_tabela_webhook_eventos(bd):
    nomes = set(inspect(db.engine).get_table_names())
    assert "webhook_eventos" in nomes
    # as tabelas do FDS 1 continuam presentes (regressão)
    assert {"registos", "clientes", "clientes_registos"} <= nomes


def test_webhook_eventos_na_metadata(bd):
    assert "webhook_eventos" in db.Base.metadata.tables


def test_insere_e_le_webhook_evento(bd):
    with db.get_session() as s:
        s.add(
            models.WebhookEvento(
                event_id="evt_1",
                tipo="checkout.session.completed",
                recebido_em=datetime(2026, 7, 5, 15, 0, tzinfo=timezone.utc),
            )
        )

    with db.get_session() as s:
        ev = s.get(models.WebhookEvento, "evt_1")
        assert ev is not None
        assert ev.event_id == "evt_1"
        assert ev.tipo == "checkout.session.completed"


def test_event_id_duplicado_e_rejeitado(bd):
    # 1.ª entrega grava o event.id
    with db.get_session() as s:
        s.add(models.WebhookEvento(event_id="evt_dup", tipo="invoice.paid"))

    # reentrega do MESMO event.id → PK duplicada rejeitada (garantia de idempotência)
    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(models.WebhookEvento(event_id="evt_dup", tipo="invoice.paid"))

    # continua a existir uma única linha
    with db.get_session() as s:
        assert s.query(models.WebhookEvento).count() == 1


# --------------------------------------------------------------------------
#  clientes — colunas aditivas de ligação Stripe/InvoiceXpress
# --------------------------------------------------------------------------
def test_clientes_tem_colunas_fds2(bd):
    cols = {c["name"] for c in inspect(db.engine).get_columns("clientes")}
    assert {"stripe_session_id", "ix_fatura_id", "ix_atcud", "ix_permalink"} <= cols
    # colunas do FDS 1 intactas
    assert {"email", "nif", "stripe_customer_id", "plano", "estado"} <= cols


def test_cliente_persiste_campos_faturacao(bd):
    with db.get_session() as s:
        s.add(
            models.Cliente(
                email="dono@ex.pt",
                plano="anual",
                estado="ativo",
                stripe_session_id="cs_test_abc",
                ix_fatura_id="998877",
                ix_atcud="ABCD1234-6",
                ix_permalink="https://cosmicoasis.app.invoicexpress.com/i/xyz",
            )
        )

    with db.get_session() as s:
        c = s.query(models.Cliente).one()
        assert c.stripe_session_id == "cs_test_abc"
        assert c.ix_fatura_id == "998877"
        assert c.ix_atcud == "ABCD1234-6"
        assert c.ix_permalink.endswith("/i/xyz")
        # colunas do FDS 1 continuam a funcionar
        assert c.email == "dono@ex.pt"
        assert c.plano == "anual"


def test_cliente_campos_fds2_default_nulo(bd):
    # sem os passar, nascem NULL (aditivo, não obrigatório)
    with db.get_session() as s:
        s.add(models.Cliente(email="x@y.pt", plano="anual", estado="ativo"))

    with db.get_session() as s:
        c = s.query(models.Cliente).one()
        assert c.stripe_session_id is None
        assert c.ix_fatura_id is None
        assert c.ix_atcud is None
        assert c.ix_permalink is None


# --------------------------------------------------------------------------
#  config — extensão aditiva FDS 2
# --------------------------------------------------------------------------
def test_config_flags_fds2():
    assert config.CHECKAL_MODO_TESTE is True
    assert config.INVOICEXPRESS_TAXA_NOME == "IVA23"
    assert hasattr(config, "INVOICEXPRESS_SEQUENCE_ID")
    assert isinstance(config.STRIPE_PRICE_PLANO, dict)
    assert isinstance(config.STRIPE_PAYMENT_LINKS, dict)
