"""Base de composição de emails do CheckAL (SPEC-FASE1-EMAILS §base).

A **fundação** de que todo o email do CheckAL depende. Expõe:

  * :class:`EmailRenderizado` — o resultado ``{assunto, html, texto}``;
  * :func:`render_email` — renderiza um template (que estende ``email_base.html``) e
    **garante** o rodapé/opt-out/remetente antes de devolver (levanta
    :class:`EmailInvalido` se faltarem);
  * :func:`url_optout` — a URL de opt-out 1-clique (``checkal.pt/remover?e=&t=``);
  * :data:`ESTADOS` + :func:`bloco_estado_html`/:func:`bloco_estado_texto` — os blocos
    reutilizáveis dos estados 🟢🟡🔴 (emoji + cor canónica do SPEC).

Disciplina (SPEC-FASE1-EMAILS §disciplina):
  * **HTML com CSS inline** (compat. cliente de email) + versão texto — sempre as duas;
  * header de marca por **HTML/CSS** (wordmark + ✓ verde ``#12B76A``), **sem imagem
    externa** — nada de `<img>`/CDN a ser bloqueado por clientes de email;
  * cada email leva SEMPRE, em HTML e em texto: **remetente identificado** (a marca),
    **rodapé legal** (Cosmic Oasis, Lda. · morada [placeholder]) e **opt-out 1-clique**;
  * os tokens de cor são os canónicos do SPEC — reexportados de :mod:`app.web.marca`,
    fonte única, para não haver deriva de marca entre web e email.

Pureza: importar este módulo **não** toca a rede nem a BD (só compila templates).
O envio real vive noutro lado (`app.envio` / `app.campanhas`), atrás de seams gated.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.web import marca

__all__ = [
    "EmailRenderizado",
    "EmailInvalido",
    "render_email",
    "url_optout",
    "ESTADOS",
    "bloco_estado_html",
    "bloco_estado_texto",
    "env",
    "TEMPLATES_DIR",
    "REMETENTE_NOME",
    "ENTIDADE_LEGAL",
    "MORADA",
]

# ==========================================================================
#  Tokens da marca no email (cor = fonte única em app.web.marca; sem deriva)
# ==========================================================================
REMETENTE_NOME = marca.NOME                     # "CheckAL" — o remetente identificado
ENTIDADE_LEGAL = "Cosmic Oasis, Lda."           # veículo legal (rodapé)
MORADA = "[morada]"                             # placeholder — a preencher antes de produção

# Clientes de email não carregam Google Fonts: pilha de sistema (SPEC-FASE1-WEB §tipografia).
FONTE_EMAIL = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"

# URLs legais (o link é sempre para checkal.pt; o opt-out é 1-clique).
URL_PRIVACIDADE = "https://checkal.pt/privacidade"
URL_TERMOS = "https://checkal.pt/termos"
URL_OPTOUT_BASE = "https://checkal.pt/remover"

# Disclaimer dos alertas — "informação, não aconselhamento" (parecer RGPD §7).
DISCLAIMER = (
    "Informação de monitorização a partir de dados públicos do RNAL; "
    "não constitui aconselhamento jurídico."
)

# Estados 🟢🟡🔴 — blocos reutilizáveis (emoji + cor canónica do SPEC-FASE1-WEB).
ESTADOS: dict[str, dict[str, str]] = {
    "verde": {"emoji": "\U0001F7E2", "cor": marca.COR_VERDE_CHECK, "rotulo": "passou no check"},
    "amarelo": {"emoji": "\U0001F7E1", "cor": marca.COR_AMBAR, "rotulo": "1 ponto sem check"},
    "vermelho": {"emoji": "\U0001F534", "cor": marca.COR_CORAL, "rotulo": "falhou o check"},
}

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


# ==========================================================================
#  Erros
# ==========================================================================
class EmailInvalido(RuntimeError):
    """Um email cujo HTML/texto perdeu o rodapé legal, o opt-out ou o remetente.

    A garantia da base é **dura**: nenhum email sai sem estes elementos. Se um
    template não estender ``email_base.html`` (ou lhe apagar o rodapé), :func:`render_email`
    recusa-se a devolvê-lo — para nunca enviarmos um email não-conforme.
    """


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class EmailRenderizado:
    """Um email pronto a entregar: assunto + corpo HTML (CSS inline) + versão texto."""

    assunto: str
    html: str
    texto: str


# ==========================================================================
#  Opt-out 1-clique
# ==========================================================================
def url_optout(email: str = "", token: str = "") -> str:
    """URL de opt-out 1-clique — ``https://checkal.pt/remover?e=<email>&t=<token>``.

    Sem argumentos devolve a forma canónica vazia (``…/remover?e=&t=``); com
    destinatário/token, ambos vão URL-encoded (o ``@`` vira ``%40``).
    """
    return f"{URL_OPTOUT_BASE}?e={quote(email, safe='')}&t={quote(token, safe='')}"


# ==========================================================================
#  Blocos de estado reutilizáveis (Python — para módulos que compõem em str)
# ==========================================================================
def bloco_estado_html(tipo: str, titulo: str, texto: str = "") -> str:
    """Cartão HTML (CSS inline) de um estado 🟢🟡🔴 — emoji + cor canónica + faixa lateral.

    `tipo` ∈ {"verde","amarelo","vermelho"}. Devolve *string* de HTML (o chamador
    injeta-a com ``| safe`` no corpo). Espelha a macro Jinja ``blocos.estado``.
    """
    e = ESTADOS[tipo]
    corpo = (
        f'<div style="margin-top:6px;color:{marca.COR_GRAFITE};">{texto}</div>'
        if texto
        else ""
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;margin:12px 0;">'
        "<tr><td style=\"padding:14px 16px;border-radius:10px;"
        f'background:{marca.COR_FUNDO_FRIO};border-left:4px solid {e["cor"]};">'
        f'<strong style="color:{e["cor"]};font-size:16px;">{e["emoji"]} {titulo}</strong>'
        f"{corpo}"
        "</td></tr></table>"
    )


def bloco_estado_texto(tipo: str, titulo: str, texto: str = "") -> str:
    """Versão texto simples de um bloco de estado: ``🟢 Título`` (+ linha de texto)."""
    e = ESTADOS[tipo]
    cabeca = f'{e["emoji"]} {titulo}'
    return f"{cabeca}\n{texto}".rstrip() if texto else cabeca


# ==========================================================================
#  Ambiente Jinja (puro — compila templates, não toca a rede)
# ==========================================================================
env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    # autoescape só no HTML; o .txt é texto puro (URLs/emojis renderizam crus).
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
)
# Globais partilhados por todos os templates de email (marca + tokens + estados).
env.globals.update(
    {
        "cores": marca.CORES,
        "cor_check": marca.COR_VERDE_CHECK,
        "estados": ESTADOS,
        "fonte": FONTE_EMAIL,
        "fundo": marca.COR_MARFIM,
        "remetente_nome": REMETENTE_NOME,
        "entidade_legal": ENTIDADE_LEGAL,
        "morada": MORADA,
        "url_privacidade": URL_PRIVACIDADE,
        "url_termos": URL_TERMOS,
        "disclaimer": DISCLAIMER,
    }
)


# ==========================================================================
#  Render + garantia
# ==========================================================================
def _ctx_completo(ctx: dict) -> dict:
    """Enriquece o contexto com o que a base precisa (opt-out) sem apagar o do chamador."""
    ctx = dict(ctx)
    if "url_optout" not in ctx:
        ctx["url_optout"] = url_optout(
            ctx.get("email_destinatario", ""), ctx.get("token_optout", "")
        )
    return ctx


def _sanitizar_assunto(assunto: str) -> str:
    """Torna o assunto seguro como **cabeçalho** de email (anti-injeção de header).

    O assunto pode derivar de dados NÃO confiáveis do RNAL (nome do AL/alojamento,
    n.º de registo). Um ``\\r``/``\\n`` embutido permitiria, no envio, injetar cabeçalhos
    (``Bcc:``, ``Subject:`` extra…). Colapsamos TODO o carácter de controlo C0/DEL
    (inclui CR, LF, TAB) num espaço e normalizamos — nenhum assunto legítimo os tem.
    """
    limpo = re.sub(r"[\x00-\x1f\x7f]+", " ", assunto)
    return re.sub(r"[ \t]{2,}", " ", limpo).strip()


def _extrair_assunto(html_tmpl, ctx: dict) -> str:
    """Assunto do email: do ``ctx["assunto"]`` (prioritário) OU do bloco ``{% block assunto %}``.

    Deixa o assunto viver OU no código que chama (copy dona do módulo) OU no próprio
    template (copy dona do template) — o que for mais natural para cada email. O resultado
    é sempre saneado (:func:`_sanitizar_assunto`) — nenhum assunto sai com CR/LF (header-safe).
    """
    do_ctx = ctx.get("assunto")
    if do_ctx:
        return _sanitizar_assunto(str(do_ctx))
    bloco = html_tmpl.blocks.get("assunto")
    if bloco is not None:
        return _sanitizar_assunto("".join(bloco(html_tmpl.new_context(vars=dict(ctx)))))
    return ""


def _garantir(html: str, texto: str) -> None:
    """Garante — em HTML **e** em texto — remetente + rodapé legal + opt-out. Senão, rebenta."""
    exigencias = (
        (REMETENTE_NOME, "remetente identificado"),
        (ENTIDADE_LEGAL, "rodapé legal (entidade)"),
        ("checkal.pt/remover", "opt-out 1-clique"),
    )
    faltas: list[str] = []
    for etiqueta, conteudo in (("html", html), ("texto", texto)):
        for agulha, descricao in exigencias:
            if agulha not in conteudo:
                faltas.append(f"{etiqueta}: falta {descricao}")
    if faltas:
        raise EmailInvalido("email não-conforme — " + "; ".join(faltas))


def _finalizar(html_tmpl, ctx: dict, *, nome: str | None = None, texto_forcado: str | None = None) -> EmailRenderizado:
    """Renderiza HTML+texto a partir de um template já carregado, garante e embrulha.

    `texto_forcado` curto-circuita a versão texto (usado quando o chamador já a tem);
    caso contrário procura ``{nome}.txt`` e, na sua ausência, deriva texto do HTML.
    """
    ctx = _ctx_completo(ctx)
    assunto = _extrair_assunto(html_tmpl, ctx)
    ctx["assunto"] = assunto
    html = html_tmpl.render(**ctx)

    if texto_forcado is not None:
        texto = texto_forcado
    elif nome is not None:
        try:
            texto = env.get_template(f"{nome}.txt").render(**ctx)
        except TemplateNotFound:
            texto = _html_para_texto(html)
    else:
        texto = _html_para_texto(html)

    _garantir(html, texto)
    return EmailRenderizado(assunto=assunto, html=html, texto=texto)


def render_email(nome_template: str, **ctx) -> EmailRenderizado:
    """Renderiza um template de email (que estende ``email_base.html``) → :class:`EmailRenderizado`.

    Procura ``{nome}.html`` (obrigatório) e ``{nome}.txt`` (para a versão texto; se faltar,
    deriva-se do HTML). O assunto vem de ``assunto=`` no `ctx` ou do bloco ``{% block assunto %}``.
    O opt-out compõe-se de ``email_destinatario=`` / ``token_optout=`` (ou passa-se ``url_optout=``).

    Levanta :class:`EmailInvalido` se o resultado perder o rodapé/opt-out/remetente —
    a garantia dura de que **nenhum email sai** sem estes elementos.
    """
    nome = nome_template[:-5] if nome_template.endswith(".html") else nome_template
    html_tmpl = env.get_template(f"{nome}.html")
    return _finalizar(html_tmpl, ctx, nome=nome)


# ==========================================================================
#  Fallback HTML → texto (usado só quando um template não traz par .txt)
# ==========================================================================
def _html_para_texto(html: str) -> str:
    """Conversão simples e determinística de HTML para texto (tira tags, mantém o conteúdo)."""
    txt = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    txt = re.sub(r"(?is)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?is)</(p|div|tr|h[1-6]|li)>", "\n", txt)
    txt = re.sub(r"(?is)<[^>]+>", "", txt)
    txt = _html.unescape(txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n[ \t]+", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()
