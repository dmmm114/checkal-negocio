"""Testes da app FastAPI de composição — app.web.app (SPEC-FDS2.md §app).

`criar_app() -> FastAPI` é o único ponto que monta os três routers do FDS 2
(landing, verificação consent-first e webhook Stripe) numa única aplicação. Estes
testes garantem o contrato mínimo de integração:

  - `criar_app()` devolve uma instância `FastAPI` que arranca sob `TestClient`;
  - o healthcheck `GET /saude` responde 200 com `{"ok": true}`;
  - a landing `GET /` está montada (200, HTML);
  - as rotas dos três routers estão registadas (`/`, `/saude`, `/api/verificar`,
    `/webhooks/stripe`) — a composição não deixou nenhum router de fora.

SEM rede, SEM I/O externo, SEM DB semeada (só se inspecionam rotas + healthcheck +
landing, que não tocam a BD). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app() -> FastAPI:
    from app.web.app import criar_app

    return criar_app()


# --------------------------------------------------------------------------
#  criar_app() devolve uma FastAPI que arranca
# --------------------------------------------------------------------------
def test_criar_app_devolve_fastapi():
    app = _app()
    assert isinstance(app, FastAPI)


def test_app_arranca_sob_testclient():
    # o simples facto de o TestClient entrar no context manager exercita o arranque
    with TestClient(_app()) as client:
        assert client is not None


# --------------------------------------------------------------------------
#  Healthcheck + landing montados
# --------------------------------------------------------------------------
def test_saude_200():
    client = TestClient(_app())
    r = client.get("/saude")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_home_200_html():
    client = TestClient(_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "CheckAL" in r.text


# --------------------------------------------------------------------------
#  Todas as rotas dos três routers estão registadas
# --------------------------------------------------------------------------
def test_rotas_dos_tres_routers_registadas():
    app = _app()
    caminhos = {getattr(r, "path", None) for r in app.routes}
    for esperado in ("/", "/saude", "/api/verificar", "/webhooks/stripe"):
        assert esperado in caminhos, f"rota em falta na composição: {esperado}"


def test_webhook_e_post():
    # a rota do webhook existe e aceita POST (não é acidentalmente um GET)
    app = _app()
    metodos: set[str] = set()
    for r in app.routes:
        if getattr(r, "path", None) == "/webhooks/stripe":
            metodos |= set(getattr(r, "methods", set()) or set())
    assert "POST" in metodos
