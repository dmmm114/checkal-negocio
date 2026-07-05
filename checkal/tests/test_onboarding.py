"""Testes do onboarding automático de pagantes — app.onboarding (FDS 3, SPEC-FDS3 §onboarding).

Contrato (SPEC-FDS3.md §onboarding):

    processar_onboarding(cliente_id, *, obter_detalhe, enviar) -> ResultadoOnboarding
      · carrega o cliente + o(s) nr(s) associados
      · por cada nr: `obter_detalhe` (INJETADO) → `persistir_detalhe` (detalhes_cliente)
      · `gerar_relatorio_inicial` + `render_pdf` (PDF anexo)
      · compõe o email de boas-vindas (relatório + link da fatura já emitida + link do
        selo `config.BASE_URL/selo/{nr}`) → `enviar` (INJETADO)
      · IDEMPOTENTE: re-processar NÃO duplica envios
      · detalhe `indeterminado`/`nao_encontrado` → relatório sai com ressalva + regista
        tarefa para o dono, sem rebentar (ponto semi-manual, <5%)

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — `obter_detalhe` e
`enviar` são dublês injetados (nunca tocam a rede nem o fornecedor). G4: o relatório
nunca afirma "cancelado" a partir do detalhe. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
)
from app.onboarding import (
    ORIGEM_ONBOARDING,
    ORIGEM_TAREFA_DONO,
    ResultadoOnboarding,
    processar_onboarding,
)


# ==========================================================================
#  Dublês injetados (nunca há rede)
# ==========================================================================
class FakeObterDetalhe:
    """`obter_detalhe(nr)` falso: devolve um `DetalheRegisto` scriptado e conta as chamadas.

    Se `erro` for dado, levanta-o (simula falha de transporte esgotada) para o onboarding
    provar que o degrada para `indeterminado` sem rebentar.
    """

    def __init__(self, estado: str = ESTADO_ATIVO, *, erro: Exception | None = None, **seguro):
        self.estado = estado
        self.erro = erro
        self.seguro = seguro
        self.chamadas: list[int] = []

    def __call__(self, nr, **kw):
        self.chamadas.append(nr)
        if self.erro is not None:
            raise self.erro
        return DetalheRegisto(nr_registo=nr, estado=self.estado, **self.seguro)


class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_onb_1"):
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
#  Fixtures: BD SQLite temporária isolada, com um pagante + registo associado
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_onboarding.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _semear_cliente(*, com_registo: bool = True, email: str = "cliente@exemplo.pt") -> int:
    """Cria um pagante (opcionalmente já casado a um registo) e devolve o `cliente_id`."""
    with db.get_session() as s:
        if com_registo:
            s.add(models.Registo(
                nr_registo=100031, data_registo=date(2019, 7, 16),
                nome_alojamento="Casa do Sol", modalidade="Apartamento",
                concelho="Faro", distrito="Faro",
                titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda",
                nif="513029591", hash_campos="h1",
            ))
        cliente = models.Cliente(
            email=email, nome="Ana Cliente", nif="508000000",
            stripe_customer_id="cus_1", plano="anual", estado="ativo",
            criado_em=datetime(2026, 7, 5, tzinfo=timezone.utc),
            stripe_session_id="cs_onb_1",
            ix_fatura_id="998877", ix_atcud="ABCD1234-6",
            ix_permalink="https://cosmicoasis.app.invoicexpress.com/i/998877",
        )
        s.add(cliente)
        s.flush()
        cid = cliente.id
        if com_registo:
            s.add(models.ClienteRegisto(cliente_id=cid, nr_registo=100031))
    return cid


def _detalhe_ativo() -> FakeObterDetalhe:
    return FakeObterDetalhe(
        ESTADO_ATIVO,
        seguro_companhia="Zurich",
        seguro_apolice="009238995",
        seguro_inicio=date(2025, 12, 12),
        seguro_validade=date(2026, 12, 11),
    )


# ==========================================================================
#  Gera relatório + email de boas-vindas (caminho feliz)
# ==========================================================================
def test_onboarding_gera_relatorio_e_envia(bd):
    cid = _semear_cliente()
    obter = _detalhe_ativo()
    enviar = FakeEnviar()

    res = processar_onboarding(cid, obter_detalhe=obter, enviar=enviar)

    assert isinstance(res, ResultadoOnboarding)
    assert res.cliente_id == cid
    assert res.enviado is True
    assert res.idempotente is False
    assert res.email_id == "re_onb_1"
    assert res.nrs == (100031,)
    assert res.requer_atencao is False

    # o detalhe foi obtido e persistido
    assert obter.chamadas == [100031]
    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d is not None
        assert d.estado_detalhado == ESTADO_ATIVO
        assert d.seguro_companhia == "Zurich"
        assert d.seguro_inicio == date(2025, 12, 12)

    # exatamente um email, para o cliente, com o PDF do relatório em anexo
    assert enviar.n == 1
    chamada = enviar.chamadas[0]
    assert chamada["para"] == "cliente@exemplo.pt"
    assert len(chamada["anexos"]) >= 1
    pdf = chamada["anexos"][0]["conteudo"]
    assert isinstance(pdf, (bytes, bytearray)) and bytes(pdf[:4]) == b"%PDF"
    # o corpo liga ao selo público e à fatura já emitida
    html = chamada["html"]
    assert f"{config.BASE_URL}/selo/100031" in html
    assert "998877" in html  # o permalink da fatura certificada
    # G4: nunca afirma cancelamento
    assert "cancelad" not in html.lower()
    # a chave de idempotência da Resend é estável por cliente
    assert chamada["kw"].get("idempotency_key") == f"onboarding-{cid}"


def test_onboarding_regista_marcador_de_envio(bd):
    cid = _semear_cliente()
    processar_onboarding(cid, obter_detalhe=_detalhe_ativo(), enviar=FakeEnviar())
    with db.get_session() as s:
        marcadores = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == cid, models.Alerta.origem == ORIGEM_ONBOARDING)
            .all()
        )
        assert len(marcadores) == 1
        assert marcadores[0].enviado_em is not None


# ==========================================================================
#  Idempotência — re-processar não duplica envios
# ==========================================================================
def test_onboarding_idempotente_nao_reenvia(bd):
    cid = _semear_cliente()
    enviar = FakeEnviar()

    r1 = processar_onboarding(cid, obter_detalhe=_detalhe_ativo(), enviar=enviar)
    r2 = processar_onboarding(cid, obter_detalhe=_detalhe_ativo(), enviar=enviar)

    assert r1.idempotente is False
    assert r1.enviado is True
    assert r2.idempotente is True
    assert r2.enviado is False
    # o email de boas-vindas saiu UMA só vez apesar das duas passagens
    assert enviar.n == 1
    with db.get_session() as s:
        n_marcadores = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == cid, models.Alerta.origem == ORIGEM_ONBOARDING)
            .count()
        )
        assert n_marcadores == 1


# ==========================================================================
#  Detalhe indeterminado / não encontrado — ressalva + tarefa, sem rebentar
# ==========================================================================
def test_onboarding_detalhe_indeterminado_envia_com_ressalva_e_tarefa(bd):
    cid = _semear_cliente()
    obter = FakeObterDetalhe(ESTADO_INDETERMINADO)
    enviar = FakeEnviar()

    res = processar_onboarding(cid, obter_detalhe=obter, enviar=enviar)

    # o relatório sai à mesma (email enviado) mas assinala que requer atenção
    assert res.enviado is True
    assert res.requer_atencao is True
    assert res.tarefas  # há pelo menos uma tarefa para o dono
    assert enviar.n == 1
    # G4: mesmo com detalhe ambíguo, nunca se afirma "cancelado"
    assert "cancelad" not in enviar.chamadas[0]["html"].lower()
    # a tarefa para o dono ficou persistida
    with db.get_session() as s:
        tarefas = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == cid, models.Alerta.origem == ORIGEM_TAREFA_DONO)
            .all()
        )
        assert len(tarefas) == 1


def test_onboarding_detalhe_nao_encontrado_requer_atencao(bd):
    cid = _semear_cliente()
    res = processar_onboarding(
        cid, obter_detalhe=FakeObterDetalhe(ESTADO_NAO_ENCONTRADO), enviar=FakeEnviar()
    )
    assert res.requer_atencao is True
    assert res.enviado is True


def test_onboarding_falha_obter_detalhe_degrada_para_indeterminado(bd):
    # uma falha de transporte esgotada ao obter o detalhe não pode rebentar o onboarding
    cid = _semear_cliente()
    obter = FakeObterDetalhe(erro=RuntimeError("timeout RNAL"))
    enviar = FakeEnviar()

    res = processar_onboarding(cid, obter_detalhe=obter, enviar=enviar)

    assert res.enviado is True
    assert res.requer_atencao is True
    assert enviar.n == 1
    # persistiu um detalhe conservador (indeterminado), nunca "cancelado"
    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d is not None
        assert d.estado_detalhado == ESTADO_INDETERMINADO


# ==========================================================================
#  Cliente sem registo associado — tarefa para o dono, sem enviar
# ==========================================================================
def test_onboarding_cliente_sem_registo_regista_tarefa_sem_enviar(bd):
    cid = _semear_cliente(com_registo=False)
    obter = _detalhe_ativo()
    enviar = FakeEnviar()

    res = processar_onboarding(cid, obter_detalhe=obter, enviar=enviar)

    assert res.enviado is False
    assert res.requer_atencao is True
    assert res.tarefas
    assert res.nrs == ()
    # sem registo não há detalhe a obter nem email a enviar
    assert obter.chamadas == []
    assert enviar.n == 0
    with db.get_session() as s:
        tarefas = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == cid, models.Alerta.origem == ORIGEM_TAREFA_DONO)
            .count()
        )
        assert tarefas == 1

    # e é idempotente: re-processar não regista outra tarefa
    r2 = processar_onboarding(cid, obter_detalhe=obter, enviar=enviar)
    assert r2.idempotente is True
    with db.get_session() as s:
        assert (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == cid, models.Alerta.origem == ORIGEM_TAREFA_DONO)
            .count()
            == 1
        )


# ==========================================================================
#  Cliente inexistente — não rebenta
# ==========================================================================
def test_onboarding_cliente_inexistente_nao_rebenta(bd):
    enviar = FakeEnviar()
    res = processar_onboarding(999999, obter_detalhe=_detalhe_ativo(), enviar=enviar)
    assert res.enviado is False
    assert res.requer_atencao is True
    assert enviar.n == 0
