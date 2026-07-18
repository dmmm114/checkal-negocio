"""Sequência de COLD B2B do CheckAL (SPEC-FASE1-EMAILS §prospeccao) — ⚠️ PARECER-GATED.

Este módulo é **só o template** da prospeção a frio a pessoa **coletiva**: compõe as três
peças da cadência (D+0, D+4, D+10 — copy de `COPY-VENDAS.md §2`) prontas a entregar. **NÃO
envia**: o envio é do `app.campanhas.cold_email` (FDS6), triplamente gated (parecer RGPD OK
+ modo de teste OFF + SMTP dedicado). Este pacote apenas devolve :class:`PecaFria`.

Fronteiras inegociáveis (LEGAL-PARECER-DECISOES.md · CLAUDE.md · task):

  * **Remetente = `getcheckal.com`** (:data:`REMETENTE`, de ``config.COLD_FROM``) — o cold
    JAMAIS parte de ``checkal.pt``: partilhar domínio/reputação com o canal transacional
    violaria a AUP da Resend e um lote de cold poderia derrubar os alertas dos clientes.
  * **NUNCA importa `app.envio`** (Resend) nem abre SMTP — este módulo é puro (compila
    templates; não toca a rede nem a BD).
  * Cada peça leva SEMPRE: **disclaimer de independência** no topo ("serviço privado … não é
    uma notificação oficial"), **nota RGPD** (Anexo 1 corrigido, :data:`NOTA_RGPD`) e
    **opt-out 1-clique** (``checkal.pt/remover`` — garantido pelo rodapé da base).
  * A nota RGPD **NÃO afirma** que o email é "público por imposição do art. 10.º": a base
    legal da *fonte* do contacto está por confirmar (parecer §2/§5). Afirmá-la seria falso
    até validação documental — por isso a nota descreve a origem (RNAL) sem invocar essa base.
  * **Sem inventar dados** (anti-alucinação): o merge só escreve o que vem no prospeto; campo
    em falta → frase neutra, nunca um valor fabricado. Merge do RNAL não é confiável → todo o
    valor injetado em HTML é escapado (anti-XSS).
"""
from __future__ import annotations

import html as _html
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

import app.config as config
from app.emails import base
from app.web import marca

__all__ = [
    "REMETENTE",
    "NOTA_RGPD",
    "DISCLAIMER_INDEPENDENCIA",
    "SEQUENCIA",
    "PecaFria",
    "render_passo",
    "render_sequencia",
]

# ==========================================================================
#  Remetente — SEMPRE getcheckal.com (fronteira dura Resend/AUP)
# ==========================================================================
# Fonte única: `config.COLD_FROM` (default "CheckAL <geral@getcheckal.com>"). O envio real
# usa este mesmo valor como `de=` em `cold_email.enviar_frio` (gated).
REMETENTE = config.COLD_FROM

# ==========================================================================
#  Copy fixa de conformidade (redação canónica — COPY-VENDAS.md §2 / parecer §5)
# ==========================================================================
# Disclaimer de independência — 1.ª dobra, obrigatório em cada peça (versão email).
DISCLAIMER_INDEPENDENCIA = (
    "O CheckAL é um serviço privado e independente de monitorização de Alojamento Local, "
    "sem qualquer vínculo ao Turismo de Portugal, ao RNAL ou a qualquer câmara municipal. "
    "Este email não é uma notificação oficial."
)

# Nota RGPD (Anexo 1 CORRIGIDO — LEGAL-PARECER-DECISOES.md §5). Descreve a origem (RNAL) e a
# base legal do *tratamento* (interesse legítimo), mas **NÃO** afirma que o email é público
# "por imposição do art. 10.º" — essa base está por confirmar documentalmente (parecer §2).
# Conservação a 6 meses para quem nunca interage (§5); a lista de supressão conserva-se à parte.
# Fecha com o disclaimer "informação, não aconselhamento" (linter R7 — exigido em canal COLD).
NOTA_RGPD = (
    f"Proteção de dados: o CheckAL é operado por {base.ENTIDADE_LEGAL} O contacto desta "
    "mensagem foi obtido no Registo Nacional de Alojamento Local (RNAL). Tratamos apenas o "
    "endereço de email e os dados de registo do estabelecimento, ao abrigo do interesse "
    "legítimo (art. 6.º, n.º 1, al. f) do RGPD): informar titulares de Alojamento Local "
    "sobre um serviço diretamente relacionado com a sua atividade. Os dados podem ser "
    "tratados por subcontratantes de envio de email e de alojamento, sob contrato e com "
    "garantias adequadas de proteção de dados. Conservamos estes dados por um máximo de "
    "6 meses ou até à sua oposição, o que ocorrer primeiro. Pode opor-se num clique, sem "
    "custos, em checkal.pt/remover. Tem ainda direito de acesso, retificação, apagamento e "
    "limitação, e o direito de apresentar queixa à CNPD (cnpd.pt). Política de privacidade "
    "completa: checkal.pt/privacidade. Os conteúdos do CheckAL são informação a partir de "
    "fontes públicas; não constituem aconselhamento jurídico."
)

