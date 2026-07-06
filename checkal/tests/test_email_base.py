"""Testes da BASE de email do CheckAL (SPEC-FASE1-EMAILS §base) — a fundação de que
todos os templates de email (transacional, dunning, prospeção) dependem.

Contrato garantido (inviolável):
  * `render_email(nome, **ctx) -> EmailRenderizado{assunto, html, texto}` gera SEMPRE
    as duas versões (HTML com CSS inline + texto simples);
  * cada email leva SEMPRE — em HTML **e** em texto — o remetente identificado
    (wordmark "CheckAL"), o rodapé legal (Cosmic Oasis, Lda. · morada) e o
    **opt-out 1-clique** (`checkal.pt/remover?e=&t=`);
  * o header é marca por HTML/CSS (wordmark + ✓ verde `#12B76A`), SEM imagem externa;
  * os estados 🟢🟡🔴 existem como blocos reutilizáveis (emoji + cor canónica).

LIVE-GATED: importar/rodar NÃO toca a rede nem a BD (o módulo é puro). Escrito ANTES
da implementação (TDD).
"""
from __future__ import annotations

import pytest


# ==========================================================================
#  render_email — gera html + texto e devolve o assunto
# ==========================================================================
def test_render_email_gera_html_e_texto():
    from app.emails import base

    email = base.render_email(
        "email_base",
        assunto="O teu AL passou no check",
        corpo_html="<p>Olá titular, tudo em ordem.</p>",
        corpo_texto="Olá titular, tudo em ordem.",
    )
    # devolve a estrutura do contrato
    assert isinstance(email, base.EmailRenderizado)
    assert email.assunto == "O teu AL passou no check"
    # as duas versões geradas e não-vazias
    assert email.html.strip()
    assert email.texto.strip()
    # o corpo injetado aparece em ambas
    assert "tudo em ordem" in email.html
    assert "tudo em ordem" in email.texto
    # HTML é HTML; texto NÃO tem tags do corpo
    assert "<p>" in email.html
    assert "<p>" not in email.texto


# ==========================================================================
#  Rodapé + opt-out + remetente SEMPRE presentes (html e texto)
# ==========================================================================
def test_rodape_optout_remetente_sempre_presentes():
    from app.emails import base

    email = base.render_email("email_base", corpo_html="<p>x</p>", corpo_texto="x")
    for conteudo in (email.html, email.texto):
        # remetente identificado (a marca)
        assert "CheckAL" in conteudo
        # rodapé legal — entidade + veículo
        assert "Cosmic Oasis, Lda." in conteudo
        # morada (placeholder por preencher, mas presente)
        assert "[morada]" in conteudo
        # opt-out 1-clique
        assert "checkal.pt/remover" in conteudo
        # link de privacidade
        assert "checkal.pt/privacidade" in conteudo
        # qualificador de independência (serviço privado, nunca aspeto de Estado)
        assert "representamos" in conteudo.lower()
        assert "turismo de portugal" in conteudo.lower()


def test_render_email_recusa_email_sem_rodape():
    """A GARANTIA é dura: se um template perdesse o rodapé/opt-out, render_email rebenta."""
    from app.emails import base

    # um template que não estende a base (sem rodapé/opt-out) tem de ser rejeitado
    tmpl = base.env.from_string("<p>corpo solto sem rodape</p>")
    with pytest.raises(base.EmailInvalido):
        base._finalizar(tmpl, {}, texto_forcado="corpo solto")


# ==========================================================================
#  Header wordmark por HTML/CSS (✓ verde), SEM imagem externa
# ==========================================================================
def test_header_wordmark_verde_check_sem_imagem_externa():
    from app.emails import base

    email = base.render_email("email_base", corpo_html="<p>x</p>", corpo_texto="x")
    html = email.html
    # wordmark textual + o ✓ + a cor verde-check canónica
    assert "CheckAL" in html
    assert "✓" in html  # ✓
    assert "#12B76A" in html
    # marca por HTML/CSS: nenhuma imagem externa (nem <img>, nem url http(s) de asset)
    assert "<img" not in html.lower()
    assert "http://" not in html
    # o único domínio referenciado é checkal.pt (links legais), nunca um CDN de imagem
    assert "googleapis.com" not in html


# ==========================================================================
#  CSS inline (compatibilidade com clientes de email)
# ==========================================================================
def test_css_inline_sem_folha_externa():
    from app.emails import base

    html = base.render_email("email_base", corpo_html="<p>x</p>", corpo_texto="x").html
    # estilos aplicados inline nos elementos, não por <link>/<style> externo
    assert "style=" in html
    assert "<link" not in html.lower()


