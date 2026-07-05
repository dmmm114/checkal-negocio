"""Testes da triagem IA (FDS 4, Passo 1) — Haiku + structured output → `Triagem`.

Contrato (SPEC-FDS4 §triagem + SPEC-IA §3):

    triar(evento_regulatorio, *, cliente_ia) -> Triagem
        → Haiku (`config.MODEL_TRIAGEM`), input = título + ~3.000 primeiras palavras do
          documento, **structured output** JSON estrito
          `{relevante_para_al: sim|nao|duvida, concelhos: [...],
            tipo: regulamento|contencao|limpeza|outro, resumo_1_frase}`.
    e_relevante(triagem) -> bool
        → **regra conservadora**: `duvida` conta como `sim` (nunca se cala por dúvida);
          só `nao` é não-relevante.

O `cliente_ia` (SDK Anthropic) é sempre **injetado**; a submissão/polling do Batch API
fica atrás de :mod:`app.ia.cliente`. Nos testes o cliente é **falso** e nunca se toca a
rede (MODO DE TESTE, LIVE-GATED). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.config as config
from app.ia import triagem


# ==========================================================================
#  Duplos de teste — cliente Anthropic falso + evento regulatório
# ==========================================================================
class _Bloco:
    """Bloco de conteúdo à laia do SDK (`.type` + `.text`)."""

    def __init__(self, tipo: str, texto: str = "") -> None:
        self.type = tipo
        self.text = texto


class _Mensagem:
    """Resposta à laia de `anthropic.types.Message` (só o que o wrapper lê)."""

    def __init__(self, blocos: list[_Bloco], stop_reason: str = "end_turn") -> None:
        self.content = blocos
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, resposta: _Mensagem) -> None:
        self._resposta = resposta
        self.chamadas: list[dict] = []  # kwargs de cada `.create(...)`

    def create(self, **kwargs) -> _Mensagem:
        self.chamadas.append(kwargs)
        return self._resposta


class ClienteFalso:
    """`.messages.create(**kwargs)` devolve uma resposta scriptada e regista os kwargs."""

    def __init__(self, resposta: _Mensagem) -> None:
        self.messages = _Messages(resposta)


def _cliente_json(texto: str) -> ClienteFalso:
    """Cliente falso cuja resposta é um único bloco de texto (o JSON da triagem)."""
    return ClienteFalso(_Mensagem([_Bloco("text", texto)]))


def _evento(*, titulo: str = "Regulamento de AL", texto: str = "corpo do documento"):
    """Evento regulatório mínimo (duck-typed: `.titulo` + `.texto`)."""
    return SimpleNamespace(titulo=titulo, texto=texto, url="https://dre.pt/x", concelhos=[])


_JSON_SIM = (
    '{"relevante_para_al": "sim", "concelhos": ["Loulé", "Faro"], '
    '"tipo": "regulamento", "resumo_1_frase": "Novo regulamento de AL em Loulé."}'
)


# ==========================================================================
#  triar — parse do structured output em `Triagem`
# ==========================================================================
def test_triar_parse_devolve_triagem():
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(_JSON_SIM))
    assert isinstance(t, triagem.Triagem)
    assert t.relevante_para_al == "sim"
    assert t.tipo == "regulamento"
    assert t.resumo_1_frase == "Novo regulamento de AL em Loulé."


def test_triar_extrai_concelhos():
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(_JSON_SIM))
    assert t.concelhos == ["Loulé", "Faro"]


def test_triar_concelhos_vazios_quando_ausentes_ou_nao_lista():
    # defensivo: `concelhos` em falta ou de tipo errado → lista vazia (nunca rebenta).
    j = ('{"relevante_para_al": "nao", "tipo": "outro", '
         '"resumo_1_frase": "Nada de AL.", "concelhos": null}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert t.concelhos == []


def test_triar_concelhos_filtra_nao_strings():
    j = ('{"relevante_para_al": "sim", "concelhos": ["Porto", 123, null, "Braga"], '
         '"tipo": "contencao", "resumo_1_frase": "x"}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert t.concelhos == ["Porto", "Braga"]


# ==========================================================================
#  e_relevante — regra conservadora (duvida conta como sim)
# ==========================================================================
def test_e_relevante_sim():
    t = triagem.Triagem("sim", ["Loulé"], "regulamento", "x")
    assert triagem.e_relevante(t) is True


def test_e_relevante_duvida_e_relevante():
    # 🧯 regra conservadora: na dúvida NÃO se cala — 'duvida' é tratado como 'sim'.
    t = triagem.Triagem("duvida", [], "outro", "x")
    assert triagem.e_relevante(t) is True


def test_e_relevante_nao_nao_e_relevante():
    t = triagem.Triagem("nao", [], "outro", "x")
    assert triagem.e_relevante(t) is False


def test_triar_nao_via_pipeline():
    j = ('{"relevante_para_al": "nao", "concelhos": [], '
         '"tipo": "outro", "resumo_1_frase": "Nada de AL."}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert t.relevante_para_al == "nao"
    assert triagem.e_relevante(t) is False


def test_triar_duvida_via_pipeline_e_relevante():
    j = ('{"relevante_para_al": "duvida", "concelhos": ["Lisboa"], '
         '"tipo": "regulamento", "resumo_1_frase": "Pode afetar AL."}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert triagem.e_relevante(t) is True


def test_triar_relevancia_desconhecida_e_conservador():
    # valor fora do enum (defesa contra drift): trata-se como 'duvida' → relevante,
    # nunca como 'nao' (não se descarta um evento por um valor inesperado).
    j = ('{"relevante_para_al": "talvez", "concelhos": [], '
         '"tipo": "outro", "resumo_1_frase": "?"}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert t.relevante_para_al == "duvida"
    assert triagem.e_relevante(t) is True


def test_triar_tipo_desconhecido_vira_outro():
    j = ('{"relevante_para_al": "sim", "concelhos": [], '
         '"tipo": "fiscal", "resumo_1_frase": "x"}')
    t = triagem.triar(_evento(), cliente_ia=_cliente_json(j))
    assert t.tipo == "outro"


# ==========================================================================
#  Forma do pedido — modelo, structured output, sem thinking/amostragem
# ==========================================================================
def test_triar_passa_modelo_triagem():
    cliente = _cliente_json(_JSON_SIM)
    triagem.triar(_evento(), cliente_ia=cliente)
    assert cliente.messages.chamadas[0]["model"] == config.MODEL_TRIAGEM


def test_triar_usa_structured_output_com_esquema():
    cliente = _cliente_json(_JSON_SIM)
    triagem.triar(_evento(), cliente_ia=cliente)
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": triagem.ESQUEMA_TRIAGEM}
    }


def test_triar_nao_envia_thinking_nem_amostragem():
    # Haiku: thinking off por omissão; nunca temperature/top_p/top_k (400 no Sonnet 5 e
    # desnecessário aqui). A triagem é structured output puro.
    cliente = _cliente_json(_JSON_SIM)
    triagem.triar(_evento(), cliente_ia=cliente)
    kwargs = cliente.messages.chamadas[0]
    for proibido in ("thinking", "temperature", "top_p", "top_k"):
        assert proibido not in kwargs


def test_esquema_triagem_respeita_regras_structured_outputs():
    # SPEC-IA §3.1: additionalProperties:false + required lista todos os campos + enums.
    esq = triagem.ESQUEMA_TRIAGEM
    assert esq["additionalProperties"] is False
    assert set(esq["required"]) == {
        "relevante_para_al", "concelhos", "tipo", "resumo_1_frase"
    }
    assert esq["properties"]["relevante_para_al"]["enum"] == ["sim", "nao", "duvida"]
    assert esq["properties"]["tipo"]["enum"] == [
        "regulamento", "contencao", "limpeza", "outro"
    ]


# ==========================================================================
#  Input — título + ~3.000 primeiras palavras do documento
# ==========================================================================
def test_input_inclui_titulo_e_texto_do_documento():
    cliente = _cliente_json(_JSON_SIM)
    ev = _evento(titulo="Regulamento Municipal de AL de Sintra", texto="corpo integral aqui")
    triagem.triar(ev, cliente_ia=cliente)
    conteudo = cliente.messages.chamadas[0]["messages"][0]["content"]
    assert "Regulamento Municipal de AL de Sintra" in conteudo
    assert "corpo integral aqui" in conteudo


def test_input_trunca_documento_a_3000_palavras():
    cliente = _cliente_json(_JSON_SIM)
    corpo = " ".join(f"p{i}" for i in range(5000))  # 5000 palavras: p0 … p4999
    triagem.triar(_evento(texto=corpo), cliente_ia=cliente)
    conteudo = cliente.messages.chamadas[0]["messages"][0]["content"]
    assert " p2999 " in f" {conteudo} "      # última palavra mantida (índice 2999)
    assert "p3000" not in conteudo            # a 3001.ª palavra é cortada


def test_triar_sem_texto_usa_so_titulo():
    # Um `EventoRegulatorio` persistido não tem corpo (`.texto`); a triagem tolera-o e
    # corre só com o título, sem rebentar.
    cliente = _cliente_json(_JSON_SIM)
    ev = SimpleNamespace(titulo="Regulamento de AL de Faro")  # sem `.texto`
    t = triagem.triar(ev, cliente_ia=cliente)
    assert isinstance(t, triagem.Triagem)
    conteudo = cliente.messages.chamadas[0]["messages"][0]["content"]
    assert "Regulamento de AL de Faro" in conteudo


# ==========================================================================
#  Isolamento — uma única chamada ao cliente injetado, sem rede
# ==========================================================================
def test_triar_faz_exatamente_uma_chamada_ao_cliente_injetado():
    cliente = _cliente_json(_JSON_SIM)
    triagem.triar(_evento(), cliente_ia=cliente)
    assert len(cliente.messages.chamadas) == 1


def test_triar_json_invalido_propaga_erro_ia():
    # Sem JSON válido (ex. refusal) → o wrapper levanta ErroIA; a triagem propaga para o
    # pipeline decidir (não inventa uma triagem silenciosa).
    from app.ia import cliente as cli

    cliente = _cliente_json("isto não é JSON")
    with pytest.raises(cli.ErroIA):
        triagem.triar(_evento(), cliente_ia=cliente)
