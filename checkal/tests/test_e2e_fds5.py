"""Teste de INTEGRAÇÃO ponta-a-ponta do FDS 5 (SPEC-FDS5 §INTEGRAÇÃO · AUTOMACAO §5/§6).

Prova a **camada de fiabilidade** do FDS 5 ligada de ponta a ponta pelo WIRE
(`app.crons`), da limpeza em massa de um concelho até à decisão de enviar/suprimir/
escalar — e a régua de dunning de um cartão falhado até ao cancelamento:

    varrimento (ingest, FDS 1)  →  gerar_alertas_estado (FDS 3: pendente_desambiguacao)
                                →  resolver_desaparecidos_pendentes (breaker por concelho)
                                     avaliar_concelho → desambiguar → resolver_pendentes

Simula uma **limpeza em massa** num concelho de teste (Porto) e verifica os três
ramos da 🚦 guarda de sequência, mais o isolamento e o dunning:

  1. REAL          — as páginas individuais amostradas confirmam `cancelado` → os
                     alertas `desaparecido` RETIDOS são LIBERTADOS e enviados (mock);
                     um concelho VIZINHO (Lisboa), cujo AL continua vivo no varrimento,
                     NÃO é afetado (nenhum falso «cancelado» sai);
  2. API PARTIDA   — as páginas devolvem `nao_encontrado`/erro (resposta nacional
                     truncada ou concelho em falha) → os pendentes são SUPRIMIDOS (nada
                     enviado) e o evento de origem reabre para retry (`processado=False`);
  3. AMBÍGUO       — as páginas ficam `indeterminado` → ESCALA ao dono, nada é enviado,
                     os pendentes ficam RETIDOS;
  4. DUNNING       — um cartão falhado percorre a régua D-30 → D-7 → D+3 → D+7 → D+21,
                     terminando em `estado=cancelado` (relógio injetado).

Cada cron pinga o dead-man switch (Healthchecks.io) no fim — observado por um cliente
HTTP falso, sem tocar a rede.

DISCIPLINA (inviolável, SPEC-FDS5 §disciplina): **MODO DE TESTE, LIVE-GATED.** Zero
rede/IA/IMAP/subprocess real — `obter_detalhe`, `enviar`, `escalar`, o cliente de
varrimento, o cliente HTTP dos pings e o relógio são dublês injetados; BD SQLite
temporária. 🚦 O alerta `desaparecido` só sai DEPOIS de o breaker confirmar
cancelamento REAL — nunca antes. Nada de cold.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.alertas_estado import CANAL_EMAIL, CANAL_PENDENTE, pendente_desambiguacao
from app.crons import (
    SLUG_DUNNING,
    SLUG_VARRIMENTO,
    ResultadoBreaker,
    cron_dunning,
    cron_varrimento,
)
from app.dunning import (
    PASSO_D3,
    PASSO_D7,
    PASSO_D7_POS,
    PASSO_D21,
    PASSO_D30,
)
from app.rnal import hashing
from app.rnal.client import ResultadoVarrimento
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_CANCELADO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
)
from app.rnal.diffing import TIPO_DESAPARECIDO
from app.rnal.schema import parse_registo

UTC = timezone.utc
MOMENTO = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


# ==========================================================================
#  Dublês injetados (nada toca a rede/IA/IMAP/subprocess)
# ==========================================================================
class FakeEnviar:
    """`enviar(*, para, assunto, html, anexos, **kw)` falso: regista e devolve um id."""

    def __init__(self, email_id: str = "re_e2e_fds5") -> None:
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

    @property
    def destinatarios(self) -> set[str]:
        return {c["para"] for c in self.chamadas}


class FakeEscalar:
    """`escalar(mensagem)` falso: guarda as mensagens de escalação/FYI ao dono."""

    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def __call__(self, mensagem: str) -> None:
        self.mensagens.append(mensagem)

    @property
    def n(self) -> int:
        return len(self.mensagens)


class ObterDetalheFalso:
    """`obter_detalhe(nr)` falso: `DetalheRegisto` com o estado mapeado, ou levanta.

    `mapa`: nr -> estado (str) ou a sentinela `ERRO` (simula falha de transporte —
    o breaker conta-a como voto `api_partida`). `padrao`: estado dos nrs fora do mapa.
    Regista `chamadas` (nada toca a rede).
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
    return ResultadoVarrimento(
        registos_por_concelho=dict(registos_por_concelho),
        concelhos_ok=set(ok),
        concelhos_falhados=set(falhados or set()),
        raw_path="/tmp/fake.json.gz",
        iniciado_em=MOMENTO,
        concluido_em=MOMENTO,
    )


