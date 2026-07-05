"""Testes do orquestrador de ingestão RNAL — app.rnal.ingest (SPEC-FDS1.md §ingest).

`ingest` é o **único** módulo do FDS 1 que toca na BD. Orquestra um varrimento:
fetch (via cliente injetado) → validação Pydantic (drift ⇒ varrimento ``abortado``,
sem diffing) → normalização → carrega ``estado_atual`` da BD → `diff_varrimento`
→ persiste eventos + upsert em ``registos`` (``hash_campos``, ``visto_ultimo``,
``ausencias_consecutivas``, ``desaparecido_em``) → grava a linha ``varrimentos``.

Isolamento: cada teste corre contra uma BD SQLite temporária própria (monkeypatch
de ``db.engine``/``db.SessionLocal``), como em test_models. SEM rede — o cliente é
um duplo (`ClienteFalso`) que devolve um `ResultadoVarrimento` pré-fabricado; os
`ResultadoVarrimento` também se constroem à mão. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.rnal.client import ResultadoVarrimento
from app.rnal import ingest


# --------------------------------------------------------------------------
#  Fixture: BD SQLite temporária, isolada, com o esquema criado
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_test.db'}"
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
#  Dublês de teste (nada toca a rede)
# --------------------------------------------------------------------------
def _raw(nr: int, *, concelho: str = "Faro", nome: str = "Casa do Mar",
         email: str = "a@b.pt", nr_camas=2, **over) -> dict:
    """Um registo bruto no formato da API (`RNAL_Registo` aninhado)."""
    interno = {
        "NrRegisto": f"{nr}/AL",
        "Concelho": concelho,
        "NomeAlojamento": nome,
        "Modalidade": "Estabelecimento de hospedagem",
        "NrCamas": nr_camas,
        "NrUtentes": 4,
        "Endereco": "Rua das Flores 10",
        "CodPostal": "8000-444",
        "Freguesia": "Sé",
        "Distrito": "Faro",
        "TitulardaExploracao": {
            "Tipo": "Pessoa coletiva",
            "Nome": "Oasis Lda",
            "Contribuinte": "513029591",
            "Email": email,
        },
    }
    interno.update(over)
    return {"RNAL_Registo": interno}


def _resultado(registos_por_concelho, *, ok=None, falhados=None,
               momento: datetime | None = None) -> ResultadoVarrimento:
    """Constrói um `ResultadoVarrimento` como o `client.fetch_todos` devolveria."""
    if ok is None:
        ok = set(registos_por_concelho)
    if falhados is None:
        falhados = set()
    momento = momento or datetime(2026, 7, 5, 3, 0, tzinfo=timezone.utc)
    return ResultadoVarrimento(
        registos_por_concelho=dict(registos_por_concelho),
        concelhos_ok=set(ok),
        concelhos_falhados=set(falhados),
        raw_path="/tmp/fake.json.gz",
        iniciado_em=momento,
        concluido_em=momento,
    )


class ClienteFalso:
    """Substitui o módulo `client`: `fetch_todos` devolve resultados enfileirados."""

    def __init__(self, *resultados: ResultadoVarrimento):
        self._fila = list(resultados)
        self.concelhos_pedidos: list[list[str]] = []

    def fetch_todos(self, concelhos, **kwargs) -> ResultadoVarrimento:
        self.concelhos_pedidos.append(list(concelhos))
        return self._fila.pop(0)


def _tipos_por_nr(res) -> dict[int, str]:
    return {ev.nr_registo: ev.tipo for ev in res.eventos}


# --------------------------------------------------------------------------
#  Registo novo → INSERT + evento `novo`
# --------------------------------------------------------------------------
def test_varrimento_novo_insere_registo_e_evento_novo(bd):
    res = ingest.ingerir_resultado(
        _resultado({"Faro": [_raw(100, DataRegisto="2019-07-16")]})
    )

    assert res.estado == "ok"
    assert _tipos_por_nr(res) == {100: "novo"}

    with db.get_session() as s:
        r = s.get(models.Registo, 100)
        assert r is not None
        assert r.concelho == "Faro"
        assert r.nome_alojamento == "Casa do Mar"
        assert r.email == "a@b.pt"
        assert r.data_registo == date(2019, 7, 16)
        assert r.ausencias_consecutivas == 0
        assert r.desaparecido_em is None
        assert r.hash_campos  # preenchido
        assert r.visto_primeiro is not None and r.visto_ultimo is not None

        ev = s.query(models.EventoRegisto).one()
        assert ev.tipo == "novo"
        assert ev.nr_registo == 100
        assert ev.varrimento_id == res.varrimento_id
        assert ev.campos_alterados is None


def test_varrimento_grava_linha_varrimentos(bd):
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))
    with db.get_session() as s:
        v = s.get(models.Varrimento, res.varrimento_id)
        assert v is not None
        assert v.estado == "ok"
        assert v.concelhos_ok == 1
        assert v.concelhos_falhados == 0
        assert v.total_registos == 1
        assert v.raw_path == "/tmp/fake.json.gz"


def test_varrimento_com_concelho_falhado_e_parcial(bd):
    res = ingest.ingerir_resultado(
        _resultado({"Faro": [_raw(1)]}, ok={"Faro"}, falhados={"Porto"})
    )
    assert res.estado == "parcial"
    with db.get_session() as s:
        v = s.get(models.Varrimento, res.varrimento_id)
        assert v.estado == "parcial"
        assert v.concelhos_falhados == 1


# --------------------------------------------------------------------------
#  Drift de esquema ⇒ varrimento `abortado` e diffing NÃO corre
# --------------------------------------------------------------------------
def test_drift_aborta_sem_diffing(bd, monkeypatch):
    # Espia o diffing para provar que não é chamado no caminho de drift.
    chamado: list[int] = []
    real = ingest.diff_varrimento
    monkeypatch.setattr(
        ingest, "diff_varrimento",
        lambda *a, **k: (chamado.append(1), real(*a, **k))[1],
    )

    # Registo malformado: falta `NrRegisto` → DriftEsquemaRNAL na validação.
    mau = {"RNAL_Registo": {"Concelho": "Faro",
                            "TitulardaExploracao": {"Tipo": "Pessoa singular"}}}
    res = ingest.ingerir_resultado(_resultado({"Faro": [mau]}))

    assert res.estado == "abortado"
    assert res.eventos == []
    assert chamado == []  # diffing não correu

    with db.get_session() as s:
        assert s.query(models.Registo).count() == 0        # nada persistido
        assert s.query(models.EventoRegisto).count() == 0
        v = s.get(models.Varrimento, res.varrimento_id)
        assert v.estado == "abortado"


def test_drift_nao_toca_no_estado_existente(bd):
    # Já há um registo; um varrimento com drift não pode alterá-lo.
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))
    mau = {"RNAL_Registo": {"NomeAlojamento": "X"}}  # faltam obrigatórias
    res = ingest.ingerir_resultado(_resultado({"Faro": [mau]}))

    assert res.estado == "abortado"
    with db.get_session() as s:
        r = s.get(models.Registo, 1)
        assert r.ausencias_consecutivas == 0  # não foi mexido
        assert r.desaparecido_em is None


# --------------------------------------------------------------------------
#  Registo alterado → evento `alterado` + campos atualizados
# --------------------------------------------------------------------------
def test_registo_alterado_gera_evento_e_atualiza_campos(bd):
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1, email="a@b.pt")]}))
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1, email="novo@b.pt")]}))

    assert _tipos_por_nr(res) == {1: "alterado"}
    with db.get_session() as s:
        r = s.get(models.Registo, 1)
        assert r.email == "novo@b.pt"  # campo atualizado no upsert
        ev = (s.query(models.EventoRegisto)
              .filter_by(nr_registo=1, tipo="alterado").one())
        assert ev.campos_alterados == {"email": ["a@b.pt", "novo@b.pt"]}


def test_registo_inalterado_nao_gera_evento(bd):
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))
    assert res.eventos == []
    with db.get_session() as s:
        assert s.query(models.EventoRegisto).count() == 1  # só o `novo` inicial


# --------------------------------------------------------------------------
#  Regra dos 2 varrimentos (ausências)
# --------------------------------------------------------------------------
def test_ausencia_isolada_incrementa_sem_evento(bd):
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1), _raw(2)]}))
    # 2.º varrimento: o registo 2 não vem (1.ª ausência).
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))

    assert res.eventos == []  # 1 ausência não gera evento
    with db.get_session() as s:
        r = s.get(models.Registo, 2)
        assert r.ausencias_consecutivas == 1
        assert r.desaparecido_em is None


def test_duas_ausencias_marca_desaparecido(bd):
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1), _raw(2)]}))
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))          # ausência 1
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))    # ausência 2

    assert _tipos_por_nr(res) == {2: "desaparecido"}
    with db.get_session() as s:
        r = s.get(models.Registo, 2)
        assert r.ausencias_consecutivas == 2
        assert r.desaparecido_em is not None
        ev = s.query(models.EventoRegisto).filter_by(tipo="desaparecido").one()
        assert ev.nr_registo == 2


def test_ausencia_em_concelho_parcial_nao_conta(bd):
    # Registo em Porto; 2.º varrimento só devolve Faro (Porto falhado/parcial):
    # a ausência do Porto é ignorada — não incrementa nem marca.
    ingest.ingerir_resultado(
        _resultado({"Faro": [_raw(1)], "Porto": [_raw(2, concelho="Porto")]})
    )
    res = ingest.ingerir_resultado(
        _resultado({"Faro": [_raw(1)]}, ok={"Faro"}, falhados={"Porto"})
    )
    assert res.eventos == []
    with db.get_session() as s:
        r = s.get(models.Registo, 2)
        assert r.ausencias_consecutivas == 0   # intacto (Porto não respondeu)
        assert r.desaparecido_em is None


def test_reaparecimento_limpa_desaparecido(bd):
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1), _raw(2)]}))
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))          # ausência 1
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1)]}))          # → desaparecido
    res = ingest.ingerir_resultado(_resultado({"Faro": [_raw(1), _raw(2)]}))  # volta

    assert _tipos_por_nr(res)[2] == "reapareceu"
    with db.get_session() as s:
        r = s.get(models.Registo, 2)
        assert r.desaparecido_em is None
        assert r.ausencias_consecutivas == 0


# --------------------------------------------------------------------------
#  Idempotência: reprocessar dados iguais não duplica registos nem eventos
# --------------------------------------------------------------------------
def test_reprocessar_dados_iguais_e_idempotente(bd):
    dados = _resultado({"Faro": [_raw(1), _raw(2)]})
    ingest.ingerir_resultado(dados)
    ingest.ingerir_resultado(_resultado({"Faro": [_raw(1), _raw(2)]}))

    with db.get_session() as s:
        assert s.query(models.Registo).count() == 2          # sem duplicados (PK)
        assert s.query(models.EventoRegisto).count() == 2     # só os 2 `novo`
        # a 2.ª passagem regista na mesma a sua linha de varrimento
        assert s.query(models.Varrimento).count() == 2


# --------------------------------------------------------------------------
#  Fetch via cliente injetado (sem rede)
# --------------------------------------------------------------------------
def test_executar_varrimento_usa_o_cliente_injetado(bd):
    cli = ClienteFalso(_resultado({"Faro": [_raw(1)]}))
    res = ingest.executar_varrimento(["Faro"], cliente=cli)

    assert cli.concelhos_pedidos == [["Faro"]]
    assert _tipos_por_nr(res) == {1: "novo"}
    with db.get_session() as s:
        assert s.get(models.Registo, 1) is not None


# --------------------------------------------------------------------------
#  TESTE DE ACEITAÇÃO FDS 1 — 2 varrimentos sobre dados mutados entre eles
#  (1 novo, 1 alterado, 1 desaparecido nos 2, 1 com ausência isolada)
# --------------------------------------------------------------------------
def test_aceitacao_dois_varrimentos_dados_mutados(bd):
    """Estado inicial via um varrimento-base; depois os 2 varrimentos mutados.

    Registos: 1 estável, 2 alterado, 3 novo (no 1.º dos 2), 4 desaparecido
    (ausente nos 2), 5 com ausência isolada (só no 2.º). Injeta-se um cliente
    falso (sem rede). Verificam-se os eventos gerados E o estado final da BD.
    """
    T0 = datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc)
    T1 = datetime(2026, 7, 4, 3, 0, tzinfo=timezone.utc)
    T2 = datetime(2026, 7, 8, 3, 0, tzinfo=timezone.utc)

    base = _resultado(
        {"Faro": [_raw(1), _raw(2, email="a@b.pt"), _raw(4), _raw(5)]},
        momento=T0,
    )
    v1 = _resultado(
        {"Faro": [_raw(1), _raw(2, email="novo@b.pt"), _raw(3), _raw(5)]},
        momento=T1,
    )  # 4 ausente (1.ª); 2 alterado; 3 novo
    v2 = _resultado(
        {"Faro": [_raw(1), _raw(2, email="novo@b.pt"), _raw(3)]},
        momento=T2,
    )  # 4 ausente (2.ª → desaparecido); 5 ausente (1.ª → isolada)

    cli = ClienteFalso(base, v1, v2)

    # -- Varrimento base: tudo novo --
    r0 = ingest.executar_varrimento(["Faro"], cliente=cli)
    assert r0.estado == "ok"
    assert _tipos_por_nr(r0) == {1: "novo", 2: "novo", 4: "novo", 5: "novo"}

    # -- Varrimento 1 dos 2 (dados mutados) --
    r1 = ingest.executar_varrimento(["Faro"], cliente=cli)
    assert _tipos_por_nr(r1) == {2: "alterado", 3: "novo"}
    with db.get_session() as s:
        assert s.get(models.Registo, 2).email == "novo@b.pt"
        assert s.get(models.Registo, 3) is not None
        r4 = s.get(models.Registo, 4)
        assert r4.ausencias_consecutivas == 1 and r4.desaparecido_em is None
        assert s.get(models.Registo, 5).ausencias_consecutivas == 0

    # -- Varrimento 2 dos 2 (dados mutados) --
    r2 = ingest.executar_varrimento(["Faro"], cliente=cli)
    assert _tipos_por_nr(r2) == {4: "desaparecido"}

    # -- Estado final da BD --
    with db.get_session() as s:
        r1_ = s.get(models.Registo, 1)
        assert r1_.ausencias_consecutivas == 0 and r1_.desaparecido_em is None
        r4 = s.get(models.Registo, 4)
        assert r4.ausencias_consecutivas == 2 and r4.desaparecido_em is not None
        r5 = s.get(models.Registo, 5)
        assert r5.ausencias_consecutivas == 1 and r5.desaparecido_em is None

        # eventos acumulados: 4 (base) + 2 (v1) + 1 (v2) = 7
        assert s.query(models.EventoRegisto).count() == 7
        por_tipo = {
            t: s.query(models.EventoRegisto).filter_by(tipo=t).count()
            for t in ("novo", "alterado", "desaparecido", "reapareceu")
        }
        assert por_tipo == {"novo": 5, "alterado": 1, "desaparecido": 1,
                            "reapareceu": 0}

        ev_alt = (s.query(models.EventoRegisto)
                  .filter_by(nr_registo=2, tipo="alterado").one())
        assert ev_alt.campos_alterados == {"email": ["a@b.pt", "novo@b.pt"]}

        # 3 linhas de varrimento, todas ok
        assert s.query(models.Varrimento).count() == 3
        assert {v.estado for v in s.query(models.Varrimento).all()} == {"ok"}
