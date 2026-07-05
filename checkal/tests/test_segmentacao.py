"""Testes do segmentador de campanhas (FDS 6) — o núcleo de compliance no fluxo.

Regra que se prova aqui (SPEC-FDS6.md §segmentacao, RATIONALE.md §3):
`segmentar(registos)` separa um lote MISTO do RNAL em três destinos, usando o
**núcleo de compliance** (`app.compliance.*`) como autoridade:

    cold_email  — SÓ coletiva (NIF 5/6) COM email genérico E não oposta (DGC/opt-out)
    carta       — singulares e coletivas-com-email-pessoal (canal postal), NUNCA cold
    descartados — contagem do que não entra em nenhum canal (malformado, oposto, sem nome)

Traps invioláveis (compliance legal, não só qualidade):
  - NENHUM singular/ENI entra em cold, ainda que o email seja genérico (o portão é o NIF).
  - NENHUM email pessoal entra em cold.
  - NENHUM email — de quem quer que seja — viaja no ramo `carta` (canal postal;
    materializar emails de singulares recriaria a lista de marketing proibida).
  - Contacto na oposição DGC / opt-out é excluído do cold (Lei 41/2004, art. 13.º-B).
  - Cada contacto cold leva proveniência registada (prova de lookup dirigido, não scraping).

Os testes correm sobre os módulos de compliance REAIS (integração deliberada — é a
reutilização do núcleo que se está a validar), com NIFs/emails inequívocos.
"""
from __future__ import annotations

from dataclasses import fields

import pytest


def _import_modulo():
    from app.campanhas import segmentacao
    return segmentacao


# --- Fábricas de registos RNAL ---------------------------------------------

def _reg(nr, *, tipo, nif, email, nome, concelho="Lisboa", endereco="Rua Um, 1",
         cod_postal="1000-001", localidade="Lisboa", freguesia="Sé"):
    """Registo no formato RNAL aninhado (com bloco de morada para a carta)."""
    return {
        "RNAL_Registo": {
            "NrRegisto": nr,
            "Concelho": concelho,
            "Endereco": endereco,
            "CodPostal": cod_postal,
            "Localidade": localidade,
            "Freguesia": freguesia,
            "TitulardaExploracao": {
                "Tipo": tipo,
                "Contribuinte": nif,
                "Email": email,
                "Nome": nome,
            },
        }
    }


def _reg_flat(nr, *, tipo, nif, email, nome, concelho="Lisboa", endereco="Rua Um, 1",
              cod_postal="1000-001"):
    """Mesmo registo, já achatado (sem o embrulho RNAL_Registo)."""
    return {
        "NrRegisto": nr,
        "Concelho": concelho,
        "Endereco": endereco,
        "CodPostal": cod_postal,
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
    tipo="coletiva", nif="500000003", email="joao.silva@tres.pt", nome="Tres, Lda"
)
SINGULAR_PESSOAL = dict(
    tipo="singular", nif="123456789", email="ana.quatro@mail.pt", nome="Ana Quatro"
)
SINGULAR_GENERICO = dict(
    tipo="singular", nif="234567890", email="info@cinco.pt", nome="Rui Cinco"
)
ENI_8 = dict(
    tipo="singular", nif="800000005", email="geral@seis.pt", nome="Empresario Seis"
)
ENI_45 = dict(
    tipo="singular", nif="450000006", email="reservas@sete.pt", nome="Rui Sete"
)


# --- Estrutura de saída -----------------------------------------------------

def test_segmentar_de_lote_vazio():
    m = _import_modulo()
    seg = m.segmentar([])
    assert seg.cold_email == []
    assert seg.carta == []
    assert seg.descartados == 0


def test_segmentos_tem_os_tres_campos():
    m = _import_modulo()
    nomes = {f.name for f in fields(m.Segmentos)}
    assert nomes == {"cold_email", "carta", "descartados"}


