#!/usr/bin/env bash
# =========================================================================
# correr-agente.sh <instancia> — o ÚNICO ponto que invoca o Claude CLI no Polaris.
#
# Instâncias: maestro-digest | maestro-governanca | angariador | gestor |
#             gestor-suporte | sentinela | editor | comunicador
#
# Ordem canónica (prompt-mestre §3.9), tudo fail-closed:
#   1. flock anti-reentrância (sai 0 em silêncio se já corre);
#   2. ping START (…/start) ao Healthchecks, se HC_PING_KEY definido;
#   3. flag PAUSA_LLM → aborta com ping /log (teto de custo; determinista continua);
#   4. gate DPA (CHECKAL_ANTHROPIC_DPA_OK) → sem DPA assinado, NENHUM agente LLM
#      arranca (RT-DPA — o portão é código);
#   5. teto diário de custo (swarm.tetos.teto_atingido) → cria PAUSA_LLM e aborta;
#   6. passo determinista da instância (maestro-run / sentinela verificar);
#   7. `claude -p … --output-format json --max-turns N` com `timeout` guarda-costas;
#   8. registar_custo (usage do JSON) na BD;
#   9. ping final: sucesso → slug; falha → slug/fail com o stderr.
#
# Corre DENTRO do cgroup da unit checkal-agente@%i (MemoryMax real no claude -p).
# Nunca salta as permissões do CLI: a segurança vem do allowlist de ferramentas.
# =========================================================================
set -uo pipefail

AGENTE="${1:?uso: correr-agente.sh <instancia>}"
BASE="${CHECKAL_BASE_DIR:-/opt/checkal/checkal}"
PROMPTS="${CHECKAL_PROMPTS_DIR:-${BASE}/prompts}"
RUN_DIR="${CHECKAL_RUN_DIR:-/run/checkal}"
PAUSA="${CHECKAL_PAUSA_LLM_PATH:-${RUN_DIR}/PAUSA_LLM}"
PY="${CHECKAL_PYTHON:-${BASE}/.venv/bin/python}"
CLAUDE_BIN="${CHECKAL_CLAUDE_BIN:-claude}"
MAX_TURNS="${CHECKAL_MAX_TURNS:-40}"
TIMEOUT_S="${CHECKAL_TIMEOUT_S:-840}"          # < TimeoutStartSec=960 da unit
HC_BASE="${HEALTHCHECKS_BASE_URL:-https://hc-ping.com}"
HC_KEY="${HEALTHCHECKS_PING_KEY:-}"

hc_ping() {  # hc_ping <sufixo: '' | start | fail | log> [corpo]
  [ -n "${HC_KEY}" ] || return 0
  local sufixo="${1:-}" corpo="${2:-}"
  local url="${HC_BASE}/${HC_KEY}/agente-${AGENTE}"
  [ -n "${sufixo}" ] && url="${url}/${sufixo}"
  curl -fsS -m 10 --retry 3 ${corpo:+--data-raw "${corpo}"} "${url}" >/dev/null 2>&1 || true
}

# 1) flock anti-reentrância (2.ª camada; a 1.ª é o ConditionPathExists da unit).
mkdir -p "${RUN_DIR}" 2>/dev/null || true
exec 9>"${RUN_DIR}/${AGENTE}.lock" || exit 0
if ! flock -n 9; then
  exit 0
fi
# O lock é nosso: apagar o FICHEIRO em qualquer saída. A unit testa a
# existência do ficheiro (ConditionPathExists=!lock), não o flock — um
# ficheiro deixado para trás bloqueia todas as execuções futuras da instância.
trap 'rm -f "${RUN_DIR}/${AGENTE}.lock"' EXIT
trap 'exit 143' TERM INT   # SIGTERM (systemd stop) não corre o trap EXIT sozinho

# 2) ping START.
hc_ping start

# 3) PAUSA_LLM: teto de custo atingido — os passos LLM param, o determinista continua.
if [ -e "${PAUSA}" ]; then
  hc_ping log "PAUSA_LLM ativa — passagem LLM de ${AGENTE} saltada"
  exit 0
