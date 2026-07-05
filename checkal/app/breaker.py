"""Circuit breaker por concelho — o guardião do falso «cancelado» (FDS 5).

Este é o **módulo-chave** do FDS 5 (SPEC-FDS5.md §breaker): resolve a 🚦 *guarda de
sequência* que o FDS 1/FDS 3 deixaram em aberto (`app/rnal/LIMITACOES-CONHECIDAS.md`).
Um alerta de estado `desaparecido` («o teu registo deixou de constar») nasce no
diffing nacional (FDS 1) e é PERSISTIDO mas RETIDO pelo FDS 3
(`alertas.canal == 'pendente_desambiguacao'`, `enviado_em IS NULL`) — **nunca** é
enviado às cegas. Cabe a este módulo confirmar, junto da página individual do RNAL,
se o desaparecimento é **real** (limpeza/cancelamento no concelho) ou uma **API
partida** (resposta nacional truncada / concelho em falha), e só então libertar,
suprimir ou escalar. *Um falso «o teu registo foi cancelado» é o pior erro do
produto* — por isso a régua é conservadora: **só se envia com confirmação positiva**.

Três funções, três responsabilidades disjuntas:

    avaliar_concelho(concelho, desaparecidos, base_total) -> Decisao   [pura]
        Porta do limiar: se a fração de desaparecidos ultrapassar
        `config.BREAKER_PCT_CONCELHO` (baseline ~0,2%/semana), há um salto anómalo
        e dispara-se a desambiguação. Senão, segue tudo normal.

    desambiguar(concelho, nrs_amostra, *, obter_detalhe) -> Veredicto  [pura]
        Amostra até `MAX_AMOSTRA` páginas individuais via `obter_detalhe` (o
        `app.rnal.detalhe.obter_detalhe` do FDS 3, INJETADO). Vota por estado:
          · `cancelado`/`suspenso`  → confirmação positiva de fim de atividade → REAL
          · `nao_encontrado`/`ativo`/erro → ausência sem prova OU AL vivo → API_PARTIDA
          · `indeterminado`/outro   → sinal neutro → AMBIGUO
        Um veredicto decisivo exige predominância (`PREDOMINANCIA_MINIMA`); mistura
        inconclusiva → `ambiguo`.

    resolver_pendentes(session, concelho, veredicto, *, enviar, obter_detalhe=None, escalar=None)
        O único ponto que toca a BD. Age sobre os pendentes DESTE concelho (e só
        deste — isolamento). A decisão de `desambiguar` é do circuit-breaker (a API
        está de pé?); a decisão de ENVIAR é tomada aqui, **nr a nr**:
          · REAL        → CONFIRMA CADA nr na sua própria página individual
                          (`obter_detalhe(nr)`, INJETADO) e só liberta o que confirmar:
                            – página `cancelado`/`suspenso` → LIBERTA (envia, data
                              `enviado_em`, canal email) — a copy «confirmámos na página
                              individual» passa a ser VERDADE para esse nr;
                            – página `ativo` (AL VIVO, ex.: L1) → NÃO envia; SUPRIME e
                              reabre o evento (`processado=false`) para retry;
                            – `nao_encontrado`/`indeterminado`/erro/sem seam → NÃO envia
                              (sem prova positiva); mantém retido. FYI ao dono da divergência.
          · API_PARTIDA → SUPRIME (reabre o evento `processado=false` p/ retry, NÃO
                          envia) + FYI ao dono
          · AMBIGUO     → ESCALA ao dono, NÃO envia, mantém os pendentes retidos

Disciplina inviolável (SPEC-FDS5 §disciplina):
  - **MODO DE TESTE, LIVE-GATED.** `obter_detalhe`, `enviar` e `escalar` são
    **injetados**; este módulo nunca cria clientes HTTP/IMAP nem corre subprocess —
    logo os testes nunca tocam a rede. `avaliar_concelho`/`desambiguar` são puras.
  - **🚦 Ordem sagrada + confirmação POR-NR.** O alerta `desaparecido` só é enviado
    DEPOIS de a página individual DAQUELE nr dizer positivamente `cancelado`/`suspenso`.
    A maioria da amostra (`desambiguar`) decide apenas se a API está de pé (evento real
    vs API partida vs ambíguo); NUNCA basta para libertar um nr. Absência
    (`nao_encontrado`) ou AL vivo (`ativo`) NÃO são confirmação: suprime-se/retém-se e
    reavalia-se, nr a nr.
  - **Isolamento por concelho.** A resolução filtra os pendentes pelo `concelho`
    (comparado normalizado, casefold+trim, como no diffing) — o breaker de um
    concelho nunca afeta os pendentes de outro.
  - **Idempotência.** Um pendente libertado (`enviado_em` datado, canal `email`) sai
    da fila de pendentes: correr `resolver_pendentes` outra vez não o reenvia.

Fronteira: `resolver_pendentes` recebe a `session` de quem chama (o cron do wire, sob
`db.get_session`) e **não** faz commit — a transação é do orquestrador; se `enviar`
levantar, o rollback do chamador desfaz o efeito e o pendente permanece para retry.
"""
from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any

