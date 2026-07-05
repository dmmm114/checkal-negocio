"""WIRE de orquestração dos crons do CheckAL (FDS 5, SPEC-FDS5.md §wire).

Este é o **agente de orquestração**: liga as peças construídas nos blocos do FDS 5
(breaker, observabilidade, dunning, suporte, backups) e das fases anteriores (ingest
do FDS 1, alertas de estado do FDS 3, detalhe individual do FDS 3, pipeline DRE/IA do
FDS 4, envio da Resend) em **crons** completos, cada um sob o dead-man switch
:class:`app.observabilidade.com_healthcheck`.

O que o wire resolve — a 🚦 GUARDA DE SEQUÊNCIA
------------------------------------------------
O FDS 1 deteta desaparecimentos no varrimento nacional; o FDS 3
(:func:`app.alertas_estado.gerar_alertas_estado`) transforma-os em alertas
`desaparecido` **retidos** (`canal == pendente_desambiguacao`, `enviado_em IS NULL`) —
NUNCA enviados às cegas (`app/rnal/LIMITACOES-CONHECIDAS.md`). Cabe a este wire fechar
o circuito, correndo o breaker por concelho **antes de deixar sair qualquer alerta**:

    varrimento (ingest, FDS 1)
        → gerar_alertas_estado (FDS 3: cria os pendentes)
        → resolver_desaparecidos_pendentes (breaker por concelho, FDS 5):
              avaliar_concelho → desambiguar (página individual) → resolver_pendentes

:func:`resolver_desaparecidos_pendentes` agrupa os pendentes **por concelho** e, para
cada concelho, corre a cadeia do breaker. Sobre a leitura do limiar
(`avaliar_concelho.disparar`): o limiar `BREAKER_PCT_CONCELHO` mede um **salto anómalo**
(L2 — resposta nacional truncada; L1 em massa) e é registado como metadado; **mas a
amostragem da página individual (`desambiguar`) corre para TODO o concelho que tenha
pendentes**, mesmo abaixo do limiar. É a única leitura que satisfaz a guarda em todos
os casos:

  - a guarda exige confirmação POSITIVA na página individual antes de QUALQUER envio;
  - a copy do ramo `real` (`app.breaker._compor_confirmado`) **afirma** «confirmámos na
    página individual do RNAL» — só é verdade se de facto se amostrou;
  - 🚦 **L1** manifesta-se como UM único falso `desaparecido` (mudança de concelho com
    o destino em falha) — **abaixo** do limiar; só a amostragem por página o apanha.

Veredicto por concelho (`app.breaker.resolver_pendentes`):
  - `real`        → LIBERTA os pendentes (envia, data `enviado_em`, canal `email`);
  - `api_partida` → SUPRIME (reabre o evento p/ retry, NÃO envia) + FYI ao dono;
  - `ambiguo`     → ESCALA ao dono, retém os pendentes.
**Isolamento por concelho** é preservado: `resolver_pendentes` filtra os pendentes pelo
concelho (normalizado), logo o breaker de um concelho nunca afeta outro.

Os crons e as suas checks (slugs do Healthchecks.io)
----------------------------------------------------
    cron_varrimento → "varrimento"   (nacional 2×/semana: ingest → alertas → breaker)
    cron_dre        → "dre"          (diário: ingestão DRE → triagem/redação IA → envio)
    cron_dunning    → "dunning"      (diário: régua de renovação/cobrança)
    cron_suporte    → "suporte"      (15 min: apoio@ por IA)
    cron_backup     → "backup"       (noturno: pg_dump + retenção)

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria nenhum
cliente de rede/IA/IMAP/subprocess: compõe-os pelos *seams* live-gated de cada camada
(:func:`app.envio.obter_enviador`, :func:`app.ia.obter_cliente_ia`,
:func:`app.suporte.obter_leitor`/:func:`obter_escalador`,
:func:`app.regulatorio.dre_pipeline.obter_cliente_http`) — todos devolvem ``None`` sob
`config.CHECKAL_MODO_TESTE` — e injeta-os. Nos crons de escrita (`varrimento`), sem os
seams de I/O disponíveis (modo de teste), corre-se **só** o ingest e não se sonda a
página individual nem se envia nada. Nos testes, tudo é injetado — a rede nunca é
tocada. Cada cron recebe `cliente_hc` (o cliente HTTP dos pings) injetável, para os
testes observarem os pings sem tocar a rede.

Fronteira: cada passo que toca a BD corre sob a sua própria `db.get_session()`
(commit/rollback atómicos por passo), o que dá a semântica de retry desejada — se o
breaker falhar, os pendentes já persistidos ficam retidos para a corrida seguinte.

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import app.breaker as breaker
import app.config as config
import app.db as db
import app.models as models
from app.alertas_estado import CANAL_PENDENTE, gerar_alertas_estado
from app.backups import ResultadoBackup, correr_backup
from app.breaker import (
    Resolucao,
    avaliar_concelho,
    desambiguar,
    resolver_pendentes,
)
from app.dunning import PassoDunning, correr_dunning
from app.envio import obter_enviador
from app.ia import obter_cliente_ia
from app.observabilidade import com_healthcheck
from app.regulatorio.dre_pipeline import ResultadoDRE, correr_dre
from app.regulatorio.pipeline import correr_pipeline
from app.rnal import detalhe
from app.rnal.ingest import ResultadoIngest, executar_varrimento
from app.suporte import ResultadoSuporte, correr_suporte, obter_escalador, obter_leitor

__all__ = [
    "SLUG_VARRIMENTO",
    "SLUG_DRE",
    "SLUG_DUNNING",
    "SLUG_SUPORTE",
    "SLUG_BACKUP",
    "ResultadoBreaker",
    "ResultadoVarrimentoCron",
    "resolver_desaparecidos_pendentes",
    "cron_varrimento",
    "cron_dre",
    "cron_dunning",
    "cron_suporte",
    "cron_backup",
]

# Slugs das checks do Healthchecks.io (AUTOMACAO.md §6). Cada cron pinga a sua no fim;
# a ausência do ping dentro do período esperado é o que o Healthchecks converte em alerta.
SLUG_VARRIMENTO = "varrimento"
SLUG_DRE = "dre"
SLUG_DUNNING = "dunning"
SLUG_SUPORTE = "suporte"
SLUG_BACKUP = "backup"

_log = logging.getLogger(__name__)


def _norm_concelho(nome: Any) -> str:
    """Normaliza um nome de concelho (casefold + trim) — a chave de agrupamento.

    Espelha `app.rnal.diffing._norm_concelho` e `app.breaker._norm_concelho`: a chave de
    agrupamento dos pendentes tem de casar exatamente com o filtro de isolamento do
    `resolver_pendentes`, para o breaker de um concelho nunca ignorar (ou pisar) os seus.
    """
    return (nome or "").strip().casefold()


# ==========================================================================
#  Resultados de orquestração (para logs/testes; a BD é a fonte de verdade)
# ==========================================================================
@dataclass
class ResultadoBreaker:
    """Sumário de :func:`resolver_desaparecidos_pendentes` (agregado de concelhos).

    Atributos
    ---------
    concelhos:
        Concelhos que tinham pendentes e foram avaliados (por ordem de aparição).
    disparados:
        Quantos concelhos cruzaram `BREAKER_PCT_CONCELHO` (metadado de anomalia).
    enviados / suprimidos / retidos:
        Total de pendentes LIBERTADOS (ramo `real`), SUPRIMIDOS (ramo `api_partida`) e
        RETIDOS (ramo `ambiguo`) em todos os concelhos.
    escalados:
        Quantos concelhos geraram FYI/escalação ao dono.
    resolucoes:
        As :class:`app.breaker.Resolucao` por concelho (detalhe para auditoria/testes).
    """

    concelhos: list[str] = field(default_factory=list)
    disparados: int = 0
    enviados: int = 0
    suprimidos: int = 0
    retidos: int = 0
    escalados: int = 0
    resolucoes: list[Resolucao] = field(default_factory=list)


@dataclass
class ResultadoVarrimentoCron:
    """Sumário de uma corrida de :func:`cron_varrimento`.

    `ingest` é o :class:`app.rnal.ingest.ResultadoIngest` do varrimento; `alertas_estado`
    é o nº de alertas de estado criados pelo FDS 3 nesta corrida (enviados **e**
    pendentes); `breaker` é o :class:`ResultadoBreaker` (``None`` se o breaker não correu
    por falta dos seams de I/O — modo de teste sem injeção).
    """

    ingest: ResultadoIngest
    alertas_estado: int = 0
    breaker: ResultadoBreaker | None = None


# ==========================================================================
#  Seam live-gated do obter_detalhe (real em produção; None sob modo de teste)
# ==========================================================================
def _seam_obter_detalhe() -> Callable[..., Any] | None:
    """`app.rnal.detalhe.obter_detalhe` em produção, ou ``None`` (LIVE-GATED).

    O detalhe individual cria um `httpx.Client` real quando `cliente_http=None`, logo
    sob `config.CHECKAL_MODO_TESTE` devolve-se ``None`` (a sondagem não corre e nada
    toca a rede). Nos testes injeta-se um dublê — este seam nunca é o usado.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    return detalhe.obter_detalhe


