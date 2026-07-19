#!/usr/bin/env bash
# Instala e ATIVA o CheckAL no Polaris (correr com sudo). Tudo o que é real vive
# no projeto; isto só copia as units (ponteiros) para /etc/systemd/system.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
cp "${AQUI}/units/"* /etc/systemd/system/
systemctl daemon-reload

# Crons deterministas do backbone (LIVE-GATED: sem chaves nada envia/cobra):
systemctl enable --now checkal-cron-varrimento.timer checkal-cron-dre.timer \
  checkal-cron-dunning.timer checkal-cron-backup.timer checkal-cron-publicador.timer

# Agentes (fase 1 do rollout):
systemctl enable --now checkal-sentinela.timer checkal-maestro-digest.timer \
  checkal-maestro-governanca.timer checkal-angariador.timer checkal-gestor.timer \
  checkal-editor.timer checkal-comunicador.timer \
  checkal-reset-pausa-llm.timer

# DESLIGADOS de propósito (ativar quando os pré-requisitos existirem):
#   checkal-cron-suporte.timer / checkal-gestor-suporte.timer → precisam de IMAP (apoio@)
#   checkal-cron-token.timer                                  → precisa das credenciais TOConline

# Portão 1-clique (fase 2) — só local (127.0.0.1:8600); exposição tailscale é manual (HANDOFF fase 2)
systemctl enable --now checkal-web.service

echo "OK — timers ativos:"
systemctl list-timers 'checkal*' --no-pager
