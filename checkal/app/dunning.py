"""Régua de renovação/cobrança do CheckAL — dunning (FDS 5, SPEC-FDS5.md §dunning).

Cron **diário** que percorre os assinantes e emite a cadência de renovação e de
cobrança falhada descrita em AUTOMACAO.md §137, movendo a máquina de estados de
`clientes` (`ativo` → `em_dunning` → `cancelado`):

    D-30   email "a tua proteção renova a {data}" + resumo do valor entregue
           ("no último ano fizemos X varrimentos e enviámos Y alertas" — reduz churn)
    D-7    segundo aviso de que a cobrança está iminente
    D0     a **Stripe** cobra (Smart Retries) — NÃO é um passo nosso; nada sai daqui
    D+3    email de falha (só se a cobrança falhou → `estado == em_dunning`)
    D+7    segundo email de falha (idem)
    D+21   downgrade para `estado = cancelado` + email final ("o teu AL deixou de
           estar monitorizado" — o melhor win-back possível)

**Pré-pago (Trienal/Portfólio trienal, >12 meses):** sem dunning; só o aviso **D-30
do fim** (não há auto-cobrança para falhar). Ver `_prepago`.

Divisão de responsabilidades da máquina de estados
---------------------------------------------------
A transição `ativo → em_dunning` **não** é feita aqui: é o webhook
`invoice.payment_failed` (FDS 2, `app.fulfillment.registar_falha_pagamento`) que a
assenta quando a Stripe reporta a falha da cobrança; a renovação bem-sucedida
(`invoice.paid`) repõe `ativo`. Este módulo **reage** a esse estado — só emite os
emails de falha (D+3/D+7) a quem está `em_dunning` — e é o dono da transição final
`em_dunning → cancelado` no D+21. Um cliente que pagou (fica `ativo`) nunca recebe
emails de falha nem é cancelado.

Data de renovação sem coluna dedicada
-------------------------------------
O esquema de `clientes` (fechado no FDS 2) não guarda a data de renovação, e o FDS 5
é **aditivo** — não a altera. A data deriva de `criado_em + PLANOS[plano].meses`
(a subscrição Stripe arranca no checkout, logo o aniversário coincide na prática com
a cobrança). :func:`_boundary_corrente` escolhe a fronteira de renovação cujo ciclo
(janela [-30, +21] dias, e para trás até à fronteira anterior) contém `hoje`, o que
generaliza para renovações de anos seguintes e tolera catch-up (cron em baixo).

Idempotência
------------
Cada passo executado grava **um** `Alerta` que é, ao mesmo tempo, o email enviado e o
marcador durável do passo. A `origem` compõe passo+ciclo — ``f"dunning:{passo}:{data
de renovação}"`` — pelo que a chave (`cliente_id`, `origem`) identifica exatamente um
passo de um ciclo. Antes de executar consulta-se esse marcador; existir ⇒ no-op. O
`idempotency_key` passado ao enviador (a mesma `origem`) deduplica também no lado da
Resend, cobrindo o intervalo entre o envio e o commit.

Disciplina inviolável (SPEC-FDS5)
---------------------------------
  - **MODO DE TESTE, LIVE-GATED.** O `enviar` é **injetado** por quem chama (dublê nos
    testes; em produção o *callable* de `app.envio.obter_enviador`, que devolve ``None``
    sob modo de teste). Este módulo nunca cria clientes HTTP — os testes nunca tocam a
    rede. O relógio (`agora`) é injetado, para a sequência ser testável sem esperar dias.
  - **Isolamento por cliente.** Cada assinante é processado na sua própria transação,
    dentro de um `try/except`: uma falha de envio de um cliente é revertida e registada,
    e a corrida continua para os restantes (incl. os cancelamentos D+21). No fim, se
    algum falhou, levanta-se :class:`DunningIncompleto` para o `com_healthcheck` do cron
    pingar `/fail` — os passos que correram ficam, na mesma, feitos.
  - **Um passo por cliente por dia, no máximo.** As janelas são disjuntas por sinal e
    magnitude de `dias`, pelo que nunca saem dois emails ao mesmo cliente no mesmo dia.
"""
from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import app.config as config
import app.db as db
import app.models as models
from app.alertas_estado import ORIGEM_EVENTO_REGISTO
from app.emails import dunning as _emails_dunning
from app.fulfillment import ESTADO_ATIVO, ESTADO_CANCELADO, ESTADO_DUNNING, PLANO_PADRAO

__all__ = [
    "ORIGEM_DUNNING",
    "PASSO_D30",
    "PASSO_D7",
    "PASSO_D3",
    "PASSO_D7_POS",
    "PASSO_D21",
    "PassoDunning",
    "DunningIncompleto",
    "correr_dunning",
]

