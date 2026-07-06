"""Emails TRANSACIONAIS do CheckAL (SPEC-FASE1-EMAILS §transacional).

Os quatro emails do **Canal A** (Resend, `app.envio` — que este módulo NÃO importa):
compõem-se todos sobre :mod:`app.emails.base` (HTML com CSS inline + versão texto,
header de marca por HTML/CSS, rodapé/opt-out garantidos).

  * :func:`boas_vindas` — boas-vindas + linha dos 3 checks + link do selo + nota do
    Relatório Inicial (PDF anexado pelo onboarding);
  * :func:`alerta_estado` — o PRODUTO: estado 🟢/🟡/🔴, assunto conforme ``MARCA.md``,
    corpo determinístico OU da camada IA (apenas embrulhado — anti-alucinação), com o
    disclaimer "informação, não aconselhamento jurídico" (parecer §7);
  * :func:`relatorio_mensal` — a âncora anti-churn do dia 1 ("✅ {mês}: o teu AL passou
    no check — relatório CheckAL");
  * :func:`confirmacao_consentimento` — double opt-in (``checkal.pt/confirmar?token=``)
    que REFLETE o consentimento **granular** (alertas do serviço vs ofertas) — a CNPD
    rejeita consentimento global (LEGAL-PARECER §3).

Copy de ``../COPY-VENDAS.md`` / ``MARCA.md`` — não inventar. Pureza (LIVE-GATED):
importar este módulo não toca a rede nem a BD; **não envia** (o envio vive em
`app.envio`/`app.campanhas`, atrás de seams gated). Só produz :class:`EmailRenderizado`.
"""
from __future__ import annotations

from urllib.parse import quote

from app.emails import base
from app.emails.base import EmailRenderizado

__all__ = [
    "ASSUNTO_BOAS_VINDAS",
    "ASSUNTO_CONFIRMACAO",
    "LINHA_CHECKS",
    "URL_CONFIRMAR_BASE",
    "assunto_relatorio_mensal",
    "assunto_alerta",
    "url_confirmar",
    "boas_vindas",
    "alerta_estado",
    "relatorio_mensal",
    "confirmacao_consentimento",
]

# ==========================================================================
#  Assuntos canónicos (MARCA.md §remetente/assuntos — não inventar)
# ==========================================================================
ASSUNTO_BOAS_VINDAS = "✅ O teu AL passou no check — bem-vindo ao CheckAL"
ASSUNTO_CONFIRMACAO = "Confirma o teu email — CheckAL"

# Micro-copy dos 3 checks (MARCA.md) — a mesma linha no boas-vindas e no relatório.
LINHA_CHECKS = "Registo: check ✓ · Seguro: check ✓ · Regulamento: check ✓"

URL_CONFIRMAR_BASE = "https://checkal.pt/confirmar"


def assunto_relatorio_mensal(mes: str) -> str:
    """Assunto do relatório mensal — ``✅ {mês}: o teu AL passou no check — relatório CheckAL``."""
    return f"✅ {mes}: o teu AL passou no check — relatório CheckAL"


def assunto_alerta(nome_al: str, estado: str, facto: str = "") -> str:
    """Assunto do alerta, dependente do estado (MARCA.md §assunto de alerta).

    🔴 ``ALERTA CheckAL — o teu AL «{nome}» falhou o check: {facto}`` ·
    🟡 ``CheckAL — o teu AL «{nome}»: 1 ponto sem check[ — {facto}]`` ·
    🟢 ``CheckAL — o teu AL «{nome}» passou no check``.

    Levanta :class:`ValueError` para um estado fora de {verde, amarelo, vermelho}.
    """
    if estado not in base.ESTADOS:
        raise ValueError(
            f"estado inválido: {estado!r} (esperado um de {sorted(base.ESTADOS)})"
        )
    emoji = base.ESTADOS[estado]["emoji"]
    if estado == "vermelho":
        return f"{emoji} ALERTA CheckAL — o teu AL «{nome_al}» falhou o check: {facto}"
    if estado == "amarelo":
        cabeca = f"{emoji} CheckAL — o teu AL «{nome_al}»: 1 ponto sem check"
        return f"{cabeca} — {facto}" if facto else cabeca
    return f"{emoji} CheckAL — o teu AL «{nome_al}» passou no check"


def _url_confirmar(token: str = "") -> str:
    return f"{URL_CONFIRMAR_BASE}?token={quote(token, safe='')}"


def url_confirmar(token: str = "") -> str:
    """URL de confirmação do double opt-in — ``checkal.pt/confirmar?token=<token>`` (URL-encoded)."""
    return _url_confirmar(token)


