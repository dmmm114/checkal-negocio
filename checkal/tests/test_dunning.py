"""Testes do dunning — app.dunning (FDS 5, SPEC-FDS5.md §dunning · AUTOMACAO §5).

Contrato (SPEC-FDS5.md §dunning · AUTOMACAO.md §137):

    correr_dunning(agora, *, enviar) -> list[PassoDunning]
      · cron DIÁRIO; relógio (`agora`) e `enviar` **injetados**
      · máquina de estados sobre `clientes` (`ativo`→`em_dunning`→`cancelado`)
      · sequência anual: D-30 (aviso de renovação + resumo de valor), D-7 (aviso),
        D0 (a Stripe cobra — não é passo NOSSO), D+3/D+7 (emails de falha, só se a
        cobrança falhou → estado `em_dunning`), D+21 (downgrade `cancelado` + email final)
      · TRIENAL/pré-pago: sem dunning; só email a D-30 do fim
      · IDEMPOTENTE: não reenvia o mesmo passo (marcador durável em `alertas`)

A data de renovação deriva de `criado_em + PLANOS[plano].meses` (o esquema de
`clientes` não tem coluna de renovação — não se altera no FDS 5). A transição
`ativo→em_dunning` é do webhook `invoice.payment_failed` (FDS 2,
`fulfillment.registar_falha_pagamento`); aqui simula-se assentando `estado`.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede/IA/IMAP — `enviar`
é um dublê injetado. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.dunning import (
    ORIGEM_DUNNING,
    PASSO_D3,
    PASSO_D7,
    PASSO_D7_POS,
    PASSO_D21,
    PASSO_D30,
    DunningIncompleto,
    PassoDunning,
    correr_dunning,
)

UTC = timezone.utc

# Datas-âncora: cliente criado a 2026-07-05 → renovação anual a 2027-07-05.
CRIADO = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
RENOVA = date(2027, 7, 5)


# ==========================================================================
#  Dublê injetado (nunca há rede)
# ==========================================================================
class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_dunning_1"):
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


class EnviarComFalha:
    """`enviar` que levanta na N-ésima chamada (1-indexed); as outras registam e seguem."""

    def __init__(self, falhar_na: int = 1) -> None:
        self.falhar_na = falhar_na
        self.chamadas: list[str] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        self.chamadas.append(para)
        if len(self.chamadas) == self.falhar_na:
            raise RuntimeError("Resend indisponível")
        from app.envio import ResultadoEnvio

        return ResultadoEnvio(id="re_falha")

    @property
    def n(self) -> int:
        return len(self.chamadas)


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_dunning.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _semear_cliente(
    *,
    email: str = "cliente@exemplo.pt",
    plano: str = "anual",
    estado: str = "ativo",
    criado_em: datetime = CRIADO,
) -> int:
    with db.get_session() as s:
        cliente = models.Cliente(
            email=email, nome="Ana Cliente", nif="508000000",
            stripe_customer_id="cus_1", plano=plano, estado=estado, criado_em=criado_em,
        )
        s.add(cliente)
        s.flush()
        return cliente.id


def _estado(cid: int) -> str:
    with db.get_session() as s:
        return s.get(models.Cliente, cid).estado


def _set_estado(cid: int, estado: str) -> None:
    """Simula o webhook `invoice.payment_failed`/renovação a assentar o estado."""
    with db.get_session() as s:
        s.get(models.Cliente, cid).estado = estado


def _agora(d: date, *, hora: int = 9) -> datetime:
    return datetime(d.year, d.month, d.day, hora, 0, tzinfo=UTC)


def _dia(offset: int) -> date:
    return date.fromordinal(RENOVA.toordinal() + offset)


def _run(agora: datetime, enviar: FakeEnviar) -> list[PassoDunning]:
    return correr_dunning(agora, enviar=enviar)


def _alertas():
    with db.get_session() as s:
        return s.query(models.Alerta).order_by(models.Alerta.id).all()


# ==========================================================================
#  D-30 → aviso de renovação (com resumo de valor), estado mantém-se ativo
# ==========================================================================
def test_d30_envia_aviso_renovacao(bd):
    cid = _semear_cliente()
    enviar = FakeEnviar()

    passos = _run(_agora(_dia(-30)), enviar)

    assert len(passos) == 1
    p = passos[0]
    assert p.cliente_id == cid
    assert p.passo == PASSO_D30
    assert p.enviado is True
    assert p.cancelou is False

    assert enviar.n == 1
    ch = enviar.chamadas[0]
    assert ch["para"] == "cliente@exemplo.pt"
    # o assunto/corpo menciona a data de renovação (05/07/2027) — DD/MM/AAAA
    assert "05/07/2027" in (ch["assunto"] + ch["html"])

    assert _estado(cid) == "ativo"  # D-30 não muda o estado
    linhas = _alertas()
    assert len(linhas) == 1
    a = linhas[0]
    assert a.origem.startswith(ORIGEM_DUNNING + ":")
    assert a.enviado_em is not None


def test_d30_idempotente_nao_reenvia(bd):
    _semear_cliente()
    enviar = FakeEnviar()

    _run(_agora(_dia(-30)), enviar)
    p2 = _run(_agora(_dia(-29)), enviar)  # dia seguinte, ainda na janela

    assert p2 == []
    assert enviar.n == 1  # saiu UMA só vez
    assert len(_alertas()) == 1


def test_d30_resumo_de_valor_entregue(bd):
    """O D-30 traz o resumo do que foi entregue (nº de varrimentos e alertas)."""
    cid = _semear_cliente()
    # 2 varrimentos concluídos no último ano + 1 alerta de estado enviado ao cliente
    with db.get_session() as s:
        for i in range(2):
            s.add(models.Varrimento(
                iniciado_em=datetime(2026, 10, 1, tzinfo=UTC),
                concluido_em=datetime(2026, 10, 1 + i, tzinfo=UTC),
                estado="ok", total_registos=100,
            ))
        s.add(models.Alerta(
            cliente_id=cid, nr_registo=100031, origem="eventos_registo",
            conteudo="alterou", canal="email", enviado_em=datetime(2026, 11, 1, tzinfo=UTC),
        ))
    enviar = FakeEnviar()

    _run(_agora(_dia(-30)), enviar)

    corpo = enviar.chamadas[0]["html"].lower()
    assert "2" in corpo and "varrimento" in corpo


# ==========================================================================
#  D-7 → segundo aviso, ainda ativo
# ==========================================================================
def test_d7_envia_aviso(bd):
    cid = _semear_cliente()
    enviar = FakeEnviar()

    passos = _run(_agora(_dia(-7)), enviar)

    assert [p.passo for p in passos] == [PASSO_D7]
    assert enviar.n == 1
    assert _estado(cid) == "ativo"


# ==========================================================================
#  D0 (dia da renovação) → não é passo NOSSO (a Stripe cobra); nada sai
# ==========================================================================
def test_d0_sem_accao(bd):
    _semear_cliente()
    enviar = FakeEnviar()

    passos = _run(_agora(_dia(0)), enviar)

    assert passos == []
    assert enviar.n == 0


# ==========================================================================
#  Pagamento bem-sucedido → sem emails de falha (post só corre em em_dunning)
# ==========================================================================
def test_pagamento_ok_sem_dunning_pos(bd):
    cid = _semear_cliente(estado="ativo")  # renovou bem: continua ativo
    enviar = FakeEnviar()

    passos_d3 = _run(_agora(_dia(3)), enviar)
    passos_d21 = _run(_agora(_dia(21)), enviar)

    assert passos_d3 == [] and passos_d21 == []
    assert enviar.n == 0
    assert _estado(cid) == "ativo"  # nunca cancela um cliente que pagou


# ==========================================================================
#  🚦 SEQUÊNCIA COMPLETA — cartão falhado percorre tudo até cancelado
# ==========================================================================
def test_sequencia_completa_cartao_falhado(bd):
    cid = _semear_cliente()
    enviar = FakeEnviar()

    # D-30 e D-7 (ainda ativo, pré-cobrança)
    assert [p.passo for p in _run(_agora(_dia(-30)), enviar)] == [PASSO_D30]
    assert [p.passo for p in _run(_agora(_dia(-7)), enviar)] == [PASSO_D7]
    assert _estado(cid) == "ativo"

    # D0: a Stripe tenta cobrar e FALHA → o webhook assenta em_dunning (simulado)
    _run(_agora(_dia(0)), enviar)  # o nosso cron nada faz em D0
    _set_estado(cid, "em_dunning")

    # D+3 e D+7: emails de falha
    assert [p.passo for p in _run(_agora(_dia(3)), enviar)] == [PASSO_D3]
    assert [p.passo for p in _run(_agora(_dia(7)), enviar)] == [PASSO_D7_POS]
    assert _estado(cid) == "em_dunning"

    # D+21: downgrade para cancelado + email final
    passos = _run(_agora(_dia(21)), enviar)
    assert len(passos) == 1
    assert passos[0].passo == PASSO_D21
    assert passos[0].cancelou is True
    assert _estado(cid) == "cancelado"

    # percorreu tudo: 5 emails (D-30, D-7, D+3, D+7, D+21)
    assert enviar.n == 5

    # idempotência terminal: reprocessar D+21 não reenvia nem re-cancela
    assert _run(_agora(_dia(21)), enviar) == []
    assert enviar.n == 5


def test_pos_passos_so_em_dunning(bd):
    """Sem falha de cobrança (estado ativo em D+3) não sai email de falha."""
    _semear_cliente(estado="ativo")
    enviar = FakeEnviar()
    assert _run(_agora(_dia(3)), enviar) == []
    assert enviar.n == 0


def test_d21_cancela_mesmo_em_catchup(bd):
    """Se o cron esteve em baixo, D+21 ainda cancela um em_dunning muito atrasado."""
    cid = _semear_cliente(estado="em_dunning")
    enviar = FakeEnviar()

    passos = _run(_agora(_dia(90)), enviar)  # 90 dias após a renovação falhada

    assert len(passos) == 1 and passos[0].passo == PASSO_D21
    assert _estado(cid) == "cancelado"


# ==========================================================================
#  TRIENAL / pré-pago → só D-30, sem D-7 e sem dunning
# ==========================================================================
def test_trienal_so_d30(bd):
    # trienal = 36 meses → renova a 2029-07-05
    cid = _semear_cliente(plano="trienal")
    fim = date(2029, 7, 5)
    enviar = FakeEnviar()

    # D-30 do fim → sai o aviso
    d30 = _run(_agora(date.fromordinal(fim.toordinal() - 30)), enviar)
    assert [p.passo for p in d30] == [PASSO_D30]
    assert enviar.n == 1

    # D-7 do fim → NÃO sai (pré-pago não tem 2.º aviso)
    d7 = _run(_agora(date.fromordinal(fim.toordinal() - 7)), enviar)
    assert d7 == []
    assert enviar.n == 1


def test_trienal_sem_dunning_pos(bd):
    """Mesmo em em_dunning (não deveria acontecer no pré-pago), não há D+3/D+21."""
    cid = _semear_cliente(plano="trienal", estado="em_dunning")
    fim = date(2029, 7, 5)
    enviar = FakeEnviar()

    p = _run(_agora(date.fromordinal(fim.toordinal() + 21)), enviar)

    assert p == []
    assert enviar.n == 0
    assert _estado(cid) == "em_dunning"  # o pré-pago não é cancelado por dunning


# ==========================================================================
#  Estado terminal e isolamento
# ==========================================================================
def test_cancelado_e_ignorado(bd):
    cid = _semear_cliente(estado="cancelado")
    enviar = FakeEnviar()
    assert _run(_agora(_dia(-30)), enviar) == []
    assert _run(_agora(_dia(21)), enviar) == []
    assert enviar.n == 0
    assert _estado(cid) == "cancelado"


def test_isolamento_entre_clientes(bd):
    """O passo de um cliente não afeta outro (datas/planos diferentes)."""
    cid_a = _semear_cliente(email="a@exemplo.pt")                       # renova 2027-07-05
    cid_b = _semear_cliente(email="b@exemplo.pt",
                            criado_em=datetime(2026, 1, 5, tzinfo=UTC))  # renova 2027-01-05
    enviar = FakeEnviar()

    # No D-30 de A, B está longe da renovação → só A recebe
    passos = _run(_agora(_dia(-30)), enviar)

    assert len(passos) == 1
    assert passos[0].cliente_id == cid_a
    assert enviar.chamadas[0]["para"] == "a@exemplo.pt"
    assert _estado(cid_b) == "ativo"


def test_pre_passos_exigem_ativo(bd):
    """Um cliente já em_dunning na janela pré-renovação não recebe o aviso D-30."""
    _semear_cliente(estado="em_dunning")
    enviar = FakeEnviar()
    assert _run(_agora(_dia(-30)), enviar) == []
    assert enviar.n == 0


# ==========================================================================
#  🚦 FIX B — isolamento por cliente: a falha de envio de um não aborta o lote
# ==========================================================================
def test_falha_de_envio_de_um_cliente_nao_aborta_o_lote(bd):
    """FIX B: `enviar` levanta no 1.º de 3 clientes (todos em D-30) → os outros 2 são
    processados na mesma; no fim sinaliza-se (DunningIncompleto) para pingar /fail."""
    _semear_cliente(email="c0@exemplo.pt")
    _semear_cliente(email="c1@exemplo.pt")
    _semear_cliente(email="c2@exemplo.pt")
    enviar = EnviarComFalha(falhar_na=1)  # o 1.º cliente falha o envio

    with pytest.raises(DunningIncompleto) as exc:
        _run(_agora(_dia(-30)), enviar)

    # exatamente 1 falha; os 3 clientes foram TENTADOS (o 1.º rebentou, os 2 seguiram)
    assert exc.value.n_falhas == 1
    assert enviar.n == 3
    # os 2 passos que correram estão em `executados` e persistidos (o 1.º foi revertido)
    assert len(exc.value.executados) == 2
    linhas = _alertas()
    assert len(linhas) == 2
    assert {a.enviado_em is not None for a in linhas} == {True}


def test_falha_de_envio_nao_impede_cancelamento_de_outro(bd):
    """FIX B: mesmo que um cliente falhe o envio, um D+21 de OUTRO cliente ainda cancela
    (o cancelamento não é bloqueado pela falha de um vizinho)."""
    # `falha`: criado 2026-07-05 → renova 2027-07-05; hoje = _dia(-30) = 2027-06-05 → D-30.
    falha = _semear_cliente(email="falha@exemplo.pt")             # D-30, envio vai rebentar
    # `tardio`: criado 2026-05-05 → renova 2027-05-05; hoje = 2027-06-05 → dias = -31 → D+21.
    tardio = _semear_cliente(email="tardio@exemplo.pt",
                             estado="em_dunning",
                             criado_em=datetime(2026, 5, 5, tzinfo=UTC))
    enviar = EnviarComFalha(falhar_na=1)  # o 1.º cliente processado (falha) rebenta o envio

    with pytest.raises(DunningIncompleto):
        _run(_agora(_dia(-30)), enviar)

    assert _estado(tardio) == "cancelado"   # o D+21 do vizinho correu na mesma
    assert _estado(falha) == "ativo"        # o que falhou não avançou de estado