# ==========================================================================
#  Breaker por concelho — o coração do wire (resolução da guarda de sequência)
# ==========================================================================
def _pendentes_por_concelho(session: Any) -> list[tuple[str, list[int]]]:
    """Agrupa os alertas `desaparecido` retidos por concelho (isolamento).

    Devolve `[(concelho_display, [nrs])]` por ordem de aparição do 1.º pendente de cada
    concelho — determinístico. A chave de agrupamento é o concelho normalizado
    (casefold+trim, como no diffing/breaker), mas guarda-se o valor tal-e-qual guardado
    em `registos` para a contagem da base e para a passagem a `resolver_pendentes`.
    """
    linhas = (
        session.query(models.Alerta, models.Registo)
        .join(models.Registo, models.Registo.nr_registo == models.Alerta.nr_registo)
        .filter(models.Alerta.canal == CANAL_PENDENTE)
        .filter(models.Alerta.enviado_em.is_(None))
        .order_by(models.Alerta.id)
        .all()
    )
    ordem: list[str] = []
    grupos: dict[str, dict[str, Any]] = {}
    for alerta, registo in linhas:
        chave = _norm_concelho(registo.concelho)
        grupo = grupos.get(chave)
        if grupo is None:
            grupo = {"concelho": registo.concelho, "nrs": []}
            grupos[chave] = grupo
            ordem.append(chave)
        grupo["nrs"].append(alerta.nr_registo)
    return [(grupos[k]["concelho"], grupos[k]["nrs"]) for k in ordem]


