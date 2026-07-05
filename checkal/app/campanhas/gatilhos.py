"""Deteção de gatilhos de campanha (FDS 6, SPEC-FDS6.md §gatilhos).

Primeiro elo do motor de prospeção: transforma os **eventos de negócio** já
detetados pelo pipeline de dados em **candidatos a campanha** (nrs + motivo), sem
enviar nada nem decidir endereçamento — isso é da segmentação (núcleo de
compliance) e do motor a jusante.

Lê duas filas de eventos AINDA NÃO usados para campanha e classifica-as em três
motivos (SPEC-FDS6.md §gatilhos):

    novo                 ← `eventos_registo.tipo == 'novo'` (um AL novo no RNAL);
                           1 gatilho por registo novo.
    alteracao_relevante  ← `eventos_registo.tipo == 'alterado'` (o diff já só nasce
                           para campos relevantes — `app.rnal.diffing`) OU
                           `eventos_regulatorios` com triagem relevante (regulamento
                           municipal); 1 gatilho por alteração.
    limpeza              ← `eventos_registo.tipo == 'desaparecido'` **em massa** num
                           concelho (>= `limiar_limpeza` desaparecidos no mesmo
                           concelho — a onda de cancelamentos que é sinal de mercado,
                           ex.: Porto mai/2026); 1 gatilho por concelho.

🚦 **Idempotência com âncora PRÓPRIA (não colide com os outros pipelines).**
`eventos_registo.processado` e `eventos_regulatorios.processado` são as âncoras dos
pipelines de **alertas a clientes** (`app.alertas_estado`) e **regulatório**
(`app.regulatorio.pipeline`) — reutilizá-las aqui roubava eventos a esses
consumidores (o `novo`, por ex., é drenado por `alertas_estado` com `processado=True`
sem gerar nada). A campanha é um consumidor SEPARADO dos mesmos eventos, por isso
tem a sua própria marca durável: uma linha em `alertas` com `canal == CANAL_GATILHO`
(sem cliente, não enviada). É o mesmo idioma de "marcador durável sem coluna
dedicada" que `app.alertas_estado` usa para o pendente de desambiguação, e é
inequívoco porque **todas** as consultas de "já usado?" filtram por esse canal — um
alerta a cliente sobre o mesmo evento (canal `email`/`pendente_desambiguacao`) nunca
conta como usado para campanha.

Fronteira (igual a `app.alertas_estado`): a função recebe a **`session`** de quem
chama e **não faz commit** — a transação é do orquestrador (o cron do wire, sob
`db.get_session`). Se algo a jusante levantar, o rollback do chamador desfaz os
marcadores e os eventos ficam por usar (retry natural na passagem seguinte).

Nota de acumulação: desaparecidos **abaixo** do limiar de um concelho NÃO são
marcados usados — ficam por consumir para poderem juntar-se a uma onda futura; só
quando o concelho cruza o limiar é que a limpeza é emitida e os seus eventos
marcados. Assim a mesma limpeza nunca é emitida duas vezes, mas uma onda que se
forma ao longo de várias passagens acaba por ser apanhada por inteiro.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import app.models as models
from app.rnal.diffing import TIPO_ALTERADO, TIPO_DESAPARECIDO, TIPO_NOVO

__all__ = [
    "MOTIVO_NOVO",
    "MOTIVO_ALTERACAO",
    "MOTIVO_LIMPEZA",
    "ORIGEM_EVENTO_REGISTO",
    "ORIGEM_EVENTO_REGULATORIO",
    "CANAL_GATILHO",
    "LIMIAR_LIMPEZA",
    "RELEVANCIAS_GATILHO",
    "Gatilho",
    "detetar_gatilhos",
]

# --- Motivos do gatilho (o "porquê" da abordagem) ---
MOTIVO_NOVO = "novo"
MOTIVO_ALTERACAO = "alteracao_relevante"
MOTIVO_LIMPEZA = "limpeza"

# --- Origem do evento consumido (qual das duas filas) ---
# Coincidem com `Alerta.origem` já usado por `app.alertas_estado` /
# `app.regulatorio.pipeline` — o par (origem, origem_id) identifica o evento.
ORIGEM_EVENTO_REGISTO = "eventos_registo"
ORIGEM_EVENTO_REGULATORIO = "eventos_regulatorios"

# --- Âncora de idempotência da campanha ---
# Valor de `Alerta.canal` do marcador durável "evento usado para campanha".
# SEPARADO dos canais de comunicação a clientes (`email`, `pendente_desambiguacao`).
CANAL_GATILHO = "campanha"

# --- Limiar de "limpeza" (desaparecimento em massa num concelho) ---
# Nº mínimo de desaparecidos (não usados) no mesmo concelho para a onda contar como
# sinal de mercado. Tunável (o cron/motor pode injetar outro; um refinamento por
# percentagem da base do concelho, à la `config.BREAKER_PCT_CONCELHO`, fica em aberto).
LIMIAR_LIMPEZA = 5

# --- Triagens regulatórias que geram gatilho ---
# 🧯 Conservador: `duvida` conta como relevante (nunca calar por dúvida) — mesma
# regra de `app.ia.triagem.e_relevante` / `app.regulatorio.pipeline`.
RELEVANCIAS_GATILHO = frozenset({"relevante", "duvida"})


@dataclass(frozen=True, slots=True)
class Gatilho:
    """Um candidato a campanha: o "porquê" (motivo) + os alvos (nrs/concelhos).

    Imutável e feito só de primitivos (tuplos de int/str), pelo que sobrevive ao
    fecho da sessão e é seguro de comparar/hashear nos testes e no motor.

    Campos
    ------
    motivo:
        `MOTIVO_NOVO` | `MOTIVO_ALTERACAO` | `MOTIVO_LIMPEZA`.
    origem:
        `ORIGEM_EVENTO_REGISTO` | `ORIGEM_EVENTO_REGULATORIO` — qual fila o gerou.
    nrs:
        Registos-alvo. Vazio para o gatilho regulatório (é ao nível do concelho; a
        expansão para registos é da segmentação/motor).
    concelhos:
        Contexto de concelho (o concelho da limpeza; os concelhos do regulamento; o
        concelho do registo novo/alterado quando conhecido).
    evento_ids:
        Ids dos eventos consumidos por este gatilho — a prova e a base da marca de
        idempotência.
    """

    motivo: str
    origem: str
    nrs: tuple[int, ...] = ()
    concelhos: tuple[str, ...] = ()
    evento_ids: tuple[int, ...] = field(default_factory=tuple)


# ==========================================================================
#  Deteção
# ==========================================================================
def detetar_gatilhos(session, *, limiar_limpeza: int = LIMIAR_LIMPEZA) -> list[Gatilho]:
    """Deteta os gatilhos de campanha a partir dos eventos ainda não usados.

    Lê `eventos_registo` (novo | alterado | desaparecido) e `eventos_regulatorios`
    (triagem relevante) que ainda não têm marcador de campanha, classifica-os nos três
    motivos e devolve a lista de :class:`Gatilho` numa ordem determinística (registos
    por id de evento; limpeza por concelho ordenado; regulatório por id de evento).

    Marca cada evento consumido como usado (uma linha em `alertas` com
    `canal == CANAL_GATILHO`), de forma idempotente: uma 2.ª passagem não reemite os
    mesmos gatilhos. **Não faz commit** — a transação é do chamador.

    :param session: sessão SQLAlchemy do chamador (não é aberta nem committada aqui).
    :param limiar_limpeza: nº mínimo de desaparecidos no mesmo concelho para gerar
        uma limpeza. Abaixo dele, os desaparecidos ficam por usar (acumulam).
    :returns: lista de :class:`Gatilho` (vazia se não houver eventos por usar).
    """
    gatilhos: list[Gatilho] = []

    gatilhos.extend(_gatilhos_de_registo(session, limiar_limpeza=limiar_limpeza))
    gatilhos.extend(_gatilhos_regulatorios(session))

    # Popula os ids dos marcadores e torna-os visíveis a consultas posteriores na
    # mesma sessão (sem commit — é do chamador, tal como `app.alertas_estado`).
    session.flush()
    return gatilhos


# --- eventos_registo -------------------------------------------------------

def _usados_registo(session) -> set[int]:
    """Ids de `eventos_registo` já marcados usados para campanha."""
    linhas = (
        session.query(models.Alerta.origem_id)
        .filter(
            models.Alerta.canal == CANAL_GATILHO,
            models.Alerta.origem == ORIGEM_EVENTO_REGISTO,
            models.Alerta.origem_id.isnot(None),
        )
        .all()
    )
    return {origem_id for (origem_id,) in linhas}


def _gatilhos_de_registo(session, *, limiar_limpeza: int) -> list[Gatilho]:
    usados = _usados_registo(session)

    # Traz o concelho junto (LEFT JOIN) — evita N+1 e tolera registo em falta.
    linhas = (
        session.query(models.EventoRegisto, models.Registo.concelho)
        .outerjoin(
            models.Registo,
            models.Registo.nr_registo == models.EventoRegisto.nr_registo,
        )
        .filter(models.EventoRegisto.tipo.in_((TIPO_NOVO, TIPO_ALTERADO, TIPO_DESAPARECIDO)))
        .order_by(models.EventoRegisto.id)
        .all()
    )

    gatilhos: list[Gatilho] = []
    # concelho -> lista ordenada de (evento_id, nr) dos desaparecidos por usar
    desap_por_concelho: dict[str, list[tuple[int, int | None]]] = {}

    for evento, concelho in linhas:
        if evento.id in usados:
            continue

        nr = evento.nr_registo

        if evento.tipo == TIPO_NOVO:
            gatilhos.append(_gatilho_registo(MOTIVO_NOVO, evento.id, nr, concelho))
            _marcar_usado(session, ORIGEM_EVENTO_REGISTO, evento.id, nr, MOTIVO_NOVO)
        elif evento.tipo == TIPO_ALTERADO:
            gatilhos.append(_gatilho_registo(MOTIVO_ALTERACAO, evento.id, nr, concelho))
            _marcar_usado(session, ORIGEM_EVENTO_REGISTO, evento.id, nr, MOTIVO_ALTERACAO)
        elif evento.tipo == TIPO_DESAPARECIDO and concelho:
            # Sem concelho não há "concelho" para a onda: ignora-se (não se marca,
            # para não perder o evento sem sinal aproveitável).
            desap_por_concelho.setdefault(concelho, []).append((evento.id, nr))

    # Limpezas: um gatilho por concelho que cruzou o limiar (concelhos ordenados
    # para determinismo). Os sub-limiar ficam por marcar → acumulam p/ o futuro.
    for concelho in sorted(desap_por_concelho):
        eventos = desap_por_concelho[concelho]
        if len(eventos) < limiar_limpeza:
            continue
        evento_ids = tuple(eid for eid, _ in eventos)
        nrs = tuple(nr for _, nr in eventos if nr is not None)
        gatilhos.append(
            Gatilho(
                motivo=MOTIVO_LIMPEZA,
                origem=ORIGEM_EVENTO_REGISTO,
                nrs=nrs,
                concelhos=(concelho,),
                evento_ids=evento_ids,
            )
        )
        for eid, nr in eventos:
            _marcar_usado(session, ORIGEM_EVENTO_REGISTO, eid, nr, MOTIVO_LIMPEZA)

    return gatilhos


def _gatilho_registo(motivo: str, evento_id: int, nr: int | None, concelho: str | None) -> Gatilho:
    return Gatilho(
        motivo=motivo,
        origem=ORIGEM_EVENTO_REGISTO,
        nrs=(nr,) if nr is not None else (),
        concelhos=(concelho,) if concelho else (),
        evento_ids=(evento_id,),
    )


# --- eventos_regulatorios --------------------------------------------------

def _usados_regulatorio(session) -> set[int]:
    linhas = (
        session.query(models.Alerta.origem_id)
        .filter(
            models.Alerta.canal == CANAL_GATILHO,
            models.Alerta.origem == ORIGEM_EVENTO_REGULATORIO,
            models.Alerta.origem_id.isnot(None),
        )
        .all()
    )
    return {origem_id for (origem_id,) in linhas}


def _gatilhos_regulatorios(session) -> list[Gatilho]:
    usados = _usados_regulatorio(session)

    eventos = (
        session.query(models.EventoRegulatorio)
        .filter(models.EventoRegulatorio.triagem.in_(tuple(RELEVANCIAS_GATILHO)))
        .order_by(models.EventoRegulatorio.id)
        .all()
    )

    gatilhos: list[Gatilho] = []
    for evento in eventos:
        if evento.id in usados:
            continue
        concelhos = tuple(c for c in (evento.concelhos or []) if c)
        gatilhos.append(
            Gatilho(
                motivo=MOTIVO_ALTERACAO,
                origem=ORIGEM_EVENTO_REGULATORIO,
                nrs=(),
                concelhos=concelhos,
                evento_ids=(evento.id,),
            )
        )
        _marcar_usado(session, ORIGEM_EVENTO_REGULATORIO, evento.id, None, MOTIVO_ALTERACAO)
    return gatilhos


# --- Marcador durável ------------------------------------------------------

def _marcar_usado(session, origem: str, origem_id: int, nr: int | None, motivo: str) -> None:
    """Grava a marca "evento usado para campanha" (linha em `alertas`, canal próprio).

    Não é uma comunicação: `cliente_id` nulo (é prospeto), `enviado_em` nulo. O par
    (origem, origem_id) + `canal == CANAL_GATILHO` é a chave de idempotência lida por
    `_usados_registo`/`_usados_regulatorio`.
    """
    session.add(
        models.Alerta(
            cliente_id=None,
            nr_registo=nr,
            origem=origem,
            origem_id=origem_id,
            conteudo=motivo,
            enviado_em=None,
            canal=CANAL_GATILHO,
        )
    )
