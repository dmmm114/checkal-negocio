"""Testes da autenticação do painel admin — app.web.admin.auth (SPEC-FASE1-DASHBOARD §auth).

O painel é do DONO e só do dono. A fundação de segurança de toda a FASE 1 · WF3:

  GET  /admin/login   → formulário (pede a palavra-passe);
  POST /admin/login   → password == config.ADMIN_PASSWORD ⇒ cria uma sessão num
                        COOKIE ASSINADO (itsdangerous + config.SECRET_KEY) e
                        redireciona para /admin; password errada ⇒ recusa (401),
                        sem cookie de sessão;
  GET  /admin/logout  → limpa o cookie e volta ao login;
  requer_admin        → dependência FastAPI que guarda TODAS as rotas /admin/*:
                        sem sessão válida ⇒ redireciona (303) para /admin/login.

Contrato verificado (o que o SPEC exige, "Testa: …"):
  * sem sessão → bloqueado (não serve a rota protegida; manda para o login);
  * password certa → entra (cookie assinado; dá acesso à rota protegida);
  * password errada → recusa (401; nenhum cookie de sessão);
  * logout → limpa (o acesso volta a ser bloqueado);
  * o cookie é ASSINADO (não expõe a password; um cookie forjado é rejeitado);
  * Secure relaxado sob pytest (config.cookie_secure() ⇒ False), HttpOnly ligado.

LIVE-GATED: a autenticação não toca a rede nem a BD — só assina/valida o cookie e
renderiza o login pelo Jinja PARTILHADO (autoescape ⇒ anti-XSS). Sem DB fixture: a
auth é pura. A password de teste injeta-se por monkeypatch de `config.ADMIN_PASSWORD`
(lido em cada chamada), pois o default sob pytest é vazio (recusa tudo). Escrito ANTES
da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.config as config
from app.web.admin import auth

_PASSWORD = "segredo-do-dono-42"
_ROTA_PROTEGIDA = "/admin/painel-de-teste"


@pytest.fixture()
def password(monkeypatch):
    """Injeta a palavra-passe do dono (lida em cada verificação; default vazio recusa tudo)."""
    monkeypatch.setattr(config, "ADMIN_PASSWORD", _PASSWORD)
    return _PASSWORD


@pytest.fixture()
def client(password):
    """App de teste: o router de auth + uma rota protegida por `requer_admin`.

    A rota protegida existe só no teste (a `/admin` real é de outro agente): serve
    para exercitar a dependência `requer_admin` de forma isolada.
    """
    app = FastAPI()
    app.include_router(auth.router)

    @app.get(_ROTA_PROTEGIDA)
    def _protegida(_=Depends(auth.requer_admin)):
        return {"ok": True}

    # follow_redirects=False: queremos ASSERTAR o 303→login, não segui-lo cegamente.
    return TestClient(app, follow_redirects=False)


def _fazer_login(client: TestClient, pw: str = _PASSWORD):
    """POST /admin/login com a password dada; devolve a resposta (não seguida)."""
    return client.post("/admin/login", data={"password": pw})


# ==========================================================================
#  GET /admin/login — formulário
# ==========================================================================
def test_get_login_mostra_formulario(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    assert "<form" in corpo
    assert 'method="post"' in corpo.lower()
    assert 'name="password"' in corpo
    assert 'type="password"' in corpo
    assert "submit" in corpo.lower()
    # chrome da marca (estende base.html)
    assert "CheckAL" in corpo
    assert "/static/brand.css" in corpo


# ==========================================================================
#  Sem sessão → bloqueado (redireciona para o login)
# ==========================================================================
def test_sem_sessao_bloqueia_rota_protegida(client):
    r = client.get(_ROTA_PROTEGIDA)
    # NÃO serve a rota; manda para o login
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # o corpo NUNCA é o payload da rota protegida
    assert '"ok":true' not in r.text.replace(" ", "").lower()


def test_sem_sessao_nao_da_200(client):
    r = client.get(_ROTA_PROTEGIDA)
    assert r.status_code != 200


# ==========================================================================
#  Password certa → entra (cookie assinado dá acesso)
# ==========================================================================
def test_password_certa_cria_sessao_e_redireciona(client):
    r = _fazer_login(client)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"
    set_cookie = r.headers.get("set-cookie", "")
    assert auth.COOKIE_NOME in set_cookie


def test_sessao_da_acesso_a_rota_protegida(client):
    _fazer_login(client)  # o cookie fica no jar do TestClient
    r = client.get(_ROTA_PROTEGIDA)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ==========================================================================
#  Password errada → recusa (401, sem cookie de sessão)
# ==========================================================================
def test_password_errada_recusa(client):
    r = _fazer_login(client, pw="nao-e-a-password")
    assert r.status_code == 401
    # NENHUM cookie de sessão emitido
    assert auth.COOKIE_NOME not in r.headers.get("set-cookie", "")
    # e continua sem acesso
    assert client.get(_ROTA_PROTEGIDA).status_code == 303


def test_password_vazia_recusa(client):
    r = _fazer_login(client, pw="")
    assert r.status_code == 401
    assert client.get(_ROTA_PROTEGIDA).status_code == 303


def test_sem_password_configurada_recusa_tudo(monkeypatch):
    """Fail-closed: sem ADMIN_PASSWORD (default sob pytest) nenhuma password entra."""
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    app = FastAPI()
    app.include_router(auth.router)
    c = TestClient(app, follow_redirects=False)
    # mesmo a password "certa" (que seria vazia) não abre sessão
    r = c.post("/admin/login", data={"password": ""})
    assert r.status_code == 401
    assert auth.COOKIE_NOME not in r.headers.get("set-cookie", "")


# ==========================================================================
#  Logout → limpa a sessão
# ==========================================================================
def test_logout_limpa_sessao(client):
    _fazer_login(client)
    assert client.get(_ROTA_PROTEGIDA).status_code == 200  # entrou
    r = client.get("/admin/logout")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # cookie apagado no jar → volta a ser bloqueado
    assert client.get(_ROTA_PROTEGIDA).status_code == 303


# ==========================================================================
#  Segurança do cookie — assinado, não expõe a password, forja rejeitada
# ==========================================================================
def test_cookie_assinado_nao_expoe_password(client):
    r = _fazer_login(client)
    set_cookie = r.headers.get("set-cookie", "")
    assert auth.COOKIE_NOME in set_cookie
    # a password NUNCA aparece no cookie (é um token assinado, não a password)
    assert _PASSWORD not in set_cookie
    # o valor do cookie tem a forma de um token itsdangerous (contém separadores '.')
    valor = client.cookies.get(auth.COOKIE_NOME)
    assert valor and "." in valor


def test_cookie_falsificado_rejeitado(client):
    # um cookie com valor arbitrário (não assinado com SECRET_KEY) não vale
    client.cookies.set(auth.COOKIE_NOME, "dono-falso-sem-assinatura")
    r = client.get(_ROTA_PROTEGIDA)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_cookie_seguro_relaxado_sob_pytest_e_httponly(client):
    """Sob pytest config.cookie_secure() é False (TestClient é http) mas HttpOnly fica."""
    r = _fazer_login(client)
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "secure" not in set_cookie  # relaxado sob pytest (senão o TestClient http perdia o cookie)
    assert "samesite=lax" in set_cookie


# ==========================================================================
#  Helpers de sessão (unidade) — assinar/validar com SECRET_KEY
# ==========================================================================
def test_token_valido_e_forja_invalida():
    token = auth.criar_token_sessao()
    assert auth.sessao_valida(token) is True
    assert auth.sessao_valida(None) is False
    assert auth.sessao_valida("") is False
    assert auth.sessao_valida(token + "x") is False  # assinatura partida
