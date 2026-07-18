"""Tetos de custo LLM + pausa + escalação — app.swarm.tetos (Fase C).

Regras provadas:
  - `registar_custo` parseia o `usage` do `claude -p --output-format json`,
    estima o custo pela tabela de preços (Haiku/Sonnet) e grava em `custo_llm`
    em CÊNTIMOS, arredondado POR EXCESSO (o teto dispara mais cedo — direção segura);
  - `teto_atingido` soma o dia vs `config.TETO_DIARIO_EUR`;
  - `verificar_e_pausar` cria a flag-ficheiro PAUSA_LLM; `pausa_llm_ativa` lê-a;
    o reset (`limpar_pausa_llm`) remove-a;
  - os tetos NUNCA tocam os gates de segurança (parecer/modo teste/SMTP) —
    pausar LLM ≠ abrir/fechar compliance;
  - `escalar` escreve em `escalacoes` + `eventos_agente`;
  - novos gates de config: `CHECKAL_ANTHROPIC_DPA_OK` default False bloqueia o
    arranque LLM de qualquer agente (`agente_llm_pode_arrancar`).

Isolamento: BD SQLite temporária; PAUSA_LLM em tmp_path. Escritos ANTES (TDD).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models_swarm as ms
from app.swarm import tetos


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_tetos_test.db'}"
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


_USAGE_SONNET = {
    "model": "claude-sonnet-5",
    "usage": {"input_tokens": 12000, "output_tokens": 3000},
}


# ==========================================================================
#  registar_custo — parse + preço + cêntimos por excesso
# ==========================================================================
def test_registar_custo_sonnet_arredonda_por_excesso(bd):
    # 12k in × 3€/M + 3k out × 15€/M = 0,081 € ⇒ 9 cêntimos (ceil).
    with db.get_session() as s:
        linha = tetos.registar_custo(s, "maestro", _USAGE_SONNET, dia=date(2026, 7, 18))
        assert linha.custo_eur_cent == 9
        assert linha.input_tokens == 12000
        assert linha.output_tokens == 3000

    with db.get_session() as s:
        assert s.query(ms.CustoLlm).count() == 1


def test_registar_custo_haiku_mais_barato(bd):
    usage = {"model": "claude-haiku-4-5", "usage": {"input_tokens": 100000, "output_tokens": 0}}
    with db.get_session() as s:
        linha = tetos.registar_custo(s, "angariador", usage, dia=date(2026, 7, 18))
        # 100k × 1€/M = 0,10 € ⇒ 10 cêntimos exatos.
        assert linha.custo_eur_cent == 10


def test_registar_custo_sem_modelo_assume_o_mais_caro(bd):
    usage = {"usage": {"input_tokens": 1000, "output_tokens": 0}}
    with db.get_session() as s:
        linha = tetos.registar_custo(s, "gestor", usage, dia=date(2026, 7, 18))
        # sem modelo ⇒ preços de Sonnet (conservador): 0,003 € ⇒ ceil 1 cêntimo.
        assert linha.custo_eur_cent == 1


def test_registar_custo_usage_achatado_tambem_serve(bd):
    with db.get_session() as s:
        linha = tetos.registar_custo(
            s, "sentinela", {"input_tokens": 500, "output_tokens": 100},
            dia=date(2026, 7, 18),
        )
        assert linha.input_tokens == 500


# ==========================================================================
#  teto_atingido + pausa
# ==========================================================================
def test_teto_atingido_soma_o_dia(bd, monkeypatch):
    dia = date(2026, 7, 18)
    with db.get_session() as s:
        tetos.registar_custo(s, "maestro", _USAGE_SONNET, dia=dia)   # 9 cêntimos

    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 0.05)
    with db.get_session() as s:
        assert tetos.teto_atingido(s, dia) is True

    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 5.0)
    with db.get_session() as s:
        assert tetos.teto_atingido(s, dia) is False


def test_verificar_e_pausar_cria_flag(bd, monkeypatch):
    dia = date(2026, 7, 18)
    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 0.01)
    with db.get_session() as s:
        tetos.registar_custo(s, "maestro", _USAGE_SONNET, dia=dia)
        assert tetos.verificar_e_pausar(s, dia) is True
    assert tetos.pausa_llm_ativa() is True

    tetos.limpar_pausa_llm()
    assert tetos.pausa_llm_ativa() is False


def test_pausa_sem_teto_nao_dispara(bd, monkeypatch):
    dia = date(2026, 7, 18)
    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 100.0)
    with db.get_session() as s:
        tetos.registar_custo(s, "maestro", _USAGE_SONNET, dia=dia)
        assert tetos.verificar_e_pausar(s, dia) is False
    assert tetos.pausa_llm_ativa() is False


def test_tetos_nunca_tocam_gates_de_seguranca(bd, monkeypatch):
    dia = date(2026, 7, 18)
    monkeypatch.setattr(config, "TETO_DIARIO_EUR", 0.01)
    antes = (
        config.CHECKAL_PARECER_RGPD_OK,
        config.CHECKAL_MODO_TESTE,
        config.pode_enviar_frio_global(),
    )
    with db.get_session() as s:
        tetos.registar_custo(s, "maestro", _USAGE_SONNET, dia=dia)
        tetos.verificar_e_pausar(s, dia)
    depois = (
        config.CHECKAL_PARECER_RGPD_OK,
        config.CHECKAL_MODO_TESTE,
        config.pode_enviar_frio_global(),
    )
    assert antes == depois == (False, True, False)


# ==========================================================================
#  escalar — escalacoes + eventos_agente
# ==========================================================================
def test_escalar_escreve_escalacao_e_evento(bd):
    with db.get_session() as s:
        tetos.escalar(
            s, severidade="critica", agente="maestro",
            mensagem="teto diário de LLM atingido — PAUSA_LLM criada",
        )

    with db.get_session() as s:
        e = s.query(ms.Escalacao).one()
        assert e.severidade == "critica"
        ev = s.query(ms.EventoAgente).one()
        assert ev.tipo == "escalada"
        assert ev.agente == "maestro"


# ==========================================================================
#  Gates novos de config (RT-DPA)
# ==========================================================================
def test_dpa_gate_default_fechado():
    assert config.CHECKAL_ANTHROPIC_DPA_OK is False
    assert config.agente_llm_pode_arrancar() is False


def test_dpa_gate_aberto_liberta_arranque(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_ANTHROPIC_DPA_OK", True)
    assert config.agente_llm_pode_arrancar() is True


def test_teto_diario_default_5_eur():
    assert config.TETO_DIARIO_EUR == 5.0
