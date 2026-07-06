"""Testes da sequência de COLD B2B do CheckAL (SPEC-FASE1-EMAILS §prospeccao) — ⚠️ PARECER-GATED.

Este módulo é **só o template** da prospeção a frio (o envio é do `app.campanhas.cold_email`,
FDS6, triplo-gated). Contrato inviolável (LEGAL-PARECER-DECISOES.md §5 + task):

  * remetente identificado = **getcheckal.com** (NUNCA `checkal.pt` — fronteira dura da AUP Resend);
  * cada peça leva SEMPRE: **nota RGPD** (Anexo 1 corrigido) + **opt-out 1-clique** (`checkal.pt/remover`)
    + o disclaimer de independência ("serviço privado … não é uma notificação oficial");
  * a nota RGPD **NÃO afirma** que o email é "público por imposição do art. 10.º" — a base de
    publicidade está por confirmar (parecer §2/§5); afirmá-la seria falso até validação documental;
  * o módulo **NUNCA importa `app.envio`** (Resend) — partilhar reputação com o canal transacional
    violaria a AUP e um lote de cold podia derrubar os alertas dos clientes pagantes.

LIVE-GATED: importar/renderizar é puro (compila templates; não toca rede nem BD). Escrito ANTES da
implementação (TDD).
"""
from __future__ import annotations

import ast
import inspect

import pytest


def _modulos_importados(modulo) -> set[str]:
    """Nomes de módulos realmente importados por `modulo` (via AST, não menções em docstrings)."""
    arvore = ast.parse(inspect.getsource(modulo))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
    return nomes


# Prospeto de exemplo — pessoa COLETIVA (o único destinatário legítimo do cold).
PROSPETO = {
    "nome": "Alojamentos Sol & Mar, Lda.",
    "nome_alojamento": "Casa da Graça",
    "nr_registo": "93415/AL",
    "concelho": "Lisboa",
    "email": "geral@solemar.pt",
}

# Substrings PROIBIDAS na nota RGPD (afirmação da base de publicidade — parecer §5).
AFIRMACOES_PROIBIDAS = (
    "art. 10",
    "art.º 10",
    "artigo 10",
    "por força do art",
    "imposição",
    "divulgação é obrigatória",
)


# ==========================================================================
#  Remetente — getcheckal.com (NUNCA checkal.pt)
# ==========================================================================
def test_remetente_e_getcheckal_nunca_checkal_pt():
    from app.emails import prospeccao

    assert "getcheckal.com" in prospeccao.REMETENTE
    # o cold jamais parte de checkal.pt (fronteira dura Resend/AUP)
    assert "@checkal.pt" not in prospeccao.REMETENTE


def test_cada_peca_declara_remetente_getcheckal():
    from app.emails import prospeccao

    for peca in prospeccao.render_sequencia(PROSPETO):
        assert "getcheckal.com" in peca.remetente
        assert peca.remetente == prospeccao.REMETENTE


# ==========================================================================
#  NUNCA importar app.envio (Resend) — fronteira dura de reputação
# ==========================================================================
def test_nao_importa_envio_resend():
    from app.emails import prospeccao

    importados = _modulos_importados(prospeccao)
    # NUNCA o canal transacional (Resend / app.envio) nem SMTP — este módulo não envia.
    assert not any(m == "app.envio" or m.startswith("app.envio.") for m in importados)
    assert not any("resend" in m.lower() for m in importados)
    assert "smtplib" not in importados


# ==========================================================================
#  Nota RGPD + opt-out presentes em CADA peça (html e texto)
# ==========================================================================
def test_cada_peca_tem_nota_rgpd_e_optout():
    from app.emails import prospeccao

    pecas = prospeccao.render_sequencia(PROSPETO)
    assert len(pecas) == 3
    for peca in pecas:
        for conteudo in (peca.email.html, peca.email.texto):
            # nota RGPD (Anexo 1 corrigido)
            assert "Proteção de dados" in conteudo
            assert "RNAL" in conteudo
            assert "interesse legítimo" in conteudo
            assert "CNPD" in conteudo
            # opt-out 1-clique
            assert "checkal.pt/remover" in conteudo


# ==========================================================================
#  A nota RGPD NÃO afirma a base de publicidade proibida (parecer §5)
# ==========================================================================
def test_nota_rgpd_sem_afirmacao_proibida():
    from app.emails import prospeccao

    # a constante isolada
    for proibida in AFIRMACOES_PROIBIDAS:
        assert proibida.lower() not in prospeccao.NOTA_RGPD.lower()

    # e o email renderizado inteiro (html + texto), em toda a sequência
    for peca in prospeccao.render_sequencia(PROSPETO):
        for conteudo in (peca.email.html, peca.email.texto):
            for proibida in AFIRMACOES_PROIBIDAS:
                assert proibida.lower() not in conteudo.lower(), (
                    f"afirmação proibida {proibida!r} no email {peca.passo}"
                )


