"""Envio transacional do CheckAL (Canal A): seam LIVE-GATED sobre a Resend.

O CheckAL entrega email transacional (onboarding, relatório, selo, alertas de
estado, dunning, respostas de suporte) por trás de **uma única interface** —
:class:`ResultadoEnvio` + :func:`enviar_email` — com um único adaptador:

    - :mod:`app.envio.resend_client` — `POST https://api.resend.com/emails`
      (Bearer `RESEND_API_KEY`; anexos PDF em base64; SPEC-RESEND §3.1).

Este pacote expõe o **ponto único de composição** — :func:`obter_enviador` — que o
onboarding/alertas usam sem conhecer o cliente HTTP. À imagem **exata** de
:func:`app.faturacao.obter_emissor`, devolve um *callable* já ligado ao HTTP:

    enviar(*, para, assunto, html, anexos=(), **kw) -> ResultadoEnvio

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** :func:`obter_enviador` é o
**único sítio** que cria um cliente HTTP real (`httpx.Client`). Sob
`config.CHECKAL_MODO_TESTE` **ou** sem `config.RESEND_API_KEY` devolve ``None`` —
pelo que correr os testes nunca toca a rede. Nos testes injeta-se um enviador falso
(um *callable* que devolve uma :class:`ResultadoEnvio`) em vez deste; a rede real só
liga em produção, quando o dono desliga o modo de teste e há chave.

Fronteira dura (SPEC-RESEND §0): a prospeção a frio (Canal B, `getcheckal.com`)
**nunca** passa por aqui — a AUP da Resend proíbe cold e um único lote pode
suspender a conta e derrubar todos os alertas dos clientes pagantes.
"""
from __future__ import annotations

from collections.abc import Callable

import app.config as config
from app.envio.resend_client import (
    RESEND_API,
    ErroEnvio,
    ResultadoEnvio,
    enviar_email,
)

__all__ = [
    "ResultadoEnvio",
    "ErroEnvio",
    "enviar_email",
    "RESEND_API",
    "obter_enviador",
]

# Tipo do enviador agnóstico devolvido por `obter_enviador`.
Enviador = Callable[..., ResultadoEnvio]


def obter_enviador() -> Enviador | None:
    """Compõe o enviador transacional (Resend), ou ``None`` (LIVE-GATED).

    Devolve um *callable* ``enviar(*, para, assunto, html, anexos=(), **kw)`` que
    entrega o email e devolve uma :class:`ResultadoEnvio`. É o **único** ponto que
    cria um cliente HTTP real.

    Devolve ``None`` (sem tocar na rede) quando:
      - `config.CHECKAL_MODO_TESTE` está ligado (o default nos testes), **ou**
      - falta `config.RESEND_API_KEY` (o adaptador não pode autenticar).

    Nesse caso quem chama injeta um enviador falso (testes) ou trata o ``None`` como
    "envio indisponível". Em produção (modo de teste desligado + chave) devolve o
    *callable* real.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    if not config.RESEND_API_KEY:
        return None

    import httpx  # import tardio: só quando de facto se liga em produção

    from app.envio import resend_client as rc

    def enviar(**kw) -> ResultadoEnvio:
        # `with` por envio: o cliente HTTP é fechado após o email (evita fuga de
        # file descriptors — um cliente por evento, como nos emissores de faturação).
        with httpx.Client(timeout=30.0) as cliente_http:
            return rc.enviar_email(cliente_http=cliente_http, **kw)

    return enviar
