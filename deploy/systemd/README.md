# Crons do CheckAL — systemd timers

O serviço templado `checkal@.service` corre `python manage.py <job>` dentro do container.
Cada job compõe os seams live-gated do ambiente (nada envia/liga sem credenciais) e corre
sob o dead-man switch. Cadências canónicas (AUTOMACAO.md §1/§5/§6):

| Job | Cadência | OnCalendar |
|---|---|---|
| `varrimento` | 2×/semana | `Mon,Thu 03:00` |
| `dre` | diário | `*-*-* 07:00` |
| `dunning` | diário | `*-*-* 09:00` |
| `suporte` | 15 min | `*:0/15` |
| `backup` | noturno | `*-*-* 02:00` |
| `token` | ~3h (TOConline OAuth) | `*:0/180` (`00:00,03:00,…`) |

## Instalação (no servidor, uma vez)
```bash
sudo cp checkal@.service /etc/systemd/system/
# cria um .timer por job (exemplo do varrimento):
cat >/etc/systemd/system/checkal-varrimento.timer <<'EOF'
[Unit]
Description=CheckAL varrimento (2x/semana)
[Timer]
OnCalendar=Mon,Thu 03:00
Persistent=true
Unit=checkal@varrimento.service
[Install]
WantedBy=timers.target
EOF
# repetir para dre/dunning/suporte/backup/token com o OnCalendar da tabela.
sudo systemctl daemon-reload
sudo systemctl enable --now checkal-varrimento.timer   # e os restantes
```

> Nota: `varrimento` só faz diffing (não envia falso "cancelado" — ver breaker/FDS5);
> `token` mantém a cadeia OAuth do TOConline viva (refresh ~8h); `backup` faz `pg_dump`.
> O detalhe diário dos clientes (03:30) e o motor de campanhas (cold, gated) ligam-se
> quando os respetivos pré-requisitos estiverem cumpridos.

---

# ENXAME DE AGENTES — units, instalação e validação de cgroups (Fase E)

Os AGENTES (camada de governação, ver `AGENTES-ENXAME.md` na raiz) usam um template
próprio **nativo** — `checkal-agente@.service` — e um timer por agente. ⚠️ Correção
red-team: ao contrário do `checkal@.service` (que entra no container via docker), o
`checkal-agente@.service` corre `correr-agente.sh` DIRETAMENTE no host, pelo que os
limites `MemoryMax/MemoryHigh/CPUQuota/TasksMax/OOMScoreAdjust` recaem no processo
REAL do `claude -p` (filho direto no cgroup da unit) — é isto que resolve o OOM do
Polaris.

| Timer | Instância | OnCalendar |
|---|---|---|
| `checkal-maestro-digest.timer` | `maestro-digest` | `07:50` |
| `checkal-maestro-governanca.timer` | `maestro-governanca` | `11,15,19:50` |
| `checkal-angariador.timer` | `angariador` | `Mon,Thu 03:30` + `12:00` |
| `checkal-gestor.timer` | `gestor` | `07:15` |
| `checkal-gestor-suporte.timer` | `gestor-suporte` | `*:0/15` |
| `checkal-sentinela.timer` | `sentinela` | `06,12,18,23:40` (fora de fase — timer próprio) |
| `checkal-reset-pausa-llm.timer` | — | `00:00` (limpa /run/checkal/PAUSA_LLM) |

Timers deliberadamente DESCORRELACIONADOS (`RandomizedDelaySec` + minutos distintos):
nunca dois agentes pesados na mesma janela de RAM.

## Instalação (no Polaris, uma vez — os timers ficam DISABLED até o dono ativar)

```bash
sudo cp checkal-agente@.service checkal-*.timer checkal-reset-pausa-llm.service /etc/systemd/system/
sudo install -m 600 -o root -g checkal agente.env /etc/checkal/agente.env   # segredos
sudo systemctl daemon-reload
# ⚠️ NADA é ativado por omissão. Ativar é decisão do DONO, timer a timer:
#   sudo systemctl enable --now checkal-sentinela.timer          (fase 0/1)
#   sudo systemctl enable --now checkal-maestro-digest.timer …   (fase 1)
```

Gates herdados do ambiente (`/etc/checkal/agente.env`) — NUNCA abertos por este repo:
`CHECKAL_MODO_TESTE=true`, `CHECKAL_PARECER_RGPD_OK=false`, `CHECKAL_ANTHROPIC_DPA_OK=false`.
Sem o DPA da Anthropic assinado, o wrapper recusa QUALQUER arranque LLM (RT-DPA).

## Validar que o `claude -p` cai no cgroup limitado

```bash
sudo systemctl start checkal-agente@sentinela.service
systemd-cgls -u checkal-agente@sentinela.service       # o claude/python aparece DENTRO da unit
cat /sys/fs/cgroup/system.slice/'checkal-agente@sentinela.service'/memory.max   # ≈ 1258291200 (1200M)
journalctl -k | grep -i oom                             # (vazio = sem OOM kill do kernel)
```

Se o processo do modelo aparecer FORA da unit (ex.: no cgroup do dockerd por se ter
usado `docker exec`), os limites NÃO se aplicam — é exatamente o erro que este
template evita. Nota: com `Type=oneshot` o systemd ignora `RuntimeMaxSec` (aviso do
`systemd-analyze verify`); o limite de parede efetivo é `TimeoutStartSec=960` na unit
+ `timeout 840` no wrapper (dupla guarda).

## Verificação de sintaxe

```bash
systemd-analyze verify --man=no checkal-agente@.service   # rc=0 (avisos de ambiente à parte)
```