def _raw(nr: int, *, concelho: str, nome: str = "Casa", email: str = "t@ex.pt") -> dict:
    """Registo bruto no formato da API RNAL (`RNAL_Registo` aninhado)."""
    return {
        "RNAL_Registo": {
            "NrRegisto": f"{nr}/AL",
            "Concelho": concelho,
            "NomeAlojamento": nome,
            "Modalidade": "Apartamento",
            "NrCamas": 4,
            "NrUtentes": 8,
            "Endereco": "Rua X 1",
            "CodPostal": "1000-001",
            "Freguesia": "Sé",
            "Distrito": concelho,
            "TitulardaExploracao": {
                "Tipo": "Pessoa coletiva",
                "Nome": "AL, Lda",
                "Contribuinte": "513029591",
                "Email": email,
            },
        }
    }


# ==========================================================================
#  Fixture: BD SQLite temporária isolada (como test_crons / test_dunning)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_fds5.db'}"
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
#  Semeadores — o estado ANTES do varrimento da limpeza em massa
# --------------------------------------------------------------------------
def _semear_registo_pronto_a_desaparecer(nr: int, *, concelho: str) -> None:
    """Registo conhecido com 1 ausência anterior (`ausencias_consecutivas=1`).

    À próxima ausência num concelho que responde, a regra dos 2 varrimentos marca-o
    `desaparecido` — é o gatilho da limpeza em massa deste concelho.
    """
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr, nome_alojamento=f"Casa {nr}", concelho=concelho, distrito=concelho,
            titular_tipo="coletiva", titular_nome="AL, Lda", nif="513029591", hash_campos="h",
            ausencias_consecutivas=1, desaparecido_em=None,
        ))


def _semear_registo_presente(raw: dict, *, ausencias: int = 0) -> int:
    """Regista uma linha VIVA cujo `hash_campos` casa EXATAMENTE com o `raw` do scan.

    Como o `hash_campos` guardado é o mesmo que o varrimento recomputa para o `raw`
    idêntico, o diffing não gera evento algum (registo presente e inalterado) — é o
    vizinho que continua vivo. Devolve o `nr_registo`.
    """
    reg = parse_registo(raw)
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=reg.nr_registo, nome_alojamento=reg.nome_alojamento,
            modalidade=reg.modalidade, concelho=reg.concelho, distrito=reg.distrito,
            titular_tipo=reg.titular_tipo, titular_nome=reg.titular_nome, nif=reg.nif,
            email=reg.email, hash_campos=hashing.hash_campos(reg),
            ausencias_consecutivas=ausencias, desaparecido_em=None,
        ))
    return reg.nr_registo


def _semear_cliente_do_registo(nr: int, *, email: str) -> int:
    """Cliente ativo casado ao registo `nr` (via `clientes_registos`)."""
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


def _preparar_limpeza_porto(nrs: list[int]) -> dict[int, str]:
    """Semeia `nrs` registos no Porto prontos a desaparecer, cada um com um cliente.

    Devolve o mapa `nr -> email` (para verificar quem recebe/não recebe).
    """
    emails: dict[int, str] = {}
    for nr in nrs:
        _semear_registo_pronto_a_desaparecer(nr, concelho="Porto")
        emails[nr] = f"dono{nr}@ex.pt"
        _semear_cliente_do_registo(nr, email=emails[nr])
    return emails


def _alertas_do_registo(nr: int) -> list[models.Alerta]:
    with db.get_session() as s:
        return s.query(models.Alerta).filter(models.Alerta.nr_registo == nr).all()


def _eventos_desaparecido(nr: int) -> list[models.EventoRegisto]:
    with db.get_session() as s:
        return (
            s.query(models.EventoRegisto)
            .filter(models.EventoRegisto.nr_registo == nr,
                    models.EventoRegisto.tipo == TIPO_DESAPARECIDO)
            .all()
        )


