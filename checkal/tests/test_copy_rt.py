"""Correções de copy do RED-TEAM (Fase C, §4 do prompt-mestre) — obrigatórias.

  RT-copy fria (`emails/prospeccao.py`):
    - sem "exploração irregular" nem "cancelamento tácito" (caracterizações
      jurídicas do destinatário) e sem "incumprimento";
    - identificador do destinatário NUNCA na mesma frase (nem adjacente) ao
      valor da coima;
    - coimas saem de `config.COIMA` (fonte única — nunca valores cravados);
    - as 3 peças da cadência PASSAM o linter em canal COLD.

  RT-relatório mensal (`emails/transacional.py`):
    - `relatorio_mensal` ganha a divulgação de IA (AI Act art. 50) quando o
      texto é redigido/apoiado por agente; sem a flag, o render mantém-se igual;
    - com divulgação, a peça passa o linter em canal RELATORIO com
      `gerado_por_ia=True` (o linter reprova a ausência — fail-closed).

Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import re

import pytest

import app.config as config
from app.compliance.linter import Canal, DIVULGACAO_IA, PecaOutward, lint
from app.emails import prospeccao, transacional


class _Prospeto:
    nr_registo = "100031"
    nome = "Alojamentos Sul, Lda."
    concelho = "Faro"
    email = "geral@sul.pt"
    nome_alojamento = "Casa do Sol"


_PROIBIDAS = ("exploração irregular", "exploracao irregular", "cancelamento tácito",
              "cancelamento tacito", "incumprimento")


# ==========================================================================
#  RT-copy fria
# ==========================================================================
@pytest.mark.parametrize("passo", prospeccao.SEQUENCIA)
def test_prospeccao_sem_caracterizacoes_juridicas(passo):
    peca = prospeccao.render_passo(passo, _Prospeto())
    for proibida in _PROIBIDAS:
        assert proibida not in peca.email.html.lower(), (passo, proibida)
        assert proibida not in peca.email.texto.lower(), (passo, proibida)


@pytest.mark.parametrize("passo", prospeccao.SEQUENCIA)
def test_prospeccao_passa_o_linter_cold(passo):
    peca = prospeccao.render_passo(passo, _Prospeto())
    r = lint(
        PecaOutward(
            texto=peca.email.html, canal=Canal.COLD, tem_optout_carimbado=True,
        )
    )
    assert r.aprovado is True, [f"{v.regra}: {v.razao} [{v.trecho}]" for v in r.violacoes]


def test_prospeccao_coima_vem_de_config(monkeypatch):
    # Fonte única: mudar config.COIMA muda a copy (nada cravado no template).
    monkeypatch.setattr(config, "COIMA", {"singular": (1111, 2222), "coletiva": (33333, 44444)})
    peca = prospeccao.render_passo("d0", _Prospeto())
    assert "33.333" in peca.email.html
    assert "44.444" in peca.email.html
    assert "25.000" not in peca.email.html


def test_prospeccao_nota_rgpd_tem_disclaimer_de_nao_aconselhamento():
    assert re.search(r"n[ãa]o\s+constitu\w*\s+aconselhamento", prospeccao.NOTA_RGPD.lower())


def test_prospeccao_assuntos_intactos():
    # O agente não pode alterar assunto/CTA — os assuntos canónicos mantêm-se.
    p = prospeccao.render_passo("d0", _Prospeto())
    assert "quem vigia os prazos?" in p.email.assunto
    p10 = prospeccao.render_passo("d10", _Prospeto())
    assert "6.765" in p10.email.assunto


# ==========================================================================
#  RT-relatório mensal — divulgação de IA
# ==========================================================================
def _relatorio(**kw):
    return transacional.relatorio_mensal(
        mes="Julho", nome_al="Casa do Sol", resumo="Tudo em ordem.",
        n_analisadas=4, n_relevantes=0, email_destinatario="dono@ex.pt", **kw
    )


def test_relatorio_mensal_sem_flag_mantem_se_igual():
    email = _relatorio()
    assert DIVULGACAO_IA not in email.html
    assert DIVULGACAO_IA not in email.texto


def test_relatorio_mensal_com_divulgacao_ia_embutida():
    email = _relatorio(divulgacao_ia=DIVULGACAO_IA)
    assert DIVULGACAO_IA in email.html
    assert DIVULGACAO_IA in email.texto


def test_relatorio_mensal_com_ia_passa_o_linter():
    email = _relatorio(divulgacao_ia=DIVULGACAO_IA)
    r = lint(PecaOutward(texto=email.html, canal=Canal.RELATORIO, gerado_por_ia=True))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_relatorio_mensal_sem_divulgacao_e_reprovado_pelo_linter():
    email = _relatorio()
    r = lint(PecaOutward(texto=email.html, canal=Canal.RELATORIO, gerado_por_ia=True))
    assert r.aprovado is False
    assert any(v.regra.startswith("R5") for v in r.violacoes)
