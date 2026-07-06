"""Testes das PÁGINAS institucionais — app.web.paginas (SPEC-FASE1-WEB §paginas).

Contrato garantido:

  GET /precos       200 HTML · preços canónicos de config.PLANOS (fonte ÚNICA; nunca
                    duplicados/inventados) + AL adicional + garantia + IVA incluído;
  GET /privacidade  200 HTML · estrutura RGPD REAL (responsável Cosmic Oasis, Lda.,
                    fonte RNAL, base legal, direitos, CNPD, privacidade@checkal.pt) +
                    placeholders [NIPC]/[morada] onde faltam dados;
  GET /termos       200 HTML · cláusulas críticas (natureza informativa — NÃO
                    aconselhamento jurídico, SLA ≤7 dias, garantia/livre resolução,
                    limitação de responsabilidade) + placeholders legais;
  GET /obrigado     200 HTML · confirmação pós-inscrição (double opt-in pendente).

Todas estendem `base.html` (rodapé com o qualificador legal — serviço PRIVADO, nunca
aspeto de Estado). Renderizadas pela instância Jinja PARTILHADA (autoescape ligado).
SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as config


@pytest.fixture()
def client():
    # Monta só o router das páginas (isolado — o wire em criar_app é do agente de
    # integração). As páginas só referenciam /static por URL, logo não precisam do mount.
    from app.web import paginas

    app = FastAPI()
    app.include_router(paginas.router)
    return TestClient(app)


# ==========================================================================
#  Todas as páginas: 200 HTML + estendem base.html (rodapé legal, serviço PRIVADO)
# ==========================================================================
@pytest.mark.parametrize("rota", ["/precos", "/privacidade", "/termos", "/obrigado"])
def test_pagina_200_html(client, rota):
    r = client.get(rota)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # estende base.html → marca + qualificador legal (serviço PRIVADO, nunca Estado)
    assert "CheckAL" in corpo
    assert "serviço privado e independente" in corpo
    assert "Cosmic Oasis" in corpo
    # rodapé com os links legais obrigatórios
    assert "/privacidade" in corpo
    assert "/termos" in corpo
    assert "/remover" in corpo
    # português
    assert 'lang="pt"' in corpo


# ==========================================================================
#  /precos — preços canónicos de config.PLANOS (não se inventa a folha)
# ==========================================================================
def test_precos_mostra_planos_canonicos(client):
    corpo = client.get("/precos").text
    # os três planos principais (49 / 119 / 149) da tabela canónica
    assert str(int(config.PLANOS["anual"]["preco"])) in corpo      # 49
    assert str(int(config.PLANOS["trienal"]["preco"])) in corpo    # 119
    assert str(int(config.PLANOS["portfolio"]["preco"])) in corpo  # 149
    # tiers de portfólio superiores
    assert str(int(config.PLANOS["portfolio_plus"]["preco"])) in corpo  # 299
    assert str(int(config.PLANOS["portfolio_max"]["preco"])) in corpo   # 499


def test_precos_mostra_al_adicional(client):
    # o cliente com 2–3 ALs (o núcleo do alvo) decide sem calculadora: +19€/ano visível
    corpo = client.get("/precos").text
    assert "+{}".format(int(config.AL_ADICIONAL_ANUAL)) in corpo   # +19


def test_precos_garantia_e_iva(client):
    corpo = client.get("/precos").text
    assert "30 dias" in corpo   # garantia
    assert "IVA" in corpo       # preços com IVA incluído


def test_precos_nao_usa_coima_proibida(client):
    # PRICING §1: 7.500€ é falso para singulares e está proibido em toda a copy
    assert "7.500" not in client.get("/precos").text


# ==========================================================================
#  /privacidade — estrutura RGPD real
# ==========================================================================
def test_privacidade_estrutura_rgpd(client):
    corpo = client.get("/privacidade").text
    # responsável pelo tratamento
    assert "Cosmic Oasis" in corpo
    assert "privacidade@checkal.pt" in corpo
    # fonte dos dados + base legal
    assert "RNAL" in corpo
    assert "interesse legítimo" in corpo
    # autoridade de controlo
    assert "CNPD" in corpo
    # direitos do titular (RGPD)
    for direito in ("acesso", "retificação", "apagamento", "oposição"):
        assert direito in corpo, f"direito RGPD em falta: {direito}"
    # placeholders honestos onde faltam dados da entidade
    assert "[NIPC]" in corpo
    assert "[morada]" in corpo


# ==========================================================================
#  /termos — cláusulas críticas (LEGAL §5)
# ==========================================================================
def test_termos_clausulas_criticas(client):
    corpo = client.get("/termos").text
    assert "Cosmic Oasis" in corpo
    # natureza: informação, NÃO aconselhamento jurídico
    assert "informação" in corpo
    assert "aconselhamento" in corpo
    # SLA de deteção ≤ 7 dias
    assert "7 dias" in corpo
    # livre resolução (14 dias) + garantia (30 dias)
    assert "14 dias" in corpo
    assert "30 dias" in corpo
    # limitação de responsabilidade
    assert "responsabilidade" in corpo
    # placeholder legal onde falta o NIPC
    assert "[NIPC]" in corpo


# ==========================================================================
#  /obrigado — confirmação pós-inscrição (double opt-in pendente)
# ==========================================================================
def test_obrigado_confirma_double_opt_in(client):
    corpo = client.get("/obrigado").text.lower()
    # pede a confirmação por email (double opt-in) — voz do inspetor amigo, positiva
    assert "confirma" in corpo
    assert "email" in corpo


# ==========================================================================
#  Anti-XSS — as páginas saem pela instância Jinja partilhada (autoescape ligado)
# ==========================================================================
def test_paginas_usam_o_jinja_partilhado_com_autoescape():
    from app.web import marca, paginas  # noqa: F401  (garante import sem rede)

    # o router reutiliza a instância partilhada (fonte única do autoescape anti-XSS)
    assert paginas.templates is marca.templates
    env = marca.templates.env
    assert env.autoescape is True or callable(env.autoescape)
