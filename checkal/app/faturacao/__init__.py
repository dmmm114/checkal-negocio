"""Faturação do CheckAL: seletor de fornecedor + composição do emissor (seam agnóstico).

O CheckAL emite faturas-recibo certificadas por trás de **uma única interface**
(`FaturaRecibo` + `emitir_fatura_recibo`), com dois adaptadores intermutáveis:

    - :mod:`app.faturacao.toconline_client`    — fornecedor **ativo** (o dono usa o
      TOConline no Radar Marca); OAuth2 Bearer + série CKL nova (SPEC-TOCONLINE).
    - :mod:`app.faturacao.invoicexpress_client` — adaptador **secundário/referência**
      (FDS 2); `api_key` em query string (SPEC-INVOICEXPRESS).

Este pacote expõe o **ponto único de composição** — :func:`obter_emissor` — que o
fulfillment/webhook usam sem conhecer qual fornecedor está ativo. `obter_emissor`
lê `config.CHECKAL_FATURACAO_PROVIDER` e devolve um *callable* já ligado ao HTTP e
(no TOConline) ao token OAuth:

    emitir(*, nome, nif, email, itens, codigo_cliente=None, dormir=time.sleep) -> FaturaRecibo

O contrato mínimo de quem chama é `emitir(*, nome, nif, email, itens)`; `codigo_cliente`
(id estável do cliente, evita duplicá-lo na conta) e `dormir` (pausa do PDF) são
passagens opcionais preservadas para paridade **exata** com os adaptadores.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** :func:`obter_emissor` é o
**único sítio** que cria um cliente HTTP real (`httpx.Client`). Sob
`config.CHECKAL_MODO_TESTE` **ou** sem as credenciais do fornecedor ativo devolve
``None`` — tal como o antigo `_cliente_ix()` do webhook — pelo que correr os testes
nunca toca a rede. Nos testes injeta-se um emissor falso (um *callable* que devolve
uma :class:`FaturaRecibo`) em vez deste; a rede real só liga em produção, quando o
dono desliga o modo de teste e há credenciais.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import app.config as config
from app.faturacao.base import (
    ErroFaturacao,
    FaturaNaoCertificada,
    FaturaRecibo,
    TotalInesperado,
    preco_liquido,
    total_esperado,
)

__all__ = [
    "FaturaRecibo",
    "ErroFaturacao",
    "FaturaNaoCertificada",
    "TotalInesperado",
    "preco_liquido",
    "total_esperado",
    "obter_emissor",
    "PROVIDER_TOCONLINE",
    "PROVIDER_INVOICEXPRESS",
]

# Rótulos de `config.CHECKAL_FATURACAO_PROVIDER` (o default é o TOConline).
PROVIDER_TOCONLINE = "toconline"
PROVIDER_INVOICEXPRESS = "invoicexpress"

# Tipo do emissor agnóstico devolvido por `obter_emissor`.
Emissor = Callable[..., FaturaRecibo]


def obter_emissor() -> Emissor | None:
    """Compõe o emissor de faturas do fornecedor ativo, ou ``None`` (LIVE-GATED).

    Lê `config.CHECKAL_FATURACAO_PROVIDER` e devolve um *callable*
    ``emitir(*, nome, nif, email, itens, codigo_cliente=None, dormir=time.sleep)``
    que emite uma :class:`FaturaRecibo` certificada. É o **único** ponto que cria um
    cliente HTTP real.

    Devolve ``None`` (sem tocar na rede) quando:
      - `config.CHECKAL_MODO_TESTE` está ligado (o default nos testes), **ou**
      - faltam as credenciais do fornecedor ativo (o adaptador não pode ligar).

    Nesse caso quem chama injeta um emissor falso (testes) ou trata o ``None`` como
    "faturação indisponível". Em produção (modo de teste desligado + credenciais)
    devolve o *callable* real.
    """
    if config.CHECKAL_MODO_TESTE:
        return None

    provider = str(config.CHECKAL_FATURACAO_PROVIDER or PROVIDER_TOCONLINE).strip().lower()
    if provider == PROVIDER_TOCONLINE:
        return _emissor_toconline()
    if provider == PROVIDER_INVOICEXPRESS:
        return _emissor_invoicexpress()
    return None


# ==========================================================================
#  Fábricas por-fornecedor (o ÚNICO sítio que cria `httpx.Client` real)
# ==========================================================================
def _emissor_invoicexpress() -> Emissor | None:
    """Emissor InvoiceXpress: `httpx.Client` simples + `api_key` em query (LIVE-GATED)."""
    if not config.INVOICEXPRESS_API_KEY:
        return None

    import httpx  # import tardio: só quando de facto se liga em produção

    from app.faturacao import invoicexpress_client as ix

    def emitir(
        *,
        nome: str,
        nif: str,
        email: str,
        itens: Sequence[Mapping[str, Any]],
        codigo_cliente: str | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> FaturaRecibo:
        # `with` por emissão: o cliente HTTP é fechado após a fatura (evita fuga
        # de file descriptors ao longo do tempo em produção — um cliente por evento).
        with httpx.Client(timeout=30.0) as cliente_http:
            return ix.emitir_fatura_recibo(
                nome=nome,
                nif=nif,
                email=email,
                itens=itens,
                cliente_http=cliente_http,
                codigo_cliente=codigo_cliente,
                dormir=dormir,
            )

    return emitir


def _emissor_toconline() -> Emissor | None:
    """Emissor TOConline: obtém o Bearer (cron-store DB) e compõe o `httpx.Client` (LIVE-GATED).

    A obtenção/renovação do token vive em :mod:`app.faturacao.toconline_oauth`
    (:func:`garantir_access_token` sobre o armazém DB-backed :class:`ArmazemDB`) — o
    cron mantém a cadeia viva; aqui garante-se um access válido no momento da emissão.
    Sem as credenciais OAuth/API devolve ``None``; com elas mas com a cadeia OAuth
    quebrada (refresh expirado), `garantir_access_token` levanta `BootstrapNecessario`
    — **não** se emite silenciosamente sem token.
    """
    if not (
        config.TOCONLINE_OAUTH_URL
        and config.TOCONLINE_CLIENT_ID
        and config.TOCONLINE_CLIENT_SECRET
        and config.TOCONLINE_API_URL
    ):
        return None

    import httpx  # import tardio: só quando de facto se liga em produção

    from app.faturacao import toconline_client as toc
    from app.faturacao.toconline_oauth import ArmazemDB, garantir_access_token

    # Bearer válido no momento da composição (renova via refresh se preciso; a rotação
    # persiste no armazém). O cliente OAuth é efémero — só serve a chamada ao /token.
    with httpx.Client(timeout=30.0) as oauth_http:
        access_token = garantir_access_token(cliente_http=oauth_http, store=ArmazemDB())

    def emitir(
        *,
        nome: str,
        nif: str,
        email: str,
        itens: Sequence[Mapping[str, Any]],
        codigo_cliente: str | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> FaturaRecibo:
        # Cliente da API JSON:API aberto/fechado por emissão (evita fuga de fd). O
        # adaptador compõe os headers (Bearer + vnd.api+json) por-pedido a partir do
        # `access_token`, logo basta um cliente simples.
        with httpx.Client(timeout=30.0) as api_http:
            return toc.emitir_fatura_recibo(
                nome=nome,
                nif=nif,
                email=email,
                itens=itens,
                cliente_http=api_http,
                access_token=access_token,
                codigo_cliente=codigo_cliente,
                dormir=dormir,
            )

    return emitir
