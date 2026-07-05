"""Testes do webhook único da Stripe — app.web.webhook_stripe (SPEC-FDS2.md §webhook_stripe).

Contrato do endpoint `POST /webhooks/stripe`:

  - lê o corpo **BRUTO** (bytes) → `verificar_evento` (assinatura sobre os bytes);
  - assinatura inválida/ausente/adulterada → **400** (sem despachar nada);
  - **idempotência por `event.id`** (tabela `webhook_eventos`): reentrega do mesmo
    evento → 200 sem reprocessar;
  - despacha por `type` para a ação de fulfillment certa:
      · `checkout.session.completed`   → `processar_checkout(obj, emitir_fatura=...)`
      · `invoice.paid`                 → `processar_renovacao(obj, emitir_fatura=...)`
      · `invoice.payment_failed`       → `registar_falha_pagamento(obj)`
      · `customer.subscription.deleted`→ `marcar_cancelado(obj)`
  - evento não-tratado → **200** (ignora), sem despachar.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. Zero rede. As ações de
fulfillment são substituídas por espiões (monkeypatch em `app.fulfillment`), pelo
que o emissor de faturas nunca é usado; o único teste ponta-a-ponta injeta um
emissor falso (um *callable* que devolve uma `FaturaRecibo`) via
`webhook_stripe._emissor`. A assinatura VÁLIDA é gerada aqui nos testes com o mesmo
HMAC-SHA256 nativo do adaptador (nunca com o SDK). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

SEGREDO = "whsec_teste_webhook_XYZ789"


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


def _post(client: TestClient, corpo: bytes, header: str | None):
    """POST cru ao webhook (corpo byte-a-byte + header de assinatura)."""
    headers = {"Content-Type": "application/json"}
    if header is not None:
        headers["Stripe-Signature"] = header
    return client.post("/webhooks/stripe", content=corpo, headers=headers)


# ==========================================================================
#  Fixtures: BD SQLite temporária + segredo + TestClient só com o webhook
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_webhook.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        # registo p/ o teste ponta-a-ponta (match por nr_registo)
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
    """Fixa o segredo de webhook que `verificar_evento` lê por omissão de config."""
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SEGREDO, raising=False)


@pytest.fixture()
def client(bd, segredo):
    from app.web import webhook_stripe
    app = FastAPI()
    app.include_router(webhook_stripe.router)
    return TestClient(app)


@pytest.fixture()
def spies(monkeypatch):
    """Substitui as 4 ações de fulfillment por espiões; devolve os registos de chamada."""
    import app.fulfillment as fulfillment

    chamadas: dict[str, list] = {"checkout": [], "renovacao": [], "falha": [], "cancelado": []}

    def _mk(nome: str):
        def spy(obj, **kw):
            chamadas[nome].append({"obj": obj, "kw": kw})
            return None
        return spy

    monkeypatch.setattr(fulfillment, "processar_checkout", _mk("checkout"))
    monkeypatch.setattr(fulfillment, "processar_renovacao", _mk("renovacao"))
    monkeypatch.setattr(fulfillment, "registar_falha_pagamento", _mk("falha"))
    monkeypatch.setattr(fulfillment, "marcar_cancelado", _mk("cancelado"))
    return chamadas


# ==========================================================================
#  Despacho: cada um dos 4 eventos vai à ação certa
# ==========================================================================
def test_checkout_despacha_processar_checkout(client, spies):
    corpo = _evento("checkout.session.completed", "evt_co", {"id": "cs_1", "mode": "subscription"})
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200
    assert len(spies["checkout"]) == 1
    assert spies["checkout"][0]["obj"]["id"] == "cs_1"
    # o webhook injeta o emissor de faturas (None em modo de teste) — o kwarg tem de existir
    assert "emitir_fatura" in spies["checkout"][0]["kw"]
    # nenhuma outra ação foi tocada
    assert spies["renovacao"] == spies["falha"] == spies["cancelado"] == []


def test_invoice_paid_despacha_processar_renovacao(client, spies):
    corpo = _evento("invoice.paid", "evt_ren", {"id": "in_1", "billing_reason": "subscription_cycle"})
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200
    assert len(spies["renovacao"]) == 1
    assert spies["renovacao"][0]["obj"]["id"] == "in_1"
    assert "emitir_fatura" in spies["renovacao"][0]["kw"]


def test_payment_failed_despacha_registar_falha(client, spies):
    corpo = _evento("invoice.payment_failed", "evt_fail", {"id": "in_2", "customer": "cus_1"})
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200
    assert len(spies["falha"]) == 1
    assert spies["falha"][0]["obj"]["id"] == "in_2"
    # esta ação não recebe emitir_fatura (não emite fatura)
    assert spies["falha"][0]["kw"] == {}


def test_subscription_deleted_despacha_marcar_cancelado(client, spies):
    corpo = _evento("customer.subscription.deleted", "evt_del", {"id": "sub_1", "customer": "cus_1"})
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200
    assert len(spies["cancelado"]) == 1
    assert spies["cancelado"][0]["obj"]["id"] == "sub_1"
    assert spies["cancelado"][0]["kw"] == {}


# ==========================================================================
#  Idempotência por event.id — reentrega não reprocessa
# ==========================================================================
def test_reentrega_mesmo_event_id_nao_reprocessa(client, spies):
    corpo = _evento("checkout.session.completed", "evt_dup", {"id": "cs_dup"})
    header = _assinar(corpo)

    r1 = _post(client, corpo, header)
    r2 = _post(client, corpo, header)

    assert r1.status_code == 200
    assert r2.status_code == 200
    # despachado UMA só vez, apesar das duas entregas
    assert len(spies["checkout"]) == 1
    # a 2.ª entrega é reconhecida como duplicado
    assert r2.json().get("duplicado") is True


def test_event_id_e_gravado_em_webhook_eventos(client, spies):
    corpo = _evento("checkout.session.completed", "evt_grava", {"id": "cs_g"})
    _post(client, corpo, _assinar(corpo))
    with db.get_session() as s:
        row = s.get(models.WebhookEvento, "evt_grava")
        assert row is not None
        assert row.tipo == "checkout.session.completed"
        assert row.recebido_em is not None


# ==========================================================================
#  Assinatura inválida / corpo bruto → 400 (sem despachar)
# ==========================================================================
def test_assinatura_invalida_400(client, spies):
    corpo = _evento("checkout.session.completed", "evt_bad", {"id": "cs_x"})
    header = _assinar(corpo, "whsec_OUTRO_segredo")  # segredo errado
    r = _post(client, corpo, header)
    assert r.status_code == 400
    assert spies["checkout"] == []


def test_sem_header_de_assinatura_400(client, spies):
    corpo = _evento("checkout.session.completed", "evt_nohdr", {"id": "cs_x"})
    r = _post(client, corpo, None)  # sem Stripe-Signature
    assert r.status_code == 400
    assert spies["checkout"] == []


def test_corpo_adulterado_apos_assinar_400(client, spies):
    corpo = _evento("checkout.session.completed", "evt_tamper", {"id": "cs_ok"})
    header = _assinar(corpo)
    adulterado = corpo.replace(b"cs_ok", b"cs_ATACANTE")  # muda os bytes → assinatura falha
    r = _post(client, adulterado, header)
    assert r.status_code == 400
    assert spies["checkout"] == []


def test_timestamp_fora_da_tolerancia_400(client, spies):
    corpo = _evento("checkout.session.completed", "evt_velho", {"id": "cs_ok"})
    header = _assinar(corpo, t=int(time.time()) - 600)  # 10 min no passado (> 5 min)
    r = _post(client, corpo, header)
    assert r.status_code == 400
    assert spies["checkout"] == []


# ==========================================================================
#  Evento não-tratado → 200 (ignora), sem despachar
# ==========================================================================
def test_evento_nao_tratado_200_e_nao_despacha(client, spies):
    corpo = _evento("payment_intent.succeeded", "evt_pi", {"id": "pi_1"})
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200
    assert spies["checkout"] == spies["renovacao"] == spies["falha"] == spies["cancelado"] == []


# ==========================================================================
#  Ponta-a-ponta: checkout real → cliente + fatura (emissor falso injetado)
# ==========================================================================
class _FakeEmissor:
    """Emissor falso (callable agnóstico) — devolve uma `FaturaRecibo` certificada."""

    def __init__(self, doc_id: int = 424242, total: float = 49.0):
        self.doc_id = str(doc_id)
        self.total = total

    def __call__(self, *, nome, nif, email, itens, codigo_cliente=None, dormir=None):
        from app.faturacao.base import FaturaRecibo
        return FaturaRecibo(
            id=self.doc_id,
            sequence_number="7/CKL",
            atcud="WXYZ9876-7",
            saft_hash="deadbeef",
            total=self.total,
            permalink=f"https://cosmicoasis.app.invoicexpress.com/i/{self.doc_id}",
            pdf_url=f"https://ix/pdf/{self.doc_id}.pdf",
            estado="finalizado",
        )


def test_end_to_end_checkout_emite_fatura(client, monkeypatch):
    from app.web import webhook_stripe

    monkeypatch.setattr(webhook_stripe, "_emissor", lambda: _FakeEmissor())

    sessao = {
        "id": "cs_e2e",
        "mode": "subscription",
        "payment_status": "paid",
        "amount_total": 4900,
        "currency": "eur",
        "customer": "cus_e2e",
        "subscription": "sub_e2e",
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
    corpo = _evento("checkout.session.completed", "evt_e2e", sessao)
    r = _post(client, corpo, _assinar(corpo))
    assert r.status_code == 200

    with db.get_session() as s:
        c = s.query(models.Cliente).filter_by(stripe_session_id="cs_e2e").one()
        assert c.email == "cliente@exemplo.pt"
        assert c.nif == "508000000"
        assert c.estado == "ativo"
        assert c.ix_atcud == "WXYZ9876-7"
        assert c.ix_fatura_id == "424242"
        # associação cliente↔registo criada pelo match por nr_registo
        assoc = s.query(models.ClienteRegisto).filter_by(cliente_id=c.id).all()
        assert len(assoc) == 1
        assert assoc[0].nr_registo == 100031