# Cadência da sequência (COPY-VENDAS.md §2): D+0, prova social D+4, caso real D+10.
SEQUENCIA: tuple[str, ...] = ("d0", "d4", "d10")
_DIAS: dict[str, int] = {"d0": 0, "d4": 4, "d10": 10}


# ==========================================================================
#  Peça composta (o que o motor entrega ao `cold_email.enviar_frio`, gated)
# ==========================================================================
@dataclass(frozen=True)
class PecaFria:
    """Uma peça da cadência de cold, pronta a entregar (mas ainda NÃO enviada).

    O motor de campanhas (FDS6) passa `para`/`remetente`/`email.assunto`/`email.html`/
    `email.texto` a `cold_email.enviar_frio(...)` — que só sai com o triplo gate aberto.
    """

    passo: str                      # "d0" | "d4" | "d10"
    dia: int                        # offset em dias (0 | 4 | 10)
    para: str                       # email genérico do prospeto (coletiva); "" se ausente
    remetente: str                  # sempre REMETENTE (getcheckal.com)
    email: base.EmailRenderizado    # assunto + html (CSS inline) + texto


# ==========================================================================
#  Extração tolerante do prospeto (dict OU objeto) — sem inventar dados
# ==========================================================================
def _valor(prospeto: object, *chaves: str) -> str:
    """Primeiro valor não vazio entre `chaves`, de um Mapping ou de atributos (senão "")."""
    for chave in chaves:
        if isinstance(prospeto, Mapping):
            valor = prospeto.get(chave)
        else:
            valor = getattr(prospeto, chave, None)
        if valor is not None and str(valor).strip() != "":
            return str(valor).strip()
    return ""


def _campos(prospeto: object) -> dict[str, str]:
    """Campos de merge do prospeto (tudo str; ausência → "")."""
    return {
        "nr": _valor(prospeto, "nr_registo", "NrRegisto", "nr", "numero"),
        "empresa": _valor(prospeto, "nome", "Nome", "NomeEmpresa", "empresa", "titular_nome"),
        "alojamento": _valor(
            prospeto, "nome_alojamento", "NomeAlojamento", "alojamento", "estabelecimento"
        ),
        "concelho": _valor(prospeto, "concelho", "Concelho"),
        "email": _valor(
            prospeto, "email", "Email", "email_generico", "EmailGeral", "email_titular"
        ),
    }


# ==========================================================================
#  Helpers de composição (merge escapado; link do relatório)
# ==========================================================================
def _esc(valor: str) -> str:
    """Escapa um valor de merge (RNAL, não confiável) para injeção segura em HTML."""
    return _html.escape(valor)


_ESTILO_P = f"margin:0 0 14px 0;font-size:16px;line-height:1.62;color:{marca.COR_GRAFITE};"


def _p(inner: str) -> str:
    """Um parágrafo do corpo, com estilo inline (o `inner` já traz o merge escapado)."""
    return f'<p style="{_ESTILO_P}">{inner}</p>'


def _link_relatorio(nr: str) -> tuple[str, str]:
    """Link para o relatório gratuito — (html, texto). Sem nr → cai no domínio base."""
    estilo = f"color:{marca.COR_AZUL_ACAO};font-weight:600;text-decoration:underline;"
    if nr:
        href = f"https://checkal.pt/v/{quote(nr, safe='/')}"
        html = f'<a href="{_esc(href)}" style="{estilo}">checkal.pt/v/{_esc(nr)}</a>'
        return html, f"checkal.pt/v/{nr}"
    return f'<a href="https://checkal.pt" style="{estilo}">checkal.pt</a>', "checkal.pt"


