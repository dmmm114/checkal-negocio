"""E2E do painel admin na app COMPOSTA — app.web.app.criar_app (SPEC-FASE1-DASHBOARD §Wire).

Os testes por módulo (`test_admin_auth/overview/clientes/campanhas`) montam apps
mínimas com só os seus routers. Este ficheiro fecha o contrato do agente de
INTEGRAÇÃO: prova que `criar_app()` — a fábrica única de produção — monta TODO o painel
`/admin/*` a par do website público, e que a fronteira de segurança e o portão de cold
se mantêm depois de composto o sistema inteiro.

Contrato verificado (task WF3 §Wire):
  * todas as rotas do painel estão registadas na app composta (o wire não deixou
    nenhum router de fora, nem duplicou o prefixo para `/admin/admin`);
  * fluxo do dono: login → /admin (overview) → cada secção (clientes, campanhas,
    alertas, compliance, leads) responde 200 AUTENTICADO;
  * red-team: SEM sessão, tudo o que é `/admin/*` (menos o login) bloqueia (303 →
    /admin/login) e não vaza dados; a exportação CSV de compliance também bloqueia;
  * o portão de cold: na página de campanhas o botão "Disparar" nasce DESATIVADO
    enquanto `config.pode_enviar_frio_global()` for False (o default sob pytest), e
    não existe endpoint que ENVIE (POST à página → 405).

Isolamento igual ao resto do web (test_e2e_website.py): BD SQLite temporária via
monkeypatch de `db.engine`/`db.SessionLocal`; a app é a REAL (`criar_app()`); a sessão
obtém-se pelo login real (POST /admin/login com a `config.ADMIN_PASSWORD` injetada).
LIVE-GATED: nada toca a rede; o portão de cold nasce fechado (CHECKAL_MODO_TESTE).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models

_PASSWORD = "segredo-do-dono-42"

# As rotas do painel que a app composta TEM de expor (menos os CSV/login variantes).
_ROTAS_ADMIN = (
    "/admin",
    "/admin/login",
    "/admin/logout",
    "/admin/clientes",
    "/admin/campanhas",
    "/admin/alertas",
    "/admin/compliance",
    "/admin/leads",
)
# As secções protegidas (todas GET) que um dono autenticado vê a 200 e um anónimo não.
_SECCOES = (
    "/admin",
    "/admin/clientes",
    "/admin/campanhas",
    "/admin/alertas",
    "/admin/compliance",
    "/admin/leads",
)


# --------------------------------------------------------------------------
#  Fixtures — BD temporária + password + app REAL (criar_app) + clientes
# --------------------------------------------------------------------------
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_admin.db'}"
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
def password(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", _PASSWORD)
    return _PASSWORD


@pytest.fixture()
def app(bd, password):
    from app.web.app import criar_app

    return criar_app()


@pytest.fixture()
def anon(app):
    """Cliente SEM sessão (não segue redirects — para assertar o 303 → login)."""
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def dono(app):
    """Cliente AUTENTICADO como o dono (login real; cookie assinado no jar)."""
    c = TestClient(app, follow_redirects=False)
    r = c.post("/admin/login", data={"password": _PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/admin"  # entrou
    return c


# --------------------------------------------------------------------------
#  Semeadura — um pouco de tudo, para cada secção ter conteúdo (e um cold)
# --------------------------------------------------------------------------
def _semear() -> None:
    agora = datetime.now(timezone.utc)
    with db.get_session() as s:
        # Um assinante ativo + um AL associado + um alerta enviado -----------------
        s.add(models.Cliente(id=1, email="assinante@exemplo.pt", nome="Cliente Um",
                             plano="anual", estado="ativo", criado_em=agora))
        # Coletiva com email genérico → candidato COLD (dá a fila + o botão) --------
        s.add(models.Registo(
            nr_registo=1001, titular_tipo="coletiva", titular_nome="Empresa A Lda",
            nif="500000000", email="reservas@empresa-a.pt", concelho="Lisboa",
            endereco="Av. A 1", cod_postal="1000-001", nome_alojamento="AL Alfa",
        ))
        s.flush()
        s.add(models.ClienteRegisto(cliente_id=1, nr_registo=1001))
        s.add(models.EventoRegisto(nr_registo=1001, tipo="novo", detetado_em=agora, processado=False))
        s.add(models.Alerta(
            cliente_id=1, nr_registo=1001, origem="eventos_registo",
            conteudo="ALERTA-ALFA-SEGURO", enviado_em=agora, canal="email",
        ))
        # Opt-out + Lead consent-first com a prova (compliance) --------------------
        s.add(models.OptOut(email="removido@exemplo.pt", origem="formulario", criado_em=agora))
        s.add(models.Lead(
            email="interessado@exemplo.pt", nr_registo=1001, concelho="Lisboa",
            consent_alertas=True, consent_ofertas=False,
            consentimento_texto_versao="[v2026-07-06] Autorizo a Cosmic Oasis...",
            consentimento_em=agora, ip="203.0.113.9", estado="confirmado",
            token_confirmacao="tok-e2e-1", criado_em=agora,
        ))


def _botao_disparar(html: str) -> str | None:
    m = re.search(r"<button[^>]*data-disparar[^>]*>", html, re.S)
    return m.group(0) if m else None


# ==========================================================================
#  Wire — a app composta expõe TODO o painel (sem duplicar /admin/admin)
# ==========================================================================
def test_rotas_admin_registadas_na_app_composta(app):
    caminhos = {getattr(r, "path", None) for r in app.routes}
    for rota in _ROTAS_ADMIN:
        assert rota in caminhos, f"rota do painel em falta no wire: {rota}"
    # o prefixo NÃO foi duplicado
    assert not any((p or "").startswith("/admin/admin") for p in caminhos)


def test_wire_preserva_o_website_publico(app):
    """O painel monta-se A PAR do site — o público continua registado."""
    caminhos = {getattr(r, "path", None) for r in app.routes}
    for publico in ("/", "/saude", "/api/verificar", "/webhooks/stripe"):
        assert publico in caminhos


# ==========================================================================
#  Fluxo do dono — login → overview → cada secção 200 autenticado
# ==========================================================================
def test_login_leva_ao_overview(dono):
    r = dono.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    corpo = r.text
    # chrome coerente do painel (marca + nav única com todas as secções)
    assert "CheckAL" in corpo
    assert "/static/brand.css" in corpo
    for href in ("/admin/clientes", "/admin/campanhas", "/admin/alertas",
                 "/admin/compliance", "/admin/leads", "/admin/logout"):
        assert f'href="{href}"' in corpo


@pytest.mark.parametrize("rota", _SECCOES)
def test_cada_seccao_200_autenticado(dono, rota):
    _semear()
    r = dono.get(rota)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_overview_conta_o_assinante_ativo(dono):
    _semear()
    corpo = dono.get("/admin").text
    m = re.search(r'data-metrica="clientes_ativos"[^>]*>\s*(\d+)', corpo)
    assert m and m.group(1) == "1"


def test_clientes_lista_o_assinante(dono):
    _semear()
    corpo = dono.get("/admin/clientes").text
    assert "assinante@exemplo.pt" in corpo
    assert "AL Alfa" in corpo


def test_compliance_mostra_a_prova(dono):
    _semear()
    corpo = dono.get("/admin/compliance").text
    assert "removido@exemplo.pt" in corpo          # opt-out
    assert "interessado@exemplo.pt" in corpo        # consentimento
    assert "203.0.113.9" in corpo                   # IP (prova)
    assert "reservas@empresa-a.pt" in corpo         # proveniência (canal frio)


def test_leads_mostra_o_prospect(dono):
    _semear()
    corpo = dono.get("/admin/leads").text
    assert "interessado@exemplo.pt" in corpo


# ==========================================================================
#  Red-team — sem sessão, tudo o que é /admin/* (menos login) bloqueia
# ==========================================================================
@pytest.mark.parametrize("rota", _SECCOES)
def test_sem_sessao_cada_seccao_bloqueia(anon, rota):
    _semear()
    r = anon.get(rota)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_sem_sessao_nao_vaza_pii(anon):
    _semear()
    for rota in ("/admin/clientes", "/admin/compliance", "/admin/leads"):
        corpo = anon.get(rota).text
        assert "assinante@exemplo.pt" not in corpo
        assert "interessado@exemplo.pt" not in corpo
        assert "203.0.113.9" not in corpo


def test_export_csv_sem_sessao_bloqueia(anon):
    _semear()
    for csv_rota in ("/admin/compliance/consentimentos.csv", "/admin/compliance/optouts.csv"):
        r = anon.get(csv_rota)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/login"
        assert "interessado@exemplo.pt" not in r.text
        assert "removido@exemplo.pt" not in r.text


def test_login_publico_e_password_errada_recusa(anon):
    # o login É público (senão não se entrava)
    assert anon.get("/admin/login").status_code == 200
    # password errada não abre sessão
    r = anon.post("/admin/login", data={"password": "nao-e-a-password"})
    assert r.status_code == 401
    from app.web.admin import auth
    assert auth.COOKIE_NOME not in r.headers.get("set-cookie", "")


def test_logout_termina_a_sessao(dono):
    assert dono.get("/admin").status_code == 200   # entrou
    r = dono.get("/admin/logout")
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    # cookie apagado no jar → volta a bloquear
    assert dono.get("/admin").status_code == 303


# ==========================================================================
#  Portão de cold — botão DESATIVADO sob gate fechado; sem disparo real
# ==========================================================================
def test_botao_cold_desativado_sob_gate_fechado(dono):
    _semear()
    # o portão nasce fechado sob pytest (CHECKAL_MODO_TESTE=True)
    assert config.pode_enviar_frio_global() is False

    corpo = dono.get("/admin/campanhas").text
    botao = _botao_disparar(corpo)
    assert botao is not None, "a fila de cold devia expor o botão Disparar"
    assert "disabled" in botao, "o botão Disparar tem de nascer DESATIVADO sob gate fechado"
    # o aviso explica o porquê (parecer RGPD)
    assert "parecer" in corpo.lower()


def test_campanhas_nao_tem_disparo_real(dono):
    """Read-first: não há endpoint que ENVIE — POST à página é 405."""
    r = dono.post("/admin/campanhas")
    assert r.status_code == 405
