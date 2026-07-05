"""Gestor de token OAuth2 server-to-server do TOConline (SPEC-TOCONLINE §2).

A faturação TOConline usa um `access_token` Bearer de validade **curta** (~4 h).
Para manter a assinatura *drop-in* de :func:`emitir_fatura_recibo` (que não conhece
OAuth — recebe um `cliente_http` já autenticado), a obtenção/renovação do token
vive **aqui**, fora do fluxo de emissão. Um cron externo chama
:func:`garantir_access_token` de ~3–4 h em ~3–4 h e usa o resultado para montar o
cliente HTTP autenticado que injeta na emissão.

Fluxo OAuth (SPEC §2.1) — **não há grant `client_credentials`**:
  - **Bootstrap (uma vez, com consentimento humano no browser):** o operador obtém
    um `authorization_code` e :func:`trocar_codigo` troca-o pelo 1.º par
    `access_token`+`refresh_token`, gravando-o no armazém.
  - **Renovação (automática):** :func:`garantir_access_token` devolve o access em
    cache se ainda for válido; senão renova via `grant_type=refresh_token`,
    **roda** o refresh_token (o TOConline devolve um novo a cada renovação — o
    antigo deixa de servir) e grava o NOVO par.

Se o refresh_token expirar (a doc indica ~8 h) a cadeia quebra e exige **novo
consentimento humano** — sinalizado por :class:`BootstrapNecessario` (o cron
alarma o dono; nunca se emite silenciosamente sem token).

**Armazém de token injetável** (`ler()`/`gravar()`): :class:`ArmazemMemoria` para
os testes; :class:`ArmazemDB` (linha única `toconline_tokens`) para produção.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria
nenhum cliente HTTP — o `cliente_http` é sempre **injetado** (mock nos testes;
`httpx.Client` real só em produção). As base URLs/credenciais vêm de
:mod:`app.config` (env), com placeholders vazios: sem credenciais nada toca a
rede — :func:`_exigir_credenciais` levanta :class:`CredenciaisEmFalta`.

O `cliente_http` é qualquer objeto à laia de `httpx.Client` com
``post(url, *, data=..., headers=...) -> resposta``, onde `resposta` expõe
``status_code``, ``json()`` e ``raise_for_status()``.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import app.config as config

__all__ = [
    "EstadoToken",
    "ArmazemToken",
    "ArmazemMemoria",
    "ArmazemDB",
    "ErroOAuth",
    "CredenciaisEmFalta",
    "BootstrapNecessario",
    "trocar_codigo",
    "garantir_access_token",
]

# --- Constantes do fluxo (SPEC-TOCONLINE §2.1/§2.2) -----------------------
SCOPE = "commercial"                 # único scope documentado
GRANT_CODE = "authorization_code"    # bootstrap (consentimento humano)
GRANT_REFRESH = "refresh_token"      # renovação server-to-server
ACCESS_VALIDADE_S = 14400            # 4 h — default se a resposta não trouxer `expires_in`
REFRESH_VALIDADE_S = 28800           # ~8 h — default se a resposta não trouxer validade do refresh
# Margem de segurança: renova o access um pouco ANTES de expirar, para o token
# não morrer a meio de um pedido (relógios desalinhados, latência do cron).
MARGEM_RENOVACAO_S = 300             # 5 min


# ==========================================================================
#  Exceções (erros claros; o cron distingue "renovar" de "pedir consentimento")
# ==========================================================================
class ErroOAuth(Exception):
    """Falha na gestão do token OAuth2 do TOConline."""


class CredenciaisEmFalta(ErroOAuth):
    """LIVE-GATED: faltam `TOCONLINE_OAUTH_URL`/`CLIENT_ID`/`CLIENT_SECRET`.

    Sem credenciais não se fala com o servidor OAuth — nada toca a rede.
    """


class BootstrapNecessario(ErroOAuth):
    """Sem refresh_token (nunca houve consentimento) ou refresh_token expirado.

    A cadeia de renovação automática quebrou: é preciso **novo consentimento
    humano no browser** (fluxo `authorization_code`). O cron deve alarmar o dono
    e a faturação automática pára até isso — nunca emitir sem token válido.
    """


# ==========================================================================
#  Estado do token (o par + validades)
# ==========================================================================
@dataclass(frozen=True)
class EstadoToken:
    """Par OAuth2 e respetivas validades. Campos `None` = ainda não obtido."""

    access_token: str | None = None
    access_expira_em: datetime | None = None
    refresh_token: str | None = None
    refresh_expira_em: datetime | None = None


# ==========================================================================
#  Armazém de token (INJETÁVEL): Protocolo + impl. memória (testes) e DB (prod)
# ==========================================================================
class ArmazemToken(Protocol):
    """Persistência do :class:`EstadoToken`. Injetado (não instanciado aqui)."""

    def ler(self) -> EstadoToken: ...

    def gravar(self, estado: EstadoToken) -> None: ...


class ArmazemMemoria:
    """Armazém em-memória (testes / arranque). Sem I/O — vive no processo."""

    def __init__(self, estado: EstadoToken | None = None):
        self._estado = estado or EstadoToken()

    def ler(self) -> EstadoToken:
        return self._estado

    def gravar(self, estado: EstadoToken) -> None:
        self._estado = estado


class ArmazemDB:
    """Armazém DB-backed (produção): a **linha única** `toconline_tokens` (id=1).

    Importa :mod:`app.db`/:mod:`app.models` de forma preguiçosa para não forçar a
    inicialização do motor SQLAlchemy em quem só use o armazém em-memória.
    """

    LINHA_ID = 1

    def ler(self) -> EstadoToken:
        import app.db as db
        import app.models as models

        with db.get_session() as s:
            linha = s.get(models.ToconlineToken, self.LINHA_ID)
            if linha is None:
                return EstadoToken()
            return EstadoToken(
                access_token=linha.access_token,
                access_expira_em=linha.access_expira_em,
                refresh_token=linha.refresh_token,
                refresh_expira_em=linha.refresh_expira_em,
            )

    def gravar(self, estado: EstadoToken) -> None:
        import app.db as db
        import app.models as models

        with db.get_session() as s:
            linha = s.get(models.ToconlineToken, self.LINHA_ID)
            if linha is None:
                linha = models.ToconlineToken(id=self.LINHA_ID)
                s.add(linha)
            linha.access_token = estado.access_token
            linha.access_expira_em = estado.access_expira_em
            linha.refresh_token = estado.refresh_token
            linha.refresh_expira_em = estado.refresh_expira_em
            linha.atualizado_em = _agora()


# ==========================================================================
#  Helpers internos
# ==========================================================================
def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _para_utc(dt: datetime) -> datetime:
    """Naive → aware UTC (o SQLite descarta o fuso ao guardar `DateTime`)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _valido(expira_em: datetime | None, agora: datetime, margem_s: int = 0) -> bool:
    """`True` se `expira_em` existe e ainda falta > `margem_s` para expirar."""
    if expira_em is None:
        return False
    return _para_utc(expira_em) > agora + timedelta(seconds=margem_s)