def _base_total_concelho(session: Any, concelho: str | None) -> int:
    """Nº de registos conhecidos do `concelho` (denominador do limiar do breaker).

    Conta por igualdade exata do valor guardado (a API `list_RNAL` ecoa o concelho de
    forma consistente, pelo que todos os registos do concelho partilham a string). Um
    `concelho` nulo/vazio devolve 0 → o breaker trata base 0 como conservador (dispara).
    """
    if not concelho:
        return 0
    return (
        session.query(models.Registo)
        .filter(models.Registo.concelho == concelho)
        .count()
    )


def resolver_desaparecidos_pendentes(
    session: Any,
    *,
    obter_detalhe: Callable[..., Any],
    enviar: Callable[..., Any],
    escalar: Callable[[str], Any] | None = None,
    limite_amostra: int = breaker.MAX_AMOSTRA,
) -> ResultadoBreaker:
    """Corre o breaker por concelho sobre todos os `desaparecido` retidos — a RESOLUÇÃO
    da 🚦 guarda de sequência.

    Para cada concelho com pendentes:
      1. `avaliar_concelho(concelho, nrs, base_total)` — computa o limiar (metadado de
         anomalia) e normaliza os nrs a amostrar;
      2. `desambiguar(concelho, dec.nrs, obter_detalhe)` — amostra as páginas individuais
         (corre SEMPRE que há pendentes: a guarda exige confirmação positiva antes de
         enviar, e um falso L1 único fica abaixo do limiar);
      3. `resolver_pendentes(session, concelho, veredicto, enviar, obter_detalhe, escalar)`
         — LIBERTA (real, mas SÓ os nrs que confirmam cancelado/suspenso na sua própria
         página individual — `obter_detalhe` é propagado para essa confirmação POR-NR),
         SUPRIME (api_partida) ou ESCALA (ambiguo), com isolamento por concelho.

    **Isolamento transacional POR CONCELHO:** cada concelho corre no seu próprio
    `SAVEPOINT` (`session.begin_nested`); uma exceção ao resolver um concelho reverte só
    esse e a corrida prossegue para os restantes — os já resolvidos não são desfeitos.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy **de quem chama** (o cron, sob `db.get_session`). Esta função
        não abre sessão nem faz commit — a transação é do chamador; abre um SAVEPOINT
        por concelho para os isolar.
    obter_detalhe:
        `obter_detalhe(nr) -> DetalheRegisto` **injetado** (dublê nos testes; em produção
        `app.rnal.detalhe.obter_detalhe`). Alimenta a amostra do breaker E a confirmação
        POR-NR do ramo `real` no `resolver_pendentes`.
    enviar:
        Enviador transacional **injetado** (dublê nos testes; em produção o de
        `app.envio.obter_enviador`).
    escalar:
        `escalar(mensagem)` **injetado** para FYI/escalação ao dono. Opcional.

    Devolve um :class:`ResultadoBreaker` agregado. Idempotente: um pendente libertado sai
    da fila (canal `email`), pelo que uma 2.ª corrida não o reenvia.
    """
    resultado = ResultadoBreaker()
    for concelho, nrs in _pendentes_por_concelho(session):
        # 🚦 ISOLAMENTO POR CONCELHO (FIX C): cada concelho corre no seu próprio SAVEPOINT.
        # Uma exceção ao resolver um concelho reverte SÓ esse (rollback ao savepoint) e a
        # corrida continua — nunca desfaz os concelhos já resolvidos nesta transação.
        try:
            with session.begin_nested():
                base_total = _base_total_concelho(session, concelho)
                decisao = avaliar_concelho(concelho, nrs, base_total)
                veredicto = desambiguar(
                    concelho, decisao.nrs, obter_detalhe=obter_detalhe, limite=limite_amostra
                )
                # obter_detalhe é propagado ao resolver para a confirmação POR-NR (FIX A).
                resolucao = resolver_pendentes(
                    session, concelho, veredicto,
                    enviar=enviar, obter_detalhe=obter_detalhe, escalar=escalar,
                )
                resultado.concelhos.append(concelho)
                resultado.disparados += 1 if decisao.disparar else 0
                resultado.enviados += resolucao.enviados
                resultado.suprimidos += resolucao.suprimidos
                resultado.retidos += resolucao.retidos
                resultado.escalados += 1 if resolucao.escalado else 0
                resultado.resolucoes.append(resolucao)
        except Exception:
            _log.exception(
                "breaker: falha ao resolver o concelho «%s» — revertido e isolado (continua)",
                concelho,
            )
            continue
    return resultado


