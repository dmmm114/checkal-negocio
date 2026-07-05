"""Teste de ACEITAÇÃO ponta-a-ponta do FDS 2 com o fornecedor **TOConline** ATIVO.

Gémeo do `test_e2e_fds2.py`, mas provando o critério de aceitação **através do
adaptador TOConline** (o fornecedor que o dono passou a usar, como no Radar Marca)
selecionado por `config.CHECKAL_FATURACAO_PROVIDER="toconline"`. Exercita a app REAL
(`app.web.app.criar_app`) do webhook até à BD, correndo o **fluxo verdadeiro** —
`obter_emissor` → `_emissor_toconline` → `garantir_access_token` (OAuth) →
`toconline_client.emitir_fatura_recibo` (guardas G2/G3) — sem tocar na rede:

  1. Semeia um registo do espelho RNAL (nr 100031, Faro) e uma semente OAuth (só
     `refresh_token` válido, sem access) na linha única `toconline_tokens`.
  2. Liga o fornecedor ativo a `"toconline"`, credenciais/série fake, e **DESLIGA** o
     modo de teste (`CHECKAL_MODO_TESTE=False`) — assim `obter_emissor()` compõe DE
     FACTO o emissor TOConline (não devolve `None`); a rota provider=toconline corre a
     sério.
  3. Injeta um `httpx.Client` **falso** (singleton) — a única fronteira de rede — que
     mocka o OAuth (`POST …/token`, com rotação de tokens) **e** a API JSON:API
     (`POST/GET …/commercial_sales_documents`, `url_for_print`), devolvendo uma FR com
     ATCUD/`document_hash_sum`/total certos. LIVE-GATED preservado: cliente HTTP
     INJETADO/MOCKADO, zero rede.
  4. Entrega um `checkout.session.completed` **ASSINADO** (HMAC-SHA256 nativo, nunca o
     SDK) → 200. Verifica: 1 `clientes` + 1 `clientes_registos` (match por nr_registo);
     a FR ficou **certificada** e o **ATCUD** foi guardado no cliente; o corpo JSON:API
     foi construído pelo adaptador real (FR + série + NIF + preço líquido); o OAuth foi
     exercido (houve troca no `/token`).
  5. Reentrega o MESMO evento (mesmo `event.id`) → **não duplica** (idempotência por
     `event.id` no webhook): continua 1 cliente e 1 emissão.
  6. Entrega um `invoice.paid` (`billing_reason=subscription_cycle`) para o mesmo
     `customer` → emite a **2.ª** FR (renovação), reutilizando o access em cache
     (sem 2.ª troca OAuth).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — o `httpx.Client` é
substituído por um duplo; a assinatura Stripe é gerada localmente; nada de emails, nada
de cold. Escrito como critério de aceitação do swap de faturação (TDD de integração).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

SEGREDO = "whsec_teste_e2e_toconline_XYZ789"


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
#  Duplo de rede: um `httpx.Client` falso (singleton) que mocka OAuth + a API
# ==========================================================================
class FakeResposta:
    """Resposta HTTP mínima à laia de `httpx.Response` (status + JSON + raise)."""

    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTocHTTP:
    """`httpx.Client` falso partilhado: mocka o OAuth **e** a API JSON:API do TOConline.

    Roteia por URL (nunca toca a rede):
      - `POST …/token`                          → resposta OAuth (access+refresh rotativos)
      - `POST …/commercial_sales_documents`     → criar FR (id/document_no/hash sequenciais)
      - `GET  …/commercial_sales_documents/<id>`→ detalhes (ATCUD/total/saft por `<id>`)
      - `GET  …/url_for_print/<id>`             → componentes do PDF
      - `POST …/send_document_at_webservice`    → comunicação à AT (não usada por omissão)

    Suporta o protocolo de contexto (`with httpx.Client() as oauth_http:` do
    compositor). `emissoes` conta as FR criadas — o critério de idempotência
    (não reemitir) verifica-se por aqui; `_doc_seq` dá ATCUDs distintos por emissão
    (1.ª = checkout, 2.ª = renovação).
    """

    def __init__(self, total: float = 49.0):
        self.total = total
        self.emissoes = 0
        self._doc_seq = 0
        self._token_seq = 0
        self.chamadas: list[tuple[str, str, dict]] = []

    # protocolo de contexto — o compositor abre o cliente OAuth como `with ... as ...`
    def __enter__(self) -> "FakeTocHTTP":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def post(self, url, **kw):
        self.chamadas.append(("POST", url, kw))
        if "/token" in url:
            self._token_seq += 1
            n = self._token_seq
            return FakeResposta(200, {
                "access_token": f"acc-{n}",
                "expires_in": 14400,            # 4 h
                "refresh_token": f"ref-{n}",    # rotação
                "refresh_token_expires_in": 28800,  # ~8 h
                "token_type": "Bearer",
            })
        if "send_document_at_webservice" in url:
            return FakeResposta(200, {"data": {"attributes": {"communication_status": "OK"}}})
        # criar FR (JSON:API, auto-finalizada — sem change-state)
        self._doc_seq += 1
        self.emissoes += 1
        doc_id = str(self._doc_seq)
        return FakeResposta(201, {"data": {
            "type": "commercial_sales_documents",
            "id": doc_id,
            "attributes": {
                "document_no": f"FR 2026/{doc_id}",
                "document_hash_sum": f"saft-{doc_id}",
                "hash_control": "1",
            },
        }})

    def get(self, url, **kw):
        self.chamadas.append(("GET", url, kw))
        if "url_for_print" in url:
            return FakeResposta(200, {
                "scheme": "https", "host": "app.toconline.pt", "path": "/public-file/ckl.pdf",
            })
        # detalhes do documento: <id> é o último segmento do URL
        doc_id = url.rstrip("/").rsplit("/", 1)[-1]
        return FakeResposta(200, {"data": {
            "type": "commercial_sales_documents",
            "id": doc_id,
            "attributes": {
                "document_no": f"FR 2026/{doc_id}",
                "total": self.total,
                "document_hash_sum": f"saft-{doc_id}",
                "atcud": f"AAJF7-{doc_id}",
                "permalink": f"https://app.toconline.pt/i/{doc_id}",
                "status": "finalizado",
            },
        }})


# ==========================================================================
#  Fixtures: BD SQLite semeada (RNAL + semente OAuth) + fornecedor TOConline + fakes
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_toc.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=100031, data_registo=date(2019, 7, 16),
            nome_alojamento="Casa do Sol", concelho="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda",
            nif="513029591", hash_campos="h1",
        ))
        # Semente OAuth (SPEC-TOCONLINE §2): só `refresh_token` válido (sem access) —
        # força UMA renovação via `/token` na 1.ª emissão; a 2.ª reusa o access em cache.
        s.add(models.ToconlineToken(
            id=1,
            access_token=None, access_expira_em=None,
            refresh_token="rt-seed",
            refresh_expira_em=agora + timedelta(hours=8),
            atualizado_em=agora,
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def toconline_env(monkeypatch):
    """Fornecedor ATIVO = TOConline; credenciais/série fake; MODO DE TESTE **desligado**.

    Com o modo de teste desligado e credenciais presentes, `obter_emissor()` compõe DE
    FACTO o emissor TOConline (não devolve `None`) — a rota provider=toconline é exercida
    a sério. Continua LIVE-GATED porque o `httpx.Client` está mockado (fixture `toc_http`).
    """
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "CHECKAL_FATURACAO_PROVIDER", "toconline")
    monkeypatch.setattr(config, "TOCONLINE_OAUTH_URL", "https://oauth.toconline.test")
    monkeypatch.setattr(config, "TOCONLINE_API_URL", "https://api.toconline.test")
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_ID", "cid-test")
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_SECRET", "csecret-test")
    monkeypatch.setattr(config, "TOCONLINE_SERIES_ID", "777")
    monkeypatch.setattr(config, "TOCONLINE_SERIES_PREFIX", "")


@pytest.fixture()
def toc_http(monkeypatch):
    """Injeta um `httpx.Client` falso (singleton) — OAuth + commercial_sales_documents mockados.

    É a **única** fronteira de rede do fluxo TOConline; substituí-la garante que nada
    toca a rede, mantendo intacto todo o resto do stack real (obter_emissor →
    _emissor_toconline → garantir_access_token → toconline_client).
    """
    fake = FakeTocHTTP(total=49.0)
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)
    return fake


@pytest.fixture()
def segredo(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SEGREDO, raising=False)


@pytest.fixture()
def client(bd, toconline_env, toc_http, segredo):
    from app.web.app import criar_app
    return TestClient(criar_app())


# ==========================================================================
#  Fábricas de objetos Stripe
# ==========================================================================
def _sessao_checkout(session_id="cs_toc", customer="cus_toc", plano="anual") -> dict:
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "subscription",
        "payment_status": "paid",
        "amount_total": 4900,
        "currency": "eur",
        "customer": customer,
        "subscription": "sub_toc",
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


def _invoice_renovacao(customer="cus_toc", invoice_id="in_ren_toc") -> dict:
    return {
        "id": invoice_id,
        "object": "invoice",
        "billing_reason": "subscription_cycle",
        "customer": customer,
        "subscription": "sub_toc",
        "attempt_count": 1,
    }


# ==========================================================================
#  ACEITAÇÃO — pago (provider=toconline) → cliente registado → FR certificada
# ==========================================================================
def test_aceitacao_toconline_checkout_idempotencia_e_renovacao(client, toc_http):
    # ---- 1) checkout ASSINADO via provider=toconline: pago → cliente + assoc + FR ----
    corpo_co = _evento("checkout.session.completed", "evt_toc_checkout", _sessao_checkout())
    r1 = _post(client, corpo_co, _assinar(corpo_co))
    assert r1.status_code == 200
    assert r1.json().get("tipo") == "checkout.session.completed"

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        c = s.query(models.Cliente).filter_by(stripe_session_id="cs_toc").one()
        assert c.email == "cliente@exemplo.pt"
        assert c.nif == "508000000"
        assert c.plano == "anual"
        assert c.estado == "ativo"
        # FR CERTIFICADA via TOConline — o ATCUD ficou GUARDADO (critério de aceitação)
        assert c.ix_atcud == "AAJF7-1"
        assert c.ix_fatura_id == "1"
        assert c.ix_permalink.endswith("/i/1")
        # 1 associação cliente ↔ registo (match por nr_registo)
        assoc = s.query(models.ClienteRegisto).filter_by(cliente_id=c.id).all()
        assert len(assoc) == 1
        assert assoc[0].nr_registo == 100031
    assert toc_http.emissoes == 1  # exatamente uma FR emitida

    # o corpo JSON:API foi construído pelo adaptador TOConline REAL (FR + série + NIF + líquido)
    corpo_criar = next(
        kw["json"] for m, u, kw in toc_http.chamadas
        if m == "POST" and u.endswith("/commercial_sales_documents")
    )
    assert corpo_criar["data"]["type"] == "commercial_sales_documents"
    attrs = corpo_criar["data"]["attributes"]
    assert attrs["document_type"] == "FR"
    assert attrs["document_series_id"] == 777
    assert attrs["customer_tax_registration_number"] == "508000000"
    assert attrs["vat_included_prices"] is False
    assert attrs["lines"][0]["unit_price"] == 39.84  # líquido (49/1,23), IVA 23% na linha
    # OAuth foi exercido de facto: houve (exatamente) uma troca no /token (semente só refresh)
    trocas_token = [u for _, u, _ in toc_http.chamadas if "/token" in u]
    assert len(trocas_token) == 1

    # ---- 2) reentrega do MESMO evento → NÃO duplica (idempotência por event.id) ----
    r_dup = _post(client, corpo_co, _assinar(corpo_co))
    assert r_dup.status_code == 200
    assert r_dup.json().get("duplicado") is True
    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.ClienteRegisto).count() == 1
    assert toc_http.emissoes == 1  # nenhuma FR adicional

    # ---- 3) renovação (invoice.paid, subscription_cycle) → 2.ª FR ----
    corpo_ren = _evento("invoice.paid", "evt_toc_ren", _invoice_renovacao())
    r_ren = _post(client, corpo_ren, _assinar(corpo_ren))
    assert r_ren.status_code == 200
    assert r_ren.json().get("tipo") == "invoice.paid"
    assert toc_http.emissoes == 2  # a 2.ª FR foi emitida

    with db.get_session() as s:
        # continua a haver UM cliente; a ligação de fatura aponta para a mais recente
        assert s.query(models.Cliente).count() == 1
        c = s.query(models.Cliente).filter_by(stripe_customer_id="cus_toc").one()
        assert c.estado == "ativo"
        assert c.ix_fatura_id == "2"
        assert c.ix_atcud == "AAJF7-2"

    # a renovação reutilizou o access em cache → continua a haver só UMA troca OAuth
    trocas_token = [u for _, u, _ in toc_http.chamadas if "/token" in u]
    assert len(trocas_token) == 1


# ==========================================================================
#  LIVE-GATED — sob modo de teste não se compõe emissor (nada toca a rede)
# ==========================================================================
def test_modo_teste_gate_nao_compoe_emissor(monkeypatch):
    """Sob `CHECKAL_MODO_TESTE`, `obter_emissor()` devolve `None` (disciplina LIVE-GATED)."""
    import app.faturacao as faturacao

    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    monkeypatch.setattr(config, "CHECKAL_FATURACAO_PROVIDER", "toconline")
    assert faturacao.obter_emissor() is None