# --- O caso central: lote misto --------------------------------------------

def _lote_misto():
    return [
        _reg(1, **COLETIVA_GENERICA),     # cold
        _reg(2, **SINGULAR_PESSOAL),      # carta
        _reg(3, **COLETIVA_PESSOAL),      # carta (coletiva mas email pessoal)
        _reg(4, **SINGULAR_GENERICO),     # carta (singular nunca vai a cold)
        _reg(5, **COLETIVA_GENERICA_2),   # cold
        _reg(6, **ENI_8),                 # carta (ENI = singular)
        _reg(7, **ENI_45),                # carta (não-residente singular)
    ]


def test_so_coletivas_genericas_entram_em_cold():
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())
    assert sorted(c.nr_registo for c in seg.cold_email) == [1, 5]


def test_singulares_e_coletiva_pessoal_vao_para_carta():
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())
    assert sorted(p.nr_registo for p in seg.carta) == [2, 3, 4, 6, 7]


def test_nenhum_singular_ou_pessoal_entra_em_cold():
    """Trap RGPD: nenhum dado de singular nem email pessoal pode aparecer no cold."""
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())

    proibidos = {
        SINGULAR_PESSOAL["nif"], SINGULAR_PESSOAL["email"],
        SINGULAR_GENERICO["nif"], SINGULAR_GENERICO["email"],
        COLETIVA_PESSOAL["email"],  # email pessoal de coletiva também é proibido em cold
        ENI_8["nif"], ENI_8["email"],
        ENI_45["nif"], ENI_45["email"],
    }
    for c in seg.cold_email:
        campos = {c.nr_registo, c.nif, c.nome_coletiva, c.email_generico, c.concelho}
        assert not (campos & proibidos)


def test_singular_com_email_generico_nunca_vai_a_cold():
    """O portão é o NIF: singular com email genérico -> carta, jamais cold."""
    m = _import_modulo()
    seg = m.segmentar([_reg(4, **SINGULAR_GENERICO)])
    assert seg.cold_email == []
    assert [p.nr_registo for p in seg.carta] == [4]


def test_eni_prefixo_8_e_45_nunca_vao_a_cold():
    m = _import_modulo()
    seg = m.segmentar([_reg(6, **ENI_8), _reg(7, **ENI_45)])
    assert seg.cold_email == []
    assert sorted(p.nr_registo for p in seg.carta) == [6, 7]


# --- Ramo carta NUNCA transporta emails ------------------------------------

def test_carta_nunca_transporta_email():
    """O canal carta é postal: NENHUM valor de nenhum prospeto pode ser um email.

    Materializar o email de um singular numa estrutura de saída recriaria a lista
    de marketing eletrónico proibida. A carta viaja por morada, não por email.
    """
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())
    assert seg.carta, "esperava prospetos de carta neste lote"

    nomes_campos = {f.name for f in fields(m.ProspetoCarta)}
    assert "email" not in nomes_campos  # o dataclass nem sequer tem campo de email

    for p in seg.carta:
        for f in fields(p):
            valor = getattr(p, f.name)
            assert "@" not in str(valor), f"email vazou para a carta em {f.name}={valor!r}"


def test_carta_preserva_nome_e_morada():
    m = _import_modulo()
    seg = m.segmentar([_reg(2, concelho="Porto", endereco="Rua do Sol, 3",
                            cod_postal="4000-002", **SINGULAR_PESSOAL)])
    (p,) = seg.carta
    assert p.nr_registo == 2
    assert p.nome == SINGULAR_PESSOAL["nome"]
    assert p.endereco == "Rua do Sol, 3"
    assert p.cod_postal == "4000-002"
    assert p.concelho == "Porto"
    assert p.tipo == "singular"
    assert p.proveniencia  # proveniência (morada publicada) registada


# --- Opt-out / oposição DGC no ramo cold -----------------------------------

