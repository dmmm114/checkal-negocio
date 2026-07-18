"""Testes do esquema ADITIVO do enxame — app.models_swarm (Fase A do prompt-mestre).

Cobre o contrato da Fase A:
  - `db.init_db()` cria as 13 tabelas novas do enxame (schema HARNESS(db) +
    tabelas de governação) SEM tocar nas existentes;
  - migração idempotente: correr `init_db()` 2× não falha;
  - `Lead`/`OptOut` NÃO são redefinidos (o schema é aditivo);
  - portabilidade SQLite/Postgres: só tipos portáveis (Integer, Text, Date,
    Boolean, JSON, DateTime); dinheiro em Integer de cêntimos; o DDL compila
    no dialeto postgresql sem erro;
  - UNIQUEs de idempotência: (campanha_id, nif, passo) das peças,
    `stripe_invoice_id`/`ix_fatura_id` das faturas, (dia, canal, campanha_id,
    metrica) dos rollups;
  - `RevisaoItem` traz `token_aprovacao` + `camada_risco` (exigência MAESTRO)
    e nasce `pendente`/`linter_ok=False`;
  - `Aprovacao` recusa autor == decidido_por (quem propõe nunca aprova).

Isolamento: BD SQLite temporária por teste (mesmo idioma de test_models.py).
SEM rede, SEM I/O externo. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

import app.db as db
import app.models as models


# --------------------------------------------------------------------------
#  Fixture: BD SQLite temporária, isolada, com o esquema criado
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_swarm_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


_TABELAS_ENXAME = {
    "eventos_agente",
    "campanhas",
    "campanha_pecas",
    "revisao_itens",
    "contactos_coletiva",
    "faturas",
    "metricas_rollup",
    "supressao_nif",
    "aprovacoes",
    "escalacoes",
    "agente_execucoes",
    "digests",
    "custo_llm",
}

# Tipos de coluna portáveis SQLite/Postgres (regra dura do schema do enxame).
_TIPOS_PORTAVEIS = {"INTEGER", "TEXT", "DATE", "BOOLEAN", "JSON", "DATETIME"}


def _tabelas_enxame_metadata():
    return {n: t for n, t in db.Base.metadata.tables.items() if n in _TABELAS_ENXAME}


# --------------------------------------------------------------------------
#  Criação + idempotência (migração aditiva)
# --------------------------------------------------------------------------
def test_init_db_cria_as_tabelas_do_enxame(bd):
    nomes = set(inspect(db.engine).get_table_names())
    assert _TABELAS_ENXAME <= nomes


def test_tabelas_existentes_continuam_presentes(bd):
    # A migração é ADITIVA: as 8 tabelas do pipeline + FDS2/FASE1 mantêm-se.
    nomes = set(inspect(db.engine).get_table_names())
    assert {"registos", "clientes", "alertas", "leads", "optouts"} <= nomes


def test_migracao_idempotente_correr_duas_vezes_nao_falha(bd):
    db.init_db()  # 2.ª passagem — não pode levantar nem duplicar
    nomes = set(inspect(db.engine).get_table_names())
    assert _TABELAS_ENXAME <= nomes


def test_lead_e_optout_nao_sao_redefinidos(bd):
    import app.models_swarm as ms

    # O módulo do enxame NÃO redefine as tabelas existentes.
    assert not hasattr(ms, "Lead")
    assert not hasattr(ms, "OptOut")
    # A tabela `leads` continua a dos models.py (consentimento granular intacto).
    cols = {c.name for c in db.Base.metadata.tables["leads"].columns}
    assert {"consent_alertas", "consent_ofertas", "consentimento_texto_versao"} <= cols


# --------------------------------------------------------------------------
#  Portabilidade: tipos portáveis, dinheiro em cêntimos, compila em Postgres
# --------------------------------------------------------------------------
def test_todas_as_colunas_usam_tipos_portaveis(bd):
    for nome, tabela in _tabelas_enxame_metadata().items():
        for col in tabela.columns:
            generico = type(col.type).__name__.upper()
            assert generico in _TIPOS_PORTAVEIS, (
                f"{nome}.{col.name} usa tipo não portável: {generico}"
            )


def test_dinheiro_em_integer_de_centimos(bd):
    tabelas = _tabelas_enxame_metadata()
    for col in ("total_cents", "iva_cents"):
        assert type(tabelas["faturas"].columns[col].type).__name__.upper() == "INTEGER"
    assert (
        type(tabelas["custo_llm"].columns["custo_eur_cent"].type).__name__.upper()
        == "INTEGER"
    )
    # Nenhuma coluna Float/Numeric em tabela nenhuma do enxame.
    for nome, tabela in tabelas.items():
        for c in tabela.columns:
            assert type(c.type).__name__.upper() not in {"FLOAT", "NUMERIC", "DECIMAL"}, (
                f"{nome}.{c.name} guarda dinheiro/valores em vírgula flutuante"
            )


def test_ddl_compila_no_dialeto_postgres(bd):
    # "Mock Postgres": o DDL de todas as tabelas novas compila no dialeto
    # postgresql sem erro (prova de portabilidade sem precisar de servidor).
    dialecto = postgresql.dialect()
    for tabela in _tabelas_enxame_metadata().values():
        ddl = str(CreateTable(tabela).compile(dialect=dialecto))
        assert "CREATE TABLE" in ddl


# --------------------------------------------------------------------------
#  eventos_agente — journal append-only
# --------------------------------------------------------------------------
def test_evento_agente_insert_read_com_payload_json(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.EventoAgente(
                agente="sentinela",
                execucao_id="exec-1",
                tipo="achado",
                severidade="critico",
                ref_tipo="registo",
                ref_id="100031",
                mensagem="varrimento estagnado",
                payload={"freshness_h": 80},
                criado_em=datetime(2026, 7, 18, 6, 40, tzinfo=timezone.utc),
            )
        )

    with db.get_session() as s:
        ev = s.query(ms.EventoAgente).one()
        assert ev.agente == "sentinela"
        assert ev.payload == {"freshness_h": 80}
        assert ev.escalado is False


# --------------------------------------------------------------------------
#  campanhas / campanha_pecas — persistência do RascunhoFrio + UNIQUE cadência
# --------------------------------------------------------------------------
def test_campanha_peca_unique_campanha_nif_passo(bd):
    import app.models_swarm as ms

    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        c = ms.Campanha(canal="cold_email", n_gatilhos=1, criado_em=agora)
        s.add(c)
        s.flush()
        s.add(
            ms.CampanhaPeca(
                campanha_id=c.id, nif="513029591",
                email_generico="geral@sul.pt", passo="d0", criado_em=agora,
            )
        )
        s.flush()
        campanha_id = c.id

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(
                ms.CampanhaPeca(
                    campanha_id=campanha_id, nif="513029591",
                    email_generico="geral@sul.pt", passo="d0", criado_em=agora,
                )
            )

    # Passo diferente para o mesmo NIF é permitido (a cadência avança).
    with db.get_session() as s:
        s.add(
            ms.CampanhaPeca(
                campanha_id=campanha_id, nif="513029591",
                email_generico="geral@sul.pt", passo="d4", criado_em=agora,
            )
        )

    with db.get_session() as s:
        assert s.query(ms.CampanhaPeca).count() == 2


def test_campanha_peca_nasce_pendente_parecer_e_sem_linter(bd):
    import app.models_swarm as ms

    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        c = ms.Campanha(canal="cold_email", criado_em=agora)
        s.add(c)
        s.flush()
        s.add(
            ms.CampanhaPeca(
                campanha_id=c.id, nif="513029591",
                email_generico="geral@sul.pt", criado_em=agora,
            )
        )

    with db.get_session() as s:
        p = s.query(ms.CampanhaPeca).one()
        assert p.estado == "pendente_parecer"
        assert p.passo == "d0"
        assert p.linter_ok is False


# --------------------------------------------------------------------------
#  revisao_itens — fila 1-clique com token + camada_risco (exigência MAESTRO)
# --------------------------------------------------------------------------
def test_revisao_item_defaults_e_campos_do_maestro(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.RevisaoItem(
                tipo="cold_email", risco="alto", camada_risco=4,
                agente_origem="angariador", ref_tipo="campanha_peca", ref_id="1",
                resumo="draft frio Porto", criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.estado == "pendente"
        assert item.linter_ok is False
        assert item.token_aprovacao is None
        assert item.camada_risco == 4
        assert item.tentativas == 0


# --------------------------------------------------------------------------
#  contactos_coletiva / supressao_nif — chaves naturais por NIF
# --------------------------------------------------------------------------
def test_contacto_coletiva_pk_nif_e_defaults(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(ms.ContactoColetiva(nif="513029591", email_generico="geral@sul.pt"))

    with db.get_session() as s:
        c = s.get(ms.ContactoColetiva, "513029591")
        assert c is not None
        assert c.estado == "ativo"
        assert c.opt_out is False
        assert c.n_toques == 0


def test_supressao_nif_opor_se_duas_vezes_colide_na_pk(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(ms.SupressaoNif(nif="513029591", origem="dgc"))

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(ms.SupressaoNif(nif="513029591", origem="manual"))


# --------------------------------------------------------------------------
#  faturas — idempotência dura (dois UNIQUEs)
# --------------------------------------------------------------------------
def test_fatura_unique_stripe_invoice_id_e_ix_fatura_id(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        cli = models.Cliente(email="a@b.pt", plano="anual", estado="ativo")
        s.add(cli)
        s.flush()
        s.add(
            ms.Fatura(
                cliente_id=cli.id, stripe_invoice_id="in_1", ix_fatura_id="FRCKL/1",
                serie="CKL", total_cents=4900, iva_cents=916,
            )
        )
        s.flush()
        cliente_id = cli.id

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(ms.Fatura(cliente_id=cliente_id, stripe_invoice_id="in_1"))

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(ms.Fatura(cliente_id=cliente_id, ix_fatura_id="FRCKL/1"))

    # NULLs coexistem (SQLite e Postgres tratam NULL como distinto no UNIQUE).
    with db.get_session() as s:
        s.add(ms.Fatura(cliente_id=cliente_id))
        s.add(ms.Fatura(cliente_id=cliente_id))

    with db.get_session() as s:
        assert s.query(ms.Fatura).count() == 3


# --------------------------------------------------------------------------
#  metricas_rollup — UNIQUE (dia, canal, campanha_id, metrica) p/ upsert
# --------------------------------------------------------------------------
def test_metrica_rollup_unique_dia_canal_campanha_metrica(bd):
    import app.models_swarm as ms

    dia = date(2026, 7, 18)
    with db.get_session() as s:
        s.add(ms.MetricaRollup(dia=dia, canal="cold", campanha_id=1, metrica="enviados", valor=3))

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(
                ms.MetricaRollup(dia=dia, canal="cold", campanha_id=1, metrica="enviados", valor=9)
            )

    # Métrica diferente no mesmo dia/canal/campanha é outra linha.
    with db.get_session() as s:
        s.add(ms.MetricaRollup(dia=dia, canal="cold", campanha_id=1, metrica="abertos", valor=1))

    with db.get_session() as s:
        assert s.query(ms.MetricaRollup).count() == 2


# --------------------------------------------------------------------------
#  aprovacoes — autor NUNCA é o aprovador (separação de poderes em CHECK)
# --------------------------------------------------------------------------
def test_aprovacao_recusa_autor_igual_a_decisor(bd):
    import app.models_swarm as ms

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(
                ms.Aprovacao(
                    revisao_item_id=1, autor="angariador", decidido_por="angariador",
                    decisao="aprovado", criado_em=datetime.now(timezone.utc),
                )
            )


def test_aprovacao_valida_insere(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.Aprovacao(
                revisao_item_id=1, autor="angariador", decidido_por="dono",
                decisao="aprovado", token_usado="tok-1",
                criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        a = s.query(ms.Aprovacao).one()
        assert a.autor == "angariador"
        assert a.decidido_por == "dono"


# --------------------------------------------------------------------------
#  agente_execucoes / escalacoes / digests / custo_llm — governação
# --------------------------------------------------------------------------
def test_agente_execucao_defaults(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.AgenteExecucao(
                agente="angariador", execucao_id="exec-9",
                iniciado_em=datetime.now(timezone.utc), estado="a_correr",
            )
        )

    with db.get_session() as s:
        e = s.query(ms.AgenteExecucao).one()
        assert e.retry_pedido is False
        assert e.exit_code is None


def test_escalacao_nasce_aberta(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.Escalacao(
                agente="gestor", severidade="alta", mensagem="cron_dunning não correu",
                criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        e = s.query(ms.Escalacao).one()
        assert e.estado == "aberta"


def test_digest_persiste_corpo_e_metricas(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.Digest(
                dia=date(2026, 7, 18), corpo_md="# Digest",
                metricas_json={"mrr_cents": 0}, criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        d = s.query(ms.Digest).one()
        assert d.metricas_json == {"mrr_cents": 0}
        assert d.enviado_em is None


def test_custo_llm_acumula_por_dia_agente(bd):
    import app.models_swarm as ms

    with db.get_session() as s:
        s.add(
            ms.CustoLlm(
                dia=date(2026, 7, 18), agente="maestro",
                input_tokens=12000, output_tokens=3000, custo_eur_cent=9,
                criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        c = s.query(ms.CustoLlm).one()
        assert c.custo_eur_cent == 9
        assert c.input_tokens == 12000