_log = logging.getLogger(__name__)


class DunningIncompleto(RuntimeError):
    """Sinaliza que ≥1 cliente falhou o processamento nesta passagem do dunning.

    Levantada no FIM de :func:`correr_dunning` — DEPOIS de TODOS os clientes serem
    tentados, com isolamento por cliente (uma falha de um não desfaz nem bloqueia os
    restantes). Propaga-se pelo `com_healthcheck` do `cron_dunning` para pingar `/fail`
    (dead-man switch avisa o dono), mas os passos que correram já foram COMMITADOS.
    Carrega `executados` (os passos que de facto correram) e `n_falhas`.
    """

    def __init__(self, executados: list[PassoDunning], n_falhas: int) -> None:
        self.executados = executados
        self.n_falhas = n_falhas
        super().__init__(f"dunning: {n_falhas} cliente(s) falharam esta passagem")

# Prefixo da `Alerta.origem` de todas as comunicações de dunning (auditável por
# `origem LIKE 'dunning:%'`). O marcador completo é `f"{ORIGEM_DUNNING}:{passo}:{ciclo}"`.
ORIGEM_DUNNING = "dunning"

# Rótulos dos passos (também os valores gravados no marcador). D-7 (pré) e D+7 (pós)
# são passos distintos com nomes distintos para não colidirem no marcador.
PASSO_D30 = "D-30"      # aviso de renovação (pré-cobrança)
PASSO_D7 = "D-7"        # segundo aviso (pré-cobrança)
PASSO_D3 = "D+3"        # 1.º email de falha (pós-cobrança falhada)
PASSO_D7_POS = "D+7"    # 2.º email de falha (pós-cobrança falhada)
PASSO_D21 = "D+21"      # downgrade cancelado + email final

# Assinatura do enviador injetado (só para leitura; não impõe verificação).
Enviar = Callable[..., Any]


@dataclass(frozen=True)
class PassoDunning:
    """Um passo de dunning executado numa passagem do cron (auditoria / testes).

    `enviado` diz se o email saiu nesta passagem (falso só se o cliente não tiver
    email — o passo executa na mesma para não repetir); `cancelou` marca a transição
    `em_dunning → cancelado` do D+21.
    """

    cliente_id: int
    passo: str
    enviado: bool
    cancelou: bool


# ==========================================================================
#  Aritmética de datas (aniversário de renovação)
# ==========================================================================
def _add_meses(d: date, meses: int) -> date:
    """Soma `meses` meses de calendário a `d` (aceita negativos), fixando o dia.

    O dia é limitado ao último do mês destino (ex.: 31/jan + 1 mês → 28/fev), para
    aniversários no fim do mês não rebentarem.
    """
    total = d.month - 1 + meses
    ano = d.year + total // 12
    mes = total % 12 + 1
    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def _boundary_corrente(criado: date, meses: int, hoje: date) -> date | None:
    """Fronteira de renovação do ciclo que "possui" `hoje`, ou ``None``.

    As fronteiras são `criado + n·meses` (n ≥ 1). Devolve a próxima fronteira se `hoje`
    está a ≤ 30 dias dela (janela pré-renovação); senão a fronteira anterior (a cauda de
    dunning pós-cobrança, até à véspera da pré-janela seguinte). Como as fronteiras
    distam ≥ 12 meses e a pré-janela é de 30 dias, quando muito uma serve `hoje`.
    """
    n = 1
    prox = _add_meses(criado, meses)
    while prox < hoje:
        n += 1
        prox = _add_meses(criado, n * meses)
    anterior = _add_meses(criado, (n - 1) * meses) if n >= 2 else None

    if (prox - hoje).days <= 30:
        return prox
    return anterior


def _meses_plano(plano: str | None) -> int:
    """Duração do plano em meses (default: plano anual)."""
    dados = config.PLANOS.get(plano or "", config.PLANOS[PLANO_PADRAO])
    return int(dados["meses"])


def _prepago(meses: int) -> bool:
    """Pré-pago (sem auto-cobrança) ⇒ sem dunning; só o aviso D-30 do fim."""
    return meses > 12


def _as_date(dt: datetime | date) -> date:
    """Data (UTC) de um `datetime` (ou a própria `date`)."""
    if isinstance(dt, datetime):
        base = dt.astimezone(timezone.utc) if dt.tzinfo else dt
        return base.date()
    return dt


