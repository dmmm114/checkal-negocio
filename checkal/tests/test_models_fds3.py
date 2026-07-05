"""Testes FDS 3 do esquema ORM — extensão *aditiva* a app.models (SPEC-FDS3.md §base).

Cobre o único contrato aditivo do FDS 3 sobre o esquema, sem quebrar FDS 1/FDS 2/swap:
  - `detalhes_cliente` ganha a coluna `seguro_inicio date` (a página individual do RNAL
    expõe "Data início" da apólice — SPEC-DETALHE §2.1/§4; útil para a copy "apólice de X a Y");
  - round-trip: um `DetalheCliente` com `seguro_inicio` persiste e relê-se como `date`;
  - default: sem o passar, nasce NULL (aditivo, não obrigatório);
  - regressão: as colunas antigas de `detalhes_cliente` e as tabelas de FDS 1/FDS 2/swap
    continuam presentes.

Isolamento igual ao test_models.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`. SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models


# --------------------------------------------------------------------------
#  Fixture: BD SQLite temporária, isolada, com o esquema criado
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_fds3.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _utc(dt):
    """Normaliza a UTC: o SQLite guarda `DateTime(timezone=True)` como naive."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
#  detalhes_cliente — nova coluna seguro_inicio (aditiva)
# --------------------------------------------------------------------------
def test_detalhes_cliente_tem_coluna_seguro_inicio(bd):
    cols = {c["name"] for c in inspect(db.engine).get_columns("detalhes_cliente")}
    assert "seguro_inicio" in cols
    # as colunas anteriores de detalhes_cliente continuam intactas (regressão)
    assert {
        "nr_registo",
        "estado_detalhado",
        "seguro_companhia",
        "seguro_apolice",
        "seguro_validade",
        "obtido_em",
    } <= cols


def test_seguro_inicio_na_metadata(bd):
    assert "seguro_inicio" in db.Base.metadata.tables["detalhes_cliente"].columns


def test_detalhe_cliente_persiste_seguro_inicio(bd):
    # "apólice de X a Y": Data início (2025-12-12) e Validade (2026-12-11) do nr=100031.
    with db.get_session() as s:
        s.add(
            models.DetalheCliente(
                nr_registo=100031,
                estado_detalhado="ativo",
                seguro_companhia="Zurich",
                seguro_apolice="009238995",
                seguro_inicio=date(2025, 12, 12),
                seguro_validade=date(2026, 12, 11),
                obtido_em=datetime(2026, 7, 5, 3, 30, tzinfo=timezone.utc),
            )
        )

    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d is not None
        assert d.seguro_inicio == date(2025, 12, 12)
        assert d.seguro_validade == date(2026, 12, 11)
        # zeros à esquerda da apólice preservados (guardar como texto — SPEC-DETALHE §6.4)
        assert d.seguro_apolice == "009238995"
        assert d.estado_detalhado == "ativo"
        assert _utc(d.obtido_em) == datetime(2026, 7, 5, 3, 30, tzinfo=timezone.utc)


def test_seguro_inicio_default_nulo(bd):
    # sem o passar (registo sem seguro visível), nasce NULL — não é obrigatório
    with db.get_session() as s:
        s.add(models.DetalheCliente(nr_registo=200, estado_detalhado="ativo"))

    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 200)
        assert d.seguro_inicio is None
        assert d.seguro_validade is None
        assert d.seguro_companhia is None


# --------------------------------------------------------------------------
#  Regressão: nada partiu no esquema de FDS 1/FDS 2/swap
# --------------------------------------------------------------------------
def test_tabelas_anteriores_intactas(bd):
    nomes = set(inspect(db.engine).get_table_names())
    assert {
        # FDS 1
        "registos",
        "varrimentos",
        "eventos_registo",
        "detalhes_cliente",
        "clientes",
        "clientes_registos",
        "eventos_regulatorios",
        "alertas",
        # FDS 2
        "webhook_eventos",
        # swap
        "toconline_tokens",
    } <= nomes