# ==========================================================================
#  Corpo de cada peça — (assunto, corpo_html, corpo_texto). Copy: COPY-VENDAS §2.
# ==========================================================================
def _fmt_eur(v: int) -> str:
    """25000 -> '25.000' (milhares à portuguesa) — só valores de `config.COIMA`."""
    return f"{v:,}".replace(",", ".")


def _d0(c: dict[str, str]) -> tuple[str, str, str]:
    nr, empresa, concelho, aloj = c["nr"], c["empresa"], c["concelho"], c["alojamento"]

    titulo_aloj = aloj or "O vosso Alojamento Local"
    assunto = titulo_aloj + (f" — registo {nr}" if nr else "") + ": quem vigia os prazos?"

    sujeito_html = f"A <strong>{_esc(empresa)}</strong>" if empresa else "A empresa titular"
    sujeito_txt = f"A {empresa}" if empresa else "A empresa titular"
    loc_html = f" ({_esc(concelho)})" if concelho else ""
    loc_txt = f" ({concelho})" if concelho else ""
    if nr:
        reg_html = f"{sujeito_html} é titular do registo de AL n.º {_esc(nr)}{loc_html}."
        reg_txt = f"{sujeito_txt} é titular do registo de AL n.º {nr}{loc_txt}."
    else:
        reg_html = f"{sujeito_html} é titular de um registo de Alojamento Local{loc_html}."
        reg_txt = f"{sujeito_txt} é titular de um registo de Alojamento Local{loc_txt}."
    link_html, link_txt = _link_relatorio(nr)

    # RT-copy: linguagem de serviço genérica e condicional — sem caracterizações
    # jurídicas do destinatário; coimas SÓ de config.COIMA (fonte única) e nunca
    # na mesma frase (nem adjacente) que o identificador do registo/empresa.
    coima_lo, coima_hi = config.COIMA["coletiva"]
    frase_contexto = (
        "Contexto rápido: desde março de 2025 a prova anual do seguro é obrigatória, "
        "e as câmaras já cancelaram mais de 10.000 registos, sobretudo por falta de "
        "comunicação do seguro. No regime aplicável às pessoas coletivas, as coimas "
        f"previstas podem ir de {_fmt_eur(coima_lo)}€ a {_fmt_eur(coima_hi)}€."
    )

    corpo_html = "\n".join([
        _p("Bom dia,"),
        _p(f"{reg_html} Encontrámo-lo na lista pública do RNAL — é isso que fazemos: "
           "vigiamos os 120.000+ registos do país."),
        _p(frase_contexto),
        _p("O CheckAL monitoriza semanalmente o estado do registo, o prazo do seguro e os "
           "regulamentos do concelho, e envia alertas interpretados: «isto afeta o vosso AL "
           "— sim/não e porquê». No dia 1 de cada mês, um relatório confirma que está tudo "
           "em ordem. Zero trabalho do vosso lado."),
        _p("<strong>Veja grátis o estado atual do vosso registo (30 segundos):</strong>"),
        _p(f"→ {link_html}"),
        _p("Cumprimentos,<br>Diogo Mendes · CheckAL"),
    ])
    corpo_texto = "\n\n".join([
        "Bom dia,",
        f"{reg_txt} Encontrámo-lo na lista pública do RNAL — é isso que fazemos: vigiamos "
        "os 120.000+ registos do país.",
        frase_contexto,
        "O CheckAL monitoriza semanalmente o estado do registo, o prazo do seguro e os "
        "regulamentos do concelho, e envia alertas interpretados: «isto afeta o vosso AL — "
        "sim/não e porquê». No dia 1 de cada mês, um relatório confirma que está tudo em "
        "ordem. Zero trabalho do vosso lado.",
        "Veja grátis o estado atual do vosso registo (30 segundos):",
        f"→ {link_txt}",
        "Cumprimentos,\nDiogo Mendes · CheckAL",
    ])
    return assunto, corpo_html, corpo_texto