# ==========================================================================
#  Opt-out 1-clique — URL bem formada, com email e token
# ==========================================================================
def test_url_optout_default_e_com_parametros():
    from app.emails import base

    # forma canónica vazia (checkal.pt/remover?e=&t=)
    assert base.url_optout() == "https://checkal.pt/remover?e=&t="
    # com destinatário + token, URL-encoded
    u = base.url_optout("ana@exemplo.pt", "tok123")
    assert "e=ana%40exemplo.pt" in u
    assert "t=tok123" in u


def test_render_email_propaga_optout_do_destinatario():
    from app.emails import base

    email = base.render_email(
        "email_base",
        corpo_html="<p>x</p>",
        corpo_texto="x",
        email_destinatario="ana@exemplo.pt",
        token_optout="tok123",
    )
    for conteudo in (email.html, email.texto):
        assert "e=ana%40exemplo.pt" in conteudo
        assert "t=tok123" in conteudo


# ==========================================================================
#  Estados 🟢🟡🔴 — blocos reutilizáveis (emoji + cor canónica)
# ==========================================================================
def test_estados_canonicos():
    from app.emails import base

    assert set(base.ESTADOS) == {"verde", "amarelo", "vermelho"}
    assert base.ESTADOS["verde"]["emoji"] == "\U0001F7E2"      # 🟢
    assert base.ESTADOS["amarelo"]["emoji"] == "\U0001F7E1"    # 🟡
    assert base.ESTADOS["vermelho"]["emoji"] == "\U0001F534"   # 🔴
    # cores canónicas do SPEC (verde-check / âmbar / coral)
    assert base.ESTADOS["verde"]["cor"] == "#12B76A"
    assert base.ESTADOS["amarelo"]["cor"] == "#F59E0B"
    assert base.ESTADOS["vermelho"]["cor"] == "#DC2626"


def test_bloco_estado_html_e_texto():
    from app.emails import base

    html = base.bloco_estado_html("vermelho", "Registo RNAL", "cancelado em 2026")
    assert "\U0001F534" in html                # 🔴
    assert "#DC2626" in html                   # coral
    assert "Registo RNAL" in html
    assert "cancelado em 2026" in html
    assert "style=" in html                    # inline

    txt = base.bloco_estado_texto("verde", "Seguro", "válido")
    assert "\U0001F7E2" in txt                 # 🟢
    assert "Seguro" in txt
    assert "válido" in txt
    assert "<" not in txt                       # texto puro


def test_macro_estado_disponivel_para_templates():
    from app.emails import base

    render = base.env.from_string(
        "{% import 'blocos.html' as blocos %}{{ blocos.estado('amarelo', 'Seguro', 'a confirmar') }}"
    ).render()
    assert "\U0001F7E1" in render              # 🟡
    assert "#F59E0B" in render                 # âmbar
    assert "Seguro" in render


# ==========================================================================
#  Assunto: do ctx (prioritário) OU do bloco {% block assunto %} do template
# ==========================================================================
def test_assunto_do_ctx_tem_prioridade():
    from app.emails import base

    email = base.render_email("email_base", assunto="Assunto Explícito", corpo_html="x", corpo_texto="x")
    assert email.assunto == "Assunto Explícito"


def test_assunto_extraido_do_bloco_do_template():
    from app.emails import base

    # um template concreto fixa o assunto no seu próprio bloco (copy dona do template)
    filho = base.env.from_string(
        "{% extends 'email_base.html' %}"
        "{% block assunto %}✅ O teu AL passou no check{% endblock %}"
        "{% block corpo %}<p>corpo</p>{% endblock %}"
    )
    assert base._extrair_assunto(filho, {}) == "✅ O teu AL passou no check"


def test_assunto_e_header_safe_sem_crlf():
    """O assunto pode derivar de dados não confiáveis (RNAL) — nunca sai com CR/LF.

    Um ``\\r``/``\\n`` embutido no assunto permitiria injeção de cabeçalho (Bcc:, etc.)
    no envio. A base tem de o sanear a partir de QUALQUER fonte (ctx e bloco).
    """
    from app.emails import base

    email = base.render_email(
        "email_base",
        assunto="Casa\r\nBcc: v@evil.com\r\nSubject: hijack",
        corpo_html="x",
        corpo_texto="x",
    )
    assert "\r" not in email.assunto and "\n" not in email.assunto
    assert "Bcc:" in email.assunto  # o texto fica, só o CRLF é colapsado
    assert base._sanitizar_assunto("A\r\nB\tC") == "A B C"


# ==========================================================================
#  Pureza — importar não toca a rede/BD
# ==========================================================================
def test_import_puro_sem_rede():
    import importlib

    # importar (ou reimportar) o módulo não deve exigir rede/BD nem estourar
    mod = importlib.import_module("app.emails.base")
    assert hasattr(mod, "render_email")
    assert hasattr(mod, "EmailRenderizado")
