"""Testes do PUBLICADOR — parte 1: render determinista do artigo + sitemap.

`app/publicador.py` é "o braço determinista da publicação — o LLM propõe, o
dono/config aprova, ISTO publica" (fase 3, F3.3). Esta suite cobre só a parte 1:
`md_para_html`, `render_artigo`, `atualizar_sitemap`. A passagem completa
(drain/ensaio, git, wrangler) é a F3.4 — fora do âmbito daqui.

Escritos ANTES da implementação (TDD). Sem BD, sem rede: funções puras sobre
dicts/ficheiros.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from app import publicador

# Baseado no `_ARTIGO_OK` de test_manage_editor_comunicador.py, com
# `data_publicacao` fixa (necessário para o teste de idempotência — sem data
# fixa, `render_artigo` carimbaria `date.today()` e duas chamadas em dias
# diferentes divergiriam).
_ARTIGO = {
    "slug": "regulamentos-al-porto",
    "titulo": "Regulamentos municipais de Alojamento Local no Porto: o essencial",
    "meta_description": "O que muda para o AL no Porto e onde confirmar na fonte oficial.",
    "tipo_pagina": "pilar",
    "data_publicacao": "2026-07-19",
    "seccoes": [
        {"h2": "O que é o regulamento municipal",
         "corpo_md": "Cada município pode definir regras próprias para o AL."},
        {"h2": "Onde confirmar",
         "corpo_md": "A fonte oficial é o portal do município e o Diário da República."},
    ],
    "fontes": [
        {"url": "https://www.cm-porto.pt/regulamento-al",
         "titulo": "Regulamento AL — CM Porto", "data": "2026-05-10",
         "excerto": "O presente regulamento define as regras aplicáveis."},
    ],
}

# Cabeçalho + entrada de "/" — cópia do formato real de site/sitemap.xml
# (indentação 2 espaços no <url>, 4 nos filhos).
SITEMAP_BASE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.checkal.pt/</loc>
    <lastmod>2026-07-17</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def test_md_para_html_paragrafos_negrito_listas():
    md = "Primeiro **par**.\n\nSegundo.\n\n1. um\n2. dois\n\n- a\n- b"
    html = publicador.md_para_html(md)
    assert "<p>Primeiro <strong>par</strong>.</p>" in html
    assert "<ol>" in html and "<li>um</li>" in html
    assert "<ul>" in html and "<li>a</li>" in html


def test_md_para_html_escapa_html():
    assert "&lt;script&gt;" in publicador.md_para_html("olá <script>alert(1)</script>")


def test_render_artigo_estrutura_completa():
    html = publicador.render_artigo(_ARTIGO)
    # canonical/OG/JSON-LD/slug
    assert f'href="https://www.checkal.pt/{_ARTIGO["slug"]}"' in html
    assert '"datePublished": "' in html
    # blocos garantidos ao linter (fonte única — as CONSTANTES, não cópias):
    from app.compliance.linter import DIVULGACAO_IA, DISCLAIMER_NAO_ACONSELHAMENTO
    assert DIVULGACAO_IA in html
    assert DISCLAIMER_NAO_ACONSELHAMENTO in html
    # fontes e CTA com data-evento por slug (header E corpo — a revisão notou
    # que faltava cobrir o do header)
    assert _ARTIGO["fontes"][0]["url"] in html
    assert f'data-evento="cta_{_ARTIGO["slug"]}_header"' in html
    assert f'data-evento="cta_{_ARTIGO["slug"]}_corpo"' in html
    # sem scripts inline executáveis (CSP script-src 'self'); ld+json permitido
    scripts = re.findall(r"<script(?![^>]*application/ld\+json)[^>]*>", html)
    assert all("src=" in s for s in scripts)


def test_render_artigo_idempotente():
    assert publicador.render_artigo(_ARTIGO) == publicador.render_artigo(_ARTIGO)


def test_sitemap_acrescenta_e_atualiza_idempotente(tmp_path):
    sm = tmp_path / "sitemap.xml"
    sm.write_text(SITEMAP_BASE)
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-19")
    txt = sm.read_text()
    assert "<loc>https://www.checkal.pt/regulamentos-al-porto</loc>" in txt
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-20")
    txt2 = sm.read_text()
    assert txt2.count("regulamentos-al-porto") == 1          # atualiza, não duplica
    assert "<lastmod>2026-07-20</lastmod>" in txt2


def test_render_artigo_sem_data_carimba_hoje():
    artigo = {k: v for k, v in _ARTIGO.items() if k != "data_publicacao"}
    html = publicador.render_artigo(artigo)
    assert f'"datePublished": "{date.today().isoformat()}"' in html


# ==========================================================================
#  Regressão — 2 Critical de XSS apanhados em revisão (2026-07-19)
# ==========================================================================
def test_render_recusa_slug_hostil():
    """O slug é autorado pelo LLM e entra cru em canonical/og:url/data-evento
    ×2/sitemap — whitelist estrita, não só escape (mata injeção E path
    traversal de uma vez)."""
    mau = dict(_ARTIGO)
    mau["slug"] = '../../evil"><script>x</script>'
    with pytest.raises(ValueError):
        publicador.render_artigo(mau)


def test_render_titulo_hostil_nao_fecha_script():
    """O `titulo` entra no JSON-LD via json.dumps (não html.escape) — sem
    neutralizar `<`/`>`/`&`, um `</script>` no valor fecha o bloco JSON-LD
    prematuramente e o `<script>` seguinte executa."""
    mau = dict(_ARTIGO)
    mau["titulo"] = "Olá </script><script>alert(1)</script>"
    html_out = publicador.render_artigo(mau)
    assert "</script><script>alert" not in html_out
    # e o head só tem scripts src= ou ld+json (regex do teste de estrutura)
    scripts = re.findall(r"<script(?![^>]*application/ld\+json)[^>]*>", html_out)
    assert all("src=" in s for s in scripts)


def test_sitemap_recusa_slug_hostil(tmp_path):
    sm = tmp_path / "sitemap.xml"
    sm.write_text(SITEMAP_BASE)
    with pytest.raises(ValueError):
        publicador.atualizar_sitemap(sm, slug="../../evil", lastmod="2026-07-19")
