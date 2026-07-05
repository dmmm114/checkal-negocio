"""Remetente frio (Canal B, `getcheckal.com`) — FDS 6, PARECER-GATED.

Fronteira do módulo (SPEC-FDS6.md §cold_email + `app/envio/SPEC-RESEND.md` §7):
recebe um email de prospeção já composto (assunto + HTML) e entrega-o por um SMTP
**dedicado ao cold** — o domínio irmão `getcheckal.com` (`config.COLD_SMTP_*`) —,
carimbando em cada peça o remetente identificado (`config.COLD_FROM`) e o opt-out
1-clique (`checkal.pt/remover`), no corpo E nos headers `List-Unsubscribe`/
`List-Unsubscribe-Post` (RFC 8058). Devolve um :class:`ResultadoFrio`.

🚦 **O PORTÃO é CÓDIGO, não disciplina** (o coração deste sprint). O canal frio é
PROIBIDO até o dono ter o parecer favorável do jurista RGPD (CLAUDE.md / LEGAL.md
§1). :func:`obter_remetente_frio` devolve ``None`` — e NENHUM email frio sai —
enquanto `config.pode_enviar_frio_global()` for False, i.e. enquanto não houver,
CUMULATIVAMENTE: parecer OK (`CHECKAL_PARECER_RGPD_OK`) **e** modo de teste OFF
(`CHECKAL_MODO_TESTE`) **e** SMTP de cold configurado (`cold_smtp_ativo`). Este
gate GLOBAL é a montante do núcleo de compliance por-contacto (`app.compliance.*`):
mesmo com ele aberto, cada destinatário ainda tem de ser coletiva 5/6 com email
genérico não-oposto — isso é decidido pelo motor, a montante deste seam.

FRONTEIRA DURA (SPEC-RESEND §0): este módulo **NUNCA** importa nem toca o canal A
transacional (Resend / `app.envio`). Partilhar domínio, provedor ou reputação com
`checkal.pt` violaria a AUP da Resend (que proíbe cold) e um único lote poderia
suspender a conta e derrubar os alertas de todos os clientes pagantes — por isso o
cold vive num provedor SMTP próprio de `getcheckal.com`, descartável e isolado. As
env vars são PRÓPRIAS (`COLD_SMTP_*`/`COLD_FROM`), jamais `RESEND_*`/`EMAIL_FROM`.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria
nenhum cliente SMTP — o `cliente_smtp` de :func:`enviar_frio` é sempre **injetado**
por quem chama (mock nos testes; `smtplib.SMTP` real só em produção, composto por
:func:`obter_remetente_frio` depois do triplo gate). Assim, correr os testes nunca
toca a rede.

O `cliente_smtp` é qualquer objeto à laia de `smtplib.SMTP` com:
  - ``send_message(msg) -> dict``  (dict vazio = todos aceites; não-vazio =
    recipientes recusados — mapeia endereço → (código, resposta)).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from urllib.parse import quote

import app.config as config

# Re-exportação do PORTÃO global (superfície pública — SPEC §cold_email). É o
# MESMO objeto de `config`, pelo que lê os globals do config em tempo de chamada
# (monkeypatch-friendly): parecer OK E modo de teste OFF E SMTP de cold ativo.
pode_enviar_frio_global = config.pode_enviar_frio_global

__all__ = [
    "ResultadoFrio",
    "ErroFrio",
    "enviar_frio",
    "obter_remetente_frio",
    "pode_enviar_frio_global",
    "link_remocao",
    "MARCADOR_RODAPE",
]

# Base do direito de oposição de 1 clique (LEGAL.md §37 / COPY-VENDAS.md): URL
# curto, sem login, sem fricção. O destinatário vai no query-string para o
# opt-out ser verdadeiramente 1-clique (identifica quem remover).
LINK_REMOCAO_BASE = "https://checkal.pt/remover"

# Marcador (comentário HTML) do rodapé de opt-out acrescentado por ESTE seam.
# Serve para não duplicar o opt-out quando a copy já traz o link, e para os
# testes provarem que o seam garante a presença do link.
MARCADOR_RODAPE = "<!-- checkal:rgpd-optout -->"


class ErroFrio(RuntimeError):
    """O SMTP recusou o destinatário — envio a frio não confirmável."""


@dataclass(frozen=True)
class ResultadoFrio:
    """Resultado mínimo de um envio a frio aceite pelo SMTP dedicado.

    Guarda o essencial para auditoria/prova (a proveniência do contacto e o
    cruzamento opt-out ficam a montante, no motor): destinatário, remetente
    identificado e o link de opt-out efetivamente carimbado na peça.
    """

    para: str
    remetente: str
    link_remocao: str
    recusados: dict = field(default_factory=dict)


# ==========================================================================
#  Opt-out 1-clique — link + rodapé garantidos pelo seam (compliance é código)
# ==========================================================================
def link_remocao(para: str) -> str:
    """URL de opt-out 1-clique para o destinatário `para` (`checkal.pt/remover`).

    O endereço vai codificado no query-string para o clique identificar quem
    remover, sem login (LEGAL.md §37). É este link que entra no corpo E nos
    headers `List-Unsubscribe`.
    """
    return f"{LINK_REMOCAO_BASE}?e={quote(para, safe='')}"


def _rodape_html(link: str) -> str:
    """Rodapé mínimo de opt-out acrescentado pelo seam quando a copy não o traz.

    Garante — em código — a presença do direito de oposição de 1 clique. A
    identificação completa do responsável (Cosmic Oasis, NIPC, morada) é da copy
    (COPY-VENDAS.md / LEGAL.md §46); aqui garante-se apenas o meio de oposição.
    """
    return (
        f'{MARCADOR_RODAPE}'
        f'<hr>'
        f'<p style="font-size:12px;color:#666">'
        f'Recebeu este email por operar um Alojamento Local registado no RNAL. '
        f'Para não voltar a ser contactado, remova-se num clique: '
        f'<a href="{link}">checkal.pt/remover</a>.'
        f'</p>'
    )


def _corpo_com_opt_out(html: str, link: str) -> str:
    """Devolve o HTML garantindo a presença do opt-out `checkal.pt/remover`.

    Se a copy já incluir o link, respeita-a (não duplica o rodapé); senão,
    acrescenta o rodapé do seam. O link nos headers é sempre garantido à parte.
    """
    if "checkal.pt/remover" in html:
        return html
    return html + _rodape_html(link)


def _texto_com_opt_out(texto: str, link: str) -> str:
    """Alternativa em texto simples, também com o opt-out garantido."""
    base = texto.strip()
    if "checkal.pt/remover" in base:
        return base
    linha = f"Para não voltar a ser contactado, remova-se: {link}"
    return f"{base}\n\n{linha}" if base else linha


# ==========================================================================
#  API pública — envio (cliente SMTP INJETADO) + composição do seam (gated)
# ==========================================================================
def enviar_frio(
    *,
    para: str,
    assunto: str,
    html: str,
    cliente_smtp: object,
    de: str | None = None,
    texto: str | None = None,
) -> ResultadoFrio:
    """Envia UM email de prospeção a frio pelo `cliente_smtp` injetado.

    Constrói uma :class:`email.message.EmailMessage` (multipart/alternative:
    texto + HTML) com:
      - **From** = `de` ou `config.COLD_FROM` (getcheckal.com — remetente
        identificado; NUNCA `checkal.pt`);
      - **List-Unsubscribe** + **List-Unsubscribe-Post: List-Unsubscribe=One-Click**
        (RFC 8058) apontando ao `checkal.pt/remover` do destinatário;
      - o mesmo link de opt-out garantido no corpo (rodapé do seam se a copy não
        o trouxer).
    Depois chama `cliente_smtp.send_message(msg)`. Se o SMTP recusar o
    destinatário, levanta :class:`ErroFrio` (envio não confirmável).

    Parâmetros
    ----------
    para:
        Destinatário — email genérico de pessoa coletiva (elegibilidade decidida
        a montante pelo núcleo de compliance; aqui não se revalida).
    assunto, html:
        Assunto e corpo HTML já compostos (copy de COPY-VENDAS.md).
    cliente_smtp:
        Cliente SMTP **injetado** (mock nos testes; `smtplib.SMTP` real só em
        produção, via :func:`obter_remetente_frio` — LIVE-GATED). Nunca criado aqui.
    de:
        Remetente `Nome <email>`; por omissão `config.COLD_FROM` (getcheckal.com).
    texto:
        Alternativa em texto simples (opcional); o opt-out é garantido também aqui.

    Levanta
    -------
    ErroFrio
        O SMTP devolveu o destinatário como recusado (envio não confirmável).
    """
    remetente = de or config.COLD_FROM
    link = link_remocao(para)

    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = para
    msg["Subject"] = assunto
    # Opt-out 1-clique também ao nível do protocolo (RFC 8058) — não só no corpo.
    msg["List-Unsubscribe"] = f"<{link}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.set_content(_texto_com_opt_out(texto or "", link))
    msg.add_alternative(_corpo_com_opt_out(html, link), subtype="html")

    recusados = cliente_smtp.send_message(msg) or {}
    if recusados:
        raise ErroFrio(
            f"SMTP de cold recusou o destinatário {para!r}: {recusados!r}"
        )
    return ResultadoFrio(
        para=para, remetente=remetente, link_remocao=link, recusados=dict(recusados)
    )


# Tipo do remetente frio agnóstico devolvido por `obter_remetente_frio`.
RemetenteFrio = Callable[..., ResultadoFrio]


def obter_remetente_frio() -> RemetenteFrio | None:
    """Compõe o remetente frio (SMTP `getcheckal.com`), ou ``None`` (GATED).

    🚦 Devolve ``None`` — e NENHUM email frio sai — enquanto
    `config.pode_enviar_frio_global()` for False, i.e. sem, CUMULATIVAMENTE:
    parecer RGPD favorável, modo de teste OFF e SMTP de cold configurado. É o
    **único** ponto que cria um cliente `smtplib.SMTP` real; sob qualquer gate
    fechado (o default, incluindo todos os testes) nunca toca a rede.

    Com os três gates abertos, devolve um *callable*
    ``enviar(*, para, assunto, html, de=None, texto=None) -> ResultadoFrio`` que
    abre uma ligação SMTP dedicada (STARTTLS na 587, ou TLS implícito na 465),
    autentica e delega em :func:`enviar_frio`. Fecha a ligação por envio (um
    cliente por peça — sem fuga de descritores), à imagem de
    :func:`app.envio.obter_enviador`.
    """
    if not config.pode_enviar_frio_global():
        return None

    # Import tardio: só quando de facto se liga em produção (mantém o módulo sem
    # dependências de rede à importação e os testes 100% offline).
    import smtplib

    def enviar(**kw) -> ResultadoFrio:
        # `with` por envio: a ligação SMTP fecha após a peça (um cliente por
        # email — warm-up/throttle são geridos a montante, no motor/operação).
        if config.COLD_SMTP_PORT == 465:
            gestor = smtplib.SMTP_SSL(
                config.COLD_SMTP_HOST, config.COLD_SMTP_PORT, timeout=30.0
            )
            starttls = False
        else:
            gestor = smtplib.SMTP(
                config.COLD_SMTP_HOST, config.COLD_SMTP_PORT, timeout=30.0
            )
            starttls = True
        with gestor as cliente_smtp:
            if starttls:
                cliente_smtp.starttls()
            cliente_smtp.login(config.COLD_SMTP_USER, config.COLD_SMTP_PASS)
            return enviar_frio(cliente_smtp=cliente_smtp, **kw)

    return enviar
