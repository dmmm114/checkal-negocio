"""PUBLICADOR — o braço determinista da publicação: o LLM propõe, o
dono/config aprova, ISTO publica.

Parte 1 (fase 3, F3.3): só o render. Composição da página HTML final de um
artigo aprovado e a manutenção do sitemap — funções puras, sem I/O de rede
nem BD, deterministas (mesmo artigo ⇒ mesmo HTML byte a byte). A passagem
completa (drain da fila, modo ensaio/live, git, deploy Cloudflare) é a F3.4,
noutro módulo desta mesma peça — NÃO está aqui.

Auditoria-chave (`docs/superpowers/plans/2026-07-19-fase3-publicador.md`
§F3.3): o molde é `site/porto.html`. Os blocos que não variam de artigo para
artigo (skip-link, header com o logo SVG inline, o bloco CTA do corpo, o
footer com a denominação legal, o `<script src="/assets/js/main.js" defer>`)
são copiados byte a byte em constantes de template — só levam `{slug}` onde o
molde real também varia por página (os `data-evento`). As partes que mudam
por artigo (title, meta description, canonical, OG, JSON-LD, rótulo de
secção, corpo, fontes) entram por composição.

Frases canónicas de compliance — CONTRATO com o linter (ver a docstring de
`_texto_lint_artigo` em manage.py): o texto lintado pelo EDITOR aproxima o
texto publicado apensando `linter.DISCLAIMER_NAO_ACONSELHAMENTO` e
`linter.DIVULGACAO_IA` ao fim. Para que o lint continue válido depois de
publicado, este render TEM de embutir as MESMAS constantes (nunca strings
copiadas à mão) — os artigos `site/*.html` existentes foram escritos antes
deste módulo e não as têm; o molde novo embute-as sempre. Colocação: cada
frase num `<p class="nota">` próprio, depois do bloco "Fontes" (mesma zona
onde os artigos manuscritos já tinham o disclaimer solto) — ordem: Fontes →
disclaimer → divulgação de IA.

`data_publicacao` ausente no artigo ⇒ usa `date.today()` (o PUBLICADOR
carimba a data de publicação real; contrato com o prompt do EDITOR, que não a
preenche). A data por extenso do `p.nota` "Atualizado a …" é formatada à mão
com um dicionário de meses PT — sem `locale` do sistema, que é frágil
(depende de locales instalados na máquina).
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

from app.compliance.linter import DISCLAIMER_NAO_ACONSELHAMENTO, DIVULGACAO_IA

__all__ = ["md_para_html", "render_artigo", "atualizar_sitemap"]

# Whitelist estrita do slug — não é só escape. O slug é um segmento de URL
# AUTORADO PELO LLM (payload do EDITOR) e entra cru em canonical/og:url/
# data-evento×2/sitemap; uma whitelist mata injeção (aspas, `<`, `>`, `/`) E
# path traversal (`../`) de uma só vez. Reutilizada por `render_artigo` e
# `atualizar_sitemap` — e importada por `manage.py` para recusar na ORIGEM
# (antes de o artigo sequer entrar na fila), não só aqui no render.
_RE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ==========================================================================
#  md_para_html — mini-conversor markdown → HTML determinista
# ==========================================================================
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_OL_LINHA = re.compile(r"^\d+\.\s+")
_RE_UL_LINHA = re.compile(r"^-\s+")
_RE_BLOCO_SEP = re.compile(r"\n\s*\n")


def _negrito(texto: str) -> str:
    return _RE_BOLD.sub(r"<strong>\1</strong>", texto)


def md_para_html(md: str) -> str:
    """Converte markdown minimal (o subconjunto que o EDITOR produz) em HTML.

    Determinista, sem dependências. Ordem fixa: `html.escape` PRIMEIRO (nunca
    HTML não escapado do corpo do artigo chega ao render); depois, sobre o
    texto já escapado, `**x**` → `<strong>x</strong>`; blocos são separados
    por linha em branco; um bloco cujas linhas começam TODAS por `N. ` vira
    `<ol><li>…</li></ol>`, cujas linhas começam TODAS por `- ` vira
    `<ul><li>…</li></ul>`; qualquer outro bloco vira `<p>…</p>` (linhas do
    bloco unidas por espaço). Nada mais — sem links/cabeçalhos/imagens: o
    corpo dos artigos não os usa (o linter e o prompt do EDITOR garantem).
    """
    escapado = html.escape(md or "")
    blocos = _RE_BLOCO_SEP.split(escapado.strip())
    partes: list[str] = []
    for bloco in blocos:
        linhas = [l.strip() for l in bloco.split("\n") if l.strip()]
        if not linhas:
            continue
        if all(_RE_OL_LINHA.match(l) for l in linhas):
            itens = "".join(
                f"<li>{_negrito(_RE_OL_LINHA.sub('', l))}</li>" for l in linhas
            )
            partes.append(f"<ol>{itens}</ol>")
        elif all(_RE_UL_LINHA.match(l) for l in linhas):
            itens = "".join(
                f"<li>{_negrito(_RE_UL_LINHA.sub('', l))}</li>" for l in linhas
            )
            partes.append(f"<ul>{itens}</ul>")
        else:
            partes.append(f"<p>{_negrito(' '.join(linhas))}</p>")
    return "\n".join(partes)


# ==========================================================================
#  Constantes de template — copiadas LITERALMENTE de site/porto.html
# ==========================================================================
_SKIP_LINK = '  <a class="salta" href="#conteudo">Saltar para o conteúdo</a>'

_HEADER_FMT = """  <header class="cabecalho">
    <div class="cabecalho__interior">
      <a class="logo-lockup" href="/">
        <svg class="badge-al" viewBox="0 0 180 180" aria-hidden="true"><rect width="180" height="180" rx="48" fill="#0F172A"/><g transform="translate(16,60) scale(0.52)"><path d="M12,54 L40,84 L92,12" fill="none" stroke="#12B76A" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/></g><text x="97" y="122" font-family="'Plus Jakarta Sans','Trebuchet MS',sans-serif" font-size="86" font-weight="800" fill="#FFFFFF" text-anchor="middle">A</text><text x="147" y="122" font-family="'Plus Jakarta Sans','Trebuchet MS',sans-serif" font-size="86" font-weight="800" fill="#FFFFFF" text-anchor="middle">L</text></svg>
        <span>CheckAL<small>monitorização de Alojamento Local</small></span>
      </a>
      <nav class="cabecalho__nav">
        <a href="/#precos">Preços</a>
        <a class="btn btn--acao" href="/#verificar" data-evento="cta_{slug}_header">Faz o check grátis</a>
      </nav>
    </div>
  </header>"""

_CTA_CORPO_FMT = """        <p>Ou deixa-nos fazer isso por ti, agora e todas as semanas:</p>
        <p><a class="btn btn--acao btn--grande" href="/#verificar" data-evento="cta_{slug}_corpo">Fazer o check grátis ao meu AL</a></p>
        <p class="nota">30 segundos, sem cartão. Recebes o relatório do estado atual do teu
          registo, seguro e concelho.</p>"""

_FOOTER = """  <footer class="rodape">
    <div class="envolucro">
      <p class="legal">CheckAL — serviço privado e independente de monitorização de Alojamento
        Local · Cosmic Oasis, Unipessoal Lda. · Paredes · Porto. Não somos,
        nem representamos, o Turismo de Portugal, o RNAL ou qualquer câmara municipal.</p>
      <div class="rodape__base">
        <span>© <span data-ano>2026</span> CheckAL</span>
        <span><a href="/privacidade.html">Privacidade</a> · <a href="/termos.html">Termos</a> · <a href="/remover.html">Remover os meus dados</a></span>
      </div>
    </div>
  </footer>
  <script src="/assets/js/main.js" defer></script>"""

_HEAD_FMT = """<!DOCTYPE html>
<html lang="pt-PT">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{titulo} · CheckAL</title>
  <meta name="description" content="{meta_description}">
  <link rel="canonical" href="https://www.checkal.pt/{slug}">
  <meta name="theme-color" content="#0F172A">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{titulo}">
  <meta property="og:description" content="{meta_description}">
  <meta property="og:url" content="https://www.checkal.pt/{slug}">
  <meta property="og:image" content="https://checkal.pt/assets/img/og.png">
  <link rel="icon" href="/assets/img/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/assets/css/main.css">
{json_ld}
</head>"""

# Meses por extenso pt-PT — sem locale do sistema (frágil: depende de locales
# instalados na máquina; um dict determinista é mais robusto e testável).
_MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio",
    6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
    11: "novembro", 12: "dezembro",
}


def _data_por_extenso(iso: str) -> str:
    ano, mes, dia = (int(p) for p in iso.split("-"))
    return f"{dia} de {_MESES_PT[mes]} de {ano}"


def _json_ld_bloco(titulo: str, data_publicacao: str) -> str:
    headline = json.dumps(titulo, ensure_ascii=False)
    data_str = json.dumps(data_publicacao, ensure_ascii=False)
    corpo_json = (
        "  {\n"
        '    "@context": "https://schema.org",\n'
        '    "@type": "Article",\n'
        f'    "headline": {headline},\n'
        '    "inLanguage": "pt-PT",\n'
        f'    "datePublished": {data_str},\n'
        '    "author": { "@type": "Organization", "name": "CheckAL" },\n'
        '    "publisher": { "@type": "Organization", "name": "CheckAL", '
        '"url": "https://checkal.pt/" }\n'
        "  }"
    )
    # Mitigação </script>: `titulo` chega aqui via json.dumps, NÃO via
    # html.escape — json.dumps não neutraliza `<`/`>`/`&`, e o parser HTML de
    # <script> procura a substring literal "</script" mesmo dentro de uma
    # string JSON válida. Escapes \uXXXX são JSON legal (o valor não muda) e
    # matam qualquer "</script>" embutido no titulo/data. Aplicado só ao
    # CORPO do JSON — nunca à tag <script>/</script> real que o envolve.
    corpo_json = (
        corpo_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return f'  <script type="application/ld+json">\n{corpo_json}\n  </script>'


def _render_seccao(seccao: dict) -> str:
    h2 = html.escape(seccao.get("h2", ""))
    corpo_html = md_para_html(seccao.get("corpo_md", ""))
    return f"        <h2>{h2}</h2>\n{corpo_html}"


def _render_fontes(fontes: list[dict]) -> str:
    links = []
    for fonte in fontes:
        url = fonte.get("url", "")
        rotulo = html.escape(fonte.get("titulo") or url)
        data_f = fonte.get("data")
        if data_f:
            rotulo = f"{rotulo} ({html.escape(data_f)})"
        links.append(f'<a href="{html.escape(url)}" rel="noopener">{rotulo}</a>')
    return " · ".join(links) + ("." if links else "")


def render_artigo(artigo: dict) -> str:
    """Compõe a página HTML final de um `artigo_seo` aprovado.

    Determinista: o mesmo dict produz sempre o mesmo HTML byte a byte (sem
    `datetime.now()`/aleatoriedade — só `date.today()` quando o artigo não
    traz `data_publicacao`, o que o PUBLICADOR carimba nesse momento).

    Espera o formato do payload do EDITOR (`slug`, `titulo`,
    `meta_description`, `data_publicacao` opcional, `seccoes` — lista de
    `{h2, corpo_md}` —, `fontes` — lista de `{url, titulo, data, excerto}`).
    `rotulo_secao` é opcional (por omissão "Alojamento Local" — o payload do
    EDITOR não o define hoje; um valor genérico mas honesto).
    """
    slug = artigo["slug"]
    # Fail-closed: o slug entra cru em URLs/atributos (canonical, og:url,
    # data-evento×2) — whitelist estrita antes de qualquer interpolação.
    if not _RE_SLUG.fullmatch(slug):
        raise ValueError(f"slug inválido: {slug!r}")
    titulo = artigo["titulo"]
    meta_description = artigo.get("meta_description", "")
    data_publicacao = artigo.get("data_publicacao") or date.today().isoformat()
    rotulo_secao = artigo.get("rotulo_secao", "Alojamento Local")

    titulo_esc = html.escape(titulo)
    meta_esc = html.escape(meta_description)
    rotulo_esc = html.escape(rotulo_secao)

    head = _HEAD_FMT.format(
        titulo=titulo_esc,
        meta_description=meta_esc,
        slug=slug,
        json_ld=_json_ld_bloco(titulo, data_publicacao),
    )
    header = _HEADER_FMT.format(slug=slug)
    cta_corpo = _CTA_CORPO_FMT.format(slug=slug)
    seccoes_html = "\n".join(_render_seccao(s) for s in artigo.get("seccoes", []))
    fontes_html = _render_fontes(artigo.get("fontes", []))

    corpo = f"""{_SKIP_LINK}
{header}

  <main id="conteudo">
    <article class="secao">
      <div class="envolucro pagina-estreita">
        <p class="rotulo-secao">{rotulo_esc}</p>
        <h1>{titulo_esc}</h1>
        <p class="nota">Atualizado a {_data_por_extenso(data_publicacao)} · Fontes oficiais e de imprensa no fim da página.</p>

