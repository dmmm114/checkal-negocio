"""Subcomandos `manage.py` dos agentes EDITOR e COMUNICADOR (fase 1 do enxame
de aquisição consent-first — spec 2026-07-19).

COMUNICADOR: `lint --stdin`, `enfileirar --tipo post_grupo --stdin` (linter
POST_SOCIAL fail-closed; camada_risco=2 — rascunho para o dono colar), `estado`.
EDITOR: `plano` (read-only), `lint --stdin`, `enfileirar --tipo artigo_seo
--stdin` (payload JSON estruturado; linter PAGINA_PUBLICA), `estado`.

Ambos cobertos por testes nesta suite (COMUNICADOR e EDITOR).

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import io
import json
from datetime import date

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
        "--fonte", "https://www.cm-porto.pt/regulamento-al",
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
        assert evento.payload["fonte_url"] == "https://www.cm-porto.pt/regulamento-al"


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


def test_comunicador_estado_vazio(bd, capsys):
    assert manage.main(["comunicador", "estado"]) == 0
    assert _json_out(capsys) == {"revisao": {}}


# --------------------------------------------------------------------------
#  post_pagina (fase FB, 19/07): canal POST_PAGINA — publicação AUTOMÁTICA
#  pelo sistema (camada 4), por isso EXIGE a divulgação de IA (diverge do
#  post_grupo, que o dono cola manualmente e fica isento).
# --------------------------------------------------------------------------
_POST_PAGINA_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al\n"
    "Preparado com apoio de IA."
)


def test_comunicador_lint_default_continua_post_grupo(bd, capsys, monkeypatch):
    # Retrocompatibilidade: sem --tipo, o lint continua a vetar como POST_SOCIAL.
    _stdin(monkeypatch, _POST_OK)
    assert manage.main(["comunicador", "lint", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True


def test_comunicador_lint_post_pagina_com_tipo(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_PAGINA_OK)
    rc = manage.main(["comunicador", "lint", "--stdin", "--tipo", "post_pagina"])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True


def test_comunicador_lint_post_pagina_sem_divulgacao_reprova(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)  # sem "Preparado com apoio de IA."
    rc = manage.main(["comunicador", "lint", "--stdin", "--tipo", "post_pagina"])
    assert rc == 0  # lint devolve 0 e reporta aprovado=False no JSON
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert any(v["regra"] == "R5_DIVULGACAO_IA" for v in dados["violacoes"])


def test_comunicador_enfileirar_post_pagina_cria_item_camada_4(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_PAGINA_OK)
    rc = manage.main([
        "comunicador", "enfileirar", "--tipo", "post_pagina", "--stdin",
        "--fonte", "https://www.cm-porto.pt/regulamento-al",
    ])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "post_pagina"
        assert item.risco == "alto"
        assert item.camada_risco == 4          # publicação pelo sistema, não pelo dono
        assert item.agente_origem == "comunicador"
        assert item.estado == "pendente"
        assert item.linter_ok is True
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "comunicador"
        assert evento.payload["tipo"] == "post_pagina"
        assert evento.payload["corpo_texto"] == _POST_PAGINA_OK


def test_comunicador_enfileirar_post_pagina_sem_divulgacao_da_1(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)  # sem "Preparado com apoio de IA."
    rc = manage.main(["comunicador", "enfileirar", "--tipo", "post_pagina", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert any(v["regra"] == "R5_DIVULGACAO_IA" for v in dados["violacoes"])
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_comunicador_enfileirar_post_grupo_continua_camada_2_sem_divulgacao(
    bd, capsys, monkeypatch,
):
    # Regressão: acrescentar post_pagina não pode mexer no post_grupo — sem
    # divulgação de IA continua a aprovar, e a camada mantém-se 2.
    _stdin(monkeypatch, _POST_OK)
    rc = manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin"])
    assert rc == 0
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "post_grupo"
        assert item.camada_risco == 2


# ==========================================================================
#  EDITOR
# ==========================================================================
_ARTIGO_OK = {
    "slug": "regulamentos-al-porto",
    "titulo": "Regulamentos municipais de Alojamento Local no Porto: o essencial",
    "meta_description": "O que muda para o AL no Porto e onde confirmar na fonte oficial.",
    "tipo_pagina": "pilar",
    "data_publicacao": "2026-07-19",
    "seccoes": [
        {"h2": "O que é o regulamento municipal",
         "corpo_md": "Cada município pode definir regras próprias para o AL."},
        {"h2": "Onde confirmar",
         "corpo_md": "A fonte oficial é o portal do município e o Diário da República."},
    ],
    "fontes": [
        {"url": "https://www.cm-porto.pt/regulamento-al",
         "titulo": "Regulamento AL — CM Porto", "data": "2026-05-10",
         "excerto": "O presente regulamento, publicado a 10 de maio de 2026, "
                    "define as regras aplicáveis."},
    ],
}


def test_editor_lint_aprova_artigo_conforme(bd, capsys, monkeypatch):
    _stdin(monkeypatch, json.dumps(_ARTIGO_OK, ensure_ascii=False))
    assert manage.main(["editor", "lint", "--stdin"]) == 0
    assert _json_out(capsys)["aprovado"] is True


def test_editor_lint_json_invalido_da_2(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "não é json")
    assert manage.main(["editor", "lint", "--stdin"]) == 2


def test_editor_enfileirar_artigo_valido(bd, capsys, monkeypatch):
    _stdin(monkeypatch, json.dumps(_ARTIGO_OK, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "artigo_seo"
        assert item.risco == "alto"
        assert item.camada_risco == 4          # publicação ⇒ camada máxima
        assert item.agente_origem == "editor"
        assert "regulamentos-al-porto" in item.resumo
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "editor"
        assert evento.payload["artigo"]["slug"] == "regulamentos-al-porto"


def test_editor_enfileirar_json_invalido_da_2(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "isto não é json")
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 2
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_enfileirar_slug_hostil_da_2(bd, capsys, monkeypatch):
    """Regressão (revisão 2026-07-19, XSS Critical #1): um slug hostil nunca
    deve sequer entrar na fila — validado na ORIGEM com a mesma whitelist do
    render (`app.publicador._RE_SLUG`), antes de o artigo ser enfileirado."""
    mau = dict(_ARTIGO_OK)
    mau["slug"] = "../x"
    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 2
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_enfileirar_fonte_esquema_invalido_da_2(bd, capsys, monkeypatch):
    """Regressão (revisão de conjunto F3, M2): o url das fontes também é
    autorado pelo LLM e entra cru no `href` do render (`publicador.
    _render_fontes`) — um esquema não http(s) (`javascript:`) nunca deve
    sequer entrar na fila. Validado na ORIGEM com o mesmo critério do render
    (`app.publicador._RE_URL_HTTP`), antes de o artigo ser enfileirado."""
    mau = dict(_ARTIGO_OK)
    mau["fontes"] = [{"url": "javascript:alert(1)", "titulo": "Fonte hostil"}]
    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    assert manage.main(["editor", "lint", "--stdin"]) == 2

    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 2
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_enfileirar_artigo_ofensivo_reprova(bd, capsys, monkeypatch):
    mau = dict(_ARTIGO_OK)
    mau["seccoes"] = [{"h2": "Risco",
                       "corpo_md": "O seu registo está ilegal e sem seguro."}]
    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_lint_reprova_meta_description_ofensiva(bd, capsys, monkeypatch):
    """Regressão: `_texto_lint_artigo` lintava só título/secções/URLs das
    fontes — a `meta_description` (publicada em `<meta name="description">` e
    `og:description`, `publicador._HEAD_FMT`) escapava ao lint por completo.
    Um artigo com secções limpas mas `meta_description` ofensiva passava e
    seria publicado tal e qual."""
    mau = dict(_ARTIGO_OK)
    mau["meta_description"] = "O seu registo está ilegal — coima até 40.000€"
    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    assert manage.main(["editor", "lint", "--stdin"]) == 0
    assert _json_out(capsys)["aprovado"] is False

    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_enfileirar_escalar(bd, capsys):
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo",
                      "--escalar", "--motivo", "fonte oficial indisponível"])
    assert rc == 0
    assert _json_out(capsys) == {"escalado": True}
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1


def test_editor_plano_e_estado_read_only(bd, capsys, monkeypatch):
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=100031, nome_alojamento="Casa do Sol", concelho="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda.",
            nif="513029591", email="geral@sul.pt", hash_campos="h",
        ))
    assert manage.main(["editor", "plano"]) == 0
    plano = _json_out(capsys)
    assert plano["top_concelhos"][0]["concelho"] == "Faro"
    assert plano["artigos"] == []

    _stdin(monkeypatch, json.dumps(_ARTIGO_OK, ensure_ascii=False))
    manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    capsys.readouterr()
    assert manage.main(["editor", "estado"]) == 0
    estado = _json_out(capsys)
    assert estado["revisao"] == {"pendente": 1}

    assert manage.main(["editor", "plano"]) == 0
    plano2 = _json_out(capsys)
    assert len(plano2["artigos"]) == 1
    assert "regulamentos-al-porto" in plano2["artigos"][0]["resumo"]


def test_editor_plano_expoe_eventos_regulatorios_frescos(bd, capsys):
    """A spec §3.2 promete sinais de eventos regulatórios frescos no `plano` —
    é o que ativa as páginas-gatilho do EDITOR (e os posts de gatilho do
    COMUNICADOR). Campos reais de `models.EventoRegulatorio` (linha ~210):
    id, fonte, url, titulo, publicado_em, concelhos (JSON), triagem,
    resumo_ia, processado. Nenhum é dado pessoal (documentos institucionais).
    """
    with db.get_session() as s:
        s.add(models.EventoRegulatorio(
            fonte="dre",
            url="https://dre.pt/dr/detalhe/aviso/123-2026",
            titulo="Regulamento municipal de Alojamento Local — Faro",
            publicado_em=date(2026, 7, 14),
            concelhos=["Faro"],
            triagem="relevante",
            resumo_ia="Novo regulamento municipal altera prazos de registo.",
        ))
    assert manage.main(["editor", "plano"]) == 0
    plano = _json_out(capsys)
    assert "top_concelhos" in plano
    assert "artigos" in plano
    assert len(plano["eventos_regulatorios"]) == 1
    evento = plano["eventos_regulatorios"][0]
    assert evento["titulo"] == "Regulamento municipal de Alojamento Local — Faro"
    assert evento["concelhos"] == ["Faro"]
    assert evento["publicado_em"] == "2026-07-14"


# ==========================================================================
#  MAESTRO vê os agentes novos
# ==========================================================================
def test_maestro_saude_inclui_editor_e_comunicador(bd, capsys):
    assert manage.main(["maestro-saude"]) == 0
    dados = _json_out(capsys)
    assert "editor" in dados["executores"]
    assert "comunicador" in dados["executores"]


def test_maestro_retry_aceita_editor_e_comunicador():
    p = manage._construir_parser()
    assert p.parse_args(["maestro-retry", "--agente", "editor",
                         "--backoff", "60"]).agente == "editor"
    assert p.parse_args(["maestro-retry", "--agente", "comunicador",
                         "--backoff", "60"]).agente == "comunicador"


# ==========================================================================
#  maestro-gate-token compõe URL do portão (fase 2)
# ==========================================================================
def _seed_item_pendente(capsys, monkeypatch) -> int:
    _stdin(monkeypatch, _POST_OK)
    assert manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo",
                        "--stdin"]) == 0
    return _json_out(capsys)["revisao_id"]


def test_gate_token_sem_base_url_nao_tem_url(bd, capsys, monkeypatch):
    item_id = _seed_item_pendente(capsys, monkeypatch)
    monkeypatch.setattr(config, "GATE_BASE_URL", "")
    assert manage.main(["maestro-gate-token", "--fila-id", str(item_id)]) == 0
    dados = _json_out(capsys)
    assert dados["token"]
    assert "url" not in dados


def test_gate_token_com_base_url_compoe_url(bd, capsys, monkeypatch):
    item_id = _seed_item_pendente(capsys, monkeypatch)
    monkeypatch.setattr(config, "GATE_BASE_URL", "https://exemplo.ts.net:8443/")
    assert manage.main(["maestro-gate-token", "--fila-id", str(item_id)]) == 0
    dados = _json_out(capsys)
    assert dados["url"] == (
        f"https://exemplo.ts.net:8443/gate/{item_id}?token={dados['token']}"
    )
