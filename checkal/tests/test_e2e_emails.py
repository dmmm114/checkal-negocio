"""E2E da superfície de email do CheckAL depois do WIRE (SPEC-FASE1-EMAILS §wire).

Cada TIPO de email — depois de ligado aos pontos de envio — renderiza com **marca** e
**opt-out 1-clique**; os **alertas** levam o disclaimer "informação, não aconselhamento
jurídico" (parecer RGPD §7). Cobre toda a superfície:

  * transacionais (Canal A, Resend): `boas_vindas`, `alerta_estado` (🟢/🟡/🔴),
    `relatorio_mensal`, `confirmacao_consentimento`;
  * dunning (Canal A): D-30, D-7, D+3, D+7, D+21;
  * prospeção (Canal B, `getcheckal.com`): sequência D+0 / D+4 / D+10.

Invariante da base (inviolável, em HTML **e** texto): remetente identificado ("CheckAL"),
rodapé legal (Cosmic Oasis, Lda.) e opt-out 1-clique (`checkal.pt/remover`). Marca por
HTML/CSS (verde-check `#12B76A`), **sem imagem externa** (nada de `<img>`/CDN bloqueado).

Também trava o contrato do WIRE: `alerta_estado` aceita um `assunto` factual do módulo de
origem (alertas de estado do registo / pipeline regulatório) sem perder a validação do
estado nem o disclaimer.

LIVE-GATED: renderizar é puro (compila templates; não toca a rede nem a BD).
"""
from __future__ import annotations

import pytest

from app.emails import base, dunning, prospeccao, transacional

# --------------------------------------------------------------------------
#  Amostras de cada tipo (builders são puros → compõem-se na recolha)
# --------------------------------------------------------------------------
NOME_AL = "Casa da Graça"
URL_SELO = "https://checkal.pt/selo/93415"
FONTE = "https://files.diariodarepublica.pt/gratuitos/2s/2026/06/2S118A0000S00.pdf"

PROSPETO = {
    "nome": "Alojamentos Sol & Mar, Lda.",
    "nome_alojamento": NOME_AL,
    "nr_registo": "93415/AL",
    "concelho": "Lisboa",
    "email": "geral@solemar.pt",
}

# Alertas — o subconjunto que TEM de levar o disclaimer de "não aconselhamento".
_ALERTAS = [
    (
        "alerta_vermelho",
        transacional.alerta_estado(
            nome_al=NOME_AL, estado="vermelho", facto="novo regulamento em Lisboa",
            titulo="Regulamento municipal", corpo="A tua freguesia entra em contenção.",
            cta_texto="Ver o meu AL", cta_url="https://checkal.pt/conta",
            email_destinatario="ana@exemplo.pt", token_optout="tok",
        ),
    ),
    (
        "alerta_amarelo_wire",  # caminho do WIRE: assunto factual do módulo de origem
        transacional.alerta_estado(
            nome_al=NOME_AL, estado="amarelo",
            assunto="CheckAL: novo documento regulatório que pode afetar o teu AL em Braga",
            titulo="Novo documento regulatório", corpo="Consulta o documento: " + FONTE,
            cta_texto="Ler o documento oficial", cta_url=FONTE,
            email_destinatario="ana@exemplo.pt",
        ),
    ),
    (
        "alerta_verde",
        transacional.alerta_estado(
            nome_al=NOME_AL, estado="verde",
            titulo="Registo no RNAL", corpo="O teu registo continua ativo.",
        ),
    ),
]

_NAO_ALERTAS = [
    (
        "boas_vindas",
        transacional.boas_vindas(
            nome_al=NOME_AL, nr_registo="93415/AL", url_selo=URL_SELO, nome="Ana",
            url_fatura="https://cosmicoasis.app.invoicexpress.com/i/998877",
            selos_extra=["https://checkal.pt/selo/93416"], requer_atencao=True,
            email_destinatario="ana@exemplo.pt", token_optout="tok",
        ),
    ),
    (
        "relatorio_mensal",
        transacional.relatorio_mensal(
            mes="Junho", nome_al=NOME_AL,
            resumo="Analisámos 16 publicações do teu concelho; nenhuma te afetou.",
            email_destinatario="ana@exemplo.pt", token_optout="tok",
        ),
    ),
    (
        "confirmacao_consentimento",
        transacional.confirmacao_consentimento(
            token="tok-xyz", consente_alertas=True, consente_ofertas=False,
            email_destinatario="ana@exemplo.pt", token_optout="tok",
        ),
    ),
]


