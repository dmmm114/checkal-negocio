"""Testes do gestor de token OAuth2 do TOConline (SPEC-TOCONLINE §2 auth).

Contrato (SPEC-TOCONLINE §2.0/§2.1):

    trocar_codigo(code, *, cliente_http, store) -> EstadoToken   # bootstrap (authorization_code)
    garantir_access_token(*, cliente_http, store) -> str          # devolve/renova o access

A auth vive FORA de `emitir_fatura_recibo`: o cliente HTTP injetado nesse fluxo
já traz o Bearer. Este módulo é o que produz/renova esse Bearer, server-to-server:
  - `trocar_codigo`: troca o `authorization_code` (consentimento humano único no
    browser) pelo 1.º par access+refresh e **grava-o** no armazém.
  - `garantir_access_token`: se o access ainda é válido devolve-o SEM tocar na
    rede; senão renova via `grant_type=refresh_token`, **roda** o refresh_token
    (o TOConline devolve um novo a cada renovação) e grava o NOVO par.

Guardas de erro claras:
  - `BootstrapNecessario` — sem refresh_token ou refresh_token expirado: a cadeia
    quebrou, é preciso novo consentimento humano no browser (não emitir silêncio).
  - `CredenciaisEmFalta` — sem OAUTH_URL/client_id/secret configurados (LIVE-GATED).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede real — o
`cliente_http` é INJETADO/MOCKADO e as credenciais são falsas (monkeypatch de
`config`). O armazém de token é injetado (impl. em-memória). Escrito ANTES da
implementação (TDD).
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.faturacao import toconline_oauth as oauth


# ==========================================================================
#  Duplos de teste
# ==========================================================================
class FakeResposta:
    """Resposta HTTP mínima à laia de `httpx.Response` (status + JSON + raise)."""

    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClienteOAuth:
    """Cliente HTTP falso: devolve respostas scriptadas e regista as chamadas.

    Se `respostas` esgotar e ainda assim for chamado, `pop(0)` levanta IndexError
    — é o modo de provar que um caminho **não devia** tocar a rede.
    """

    def __init__(self, respostas=()):
        self._respostas = list(respostas)
        self.chamadas: list[tuple[str, dict]] = []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        return self._respostas.pop(0)


# --- Constantes de teste ---------------------------------------------------
OAUTH_URL = "https://oauth.example"
CLIENT_ID = "cid-fake"
CLIENT_SECRET = "secret-fake"
CODE = "authcode-123"
T0 = datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc)


def _basic_esperado() -> str:
    cru = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(cru).decode("ascii")


@pytest.fixture()
def credenciais(monkeypatch):
    """Credenciais TOConline FALSAS em `config` (nunca tocam a rede real)."""
    monkeypatch.setattr(config, "TOCONLINE_OAUTH_URL", OAUTH_URL)
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_SECRET", CLIENT_SECRET)


def _resp_token(access="acc-1", refresh="ref-1", expires_in=14400, **extra):
    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }
    payload.update(extra)
    return FakeResposta(200, payload)


# ==========================================================================
#  Bootstrap (authorization_code) — grava o 1.º par
# ==========================================================================
def test_bootstrap_grava_tokens(credenciais):
    store = oauth.ArmazemMemoria()
    cli = FakeClienteOAuth([_resp_token(access="acc-boot", refresh="ref-boot")])

    estado = oauth.trocar_codigo(CODE, cliente_http=cli, store=store, agora=T0)

    # devolve o par…
    assert estado.access_token == "acc-boot"
    assert estado.refresh_token == "ref-boot"
    # …e persiste-o no armazém (bootstrap grava tokens)
    lido = store.ler()
    assert lido.access_token == "acc-boot"
    assert lido.refresh_token == "ref-boot"
    # validades calculadas a partir do `agora` + expires_in
    assert lido.access_expira_em == T0 + timedelta(seconds=14400)


def test_bootstrap_faz_post_authorization_code(credenciais):
    store = oauth.ArmazemMemoria()
    cli = FakeClienteOAuth([_resp_token()])

    oauth.trocar_codigo(CODE, cliente_http=cli, store=store, agora=T0)

    assert len(cli.chamadas) == 1
    url, kw = cli.chamadas[0]
    assert url == f"{OAUTH_URL}/token"
    corpo = kw["data"]
    assert corpo["grant_type"] == "authorization_code"
    assert corpo["code"] == CODE
    assert corpo["scope"] == "commercial"
    # Basic base64(client_id:secret) + form-urlencoded
    assert kw["headers"]["Authorization"] == _basic_esperado()
    assert kw["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


# ==========================================================================
#  Renovação — grant_type=refresh_token, rotação do refresh_token
# ==========================================================================
def test_refresh_renova_e_roda_o_refresh_token(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=1),      # expirado → renovar
            refresh_token="ref-antigo",
            refresh_expira_em=T0 + timedelta(hours=4),      # ainda válido
        )
    )
    cli = FakeClienteOAuth([_resp_token(access="acc-novo", refresh="ref-novo")])

    token = oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)

    assert token == "acc-novo"
    # enviou o refresh antigo…
    url, kw = cli.chamadas[0]
    assert url == f"{OAUTH_URL}/token"
    assert kw["data"]["grant_type"] == "refresh_token"
    assert kw["data"]["refresh_token"] == "ref-antigo"
    assert kw["data"]["scope"] == "commercial"
    # …e gravou o NOVO par, com o refresh rodado
    lido = store.ler()
    assert lido.access_token == "acc-novo"
    assert lido.refresh_token == "ref-novo"


def test_refresh_sem_novo_refresh_mantem_o_anterior(credenciais):
    # Se a resposta de refresh não trouxer novo refresh_token, preserva-se o atual
    # (a cadeia não pode ficar sem refresh).
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=1),
            refresh_token="ref-mantido",
            refresh_expira_em=T0 + timedelta(hours=4),
        )
    )
    cli = FakeClienteOAuth([FakeResposta(200, {"access_token": "acc-novo", "expires_in": 14400})])

    token = oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)

    assert token == "acc-novo"
    assert store.ler().refresh_token == "ref-mantido"


# ==========================================================================
#  Access ainda válido — NÃO toca a rede
# ==========================================================================
def test_access_valido_nao_chama_rede(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-cache",
            access_expira_em=T0 + timedelta(hours=3),       # bem dentro da validade
            refresh_token="ref-x",
            refresh_expira_em=T0 + timedelta(hours=7),
        )
    )
    cli = FakeClienteOAuth([])  # sem respostas: qualquer POST rebentaria

    token = oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)

    assert token == "acc-cache"
    assert cli.chamadas == []


# ==========================================================================
#  Refresh expirado / ausente — BootstrapNecessario (novo consentimento humano)
# ==========================================================================
def test_refresh_expirado_levanta_bootstrap_necessario(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=2),
            refresh_token="ref-morto",
            refresh_expira_em=T0 - timedelta(hours=1),      # expirado
        )
    )
    cli = FakeClienteOAuth([])

    with pytest.raises(oauth.BootstrapNecessario):
        oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)
    assert cli.chamadas == []  # não tentou renovar sem refresh válido


def test_sem_refresh_token_levanta_bootstrap_necessario(credenciais):
    store = oauth.ArmazemMemoria()  # armazém vazio (nunca houve consentimento)
    cli = FakeClienteOAuth([])

    with pytest.raises(oauth.BootstrapNecessario):
        oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)
    assert cli.chamadas == []


# ==========================================================================
#  Sem credenciais — erro claro (LIVE-GATED), mas só quando é preciso a rede
# ==========================================================================
def test_sem_credenciais_ao_renovar_levanta_erro_claro():
    # SEM a fixture `credenciais`: config.TOCONLINE_* estão vazios.
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=1),        # precisa renovar
            refresh_token="ref-antigo",
            refresh_expira_em=T0 + timedelta(hours=4),
        )
    )
    cli = FakeClienteOAuth([_resp_token()])
    with pytest.raises(oauth.CredenciaisEmFalta):
        oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0)


def test_access_valido_dispensa_credenciais():
    # Access em cache válido não precisa de credenciais nem de rede.
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-cache",
            access_expira_em=T0 + timedelta(hours=3),
            refresh_token="ref-x",
            refresh_expira_em=T0 + timedelta(hours=7),
        )
    )
    cli = FakeClienteOAuth([])
    assert oauth.garantir_access_token(cliente_http=cli, store=store, agora=T0) == "acc-cache"


# ==========================================================================
#  Armazém DB-backed (produção) — round-trip sobre `toconline_tokens`
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_oauth.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _utc(dt):
    """SQLite guarda DateTime(timezone=True) como naive; comparar em UTC é portável."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_armazem_db_grava_e_le(bd):
    store = oauth.ArmazemDB()
    estado = oauth.EstadoToken(
        access_token="acc-db",
        access_expira_em=T0 + timedelta(hours=4),
        refresh_token="ref-db",
        refresh_expira_em=T0 + timedelta(hours=8),
    )
    store.gravar(estado)

    lido = store.ler()
    assert lido.access_token == "acc-db"
    assert lido.refresh_token == "ref-db"
    assert _utc(lido.access_expira_em) == T0 + timedelta(hours=4)
    assert _utc(lido.refresh_expira_em) == T0 + timedelta(hours=8)

    # persistiu na linha única id=1
    with db.get_session() as s:
        linha = s.get(models.ToconlineToken, 1)
        assert linha is not None
        assert linha.access_token == "acc-db"


def test_armazem_db_vazio_le_estado_sem_refresh(bd):
    # Sem linha ainda: ler devolve estado vazio → força BootstrapNecessario a montante.
    store = oauth.ArmazemDB()
    lido = store.ler()
    assert lido.refresh_token is None
    assert lido.access_token is None


def test_armazem_db_gravar_e_regravar_atualiza_a_mesma_linha(bd):
    store = oauth.ArmazemDB()
    store.gravar(oauth.EstadoToken(access_token="v1", refresh_token="r1"))
    store.gravar(oauth.EstadoToken(access_token="v2", refresh_token="r2"))

    lido = store.ler()
    assert lido.access_token == "v2"
    assert lido.refresh_token == "r2"
    # continua a ser UMA linha (id=1)
    with db.get_session() as s:
        assert s.query(models.ToconlineToken).count() == 1
