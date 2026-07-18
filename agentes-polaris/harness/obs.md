=== OBSERVABILIDADE, EXECUÇÃO HEADLESS E TETOS DE CUSTO — CONCRETO PARA POLARIS ===

Premissa dura (Polaris, Ubuntu home server, Tailscale): já houve OOM kill por sessões Claude Code persistentes. Regra inviolável: NENHUM processo persistente. Cada agente é uma invocação `claude -p` single-shot, headless, lançada por systemd, que faz o trabalho, escreve na BD/fila de revisão e SAI. Toda a observabilidade assenta em artefactos deixados em disco/SQLite + pings HTTP — nunca num daemon a correr.

--- (a) PADRÃO systemd UNIVERSAL PARA AGENTES ---

Cada agente = par `.service` (Type=oneshot) + `.timer`. Template `checkal-agente@.service` parametrizado pelo nome do agente:

```ini
# /etc/systemd/system/checkal-agente@.service
[Unit]
Description=CheckAL agente %i (single-shot)
After=network-online.target
Wants=network-online.target
# não re-entrar se a passagem anterior ainda corre
ConditionPathExists=!/run/checkal/%i.lock

[Service]
Type=oneshot
User=checkal
WorkingDirectory=/opt/checkal
EnvironmentFile=/etc/checkal/agente.env          # segredos (chmod 600, root:checkal)
# --- TETOS DE RAM/CPU: o que resolve o OOM ---
MemoryMax=1200M                                   # HARD: cgroup mata o processo, não o kernel às cegas
MemoryHigh=900M                                   # soft: throttle antes do kill
CPUQuota=60%
TasksMax=64
OOMScoreAdjust=800                                # se houver pressão global, o kernel escolhe ESTE antes do resto
OOMPolicy=kill
# --- TEMPO: nada fica pendurado ---
RuntimeMaxSec=900                                 # 15 min máximo por passagem; excedeu => SIGTERM
TimeoutStartSec=960
# --- lock anti-reentrância + healthcheck no mesmo wrapper ---
ExecStartPre=/usr/bin/install -d -o checkal /run/checkal
ExecStart=/opt/checkal/bin/correr-agente.sh %i
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=6
```

```ini
# /etc/systemd/system/checkal-angariador.timer  (exemplo; um .timer por agente)
[Unit]
Description=Timer do ANGARIADOR
[Timer]
OnCalendar=*-*-* 08,14,20:00      # 3 passagens/dia, event-driven-ish
RandomizedDelaySec=300            # de-sincroniza dos outros agentes (evita picos de RAM simultâneos)
Persistent=true                   # apanha passagens perdidas se o Polaris esteve off
AccuracySec=60
[Install]
WantedBy=timers.target
```

Cadências por agente (timers DESCORRELACIONADOS — nunca dois agentes pesados na mesma janela):
- MAESTRO: `08,13,19:30` (digest às 19:30).
- ANGARIADOR: `08,14,20:00`.
- GESTOR-DE-CLIENTE: dunning/relatório diário `07:15`; suporte `*:0/15` (15 min) mas leve.
- SENTINELA-SERVIÇO: `*-*-* 06,12,18,23:40` — TIMER PRÓPRIO, deliberadamente fora de fase do Maestro (deteção descorrelacionada; tem de conseguir apanhar o Maestro morto).

O wrapper `correr-agente.sh %i` faz, por esta ordem:
1. `flock -n /run/checkal/%i.lock` (segunda camada anti-reentrância; se falhar, sai 0 silenciosamente).
2. Ping de START ao Healthchecks.io do job: `curl -fsS -m10 --retry 3 $HC_URL/$AGENTE/start`.
3. Verifica os interruptores globais de PAUSA (ver secção c): se `/run/checkal/PAUSA_LLM` existe e o job usa LLM, aborta com ping `/log` (não `/fail`) e sai.
4. Corre `claude -p "$(cat /opt/checkal/prompts/$AGENTE.md)" --output-format json --max-turns N ...` com `timeout` de guarda-costas.
5. Regista consumo de tokens/custo (secção c) na BD.
6. Ping final: sucesso → `$HC_URL/$AGENTE` (código 0); falha/exceção → `$HC_URL/$AGENTE/fail` com o corpo do stderr (`--data-raw`).