def _exigir_credenciais() -> None:
    """Recusa falar com o OAuth sem credenciais configuradas (LIVE-GATED)."""
    faltam = [
        nome
        for nome, valor in (
            ("TOCONLINE_OAUTH_URL", config.TOCONLINE_OAUTH_URL),
            ("TOCONLINE_CLIENT_ID", config.TOCONLINE_CLIENT_ID),
            ("TOCONLINE_CLIENT_SECRET", config.TOCONLINE_CLIENT_SECRET),
        )
        if not valor
    ]
    if faltam:
        raise CredenciaisEmFalta(
            "Credenciais TOConline em falta: "
            + ", ".join(faltam)
            + ". Provisiona-as em 'Empresa > Dados API' (SPEC-TOCONLINE §2.3)."
        )


def _url_token() -> str:
    return config.TOCONLINE_OAUTH_URL.rstrip("/") + "/token"


def _cabecalho_basic() -> str:
    cru = f"{config.TOCONLINE_CLIENT_ID}:{config.TOCONLINE_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(cru).decode("ascii")


def _headers_token() -> dict[str, str]:
    return {
        "Authorization": _cabecalho_basic(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }


def _estado_de_payload(
    payload: Any, agora: datetime, *, refresh_anterior: str | None = None
) -> EstadoToken:
    """Constrói o :class:`EstadoToken` da resposta `/token`.

    O `refresh_token` da resposta **roda** o anterior; se a resposta não o trouxer
    (renovações que não rodam), preserva-se `refresh_anterior` — a cadeia nunca
    pode ficar sem refresh. As validades derivam de `expires_in` (default 4 h) e,
    para o refresh, de `refresh_token_expires_in`/`refresh_expires_in` (default ~8 h).
    """
    dados = payload if isinstance(payload, Mapping) else {}
    access = dados.get("access_token")
    refresh = dados.get("refresh_token") or refresh_anterior

    access_s = int(dados.get("expires_in") or ACCESS_VALIDADE_S)
    refresh_s = int(
        dados.get("refresh_token_expires_in")
        or dados.get("refresh_expires_in")
        or REFRESH_VALIDADE_S
    )
    return EstadoToken(
        access_token=access,
        access_expira_em=agora + timedelta(seconds=access_s),
        refresh_token=refresh,
        refresh_expira_em=agora + timedelta(seconds=refresh_s),
    )


def _pedir_token(
    cliente_http: Any,
    dados: Mapping[str, str],
    *,
    agora: datetime,
    refresh_anterior: str | None = None,
) -> EstadoToken:
    """POST `<OAUTH_URL>/token` (form-urlencoded, Basic auth) → :class:`EstadoToken`."""
    _exigir_credenciais()
    resposta = cliente_http.post(
        _url_token(),
        data=dict(dados),
        headers=_headers_token(),
    )
    resposta.raise_for_status()
    estado = _estado_de_payload(resposta.json(), agora, refresh_anterior=refresh_anterior)
    if not estado.access_token:
        raise ErroOAuth("Resposta do /token sem `access_token`.")
    return estado


# ==========================================================================
#  API pública
# ==========================================================================
def trocar_codigo(
    code: str,
    *,
    cliente_http: Any,
    store: ArmazemToken,
    agora: datetime | None = None,
) -> EstadoToken:
    """Bootstrap: troca um `authorization_code` pelo 1.º par e **grava-o**.

    Chamado uma vez, no arranque, logo a seguir ao consentimento humano no browser
    (SPEC §2.1 passo 1→2). Persiste o par no `store` e devolve o :class:`EstadoToken`.

    Levanta
    -------
    CredenciaisEmFalta
        Sem `TOCONLINE_OAUTH_URL`/`CLIENT_ID`/`CLIENT_SECRET` (LIVE-GATED).
    ErroOAuth
        Resposta do `/token` sem `access_token`.
    """
    agora = agora or _agora()
    estado = _pedir_token(
        cliente_http,
        {"grant_type": GRANT_CODE, "code": code, "scope": SCOPE},
        agora=agora,
    )
    store.gravar(estado)
    return estado


def garantir_access_token(
    *,
    cliente_http: Any,
    store: ArmazemToken,
    agora: datetime | None = None,
) -> str:
    """Devolve um `access_token` válido, renovando-o se preciso.

    - Se o access em cache ainda é válido (com margem), devolve-o **sem tocar na
      rede**.
    - Senão renova via `grant_type=refresh_token`, **roda** o refresh_token e grava
      o NOVO par no `store`.

    Levanta
    -------
    BootstrapNecessario
        Sem refresh_token ou refresh_token expirado → é preciso novo consentimento
        humano no browser (o cron alarma o dono).
    CredenciaisEmFalta
        Sem credenciais configuradas quando é preciso renovar (LIVE-GATED).
    """
    agora = agora or _agora()
    estado = store.ler()

    # [1] access ainda válido → devolve da cache (não toca a rede, dispensa credenciais)
    if estado.access_token and _valido(estado.access_expira_em, agora, MARGEM_RENOVACAO_S):
        return estado.access_token

    # [2] renovar exige um refresh_token ainda válido
    if not estado.refresh_token or not _valido(estado.refresh_expira_em, agora):
        raise BootstrapNecessario(
            "Sem refresh_token válido (ausente ou expirado) — é preciso novo "
            "consentimento humano no browser (fluxo authorization_code)."
        )

    # [3] renova, roda o refresh e grava o novo par
    novo = _pedir_token(
        cliente_http,
        {"grant_type": GRANT_REFRESH, "refresh_token": estado.refresh_token, "scope": SCOPE},
        agora=agora,
        refresh_anterior=estado.refresh_token,
    )
    store.gravar(novo)
    return novo.access_token  # type: ignore[return-value]  # garantido por _pedir_token
