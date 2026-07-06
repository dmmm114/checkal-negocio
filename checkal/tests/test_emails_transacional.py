"""Testes dos templates TRANSACIONAIS do CheckAL (SPEC-FASE1-EMAILS §transacional).

Os quatro emails do Canal A (Resend), compostos sobre `app.emails.base`:
  * `boas_vindas` — boas-vindas + linha dos 3 checks + link do selo + nota do PDF inicial;
  * `alerta_estado` — 🟢/🟡/🔴, assunto conforme MARCA.md, disclaimer "não aconselhamento";
  * `relatorio_mensal` — "✅ {mês}: o teu AL passou no check — relatório CheckAL";
  * `confirmacao_consentimento` — double opt-in (`/confirmar?token=`) + consentimento GRANULAR.

Contrato herdado da base (inviolável, garantido em HTML **e** texto): remetente identificado
(wordmark "CheckAL"), rodapé legal (Cosmic Oasis, Lda.) e opt-out 1-clique (`checkal.pt/remover`).
Copy de `../COPY-VENDAS.md` / `MARCA.md` — não inventar. LIVE-GATED: importar/rodar não toca
a rede nem a BD (puro). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest

from app.emails import base


# Dados de exemplo reutilizados
NOME_AL = "Casa da Graça"
NR = "93415/AL"
URL_SELO = "https://checkal.pt/selo/93415"
FACTO = "novo regulamento em Lisboa"


# ==========================================================================
#  Assuntos canónicos (constantes/funções do módulo)
# ==========================================================================
def test_constantes_de_assunto():
    from app.emails import transacional as t

    # boas-vindas: assunto fixo (SPEC-FASE1-EMAILS §transacional)
    assert t.ASSUNTO_BOAS_VINDAS == "✅ O teu AL passou no check — bem-vindo ao CheckAL"
    # relatório mensal: assunto parametrizado pelo mês (MARCA.md)
    assert (
        t.assunto_relatorio_mensal("Junho")
        == "✅ Junho: o teu AL passou no check — relatório CheckAL"
    )


def test_assunto_alerta_por_estado():
    from app.emails import transacional as t

    # 🔴 — formato canónico do MARCA.md/SPEC (guillemets + facto)
    assert (
        t.assunto_alerta(NOME_AL, "vermelho", FACTO)
        == "🔴 ALERTA CheckAL — o teu AL «Casa da Graça» falhou o check: novo regulamento em Lisboa"
    )
    # 🟡 — "1 ponto sem check"
    a = t.assunto_alerta(NOME_AL, "amarelo", "seguro por confirmar")
    assert a.startswith("🟡")
    assert "«Casa da Graça»" in a
    assert "1 ponto sem check" in a
    # 🟢 — "passou no check"
    v = t.assunto_alerta(NOME_AL, "verde")
    assert v.startswith("🟢")
    assert "passou no check" in v


def test_url_confirmar_1clique():
    from app.emails import transacional as t

    assert t.url_confirmar("tok-abc") == "https://checkal.pt/confirmar?token=tok-abc"
    # token com caracteres especiais vai URL-encoded
    assert "token=a%2Fb" in t.url_confirmar("a/b")


# ==========================================================================
#  boas_vindas
# ==========================================================================
def test_boas_vindas():
    from app.emails import transacional as t

    email = t.boas_vindas(
        nome_al=NOME_AL,
        nr_registo=NR,
        url_selo=URL_SELO,
        nome="Ana",
        email_destinatario="ana@exemplo.pt",
        token_optout="tok1",
    )
    assert isinstance(email, base.EmailRenderizado)
    # assunto correto
    assert email.assunto == t.ASSUNTO_BOAS_VINDAS
    for conteudo in (email.html, email.texto):
        # linha dos 3 checks (micro-copy do produto — MARCA.md)
        assert "Registo: check ✓" in conteudo
        assert "Seguro: check ✓" in conteudo
        assert "Regulamento: check ✓" in conteudo
        # link do selo
        assert URL_SELO in conteudo
        # nota do Relatório Inicial (anexado pelo onboarding)
        assert "Relatório Inicial" in conteudo
        # o AL e o registo aparecem
        assert NOME_AL in conteudo
        assert NR in conteudo
        # opt-out 1-clique propagado com o destinatário
        assert "checkal.pt/remover" in conteudo
        assert "e=ana%40exemplo.pt" in conteudo
    # marca por HTML/CSS, sem imagem externa
    assert "<img" not in email.html.lower()
    assert "#12B76A" in email.html


# ==========================================================================
#  alerta_estado — 🟢/🟡/🔴
# ==========================================================================
def test_alerta_estado_vermelho():
    from app.emails import transacional as t

    email = t.alerta_estado(
        nome_al=NOME_AL,
        estado="vermelho",
        facto=FACTO,
        titulo="Regulamento municipal",
        corpo="A Câmara de Lisboa publicou a 2.ª alteração ao regulamento de AL.\n\nA tua freguesia entra em contenção absoluta.",
        cta_texto="Ver o meu AL no CheckAL",
        cta_url="https://checkal.pt/conta",
        email_destinatario="ana@exemplo.pt",
        token_optout="tok1",
    )
    # assunto conforme MARCA.md/SPEC
    assert (
        email.assunto
        == "🔴 ALERTA CheckAL — o teu AL «Casa da Graça» falhou o check: novo regulamento em Lisboa"
    )
    for conteudo in (email.html, email.texto):
        assert "\U0001F534" in conteudo  # 🔴
        assert "Regulamento municipal" in conteudo
        assert "contenção absoluta" in conteudo  # corpo (IA/determinístico) embrulhado
        # disclaimer "informação, não aconselhamento jurídico" (parecer §7)
        assert "aconselhamento jurídico" in conteudo
        # CTA
        assert "https://checkal.pt/conta" in conteudo
        # opt-out sempre
        assert "checkal.pt/remover" in conteudo
    # cor canónica do estado 🔴 (coral) no HTML
    assert "#DC2626" in email.html


def test_alerta_estado_amarelo_e_verde():
    from app.emails import transacional as t

    amarelo = t.alerta_estado(
        nome_al=NOME_AL, estado="amarelo", facto="seguro por confirmar",
        titulo="Seguro obrigatório", corpo="Confirma a data da tua comunicação anual.",
    )
    assert amarelo.assunto.startswith("🟡")
    assert "1 ponto sem check" in amarelo.assunto
    assert "\U0001F7E1" in amarelo.html          # 🟡
    assert "#F59E0B" in amarelo.html             # âmbar
    assert "aconselhamento jurídico" in amarelo.html

    verde = t.alerta_estado(
        nome_al=NOME_AL, estado="verde",
        titulo="Registo no RNAL", corpo="O teu registo continua ativo.",
    )
    assert verde.assunto.startswith("🟢")
    assert "passou no check" in verde.assunto
    assert "\U0001F7E2" in verde.html            # 🟢
    assert "#12B76A" in verde.html               # verde-check
    assert "aconselhamento jurídico" in verde.html


def test_alerta_estado_invalido():
    from app.emails import transacional as t

    with pytest.raises(ValueError):
        t.alerta_estado(nome_al=NOME_AL, estado="laranja", facto="x")


# ==========================================================================
#  relatorio_mensal
# ==========================================================================
def test_relatorio_mensal():
    from app.emails import transacional as t

    email = t.relatorio_mensal(
        mes="Junho",
        nome_al=NOME_AL,
        nome="Ana",
        resumo="Analisámos 16 publicações do teu concelho; nenhuma te afetou.",
        n_analisadas=16,
        n_relevantes=0,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok1",
    )
    assert email.assunto == "✅ Junho: o teu AL passou no check — relatório CheckAL"
    for conteudo in (email.html, email.texto):
        assert "Junho" in conteudo
        # estado verde "tudo em ordem" + a linha dos 3 checks
        assert "\U0001F7E2" in conteudo          # 🟢
        assert "Registo: check ✓" in conteudo
        # o resumo do valor entregue
        assert "16 publicações" in conteudo
        assert "checkal.pt/remover" in conteudo
    assert "#12B76A" in email.html
    # relatório NÃO é um alerta: sem disclaimer de aconselhamento
    assert "aconselhamento jurídico" not in email.html


# ==========================================================================
#  confirmacao_consentimento — double opt-in + granular
# ==========================================================================
def test_confirmacao_consentimento_granular_so_alertas():
    from app.emails import transacional as t

    email = t.confirmacao_consentimento(
        token="tok-xyz",
        consente_alertas=True,
        consente_ofertas=False,
        nome="Ana",
        email_destinatario="ana@exemplo.pt",
        token_optout="tok1",
    )
    assert email.assunto == t.ASSUNTO_CONFIRMACAO
    for conteudo in (email.html, email.texto):
        # link de confirmação double opt-in
        assert "checkal.pt/confirmar?token=tok-xyz" in conteudo
        # reflete o consentimento dado: alertas SIM
        assert "alertas" in conteudo.lower()
        # ofertas NÃO foi consentido → não promete ofertas
        assert "ofertas" not in conteudo.lower()
        # linguagem de double opt-in
        assert "confirm" in conteudo.lower()
        assert "checkal.pt/remover" in conteudo


def test_confirmacao_consentimento_alertas_e_ofertas():
    from app.emails import transacional as t

    email = t.confirmacao_consentimento(
        token="tok-xyz", consente_alertas=True, consente_ofertas=True,
    )
    for conteudo in (email.html, email.texto):
        assert "alertas" in conteudo.lower()
        assert "ofertas" in conteudo.lower()


def test_confirmacao_aceita_url_pronta():
    from app.emails import transacional as t

    email = t.confirmacao_consentimento(url_confirmar="https://checkal.pt/confirmar?token=Q")
    assert "checkal.pt/confirmar?token=Q" in email.html


# ==========================================================================
#  Invariantes transversais — opt-out + remetente + rodapé em TODOS
# ==========================================================================
def _todos_os_emails():
    from app.emails import transacional as t

    return [
        t.boas_vindas(nome_al=NOME_AL, nr_registo=NR, url_selo=URL_SELO),
        t.alerta_estado(nome_al=NOME_AL, estado="vermelho", facto=FACTO,
                        titulo="Regulamento", corpo="corpo do alerta"),
        t.relatorio_mensal(mes="Junho", nome_al=NOME_AL, resumo="tudo em ordem"),
        t.confirmacao_consentimento(token="tok"),
    ]


def test_todos_tem_remetente_rodape_optout():
    for email in _todos_os_emails():
        assert isinstance(email, base.EmailRenderizado)
        assert email.assunto.strip()
        for conteudo in (email.html, email.texto):
            assert "CheckAL" in conteudo                 # remetente identificado
            assert "Cosmic Oasis, Lda." in conteudo      # rodapé legal
            assert "checkal.pt/remover" in conteudo      # opt-out 1-clique
        # HTML: marca por CSS, sem imagem externa nem CDN
        assert "<img" not in email.html.lower()
        assert "http://" not in email.html


def test_disclaimer_so_nos_alertas():
    from app.emails import transacional as t

    # o disclaimer de "não aconselhamento" é exclusivo dos alertas (parecer §7)
    nao_alertas = [
        t.boas_vindas(nome_al=NOME_AL, nr_registo=NR, url_selo=URL_SELO),
        t.relatorio_mensal(mes="Junho", nome_al=NOME_AL),
        t.confirmacao_consentimento(token="tok"),
    ]
    for email in nao_alertas:
        assert "aconselhamento jurídico" not in email.html
        assert "aconselhamento jurídico" not in email.texto


# ==========================================================================
#  Pureza — importar não toca a rede/BD
# ==========================================================================
def test_import_puro():
    import importlib

    mod = importlib.import_module("app.emails.transacional")
    for nome in ("boas_vindas", "alerta_estado", "relatorio_mensal", "confirmacao_consentimento"):
        assert hasattr(mod, nome)
