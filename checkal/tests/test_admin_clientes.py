"""Testes do dashboard de clientes + alertas — app.web.admin.dashboard_clientes
(SPEC-FASE1-DASHBOARD §dashboard: /admin/clientes e /admin/alertas).

O painel é do DONO e só do dono. Duas páginas de LEITURA (read-first, nenhuma ação
que envie/cobre a frio):

  GET /admin/clientes  → lista dos assinantes (email, nome, plano, estado, n.º AL,
                         criado) + detalhe/histórico (alojamentos associados +
                         alertas enviados). Só informa.
  GET /admin/alertas   → fila de alertas enviados + os eventos `desaparecido`
                         PENDENTES de desambiguação (processado=False). Só informa;
                         o breaker decide.

Contrato verificado (o que o SPEC/task exige, "Testa: …"):
  * autenticado → 200 com os dados semeados (emails, planos, estados, n.º AL,
    nomes dos alojamentos associados, conteúdo dos alertas, desaparecidos pendentes);
  * sem sessão → BLOQUEADO (303 → /admin/login), nada da página protegida sai;
  * cookie forjado → BLOQUEADO (red-team: a posse de um cookie não-assinado não abre);
  * MINIMIZAÇÃO / zero-PII indevida: os CONTACTOS do titular do RNAL (NIF, email,
    telefone, nome do titular) NÃO aparecem no painel de clientes — só o que a
    operação precisa (o email do PRÓPRIO assinante é operacional e pode aparecer);
  * o filtro de desambiguação mostra SÓ `desaparecido` NÃO processados (um
    `alterado` e um `desaparecido` já processado não entram).

Isolamento igual ao test_selo.py/test_consentimento.py: BD SQLite temporária via
monkeypatch de `db.engine`/`db.SessionLocal`; a app FastAPI monta só o router em
teste (+ o de auth) e é exercida com `fastapi.testclient.TestClient`. A sessão do
dono injeta-se pelo token assinado (`auth.criar_token_sessao`) — sem passar pelo
formulário, determinístico. SEM rede, SEM I/O externo. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.web.admin import auth

# --- Contactos do TITULAR do RNAL (NUNCA devem aparecer no painel de clientes) ---
_TITULAR_NOME = "Ana Titular Silva"
_TITULAR_NIF = "500100200"
_TITULAR_EMAIL = "titular.privado@exemplo.pt"
_TITULAR_TEL = "289000111"


# ==========================================================================
#  Fixtures: BD SQLite temporária + dados semeados + TestClient (routers em teste)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_admin_clientes.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    with db.get_session() as s:
        # --- Registos (alojamentos) ---
        # 100031: ATIVO, com TODOS os contactos do titular preenchidos (prova de não-vazamento).
        s.add(models.Registo(
            nr_registo=100031,
            data_registo=date(2019, 7, 16),
            nome_alojamento="Casa das Flores",
            modalidade="Apartamento",
            concelho="Lagos",
            distrito="Faro",
            titular_tipo="singular",
            titular_nome=_TITULAR_NOME,
            nif=_TITULAR_NIF,
            email=_TITULAR_EMAIL,
            telefone=_TITULAR_TEL,
            hash_campos="h1",
        ))
        # 200500: DESAPARECIDO (desaparecido_em preenchido).
        s.add(models.Registo(
            nr_registo=200500,
            nome_alojamento="Vivenda Mar",
            concelho="Porto",
            desaparecido_em=datetime(2026, 6, 21, tzinfo=timezone.utc),
            hash_campos="h2",
        ))
        # 300700: ATIVO.
        s.add(models.Registo(
            nr_registo=300700,
            nome_alojamento="Loft Douro",
            concelho="Porto",
            hash_campos="h3",
        ))
        # 500000: registo de um desaparecido JÁ PROCESSADO (não deve entrar na fila pendente).
        s.add(models.Registo(
            nr_registo=500000,
            nome_alojamento="Reg Processado",
            concelho="Braga",
            desaparecido_em=datetime(2026, 5, 1, tzinfo=timezone.utc),
            hash_campos="h4",
        ))

        # --- Clientes (assinantes) ---
        cliente_a = models.Cliente(
            id=1, email="ana@exemplo.pt", nome="Ana Cliente",
            plano="anual", estado="ativo",
            criado_em=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        )
        cliente_b = models.Cliente(
            id=2, email="bruno@empresa.pt", nome="Bruno Lda",
            plano="portfolio", estado="em_dunning",
            criado_em=datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc),
        )
        s.add(cliente_a)
        s.add(cliente_b)
        s.flush()

        # --- Associações cliente ↔ registo ---
        s.add(models.ClienteRegisto(cliente_id=1, nr_registo=100031))   # Ana: 1 AL
        s.add(models.ClienteRegisto(cliente_id=2, nr_registo=200500))   # Bruno: 2 AL
        s.add(models.ClienteRegisto(cliente_id=2, nr_registo=300700))

        # --- Alertas enviados ---
        s.add(models.Alerta(
            cliente_id=1, nr_registo=100031, origem="eventos_registo",
            conteudo="ALERTA-CASA-FLORES-SEGURO",
            enviado_em=datetime(2026, 6, 20, 8, 0, tzinfo=timezone.utc), canal="email",
        ))
        s.add(models.Alerta(
            cliente_id=2, nr_registo=200500, origem="eventos_registo",
            conteudo="ALERTA-VIVENDA-DESAPARECIDO",
            enviado_em=datetime(2026, 6, 21, 8, 0, tzinfo=timezone.utc), canal="email",
        ))

        # --- Eventos de registo (para a fila de desambiguação) ---
        # PENDENTE: desaparecido não processado → DEVE aparecer.
        s.add(models.EventoRegisto(
            nr_registo=200500, tipo="desaparecido", processado=False,
            detetado_em=datetime(2026, 6, 21, 7, 0, tzinfo=timezone.utc),
        ))
        # 'alterado' (não é desaparecido) → NÃO deve aparecer na fila de desambiguação.
        s.add(models.EventoRegisto(
            nr_registo=300700, tipo="alterado", processado=False,
            detetado_em=datetime(2026, 6, 22, 7, 0, tzinfo=timezone.utc),
        ))
        # desaparecido JÁ processado → NÃO deve aparecer na fila.
        s.add(models.EventoRegisto(
            nr_registo=500000, tipo="desaparecido", processado=True,
            detetado_em=datetime(2026, 5, 1, 7, 0, tzinfo=timezone.utc),
        ))
    try:
        yield
    finally:
        eng.dispose()


@pytest.fixture()
def app_admin(bd):
    from app.web.admin import dashboard_clientes
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(dashboard_clientes.router)
    return app


@pytest.fixture()
def anon(app_admin):
    """Cliente SEM sessão — follow_redirects=False para assertar o 303 → login."""
    return TestClient(app_admin, follow_redirects=False)


@pytest.fixture()
def dono(app_admin):
    """Cliente COM a sessão do dono (token assinado injetado no cookie jar)."""
    c = TestClient(app_admin, follow_redirects=False)
    c.cookies.set(auth.COOKIE_NOME, auth.criar_token_sessao())
    return c


# ==========================================================================
#  /admin/clientes — autenticado (200 + dados)
# ==========================================================================
def test_clientes_autenticado_200_lista(dono):
    r = dono.get("/admin/clientes")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # os assinantes e os seus dados operacionais
    assert "ana@exemplo.pt" in corpo
    assert "bruno@empresa.pt" in corpo
    # nome legível do plano (de config.PLANOS, não o código cru)
    from app.config import PLANOS
    assert PLANOS["anual"]["nome"] in corpo        # "CheckAL Anual"
    assert PLANOS["portfolio"]["nome"] in corpo    # "Portfólio"
    # estados dos assinantes
    assert "em_dunning" in corpo


def test_clientes_mostra_detalhe_e_historico(dono):
    """Detalhe/histórico: alojamentos associados + alertas enviados por cliente."""
    corpo = dono.get("/admin/clientes").text
    # alojamentos associados (detalhe) — 1 do cliente A, 2 do cliente B
    assert "Casa das Flores" in corpo
    assert "Vivenda Mar" in corpo
    assert "Loft Douro" in corpo
    # histórico de alertas do cliente
    assert "ALERTA-CASA-FLORES-SEGURO" in corpo


def test_clientes_nao_vaza_pii_do_titular(dono):
    """Minimização: os contactos do TITULAR do RNAL não entram no painel de clientes."""
    corpo = dono.get("/admin/clientes").text
    for sensivel in (_TITULAR_NIF, _TITULAR_EMAIL, _TITULAR_NOME, _TITULAR_TEL):
        assert sensivel not in corpo, f"PII do titular vazou no painel de clientes: {sensivel}"


# ==========================================================================
#  /admin/clientes — sem sessão / cookie forjado → bloqueado
# ==========================================================================
def test_clientes_sem_sessao_bloqueia(anon):
    r = anon.get("/admin/clientes")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    # nada dos dados protegidos sai no corpo do redirect
    assert "ana@exemplo.pt" not in r.text


def test_clientes_cookie_forjado_bloqueia(app_admin):
    c = TestClient(app_admin, follow_redirects=False)
    c.cookies.set(auth.COOKIE_NOME, "dono-falso-sem-assinatura")
    r = c.get("/admin/clientes")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


# ==========================================================================
#  /admin/alertas — autenticado (200 + fila + desaparecidos pendentes)
# ==========================================================================
def test_alertas_autenticado_200_fila(dono):
    r = dono.get("/admin/alertas")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # a fila de alertas enviados
    assert "ALERTA-CASA-FLORES-SEGURO" in corpo
    assert "ALERTA-VIVENDA-DESAPARECIDO" in corpo


def test_alertas_mostra_desaparecidos_pendentes(dono):
    corpo = dono.get("/admin/alertas").text
    # o desaparecido PENDENTE (200500 / Vivenda Mar) tem de aparecer na desambiguação
    assert "200500" in corpo
    assert "Vivenda Mar" in corpo


def test_alertas_filtra_so_desaparecido_nao_processado(dono):
    """Só entram `desaparecido` NÃO processados: nem o 'alterado', nem o já processado."""
    corpo = dono.get("/admin/alertas").text
    # 'alterado' (300700) não é desaparecido → o seu registo não é convocado à fila
    assert "300700" not in corpo
    assert "Loft Douro" not in corpo
    # desaparecido JÁ processado (500000 / Reg Processado) não entra na fila pendente
    assert "500000" not in corpo
    assert "Reg Processado" not in corpo


# ==========================================================================
#  /admin/alertas — sem sessão / cookie forjado → bloqueado
# ==========================================================================
def test_alertas_sem_sessao_bloqueia(anon):
    r = anon.get("/admin/alertas")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    assert "ALERTA-" not in r.text


def test_alertas_cookie_forjado_bloqueia(app_admin):
    c = TestClient(app_admin, follow_redirects=False)
    c.cookies.set(auth.COOKIE_NOME, "dono-falso-sem-assinatura")
    r = c.get("/admin/alertas")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