import app.config as config
import app.models as models
from app.alertas_estado import (
    CANAL_EMAIL,
    CANAL_PENDENTE,
    ORIGEM_EVENTO_REGISTO,
)
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_CANCELADO,
    ESTADO_NAO_ENCONTRADO,
    ESTADO_SUSPENSO,
)

__all__ = [
    "VEREDICTO_REAL",
    "VEREDICTO_API_PARTIDA",
    "VEREDICTO_AMBIGUO",
    "MIN_AMOSTRA",
    "MAX_AMOSTRA",
    "PREDOMINANCIA_MINIMA",
    "Decisao",
    "Veredicto",
    "Resolucao",
    "avaliar_concelho",
    "desambiguar",
    "resolver_pendentes",
]

# --- Veredictos da desambiguação (ver módulo `detalhe` para os estados de origem) ---
VEREDICTO_REAL = "real"            # cancelamento/suspensão confirmado → liberta os alertas
VEREDICTO_API_PARTIDA = "api_partida"  # ausência sem prova / AL vivo → suprime + retry
VEREDICTO_AMBIGUO = "ambiguo"      # amostra inconclusiva → escala ao dono, não envia

# Amostragem da página individual (SPEC-FDS5 §breaker: «amostra 10–20 páginas»).
MIN_AMOSTRA = 10   # informativo: o wire deve tentar reunir ≥10 nrs quando existirem
MAX_AMOSTRA = 20   # teto rígido de páginas individuais amostradas por concelho

# Fração mínima de votos de um bucket para um veredicto DECISIVO. Acima de 0,5 garante
# que, no máximo, um dos buckets (real|api_partida) pode predominar — sem empates.
PREDOMINANCIA_MINIMA = 0.6

# Estados da página individual agrupados por voto (ver `app.rnal.detalhe.ESTADOS`).
#   - REAL: confirmação POSITIVA de fim de atividade.
#   - API_PARTIDA: `nao_encontrado` (ausência sem prova — conservador: não basta para
#     enviar) e `ativo` (o AL está VIVO — o desaparecimento nacional foi espúrio); a
#     ambos junta-se o ERRO de transporte. Ação comum: NÃO enviar.
#   - Tudo o resto (`indeterminado`, desconhecido) é sinal neutro → conta p/ AMBIGUO.
_ESTADOS_REAL = frozenset({ESTADO_CANCELADO, ESTADO_SUSPENSO})
_ESTADOS_API_PARTIDA = frozenset({ESTADO_NAO_ENCONTRADO, ESTADO_ATIVO})

# Disclaimer factual repetido em cada alerta (informação, não aconselhamento).
_DISCLAIMER = (
    "Isto é informação de monitorização a partir de dados públicos do RNAL; "
    "não constitui aconselhamento jurídico."
)


