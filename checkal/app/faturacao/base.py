"""Fundação partilhada dos adaptadores de faturação (InvoiceXpress, TOConline, ...).

Tronco comum, agnóstico ao fornecedor, para que a interface pública de emissão
seja **intermutável** (drop-in) e as guardas continuem a apanhar o mesmo, seja
qual for o adaptador ativo. Aqui vive só o que é fiscal/de contrato, não o que é
específico de cada API:

  - :class:`FaturaRecibo` — o resultado (dataclass frozen, contrato drop-in);
  - a hierarquia de exceções: :class:`ErroFaturacao` (base, carrega `doc_id` para
    reconciliação) + as guardas :class:`FaturaNaoCertificada` (G2) e
    :class:`TotalInesperado` (G3);
  - os helpers de preço :func:`preco_liquido` / :func:`total_esperado` (o IVA sai
    da folha canónica em :data:`app.config.IVA`);
  - a validação da certificação AT :func:`atcud_valido` / :func:`saft_presente` e
    a tolerância de total :data:`TOLERANCIA_TOTAL_EUR` (cêntimo) da guarda G3.

Cada adaptador (`invoicexpress_client`, `toconline_client`) importa daqui e
re-exporta os nomes históricos que precise (ex. `ErroInvoiceXpress =
ErroFaturacao`), mantendo a sua fronteira pública sem duplicar a lógica fiscal.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import app.config as config

# Folga (cêntimo) na comparação de totais da guarda G3 — comum a todos os fornecedores.
TOLERANCIA_TOTAL_EUR = 0.01

# Valores de ATCUD que significam "documento ainda não registado na AT".
_ATCUD_INVALIDO = {"", "N/D", "N/A", "ND", "NA"}


# ==========================================================================
#  Exceções (hierarquia partilhada; a base carrega o doc_id p/ reconciliação)
# ==========================================================================
class ErroFaturacao(Exception):
    """Falha na emissão de uma fatura-recibo. `doc_id` (se conhecido) permite reconciliar."""

    def __init__(self, mensagem: str, *, doc_id: str | None = None):
        super().__init__(mensagem)
        self.doc_id = doc_id


class FaturaNaoCertificada(ErroFaturacao):
    """GUARDA G2: documento finalizado sem ATCUD/saft_hash → não comunicado à AT."""


class TotalInesperado(ErroFaturacao):
    """GUARDA G3: o total devolvido pela API não bate certo com o total esperado."""


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class FaturaRecibo:
    """Fatura-recibo **certificada** emitida com sucesso (documento fiscal definitivo).

    Contrato drop-in: os mesmos campos, seja qual for o fornecedor; cada adaptador
    preenche-os a partir do seu vocabulário (InvoiceXpress / TOConline).

    `pdf_url` pode ser ``None`` se o PDF ainda estiver a gerar — a certificação
    (ATCUD/saft_hash) não depende do PDF, que é só para anexar ao email (FDS 3).
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
#  Helpers de preço (PLANOS traz preço com IVA incluído)
# ==========================================================================
def preco_liquido(preco_bruto: float) -> float:
    """Converte um preço IVA-incluído no valor **líquido** (base sem IVA).

    A base é aquela sobre a qual a taxa de IVA volta a somar os 23%; para o total
    voltar ao preço de tabela (ex. 49,00 €) a base é 49/1,23 = 39,84 €.
    """
    return round(preco_bruto / (1 + config.IVA), 2)


def total_esperado(itens: Sequence[Mapping[str, Any]]) -> float:
    """Total esperado (base + IVA 23%), calculado à moda da AT: IVA sobre a base.

    Soma as bases líquidas por linha (cêntimo a cêntimo, como a fatura), aplica o
    IVA à base total e arredonda. É o valor que a guarda G3 exige que a API
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
#  Validação da certificação AT (guarda G2)
# ==========================================================================
def atcud_valido(atcud: Any) -> bool:
    """ATCUD real (documento registado na AT), não `"N/D"`/`"N/A"`/vazio."""
    return str(atcud or "").strip().upper() not in _ATCUD_INVALIDO


def saft_presente(saft_hash: Any) -> bool:
    """`saft_hash` presente e não vazio (marca de comunicação à AT)."""
    return bool(str(saft_hash or "").strip())
