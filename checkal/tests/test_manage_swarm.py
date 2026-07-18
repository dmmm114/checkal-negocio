"""Subcomandos `manage.py` do MAESTRO + dispatch (Fase D do prompt-mestre).

Cobre:
  - retrocompatibilidade: os jobs de arg único (`varrimento|dre|dunning|suporte|
    backup|token`) continuam a despachar como antes;
  - leituras (`maestro-metricas|saude|fila|escalacoes`) devolvem JSON agregado e
    abrem a BD em modo READ-ONLY (escrita por essa sessão rebenta);
  - escritas estreitas (`maestro-digest|escalar|retry|gate-token`) só tocam
    tabelas de governação;
  - `maestro-run` é o runner determinista: encadeia executores EM SEQUÊNCIA,
    regista em `agente_execucoes`, e SÓ invoca o passo LLM com o gate DPA aberto,
    sem PAUSA_LLM e sem teto atingido (senão: skip com motivo).

Isolamento: BD SQLite temporária; SEM rede; nada envia (obter_escalador → None
sob CHECKAL_MODO_TESTE). Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
import manage


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_manage_test.db'}"
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


def _agora():
    return datetime.now(timezone.utc)


# ==========================================================================
#  Dispatch — retrocompatibilidade + subcomandos
# ==========================================================================
def test_jobs_legados_continuam_a_despachar(monkeypatch):
    chamadas = []
    import app.crons as crons

    monkeypatch.setattr(crons, "cron_dre", lambda: chamadas.append("dre"))
    assert manage.main(["dre"]) == 0
    assert chamadas == ["dre"]


def test_comando_desconhecido_devolve_2():
    assert manage.main(["inexistente"]) == 2


def test_sem_argumentos_devolve_2():
    assert manage.main([]) == 2


# ==========================================================================
#  Leituras do MAESTRO — JSON agregado, sessão read-only
# ==========================================================================
def test_sessao_leitura_recusa_escrita(bd):
    s = manage._sessao_leitura()
    try:
        s.add(ms.Escalacao(agente="x", severidade="alta", mensagem="m", criado_em=_agora()))
        with pytest.raises(OperationalError):
            s.flush()
    finally:
        s.rollback()
        s.close()


def test_maestro_metricas_devolve_json_agregado(bd, capsys):
    with db.get_session() as s:
        s.add(models.Cliente(email="a@b.pt", plano="anual", estado="ativo"))
        s.add(models.Cliente(email="c@d.pt", plano="anual", estado="em_dunning"))
        s.add(models.Lead(email="l@e.pt", estado="confirmado", consent_alertas=True))

    assert manage.main(["maestro-metricas"]) == 0
    dados = _json_out(capsys)
    assert dados["clientes"]["ativos"] == 1
    assert dados["clientes"]["em_dunning"] == 1
    assert dados["leads"]["confirmado"] == 1
    assert "mrr_cents" in dados
    # Dados AGREGADOS: nenhum campo pessoal no output.
    assert "a@b.pt" not in json.dumps(dados)


def test_maestro_saude_inclui_gates_como_facto(bd, capsys):
    assert manage.main(["maestro-saude"]) == 0
    dados = _json_out(capsys)
    assert dados["gates"]["parecer_rgpd_ok"] is False
    assert dados["gates"]["modo_teste"] is True
    assert dados["gates"]["dpa_ok"] is False
    assert dados["gates"]["pode_enviar_frio"] is False
    assert "varrimento" in dados


def test_maestro_fila_lista_pendentes(bd, capsys):
    from app.swarm import fila
    from tests.test_swarm_fila import _peca_cold_ok

    with db.get_session() as s:
        fila.enfileirar(
            s, tipo="cold_email", risco="alto", agente_origem="angariador",
            peca=_peca_cold_ok(), resumo="draft frio Porto",
        )

    assert manage.main(["maestro-fila"]) == 0
    dados = _json_out(capsys)
    assert len(dados["pendentes"]) == 1
    item = dados["pendentes"][0]
    assert item["tipo"] == "cold_email"
    assert item["camada_risco"] == 4
    assert item["linter_ok"] is True


def test_maestro_escalacoes_lista_abertas(bd, capsys):
    with db.get_session() as s:
        s.add(ms.Escalacao(agente="gestor", severidade="alta",
                           mensagem="cron_dunning não correu", criado_em=_agora()))

    assert manage.main(["maestro-escalacoes"]) == 0
    dados = _json_out(capsys)
    assert len(dados["escalacoes"]) == 1
    assert dados["escalacoes"][0]["severidade"] == "alta"


# ==========================================================================
#  Escritas estreitas do MAESTRO
# ==========================================================================
def test_maestro_digest_persiste_e_nao_envia_sob_gate(bd, tmp_path, capsys):
    f = tmp_path / "digest.json"
    f.write_text(json.dumps({"corpo_md": "# Digest de teste", "metricas_json": {"mrr": 0}}),
                 encoding="utf-8")
    assert manage.main(["maestro-digest", "--ficheiro", str(f)]) == 0
    dados = _json_out(capsys)
    assert dados["enviado"] is False  # obter_escalador → None sob CHECKAL_MODO_TESTE

    with db.get_session() as s:
        d = s.query(ms.Digest).one()
        assert d.corpo_md == "# Digest de teste"
        assert d.enviado_em is None


def test_maestro_escalar_escreve_escalacao(bd, capsys):
    assert manage.main(["maestro-escalar", "--sev", "critica", "--msg", "varrimento parado"]) == 0
    with db.get_session() as s:
        e = s.query(ms.Escalacao).one()
        assert e.agente == "maestro"
        assert e.severidade == "critica"


def test_maestro_retry_anota_flag_para_o_runner(bd, capsys):
    with db.get_session() as s:
        s.add(ms.AgenteExecucao(agente="angariador", iniciado_em=_agora(),
                                estado="falhou", exit_code=1))

    assert manage.main(["maestro-retry", "--agente", "angariador", "--backoff", "120"]) == 0
    with db.get_session() as s:
        e = s.query(ms.AgenteExecucao).one()
        assert e.retry_pedido is True
        assert e.backoff_s == 120


def test_maestro_gate_token_gera_token_sem_aprovar(bd, capsys):
    from app.swarm import fila
    from tests.test_swarm_fila import _peca_cold_ok

    with db.get_session() as s:
        item = fila.enfileirar(
            s, tipo="cold_email", risco="alto", agente_origem="angariador",
            peca=_peca_cold_ok(),
        )
        s.flush()
        item_id = item.id

    assert manage.main(["maestro-gate-token", "--fila-id", str(item_id)]) == 0
    dados = _json_out(capsys)
    assert dados["token"]
    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "pendente"  # NÃO aprovou


# ==========================================================================
#  maestro-run — runner determinista (sequencial; LLM gated)
# ==========================================================================
def test_maestro_run_llm_bloqueado_pelo_dpa_por_defeito(bd):
    resultado = manage.maestro_run("governanca")
    assert resultado["llm_invocado"] is False
    assert resultado["motivo_llm_skip"] == "dpa_fechado"
    with db.get_session() as s:
        assert s.query(ms.AgenteExecucao).count() >= 0  # nada rebentou


def test_maestro_run_reexecuta_executores_com_retry_em_sequencia(bd, monkeypatch):
    with db.get_session() as s:
        s.add(ms.AgenteExecucao(agente="angariador", iniciado_em=_agora(),
                                estado="falhou", retry_pedido=True, backoff_s=0))
        s.add(ms.AgenteExecucao(agente="sentinela", iniciado_em=_agora(),
                                estado="falhou", retry_pedido=True, backoff_s=0))

    lancados: list[str] = []
    resultado = manage.maestro_run(
        "governanca", lancador=lambda agente: (lancados.append(agente), 0)[1]
    )
    assert lancados == ["angariador", "sentinela"]  # sequência determinística
    assert resultado["executores_corridos"] == ["angariador", "sentinela"]

    with db.get_session() as s:
        novos = (
            s.query(ms.AgenteExecucao)
            .filter(ms.AgenteExecucao.estado == "ok").all()
        )
        assert {e.agente for e in novos} == {"angariador", "sentinela"}
        antigos = s.query(ms.AgenteExecucao).filter(ms.AgenteExecucao.retry_pedido.is_(True)).all()
        assert antigos == []  # flag consumida


def test_maestro_run_com_dpa_aberto_invoca_llm_e_regista_custo(bd, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_ANTHROPIC_DPA_OK", True)
    usage = {"model": "claude-sonnet-5", "usage": {"input_tokens": 1000, "output_tokens": 100}}
    resultado = manage.maestro_run("digest", lancador_llm=lambda modo: usage)
    assert resultado["llm_invocado"] is True
    with db.get_session() as s:
        c = s.query(ms.CustoLlm).one()
        assert c.agente == "maestro"


def test_maestro_run_respeita_pausa_llm(bd, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_ANTHROPIC_DPA_OK", True)
    from app.swarm import tetos

    tetos.flag_pausa_llm()
    resultado = manage.maestro_run("digest", lancador_llm=lambda modo: {})
    assert resultado["llm_invocado"] is False
    assert resultado["motivo_llm_skip"] == "pausa_llm"


def test_maestro_run_teto_atingido_pausa_e_escala(bd, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_ANTHROPIC_DPA_OK", True)
    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 0.001)
    from app.swarm import tetos

    with db.get_session() as s:
        tetos.registar_custo(
            s, "maestro",
            {"model": "claude-sonnet-5", "usage": {"input_tokens": 100000, "output_tokens": 0}},
        )

    resultado = manage.maestro_run("digest", lancador_llm=lambda modo: {})
    assert resultado["llm_invocado"] is False
    assert resultado["motivo_llm_skip"] == "teto_diario"
    assert tetos.pausa_llm_ativa() is True
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1