# ==========================================================================
#  Estruturas de resultado (imutáveis)
# ==========================================================================
@dataclass(frozen=True)
class Decisao:
    """Resultado de :func:`avaliar_concelho` — se o concelho precisa de desambiguação.

    `pct` é a fração `n_desaparecidos / base_total` (0.0 se `base_total <= 0` e não há
    desaparecidos; 1.0 se há desaparecidos mas base desconhecida). `disparar` é True
    quando `pct` ultrapassa `config.BREAKER_PCT_CONCELHO`. `nrs` são os nº de registo
    desaparecidos (ordenados), prontos a alimentar :func:`desambiguar`.
    """

    concelho: str
    n_desaparecidos: int
    base_total: int
    pct: float
    disparar: bool
    nrs: tuple[int, ...]


@dataclass(frozen=True)
class Veredicto:
    """Resultado de :func:`desambiguar` — o que a amostra das páginas individuais diz.

    `resultado` é um de :data:`VEREDICTO_REAL`/:data:`VEREDICTO_API_PARTIDA`/
    :data:`VEREDICTO_AMBIGUO`. Os `votos_*` guardam a contagem por bucket (para a
    mensagem de FYI/escalação e para os testes).
    """

    concelho: str
    resultado: str
    n_amostra: int
    votos_real: int
    votos_api_partida: int
    votos_ambiguo: int


@dataclass(frozen=True)
class Resolucao:
    """Sumário de :func:`resolver_pendentes` (para logs/testes; não é a BD)."""

    concelho: str
    veredicto: str
    enviados: int           # alertas libertados/enviados (ramo real)
    suprimidos: int         # pendentes suprimidos (ramo api_partida)
    retidos: int            # pendentes deixados retidos (ramo ambiguo / sem email)
    eventos_reabertos: int  # eventos postos processado=false p/ retry (ramo api_partida)
    escalado: bool          # houve FYI/escalação ao dono


# ==========================================================================
#  Normalização de concelho (casefold + trim) — igual à porta do diffing
# ==========================================================================
def _norm_concelho(nome: Any) -> str:
    """Normaliza um nome de concelho (casefold + trim) para a comparação de isolamento.

    Espelha `app.rnal.diffing._norm_concelho`: um mismatch por caixa/espaços nunca pode
    fazer o breaker de um concelho ignorar (ou pisar) os pendentes do seu próprio
    concelho.
    """
    return (nome or "").strip().casefold()


# ==========================================================================
#  avaliar_concelho — porta do limiar (pura)
# ==========================================================================
def _contar(desaparecidos: Collection[int] | int) -> tuple[int, tuple[int, ...]]:
    """`(n, nrs)` a partir de uma coleção de nrs OU de uma contagem inteira.

    Uma contagem inteira (o wire pode passar só o número) devolve `nrs = ()` — nesse
    caso não há nrs concretos para amostrar. Uma coleção devolve os nrs deduplicados e
    ordenados (amostragem determinística).
    """
    if isinstance(desaparecidos, bool):  # bool é int; recusa-se explicitamente
        raise TypeError("desaparecidos não pode ser bool")
    if isinstance(desaparecidos, int):
        return max(desaparecidos, 0), ()
    nrs = tuple(sorted({int(x) for x in desaparecidos}))
    return len(nrs), nrs


def avaliar_concelho(
    concelho: str,
    desaparecidos: Collection[int] | int,
    base_total: int,
) -> Decisao:
    """Decide se o salto de desaparecidos num concelho justifica desambiguação.

    `desaparecidos` é a coleção de nº de registo marcados `desaparecido` neste
    varrimento nesse concelho (ou a sua contagem). `base_total` é a base conhecida do
    concelho (nº de registos). Dispara quando `n/base_total > BREAKER_PCT_CONCELHO`.

    Casos-limite conservadores: `base_total <= 0` com desaparecidos → `pct = 1.0` e
    dispara (base desconhecida + algo desapareceu = melhor confirmar); sem
    desaparecidos → nunca dispara.
    """
    n, nrs = _contar(desaparecidos)
    if base_total > 0:
        pct = n / base_total
    else:
        pct = 1.0 if n > 0 else 0.0
    return Decisao(
        concelho=concelho,
        n_desaparecidos=n,
        base_total=base_total,
        pct=pct,
        disparar=pct > config.BREAKER_PCT_CONCELHO,
        nrs=nrs,
    )


