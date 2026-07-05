"""Passo 1 do pipeline regulatório — triagem IA (Haiku + structured output).

Fronteira do módulo (SPEC-FDS4 §triagem, SPEC-IA §3, AUTOMACAO.md §3): recebe um
**evento regulatório** (um documento já captado do DRE/câmaras) e classifica-o quanto
à relevância para Alojamento Local, chamando o Haiku (`config.MODEL_TRIAGEM`) **uma**
vez, em modo **structured output** (`output_config.format` com `json_schema`) para o
resultado ser JSON garantido. Devolve uma :class:`Triagem` já normalizada::

    triar(evento_regulatorio, *, cliente_ia) -> Triagem
    e_relevante(triagem) -> bool          # 'duvida' conta como 'sim' (conservador)

**Input do modelo** (SPEC-IA §3 / AUTOMACAO §3): título + as ~3.000 primeiras palavras
do documento. O `evento_regulatorio` é *duck-typed* — só se lêem `.titulo` (obrigatório
na prática) e `.texto` (o corpo do documento; **opcional**). Um `EventoRegulatorio`
persistido (`app.models`) não guarda o corpo — nesse caso a triagem corre só com o
título, sem rebentar; quando o pipeline dispõe do texto integral do ato (extraído pelo
`dre_client`), anexa-o em `.texto` e a triagem usa-o.

**Output** (schema fixo — :data:`ESQUEMA_TRIAGEM`):
``{relevante_para_al: sim|nao|duvida, concelhos: [...],
   tipo: regulamento|contencao|limpeza|outro, resumo_1_frase}``.

🧯 **Regra conservadora (inviolável, AUTOMACAO §3):** `duvida` é tratado como `sim` —
:func:`e_relevante` só devolve ``False`` para `nao`. Nunca se cala por dúvida (um evento
ambíguo segue para redação, não é descartado). O parse é igualmente conservador: um
`relevante_para_al` fora do enum (drift do modelo) vira `duvida` (relevante), **nunca**
`nao`; um `tipo` desconhecido vira `outro`; `concelhos` não-lista vira ``[]``.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria nem
importa nenhum cliente Anthropic — o `cliente_ia` é sempre **injetado** por quem chama
(o pipeline compõe-o via :func:`app.ia.obter_cliente_ia`; falso nos testes). Toda a
conversa com o modelo passa pelo wrapper :mod:`app.ia.cliente` (`pedir_json`), pelo que
correr os testes nunca toca a IA/rede. Se o modelo não devolver JSON válido, `pedir_json`
levanta :class:`app.ia.cliente.ErroIA` e a triagem **propaga** — não inventa um veredicto.

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import app.config as config
from app.ia import cliente as _cliente

__all__ = [
    "Triagem",
    "triar",
    "e_relevante",
    "ESQUEMA_TRIAGEM",
    "SISTEMA_TRIAGEM",
    "MAX_PALAVRAS_DOC",
    "RELEVANCIAS",
    "TIPOS",
]

# Nº máximo de palavras do corpo do documento enviadas ao modelo (SPEC-IA §3 /
# AUTOMACAO §3: "título + primeiras ~3.000 palavras"). Haiku 4.5 tem contexto de 200k
# → folga total; o corte serve o custo/estabilidade, não o limite de contexto.
MAX_PALAVRAS_DOC = 3000

# Valores canónicos dos enums (SPEC-IA §3.2). Fora destes conjuntos, o parse normaliza
# conservadoramente (ver módulo).
RELEVANCIAS: tuple[str, ...] = ("sim", "nao", "duvida")
TIPOS: tuple[str, ...] = ("regulamento", "contencao", "limpeza", "outro")

# Relevância que faz o evento **seguir** para redação. 'duvida' entra de propósito —
# regra conservadora: na dúvida, não se cala (só 'nao' trava).
_RELEVANTES: frozenset[str] = frozenset({"sim", "duvida"})

# Schema do structured output (SPEC-IA §3.2). Regras dos structured outputs:
# `additionalProperties: false` em cada objeto, `required` lista todos os campos, `enum`
# suportado — nada de min/max/pattern. Manter **estável e único** (a gramática fica em
# cache 24h por estrutura de schema). É idêntico ao usado nos testes do wrapper.
ESQUEMA_TRIAGEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevante_para_al": {"type": "string", "enum": ["sim", "nao", "duvida"]},
        "concelhos": {"type": "array", "items": {"type": "string"}},
        "tipo": {
            "type": "string",
            "enum": ["regulamento", "contencao", "limpeza", "outro"],
        },
        "resumo_1_frase": {"type": "string"},
    },
    "required": ["relevante_para_al", "concelhos", "tipo", "resumo_1_frase"],
    "additionalProperties": False,
}

# System da triagem. Estável (sem bytes voláteis — datas/IDs) para não estragar a cache
# de gramática/prompt. Instrui o Haiku a classificar e — alinhado com a regra
# conservadora — a preferir `duvida` a `nao` quando o documento é ambíguo.
SISTEMA_TRIAGEM = (
    "És o classificador do CheckAL. Recebes um documento publicado no Diário da "
    "República (ou por uma câmara municipal) e decides se ele regula ou afeta o "
    "Alojamento Local (AL) em Portugal.\n"
    "Responde SÓ com o JSON do formato pedido, com estes campos:\n"
    "- relevante_para_al: 'sim' se o documento regula/afeta AL; 'nao' só se claramente "
    "nada tem a ver com AL; 'duvida' se for ambíguo ou não tiveres a certeza. Na dúvida "
    "escolhe 'duvida', NUNCA 'nao'.\n"
    "- concelhos: os municípios portugueses afetados, tal como aparecem no documento "
    "(lista vazia se nenhum for identificável).\n"
    "- tipo: 'regulamento' (regulamento municipal de AL), 'contencao' (área de "
    "contenção/suspensão de novos registos), 'limpeza' (regras de higiene/resíduos/ruído "
    "aplicáveis a AL) ou 'outro'.\n"
    "- resumo_1_frase: uma frase curta, em português, do que o documento faz.\n"
    "Baseia-te apenas no texto fornecido; não inventes concelhos nem factos."
)


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class Triagem:
    """Veredicto normalizado da triagem de um evento regulatório (imutável).

    :param relevante_para_al: ``"sim"`` | ``"nao"`` | ``"duvida"`` (já normalizado — um
        valor inesperado do modelo é reduzido conservadoramente a ``"duvida"``).
    :param concelhos: municípios afetados segundo o modelo (só strings; pode ser vazia).
    :param tipo: ``"regulamento"`` | ``"contencao"`` | ``"limpeza"`` | ``"outro"``.
    :param resumo_1_frase: resumo do documento numa frase (``""`` se ausente).
    """

    relevante_para_al: str
    concelhos: list[str] = field(default_factory=list)
    tipo: str = "outro"
    resumo_1_frase: str = ""


def e_relevante(triagem: Triagem) -> bool:
    """O evento deve seguir para redação de alerta? (`duvida` conta como `sim`).

    🧯 Regra conservadora (AUTOMACAO §3): só ``"nao"`` trava o pipeline; ``"sim"`` e
    ``"duvida"`` seguem. Nunca se cala um evento por dúvida.
    """
    return triagem.relevante_para_al in _RELEVANTES


# ==========================================================================
#  Auxiliares puros — construção do input e parse do output
# ==========================================================================
def _primeiras_palavras(texto: str, n: int) -> str:
    """As primeiras `n` palavras de `texto` (colapsa espaços; ``""`` se vazio)."""
    return " ".join(texto.split()[:n])


def _texto_utilizador(evento: Any) -> str:
    """Monta a mensagem `user`: título + as ~3.000 primeiras palavras do documento.

    Lê `.titulo` e `.texto` do evento (ambos opcionais/tolerados). Um evento sem corpo
    (`EventoRegulatorio` persistido) corre só com o título; um sem título nenhum corre
    só com o corpo. A estrutura é estável (rótulos fixos) — sem bytes voláteis.
    """
    titulo = (getattr(evento, "titulo", None) or "").strip()
    corpo = (getattr(evento, "texto", None) or "").strip()

    partes: list[str] = []
    if titulo:
        partes.append(f"TÍTULO: {titulo}")
    if corpo:
        partes.append(f"DOCUMENTO:\n{_primeiras_palavras(corpo, MAX_PALAVRAS_DOC)}")
    return "\n\n".join(partes)


def _normalizar_relevancia(valor: Any) -> str:
    """Reduz `relevante_para_al` ao enum, conservadoramente.

    Um valor fora de {sim,nao,duvida} (drift do modelo) vira ``"duvida"`` — nunca
    ``"nao"``: não se descarta um evento por causa de um rótulo inesperado.
    """
    if isinstance(valor, str) and valor in RELEVANCIAS:
        return valor
    return "duvida"


def _normalizar_tipo(valor: Any) -> str:
    """Reduz `tipo` ao enum; desconhecido → ``"outro"``."""
    if isinstance(valor, str) and valor in TIPOS:
        return valor
    return "outro"


def _normalizar_concelhos(valor: Any) -> list[str]:
    """Extrai só as strings (não vazias, sem espaços supérfluos) de `concelhos`.

    Um valor não-lista (``None``/objeto) vira ``[]``; itens não-string são descartados.
    Preserva a ordem, sem repetidos.
    """
    if not isinstance(valor, (list, tuple)):
        return []
    vistos: list[str] = []
    for item in valor:
        if isinstance(item, str) and (nome := item.strip()) and nome not in vistos:
            vistos.append(nome)
    return vistos


def _triagem_de(dados: dict[str, Any]) -> Triagem:
    """Converte o `dict` do structured output numa :class:`Triagem` normalizada."""
    resumo = dados.get("resumo_1_frase")
    return Triagem(
        relevante_para_al=_normalizar_relevancia(dados.get("relevante_para_al")),
        concelhos=_normalizar_concelhos(dados.get("concelhos")),
        tipo=_normalizar_tipo(dados.get("tipo")),
        resumo_1_frase=resumo.strip() if isinstance(resumo, str) else "",
    )


# ==========================================================================
#  API pública — triagem de um evento
# ==========================================================================
def triar(evento_regulatorio: Any, *, cliente_ia: Any) -> Triagem:
    """Triagem IA de um evento regulatório (Haiku, structured output → :class:`Triagem`).

    :param evento_regulatorio: o documento captado (duck-typed: lê `.titulo` e, se
        existir, `.texto`). Ver o módulo para a tolerância a corpo ausente.
    :param cliente_ia: cliente Anthropic **injetado** (falso nos testes; nunca criado
        aqui — LIVE-GATED). É passado tal e qual ao wrapper :func:`app.ia.cliente.pedir_json`.
    :returns: :class:`Triagem` normalizada. Usar :func:`e_relevante` para decidir se
        segue para redação (`duvida` conta como relevante).

    Faz **uma** chamada ao modelo (`config.MODEL_TRIAGEM`), em structured output com
    :data:`ESQUEMA_TRIAGEM`. Não envia `thinking` (Haiku: off por omissão) nem parâmetros
    de amostragem — tudo isso é garantido pelo wrapper.

    :raises app.ia.cliente.ErroIA: o modelo não devolveu JSON válido (ex. `refusal`). A
        triagem **propaga** — cabe ao pipeline decidir (retry/arquivar/avisar), nunca se
        fabrica um veredicto silencioso.
    """
    dados = _cliente.pedir_json(
        cliente_ia,
        modelo=config.MODEL_TRIAGEM,
        sistema=SISTEMA_TRIAGEM,
        utilizador=_texto_utilizador(evento_regulatorio),
        esquema=ESQUEMA_TRIAGEM,
    )
    return _triagem_de(dados)