Princípio: o dead-man switch por job (Healthchecks.io) é o que deteta "o cron NÃO correu / correu e rebentou". É determinista e vive fora do Polaris (se o Polaris morre inteiro, o Healthchecks dispara na mesma por ausência de ping).

--- (b) FILA DE TRABALHO EM SQLite (drain on-demand) ---

Complemento aos timers para trabalho event-driven e para desacoplar "detetar" de "executar". Uma única BD `/opt/checkal/var/fila.db` (WAL mode; a app já usa SQLite/Postgres — esta fila é operacional, separada do domínio):

```sql
CREATE TABLE trabalho (
  id            INTEGER PRIMARY KEY,
  agente        TEXT NOT NULL,              -- angariador|gestor|sentinela|maestro
  tipo          TEXT NOT NULL,              -- ex: campanha_gatilho, onboarding_tarefa, suporte_email
  payload       TEXT,                       -- JSON mínimo (IDs, nunca dados pessoais em claro)
  estado        TEXT NOT NULL DEFAULT 'pendente', -- pendente|a_correr|feito|falhado|morto
  tentativas    INTEGER NOT NULL DEFAULT 0,
  max_tentativas INTEGER NOT NULL DEFAULT 5,
  nao_antes_de  TEXT,                       -- ISO; backoff exponencial
  lease_ate     TEXT,                       -- lease/visibilidade; expira => re-elegível
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);
CREATE INDEX ix_fila_elegivel ON trabalho(agente, estado, nao_antes_de);
```

Padrão de drain (o timer chama `drain-fila.sh <agente>`, single-shot):
- `BEGIN IMMEDIATE` → seleciona N itens `estado='pendente' AND (nao_antes_de IS NULL OR nao_antes_de<=now) AND (lease_ate IS NULL OR lease_ate<now)` → marca `a_correr` + `lease_ate=now+15min` → COMMIT. (Lease evita dupla-execução se duas passagens se sobrepuserem; a idempotência de domínio — marcadores em `alertas`, `stripe_session_id` — é a rede de segurança final.)
- Processa cada item numa transação; sucesso → `feito`; exceção → `tentativas+1`, backoff `nao_antes_de=now+min(2^tentativas·60s, 6h)`; `tentativas>=max` → `morto` + escala ao Maestro.
- Cap por passagem alinhado com os caps de rate (secção c): drena no máximo `CAMPANHA_CAP_DIARIO` itens de envio por dia.

Timers e fila coexistem: timers dão cadência garantida e apanham passagens perdidas (`Persistent=true`); a fila dá reação a eventos e retry com backoff sem processo persistente. O drain é sempre single-shot.

--- (c) TETOS DE CUSTO E CAPS DE RATE ---

Custo LLM (Claude CLI → API Anthropic, inferência paga):
- Cada passagem escreve em `custo_llm(dia, agente, input_tokens, output_tokens, custo_eur, ts)` a partir do JSON de `--output-format json` (campo usage). Custo estimado localmente pela tabela de preços do modelo (Haiku triagem / Sonnet redação).
- `TETO_DIARIO_EUR` (config, ex. 5€/dia agregado; sub-tetos por agente). Antes de cada chamada LLM o wrapper soma o gasto do dia corrente: se `>= TETO_DIARIO_EUR` → cria `/run/checkal/PAUSA_LLM` (flag-ficheiro), NÃO chama o modelo, e pagina o dono. A flag é limpa à meia-noite por um timer de reset (ou manualmente pelo dono). Os crons DETERMINISTAS (varrimento, diff, faturação, dunning determinista) continuam a correr — só os passos LLM pausam.
- Sub-teto de "circuit breaker" por passagem: `--max-turns` + `RuntimeMaxSec=900` limitam o gasto de uma única invocação descontrolada.

Caps de rate (envio) — reforçados por CÓDIGO, não por disciplina (já existem no backbone):
- `CAMPANHA_CAP_DIARIO=20` cold/dia/caixa (warm-up getcheckal.com); excedente fica em fila com `razao=RAZAO_CAP`.
- Cap de nurture/transacional análogo para checkal.pt (Resend), separado do cold (fronteira dura de reputação).
- O Maestro aplica os tetos como CONFIG (lê `custo_llm`, `campanhas`), nunca os relitiga em runtime.

