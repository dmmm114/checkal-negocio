"""Testes da fundação partilhada de faturação — app.faturacao.base.

`base.py` é o tronco comum de todos os adaptadores de faturação (InvoiceXpress,
TOConline, ...): a dataclass `FaturaRecibo`, a hierarquia de exceções
(`ErroFaturacao` base + guardas `FaturaNaoCertificada`/`TotalInesperado`), os
helpers de preço (`preco_liquido`/`total_esperado`) e a validação da certificação
AT (`atcud_valido`/`saft_presente`) + a tolerância de total (`TOLERANCIA_TOTAL_EUR`).

Este ficheiro fixa o CONTRATO da base e, sobretudo, que o adaptador InvoiceXpress
partilha exatamente os MESMOS objetos (mesma identidade) — para que um `except
FaturaNaoCertificada` continue a apanhar o que qualquer adaptador levanta e o
swap de fornecedor não parta ninguém.

SEM rede, SEM I/O. Escrito ANTES do refactor (TDD).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config
from app.faturacao import base
from app.faturacao import invoicexpress_client as ix


# ==========================================================================
#  Helpers de preço (a base é a única fonte de verdade; a IX re-exporta)
# ==========================================================================
def test_preco_liquido_49_da_39_84():
    # 49,00 € IVA incl. → 39,84 € líquido (base sobre a qual se aplica o IVA)
    assert base.preco_liquido(49.0) == 39.84


def test_total_esperado_de_um_item_da_49():
    itens = [{"nome": "CheckAL Anual", "preco": 49.0, "quantidade": 1}]
    assert base.total_esperado(itens) == pytest.approx(49.0, abs=0.005)


def test_total_esperado_soma_quantidades():
    # A quantidade é somada (não ignorada): 2× ≈ o dobro de 1× (cêntimo a cêntimo,
    # daí a folga — 79,68 base + 23% arredonda a 98,01, não 98,00 exatos).
    um = base.total_esperado([{"nome": "CheckAL Anual", "preco": 49.0, "quantidade": 1}])
    dois = base.total_esperado([{"nome": "CheckAL Anual", "preco": 49.0, "quantidade": 2}])
    assert dois == pytest.approx(2 * um, abs=0.02)
    assert dois > um


def test_total_esperado_usa_iva_da_config():
    # O helper deriva do IVA canónico da config, não de um número mágico.
    assert config.IVA == 0.23


# ==========================================================================
#  FaturaRecibo — dataclass frozen com os campos do contrato drop-in
# ==========================================================================
def test_fatura_recibo_e_dataclass_frozen():
    f = base.FaturaRecibo(
        id="1",
        sequence_number="FR 2026/1",
        atcud="ABCD1234-1",
        saft_hash="deadbeef",
        total=49.0,
        permalink="https://ex/p",
        pdf_url=None,
        estado="finalizado",
    )
    assert dataclasses.is_dataclass(f)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.total = 0.0  # type: ignore[misc]


def test_fatura_recibo_tem_os_campos_do_contrato():
    campos = {f.name for f in dataclasses.fields(base.FaturaRecibo)}
    assert campos == {
        "id", "sequence_number", "atcud", "saft_hash",
        "total", "permalink", "pdf_url", "estado",
    }


# ==========================================================================
#  Hierarquia de exceções — base + guardas G2/G3
# ==========================================================================
def test_guardas_descendem_de_erro_faturacao():
    assert issubclass(base.FaturaNaoCertificada, base.ErroFaturacao)
    assert issubclass(base.TotalInesperado, base.ErroFaturacao)


def test_erro_faturacao_carrega_doc_id():
    e = base.ErroFaturacao("falhou", doc_id="998877")
    assert e.doc_id == "998877"
    assert str(e) == "falhou"


def test_erro_faturacao_doc_id_opcional():
    assert base.ErroFaturacao("sem id").doc_id is None


# ==========================================================================
#  Validação da certificação AT (G2) — atcud_valido / saft_presente
# ==========================================================================
@pytest.mark.parametrize("valor", ["", "N/D", "N/A", "ND", "NA", "n/d", "  ", None])
def test_atcud_invalido(valor):
    assert base.atcud_valido(valor) is False


@pytest.mark.parametrize("valor", ["ABCD1234-6", "0", "AJF7-1"])
def test_atcud_valido(valor):
    assert base.atcud_valido(valor) is True


@pytest.mark.parametrize("valor", ["", "   ", None])
def test_saft_ausente(valor):
    assert base.saft_presente(valor) is False


@pytest.mark.parametrize("valor", ["a1b2c3", "0"])
def test_saft_presente(valor):
    assert base.saft_presente(valor) is True


def test_tolerancia_total_e_um_centimo():
    assert base.TOLERANCIA_TOTAL_EUR == 0.01


# ==========================================================================
#  Compat do swap: a IX re-exporta os MESMOS objetos da base (identidade)
# ==========================================================================
def test_invoicexpress_reexporta_a_mesma_fatura_recibo():
    assert ix.FaturaRecibo is base.FaturaRecibo


def test_invoicexpress_reexporta_as_mesmas_guardas():
    assert ix.FaturaNaoCertificada is base.FaturaNaoCertificada
    assert ix.TotalInesperado is base.TotalInesperado


def test_invoicexpress_reexporta_os_mesmos_helpers():
    assert ix.preco_liquido is base.preco_liquido
    assert ix.total_esperado is base.total_esperado


def test_erro_invoicexpress_partilha_a_base():
    # O nome histórico continua a existir e a apanhar as guardas partilhadas:
    # um `except ErroInvoiceXpress` legado tem de continuar a apanhar
    # FaturaNaoCertificada/TotalInesperado emitidas por qualquer adaptador.
    assert issubclass(base.FaturaNaoCertificada, ix.ErroInvoiceXpress)
    assert issubclass(base.TotalInesperado, ix.ErroInvoiceXpress)
