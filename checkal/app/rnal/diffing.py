"""Diffing puro de um varrimento RNAL — o núcleo da deteção de eventos.

Fronteira do módulo (SPEC-FDS1.md §diffing): lógica **pura**, sem qualquer I/O
de BD. Recebe estruturas em memória (o estado conhecido + o que o varrimento viu)
e devolve a lista de eventos a persistir. Quem carrega o estado da BD, persiste os
eventos e atualiza os contadores (`ausencias_consecutivas`, `desaparecido_em`,
`visto_ultimo`, `hash_campos`) é o orquestrador `app.rnal.ingest`.

A **regra dos 2 varrimentos** (AUTOMACAO.md §1, `config.REGRA_N_VARRIMENTOS`) é o
coração deste módulo, porque um falso "o teu registo foi cancelado" destrói a
confiança no produto. Um registo só é dado como `desaparecido` quando:

  1. falta em **N varrimentos consecutivos** (`REGRA_N_VARRIMENTOS`, hoje 2), **e**
  2. o **concelho do registo devolveu resposta válida** (∈ `concelhos_ok`) em cada
     um desses varrimentos.

Uma ausência isolada não gera evento (apenas conta, do lado do `ingest`). Uma
ausência num concelho **fora** de `concelhos_ok` (varrimento parcial / timeout) é
**ignorada** — nem conta nem marca — para nunca confundir "a API não respondeu"
com "o AL foi cancelado".

Semântica do contador (contrato partilhado com `ingest`): `ausencias_consecutivas`
é o número de ausências **já contadas** (i.e. em concelhos que responderam). Por
indução, um valor ≥ 1 garante que as ausências anteriores foram todas em concelhos
`ok` — logo, para decidir o desaparecimento nesta passagem, basta verificar que o
concelho responde **agora**. O `ingest` incrementa o contador na presença de uma
ausência contável, repõe-no a 0 na presença do registo, e deixa-o intacto quando a
ausência é ignorada (concelho fora de `concelhos_ok`).

Tipos de evento (coincidem com `models.EventoRegisto.tipo`):
    ``novo`` | ``alterado`` | ``desaparecido`` | ``reapareceu``
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import app.config as config
from app.rnal.hashing import CAMPOS_RELEVANTES, hash_campos
from app.rnal.hashing import _normalizar as _normalizar

# Tipos de evento (espelham `models.EventoRegisto.tipo`).
TIPO_NOVO = "novo"
TIPO_ALTERADO = "alterado"
TIPO_DESAPARECIDO = "desaparecido"
TIPO_REAPARECEU = "reapareceu"

__all__ = [
    "EventoDiff",
    "RegistoEstado",
    "RegistoNovo",
    "diff_varrimento",
    "TIPO_NOVO",
    "TIPO_ALTERADO",
    "TIPO_DESAPARECIDO",
    "TIPO_REAPARECEU",
]


def _campos_de(fonte: Any) -> dict[str, Any]:
    """Extrai os `CAMPOS_RELEVANTES` de um dict achatado ou de um objeto."""
    if isinstance(fonte, Mapping):
        return {campo: fonte.get(campo) for campo in CAMPOS_RELEVANTES}
    return {campo: getattr(fonte, campo, None) for campo in CAMPOS_RELEVANTES}


def _norm_concelho(nome: Any) -> str:
    """Normaliza um nome de concelho para a porta `concelhos_ok` (casefold + trim).

    A API `list_RNAL` ecoa o concelho consultado, pelo que na prática o valor de
    `concelhos_ok` e o campo `Concelho` guardado coincidem. Esta normalização fecha
    a hipótese de um mismatch por caixa/espaços silenciar um cancelamento real
    (falso silêncio) — o pior erro depois do falso "cancelado", porque a promessa
    central do produto é justamente detetar o cancelamento. Preserva o contrato:
    `concelhos_ok` continua a ser `set[str]`; a normalização é só interna à porta.
    """
    return (nome or "").strip().casefold()


@dataclass(frozen=True)
class RegistoEstado:
    """Estado conhecido de um registo (o que o diffing precisa de saber da BD).

    - `hash_campos`: sha256 dos campos relevantes na última vez que foi visto.
    - `concelho`: último concelho conhecido — usado para a porta `concelhos_ok`
      quando o registo está **ausente** (não veio no scan para se ler o concelho).
    - `ausencias_consecutivas`: nº de ausências já contadas (concelho respondeu).
    - `desaparecido`: se já está marcado `desaparecido_em IS NOT NULL`.
    - `campos`: valores dos campos relevantes, para compor o diff de `alterado`.
    """

    hash_campos: str | None = None
    concelho: str | None = None
    ausencias_consecutivas: int = 0
    desaparecido: bool = False
    campos: Mapping[str, Any] | None = None

    @classmethod
    def de_campos(
        cls,
        campos: Mapping[str, Any],
        *,
        ausencias: int = 0,
        desaparecido: bool = False,
    ) -> RegistoEstado:
        """Constrói o estado a partir de um dict achatado (deriva hash e concelho)."""
        campos = dict(campos)
        return cls(
            hash_campos=hash_campos(campos),
            concelho=campos.get("concelho"),
            ausencias_consecutivas=ausencias,
            desaparecido=desaparecido,
            campos=campos,
        )

    @classmethod
    def de_linha(cls, linha: Any) -> RegistoEstado:
        """Constrói o estado a partir de uma linha ORM `registos` (ou objeto afim).

        Usa o `hash_campos` **guardado** (não o recalcula), para casar exatamente
        com o que o `ingest` gravou no varrimento anterior. `desaparecido` deriva
        de `desaparecido_em IS NOT NULL`.
        """
        return cls(
            hash_campos=getattr(linha, "hash_campos", None),
            concelho=getattr(linha, "concelho", None),
            ausencias_consecutivas=getattr(linha, "ausencias_consecutivas", 0) or 0,
            desaparecido=getattr(linha, "desaparecido_em", None) is not None,
            campos=_campos_de(linha),
        )


@dataclass(frozen=True)
class RegistoNovo:
    """Um registo tal como foi visto no varrimento atual.

    - `concelho`: concelho devolvido pelo scan (implica que o concelho respondeu).
    - `hash_campos`: sha256 dos campos relevantes agora.
    - `campos`: valores atuais dos campos relevantes, para compor o diff.
    """

    concelho: str | None = None
    hash_campos: str | None = None
    campos: Mapping[str, Any] | None = None

    @classmethod
    def de_campos(cls, campos: Mapping[str, Any]) -> RegistoNovo:
        """Constrói a partir de um dict achatado (deriva hash e concelho)."""
        campos = dict(campos)
        return cls(
            concelho=campos.get("concelho"),
            hash_campos=hash_campos(campos),
            campos=campos,
        )

    @classmethod
    def de_registo(cls, registo: Any) -> RegistoNovo:
        """Constrói a partir de um `schema.RegistoRNAL` (objeto achatado validado)."""
        return cls(
            concelho=getattr(registo, "concelho", None),
            hash_campos=hash_campos(registo),
            campos=_campos_de(registo),
        )


@dataclass(frozen=True)
class EventoDiff:
    """Um evento detetado por `diff_varrimento`, pronto para `eventos_registo`.

    `campos_alterados` (só em `alterado`) é o mapa ``campo → [antes, depois]``,
    JSON-serializável, para a coluna `eventos_registo.campos_alterados`.
    """

    tipo: str
    nr_registo: int
    campos_alterados: dict[str, list[Any]] | None = None


def _diff_campos(estado: RegistoEstado, novo: RegistoNovo) -> dict[str, list[Any]] | None:
    """Mapa ``campo → [antes, depois]`` dos campos relevantes que mudaram.

    A igualdade usa a **mesma** normalização do `hashing` (`_normalizar`), pelo que
    a invariante hash-diferente ⇒ pelo menos um campo listado se mantém: dois campos
    só divergem aqui se divergirem também no hash. Os valores devolvidos são os
    **originais** (não normalizados), para o alerta ser legível.
    """
    antes = estado.campos or {}
    depois = novo.campos or {}
    diff: dict[str, list[Any]] = {}
    for campo in CAMPOS_RELEVANTES:
        a = antes.get(campo)
        d = depois.get(campo)
        if _normalizar(a) != _normalizar(d):
            diff[campo] = [a, d]
    return diff or None


def diff_varrimento(
    estado_atual: Mapping[int, RegistoEstado],
    scan: Mapping[int, RegistoNovo],
    concelhos_ok: set[str],
) -> list[EventoDiff]:
    """Compara o estado conhecido com um varrimento e devolve os eventos.

    Parâmetros
    ----------
    estado_atual : nr_registo → `RegistoEstado` conhecido (da BD).
    scan         : nr_registo → `RegistoNovo` visto neste varrimento.
    concelhos_ok : concelhos que devolveram resposta válida neste varrimento.

    Regras (SPEC-FDS1.md §diffing):
      - **Presente** e desconhecido → ``novo``.
      - **Presente**, conhecido e `desaparecido` → ``reapareceu`` (facto saliente;
        um só evento, mesmo que os dados também tenham mudado).
      - **Presente**, conhecido, ativo e hash diferente → ``alterado`` (+ diff).
      - **Presente**, conhecido, ativo e hash igual → sem evento.
      - **Ausente**: regra dos 2 varrimentos. Se o concelho do registo **não** está
        em `concelhos_ok` → ignorado (varrimento parcial). Se já está `desaparecido`
        → sem evento (sem duplicados). Senão, à `REGRA_N_VARRIMENTOS`-ésima ausência
        contada → ``desaparecido``.

    Função pura: não muta os argumentos nem toca em I/O. A ordenação dos eventos é
    determinística (por `nr_registo`). A porta `concelhos_ok` governa **apenas**
    ausências: um registo presente processa-se sempre (se veio no scan, respondeu).
    """
    eventos: list[EventoDiff] = []

    # 1) Registos presentes no varrimento.
    for nr in sorted(scan):
        novo = scan[nr]
        estado = estado_atual.get(nr)
        if estado is None:
            eventos.append(EventoDiff(TIPO_NOVO, nr))
        elif estado.desaparecido:
            eventos.append(EventoDiff(TIPO_REAPARECEU, nr))
        elif estado.hash_campos != novo.hash_campos:
            eventos.append(EventoDiff(TIPO_ALTERADO, nr, _diff_campos(estado, novo)))
        # hash igual → registo inalterado → sem evento.

    # 2) Registos ausentes (no estado, mas não no varrimento).
    limiar = config.REGRA_N_VARRIMENTOS
    concelhos_ok_norm = {_norm_concelho(c) for c in concelhos_ok}
    for nr in sorted(estado_atual):
        if nr in scan:
            continue
        estado = estado_atual[nr]
        # Concelho não respondeu neste varrimento → ausência ignorada (parcial).
        # Comparação normalizada: um mismatch por caixa/espaços nunca pode
        # silenciar um cancelamento real (ver `_norm_concelho`).
        if _norm_concelho(estado.concelho) not in concelhos_ok_norm:
            continue
        # Já marcado desaparecido e ainda ausente → sem novo evento.
        if estado.desaparecido:
            continue
        # Esta ausência (contável) leva o contador a `ausencias_consecutivas + 1`.
        if estado.ausencias_consecutivas + 1 >= limiar:
            eventos.append(EventoDiff(TIPO_DESAPARECIDO, nr))
        # Abaixo do limiar → só conta (feito no ingest), sem evento.

    return eventos
