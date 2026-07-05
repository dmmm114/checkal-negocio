"""Testes do selo público — app.selo (badge/snippet) + app.web.selo (página) (SPEC-FDS3.md §selo).

Garante o contrato do selo, a prova social "CheckAL ✓ — AL Verificado / Monitorizado":

  app.selo (funções puras de formatação, SEM rede, SEM BD):
    - `gerar_selo_svg` devolve um SVG inline (string) com a marca, o ✓ e o nº de registo;
    - o `nome` vindo de fora é SEMPRE escapado — o selo nunca injeta markup (XSS);
    - `snippet_anuncio` produz uma âncora copy-paste que liga a `BASE_URL/selo/{nr}`.

  app.web.selo (`GET /selo/{nr}`, página pública a partir da BD):
    - registo existente → 200 HTML com "AL Verificado" e "AL Monitorizado" + badge SVG;
    - registo inexistente → 404;
    - **ZERO PII do titular**: NIF, email, telefone, telemóvel e nome do titular NUNCA
      aparecem no corpo — nem como chave nem como valor (lista branca no código).

Isolamento igual ao test_verificar.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; a app FastAPI é montada só com o router do selo e
exercida com `fastapi.testclient.TestClient`. SEM rede, SEM I/O externo.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

# Valores sensíveis do titular — NUNCA devem aparecer em nenhuma saída pública.
_NIF = "513029591"
_EMAIL_TITULAR = "dono.privado@exemplo.pt"
_TITULAR = "João Titular Silva"
_TELEFONE = "289111222"
_TELEMOVEL = "912333444"


# ==========================================================================
#  app.selo — badge SVG (função pura, sem rede/BD)
# ==========================================================================
def test_gerar_selo_svg_e_svg_inline():
    from app.selo import gerar_selo_svg

    svg = gerar_selo_svg(100031, "Casa das Flores")
    assert isinstance(svg, str)
    assert svg.lstrip().startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # marca, tagline, símbolo e nº de registo presentes
    assert "CheckAL" in svg
    assert "✓" in svg          # ✓
    assert "Verificado" in svg
    assert "100031" in svg
    # o nome público do estabelecimento entra no badge
    assert "Casa das Flores" in svg


def test_gerar_selo_svg_escapa_nome_evita_injecao():
    from app.selo import gerar_selo_svg

    svg = gerar_selo_svg(100031, 'Vivenda & "Sol" <script>alert(1)</script>')
    # o markup vindo de fora NUNCA sai cru — nada de tags injetadas
    assert "<script>" not in svg
    assert "</script>" not in svg
    # sai escapado, como texto inofensivo
    assert "&lt;script&gt;" in svg
    assert "&amp;" in svg
    assert "&quot;" in svg


def test_gerar_selo_svg_sem_nome_nao_rebenta():
    from app.selo import gerar_selo_svg

    svg = gerar_selo_svg(100031, "")
    assert svg.lstrip().startswith("<svg")
    assert "100031" in svg


# ==========================================================================
#  app.selo — snippet para o anúncio (âncora copy-paste)
# ==========================================================================
def test_snippet_anuncio_liga_ao_selo():
    from app.selo import snippet_anuncio

    snip = snippet_anuncio(100031)
    assert isinstance(snip, str)
    assert snip.lstrip().startswith("<a")
    # liga à página pública do selo, sob a BASE_URL configurada
    assert "/selo/100031" in snip
    assert config.BASE_URL in snip
    # embute o próprio badge (SVG inline)
    assert "<svg" in snip


# ==========================================================================
#  Fixtures da página pública: BD SQLite temporária + TestClient só com o router
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_selo.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        # AL ativo, com TODOS os campos de titular preenchidos (prova de que não vazam)
        s.add(models.Registo(
            nr_registo=100031,
            data_registo=date(2019, 7, 16),
            nome_alojamento="Casa das Flores",
            modalidade="Apartamento",
            concelho="Lagos",
            distrito="Faro",
            freguesia="São Sebastião",
            titular_tipo="singular",
            titular_nome=_TITULAR,
            nif=_NIF,
            email=_EMAIL_TITULAR,
            telefone=_TELEFONE,
            telemovel=_TELEMOVEL,
            hash_campos="h1",
        ))
        # AL desaparecido (desaparecido_em preenchido) — a página pública ainda responde
        s.add(models.Registo(
            nr_registo=200500,
            data_registo=date(2020, 1, 2),
            nome_alojamento="Vivenda Mar",
            concelho="Porto",
            desaparecido_em=datetime(2026, 6, 1, tzinfo=timezone.utc),
            hash_campos="h2",
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def client(bd):
    from app.web import selo
    app = FastAPI()
    app.include_router(selo.router)
    return TestClient(app)


# ==========================================================================
#  Página pública do selo
# ==========================================================================
def test_selo_existente_200(client):
    r = client.get("/selo/100031")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # a página afirma o selo e a monitorização
    assert "AL Verificado" in corpo
    assert "AL Monitorizado" in corpo
    # dados PÚBLICOS do estabelecimento presentes
    assert "Casa das Flores" in corpo
    assert "Lagos" in corpo
    assert "100031" in corpo
    # o badge SVG está embutido na página
    assert "<svg" in corpo


def test_selo_desaparecido_ainda_responde_200(client):
    # a página é pública e factual; um registo já não listado no RNAL não rebenta
    r = client.get("/selo/200500")
    assert r.status_code == 200
    assert "AL Monitorizado" in r.text


def test_selo_inexistente_404(client):
    r = client.get("/selo/99999999")
    assert r.status_code == 404


def test_selo_zero_pii_do_titular(client):
    r = client.get("/selo/100031")
    corpo = r.text
    for sensivel in (_NIF, _EMAIL_TITULAR, _TITULAR, _TELEFONE, _TELEMOVEL):
        assert sensivel not in corpo, f"PII do titular vazou na página do selo: {sensivel}"
