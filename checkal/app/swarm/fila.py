"""Fila de revisão + gates do enxame — API determinista sobre `revisao_itens`.

O único caminho pelo qual trabalho de agente se torna aprovável — e, depois de
aprovado PELO DONO, executável. Regras duras (invariantes de governação, §6 do
prompt-mestre), todas código e testadas:

  - :func:`enfileirar` corre o LINTER internamente e SÓ insere se `aprovado=True`;
    caso contrário levanta :class:`LinterReprovado` com as violações (FAIL-CLOSED);
    se o import do linter falhar, recusa (:class:`LinterIndisponivel`) — nunca
    enfileira às cegas. Alertas "cancelado" só entram com breaker E cross-check
    confirmados (RT-Sentinela pré-envio), senão :class:`PreEnvioNaoConfirmado`.
  - NENHUM caminho de agente escreve `estado='aprovado'`: só :func:`aprovar`
    (o dono, com token válido gerado pelo MAESTRO) o faz — e escreve a linha em
    `aprovacoes` com autor ≠ aprovador (quem PROPÕE nunca APROVA).
  - :func:`drain` serve APENAS itens já aprovados, com lease + backoff exponencial
    e cap por passagem alinhado com `config.CAMPANHA_CAP_DIARIO`.
  - Gate DGC fail-closed (:func:`dgc_ok` / :func:`pode_enviar_frio_com_dgc`):
    lista de oposição vazia/estagnada ⇒ trata-se como se TODOS estivessem
    opostos — recusa, mesmo com os restantes gates abertos.
  - :func:`sessao_governacao` devolve uma sessão que RECUSA (before_flush)
    qualquer escrita fora das tabelas de governação do enxame — os agentes não
    podem tocar `clientes`/`alertas`/`registos`/`faturas`/`leads` nem por engano.

Nada aqui envia/publica/cobra: o envio real continua atrás do triplo gate do
backbone (`pode_enviar_frio_global` + núcleo de compliance + oposição).
"""
from __future__ import annotations

import importlib
import secrets
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

import app.config as config
import app.db as db
import app.models_swarm as ms
from app.campanhas import motor

__all__ = [
    "LinterIndisponivel",
    "LinterReprovado",
    "PreEnvioNaoConfirmado",
    "TokenInvalido",
    "AutorNaoAprova",
    "EscritaForaDaGovernacao",
    "TABELAS_GOVERNACAO",
    "enfileirar",
    "drain",
    "gerar_token",
    "token_bate",
    "aprovar",
    "rejeitar",
    "dgc_ok",
    "carregar_lista_dgc",
    "pode_enviar_frio_com_dgc",
    "sessao_governacao",
]

# Tabelas em que a camada de agentes PODE escrever. Tudo o resto é domínio do
# backbone determinista — fora do alcance de qualquer subcomando de agente.
# (`faturas` fica de fora: o ledger é escrito pelo fulfillment, não por agentes.)
TABELAS_GOVERNACAO = frozenset({
    "eventos_agente", "campanhas", "campanha_pecas", "revisao_itens",
    "contactos_coletiva", "metricas_rollup", "supressao_nif",
    "aprovacoes", "escalacoes", "agente_execucoes", "digests", "custo_llm",
})

# Mapeamento risco (texto, schema canónico) → camada_risco (1 mínimo … 4 máximo).
# Camadas 3–4 = dinheiro/terceiros/publicação/envio em massa ⇒ SEMPRE clique do dono.
_CAMADA_POR_RISCO = {"baixo": 1, "medio": 3, "alto": 4}

_BACKOFF_MAX_S = 6 * 3600
_LEASE_MIN = 15


class LinterIndisponivel(RuntimeError):
    """O linter não pôde ser importado — enfileirar recusa (fail-closed)."""


class LinterReprovado(RuntimeError):
    """O linter reprovou a peça — nada foi inserido; as violações seguem p/ escala."""

    def __init__(self, violacoes) -> None:
        super().__init__(f"linter reprovou a peça ({len(violacoes)} violações)")
        self.violacoes = list(violacoes)


class PreEnvioNaoConfirmado(RuntimeError):
    """Alerta "cancelado" sem breaker E cross-check confirmados (RT-Sentinela)."""


class TokenInvalido(RuntimeError):
    """Token de aprovação ausente/errado — a decisão não é do dono."""


