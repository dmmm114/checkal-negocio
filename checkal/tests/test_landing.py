"""Testes da landing pública + healthcheck — app.web.landing (SPEC-FDS2.md §landing).

Garante: `GET /` devolve 200 com HTML; `GET /saude` devolve `{"ok": true}`.
A copy é placeholder (a final é canónica em COPY-VENDAS.md — não se inventa aqui).
SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.web import landing
    app = FastAPI()
    app.include_router(landing.router)
    return TestClient(app)


# --------------------------------------------------------------------------
#  GET / — página inicial (HTML)
# --------------------------------------------------------------------------
def test_home_200_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_home_menciona_marca(client):
    # a copy é placeholder, mas a marca CheckAL está presente
    r = client.get("/")
    assert "CheckAL" in r.text


# --------------------------------------------------------------------------
#  GET /saude — healthcheck
# --------------------------------------------------------------------------
def test_saude_ok(client):
    r = client.get("/saude")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"ok": True}
