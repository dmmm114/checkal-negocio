"""Testes do WIRE de orquestração — app.crons (FDS 5, SPEC-FDS5.md §wire).

O wire liga o **circuit breaker** ao fluxo pós-varrimento e envolve **cada cron**
(varrimento, DRE, dunning, suporte, backup) no dead-man switch `com_healthcheck`.
É a RESOLUÇÃO da 🚦 guarda de sequência do FDS 1/3 (`app/rnal/LIMITACOES-CONHECIDAS.md`):

    varrimento (ingest) → gerar_alertas_estado (FDS 3: pendente_desambiguacao)
                        → resolver_desaparecidos_pendentes (breaker por concelho)

Contrato verificado aqui:
  · REAL confirmado na página individual → o alerta retido é LIBERTADO (enviado);
  · 🚦 L1 (mudança de concelho c/ destino em falha) — UM falso `desaparecido` cuja
    página individual mostra o AL VIVO → SUPRIMIDO, nunca enviado (mesmo abaixo do
    limiar do breaker: a amostragem por página individual corre sempre);
  · 🚦 L2 (resposta nacional truncada) — pico de `desaparecidos` num concelho cujas
    páginas mostram os ALs vivos → SUPRIMIDO em massa + FYI ao dono, nada enviado;
  · AMBÍGUO → escalado ao dono, retido;
  · ISOLAMENTO por concelho preservado no wire;
  · cada cron pinga o Healthchecks no fim (sucesso) e no `/fail` (exceção propaga).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede/IA/IMAP/subprocess —
o cliente de varrimento, `obter_detalhe`, `enviar`, `escalar` e o cliente HTTP dos
pings são dublês injetados; BD SQLite temporária. Escritos ANTES da implementação (TDD).
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
    gerar_alertas_estado,
    pendente_desambiguacao,
)
from app.backups import BackupInativo
from app.dunning import DunningIncompleto
from app.rnal.client import ResultadoVarrimento
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_CANCELADO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
)
from app.rnal.diffing import TIPO_DESAPARECIDO

from app.crons import (
    SLUG_BACKUP,
    SLUG_DRE,
    SLUG_DUNNING,
    SLUG_SUPORTE,
    SLUG_VARRIMENTO,
    ResultadoBreaker,
    cron_backup,
    cron_dre,
    cron_dunning,
    cron_suporte,
    cron_varrimento,
    resolver_desaparecidos_pendentes,
)

UTC = timezone.utc


# ==========================================================================
#  Dublês injetados (nada toca a rede/IA/IMAP/subprocess)
# ==========================================================================
class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_crons_1") -> None:
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


class EnviarFalhaPara:
    """`enviar` que levanta SÓ para um destinatário (isola falha por concelho nos testes)."""

    def __init__(self, falhar_para: str) -> None:
        self.falhar_para = falhar_para
        self.chamadas: list[str] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        self.chamadas.append(para)
        if para == self.falhar_para:
            raise RuntimeError(f"envio falhou para {para}")
        from app.envio import ResultadoEnvio

        return ResultadoEnvio(id="re_falha_para")

    @property
    def n(self) -> int:
        return len(self.chamadas)


class ObterDetalheFalso:
    """`obter_detalhe(nr)` falso: `DetalheRegisto` com o estado mapeado, ou levanta.

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


def _uniforme(estado) -> ObterDetalheFalso:
    """`obter_detalhe` que devolve sempre `estado` para qualquer nr."""
    return ObterDetalheFalso(padrao=estado)


class _RespHTTP:
    status_code = 200

    def raise_for_status(self):
        return None


class FakeClienteHTTP:
    """Cliente HTTP falso para os pings do Healthchecks: regista as URLs pingadas."""

    def __init__(self) -> None:
        self.gets: list[str] = []

    def get(self, url, **kw):
        self.gets.append(url)
        return _RespHTTP()


class ClienteVarrimentoFalso:
    """Substitui o módulo `client`: `fetch_todos` devolve um `ResultadoVarrimento`."""

    def __init__(self, resultado: ResultadoVarrimento) -> None:
        self._resultado = resultado
        self.concelhos_pedidos: list[list[str]] = []

    def fetch_todos(self, concelhos, **kwargs) -> ResultadoVarrimento:
        self.concelhos_pedidos.append(list(concelhos))
        return self._resultado