# ==========================================================================
#  Decisão do passo do dia
# ==========================================================================
def _passo_do_dia(estado: str, dias: int, *, prepago: bool) -> tuple[str, bool] | None:
    """Devolve `(passo, cancelar)` para `hoje`, ou ``None`` se nada é devido.

    `dias = (renovação - hoje).days`: positivo antes da renovação (avisos), negativo
    depois (dunning). Janelas disjuntas ⇒ no máximo um passo por dia. Os avisos exigem
    `ativo`; os emails de falha exigem `em_dunning`. Pré-pago: só D-30.
    """
    if dias > 0:
        if estado != ESTADO_ATIVO:
            return None
        if 7 < dias <= 30:
            return (PASSO_D30, False)
        if not prepago and 0 < dias <= 7:
            return (PASSO_D7, False)
        return None

    if dias < 0:
        if prepago or estado != ESTADO_DUNNING:
            return None
        if -7 < dias <= -3:
            return (PASSO_D3, False)
        if -21 < dias <= -7:
            return (PASSO_D7_POS, False)
        if dias <= -21:
            return (PASSO_D21, True)
        return None

    return None  # dias == 0 → D0 (a Stripe cobra), não é passo nosso


# ==========================================================================
#  Resumo de valor entregue (para o email D-30)
# ==========================================================================
def _resumo_valor(s: Any, cliente: models.Cliente, inicio: date) -> str:
    """Frase factual do valor entregue no ciclo (nº de varrimentos e de alertas).

    Nunca rebenta o email: qualquer erro de contagem degrada para uma frase genérica.
    """
    try:
        limite = datetime(inicio.year, inicio.month, inicio.day, tzinfo=timezone.utc)
        n_varr = (
            s.query(models.Varrimento)
            .filter(
                models.Varrimento.concluido_em.isnot(None),
                models.Varrimento.concluido_em >= limite,
            )
            .count()
        )
        n_alertas = (
            s.query(models.Alerta)
            .filter(
                models.Alerta.cliente_id == cliente.id,
                models.Alerta.origem == ORIGEM_EVENTO_REGISTO,
                models.Alerta.enviado_em.isnot(None),
            )
            .count()
        )
    except Exception:  # pragma: no cover - contagem é acessória, nunca bloqueia o email
        return "Mantivemos o teu Alojamento Local sob vigilância contínua no último ciclo."

    if n_varr <= 0:
        return "Mantivemos o teu Alojamento Local sob vigilância contínua no último ciclo."
    return (
        f"No último ciclo fizemos {n_varr} varrimento(s) nacionais do RNAL e "
        f"enviámos-te {n_alertas} alerta(s) sobre o teu Alojamento Local."
    )


# ==========================================================================
#  Formatação dos dados de faturação (a copy/estilo vivem nos templates WF2)
# ==========================================================================
def _euros(v: float) -> str:
    """Preço em euros, PT-PT (vírgula decimal; inteiro sem casas)."""
    if float(v).is_integer():
        return f"{int(v)} €"
    return f"{v:.2f} €".replace(".", ",")


def _data_pt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _gerir_url() -> str:
    """Ligação para o cliente gerir subscrição/método de pagamento (área de cliente)."""
    return config.SITE_URL


# ==========================================================================
#  Ponto de entrada (cron diário)
# ==========================================================================
def correr_dunning(agora: datetime, *, enviar: Enviar | None) -> list[PassoDunning]:
    """Corre um dia de dunning sobre todos os assinantes não cancelados.

    Parâmetros
    ----------
    agora:
        Instante de referência (relógio **injetado**; em produção
        `datetime.now(timezone.utc)`). Só a data (UTC) é usada.
    enviar:
        `enviar(*, para, assunto, html, anexos, **kw) -> ResultadoEnvio` **injetado**
        (dublê nos testes; em produção o *callable* de `app.envio.obter_enviador`, ou
        ``None`` sob modo de teste — nesse caso os emails não saem mas o D+21 ainda
        cancela). Este módulo nunca cria clientes HTTP.

    Devolve a lista de :class:`PassoDunning` executados nesta passagem. Idempotente:
    reprocessar o mesmo dia não reenvia passos já feitos.

    **Isolamento por cliente (à prova de falha de envio):** cada assinante corre na sua
    própria transação DENTRO de um `try/except`. Se o processamento de um cliente
    levantar (ex.: `enviar` rebenta), essa transação é revertida, a falha é registada e
    a corrida **continua** para os seguintes (incluindo os cancelamentos D+21). No fim,
    se algum cliente falhou, levanta :class:`DunningIncompleto` — para o
    `com_healthcheck` do cron pingar `/fail` — mas os passos que correram ficam feitos.
    """
    with db.get_session() as s0:
        ids = [
            cid
            for (cid,) in s0.query(models.Cliente.id)
            .filter(models.Cliente.estado != ESTADO_CANCELADO)
            .order_by(models.Cliente.id)
            .all()
        ]

    hoje = _as_date(agora)
    executados: list[PassoDunning] = []
    n_falhas = 0

    # Uma transação por cliente, isolada por try/except → a falha de um não desfaz nem
    # bloqueia os outros; só se regista após o commit do cliente ter corrido sem exceção.
    for cid in ids:
        try:
            with db.get_session() as s:
                cliente = s.get(models.Cliente, cid)
                if cliente is None or cliente.estado == ESTADO_CANCELADO:
                    passo = None
                else:
                    passo = _avaliar_cliente(s, cliente, hoje, agora, enviar)
            # `with` saiu sem exceção → transação do cliente COMMITADA; só então regista.
            if passo is not None:
                executados.append(passo)
        except Exception:
            n_falhas += 1
            _log.exception("dunning: falha ao processar cliente id=%s (revertido; continua)", cid)
            continue

    if n_falhas:
        raise DunningIncompleto(executados, n_falhas)
    return executados