# ==========================================================================
#  cron_varrimento — nacional 2×/semana: ingest → alertas_estado → breaker
# ==========================================================================
def cron_varrimento(
    concelhos,
    *,
    cliente: Any = None,
    obter_detalhe: Callable[..., Any] | None = None,
    enviar: Callable[..., Any] | None = None,
    escalar: Callable[[str], Any] | None = None,
    cliente_hc: Any | None = None,
    **fetch_kwargs: Any,
) -> ResultadoVarrimentoCron:
    """Cron do varrimento nacional: ingere, gera os alertas de estado e corre o breaker.

    Encadeia (cada passo na sua transação):
      1. :func:`app.rnal.ingest.executar_varrimento` — varre `concelhos` e persiste
         `eventos_registo` (o `cliente` é injetável; por omissão o módulo `app.rnal.client`);
      2. :func:`app.alertas_estado.gerar_alertas_estado` — FDS 3: `desaparecido` vira
         pendente retido; `alterado`/`reapareceu` são enviados. Só corre com `enviar`
         disponível (LIVE-GATED);
      3. :func:`resolver_desaparecidos_pendentes` — breaker por concelho. Só corre com
         `obter_detalhe` **e** `enviar` disponíveis (LIVE-GATED) — sob modo de teste sem
         injeção, corre-se **só** o ingest e nada é sondado nem enviado.

    Tudo sob :class:`com_healthcheck` (`"varrimento"`): fim sem exceção → ping de sucesso;
    exceção → ping `/fail` e propaga. `cliente_hc` é o cliente HTTP dos pings (injetável
    nos testes; ``None`` → composto em produção se houver ping key).
    """
    with com_healthcheck(SLUG_VARRIMENTO, cliente_http=cliente_hc):
        if cliente is None:
            from app.rnal import client as _client

            cliente = _client
        if enviar is None:
            enviar = obter_enviador()
        if obter_detalhe is None:
            obter_detalhe = _seam_obter_detalhe()
        if escalar is None:
            escalar = obter_escalador()

        # 1) varrimento + ingest (não precisa de seams de I/O de saída)
        ingest = executar_varrimento(concelhos, cliente=cliente, **fetch_kwargs)

        # 2) FDS 3: alertas de estado (precisa de enviar para os alterado/reapareceu)
        n_alertas = 0
        if enviar is not None:
            with db.get_session() as s:
                n_alertas = len(gerar_alertas_estado(s, enviar=enviar))

        # 3) breaker por concelho (precisa de sondar a página individual E de enviar)
        resultado_breaker: ResultadoBreaker | None = None
        if obter_detalhe is not None and enviar is not None:
            with db.get_session() as s:
                resultado_breaker = resolver_desaparecidos_pendentes(
                    s, obter_detalhe=obter_detalhe, enviar=enviar, escalar=escalar
                )

        return ResultadoVarrimentoCron(
            ingest=ingest, alertas_estado=n_alertas, breaker=resultado_breaker
        )


