"""Filtro de NIF (titular) — decide quem é endereçável por email frio B2B.

Regra fechada (RATIONALE.md §3): só é endereçável a pessoa COLETIVA, cujo NIF
começa por 5 ou 6. Tudo o resto (singular 1/2/3, singular não-residente 45,
ENI 8, provisória/condomínio 9, não-residente coletiva 7x, inválidos) fica
FORA do canal frio. `classificar_nif` serve só para logging/contexto.

Prefixos de NIF português relevantes:
  1/2/3 -> pessoa singular
  45    -> pessoa singular não-residente
  5/6   -> pessoa coletiva              (ÚNICO endereçável)
  7x    -> coletiva não-residente / entes públicos
  8     -> empresário em nome individual (ENI, pessoa singular)
  9x    -> coletiva provisória, condomínio, herança
"""
from __future__ import annotations

_SINGULAR = frozenset("123")
_COLETIVA = frozenset("56")


def _limpar(nif: str | None) -> str:
    """Remove todo o whitespace, pontos e o prefixo 'PT'; devolve "" se inválido de raiz.

    Usa ``"".join(nif.split())`` para apanhar qualquer whitespace Unicode
    (espaço, tab, newline '\\n', carriage return '\\r', non-breaking space
    '\\xa0', …) que um export do RNAL possa trazer — senão uma coletiva 5/6
    legítima com '\\n'/'\\xa0' no campo seria descartada do canal (falso negativo).
    O guard ASCII em `classificar_nif`/`e_enderecavel` continua a rejeitar
    numerais Unicode não-ASCII.
    """
    if not isinstance(nif, str):
        return ""
    limpo = "".join(nif.split()).replace(".", "")
    if limpo[:2].upper() == "PT":
        limpo = limpo[2:]
    return limpo


def classificar_nif(nif: str | None) -> str:
    """Classifica o NIF em "singular" | "coletiva" | "outro" | "invalido".

    Só para logging/contexto — a decisão de endereçamento é `e_enderecavel`.
    """
    limpo = _limpar(nif)
    if len(limpo) != 9 or not (limpo.isascii() and limpo.isdigit()):
        return "invalido"
    if limpo[0] in _SINGULAR or limpo[:2] == "45":
        return "singular"
    if limpo[0] in _COLETIVA:
        return "coletiva"
    return "outro"


def e_enderecavel(nif: str | None) -> bool:
    """True SÓ se o NIF for 9 dígitos numéricos ASCII e o 1.º dígito ∈ {5,6}.

    Viés conservador: qualquer ambiguidade (letras, comprimento, None, prefixo
    '45' que contém um 5 fora do 1.º dígito, numerais Unicode não-ASCII como
    árabe-índicos/sobrescritos/devanágari) resulta em False.
    """
    limpo = _limpar(nif)
    return (
        len(limpo) == 9
        and limpo.isascii()
        and limpo.isdigit()
        and limpo[0] in _COLETIVA
    )
