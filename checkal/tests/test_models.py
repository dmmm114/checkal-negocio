"""Testes do esquema ORM canónico — app.models (SPEC-FDS1.md §models).

Cobre o mínimo contratual do FDS 1:
  - `db.init_db()` cria as 8 tabelas em SQLite;
  - insert/read de um `registo`;
  - insert/read de um `evento_registo` com `campos_alterados` (coluna JSON);
  - a relação muitos-para-muitos `clientes_registos`.

Isolamento: cada teste corre contra uma BD SQLite temporária própria. Em vez
de depender de `config.DB_URL`, faz-se monkeypatch de `db.engine`/`db.SessionLocal`
para um ficheiro em `tmp_path` — assim `db.init_db()` e `db.get_session()`
(que resolvem os globais no momento da chamada) usam a BD de teste e nunca
tocam na base real. SEM rede, SEM I/O externo. Escritos ANTES da implementação (TDD).
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
    url = f"sqlite:///{tmp_path / 'checkal_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    # init_db/get_session leem os globais do módulo db no momento da chamada;
    # ao trocá-los, todo o acesso passa pela BD de teste.
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


_TABELAS_ESPERADAS = {
    "registos",
    "varrimentos",
    "eventos_registo",
    "detalhes_cliente",
    "clientes",
    "clientes_registos",
    "eventos_regulatorios",
    "alertas",
}


# --------------------------------------------------------------------------
#  init_db cria o esquema completo
# --------------------------------------------------------------------------
def test_init_db_cria_as_oito_tabelas(bd):
    nomes = set(inspect(db.engine).get_table_names())
    assert _TABELAS_ESPERADAS <= nomes


def test_modelos_declaram_as_oito_tabelas_na_metadata(bd):
    assert _TABELAS_ESPERADAS <= set(db.Base.metadata.tables)


# --------------------------------------------------------------------------
#  registos — insert/read
# --------------------------------------------------------------------------
def test_insere_e_le_registo(bd):
    with db.get_session() as s:
        s.add(
            models.Registo(
                nr_registo=100031,
                data_registo=date(2019, 7, 16),
                nome_alojamento="Casa do Sol",
                modalidade="Estabelecimento de hospedagem",
                nr_camas=2,
                nr_utentes=4,
                endereco="Rua X, 1",
                cod_postal="8000-444",
                freguesia="Sé",
                concelho="Faro",
                distrito="Faro",
                titular_tipo="coletiva",
                titular_nome="Alojamentos Sul, Lda",
                nif="513029591",
                email="geral@sul.pt",
                hash_campos="abc123",
            )
        )

    with db.get_session() as s:
        r = s.get(models.Registo, 100031)
        assert r is not None
        assert r.nr_registo == 100031
        assert r.concelho == "Faro"
        assert r.titular_tipo == "coletiva"
        assert r.nr_camas == 2
        assert r.data_registo == date(2019, 7, 16)


def test_registo_nasce_com_ausencias_consecutivas_zero(bd):
    # Coluna de estado usada pela regra dos 2 varrimentos (SPEC diffing/ingest).
    with db.get_session() as s:
        s.add(models.Registo(nr_registo=200, concelho="Lisboa", hash_campos="h"))

    with db.get_session() as s:
        r = s.get(models.Registo, 200)
        assert r.ausencias_consecutivas == 0
        assert r.desaparecido_em is None


# --------------------------------------------------------------------------
#  eventos_registo — coluna JSON campos_alterados
# --------------------------------------------------------------------------
def test_insere_e_le_evento_registo_com_campos_alterados_json(bd):
    diff = {"email": ["geral@sul.pt", "novo@sul.pt"], "nr_camas": [2, 3]}
    with db.get_session() as s:
        s.add(models.Registo(nr_registo=100031, concelho="Faro", hash_campos="h1"))
        s.flush()
        s.add(
            models.EventoRegisto(
                nr_registo=100031,
                tipo="alterado",
                campos_alterados=diff,
                varrimento_id=1,
                detetado_em=datetime(2026, 7, 5, 3, 0, tzinfo=timezone.utc),
            )
        )

    with db.get_session() as s:
        ev = s.query(models.EventoRegisto).one()
        assert ev.tipo == "alterado"
        # round-trip JSON: sai um dict nativo, não uma string
        assert isinstance(ev.campos_alterados, dict)
        assert ev.campos_alterados == diff
        assert ev.campos_alterados["nr_camas"] == [2, 3]
        # boolean com default aplicado
        assert ev.processado is False


def test_evento_regulatorio_concelhos_lista_json(bd):
    # `concelhos text[]` do Postgres → JSON portável; guarda/lê uma lista.
    with db.get_session() as s:
        s.add(
            models.EventoRegulatorio(
                fonte="DRE",
                url="https://dre.pt/reg/884-2024",
                titulo="Regulamento AL Loulé",
                publicado_em=date(2024, 9, 1),
                concelhos=["Loulé", "Faro"],
                triagem="relevante",
            )
        )

    with db.get_session() as s:
        e = s.query(models.EventoRegulatorio).one()
        assert e.concelhos == ["Loulé", "Faro"]
        assert e.processado is False


# --------------------------------------------------------------------------
#  clientes_registos — relação muitos-para-muitos
# --------------------------------------------------------------------------
def test_relacao_clientes_registos(bd):
    with db.get_session() as s:
        r1 = models.Registo(nr_registo=1, concelho="Lisboa", hash_campos="a")
        r2 = models.Registo(nr_registo=2, concelho="Porto", hash_campos="b")
        c = models.Cliente(email="dono@ex.pt", nome="Dono", plano="anual", estado="ativo")
        c.registos.extend([r1, r2])
        s.add(c)

    with db.get_session() as s:
        c = s.query(models.Cliente).one()
        assert {r.nr_registo for r in c.registos} == {1, 2}
        # navegação inversa
        r1 = s.get(models.Registo, 1)
        assert [cl.email for cl in r1.clientes] == ["dono@ex.pt"]
        # a linha de junção existe na tabela de associação
        assert s.query(models.ClienteRegisto).count() == 2
