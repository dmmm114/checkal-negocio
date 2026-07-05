"""Teste de ACEITAÇÃO ponta-a-ponta do FDS 3 (SPEC-FDS3.md §critério de "feito").

Prova o critério canónico do AUTOMACAO.md §7 / SPEC-FDS3: *"compra → relatório sem
intervenção humana"*. Exercita a app REAL (`app.web.app.criar_app`) através do
`TestClient`, do webhook até ao selo público, com **só** as duas folhas de I/O
mockadas (`obter_detalhe` do RNAL e `enviar` da Resend) e o emissor de faturação
injetado — tudo o resto (webhook → fulfillment → onboarding → relatório/PDF → selo) é
o código de produção.

Percurso:
  1. Semeia um registo do espelho RNAL (nr 100031, Faro) **com PII do titular**
     (nome/NIF/email/telefones) — para depois provar que o selo público não a expõe.
  2. Compõe a app (`criar_app`) + `TestClient`.
  3. Injeta um emissor falso (`_FakeEmissor`) via `webhook_stripe._emissor` e o seam
     de onboarding via `fulfillment._compor_onboarding` — este devolve o
     `processar_onboarding` REAL com `obter_detalhe`/`enviar` mockados (zero rede).
  4. Entrega um `checkout.session.completed` **ASSINADO** → 200. Verifica que:
        · o cliente + associação ao registo foram materializados (fulfillment);
        · o **detalhe** foi obtido e persistido em `detalhes_cliente`;
        · o **Relatório PDF** foi gerado (anexo `%PDF`);
        · o **email de boas-vindas** foi 'enviado' (mock) com o link do **selo**;
        · ficou o marcador de idempotência do onboarding em `alertas`.
  5. `GET /selo/100031` → **200** "Verificado", com dados públicos do estabelecimento
     e **zero PII** do titular.
  6. Reentrega do MESMO evento → **não duplica** (idempotência): 1 cliente, 1 detalhe,
     1 email, 1 marcador.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — emissor, detalhe e
enviador são dublês injetados; a assinatura Stripe é gerada localmente (HMAC-SHA256
nativo); nada de emails reais, nada de cold. Só dados públicos do estabelecimento na
saída pública (selo).
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
from app.rnal.detalhe import ESTADO_ATIVO, DetalheRegisto

SEGREDO = "whsec_teste_e2e_fds3_XYZ789"

# PII do titular semeada no espelho — NUNCA pode aparecer no selo público.
PII_TITULAR = "Alojamentos Sul, Lda"
PII_NIF = "513029591"
PII_EMAIL = "dono.privado@exemplo.pt"
PII_TELEFONE = "289111222"
PII_TELEMOVEL = "910333444"


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
#  Dublês injetados — emissor de faturas, detalhe RNAL e enviador (sem rede)
# ==========================================================================
class _FakeEmissor:
    """Emissor falso: uma `FaturaRecibo` certificada por chamada (sem HTTP nem fornecedor)."""

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


class _FakeObterDetalhe:
    """`obter_detalhe(nr)` falso: devolve um `DetalheRegisto` ativo com seguro; conta chamadas."""

    def __init__(self):
        self.chamadas: list[int] = []

    def __call__(self, nr, **kw):
        self.chamadas.append(nr)
        return DetalheRegisto(
            nr_registo=nr,
            estado=ESTADO_ATIVO,
            seguro_companhia="Zurich",
            seguro_apolice="009238995",
            seguro_inicio=date(2025, 12, 12),
            seguro_validade=date(2026, 12, 11),
        )


class _FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_e2e_fds3_1"):
        self.email_id = email_id
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio
        self.chamadas.append(
            {"para": para, "assunto": assunto, "html": html, "anexos": list(anexos), "kw": kw}
        )
        return ResultadoEnvio(id=self.email_id)

    @property
    def n(self) -> int:
        return len(self.chamadas)


class _SeamOnboarding:
    """Seam injetado no lugar de `fulfillment._compor_onboarding` (LIVE-GATED).

    `compor()` devolve o *callable* `_seam(cliente_id, fatura)` que chama o
    `processar_onboarding` REAL com os dublês `obter_detalhe`/`enviar`. Guarda o
    resultado e qualquer exceção (que o `_agendar_boas_vindas` engole por ser
    best-effort) para o teste as poder inspecionar/surfar.
    """

    def __init__(self, obter, enviar):
        self.obter = obter
        self.enviar = enviar
        self.resultados: list = []
        self.erros: list[Exception] = []

    def compor(self):
        from app.onboarding import processar_onboarding

        def _seam(cliente_id, fatura):
            try:
                res = processar_onboarding(
                    cliente_id, obter_detalhe=self.obter, enviar=self.enviar
                )
                self.resultados.append(res)
                return res
            except Exception as exc:  # o wrapper best-effort engole; guardamos para o teste
                self.erros.append(exc)
                raise

        return _seam


# ==========================================================================
#  Fixtures: BD SQLite temporária semeada + segredo + app + dublês injetados
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_fds3.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=100031, data_registo=date(2019, 7, 16),
            nome_alojamento="Casa do Sol", modalidade="Apartamento",
            concelho="Faro", distrito="Faro",
            titular_tipo="coletiva", titular_nome=PII_TITULAR,
            nif=PII_NIF, email=PII_EMAIL, telefone=PII_TELEFONE, telemovel=PII_TELEMOVEL,
            hash_campos="h1",
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def segredo(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SEGREDO, raising=False)


@pytest.fixture()
def emissor(monkeypatch):
    """Injeta um `_FakeEmissor` partilhado no webhook (fatura certificada, sem rede)."""
    from app.web import webhook_stripe
    fake = _FakeEmissor(total=49.0)
    monkeypatch.setattr(webhook_stripe, "_emissor", lambda: fake)
    return fake


@pytest.fixture()
def seam(monkeypatch):
    """Injeta o seam de onboarding (obter_detalhe + enviar mockados) no fulfillment.

    Substitui `fulfillment._compor_onboarding` — o ponto LIVE-GATED da wire — por um
    seam que chama o `processar_onboarding` real. É a fronteira de injeção do FDS 3:
    o fulfillment e o onboarding correm de verdade; só as duas folhas de rede são falsas.
    """
    from app import fulfillment
    obter = _FakeObterDetalhe()
    enviar = _FakeEnviar()
    recorder = _SeamOnboarding(obter, enviar)
    monkeypatch.setattr(fulfillment, "_compor_onboarding", recorder.compor)
    recorder.obter = obter
    recorder.enviar = enviar
    return recorder


@pytest.fixture()
def client(bd, segredo, emissor, seam):
    from app.web.app import criar_app
    return TestClient(criar_app())


# ==========================================================================
#  Fábrica de objetos Stripe
# ==========================================================================
def _sessao_checkout(session_id="cs_e2e_fds3", customer="cus_e2e_fds3", plano="anual") -> dict:
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "subscription",
        "payment_status": "paid",
        "amount_total": 4900,
        "currency": "eur",
        "customer": customer,
        "subscription": "sub_e2e_fds3",
        "metadata": {"plano": plano},
        "custom_fields": [
            {"key": "nif", "type": "text", "text": {"value": "508000000"}},
            {"key": "nr_registo_al", "type": "text", "text": {"value": "100031"}},
        ],
        "customer_details": {
            "email": "cliente@exemplo.pt",
            "name": PII_TITULAR,
            "address": {"city": "Faro", "country": "PT"},
        },
    }


# ==========================================================================
#  ACEITAÇÃO FDS 3 — pago → onboarding → relatório+email+selo → idempotência
# ==========================================================================
def test_aceitacao_fds3_onboarding_selo_e_idempotencia(client, emissor, seam):
    obter, enviar = seam.obter, seam.enviar

    # ---- 1) checkout ASSINADO → fulfillment + onboarding (sem intervenção humana) ----
    corpo = _evento("checkout.session.completed", "evt_e2e_fds3_checkout", _sessao_checkout())
    r1 = _post(client, corpo, _assinar(corpo))
    assert r1.status_code == 200
    assert r1.json().get("tipo") == "checkout.session.completed"

    # o onboarding correu sem engolir nenhuma exceção
    assert seam.erros == []
    assert len(seam.resultados) == 1
    res = seam.resultados[0]
    assert res.enviado is True
    assert res.idempotente is False
    assert res.nrs == (100031,)

    # cliente + associação materializados pelo fulfillment; fatura certificada guardada
    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        c = s.query(models.Cliente).filter_by(stripe_session_id="cs_e2e_fds3").one()
        assert c.email == "cliente@exemplo.pt"
        assert c.ix_atcud == "ATCUD0001-1"
        assert c.ix_permalink.endswith("/i/900001")
        assert s.query(models.ClienteRegisto).filter_by(cliente_id=c.id).count() == 1
    assert emissor.emissoes == 1

    # o DETALHE foi obtido e persistido em detalhes_cliente
    assert obter.chamadas == [100031]
    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d is not None
        assert d.estado_detalhado == ESTADO_ATIVO
        assert d.seguro_companhia == "Zurich"
        assert d.seguro_validade == date(2026, 12, 11)

    # o email de boas-vindas saiu UMA vez, para o cliente, com o RELATÓRIO PDF em anexo
    assert enviar.n == 1
    chamada = enviar.chamadas[0]
    assert chamada["para"] == "cliente@exemplo.pt"
    assert len(chamada["anexos"]) >= 1
    pdf = chamada["anexos"][0]["conteudo"]
    assert isinstance(pdf, (bytes, bytearray)) and bytes(pdf[:4]) == b"%PDF"
    # o corpo liga ao SELO público e à fatura já emitida; G4: nunca afirma cancelamento
    html = chamada["html"]
    assert f"{config.BASE_URL}/selo/100031" in html
    assert "900001" in html  # permalink da fatura certificada
    assert "cancelad" not in html.lower()

    # marcador de idempotência do onboarding gravado em `alertas`
    with db.get_session() as s:
        marcadores = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == res.cliente_id, models.Alerta.origem == "onboarding")
            .all()
        )
        assert len(marcadores) == 1

    # ---- 2) SELO público: 200 "Verificado", só dados públicos, ZERO PII ----
    sel = client.get("/selo/100031")
    assert sel.status_code == 200
    corpo_selo = sel.text
    assert "Verificado" in corpo_selo
    # dados públicos do estabelecimento presentes
    assert "Casa do Sol" in corpo_selo
    assert "Faro" in corpo_selo
    # ZERO PII do titular (nome/NIF/email/telefone/telemóvel)
    assert PII_TITULAR not in corpo_selo
    assert PII_NIF not in corpo_selo
    assert PII_EMAIL not in corpo_selo
    assert PII_TELEFONE not in corpo_selo
    assert PII_TELEMOVEL not in corpo_selo

    # selo de registo inexistente → 404
    assert client.get("/selo/99999999").status_code == 404

    # ---- 3) reentrega do MESMO evento → NÃO duplica (idempotência) ----
    r_dup = _post(client, corpo, _assinar(corpo))
    assert r_dup.status_code == 200
    assert r_dup.json().get("duplicado") is True

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.ClienteRegisto).count() == 1
        assert s.query(models.DetalheCliente).count() == 1
        assert (
            s.query(models.Alerta)
            .filter(models.Alerta.origem == "onboarding")
            .count()
            == 1
        )
    # nenhum email/fatura/onboarding adicional
    assert enviar.n == 1
    assert emissor.emissoes == 1
    assert len(seam.resultados) == 1
