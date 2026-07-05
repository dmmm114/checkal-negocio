"""Testes FDS 5 da extensão *aditiva* de `app.config` (SPEC-FDS5.md §config).

Verifica que as novas constantes de fiabilidade — Healthchecks (dead-man
switch), IMAP (suporte apoio@), Telegram (escalação ao dono) e backups
(pg_dump/retenção) — existem com defaults **seguros/vazios**. Disciplina
LIVE-GATED: sem segredos, os predicados `*_ativo()` devolvem `False`, logo
nenhum seam (rede/IMAP/subprocess) toca nada. Não corre rede/IMAP/subprocess.

Escrito ANTES da implementação (TDD). Isolamento total: só lê constantes.
"""
from __future__ import annotations

from pathlib import Path

import app.config as config


# --------------------------------------------------------------------------
#  Healthchecks.io — dead-man switch
# --------------------------------------------------------------------------
def test_healthchecks_defaults():
    assert config.HEALTHCHECKS_BASE_URL == "https://hc-ping.com"  # endpoint público
    assert config.HEALTHCHECKS_PING_KEY == ""                     # segredo vazio por omissão
    assert isinstance(config.HEALTHCHECKS_TIMEOUT_S, float)
    assert config.HEALTHCHECKS_TIMEOUT_S > 0


def test_healthchecks_gate_desligado_por_omissao():
    # Sem ping key ⇒ o dead-man switch não pinga (live-gate).
    assert config.healthchecks_ativo() is False


# --------------------------------------------------------------------------
#  IMAP — suporte de 1.ª linha (apoio@)
# --------------------------------------------------------------------------
def test_imap_defaults():
    assert config.IMAP_HOST == ""
    assert config.IMAP_USER == ""
    assert config.IMAP_PASSWORD == ""
    assert config.IMAP_MAILBOX == "INBOX"
    assert config.IMAP_PORT == 993 and isinstance(config.IMAP_PORT, int)
    assert config.IMAP_SSL is True


def test_imap_gate_desligado_por_omissao():
    # Sem host/user/password ⇒ o cron de suporte não abre ligação IMAP.
    assert config.imap_ativo() is False


# --------------------------------------------------------------------------
#  Telegram — escalação ao dono
# --------------------------------------------------------------------------
def test_telegram_defaults():
    assert config.TELEGRAM_API_BASE == "https://api.telegram.org"  # endpoint público
    assert config.TELEGRAM_BOT_TOKEN == ""                         # segredo vazio
    assert config.TELEGRAM_CHAT_ID == ""                           # segredo/infra vazio
    assert isinstance(config.TELEGRAM_TIMEOUT_S, float)
    assert config.TELEGRAM_TIMEOUT_S > 0


def test_telegram_gate_desligado_por_omissao():
    # Sem token+chat_id ⇒ nenhuma mensagem de escalação sai (live-gate).
    assert config.telegram_ativo() is False


# --------------------------------------------------------------------------
#  Backups — pg_dump + retenção
# --------------------------------------------------------------------------
def test_backup_defaults():
    assert isinstance(config.BACKUP_DIR, Path)
    assert config.BACKUP_DB_URL == ""                       # DSN de origem vazio por omissão
    assert config.BACKUP_PGDUMP_BIN == "pg_dump"
    assert config.BACKUP_RETENCAO_DIAS == 30 and isinstance(config.BACKUP_RETENCAO_DIAS, int)


def test_backup_gate_desligado_por_omissao():
    # Sem DSN de origem ⇒ o cron de backup não corre subprocess real (live-gate).
    assert config.backups_ativo() is False


# --------------------------------------------------------------------------
#  Regressão — o aditivo FDS 5 não mexe nas constantes de sprints anteriores
# --------------------------------------------------------------------------
def test_fds5_preserva_constantes_anteriores():
    assert config.BREAKER_PCT_CONCELHO == 0.03     # usada pelo breaker deste sprint
    assert config.REGRA_N_VARRIMENTOS == 2         # guarda de sequência (FDS 1/3)
    assert config.CHECKAL_MODO_TESTE is True       # live-gate global permanece ligado