fi

# 4) Gate DPA (RT-DPA): sem CHECKAL_ANTHROPIC_DPA_OK=true, nenhum agente LLM arranca.
DPA="$(printf '%s' "${CHECKAL_ANTHROPIC_DPA_OK:-false}" | tr '[:upper:]' '[:lower:]')"
if [ "${DPA}" != "true" ] && [ "${DPA}" != "1" ] && [ "${DPA}" != "sim" ]; then
  hc_ping log "gate DPA fechado (CHECKAL_ANTHROPIC_DPA_OK=false) — ${AGENTE} não arranca"
  exit 0
fi

# 5) Teto diário de custo — verifica ANTES de gastar; atingido ⇒ pausa + aborta.
if ! "${PY}" - <<PYEOF
import sys
sys.path.insert(0, "${BASE}")
import app.db as db
from app.swarm import tetos
s = db.SessionLocal()
try:
    if tetos.teto_atingido(s):
        tetos.flag_pausa_llm()
        raise SystemExit(3)
finally:
    s.close()
PYEOF
then
  hc_ping log "teto diário de custo LLM atingido — PAUSA_LLM criada; ${AGENTE} não corre"
  exit 0
fi

cd "${BASE}" || { hc_ping fail "BASE ${BASE} inexistente"; exit 1; }

# O agente corre `python manage.py …` (allowlist): garante que `python` resolve
# para o venv do projeto (deps + nome `python` disponível sob systemd).
export PATH="${BASE}/.venv/bin:${PATH}"

# 6) Passo DETERMINISTA por instância (antes do LLM; o LLM nunca faz spawn).
PROMPT_FILE=""
ARG_LLM=""
case "${AGENTE}" in
  maestro-digest)
    "${PY}" manage.py maestro-run --modo digest || { hc_ping fail "maestro-run digest falhou"; exit 1; }
    # Em MODO_TESTE o artefacto do digest (insert na BD + Telegram) está
    # live-gated a jusante (manage.py maestro-digest via obter_escalador):
    # a passagem LLM custaria €€ para um no-op. Salta até o modo live abrir.
    # Truthiness espelha _env_bool do config.py (ausente → teste ativo).
    MT="$(printf '%s' "${CHECKAL_MODO_TESTE:-1}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "${MT}" in
      1|true|sim|yes|on)
        hc_ping log "MODO_TESTE ativo — passagem LLM do digest saltada (artefacto live-gated)"
        exit 0 ;;
    esac
    PROMPT_FILE="${PROMPTS}/maestro.txt"; ARG_LLM="modo=digest" ;;
  maestro-governanca)
    "${PY}" manage.py maestro-run --modo governanca || { hc_ping fail "maestro-run governanca falhou"; exit 1; }
    PROMPT_FILE="${PROMPTS}/maestro.txt"; ARG_LLM="modo=governanca" ;;
  angariador)
    PROMPT_FILE="${PROMPTS}/angariador.txt"; ARG_LLM="passagem=normal" ;;
  gestor)
    PROMPT_FILE="${PROMPTS}/gestor.txt"; ARG_LLM="passagem=diaria" ;;
  gestor-suporte)
    PROMPT_FILE="${PROMPTS}/gestor.txt"; ARG_LLM="passagem=suporte" ;;
  sentinela)
    # O SENTINELA é determinista por omissão: os coletores + achados vivem em
    # `manage.py sentinela verificar`. O passo LLM (adjudicação) só liga com
    # CHECKAL_SENTINELA_LLM=1 — custo mínimo, watchdog sempre vivo.
    "${PY}" manage.py sentinela verificar || { hc_ping fail "sentinela verificar falhou"; exit 1; }
    if [ "${CHECKAL_SENTINELA_LLM:-0}" != "1" ]; then
      hc_ping
      exit 0
    fi
    PROMPT_FILE="${PROMPTS}/sentinela.txt"; ARG_LLM="passagem=adjudicacao" ;;
  editor)
    PROMPT_FILE="${PROMPTS}/editor.txt"; ARG_LLM="passagem=editorial" ;;
  comunicador)
    PROMPT_FILE="${PROMPTS}/comunicador.txt"; ARG_LLM="passagem=diaria" ;;
  *)
    hc_ping fail "instância desconhecida: ${AGENTE}"
    exit 2 ;;