def _d4(c: dict[str, str]) -> tuple[str, str, str]:
    nr, aloj = c["nr"], c["alojamento"]
    titulo_aloj = aloj or "o vosso Alojamento Local"
    assunto = f"Re: {titulo_aloj} — o que os outros titulares já viram"
    link_html, link_txt = _link_relatorio(nr)

    # Nota (COPY-VENDAS.md §7): "1 em cada 3" é placeholder — substituir pelo número real
    # quando houver 100+ verificações. Mantém-se a copy canónica; a troca é decisão de negócio.
    social = (
        "Só um dado: dos relatórios gratuitos que gerámos este mês, 1 em cada 3 registos "
        "tinha pelo menos um ponto por resolver — quase sempre o seguro por comunicar ou o "
        "concelho com regulamento novo. Os titulares não sabiam. É esse o padrão: ninguém "
        "avisa, publica-se e conta-se o prazo."
    )
    reg = f"do vosso registo {_esc(nr)} " if nr else "do vosso registo "
    reg_txt = f"do vosso registo {nr} " if nr else "do vosso registo "

    corpo_html = "\n".join([
        _p("Bom dia,"),
        _p(social),
        _p(f"O relatório {reg}continua disponível, grátis: {link_html}"),
        _p("Diogo · CheckAL"),
    ])
    corpo_texto = "\n\n".join([
        "Bom dia,",
        social,
        f"O relatório {reg_txt}continua disponível, grátis: {link_txt}",
        "Diogo · CheckAL",
    ])
    return assunto, corpo_html, corpo_texto


def _d10(c: dict[str, str]) -> tuple[str, str, str]:
    nr = c["nr"]
    assunto = "6.765 registos cancelados em Lisboa — a mecânica é sempre a mesma"
    link_html, link_txt = _link_relatorio(nr)

    caso = (
        "Caso real: em fevereiro de 2026, a Câmara de Lisboa cancelou 6.765 registos de AL "
        "— cerca de um terço da cidade — sobretudo por falta de comunicação do seguro "
        "(Observador). O Porto seguiu-se com 1.413. A ALEP estima que o processo chegue aos "
        "40–45 mil cancelamentos no país."
    )
    # RT-copy: sem "cancelamento tácito" (caracterização jurídica) — descrição
    # factual e genérica do processo, sem concluir o desfecho jurídico.
    mecanica = (
        "A mecânica é sempre a mesma: notificação, prazo curto e, sem resposta, o "
        "processo segue para o cancelamento do registo. Recuperar um registo "
        "cancelado num concelho em contenção pode ser impossível — não há novos "
        "registos lá."
    )
    fecho_html = (
        "49€/ano por AL para nunca ser apanhado nesta engrenagem. Último email que vos "
        f"envio; o relatório gratuito fica aqui: {link_html}"
    )
    fecho_txt = (
        "49€/ano por AL para nunca ser apanhado nesta engrenagem. Último email que vos "
        f"envio; o relatório gratuito fica aqui: {link_txt}"
    )

    corpo_html = "\n".join([
        _p("Bom dia,"), _p(caso), _p(mecanica), _p(fecho_html), _p("Diogo · CheckAL"),
    ])
    corpo_texto = "\n\n".join([
        "Bom dia,", caso, mecanica, fecho_txt, "Diogo · CheckAL",
    ])
    return assunto, corpo_html, corpo_texto


_BUILDERS = {"d0": _d0, "d4": _d4, "d10": _d10}


# ==========================================================================
#  API pública — compõe a peça (NÃO envia)
# ==========================================================================
def render_passo(passo: str, prospeto: object) -> PecaFria:
    """Compõe UMA peça da cadência (`passo` ∈ {"d0","d4","d10"}) para `prospeto`.

    Devolve uma :class:`PecaFria` pronta a entregar ao `cold_email.enviar_frio` (gated).
    O corpo é escrito **sem inventar dados** (campo em falta → frase neutra) e a base
    garante rodapé legal + opt-out 1-clique personalizado com o email do prospeto.
    """
    if passo not in _BUILDERS:
        raise ValueError(f"passo de prospeção desconhecido: {passo!r} (use {SEQUENCIA})")

    c = _campos(prospeto)
    assunto, corpo_html, corpo_texto = _BUILDERS[passo](c)

    email = base.render_email(
        "prospeccao",
        assunto=assunto,
        disclaimer=DISCLAIMER_INDEPENDENCIA,
        corpo_html=corpo_html,
        corpo_texto=corpo_texto,
        nota_rgpd=NOTA_RGPD,
        email_destinatario=c["email"],
    )
    return PecaFria(
        passo=passo, dia=_DIAS[passo], para=c["email"], remetente=REMETENTE, email=email
    )


def render_sequencia(prospeto: object) -> list[PecaFria]:
    """Compõe a cadência completa (D+0 → D+4 → D+10) para `prospeto`, por ordem."""
    return [render_passo(passo, prospeto) for passo in SEQUENCIA]
