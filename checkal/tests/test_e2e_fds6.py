"""Teste de INTEGRAÇÃO ponta-a-ponta do FDS 6 (SPEC-FDS6.md §INTEGRAÇÃO) — HARD-GATED.

Prova o motor de campanhas ligado de ponta a ponta — gatilho → segmentação (núcleo
de compliance) → composição → envio/pendente/carta — sobre um lote MISTO realista, e
verifica que o 🚦 PORTÃO BLOQUEANTE é CÓDIGO, não disciplina humana:

Lote semeado (4 registos + 1 gatilho `novo` cada):

  · COLETIVA 5/6 GENÉRICA  (nif 5…, geral@empresa.pt)        -> ÚNICO elegível a cold
  · COLETIVA 5/6 PESSOAL   (nif 5…, joao.silva@…)            -> carta (email não endereçável)
  · COLETIVA 5/6 EM OPT-OUT/DGC (nif 6…, reservas@dois.pt)   -> suprimida (nem cold nem carta)
  · SINGULAR 1/2/3 GENÉRICO (nif 1…, geral@quatro.pt)        -> carta, NUNCA cold

Fase 1 — `CHECKAL_PARECER_RGPD_OK=False` (o default, inviolável):
  · SÓ a coletiva genérica não-oposta entra no segmento cold;
  · NADA é enviado — o remetente mock NUNCA é chamado; o cold fica em `pendentes_parecer`
    com razão `gate_fechado`;
  · o singular gera CARTA e NUNCA cold; a coletiva de email pessoal também vai à carta;
  · o email pessoal e a oposta NÃO entram em cold; a oposta é registada em `optouts`.

Fase 2 — liga o parecer (mock) + `remetente_frio` (mock) + modo de teste OFF + SMTP de
cold: SÓ o contacto endereçável recebe, e o email leva o opt-out 1-clique
(`checkal.pt/remover`) no corpo E no header `List-Unsubscribe`, saindo de getcheckal.com
(NUNCA checkal.pt — fronteira dura). A oposta continua suprimida; singular/pessoal
continuam só na carta.

DISCIPLINA (inviolável, SPEC-FDS6.md §disciplina): **MODO DE TESTE, LIVE-GATED.** Zero
rede/SMTP real — o `remetente_frio` embrulha o seam REAL `cold_email.enviar_frio` sobre
um cliente SMTP FALSO (captura a `EmailMessage`), e as cartas são um gerador mock. BD
SQLite temporária. Este ficheiro NUNCA importa `app.envio`/Resend (fronteira dura).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.campanhas import cold_email, motor

UTC = timezone.utc
AGORA = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada (espelha test_motor)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_fds6.db'}"
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
#  Duplos de teste — nunca tocam a rede
# ==========================================================================
class FakeRemetente:
    """Remetente frio falso: regista cada chamada. Prova que NÃO foi chamado (parecer OFF)."""

    def __init__(self):
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, **kw):
        self.chamadas.append({"para": para, "assunto": assunto, "html": html})
        return cold_email.ResultadoFrio(
            para=para, remetente=config.COLD_FROM, link_remocao=cold_email.link_remocao(para)
        )


class FakeCartas:
    """Gerador de cartas falso: captura os prospetos e devolve bytes de PDF."""

    def __init__(self):
        self.prospetos: list = []

    def __call__(self, prospetos, **kw):
        self.prospetos = list(prospetos)
        return b"%PDF-1.4 fake"


class SMTPFalso:
    """Cliente SMTP falso à laia de `smtplib.SMTP`: captura a `EmailMessage`, aceita tudo."""

    def __init__(self):
        self.mensagens: list = []

    def send_message(self, msg):
        self.mensagens.append(msg)
        return {}  # dict vazio = todos os destinatários aceites


def _remetente_real_sobre_smtp_falso(smtp: SMTPFalso):
    """Remetente que embrulha o seam REAL `cold_email.enviar_frio` sobre um SMTP falso.

    É o que torna a Fase 2 um verdadeiro e2e: o opt-out 1-clique não é cravado pela
    copy (o motor deixa-o para o seam) — só passando pelo seam real é que ele é
    carimbado no corpo E nos headers. Continua 100% offline (SMTP injetado, mock).
    """

    def remetente(*, para, assunto, html, **kw):
        return cold_email.enviar_frio(
            para=para, assunto=assunto, html=html, cliente_smtp=smtp
        )

    return remetente


def _abrir_todos_os_gates(monkeypatch):
    """Abre o triplo gate GLOBAL: parecer OK + modo de teste OFF + SMTP de cold presente."""
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "cold@getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "segredo")


# ==========================================================================
#  Semeadores
# ==========================================================================
def _semear_registo(*, nr, nif, email, nome, tipo, concelho="Lisboa") -> None:
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr,
            nome_alojamento=f"AL {nr}",
            concelho=concelho,
            endereco="Rua Um, 1",
            cod_postal="1000-001",
            freguesia="Sé",
            titular_tipo=tipo,
            titular_nome=nome,
            nif=nif,
            email=email,
            visto_primeiro=AGORA,
            visto_ultimo=AGORA,
        ))


def _semear_evento_novo(*, nr) -> None:
    with db.get_session() as s:
        s.add(models.EventoRegisto(
            nr_registo=nr, tipo="novo", detetado_em=AGORA, processado=False,
        ))


# Contactos alvo (email do opt-out cruza com a lista DGC injetada) --------------
GENERICA = dict(nr=101, nif="500000001", email="geral@empresa.pt", nome="Empresa Um, Lda", tipo="coletiva")
PESSOAL = dict(nr=102, nif="500000003", email="joao.silva@tres.pt", nome="Tres, Lda", tipo="coletiva")
OPOSTA = dict(nr=103, nif="600000002", email="reservas@dois.pt", nome="Dois SA", tipo="coletiva")
SINGULAR = dict(nr=104, nif="123456789", email="geral@quatro.pt", nome="Ana Singular", tipo="singular")

DGC = frozenset({"reservas@dois.pt"})  # oposição da coletiva 103


def _semear_lote_misto() -> None:
    """Semeia os 4 registos mistos + 1 gatilho `novo` por cada (janela fresca)."""
    for reg in (GENERICA, PESSOAL, OPOSTA, SINGULAR):
        _semear_registo(**reg)
        _semear_evento_novo(nr=reg["nr"])


def _correr(**kw) -> motor.ResultadoCampanha:
    kw.setdefault("agora", AGORA)
    with db.get_session() as s:
        return motor.correr_campanhas(s, **kw)


# ==========================================================================
#  FASE 1 — parecer OFF: segmenta certo, mas NADA sai (o teste-âncora)
# ==========================================================================
def test_e2e_parecer_off_segmenta_certo_e_nada_e_enviado(bd):
    _semear_lote_misto()
    rem = FakeRemetente()
    cartas = FakeCartas()

    res = _correr(remetente_frio=rem, gerar_cartas=cartas, lista_dgc=DGC)

    # Os 4 registos novos geraram 4 gatilhos.
    assert res.gatilhos == 4

    # 🚦 PORTÃO: parecer OFF ⇒ NADA é enviado, o remetente NUNCA é chamado.
    assert res.enviados == []
    assert rem.chamadas == []

    # SÓ a coletiva genérica não-oposta entrou no segmento cold (fica pendente).
    assert [p.para for p in res.pendentes_parecer] == ["geral@empresa.pt"]
    pend = res.pendentes_parecer[0]
    assert pend.razao == motor.RAZAO_GATE          # retido pelo portão, não pelo cap
    assert "Empresa Um, Lda" in pend.html
    assert "101" in pend.assunto
    assert pend.proveniencia                        # proveniência registada (lookup dirigido)

    # A oposta (DGC) foi suprimida do cold e registada — NEM cold NEM carta.
    assert "reservas@dois.pt" in res.optouts

    # Singular genérico e coletiva de email PESSOAL vão à carta; a oposta NÃO.
    nrs_carta = sorted(p.nr_registo for p in cartas.prospetos)
    assert nrs_carta == [102, 104]
    assert res.cartas == 2
    assert res.carta_pdf == b"%PDF-1.4 fake"

    # Email pessoal e oposta NUNCA entram em cold (nem enviados nem pendentes).
    paras_cold = {p.para for p in res.pendentes_parecer} | {e.para for e in res.enviados}
    assert "joao.silva@tres.pt" not in paras_cold
    assert "reservas@dois.pt" not in paras_cold
    assert "geral@quatro.pt" not in paras_cold      # o genérico do SINGULAR nunca é cold


# ==========================================================================
#  FASE 2 — parecer ON + remetente + modo OFF: só o endereçável recebe, com opt-out
# ==========================================================================
def test_e2e_parecer_on_so_enderecavel_recebe_com_optout(bd, monkeypatch):
    _semear_lote_misto()
    _abrir_todos_os_gates(monkeypatch)
    smtp = SMTPFalso()
    rem = _remetente_real_sobre_smtp_falso(smtp)
    cartas = FakeCartas()

    res = _correr(remetente_frio=rem, gerar_cartas=cartas, lista_dgc=DGC)

    # SÓ o contacto endereçável (coletiva genérica não-oposta) recebe.
    assert [e.para for e in res.enviados] == ["geral@empresa.pt"]
    assert res.pendentes_parecer == []
    assert len(smtp.mensagens) == 1

    msg = smtp.mensagens[0]
    assert msg["To"] == "geral@empresa.pt"

    # Fronteira dura: sai de getcheckal.com, NUNCA de checkal.pt.
    assert "@getcheckal.com" in msg["From"]
    assert "checkal.pt" not in msg["From"]

    # Opt-out 1-clique carimbado pelo seam: no header List-Unsubscribe E no corpo HTML.
    assert "checkal.pt/remover" in msg["List-Unsubscribe"]
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    corpo_html = msg.get_body(preferencelist=("html",)).get_content()
    assert "checkal.pt/remover" in corpo_html

    # A oposta continua suprimida; singular/pessoal continuam só na carta, nunca cold.
    assert "reservas@dois.pt" in res.optouts
    assert "reservas@dois.pt" not in {e.para for e in res.enviados}
    assert sorted(p.nr_registo for p in cartas.prospetos) == [102, 104]
    assert res.cartas == 2
