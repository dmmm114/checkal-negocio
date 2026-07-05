"""Adaptador InvoiceXpress: emissão de **fatura-recibo certificada** (série CKL).

Fronteira do módulo (SPEC-FDS2 §invoicexpress_client + `SPEC-INVOICEXPRESS.md`):
recebe os dados fiscais de um pagamento confirmado e devolve uma
:class:`FaturaRecibo` **certificada** (com ATCUD e saft_hash), correndo o fluxo:

    [1] POST  /invoice_receipts.json          → cria a fatura-recibo (draft)
    [2] PUT   /invoice_receipts/:id/change-state.json  (state="finalized")
    [3] GET   /api/pdf/:id.json               → PDF (tolera 202 → polling curto)
    [4] GET   /invoice_receipts/:id.json      → lê ATCUD + saft_hash + total

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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import app.config as config

# --- Constantes do fluxo (SPEC-INVOICEXPRESS §2.3/§2.5/§6) ----------------
ESTADO_FINALIZADO = "finalized"     # a doc mente ("settled"); o que funciona é este (gotcha §1)
PDF_TENTATIVAS = 6                  # nº de GETs ao PDF antes de desistir do polling (202)
PDF_PAUSA_S = 1.0                  # pausa base entre tentativas de PDF (passa por `dormir`)
TOLERANCIA_TOTAL_EUR = 0.01        # folga (cêntimo) na comparação de totais da guarda G3

# Valores de ATCUD que significam "documento ainda não registado na AT".
_ATCUD_INVALIDO = {"", "N/D", "N/A", "ND", "NA"}


# ==========================================================================
#  Exceções (hierarquia própria; a base carrega o doc_id p/ reconciliação)
# ==========================================================================
class ErroInvoiceXpress(Exception):
    """Falha na emissão da fatura-recibo. `doc_id` (se conhecido) permite reconciliar."""

    def __init__(self, mensagem: str, *, doc_id: str | None = None):
        super().__init__(mensagem)
        self.doc_id = doc_id


class FaturaNaoCertificada(ErroInvoiceXpress):
    """GUARDA G2: documento finalizado sem ATCUD/saft_hash → não comunicado à AT."""


class TotalInesperado(ErroInvoiceXpress):
    """GUARDA G3: o total devolvido pela API não bate certo com o total esperado."""


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class FaturaRecibo:
    """Fatura-recibo **certificada** emitida com sucesso (documento fiscal definitivo).

    `pdf_url` pode ser ``None`` se o PDF ainda estiver a gerar quando o polling
    esgota — a certificação (ATCUD/saft_hash) não depende do PDF, que é só para
    anexar ao email de boas-vindas (FDS 3).
    """

    id: str
    sequence_number: str
    atcud: str
    saft_hash: str
    total: float
    permalink: str
    pdf_url: str | None
    estado: str


# ==========================================================================
#  Helpers de preço (SPEC-INVOICEXPRESS §5) — PLANOS traz preço com IVA incl.
# ==========================================================================
def preco_liquido(preco_bruto: float) -> float:
    """Converte um preço IVA-incluído no `unit_price` **líquido** a enviar à API.

    A API calcula o IVA sobre `unit_price`; para o total voltar ao preço de
    tabela (ex. 49,00 €) enviamos a base líquida (49/1,23 = 39,84 €), a que a
    taxa `IVA23` volta a somar os 23%.
    """
    return round(preco_bruto / (1 + config.IVA), 2)


def total_esperado(itens: Sequence[Mapping[str, Any]]) -> float:
    """Total esperado (base + IVA 23%), calculado à moda da AT: IVA sobre a base.

    Soma as bases líquidas por linha (cêntimo a cêntimo, como a fatura), aplica
    o IVA à base total e arredonda. É o valor que a guarda G3 exige que a API
    devolva. Trabalha em cêntimos inteiros para não arrastar ruído de vírgula.
    """
    base_cent = 0
    for it in itens:
        liquido = preco_liquido(float(it["preco"]))
        quantidade = int(it.get("quantidade", 1))
        base_cent += round(liquido * quantidade * 100)
    iva_cent = round(base_cent * config.IVA)
    return (base_cent + iva_cent) / 100


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


def _atcud_valido(atcud: Any) -> bool:
    """ATCUD real (documento registado na AT), não `"N/D"`/`"N/A"`/vazio."""
    return str(atcud or "").strip().upper() not in _ATCUD_INVALIDO


def _saft_presente(saft_hash: Any) -> bool:
    """`saft_hash` presente e não vazio (marca de comunicação à AT)."""
    return bool(str(saft_hash or "").strip())


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
    if not _atcud_valido(atcud) or not _saft_presente(saft_hash):
        raise FaturaNaoCertificada(
            f"Fatura {doc_id} finalizada sem certificação AT "
            f"(atcud={atcud!r}, saft_hash={'presente' if _saft_presente(saft_hash) else 'ausente'}).",
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