def _resultado_scan(registos_por_concelho, *, ok=None, falhados=None) -> ResultadoVarrimento:
    """`ResultadoVarrimento` como o `client.fetch_todos` devolveria (sem rede)."""
    if ok is None:
        ok = set(registos_por_concelho)
    momento = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    return ResultadoVarrimento(
        registos_por_concelho=dict(registos_por_concelho),
        concelhos_ok=set(ok),
        concelhos_falhados=set(falhados or set()),
        raw_path="/tmp/fake.json.gz",
        iniciado_em=momento,
        concluido_em=momento,
    )


# ==========================================================================
#  Fixture: BD SQLite temporária isolada (como test_breaker / test_ingest)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_crons.db'}"
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
#  Semeadores (registo desaparecido + cliente casado + pendente FDS 3)
# --------------------------------------------------------------------------
def _semear_registo_desaparecido(nr: int, *, concelho: str, nome: str = "Casa X") -> None:
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr, nome_alojamento=nome, concelho=concelho, distrito="X",
            titular_tipo="coletiva", titular_nome="AL, Lda", nif="513029591", hash_campos="h",
            ausencias_consecutivas=2, desaparecido_em=datetime(2026, 7, 5, 3, tzinfo=UTC),
        ))


def _semear_base(concelho: str, n: int, *, base_nr: int = 900000) -> None:
    """Semeia `n` registos ATIVOS no `concelho` (para controlar o base_total do breaker)."""
    with db.get_session() as s:
        for i in range(n):
            s.add(models.Registo(
                nr_registo=base_nr + i, nome_alojamento="Base", concelho=concelho,
                distrito="X", hash_campos="h",
            ))


def _semear_cliente(nr: int, *, email: str = "cliente@ex.pt") -> int:
    with db.get_session() as s:
        c = models.Cliente(
            email=email, nome="Cliente", nif="508000000", plano="anual", estado="ativo",
            criado_em=datetime(2026, 7, 5, tzinfo=UTC),
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
            detetado_em=datetime(2026, 7, 5, 3, tzinfo=UTC), processado=False,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _mint_pendentes() -> None:
    """Como o FDS 3 em produção: transforma os eventos em alertas `pendente_desambiguacao`."""
    with db.get_session() as s:
        gerar_alertas_estado(s, enviar=FakeEnviar())


def _cenario_pendente(nr: int, *, concelho: str, email: str = "cliente@ex.pt") -> tuple[int, int]:
    _semear_registo_desaparecido(nr, concelho=concelho)
    cid = _semear_cliente(nr, email=email)
    ev_id = _semear_evento_desaparecido(nr)
    _mint_pendentes()
    return cid, ev_id


def _alerta_de(nr: int) -> models.Alerta:
    with db.get_session() as s:
        return s.query(models.Alerta).filter(models.Alerta.nr_registo == nr).one()


# ==========================================================================
#  resolver_desaparecidos_pendentes — REAL confirmado → LIBERTA
# ==========================================================================
def test_real_confirmado_liberta_o_pendente(bd):
    _cenario_pendente(100031, concelho="Porto")
    # 🚦 antes do breaker: existe mas NÃO foi enviado
    assert pendente_desambiguacao(_alerta_de(100031)) is True

    enviar = FakeEnviar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=_uniforme(ESTADO_CANCELADO), enviar=enviar, escalar=FakeEscalar()
        )

    assert isinstance(res, ResultadoBreaker)
    assert res.enviados == 1
    assert enviar.n == 1
    a = _alerta_de(100031)
    assert a.enviado_em is not None and a.canal == CANAL_EMAIL
    assert "cancel" in (a.conteudo or "").lower()


# ==========================================================================
#  🚦 L1 — UM falso desaparecido (abaixo do limiar) com a página VIVA → SUPRIME
# ==========================================================================
def test_L1_falso_unico_abaixo_do_limiar_e_suprimido(bd):
    """Mudança de concelho c/ destino em falha: 1/100 (< 3%) NÃO dispara o breaker,
    mas a amostragem por página individual corre na mesma e vê o AL VIVO → api_partida
    → SUPRIME. Nada de falso «cancelado» é enviado."""
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    _semear_base("Porto", 99)  # base_total = 100 → 1% < BREAKER_PCT_CONCELHO

    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=_uniforme(ESTADO_ATIVO), enviar=enviar, escalar=escalar
        )

    assert enviar.n == 0                     # 🚦 o falso «cancelado» foi IMPEDIDO
    assert res.suprimidos == 1
    assert escalar.n == 1                     # FYI ao dono
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 100031).count() == 0
        assert s.get(models.EventoRegisto, ev_id).processado is False  # reaberto p/ retry


