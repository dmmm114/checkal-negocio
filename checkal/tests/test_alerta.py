"""Testes do Passo 2 do pipeline regulatório — redação do alerta (Sonnet) + 3 camadas.

Contrato (SPEC-FDS4 §alerta, SPEC-IA §4/§5, AUTOMACAO §3)::

    gerar_alerta(evento, dados_al, *, cliente_ia, excerto) -> Alerta

Três camadas anti-alucinação:
  1. **template restritivo** — o prompt baseia-se só no excerto, cita a fonte, ≤180
     palavras, sem jargão; o excerto vai no último bloco de `system` com `cache_control`;
  2. **validação programática** (`app.ia.validacao.validar_alerta`) — url citada + todo
     o valor monetário/data ⊂ excerto; inválido → **regenera** (máx. 2 tentativas de IA);
  3. **formato manual de recurso** — 2 falhas → alerta por template **sem prosa da IA**
     ("Foi publicado {titulo} … em {concelho}. Lê aqui: {url}"), válido **por construção**.

🧯 Invariante inviolável: `gerar_alerta` **nunca** devolve um alerta que falhe
`validar_alerta` — nem da IA, nem do fallback. E o fallback **cita sempre** a url.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. Zero IA/rede real — o `cliente_ia`
é **injetado** e **falso** (devolve respostas scriptadas). Escrito ANTES da implementação.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import app.config as config
from app.ia import alerta as mod
from app.ia.validacao import validar_alerta


# ==========================================================================
#  Duplo de teste — cliente Anthropic falso (respostas scriptadas por chamada)
# ==========================================================================
class _Bloco:
    """Bloco de conteúdo à laia do SDK (`.type` + `.text`)."""

    def __init__(self, texto: str) -> None:
        self.type = "text"
        self.text = texto


class _Mensagem:
    """Resposta à laia de `anthropic.types.Message` (só o que o wrapper lê).

    Texto vazio (``""``) ⇒ sem qualquer bloco de texto — simula um `refusal` sem prosa.
    """

    def __init__(self, texto: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Bloco(texto)] if texto else []
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, respostas: list[str]) -> None:
        self._respostas = respostas
        self.chamadas: list[dict] = []  # kwargs de cada `.create(...)`

    def create(self, **kwargs) -> _Mensagem:
        i = min(len(self.chamadas), len(self._respostas) - 1)
        self.chamadas.append(kwargs)
        return _Mensagem(self._respostas[i])


class ClienteFalso:
    """`.messages.create(**kwargs)` devolve a resposta scriptada da vez e regista kwargs."""

    def __init__(self, *respostas: str) -> None:
        self.messages = _Messages(list(respostas))


# ==========================================================================
#  Dados de teste — evento, AL e excerto (a única fonte de verdade)
# ==========================================================================
URL = "https://files.diariodarepublica.pt/2s/2025/07/142000000/0037800403.pdf"

# Excerto canónico. Números fundamentados: 2500, 4000 (coima, com €), 30 (prazo, dias),
# e a data 15/06/2026. Nenhum outro valor pode aparecer no alerta.
EXCERTO = (
    "Regulamento Municipal de Alojamento Local de Loulé. Foi criada uma área de "
    "contenção onde ficam suspensos novos registos. A coima aplicável varia entre "
    "2.500 € e 4.000 €. Os titulares dispõem de um prazo de 30 dias, a contar de "
    "15/06/2026, para comunicar a sua situação."
)

# Alerta fiel: só valores do excerto (2.500 €, 4.000 €, 30 dias) e cita a url.
ALERTA_VALIDO = (
    "(a) Foi publicado um novo regulamento municipal de Alojamento Local em Loulé. "
    "(b) Afeta o teu AL? Possivelmente: o teu apartamento nº 100031, em Loulé, pode "
    "ficar abrangido pela nova área de contenção. "
    "(c) Confirma a tua situação junto da câmara; a coima aplicável varia entre "
    "2.500 € e 4.000 € e há um prazo de 30 dias para comunicar. "
    "Consulta o documento em " + URL
)

# Alerta com um valor INVENTADO (7.500 € não está no excerto) — deve ser reprovado.
ALERTA_INVALIDO = (
    "Foi publicado um regulamento em Loulé. A coima pode chegar a 7.500 €. "
    "Consulta o documento em " + URL
)


def _evento(titulo: str = "Regulamento n.º 927/2025 — Alojamento Local de Loulé"):
    return SimpleNamespace(
        titulo=titulo,
        url=URL,
        publicado_em=dt.date(2025, 7, 22),
        concelhos=["Loulé"],
    )


def _dados_al(concelho: str = "Loulé"):
    return SimpleNamespace(
        nr_registo=100031,
        nome_alojamento="Casa do Sol",
        modalidade="Apartamento",
        freguesia="Quarteira",
        concelho=concelho,
        data_registo=dt.date(2020, 3, 1),
        titular_tipo="singular",
    )


def _gerar(cliente_ia, *, evento=None, dados_al=None):
    return mod.gerar_alerta(
        evento or _evento(),
        dados_al or _dados_al(),
        cliente_ia=cliente_ia,
        excerto=EXCERTO,
    )


def _passa_validacao(alerta) -> bool:
    return validar_alerta(alerta.conteudo, url_fonte=URL, excerto=EXCERTO).valido


# ==========================================================================
#  Sanidade dos fixtures (o alerta "válido" é mesmo válido; o "inválido" não é)
# ==========================================================================
def test_fixture_alerta_valido_passa_validacao():
    assert validar_alerta(ALERTA_VALIDO, url_fonte=URL, excerto=EXCERTO).valido


def test_fixture_alerta_invalido_reprova_validacao():
    r = validar_alerta(ALERTA_INVALIDO, url_fonte=URL, excerto=EXCERTO)
    assert not r.valido
    assert "7.500" in " ".join(r.valores_orfaos)


# ==========================================================================
#  Camada 2 — caminho feliz: válido à 1.ª
# ==========================================================================
def test_valido_a_primeira_devolve_prosa_da_ia():
    cliente = ClienteFalso(ALERTA_VALIDO)
    alerta = _gerar(cliente)

    assert alerta.conteudo == ALERTA_VALIDO
    assert alerta.manual is False
    assert alerta.tentativas_ia == 1
    assert len(cliente.messages.chamadas) == 1  # uma única geração
    assert _passa_validacao(alerta)


# ==========================================================================
#  Camada 2 — regenera: inválido à 1.ª, válido à 2.ª
# ==========================================================================
def test_invalido_depois_valido_regenera_e_aceita():
    cliente = ClienteFalso(ALERTA_INVALIDO, ALERTA_VALIDO)
    alerta = _gerar(cliente)

    assert alerta.conteudo == ALERTA_VALIDO
    assert alerta.manual is False
    assert alerta.tentativas_ia == 2
    assert len(cliente.messages.chamadas) == 2  # regenerou exatamente uma vez
    assert _passa_validacao(alerta)


# ==========================================================================
#  Camada 3 — 2 falhas → formato manual de recurso
# ==========================================================================
def test_invalido_duas_vezes_cai_no_formato_manual():
    cliente = ClienteFalso(ALERTA_INVALIDO, ALERTA_INVALIDO)
    alerta = _gerar(cliente)

    assert alerta.manual is True
    assert alerta.tentativas_ia == 2
    assert len(cliente.messages.chamadas) == 2  # não há 3.ª tentativa de IA
    # sem prosa da IA — não reaproveita o texto reprovado
    assert "7.500" not in alerta.conteudo
    assert alerta.conteudo != ALERTA_INVALIDO
    assert _passa_validacao(alerta)


def test_fallback_manual_cita_sempre_a_url():
    cliente = ClienteFalso(ALERTA_INVALIDO, ALERTA_INVALIDO)
    alerta = _gerar(cliente)
    assert URL in alerta.conteudo


def test_fallback_manual_inclui_titulo_e_concelho_quando_seguro():
    # O título "Regulamento n.º 927/2025 …" não introduz nenhum valor órfão (927/2025
    # não é data/coima/prazo) → o formato rico passa a validação e é usado tal e qual.
    cliente = ClienteFalso(ALERTA_INVALIDO, ALERTA_INVALIDO)
    alerta = _gerar(cliente)
    assert "Regulamento n.º 927/2025" in alerta.conteudo
    assert "Loulé" in alerta.conteudo
    assert _passa_validacao(alerta)


def test_fallback_degrada_quando_titulo_traz_valor_orfao():
    # Um título com uma data que NÃO está no excerto tornaria o formato rico inválido;
    # o fallback degrada (larga o título) até passar a validação — por construção.
    evento = _evento(titulo="Regulamento de 01/01/2099 sobre Alojamento Local")
    cliente = ClienteFalso(ALERTA_INVALIDO, ALERTA_INVALIDO)
    alerta = _gerar(cliente, evento=evento)

    assert alerta.manual is True
    assert "01/01/2099" not in alerta.conteudo  # o valor órfão foi descartado
    assert "Loulé" in alerta.conteudo           # mantém o concelho (seguro)
    assert URL in alerta.conteudo
    assert _passa_validacao(alerta)


# ==========================================================================
#  Refusal / resposta sem prosa → tratado como falha → fallback
# ==========================================================================
def test_resposta_sem_texto_cai_no_manual():
    cliente = ClienteFalso("", "")  # refusal sem prosa nas duas tentativas
    alerta = _gerar(cliente)
    assert alerta.manual is True
    assert len(cliente.messages.chamadas) == 2
    assert _passa_validacao(alerta)


# ==========================================================================
#  cliente_ia None (IA indisponível) → direto ao manual, sem qualquer chamada
# ==========================================================================
def test_cliente_ia_none_vai_direto_ao_manual():
    alerta = mod.gerar_alerta(_evento(), _dados_al(), cliente_ia=None, excerto=EXCERTO)
    assert alerta.manual is True
    assert alerta.tentativas_ia == 0
    assert URL in alerta.conteudo
    assert _passa_validacao(alerta)


# ==========================================================================
#  🧯 Invariante — NUNCA devolve um alerta que falhe a validação
# ==========================================================================
@pytest.mark.parametrize(
    "respostas",
    [
        (ALERTA_VALIDO,),                    # válido à 1.ª
        (ALERTA_INVALIDO, ALERTA_VALIDO),    # regenera → válido
        (ALERTA_INVALIDO, ALERTA_INVALIDO),  # 2 falhas → manual
        ("", ""),                            # refusal → manual
    ],
)
def test_nunca_devolve_alerta_que_falhe_validacao(respostas):
    alerta = _gerar(ClienteFalso(*respostas))
    assert _passa_validacao(alerta)


# ==========================================================================
#  Camada 1 — forma do prompt (template restritivo + cache no excerto)
# ==========================================================================
def test_prompt_usa_modelo_de_alerta_e_thinking_desligado():
    cliente = ClienteFalso(ALERTA_VALIDO)
    _gerar(cliente)
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["model"] == config.MODEL_ALERTA
    # o wrapper `pedir_texto` desliga o adaptive thinking do Sonnet 5
    assert kwargs["thinking"] == {"type": "disabled"}
    for proibido in ("temperature", "top_p", "top_k", "output_config"):
        assert proibido not in kwargs


def test_prompt_excerto_no_ultimo_bloco_de_system_com_cache_1h():
    cliente = ClienteFalso(ALERTA_VALIDO)
    _gerar(cliente)
    system = cliente.messages.chamadas[0]["system"]
    assert isinstance(system, list) and len(system) >= 2
    ultimo = system[-1]
    assert EXCERTO in ultimo["text"]
    # estável→volátil: o breakpoint de cache fica no último bloco partilhado (o excerto)
    assert ultimo["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_prompt_cita_a_url_e_baseia_se_no_excerto():
    cliente = ClienteFalso(ALERTA_VALIDO)
    _gerar(cliente)
    system_texto = " ".join(b["text"] for b in cliente.messages.chamadas[0]["system"])
    assert URL in system_texto       # instrui a citar a fonte
    assert EXCERTO in system_texto   # baseia-se no excerto fornecido


def test_prompt_user_traz_os_dados_do_al():
    cliente = ClienteFalso(ALERTA_VALIDO)
    _gerar(cliente)
    kwargs = cliente.messages.chamadas[0]
    assert kwargs["messages"][0]["role"] == "user"
    conteudo_user = kwargs["messages"][0]["content"]
    assert "100031" in conteudo_user     # nº de registo do AL
    assert "Loulé" in conteudo_user      # concelho do AL
    # o excerto NÃO se repete no user (fica no system partilhado/cacheado)
    assert EXCERTO not in conteudo_user