def test_opt_out_dgc_exclui_do_cold():
    """Coletiva genérica na oposição DGC sai do cold e NÃO cai na carta."""
    m = _import_modulo()
    seg = m.segmentar(
        [_reg(1, **COLETIVA_GENERICA), _reg(5, **COLETIVA_GENERICA_2)],
        lista_dgc={COLETIVA_GENERICA_2["email"]},
    )
    assert [c.nr_registo for c in seg.cold_email] == [1]
    # a oposta não vai para carta (respeito ao opt-out em qualquer canal)
    assert all(p.nr_registo != 5 for p in seg.carta)
    assert seg.descartados == 1


def test_opt_out_log_interno_exclui_do_cold():
    m = _import_modulo()
    seg = m.segmentar(
        [_reg(1, **COLETIVA_GENERICA), _reg(5, **COLETIVA_GENERICA_2)],
        log_optout={COLETIVA_GENERICA["email"]},
    )
    assert [c.nr_registo for c in seg.cold_email] == [5]
    assert seg.descartados == 1


def test_opt_out_normaliza_antes_de_cruzar():
    """A lista DGC pode vir com casing/espacos; o cruzamento normaliza os dois lados."""
    m = _import_modulo()
    seg = m.segmentar(
        [_reg(1, **COLETIVA_GENERICA)],
        lista_dgc={"  GERAL@EMPRESA.PT "},
    )
    assert seg.cold_email == []
    assert seg.descartados == 1


# --- Proveniência do cold ---------------------------------------------------

def test_cada_cold_tem_proveniencia_registada():
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())
    assert seg.cold_email
    for c in seg.cold_email:
        assert c.proveniencia  # não vazia — prova de lookup dirigido, não scraping
        assert "rnal" in c.proveniencia.lower()


# --- Robustez ---------------------------------------------------------------

def test_entrada_malformada_conta_como_descartada_sem_crashar():
    m = _import_modulo()
    lote = [
        None, "lixo", 123, [],
        _reg(1, **COLETIVA_GENERICA),
        {},  # dict vazio: sem NIF nem nome -> descartado
        _reg(5, **COLETIVA_GENERICA_2),
    ]
    seg = m.segmentar(lote)
    assert sorted(c.nr_registo for c in seg.cold_email) == [1, 5]
    # 4 não-Mapping + 1 dict vazio (sem nome para carta) = 5 descartados
    assert seg.descartados == 5


def test_aceita_formato_achatado():
    m = _import_modulo()
    seg = m.segmentar([
        _reg_flat(10, **COLETIVA_GENERICA),
        _reg_flat(11, **SINGULAR_PESSOAL),
    ])
    assert [c.nr_registo for c in seg.cold_email] == [10]
    assert [p.nr_registo for p in seg.carta] == [11]


def test_aceita_gerador_de_entrada():
    """A entrada pode ser um gerador de uso único; não pode ser consumida duas vezes."""
    m = _import_modulo()

    def fluxo():
        yield _reg(1, **COLETIVA_GENERICA)
        yield _reg(2, **SINGULAR_PESSOAL)

    seg = m.segmentar(fluxo())
    assert [c.nr_registo for c in seg.cold_email] == [1]
    assert [p.nr_registo for p in seg.carta] == [2]


def test_contagem_total_fecha():
    """cold + carta + descartados = nº de entradas do lote (nada se perde nem duplica)."""
    m = _import_modulo()
    lote = _lote_misto() + [None, {}]
    seg = m.segmentar(lote)
    assert len(seg.cold_email) + len(seg.carta) + seg.descartados == len(lote)


def test_ordem_preservada_no_cold_e_na_carta():
    m = _import_modulo()
    seg = m.segmentar(_lote_misto())
    assert [c.nr_registo for c in seg.cold_email] == [1, 5]
    assert [p.nr_registo for p in seg.carta] == [2, 3, 4, 6, 7]
