"""Testes do relatório inicial de onboarding — app.relatorio (FDS 3, SPEC-FDS3 §relatorio).

Contrato (SPEC-FDS3.md §relatorio):
  - `gerar_relatorio_inicial(cliente, detalhe, *, contencao=None, regulamentos=())
    -> RelatorioInicial`: estrutura de dados factual (PT-PT, sem inventar) com as secções
    **estado do registo**, **seguro**, **área de contenção do concelho** e **regulamentos
    ativos**. As duas últimas toleram vazio (o FDS 4 é que as preenche).
  - `render_pdf(relatorio) -> bytes` (fpdf2): PDF não vazio, começa por `%PDF`.

Disciplina inviolável verificada aqui:
  - **G4:** o relatório NUNCA afirma "cancelado" a partir do detalhe. Para os estados
    `nao_encontrado`/`indeterminado` a copy é uma ressalva ("requer confirmação"), nunca
    uma afirmação de cancelamento — o teste garante que o radical "cancelad" não aparece.
  - **Tolera dados em falta:** contenção/regulamentos vazios e detalhe sem seguro ou
    indeterminado não rebentam nem o gerador nem o render.

Zero rede, zero BD: o `cliente`/`registo` são dublês duck-typed (`SimpleNamespace`) e o
`detalhe` é um `DetalheRegisto` real. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
)
import app.relatorio as relatorio
from app.relatorio import (
    SECAO_CONTENCAO,
    SECAO_ESTADO,
    SECAO_REGULAMENTOS,
    SECAO_SEGURO,
    RelatorioInicial,
    gerar_relatorio_inicial,
    render_pdf,
)

HOJE = date(2026, 7, 5)


# ==========================================================================
#  Dublês (duck-typed) — sem ORM, sem BD
# ==========================================================================
def _cliente(
    nr: int = 100031,
    nome_al: str = "BAIXA DE FARO ROOFTOP",
    concelho: str = "Faro",
    nome_cli: str = "Ana Cliente",
):
    registo = SimpleNamespace(
        nr_registo=nr, nome_alojamento=nome_al, concelho=concelho
    )
    return SimpleNamespace(
        nome=nome_cli, email="ana@example.pt", registos=[registo]
    )


def _detalhe_ativo(nr: int = 100031) -> DetalheRegisto:
    return DetalheRegisto(
        nr_registo=nr,
        estado=ESTADO_ATIVO,
        seguro_companhia="Zurich",
        seguro_apolice="009238995",
        seguro_inicio=date(2025, 12, 12),
        seguro_validade=date(2026, 12, 11),
    )


# ==========================================================================
#  Estrutura: secções presentes
# ==========================================================================
def test_relatorio_tem_as_quatro_seccoes():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    assert isinstance(rel, RelatorioInicial)
    titulos = [s.titulo for s in rel.secoes]
    assert SECAO_ESTADO in titulos
    assert SECAO_SEGURO in titulos
    assert SECAO_CONTENCAO in titulos
    assert SECAO_REGULAMENTOS in titulos
    # cada secção tem pelo menos um parágrafo não vazio
    for s in rel.secoes:
        assert s.paragrafos
        assert all(p.strip() for p in s.paragrafos)


def test_relatorio_identifica_registo_e_cliente():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    assert rel.nr_registo == 100031
    assert rel.nome_alojamento == "BAIXA DE FARO ROOFTOP"
    assert rel.concelho == "Faro"
    assert rel.cliente_nome == "Ana Cliente"
    assert rel.gerado_em == HOJE
    t = rel.texto()
    assert "100031" in t
    assert "BAIXA DE FARO ROOFTOP" in t
    assert "Ana Cliente" in t


# ==========================================================================
#  PDF
# ==========================================================================
def test_render_pdf_comeca_por_pdf_e_nao_vazio():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    pdf = render_pdf(rel)
    assert isinstance(pdf, (bytes, bytearray))
    assert bytes(pdf[:4]) == b"%PDF"
    assert len(pdf) > 500


def test_render_pdf_com_acentos_pt_nao_rebenta():
    # concelho e nome com acentos e cedilha — têm de sobreviver ao latin-1 do core font
    cli = _cliente(nome_al="Solar da Çã — Évora", concelho="Évora", nome_cli="João Gonçalves")
    rel = gerar_relatorio_inicial(cli, _detalhe_ativo(), hoje=HOJE)
    pdf = render_pdf(rel)
    assert bytes(pdf[:4]) == b"%PDF"


# ==========================================================================
#  Secção estado
# ==========================================================================
def test_estado_ativo_e_factual():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    estado = next(s for s in rel.secoes if s.titulo == SECAO_ESTADO)
    texto = " ".join(estado.paragrafos).lower()
    assert "ativo" in texto
    # G4: nunca afirma cancelamento
    assert "cancelad" not in texto


def test_estado_nao_encontrado_ressalva_sem_afirmar_cancelado():
    det = DetalheRegisto(nr_registo=100031, estado=ESTADO_NAO_ENCONTRADO)
    rel = gerar_relatorio_inicial(_cliente(), det, hoje=HOJE)
    texto = rel.texto().lower()
    # 🚦 G4 inviolável: o detalhe nunca vira "cancelado" no relatório
    assert "cancelad" not in texto
    # há uma ressalva de confirmação
    assert "confirm" in texto
    # e o PDF sai à mesma
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


def test_estado_indeterminado_nao_rebenta_e_sem_cancelado():
    det = DetalheRegisto(nr_registo=100031, estado=ESTADO_INDETERMINADO)
    rel = gerar_relatorio_inicial(_cliente(), det, hoje=HOJE)
    texto = rel.texto().lower()
    assert "cancelad" not in texto
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


# ==========================================================================
#  Secção seguro
# ==========================================================================
def test_seguro_presente_aparece_no_relatorio():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    t = rel.texto()
    assert "Zurich" in t
    assert "009238995" in t          # zeros à esquerda preservados
    assert "2026-12-11" in t         # validade em ISO
    assert "2025-12-12" in t         # início em ISO


def test_seguro_ausente_da_nota_factual():
    det = DetalheRegisto(nr_registo=100031, estado=ESTADO_ATIVO)  # sem bloco seguro
    rel = gerar_relatorio_inicial(_cliente(), det, hoje=HOJE)
    seguro = next(s for s in rel.secoes if s.titulo == SECAO_SEGURO)
    t = " ".join(seguro.paragrafos).lower()
    assert "seguro" in t
    assert "obrigat" in t            # lembra a obrigatoriedade do RC
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


def test_seguro_caducado_assinalado():
    det = DetalheRegisto(
        nr_registo=100031,
        estado=ESTADO_ATIVO,
        seguro_companhia="CA Seguros",
        seguro_apolice="03662951",
        seguro_validade=date(2025, 7, 3),   # anterior a HOJE (2026-07-05)
    )
    rel = gerar_relatorio_inicial(_cliente(), det, hoje=HOJE)
    t = rel.texto()
    assert "2025-07-03" in t
    assert "renov" in t.lower() or "anterior" in t.lower()


def test_seguro_valido_nao_marca_caducado():
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), hoje=HOJE)
    seguro = next(s for s in rel.secoes if s.titulo == SECAO_SEGURO)
    t = " ".join(seguro.paragrafos).lower()
    assert "caduc" not in t
    assert "anterior a" not in t


# ==========================================================================
#  Secções contenção / regulamentos — toleram vazio (FDS 4 preenche)
# ==========================================================================
def test_contencao_e_regulamentos_vazios_toleram():
    rel = gerar_relatorio_inicial(
        _cliente(), _detalhe_ativo(), contencao=None, regulamentos=(), hoje=HOJE
    )
    cont = next(s for s in rel.secoes if s.titulo == SECAO_CONTENCAO)
    regs = next(s for s in rel.secoes if s.titulo == SECAO_REGULAMENTOS)
    assert cont.paragrafos and all(p.strip() for p in cont.paragrafos)
    assert regs.paragrafos and all(p.strip() for p in regs.paragrafos)
    # não inventa ausência: não afirma taxativamente que "não existe" contenção/regulamento
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


def test_contencao_texto_preenchido_aparece():
    rel = gerar_relatorio_inicial(
        _cliente(),
        _detalhe_ativo(),
        contencao="Faro tem área de contenção com suspensão de novos registos desde 2024.",
        hoje=HOJE,
    )
    assert "área de contenção com suspensão" in rel.texto()


def test_contencao_objeto_com_descricao():
    contencao = SimpleNamespace(
        concelho="Faro", descricao="Concelho em contenção parcial na zona ribeirinha."
    )
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), contencao=contencao, hoje=HOJE)
    assert "contenção parcial na zona ribeirinha" in rel.texto()


def test_regulamentos_lista_de_strings():
    regs = (
        "Regulamento Municipal de AL de Faro (2025)",
        "Aviso n.º 123/2026 — suspensão temporária",
    )
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), regulamentos=regs, hoje=HOJE)
    t = rel.texto()
    assert "Regulamento Municipal de AL de Faro (2025)" in t
    assert "Aviso n.º 123/2026" in t


def test_regulamentos_objetos_com_titulo():
    reg = SimpleNamespace(titulo="Deliberação 45/2026 do Município de Faro")
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo(), regulamentos=[reg], hoje=HOJE)
    assert "Deliberação 45/2026 do Município de Faro" in rel.texto()


# ==========================================================================
#  Robustez do gerador
# ==========================================================================
def test_cliente_sem_registos_nao_rebenta():
    cli = SimpleNamespace(nome="Sem Registos", email="x@x.pt", registos=[])
    rel = gerar_relatorio_inicial(cli, _detalhe_ativo(), hoje=HOJE)
    assert rel.nr_registo == 100031
    assert rel.nome_alojamento is None
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


def test_cliente_sem_atributo_registos_nao_rebenta():
    cli = SimpleNamespace(nome="Minimal", email="m@m.pt")  # sem .registos
    rel = gerar_relatorio_inicial(cli, _detalhe_ativo(), hoje=HOJE)
    assert rel.nr_registo == 100031
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"


def test_hoje_default_usa_data_corrente():
    # sem passar `hoje`, usa date.today() — só verificamos que gera e é uma data
    rel = gerar_relatorio_inicial(_cliente(), _detalhe_ativo())
    assert isinstance(rel.gerado_em, date)
    assert bytes(render_pdf(rel)[:4]) == b"%PDF"
