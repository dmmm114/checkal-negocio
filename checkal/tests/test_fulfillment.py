"""Testes do orquestrador de fulfillment (FDS 2) — app.fulfillment.

Contrato (SPEC-FDS2.md §fulfillment):

    processar_checkout(sessao, *, emitir_fatura) -> Resultado
      · lê NIF + nº de registo dos `custom_fields`, email de `customer_details`
      · faz match contra `registos` (por nr_registo; fallback fuzzy nome+concelho)
      · cria/atualiza `clientes` + `clientes_registos`
      · emite a fatura-recibo (via emissor agnóstico) e guarda ix_fatura_id/ix_atcud/ix_permalink
      · IDEMPOTENTE por `stripe_session_id` (repetir a sessão não duplica cliente nem fatura)

    processar_renovacao(invoice, *, emitir_fatura)  · G1: só `billing_reason=subscription_cycle`
    marcar_cancelado(subscription)                  · estado → 'cancelado'
    registar_falha_pagamento(invoice)               · estado → 'em_dunning' (dunning é FDS 5)

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede: o `emitir_fatura` é um
`FakeEmissor` injetado — um *callable* agnóstico que devolve uma `FaturaRecibo` certificada
sem tocar em HTTP nem no fornecedor. Nada de emails, nada de cold. O `dormir` do polling do
PDF é neutralizado. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.faturacao.base import FaturaRecibo


# ==========================================================================
#  Duplo de teste do emissor: FakeEmissor (callable agnóstico) — devolve uma
#  FaturaRecibo certificada sem HTTP, e conta as emissões.
# ==========================================================================
class FakeEmissor:
    """Emissor falso à laia de `app.faturacao.obter_emissor()`.

    Assinatura do contrato: `emitir(*, nome, nif, email, itens, codigo_cliente=None,
    dormir=...)`. Cada chamada conta uma emissão e devolve uma `FaturaRecibo` com
    `id`/`atcud`/`permalink` derivados de `doc_id` (para as asserções de ligação).
    """

    def __init__(self, *, doc_id=998877, total=49.0, atcud="ABCD1234-6"):
        self.doc_id = str(doc_id)
        self.total = total
        self.atcud = atcud
        self.emissoes = 0
        self.chamadas: list[dict] = []

    def __call__(self, *, nome, nif, email, itens, codigo_cliente=None, dormir=None):
        self.emissoes += 1
        self.chamadas.append({
            "nome": nome, "nif": nif, "email": email,
            "itens": itens, "codigo_cliente": codigo_cliente,
        })
        return FaturaRecibo(
            id=self.doc_id,
            sequence_number="6/CKL",
            atcud=self.atcud,
            saft_hash="a1b2c3d4e5",
            total=self.total,
            permalink=f"https://cosmicoasis.app.invoicexpress.com/i/{self.doc_id}",
            pdf_url=f"https://ix/pdf/{self.doc_id}.pdf",
            estado="finalized",
        )

    def n_emissoes(self) -> int:
        return self.emissoes


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada (igual ao test_models.py)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_fulfillment.db'}"
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
        s.add(models.Registo(
            nr_registo=555000, data_registo=date(2021, 3, 1),
            nome_alojamento="Vivenda da Praia", concelho="Lagos",
            titular_tipo="singular", titular_nome="Joana Martins Pereira",
            nif="219876543", hash_campos="h2",
        ))
    try:
        yield
    finally:
        eng.dispose()


# ==========================================================================
#  Fábricas de objetos Stripe (dicts como vêm de `event.data.object`)
# ==========================================================================
def _sessao(
    *, session_id="cs_test_1", nif="508000000", nr="100031",
    email="cliente@exemplo.pt", nome="Alojamentos Sul, Lda",
    concelho="Faro", plano="anual", customer="cus_1", mode="subscription",
    amount_total=4900,
):
    custom = []
    if nif is not None:
        custom.append({"key": "nif", "type": "text", "text": {"value": nif}})
    if nr is not None:
        custom.append({"key": "nr_registo_al", "type": "text", "text": {"value": nr}})
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": mode,
        "payment_status": "paid",
        "amount_total": amount_total,
        "currency": "eur",
        "customer": customer,
        "subscription": "sub_1" if mode == "subscription" else None,
        "metadata": {"plano": plano} if plano else {},
        "custom_fields": custom,
        "customer_details": {
            "email": email,
            "name": nome,
            "address": {"city": concelho, "country": "PT"},
        },
    }


def _invoice(*, billing_reason="subscription_cycle", customer="cus_1", invoice_id="in_1"):
    return {
        "id": invoice_id,
        "object": "invoice",
        "billing_reason": billing_reason,
        "customer": customer,
        "subscription": "sub_1",
        "attempt_count": 1,
    }


# ==========================================================================
#  processar_checkout — cria cliente + associação + fatura certificada
# ==========================================================================
def test_checkout_cria_cliente_associacao_e_fatura(bd):
    from app import fulfillment

    emissor = FakeEmissor(total=49.0)
    res = fulfillment.processar_checkout(_sessao(), emitir_fatura=emissor, dormir=lambda _s: None)

    assert res.accao == fulfillment.ACCAO_CHECKOUT
    assert res.idempotente is False
    assert res.fatura is not None
    assert res.correspondido is True
    assert res.nr_registo == 100031

    with db.get_session() as s:
        c = s.query(models.Cliente).one()
        assert c.email == "cliente@exemplo.pt"
        assert c.nif == "508000000"
        assert c.plano == "anual"
        assert c.estado == "ativo"
        assert c.stripe_session_id == "cs_test_1"
        assert c.stripe_customer_id == "cus_1"
        # ligação Stripe ↔ faturação persistida
        assert c.ix_fatura_id == "998877"
        assert c.ix_atcud == "ABCD1234-6"
        assert c.ix_permalink.endswith("/i/998877")
        # associação cliente ↔ registo criada
        assoc = s.query(models.ClienteRegisto).all()
        assert len(assoc) == 1
        assert assoc[0].cliente_id == c.id
        assert assoc[0].nr_registo == 100031

    # exatamente uma emissão de fatura
    assert emissor.n_emissoes() == 1
    # o código de cliente estável (evita duplicar clientes na conta) deriva do id local
    assert emissor.chamadas[0]["codigo_cliente"] == f"checkal-{res.cliente_id}"


def test_checkout_nif_vai_para_fatura(bd):
    from app import fulfillment

    emissor = FakeEmissor()
    fulfillment.processar_checkout(
        _sessao(nif="508000000"), emitir_fatura=emissor, dormir=lambda _s: None
    )

    chamada = emissor.chamadas[0]
    assert chamada["nif"] == "508000000"
    assert chamada["email"] == "cliente@exemplo.pt"
    # o item faturado corresponde ao plano anual (49,00 € IVA incl.)
    assert chamada["itens"][0]["preco"] == 49.0


def test_checkout_nr_com_sufixo_al(bd):
    from app import fulfillment
    res = fulfillment.processar_checkout(
        _sessao(nr="100031/AL"), emitir_fatura=FakeEmissor(), dormir=lambda _s: None
    )
    assert res.nr_registo == 100031
    assert res.correspondido is True


# ==========================================================================
#  Idempotência por stripe_session_id — repetir a sessão não duplica
# ==========================================================================
def test_checkout_idempotente_por_session_id(bd):
    from app import fulfillment
    emissor = FakeEmissor()
    sessao = _sessao(session_id="cs_test_dup")

    r1 = fulfillment.processar_checkout(sessao, emitir_fatura=emissor, dormir=lambda _s: None)
    r2 = fulfillment.processar_checkout(sessao, emitir_fatura=emissor, dormir=lambda _s: None)

    assert r1.idempotente is False
    assert r2.idempotente is True
    assert r2.cliente_id == r1.cliente_id
    assert r2.fatura is None  # não reemite

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.ClienteRegisto).count() == 1
    # a fatura foi emitida UMA só vez apesar das duas entregas
    assert emissor.n_emissoes() == 1


# ==========================================================================
#  Fallback fuzzy — sem match por nr, casa por nome + concelho
# ==========================================================================
def test_checkout_fallback_fuzzy_nome_concelho(bd):
    from app import fulfillment
    # nº inexistente força o fallback; nome+concelho batem no registo 555000
    sessao = _sessao(
        session_id="cs_fuzzy", nr="999999",
        nome="Joana Martins Pereira", concelho="Lagos",
        email="joana@ex.pt", customer="cus_z", plano="anual",
    )
    res = fulfillment.processar_checkout(sessao, emitir_fatura=FakeEmissor(), dormir=lambda _s: None)
    assert res.correspondido is True
    assert res.nr_registo == 555000

    with db.get_session() as s:
        assoc = s.query(models.ClienteRegisto).one()
        assert assoc.nr_registo == 555000


def test_checkout_sem_match_cria_cliente_sem_associacao(bd):
    from app import fulfillment
    # nem nr existente nem nome/concelho reconhecíveis → cliente na mesma, sem associação
    sessao = _sessao(
        session_id="cs_semmatch", nr="424242",
        nome="Empresa Totalmente Desconhecida XPTO", concelho="Bragança",
        email="novo@ex.pt", customer="cus_new",
    )
    res = fulfillment.processar_checkout(sessao, emitir_fatura=FakeEmissor(), dormir=lambda _s: None)
    assert res.correspondido is False
    assert res.nr_registo is None
    assert res.fatura is not None  # o cliente pagou → fatura na mesma

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.ClienteRegisto).count() == 0


# ==========================================================================
#  Ponto de extensão do email de boas-vindas (FDS 3) — NÃO envia, é chamável
# ==========================================================================
def test_checkout_chama_ponto_extensao_boas_vindas_sem_enviar(bd, monkeypatch):
    from app import fulfillment
    registos: list = []
    monkeypatch.setattr(
        fulfillment, "_agendar_boas_vindas",
        lambda cliente_id, fatura, **kw: registos.append((cliente_id, fatura)),
    )
    res = fulfillment.processar_checkout(_sessao(), emitir_fatura=FakeEmissor(), dormir=lambda _s: None)
    assert len(registos) == 1
    assert registos[0][0] == res.cliente_id
    assert registos[0][1] is not None  # recebe a fatura para anexar (FDS 3)


def test_ponto_extensao_boas_vindas_e_no_op(bd):
    # por omissão não envia nada e não rebenta (a implementação de envio é FDS 3)
    from app import fulfillment
    assert fulfillment._agendar_boas_vindas(1, None) is None


# ==========================================================================
#  processar_renovacao — G1 (só subscription_cycle) e emite a 2.ª fatura
# ==========================================================================
def test_renovacao_emite_segunda_fatura(bd):
    from app import fulfillment
    # 1) compra inicial cria o cliente cus_ren
    fulfillment.processar_checkout(
        _sessao(session_id="cs_ren", customer="cus_ren"),
        emitir_fatura=FakeEmissor(), dormir=lambda _s: None,
    )
    # 2) renovação (subscription_cycle) → emite a 2.ª fatura-recibo
    emissor2 = FakeEmissor(doc_id=1112223, total=49.0)
    res = fulfillment.processar_renovacao(
        _invoice(customer="cus_ren", invoice_id="in_ren"),
        emitir_fatura=emissor2, dormir=lambda _s: None,
    )
    assert res.accao == fulfillment.ACCAO_RENOVACAO
    assert res.fatura is not None
    assert emissor2.n_emissoes() == 1

    with db.get_session() as s:
        c = s.query(models.Cliente).filter_by(stripe_customer_id="cus_ren").one()
        assert c.estado == "ativo"
        # a ligação de fatura é atualizada para a mais recente
        assert c.ix_fatura_id == "1112223"


def test_renovacao_ignora_se_nao_for_subscription_cycle(bd):
    from app import fulfillment
    fulfillment.processar_checkout(
        _sessao(session_id="cs_first", customer="cus_first"),
        emitir_fatura=FakeEmissor(), dormir=lambda _s: None,
    )
    emissor2 = FakeEmissor()
    # billing_reason=subscription_create é a fatura da 1.ª compra → NÃO refaturar
    res = fulfillment.processar_renovacao(
        _invoice(billing_reason="subscription_create", customer="cus_first"),
        emitir_fatura=emissor2, dormir=lambda _s: None,
    )
    assert res.accao == fulfillment.ACCAO_IGNORADO
    assert res.fatura is None
    assert emissor2.n_emissoes() == 0


def test_renovacao_de_cliente_desconhecido_e_ignorada(bd):
    from app import fulfillment
    emissor2 = FakeEmissor()
    res = fulfillment.processar_renovacao(
        _invoice(customer="cus_inexistente"), emitir_fatura=emissor2, dormir=lambda _s: None
    )
    assert res.accao == fulfillment.ACCAO_IGNORADO
    assert emissor2.n_emissoes() == 0


# ==========================================================================
#  marcar_cancelado / registar_falha_pagamento
# ==========================================================================
def test_marcar_cancelado(bd):
    from app import fulfillment
    fulfillment.processar_checkout(
        _sessao(session_id="cs_cxl", customer="cus_cxl"),
        emitir_fatura=FakeEmissor(), dormir=lambda _s: None,
    )
    res = fulfillment.marcar_cancelado({"id": "sub_1", "customer": "cus_cxl"})
    assert res.accao == fulfillment.ACCAO_CANCELADO
    with db.get_session() as s:
        c = s.query(models.Cliente).filter_by(stripe_customer_id="cus_cxl").one()
        assert c.estado == "cancelado"


def test_registar_falha_pagamento(bd):
    from app import fulfillment
    fulfillment.processar_checkout(
        _sessao(session_id="cs_fail", customer="cus_fail"),
        emitir_fatura=FakeEmissor(), dormir=lambda _s: None,
    )
    res = fulfillment.registar_falha_pagamento(_invoice(customer="cus_fail"))
    assert res.accao == fulfillment.ACCAO_FALHA
    with db.get_session() as s:
        c = s.query(models.Cliente).filter_by(stripe_customer_id="cus_fail").one()
        assert c.estado == "em_dunning"


def test_cancelado_e_falha_de_cliente_desconhecido_nao_rebentam(bd):
    from app import fulfillment
    assert fulfillment.marcar_cancelado({"customer": "cus_x"}).accao == fulfillment.ACCAO_IGNORADO
    assert fulfillment.registar_falha_pagamento(
        _invoice(customer="cus_x")
    ).accao == fulfillment.ACCAO_IGNORADO
