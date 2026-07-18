"""Página `/pagar` + callback IfThenPay + tabela `pagamentos` (Fase G).

Regras provadas (gate/aceitação do prompt-mestre §G):
  - token ASSINADO e com validade, SEM PII (campanha/segmento/nr_registo/plano);
    expirado/adulterado ⇒ rejeitado;
  - GET /pagar transmite CONFIANÇA (ADENDA §2): identificação Cosmic Oasis/NIPC,
    "serviço privado e independente", marcas Multibanco/MB Way, "processado por
    IfThenPay", T&C visíveis, fatura prometida — sem dark patterns;
  - POST /pagar capta NIF + email + aceitação T&C ANTES de gerar o método;
    sem T&C ⇒ recusa e nada é criado; LIVE-GATED: sem chaves IfThenPay não há
    rede (a referência fica por gerar; o pagamento nasce `pendente`);
  - transferência ⇒ `por_casar` (reconciliação semi-manual do GESTOR);
  - callback: anti-phishing OBRIGATÓRIA; montante tem de bater; IDEMPOTENTE
    (reprocessar não duplica fulfillment); fatura/fulfillment SÓ com callback
    pago (o emissor segue o seam live-gated — série CKL guardada a jusante);
  - renovação D-30: token de renovação gera nova passagem por /pagar (sem
    cartão guardado);
  - `pagamentos` NÃO é escrevível pela sessão de governação dos agentes.

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
from app.web.app import criar_app


@pytest.fixture()
def cliente_web(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_pagar_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    app = criar_app()
    with TestClient(app) as c:
        yield c
    eng.dispose()


def _token(**payload) -> str:
    from app.web import pagar

    return pagar.gerar_token_pagamento(**payload)


def _fatura_fake(fid: str = "FT-1"):
    from app.faturacao.base import FaturaRecibo

    return FaturaRecibo(
        id=fid, sequence_number="FRCKL/1", atcud="ATCUD-1", saft_hash="h",
        total=49.0, permalink="http://pdf", pdf_url=None, estado="finalizado",
    )


def _form_valido(t: str, **extra) -> dict:
    dados = {
        "t": t, "plano": "anual", "nif": "513029591",
        "email": "geral@sul.pt", "metodo": "mbref", "tc_aceite": "1",
    }
    dados.update(extra)
    return dados


# ==========================================================================
#  Tabela pagamentos
# ==========================================================================
def test_tabela_pagamentos_criada_e_portavel(cliente_web):
    from sqlalchemy import inspect

    assert "pagamentos" in set(inspect(db.engine).get_table_names())
    tabela = db.Base.metadata.tables["pagamentos"]
    assert type(tabela.columns["valor_cent"].type).__name__.upper() == "INTEGER"


def test_pagamentos_fora_da_sessao_de_governacao(cliente_web):
    from datetime import datetime, timezone

    from app.swarm import fila

    with pytest.raises(fila.EscritaForaDaGovernacao):
        with fila.sessao_governacao() as s:
            s.add(ms.Pagamento(order_id="CKL-X", plano="anual", valor_cent=4900,
                               metodo="mbref", nif="513029591", email="a@b.pt",
                               criado_em=datetime.now(timezone.utc)))
            s.flush()


# ==========================================================================
#  Token — assinado, com validade, sem PII
# ==========================================================================
def test_token_valido_e_lido():
    from app.web import pagar

    t = _token(campanha_id=3, segmento="porto", nr_registo=100031, plano_sugerido="anual")
    dados = pagar.ler_token(t)
    assert dados["campanha_id"] == 3
    assert dados["nr_registo"] == 100031


def test_token_adulterado_rejeitado():
    from app.web import pagar

    t = _token(plano_sugerido="anual")
    assert pagar.ler_token(t + "x") is None


def test_token_expirado_rejeitado():
    from app.web import pagar

    t = _token(plano_sugerido="anual")
    assert pagar.ler_token(t, max_age_s=-1) is None


def test_token_nao_transporta_pii():
    # O payload só referencia campanha/segmento/registo/plano — nunca nome/email/NIF.
    from app.web import pagar

    with pytest.raises(TypeError):
        pagar.gerar_token_pagamento(email="a@b.pt")


# ==========================================================================
#  GET /pagar — a página de confiança (ADENDA §2)
# ==========================================================================
def test_get_pagar_com_token_valido_mostra_confianca(cliente_web):
    r = cliente_web.get("/pagar", params={"t": _token(plano_sugerido="anual")})
    assert r.status_code == 200
    corpo = r.text
    for obrigatorio in (
        "Cosmic Oasis", "NIPC", "privado e independente", "IfThenPay",
        "Multibanco", "MB Way", "termos", "NIF", "fatura",
    ):
        assert obrigatorio.lower() in corpo.lower(), f"falta {obrigatorio!r} na página"


def test_get_pagar_token_invalido_rejeita(cliente_web):
    r = cliente_web.get("/pagar", params={"t": "forjado"})
    assert r.status_code == 400


def test_get_pagar_sem_token_rejeita(cliente_web):
    assert cliente_web.get("/pagar").status_code == 400


# ==========================================================================
#  POST /pagar — NIF + T&C ANTES de gerar; LIVE-GATED
# ==========================================================================
def test_post_pagar_sem_tc_recusa_e_nada_cria(cliente_web):
    form = _form_valido(_token(plano_sugerido="anual"))
    form.pop("tc_aceite")
    r = cliente_web.post("/pagar", data=form)
    assert r.status_code == 400
    with db.get_session() as s:
        assert s.query(ms.Pagamento).count() == 0


def test_post_pagar_nif_invalido_recusa(cliente_web):
    r = cliente_web.post("/pagar", data=_form_valido(_token(), nif="abc"))
    assert r.status_code == 400
    with db.get_session() as s:
        assert s.query(ms.Pagamento).count() == 0


def test_post_pagar_mbref_gated_cria_pendente_sem_rede(cliente_web):
    r = cliente_web.post("/pagar", data=_form_valido(_token(plano_sugerido="anual")))
    assert r.status_code == 200
    with db.get_session() as s:
        p = s.query(ms.Pagamento).one()
        assert p.order_id.startswith("CKL-")
        assert p.estado == "pendente"
        assert p.valor_cent == 4900          # anual 49€ IVA incl.
        assert p.metodo == "mbref"
        assert p.tc_aceite_em is not None
        assert p.tc_versao
        assert p.ifthenpay_ref is None       # LIVE-GATED: sem chaves, nada gerado


def test_post_pagar_transferencia_fica_por_casar(cliente_web):
    r = cliente_web.post(
        "/pagar", data=_form_valido(_token(), metodo="transferencia"),
    )
    assert r.status_code == 200
    with db.get_session() as s:
        p = s.query(ms.Pagamento).one()
        assert p.estado == "por_casar"       # reconciliação semi-manual (GESTOR)


def test_post_pagar_trienal_usa_preco_canonico(cliente_web):
    cliente_web.post("/pagar", data=_form_valido(_token(), plano="trienal"))
    with db.get_session() as s:
        assert s.query(ms.Pagamento).one().valor_cent == 11900


# ==========================================================================
#  Callback IfThenPay — anti-phishing, montante, idempotência, fulfillment
# ==========================================================================
def _pagamento_pendente(cliente_web) -> str:
    cliente_web.post("/pagar", data=_form_valido(_token(nr_registo=100031)))
    with db.get_session() as s:
        return s.query(ms.Pagamento).one().order_id


def test_callback_sem_antiphishing_rejeitado(cliente_web):
    order = _pagamento_pendente(cliente_web)
    r = cliente_web.post(
        "/callback/ifthenpay",
        params={"key": "qualquer", "orderId": order, "amount": "49.00"},
    )
    assert r.status_code == 403
    with db.get_session() as s:
        assert s.query(ms.Pagamento).one().estado == "pendente"


def test_callback_montante_errado_rejeitado(cliente_web, monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")
    order = _pagamento_pendente(cliente_web)
    r = cliente_web.post(
        "/callback/ifthenpay",
        params={"key": "ANTI-1", "orderId": order, "amount": "1.00"},
    )
    assert r.status_code == 400
    with db.get_session() as s:
        assert s.query(ms.Pagamento).one().estado == "pendente"


def test_callback_valido_marca_pago_e_cumpre_fulfillment(cliente_web, monkeypatch):
    from app.web import pagar

    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")

    def _emissor_fake():
        def emitir(*, nome, nif, email, itens, codigo_cliente=None, dormir=None):
            return _fatura_fake("FT-1")
        return emitir

    monkeypatch.setattr(pagar, "_emissor", _emissor_fake)

    with db.get_session() as s:
        s.add(models.Registo(nr_registo=100031, nome_alojamento="Casa do Sol",
                             concelho="Faro", hash_campos="h"))

    order = _pagamento_pendente(cliente_web)
    r = cliente_web.post(
        "/callback/ifthenpay",
        params={"key": "ANTI-1", "orderId": order, "amount": "49.00"},
    )
    assert r.status_code == 200

    with db.get_session() as s:
        p = s.query(ms.Pagamento).one()
        assert p.estado == "pago"
        assert p.pago_em is not None
        cliente = s.query(models.Cliente).one()   # fulfillment correu
        assert cliente.nif == "513029591"
        assert cliente.ix_fatura_id == "FT-1"     # fatura SÓ com callback pago
        assert cliente.estado == "ativo"


def test_callback_idempotente_nao_duplica(cliente_web, monkeypatch):
    from app.web import pagar

    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")
    emissoes = []

    def _emissor_fake():
        def emitir(**kw):
            emissoes.append(kw)
            return _fatura_fake(f"FT-{len(emissoes)}")
        return emitir

    monkeypatch.setattr(pagar, "_emissor", _emissor_fake)
    order = _pagamento_pendente(cliente_web)
    params = {"key": "ANTI-1", "orderId": order, "amount": "49.00"}
    assert cliente_web.post("/callback/ifthenpay", params=params).status_code == 200
    assert cliente_web.post("/callback/ifthenpay", params=params).status_code == 200

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(ms.Pagamento).count() == 1
    assert len(emissoes) == 1                      # NUNCA 2.º documento fiscal


def test_callback_order_desconhecida_404(cliente_web, monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")
    r = cliente_web.post(
        "/callback/ifthenpay",
        params={"key": "ANTI-1", "orderId": "CKL-INEXISTENTE", "amount": "49.00"},
    )
    assert r.status_code == 404


# ==========================================================================
#  Transferência — reconciliação semi-manual (GESTOR) → mesmo fulfillment
# ==========================================================================
def test_casar_transferencia_dispara_fulfillment(cliente_web, monkeypatch):
    from app.web import pagar

    def _emissor_fake():
        def emitir(**kw):
            return _fatura_fake("FT-T")
        return emitir

    monkeypatch.setattr(pagar, "_emissor", _emissor_fake)
    cliente_web.post("/pagar", data=_form_valido(_token(), metodo="transferencia"))
    with db.get_session() as s:
        order = s.query(ms.Pagamento).one().order_id

    with db.get_session() as s:
        pagar.casar_transferencia(s, order_id=order, valor_cent=4900)

    with db.get_session() as s:
        assert s.query(ms.Pagamento).one().estado == "pago"
        assert s.query(models.Cliente).count() == 1


def test_casar_transferencia_valor_errado_recusa(cliente_web):
    from app.web import pagar

    cliente_web.post("/pagar", data=_form_valido(_token(), metodo="transferencia"))
    with db.get_session() as s:
        order = s.query(ms.Pagamento).one().order_id

    with pytest.raises(ValueError):
        with db.get_session() as s:
            pagar.casar_transferencia(s, order_id=order, valor_cent=100)

    with db.get_session() as s:
        assert s.query(ms.Pagamento).one().estado == "por_casar"


# ==========================================================================
#  Renovação D-30 — nova referência, sem cartão guardado
# ==========================================================================
def test_token_renovacao_reutiliza_o_fluxo_pagar(cliente_web):
    from app.web import pagar

    t = pagar.gerar_token_renovacao(cliente_id=7, plano="anual")
    r = cliente_web.get("/pagar", params={"t": t})
    assert r.status_code == 200
    dados = pagar.ler_token(t)
    assert dados["renovacao_cliente"] == 7
    assert dados["plano_sugerido"] == "anual"
