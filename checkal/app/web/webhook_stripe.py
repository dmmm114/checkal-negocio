"""Webhook único da Stripe (FDS 2, SPEC-FDS2.md §webhook_stripe · SPEC-STRIPE §2.4/§2.5).

`POST /webhooks/stripe` é a **única** porta de entrada dos eventos da Stripe. A sua
responsabilidade é curta e defensiva (o trabalho pesado vive em `app.fulfillment`):

    1. lê o corpo **BRUTO** (bytes) do request — nunca o dict re-serializado;
    2. `verificar_evento` valida a assinatura sobre esses bytes (HMAC-SHA256 nativo,
       tolerância 5 min); assinatura ausente/inválida/adulterada/expirada → **400**;
    3. **idempotência por `event.id`** (tabela `webhook_eventos`): um evento já
       processado é reconhecido e devolve 200 **sem** voltar a despachar;
    4. despacha por `type` para a ação de fulfillment correspondente;
    5. responde **2xx rápido**.

Mapeamento evento → ação (SPEC-STRIPE §2.5):

    checkout.session.completed    → fulfillment.processar_checkout(obj, ix_http=...)
    invoice.paid                  → fulfillment.processar_renovacao(obj, ix_http=...)  (G1 dentro)
    invoice.payment_failed        → fulfillment.registar_falha_pagamento(obj)
    customer.subscription.deleted → fulfillment.marcar_cancelado(obj)

Qualquer outro `type` é deliberadamente **ignorado** (200) — a Stripe entrega muitos
eventos que não subscrevemos; ignorá-los com 2xx evita retries inúteis.

**Ordem idempotência ↔ despacho.** Verifica-se primeiro se o `event.id` já foi
processado (→ 200); só então se despacha e, por fim, se grava o `event.id`. Gravar
DEPOIS do despacho (e não antes) é deliberado: se o despacho rebentar, o evento **não**
fica marcado como visto e a Stripe reentrega-o — e a reentrega é segura porque o
fulfillment é idempotente por `stripe_session_id` (ver `app.fulfillment`). Assim nunca
se perde a materialização de um pagamento por uma falha transitória.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo não usa o SDK
`stripe` (a verificação é o HMAC nativo de `stripe_client`) e não cria clientes HTTP de
rede sob modo de teste — `_cliente_ix()` devolve `None` (o InvoiceXpress só liga em
produção, quando o dono desliga o modo de teste e há chaves). Nos testes, as ações de
fulfillment são espiadas e/ou o `_cliente_ix` é substituído por um duplo. Nada de emails,
nada de cold.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError

import app.config as config
import app.db as db
import app.models as models
from app import fulfillment
from app.billing.stripe_client import AssinaturaInvalida, verificar_evento

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# Tipos de evento tratados (SPEC-STRIPE §2.5). Manter como constantes evita gralhas.
EVT_CHECKOUT = "checkout.session.completed"
EVT_RENOVACAO = "invoice.paid"
EVT_FALHA_PAGAMENTO = "invoice.payment_failed"
EVT_CANCELAMENTO = "customer.subscription.deleted"


# ==========================================================================
#  Cliente HTTP do InvoiceXpress — composição em produção; None em teste
# ==========================================================================
def _cliente_ix() -> Any:
    """Cria o cliente HTTP do InvoiceXpress para o fulfillment (composição em produção).

    **LIVE-GATED**: sob `config.CHECKAL_MODO_TESTE` (default) ou sem chave de API,
    devolve ``None`` — nenhum cliente de rede é criado, pelo que correr os testes nunca
    toca a rede. Só em produção (modo de teste desligado **e** chave configurada) se
    instancia um `httpx.Client`. Nos testes esta função é substituída por um duplo que
    dirige o adaptador InvoiceXpress sem tocar na rede.
    """
    if config.CHECKAL_MODO_TESTE or not config.INVOICEXPRESS_API_KEY:
        return None
    import httpx  # import tardio: só quando de facto se liga em produção

    return httpx.Client(timeout=30.0)


# ==========================================================================
#  Idempotência por event.id (tabela webhook_eventos)
# ==========================================================================
def _ja_processado(event_id: str) -> bool:
    """Diz se este `event.id` já foi processado (PK em `webhook_eventos`)."""
    with db.get_session() as s:
        return s.get(models.WebhookEvento, event_id) is not None


def _registar_processado(event_id: str, tipo: str) -> None:
    """Marca o `event.id` como processado. Idempotente: uma corrida na PK é engolida.

    A colisão na chave primária (`IntegrityError`) significa que outra entrega do mesmo
    evento já o gravou — o objetivo (processar no máximo uma vez) está garantido, logo
    a exceção é absorvida em vez de virar 500.
    """
    try:
        with db.get_session() as s:
            s.add(models.WebhookEvento(
                event_id=event_id,
                tipo=tipo,
                recebido_em=datetime.now(timezone.utc),
            ))
    except IntegrityError:
        pass


# ==========================================================================
#  Despacho evento → ação de fulfillment
# ==========================================================================
def _objeto(evento: Mapping[str, Any]) -> dict:
    """Extrai `event.data.object` (a Checkout Session / Invoice / Subscription)."""
    dados = evento.get("data")
    obj = dados.get("object") if isinstance(dados, Mapping) else None
    return obj if isinstance(obj, dict) else {}


def _despachar(tipo: str, obj: dict) -> None:
    """Encaminha o objeto do evento para a ação de fulfillment do seu `tipo`.

    Apenas os 4 tipos subscritos têm ação; qualquer outro é ignorado (o webhook
    responde 200 na mesma). As ações que emitem fatura recebem o cliente HTTP do
    InvoiceXpress; as restantes (falha/cancelamento) só mexem no estado local.
    """
    if tipo == EVT_CHECKOUT:
        fulfillment.processar_checkout(obj, ix_http=_cliente_ix())
    elif tipo == EVT_RENOVACAO:
        fulfillment.processar_renovacao(obj, ix_http=_cliente_ix())
    elif tipo == EVT_FALHA_PAGAMENTO:
        fulfillment.registar_falha_pagamento(obj)
    elif tipo == EVT_CANCELAMENTO:
        fulfillment.marcar_cancelado(obj)
    # outro tipo → ignorado deliberadamente


# ==========================================================================
#  Endpoint
# ==========================================================================
@router.post("/webhooks/stripe")
async def receber_webhook(request: Request) -> Response:
    """Recebe e despacha um evento da Stripe (ver docstring do módulo).

    Lê o corpo cru (`await request.body()`) para verificar a assinatura sobre os bytes
    exatos que chegaram. Devolve 400 se a assinatura não bater; 200 nos restantes casos
    (duplicado, tratado ou ignorado), sempre rápido.
    """
    payload = await request.body()
    assinatura = request.headers.get("stripe-signature", "")
    try:
        evento = verificar_evento(payload, assinatura)
    except AssinaturaInvalida:
        return Response(status_code=400)

    event_id = str(evento.get("id") or "")
    tipo = str(evento.get("type") or "")

    # Sem id não há como deduplicar; aceita-se e ignora-se (não deve acontecer na Stripe).
    if not event_id:
        return JSONResponse({"ok": True, "ignorado": "sem_id"})

    # Idempotência: já processado → 200 sem reprocessar.
    if _ja_processado(event_id):
        return JSONResponse({"ok": True, "duplicado": True})

    _despachar(tipo, _objeto(evento))
    _registar_processado(event_id, tipo)
    return JSONResponse({"ok": True, "tipo": tipo})