# ==========================================================================
#  🚦 L2 — pico truncado num concelho, páginas vivas → SUPRIME em massa
# ==========================================================================
def test_L2_pico_truncado_suprime_em_massa(bd):
    """Resposta nacional truncada: muitos `desaparecidos` de um concelho cujas páginas
    individuais mostram os ALs vivos → api_partida → SUPRIME todos, nada enviado."""
    nrs = list(range(100001, 100013))       # 12 pendentes no mesmo concelho
    for nr in nrs:
        _cenario_pendente(nr, concelho="Porto", email=f"c{nr}@ex.pt")

    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=_uniforme(ESTADO_ATIVO), enviar=enviar, escalar=escalar
        )

    assert enviar.n == 0                     # 🚦 nada enviado
    assert res.suprimidos == 12
    assert escalar.n == 1                     # UM FYI para o concelho
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0


# ==========================================================================
#  AMBÍGUO → escala e retém
# ==========================================================================
def test_ambiguo_escala_e_retem(bd):
    _cid, ev_id = _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=_uniforme(ESTADO_INDETERMINADO), enviar=enviar, escalar=escalar
        )

    assert enviar.n == 0
    assert res.retidos == 1
    assert escalar.n == 1
    assert pendente_desambiguacao(_alerta_de(100031)) is True  # continua retido
    with db.get_session() as s:
        assert s.get(models.EventoRegisto, ev_id).processado is True  # NÃO reabre (manual)


# ==========================================================================
#  ISOLAMENTO — dois concelhos, ramos diferentes, sem contaminação
# ==========================================================================
def test_isolamento_entre_concelhos(bd):
    _cenario_pendente(1, concelho="Porto", email="porto@ex.pt")     # → REAL (cancelado)
    _cenario_pendente(2, concelho="Lisboa", email="lisboa@ex.pt")   # → api_partida (ativo)

    obter = ObterDetalheFalso({1: ESTADO_CANCELADO, 2: ESTADO_ATIVO})
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=obter, enviar=enviar, escalar=escalar
        )

    # só o Porto (cancelado confirmado) recebe; Lisboa (vivo) é suprimido
    assert {c["para"] for c in enviar.chamadas} == {"porto@ex.pt"}
    assert res.enviados == 1 and res.suprimidos == 1
    assert _alerta_de(1).enviado_em is not None
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 2).count() == 0


# ==========================================================================
#  🚦 FIX A — confirmação POR-NR no wire: maioria cancelado mas um nr vivo
# ==========================================================================
def test_real_maioria_cancelado_mas_um_nr_vivo_nao_e_enviado(bd):
    """🚦 A amostra do concelho dá maioria cancelado (veredicto REAL), mas UM dos nrs
    pendentes tem a página individual `ativo` → esse nr NUNCA é enviado; os confirmados
    cancelado saem. A guarda vive no `resolver_pendentes` (confirmação POR-NR), não só
    na maioria da amostra."""
    _cenario_pendente(1, concelho="Porto", email="c1@ex.pt")   # página: cancelado → envia
    _cenario_pendente(2, concelho="Porto", email="c2@ex.pt")   # página: ativo → NÃO envia
    _cenario_pendente(3, concelho="Porto", email="c3@ex.pt")   # página: cancelado → envia

    # amostra: 2 cancelado + 1 ativo → 2/3 ≥ predominância → veredicto REAL do concelho
    obter = ObterDetalheFalso({1: ESTADO_CANCELADO, 2: ESTADO_ATIVO, 3: ESTADO_CANCELADO})
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=obter, enviar=enviar, escalar=escalar
        )

    # só os cancelado-confirmados POR-NR saíram; o AL vivo (nr 2) foi IMPEDIDO
    assert {c["para"] for c in enviar.chamadas} == {"c1@ex.pt", "c3@ex.pt"}
    assert res.enviados == 2
    assert res.suprimidos == 1
    assert _alerta_de(1).enviado_em is not None
    assert _alerta_de(3).enviado_em is not None
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(models.Alerta.nr_registo == 2).count() == 0


