"""Testes da landing consent-first — app.web.landing (SPEC-FASE1-WEB §landing).

Garante o contrato da página inicial FINAL (já não placeholder), com a copy
canónica de COPY-VENDAS.md e os preços de config.PLANOS:

  * `GET /` → 200 HTML, estende `base.html` (logo + rodapé legal herdados);
  * hero com a headline/tagline "O teu AL? Check" e a subheadline canónica;
  * barra de prova que afirma o serviço PRIVADO ("não somos o Turismo de Portugal");
  * o WIDGET "Faz o check grátis ao teu AL" — input do nº de registo que o JS liga a
    `GET /api/verificar`, seguido do form de email + checkbox de consentimento que faz
    `POST /inscrever` (consent-first, checkbox NÃO pré-marcada);
  * secções "como funciona" (3 checks: Registo/Seguro/Regulamento), preços (49/119/149
    de config.PLANOS), confiança, FAQ e garantia de 30 dias;
  * o JS do widget é anti-XSS (usa `textContent`, nunca injeta `innerHTML` de dados).

`GET /saude` mantém-se `{"ok": true}`. SEM rede, SEM BD (a rota `/` só renderiza).
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as config


@pytest.fixture()
def client():
    from app.web import landing

    app = FastAPI()
    app.include_router(landing.router)
    return TestClient(app)


# --------------------------------------------------------------------------
#  Contrato base — 200 HTML + healthcheck intacto
# --------------------------------------------------------------------------
def test_landing_200_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_saude_mantem_se(client):
    r = client.get("/saude")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"ok": True}


def test_estende_base_html(client):
    # herda o cromado do layout base: logo no header, qualificador legal no rodapé
    html = client.get("/").text
    assert "/static/marca/logo-horizontal.svg" in html
    assert "/static/brand.css" in html
    assert "Cosmic Oasis" in html
    assert 'lang="pt"' in html


# --------------------------------------------------------------------------
#  Hero + barra de prova (copy canónica de COPY-VENDAS.md)
# --------------------------------------------------------------------------
def test_hero_headline_e_tagline(client):
    html = client.get("/").text
    assert "O teu AL? Check" in html          # tagline/headline
    assert "10.000 registos" in html          # subheadline canónica (COPY-VENDAS §3)


def test_barra_de_prova_afirma_servico_privado(client):
    # inviolável: serviço PRIVADO, nunca aspeto de Estado
    html = client.get("/").text
    assert "não somos o Turismo de Portugal" in html


# --------------------------------------------------------------------------
#  WIDGET consent-first — check grátis → /api/verificar
# --------------------------------------------------------------------------
def test_widget_check_gratis(client):
    html = client.get("/").text
    assert 'id="verificar"' in html                     # âncora do CTA do header
    assert "Faz o check grátis ao teu AL" in html       # título do widget
    assert 'name="q"' in html                           # input do nº de registo/nome
    assert "/api/verificar" in html                     # o JS consome o endpoint público


def test_form_consentimento_para_inscrever(client):
    html = client.get("/").text
    assert 'action="/inscrever"' in html                # POST consent-first
    assert 'method="post"' in html
    assert 'type="email"' in html                       # campo de email
    assert 'type="checkbox"' in html                    # checkbox de consentimento
    # GRANULAR (CNPD): dois consentimentos INDEPENDENTES, nenhum pré-marcado
    assert 'name="consent_alertas"' in html
    assert 'name="consent_ofertas"' in html
    # nenhuma checkbox pré-marcada (consent-first): sem atributo `checked`
    assert "checked" not in html
    assert "/privacidade" in html                       # o consentimento liga à política


def test_consentimento_granular_renderiza_texto_canonico(client):
    # a prova gravada TEM de ser exatamente o texto mostrado: os labels renderizam
    # as constantes canónicas de app.web.consentimento (fecha o drift do red-team)
    from app.web import consentimento

    html = client.get("/").text
    assert consentimento.CONSENTIMENTO_ALERTAS_TEXTO in html
    assert consentimento.CONSENTIMENTO_OFERTAS_TEXTO in html
    # identidade do responsável junto aos checkboxes (RGPD art. 13.º)
    assert "Cosmic Oasis, Lda. — CheckAL" in html
    # NÃO afirmar a base de publicidade do email (LEGAL-PARECER §2/§5 — por confirmar)
    assert "art. 10" not in html


def test_widget_js_e_anti_xss(client):
    # o JS constrói o cartão de estado com textContent — nunca injeta HTML de dados
    html = client.get("/").text
    assert "textContent" in html
    assert "innerHTML" not in html


# --------------------------------------------------------------------------
#  Secções: como funciona (3 checks), preços, FAQ, garantia
# --------------------------------------------------------------------------
def test_como_funciona_3_checks(client):
    html = client.get("/").text
    assert "Como funciona" in html
    for check in ("Registo", "Seguro", "Regulamento"):
        assert check in html


def test_precos_vem_de_config(client):
    # a landing NÃO duplica a tabela de preços — lê de config.PLANOS
    html = client.get("/").text
    assert f"{int(config.PLANOS['anual']['preco'])}€" in html       # 49€
    assert f"{int(config.PLANOS['trienal']['preco'])}€" in html     # 119€
    assert f"{int(config.PLANOS['portfolio']['preco'])}€" in html   # 149€


def test_faq_presente(client):
    html = client.get("/").text
    assert "<details" in html                            # FAQ acessível
    assert "advogado" in html                            # pergunta canónica (COPY-VENDAS §3)


def test_garantia_30_dias(client):
    html = client.get("/").text
    assert "30 dias" in html
