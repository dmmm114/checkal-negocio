"""Adaptador de envio transacional (Canal A): Resend — `POST /emails`.

Fronteira do módulo (SPEC-FDS3 §envio + `app/envio/SPEC-RESEND.md`): recebe um
email de negócio já composto (assunto + HTML + anexos PDF) e entrega-o via API
REST da Resend, devolvendo o id de rastreio (`ResultadoEnvio`). É a via **única**
do produto para tocar clientes/prospects que já são clientes ou pediram contacto —
NUNCA prospeção a frio (a AUP da Resend proíbe cold; ver SPEC-RESEND §0).

Fluxo (SPEC-RESEND §3.1):

    POST https://api.resend.com/emails
        Authorization: Bearer <RESEND_API_KEY>
        [Idempotency-Key: <chave>]              (opcional; evita duplicar em retries)
        { from, to, subject, html, reply_to, attachments? }
    → { "id": "<uuid>" }                        → ResultadoEnvio(id=...)

Decisões desta fronteira:
  - **`from`** default = `config.EMAIL_FROM`; sobreponível por `de=`.
  - **`reply_to`** default = `config.EMAIL_APOIO` para as respostas caírem no fluxo
    de suporte, não num remetente `alertas@` não monitorizado (SPEC-RESEND §6.7).
  - **`attachments`** — cada anexo `{"filename", "conteudo"}` vai em **base64**
    (a Resend exige base64); `conteudo` em `bytes` é codificado aqui, uma `str`
    assume-se já-base64 e passa intacta. O endpoint singular suporta anexos (o
    *batch* não — SPEC-RESEND §3.2), por isso relatórios/faturas com PDF vão um a um.
  - **`Idempotency-Key`** — opcional mas recomendado em envios disparados por
    cron/webhook (dunning, alertas); sem ele um retry duplica o email (SPEC §6.8).

Fora de âmbito (SPEC-FDS3): webhook de bounces/complaints (verificação Svix por
confirmar), envio em lote, SMTP. Canal B (cold, `getcheckal.com`) **nunca** toca
este módulo (fronteira dura — SPEC-RESEND §0).

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria
nenhum cliente HTTP — o `cliente_http` é sempre **injetado** por quem chama (mock
nos testes; `httpx.Client` real só em produção, composto por :func:`app.envio.obter_enviador`).
Assim, correr os testes nunca toca a rede.

O `cliente_http` é qualquer objeto à laia de `httpx.Client` com:
  - ``post(url, *, headers=..., json=...) -> resposta``
onde `resposta` expõe ``status_code: int``, ``json() -> dict`` e ``raise_for_status()``.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import app.config as config

__all__ = [
    "ResultadoEnvio",
    "ErroEnvio",
    "enviar_email",
    "RESEND_API",
]

# Endpoint singular da API Resend (SPEC-RESEND §3.1). O batch (§3.2) fica fora de
# âmbito no FDS 3 (e não suporta anexos, que os relatórios/faturas exigem).
RESEND_API = "https://api.resend.com/emails"


class ErroEnvio(RuntimeError):
    """A Resend respondeu sem o `id` esperado (envio não confirmável)."""


@dataclass(frozen=True)
class ResultadoEnvio:
    """Resultado mínimo de um envio confirmado pela Resend.

    `id` é o identificador do email na Resend — a guardar na tabela de envios para
    auditoria/dedupe (a retenção da Resend é de 30 dias, por isso a BD local é a
    fonte de verdade do histórico — SPEC-RESEND §5).
    """

    id: str


# ==========================================================================
#  Helpers internos
# ==========================================================================
def _anexo_api(anexo: Mapping[str, Any]) -> dict[str, str]:
    """Converte um anexo `{"filename", "conteudo"}` no formato da Resend (base64).

    `conteudo` em `bytes` é codificado em base64; uma `str` assume-se já-base64 e
    passa intacta (deixa quem já tem o base64 evitar uma volta de encode/decode).
    """
    conteudo = anexo["conteudo"]
    if isinstance(conteudo, str):
        conteudo_b64 = conteudo
    else:
        conteudo_b64 = base64.b64encode(conteudo).decode("ascii")
    return {"filename": str(anexo["filename"]), "content": conteudo_b64}


# ==========================================================================
#  API pública
# ==========================================================================
def enviar_email(
    *,
    para: str | Sequence[str],
    assunto: str,
    html: str,
    anexos: Sequence[Mapping[str, Any]] = (),
    cliente_http: Any,
    de: str | None = None,
    reply_to: str | None = None,
    texto: str | None = None,
    idempotency_key: str | None = None,
    tags: Sequence[Mapping[str, str]] | None = None,
) -> ResultadoEnvio:
    """Envia um email transacional pela Resend e devolve o `ResultadoEnvio`.

    Parâmetros
    ----------
    para:
        Destinatário(s) — `str` ou lista de `str` (máx. 50; SPEC-RESEND §3.1).
    assunto, html:
        Assunto e corpo HTML (o `text` é auto-gerado pela Resend se omitido).
    anexos:
        Sequência de `{"filename": str, "conteudo": bytes | str-base64}` (ex. PDF do
        relatório/fatura). Vazio por omissão.
    cliente_http:
        Cliente HTTP **injetado** (mock nos testes; nunca criado aqui — LIVE-GATED).
    de:
        Remetente `Nome <email>`; por omissão `config.EMAIL_FROM`.
    reply_to:
        Endereço de resposta; por omissão `config.EMAIL_APOIO` (fluxo de suporte).
    texto:
        Alternativa em texto simples (opcional).
    idempotency_key:
        Chave de idempotência (header `Idempotency-Key`); usar em envios de
        cron/webhook para não duplicar em retries.
    tags:
        Pares key/value de tracking (ex. `[{"name": "tipo", "value": "alerta"}]`).

    Levanta
    -------
    ErroEnvio
        A resposta não trouxe `id` (envio não confirmável).
    """
    corpo: dict[str, Any] = {
        "from": de or config.EMAIL_FROM,
        "to": list(para) if isinstance(para, (list, tuple)) else para,
        "subject": assunto,
        "html": html,
        "reply_to": reply_to or config.EMAIL_APOIO,
    }
    if texto is not None:
        corpo["text"] = texto
    if anexos:
        corpo["attachments"] = [_anexo_api(a) for a in anexos]
    if tags:
        corpo["tags"] = list(tags)

    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    resposta = cliente_http.post(RESEND_API, headers=headers, json=corpo)
    resposta.raise_for_status()

    dados = resposta.json()
    msg_id = str((dados or {}).get("id", "") or "") if isinstance(dados, Mapping) else ""
    if not msg_id:
        raise ErroEnvio("Resposta da Resend sem `id` — envio não confirmável.")
    return ResultadoEnvio(id=msg_id)
