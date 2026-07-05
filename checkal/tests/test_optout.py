"""Testes do cruzamento opt-out / oposição DGC (app.compliance.optout).

Regra (RATIONALE.md §3, optout.py): antes de cada envio, exclui-se o email cujo
valor normalizado (lowercase + trim) conste da lista de oposição de pessoas
coletivas da DGC OU do log interno de opt-out. As listas são conjuntos injetados
(já normalizados pela fonte real). Este módulo não envia nada.

Um teste por trap, nomes descritivos.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.compliance.optout import (
    deve_excluir,
    filtrar_optout,
    normalizar_email,
    preparar_listas,
)


# --- normalizar_email --------------------------------------------------------

def test_normalizar_email_baixa_caixa_e_apara_espacos():
    assert normalizar_email("  Geral@X.PT  ") == "geral@x.pt"


def test_normalizar_email_ja_normalizado_fica_igual():
    assert normalizar_email("info@empresa.pt") == "info@empresa.pt"


# --- deve_excluir: traps -----------------------------------------------------

def test_maiusculas_e_espacos_batem_com_entrada_normalizada_na_dgc():
    # " Geral@X.PT " deve ser excluído se "geral@x.pt" estiver na DGC.
    assert deve_excluir(
        " Geral@X.PT ",
        lista_dgc={"geral@x.pt"},
        log_optout=set(),
    ) is True


def test_presenca_so_na_dgc_exclui():
    assert deve_excluir(
        "info@empresa.pt",
        lista_dgc={"info@empresa.pt"},
        log_optout=set(),
    ) is True


def test_presenca_so_no_optout_exclui():
    assert deve_excluir(
        "info@empresa.pt",
        lista_dgc=set(),
        log_optout={"info@empresa.pt"},
    ) is True


def test_ausente_nas_duas_listas_nao_exclui():
    assert deve_excluir(
        "reservas@hotel.pt",
        lista_dgc={"outro@x.pt"},
        log_optout={"mais@y.pt"},
    ) is False


def test_ausente_com_ambas_as_listas_vazias_nao_exclui():
    assert deve_excluir(
        "reservas@hotel.pt",
        lista_dgc=set(),
        log_optout=set(),
    ) is False


# --- deve_excluir: regressão normalização do LADO DO CONJUNTO ----------------
# O filtro é o último antes do envio; o custo de errar é uma coima (Lei 41/2004
# art. 13.º-B, fiscalização ANACOM). A fonte real (ex.: CSV da DGC) pode trazer
# casing/whitespace não-canónico que este módulo NÃO controla. Tem de falhar
# FECHADO: normalizar AMBOS os lados, nunca confiar no upstream.

def test_dgc_com_maiusculas_exclui_email_normalizado():
    # lista_dgc não-canónica ("Geral@X.PT") tem de bater com "geral@x.pt".
    assert deve_excluir(
        "geral@x.pt",
        lista_dgc={"Geral@X.PT"},
        log_optout=set(),
    ) is True


def test_dgc_com_espacos_exclui_email_normalizado():
    assert deve_excluir(
        "geral@x.pt",
        lista_dgc={" geral@x.pt "},
        log_optout=set(),
    ) is True


def test_optout_com_maiusculas_exclui_email_normalizado():
    assert deve_excluir(
        "info@e.pt",
        lista_dgc=set(),
        log_optout={"INFO@E.PT"},
    ) is True


def test_ambos_os_lados_nao_canonicos_batem():
    # Email de entrada E conjunto ambos "sujos" → continua a excluir.
    assert deve_excluir(
        "  Reservas@Hotel.PT ",
        lista_dgc={"RESERVAS@hotel.pt "},
        log_optout=set(),
    ) is True


# --- preparar_listas ---------------------------------------------------------

def test_preparar_listas_normaliza_ambos_os_conjuntos():
    dgc_norm, optout_norm = preparar_listas(
        {"Geral@X.PT", " info@y.pt "},
        {"OPTOUT@Z.PT"},
    )
    assert dgc_norm == frozenset({"geral@x.pt", "info@y.pt"})
    assert optout_norm == frozenset({"optout@z.pt"})


def test_preparar_listas_devolve_frozensets():
    dgc_norm, optout_norm = preparar_listas({"a@x.pt"}, {"b@y.pt"})
    assert isinstance(dgc_norm, frozenset)
    assert isinstance(optout_norm, frozenset)


# --- filtrar_optout ----------------------------------------------------------

def test_filtrar_optout_com_strings_remove_excluidos():
    contactos = ["a@x.pt", "b@x.pt", "c@x.pt"]
    resultado = list(
        filtrar_optout(contactos, lista_dgc={"b@x.pt"}, log_optout=set())
    )
    assert resultado == ["a@x.pt", "c@x.pt"]


def test_filtrar_optout_preserva_ordem_dos_nao_excluidos():
    contactos = ["z@x.pt", "a@x.pt", "m@x.pt", "b@x.pt"]
    resultado = list(
        filtrar_optout(
            contactos,
            lista_dgc={"a@x.pt"},
            log_optout={"b@x.pt"},
        )
    )
    assert resultado == ["z@x.pt", "m@x.pt"]


def test_filtrar_optout_normaliza_a_string_antes_de_cruzar():
    contactos = [" Geral@X.PT ", "ok@y.pt"]
    resultado = list(
        filtrar_optout(contactos, lista_dgc={"geral@x.pt"}, log_optout=set())
    )
    assert resultado == ["ok@y.pt"]


def test_filtrar_optout_exclui_mesmo_com_conjunto_nao_normalizado():
    # A lista injetada vem "suja"; o contacto excluído tem de cair na mesma.
    contactos = ["geral@x.pt", "ok@y.pt"]
    resultado = list(
        filtrar_optout(contactos, lista_dgc={"Geral@X.PT"}, log_optout={"  "})
    )
    assert resultado == ["ok@y.pt"]


def test_filtrar_optout_usa_email_generico_de_contacto_enderecavel():
    # Se o item tiver .email_generico (como ContactoEnderecavel), é esse o valor
    # cruzado — não o repr do objeto.
    excluido = SimpleNamespace(nr_registo="1", email_generico="Geral@X.PT")
    mantido = SimpleNamespace(nr_registo="2", email_generico="reservas@y.pt")
    resultado = list(
        filtrar_optout(
            [excluido, mantido],
            lista_dgc={"geral@x.pt"},
            log_optout=set(),
        )
    )
    assert resultado == [mantido]


def test_filtrar_optout_devolve_os_proprios_objetos_nao_copias():
    mantido = SimpleNamespace(nr_registo="2", email_generico="reservas@y.pt")
    (saida,) = list(
        filtrar_optout([mantido], lista_dgc=set(), log_optout=set())
    )
    assert saida is mantido


def test_filtrar_optout_vazio_devolve_vazio():
    assert list(filtrar_optout([], lista_dgc=set(), log_optout=set())) == []


# --- Regressão (sweep [baixo]): email em falta não derruba o lote ------------

def test_filtrar_optout_email_generico_none_nao_derruba_o_lote():
    # Um ContactoEnderecavel com email_generico=None não pode rebentar o gerador
    # (antes: AttributeError em .strip()); descarta-se e o resto do lote segue.
    partido = SimpleNamespace(nr_registo="1", email_generico=None)
    ok = SimpleNamespace(nr_registo="2", email_generico="reservas@y.pt")
    resultado = list(filtrar_optout([partido, ok], lista_dgc=set(), log_optout=set()))
    assert resultado == [ok]


def test_filtrar_optout_string_vazia_e_descartada():
    resultado = list(
        filtrar_optout(["", "   ", "ok@y.pt"], lista_dgc=set(), log_optout=set())
    )
    assert resultado == ["ok@y.pt"]