# ==========================================================================
#  desambiguar — amostragem das páginas individuais (pura, obter_detalhe injetado)
# ==========================================================================
def _voto(estado: Any) -> str:
    """Classifica o `estado` de uma página individual num bucket de veredicto."""
    if estado in _ESTADOS_REAL:
        return VEREDICTO_REAL
    if estado in _ESTADOS_API_PARTIDA:
        return VEREDICTO_API_PARTIDA
    return VEREDICTO_AMBIGUO  # indeterminado / desconhecido → neutro


def _classificar(n: int, r: int, a: int) -> str:
    """Do balanço de votos ao veredicto (predominância `PREDOMINANCIA_MINIMA`).

    Como `PREDOMINANCIA_MINIMA > 0.5`, no máximo um de `r`/`a` pode predominar — não há
    empate possível. Sem predominância clara (incl. muitos `indeterminado`) → ambíguo.
    """
    if n == 0:
        return VEREDICTO_AMBIGUO
    if r / n >= PREDOMINANCIA_MINIMA:
        return VEREDICTO_REAL
    if a / n >= PREDOMINANCIA_MINIMA:
        return VEREDICTO_API_PARTIDA
    return VEREDICTO_AMBIGUO


def desambiguar(
    concelho: str,
    nrs_amostra: Collection[int],
    *,
    obter_detalhe: Callable[..., Any],
    limite: int = MAX_AMOSTRA,
) -> Veredicto:
    """Amostra páginas individuais e devolve o veredicto do concelho.

    Chama `obter_detalhe(nr)` (injetado — em produção, `app.rnal.detalhe.obter_detalhe`)
    para até `limite` nº de registo (deduplicados e ordenados, determinístico). Cada
    resposta vota pelo seu `estado`:

      - `cancelado`/`suspenso` → REAL (confirmação positiva de fim de atividade);
      - `nao_encontrado`/`ativo` → API_PARTIDA (ausência sem prova ou AL vivo);
      - qualquer **exceção** de `obter_detalhe` (falha de transporte) → API_PARTIDA
        («erro predominante → api_partida»): uma amostra que rebenta é ruído da API,
        não prova de cancelamento;
      - `indeterminado`/outro → conta para AMBIGUO.

    O veredicto final exige predominância (:func:`_classificar`). Nunca levanta: uma
    falha por página é absorvida como voto `api_partida`, para a amostragem completar.
    """
    nrs = sorted({int(x) for x in nrs_amostra})[:limite]

    votos = {VEREDICTO_REAL: 0, VEREDICTO_API_PARTIDA: 0, VEREDICTO_AMBIGUO: 0}
    for nr in nrs:
        try:
            detalhe = obter_detalhe(nr)
        except Exception:
            votos[VEREDICTO_API_PARTIDA] += 1  # erro de transporte → API partida
            continue
        votos[_voto(getattr(detalhe, "estado", None))] += 1

    n = len(nrs)
    resultado = _classificar(n, votos[VEREDICTO_REAL], votos[VEREDICTO_API_PARTIDA])
    return Veredicto(
        concelho=concelho,
        resultado=resultado,
        n_amostra=n,
        votos_real=votos[VEREDICTO_REAL],
        votos_api_partida=votos[VEREDICTO_API_PARTIDA],
        votos_ambiguo=votos[VEREDICTO_AMBIGUO],
    )