class AutorNaoAprova(RuntimeError):
    """Quem propõe nunca aprova — separação de poderes inviolável."""


class EscritaForaDaGovernacao(RuntimeError):
    """Um caminho de agente tentou escrever numa tabela de domínio."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _importar_linter():
    """Import indireto e tardio do linter — o ponto único de fail-closed.

    Se falhar (módulo ausente/estragado), :func:`enfileirar` recusa em vez de
    inserir sem vet. Indireto de propósito: os testes simulam a ausência.
    """
    return importlib.import_module("app.compliance.linter")


# Deteção de afirmação forte de cancelamento/suspensão (RT-Sentinela pré-envio).
# Varre o texto COMPLETO (citações incluídas): qualquer alerta que fale de
# cancelamento só é enfileirável com prova dupla — senão degrada-se a montante
# para "em verificação" e recompõe-se.
def _afirma_cancelamento(texto: str) -> bool:
    t = (texto or "").lower()
    return "cancelad" in t or "suspens" in t


# ==========================================================================
#  enfileirar — o ÚNICO caminho de entrada na fila (linter obrigatório)
# ==========================================================================
def enfileirar(
    session,
    *,
    tipo: str,
    risco: str,
    agente_origem: str,
    peca,
    ref_tipo: str | None = None,
    ref_id: str | None = None,
    resumo: str | None = None,
    camada_risco: int | None = None,
    breaker_confirmado: bool = False,
    cross_check_ok: bool = False,
) -> ms.RevisaoItem:
    """Veta a `peca` (PecaOutward) com o linter e insere um item `pendente`.

    FAIL-CLOSED em três frentes:
      - linter ausente ⇒ :class:`LinterIndisponivel`, nada inserido;
      - linter reprova ⇒ :class:`LinterReprovado` (com `.violacoes`), nada inserido;
      - alerta que afirme cancelamento/suspensão sem `breaker_confirmado` E
        `cross_check_ok` ⇒ :class:`PreEnvioNaoConfirmado`, nada inserido (o
        chamador recompõe como "em verificação" ou escala).

    O item nasce SEMPRE `pendente` — não existe caminho para nascer aprovado.
    A transação é do chamador (sem commit aqui).
    """
    try:
        linter = _importar_linter()
    except Exception as exc:  # noqa: BLE001 — qualquer falha de import é recusa
        raise LinterIndisponivel(f"linter indisponível: {exc}") from exc

    if peca.canal is linter.Canal.ALERTA and _afirma_cancelamento(peca.texto):
        if not (breaker_confirmado and cross_check_ok):
            raise PreEnvioNaoConfirmado(
                "alerta com afirmação de cancelamento/suspensão sem confirmação "
                "dupla (breaker E cross-check) — degradar para 'em verificação'."
            )

    resultado = linter.lint(peca)
    if not resultado.aprovado:
        raise LinterReprovado(resultado.violacoes)

    item = ms.RevisaoItem(
        tipo=tipo,
        risco=risco,
        camada_risco=camada_risco if camada_risco is not None
        else _CAMADA_POR_RISCO.get(risco, 4),
        agente_origem=agente_origem,
        ref_tipo=ref_tipo,
        ref_id=ref_id,
        resumo=resumo,
        linter_ok=True,
        linter_achados={
            "versao": resultado.versao,
            "violacoes": [
                {"regra": v.regra, "severidade": v.severidade.value,
                 "trecho": v.trecho, "razao": v.razao}
                for v in resultado.violacoes
            ],
        },
        criado_em=_agora(),
    )
    session.add(item)
    session.flush()
    return item


# ==========================================================================
#  Tokens + decisão do dono (o único caminho para `aprovado`)
# ==========================================================================
def gerar_token(session, item_id: int) -> str:
    """Gera e grava o token de aprovação 1-clique (papel do MAESTRO). NÃO aprova."""
    item = session.get(ms.RevisaoItem, item_id)
    if item is None or item.estado != "pendente":
        raise TokenInvalido(f"item {item_id} inexistente ou já decidido")
    token = secrets.token_urlsafe(16)
    item.token_aprovacao = token
    session.flush()
    return token


def token_bate(item, token: str) -> bool:
    """Comparação constant-time do token 1-clique (SOBRE BYTES — não-ASCII
    de query param falha fechado, nunca TypeError). Fonte única: gate e
    _decidir usam AMBOS este helper."""
    if not token or not item.token_aprovacao:
        return False
    return secrets.compare_digest(
        token.encode("utf-8"), item.token_aprovacao.encode("utf-8"))


def _decidir(session, item_id: int, *, token: str, decidido_por: str,
             decisao: str, nota: str | None) -> ms.RevisaoItem:
    item = session.get(ms.RevisaoItem, item_id)
    if item is None:
        raise TokenInvalido(f"item {item_id} inexistente")
    if item.estado != "pendente":
        raise TokenInvalido(f"item {item_id} já não está pendente ({item.estado})")
    if not token_bate(item, token):
        raise TokenInvalido("token de aprovação ausente ou inválido")
    autor = item.agente_origem or "desconhecido"
    if decidido_por == autor:
        raise AutorNaoAprova(f"{decidido_por!r} propôs o item — não o pode decidir")

    session.add(
        ms.Aprovacao(
            revisao_item_id=item.id, autor=autor, decidido_por=decidido_por,
            decisao=decisao, token_usado=token, nota=nota, criado_em=_agora(),
        )
    )
    item.estado = decisao
    item.decidido_em = _agora()
    item.decidido_por = decidido_por
    item.nota = nota
    session.flush()
    return item


def aprovar(session, item_id: int, *, token: str, decidido_por: str = "dono",
            nota: str | None = None) -> ms.RevisaoItem:
    """Aprova um item — SÓ o caminho do dono. Valida o token, escreve `aprovacoes`
    (autor ≠ aprovador) e só então marca `aprovado`. Nenhum agente chama isto."""
    return _decidir(session, item_id, token=token, decidido_por=decidido_por,
                    decisao="aprovado", nota=nota)


def rejeitar(session, item_id: int, *, token: str, decidido_por: str = "dono",
             nota: str | None = None) -> ms.RevisaoItem:
    """Rejeita um item (mesmo circuito de validação do que aprovar)."""
    return _decidir(session, item_id, token=token, decidido_por=decidido_por,
                    decisao="rejeitado", nota=nota)


# ==========================================================================
#  drain — fila de trabalho sobre itens JÁ aprovados (lease + backoff)
# ==========================================================================
def drain(
    session,
    agente: str,
    limite: int | None = None,
    processador: Callable[[ms.RevisaoItem], object] | None = None,
) -> list[ms.RevisaoItem]:
    """Serve (e opcionalmente processa) itens `aprovado` do `agente`, com lease.

    Padrão da fila de trabalho (HARNESS(obs) §b): seleciona elegíveis
    (`aprovado`, sem backoff pendente, sem lease vivo), marca `a_correr` +
    `lease_ate = now+15min`, e — se `processador` for dado — executa cada item:
    sucesso ⇒ `feito`; exceção ⇒ `tentativas+1` + backoff exponencial
    (`falhado`) até `max_tentativas` ⇒ `morto` (a escalar ao MAESTRO). O cap por
    passagem é `min(limite, config.CAMPANHA_CAP_DIARIO)`.

    A idempotência de domínio (UNIQUEs das peças/faturas) é a rede final: um
    lease expirado pode re-servir um item, nunca duplicar o efeito externo.
    """
    agora = _agora()
    cap = config.CAMPANHA_CAP_DIARIO if limite is None else min(limite, config.CAMPANHA_CAP_DIARIO)

    candidatos = (
        session.query(ms.RevisaoItem)
        .filter(ms.RevisaoItem.estado == "aprovado")
        .order_by(ms.RevisaoItem.criado_em, ms.RevisaoItem.id)
        .all()
    )

    def _sem_tz(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    servidos: list[ms.RevisaoItem] = []
    for item in candidatos:
        if len(servidos) >= cap:
            break
        nao_antes = _sem_tz(item.nao_antes_de)
        if nao_antes is not None and nao_antes > agora:
            continue
        lease = _sem_tz(item.lease_ate)
        if lease is not None and lease > agora:
            continue
        item.estado = "a_correr"
        item.lease_ate = agora + timedelta(minutes=_LEASE_MIN)
        servidos.append(item)
    session.flush()

    if processador is None:
        return servidos

    for item in servidos:
        try:
            processador(item)
        except Exception:  # noqa: BLE001 — a falha alimenta o backoff, não rebenta o lote
            item.tentativas += 1
            if item.tentativas >= item.max_tentativas:
                item.estado = "morto"
            else:
                item.estado = "falhado"
                atraso = min(2 ** item.tentativas * 60, _BACKOFF_MAX_S)
                item.nao_antes_de = _agora() + timedelta(seconds=atraso)
            item.lease_ate = None
        else:
            item.estado = "feito"
            item.lease_ate = None
    session.flush()
    return servidos


# ==========================================================================
#  Gate DGC fail-closed (RT-DGC)
# ==========================================================================
def dgc_ok(
    lista_dgc: Iterable[str],
    *,
    carregada_em: datetime | None,
    agora: datetime | None = None,
    max_idade_dias: int | None = None,
) -> bool:
    """A lista de oposição DGC está utilizável? Fail-closed em tudo.

    False se: lista vazia, sem timestamp de carga, ou carga mais velha que
    `DGC_MAX_IDADE_DIAS`. Lista inutilizável ⇒ trata-se como se TODOS os
    destinatários estivessem opostos — o envio recusa.
    """
    contagem = sum(1 for _ in lista_dgc)
    if contagem == 0 or carregada_em is None:
        return False
    agora = agora or _agora()
    if carregada_em.tzinfo is None:
        carregada_em = carregada_em.replace(tzinfo=timezone.utc)
    idade_max = timedelta(days=config.DGC_MAX_IDADE_DIAS if max_idade_dias is None
                          else max_idade_dias)
    return agora - carregada_em <= idade_max


def carregar_lista_dgc() -> tuple[frozenset[str], datetime | None]:
    """Lê o feed DGC do ficheiro `config.LISTA_DGC_PATH` (1 email por linha).

    Devolve (emails, timestamp do ficheiro). Sem caminho configurado ou ficheiro
    ausente ⇒ `(frozenset(), None)` — que :func:`dgc_ok` recusa (fail-closed).
    """
    from pathlib import Path

    caminho = (config.LISTA_DGC_PATH or "").strip()
    if not caminho:
        return frozenset(), None
    f = Path(caminho)
    if not f.is_file():
        return frozenset(), None
    emails = frozenset(
        linha.strip().lower()
        for linha in f.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.startswith("#")
    )
    carregada_em = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
    return emails, carregada_em


def pode_enviar_frio_com_dgc(
    contacto,
    *,
    lista_dgc: Iterable[str],
    dgc_carregada_em: datetime | None,
    log_optout: Iterable[str] = (),
    agora: datetime | None = None,
) -> bool:
    """O gate de envio que os AGENTES usam: DGC utilizável E triplo gate do motor.

    Compõe (nunca substitui) `motor.pode_enviar_frio`: primeiro o gate DGC
    fail-closed; só depois o triplo gate por contacto do backbone. Qualquer
    falha ⇒ False — o draft fica em fila, nunca sai.
    """
    lista = list(lista_dgc)
    if not dgc_ok(lista, carregada_em=dgc_carregada_em, agora=agora):
        return False
    return motor.pode_enviar_frio(contacto, lista_dgc=lista, log_optout=log_optout)


# ==========================================================================
#  Sessão de governação — escrita estreita, domínio intocável
# ==========================================================================
@contextmanager
def sessao_governacao(permitidas: frozenset[str] | None = None):
    """Sessão transacional cuja escrita está LIMITADA às tabelas do enxame.

    Qualquer tentativa de escrever em `clientes`/`alertas`/`registos`/`faturas`/
    `leads` (ou outra tabela de domínio) rebenta no flush com
    :class:`EscritaForaDaGovernacao` e faz rollback — o portão é código.

    `permitidas` restringe AINDA MAIS o conjunto (ex.: o SENTINELA só pode
    escrever em `eventos_agente`/`escalacoes`); tem de ser subconjunto de
    :data:`TABELAS_GOVERNACAO`.
    """
    alvo = TABELAS_GOVERNACAO if permitidas is None else (
        frozenset(permitidas) & TABELAS_GOVERNACAO
    )

    def _guarda(session, flush_context, instances) -> None:
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            tabela = getattr(type(obj), "__tablename__", None)
            if tabela is not None and tabela not in alvo:
                raise EscritaForaDaGovernacao(
                    f"escrita recusada em {tabela!r}: esta sessão só escreve em "
                    f"{sorted(alvo)}"
                )

    s = db.SessionLocal()
    event.listen(s, "before_flush", _guarda)
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        event.remove(s, "before_flush", _guarda)
        s.close()
