"""Testes do portão 1-clique — GET/POST /gate/{item_id} (Fase 2 · F2.2).

Prova, pela app COMPOSTA (`app.web.app.criar_app`), que o token é a ÚNICA
credencial do gate: GET nunca decide (só mostra), POST decide
(aprova/rejeita) e qualquer token vazio/errado/não-ASCII, item inexistente ou
já decidido cai sempre na página de "ligação inválida" — NUNCA um 500.

Isolamento igual a test_swarm_fila.py / test_e2e_website.py: BD SQLite
temporária via monkeypatch de `db.engine`/`db.SessionLocal`. Português.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models_swarm as ms
from app.compliance.linter import Canal, PecaOutward
from app.swarm import fila


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_gate_web.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def client(bd):
    from app.web.app import criar_app

    return TestClient(criar_app())


# Peça POST_SOCIAL conforme (linter R4: fonte oficial cm-porto.pt no próprio
# texto) — o mesmo texto de test_manage_editor_comunicador._POST_OK.
_POST_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al"
)


def _semear(*, agente_origem: str = "comunicador") -> tuple[int, str]:
    """Enfileira um item POST_SOCIAL conforme e gera-lhe o token 1-clique.

    Devolve `(item_id, token)` — a dupla que o link do gate carrega.
    """
    peca = PecaOutward(texto=_POST_OK, canal=Canal.POST_SOCIAL)
    with db.get_session() as s:
        item = fila.enfileirar(
            s, tipo="post_grupo", risco="medio", agente_origem=agente_origem,
            peca=peca, resumo="Post sobre o regulamento do Porto",
        )
        s.flush()
        token = fila.gerar_token(s, item.id)
        item_id = item.id
    return item_id, token


def _item(item_id: int) -> ms.RevisaoItem | None:
    with db.get_session() as s:
        return s.get(ms.RevisaoItem, item_id)


def _aprovacoes(item_id: int) -> list[ms.Aprovacao]:
    with db.get_session() as s:
        return (
            s.query(ms.Aprovacao)
            .filter(ms.Aprovacao.revisao_item_id == item_id)
            .all()
        )


# ==========================================================================
#  GET — mostra, nunca decide
# ==========================================================================
def test_gate_get_token_valido_mostra_item(client):
    item_id, token = _semear()
    r = client.get(f"/gate/{item_id}", params={"token": token})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "post_grupo" in r.text
    assert "Aprovar" in r.text
    assert "Rejeitar" in r.text


def test_gate_get_token_errado_pagina_invalida(client):
    item_id, _token = _semear()
    r = client.get(f"/gate/{item_id}", params={"token": "isto-nao-e-o-token"})
    assert r.status_code == 200
    assert "Aprovar" not in r.text
    assert "Rejeitar" not in r.text
    assert "inválid" in r.text.lower()


def test_gate_get_token_nao_ascii_pagina_invalida(client):
    """Regressão: token não-ASCII nunca rebenta (TypeError/500) — só invalida."""
    item_id, _token = _semear()
    r = client.get(f"/gate/{item_id}", params={"token": "café-ñ"})
    assert r.status_code == 200
    assert "inválid" in r.text.lower()


def test_gate_item_inexistente_pagina_invalida(client):
    r = client.get("/gate/99999", params={"token": "x"})
    assert r.status_code == 200
    assert "inválid" in r.text.lower()


def test_gate_get_nao_decide(client):
    item_id, token = _semear()
    r = client.get(f"/gate/{item_id}", params={"token": token})
    assert r.status_code == 200
    assert _item(item_id).estado == "pendente"


# ==========================================================================
#  POST — decide (aprovar/rejeitar)
# ==========================================================================
def test_gate_post_aprovar_decide_e_regista(client):
    item_id, token = _semear()
    r = client.post(f"/gate/{item_id}/aprovar", data={"token": token})
    assert r.status_code == 200
    assert "aprovad" in r.text.lower()

    item = _item(item_id)
    assert item.estado == "aprovado"
    assert item.decidido_por == "dono"
    assert len(_aprovacoes(item_id)) == 1

    # Reutilizar o token depois de decidido: página inválida, o item continua
    # aprovado (o token já não serve para nada — não desfaz nem reaprova).
    r2 = client.post(f"/gate/{item_id}/rejeitar", data={"token": token})
    assert r2.status_code == 200
    assert "inválid" in r2.text.lower()
    assert _item(item_id).estado == "aprovado"
    assert len(_aprovacoes(item_id)) == 1  # nenhuma segunda linha gravada


def test_gate_post_rejeitar_decide(client):
    item_id, token = _semear()
    r = client.post(f"/gate/{item_id}/rejeitar", data={"token": token})
    assert r.status_code == 200
    assert _item(item_id).estado == "rejeitado"


def test_gate_item_inexistente_post_pagina_invalida(client):
    r = client.post("/gate/99999/aprovar", data={"token": "x"})
    assert r.status_code == 200
    assert "inválid" in r.text.lower()