Regra dura: os tetos de custo pausam trabalho LLM e paginam; NUNCA tocam nos gates de segurança (`pode_enviar_frio_global`, `CHECKAL_MODO_TESTE`, `CHECKAL_PARECER_RGPD_OK`) — esses são independentes e só o dono os liberta.

--- (d) CANAIS DE ESCALAÇÃO AO DONO ---

Dois canais, papéis distintos:
1. DIGEST DIÁRIO (Maestro, 19:30) — push via Telegram (bot + chat_id em `agente.env`) com o resumo: MRR, clientes ativos/em_dunning, funil, gatilhos frescos, entregabilidade, tarefas `requer_atencao` do onboarding, filas `pendentes_parecer`, estado dos dead-man switches, gasto LLM do dia vs teto. Inclui a APROVAÇÃO 1-CLIQUE por camadas de risco (liga a ação irreversível externa — envio em massa, publicação, faturas, cobranças). O link/cmd de aprovação liberta a ação (injeta `remetente_frio`, marca item da fila como aprovado); nunca altera código nem gates.
2. PÁGINA IMEDIATA (qualquer agente → Maestro → dono) — push Telegram fora de cadência para alarmes (secção e). Cada agente escala escrevendo na fila (`agente='maestro', tipo='escalar'`) + o Maestro consolida; alarmes P1 disparam push direto sem esperar pelo digest.

Entrega: Telegram como primário (mais fiável que email para paging); Healthchecks.io envia os seus próprios alertas (email/Telegram) por ausência de ping como canal de reserva independente do Polaris.

--- (e) O QUE FAZ O SISTEMA PARAR E CHAMAR O DONO (lista de alarmes) ---

P1 — PARAR + página imediata:
- Teto de custo LLM diário atingido → `PAUSA_LLM` criado (jobs LLM param; determinista continua).
- SENTINELA deteta serviço não prestado: varrimento/página individual sem snapshot fresco vs SLA, OU alerta incoerente com a fonte oficial (alucinação / falso "cancelado"), OU cliente ativo sem cobertura de monitorização em silêncio. (Dano existencial — a promessa da marca.)
- Emissão de fatura falhou/duplicou (risco fiscal TOConline L1: FR duplicada no provider) ou ATCUD/saft_hash ausente numa emissão real.
- Webhook Stripe com assinatura inválida recorrente, ou cobrança/renovação divergente.
- Tentativa de abertura de SMTP cold com gate fechado, ou qualquer sinal de que um agente tentou contornar `pode_enviar_frio_global`/`MODO_TESTE` (deve ser impossível por código; se aparecer, é incidente).
- OOM kill de qualquer serviço (detetável: `journalctl -k | grep -i oom` no arranque do wrapper; `MemoryMax` a disparar repetidamente).

P2 — não pára tudo, mas página/entra no digest com destaque:
- Dead-man switch de um job em falta (Healthchecks `/fail` ou timeout) — job não correu ou rebentou.
- Item da fila em `morto` (esgotou retries).
- Entregabilidade a degradar (bounces/spam no cold ou transacional) — risco de reputação de domínio.
- Backlog de `requer_atencao` (onboarding ambíguo, matches <0.85) acima de limiar.
- Suporte: categoria jurídico/reclamação/cancelamento, ou confiança IA baixa, ou IA indisponível → escala (política reimposta em código).
- Backup noturno falhou.

P3 — só digest:
- Filas `pendentes_parecer` a acumular (esperado enquanto o cold está gated).
- Métricas de funil/MRR fora de tendência.

Invariante final: tudo é reversível-até-ao-gate e auditável. Os agentes fazem o trabalho autónomo até ao portão human-in-the-loop; nenhuma ação irreversível externa (envio em massa, publicação, faturas, cobranças) escapa à aprovação 1-clique do dono; nenhum teto de custo ou alarme altera os gates de compliance/segurança — esses só o dono os liberta.