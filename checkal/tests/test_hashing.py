"""Testes do hashing de campos relevantes — app.rnal.hashing.

Contrato (SPEC-FDS1.md §hashing):
  hash_campos(registo) -> sha256 hex dos campos relevantes para diffing, em
  ordem canónica e estável. Determinístico; sensível a cada campo relevante;
  insensível a campos irrelevantes (ex.: DTMNFR). Aceita um RegistoRNAL
  (objeto com atributos achatados) ou um dict achatado.

Escritos ANTES da implementação (TDD). Um teste por propriedade.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rnal.hashing import CAMPOS_RELEVANTES, hash_campos


# --------------------------------------------------------------------------
#  Fixtures / helpers
# --------------------------------------------------------------------------
def _registo_base() -> dict:
    """Dict achatado canónico (chaves = campos relevantes + irrelevantes)."""
    return {
        "nome_alojamento": "Casa do Mar",
        "modalidade": "Estabelecimento de hospedagem",
        "nr_camas": 2,
        "nr_utentes": 4,
        "endereco": "Rua das Flores 10",
        "cod_postal": "8000-444",
        "freguesia": "Sé",
        "concelho": "Faro",
        "distrito": "Faro",
        "titular_tipo": "coletiva",
        "titular_nome": "Oasis Lda",
        "nif": "513029591",
        "email": "geral@oasis.pt",
        "telefone": "289000000",
        "telemovel": "910000000",
        # irrelevantes p/ diffing:
        "DTMNFR": "080508",
        "nr_registo": 100031,
        "data_registo": "2019-07-16",
    }


# --------------------------------------------------------------------------
#  Formato
# --------------------------------------------------------------------------
def test_devolve_sha256_hex_de_64_chars():
    h = hash_campos(_registo_base())
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_constante_lista_todos_os_campos_relevantes_em_ordem():
    assert CAMPOS_RELEVANTES == (
        "nome_alojamento", "modalidade", "nr_camas", "nr_utentes",
        "endereco", "cod_postal", "freguesia", "concelho", "distrito",
        "titular_tipo", "titular_nome", "nif", "email", "telefone", "telemovel",
    )


# --------------------------------------------------------------------------
#  Estabilidade / determinismo
# --------------------------------------------------------------------------
def test_mesma_entrada_mesmo_hash():
    assert hash_campos(_registo_base()) == hash_campos(_registo_base())


def test_ordem_das_chaves_do_dict_e_irrelevante():
    r1 = _registo_base()
    r2 = dict(reversed(list(r1.items())))
    assert hash_campos(r1) == hash_campos(r2)


def test_hash_e_estavel_entre_chamadas_repetidas():
    r = _registo_base()
    valores = {hash_campos(r) for _ in range(5)}
    assert len(valores) == 1


# --------------------------------------------------------------------------
#  Sensibilidade — cada campo relevante muda o hash
# --------------------------------------------------------------------------
@pytest.mark.parametrize("campo", CAMPOS_RELEVANTES)
def test_alterar_qualquer_campo_relevante_muda_o_hash(campo):
    base = _registo_base()
    h0 = hash_campos(base)
    mutado = dict(base)
    mutado[campo] = str(mutado[campo]) + "_X"
    assert hash_campos(mutado) != h0


def test_campos_nao_colidem_por_deslocamento():
    # endereco e cod_postal trocados de conteúdo devem dar hash diferente
    a = _registo_base()
    b = _registo_base()
    b["endereco"], b["cod_postal"] = a["cod_postal"], a["endereco"]
    assert hash_campos(a) != hash_campos(b)


# --------------------------------------------------------------------------
#  Insensibilidade — campos irrelevantes não afetam
# --------------------------------------------------------------------------
def test_dtmnfr_nao_afeta_o_hash():
    base = _registo_base()
    h0 = hash_campos(base)
    outro = dict(base)
    outro["DTMNFR"] = "999999"
    assert hash_campos(outro) == h0


def test_remover_campos_irrelevantes_nao_afeta_o_hash():
    base = _registo_base()
    h0 = hash_campos(base)
    limpo = {k: v for k, v in base.items() if k in CAMPOS_RELEVANTES}
    assert hash_campos(limpo) == h0


def test_chave_extra_desconhecida_nao_afeta_o_hash():
    base = _registo_base()
    h0 = hash_campos(base)
    outro = dict(base)
    outro["campo_qualquer_novo"] = "seja_o_que_for"
    assert hash_campos(outro) == h0


# --------------------------------------------------------------------------
#  Normalização de valores
# --------------------------------------------------------------------------
def test_nr_camas_int_e_string_equivalem():
    a = _registo_base()
    a["nr_camas"] = 2
    b = _registo_base()
    b["nr_camas"] = "2"
    assert hash_campos(a) == hash_campos(b)


def test_none_ausente_e_vazio_equivalem():
    base = {k: v for k, v in _registo_base().items() if k in CAMPOS_RELEVANTES}
    com_none = dict(base)
    com_none["telemovel"] = None
    com_vazio = dict(base)
    com_vazio["telemovel"] = ""
    sem_chave = {k: v for k, v in base.items() if k != "telemovel"}
    assert hash_campos(com_none) == hash_campos(com_vazio) == hash_campos(sem_chave)


# --------------------------------------------------------------------------
#  Aceita RegistoRNAL (objeto) além de dict achatado
# --------------------------------------------------------------------------
def test_objeto_com_atributos_achatados_iguala_dict():
    base = _registo_base()
    obj = SimpleNamespace(**{k: base[k] for k in CAMPOS_RELEVANTES})
    assert hash_campos(obj) == hash_campos(base)


def test_objeto_ignora_atributos_irrelevantes():
    base = _registo_base()
    obj = SimpleNamespace(**base)  # inclui DTMNFR, nr_registo, etc.
    esperado = {k: base[k] for k in CAMPOS_RELEVANTES}
    assert hash_campos(obj) == hash_campos(esperado)


def test_objeto_com_titular_aninhado_resolve_campos():
    # Robustez cross-módulo: se o RegistoRNAL guardar o titular num sub-objeto
    # em vez de atributos achatados, os campos do titular são resolvidos na
    # mesma. Deve dar o mesmo hash que a versão achatada.
    base = _registo_base()
    nao_titular = {
        k: base[k] for k in CAMPOS_RELEVANTES
        if k not in ("titular_tipo", "titular_nome", "nif", "email",
                     "telefone", "telemovel")
    }
    titular = SimpleNamespace(
        tipo=base["titular_tipo"], nome=base["titular_nome"],
        nif=base["nif"], email=base["email"],
        telefone=base["telefone"], telemovel=base["telemovel"],
    )
    obj = SimpleNamespace(**nao_titular, titular=titular)
    achatado = {k: base[k] for k in CAMPOS_RELEVANTES}
    assert hash_campos(obj) == hash_campos(achatado)
