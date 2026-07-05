"""Testes do módulo de minimização (descarte imediato — RGPD).

Regra que se prova aqui (ver ../app/compliance/RATIONALE.md §3, `minimizacao.py`):
`filtrar_enderecaveis` é um GERADOR que produz **apenas** os endereçáveis
(coletiva NIF 5/6 **E** email genérico). Tudo o resto é descartado de imediato,
nunca acumulado numa lista de rejeitados nem persistido. O `ContactoEnderecavel`
de saída **nunca** contém dados de pessoa singular.

Os testes são herméticos: injetam módulos falsos `app.compliance.nif` e
`app.compliance.email` em `sys.modules` (esses módulos têm testes próprios).
Assim o comportamento do filtro é validado de forma determinística e independente
do estado de construção das dependências.
"""
from __future__ import annotations

import inspect
import itertools
import sys
import types

import pytest

# --- Predicados falsos que espelham o contrato das dependências ------------

_GENERICOS = {
    "geral", "info", "reservas", "booking", "contacto",
    "alojamento", "geral2",
}


def _fake_e_enderecavel(nif: object) -> bool:
    """Coletiva 5/6: 9 dígitos numéricos e 1.º dígito ∈ {5,6}."""
    s = "" if nif is None else str(nif)
    return len(s) == 9 and s.isdigit() and s[0] in {"5", "6"}


def _fake_e_generico(email: object) -> bool:
    """Genérico = local-part na whitelist de negócio."""
    s = ("" if email is None else str(email)).strip().lower()
    if "@" not in s:
        return False
    return s.split("@", 1)[0] in _GENERICOS


@pytest.fixture(autouse=True)
def _injeta_dependencias_falsas(monkeypatch):
    """Substitui app.compliance.nif e app.compliance.email por falsos.

    Cobre o caso de os módulos reais ainda não existirem (construção paralela)
    e torna cada teste hermético face à classificação de NIF/email.
    """
    fake_nif = types.ModuleType("app.compliance.nif")
    fake_nif.e_enderecavel = _fake_e_enderecavel  # type: ignore[attr-defined]

    fake_email = types.ModuleType("app.compliance.email")
    fake_email.e_generico = _fake_e_generico  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "app.compliance.nif", fake_nif)
    monkeypatch.setitem(sys.modules, "app.compliance.email", fake_email)

    import app.compliance as pkg
    monkeypatch.setattr(pkg, "nif", fake_nif, raising=False)
    monkeypatch.setattr(pkg, "email", fake_email, raising=False)
    yield


# --- Fábricas de registos ---------------------------------------------------

def _reg(nr, *, tipo, nif, email, nome, concelho="Lisboa"):
    """Registo no formato RNAL aninhado."""
    return {
        "RNAL_Registo": {
            "NrRegisto": nr,
            "Concelho": concelho,
            "TitulardaExploracao": {
                "Tipo": tipo,
                "Contribuinte": nif,
                "Email": email,
                "Nome": nome,
            },
        }
    }


def _reg_achatado(nr, *, tipo, nif, email, nome, concelho="Lisboa"):
    """Mesmo registo, mas já achatado (sem o embrulho RNAL_Registo)."""
    return {
        "NrRegisto": nr,
        "Concelho": concelho,
        "Tipo": tipo,
        "Contribuinte": nif,
        "Email": email,
        "Nome": nome,
    }


# Amostras reutilizáveis -----------------------------------------------------

COLETIVA_GENERICA = dict(
    tipo="coletiva", nif="500000001", email="geral@empresa.pt", nome="Empresa Um, Lda"
)
COLETIVA_GENERICA_2 = dict(
    tipo="coletiva", nif="600000002", email="reservas@dois.pt", nome="Dois SA"
)
COLETIVA_PESSOAL = dict(
    tipo="coletiva", nif="500000003", email="joao.silva@tres.pt", nome="Tres Lda"
)
SINGULAR_GENERICO = dict(
    tipo="singular", nif="123456789", email="info@quatro.pt", nome="Ana Quatro"
)
SINGULAR_PESSOAL = dict(
    tipo="singular", nif="234567890", email="ana.quatro@mail.pt", nome="Ana Quatro"
)
ENI_45 = dict(
    tipo="singular", nif="450000006", email="geral@cinco.pt", nome="Rui Cinco"
)


def _import_modulo():
    from app.compliance import minimizacao
    return minimizacao


# --- Testes ----------------------------------------------------------------

def test_filtrar_enderecaveis_e_um_gerador():
    m = _import_modulo()
    resultado = m.filtrar_enderecaveis([])
    assert inspect.isgenerator(resultado)
    assert list(resultado) == []


def test_lote_misto_so_saem_coletivas_genericas():
    """Trap principal: só passam coletivas 5/6 COM email genérico."""
    m = _import_modulo()
    lote = [
        _reg(1, **COLETIVA_GENERICA),
        _reg(2, **SINGULAR_PESSOAL),
        _reg(3, **COLETIVA_PESSOAL),
        _reg(4, **SINGULAR_GENERICO),
        _reg(5, **COLETIVA_GENERICA_2),
        _reg(6, **ENI_45),
    ]
    saida = list(m.filtrar_enderecaveis(lote))
    assert [c.nr_registo for c in saida] == [1, 5]


