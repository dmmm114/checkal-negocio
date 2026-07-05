"""Testes do filtro de NIF (titular) — app.compliance.nif.

Regra canónica (RATIONALE.md §3):
  e_enderecavel(nif) -> True SÓ se 9 dígitos numéricos e 1.º dígito ∈ {5,6}.
  classificar_nif -> "singular" | "coletiva" | "outro" | "invalido".

Um teste por trap; nomes descritivos. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest

from app.compliance.nif import classificar_nif, e_enderecavel


# --------------------------------------------------------------------------
#  e_enderecavel — regra positiva (coletiva 5/6, limpa, 9 dígitos)
# --------------------------------------------------------------------------
def test_enderecavel_coletiva_prefixo_5_e_verdadeiro():
    assert e_enderecavel("513029591") is True


def test_enderecavel_coletiva_prefixo_6_e_verdadeiro():
    assert e_enderecavel("600000000") is True


# --------------------------------------------------------------------------
#  Traps — e_enderecavel TEM de rejeitar
# --------------------------------------------------------------------------
def test_trap_prefixo_45_nao_residente_singular_nao_e_enderecavel():
    # "45…" é singular não-residente: contém 5 mas NÃO no 1.º dígito.
    assert e_enderecavel("451234567") is False


def test_trap_prefixo_8_eni_nao_e_enderecavel():
    # ENI (empresário em nome individual) é pessoa singular.
    assert e_enderecavel("800000000") is False


def test_trap_prefixo_9_coletiva_provisoria_condominio_nao_e_enderecavel():
    assert e_enderecavel("900000000") is False


def test_trap_123456789_nao_e_enderecavel():
    # 1.º dígito = 1 -> singular.
    assert e_enderecavel("123456789") is False


def test_trap_string_vazia_nao_e_enderecavel():
    assert e_enderecavel("") is False


def test_trap_none_nao_e_enderecavel():
    assert e_enderecavel(None) is False  # type: ignore[arg-type]


def test_trap_oito_digitos_nao_e_enderecavel():
    assert e_enderecavel("51302959") is False


def test_trap_dez_digitos_nao_e_enderecavel():
    assert e_enderecavel("5130295910") is False


def test_trap_letras_nao_e_enderecavel():
    assert e_enderecavel("51302959A") is False


# --------------------------------------------------------------------------
#  Traps — numerais Unicode não-ASCII (str.isdigit() aceita-os, mas NÃO
#  são dígitos 0-9 ASCII, logo não constituem um NIF válido). Viés
#  conservador: têm de falhar o check. Regressão do red-team.
# --------------------------------------------------------------------------
def test_trap_arabe_indico_nao_e_enderecavel():
    # '5' ASCII + 8 numerais árabe-índicos (٢٣٤٥٦٧٨٩): isdigit()==True, mas não é NIF ASCII.
    assert e_enderecavel("5٢٣٤٥٦٧٨٩") is False


def test_trap_sobrescritos_nao_e_enderecavel():
    # '5' ASCII + 8 sobrescritos '²' (U+00B2): isdigit()==True.
    assert e_enderecavel("5" + "²" * 8) is False


def test_trap_devanagari_nao_e_enderecavel():
    # '5' ASCII + 8 dígitos devanágari '२' (U+0966..): isdigit()==True.
    assert e_enderecavel("5" + "२" * 8) is False


def test_trap_arabe_indico_classifica_invalido():
    assert classificar_nif("5٢٣٤٥٦٧٨٩") == "invalido"


def test_trap_sobrescritos_classifica_invalido():
    assert classificar_nif("5" + "²" * 8) == "invalido"


def test_trap_devanagari_classifica_invalido():
    assert classificar_nif("5" + "२" * 8) == "invalido"


def test_trap_espacos_limpos_antes_de_avaliar_e_verdadeiro():
    # " 5 1 3 0 2 9 5 9 1 " -> "513029591" -> True.
    assert e_enderecavel(" 5 1 3 0 2 9 5 9 1 ") is True


def test_trap_prefixo_PT_limpo_antes_de_avaliar_e_verdadeiro():
    assert e_enderecavel("PT513029591") is True


# --------------------------------------------------------------------------
#  Regressão (sweep [baixo]): whitespace não-óbvio de exports do RNAL
#  (newline, carriage return, non-breaking space, espaços internos) tem de
#  ser limpo — senão uma coletiva 5/6 legítima seria descartada (falso neg.).
# --------------------------------------------------------------------------
def test_trap_newline_final_limpo_e_verdadeiro():
    assert e_enderecavel("513029591\n") is True


def test_trap_carriage_return_final_limpo_e_verdadeiro():
    assert e_enderecavel("513029591\r") is True


def test_trap_nbsp_interno_limpo_e_verdadeiro():
    # '\xa0' (non-breaking space) entre grupos de dígitos.
    assert e_enderecavel("513\xa0029\xa0591") is True


def test_classificar_coletiva_com_newline_e_nbsp():
    assert classificar_nif("513029591\n") == "coletiva"
    assert classificar_nif("513\xa0029\xa0591") == "coletiva"


# --------------------------------------------------------------------------
#  e_enderecavel — limpeza adicional (pontos)
# --------------------------------------------------------------------------
def test_enderecavel_com_pontos_e_verdadeiro():
    assert e_enderecavel("513.029.591") is True


def test_enderecavel_prefixo_PT_minusculas_e_verdadeiro():
    assert e_enderecavel("pt513029591") is True


# --------------------------------------------------------------------------
#  classificar_nif — singular (1/2/3 e prefixo 45)
# --------------------------------------------------------------------------
def test_classificar_singular_prefixo_1():
    assert classificar_nif("123456789") == "singular"


def test_classificar_singular_prefixo_2():
    assert classificar_nif("223456789") == "singular"


def test_classificar_singular_prefixo_3():
    assert classificar_nif("323456789") == "singular"


def test_classificar_singular_prefixo_45_nao_residente():
    assert classificar_nif("451234567") == "singular"


# --------------------------------------------------------------------------
#  classificar_nif — coletiva (5/6)
# --------------------------------------------------------------------------
def test_classificar_coletiva_prefixo_5():
    assert classificar_nif("513029591") == "coletiva"


def test_classificar_coletiva_prefixo_6():
    assert classificar_nif("600000000") == "coletiva"


# --------------------------------------------------------------------------
#  classificar_nif — outro (7x, 8, 9x válidos)
# --------------------------------------------------------------------------
def test_classificar_outro_prefixo_8_eni():
    assert classificar_nif("800000000") == "outro"


def test_classificar_outro_prefixo_9_provisoria():
    assert classificar_nif("900000000") == "outro"


def test_classificar_outro_prefixo_7x():
    assert classificar_nif("700000000") == "outro"


# --------------------------------------------------------------------------
#  classificar_nif — invalido
# --------------------------------------------------------------------------
def test_classificar_invalido_vazio():
    assert classificar_nif("") == "invalido"


def test_classificar_invalido_none():
    assert classificar_nif(None) == "invalido"  # type: ignore[arg-type]


def test_classificar_invalido_oito_digitos():
    assert classificar_nif("51302959") == "invalido"


def test_classificar_invalido_dez_digitos():
    assert classificar_nif("5130295910") == "invalido"


def test_classificar_invalido_com_letras():
    assert classificar_nif("51302959A") == "invalido"


# --------------------------------------------------------------------------
#  classificar_nif — limpeza aplica-se também aqui
# --------------------------------------------------------------------------
def test_classificar_coletiva_com_espacos_e_pontos():
    assert classificar_nif(" 513.029.591 ") == "coletiva"


def test_classificar_coletiva_com_prefixo_PT():
    assert classificar_nif("PT513029591") == "coletiva"


# --------------------------------------------------------------------------
#  Coerência entre as duas funções: só "coletiva" é endereçável.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nif",
    ["513029591", "600000000", "451234567", "800000000", "900000000",
     "123456789", "700000000", "", "51302959", "5130295910", "51302959A"],
)
def test_coerencia_enderecavel_implica_coletiva(nif):
    if e_enderecavel(nif):
        assert classificar_nif(nif) == "coletiva"
