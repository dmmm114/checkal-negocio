"""Testes do cron de renovação do token OAuth2 do TOConline (SPEC-TOCONLINE §2.2).

Contrato (`app.faturacao.cron_toconline`):

    renovar_token(*, cliente_http, store) -> EstadoToken

Entrypoint de um systemd timer (~a cada 3–4 h) que mantém a cadeia OAuth viva apesar
do `refresh_token` durar só ~8 h: chama `garantir_access_token` (renova via refresh e
**roda** o refresh se o access expirou; devolve da cache se ainda válido) e o resultado
fica **persistido** no armazém DB-backed. Se a cadeia partiu (refresh expirado), propaga
`BootstrapNecessario` — o cron alarma o dono e a faturação pára até novo consentimento.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede — o `cliente_http` é
INJETADO/MOCKADO e as credenciais são falsas (monkeypatch de `config`). O armazém é
injetado (memória) ou o DB-backed sobre um SQLite temporário. Escrito ANTES da
implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.faturacao import cron_toconline as cron
from app.faturacao import toconline_oauth as oauth


# ==========================================================================
#  Duplos de teste (iguais aos do test_toconline_oauth)
# ==========================================================================
class FakeResposta:
    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClienteOAuth:
    """Cliente HTTP falso: respostas scriptadas + registo das chamadas.

    Se `respostas` esgotar e ainda for chamado, `pop(0)` levanta IndexError — a prova
    de que um caminho **não devia** tocar a rede.
    """

    def __init__(self, respostas=()):
        self._respostas = list(respostas)
        self.chamadas: list[tuple[str, dict]] = []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        return self._respostas.pop(0)


OAUTH_URL = "https://oauth.example"
CLIENT_ID = "cid-fake"
CLIENT_SECRET = "secret-fake"
T0 = datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc)


@pytest.fixture()
def credenciais(monkeypatch):
    monkeypatch.setattr(config, "TOCONLINE_OAUTH_URL", OAUTH_URL)
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "TOCONLINE_CLIENT_SECRET", CLIENT_SECRET)


def _resp_token(access="acc-novo", refresh="ref-novo", expires_in=14400):
    return FakeResposta(200, {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": expires_in,
    })


# ==========================================================================
#  Renova quando o access expirou (roda o refresh) e persiste no armazém
# ==========================================================================
def test_renovar_token_renova_e_persiste(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=1),      # expirado → renovar
            refresh_token="ref-antigo",
            refresh_expira_em=T0 + timedelta(hours=4),      # ainda válido
        )
    )
    cli = FakeClienteOAuth([_resp_token(access="acc-novo", refresh="ref-novo")])

    estado = cron.renovar_token(cliente_http=cli, store=store, agora=T0)

    # devolve o EstadoToken renovado…
    assert estado.access_token == "acc-novo"
    assert estado.refresh_token == "ref-novo"
    # …e persistiu-o no armazém (a cadeia fica viva para o próximo tick)
    lido = store.ler()
    assert lido.access_token == "acc-novo"
    assert lido.refresh_token == "ref-novo"
    # renovou via refresh_token (server-to-server), não authorization_code
    assert len(cli.chamadas) == 1
    assert cli.chamadas[0][1]["data"]["grant_type"] == "refresh_token"


# ==========================================================================
#  Access ainda válido — devolve da cache SEM tocar na rede
# ==========================================================================
def test_renovar_token_com_access_valido_nao_toca_rede(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-cache",
            access_expira_em=T0 + timedelta(hours=3),       # bem dentro da validade
            refresh_token="ref-x",
            refresh_expira_em=T0 + timedelta(hours=7),
        )
    )
    cli = FakeClienteOAuth([])  # sem respostas: qualquer POST rebentaria

    estado = cron.renovar_token(cliente_http=cli, store=store, agora=T0)

    assert estado.access_token == "acc-cache"
    assert cli.chamadas == []


# ==========================================================================
#  Refresh expirado — propaga BootstrapNecessario (o cron alarma o dono)
# ==========================================================================
def test_renovar_token_refresh_expirado_propaga_bootstrap(credenciais):
    store = oauth.ArmazemMemoria(
        oauth.EstadoToken(
            access_token="acc-velho",
            access_expira_em=T0 - timedelta(hours=2),
            refresh_token="ref-morto",
            refresh_expira_em=T0 - timedelta(hours=1),       # expirado
        )
    )
    cli = FakeClienteOAuth([])

    with pytest.raises(oauth.BootstrapNecessario):
        cron.renovar_token(cliente_http=cli, store=store, agora=T0)
    assert cli.chamadas == []  # não tentou renovar sem refresh válido


# ==========================================================================
#  Armazém por omissão = ArmazemDB (linha única toconline_tokens)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_cron.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def test_renovar_token_usa_armazem_db_por_omissao(bd, credenciais):
    # Semeia um par com access expirado + refresh válido no armazém DB.
    seed = oauth.ArmazemDB()
    seed.gravar(
        oauth.EstadoToken(
            access_token="acc-db-velho",
            access_expira_em=T0 - timedelta(hours=1),
            refresh_token="ref-db-antigo",
            refresh_expira_em=T0 + timedelta(hours=4),
        )
    )
    cli = FakeClienteOAuth([_resp_token(access="acc-db-novo", refresh="ref-db-novo")])

    # Sem `store` → usa ArmazemDB por omissão; `cliente_http` injetado (sem rede real).
    estado = cron.renovar_token(cliente_http=cli, agora=T0)

    assert estado.access_token == "acc-db-novo"
    # persistiu na linha única (id=1)
    with db.get_session() as s:
        linha = s.get(models.ToconlineToken, 1)
        assert linha is not None
        assert linha.access_token == "acc-db-novo"
        assert linha.refresh_token == "ref-db-novo"