# ==========================================================================
#  🚦 FIX C — isolamento transacional POR CONCELHO (savepoint por concelho)
# ==========================================================================
def test_falha_num_concelho_nao_desfaz_o_outro(bd):
    """FIX C: uma exceção ao resolver o concelho de Lisboa (envio rebenta) reverte SÓ
    Lisboa (savepoint) — o Porto, já resolvido e enviado, PERSISTE."""
    _cenario_pendente(1, concelho="Porto", email="porto@ex.pt")     # resolve OK (cancelado)
    _cenario_pendente(2, concelho="Lisboa", email="lisboa@ex.pt")   # envio levanta

    obter = _uniforme(ESTADO_CANCELADO)              # ambas as páginas dizem cancelado → REAL
    enviar = EnviarFalhaPara("lisboa@ex.pt")
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(
            s, obter_detalhe=obter, enviar=enviar, escalar=FakeEscalar()
        )

    # Porto foi LIBERTADO e persistiu apesar da falha em Lisboa
    assert res.enviados == 1
    a_porto = _alerta_de(1)
    assert a_porto.enviado_em is not None and a_porto.canal == CANAL_EMAIL
    # Lisboa foi revertido ao savepoint → continua pendente, nunca enviado
    assert pendente_desambiguacao(_alerta_de(2)) is True


def test_sem_pendentes_e_noop(bd):
    obter = ObterDetalheFalso()
    with db.get_session() as s:
        res = resolver_desaparecidos_pendentes(s, obter_detalhe=obter, enviar=FakeEnviar())
    assert res.enviados == 0 and res.suprimidos == 0 and res.retidos == 0
    assert obter.chamadas == []               # sem pendentes → não amostra nada


def test_idempotente_nao_reenvia(bd):
    _cenario_pendente(100031, concelho="Porto")
    enviar = FakeEnviar()
    with db.get_session() as s:
        r1 = resolver_desaparecidos_pendentes(s, obter_detalhe=_uniforme(ESTADO_CANCELADO), enviar=enviar)
    with db.get_session() as s:
        r2 = resolver_desaparecidos_pendentes(s, obter_detalhe=_uniforme(ESTADO_CANCELADO), enviar=enviar)
    assert r1.enviados == 1 and r2.enviados == 0
    assert enviar.n == 1                       # saiu UMA só vez


# ==========================================================================
#  cron_varrimento — encadeia ingest → alertas_estado → breaker, com healthcheck
# ==========================================================================
def test_cron_varrimento_encadeia_e_liberta_real(bd):
    # registo conhecido com 1 ausência anterior; o scan omite-o (concelho responde) → desaparecido
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=500, nome_alojamento="Casa 500", concelho="Porto", distrito="X",
            titular_tipo="coletiva", titular_nome="AL, Lda", nif="513029591", hash_campos="h",
            ausencias_consecutivas=1, desaparecido_em=None,
        ))
    _semear_cliente(500, email="dono500@ex.pt")

    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": []}))
    enviar = FakeEnviar()
    hc = FakeClienteHTTP()
    res = cron_varrimento(
        ["Porto"], cliente=cliente,
        obter_detalhe=_uniforme(ESTADO_CANCELADO), enviar=enviar, escalar=FakeEscalar(),
        cliente_hc=hc,
    )

    # o desaparecimento foi detetado, virou pendente e foi LIBERTADO após confirmação
    assert any(ev.tipo == TIPO_DESAPARECIDO for ev in res.ingest.eventos)
    assert res.breaker is not None and res.breaker.enviados == 1
    assert enviar.n == 1
    a = _alerta_de(500)
    assert a.enviado_em is not None and a.canal == CANAL_EMAIL
    # dead-man switch pingou SUCESSO da check "varrimento"
    assert any(u.endswith(f"/{SLUG_VARRIMENTO}") for u in hc.gets)


def test_cron_varrimento_L2_nao_envia_falso(bd):
    """No cron completo, um desaparecimento cuja página mostra o AL vivo NÃO é enviado."""
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=501, nome_alojamento="Casa 501", concelho="Porto", distrito="X",
            hash_campos="h", ausencias_consecutivas=1, desaparecido_em=None,
        ))
    _semear_cliente(501, email="dono501@ex.pt")

    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": []}))
    enviar = FakeEnviar()
    res = cron_varrimento(
        ["Porto"], cliente=cliente,
        obter_detalhe=_uniforme(ESTADO_ATIVO), enviar=enviar, escalar=FakeEscalar(),
        cliente_hc=FakeClienteHTTP(),
    )
    assert enviar.n == 0                       # 🚦 falso «cancelado» impedido no cron
    assert res.breaker is not None and res.breaker.suprimidos == 1