# ==========================================================================
#  Composição do alerta de cancelamento CONFIRMADO (ramo real)
# ==========================================================================
def _compor_confirmado(nome: str, nr: int) -> tuple[str, str]:
    """`(assunto, texto)` do alerta a libertar quando o cancelamento é CONFIRMADO.

    Ao contrário do alerta retido do FDS 3 (que, sob G4, só dizia «a reconfirmar»),
    aqui a página individual JÁ confirmou o fim de atividade — logo a copy pode afirmar
    o cancelamento/suspensão, factualmente e em PT-PT, sem sobre-especificar qual.
    """
    assunto = f"Confirmado: o registo RNAL do teu AL (nº {nr}) deixou de estar ativo"
    texto = (
        f"Confirmámos na página individual do RNAL que o registo do teu Alojamento Local "
        f"«{nome}» (nº {nr}) deixou de estar ativo (cancelamento ou suspensão). "
        "Verifica a tua situação junto do RNAL / da tua câmara e regulariza-a se for caso disso."
    )
    return assunto, texto


def _html(texto: str) -> str:
    """Envolve o texto factual num corpo HTML mínimo, com o disclaimer no rodapé."""
    return (
        f"<p>{escape(texto)}</p>"
        f'<p style="font-size:.85em;color:#6b7280">{escape(_DISCLAIMER)}</p>'
    )


# ==========================================================================
#  Escalação/FYI ao dono (seam injetado; opcional)
# ==========================================================================
def _escalar_dono(
    escalar: Callable[[str], Any] | None,
    concelho: str,
    resultado: str,
    veredicto: Veredicto | str,
    *,
    suprimidos: int,
    retidos: int,
    eventos_reabertos: int,
) -> bool:
    """Compõe e envia a mensagem ao dono (se `escalar` foi injetado). Devolve se enviou.

    `api_partida` → FYI (informativo: suprimi X e reabri Y, nada foi enviado).
    `ambiguo` → ATENÇÃO (decisão manual necessária). Sem `escalar` (None) → no-op.
    """
    if escalar is None:
        return False
    r = getattr(veredicto, "votos_real", 0)
    a = getattr(veredicto, "votos_api_partida", 0)
    m = getattr(veredicto, "votos_ambiguo", 0)
    if resultado == VEREDICTO_API_PARTIDA:
        msg = (
            f"[CheckAL] FYI — breaker: API partida em «{concelho}». "
            f"Suprimi {suprimidos} alerta(s) 'desaparecido' e reabri {eventos_reabertos} "
            f"evento(s) para retry. Nada foi enviado aos clientes. "
            f"(amostra: real={r}, api={a}, indef={m})"
        )
    else:  # VEREDICTO_AMBIGUO
        msg = (
            f"[CheckAL] ATENÇÃO — breaker AMBÍGUO em «{concelho}»: {retidos} alerta(s) "
            f"'desaparecido' retidos, amostra inconclusiva (real={r}, api={a}, indef={m}). "
            "Decisão manual necessária; nada foi enviado."
        )
    escalar(msg)
    return True


def _escalar_real_divergente(
    escalar: Callable[[str], Any] | None,
    concelho: str,
    *,
    enviados: int,
    suprimidos: int,
    retidos: int,
    eventos_reabertos: int,
) -> bool:
    """FYI ao dono quando a confirmação POR-NR do ramo `real` DIVERGIU da amostra.

    A amostra do concelho deu `real`, mas ao reconfirmar cada nr na sua página
    individual alguns não confirmaram: estavam VIVOS (`ativo` → suprimidos/reabertos) ou
    sem prova positiva (`nao_encontrado`/`indeterminado`/erro → retidos). Só saíram os
    confirmados nr a nr. `None` (sem `escalar`) → no-op.
    """
    if escalar is None:
        return False
    escalar(
        f"[CheckAL] FYI — breaker: em «{concelho}» o cancelamento foi confirmado POR-NR "
        f"para {enviados} registo(s), mas {suprimidos} estava(m) VIVO(s) "
        f"(suprimido/reaberto) e {retidos} não confirmaram na página individual (retido). "
        f"Só saíram os confirmados; reabri {eventos_reabertos} evento(s) para retry."
    )
    return True


