"""Verificação de webhooks Stripe e mapeamento Price↔plano (FDS 2).

Contrato (SPEC-FDS2.md §stripe_client · SPEC-STRIPE.md §2.4):

  - `verificar_evento(payload_bruto, sig_header, *, segredo) -> dict`
      Valida a assinatura do webhook Stripe e devolve o evento (dict). A
      verificação é criptográfica LOCAL — SEM rede e SEM o SDK `stripe`:
        * assina-se `f"{t}." + corpo_bruto` com HMAC-SHA256 nativo (stdlib);
        * o header `Stripe-Signature` traz `t=<timestamp>,v1=<hex>` (podendo
          haver várias `v1=` e outros esquemas como `v0=`, que se ignoram);
        * compara-se em tempo constante (`hmac.compare_digest`);
        * exige-se que o `t` esteja dentro da tolerância (5 min, default Stripe).
      Assinatura em falta/malformada/não-correspondente/fora de tolerância →
      `AssinaturaInvalida`.

  - `plano_de_price(price_id) -> str | None`
      Traduz um Price da Stripe para o código de plano interno (chave de
      `config.PLANOS`) via `config.STRIPE_PRICE_PLANO`. Desconhecido → `None`.

Porquê HMAC nativo e não o SDK (SPEC-STRIPE.md §2.4, disciplina do FDS 2):
verificar a assinatura é só um HMAC-SHA256 sobre bytes — a stdlib chega, evita
uma dependência e mantém os testes 100% offline (a assinatura válida é gerada
nos testes com o mesmo segredo). O CORPO tem de ser o BRUTO (bytes) tal como
chegou no request: re-serializar o JSON muda os bytes e a assinatura falha
sempre (SPEC-STRIPE.md §5.6).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import app.config as config

# Tolerância temporal por omissão entre o `t` do header e o relógio local.
# 5 min é o default documentado da Stripe (SPEC-STRIPE.md §2.4); não usar 0.
TOLERANCIA_S: int = 300

# Sentinela: `segredo` por omissão resolve-se para `config.STRIPE_WEBHOOK_SECRET`
# NO MOMENTO DA CHAMADA (não na importação), para não congelar um segredo vazio
# ou rodado. Passar `segredo=""` explicitamente é um segredo vazio → rejeitado.
_PADRAO: Any = object()


class AssinaturaInvalida(Exception):
    """Assinatura do webhook Stripe ausente, malformada, errada ou expirada."""


def _pares_do_header(sig_header: str) -> tuple[str | None, list[str]]:
    """Decompõe um header `Stripe-Signature` em `(timestamp, [assinaturas v1])`.

    Formato: pares `chave=valor` separados por vírgula, ex.
    `t=1700000000,v1=abcd...,v1=ef01...,v0=...`. Ignora esquemas != `t`/`v1`.
    Tolerante a espaços em torno dos pares.
    """
    timestamp: str | None = None
    v1s: list[str] = []
    for parte in sig_header.split(","):
        chave, sep, valor = parte.partition("=")
        if not sep:
            continue  # par sem `=` → ignora
        chave = chave.strip()
        valor = valor.strip()
        if chave == "t":
            timestamp = valor
        elif chave == "v1":
            v1s.append(valor)
    return timestamp, v1s


def verificar_evento(
    payload_bruto: bytes,
    sig_header: str,
    *,
    segredo: str = _PADRAO,
    tolerancia_s: float = TOLERANCIA_S,
) -> dict:
    """Verifica a assinatura de um webhook Stripe e devolve o evento (dict).

    `payload_bruto` é o corpo do request BYTE-A-BYTE (nunca o dict re-serializado).
    `sig_header` é o valor do header `Stripe-Signature`. `segredo` por omissão é
    `config.STRIPE_WEBHOOK_SECRET` (lido na chamada). Levanta `AssinaturaInvalida`
    se o segredo for vazio, o header estiver ausente/malformado, nenhuma `v1`
    corresponder, ou o timestamp estiver fora da tolerância.
    """
    if segredo is _PADRAO:
        segredo = config.STRIPE_WEBHOOK_SECRET
    if not segredo:
        raise AssinaturaInvalida("Segredo de webhook Stripe não configurado.")
    if not sig_header:
        raise AssinaturaInvalida("Header Stripe-Signature ausente.")

    timestamp, assinaturas = _pares_do_header(sig_header)
    if timestamp is None or not assinaturas:
        raise AssinaturaInvalida("Header Stripe-Signature malformado (falta t ou v1).")
    try:
        ts = int(timestamp)
    except ValueError as e:
        raise AssinaturaInvalida("Timestamp do header não é numérico.") from e

    assinado = f"{ts}.".encode("utf-8") + payload_bruto
    esperada = hmac.new(segredo.encode("utf-8"), assinado, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(esperada, a) for a in assinaturas):
        raise AssinaturaInvalida("Nenhuma assinatura v1 corresponde ao corpo.")

    if abs(time.time() - ts) > tolerancia_s:
        raise AssinaturaInvalida("Timestamp fora da tolerância (5 min).")

    try:
        return json.loads(payload_bruto)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Assinatura ok mas corpo não é JSON: trata-se como evento não-fiável.
        raise AssinaturaInvalida("Corpo do evento não é JSON válido.") from e


def plano_de_price(price_id: str) -> str | None:
    """Devolve o código de plano interno para um `price_id` Stripe, ou `None`.

    Lê `config.STRIPE_PRICE_PLANO` no momento da chamada (mapa alimentado por
    ambiente; ver `config.py`). Um Price não mapeado devolve `None`.
    """
    return config.STRIPE_PRICE_PLANO.get(price_id)
