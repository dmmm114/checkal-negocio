"""Testes dos alertas de estado — app.alertas_estado (FDS 3, SPEC-FDS3 §alertas_estado).

Contrato (SPEC-FDS3.md §alertas_estado):

    gerar_alertas_estado(session, *, enviar) -> list[Alerta]
      · lê `eventos_registo` NÃO processados
      · `novo` ignora-se p/ clientes; `alterado`/`desaparecido`/`reapareceu` valem
        para os clientes casados a esse `nr_registo`
      · compõe alerta DETERMINÍSTICO por template (NÃO IA), persiste em `alertas`,
        marca o evento `processado`
      · 🚦 GUARDA: `desaparecido` → persiste `pendente_desambiguacao` e NÃO envia
        (espera o FDS 5); `alterado`/`reapareceu` → envia (via `enviar` injetado)

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — `enviar` é um dublê
injetado. G4: o alerta de `desaparecido` nunca afirma "cancelado" (fonte de verdade do
cancelamento é a desambiguação do FDS 5). Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.rnal.diffing import (
    TIPO_ALTERADO,
    TIPO_DESAPARECIDO,
    TIPO_NOVO,
    TIPO_REAPARECEU,
)
from app.alertas_estado import (
    CANAL_EMAIL,
    CANAL_PENDENTE,
    ORIGEM_EVENTO_REGISTO,
    gerar_alertas_estado,
    pendente_desambiguacao,
)


# ==========================================================================
#  Dublê injetado (nunca há rede)
# ==========================================================================
class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_alerta_1"):
        self.email_id = email_id
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio

        self.chamadas.append(
            {"para": para, "assunto": assunto, "html": html, "anexos": list(anexos), "kw": kw}
        )
        return ResultadoEnvio(id=self.email_id)

    @property
    def n(self) -> int:
        return len(self.chamadas)


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_alertas.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _semear_registo(nr: int, *, nome: str = "Casa do Sol", concelho: str = "Faro") -> None:
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr, data_registo=date(2019, 7, 16), nome_alojamento=nome,
            modalidade="Apartamento", concelho=concelho, distrito="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda",
            nif="513029591", hash_campos="h1",
        ))


def _semear_cliente(*, email: str = "cliente@exemplo.pt", nr: int | None = 100031) -> int:
    """Cria um pagante e (opcionalmente) casa-o a um registo. Devolve o `cliente_id`."""
    with db.get_session() as s:
        cliente = models.Cliente(
            email=email, nome="Ana Cliente", nif="508000000", plano="anual", estado="ativo",
            criado_em=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
        s.add(cliente)
        s.flush()
        cid = cliente.id
        if nr is not None:
            s.add(models.ClienteRegisto(cliente_id=cid, nr_registo=nr))
    return cid


def _semear_evento(
    tipo: str, nr: int, *, campos_alterados=None, processado: bool = False
) -> int:
    with db.get_session() as s:
        ev = models.EventoRegisto(
            nr_registo=nr, tipo=tipo, campos_alterados=campos_alterados,
            varrimento_id=1, detetado_em=datetime(2026, 7, 5, 3, 0, tzinfo=timezone.utc),
            processado=processado,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _run(enviar: FakeEnviar) -> list:
    with db.get_session() as s:
        return gerar_alertas_estado(s, enviar=enviar)


# ==========================================================================
#  `alterado` → envia + persiste + marca o evento processado
# ==========================================================================
def test_alterado_envia_e_persiste(bd):
    _semear_registo(100031)
    cid = _semear_cliente(nr=100031)
    ev_id = _semear_evento(
        TIPO_ALTERADO, 100031, campos_alterados={"modalidade": ["Apartamento", "Moradia"]}
    )
    enviar = FakeEnviar()

    alertas = _run(enviar)

    # exatamente um email, para o cliente
    assert enviar.n == 1
    assert enviar.chamadas[0]["para"] == "cliente@exemplo.pt"

    # devolveu o alerta gerado
    assert len(alertas) == 1

    with db.get_session() as s:
        linhas = s.query(models.Alerta).all()
        assert len(linhas) == 1
        a = linhas[0]
        assert a.cliente_id == cid
        assert a.nr_registo == 100031
        assert a.origem == ORIGEM_EVENTO_REGISTO
        assert a.origem_id == ev_id
        assert a.canal == CANAL_EMAIL
        assert a.enviado_em is not None            # foi enviado
        assert pendente_desambiguacao(a) is False
        # conteúdo determinístico menciona a alteração (campo alterado)
        assert "Moradia" in (a.conteudo or "") or "modalidade" in (a.conteudo or "").lower()
        # G4: um alterado nunca fala de cancelamento
        assert "cancelad" not in (a.conteudo or "").lower()
        # o evento ficou marcado processado
        ev = s.get(models.EventoRegisto, ev_id)
        assert ev.processado is True


# ==========================================================================
#  🚦 `desaparecido` → persiste pendente_desambiguacao e NÃO envia (espera FDS 5)
# ==========================================================================
def test_desaparecido_persiste_mas_nao_envia(bd):
    _semear_registo(100031)
    cid = _semear_cliente(nr=100031)
    ev_id = _semear_evento(TIPO_DESAPARECIDO, 100031)
    enviar = FakeEnviar()

    alertas = _run(enviar)

    # 🚦 nada foi enviado
    assert enviar.n == 0
    assert len(alertas) == 1

    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert a.cliente_id == cid
        assert a.nr_registo == 100031
        assert a.origem == ORIGEM_EVENTO_REGISTO
        assert a.origem_id == ev_id
        assert a.canal == CANAL_PENDENTE          # marcador durável do "pendente"
        assert a.enviado_em is None               # persistido mas NÃO enviado
        assert pendente_desambiguacao(a) is True
        # G4: nunca afirma "cancelado" a partir do desaparecimento
        assert "cancelad" not in (a.conteudo or "").lower()
        # o evento é dado como processado (o alerta ficou persistido, à espera do FDS 5)
        ev = s.get(models.EventoRegisto, ev_id)
        assert ev.processado is True


# ==========================================================================
#  `reapareceu` → envia
# ==========================================================================
def test_reapareceu_envia(bd):
    _semear_registo(100031)
    _semear_cliente(nr=100031)
    ev_id = _semear_evento(TIPO_REAPARECEU, 100031)
    enviar = FakeEnviar()

    alertas = _run(enviar)

    assert enviar.n == 1
    assert len(alertas) == 1
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert a.origem_id == ev_id
        assert a.canal == CANAL_EMAIL
        assert a.enviado_em is not None
        assert pendente_desambiguacao(a) is False


# ==========================================================================
#  Mapeamento evento→cliente: só o cliente casado ao nr do evento é alertado
# ==========================================================================
def test_mapeamento_evento_para_cliente(bd):
    _semear_registo(100031, nome="Casa A")
    _semear_registo(200099, nome="Casa B", concelho="Porto")
    cid_a = _semear_cliente(email="a@exemplo.pt", nr=100031)
    _semear_cliente(email="b@exemplo.pt", nr=200099)  # noutro registo
    ev_id = _semear_evento(TIPO_ALTERADO, 100031, campos_alterados={"nr_camas": [2, 3]})
    enviar = FakeEnviar()

    alertas = _run(enviar)

    # só o cliente A (do registo 100031) é alertado
    assert enviar.n == 1
    assert enviar.chamadas[0]["para"] == "a@exemplo.pt"
    assert len(alertas) == 1
    with db.get_session() as s:
        linhas = s.query(models.Alerta).all()
        assert len(linhas) == 1
        assert linhas[0].cliente_id == cid_a
        assert linhas[0].origem_id == ev_id


# ==========================================================================
#  Multi-titular no mesmo registo: cada cliente recebe o seu alerta
# ==========================================================================
def test_alterado_multi_cliente_mesmo_registo(bd):
    _semear_registo(100031)
    _semear_cliente(email="a@exemplo.pt", nr=100031)
    _semear_cliente(email="b@exemplo.pt", nr=100031)
    _semear_evento(TIPO_ALTERADO, 100031, campos_alterados={"modalidade": ["A", "B"]})
    enviar = FakeEnviar()

    alertas = _run(enviar)

    assert enviar.n == 2
    assert {c["para"] for c in enviar.chamadas} == {"a@exemplo.pt", "b@exemplo.pt"}
    assert len(alertas) == 2


# ==========================================================================
#  `novo` ignora-se para clientes (mas o evento drena — fica processado)
# ==========================================================================
def test_novo_ignora_para_clientes_mas_marca_processado(bd):
    _semear_registo(100031)
    _semear_cliente(nr=100031)
    ev_id = _semear_evento(TIPO_NOVO, 100031)
    enviar = FakeEnviar()

    alertas = _run(enviar)

    assert enviar.n == 0
    assert alertas == []
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
        ev = s.get(models.EventoRegisto, ev_id)
        assert ev.processado is True   # drenado da fila, sem alerta


# ==========================================================================
#  Evento cujo nr não tem clientes: sem alerta, mas drena (processado)
# ==========================================================================
def test_evento_sem_clientes_marca_processado_sem_alerta(bd):
    _semear_registo(100031)  # sem cliente associado
    ev_id = _semear_evento(TIPO_ALTERADO, 100031, campos_alterados={"modalidade": ["A", "B"]})
    enviar = FakeEnviar()

    alertas = _run(enviar)

    assert enviar.n == 0
    assert alertas == []
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
        assert s.get(models.EventoRegisto, ev_id).processado is True


# ==========================================================================
#  Idempotência: evento já processado não reprocessa; correr 2× não duplica
# ==========================================================================
def test_idempotencia_evento_processado_nao_reprocessa(bd):
    _semear_registo(100031)
    _semear_cliente(nr=100031)
    _semear_evento(TIPO_ALTERADO, 100031, campos_alterados={"modalidade": ["A", "B"]})
    enviar = FakeEnviar()

    r1 = _run(enviar)
    r2 = _run(enviar)   # 2.ª passagem: nada novo

    assert len(r1) == 1
    assert r2 == []
    assert enviar.n == 1   # o alerta saiu UMA só vez
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 1


def test_evento_ja_processado_ignorado(bd):
    _semear_registo(100031)
    _semear_cliente(nr=100031)
    _semear_evento(
        TIPO_ALTERADO, 100031, campos_alterados={"modalidade": ["A", "B"]}, processado=True
    )
    enviar = FakeEnviar()

    alertas = _run(enviar)

    assert alertas == []
    assert enviar.n == 0
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