def test_cron_varrimento_modo_teste_so_ingest(bd, monkeypatch):
    """Sem seams injetados e em modo de teste: corre só o ingest (nada de rede/envio)."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True, raising=False)
    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": [], }))
    res = cron_varrimento(["Porto"], cliente=cliente, cliente_hc=FakeClienteHTTP())
    assert res.ingest is not None
    assert res.breaker is None                 # breaker não corre sem obter_detalhe/enviar


# ==========================================================================
#  Healthcheck — exceção no cron → ping /fail e a exceção PROPAGA
# ==========================================================================
def test_cron_backup_sucesso_pinga(bd):
    hc = FakeClienteHTTP()
    apagados: list = []
    res = cron_backup(
        dsn="postgresql://u:p@h:5432/db",
        destino_dir="/tmp/bk",
        agora=datetime(2026, 7, 5, 3, tzinfo=UTC),
        correr=lambda cmd: None,
        listar=lambda d: [],
        apagar=apagados.append,
        cliente_hc=hc,
    )
    assert res.executado is True
    assert any(u.endswith(f"/{SLUG_BACKUP}") for u in hc.gets)


def test_cron_backup_falha_pinga_fail_e_propaga(bd):
    hc = FakeClienteHTTP()
    with pytest.raises(BackupInativo):
        cron_backup(dsn="", cliente_hc=hc)     # live-gate → BackupInativo
    assert any(u.endswith(f"/{SLUG_BACKUP}/fail") for u in hc.gets)


# ==========================================================================
#  cron_dunning / cron_suporte / cron_dre — wrap correto + no-op seguro
# ==========================================================================
def test_cron_dunning_pinga_e_corre(bd):
    # cliente a D-30 da renovação → passo D-30
    with db.get_session() as s:
        s.add(models.Cliente(
            email="dun@ex.pt", nome="Dun", plano="anual", estado="ativo",
            criado_em=datetime(2025, 7, 20, tzinfo=UTC),
        ))
    hc = FakeClienteHTTP()
    enviar = FakeEnviar()
    passos = cron_dunning(agora=datetime(2026, 7, 5, tzinfo=UTC), enviar=enviar, cliente_hc=hc)
    assert any(p.passo == "D-30" for p in passos)
    assert enviar.n == 1
    assert any(u.endswith(f"/{SLUG_DUNNING}") for u in hc.gets)


def test_cron_dunning_falha_parcial_pinga_fail(bd):
    """🚦 FIX B: se algum cliente falha o envio, cron_dunning propaga DunningIncompleto →
    o dead-man switch pinga /fail (avisa o dono), mas os outros passos ficaram feitos."""
    for i in range(2):
        with db.get_session() as s:
            s.add(models.Cliente(
                email=f"dun{i}@ex.pt", nome="Dun", plano="anual", estado="ativo",
                criado_em=datetime(2025, 7, 20, tzinfo=UTC),
            ))
    hc = FakeClienteHTTP()
    enviar = EnviarFalhaPara("dun0@ex.pt")           # o 1.º cliente rebenta; o 2.º envia
    with pytest.raises(DunningIncompleto):
        cron_dunning(agora=datetime(2026, 7, 5, tzinfo=UTC), enviar=enviar, cliente_hc=hc)

    assert any(u.endswith(f"/{SLUG_DUNNING}/fail") for u in hc.gets)
    # o 2.º cliente foi processado na mesma (o seu alerta de dunning persistiu)
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(
            models.Alerta.origem.like("dunning:%")
        ).count() == 1


def test_cron_suporte_noop_sem_leitor_mas_pinga(bd):
    hc = FakeClienteHTTP()
    res = cron_suporte(leitor=None, cliente_ia=None, cliente_hc=hc)
    assert res.lidos == 0
    assert any(u.endswith(f"/{SLUG_SUPORTE}") for u in hc.gets)


def test_cron_dre_modo_teste_noop_mas_pinga(bd, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True, raising=False)
    hc = FakeClienteHTTP()
    res = cron_dre(cliente_hc=hc)              # sem cliente_http → live-gate, sem rede
    assert res.avisos                          # aviso de transporte indisponível
    assert any(u.endswith(f"/{SLUG_DRE}") for u in hc.gets)
