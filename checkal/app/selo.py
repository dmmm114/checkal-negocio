"""Selo público do CheckAL: badge SVG inline + snippet para o anúncio (SPEC-FDS3.md §selo).

O selo é a prova social do produto — *"CheckAL ✓ — AL Verificado"* (MARCA.md) — que
o titular cola no seu anúncio (site próprio, Airbnb, Booking) e que liga à página
pública `/selo/{nr}` (`app.web.selo`). Duas peças, ambas **funções puras de formatação
de strings**, SEM rede, SEM BD e SEM dependências externas:

  - :func:`gerar_selo_svg` — o badge, como string **SVG inline** (embute-se directamente
    no HTML; nada de ``<img>``, fontes ou folhas de estilo externas). Todo o texto vindo
    de fora — o `nome` do alojamento — é **escapado** (`html.escape`), pelo que o selo
    nunca injeta markup (defesa de XSS reflectido quando o nome vem da BD/RNAL).
  - :func:`snippet_anuncio` — o HTML *copy-paste* que o titular cola no anúncio: uma
    âncora para ``config.BASE_URL/selo/{nr}`` com o badge SVG lá dentro.

DISCIPLINA (inviolável): só **dados PÚBLICOS do estabelecimento** entram no selo — o
`nome` do alojamento e o nº de registo, ambos públicos no RNAL. **ZERO PII do titular**
(nome/NIF/email/telefone). Estas funções não tocam na BD, logo não têm sequer acesso aos
contactos do titular; a página pública (`app.web.selo`) reforça a mesma lista branca.
"""
from __future__ import annotations

from html import escape

import app.config as config

__all__ = ["gerar_selo_svg", "snippet_anuncio"]

# Léxico da marca (MARCA.md / CLAUDE.md — decisões fechadas). O ✓ é parte do selo.
_MARCA = "CheckAL"
_TAGLINE = "AL Verificado"
_CHECK = "✓"  # ✓


def gerar_selo_svg(nr_registo: int | str, nome: str = "") -> str:
    """Devolve o selo *"CheckAL ✓ — AL Verificado"* como string SVG inline.

    O SVG é autocontido (sem `<img>`, fontes ou CSS externos): embute-se tal e qual
    no HTML da página do selo ou do anúncio. Mostra a marca, o ✓, a tagline, o nº de
    registo RNAL e — quando fornecido — o `nome` público do alojamento.

    `nome` e `nr_registo` são **escapados** (`html.escape`, `quote=True`): o `nome`
    chega da BD/RNAL, logo é dado não confiável e nunca pode injetar markup no SVG.
    `nome` vazio/só espaços omite a linha do nome sem rebentar.
    """
    nr = escape(str(nr_registo))
    nome_limpo = str(nome or "").strip()
    linha_nome = (
        f'<text x="66" y="86" font-family="Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="12" fill="#4b5563">{escape(nome_limpo)}</text>'
        if nome_limpo
        else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="288" height="104" '
        f'viewBox="0 0 288 104" role="img" '
        f'aria-label="{_MARCA} {_CHECK} {_TAGLINE} — registo RNAL {nr}">'
        f'<title>{_MARCA} {_CHECK} — {_TAGLINE}</title>'
        f'<rect x="1" y="1" width="286" height="102" rx="12" '
        f'fill="#ffffff" stroke="#0f766e" stroke-width="2"/>'
        f'<circle cx="34" cy="52" r="20" fill="#0f766e"/>'
        f'<path d="M25 52 l6 6 l12 -13" fill="none" stroke="#ffffff" '
        f'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<text x="66" y="40" font-family="Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="20" font-weight="700" fill="#0f766e">{_MARCA} {_CHECK}</text>'
        f'<text x="66" y="62" font-family="Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="14" font-weight="600" fill="#111827">{_TAGLINE}</text>'
        f'{linha_nome}'
        f'<text x="278" y="98" text-anchor="end" '
        f'font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="10" '
        f'fill="#6b7280">RNAL n.º {nr}</text>'
        f'</svg>'
    )


def snippet_anuncio(nr_registo: int | str) -> str:
    """Devolve o HTML *copy-paste* que o titular cola no anúncio.

    Uma âncora que liga à página pública do selo (``config.BASE_URL/selo/{nr}``, aberta
    em separador novo com ``rel="noopener"``) com o badge SVG embutido. Autocontido:
    quem cola não precisa de nada do CheckAL além deste bloco.

    `nr_registo` é escapado para o atributo `href`/`title`; o badge é gerado por
    :func:`gerar_selo_svg` (que também escapa). Sem rede: é só formatação de string.
    """
    nr = escape(str(nr_registo))
    url = escape(f"{config.BASE_URL}/selo/{nr_registo}")
    badge = gerar_selo_svg(nr_registo)
    return (
        f'<a href="{url}" target="_blank" rel="noopener" '
        f'title="{_MARCA} {_CHECK} — {_TAGLINE} (registo RNAL n.º {nr})" '
        f'style="display:inline-block;line-height:0;text-decoration:none">'
        f'{badge}'
        f'</a>'
    )