# ==========================================================================
#  cron_dre — diário: ingestão do DRE → triagem/redação IA → envio
# ==========================================================================
def cron_dre(
    *,
    cliente_http: Any | None = None,
    cliente_ia: Any | None = None,
    enviar: Callable[..., Any] | None = None,
    data: date | None = None,
    edicao_inicial: int | None = None,
    cliente_hc: Any | None = None,
) -> ResultadoDRE:
    """Cron regulatório: capta o DRE (Camada A) e corre o pipeline IA (Camada B).

    `correr_dre` e `correr_pipeline` partilham a **mesma** sessão para a passagem em
    memória do excerto do ato à IA (SPEC-DRE). `cliente_http`/`cliente_ia`/`enviar` são
    injetáveis; por omissão compõem-se pelos seams live-gated (``None`` sob modo de teste
    → a corrida não toca a rede e devolve um aviso). Tudo sob `com_healthcheck("dre")`.
    """
    with com_healthcheck(SLUG_DRE, cliente_http=cliente_hc):
        if cliente_ia is None:
            cliente_ia = obter_cliente_ia()
        if enviar is None:
            enviar = obter_enviador()

        with db.get_session() as s:
            res_dre = correr_dre(
                s, cliente_http=cliente_http, data=data, edicao_inicial=edicao_inicial
            )
            correr_pipeline(
                s, cliente_ia=cliente_ia, enviar=enviar, eventos=res_dre.eventos
            )
        return res_dre


# ==========================================================================
#  cron_dunning — diário: régua de renovação/cobrança
# ==========================================================================
def cron_dunning(
    *,
    agora: datetime | None = None,
    enviar: Callable[..., Any] | None = None,
    cliente_hc: Any | None = None,
) -> list[PassoDunning]:
    """Cron diário de dunning (AUTOMACAO §5), sob `com_healthcheck("dunning")`.

    `enviar` é injetável; por omissão o seam live-gated (``None`` sob modo de teste — os
    emails não saem, mas o D+21 ainda cancela). O relógio `agora` é injetável para tornar
    a sequência testável sem esperar dias.
    """
    with com_healthcheck(SLUG_DUNNING, cliente_http=cliente_hc):
        agora = agora or datetime.now(timezone.utc)
        if enviar is None:
            enviar = obter_enviador()
        return correr_dunning(agora, enviar=enviar)


# ==========================================================================
#  cron_suporte — 15 min: apoio@ por IA
# ==========================================================================
def cron_suporte(
    *,
    leitor: Any | None = None,
    cliente_ia: Any | None = None,
    enviar: Callable[..., Any] | None = None,
    escalar: Callable[..., Any] | None = None,
    cliente_hc: Any | None = None,
) -> ResultadoSuporte:
    """Cron de suporte de 1.ª linha (AUTOMACAO §5), sob `com_healthcheck("suporte")`.

    `leitor`/`cliente_ia`/`enviar`/`escalar` são injetáveis; por omissão compõem-se pelos
    seams live-gated (``None`` sob modo de teste ou sem credenciais). Sem `leitor`
    (caixa indisponível) o cron é um no-op seguro — mas pinga na mesma (o job correu).
    """
    with com_healthcheck(SLUG_SUPORTE, cliente_http=cliente_hc):
        if leitor is None:
            leitor = obter_leitor()
        if cliente_ia is None:
            cliente_ia = obter_cliente_ia()
        if enviar is None:
            enviar = obter_enviador()
        if escalar is None:
            escalar = obter_escalador()
        with db.get_session() as s:
            return correr_suporte(
                s, leitor=leitor, cliente_ia=cliente_ia, enviar=enviar, escalar=escalar
            )


# ==========================================================================
#  cron_backup — noturno: pg_dump + retenção
# ==========================================================================
def cron_backup(*, cliente_hc: Any | None = None, **kwargs: Any) -> ResultadoBackup:
    """Cron de backup noturno (AUTOMACAO §6), sob `com_healthcheck("backup")`.

    Delega em :func:`app.backups.correr_backup` (todos os seams de subprocess/FS são
    dele, injetáveis). Uma falha (incl. o live-gate :class:`app.backups.BackupInativo`
    sem DSN) pinga `/fail` e **propaga** — o dead-man switch avisa o dono.
    """
    with com_healthcheck(SLUG_BACKUP, cliente_http=cliente_hc):
        return correr_backup(**kwargs)
