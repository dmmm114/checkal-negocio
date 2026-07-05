"""Testes do esquema Pydantic do registo RNAL — app.rnal.schema.

Contrato (SPEC-FDS1.md §schema):
  - `RegistoRNAL` valida um registo bruto (aninhado em `RNAL_Registo`).
  - `parse_registo(bruto) -> RegistoRNAL`; `parse_lista(lista) -> list[RegistoRNAL]`.
  - `NrRegisto`, `Concelho`, `TitulardaExploracao` são obrigatórios; o resto opcional.
  - `nr_registo: int` derivado de `NrRegisto` (corta em "/").
  - `titular_tipo` normalizado: "Pessoa coletiva"→"coletiva", "Pessoa singular"→"singular".
  - `NrUtentes`/`NrCamas` podem vir string OU int.
  - Estrutura esperada muda (chave obrigatória em falta / tipo incompatível) → `DriftEsquemaRNAL`.

Um teste por comportamento; nomes descritivos. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest

from app.rnal.schema import (
    DriftEsquemaRNAL,
    RegistoRNAL,
    parse_lista,
    parse_registo,
)


# --------------------------------------------------------------------------
#  Fixtures de registo bruto (formato verificado da API list_RNAL)
# --------------------------------------------------------------------------
def _registo_coletiva() -> dict:
    """Registo válido, titular pessoa coletiva, no invólucro `RNAL_Registo`."""
    return {
        "RNAL_Registo": {
            "NrRegisto": "100031/AL",
            "DataRegisto": "2019-07-16",
            "NomeAlojamento": "Casa do Sol",
            "Modalidade": "Estabelecimento de hospedagem",
            "NrCamas": 2,
            "NrUtentes": "4",
            "Endereco": "Rua das Flores 1",
            "CodPostal": "8000-444",
            "Localidade": "Faro",
            "Freguesia": "Sé",
            "Concelho": "Faro",
            "Distrito": "Faro",
            "TitulardaExploracao": {
                "Tipo": "Pessoa coletiva",
                "Nome": "Sol Lda",
                "Contribuinte": "513029591",
                "Email": "geral@sol.pt",
            },
            "DTMNFR": "080508",
        }
    }


def _registo_singular() -> dict:
    return {
        "RNAL_Registo": {
            "NrRegisto": "200500/AL",
            "Concelho": "Lisboa",
            "NomeAlojamento": "Apartamento Central",
            "NrCamas": "3",
            "NrUtentes": 6,
            "TitulardaExploracao": {
                "Tipo": "Pessoa singular",
                "Nome": "Ana Maria",
                "Contribuinte": "123456789",
                "Telefone": "289000000",
                "Telemovel": "910000000",
            },
        }
    }


# --------------------------------------------------------------------------
#  Registo válido -> objeto
# --------------------------------------------------------------------------
def test_registo_valido_coletiva_devolve_objeto():
    r = parse_registo(_registo_coletiva())
    assert isinstance(r, RegistoRNAL)


def test_campos_principais_ficam_acessiveis():
    r = parse_registo(_registo_coletiva())
    assert r.nome_alojamento == "Casa do Sol"
    assert r.modalidade == "Estabelecimento de hospedagem"
    assert r.endereco == "Rua das Flores 1"
    assert r.cod_postal == "8000-444"
    assert r.freguesia == "Sé"
    assert r.concelho == "Faro"
    assert r.distrito == "Faro"


def test_titular_achatado_para_o_topo():
    r = parse_registo(_registo_coletiva())
    assert r.titular_nome == "Sol Lda"
    assert r.nif == "513029591"
    assert r.email == "geral@sol.pt"


# --------------------------------------------------------------------------
#  nr_registo: int derivado (corta em "/")
# --------------------------------------------------------------------------
def test_nr_registo_derivado_para_inteiro():
    r = parse_registo(_registo_coletiva())
    assert r.nr_registo == 100031
    assert isinstance(r.nr_registo, int)


def test_nr_registo_aceita_valor_ja_inteiro():
    bruto = _registo_coletiva()
    bruto["RNAL_Registo"]["NrRegisto"] = 100031
    assert parse_registo(bruto).nr_registo == 100031


def test_nr_registo_nao_numerico_e_drift():
    bruto = _registo_coletiva()
    bruto["RNAL_Registo"]["NrRegisto"] = "abc/AL"
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


# --------------------------------------------------------------------------
#  titular_tipo normalizado
# --------------------------------------------------------------------------
def test_titular_tipo_coletiva_normalizado():
    assert parse_registo(_registo_coletiva()).titular_tipo == "coletiva"


def test_titular_tipo_singular_normalizado():
    assert parse_registo(_registo_singular()).titular_tipo == "singular"


def test_titular_tipo_desconhecido_ou_ausente_fica_none():
    bruto = _registo_coletiva()
    del bruto["RNAL_Registo"]["TitulardaExploracao"]["Tipo"]
    assert parse_registo(bruto).titular_tipo is None


# --------------------------------------------------------------------------
#  NrUtentes / NrCamas: string OU int
# --------------------------------------------------------------------------
def test_nr_utentes_string_aceite():
    # fixture coletiva traz NrUtentes = "4" (string)
    assert parse_registo(_registo_coletiva()).nr_utentes == 4


def test_nr_utentes_inteiro_aceite():
    # fixture singular traz NrUtentes = 6 (int)
    assert parse_registo(_registo_singular()).nr_utentes == 6


def test_nr_camas_string_e_inteiro_ambos_aceites():
    assert parse_registo(_registo_coletiva()).nr_camas == 2      # int na fonte
    assert parse_registo(_registo_singular()).nr_camas == 3      # string na fonte


def test_nr_camas_ausente_fica_none():
    bruto = _registo_coletiva()
    del bruto["RNAL_Registo"]["NrCamas"]
    assert parse_registo(bruto).nr_camas is None


def test_nr_utentes_nao_numerico_e_drift():
    bruto = _registo_coletiva()
    bruto["RNAL_Registo"]["NrUtentes"] = "muitos"
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


# --------------------------------------------------------------------------
#  Campos opcionais ausentes -> None
# --------------------------------------------------------------------------
def test_campos_opcionais_ausentes_ficam_none():
    r = parse_registo(_registo_singular())
    assert r.distrito is None
    assert r.data_registo is None
    assert r.email is None


def test_telefone_e_telemovel_do_titular_capturados():
    r = parse_registo(_registo_singular())
    assert r.telefone == "289000000"
    assert r.telemovel == "910000000"


# --------------------------------------------------------------------------
#  Chaves obrigatórias em falta -> DriftEsquemaRNAL
# --------------------------------------------------------------------------
def test_falta_nr_registo_e_drift():
    bruto = _registo_coletiva()
    del bruto["RNAL_Registo"]["NrRegisto"]
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


def test_falta_concelho_e_drift():
    bruto = _registo_coletiva()
    del bruto["RNAL_Registo"]["Concelho"]
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


def test_falta_titular_e_drift():
    bruto = _registo_coletiva()
    del bruto["RNAL_Registo"]["TitulardaExploracao"]
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


def test_nr_registo_none_e_drift():
    bruto = _registo_coletiva()
    bruto["RNAL_Registo"]["NrRegisto"] = None
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


def test_titular_nao_dicionario_e_drift():
    bruto = _registo_coletiva()
    bruto["RNAL_Registo"]["TitulardaExploracao"] = "Sol Lda"
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(bruto)


def test_bruto_nao_dicionario_e_drift():
    with pytest.raises(DriftEsquemaRNAL):
        parse_registo(["nao", "sou", "dict"])


# --------------------------------------------------------------------------
#  Invólucro RNAL_Registo: aceite com e sem envelope
# --------------------------------------------------------------------------
def test_aceita_registo_ja_desembrulhado():
    interno = _registo_coletiva()["RNAL_Registo"]
    r = parse_registo(interno)
    assert r.nr_registo == 100031


# --------------------------------------------------------------------------
#  parse_lista
# --------------------------------------------------------------------------
def test_parse_lista_devolve_lista_de_objetos():
    lista = [_registo_coletiva(), _registo_singular()]
    res = parse_lista(lista)
    assert len(res) == 2
    assert all(isinstance(r, RegistoRNAL) for r in res)
    assert [r.nr_registo for r in res] == [100031, 200500]


def test_parse_lista_com_elemento_drift_rebenta():
    mau = _registo_coletiva()
    del mau["RNAL_Registo"]["Concelho"]
    with pytest.raises(DriftEsquemaRNAL):
        parse_lista([_registo_singular(), mau])


def test_parse_lista_nao_lista_e_drift():
    with pytest.raises(DriftEsquemaRNAL):
        parse_lista(_registo_coletiva())


# --------------------------------------------------------------------------
#  DTMNFR (irrelevante para diffing) capturado mas não obrigatório
# --------------------------------------------------------------------------
def test_dtmnfr_capturado_quando_presente():
    assert parse_registo(_registo_coletiva()).dtmnfr == "080508"


def test_dtmnfr_ausente_fica_none():
    assert parse_registo(_registo_singular()).dtmnfr is None
