"""Templates de email de **dunning** do CheckAL (SPEC-FASE1-EMAILS §dunning).

A régua de renovação/cobrança vestida com a marca — HTML (CSS inline) + versão texto,
composta sobre :mod:`app.emails.base` (header por HTML/CSS, rodapé legal + opt-out garantidos).
Cada função devolve um :class:`app.emails.base.EmailRenderizado` pronto a entregar; **nada aqui
envia** — o envio vive no cron ``app.dunning`` (que injeta o *callable* de ``app.envio``, gated).

Passos (alinhados com ``AUTOMACAO.md §5`` e a máquina de estados de ``app/dunning.py``):

  * :func:`renovacao_d30`  — **D-30**: "a tua proteção renova a {data}" + resumo do valor entregue;
  * :func:`aviso_d7`       — **D-7**: a cobrança é iminente, confirma o cartão;
  * :func:`falha_pagamento`— **D+3 / D+7**: a cobrança falhou → **link para atualizar o cartão**
    (portal Stripe/área de cliente); o D+7 avisa que a monitorização será suspensa;
  * :func:`cancelado_final`— **D+21**: "o teu AL deixou de estar monitorizado" + porta de reativação.

Dunning é **comunicação de faturação** de um cliente ativo — leva o disclaimer
:data:`DISCLAIMER_FATURACAO` ("não constitui aconselhamento jurídico"), não a nota de alerta.

Pureza (LIVE-GATED): importar/renderizar só compila templates — não toca a rede nem a BD.
"""
from __future__ import annotations

from app.emails.base import EmailRenderizado, render_email

__all__ = [
    "renovacao_d30",
    "aviso_d7",
    "falha_pagamento",
    "cancelado_final",
    "render_passo",
    "DISCLAIMER_FATURACAO",
    "PASSO_D30",
    "PASSO_D7",
    "PASSO_D3",
    "PASSO_D7_POS",
    "PASSO_D21",
    "PASSOS_FALHA",
]

# Rótulos dos passos — mesmos valores da máquina de estados em ``app/dunning.py``,
# para o *wire* poder mapear passo → template sem tradução.
PASSO_D30 = "D-30"      # aviso de renovação (pré-cobrança)
PASSO_D7 = "D-7"        # segundo aviso (pré-cobrança)
PASSO_D3 = "D+3"        # 1.º email de falha (pós-cobrança falhada)
PASSO_D7_POS = "D+7"    # 2.º email de falha (pós-cobrança falhada)
PASSO_D21 = "D+21"      # downgrade cancelado + email final (win-back)

PASSOS_FALHA = (PASSO_D3, PASSO_D7_POS)

# Disclaimer dos emails de faturação — dunning é uma comunicação da subscrição do cliente,
# não um alerta regulatório; mesma redação usada em ``app/dunning.py`` (parecer RGPD §7).
DISCLAIMER_FATURACAO = (
    "Recebes este email porque tens uma subscrição CheckAL — é uma comunicação de "
    "faturação da tua subscrição, não constitui aconselhamento jurídico."
)


def _render(nome_template: str, **ctx) -> EmailRenderizado:
    """Renderiza um template de dunning, injetando o disclaimer de faturação no contexto."""
    ctx.setdefault("disclaimer_faturacao", DISCLAIMER_FATURACAO)
    return render_email(nome_template, **ctx)


# ==========================================================================
#  D-30 — aviso de renovação (+ resumo do valor entregue, anti-churn)
# ==========================================================================
def renovacao_d30(
    *,
    nome: str = "titular",
    plano_nome: str = "CheckAL",
    data_renovacao: str = "",
    preco: str = "",
    url_gerir: str = "",
    resumo_valor: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
    **_ignorado,
) -> EmailRenderizado:
    """Email **D-30**: a subscrição renova a ``data_renovacao`` por ``preco``.

    ``resumo_valor`` é a frase factual do valor entregue no ciclo (nº de varrimentos/alertas,
    já composta pelo chamador) — reduz o churn ao lembrar o que a subscrição fez.
    """
    return _render(
        "dunning_renovacao_d30",
        nome=nome,
        plano_nome=plano_nome,
        data_renovacao=data_renovacao,
        preco=preco,
        url_gerir=url_gerir,
        resumo_valor=resumo_valor,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


# ==========================================================================
#  D-7 — a cobrança é iminente; confirma o cartão
# ==========================================================================
def aviso_d7(
    *,
    nome: str = "titular",
    plano_nome: str = "CheckAL",
    data_renovacao: str = "",
    preco: str = "",
    url_gerir: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
    **_ignorado,
) -> EmailRenderizado:
    """Email **D-7**: a renovação (``preco``) será cobrada a ``data_renovacao`` — confirma o cartão."""
    return _render(
        "dunning_aviso_d7",
        nome=nome,
        plano_nome=plano_nome,
        data_renovacao=data_renovacao,
        preco=preco,
        url_gerir=url_gerir,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


# ==========================================================================
#  D+3 / D+7 — a cobrança falhou; link para atualizar o cartão
# ==========================================================================
def falha_pagamento(
    *,
    passo: str,
    nome: str = "titular",
    preco: str = "",
    url_gerir: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
    **_ignorado,
) -> EmailRenderizado:
    """Email de **falha de cobrança** — ``passo`` ∈ {``"D+3"``, ``"D+7"``}.

    ``url_gerir`` é o link do portal (Stripe/área de cliente) para **atualizar o método de
    pagamento**. O D+7 sobe a urgência e avisa que a monitorização será suspensa.

    Levanta :class:`ValueError` se ``passo`` não for um passo de falha.
    """
    if passo not in PASSOS_FALHA:
        raise ValueError(
            f"passo de falha inválido: {passo!r} (esperado um de {PASSOS_FALHA})"
        )
    return _render(
        "dunning_falha_pagamento",
        passo=passo,
        nome=nome,
        preco=preco,
        url_gerir=url_gerir,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


# ==========================================================================
#  D+21 — cancelado: monitorização suspensa + porta de reativação (win-back)
# ==========================================================================
def cancelado_final(
    *,
    nome: str = "titular",
    url_gerir: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
    **_ignorado,
) -> EmailRenderizado:
    """Email **D+21**: a monitorização foi suspensa; ``url_gerir`` reativa (atualizar pagamento)."""
    return _render(
        "dunning_cancelado_final",
        nome=nome,
        url_gerir=url_gerir,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


# ==========================================================================
#  Dispatcher por passo (conveniência para o wire de app/dunning.py)
# ==========================================================================
def render_passo(passo: str, **ctx) -> EmailRenderizado:
    """Devolve o email do ``passo`` de dunning (aceita um contexto comum; ignora chaves a mais).

    Mapeia o rótulo da máquina de estados (``D-30``/``D-7``/``D+3``/``D+7``/``D+21``) para o
    builder certo. Levanta :class:`ValueError` num passo desconhecido.
    """
    if passo == PASSO_D30:
        return renovacao_d30(**ctx)
    if passo == PASSO_D7:
        return aviso_d7(**ctx)
    if passo in PASSOS_FALHA:
        return falha_pagamento(passo=passo, **ctx)
    if passo == PASSO_D21:
        return cancelado_final(**ctx)
    raise ValueError(f"passo de dunning desconhecido: {passo!r}")
