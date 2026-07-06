"""Testes do direito de oposição / opt-out — app.web.remover (SPEC-FASE1-WEB §remover).

Garante o contrato da página que trava qualquer contacto futuro — o "não me
contactem" que a lei (Lei 41/2004, art. 13.º-B; RGPD art. 21.º) exige que seja
fácil e sem custo:

  GET  /remover                → formulário (pede o email);
  POST /remover (email)        → regista o opt-out na tabela `optouts` (idempotente),
                                  marca o(s) Lead(s) desse email como 'removido' e
                                  mostra uma confirmação amigável;
  GET  /remover?e=&t=          → opt-out de 1 clique (o link carimbado nos emails):
                                  regista logo a oposição e confirma, sem login.

Fronteiras respeitadas:
  * o email é guardado JÁ NORMALIZADO (minúsculas/sem espaços) — a MESMA forma que
    `app.compliance.optout` usa para cruzar a lista de supressão antes de cada envio,
    para que a oposição gravada aqui de facto exclua o contacto lá (o loop fecha);
  * o model `Lead` está a ser construído por OUTRO agente (consentimento). O opt-out
    toca a tabela `leads` por NOME (contrato do SPEC), pelo que este teste cria essa
    tabela por SQL bruto (fora de `db.Base`) — autónomo e sem colidir com a definição
    real de `Lead` no full-suite.

Isolamento igual ao test_selo.py: BD SQLite temporária via monkeypatch de
`db.engine`/`db.SessionLocal`; a app FastAPI é montada só com o router do remover e
exercida com `fastapi.testclient.TestClient`. SEM rede, SEM I/O externo. LIVE-GATED.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models

_LEAD_EMAIL = "geral@casaflores.pt"     # existe como Lead 'pendente' + token 'tok-abc'
_LEAD_TOKEN = "tok-abc"
_OUTRO_EMAIL = "outro@exemplo.pt"       # outro Lead — NÃO deve ser afetado


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_remover.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()  # cria `optouts` e `leads` (ambas em app.models) + o resto do esquema
    # Semeia dois Leads reais (o model é de OUTRO agente; aqui só se persiste o
    # contrato do SPEC): um 'pendente' que o opt-out deve marcar 'removido' e um
    # outro que NÃO tem de ser afetado.
    with db.get_session() as s:
        s.add(models.Lead(email=_LEAD_EMAIL, estado="pendente", token_confirmacao=_LEAD_TOKEN))
        s.add(models.Lead(email=_OUTRO_EMAIL, estado="confirmado", token_confirmacao="tok-xyz"))
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def client(bd):
    from app.web import remover
    app = FastAPI()
    app.include_router(remover.router)
    return TestClient(app)


# --- helpers de leitura da BD (via a sessão monkeypatched) --------------------
def _optouts() -> list[str]:
    with db.get_session() as s:
        return [o.email for o in s.query(models.OptOut).all()]


def _estado_lead(email: str) -> str | None:
    with db.get_session() as s:
        row = s.execute(
            text("SELECT estado FROM leads WHERE email = :e"), {"e": email}
        ).first()
        return row[0] if row else None


# ==========================================================================
#  GET /remover — formulário
# ==========================================================================
def test_get_remover_mostra_formulario(client):
    r = client.get("/remover")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # é um formulário POST com um campo de email
    assert "<form" in corpo
    assert 'method="post"' in corpo.lower()
    assert 'name="email"' in corpo
    assert 'type="email"' in corpo
    assert "submit" in corpo.lower()  # há um botão de submissão
    # chrome da marca (estende base.html)
    assert "CheckAL" in corpo
    assert "/static/brand.css" in corpo


# ==========================================================================
#  POST /remover — grava opt-out + marca Lead + confirma
# ==========================================================================
def test_post_grava_optout_confirma_e_marca_lead(bd, client):
    # email com casing/espaços — deve ser normalizado antes de gravar
    r = client.post("/remover", data={"email": "  Geral@CasaFlores.pt  "})
    assert r.status_code == 200
    corpo = r.text
    # confirmação amigável, com o email (normalizado) ecoado
    assert _LEAD_EMAIL in corpo
    assert any(p in corpo.lower() for p in ("removido", "removemos", "fora da lista"))

    # opt-out gravado UMA vez, com a chave NORMALIZADA (para o filtro cruzar)
    assert _optouts() == [_LEAD_EMAIL]

    # o Lead desse email ficou 'removido'; o outro Lead ficou intacto
    assert _estado_lead(_LEAD_EMAIL) == "removido"
    assert _estado_lead(_OUTRO_EMAIL) == "confirmado"

    # o loop fecha: o email gravado exclui o contacto no núcleo de compliance
    from app.compliance import optout
    assert optout.deve_excluir(
        "Geral@CasaFlores.pt", lista_dgc=[], log_optout=_optouts()
    )


def test_post_idempotente(bd, client):
    for _ in range(3):
        r = client.post("/remover", data={"email": _LEAD_EMAIL})
        assert r.status_code == 200
    # opor-se N vezes = UMA linha (idempotente pela chave natural)
    assert _optouts() == [_LEAD_EMAIL]
    assert _estado_lead(_LEAD_EMAIL) == "removido"


def test_post_email_invalido_reexibe_form_sem_gravar(bd, client):
    r = client.post("/remover", data={"email": "isto-nao-e-um-email"})
    assert r.status_code == 200
    corpo = r.text
    # volta a mostrar o formulário, com um aviso amigável — e NÃO grava lixo
    assert "<form" in corpo
    assert 'name="email"' in corpo
    assert _optouts() == []


# ==========================================================================
#  GET /remover?e=&t= — opt-out de 1 clique (link dos emails)
# ==========================================================================
def test_1clique_grava_e_confirma(bd, client):
    r = client.get("/remover", params={"e": _LEAD_EMAIL, "t": _LEAD_TOKEN})
    assert r.status_code == 200
    corpo = r.text
    assert _LEAD_EMAIL in corpo
    assert any(p in corpo.lower() for p in ("removido", "removemos", "fora da lista"))
    assert _optouts() == [_LEAD_EMAIL]
    assert _estado_lead(_LEAD_EMAIL) == "removido"


def test_1clique_idempotente(bd, client):
    for _ in range(2):
        r = client.get("/remover", params={"e": _LEAD_EMAIL, "t": _LEAD_TOKEN})
        assert r.status_code == 200
    assert _optouts() == [_LEAD_EMAIL]


def test_1clique_normaliza_email(bd, client):
    # o `e` do link pode vir com casing — grava-se normalizado, sem duplicar
    r = client.get("/remover", params={"e": "GERAL@CasaFlores.PT"})
    assert r.status_code == 200
    assert _optouts() == [_LEAD_EMAIL]


# ==========================================================================
#  Segurança — autoescape (templates à prova de XSS, red-team do SPEC)
# ==========================================================================
def test_confirmacao_escapa_email_anti_xss(bd, client):
    payload = "x<script>alert(1)</script>@evil.pt"
    r = client.post("/remover", data={"email": payload})
    assert r.status_code == 200
    corpo = r.text
    # o email ecoado NUNCA sai como markup cru — autoescape do Jinja
    assert "<script>alert(1)</script>" not in corpo
    assert "&lt;script&gt;" in corpo
