"""Testes do circuit breaker por concelho — app.breaker (FDS 5, SPEC-FDS5.md §breaker).

O breaker é o **módulo-chave** do FDS 5: resolve a 🚦 guarda de sequência do FDS 1/3
(`app/rnal/LIMITACOES-CONHECIDAS.md`). Contrato (SPEC-FDS5.md §breaker)::

    avaliar_concelho(concelho, desaparecidos, base_total) -> Decisao
      · dispara desambiguação se desaparecidos/base_total > BREAKER_PCT_CONCELHO

    desambiguar(concelho, nrs_amostra, *, obter_detalhe) -> Veredicto
      · amostra páginas individuais via `obter_detalhe` INJETADO
      · cancelado/suspenso predominante   -> real
      · nao_encontrado / erro predominante -> api_partida
      · mistura inconclusiva               -> ambiguo

    resolver_pendentes(session, concelho, veredicto, *, enviar, escalar=None) -> Resolucao
      · real        -> LIBERTA os alertas `desaparecido` retidos (envia, data enviado_em)
      · api_partida -> SUPRIME (reabre o evento p/ retry, não envia) + FYI ao dono
      · ambiguo     -> ESCALA ao dono, NÃO envia (retém os pendentes)
      · ISOLAMENTO por concelho: o breaker de um concelho nunca afeta outro

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede/IA/IMAP/subprocess —
`obter_detalhe`, `enviar` e `escalar` são dublês injetados; BD SQLite temporária. 🚦 o
alerta `desaparecido` só é enviado DEPOIS de o breaker confirmar cancelamento REAL —
nunca antes. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.alertas_estado import (
    CANAL_EMAIL,
    CANAL_PENDENTE,
    ORIGEM_EVENTO_REGISTO,
    gerar_alertas_estado,
    pendente_desambiguacao,
)
from app.breaker import (
    MAX_AMOSTRA,
    PREDOMINANCIA_MINIMA,
    VEREDICTO_AMBIGUO,
    VEREDICTO_API_PARTIDA,
    VEREDICTO_REAL,
    Decisao,
    Resolucao,
    Veredicto,
    avaliar_concelho,
    desambiguar,
    resolver_pendentes,
)
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_CANCELADO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    ESTADO_SUSPENSO,
    DetalheRegisto,
)
from app.rnal.diffing import TIPO_DESAPARECIDO


# ==========================================================================
#  Dublês injetados (nunca há rede/IA/IMAP)
# ==========================================================================
class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_breaker_1") -> None:
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


class FakeEscalar:
    """`escalar(mensagem)` falso: guarda as mensagens de escalação/FYI ao dono."""

    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def __call__(self, mensagem: str):
        self.mensagens.append(mensagem)

    @property
    def n(self) -> int:
        return len(self.mensagens)


class ObterDetalheFalso:
    """`obter_detalhe(nr)` falso: devolve `DetalheRegisto` com o estado mapeado, ou levanta.

    `mapa`: nr -> estado (str) ou a sentinela `ERRO` (simula falha de transporte).
    `padrao`: estado dos nrs fora do mapa. Regista `chamadas` (nada toca a rede).
    """

    ERRO = object()

    def __init__(self, mapa: dict | None = None, *, padrao: str = ESTADO_NAO_ENCONTRADO) -> None:
        self.mapa = dict(mapa or {})
        self.padrao = padrao
        self.chamadas: list[int] = []

    def __call__(self, nr: int, **kw):
        self.chamadas.append(nr)
        estado = self.mapa.get(nr, self.padrao)
        if estado is self.ERRO:
            raise RuntimeError(f"rede partida ao obter nr={nr}")
        return DetalheRegisto(nr_registo=nr, estado=estado)


def _uniforme(estado, nrs) -> ObterDetalheFalso:
    """`obter_detalhe` que devolve sempre `estado` (ou levanta se `estado is ERRO`)."""
    return ObterDetalheFalso({nr: estado for nr in nrs}, padrao=estado)


# ==========================================================================
#  Fixture: BD SQLite temporária isolada (como test_alertas_estado / test_ingest)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_breaker.db'}"
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
#  Semeadores de estado (registo + cliente casado + evento desaparecido)
# --------------------------------------------------------------------------
def _semear_registo(nr: int, *, nome: str = "Casa X", concelho: str = "Porto") -> None:
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr, nome_alojamento=nome, concelho=concelho, distrito="X",
            titular_tipo="coletiva", titular_nome="AL, Lda", nif="513029591", hash_campos="h",
        ))


def _semear_cliente(nr: int, *, email: str = "cliente@ex.pt") -> int:
    with db.get_session() as s:
        c = models.Cliente(
            email=email, nome="Cliente", nif="508000000", plano="anual", estado="ativo",
            criado_em=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
        s.add(c)
        s.flush()
        cid = c.id
        s.add(models.ClienteRegisto(cliente_id=cid, nr_registo=nr))
    return cid


def _semear_evento_desaparecido(nr: int) -> int:
    with db.get_session() as s:
        ev = models.EventoRegisto(
            nr_registo=nr, tipo=TIPO_DESAPARECIDO, varrimento_id=1,
            detetado_em=datetime(2026, 7, 5, 3, 0, tzinfo=timezone.utc), processado=False,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _mint_pendentes() -> None:
    """Transforma os eventos `desaparecido` em alertas `pendente_desambiguacao`.

    Faz exatamente o que o FDS 3 faz em produção: `gerar_alertas_estado` persiste o
    alerta retido (canal `pendente`, `enviado_em IS NULL`) e marca o evento processado.
    """
    with db.get_session() as s:
        gerar_alertas_estado(s, enviar=FakeEnviar())


def _cenario_pendente(nr: int, *, concelho: str, email: str = "cliente@ex.pt") -> tuple[int, int]:
    """Semeia um pendente completo para `nr` no `concelho`. Devolve (cliente_id, evento_id)."""
    _semear_registo(nr, concelho=concelho)
    cid = _semear_cliente(nr, email=email)
    ev_id = _semear_evento_desaparecido(nr)
    _mint_pendentes()
    return cid, ev_id


def _alerta_de(nr: int) -> models.Alerta:
    with db.get_session() as s:
        return s.query(models.Alerta).filter(models.Alerta.nr_registo == nr).one()


# ==========================================================================
#  avaliar_concelho — porta do limiar (pura)
# ==========================================================================
def test_avaliar_dispara_acima_do_limiar():
    # 40/1000 = 4% > 3% (BREAKER_PCT_CONCELHO)
    dec = avaliar_concelho("Porto", list(range(1, 41)), 1000)
    assert isinstance(dec, Decisao)
    assert dec.disparar is True
    assert dec.pct == pytest.approx(0.04)
    assert dec.n_desaparecidos == 40
    # os nrs são preservados para a amostragem posterior
    assert set(dec.nrs) == set(range(1, 41))


def test_avaliar_nao_dispara_abaixo_do_limiar():
    # 20/1000 = 2% < 3%
    dec = avaliar_concelho("Porto", list(range(1, 21)), 1000)
    assert dec.disparar is False
    assert dec.pct == pytest.approx(0.02)


def test_avaliar_no_limiar_exato_nao_dispara():
    # 30/1000 = 3% == BREAKER_PCT_CONCELHO → NÃO dispara (limiar é estrito, >)
    dec = avaliar_concelho("Porto", list(range(1, 31)), 1000)
    assert dec.pct == pytest.approx(config.BREAKER_PCT_CONCELHO)
    assert dec.disparar is False


def test_avaliar_sem_desaparecidos_e_normal():
    dec = avaliar_concelho("Porto", [], 1000)
    assert dec.disparar is False
    assert dec.pct == 0.0
    assert dec.n_desaparecidos == 0


def test_avaliar_base_zero_com_desaparecidos_dispara():
    # base desconhecida/0 mas há desaparecidos → conservador: dispara desambiguação
    dec = avaliar_concelho("Porto", [1, 2, 3], 0)
    assert dec.disparar is True


def test_avaliar_aceita_contagem_inteira():
    # o wire pode passar só a contagem; então não há nrs para amostrar
    dec = avaliar_concelho("Porto", 40, 1000)
    assert dec.disparar is True
    assert dec.n_desaparecidos == 40
    assert dec.nrs == ()


# ==========================================================================
#  desambiguar — amostragem das páginas individuais (pura, obter_detalhe injetado)
# ==========================================================================
def test_desambiguar_cancelado_predominante_real():
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ESTADO_CANCELADO, nrs))
    assert isinstance(ver, Veredicto)
    assert ver.resultado == VEREDICTO_REAL
    assert ver.votos_real == 10


def test_desambiguar_suspenso_conta_como_real():
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ESTADO_SUSPENSO, nrs))
    assert ver.resultado == VEREDICTO_REAL


def test_desambiguar_nao_encontrado_predominante_api_partida():
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ESTADO_NAO_ENCONTRADO, nrs))
    assert ver.resultado == VEREDICTO_API_PARTIDA


def test_desambiguar_ativo_e_api_partida_registo_vivo():
    # 🚦 L1/L2: a página individual mostra o AL VIVO → NÃO é cancelamento → api_partida
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ESTADO_ATIVO, nrs))
    assert ver.resultado == VEREDICTO_API_PARTIDA


def test_desambiguar_erro_predominante_api_partida():
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ObterDetalheFalso.ERRO, nrs))
    assert ver.resultado == VEREDICTO_API_PARTIDA
    assert ver.votos_api_partida == 10


def test_desambiguar_mistura_inconclusiva_ambiguo():
    # 5 cancelado + 5 nao_encontrado → nenhum predomina → ambiguo
    nrs = list(range(1, 11))
    mapa = {nr: (ESTADO_CANCELADO if nr <= 5 else ESTADO_NAO_ENCONTRADO) for nr in nrs}
    ver = desambiguar("Porto", nrs, obter_detalhe=ObterDetalheFalso(mapa))
    assert ver.resultado == VEREDICTO_AMBIGUO


def test_desambiguar_indeterminado_e_ambiguo():
    nrs = list(range(1, 11))
    ver = desambiguar("Porto", nrs, obter_detalhe=_uniforme(ESTADO_INDETERMINADO, nrs))
    assert ver.resultado == VEREDICTO_AMBIGUO
    assert ver.votos_ambiguo == 10


def test_desambiguar_maioria_cancelado_com_ruido_real():
    # 8 cancelado + 2 nao_encontrado → cancelado predomina (>= PREDOMINANCIA) → real
    nrs = list(range(1, 11))
    mapa = {nr: (ESTADO_CANCELADO if nr <= 8 else ESTADO_NAO_ENCONTRADO) for nr in nrs}
    ver = desambiguar("Porto", nrs, obter_detalhe=ObterDetalheFalso(mapa))
    assert 0.8 >= PREDOMINANCIA_MINIMA  # sanidade do pressuposto do teste
    assert ver.resultado == VEREDICTO_REAL


def test_desambiguar_amostra_e_limitada_a_max():
    # 50 desaparecidos, mas amostra-se no máximo MAX_AMOSTRA páginas
    nrs = list(range(1, 51))
    fake = _uniforme(ESTADO_ATIVO, nrs)
    ver = desambiguar("Porto", nrs, obter_detalhe=fake)
    assert len(fake.chamadas) == MAX_AMOSTRA
    assert ver.n_amostra == MAX_AMOSTRA
    assert ver.resultado == VEREDICTO_API_PARTIDA


def test_desambiguar_amostra_vazia_e_ambiguo():
    fake = ObterDetalheFalso()
    ver = desambiguar("Porto", [], obter_detalhe=fake)
    assert ver.resultado == VEREDICTO_AMBIGUO
    assert fake.chamadas == []  # nada a amostrar → não toca em obter_detalhe


# ==========================================================================
#  resolver_pendentes — real → LIBERTA (envia) os alertas retidos
# ==========================================================================
def test_resolver_real_liberta_e_envia(bd):
    _cenario_pendente(100031, concelho="Porto")

    # 🚦 antes do breaker: o pendente existe mas NÃO foi enviado
    a0 = _alerta_de(100031)
    assert a0.canal == CANAL_PENDENTE and a0.enviado_em is None
    assert pendente_desambiguacao(a0) is True

    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_CANCELADO, [100031]),
        )

    assert isinstance(res, Resolucao)
    assert res.enviados == 1
    assert enviar.n == 1
    assert enviar.chamadas[0]["para"] == "cliente@ex.pt"

    a = _alerta_de(100031)
    assert a.enviado_em is not None          # foi finalmente enviado
    assert a.canal == CANAL_EMAIL
    assert pendente_desambiguacao(a) is False
    # agora que foi POSITIVAMENTE confirmado, a copy pode falar de cancelamento/suspensão
    assert "cancel" in (a.conteudo or "").lower()


def test_resolver_real_so_envia_depois_de_confirmar(bd):
    """🚦 A garantia central: nada é enviado até o breaker confirmar REAL."""
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()

    # veredicto api_partida NÃO envia
    with db.get_session() as s:
        resolver_pendentes(s, "Porto", VEREDICTO_API_PARTIDA, enviar=enviar, escalar=FakeEscalar())
    assert enviar.n == 0


def test_resolver_real_sem_email_mantem_pendente(bd):
    _cenario_pendente(100031, concelho="Porto", email="")  # cliente sem email
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_CANCELADO, [100031]),
        )

    assert enviar.n == 0
    assert res.enviados == 0
    a = _alerta_de(100031)
    assert pendente_desambiguacao(a) is True   # continua retido (dono resolve à mão)


def test_resolver_real_idempotente_nao_reenvia(bd):
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    obter = _uniforme(ESTADO_CANCELADO, [100031])
    with db.get_session() as s:
        r1 = resolver_pendentes(s, "Porto", VEREDICTO_REAL, enviar=enviar, obter_detalhe=obter)
    with db.get_session() as s:
        r2 = resolver_pendentes(s, "Porto", VEREDICTO_REAL, enviar=enviar, obter_detalhe=obter)

    assert r1.enviados == 1
    assert r2.enviados == 0
    assert enviar.n == 1   # saiu UMA só vez


# ==========================================================================
#  🚦 FIX A — confirmação POR-NR no ramo REAL (cada nr reconfirmado na sua página)
# ==========================================================================
def test_resolver_real_confirma_por_nr_so_envia_o_cancelado(bd):
    """🚦 REGRESSÃO-CHAVE: amostra deu maioria cancelado (veredicto REAL), MAS um dos
    nrs pendentes tem a página individual `ativo` (AL vivo) → esse nr NUNCA é enviado;
    só os que confirmam cancelado POR-NR saem."""
    _cenario_pendente(1, concelho="Porto", email="c1@ex.pt")   # página: cancelado → envia
    _cenario_pendente(2, concelho="Porto", email="c2@ex.pt")   # página: ativo → NÃO envia
    _cenario_pendente(3, concelho="Porto", email="c3@ex.pt")   # página: cancelado → envia

    obter = ObterDetalheFalso({1: ESTADO_CANCELADO, 2: ESTADO_ATIVO, 3: ESTADO_CANCELADO})
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL, enviar=enviar, obter_detalhe=obter, escalar=escalar
        )

    # só os cancelado-confirmados POR-NR saíram; o AL vivo (nr 2) foi IMPEDIDO
    assert {c["para"] for c in enviar.chamadas} == {"c1@ex.pt", "c3@ex.pt"}
    assert res.enviados == 2
    assert res.suprimidos == 1                 # o nr 2 (ativo) foi suprimido
    assert _alerta_de(1).enviado_em is not None
    assert _alerta_de(3).enviado_em is not None
    assert escalar.n == 1                       # FYI ao dono da divergência
    with db.get_session() as s:
        # nr 2 nunca foi enviado — foi suprimido (removido) para reavaliação
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 2).count() == 0


def test_resolver_real_nr_ativo_nao_envia_suprime_reabre(bd):
    """Ramo REAL, mas a página DESTE nr diz `ativo` → não envia; suprime + reabre evento."""
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_ATIVO, [100031]), escalar=escalar,
        )

    assert enviar.n == 0                        # 🚦 AL vivo → nada enviado
    assert res.suprimidos == 1
    assert res.eventos_reabertos == 1
    assert escalar.n == 1
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 100031).count() == 0
        assert s.get(models.EventoRegisto, ev_id).processado is False


def test_resolver_real_nr_nao_encontrado_nao_envia_retem(bd):
    """Ramo REAL, mas a página DESTE nr diz `nao_encontrado` (ausência sem prova) →
    não se confirma positivamente → NÃO envia; mantém retido."""
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_NAO_ENCONTRADO, [100031]),
            escalar=FakeEscalar(),
        )

    assert enviar.n == 0
    assert res.retidos == 1
    assert pendente_desambiguacao(_alerta_de(100031)) is True   # continua retido
    with db.get_session() as s:
        assert s.get(models.EventoRegisto, ev_id).processado is True  # não reabre (não é AL vivo)


def test_resolver_real_nr_erro_de_transporte_nao_envia(bd):
    """Ramo REAL, mas obter_detalhe DESTE nr rebenta (rede) → sem confirmação → NÃO envia."""
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ObterDetalheFalso.ERRO, [100031]),
        )
    assert enviar.n == 0
    assert res.enviados == 0
    assert pendente_desambiguacao(_alerta_de(100031)) is True


def test_resolver_real_sem_obter_detalhe_nao_envia(bd):
    """Sem meio de reconfirmar POR-NR (obter_detalhe ausente) → direção segura: NÃO envia."""
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(s, "Porto", VEREDICTO_REAL, enviar=enviar)
    assert enviar.n == 0
    assert res.enviados == 0
    assert pendente_desambiguacao(_alerta_de(100031)) is True


# ==========================================================================
#  resolver_pendentes — api_partida → SUPRIME (reabre evento p/ retry) + FYI
# ==========================================================================
def test_resolver_api_partida_suprime_reabre_e_avisa(bd):
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_pendentes(s, "Porto", VEREDICTO_API_PARTIDA, enviar=enviar, escalar=escalar)

    assert enviar.n == 0                       # 🚦 nada enviado ao cliente
    assert res.suprimidos == 1
    assert res.eventos_reabertos == 1
    assert escalar.n == 1                       # FYI ao dono

    with db.get_session() as s:
        # o pendente foi suprimido (removido) para retry limpo
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 100031).count() == 0
        # o evento foi reaberto (processado=False) para nova avaliação
        ev = s.get(models.EventoRegisto, ev_id)
        assert ev.processado is False


# ==========================================================================
#  resolver_pendentes — ambiguo → ESCALA, NÃO envia, RETÉM
# ==========================================================================
def test_resolver_ambiguo_escala_e_retem(bd):
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_pendentes(s, "Porto", VEREDICTO_AMBIGUO, enviar=enviar, escalar=escalar)

    assert enviar.n == 0                        # 🚦 nada enviado
    assert res.retidos == 1
    assert escalar.n == 1                        # escalado ao dono

    a = _alerta_de(100031)
    assert pendente_desambiguacao(a) is True     # continua retido
    with db.get_session() as s:
        ev = s.get(models.EventoRegisto, ev_id)
        assert ev.processado is True             # NÃO reabre (decisão é manual)


# ==========================================================================
#  ISOLAMENTO por concelho — o breaker de um concelho nunca afeta outro
# ==========================================================================
def test_isolamento_real_so_afeta_o_seu_concelho(bd):
    _cenario_pendente(1, concelho="Porto", email="porto@ex.pt")
    _cenario_pendente(2, concelho="Lisboa", email="lisboa@ex.pt")
    enviar = FakeEnviar()

    with db.get_session() as s:
        resolver_pendentes(
            s, "Porto", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_CANCELADO, [1]),
        )

    # só o cliente do Porto recebe; Lisboa fica intocada
    assert {c["para"] for c in enviar.chamadas} == {"porto@ex.pt"}
    a_porto = _alerta_de(1)
    a_lisboa = _alerta_de(2)
    assert a_porto.enviado_em is not None
    assert pendente_desambiguacao(a_lisboa) is True   # Lisboa segue retido


def test_isolamento_api_partida_nao_reabre_evento_de_outro(bd):
    _c1, ev_porto = _cenario_pendente(1, concelho="Porto")
    _c2, ev_lisboa = _cenario_pendente(2, concelho="Lisboa")
    with db.get_session() as s:
        resolver_pendentes(s, "Porto", VEREDICTO_API_PARTIDA, enviar=FakeEnviar(), escalar=FakeEscalar())

    with db.get_session() as s:
        assert s.get(models.EventoRegisto, ev_porto).processado is False   # Porto reaberto
        assert s.get(models.EventoRegisto, ev_lisboa).processado is True    # Lisboa intocado
        # e o pendente de Lisboa continua vivo
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 2).count() == 1


def test_concelho_comparado_normalizado(bd):
    # registo guardado como "Porto"; resolve-se com caixa/espaços diferentes
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(
            s, "  porto ", VEREDICTO_REAL,
            enviar=enviar, obter_detalhe=_uniforme(ESTADO_CANCELADO, [100031]),
        )
    assert res.enviados == 1


# ==========================================================================
#  Ponta-a-ponta (critério de "feito"): limpeza em massa segue o ramo certo
# ==========================================================================
def test_e2e_limpeza_real_dispara_amostra_e_envia(bd):
    """Porto-style: pico de desaparecidos → breaker → amostra cancelado → real → envia."""
    _cenario_pendente(100031, concelho="Porto")

    # (1) pico anómalo dispara o breaker
    dec = avaliar_concelho("Porto", [100031] + list(range(200000, 200050)), 1000)
    assert dec.disparar is True

    # (2) a amostra das páginas individuais confirma cancelamento
    obter = _uniforme(ESTADO_CANCELADO, dec.nrs)
    ver = desambiguar("Porto", dec.nrs, obter_detalhe=obter)
    assert ver.resultado == VEREDICTO_REAL

    # (3) resolve → confirma POR-NR e LIBERTA o alerta retido
    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_pendentes(s, "Porto", ver, enviar=enviar, obter_detalhe=obter)
    assert res.enviados == 1
    assert enviar.n == 1


def test_e2e_api_truncada_dispara_amostra_e_suprime(bd):
    """🚦 L2: resposta truncada → breaker → amostra AL vivo → api_partida → suprime."""
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")

    dec = avaliar_concelho("Porto", [100031] + list(range(200000, 200050)), 1000)
    assert dec.disparar is True

    ver = desambiguar("Porto", dec.nrs, obter_detalhe=_uniforme(ESTADO_ATIVO, dec.nrs))
    assert ver.resultado == VEREDICTO_API_PARTIDA

    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_pendentes(s, "Porto", ver, enviar=enviar, escalar=escalar)

    assert enviar.n == 0                 # 🚦 o falso "cancelado" foi IMPEDIDO
    assert res.suprimidos == 1
    with db.get_session() as s:
        assert s.get(models.EventoRegisto, ev_id).processado is False   # reaberto p/ retry
