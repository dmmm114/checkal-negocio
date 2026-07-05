"""Testes do seam da camada IA (FDS 4) — obter_cliente_ia() LIVE-GATED.

Contrato (SPEC-FDS4 §BASE + SPEC-IA §0):

    obter_cliente_ia() -> cliente Anthropic | None   (LIVE-GATED, à imagem de
    faturacao.obter_emissor / envio.obter_enviador)

O cliente Anthropic é o **único** recurso de rede/IA da camada; compõe-se SÓ em
produção. Sob `config.CHECKAL_MODO_TESTE` **ou** sem `config.ANTHROPIC_API_KEY`,
`obter_cliente_ia()` devolve ``None`` — pelo que os testes de triagem/alerta
injetam sempre um `cliente_ia` falso e nunca tocam a Anthropic.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** IA/rede real. Escrito
ANTES da implementação (TDD). Construir o cliente (constructor do SDK) NÃO faz
chamadas de rede — só a composição é exercitada, nunca uma request.
"""
from __future__ import annotations

import app.config as config
from app import ia


# ==========================================================================
#  LIVE-GATE — obter_cliente_ia() à imagem de faturacao.obter_emissor
# ==========================================================================
def test_live_gate_modo_teste_devolve_none(monkeypatch):
    # Mesmo com chave presente, o modo de teste corta a IA/rede: None.
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert ia.obter_cliente_ia() is None


def test_live_gate_sem_api_key_devolve_none(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    assert ia.obter_cliente_ia() is None


def test_live_gate_com_credenciais_devolve_cliente(monkeypatch):
    # Produção (modo de teste OFF + chave): compõe o cliente Anthropic real. NÃO
    # se faz nenhuma request — o constructor do SDK não toca a rede; confirma-se só
    # que o gate deixa passar um cliente com a superfície esperada (`.messages`).
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-123")
    cliente = ia.obter_cliente_ia()
    assert cliente is not None
    assert hasattr(cliente, "messages")


# ==========================================================================
#  Fronteira pública estável do pacote
# ==========================================================================
def test_pacote_expoe_obter_cliente_ia():
    assert callable(ia.obter_cliente_ia)
    assert "obter_cliente_ia" in ia.__all__