esac

# 7) Invocação LLM single-shot, headless, com timeout guarda-costas.
#    Allowlist por agente: SÓ os subcomandos manage.py do próprio + Read.
#    (Sem WebFetch/WebSearch, sem Write/Edit, sem shell livre, sem SQL cru.)
case "${AGENTE}" in
  maestro-*)
    TOOLS="Read,Bash(python manage.py maestro-metricas),Bash(python manage.py maestro-saude),Bash(python manage.py maestro-fila),Bash(python manage.py maestro-escalacoes),Bash(python manage.py maestro-digest:*),Bash(python manage.py maestro-escalar:*),Bash(python manage.py maestro-retry:*),Bash(python manage.py maestro-gate-token:*)" ;;
  angariador)
    TOOLS="Read,Bash(python manage.py angariador detetar),Bash(python manage.py angariador estado),Bash(python manage.py angariador lint:*),Bash(python manage.py angariador enfileirar:*)" ;;
  gestor|gestor-suporte)
    TOOLS="Read,Bash(python manage.py gestor onboarding-tarefas:*),Bash(python manage.py gestor relatorio-mensal-compor:*),Bash(python manage.py gestor dunning-estado:*),Bash(python manage.py gestor suporte-triar:*)" ;;
  sentinela)
    TOOLS="Read,Bash(python manage.py sentinela verificar)" ;;
  editor)
    TOOLS="Read,Bash(python manage.py editor estado),Bash(python manage.py editor plano),Bash(python manage.py editor lint:*),Bash(python manage.py editor enfileirar:*)" ;;
  comunicador)
    TOOLS="Read,Bash(python manage.py comunicador estado),Bash(python manage.py comunicador lint:*),Bash(python manage.py comunicador enfileirar:*),Bash(python manage.py editor plano)" ;;
esac

SAIDA="$(mktemp "${RUN_DIR}/${AGENTE}.XXXXXX.json")"
ERRO="$(mktemp "${RUN_DIR}/${AGENTE}.XXXXXX.err")"
# NB: este trap SUBSTITUI o anterior (semântica do bash) — tem de repetir o lock.
trap 'rm -f "${SAIDA}" "${ERRO}" "${RUN_DIR}/${AGENTE}.lock"' EXIT

timeout "${TIMEOUT_S}" "${CLAUDE_BIN}" -p "${ARG_LLM}" \
  --append-system-prompt "$(cat "${PROMPT_FILE}")" \
  --allowedTools "${TOOLS}" \
  --disallowedTools "Write Edit WebFetch WebSearch Bash(rm:*) Bash(curl:*) Bash(systemctl:*) Bash(python -c:*)" \
  --output-format json \
  --max-turns "${MAX_TURNS}" \
  >"${SAIDA}" 2>"${ERRO}"
RC=$?

# 8) Regista o consumo de tokens/custo na BD (mesmo em falha parcial, se houver JSON).
"${PY}" - "${AGENTE}" "${SAIDA}" <<'PYEOF' || true
import json, sys
base_agente, caminho = sys.argv[1], sys.argv[2]
try:
    dados = json.loads(open(caminho, encoding="utf-8").read() or "{}")
except Exception:
    raise SystemExit(0)
import app.db as db
from app.swarm import tetos
agente = base_agente.split("-")[0]
s = db.SessionLocal()
try:
    tetos.registar_custo(s, agente, dados)
    tetos.verificar_e_pausar(s)
    s.commit()
finally:
    s.close()
PYEOF

# 9) Ping final: sucesso ou /fail com o stderr.
if [ ${RC} -eq 0 ]; then
  hc_ping
else
  hc_ping fail "$(tail -c 1500 "${ERRO}" 2>/dev/null || echo "claude -p saiu com ${RC}")"
fi
exit ${RC}
