"""Orquestrador de *fulfillment* do CheckAL (FDS 2, SPEC-FDS2.md §fulfillment).

Este é o **único** sítio (além do webhook) que compõe todas as peças de um pagamento
confirmado: lê os dados da Checkout Session da Stripe, casa-os com o espelho local do
RNAL, materializa o assinante e **emite a fatura-recibo certificada** no InvoiceXpress.
O webhook (`app/web/webhook_stripe.py`) limita-se a verificar a assinatura, garantir a
idempotência por `event.id` e despachar para as funções daqui.

Funções públicas (mapeadas 1:1 aos eventos Stripe — SPEC-STRIPE §2.5):

    processar_checkout(sessao, *, emitir_fatura)   ← checkout.session.completed  (anual e trienal)
    processar_renovacao(invoice, *, emitir_fatura) ← invoice.paid  (G1: só subscription_cycle)
    marcar_cancelado(subscription)                 ← customer.subscription.deleted
    registar_falha_pagamento(invoice)              ← invoice.payment_failed

**Idempotência.** Duas camadas complementares (SPEC-FDS2 §disciplina):
  - por `event.id` — no webhook (tabela `webhook_eventos`), que garante que cada evento
    corre no máximo uma vez;
  - por `stripe_session_id` — aqui em `processar_checkout`: se já existe um cliente para
    a mesma sessão, não se cria outro nem se reemite a fatura (a Stripe reentrega webhooks;
    um documento fiscal finalizado **não se apaga**).

**Match contra `registos`** (SPEC-FDS2 §fulfillment): primeiro por `nr_registo` (a PK do
espelho RNAL, tolerando o sufixo "/AL" que o titular copia); em falha, *fallback* fuzzy por
**nome + concelho** (nome do titular do checkout vs `titular_nome`/`nome_alojamento`, dentro
do mesmo concelho). Um cliente que pagou é sempre materializado, com ou sem match — a
associação `clientes_registos` só se cria quando há registo correspondente.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria clientes
HTTP nem conhece o fornecedor de faturação: depende de um **emissor agnóstico**
`emitir_fatura(*, nome, nif, email, itens, ...) -> FaturaRecibo` **injetado** por quem
chama (o webhook compõe-o via :func:`app.faturacao.obter_emissor`; os testes injetam um
falso). A composição do cliente HTTP (e do Bearer OAuth, no TOConline) vive toda em
`app.faturacao` — aqui só se chama o *callable*. Nada de emails, nada de cold. O email de
boas-vindas + selo é FDS 3: fica aqui um **ponto de extensão** (`_agendar_boas_vindas`) —
no FDS 2 é um no-op deliberado, para não haver envios.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import app.config as config
import app.db as db
import app.models as models
from app.faturacao import obter_emissor
from app.faturacao.base import FaturaRecibo

# Emissor agnóstico de faturas: `emitir(*, nome, nif, email, itens, codigo_cliente=None,
# dormir=time.sleep) -> FaturaRecibo`. Composto em `app.faturacao.obter_emissor` (o único
# sítio com HTTP real) ou injetado falso nos testes.
Emissor = Callable[..., FaturaRecibo]

# --- Constantes de comportamento -------------------------------------------
PLANO_PADRAO = "anual"              # plano assumido se a sessão não o revelar (SPEC-STRIPE)
LIMIAR_FUZZY = 0.85                 # razão mínima de semelhança do nome para aceitar o fuzzy
NIF_CONSUMIDOR_FINAL = "999999990"  # NIF genérico quando o cliente não fornece (LEGAL §fiscal)
BILLING_REASON_RENOVACAO = "subscription_cycle"  # G1: só isto refatura (SPEC-STRIPE §5.1)

# Chaves dos custom fields do Checkout (SPEC-STRIPE §2.1).
CF_NIF = "nif"
CF_NR_REGISTO = "nr_registo_al"

# Estados locais do cliente (models.Cliente.estado).
ESTADO_ATIVO = "ativo"
ESTADO_DUNNING = "em_dunning"
ESTADO_CANCELADO = "cancelado"

# Ações devolvidas no Resultado (para o webhook / auditoria).
ACCAO_CHECKOUT = "checkout"
ACCAO_RENOVACAO = "renovacao"
ACCAO_CANCELADO = "cancelado"
ACCAO_FALHA = "falha_pagamento"
ACCAO_IGNORADO = "ignorado"


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class Resultado:
    """Desfecho de uma ação de fulfillment (o webhook só precisa de responder 2xx).

    `idempotente=True` marca que a ação já tinha corrido (não se reemitiu nada).
    `correspondido` diz se houve match a um registo do RNAL; `fatura` traz a
    fatura-recibo certificada quando foi emitida nesta passagem (senão `None`).
    """

    accao: str
    cliente_id: int | None = None
    plano: str | None = None
    nr_registo: int | None = None
    correspondido: bool = False
    idempotente: bool = False
    fatura: FaturaRecibo | None = None


# ==========================================================================
#  Extração de campos da Stripe Checkout Session / Invoice (dicts crus)
# ==========================================================================
def _id_de(valor: Any) -> str | None:
    """ID de um campo Stripe que tanto pode vir expandido (dict) como cru (str)."""
    if isinstance(valor, Mapping):
        valor = valor.get("id")
    return str(valor) if valor else None


def _custom_field(sessao: Mapping[str, Any], chave: str) -> str | None:
    """Lê o valor de um `custom_field` do Checkout (`field[field.type].value`, §2.2)."""
    for campo in sessao.get("custom_fields") or []:
        if not isinstance(campo, Mapping) or campo.get("key") != chave:
            continue
        tipo = campo.get("type") or "text"
        sub = campo.get(tipo)
        if isinstance(sub, Mapping) and sub.get("value") not in (None, ""):
            return str(sub["value"])
    return None


def _nr_registo_de_texto(texto: str | None) -> int | None:
    """Interpreta o nº de registo RNAL, tolerando o sufixo "/AL" e espaços."""
    if not texto:
        return None
    cabeca = str(texto).strip().split("/", 1)[0].strip()
    return int(cabeca) if cabeca.isdigit() else None


def _plano_da_sessao(sessao: Mapping[str, Any]) -> str:
    """Deriva o código de plano interno (chave de `config.PLANOS`) da sessão.

    Precedência: `metadata.plano` → `line_items[].price.id` via `STRIPE_PRICE_PLANO`
    → `amount_total` (cêntimos) que bata com um preço de `PLANOS`. Sem sinal → `PLANO_PADRAO`.
    """
    md = sessao.get("metadata") or {}
    p = md.get("plano")
    if p in config.PLANOS:
        return str(p)

    linhas = ((sessao.get("line_items") or {}).get("data")) or []
    for item in linhas:
        pid = _id_de((item or {}).get("price"))
        if pid and pid in config.STRIPE_PRICE_PLANO:
            return config.STRIPE_PRICE_PLANO[pid]

    total = sessao.get("amount_total")
    if isinstance(total, int):
        for cod, dados in config.PLANOS.items():
            if round(float(dados["preco"]) * 100) == total:
                return cod
    return PLANO_PADRAO


def _itens_do_plano(plano: str) -> list[dict[str, Any]]:
    """Linha(s) de fatura a partir do plano (preço IVA incl. de `PLANOS`)."""
    dados = config.PLANOS.get(plano, config.PLANOS[PLANO_PADRAO])
    return [{
        "nome": dados["nome"],
        "descricao": f"Subscrição de monitorização RNAL — {dados['meses']} meses",
        "preco": float(dados["preco"]),
        "quantidade": 1,
    }]


# ==========================================================================
#  Match contra o espelho RNAL (por nr; fallback fuzzy nome+concelho)
# ==========================================================================
def _norm(valor: Any) -> str:
    """Forma canónica p/ comparação de nomes: sem acentos, minúsculas, espaços colapsados."""
    if not valor:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(valor))
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acentos.casefold().split())


def _match_registo(
    s, *, nr_registo: int | None, nome: str | None, concelho: str | None
) -> models.Registo | None:
    """Encontra o `Registo` correspondente ao checkout, ou `None`.

    1) Direto pela PK `nr_registo` (barato e exato).
    2) *Fallback* fuzzy: dentro do mesmo concelho, a maior semelhança entre o `nome`
       do checkout e o `titular_nome`/`nome_alojamento` do registo, acima de
       `LIMIAR_FUZZY`. Exige concelho (evita varrer o espelho inteiro por nome só).
    """
    if nr_registo is not None:
        reg = s.get(models.Registo, nr_registo)
        if reg is not None:
            return reg

    nome_norm = _norm(nome)
    if not nome_norm or not concelho:
        return None

    candidatos = (
        s.query(models.Registo)
        .filter(func.lower(func.trim(models.Registo.concelho)) == concelho.strip().lower())
        .all()
    )
    melhor: models.Registo | None = None
    melhor_ratio = 0.0
    for reg in candidatos:
        for campo in (reg.titular_nome, reg.nome_alojamento):
            alvo = _norm(campo)
            if not alvo:
                continue
            ratio = SequenceMatcher(None, nome_norm, alvo).ratio()
            if ratio > melhor_ratio:
                melhor_ratio = ratio
                melhor = reg
    return melhor if melhor is not None and melhor_ratio >= LIMIAR_FUZZY else None


# ==========================================================================
#  Ponto de extensão FDS 3 (boas-vindas + selo) — seam LIVE-GATED
# ==========================================================================
def _compor_onboarding() -> Callable[[int, FaturaRecibo | None], Any] | None:
    """Compõe o *seam* de onboarding do FDS 3, ou ``None`` (LIVE-GATED).

    À imagem **exata** de :func:`app.faturacao.obter_emissor` /
    :func:`app.envio.obter_enviador`: devolve ``None`` (sem tocar a rede) sob
    `config.CHECKAL_MODO_TESTE` **ou** quando o enviador transacional não está composto
    (sem `RESEND_API_KEY`). Só em produção compõe o *callable* que liga o detalhe RNAL
    (`app.rnal.detalhe.obter_detalhe`, o único ponto que cria o seu cliente HTTP) e o
    enviador Resend ao :func:`app.onboarding.processar_onboarding`.

    Os imports são **tardios**: nos testes este seam nunca resolve (modo de teste), pelo
    que nem `fpdf` nem a stack de envio são carregados a partir daqui.
    """
    if config.CHECKAL_MODO_TESTE:
        return None

    from app.envio import obter_enviador

    enviar = obter_enviador()
    if enviar is None:
        return None

    from app.onboarding import processar_onboarding
    from app.rnal.detalhe import obter_detalhe

    def _seam(cliente_id: int, fatura: FaturaRecibo | None) -> Any:
        return processar_onboarding(cliente_id, obter_detalhe=obter_detalhe, enviar=enviar)

    return _seam


def _agendar_boas_vindas(
    cliente_id: int, fatura: FaturaRecibo | None, *, sessao: Mapping[str, Any] | None = None
) -> None:
    """Ponto de extensão (pós-fatura) do email de boas-vindas + selo (FDS 3).

    Chamado **depois** de o cliente e a fatura-recibo estarem duravelmente commitados
    (fora da transação do checkout), para que o onboarding, ao abrir a sua própria
    sessão, veja o pagante já persistido. LIVE-GATED via :func:`_compor_onboarding`:
    sob modo de teste é um no-op (devolve ``None`` sem enviar) — os testes de fulfillment
    substituem esta função ou verificam o no-op. **Best-effort**: uma falha do onboarding
    (um email de cortesia) nunca desfaz um pagamento já materializado — engole-se e regista.
    """
    seam = _compor_onboarding()
    if seam is None:
        return None
    try:
        seam(cliente_id, fatura)
    except Exception:
        logging.getLogger(__name__).exception(
            "onboarding (boas-vindas) falhou para o cliente %s", cliente_id
        )
    return None


# ==========================================================================
#  Helpers de persistência
# ==========================================================================
def _cliente_por_customer(s, customer_id: str | None) -> models.Cliente | None:
    """Assinante ligado a um `customer` Stripe (o mais antigo, se houver colisão)."""
    if not customer_id:
        return None
    return (
        s.query(models.Cliente)
        .filter(models.Cliente.stripe_customer_id == customer_id)
        .order_by(models.Cliente.id)
        .first()
    )


def _cliente_por_sessao(s, session_id: str | None) -> models.Cliente | None:
    """Assinante já materializado para uma `checkout.session` (idempotência do checkout).

    `session_id` vazio nunca casa (evita colar-se a clientes de sessão NULL). É o
    ponto único de leitura da idempotência por sessão — partilhado pela verificação
    inicial e pela reconciliação após uma corrida perdida (ver `processar_checkout`).
    """
    if not session_id:
        return None
    return (
        s.query(models.Cliente)
        .filter(models.Cliente.stripe_session_id == session_id)
        .first()
    )


def _resultado_idempotente(cliente: models.Cliente) -> Resultado:
    """`Resultado` de um checkout que já tinha sido materializado (não reemite fatura).

    Tem de ser construído com a sessão ORM ainda aberta: lê a relação `registos`
    (lazy) do cliente. `fatura=None` sinaliza que nada foi emitido nesta passagem.
    """
    return Resultado(
        accao=ACCAO_CHECKOUT,
        cliente_id=cliente.id,
        plano=cliente.plano,
        correspondido=bool(cliente.registos),
        nr_registo=cliente.registos[0].nr_registo if cliente.registos else None,
        idempotente=True,
        fatura=None,
    )


def _emitir_e_guardar(
    s,
    cliente: models.Cliente,
    *,
    nome: str,
    nif: str,
    email: str,
    itens: Sequence[Mapping[str, Any]],
    emitir_fatura: Emissor,
    dormir: Callable[[float], None],
) -> FaturaRecibo:
    """Emite a fatura-recibo certificada e grava a ligação no cliente.

    Corre dentro da transação de quem chama: se a emissão levantar (G2/G3), o
    rollback desfaz o cliente — nunca fica um assinante sem fatura certificada.
    O `codigo_cliente` (código estável do cliente na conta de faturação — evita
    duplicá-lo) deriva do id local do cliente, seja qual for o fornecedor por trás
    do emissor (SPEC-INVOICEXPRESS §2.2 / SPEC-TOCONLINE §8).
    """
    fatura = emitir_fatura(
        nome=nome or "Consumidor final",
        nif=nif or NIF_CONSUMIDOR_FINAL,
        email=email or "",
        itens=itens,
        codigo_cliente=f"checkal-{cliente.id}",
        dormir=dormir,
    )
    cliente.ix_fatura_id = fatura.id
    cliente.ix_atcud = fatura.atcud
    cliente.ix_permalink = fatura.permalink
    return fatura


# ==========================================================================
#  API pública — despachada pelo webhook
# ==========================================================================
def processar_checkout(
    sessao: Mapping[str, Any],
    *,
    emitir_fatura: Emissor | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> Resultado:
    """Materializa um pagamento confirmado (checkout.session.completed).

    Idempotente por `stripe_session_id`: reprocessar a mesma sessão devolve o cliente
    existente sem reemitir fatura. Serve os dois modos (subscription/payment) — a
    diferença de recorrência é da Stripe; aqui o fluxo é o mesmo.

    `emitir_fatura` é o emissor agnóstico (default: :func:`app.faturacao.obter_emissor`);
    injeta-se um falso nos testes. LIVE-GATED: em modo de teste o default resolve para
    ``None`` — só se emite quando quem chama injeta um emissor (real em produção, falso
    nos testes).
    """
    if emitir_fatura is None:
        emitir_fatura = obter_emissor()

    session_id = _id_de(sessao.get("id"))
    nif = _custom_field(sessao, CF_NIF) or ""
    nr_registo = _nr_registo_de_texto(_custom_field(sessao, CF_NR_REGISTO))
    detalhes = sessao.get("customer_details") or {}
    email = str(detalhes.get("email") or "")
    nome = str(detalhes.get("name") or "")
    concelho = str((detalhes.get("address") or {}).get("city") or "")
    customer_id = _id_de(sessao.get("customer"))
    plano = _plano_da_sessao(sessao)

    try:
        with db.get_session() as s:
            # (0) idempotência por sessão — não duplicar cliente nem fatura
            existente = _cliente_por_sessao(s, session_id)
            if existente is not None:
                return _resultado_idempotente(existente)

            # (1) match contra o espelho RNAL
            registo = _match_registo(s, nr_registo=nr_registo, nome=nome, concelho=concelho)

            # (2) materializa o assinante
            cliente = models.Cliente(
                email=email or None,
                nome=nome or (registo.titular_nome if registo else None),
                nif=nif or None,
                stripe_customer_id=customer_id,
                plano=plano,
                estado=ESTADO_ATIVO,
                criado_em=datetime.now(timezone.utc),
                stripe_session_id=session_id,
            )
            s.add(cliente)
            # `flush` corre ANTES de qualquer chamada ao InvoiceXpress: se outro worker
            # já materializou esta sessão, a UNIQUE de `stripe_session_id` faz o INSERT
            # rebentar aqui (IntegrityError) — logo o perdedor da corrida aborta SEM
            # emitir uma 2.ª fatura certificada. Ver except em baixo.
            s.flush()  # atribui cliente.id (necessário p/ associação e client.code)

            # (3) associação cliente ↔ registo (só quando há match)
            if registo is not None:
                s.add(models.ClienteRegisto(cliente_id=cliente.id, nr_registo=registo.nr_registo))

            # (4) fatura-recibo certificada + ligação persistida
            fatura = _emitir_e_guardar(
                s, cliente,
                nome=cliente.nome or "", nif=nif, email=email,
                itens=_itens_do_plano(plano), emitir_fatura=emitir_fatura, dormir=dormir,
            )

            cliente_id = cliente.id
            nr_correspondido = registo.nr_registo if registo is not None else None

        # (5) ponto de extensão FDS 3 (boas-vindas + selo) — DEPOIS do commit da
        # transação do checkout, para o onboarding ver o pagante já persistido ao abrir
        # a sua própria sessão. LIVE-GATED: no-op sob modo de teste (ver `_agendar_boas_vindas`).
        _agendar_boas_vindas(cliente_id, fatura, sessao=sessao)

        return Resultado(
            accao=ACCAO_CHECKOUT,
            cliente_id=cliente_id,
            plano=plano,
            nr_registo=nr_correspondido,
            correspondido=registo is not None,
            idempotente=False,
            fatura=fatura,
        )
    except IntegrityError:
        # Corrida perdida: outro worker gravou esta sessão entre a verificação (0) e o
        # flush (2). O documento fiscal já foi (ou está a ser) emitido por esse worker;
        # reconcilia-se devolvendo o cliente existente, idempotente e SEM reemitir.
        with db.get_session() as s:
            existente = _cliente_por_sessao(s, session_id)
            if existente is not None:
                return _resultado_idempotente(existente)
        raise


def processar_renovacao(
    invoice: Mapping[str, Any],
    *,
    emitir_fatura: Emissor | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> Resultado:
    """Fatura uma renovação anual/portfólio (invoice.paid).

    **G1**: só refatura quando `billing_reason == "subscription_cycle"` — a fatura da 1.ª
    compra já saiu no checkout; qualquer outro motivo (`subscription_create`, etc.) é
    ignorado para não duplicar. O plano e o NIF vêm do cliente local (guardados no
    checkout; a Stripe não repete os custom fields nas renovações — SPEC-STRIPE §5.5).

    `emitir_fatura` é o emissor agnóstico (default: :func:`app.faturacao.obter_emissor`);
    injeta-se um falso nos testes.
    """
    if invoice.get("billing_reason") != BILLING_REASON_RENOVACAO:
        return Resultado(accao=ACCAO_IGNORADO)

    if emitir_fatura is None:
        emitir_fatura = obter_emissor()

    customer_id = _id_de(invoice.get("customer"))
    with db.get_session() as s:
        cliente = _cliente_por_customer(s, customer_id)
        if cliente is None:
            return Resultado(accao=ACCAO_IGNORADO)

        plano = cliente.plano or PLANO_PADRAO
        fatura = _emitir_e_guardar(
            s, cliente,
            nome=cliente.nome or "", nif=cliente.nif or "", email=cliente.email or "",
            itens=_itens_do_plano(plano), emitir_fatura=emitir_fatura, dormir=dormir,
        )
        cliente.estado = ESTADO_ATIVO
        cliente_id = cliente.id

    return Resultado(
        accao=ACCAO_RENOVACAO, cliente_id=cliente_id, plano=plano, fatura=fatura,
    )


def marcar_cancelado(subscription: Mapping[str, Any]) -> Resultado:
    """Marca o assinante `cancelado` (customer.subscription.deleted).

    O corte de alertas e o selo público "monitorização suspensa" ficam para os
    consumidores do estado; aqui só se assenta o estado local.
    """
    customer_id = _id_de(subscription.get("customer"))
    with db.get_session() as s:
        cliente = _cliente_por_customer(s, customer_id)
        if cliente is None:
            return Resultado(accao=ACCAO_IGNORADO)
        cliente.estado = ESTADO_CANCELADO
        cliente_id = cliente.id
    return Resultado(accao=ACCAO_CANCELADO, cliente_id=cliente_id)


def registar_falha_pagamento(invoice: Mapping[str, Any]) -> Resultado:
    """Regista uma falha de cobrança de renovação (invoice.payment_failed).

    Assenta o cliente em `em_dunning`. A Stripe já reenvia (Smart Retries) e avisa por
    email; a régua de dunning própria (D+3/D+7) é FDS 5 — aqui só se marca o estado.
    """
    customer_id = _id_de(invoice.get("customer"))
    with db.get_session() as s:
        cliente = _cliente_por_customer(s, customer_id)
        if cliente is None:
            return Resultado(accao=ACCAO_IGNORADO)
        cliente.estado = ESTADO_DUNNING
        cliente_id = cliente.id
    return Resultado(accao=ACCAO_FALHA, cliente_id=cliente_id)