# ==========================================================================
#  resolver_pendentes — o único ponto que toca a BD
# ==========================================================================
def _estado_da_pagina(nr: int, obter_detalhe: Callable[..., Any] | None) -> str | None:
    """Estado da página individual DESTE nr (confirmação POR-NR), ou ``None``.

    Direção segura: sem `obter_detalhe` (seam ausente) ou perante uma exceção de
    transporte, devolve ``None`` — o chamador trata ``None`` como «não confirmado» e
    NÃO envia. Nunca levanta: uma falha de rede não pode virar um envio.
    """
    if obter_detalhe is None:
        return None
    try:
        detalhe = obter_detalhe(nr)
    except Exception:
        return None  # erro de transporte → não se confirma → não envia
    return getattr(detalhe, "estado", None)


def _reabrir_evento(session: Any, alerta: models.Alerta, reabertos: set[int]) -> None:
    """Reabre (`processado=False`) o evento de origem de `alerta` p/ retry; regista o id."""
    if alerta.origem == ORIGEM_EVENTO_REGISTO and alerta.origem_id is not None:
        ev = session.get(models.EventoRegisto, alerta.origem_id)
        if ev is not None and ev.processado:
            ev.processado = False
            reabertos.add(ev.id)
def _pendentes_do_concelho(
    session: Any, concelho: str
) -> list[tuple[models.Alerta, models.Registo]]:
    """Alertas `desaparecido` retidos DESTE concelho (isolamento), ordenados por id.

    O pendente é o par durável (`canal == CANAL_PENDENTE`, `enviado_em IS NULL`) do
    FDS 3. Junta-se a `registos` (por `nr_registo`) para obter o concelho e o nome; o
    filtro por concelho é feito em Python com :func:`_norm_concelho` (robusto a
    caixa/acentos, ao contrário de um `lower()` de SQL).
    """
    linhas = (
        session.query(models.Alerta, models.Registo)
        .join(models.Registo, models.Registo.nr_registo == models.Alerta.nr_registo)
        .filter(models.Alerta.canal == CANAL_PENDENTE)
        .filter(models.Alerta.enviado_em.is_(None))
        .order_by(models.Alerta.id)
        .all()
    )
    alvo = _norm_concelho(concelho)
    return [(a, r) for (a, r) in linhas if _norm_concelho(r.concelho) == alvo]