def _avaliar_cliente(
    s: Any, cliente: models.Cliente, hoje: date, agora: datetime, enviar: Enviar | None
) -> PassoDunning | None:
    """Avalia e, se devido, executa o passo de dunning de um cliente (na sessão `s`)."""
    if cliente.criado_em is None or not cliente.estado:
        return None

    meses = _meses_plano(cliente.plano)
    renova = _boundary_corrente(_as_date(cliente.criado_em), meses, hoje)
    if renova is None:
        return None

    dias = (renova - hoje).days
    decisao = _passo_do_dia(cliente.estado, dias, prepago=_prepago(meses))
    if decisao is None:
        return None
    passo, cancelar = decisao

    marcador = f"{ORIGEM_DUNNING}:{passo}:{renova.isoformat()}"
    if _ja_feito(s, cliente.id, marcador):
        return None

    return _executar(
        s, cliente, passo=passo, cancelar=cancelar, marcador=marcador,
        renova=renova, meses=meses, agora=agora, enviar=enviar,
    )


def _ja_feito(s: Any, cliente_id: int, marcador: str) -> bool:
    """Diz se este passo (do ciclo) já foi executado (marcador durável em `alertas`)."""
    return (
        s.query(models.Alerta)
        .filter(models.Alerta.cliente_id == cliente_id, models.Alerta.origem == marcador)
        .first()
        is not None
    )


def _executar(
    s: Any,
    cliente: models.Cliente,
    *,
    passo: str,
    cancelar: bool,
    marcador: str,
    renova: date,
    meses: int,
    agora: datetime,
    enviar: Enviar | None,
) -> PassoDunning:
    """Envia o email do passo (se houver para quem), grava o marcador e — no D+21 —
    faz o downgrade `em_dunning → cancelado`. Tudo na transação de `s`."""
    dados = config.PLANOS.get(cliente.plano or "", config.PLANOS[PLANO_PADRAO])
    preco = float(dados["preco"])
    plano_nome = str(dados["nome"])

    resumo = ""
    if passo == PASSO_D30:
        resumo = _resumo_valor(s, cliente, _add_meses(renova, -meses))

    # Branded (templates WF2 de dunning): marca + rodapé legal + opt-out + disclaimer de
    # faturação garantidos pela base; aqui só se reúnem os DADOS do ciclo (data, preço,
    # resumo de valor, link de gestão). O dispatcher mapeia o passo → template certo.
    email = _emails_dunning.render_passo(
        passo,
        nome=cliente.nome or "titular",
        plano_nome=plano_nome,
        data_renovacao=_data_pt(renova),
        preco=_euros(preco),
        url_gerir=_gerir_url(),
        resumo_valor=resumo,
        email_destinatario=cliente.email or "",
        token_optout="",
    )

    enviado = False
    if enviar is not None and cliente.email:
        enviar(
            para=cliente.email,
            assunto=email.assunto,
            html=email.html,
            anexos=(),
            texto=email.texto,
            idempotency_key=marcador,
        )
        enviado = True

    s.add(models.Alerta(
        cliente_id=cliente.id,
        nr_registo=None,
        origem=marcador,
        conteudo=email.texto,
        canal="email",
        enviado_em=agora if enviado else None,
    ))

    if cancelar:
        cliente.estado = ESTADO_CANCELADO

    return PassoDunning(
        cliente_id=cliente.id, passo=passo, enviado=enviado, cancelou=cancelar
    )
