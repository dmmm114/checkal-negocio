"""Adaptador InvoiceXpress: emissão de **fatura-recibo certificada** (série CKL).

Fronteira do módulo (SPEC-FDS2 §invoicexpress_client + `SPEC-INVOICEXPRESS.md`):
recebe os dados fiscais de um pagamento confirmado e devolve uma
:class:`FaturaRecibo` **certificada** (com ATCUD e saft_hash), correndo o fluxo:

    [1] POST  /invoice_receipts.json          → cria a fatura-recibo (draft)
    [2] PUT   /invoice_receipts/:id/change-state.json  (state="finalized")
    [3] GET   /api/pdf/:id.json               → PDF (tolera 202 → polling curto)
    [4] GET   /invoice_receipts/:id.json      → lê ATCUD + saft_hash + total

A dataclass :class:`FaturaRecibo`, a hierarquia de exceções e os helpers de
preço/certificação vivem agora em :mod:`app.faturacao.base` (tronco partilhado
por todos os fornecedores). Este módulo importa-os e **re-exporta** os nomes
históricos — a sua fronteira pública mantém-se **exatamente** igual
(`FaturaRecibo`, `ErroInvoiceXpress`, `FaturaNaoCertificada`, `TotalInesperado`,
`preco_liquido`, `total_esperado`, `emitir_fatura_recibo`).

Guardas (não devolvem fatura "boa" quando a realidade fiscal falha):
  - **G2 — `FaturaNaoCertificada`**: `atcud` vazio/"N/D"/"N/A" ou `saft_hash`
    ausente. Sem ATCUD o documento não foi comunicado à AT (é ilegal emiti-lo
    como bom). Cf. gotcha §5/§8 da SPEC-INVOICEXPRESS.
  - **G3 — `TotalInesperado`**: o `total` devolvido diverge do total esperado
    (base + IVA 23%). Apanha o caso em que a taxa `IVA23` não existe na conta e
    a API aplica silenciosamente a taxa por omissão (gotcha §8).

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria
nenhum cliente HTTP — o `cliente_http` é sempre **injetado** por quem chama
(mock nos testes; `httpx.Client` real só em produção, quando o dono desliga o
modo de teste e há chaves). Assim, correr os testes nunca toca a rede.

O `cliente_http` é qualquer objeto à laia de `httpx.Client` com:
  - ``post(url, *, params=..., json=...) -> resposta``
  - ``put(url, *, params=..., json=...) -> resposta``
  - ``get(url, *, params=...) -> resposta``
onde `resposta` expõe ``status_code: int``, ``json() -> dict`` e
``raise_for_status()``. O `dormir` do polling é injetável (neutralizado nos testes).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import app.config as config
from app.faturacao.base import (
    TOLERANCIA_TOTAL_EUR,
    ErroFaturacao,
    FaturaNaoCertificada,
    FaturaRecibo,
    TotalInesperado,
    atcud_valido,
    preco_liquido,
    saft_presente,
    total_esperado,
)

# Compat: o nome histórico da exceção base deste adaptador É a exceção partilhada.
# Um `except ErroInvoiceXpress` legado continua a apanhar as guardas G2/G3 (que
# descendem de `ErroFaturacao`), seja qual for o fornecedor ativo.
ErroInvoiceXpress = ErroFaturacao

# Fronteira pública inalterada: `FaturaRecibo`, as guardas e os helpers vêm de
# `base` mas continuam acessíveis como `invoicexpress_client.<nome>`.
__all__ = [
    "FaturaRecibo",
    "ErroInvoiceXpress",
    "FaturaNaoCertificada",
    "TotalInesperado",
    "preco_liquido",
    "total_esperado",
    "emitir_fatura_recibo",
]

# --- Constantes do fluxo (SPEC-INVOICEXPRESS §2.3/§2.5/§6) ----------------
ESTADO_FINALIZADO = "finalized"     # a doc mente ("settled"); o que funciona é este (gotcha §1)
PDF_TENTATIVAS = 6                  # nº de GETs ao PDF antes de desistir do polling (202)
PDF_PAUSA_S = 1.0                  # pausa base entre tentativas de PDF (passa por `dormir`)


# ==========================================================================
#  Helpers internos de parsing (tolerantes às ambiguidades de root key da SPEC)
# ==========================================================================
def _base_url() -> str:
    """Host da conta InvoiceXpress (subdomínio em `config.INVOICEXPRESS_ACCOUNT`)."""
    return f"https://{config.INVOICEXPRESS_ACCOUNT}.app.invoicexpress.com"


def _params() -> dict[str, str]:
    """Autenticação por `api_key` em query string (SPEC §2.1)."""
    return {"api_key": config.INVOICEXPRESS_API_KEY}


def _desembrulhar(payload: Any, *chaves: str) -> dict:
    """Devolve o dict interno sob a 1.ª de `chaves` presente; senão o próprio payload.

    A SPEC deixa a *root key* como ASSUMIDA (`invoice` vs `invoice_receipt`); em
    vez de fixar uma, aceitamos ambas e ainda o objeto no topo.
    """
    if isinstance(payload, dict):
        for chave in chaves:
            interno = payload.get(chave)
            if isinstance(interno, dict):
                return interno
        return payload
    return {}


def _extrair_pdf_url(payload: Any) -> str | None:
    """Extrai o URL do PDF das variantes conhecidas (`output.pdfUrl` / `pdfUrl` / `permalink`)."""
    if not isinstance(payload, dict):
        return None
    saida = payload.get("output")
    if isinstance(saida, dict):
        for chave in ("pdfUrl", "pdf_url", "permalink"):
            if saida.get(chave):
                return str(saida[chave])
    for chave in ("pdfUrl", "pdf_url", "permalink"):
        if payload.get(chave):
            return str(payload[chave])
    return None


# ==========================================================================
#  Passos do fluxo
# ==========================================================================
def _corpo_criar(
    *, nome: str, nif: str, email: str,
    itens: Sequence[Mapping[str, Any]], codigo_cliente: str,
) -> dict:
    """Monta o corpo de criação (root `"invoice"`; `unit_price` líquido; taxa nomeada)."""
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")  # dd/mm/yyyy (§2.2, gotcha §10)
    itens_api = [
        {
            "name": it["nome"],
            "description": it.get("descricao", ""),
            "unit_price": preco_liquido(float(it["preco"])),
            "quantity": int(it.get("quantidade", 1)),
            "tax": {"name": config.INVOICEXPRESS_TAXA_NOME},
        }
        for it in itens
    ]
    return {
        "invoice": {
            "date": hoje,
            "due_date": hoje,
            "sequence_id": config.INVOICEXPRESS_SEQUENCE_ID,
            "client": {
                "name": nome,
                "code": codigo_cliente,   # id estável nosso (evita duplicar clientes) — §2.2
                "fiscal_id": nif,
                "email": email,
            },
            "items": itens_api,
        }
    }


def _obter_pdf_url(
    cliente_http: Any, doc_id: str, *, dormir: Callable[[float], None]
) -> str | None:
    """GET ao PDF com polling curto: tolera 202 (a gerar) até 200 (gotcha §3).

    Não bloqueia a certificação: se esgotar o polling ainda em 202, devolve
    ``None`` (o PDF é para o email, FDS 3), deixando o resto do fluxo seguir.
    """
    url = f"{_base_url()}/api/pdf/{doc_id}.json"
    for tentativa in range(1, PDF_TENTATIVAS + 1):
        resposta = cliente_http.get(url, params=_params())
        if resposta.status_code == 202:
            if tentativa < PDF_TENTATIVAS:
                dormir(PDF_PAUSA_S * tentativa)
            continue
        resposta.raise_for_status()
        return _extrair_pdf_url(resposta.json())
    return None


# ==========================================================================
#  API pública
# ==========================================================================
def emitir_fatura_recibo(
    *,
    nome: str,
    nif: str,
    email: str,
    itens: Sequence[Mapping[str, Any]],
    cliente_http: Any,
    codigo_cliente: str | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> FaturaRecibo:
    """Emite uma fatura-recibo certificada e devolve-a, ou levanta uma guarda.

    Parâmetros
    ----------
    nome, nif, email:
        Dados fiscais do cliente (o `nif` vai em `client.fiscal_id`).
    itens:
        Sequência de dicts ``{"nome", "preco" (IVA incl.), "quantidade"?, "descricao"?}``.
        O `preco` é o de tabela (PLANOS); convertemo-lo em base líquida internamente.
    cliente_http:
        Cliente HTTP **injetado** (mock nos testes; nunca criado aqui — LIVE-GATED).
    codigo_cliente:
        Id estável do cliente para `client.code` (evita duplicar clientes na conta).
        Por omissão deriva do NIF.
    dormir:
        Pausa do polling do PDF; neutralizada nos testes.

    Levanta
    -------
    FaturaNaoCertificada
        Guarda G2 — sem ATCUD/saft_hash (documento não comunicado à AT).
    TotalInesperado
        Guarda G3 — total devolvido diverge do esperado (IVA 23% incl.).
    ErroInvoiceXpress
        Resposta de criação sem `id`.
    """
    codigo = codigo_cliente or f"checkal-{nif}"

    # [1] criar (draft)
    r_criar = cliente_http.post(
        f"{_base_url()}/invoice_receipts.json",
        params=_params(),
        json=_corpo_criar(nome=nome, nif=nif, email=email, itens=itens, codigo_cliente=codigo),
    )
    r_criar.raise_for_status()
    doc_id = str(_desembrulhar(r_criar.json(), "invoice_receipt", "invoice").get("id", "") or "")
    if not doc_id:
        raise ErroInvoiceXpress("Resposta de criação da fatura-recibo sem `id`.")

    # [2] finalizar (torna definitivo → nº sequencial + ATCUD + comunicação à AT)
    r_final = cliente_http.put(
        f"{_base_url()}/invoice_receipts/{doc_id}/change-state.json",
        params=_params(),
        json={"invoice_receipt": {"state": ESTADO_FINALIZADO}},
    )
    r_final.raise_for_status()

    # [3] PDF (tolera 202 → polling curto; não bloqueia a certificação)
    pdf_url = _obter_pdf_url(cliente_http, doc_id, dormir=dormir)

    # [4] ler campos fiscais (ATCUD, saft_hash, total, sequência, permalink)
    r_det = cliente_http.get(
        f"{_base_url()}/invoice_receipts/{doc_id}.json",
        params=_params(),
    )
    r_det.raise_for_status()
    det = _desembrulhar(r_det.json(), "invoice_receipt", "invoice")

    atcud = det.get("atcud")
    saft_hash = det.get("saft_hash")

    # GUARDA G2 — certificação AT
    if not atcud_valido(atcud) or not saft_presente(saft_hash):
        raise FaturaNaoCertificada(
            f"Fatura {doc_id} finalizada sem certificação AT "
            f"(atcud={atcud!r}, saft_hash={'presente' if saft_presente(saft_hash) else 'ausente'}).",
            doc_id=doc_id,
        )

    # GUARDA G3 — total tem de bater certo (IVA 23% incl.)
    total_devolvido = float(det.get("total") or 0.0)
    esperado = total_esperado(itens)
    if abs(total_devolvido - esperado) > TOLERANCIA_TOTAL_EUR:
        raise TotalInesperado(
            f"Fatura {doc_id}: total devolvido {total_devolvido:.2f} € != esperado {esperado:.2f} € "
            f"(taxa {config.INVOICEXPRESS_TAXA_NOME!r} aplicada?).",
            doc_id=doc_id,
        )

    return FaturaRecibo(
        id=doc_id,
        sequence_number=str(det.get("sequence_number", "") or ""),
        atcud=str(atcud),
        saft_hash=str(saft_hash),
        total=total_devolvido,
        permalink=str(det.get("permalink", "") or ""),
        pdf_url=pdf_url,
        estado=str(det.get("status", ESTADO_FINALIZADO) or ESTADO_FINALIZADO),
    )
