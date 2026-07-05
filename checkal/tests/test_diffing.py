"""Testes do diffing puro de varrimentos RNAL — app.rnal.diffing.

Contrato (SPEC-FDS1.md §diffing):
  diff_varrimento(estado_atual, scan, concelhos_ok) -> list[EventoDiff]

  - Presente e desconhecido → evento ``novo``.
  - Presente com hash diferente → evento ``alterado`` (+ ``campos_alterados``).
  - Estava ``desaparecido`` e reaparece no scan → evento ``reapareceu``.
  - Ausente → **regra dos 2 varrimentos** (``config.REGRA_N_VARRIMENTOS``): só
    gera ``desaparecido`` à N-ésima ausência consecutiva E com o concelho do
    registo em ``concelhos_ok`` (resposta válida). Uma ausência isolada não gera
    evento. Ausência num concelho FORA de ``concelhos_ok`` (varrimento parcial)
    é **ignorada** — nem conta nem marca (evita falso "cancelado" por timeout).

Um falso ``desaparecido`` destrói o produto: por isso cobrem-se todos os ramos
com dados mutados. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.config as config
from app.rnal.diffing import (
    EventoDiff,
    RegistoEstado,
    RegistoNovo,
    diff_varrimento,
)
from app.rnal.hashing import CAMPOS_RELEVANTES, hash_campos
from app.rnal.schema import parse_registo


# --------------------------------------------------------------------------
#  Helpers de construção de dados
# --------------------------------------------------------------------------
def _campos(**alteracoes) -> dict:
    """Dict achatado canónico dos campos relevantes; `alteracoes` sobrepõe-se."""
    base = {
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
    }
    base.update(alteracoes)
    return base


def _por_nr(eventos: list[EventoDiff]) -> dict[int, EventoDiff]:
    return {ev.nr_registo: ev for ev in eventos}


# --------------------------------------------------------------------------
#  Regressão (red-team [baixo]): a porta concelhos_ok tem de bater por caixa/
#  espaços — senão um mismatch de nome silencia um cancelamento real.
# --------------------------------------------------------------------------
def test_concelho_ok_bate_apesar_de_caixa_diferente_e_conta_ausencia():
    # Estado em "Faro" (como a API grava); concelhos_ok vem "faro"/" FARO ".
    # A ausência TEM de contar (não ser ignorada), senão o cancelamento nunca
    # é detetado (falso silêncio).
    estado = {10: RegistoEstado.de_campos(_campos(concelho="Faro"), ausencias=1)}
    eventos = diff_varrimento(estado, {}, {" FARO "})
    assert _tipos(eventos) == [("desaparecido", 10)]


def test_concelho_diferente_normalizado_continua_a_gerar_desaparecido():
    estado = {11: RegistoEstado.de_campos(_campos(concelho="Vila Nova de Gaia"), ausencias=1)}
    eventos = diff_varrimento(estado, {}, {"vila nova de gaia"})
    assert _tipos(eventos) == [("desaparecido", 11)]


def test_concelho_realmente_ausente_da_lista_continua_ignorado():
    # Guarda de não-regressão: se o concelho NÃO respondeu de todo, a ausência
    # continua ignorada (varrimento parcial) — a normalização não relaxa isto.
    estado = {12: RegistoEstado.de_campos(_campos(concelho="Faro"), ausencias=1)}
    eventos = diff_varrimento(estado, {}, {"Lisboa"})
    assert eventos == []


def _tipos(eventos: list[EventoDiff]) -> list[tuple[str, int]]:
    return [(ev.tipo, ev.nr_registo) for ev in eventos]


# --------------------------------------------------------------------------
#  Registo novo
# --------------------------------------------------------------------------
def test_registo_no_scan_e_desconhecido_gera_novo():
    scan = {100: RegistoNovo.de_campos(_campos())}
    eventos = diff_varrimento({}, scan, {"Faro"})
    assert _tipos(eventos) == [("novo", 100)]
    assert eventos[0].campos_alterados is None


def test_estado_vazio_todos_os_registos_sao_novos():
    scan = {
        1: RegistoNovo.de_campos(_campos()),
        2: RegistoNovo.de_campos(_campos(concelho="Lisboa")),
    }
    eventos = diff_varrimento({}, scan, {"Faro", "Lisboa"})
    assert _tipos(eventos) == [("novo", 1), ("novo", 2)]


# --------------------------------------------------------------------------
#  Registo presente sem alteração
# --------------------------------------------------------------------------
def test_registo_presente_com_mesmo_hash_nao_gera_evento():
    campos = _campos()
    estado = {100: RegistoEstado.de_campos(campos)}
    scan = {100: RegistoNovo.de_campos(campos)}
    assert diff_varrimento(estado, scan, {"Faro"}) == []


def test_normalizacao_nao_produz_falso_alterado():
    # nr_camas 2 (int) vs "2" (str): mesmo hash → NÃO é alteração.
    estado = {100: RegistoEstado.de_campos(_campos(nr_camas=2))}
    scan = {100: RegistoNovo.de_campos(_campos(nr_camas="2"))}
    assert diff_varrimento(estado, scan, {"Faro"}) == []


# --------------------------------------------------------------------------
#  Registo alterado (diff de campos)
# --------------------------------------------------------------------------
def test_registo_com_hash_diferente_gera_alterado():
    estado = {100: RegistoEstado.de_campos(_campos(nome_alojamento="Casa do Mar"))}
    scan = {100: RegistoNovo.de_campos(_campos(nome_alojamento="Casa Nova"))}
    eventos = diff_varrimento(estado, scan, {"Faro"})
    assert _tipos(eventos) == [("alterado", 100)]
    assert eventos[0].campos_alterados == {"nome_alojamento": ["Casa do Mar", "Casa Nova"]}


def test_alterado_lista_apenas_os_campos_que_mudaram():
    estado = {100: RegistoEstado.de_campos(_campos())}
    scan = {100: RegistoNovo.de_campos(_campos(email="novo@oasis.pt", nr_camas=5))}
    eventos = diff_varrimento(estado, scan, {"Faro"})
    assert eventos[0].tipo == "alterado"
    assert eventos[0].campos_alterados == {
        "nr_camas": [2, 5],
        "email": ["geral@oasis.pt", "novo@oasis.pt"],
    }


def test_alterado_de_concelho_reporta_o_campo_concelho():
    estado = {100: RegistoEstado.de_campos(_campos(concelho="Faro"))}
    scan = {100: RegistoNovo.de_campos(_campos(concelho="Olhão"))}
    eventos = diff_varrimento(estado, scan, {"Faro", "Olhão"})
    assert eventos[0].tipo == "alterado"
    assert eventos[0].campos_alterados == {"concelho": ["Faro", "Olhão"]}


def test_campos_alterados_e_json_serializavel():
    import json

    estado = {100: RegistoEstado.de_campos(_campos())}
    scan = {100: RegistoNovo.de_campos(_campos(nr_utentes=8))}
    eventos = diff_varrimento(estado, scan, {"Faro"})
    # não rebenta a serializar (colunas JSON portáteis)
    assert json.loads(json.dumps(eventos[0].campos_alterados)) == {"nr_utentes": [4, 8]}


# --------------------------------------------------------------------------
#  Regra dos 2 varrimentos — ausências
# --------------------------------------------------------------------------
def test_uma_ausencia_com_concelho_ok_nao_gera_evento():
    # Estado sem ausências prévias; falta agora (1.ª ausência). Sem evento.
    estado = {100: RegistoEstado.de_campos(_campos(), ausencias=0)}
    eventos = diff_varrimento(estado, {}, {"Faro"})
    assert eventos == []


def test_duas_ausencias_consecutivas_com_concelho_ok_gera_desaparecido():
    # Já faltou 1 vez (ausencias=1); falta de novo → 2.ª ausência → desaparecido.
    estado = {100: RegistoEstado.de_campos(_campos(), ausencias=1)}
    eventos = diff_varrimento(estado, {}, {"Faro"})
    assert _tipos(eventos) == [("desaparecido", 100)]
    assert eventos[0].campos_alterados is None


def test_ausencia_com_concelho_fora_de_concelhos_ok_e_ignorada():
    # Concelho do registo NÃO devolveu resposta (varrimento parcial): a ausência
    # não conta, mesmo já estando no limiar. Guarda-chuva contra falso cancelado.
    estado = {100: RegistoEstado.de_campos(_campos(concelho="Porto"), ausencias=1)}
    eventos = diff_varrimento(estado, {}, {"Faro"})  # Porto fora de concelhos_ok
    assert eventos == []


def test_primeira_ausencia_em_concelho_fora_ok_tambem_ignorada():
    estado = {100: RegistoEstado.de_campos(_campos(concelho="Porto"), ausencias=0)}
    eventos = diff_varrimento(estado, {}, {"Faro"})
    assert eventos == []


def test_desaparecido_respeita_regra_n_varrimentos(monkeypatch):
    # Prova que o limiar vem de config e não está fixo em 2.
    monkeypatch.setattr(config, "REGRA_N_VARRIMENTOS", 3)
    estado_1 = {100: RegistoEstado.de_campos(_campos(), ausencias=1)}  # →2, < 3
    assert diff_varrimento(estado_1, {}, {"Faro"}) == []
    estado_2 = {100: RegistoEstado.de_campos(_campos(), ausencias=2)}  # →3, == 3
    assert _tipos(diff_varrimento(estado_2, {}, {"Faro"})) == [("desaparecido", 100)]


def test_registo_ja_desaparecido_e_ainda_ausente_nao_regenera_evento():
    # Sem duplicados: quem já está marcado desaparecido e continua ausente cala-se.
    estado = {100: RegistoEstado.de_campos(_campos(), ausencias=2, desaparecido=True)}
    eventos = diff_varrimento(estado, {}, {"Faro"})
    assert eventos == []


# --------------------------------------------------------------------------
#  Reaparecimento
# --------------------------------------------------------------------------
def test_reaparecimento_apos_desaparecido_gera_reapareceu():
    campos = _campos()
    estado = {100: RegistoEstado.de_campos(campos, ausencias=2, desaparecido=True)}
    scan = {100: RegistoNovo.de_campos(campos)}
    eventos = diff_varrimento(estado, scan, {"Faro"})
    assert _tipos(eventos) == [("reapareceu", 100)]


def test_reaparecimento_com_dados_alterados_continua_reapareceu():
    # Reaparecer é o facto saliente: mesmo com dados diferentes, é `reapareceu`,
    # não `alterado` (um só evento).
    estado = {100: RegistoEstado.de_campos(_campos(), ausencias=2, desaparecido=True)}
    scan = {100: RegistoNovo.de_campos(_campos(nome_alojamento="Renovada"))}
    eventos = diff_varrimento(estado, scan, {"Faro"})
    assert _tipos(eventos) == [("reapareceu", 100)]


# --------------------------------------------------------------------------
#  Presente não é filtrado por concelhos_ok
# --------------------------------------------------------------------------
def test_presente_alterado_nao_e_filtrado_por_concelhos_ok():
    # A porta de concelhos_ok só governa AUSÊNCIAS. Um registo presente processa-se
    # sempre (se veio no scan, o concelho respondeu).
    estado = {100: RegistoEstado.de_campos(_campos(concelho="Faro"))}
    scan = {100: RegistoNovo.de_campos(_campos(concelho="Faro", nr_camas=9))}
    eventos = diff_varrimento(estado, scan, set())  # concelhos_ok vazio de propósito
    assert _tipos(eventos) == [("alterado", 100)]


# --------------------------------------------------------------------------
#  Determinismo / ordenação
# --------------------------------------------------------------------------
def test_eventos_ordenados_por_nr_registo():
    scan = {
        30: RegistoNovo.de_campos(_campos()),
        10: RegistoNovo.de_campos(_campos()),
        20: RegistoNovo.de_campos(_campos()),
    }
    eventos = diff_varrimento({}, scan, {"Faro"})
    assert [ev.nr_registo for ev in eventos] == [10, 20, 30]


# --------------------------------------------------------------------------
#  Varrimento completo com dados mutados (aceitação do diffing)
# --------------------------------------------------------------------------
def test_varrimento_completo_com_dados_mutados():
    """1 novo, 1 alterado, 1 desaparecido (2.ª ausência), 1 ausência isolada,
    1 inalterado e 1 ausência num concelho parcial (ignorada)."""
    estado = {
        1: RegistoEstado.de_campos(_campos()),                       # ficará inalterado
        2: RegistoEstado.de_campos(_campos(email="a@b.pt")),         # alterado
        4: RegistoEstado.de_campos(_campos(), ausencias=1),          # 2.ª ausência → desaparecido
        5: RegistoEstado.de_campos(_campos(), ausencias=0),          # 1.ª ausência → nada
        6: RegistoEstado.de_campos(_campos(concelho="Guarda"), ausencias=1),  # parcial → ignorado
    }
    scan = {
        1: RegistoNovo.de_campos(_campos()),                         # igual
        2: RegistoNovo.de_campos(_campos(email="novo@b.pt")),        # alterado
        3: RegistoNovo.de_campos(_campos()),                         # novo
    }
    concelhos_ok = {"Faro"}  # Guarda ausente da lista → registo 6 ignorado

    eventos = diff_varrimento(estado, scan, concelhos_ok)

    assert _tipos(eventos) == [
        ("alterado", 2),
        ("novo", 3),
        ("desaparecido", 4),
    ]
    assert _por_nr(eventos)[2].campos_alterados == {"email": ["a@b.pt", "novo@b.pt"]}


# --------------------------------------------------------------------------
#  Fábricas de RegistoNovo / RegistoEstado
# --------------------------------------------------------------------------
def test_registonovo_de_campos_calcula_hash_com_hashing():
    campos = _campos()
    novo = RegistoNovo.de_campos(campos)
    assert novo.hash_campos == hash_campos(campos)
    assert novo.concelho == "Faro"


def test_registoestado_de_campos_calcula_hash_com_hashing():
    campos = _campos()
    estado = RegistoEstado.de_campos(campos, ausencias=3, desaparecido=True)
    assert estado.hash_campos == hash_campos(campos)
    assert estado.concelho == "Faro"
    assert estado.ausencias_consecutivas == 3
    assert estado.desaparecido is True


def test_registonovo_de_registo_a_partir_de_registornal():
    bruto = {
        "RNAL_Registo": {
            "NrRegisto": "100031/AL",
            "NomeAlojamento": "Casa do Sol",
            "Modalidade": "Estabelecimento de hospedagem",
            "NrCamas": 2,
            "NrUtentes": "4",
            "Endereco": "Rua X",
            "CodPostal": "8000-444",
            "Freguesia": "Sé",
            "Concelho": "Faro",
            "Distrito": "Faro",
            "TitulardaExploracao": {
                "Tipo": "Pessoa coletiva",
                "Nome": "Oasis Lda",
                "Contribuinte": "513029591",
                "Email": "geral@oasis.pt",
            },
            "DTMNFR": "080508",
        }
    }
    reg = parse_registo(bruto)
    novo = RegistoNovo.de_registo(reg)
    assert novo.concelho == "Faro"
    assert novo.hash_campos == hash_campos(reg)


def test_registoestado_de_linha_le_atributos_de_uma_linha_orm():
    linha = SimpleNamespace(
        hash_campos="abc",
        ausencias_consecutivas=1,
        desaparecido_em=None,
        **_campos(),  # inclui concelho="Faro"
    )
    estado = RegistoEstado.de_linha(linha)
    assert estado.hash_campos == "abc"
    assert estado.concelho == "Faro"
    assert estado.ausencias_consecutivas == 1
    assert estado.desaparecido is False


def test_registoestado_de_linha_desaparecido_quando_ha_data():
    from datetime import datetime, timezone

    linha = SimpleNamespace(
        hash_campos="abc",
        ausencias_consecutivas=2,
        desaparecido_em=datetime(2026, 7, 1, tzinfo=timezone.utc),
        **_campos(),  # inclui concelho="Faro"
    )
    estado = RegistoEstado.de_linha(linha)
    assert estado.desaparecido is True


# --------------------------------------------------------------------------
#  Pureza: a função não lê nem escreve nada além dos argumentos
# --------------------------------------------------------------------------
def test_diff_nao_muta_os_argumentos():
    estado_reg = RegistoEstado.de_campos(_campos(), ausencias=1)
    estado = {100: estado_reg}
    diff_varrimento(estado, {}, {"Faro"})
    # o estado de entrada não é alterado pelo diffing (é ingest quem persiste)
    assert estado[100].ausencias_consecutivas == 1
    assert estado[100].desaparecido is False