def _dunning_todos():
    ctx = dict(
        nome="Ana", plano_nome="CheckAL Anual", data_renovacao="05/07/2027", preco="49 €",
        url_gerir="https://checkal.pt/conta/subscricao",
        resumo_valor="No último ciclo fizemos 2 varrimento(s) nacionais do RNAL.",
        email_destinatario="ana@exemplo.pt", token_optout="tok",
    )
    passos = (
        dunning.PASSO_D30, dunning.PASSO_D7, dunning.PASSO_D3,
        dunning.PASSO_D7_POS, dunning.PASSO_D21,
    )
    return [(f"dunning_{p}", dunning.render_passo(p, **ctx)) for p in passos]


def _prospeccao_todos():
    return [(f"prospeccao_{p.passo}", p.email) for p in prospeccao.render_sequencia(PROSPETO)]


# Todos os EmailRenderizado da superfície (transacionais + dunning + prospeção).
_TODOS = _ALERTAS + _NAO_ALERTAS + _dunning_todos() + _prospeccao_todos()


# ==========================================================================
#  Cada tipo renderiza com MARCA + OPT-OUT (em HTML e texto)
# ==========================================================================
@pytest.mark.parametrize("nome,email", _TODOS, ids=[n for n, _ in _TODOS])
def test_cada_tipo_tem_marca_e_optout(nome, email):
    assert isinstance(email, base.EmailRenderizado)
    assert email.assunto.strip()
    assert email.html.strip()
    assert email.texto.strip()
    for conteudo in (email.html, email.texto):
        assert "CheckAL" in conteudo                 # remetente identificado
        assert "Cosmic Oasis, Lda." in conteudo      # rodapé legal
        assert "checkal.pt/remover" in conteudo      # opt-out 1-clique
    # marca por HTML/CSS (verde-check), sem imagem externa nem folha de estilo remota
    assert "#12B76A" in email.html
    assert "<img" not in email.html.lower()
    assert "<link" not in email.html.lower()
    # html é html; texto é texto puro (sem as tags de corpo)
    assert "style=" in email.html
    assert "<p" not in email.texto
    assert "<table" not in email.texto


# ==========================================================================
#  Os ALERTAS levam SEMPRE o disclaimer "informação, não aconselhamento"
# ==========================================================================
@pytest.mark.parametrize("nome,email", _ALERTAS, ids=[n for n, _ in _ALERTAS])
def test_alertas_tem_disclaimer(nome, email):
    for conteudo in (email.html, email.texto):
        assert "aconselhamento" in conteudo.lower()


# ==========================================================================
#  Contrato do WIRE — `alerta_estado` aceita o assunto factual do módulo de origem
# ==========================================================================
def test_alerta_estado_aceita_assunto_do_wire():
    # o WIRE (alertas_estado / pipeline) passa um assunto próprio, factual (não o
    # canónico "falhou o check"), preservando estado + disclaimer + opt-out.
    email = transacional.alerta_estado(
        nome_al="Casa do Sol", estado="amarelo",
        assunto="O registo RNAL do teu AL (nº 100031) foi atualizado",
        titulo="Registo RNAL atualizado", corpo="Mudou a modalidade.",
        email_destinatario="dono@exemplo.pt",
    )
    assert email.assunto == "O registo RNAL do teu AL (nº 100031) foi atualizado"
    for conteudo in (email.html, email.texto):
        assert "aconselhamento" in conteudo.lower()
        assert "checkal.pt/remover" in conteudo


def test_alerta_estado_estado_invalido_rebenta():
    with pytest.raises(ValueError):
        transacional.alerta_estado(
            nome_al="X", estado="laranja", assunto="seja qual for", titulo="t", corpo="c"
        )


# ==========================================================================
#  A prospeção (Canal B) parte SEMPRE de getcheckal.com (nunca checkal.pt)
# ==========================================================================
def test_prospeccao_remetente_getcheckal():
    for peca in prospeccao.render_sequencia(PROSPETO):
        assert "getcheckal.com" in peca.remetente
        assert "@checkal.pt" not in peca.remetente
