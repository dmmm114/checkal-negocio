"""Teste de ACEITAÇÃO ponta-a-ponta do FDS 2 (SPEC-FDS2.md §critério de "feito").

Exercita a app REAL (`app.web.app.criar_app`) através do `TestClient`, do webhook até
à BD, provando o critério canónico do AUTOMACAO.md §7: *"consigo pagar-me a mim próprio,
ficar registado como cliente E receber fatura-recibo certificada"*. Percurso:

  1. Semeia um registo do espelho RNAL (nr 100031, Faro).
  2. Compõe a app com os três routers (`criar_app`) e um `TestClient`.
  3. Injeta um emissor falso (`_FakeEmissor`) via `webhook_stripe._emissor`
     — devolve uma fatura com ATCUD + saft_hash + total corretos (certificada).
  4. Entrega um `checkout.session.completed` **ASSINADO** (assinatura gerada aqui com
     o segredo de teste, HMAC-SHA256 nativo — nunca o SDK) → 200. Verifica:
        · 1 `clientes` + 1 `clientes_registos` (match por nr_registo);
        · a fatura ficou certificada e o ATCUD foi **guardado** no cliente.
  5. Reentrega o MESMO evento (mesmo `event.id`) → **não duplica** (idempotência por
     event.id no webhook + por stripe_session_id no fulfillment): continua 1 cliente e
     1 emissão de fatura.
  6. Entrega um `invoice.paid` (`billing_reason=subscription_cycle`) para o mesmo
     `customer` → emite a **2.ª** fatura-recibo (renovação).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — o `_FakeEmissor` é um
emissor agnóstico injetado (devolve a `FaturaRecibo` sem HTTP nem fornecedor); a assinatura
Stripe é gerada localmente; nada de emails, nada de cold. Escrito como critério de aceitação
do FDS 2 (TDD de integração).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

SEGREDO = "whsec_teste_e2e_fds2_ABC123"


# ==========================================================================
#  Assinatura Stripe do lado do TESTE (HMAC-SHA256 nativo — igual ao adaptador)
# ==========================================================================
def _assinar(corpo: bytes, segredo: str = SEGREDO, *, t: int | None = None) -> str:
    """Constrói um header `Stripe-Signature` (`t=...,v1=...`) para `corpo` (bytes)."""
    if t is None:
        t = int(time.time())
    assinado = f"{t}.".encode("utf-8") + corpo
    v1 = hmac.new(segredo.encode("utf-8"), assinado, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def _evento(tipo: str, event_id: str, obj: dict) -> bytes:
    """Corpo bruto de um evento Stripe (`data.object` = `obj`), como chega no request."""
    return json.dumps(
        {"id": event_id, "type": tipo, "data": {"object": obj}},
        separators=(",", ":"),
    ).encode("utf-8")


def _post(client: TestClient, corpo: bytes, header: str):
    """POST cru ao webhook (corpo byte-a-byte + header de assinatura)."""
    return client.post(
        "/webhooks/stripe",
        content=corpo,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )


# ==========================================================================
#  Emissor falso agnóstico (devolve a FaturaRecibo, sem rede)
# ==========================================================================
class _FakeEmissor:
    """Emissor falso: uma `FaturaRecibo` distinta por chamada (sem HTTP nem fornecedor).

    Cada emissão recebe um `doc_id`/ATCUD sequencial, para se poder distinguir a 1.ª
    fatura (checkout) da 2.ª (renovação). `emissoes` conta as faturas emitidas — o
    critério de idempotência (não reemitir) verifica-se por aqui.
    """

    def __init__(self, total: float = 49.0):
        self.total = total
        self._seq = 0
        self.emissoes = 0

    def __call__(self, *, nome, nif, email, itens, codigo_cliente=None, dormir=None):
        from app.faturacao.base import FaturaRecibo
        self._seq += 1
        self.emissoes += 1
        doc_id = 900000 + self._seq
        return FaturaRecibo(
            id=str(doc_id),
            sequence_number=f"{self._seq}/CKL",
            atcud=f"ATCUD{self._seq:04d}-{self._seq}",
            saft_hash="deadbeef",
            total=self.total,
            permalink=f"https://cosmicoasis.app.invoicexpress.com/i/{doc_id}",
            pdf_url=f"https://ix/pdf/{doc_id}.pdf",
            estado="finalizado",
        )


# ==========================================================================
#  Fixtures: BD SQLite temporária semeada + segredo + app composta + FakeIX
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e.db'}"
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


@pytest.fixture()
def segredo(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SEGREDO, raising=False)


@pytest.fixture()
def ix(monkeypatch):
    """Injeta um `_FakeEmissor` partilhado no webhook (o mesmo em todos os despachos)."""
    from app.web import webhook_stripe
    fake = _FakeEmissor(total=49.0)
    monkeypatch.setattr(webhook_stripe, "_emissor", lambda: fake)
    return fake


@pytest.fixture()
def client(bd, segredo, ix):
    from app.web.app import criar_app
    return TestClient(criar_app())


# ==========================================================================
#  Fábricas de objetos Stripe
# ==========================================================================
def _sessao_checkout(session_id="cs_e2e", customer="cus_e2e", plano="anual") -> dict:
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "subscription",
        "payment_status": "paid",
        "amount_total": 4900,
        "currency": "eur",
        "customer": customer,
        "subscription": "sub_e2e",
        "metadata": {"plano": plano},
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


def _invoice_renovacao(customer="cus_e2e", invoice_id="in_ren_e2e") -> dict:
    return {
        "id": invoice_id,
        "object": "invoice",
        "billing_reason": "subscription_cycle",
        "customer": customer,
        "subscription": "sub_e2e",
        "attempt_count": 1,
    }


# ==========================================================================
#  ACEITAÇÃO FDS 2 — pago → cliente registado → fatura-recibo certificada
# ==========================================================================
def test_aceitacao_fds2_checkout_idempotencia_e_renovacao(client, ix):
    # ---- 1) checkout ASSINADO: pago → cliente + associação + fatura certificada ----
    corpo_co = _evento("checkout.session.completed", "evt_e2e_checkout", _sessao_checkout())
    r1 = _post(client, corpo_co, _assinar(corpo_co))
    assert r1.status_code == 200
    assert r1.json().get("tipo") == "checkout.session.completed"

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        c = s.query(models.Cliente).filter_by(stripe_session_id="cs_e2e").one()
        assert c.email == "cliente@exemplo.pt"
        assert c.nif == "508000000"
        assert c.plano == "anual"
        assert c.estado == "ativo"
        # fatura-recibo CERTIFICADA — o ATCUD ficou GUARDADO (critério de aceitação)
        assert c.ix_atcud == "ATCUD0001-1"
        assert c.ix_fatura_id == "900001"
        assert c.ix_permalink.endswith("/i/900001")
        # 1 associação cliente ↔ registo (match por nr_registo)
        assoc = s.query(models.ClienteRegisto).filter_by(cliente_id=c.id).all()
        assert len(assoc) == 1
        assert assoc[0].nr_registo == 100031
    assert ix.emissoes == 1  # exatamente uma fatura emitida

    # ---- 2) reentrega do MESMO evento → NÃO duplica (idempotência) ----
    r_dup = _post(client, corpo_co, _assinar(corpo_co))
    assert r_dup.status_code == 200
    assert r_dup.json().get("duplicado") is True
    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.ClienteRegisto).count() == 1
    assert ix.emissoes == 1  # nenhuma fatura adicional

    # ---- 3) renovação (invoice.paid, subscription_cycle) → 2.ª fatura ----
    corpo_ren = _evento("invoice.paid", "evt_e2e_ren", _invoice_renovacao())
    r_ren = _post(client, corpo_ren, _assinar(corpo_ren))
    assert r_ren.status_code == 200
    assert r_ren.json().get("tipo") == "invoice.paid"
    assert ix.emissoes == 2  # a 2.ª fatura-recibo foi emitida

    with db.get_session() as s:
        # continua a haver UM cliente; a ligação de fatura aponta para a mais recente
        assert s.query(models.Cliente).count() == 1
        c = s.query(models.Cliente).filter_by(stripe_customer_id="cus_e2e").one()
        assert c.estado == "ativo"
        assert c.ix_fatura_id == "900002"
        assert c.ix_atcud == "ATCUD0002-2"
