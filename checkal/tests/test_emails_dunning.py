"""Testes dos templates de email de **dunning** do CheckAL (SPEC-FASE1-EMAILS §dunning).

A régua de renovação/cobrança, agora vestida com a marca (branded HTML + versão texto):

  * ``renovacao_d30``  — D-30: "a tua proteção renova a {data}" + resumo do valor entregue;
  * ``aviso_d7``       — D-7: a cobrança é iminente, confirma o cartão;
  * ``falha_pagamento``— D+3/D+7: a cobrança falhou, **link Stripe para atualizar o cartão**;
  * ``cancelado_final``— D+21: "o teu AL deixou de estar monitorizado" (win-back).

Copy alinhada com ``AUTOMACAO.md §5`` / ``COPY-VENDAS.md`` e com a máquina de estados de
``app/dunning.py`` (para o *wire* poder trocar o HTML ad-hoc pelos templates sem partir testes).

Contrato herdado da base (inviolável, ver ``test_email_base.py``): cada email leva SEMPRE — em
HTML **e** em texto — remetente identificado (CheckAL), rodapé legal (Cosmic Oasis, Lda. · morada)
e **opt-out 1-clique** (``checkal.pt/remover``). Dunning é comunicação de faturação: leva o
disclaimer "não constitui aconselhamento jurídico".

LIVE-GATED: renderizar NÃO toca a rede/BD (só compila templates). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest


# ==========================================================================
#  Contexto-tipo de cada builder (dados dinâmicos; o template é que é dono da copy)
# ==========================================================================
DATA = "05/07/2027"
PRECO = "49 €"
GERIR = "https://checkal.pt/conta/subscricao"          # área de cliente / portal Stripe
RESUMO = "No último ciclo fizemos 2 varrimento(s) nacionais do RNAL e enviámos-te 1 alerta(s)."


def _d30(**kw):
    from app.emails import dunning
    base = dict(
        nome="Ana",
        plano_nome="CheckAL Anual",
        data_renovacao=DATA,
        preco=PRECO,
        url_gerir=GERIR,
        resumo_valor=RESUMO,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    base.update(kw)
    return dunning.renovacao_d30(**base)


def _d7(**kw):
    from app.emails import dunning
    base = dict(
        nome="Ana",
        plano_nome="CheckAL Anual",
        data_renovacao=DATA,
        preco=PRECO,
        url_gerir=GERIR,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    base.update(kw)
    return dunning.aviso_d7(**base)


def _falha(passo, **kw):
    from app.emails import dunning
    base = dict(
        nome="Ana",
        preco=PRECO,
        url_gerir=GERIR,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    base.update(kw)
    return dunning.falha_pagamento(passo=passo, **base)


def _cancelado(**kw):
    from app.emails import dunning
    base = dict(
        nome="Ana",
        url_gerir=GERIR,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    base.update(kw)
    return dunning.cancelado_final(**base)


TODOS = [
    ("renovacao_d30", _d30),
    ("aviso_d7", _d7),
    ("falha_d3", lambda **kw: _falha("D+3", **kw)),
    ("falha_d7", lambda **kw: _falha("D+7", **kw)),
    ("cancelado_final", _cancelado),
]


# ==========================================================================
#  Cada builder devolve um EmailRenderizado com HTML + texto gerados
# ==========================================================================
@pytest.mark.parametrize("nome,builder", TODOS)
def test_devolve_email_renderizado_html_e_texto(nome, builder):
    from app.emails import base as email_base

    email = builder()
    assert isinstance(email, email_base.EmailRenderizado)
    assert email.assunto.strip()
    assert email.html.strip()
    assert email.texto.strip()
    # HTML é HTML; texto é texto puro (sem tags do corpo)
    assert "style=" in email.html
    assert "<p" not in email.texto
    assert "<table" not in email.texto


# ==========================================================================
#  Assuntos corretos por passo (alinhados com AUTOMACAO §5 / app/dunning.py)
# ==========================================================================
def test_assunto_d30_renovacao_com_data():
    email = _d30()
    assert "renova" in email.assunto.lower()
    assert DATA in email.assunto


def test_assunto_d7_renovacao_iminente_com_data():
    email = _d7()
    assert "renova" in email.assunto.lower()
    assert DATA in email.assunto


def test_assunto_falha_d3_pede_atualizar_pagamento():
    email = _falha("D+3")
    a = email.assunto.lower()
    assert "não conseguimos renovar" in a
    assert "atualiza" in a and "pagamento" in a


def test_assunto_falha_d7_continua_sem_conseguir():
    email = _falha("D+7")
    assert "continuamos sem conseguir" in email.assunto.lower()


def test_assunto_cancelado_final_deixou_de_estar_monitorizado():
    email = _cancelado()
    a = email.assunto.lower()
    assert "deixou de estar monitorizado" in a


# ==========================================================================
#  D-30 — resumo de valor entregue + preço + data no corpo
# ==========================================================================
def test_d30_corpo_tem_resumo_valor_preco_e_data():
    email = _d30()
    for conteudo in (email.html, email.texto):
        assert RESUMO in conteudo
        assert "varrimento" in conteudo          # o resumo factual é renderizado
        assert PRECO in conteudo
        assert DATA in conteudo
        assert "Ana" in conteudo
        assert "CheckAL Anual" in conteudo


# ==========================================================================
#  Falha de pagamento — link Stripe/portal para ATUALIZAR o cartão (D+3 e D+7)
# ==========================================================================
@pytest.mark.parametrize("passo", ["D+3", "D+7"])
def test_falha_tem_link_atualizar_pagamento(passo):
    email = _falha(passo)
    for conteudo in (email.html, email.texto):
        assert GERIR in conteudo                 # o link do portal está presente
    # o HTML tem um botão de ação (link clicável) apontando ao portal
    assert f'href="{GERIR}"' in email.html


def test_falha_d7_avisa_suspensao():
    email = _falha("D+7")
    for conteudo in (email.html, email.texto):
        assert "suspens" in conteudo.lower()     # avisa que a monitorização será suspensa


def test_falha_passo_invalido_rebenta():
    from app.emails import dunning

    with pytest.raises(ValueError):
        dunning.falha_pagamento(passo="D+99", nome="Ana", preco=PRECO, url_gerir=GERIR)


# ==========================================================================
#  D+21 — cancelado: monitorização suspensa + porta de reativação (win-back)
# ==========================================================================
def test_cancelado_menciona_suspensao_e_reativacao():
    email = _cancelado()
    for conteudo in (email.html, email.texto):
        low = conteudo.lower()
        assert "suspens" in low                  # monitorização/selo suspensos
        assert GERIR in conteudo                 # porta de reativação (atualizar pagamento)
    assert "reativ" in email.html.lower()        # convite explícito a reativar


# ==========================================================================
#  Rodapé/opt-out/remetente SEMPRE presentes (html e texto) — em todos os passos
# ==========================================================================
@pytest.mark.parametrize("nome,builder", TODOS)
def test_optout_remetente_rodape_em_todos(nome, builder):
    email = builder()
    for conteudo in (email.html, email.texto):
        assert "CheckAL" in conteudo                     # remetente identificado
        assert "Cosmic Oasis, Lda." in conteudo          # entidade legal
        assert "[morada]" in conteudo                    # morada placeholder presente
        assert "checkal.pt/remover" in conteudo          # opt-out 1-clique
        # opt-out 1-clique carrega o destinatário + token (email codificado)
        assert "e=ana%40exemplo.pt" in conteudo
        assert "t=tok123" in conteudo


# ==========================================================================
#  Disclaimer de faturação ("não constitui aconselhamento jurídico") em todos
# ==========================================================================
@pytest.mark.parametrize("nome,builder", TODOS)
def test_disclaimer_faturacao_em_todos(nome, builder):
    email = builder()
    for conteudo in (email.html, email.texto):
        low = conteudo.lower()
        assert "não constitui aconselhamento jurídico" in low
        assert "subscrição" in conteudo                  # é comunicação de faturação da subscrição


# ==========================================================================
#  Marca por HTML/CSS — sem imagem externa, CSS inline (compat. cliente de email)
# ==========================================================================
@pytest.mark.parametrize("nome,builder", TODOS)
def test_marca_html_css_sem_imagem_externa(nome, builder):
    html = builder().html
    assert "CheckAL" in html
    assert "#12B76A" in html                 # ✓ verde-check da base
    assert "<img" not in html.lower()        # nada de imagem/CDN a ser bloqueado
    assert "<link" not in html.lower()       # sem folha de estilo externa
    assert "googleapis.com" not in html      # sem Google Fonts no email
    assert "style=" in html                  # estilos inline


# ==========================================================================
#  Anti-XSS — o corpo é autoescapado (o nome do titular não injeta HTML)
# ==========================================================================
def test_nome_e_autoescapado_no_html():
    email = _d30(nome="<b>injeta</b>")
    assert "<b>injeta</b>" not in email.html
    assert "&lt;b&gt;injeta&lt;/b&gt;" in email.html


# ==========================================================================
#  Dispatcher por passo (conveniência para o wire de app/dunning.py)
# ==========================================================================
def test_render_passo_dispatcher():
    from app.emails import dunning

    ctx = dict(
        nome="Ana",
        plano_nome="CheckAL Anual",
        data_renovacao=DATA,
        preco=PRECO,
        url_gerir=GERIR,
        resumo_valor=RESUMO,
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    assert DATA in dunning.render_passo(dunning.PASSO_D30, **ctx).assunto
    assert DATA in dunning.render_passo(dunning.PASSO_D7, **ctx).assunto
    assert "atualiza" in dunning.render_passo(dunning.PASSO_D3, **ctx).assunto.lower()
    assert "continuamos" in dunning.render_passo(dunning.PASSO_D7_POS, **ctx).assunto.lower()
    assert "monitorizado" in dunning.render_passo(dunning.PASSO_D21, **ctx).assunto.lower()


def test_render_passo_desconhecido_rebenta():
    from app.emails import dunning

    with pytest.raises(ValueError):
        dunning.render_passo("D+999", nome="Ana")


# ==========================================================================
#  Pureza — importar não toca a rede/BD
# ==========================================================================
def test_import_puro():
    import importlib

    mod = importlib.import_module("app.emails.dunning")
    assert hasattr(mod, "renovacao_d30")
    assert hasattr(mod, "falha_pagamento")