# ==========================================================================
#  INTEGRAÇÃO 1 — REAL: limpeza confirmada LIBERTA; vizinho vivo NÃO é afetado
# ==========================================================================
def test_e2e_limpeza_real_liberta_e_vizinho_nao_afetado(bd):
    """Porto sofre uma limpeza em massa (5 ALs desaparecem, o concelho responde). As
    páginas individuais confirmam `cancelado` → os 5 alertas retidos são LIBERTADOS e
    enviados. Lisboa (vizinho) continua vivo no scan → nenhum falso «cancelado» sai."""
    porto_nrs = [100001, 100002, 100003, 100004, 100005]
    emails_porto = _preparar_limpeza_porto(porto_nrs)

    # Vizinho: um AL vivo em Lisboa (presente e inalterado no scan) + o seu cliente.
    raw_lisboa = _raw(200001, concelho="Lisboa", nome="Casa Lisboa", email="lx@ex.pt")
    _semear_registo_presente(raw_lisboa)
    _semear_cliente_do_registo(200001, email="vizinho@ex.pt")

    # Scan: Porto responde mas SEM os seus registos (limpeza); Lisboa responde com o AL vivo.
    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": [], "Lisboa": [raw_lisboa]}))
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    hc = FakeClienteHTTP()

    res = cron_varrimento(
        ["Porto", "Lisboa"], cliente=cliente,
        obter_detalhe=_uniforme(ESTADO_CANCELADO), enviar=enviar, escalar=escalar,
        cliente_hc=hc,
    )

    # --- o varrimento detetou 5 desaparecimentos (só no Porto) ---
    desap = res.ingest.por_tipo(TIPO_DESAPARECIDO)
    assert {ev.nr_registo for ev in desap} == set(porto_nrs)

    # --- o breaker disparou (limpeza cruza o limiar) e LIBERTOU os 5 ---
    assert isinstance(res.breaker, ResultadoBreaker)
    assert res.breaker.disparados >= 1
    assert res.breaker.enviados == 5
    assert res.breaker.suprimidos == 0 and res.breaker.retidos == 0

    # --- exatamente 5 emails, um por dono do Porto; o vizinho NÃO recebeu ---
    assert enviar.n == 5
    assert enviar.destinatarios == set(emails_porto.values())
    assert "vizinho@ex.pt" not in enviar.destinatarios
    assert escalar.n == 0  # ramo real não escala

    # --- cada alerta do Porto saiu da fila de pendentes (enviado, canal email, afirma cancelamento) ---
    for nr in porto_nrs:
        alertas = _alertas_do_registo(nr)
        assert len(alertas) == 1
        a = alertas[0]
        assert a.enviado_em is not None and a.canal == CANAL_EMAIL
        assert pendente_desambiguacao(a) is False
        assert "cancel" in (a.conteudo or "").lower()

    # --- 🎯 ISOLAMENTO: o vizinho de Lisboa continua vivo e intocado ---
    assert _alertas_do_registo(200001) == []            # nenhum alerta gerado
    with db.get_session() as s:
        lx = s.get(models.Registo, 200001)
        assert lx.desaparecido_em is None                # não marcado desaparecido
        assert lx.ausencias_consecutivas == 0            # presente → contador reposto
        assert _eventos_desaparecido(200001) == []       # nem sequer um evento

    # --- dead-man switch: pingou SUCESSO da check "varrimento" (nunca /fail) ---
    assert any(u.endswith(f"/{SLUG_VARRIMENTO}") for u in hc.gets)
    assert not any(u.endswith(f"/{SLUG_VARRIMENTO}/fail") for u in hc.gets)


# ==========================================================================
#  INTEGRAÇÃO 2 — API PARTIDA: páginas nao_encontrado/erro → SUPRIME + retry
# ==========================================================================
def test_e2e_api_partida_suprime_e_reabre_para_retry(bd):
    """Resposta nacional truncada: um pico de `desaparecidos` no Porto cujas páginas
    individuais devolvem `nao_encontrado` (e uma REBENTA por erro de transporte) →
    veredicto `api_partida` → SUPRIME todos, NADA é enviado e cada evento de origem
    reabre para retry (`processado=False`) + UM FYI ao dono."""
    porto_nrs = [100001, 100002, 100003, 100004]
    _preparar_limpeza_porto(porto_nrs)

    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": []}))
    enviar = FakeEnviar()
    escalar = FakeEscalar()
    # 3 páginas 'nao_encontrado' + 1 que rebenta (erro de transporte → voto api_partida)
    obter = ObterDetalheFalso({100004: ObterDetalheFalso.ERRO}, padrao=ESTADO_NAO_ENCONTRADO)

    res = cron_varrimento(
        ["Porto"], cliente=cliente,
        obter_detalhe=obter, enviar=enviar, escalar=escalar, cliente_hc=FakeClienteHTTP(),
    )

    # 🚦 nada de falso «cancelado»: 0 envios, 4 suprimidos, 1 FYI ao dono
    assert enviar.n == 0
    assert res.breaker is not None
    assert res.breaker.enviados == 0
    assert res.breaker.suprimidos == 4
    assert escalar.n == 1
    assert "api partida" in escalar.mensagens[0].lower()

    # cada pendente foi removido e o evento de origem reaberto para retry
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
    for nr in porto_nrs:
        eventos = _eventos_desaparecido(nr)
        assert len(eventos) == 1
        assert eventos[0].processado is False           # reaberto p/ o próximo varrimento


