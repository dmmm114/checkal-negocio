"""PUBLICADOR — o braço determinista da publicação: o LLM propõe, o
dono/config aprova, ISTO publica.

Parte 1 (fase 3, F3.3): só o render. Composição da página HTML final de um
artigo aprovado e a manutenção do sitemap — funções puras, sem I/O de rede
nem BD, deterministas (mesmo artigo ⇒ mesmo HTML byte a byte).

Parte 2 (fase 3, F3.4): `correr()` — a passagem completa chamada pelo job
`manage.py publicador`. Em `config.CHECKAL_MODO_TESTE` é ensaio read-only
(SELECT + render para `ensaio_dir`, zero escrita na BD/site); em modo live
drena `artigo_seo`/`post_grupo` aprovados via `fila.drain` (dentro de UMA
`fila.sessao_governacao()`) e publica cada artigo: escreve o HTML, atualiza o
sitemap, e faz commit+push no repo aninhado + deploy Cloudflare Pages via
staging com `npx wrangler` PINADO. `post_grupo` é sempre no-op (o dono cola à
mão). Nada aqui corre git/wrangler diretamente — tudo passa pelo seam
`executar` injetável (testes usam fakes; NUNCA rede/processos reais em teste).

Parte 3 (fase FB, FB2): publicação de `post_pagina` na Página de Facebook da
marca via Graph API oficial (:func:`publicar_facebook`), live-gated por
`config.facebook_ativo()` — sem `CHECKAL_FACEBOOK_PAGE_ID`/`_PAGE_TOKEN`
configurados, o `tipos` do drain nem inclui `post_pagina`: os itens aprovados
ficam intactos à espera (sem lease, sem churn de backoff), e o relatório live
sinaliza essa espera com `"facebook": "por configurar"` (contados por um
SELECT read-only, nunca um `falhado` artificial). Auto-aprovação simétrica à
dos artigos via `config.AUTO_PUBLICAR_POST_PAGINA` (mesmo filtro por tipo
OBRIGATÓRIO de `fila.auto_aprovar` — ver o aviso TYPE-AGNOSTIC no seu
docstring). Em ensaio, os `post_pagina` elegíveis só aparecem no relatório
(`"posts_pagina"`) — zero rede, zero drain, mesmo padrão do resto do ensaio.
`publicar_facebook` é o seam de rede (default `httpx.post`, injetável nos
testes); a mensagem de erro de uma falha HTTP é truncada e NUNCA inclui o
token de acesso.

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
import subprocess
from datetime import date
from pathlib import Path

from app.compliance.linter import DISCLAIMER_NAO_ACONSELHAMENTO, DIVULGACAO_IA

__all__ = [
    "md_para_html", "render_artigo", "atualizar_sitemap", "publicar_facebook", "correr",
]

# Whitelist estrita do slug — não é só escape. O slug é um segmento de URL
# AUTORADO PELO LLM (payload do EDITOR) e entra cru em canonical/og:url/
# data-evento×2/sitemap; uma whitelist mata injeção (aspas, `<`, `>`, `/`) E
# path traversal (`../`) de uma só vez. Reutilizada por `render_artigo` e
# `atualizar_sitemap` — e importada por `manage.py` para recusar na ORIGEM
# (antes de o artigo sequer entrar na fila), não só aqui no render.
_RE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Whitelist de esquema para o `href` das fontes — também autorado pelo LLM.
# Só `http://`/`https://` (case-insensitive); `javascript:`/`data:`/etc.
# recusados fail-closed. Reutilizada por `_render_fontes` e importada por
# `manage.py` para recusar na ORIGEM (mesmo padrão do `_RE_SLUG`).
_RE_URL_HTTP = re.compile(r"^https?://", re.IGNORECASE)


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
        # Fail-closed: o url é autorado pelo LLM e entra cru no `href` — um
        # esquema não http(s) (`javascript:`, `data:`, …) executaria/injetaria
        # no clique. Mesma filosofia da whitelist do slug (_RE_SLUG): recusa
        # em vez de sanitizar. Reutilizada na ORIGEM por `manage.py`.
        if not _RE_URL_HTTP.match(url):
            raise ValueError(f"fonte com esquema não permitido: {url!r}")
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


# ==========================================================================
#  Parte 2 (F3.4) — a passagem: ensaio (read-only) vs live (drain+git+wrangler)
# ==========================================================================
_TIPOS_PUBLICAVEIS = ("artigo_seo", "post_grupo")

# Ensaio (read-only, F3.4) mostra os `post_pagina` elegíveis SEMPRE — é só
# diagnóstico, sem drain nem rede, por isso não precisa do live-gate de
# `config.facebook_ativo()` (esse gate é só sobre o que o drain LIVE serve).
_TIPOS_ENSAIO = _TIPOS_PUBLICAVEIS + ("post_pagina",)

# rsync: nunca leva o `.git` aninhado, o estado do wrangler, docs internos nem
# as ferramentas de manutenção — e `functions/` fica de fora porque vai à
# parte, como pasta IRMÃ de `dist/` (é assim que o Cloudflare Pages a exige).
_RSYNC_EXCLUDES = (
    "--exclude=.git", "--exclude=.wrangler", "--exclude=*.md",
    "--exclude=tools", "--exclude=functions",
)
_WRANGLER_VERSAO = "wrangler@4.111.0"  # PINADA — `npx wrangler` sem pin flutua


def _executar_padrao(cmd, **kw):
    """Default do parâmetro `executar` de :func:`correr` — `subprocess.run`
    real. Injetável: os testes passam sempre um fake (nenhum corre git/
    wrangler/rede de verdade). `check`/`capture_output`/`text` são só
    DEFAULTS — o chamador pode substituí-los via `**kw` (o guard do commit
    vazio em `_processar` passa `check=False` ao `git diff --cached --quiet`,
    cujo returncode 1 é esperado e nunca deve levantar `CalledProcessError`);
    por isso usa `setdefault`, não um `check=True` fixo que colidiria com um
    `check` recebido em `kw`."""
    kw.setdefault("check", True)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def _carregar_artigo(session, item) -> dict:
    """Carrega o payload do artigo a partir do `EventoAgente` referido por
    `item.ref_id` (o mesmo padrão do EDITOR em `manage._cmd_editor_enfileirar`:
    `payload={"tipo": "artigo_seo", "artigo": {...}}`).

    Levanta `ValueError` se o ref for inexistente/não-numérico ou o payload
    não tiver `"artigo"` — quem chama isto dentro de um `processador` do
    `fila.drain` sabe que a exceção vira `falhado` + backoff exponencial
    (nunca publica um artigo fantasma).
    """
    import app.models_swarm as ms

    if not item.ref_id:
        raise ValueError(f"item {item.id} (artigo_seo) sem ref_id")
    try:
        evento_id = int(item.ref_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"item {item.id}: ref_id {item.ref_id!r} não é um id de EventoAgente"
        ) from exc
    evento = session.get(ms.EventoAgente, evento_id)
    if evento is None or not isinstance(evento.payload, dict) or "artigo" not in evento.payload:
        raise ValueError(
            f"item {item.id}: EventoAgente {item.ref_id!r} inexistente ou sem "
            "payload['artigo']"
        )
    return evento.payload["artigo"]


def _carregar_corpo_texto(session, item) -> str:
    """Carrega `corpo_texto` do payload do `EventoAgente` referido por
    `item.ref_id` — o mesmo padrão de :func:`_carregar_artigo`, mas para
    `post_pagina`: o payload do COMUNICADOR (`manage._cmd_comunicador_enfileirar`)
    é `{"tipo": "post_pagina", "corpo_texto": ..., ...}`, sem a chave `"artigo"`.

    Levanta `ValueError` nas mesmas condições (ref ausente/não-numérico, evento
    inexistente, ou payload sem `corpo_texto` não vazio) — a exceção vira
    `falhado` + backoff dentro do `processador` do `fila.drain`.
    """
    import app.models_swarm as ms

    if not item.ref_id:
        raise ValueError(f"item {item.id} (post_pagina) sem ref_id")
    try:
        evento_id = int(item.ref_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"item {item.id}: ref_id {item.ref_id!r} não é um id de EventoAgente"
        ) from exc
    evento = session.get(ms.EventoAgente, evento_id)
    if (
        evento is None
        or not isinstance(evento.payload, dict)
        or not evento.payload.get("corpo_texto")
    ):
        raise ValueError(
            f"item {item.id}: EventoAgente {item.ref_id!r} inexistente ou sem "
            "payload['corpo_texto']"
        )
    return evento.payload["corpo_texto"]


def publicar_facebook(mensagem: str, *, page_id: str, token: str, http_post=None) -> str:
    """Publica `mensagem` na Página de Facebook via Graph API oficial.

    POST `https://graph.facebook.com/v21.0/{page_id}/feed`, corpo form-encoded
    `{"message": mensagem, "access_token": token}`. Resposta HTTP 200 com JSON
    `{"id": ...}` ⇒ devolve esse id (o id do post criado). Qualquer outro caso
    — status ≠ 200, JSON inválido, ou JSON sem `"id"` — levanta `RuntimeError`
    com o corpo da resposta TRUNCADO (300 carateres); o `token` é removido
    desse corpo antes de entrar na mensagem de erro (defesa em profundidade —
    a Graph API não costuma ecoar o token de acesso, mas um log/mensagem de
    erro nunca deve poder vazá-lo).

    Live-gated A MONTANTE: esta função não decide SE deve publicar
    (`config.facebook_ativo()` é responsabilidade de quem chama, em
    `correr()`) — aqui é só o seam de rede, puro no sentido de que não lê
    config nem BD. `http_post` é injetável nos testes (fakes; NUNCA rede real
    em teste); o default é `httpx.post` com `timeout=30` segundos.
    """
    if http_post is None:
        import httpx  # import tardio: só quando de facto se liga em produção

        http_post = httpx.post

    resposta = http_post(
        f"https://graph.facebook.com/v21.0/{page_id}/feed",
        data={"message": mensagem, "access_token": token},
        timeout=30,
    )
    status = getattr(resposta, "status_code", None)
    post_id = None
    if status == 200:
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = None
        if isinstance(corpo, dict):
            post_id = corpo.get("id")
    if status == 200 and post_id:
        return post_id

    corpo_texto = (getattr(resposta, "text", "") or "")[:300]
    if token:
        corpo_texto = corpo_texto.replace(token, "***")
    raise RuntimeError(
        f"Graph API /{page_id}/feed falhou (status={status}): {corpo_texto}"
    )


def _publicar_no_cloudflare(site_dir: Path, executar) -> None:
    """Commit+push no repo aninhado `site_dir` + deploy de staging (wrangler
    PINADO). Todos os passos passam por `executar` (injetável) — nada aqui
    toca git/rede diretamente.

    Staging: `stage/` nasce sempre de novo (irmã de `site_dir`), `dist/` é o
    rsync do site (com os excludes) e `functions/` entra à parte, como pasta
    IRMÃ de `dist/` dentro de `stage/` (exigência do Cloudflare Pages — não
    fica dentro de `dist/`). Valida a linha "Uploading Functions bundle" no
    stdout do wrangler; ausente ⇒ `RuntimeError` (o deploy não fica confirmado
    só por o processo ter saído com código 0).
    """
    stage_dir = site_dir.parent / "stage"
    executar(["rm", "-rf", str(stage_dir)])
    executar(["mkdir", "-p", str(stage_dir / "dist")])
    executar(["rsync", "-a", *_RSYNC_EXCLUDES, f"{site_dir}/", f"{stage_dir}/dist/"])
    executar(["cp", "-r", str(site_dir / "functions"), str(stage_dir / "functions")])
    resultado = executar(
        ["npx", "--yes", _WRANGLER_VERSAO, "pages", "deploy", "dist",
         "--project-name", "checkal", "--branch", "main"],
        cwd=str(stage_dir),
    )
    stdout = getattr(resultado, "stdout", "") or ""
    if "Uploading Functions bundle" not in stdout:
        raise RuntimeError(
            "wrangler pages deploy: 'Uploading Functions bundle' ausente do "
            "stdout — deploy não confirmado."
        )


def correr(
    *,
    site_dir: Path | str | None = None,
    ensaio_dir: Path | str | None = None,
    executar=None,
    http_post=None,
) -> dict:
    """A passagem do PUBLICADOR — chamada pelo job `manage.py publicador`.

    **Modo ensaio** (`config.CHECKAL_MODO_TESTE=True`): NUNCA drena — um
    dry-run que drenasse marcaria itens `feito` sem os publicar de facto,
    perdendo-os. Faz um SELECT read-only dos itens `aprovado`/`auto_aprovado`
    de tipo `artigo_seo`/`post_grupo`/`post_pagina`, renderiza os artigos para
    `ensaio_dir` e devolve `{"modo": "ensaio", "artigos": [...], "posts": N,
    "posts_pagina": [{"id", "resumo"}, ...]}`. Zero `fila.drain`, zero escrita
    na BD, zero escrita em `site_dir`, zero comando/rede executado (os
    `post_pagina` elegíveis aparecem sempre no relatório, mesmo sem
    `config.facebook_ativo()` — é só diagnóstico read-only, o live-gate é só
    sobre o drain LIVE). Um item `artigo_seo` malformado (payload em falta/
    inválido, ou recusado pelo próprio `render_artigo` — slug hostil, esquema
    de fonte não permitido) não rebenta a passagem: fica em `artigos` como
    `{"item_id": ..., "erro": str(exc)}` e os restantes itens continuam a
    renderizar normalmente (diagnóstico tolerante — é read-only por natureza).

    **Modo live**: (a) se `config.AUTO_PUBLICAR_ARTIGO_SEO`, auto-aprova (via
    `fila.auto_aprovar`) os `artigo_seo` `pendente`s com `linter_ok`; se
    `config.AUTO_PUBLICAR_POST_PAGINA`, auto-aprova (mesma via) os
    `post_pagina` `pendente`s com `linter_ok` — cada auto-aprovação SÓ apanha
    o SEU tipo (o filtro por tipo é responsabilidade de quem chama
    `auto_aprovar`, não da função — ela é TYPE-AGNOSTIC); (b) drena
    `artigo_seo`/`post_grupo` aprovados + auto-aprovados sempre, e
    `post_pagina` SÓ quando `config.facebook_ativo()` (sem page id + token,
    `post_pagina` nem entra nos `tipos` do drain — os itens aprovados ficam
    intactos à espera, sem lease; o relatório sinaliza com `"facebook": "por
    configurar"` quando há pelo menos um, contado por um SELECT read-only)
    (`fila.drain`, cap `config.PUBLICADOR_CAP_PASSAGEM`) — tudo dentro de UMA
    `fila.sessao_governacao()`; (c) por item: `post_grupo` é no-op (o dono
    cola sempre à mão — o `drain` marca `feito`); `artigo_seo` renderiza,
    escreve `{slug}.html`, atualiza o sitemap e publica (git commit+push +
    deploy Cloudflare via staging), POR ITEM: o render/commit são idempotentes
    por slug (reescrever o mesmo ficheiro e tentar comitar sem nada staged são
    ambos no-ops seguros — ver o guard do commit vazio em `_processar`);
    `post_pagina` carrega `corpo_texto` do `EventoAgente` e publica via
    `publicar_facebook` (Graph API). Isto NÃO é auto-retry: o `drain` só
    re-serve itens já `aprovado`/`auto_aprovado` cujo `nao_antes_de`/
    `lease_ate` já passou — um item `falhado` fica `falhado` até alguém o
    repor manualmente a `aprovado` (ver HANDOFF fase 3).

    `executar(cmd, **kw)` é o seam injetável (testes) — o default embrulha
    `subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)`.
    `http_post` é o seam de rede de `publicar_facebook` (testes) — o default
    é `httpx.post`.
    """
    import app.config as config
    import app.db as db
    import app.models_swarm as ms
    from app.swarm import fila

    site_dir = Path(site_dir) if site_dir is not None else (config.BASE_DIR.parent / "site")
    ensaio_dir = (
        Path(ensaio_dir) if ensaio_dir is not None
        else (config.DATA_DIR / "publicador-ensaio")
    )
    executar = executar or _executar_padrao

    if config.CHECKAL_MODO_TESTE:
        ensaio_dir.mkdir(parents=True, exist_ok=True)  # só criado quando é mesmo usado
        artigos: list[dict] = []
        posts = 0
        posts_pagina: list[dict] = []
        with db.get_session() as s:
            itens = (
                s.query(ms.RevisaoItem)
                .filter(ms.RevisaoItem.estado.in_(("aprovado", "auto_aprovado")))
                .filter(ms.RevisaoItem.tipo.in_(_TIPOS_ENSAIO))
                .order_by(ms.RevisaoItem.criado_em, ms.RevisaoItem.id)
                .all()
            )
            for item in itens:
                if item.tipo == "post_grupo":
                    posts += 1
                    continue
                if item.tipo == "post_pagina":
                    posts_pagina.append({"id": item.id, "resumo": item.resumo})
                    continue
                try:
                    artigo = _carregar_artigo(s, item)
                    html_final = render_artigo(artigo)
                    (ensaio_dir / f"{artigo['slug']}.html").write_text(
                        html_final, encoding="utf-8"
                    )
                    artigos.append({"item_id": item.id, "slug": artigo["slug"]})
                except (ValueError, KeyError) as exc:
                    # Ensaio é diagnóstico read-only: um item malformado — payload
                    # em falta/inválido (`_carregar_artigo`) OU recusado pelo
                    # próprio render (slug hostil, esquema de fonte não permitido,
                    # `KeyError` de campo obrigatório em falta) — não rebenta a
                    # passagem; fica no relatório com o erro, e os restantes itens
                    # continuam a ser processados.
                    artigos.append({"item_id": item.id, "erro": str(exc)})
        return {
            "modo": "ensaio", "artigos": artigos, "posts": posts,
            "posts_pagina": posts_pagina,
        }

    hoje = date.today().isoformat()
    publicados: list[dict] = []

    def _processar(item) -> None:
        if item.tipo == "post_grupo":
            return  # no-op — o dono cola sempre à mão; o drain marca 'feito'.
        if item.tipo == "post_pagina":
            corpo = _carregar_corpo_texto(s, item)
            publicar_facebook(
                corpo, page_id=config.FACEBOOK_PAGE_ID, token=config.FACEBOOK_PAGE_TOKEN,
                http_post=http_post,
            )
            return  # publicado — o drain marca 'feito'.
        artigo = _carregar_artigo(s, item)
        slug = artigo["slug"]
        html_final = render_artigo(artigo)
        (site_dir / f"{slug}.html").write_text(html_final, encoding="utf-8")
        atualizar_sitemap(site_dir / "sitemap.xml", slug=slug, lastmod=hoje)

        executar(["git", "-C", str(site_dir), "add", f"{slug}.html", "sitemap.xml"])
        # Guard do commit vazio: um re-serviço (após reposição manual de um
        # item 'falhado' a 'aprovado') pode encontrar o working tree já
        # comitado da tentativa anterior — `git commit` sem nada staged sai
        # com erro e bloquearia o push+deploy para sempre. `diff --cached
        # --quiet` devolve 1 quando HÁ staged changes (commit necessário) e 0
        # quando NÃO há; `check=False` porque um returncode 1 aqui é o
        # caminho normal, não uma falha. Push e deploy correm SEMPRE.
        diff = executar(
            ["git", "-C", str(site_dir), "diff", "--cached", "--quiet"], check=False,
        )
        if getattr(diff, "returncode", 1) != 0:
            executar(["git", "-C", str(site_dir), "commit", "-m", f"artigo: /{slug} (publicador)"])
        executar(["git", "-C", str(site_dir), "push", "origin", "main"])
        _publicar_no_cloudflare(site_dir, executar)

        publicados.append({"item_id": item.id, "slug": slug})

    facebook_ativo = config.facebook_ativo()
    # post_pagina só entra nos tipos servidos pelo drain quando há page id +
    # token — sem config, os itens aprovados nem são leased (ficam intactos
    # à espera; nota "facebook": "por configurar" no relatório, abaixo).
    tipos_live = _TIPOS_PUBLICAVEIS + (("post_pagina",) if facebook_ativo else ())

    with fila.sessao_governacao() as s:
        if config.AUTO_PUBLICAR_ARTIGO_SEO:
            pendentes = (
                s.query(ms.RevisaoItem)
                .filter(ms.RevisaoItem.tipo == "artigo_seo",
                        ms.RevisaoItem.estado == "pendente",
                        ms.RevisaoItem.linter_ok.is_(True))
                .all()
            )
            for item in pendentes:
                fila.auto_aprovar(s, item.id)

        if config.AUTO_PUBLICAR_POST_PAGINA:
            pendentes_pagina = (
                s.query(ms.RevisaoItem)
                .filter(ms.RevisaoItem.tipo == "post_pagina",
                        ms.RevisaoItem.estado == "pendente",
                        ms.RevisaoItem.linter_ok.is_(True))
                .all()
            )
            for item in pendentes_pagina:
                fila.auto_aprovar(s, item.id)

        # Nota "por configurar": SELECT read-only, só quando facebook está
        # inativo (senão o drain já os serve — ver `tipos_live` acima). Nunca
        # marca nada 'falhado'; é só uma contagem para o relatório.
        post_pagina_por_configurar = 0
        if not facebook_ativo:
            post_pagina_por_configurar = (
                s.query(ms.RevisaoItem)
                .filter(ms.RevisaoItem.tipo == "post_pagina",
                        ms.RevisaoItem.estado.in_(("aprovado", "auto_aprovado")))
                .count()
            )

        servidos = fila.drain(
            s, "publicador", tipos=tipos_live,
            cap=config.PUBLICADOR_CAP_PASSAGEM, incluir_auto_aprovado=True,
            processador=_processar,
        )
        posts_fechados = sum(
            1 for i in servidos if i.tipo == "post_grupo" and i.estado == "feito"
        )

    relatorio = {
        "modo": "live", "publicados": publicados, "posts_fechados": posts_fechados,
    }
    if post_pagina_por_configurar:
        relatorio["facebook"] = "por configurar"
    return relatorio
