"""Testes FDS 6 da extensão *aditiva* de `app.config` (SPEC-FDS6.md §config).

O coração deste sprint é um **portão bloqueante**: o canal de email frio é
PROIBIDO até o dono ter o parecer favorável do jurista RGPD (CLAUDE.md /
LEGAL.md §1). Isto é código, não disciplina — logo tem de estar coberto por
teste. Verifica-se aqui que:

  - `CHECKAL_PARECER_RGPD_OK` existe e nasce **False** (o PORTÃO);
  - o SMTP dedicado do canal frio (`COLD_SMTP_*`, domínio irmão `getcheckal.com`)
    tem defaults **seguros/vazios** ⇒ LIVE-GATED (`cold_smtp_ativo()` False);
  - a fronteira é DURA: `COLD_FROM` sai de `getcheckal.com`, NUNCA de `checkal.pt`;
  - `pode_enviar_frio_global()` é **triplamente gated** (parecer OK E modo teste
    OFF E SMTP configurado) e devolve False por omissão — nenhum email frio sai;
  - a política de campanha (`CAMPANHA_JANELA_H` = 72h, `CAMPANHA_CAP_DIARIO`)
    existe com defaults conservadores.

Escrito ANTES da implementação (TDD). Isolamento total: só lê constantes e
chama predicados puros; não toca rede/SMTP.
"""
from __future__ import annotations

import app.config as config


# --------------------------------------------------------------------------
#  🚦 O PORTÃO — parecer RGPD (default False, inviolável)
# --------------------------------------------------------------------------
def test_portao_parecer_rgpd_existe_e_e_falso_por_omissao():
    # O portão bloqueante do sprint: sem parecer, nada de cold.
    assert hasattr(config, "CHECKAL_PARECER_RGPD_OK")
    assert config.CHECKAL_PARECER_RGPD_OK is False


# --------------------------------------------------------------------------
#  SMTP dedicado do canal frio (getcheckal.com) — segredos vazios, live-gate
# --------------------------------------------------------------------------
def test_cold_smtp_defaults_vazios():
    assert config.COLD_SMTP_HOST == ""          # host (segredo/infra) vazio
    assert config.COLD_SMTP_USER == ""          # utilizador (segredo) vazio
    assert config.COLD_SMTP_PASS == ""          # password (segredo) vazio
    assert isinstance(config.COLD_SMTP_PORT, int) and config.COLD_SMTP_PORT > 0


def test_cold_smtp_gate_desligado_por_omissao():
    # Sem host/user/password ⇒ o envio frio não abre ligação SMTP (live-gate).
    assert config.cold_smtp_ativo() is False


def test_cold_from_sai_de_getcheckal_e_nunca_de_checkal_pt():
    # Fronteira DURA (SPEC-RESEND §0): o cold usa o domínio irmão, jamais o
    # domínio transacional — partilhar reputação suspenderia a conta Resend.
    assert "getcheckal.com" in config.COLD_FROM
    assert "checkal.pt" not in config.COLD_FROM
    # E é um remetente distinto do transacional (EMAIL_FROM = checkal.pt).
    assert config.COLD_FROM != config.EMAIL_FROM


# --------------------------------------------------------------------------
#  Política de campanha — janela 72h + throttle/warm-up diário
# --------------------------------------------------------------------------
def test_politica_campanha_defaults():
    assert config.CAMPANHA_JANELA_H == 72 and isinstance(config.CAMPANHA_JANELA_H, int)
    assert isinstance(config.CAMPANHA_CAP_DIARIO, int) and config.CAMPANHA_CAP_DIARIO > 0
    # Warm-up: teto humano (dezenas/dia, não centenas — SPEC-RESEND §7.3).
    assert config.CAMPANHA_CAP_DIARIO <= 100


# --------------------------------------------------------------------------
#  🚦 O TRIPLO GATE global — o único caminho para um email frio sair
# --------------------------------------------------------------------------
def test_pode_enviar_frio_global_falso_por_omissao():
    # Estado de fábrica: parecer OFF + modo de teste ON + sem SMTP ⇒ False.
    assert config.pode_enviar_frio_global() is False


def test_pode_enviar_frio_global_exige_os_tres_gates(monkeypatch):
    # Todos os segredos SMTP presentes, mas o PORTÃO (parecer) fechado ⇒ False.
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "cold@getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "segredo")
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", False)
    assert config.pode_enviar_frio_global() is False

    # Parecer ON mas ainda em modo de teste ⇒ False (não se dispara em sandbox).
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    assert config.pode_enviar_frio_global() is False

    # Parecer ON + modo teste OFF, mas SMTP por configurar ⇒ False (live-gate).
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "")
    assert config.pode_enviar_frio_global() is False

    # Só com os TRÊS gates alinhados é que o canal frio abre.
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    assert config.cold_smtp_ativo() is True
    assert config.pode_enviar_frio_global() is True


# --------------------------------------------------------------------------
#  Regressão — o aditivo FDS 6 não mexe no que veio antes
# --------------------------------------------------------------------------
def test_fds6_preserva_constantes_anteriores():
    assert config.CHECKAL_MODO_TESTE is True       # live-gate global permanece ligado
    assert config.EMAIL_FROM == "CheckAL <alertas@checkal.pt>"  # canal A intacto
    assert config.CADENCIA_NACIONAL_DIAS == 3      # varrimento nacional (FDS 1)
    assert config.REGRA_N_VARRIMENTOS == 2         # guarda de sequência (FDS 1/3)