# ==========================================================================
#  INTEGRAÇÃO 3 — AMBÍGUO: páginas indeterminado → ESCALA, retém, não envia
# ==========================================================================
def test_e2e_ambiguo_escala_e_retem(bd):
    """As páginas ficam `indeterminado` (amostra inconclusiva) → veredicto `ambiguo` →
    ESCALA ao dono para decisão manual, NADA é enviado e os pendentes ficam RETIDOS."""
    porto_nrs = [100001, 100002, 100003]
    _preparar_limpeza_porto(porto_nrs)

    cliente = ClienteVarrimentoFalso(_resultado_scan({"Porto": []}))
    enviar = FakeEnviar()
    escalar = FakeEscalar()

    res = cron_varrimento(
        ["Porto"], cliente=cliente,
        obter_detalhe=_uniforme(ESTADO_INDETERMINADO), enviar=enviar, escalar=escalar,
        cliente_hc=FakeClienteHTTP(),
    )

    assert enviar.n == 0
    assert res.breaker is not None
    assert res.breaker.enviados == 0 and res.breaker.suprimidos == 0
    assert res.breaker.retidos == 3
    assert escalar.n == 1
    assert "ambíguo" in escalar.mensagens[0].lower()

    # os pendentes continuam retidos (à espera de decisão manual) e os eventos NÃO reabrem
    for nr in porto_nrs:
        alertas = _alertas_do_registo(nr)
        assert len(alertas) == 1
        assert pendente_desambiguacao(alertas[0]) is True
        assert alertas[0].canal == CANAL_PENDENTE and alertas[0].enviado_em is None
        assert _eventos_desaparecido(nr)[0].processado is True  # NÃO reabre (manual)


# ==========================================================================
#  INTEGRAÇÃO 4 — DUNNING: cartão falhado percorre D-30…D+21 → cancelado
# ==========================================================================
def _agora(d: date, *, hora: int = 9) -> datetime:
    return datetime(d.year, d.month, d.day, hora, 0, tzinfo=UTC)


def _estado_cliente(cid: int) -> str:
    with db.get_session() as s:
        return s.get(models.Cliente, cid).estado


def test_e2e_dunning_cartao_falhado_percorre_ate_cancelado(bd):
    """Assinante anual cujo cartão falha na renovação: o cron diário de dunning percorre
    D-30 → D-7 → D+3 → D+7 → D+21, terminando `cancelado`, com o relógio injetado. A
    transição para `em_dunning` (D0) é do webhook `invoice.payment_failed` — simulada."""
    # Criado a 2026-07-05 (plano anual) → renova a 2027-07-05.
    with db.get_session() as s:
        c = models.Cliente(
            email="dun@ex.pt", nome="Dun", nif="508000000", plano="anual", estado="ativo",
            criado_em=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
        )
        s.add(c)
        s.flush()
        cid = c.id

    renova = date(2027, 7, 5)
    enviar = FakeEnviar()
    hc = FakeClienteHTTP()

    def _run(offset_dias: int):
        agora = _agora(renova + timedelta(days=offset_dias))
        return cron_dunning(agora=agora, enviar=enviar, cliente_hc=hc)

    # D-30 e D-7 — avisos de renovação, cliente ainda ativo
    assert [p.passo for p in _run(-30)] == [PASSO_D30]
    assert [p.passo for p in _run(-7)] == [PASSO_D7]
    assert _estado_cliente(cid) == "ativo"

    # D0 — a Stripe cobra e FALHA; o nosso cron nada faz. O webhook assenta em_dunning.
    assert _run(0) == []
    with db.get_session() as s:
        s.get(models.Cliente, cid).estado = "em_dunning"

    # D+3 e D+7 — emails de falha (só porque está em_dunning)
    assert [p.passo for p in _run(3)] == [PASSO_D3]
    assert [p.passo for p in _run(7)] == [PASSO_D7_POS]
    assert _estado_cliente(cid) == "em_dunning"

    # D+21 — downgrade para cancelado + email final
    passos = _run(21)
    assert len(passos) == 1 and passos[0].passo == PASSO_D21 and passos[0].cancelou is True
    assert _estado_cliente(cid) == "cancelado"

    # percorreu tudo: 5 emails (D-30, D-7, D+3, D+7, D+21); idempotente ao reprocessar D+21
    assert enviar.n == 5
    assert _run(21) == []
    assert enviar.n == 5

    # cada corrida do cron pingou o dead-man switch "dunning" (nunca /fail)
    assert any(u.endswith(f"/{SLUG_DUNNING}") for u in hc.gets)
    assert not any(u.endswith(f"/{SLUG_DUNNING}/fail") for u in hc.gets)
