"""Testes do esquema ORM — extensão TOConline (aditiva a app.models).

Cobre o contrato aditivo do swap de faturação para TOConline, sem quebrar
FDS 1/FDS 2:
  - tabela `toconline_tokens` (linha única com o par de tokens OAuth2 + validades);
  - round-trip de uma linha de token (access/refresh + expiries + atualizado_em);
  - as tabelas anteriores continuam presentes (regressão).

`toconline_tokens` guarda o estado da autenticação server-to-server do TOConline
(SPEC-TOCONLINE §2.2): access_token (~4 h) e refresh_token (~8 h) renovados por
um cron externo; a emissão de faturas nunca conhece OAuth (cliente HTTP injetado
já autenticado). Isto é só a persistência do estado.

Isolamento igual ao test_models.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`. SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_toconline.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


# --------------------------------------------------------------------------
#  toconline_tokens — nova tabela
# --------------------------------------------------------------------------
def test_init_db_cria_tabela_toconline_tokens(bd):
    nomes = set(inspect(db.engine).get_table_names())
    assert "toconline_tokens" in nomes
    # tabelas anteriores intactas (regressão FDS 1/FDS 2)
    assert {"registos", "clientes", "webhook_eventos"} <= nomes


def test_toconline_tokens_na_metadata(bd):
    assert "toconline_tokens" in db.Base.metadata.tables


def test_toconline_tokens_colunas(bd):
    cols = {c["name"] for c in inspect(db.engine).get_columns("toconline_tokens")}
    assert {
        "id",
        "access_token",
        "access_expira_em",
        "refresh_token",
        "refresh_expira_em",
        "atualizado_em",
    } <= cols


# --------------------------------------------------------------------------
#  round-trip da linha única de tokens
# --------------------------------------------------------------------------
def _utc(dt):
    """Normaliza a UTC: o SQLite guarda `DateTime(timezone=True)` como valor naive
    (o fuso é descartado), tal como as outras tabelas — comparar em UTC é portável."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_insere_e_le_toconline_token(bd):
    agora = datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc)
    with db.get_session() as s:
        s.add(
            models.ToconlineToken(
                id=1,
                access_token="acc-xyz",
                access_expira_em=agora + timedelta(hours=4),
                refresh_token="ref-abc",
                refresh_expira_em=agora + timedelta(hours=8),
                atualizado_em=agora,
            )
        )

    with db.get_session() as s:
        t = s.get(models.ToconlineToken, 1)
        assert t is not None
        assert t.access_token == "acc-xyz"
        assert t.refresh_token == "ref-abc"
        assert _utc(t.access_expira_em) == agora + timedelta(hours=4)
        assert _utc(t.refresh_expira_em) == agora + timedelta(hours=8)
        assert _utc(t.atualizado_em) == agora