def resolver_pendentes(
    session: Any,
    concelho: str,
    veredicto: Veredicto | str,
    *,
    enviar: Callable[..., Any],
    obter_detalhe: Callable[..., Any] | None = None,
    escalar: Callable[[str], Any] | None = None,
) -> Resolucao:
    """Aplica o `veredicto` aos alertas `desaparecido` retidos DESTE concelho.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy **de quem chama** (o cron do wire). Esta função não abre
        sessão nem faz commit — a transação é do chamador.
    concelho:
        Concelho a resolver (isolamento: só os seus pendentes são tocados).
    veredicto:
        :class:`Veredicto` (de :func:`desambiguar`) ou a string do resultado.
    enviar:
        `enviar(*, para, assunto, html, anexos, texto, idempotency_key) -> ...`
        **injetado** (dublê nos testes; em produção o de `app.envio.obter_enviador`).
    obter_detalhe:
        `obter_detalhe(nr) -> DetalheRegisto` **injetado** (o mesmo de :func:`desambiguar`;
        em produção `app.rnal.detalhe.obter_detalhe`). Usado no ramo `real` para
        RECONFIRMAR CADA nr na sua própria página individual antes de libertar. `None`
        (não injetado) → no ramo `real` nada se confirma → nada sai (direção segura).
    escalar:
        `escalar(mensagem)` **injetado** para FYI/escalação ao dono (Telegram/email no
        wire). Opcional: `None` → escalação é no-op.

    Ramos (SPEC-FDS5 §breaker) — a decisão de ENVIAR é sempre POR-NR:
      - **real** → confirma cada pendente na sua página individual (`obter_detalhe(nr)`):
          · `cancelado`/`suspenso` → compõe o alerta CONFIRMADO, ENVIA (se houver email),
            data `enviado_em`, canal `email` (sai da fila → idempotente); sem email fica
            retido (o dono resolve à mão);
          · `ativo` (AL VIVO) → NÃO envia; SUPRIME e reabre o evento (`processado=false`);
          · `nao_encontrado`/`indeterminado`/erro/sem seam → NÃO envia; mantém retido.
        Se algum nr divergiu (suprimido/retido sem confirmação), FYI ao dono.
      - **api_partida** → SUPRIME cada pendente (remove-o) e reabre o evento de origem
        (`processado=false`) para retry; **não** envia; FYI ao dono.
      - **ambiguo** (ou resultado desconhecido → conservador) → mantém os pendentes
        retidos, **não** envia, ESCALA ao dono.
    """
    resultado = veredicto.resultado if isinstance(veredicto, Veredicto) else str(veredicto)
    agora = datetime.now(timezone.utc)
    pendentes = _pendentes_do_concelho(session, concelho)

    enviados = suprimidos = retidos = 0
    nao_confirmados = 0  # divergências do ramo real (ativo suprimido + sem prova retido)
    eventos_reabertos: set[int] = set()

    if resultado == VEREDICTO_REAL:
        for alerta, registo in pendentes:
            # 🚦 confirmação POR-NR: só a página DESTE nr autoriza o envio.
            estado_nr = _estado_da_pagina(alerta.nr_registo, obter_detalhe)
            if estado_nr in _ESTADOS_REAL:
                cliente = (
                    session.get(models.Cliente, alerta.cliente_id)
                    if alerta.cliente_id is not None
                    else None
                )
                email = cliente.email if cliente is not None else None
                if not email:
                    retidos += 1  # confirmado mas sem email → dono resolve à mão
                    continue
                nome = registo.nome_alojamento or f"nº {alerta.nr_registo}"
                assunto, texto = _compor_confirmado(nome, alerta.nr_registo)
                enviar(
                    para=email,
                    assunto=assunto,
                    html=_html(texto),
                    anexos=(),
                    texto=texto,
                    idempotency_key=f"desaparecido-confirmado-{alerta.id}",
                )
                alerta.conteudo = texto          # regista o que foi de facto enviado
                alerta.canal = CANAL_EMAIL       # deixa de ser pendente (idempotência)
                alerta.enviado_em = agora
                enviados += 1
            elif estado_nr == ESTADO_ATIVO:
                # AL VIVO (ex.: mudança de concelho, L1) → NÃO envia; suprime + reabre.
                _reabrir_evento(session, alerta, eventos_reabertos)
                session.delete(alerta)
                suprimidos += 1
                nao_confirmados += 1
            else:
                # nao_encontrado / indeterminado / erro / sem seam → sem prova → retém.
                retidos += 1
                nao_confirmados += 1

    elif resultado == VEREDICTO_API_PARTIDA:
        for alerta, _registo in pendentes:
            # reabre o evento de origem para retry (SPEC: «mantém processado=false»)
            _reabrir_evento(session, alerta, eventos_reabertos)
            session.delete(alerta)  # suprime o pendente (retry recria-o limpo)
            suprimidos += 1

    else:  # VEREDICTO_AMBIGUO (ou desconhecido) → retém tudo, não envia
        retidos = len(pendentes)

    escalado = False
    if resultado in (VEREDICTO_API_PARTIDA, VEREDICTO_AMBIGUO) and pendentes:
        escalado = _escalar_dono(
            escalar, concelho, resultado, veredicto,
            suprimidos=suprimidos, retidos=retidos,
            eventos_reabertos=len(eventos_reabertos),
        )
    elif resultado == VEREDICTO_REAL and nao_confirmados:
        escalado = _escalar_real_divergente(
            escalar, concelho,
            enviados=enviados, suprimidos=suprimidos, retidos=retidos,
            eventos_reabertos=len(eventos_reabertos),
        )

    session.flush()  # materializa envios/deletes/reaberturas (sem commit — é do chamador)
    return Resolucao(
        concelho=concelho,
        veredicto=resultado,
        enviados=enviados,
        suprimidos=suprimidos,
        retidos=retidos,
        eventos_reabertos=len(eventos_reabertos),
        escalado=escalado,
    )
