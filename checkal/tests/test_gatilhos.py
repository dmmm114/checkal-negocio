"""Testes de `app.campanhas.gatilhos` (FDS 6, SPEC-FDS6.md §gatilhos).

Contrato:

    detetar_gatilhos(session, *, limiar_limpeza=LIMIAR_LIMPEZA) -> list[Gatilho]
      · lê `eventos_registo` (novo | alterado | desaparecido) e
        `eventos_regulatorios` (triagem relevante) AINDA NÃO usados p/ campanha
      · produz candidatos (nrs + motivo):
          novo                → 1 gatilho por registo novo
          alteracao_relevante → 1 gatilho por alteração relevante (registo ou regulatório)
          limpeza             → 1 gatilho por concelho com desaparecimentos em massa
            (>= `limiar_limpeza` desaparecidos no mesmo concelho)
      · IDEMPOTENTE: marca cada evento consumido como usado p/ campanha (âncora
        durável = `alertas` com `canal == CANAL_GATILHO`, SEPARADA do `processado`
        que serve os pipelines de alertas a clientes / regulatório).
      · Fronteira: recebe a `session` do chamador, NÃO faz commit (a transação é
        do orquestrador; rollback = retry natural).

DISCIPLINA: MODO DE TESTE, LIVE-GATED. Zero rede/IA. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.campanhas.gatilhos import (
    CANAL_GATILHO,
    LIMIAR_LIMPEZA,
    MOTIVO_ALTERACAO,
    MOTIVO_LIMPEZA,
    MOTIVO_NOVO,
    ORIGEM_EVENTO_REGISTO,
    ORIGEM_EVENTO_REGULATORIO,
    Gatilho,
    detetar_gatilhos,
)

UTC = timezone.utc
AGORA = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada (espelha test_dunning)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_gatilhos.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


# ==========================================================================
#  Semeadores
# ==========================================================================
_seq = {"nr": 100000, "evt_reg": 0}


def _proximo_nr() -> int:
    _seq["nr"] += 1
    return _seq["nr"]


def _semear_registo(*, nr: int | None = None, concelho: str = "Lisboa",
                    desaparecido: bool = False) -> int:
    nr = nr if nr is not None else _proximo_nr()
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr,
            nome_alojamento=f"AL {nr}",
            concelho=concelho,
            desaparecido_em=(AGORA if desaparecido else None),
            visto_primeiro=AGORA,
            visto_ultimo=AGORA,
        ))
    return nr


def _semear_evento_registo(*, tipo: str, nr: int,
                           campos_alterados: dict | None = None) -> int:
    with db.get_session() as s:
        ev = models.EventoRegisto(
            nr_registo=nr, tipo=tipo, campos_alterados=campos_alterados,
            detetado_em=AGORA, processado=False,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _semear_evento_regulatorio(*, triagem: str, concelhos: list[str],
                               url: str) -> int:
    with db.get_session() as s:
        ev = models.EventoRegulatorio(
            fonte="DRE", url=url, titulo="Regulamento municipal de AL",
            concelhos=concelhos, triagem=triagem, processado=True,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _novo(concelho: str = "Lisboa") -> tuple[int, int]:
    """Cria registo + evento 'novo'. Devolve (nr, evento_id)."""
    nr = _semear_registo(concelho=concelho)
    eid = _semear_evento_registo(tipo="novo", nr=nr)
    return nr, eid


def _desaparecido(concelho: str) -> tuple[int, int]:
    nr = _semear_registo(concelho=concelho, desaparecido=True)
    eid = _semear_evento_registo(tipo="desaparecido", nr=nr)
    return nr, eid


def _detetar(**kw) -> list[Gatilho]:
    with db.get_session() as s:
        return detetar_gatilhos(s, **kw)


def _marcadores(canal: str = CANAL_GATILHO) -> list[models.Alerta]:
    with db.get_session() as s:
        return (
            s.query(models.Alerta)
            .filter(models.Alerta.canal == canal)
            .order_by(models.Alerta.id)
            .all()
        )


# ==========================================================================
#  novo
# ==========================================================================
def test_registo_novo_gera_gatilho(bd):
    nr, eid = _novo(concelho="Porto")

    gatilhos = _detetar()

    assert len(gatilhos) == 1
    g = gatilhos[0]
    assert g.motivo == MOTIVO_NOVO
    assert g.origem == ORIGEM_EVENTO_REGISTO
    assert g.nrs == (nr,)
    assert g.concelhos == ("Porto",)
    assert g.evento_ids == (eid,)


def test_registo_novo_marca_usado(bd):
    nr, eid = _novo()

    _detetar()

    marcadores = _marcadores()
    assert len(marcadores) == 1
    m = marcadores[0]
    assert m.canal == CANAL_GATILHO
    assert m.origem == ORIGEM_EVENTO_REGISTO
    assert m.origem_id == eid
    assert m.nr_registo == nr
    assert m.cliente_id is None       # prospeto, não cliente
    assert m.enviado_em is None       # marcador, não comunicação enviada


# ==========================================================================
#  alteração relevante
# ==========================================================================
def test_alteracao_relevante_gera_gatilho(bd):
    nr = _semear_registo(concelho="Faro")
    eid = _semear_evento_registo(
        tipo="alterado", nr=nr,
        campos_alterados={"modalidade": ["Apartamento", "Moradia"]},
    )

    gatilhos = _detetar()

    assert len(gatilhos) == 1
    g = gatilhos[0]
    assert g.motivo == MOTIVO_ALTERACAO
    assert g.origem == ORIGEM_EVENTO_REGISTO
    assert g.nrs == (nr,)
    assert g.concelhos == ("Faro",)
    assert g.evento_ids == (eid,)


# ==========================================================================
#  limpeza (desaparecimento em massa num concelho)
# ==========================================================================
def test_desaparecidos_abaixo_do_limiar_nao_geram_limpeza(bd):
    # 2 desaparecidos, limiar 3 → nenhum gatilho de limpeza.
    _desaparecido("Sintra")
    _desaparecido("Sintra")

    gatilhos = _detetar(limiar_limpeza=3)

    assert gatilhos == []
    # E — crucial p/ acumulação — os sub-limiar NÃO ficam marcados usados.
    assert _marcadores() == []


def test_desaparecimento_em_massa_gera_uma_limpeza(bd):
    nrs = [
        _desaparecido("Albufeira")[0],
        _desaparecido("Albufeira")[0],
        _desaparecido("Albufeira")[0],
    ]

    gatilhos = _detetar(limiar_limpeza=3)

    assert len(gatilhos) == 1
    g = gatilhos[0]
    assert g.motivo == MOTIVO_LIMPEZA
    assert g.origem == ORIGEM_EVENTO_REGISTO
    assert set(g.nrs) == set(nrs)
    assert g.concelhos == ("Albufeira",)
    assert len(g.evento_ids) == 3
    # marca os 3 eventos usados
    assert len(_marcadores()) == 3


def test_limpeza_por_concelho_isolada(bd):
    # Albufeira atinge o limiar; Loulé não.
    _desaparecido("Albufeira")
    _desaparecido("Albufeira")
    _desaparecido("Loulé")

    gatilhos = _detetar(limiar_limpeza=2)

    motivos = [(g.motivo, g.concelhos) for g in gatilhos]
    assert (MOTIVO_LIMPEZA, ("Albufeira",)) in motivos
    assert not any(g.concelhos == ("Loulé",) for g in gatilhos)


def test_limpeza_acumula_entre_passagens(bd):
    # 1.ª passagem: 2 em Tavira, limiar 3 → sem gatilho, sem marcar.
    _desaparecido("Tavira")
    _desaparecido("Tavira")
    assert _detetar(limiar_limpeza=3) == []
    assert _marcadores() == []

    # Chega mais um → cruza o limiar; a limpeza deve incluir os 3.
    _desaparecido("Tavira")
    gatilhos = _detetar(limiar_limpeza=3)

    assert len(gatilhos) == 1
    assert gatilhos[0].motivo == MOTIVO_LIMPEZA
    assert len(gatilhos[0].nrs) == 3


def test_limiar_limpeza_default_e_5(bd):
    assert LIMIAR_LIMPEZA == 5
    for _ in range(4):
        _desaparecido("Cascais")
    assert _detetar() == []            # 4 < default 5
    _desaparecido("Cascais")
    gatilhos = _detetar()              # 5 == default 5
    assert len(gatilhos) == 1
    assert gatilhos[0].motivo == MOTIVO_LIMPEZA


# ==========================================================================
#  eventos regulatórios
# ==========================================================================
def test_regulatorio_relevante_gera_gatilho(bd):
    eid = _semear_evento_regulatorio(
        triagem="relevante", concelhos=["Funchal"], url="https://dre.pt/a/1",
    )

    gatilhos = _detetar()

    assert len(gatilhos) == 1
    g = gatilhos[0]
    assert g.motivo == MOTIVO_ALTERACAO
    assert g.origem == ORIGEM_EVENTO_REGULATORIO
    assert g.nrs == ()                 # sem nrs específicos (é ao nível do concelho)
    assert g.concelhos == ("Funchal",)
    assert g.evento_ids == (eid,)
    m = _marcadores()
    assert len(m) == 1
    assert m[0].origem == ORIGEM_EVENTO_REGULATORIO
    assert m[0].origem_id == eid
    assert m[0].nr_registo is None


def test_regulatorio_duvida_conta_como_relevante(bd):
    # 🧯 dúvida conta como relevante (nunca calar por dúvida) — mesma regra da triagem.
    _semear_evento_regulatorio(
        triagem="duvida", concelhos=["Lagos"], url="https://dre.pt/a/2",
    )
    gatilhos = _detetar()
    assert len(gatilhos) == 1
    assert gatilhos[0].motivo == MOTIVO_ALTERACAO


def test_regulatorio_irrelevante_ignorado(bd):
    _semear_evento_regulatorio(
        triagem="irrelevante", concelhos=["Lisboa"], url="https://dre.pt/a/3",
    )
    assert _detetar() == []
    assert _marcadores() == []


# ==========================================================================
#  idempotência
# ==========================================================================
def test_segunda_passagem_nao_reemite(bd):
    _novo()
    nr = _semear_registo(concelho="Braga")
    _semear_evento_registo(tipo="alterado", nr=nr, campos_alterados={"nr_camas": [2, 4]})

    primeira = _detetar()
    assert len(primeira) == 2

    segunda = _detetar()
    assert segunda == []               # idempotente: nada de novo

    # marcadores estáveis (2 eventos consumidos, não duplicados)
    assert len(_marcadores()) == 2


def test_idempotente_na_mesma_sessao(bd):
    _novo()
    with db.get_session() as s:
        primeira = detetar_gatilhos(s)
        segunda = detetar_gatilhos(s)   # 2.ª chamada na MESMA sessão (autoflush vê o marcador)
    assert len(primeira) == 1
    assert segunda == []


def test_eventos_mutados_apenas_os_novos_reemitem(bd):
    _novo(concelho="Olhão")
    assert len(_detetar()) == 1

    # muta o estado: chega um novo registo
    nr2, eid2 = _novo(concelho="Setúbal")
    gatilhos = _detetar()

    assert len(gatilhos) == 1
    assert gatilhos[0].nrs == (nr2,)
    assert gatilhos[0].evento_ids == (eid2,)


# ==========================================================================
#  fronteira transacional: não faz commit
# ==========================================================================
def test_nao_faz_commit_transacao_do_chamador(bd):
    _novo()

    # Chamada numa sessão que o teste NÃO faz commit → marcadores não persistem.
    s = db.SessionLocal()
    try:
        gatilhos = detetar_gatilhos(s)
        assert len(gatilhos) == 1      # detetou
    finally:
        s.close()                      # descarta sem commit

    assert _marcadores() == []         # nada persistido

    # Como a âncora não persistiu, uma nova passagem volta a detetar.
    with db.get_session() as s2:
        assert len(detetar_gatilhos(s2)) == 1


# ==========================================================================
#  não colide com os alertas a clientes (canal != CANAL_GATILHO)
# ==========================================================================
def test_alerta_a_cliente_nao_conta_como_usado(bd):
    nr, eid = _novo()
    # Um alerta do pipeline a clientes sobre o MESMO evento, noutro canal, não
    # deve marcar o evento como usado para campanha.
    with db.get_session() as s:
        s.add(models.Alerta(
            cliente_id=1, nr_registo=nr, origem=ORIGEM_EVENTO_REGISTO,
            origem_id=eid, conteudo="alerta ao cliente", canal="email",
        ))

    gatilhos = _detetar()

    assert len(gatilhos) == 1          # o canal 'email' não bloqueia a campanha
    assert gatilhos[0].evento_ids == (eid,)


# ==========================================================================
#  origens mistas numa só passagem
# ==========================================================================
def test_mistura_de_origens(bd):
    nr_novo, _ = _novo(concelho="Nazaré")
    nr_alt = _semear_registo(concelho="Óbidos")
    _semear_evento_registo(tipo="alterado", nr=nr_alt, campos_alterados={"endereco": ["A", "B"]})
    _desaparecido("Mafra")
    _desaparecido("Mafra")
    _semear_evento_regulatorio(triagem="relevante", concelhos=["Cascais"], url="https://dre.pt/a/9")

    gatilhos = _detetar(limiar_limpeza=2)

    motivos = sorted(g.motivo for g in gatilhos)
    assert motivos == sorted([MOTIVO_NOVO, MOTIVO_ALTERACAO, MOTIVO_LIMPEZA, MOTIVO_ALTERACAO])
    # todos os eventos-fonte ficam marcados usados (novo1 + alt1 + desap2 + reg1 = 5)
    assert len(_marcadores()) == 5
