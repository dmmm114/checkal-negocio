"""Regressão de idempotência DURÁVEL do fulfillment (red-team FDS 2).

A idempotência por `stripe_session_id` não pode assentar só no query-then-insert de
`app.fulfillment.processar_checkout` (TOCTOU): com >1 worker uvicorn, a reentrega
rotineira do MESMO `checkout.session.completed` pela Stripe podia fazer dois processos
passarem a verificação e emitirem DOIS documentos fiscais certificados (ilegal de
reverter). Estes testes fixam o backstop:

  1. a coluna `clientes.stripe_session_id` é UNIQUE na BD (rejeita o 2.º INSERT);
  2. quando `processar_checkout` PERDE a corrida (a sessão foi materializada por outro
     worker entre a verificação e o `flush`), o `flush` rebenta ANTES da emissão e a
     função reconcilia-se devolvendo o cliente existente, idempotente e SEM reemitir
     uma 2.ª fatura.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. Zero rede: o emissor de faturas é um
`_FakeEmissor` injetado; se ele fosse chamado na corrida perdida, `emissoes > 0` denunciava.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.fulfillment as fulfillment
import app.models as models
from app.faturacao.base import FaturaRecibo


# ==========================================================================
#  Emissor falso agnóstico — se for chamado, conta uma emissão (delator)
# ==========================================================================
class _FakeEmissor:
    def __init__(self, doc_id: int = 700700, total: float = 49.0):
        self.doc_id = str(doc_id)
        self.total = total
        self.emissoes = 0

    def __call__(self, *, nome, nif, email, itens, codigo_cliente=None, dormir=None):
        self.emissoes += 1  # 1 chamada ao emissor == 1 emissão
        return FaturaRecibo(
            id=self.doc_id,
            sequence_number="9/CKL",
            atcud="ZZZZ0001-9",
            saft_hash="cafef00d",
            total=self.total,
            permalink=f"https://cosmicoasis.app.invoicexpress.com/i/{self.doc_id}",
            pdf_url=f"https://ix/pdf/{self.doc_id}.pdf",
            estado="finalizado",
        )


# ==========================================================================
#  Fixtures — BD SQLite isolada com um registo para o match por nr
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_idem.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=100031, data_registo=date(2019, 7, 16),
            nome_alojamento="Casa do Sol", concelho="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda",
            nif="513029591", hash_campos="h1",
        ))
    try:
        yield
    finally:
        eng.dispose()


def _sessao(session_id="cs_race"):
    return {
        "id": session_id,
        "mode": "subscription",
        "amount_total": 4900,
        "customer": "cus_race",
        "metadata": {"plano": "anual"},
        "custom_fields": [
            {"key": "nif", "type": "text", "text": {"value": "508000000"}},
            {"key": "nr_registo_al", "type": "text", "text": {"value": "100031"}},
        ],
        "customer_details": {
            "email": "cliente@exemplo.pt",
            "name": "Alojamentos Sul, Lda",
            "address": {"city": "Faro", "country": "PT"},
        },
    }


# ==========================================================================
#  (1) A UNIQUE é o backstop durável — a BD rejeita a 2.ª sessão igual
# ==========================================================================
def test_stripe_session_id_e_unico_na_bd(bd):
    with db.get_session() as s:
        s.add(models.Cliente(
            email="a@ex.pt", plano="anual", estado="ativo", stripe_session_id="cs_dup",
        ))
    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(models.Cliente(
                email="b@ex.pt", plano="anual", estado="ativo", stripe_session_id="cs_dup",
            ))


def test_multiplos_clientes_sem_sessao_coexistem(bd):
    # NULLs são distintos sob UNIQUE (SQLite/Postgres) — clientes sem checkout coexistem.
    with db.get_session() as s:
        s.add(models.Cliente(email="x@ex.pt", plano="anual", estado="ativo"))
        s.add(models.Cliente(email="y@ex.pt", plano="anual", estado="ativo"))
    with db.get_session() as s:
        assert s.query(models.Cliente).filter(
            models.Cliente.stripe_session_id.is_(None)
        ).count() == 2


# ==========================================================================
#  (2) Corrida PERDIDA — flush rebenta ANTES da emissão → idempotente, 0 faturas
# ==========================================================================
def test_processar_checkout_corrida_perdida_nao_reemite(bd, monkeypatch):
    # Simula o outro worker: a sessão JÁ está materializada na BD (com fatura própria)...
    with db.get_session() as s:
        s.add(models.Cliente(
            email="vencedor@ex.pt", nome="Alojamentos Sul, Lda", nif="508000000",
            plano="anual", estado="ativo", stripe_customer_id="cus_race",
            criado_em=datetime.now(timezone.utc), stripe_session_id="cs_race",
            ix_fatura_id="700700", ix_atcud="ZZZZ0001-9",
        ))

    # ...mas forçamos a VERIFICAÇÃO inicial (0) a não a ver (TOCTOU), para exercitar o
    # caminho de INSERT que colide na UNIQUE. A reconciliação (2.ª leitura) usa o real.
    real = fulfillment._cliente_por_sessao
    estado = {"n": 0}

    def _cego_na_primeira(s, session_id):
        estado["n"] += 1
        return None if estado["n"] == 1 else real(s, session_id)

    monkeypatch.setattr(fulfillment, "_cliente_por_sessao", _cego_na_primeira)

    ix = _FakeEmissor()
    res = fulfillment.processar_checkout(_sessao("cs_race"), emitir_fatura=ix, dormir=lambda _s: None)

    # Reconciliou-se com o cliente do vencedor, sem reemitir nada.
    assert res.idempotente is True
    assert res.fatura is None
    assert ix.emissoes == 0, "corrida perdida NUNCA pode emitir uma 2.ª fatura certificada"

    with db.get_session() as s:
        assert s.query(models.Cliente).filter_by(stripe_session_id="cs_race").count() == 1


def test_processar_checkout_reentrega_normal_continua_idempotente(bd):
    # Guarda o caminho feliz da idempotência (verificação inicial vê o cliente): 1 emissão.
    ix = _FakeEmissor()
    r1 = fulfillment.processar_checkout(_sessao("cs_norm"), emitir_fatura=ix, dormir=lambda _s: None)
    r2 = fulfillment.processar_checkout(_sessao("cs_norm"), emitir_fatura=ix, dormir=lambda _s: None)
    assert r1.idempotente is False and r2.idempotente is True
    assert r2.fatura is None
    assert ix.emissoes == 1
    with db.get_session() as s:
        assert s.query(models.Cliente).filter_by(stripe_session_id="cs_norm").count() == 1