def test_coletiva_com_email_pessoal_e_descartada():
    m = _import_modulo()
    saida = list(m.filtrar_enderecaveis([_reg(3, **COLETIVA_PESSOAL)]))
    assert saida == []


def test_singular_mesmo_com_email_generico_e_descartada():
    """O portão é o NIF: singular nunca passa, ainda que o email seja genérico."""
    m = _import_modulo()
    saida = list(m.filtrar_enderecaveis([_reg(4, **SINGULAR_GENERICO)]))
    assert saida == []


def test_eni_prefixo_45_e_descartado():
    m = _import_modulo()
    saida = list(m.filtrar_enderecaveis([_reg(6, **ENI_45)]))
    assert saida == []


def test_output_nunca_contem_email_ou_nif_de_pessoa_singular():
    """Trap RGPD: nenhum email/NIF de singular pode aparecer em campo nenhum."""
    m = _import_modulo()
    lote = [
        _reg(1, **COLETIVA_GENERICA),
        _reg(2, **SINGULAR_PESSOAL),
        _reg(4, **SINGULAR_GENERICO),
        _reg(5, **COLETIVA_GENERICA_2),
        _reg(6, **ENI_45),
    ]
    saida = list(m.filtrar_enderecaveis(lote))

    proibidos = {
        SINGULAR_PESSOAL["nif"], SINGULAR_PESSOAL["email"],
        SINGULAR_GENERICO["nif"], SINGULAR_GENERICO["email"],
        ENI_45["nif"],  # email do ENI é genérico mas o NIF 45 é de singular
    }
    for c in saida:
        campos = {c.nr_registo, c.nif, c.nome_coletiva, c.email_generico, c.concelho}
        assert not (campos & proibidos)


def test_entrada_malformada_e_descartada_sem_derrubar_o_lote():
    """Regressão (sweep [baixo]): um registo não-Mapping (None, str, int, lista)
    não pode rebentar o gerador — descarta-se e continua o lote."""
    m = _import_modulo()
    lote = [
        None,
        "lixo",
        123,
        _reg(1, **COLETIVA_GENERICA),
        [],
        {},                       # dict vazio: sem NIF -> descartado, sem crash
        _reg(5, **COLETIVA_GENERICA_2),
    ]
    saida = list(m.filtrar_enderecaveis(lote))
    assert [c.nr_registo for c in saida] == [1, 5]


def test_aceita_formato_achatado():
    m = _import_modulo()
    saida = list(m.filtrar_enderecaveis([_reg_achatado(7, **COLETIVA_GENERICA)]))
    assert len(saida) == 1
    c = saida[0]
    assert c.nr_registo == 7
    assert c.nif == COLETIVA_GENERICA["nif"]
    assert c.email_generico == COLETIVA_GENERICA["email"]
    assert c.nome_coletiva == COLETIVA_GENERICA["nome"]


def test_contacto_guarda_apenas_o_minimo_com_proveniencia():
    m = _import_modulo()
    (c,) = list(m.filtrar_enderecaveis([_reg(1, concelho="Porto", **COLETIVA_GENERICA)]))
    assert c.nr_registo == 1
    assert c.nif == COLETIVA_GENERICA["nif"]
    assert c.nome_coletiva == COLETIVA_GENERICA["nome"]
    assert c.email_generico == COLETIVA_GENERICA["email"]
    assert c.concelho == "Porto"
    assert c.proveniencia == "rnal:email_generico_publicado"

    # O objeto guarda o mínimo: exatamente estes 6 campos, nada de "Tipo",
    # "nome_titular" ou outro campo que pudesse carregar dados de singular.
    from dataclasses import fields
    nomes = {f.name for f in fields(c)}
    assert nomes == {
        "nr_registo", "nif", "nome_coletiva",
        "email_generico", "concelho", "proveniencia",
    }


def test_nao_faz_pre_scan_consome_input_preguicosamente():
    """Puxar 1 endereçável toca só nos registos necessários (streaming),
    não pré-varre a lista inteira nem constrói coleções de rejeitados."""
    m = _import_modulo()
    tocados: list[int] = []

    def rastreador(regs):
        for r in regs:
            tocados.append(r["RNAL_Registo"]["NrRegisto"])
            yield r

    regs = [
        _reg(1, **COLETIVA_GENERICA),
        _reg(2, **COLETIVA_GENERICA_2),
        _reg(3, **COLETIVA_GENERICA),
    ]
    g = m.filtrar_enderecaveis(rastreador(regs))
    primeiro = next(g)
    assert primeiro.nr_registo == 1
    # Só o 1.º registo foi consumido para produzir o 1.º endereçável.
    assert tocados == [1]


def test_lazy_sobre_entrada_infinita_nao_materializa():
    """Sobre um gerador infinito com rejeitados intercalados, pedir N
    endereçáveis termina — prova que descarta em fluxo, sem acumular tudo."""
    m = _import_modulo()

    def fluxo_infinito():
        i = 0
        while True:
            i += 1
            # alterna: rejeitado (singular) e endereçável (coletiva genérica)
            if i % 2:
                yield _reg(i, **SINGULAR_PESSOAL)
            else:
                yield _reg(i, **COLETIVA_GENERICA)

    saida = list(itertools.islice(m.filtrar_enderecaveis(fluxo_infinito()), 3))
    assert len(saida) == 3
    assert all(c.nif == COLETIVA_GENERICA["nif"] for c in saida)