{seccoes_html}
{cta_corpo}

        <hr style="border:0;border-top:1px solid var(--borda);margin:2.5rem 0 1.5rem">
        <p class="nota"><strong>Fontes:</strong> {fontes_html}</p>
        <p class="nota">{DISCLAIMER_NAO_ACONSELHAMENTO}</p>
        <p class="nota">{DIVULGACAO_IA}</p>
      </div>
    </article>
  </main>

{_FOOTER}
"""
    return f"{head}\n<body>\n{corpo}</body>\n</html>\n"


# ==========================================================================
#  Sitemap — manipulação por texto, formato exato de site/sitemap.xml
# ==========================================================================
_RE_BLOCO_URL = re.compile(
    r"  <url>\n"
    r"    <loc>(?P<loc>[^<]*)</loc>\n"
    r"    <lastmod>(?P<lastmod>[^<]*)</lastmod>\n"
    r"    <changefreq>(?P<changefreq>[^<]*)</changefreq>\n"
    r"    <priority>(?P<priority>[^<]*)</priority>\n"
    r"  </url>\n"
)


def atualizar_sitemap(caminho: Path, *, slug: str, lastmod: str) -> None:
    """Acrescenta/atualiza a entrada de `slug` em `caminho` (sitemap.xml).

    Manipulação por TEXTO (não XML parser) no formato exato do sitemap real
    (indentação 2 espaços no `<url>`, 4 nos filhos — `site/sitemap.xml`).
    Entrada já existente (mesmo `<loc>`) ⇒ substitui só o `<lastmod>`,
    preservando `changefreq`/`priority` como estavam. Entrada nova ⇒ insere
    um bloco `<url>` antes de `</urlset>` com `changefreq=monthly` e
    `priority=0.8` (moldura dos artigos, como `porto`/`funchal`). Idempotente:
    chamar duas vezes com o mesmo `slug`/`lastmod` não duplica nem move nada.
    """
    # Mesma whitelist de `render_artigo` — o slug entra cru na <loc>.
    if not _RE_SLUG.fullmatch(slug):
        raise ValueError(f"slug inválido: {slug!r}")
    texto = caminho.read_text(encoding="utf-8")
    loc = f"https://www.checkal.pt/{slug}"

    for m in _RE_BLOCO_URL.finditer(texto):
        if m.group("loc") == loc:
            bloco_novo = m.group(0).replace(
                f"<lastmod>{m.group('lastmod')}</lastmod>",
                f"<lastmod>{lastmod}</lastmod>",
            )
            texto = texto[: m.start()] + bloco_novo + texto[m.end():]
            caminho.write_text(texto, encoding="utf-8")
            return

    bloco_novo = (
        "  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>0.8</priority>\n"
        "  </url>\n"
    )
    texto = texto.replace("</urlset>", bloco_novo + "</urlset>", 1)
    caminho.write_text(texto, encoding="utf-8")
