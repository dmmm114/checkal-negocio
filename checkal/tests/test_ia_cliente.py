"""Testes do wrapper fino sobre o SDK Anthropic (FDS 4) — pedir_json / pedir_texto.

Contrato (SPEC-FDS4 §BASE + SPEC-IA §2/§3/§4):

    pedir_json(cliente_ia, *, modelo, utilizador, esquema, sistema=None, max_tokens=...) -> dict
        → Passo 1 (triagem, Haiku): structured output (`output_config.format` json_schema);
          o 1.º bloco de texto é JSON do schema → devolve `dict`.
    pedir_texto(cliente_ia, *, modelo, utilizador, sistema=None, max_tokens=...) -> str
        → Passo 2 (redação, Sonnet): prosa PT-PT; `thinking:disabled`; devolve `str`.

O `cliente_ia` (SDK Anthropic) é sempre **injetado**; a submissão/polling do Batch API
fica atrás desta interface — nos testes o cliente é **falso** e nunca se toca a rede.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. Zero IA/rede real. Escrito ANTES da
implementação (TDD). Verifica-se:
  - structured output devolve `dict`; texto devolve `str`; **modelo correto passado**;
  - Sonnet: `thinking:disabled` e **nunca** `temperature`/`top_p`/`top_k` (400 se enviados);
  - triagem: `output_config.format` com o `json_schema` recebido; **sem** `thinking`;
  - o `sistema` (incl. lista de blocos com `cache_control` no excerto) passa **intacto**.
"""
from __future__ import annotations

import pytest

from app.ia import cliente as cli


# ==========================================================================
#  Duplo de teste — cliente Anthropic falso (registador de chamadas)
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


def _cliente_texto(texto: str, *, stop_reason: str = "end_turn") -> ClienteFalso:
    return ClienteFalso(_Mensagem([_Bloco("text", texto)], stop_reason=stop_reason))


ESQUEMA_TRIAGEM = {
    "type": "object",
    "properties": {
        "relevante_para_al": {"type": "string", "enum": ["sim", "nao", "duvida"]},
        "concelhos": {"type": "array", "items": {"type": "string"}},
        "tipo": {"type": "string", "enum": ["regulamento", "contencao", "limpeza", "outro"]},
        "resumo_1_frase": {"type": "string"},
    },
    "required": ["relevante_para_al", "concelhos", "tipo", "resumo_1_frase"],
    "additionalProperties": False,
}


# ==========================================================================
#  pedir_json — structured output (triagem, Haiku) → dict
# ==========================================================================
def test_pedir_json_devolve_dict():
    cliente = _cliente_texto(
        '{"relevante_para_al": "sim", "concelhos": ["Loulé"], '
        '"tipo": "regulamento", "resumo_1_frase": "Novo regulamento de AL em Loulé."}'
    )
    resultado = cli.pedir_json(
        cliente,
        modelo="claude-haiku-4-5-20251001",
        utilizador="Título + excerto do documento…",
        esquema=ESQUEMA_TRIAGEM,
    )
    assert isinstance(resultado, dict)
    assert resultado["relevante_para_al"] == "sim"
    assert resultado["concelhos"] == ["Loulé"]


def test_pedir_json_passa_modelo_e_output_config():
    cliente = _cliente_texto('{"relevante_para_al": "nao", "concelhos": [], '
                             '"tipo": "outro", "resumo_1_frase": "Nada de AL."}')
    cli.pedir_json(
        cliente,
        modelo="claude-haiku-4-5-20251001",
        utilizador="doc",
        esquema=ESQUEMA_TRIAGEM,
    )
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    # structured output: output_config.format json_schema com o esquema recebido, tal e qual.
    assert kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": ESQUEMA_TRIAGEM}
    }


def test_pedir_json_nao_envia_thinking_nem_amostragem():
    # Haiku: thinking off por omissão (não se configura); nunca parâmetros de amostragem.
    cliente = _cliente_texto('{"relevante_para_al": "duvida", "concelhos": [], '
                             '"tipo": "outro", "resumo_1_frase": "x"}')
    cli.pedir_json(cliente, modelo="m", utilizador="doc", esquema=ESQUEMA_TRIAGEM)
    kwargs = cliente.messages.chamadas[0]
    for proibido in ("thinking", "temperature", "top_p", "top_k"):
        assert proibido not in kwargs


def test_pedir_json_json_invalido_levanta_erro():
    cliente = _cliente_texto("isto não é JSON")
    with pytest.raises(cli.ErroIA):
        cli.pedir_json(cliente, modelo="m", utilizador="doc", esquema=ESQUEMA_TRIAGEM)


