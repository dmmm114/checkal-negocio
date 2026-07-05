"""Cruzamento opt-out / oposição DGC — o último filtro antes de cada envio.

Regra (RATIONALE.md §3): regime de opt-out (Lei 41/2004, art. 13.º-B). Antes de
contactar uma coletiva, cruza-se o email com (i) a lista de oposição de pessoas
coletivas da Direção-Geral do Consumidor (DGC) e (ii) o log interno de opt-out.
Se constar de qualquer uma delas, não se contacta.

As duas listas são conjuntos INJETADOS (a fonte real liga-se depois). Este módulo
NÃO confia em que venham normalizadas: como é o último filtro antes do envio e o
custo de um falso negativo é uma coima (Lei 41/2004, art. 13.º-B; fiscalização
ANACOM), normaliza AMBOS os lados — o email de entrada E cada entrada dos
conjuntos — antes de comparar. Falha fechado, nunca confia no upstream (ex.: um
CSV da DGC com casing/whitespace que não controlamos).

Este módulo é filtro puro: NÃO envia, não persiste, não descobre emails. Funções
puras, sem efeitos colaterais.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

_T = TypeVar("_T")


def normalizar_email(email: str) -> str:
    """Forma canónica de um email para comparação: minúsculas + sem espaços à volta.

    É a mesma normalização que a fonte das listas (DGC/opt-out) aplica, para que
    "  Geral@X.PT  " bata com "geral@x.pt".
    """
    return email.strip().lower()


def preparar_listas(
    lista_dgc: Iterable[str],
    log_optout: Iterable[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """Normaliza AMBAS as listas de oposição UMA vez, na fronteira de injeção.

    Aplica `normalizar_email` a cada entrada dos dois conjuntos, devolvendo
    `frozenset`s canónicos. Feito uma só vez (ex.: no arranque de um lote), evita
    re-normalizar a cada `deve_excluir` e garante que a comparação de membership
    é simétrica. É aqui que se para de confiar no upstream.
    """
    return (
        frozenset(normalizar_email(e) for e in lista_dgc),
        frozenset(normalizar_email(e) for e in log_optout),
    )


def _consta(email_normalizado: str, dgc_norm: frozenset[str], optout_norm: frozenset[str]) -> bool:
    """Membership puro contra conjuntos JÁ normalizados. Qualquer presença exclui."""
    return email_normalizado in dgc_norm or email_normalizado in optout_norm


def deve_excluir(email: str, *, lista_dgc: Iterable[str], log_optout: Iterable[str]) -> bool:
    """True se o email (normalizado) constar da oposição DGC OU do opt-out interno.

    Normaliza os DOIS lados (email e conjuntos) antes de comparar — não assume que
    as listas injetadas venham canónicas. Viés conservador: qualquer presença
    exclui. Para cruzar muitos contactos contra as mesmas listas, usa
    `preparar_listas` uma vez e `filtrar_optout` (que não re-normaliza por item).
    """
    dgc_norm, optout_norm = preparar_listas(lista_dgc, log_optout)
    return _consta(normalizar_email(email), dgc_norm, optout_norm)


def _email_de(item: object) -> str:
    """Extrai o email a cruzar: `.email_generico` de um ContactoEnderecavel, ou o
    próprio valor se for string.

    Se não houver email utilizável (None, tipo inesperado), devolve "" — o
    chamador trata-o como não-enviável e descarta-o, em vez de rebentar o gerador
    a meio e interromper o processamento de todo o lote.
    """
    generico = getattr(item, "email_generico", None)
    if isinstance(generico, str):
        return generico
    if isinstance(item, str):
        return item
    return ""


def filtrar_optout(
    contactos: Iterable[_T],
    *,
    lista_dgc: Iterable[str],
    log_optout: Iterable[str],
) -> Iterator[_T]:
    """Gera os contactos que NÃO devem ser excluídos, preservando a ordem.

    Cada item é ou um ContactoEnderecavel (usa-se `.email_generico`) ou uma string
    de email. Devolve os próprios objetos de entrada, não cópias. Não materializa
    os excluídos.

    Normaliza as listas UMA vez (via `preparar_listas`) e só depois itera — o custo
    de normalização não se paga por contacto, mas a comparação continua simétrica.
    """
    dgc_norm, optout_norm = preparar_listas(lista_dgc, log_optout)
    for item in contactos:
        email = _email_de(item)
        if not email.strip():
            continue  # sem email cruzável/enviável -> não segue para envio
        if not _consta(normalizar_email(email), dgc_norm, optout_norm):
            yield item
