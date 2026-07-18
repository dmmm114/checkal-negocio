"""Adaptador IfThenPay — geração AO VIVO de referências MB / pedidos MB Way (Fase G).

Decisão do dono (ADENDA §1/§3): o email frio NUNCA leva referência crua — leva um
CTA para `checkal.pt/pagar`, e é a página que gera o método no clique (Opção A):
o valor fixa-se na geração, o MB Way exige o telemóvel, e só a página capta
NIF + T&C (sem os quais não há fatura-recibo válida nem contrato).

Fronteira do módulo (padrão do resto da app — ver `toconline_client.py`):

  - **LIVE-GATED:** sem as chaves (`IFTHENPAY_MB_KEY`/`IFTHENPAY_MBWAY_KEY`,
    defaults vazios) e sem `cliente_http` injetado, as funções devolvem ``None``
    e NUNCA tocam a rede. Os testes injetam um cliente HTTP falso.
  - `verificar_callback` valida a **anti-phishing key OBRIGATORIAMENTE**: chave
    não configurada ⇒ NENHUM callback é aceite (fail-closed). Função pura.
  - Nenhum cliente HTTP é criado à importação; o `httpx` importa-se TARDIAMENTE
    e só quando há chaves reais e o modo de teste está desligado.

O `cliente_http` é qualquer objeto à laia de `httpx.Client` com
``post(url, json=...) -> resposta`` onde `resposta` expõe ``json()`` e
``raise_for_status()``.
"""
from __future__ import annotations

from typing import Any

import app.config as config

__all__ = [
    "ifthenpay_ativo",
    "gerar_referencia_mb",
    "iniciar_mbway",
    "verificar_callback",
]


def ifthenpay_ativo() -> bool:
    """Há pelo menos uma chave IfThenPay configurada? (live-gate da integração)."""
    return bool(config.IFTHENPAY_MB_KEY or config.IFTHENPAY_MBWAY_KEY)


def _cliente_real() -> Any | None:
    """Compõe um cliente HTTP real, ou ``None`` (LIVE-GATED, como o resto da app)."""
    if config.CHECKAL_MODO_TESTE:
        return None
    import httpx  # import tardio: só quando de facto se liga em produção

    return httpx.Client(base_url="", timeout=30.0)


def gerar_referencia_mb(
    order_id: str,
    valor: float,
    validade_dias: int | None = None,
    *,
    cliente_http: Any | None = None,
) -> dict | None:
    """Gera uma referência Multibanco ao vivo → ``{entidade, referencia, valor}``.

    LIVE-GATED: sem `IFTHENPAY_MB_KEY` (ou sem cliente injetado sob modo de
    teste) devolve ``None`` sem tocar a rede.
    """
    if not config.IFTHENPAY_MB_KEY:
        return None
    if cliente_http is None:
        cliente_http = _cliente_real()
        if cliente_http is None:
            return None

    corpo = {
        "mbKey": config.IFTHENPAY_MB_KEY,
        "orderId": order_id,
        "amount": f"{valor:.2f}",
    }
    if validade_dias is not None:
        corpo["expiryDays"] = int(validade_dias)
    r = cliente_http.post(
        f"{config.IFTHENPAY_BASE}/multibanco/reference/init", json=corpo,
    )
    r.raise_for_status()
    dados = r.json() or {}
    return {
        "entidade": str(dados.get("Entity") or dados.get("entidade") or ""),
        "referencia": str(dados.get("Reference") or dados.get("referencia") or ""),
        "valor": str(dados.get("Amount") or corpo["amount"]),
    }


def iniciar_mbway(
    order_id: str,
    valor: float,
    telemovel: str,
    *,
    cliente_http: Any | None = None,
) -> dict | None:
    """Dispara um pedido MB Way (push na app do cliente) → ``{id_pedido, estado}``.

    LIVE-GATED como :func:`gerar_referencia_mb` (chave `IFTHENPAY_MBWAY_KEY`).
    """
    if not config.IFTHENPAY_MBWAY_KEY:
        return None
    if cliente_http is None:
        cliente_http = _cliente_real()
        if cliente_http is None:
            return None

    r = cliente_http.post(
        f"{config.IFTHENPAY_BASE}/spg/payment/mbway",
        json={
            "mbWayKey": config.IFTHENPAY_MBWAY_KEY,
            "orderId": order_id,
            "amount": f"{valor:.2f}",
            "mobileNumber": telemovel,
        },
    )
    r.raise_for_status()
    dados = r.json() or {}
    return {
        "id_pedido": str(dados.get("RequestId") or dados.get("id_pedido") or ""),
        "estado": str(dados.get("Status") or dados.get("estado") or ""),
    }


def verificar_callback(payload: dict, chave: str | None = None) -> dict:
    """Valida um callback de confirmação — a anti-phishing key é OBRIGATÓRIA.

    Fail-closed em tudo: sem chave configurada, chave errada ou payload sem
    `orderId` ⇒ ``{"ok": False}``. Com chave certa devolve
    ``{"ok": True, "order_id": ..., "valor_cent": ...}``. Função pura, sem rede.
    """
    esperada = chave if chave is not None else config.IFTHENPAY_ANTIPHISHING_KEY
    recebida = str(payload.get("key") or payload.get("chave") or "")
    if not esperada or recebida != esperada:
        return {"ok": False, "motivo": "antiphishing"}

    order_id = str(payload.get("orderId") or payload.get("order_id") or "")
    if not order_id:
        return {"ok": False, "motivo": "sem_order_id"}

    valor_cent: int | None = None
    bruto = payload.get("amount") or payload.get("valor")
    if bruto is not None:
        try:
            valor_cent = round(float(str(bruto).replace(",", ".")) * 100)
        except ValueError:
            return {"ok": False, "motivo": "valor_invalido"}

    return {"ok": True, "order_id": order_id, "valor_cent": valor_cent,
            "id_pedido": str(payload.get("requestId") or payload.get("RequestId") or "")}
