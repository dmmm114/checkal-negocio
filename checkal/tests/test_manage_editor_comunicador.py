"""Subcomandos `manage.py` dos agentes EDITOR e COMUNICADOR (fase 1 do enxame
de aquisição consent-first — spec 2026-07-19).

COMUNICADOR: `lint --stdin`, `enfileirar --tipo post_grupo --stdin` (linter
POST_SOCIAL fail-closed; camada_risco=2 — rascunho para o dono colar), `estado`.
EDITOR: `plano` (read-only), `lint --stdin`, `enfileirar --tipo artigo_seo
--stdin` (payload JSON estruturado; linter PAGINA_PUBLICA), `estado`.

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
import manage


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_editor_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    monkeypatch.setattr(config, "PAUSA_LLM_PATH", tmp_path / "PAUSA_LLM")
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _json_out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _stdin(monkeypatch, texto: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


_POST_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al"
)


# ==========================================================================
#  COMUNICADOR
# ==========================================================================
def test_comunicador_lint_aprova_post_conforme(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    assert manage.main(["comunicador", "lint", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True


def test_comunicador_enfileirar_cria_item_camada_2(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    rc = manage.main([
        "comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin",
        "--grupo", "AL Porto e Norte",
    ])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "post_grupo"
        assert item.risco == "medio"
        assert item.camada_risco == 2          # rascunho p/ humano, não camada 3
        assert item.agente_origem == "comunicador"
        assert item.estado == "pendente"
        assert item.linter_ok is True
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "comunicador"
        assert evento.payload["corpo_texto"] == _POST_OK
        assert evento.payload["grupo_alvo"] == "AL Porto e Norte"


def test_comunicador_enfileirar_reprovado_nao_insere(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "O teu alojamento está ilegal — paga já.")
    rc = manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert dados["violacoes"]
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_comunicador_estado_conta_por_estado(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin"])
    capsys.readouterr()
    assert manage.main(["comunicador", "estado"]) == 0
    dados = _json_out(capsys)
    assert dados["revisao"] == {"pendente": 1}


def test_comunicador_enfileirar_escalar(bd, capsys):
    rc = manage.main([
        "comunicador", "enfileirar", "--tipo", "post_grupo",
        "--escalar", "--motivo", "sem gatilho fresco utilizável",
    ])
    assert rc == 0
    assert _json_out(capsys) == {"escalado": True}
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1
