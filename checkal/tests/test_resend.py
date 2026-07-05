"""Testes do adaptador de envio transacional Resend (Canal A) — FDS 3.

Contrato (SPEC-FDS3 §envio + `app/envio/SPEC-RESEND.md`):

    enviar_email(*, para, assunto, html, anexos, cliente_http) -> ResultadoEnvio
    obter_enviador() -> callable | None   (LIVE-GATED, à imagem de faturacao.obter_emissor)

Fluxo: POST único a `https://api.resend.com/emails` (Bearer RESEND_API_KEY) com
`from/to/subject/html` (+ `attachments` em base64 e `reply_to` de apoio); resposta
`{"id": "<uuid>"}` → `ResultadoEnvio(id=...)`. SEM webhook de bounces (fora de âmbito).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — o `cliente_http`
é INJETADO/MOCKADO (`FakeCliente`); `obter_enviador()` devolve `None` sob modo de
teste / sem `RESEND_API_KEY`. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import base64

import pytest

import app.config as config
from app import envio
from app.envio import resend_client as rc


# ==========================================================================
#  Duplos de teste: cliente HTTP falso (nunca há rede) + resposta scriptada
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


class FakeCliente:
    """Cliente que devolve sempre a mesma resposta a `.post` e regista a chamada."""

    def __init__(self, resposta: FakeResposta | None = None):
        self.resposta = resposta or FakeResposta(200, {"id": "re_abc123"})
        self.chamadas: list[tuple[str, dict]] = []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        return self.resposta


PDF_BYTES = b"%PDF-1.4\n%fake pdf bytes\n"


# ==========================================================================
#  Envio OK — devolve ResultadoEnvio com o id da Resend
# ==========================================================================
def test_envio_ok_devolve_resultado_com_id():
    cli = FakeCliente(FakeResposta(200, {"id": "re_abc123"}))
    res = rc.enviar_email(
        para="cliente@exemplo.pt",
        assunto="Bem-vindo ao CheckAL",
        html="<p>O teu AL passou no check.</p>",
        anexos=(),
        cliente_http=cli,
    )
    assert isinstance(res, rc.ResultadoEnvio)
    assert res.id == "re_abc123"


def test_post_a_endpoint_da_resend():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="Olá", html="<p>oi</p>", anexos=(), cliente_http=cli,
    )
    assert len(cli.chamadas) == 1
    url, _kw = cli.chamadas[0]
    assert url == "https://api.resend.com/emails"


def test_payload_tem_campos_obrigatorios():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt",
        assunto="Assunto X",
        html="<p>corpo</p>",
        anexos=(),
        cliente_http=cli,
    )
    _url, kw = cli.chamadas[0]
    corpo = kw["json"]
    assert corpo["from"] == config.EMAIL_FROM        # remetente default = config
    assert corpo["to"] == "c@ex.pt"
    assert corpo["subject"] == "Assunto X"
    assert corpo["html"] == "<p>corpo</p>"
    # reply_to aponta para o apoio (respostas caem no fluxo de suporte — SPEC §6.7)
    assert corpo["reply_to"] == config.EMAIL_APOIO


def test_remetente_pode_ser_sobreposto():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(),
        cliente_http=cli, de="CheckAL <alertas@send.checkal.pt>",
    )
    assert cli.chamadas[0][1]["json"]["from"] == "CheckAL <alertas@send.checkal.pt>"


def test_autorizacao_bearer_no_header(monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key_123")
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(), cliente_http=cli,
    )
    headers = cli.chamadas[0][1]["headers"]
    assert headers["Authorization"] == "Bearer re_test_key_123"


def test_to_aceita_lista_de_destinatarios():
    cli = FakeCliente()
    rc.enviar_email(
        para=["a@ex.pt", "b@ex.pt"], assunto="a", html="<p>b</p>", anexos=(),
        cliente_http=cli,
    )
    assert cli.chamadas[0][1]["json"]["to"] == ["a@ex.pt", "b@ex.pt"]


# ==========================================================================
#  Anexos — o PDF (relatório/fatura) vai em base64 no campo `attachments`
# ==========================================================================
def test_anexo_pdf_vai_em_base64():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt",
        assunto="Relatório inicial",
        html="<p>Em anexo o teu relatório.</p>",
        anexos=[{"filename": "relatorio.pdf", "conteudo": PDF_BYTES}],
        cliente_http=cli,
    )
    anexos = cli.chamadas[0][1]["json"]["attachments"]
    assert len(anexos) == 1
    assert anexos[0]["filename"] == "relatorio.pdf"
    # o conteúdo é base64 dos bytes originais (a Resend exige base64)
    assert base64.b64decode(anexos[0]["content"]) == PDF_BYTES


def test_anexo_ja_em_base64_string_passa_intacto():
    cli = FakeCliente()
    b64 = base64.b64encode(PDF_BYTES).decode("ascii")
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>",
        anexos=[{"filename": "fatura.pdf", "conteudo": b64}],
        cliente_http=cli,
    )
    assert cli.chamadas[0][1]["json"]["attachments"][0]["content"] == b64


def test_sem_anexos_nao_inclui_attachments():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(), cliente_http=cli,
    )
    assert "attachments" not in cli.chamadas[0][1]["json"]


# ==========================================================================
#  Idempotency-Key — evita duplicar em retries (SPEC §3.1)
# ==========================================================================
def test_idempotency_key_vai_no_header_quando_dado():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(),
        cliente_http=cli, idempotency_key="onboarding-42",
    )
    assert cli.chamadas[0][1]["headers"]["Idempotency-Key"] == "onboarding-42"


def test_sem_idempotency_key_nao_poe_header():
    cli = FakeCliente()
    rc.enviar_email(
        para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(), cliente_http=cli,
    )
    assert "Idempotency-Key" not in cli.chamadas[0][1]["headers"]


# ==========================================================================
#  Erros — resposta sem id / HTTP de erro
# ==========================================================================
def test_resposta_sem_id_levanta_erro_envio():
    cli = FakeCliente(FakeResposta(200, {}))
    with pytest.raises(rc.ErroEnvio):
        rc.enviar_email(
            para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(), cliente_http=cli,
        )


def test_http_de_erro_propaga():
    cli = FakeCliente(FakeResposta(422, {"message": "invalid"}))
    with pytest.raises(RuntimeError):
        rc.enviar_email(
            para="c@ex.pt", assunto="a", html="<p>b</p>", anexos=(), cliente_http=cli,
        )


# ==========================================================================
#  LIVE-GATE — obter_enviador() à imagem de faturacao.obter_emissor
# ==========================================================================
def test_live_gate_modo_teste_devolve_none(monkeypatch):
    # Mesmo com chave presente, o modo de teste corta a rede: None.
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key_123")
    assert envio.obter_enviador() is None


def test_live_gate_sem_api_key_devolve_none(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    assert envio.obter_enviador() is None


def test_live_gate_com_credenciais_devolve_callable(monkeypatch):
    # Produção (modo de teste OFF + chave): devolve um callable. NÃO o invocamos
    # (invocá-lo criaria httpx.Client e tocaria a rede) — só confirmamos o gate.
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key_123")
    enviador = envio.obter_enviador()
    assert enviador is not None
    assert callable(enviador)


# ==========================================================================
#  Re-exportações do pacote (fronteira pública estável)
# ==========================================================================
def test_pacote_reexporta_fronteira_publica():
    assert envio.enviar_email is rc.enviar_email
    assert envio.ResultadoEnvio is rc.ResultadoEnvio
    assert envio.ErroEnvio is rc.ErroEnvio