def _paragrafos(corpo: str) -> list[str]:
    """Parte o corpo (determinístico ou da IA) em parágrafos, por linha em branco."""
    return [p.strip() for p in (corpo or "").split("\n\n") if p.strip()]


# ==========================================================================
#  Os quatro emails
# ==========================================================================
def boas_vindas(
    *,
    nome_al: str,
    nr_registo: str,
    url_selo: str,
    nome: str | None = None,
    url_fatura: str = "",
    selos_extra: "list[str] | tuple[str, ...]" = (),
    requer_atencao: bool = False,
    email_destinatario: str = "",
    token_optout: str = "",
) -> EmailRenderizado:
    """Email de boas-vindas do cliente (assunto fixo :data:`ASSUNTO_BOAS_VINDAS`).

    Slots opcionais preenchidos pelo onboarding (dados, não HTML ad-hoc): `url_fatura`
    (permalink da fatura-recibo certificada), `selos_extra` (selos dos registos além do
    primeiro, para portfólios) e `requer_atencao` (ressalva do ponto semi-manual — G4:
    nunca afirma "cancelado").
    """
    return base.render_email(
        "boas_vindas",
        assunto=ASSUNTO_BOAS_VINDAS,
        nome=nome,
        nome_al=nome_al,
        nr_registo=nr_registo,
        url_selo=url_selo,
        url_fatura=url_fatura,
        selos_extra=list(selos_extra),
        requer_atencao=requer_atencao,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


def alerta_estado(
    *,
    nome_al: str,
    estado: str,
    facto: str = "",
    titulo: str = "",
    corpo: str = "",
    assunto: str = "",
    cta_texto: str = "",
    cta_url: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
) -> EmailRenderizado:
    """Alerta 🟢/🟡/🔴 do produto. `corpo` vem da camada IA/determinístico — o template só o embrulha.

    Por omissão o assunto sai de :func:`assunto_alerta` (formato canónico do MARCA.md). O
    *wire* dos módulos de origem (alertas de estado do registo, pipeline regulatório) pode
    passar um `assunto` próprio — factual e mais claro para eventos que não são "falhou o
    check" — sem perder a validação do estado. O disclaimer "informação, não aconselhamento
    jurídico" (parecer §7) é fixo no template.
    """
    if estado not in base.ESTADOS:
        raise ValueError(
            f"estado inválido: {estado!r} (esperado um de {sorted(base.ESTADOS)})"
        )
    assunto = assunto or assunto_alerta(nome_al, estado, facto)  # valida/deriva o assunto
    return base.render_email(
        "alerta_estado",
        assunto=assunto,
        nome_al=nome_al,
        estado=estado,
        facto=facto,
        titulo=titulo or f"O teu AL «{nome_al}»",
        corpo_paragrafos=_paragrafos(corpo),
        cta_texto=cta_texto,
        cta_url=cta_url,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


def relatorio_mensal(
    *,
    mes: str,
    nome_al: str,
    nome: str | None = None,
    resumo: str = "",
    n_analisadas: int | None = None,
    n_relevantes: int | None = None,
    cta_texto: str = "",
    cta_url: str = "",
    email_destinatario: str = "",
    token_optout: str = "",
) -> EmailRenderizado:
    """Relatório mensal "Tudo em ordem" (dia 1). NÃO é alerta: sem disclaimer de aconselhamento."""
    return base.render_email(
        "relatorio_mensal",
        assunto=assunto_relatorio_mensal(mes),
        mes=mes,
        nome_al=nome_al,
        nome=nome,
        resumo=resumo,
        n_analisadas=n_analisadas,
        n_relevantes=n_relevantes,
        cta_texto=cta_texto,
        cta_url=cta_url,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )


def confirmacao_consentimento(
    *,
    token: str = "",
    url_confirmar: str = "",
    consente_alertas: bool = True,
    consente_ofertas: bool = False,
    nome: str | None = None,
    email_destinatario: str = "",
    token_optout: str = "",
) -> EmailRenderizado:
    """Double opt-in que reflete o consentimento **granular** dado no widget.

    Passa `url_confirmar` pronta OU um `token` (dá origem a ``checkal.pt/confirmar?token=``).
    Só lista as finalidades efetivamente consentidas (alertas do serviço / ofertas).
    """
    url = url_confirmar or _url_confirmar(token)
    return base.render_email(
        "confirmacao_consentimento",
        assunto=ASSUNTO_CONFIRMACAO,
        url_confirmar=url,
        consente_alertas=consente_alertas,
        consente_ofertas=consente_ofertas,
        nome=nome,
        email_destinatario=email_destinatario,
        token_optout=token_optout,
    )
