"""Testes do DESIGN SYSTEM do CheckAL — fundação da FASE 1 web (SPEC-FASE1-WEB §marca.py).

Garante o contrato da fundação de que todos os outros módulos web dependem:

  app.web.marca (tokens canónicos, SEM rede, SEM BD):
    - as cores do SPEC estão presentes e imutáveis (grafite/verde-check/azul-ação/…);
    - os caminhos dos assets SVG apontam para `/static/marca/…`;
    - `PLANOS` é a MESMA folha de `config.PLANOS` (fonte única — não se reinventa);
    - `contexto_base()` devolve marca/cores/assets/planos para os templates Jinja.

  app.web.static/brand.css (o design system, servido por StaticFiles):
    - `GET /static/brand.css` → 200 `text/css`, com as variáveis CSS dos tokens.

  app.web.templates/base.html (layout base, renderizado por Jinja):
    - renderiza com o `logo-horizontal.svg`, a marca "CheckAL", o qualificador legal
      ("serviço privado e independente… · Cosmic Oasis, Lda.") e os links
      privacidade/termos/remover no rodapé.

  Composição (criar_app):
    - StaticFiles montado em `/static` (brand.css + assets acessíveis);
    - as rotas existentes (`/`, `/saude`, `/api/verificar`, `/webhooks/stripe`)
      continuam registadas — a fundação NÃO parte nada.

SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _app():
    from app.web.app import criar_app

    return criar_app()


# ==========================================================================
#  app.web.marca — tokens canónicos (função pura, sem rede/BD)
# ==========================================================================
def test_cores_canonicas_do_spec():
    from app.web import marca

    # Cores do SPEC-FASE1-WEB (inviolável): não inventadas, exatamente estas.
    assert marca.COR_GRAFITE == "#0F172A"
    assert marca.COR_VERDE_CHECK == "#12B76A"
    assert marca.COR_AZUL_ACAO == "#2563EB"
    assert marca.COR_CINZA_SUSPENSO == "#94A3B8"
    assert marca.COR_AMBAR == "#F59E0B"
    assert marca.COR_CORAL == "#DC2626"
    assert marca.COR_FUNDO_FRIO == "#F8FAFC"
    assert marca.COR_MARFIM == "#F6F2E9"
    assert marca.COR_TEXTO_SECUNDARIO == "#475569"


def test_assets_apontam_para_static_marca():
    from app.web import marca

    assert marca.LOGO_HORIZONTAL == "/static/marca/logo-horizontal.svg"
    # os ficheiros referenciados existem mesmo no disco
    assert marca.STATIC_DIR.is_dir()
    assert (marca.STATIC_DIR / "marca" / "logo-horizontal.svg").is_file()
    assert (marca.STATIC_DIR / "marca" / "selo-ativo.svg").is_file()
    assert (marca.STATIC_DIR / "marca" / "selo-suspenso.svg").is_file()


def test_planos_sao_a_folha_de_config():
    from app.web import marca
    import app.config as config

    # Fonte ÚNICA de preços: não se duplica a tabela, reexporta-se.
    assert marca.PLANOS is config.PLANOS
    assert marca.PLANOS["anual"]["preco"] == 49.0
    assert marca.PLANOS["trienal"]["preco"] == 119.0


def test_contexto_base_alimenta_os_templates():
    from app.web import marca

    ctx = marca.contexto_base()
    assert isinstance(ctx, dict)
    # blocos que os templates consomem
    assert ctx["marca"]["nome"] == "CheckAL"
    assert ctx["marca"]["tagline"] == "O teu AL? Check."
    assert "serviço privado e independente" in ctx["marca"]["qualificador_legal"]
    assert "Cosmic Oasis" in ctx["marca"]["qualificador_legal"]
    assert ctx["assets"]["logo_horizontal"] == "/static/marca/logo-horizontal.svg"
    assert ctx["cores"]["grafite"] == "#0F172A"
    assert ctx["planos"] is marca.PLANOS


# ==========================================================================
#  brand.css — o design system servido por StaticFiles
# ==========================================================================
def test_brand_css_servido_200_text_css():
    client = TestClient(_app())
    r = client.get("/static/brand.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    corpo = r.text
    # variáveis CSS dos tokens presentes (design system, não folha vazia)
    assert "--cor-grafite" in corpo
    assert "#0F172A" in corpo
    assert "#12B76A" in corpo
    assert "#2563EB" in corpo
    # tipografia da marca
    assert "Plus Jakarta Sans" in corpo
    assert "Inter" in corpo
    # estados 🟢🟡🔴 têm classes utilitárias
    assert ".estado" in corpo


def test_assets_svg_servidos_por_static():
    client = TestClient(_app())
    r = client.get("/static/marca/logo-horizontal.svg")
    assert r.status_code == 200
    assert "svg" in r.headers["content-type"].lower()
    assert "CheckAL" in r.text


# ==========================================================================
#  base.html — layout base renderizado por Jinja
# ==========================================================================
def test_base_html_renderiza_com_logo_e_rodape_legal():
    from app.web import marca

    # renderiza o layout base isolado (os globais da marca alimentam-no)
    html = marca.templates.get_template("base.html").render()
    # header traz o logo horizontal
    assert "/static/marca/logo-horizontal.svg" in html
    # liga a folha do design system
    assert "/static/brand.css" in html
    # marca e qualificador legal (serviço PRIVADO, nunca aspeto de Estado)
    assert "CheckAL" in html
    assert "serviço privado e independente" in html
    assert "Cosmic Oasis" in html
    # rodapé com os links obrigatórios
    assert "/privacidade" in html
    assert "/termos" in html
    assert "/remover" in html
    # tipografia carregada via Google Fonts (<link>)
    assert "fonts.googleapis.com" in html
    # português
    assert 'lang="pt"' in html


def test_base_html_autoescape_ativo():
    from app.web import marca

    # o ambiente Jinja partilhado tem autoescape ligado (anti-XSS) — herdado por
    # todos os templates que estendem base.html.
    assert marca.templates.env.autoescape is True or callable(marca.templates.env.autoescape)
    render = marca.templates.env.from_string("{{ x }}").render(x='<script>alert(1)</script>')
    assert "<script>" not in render
    assert "&lt;script&gt;" in render


# ==========================================================================
#  Composição — a fundação não parte as rotas existentes (regressão do test_app)
# ==========================================================================
def test_static_montado_sem_partir_rotas_existentes():
    app = _app()
    caminhos = {getattr(r, "path", None) for r in app.routes}
    for esperado in ("/", "/saude", "/api/verificar", "/webhooks/stripe"):
        assert esperado in caminhos, f"rota partida pela fundação: {esperado}"


def test_saude_e_home_continuam_verdes():
    client = TestClient(_app())
    assert client.get("/saude").json() == {"ok": True}
    r = client.get("/")
    assert r.status_code == 200
    assert "CheckAL" in r.text
