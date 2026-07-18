"""Artefactos de execução do enxame — prompts, wrapper e units systemd (Fase E).

Valida, por parsing textual determinista (sem systemd instalado):
  - o template `checkal-agente@.service` é NATIVO (correção RT: os limites de
    cgroup recaem no processo real do `claude -p`, não num `docker exec`) e traz
    TODOS os campos obrigatórios (MemoryMax/MemoryHigh/CPUQuota/TasksMax/
    OOMScoreAdjust/OOMPolicy/RuntimeMaxSec/TimeoutStartSec/ConditionPathExists/
    EnvironmentFile);
  - os timers existem, são PERSISTENT, têm RandomizedDelaySec e estão
    DESCORRELACIONADOS (minutos distintos por agente; SENTINELA fora de fase);
  - existe o timer+service de reset da PAUSA_LLM à meia-noite;
  - o wrapper `correr-agente.sh` faz, por ordem: flock → ping START → PAUSA_LLM
    → gate DPA → teto → `claude -p … --output-format json` com timeout →
    registar_custo → ping final /fail em erro;
  - os 4 prompts operacionais existem em `checkal/prompts/`, em PT-PT, com as
    fronteiras certas (gates de código; quem propõe nunca aprova) e SEM
    referências a subcomandos que não existem no manage.py construído.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]          # raiz do repositório
_SYSTEMD = _RAIZ / "deploy" / "systemd"
_WRAPPER = _RAIZ / "deploy" / "bin" / "correr-agente.sh"
_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"

_TIMERS = {
    "checkal-maestro-digest.timer": "07:50",
    "checkal-maestro-governanca.timer": "11,15,19:50",
    "checkal-angariador.timer": "03:30",
    "checkal-gestor.timer": "07:15",
    "checkal-gestor-suporte.timer": "0/15",
    "checkal-sentinela.timer": "06,12,18,23:40",
    "checkal-reset-pausa-llm.timer": "00:00",
}


# ==========================================================================
#  Template .service — cgroups REAIS (nativo, não docker exec)
# ==========================================================================
def test_template_service_existe_e_e_nativo():
    unit = (_SYSTEMD / "checkal-agente@.service").read_text(encoding="utf-8")
    assert "docker" not in unit.lower()  # correção RT: limites no processo real
    assert "correr-agente.sh %i" in unit


def test_template_service_campos_obrigatorios():
    unit = (_SYSTEMD / "checkal-agente@.service").read_text(encoding="utf-8")
    for campo in (
        "Type=oneshot", "MemoryMax=", "MemoryHigh=", "CPUQuota=", "TasksMax=",
        "OOMScoreAdjust=", "OOMPolicy=kill", "RuntimeMaxSec=900",
        "TimeoutStartSec=", "ConditionPathExists=!/run/checkal/%i.lock",
        "EnvironmentFile=/etc/checkal/agente.env",
    ):
        assert campo in unit, f"falta {campo!r} no checkal-agente@.service"


# ==========================================================================
#  Timers — descorrelacionados, persistentes, com jitter
# ==========================================================================
@pytest.mark.parametrize("nome,oncalendar", sorted(_TIMERS.items()))
def test_timer_existe_com_cadencia_certa(nome, oncalendar):
    timer = (_SYSTEMD / nome).read_text(encoding="utf-8")
    assert oncalendar in timer, f"{nome} sem OnCalendar {oncalendar!r}"
    assert "Persistent=true" in timer
    if nome != "checkal-reset-pausa-llm.timer":
        assert "RandomizedDelaySec=" in timer


def test_timers_de_agentes_descorrelacionados():
    # Nunca dois agentes pesados na mesma janela: os MINUTOS de disparo diferem.
    minutos = {}
    for nome in _TIMERS:
        if nome == "checkal-reset-pausa-llm.timer":
            continue
        texto = (_SYSTEMD / nome).read_text(encoding="utf-8")
        m = re.findall(r"OnCalendar=.*?:(\d+(?:/\d+)?)", texto)
        minutos[nome] = frozenset(m)
    # SENTINELA (:40) fora de fase do MAESTRO (:50) e do resto.
    assert minutos["checkal-sentinela.timer"].isdisjoint(
        minutos["checkal-maestro-digest.timer"]
        | minutos["checkal-maestro-governanca.timer"]
    )
    assert minutos["checkal-angariador.timer"].isdisjoint(
        minutos["checkal-maestro-digest.timer"]
    )


def test_reset_pausa_llm_a_meia_noite():
    service = (_SYSTEMD / "checkal-reset-pausa-llm.service").read_text(encoding="utf-8")
    assert "PAUSA_LLM" in service
    assert "rm -f" in service
    timer = (_SYSTEMD / "checkal-reset-pausa-llm.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 00:00" in timer


def test_timers_apontam_a_instancias_do_template():
    for nome in _TIMERS:
        if nome == "checkal-reset-pausa-llm.timer":
            continue
        timer = (_SYSTEMD / nome).read_text(encoding="utf-8")
        assert re.search(r"Unit=checkal-agente@[a-z-]+\.service", timer), nome


# ==========================================================================
#  Wrapper correr-agente.sh — a ordem canónica do §3.9
# ==========================================================================
def test_wrapper_existe_e_e_executavel():
    assert _WRAPPER.is_file()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_faz_os_passos_na_ordem_canonica():
    corpo = _WRAPPER.read_text(encoding="utf-8")
    posicoes = [
        corpo.index("flock"),
        corpo.index("/start"),            # ping START Healthchecks
        corpo.index("PAUSA_LLM"),
        corpo.index("CHECKAL_ANTHROPIC_DPA_OK"),
        corpo.index("teto_atingido"),
        corpo.index("claude -p"),
        corpo.index("registar_custo"),
        corpo.index("/fail"),
    ]
    assert posicoes == sorted(posicoes), "passos do wrapper fora de ordem"


def test_wrapper_invoca_claude_gated_e_com_guarda_costas():
    corpo = _WRAPPER.read_text(encoding="utf-8")
    assert "--output-format json" in corpo
    assert "--max-turns" in corpo
    assert "timeout" in corpo
    assert "--dangerously-skip-permissions" not in corpo


# ==========================================================================
#  Prompts operacionais — PT-PT, fronteiras certas, subcomandos reais
# ==========================================================================
def test_os_quatro_prompts_existem():
    for nome in ("maestro", "angariador", "gestor", "sentinela"):
        assert (_PROMPTS / f"{nome}.txt").is_file(), f"falta prompts/{nome}.txt"


def test_prompt_maestro_separa_poderes():
    p = (_PROMPTS / "maestro.txt").read_text(encoding="utf-8")
    assert "Quem propõe nunca aprova" in p or "quem propõe nunca aprova" in p
    assert "maestro-gate-token" in p
    assert "CHECKAL_PARECER_RGPD_OK" in p


def test_prompt_angariador_gates_e_subcomandos():
    p = (_PROMPTS / "angariador.txt").read_text(encoding="utf-8")
    assert "pode_enviar_frio_global" in p
    assert "angariador detetar" in p
    assert "na dúvida" in p.lower()


def test_prompt_gestor_usa_os_subcomandos_construidos():
    p = (_PROMPTS / "gestor.txt").read_text(encoding="utf-8")
    for cmd in ("onboarding-tarefas", "relatorio-mensal-compor",
                "dunning-estado", "suporte-triar"):
        assert cmd in p, f"prompt do gestor sem {cmd!r}"
    # Sem referências a subcomandos que NÃO existem no manage.py construído.
    for fantasma in ("gestor snapshot", "gestor enqueue", "gestor listar-fila",
                     "gestor compor-relatorio"):
        assert fantasma not in p, f"prompt do gestor refere {fantasma!r} (não existe)"


def test_prompt_sentinela_read_only_e_verificar():
    p = (_PROMPTS / "sentinela.txt").read_text(encoding="utf-8")
    assert "sentinela verificar" in p
    assert "eventos_agente" in p
    assert "sentinela_achados" not in p   # a tabela canónica é eventos_agente
    assert "só o breaker confirma" in p.lower() or "G4" in p