# ==========================================================================
#  Disclaimer de independência no topo de cada peça
# ==========================================================================
def test_disclaimer_independencia_em_cada_peca():
    from app.emails import prospeccao

    for peca in prospeccao.render_sequencia(PROSPETO):
        for conteudo in (peca.email.html, peca.email.texto):
            assert "serviço privado" in conteudo.lower()
            assert "não é uma notificação oficial" in conteudo.lower()
            assert "turismo de portugal" in conteudo.lower()


# ==========================================================================
#  Marca + garantia da base (remetente identificado, rodapé legal)
# ==========================================================================
def test_marca_e_rodape_legal_em_cada_peca():
    from app.emails import prospeccao

    for peca in prospeccao.render_sequencia(PROSPETO):
        for conteudo in (peca.email.html, peca.email.texto):
            assert "CheckAL" in conteudo
            assert "Cosmic Oasis, Lda." in conteudo
        # html é html; texto não traz as tags de corpo
        assert "<p" in peca.email.html
        assert "<p" not in peca.email.texto


# ==========================================================================
#  Assuntos da sequência (copy de COPY-VENDAS.md §2)
# ==========================================================================
def test_assuntos_da_sequencia():
    from app.emails import prospeccao

    pecas = {p.passo: p for p in prospeccao.render_sequencia(PROSPETO)}
    assert set(pecas) == {"d0", "d4", "d10"}

    # D+0 — merge do alojamento + registo
    a0 = pecas["d0"].email.assunto
    assert "Casa da Graça" in a0
    assert "93415/AL" in a0
    assert "quem vigia os prazos?" in a0

    # D+4 — "Re:" + prova social
    a4 = pecas["d4"].email.assunto
    assert a4.startswith("Re:")
    assert "o que os outros titulares já viram" in a4

    # D+10 — caso real (fixo, sem merge)
    assert pecas["d10"].email.assunto == (
        "6.765 registos cancelados em Lisboa — a mecânica é sempre a mesma"
    )


# ==========================================================================
#  Ordem e cadência (D+0 → D+4 → D+10)
# ==========================================================================
def test_sequencia_ordem_e_dias():
    from app.emails import prospeccao

    pecas = prospeccao.render_sequencia(PROSPETO)
    assert [p.passo for p in pecas] == ["d0", "d4", "d10"]
    assert [p.dia for p in pecas] == [0, 4, 10]


# ==========================================================================
#  Destinatário do prospeto → opt-out 1-clique personalizado
# ==========================================================================
def test_optout_personalizado_com_email_do_prospeto():
    from app.emails import prospeccao

    peca = prospeccao.render_passo("d0", PROSPETO)
    assert peca.para == "geral@solemar.pt"
    for conteudo in (peca.email.html, peca.email.texto):
        assert "e=geral%40solemar.pt" in conteudo


# ==========================================================================
#  Sem inventar dados + à prova de XSS (dados vêm do RNAL, não confiáveis)
# ==========================================================================
def test_merge_sem_inventar_e_sem_placeholders():
    from app.emails import prospeccao

    # prospeto mínimo: só o registo (sem alojamento, sem concelho, sem empresa)
    magro = {"nr_registo": "55555/AL"}
    peca = prospeccao.render_passo("d0", magro)
    for conteudo in (peca.email.html, peca.email.texto):
        assert "55555/AL" in conteudo
        # nenhum placeholder de merge por resolver
        assert "{{" not in conteudo
        assert "}}" not in conteudo
        assert "None" not in conteudo


def test_html_escapa_merge_para_xss():
    from app.emails import prospeccao

    veneno = {
        "nome": "<script>alert(1)</script>",
        "nome_alojamento": "<img src=x onerror=alert(1)>",
        "nr_registo": "1/AL",
        "email": "x@y.pt",
    }
    peca = prospeccao.render_passo("d0", veneno)
    # a tag crua nunca chega ao html (autoescape / escape manual do merge):
    # o `<` vira `&lt;`, logo o parser do cliente de email não a interpreta.
    assert "<script>" not in peca.email.html
    assert "<img" not in peca.email.html
    # a versão escapada tem de estar presente (prova de que foi escapada, não removida)
    assert "&lt;script&gt;" in peca.email.html


# ==========================================================================
#  Pureza — importar não toca rede nem BD
# ==========================================================================
def test_import_puro():
    import importlib

    mod = importlib.import_module("app.emails.prospeccao")
    assert hasattr(mod, "render_sequencia")
    assert hasattr(mod, "render_passo")
    assert hasattr(mod, "REMETENTE")
    assert hasattr(mod, "NOTA_RGPD")