def test_pedir_json_sem_bloco_texto_levanta_erro():
    cliente = ClienteFalso(_Mensagem([]))  # resposta sem qualquer bloco de texto
    with pytest.raises(cli.ErroIA):
        cli.pedir_json(cliente, modelo="m", utilizador="doc", esquema=ESQUEMA_TRIAGEM)


# ==========================================================================
#  pedir_texto — prosa (alerta, Sonnet) → str
# ==========================================================================
def test_pedir_texto_devolve_str():
    cliente = _cliente_texto("O documento não especifica prazo. Fonte: https://exemplo.pt")
    resultado = cli.pedir_texto(
        cliente,
        modelo="claude-sonnet-5",
        sistema="regras + excerto",
        utilizador="DADOS DO AL: nº 12345…",
    )
    assert isinstance(resultado, str)
    assert resultado == "O documento não especifica prazo. Fonte: https://exemplo.pt"


def test_pedir_texto_passa_modelo_e_thinking_desligado():
    cliente = _cliente_texto("alerta")
    cli.pedir_texto(cliente, modelo="claude-sonnet-5", utilizador="dados do AL")
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["model"] == "claude-sonnet-5"
    # Sonnet 5: adaptive thinking está LIGADO por omissão → tem de vir explicitamente desligado.
    assert kwargs["thinking"] == {"type": "disabled"}


def test_pedir_texto_nunca_envia_amostragem_nem_output_config():
    # Sonnet 5 devolve 400 a temperature/top_p/top_k; e prosa não usa output_config.
    cliente = _cliente_texto("alerta")
    cli.pedir_texto(cliente, modelo="claude-sonnet-5", utilizador="dados")
    kwargs = cliente.messages.chamadas[0]
    for proibido in ("temperature", "top_p", "top_k", "output_config"):
        assert proibido not in kwargs


def test_pedir_texto_sem_bloco_texto_devolve_vazio():
    # Sem prosa (ex. refusal sem texto) → "" para a validação a jusante reprovar e cair
    # no formato manual de recurso (nunca fica nada por comunicar).
    cliente = ClienteFalso(_Mensagem([], stop_reason="refusal"))
    assert cli.pedir_texto(cliente, modelo="m", utilizador="dados") == ""


# ==========================================================================
#  Forma partilhada do pedido (system/mensagens/max_tokens)
# ==========================================================================
def test_utilizador_vai_como_mensagem_de_role_user():
    cliente = _cliente_texto("ok")
    cli.pedir_texto(cliente, modelo="m", utilizador="conteúdo do utilizador")
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["messages"] == [{"role": "user", "content": "conteúdo do utilizador"}]


def test_sistema_ausente_nao_passa_system():
    cliente = _cliente_texto("ok")
    cli.pedir_texto(cliente, modelo="m", utilizador="dados")
    assert "system" not in cliente.messages.chamadas[0]


def test_sistema_lista_de_blocos_com_cache_control_passa_intacto():
    # O alerta põe o excerto no último bloco do system com cache_control ttl 1h; o wrapper
    # é agnóstico e passa a estrutura tal e qual (estável→volátil fica a cargo de quem chama).
    sistema = [
        {"type": "text", "text": "És o analista do CheckAL. Regras invioláveis…"},
        {
            "type": "text",
            "text": "EXCERTO: … alojamento local … 15/06/2026 …",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]
    cliente = _cliente_texto("alerta")
    cli.pedir_texto(cliente, modelo="claude-sonnet-5", sistema=sistema, utilizador="dados")
    assert cliente.messages.chamadas[0]["system"] == sistema


def test_max_tokens_default_e_parametrizavel():
    cliente = _cliente_texto("ok")
    cli.pedir_texto(cliente, modelo="m", utilizador="dados")
    assert cliente.messages.chamadas[0]["max_tokens"] == cli.MAX_TOKENS_TEXTO

    cliente2 = _cliente_texto("ok")
    cli.pedir_texto(cliente2, modelo="m", utilizador="dados", max_tokens=123)
    assert cliente2.messages.chamadas[0]["max_tokens"] == 123


def test_pedir_json_max_tokens_default():
    cliente = _cliente_texto('{"relevante_para_al": "sim", "concelhos": [], '
                             '"tipo": "outro", "resumo_1_frase": "x"}')
    cli.pedir_json(cliente, modelo="m", utilizador="doc", esquema=ESQUEMA_TRIAGEM)
    assert cliente.messages.chamadas[0]["max_tokens"] == cli.MAX_TOKENS_JSON


# ==========================================================================
#  Isolamento — uma única chamada, ao cliente injetado, sem rede
# ==========================================================================
def test_faz_exatamente_uma_chamada_ao_cliente_injetado():
    cliente = _cliente_texto("ok")
    cli.pedir_texto(cliente, modelo="m", utilizador="dados")
    assert len(cliente.messages.chamadas) == 1
