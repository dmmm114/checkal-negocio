# AGENTES-ENXAME — a camada de governação do CheckAL no Polaris

> Construído pelas Fases A–F do prompt-mestre (`agentes-polaris/01-PROMPT-MESTRE-FABLE.md`).
> 4 agentes single-shot (`claude -p`, systemd timer, **sem processos persistentes**) que
> supervisionam, redigem e orquestram **por cima** do backbone determinista — sem nunca o
> reimplementar nem contornar. **O portão é código, não disciplina.**

## 1. O loop fechado

```
SENTIR → DECIDIR → REDIGIR → APROVAR → AGIR → MEDIR → APRENDER
```

| Fase | Quem | Onde escreve/lê |
|---|---|---|
| SENTIR | ANGARIADOR (`angariador detetar`) | `detetar_gatilhos` sobre eventos frescos (janela 72h) |
| DECIDIR | núcleo de compliance (backbone) | coletiva NIF 5/6 + email genérico + oposição DGC/opt-out |
| REDIGIR | ANGARIADOR / GESTOR | `campanha_pecas`, `eventos_agente` (conteúdo proposto) |
| VET | **linter determinista** (`compliance/linter.py`) | `linter_ok` + violações — fail-closed |
| APROVAR | **dono** (token 1-clique gerado pelo MAESTRO) | `revisao_itens` → `aprovacoes` (autor ≠ aprovador) |
| AGIR | seams gated do backbone | só com token válido **E** gate de código aberto |
| MEDIR | MAESTRO (`maestro-metricas/saude`) | `metricas_rollup`, `agente_execucoes`, `custo_llm` |
| APRENDER | dono (curadoria humana) | few-shots/guardrails — **não há ML loop** |

Nenhum agente chama outro diretamente: comunicam por estado persistido (SQLite/Postgres).
O SENTINELA corre em timer próprio, fora de fase, para apanhar o próprio orquestrador morto.

## 2. Os 4 agentes

| Agente | Timer | Papel | Escreve em |
|---|---|---|---|
| MAESTRO | digest 07:50 · governança 11:50/15:50/19:50 | consolida, arbitra retries, gera tokens 1-clique, compõe o digest | `digests`, `escalacoes`, `agente_execucoes` (flag retry), `revisao_itens.token_aprovacao` |
| ANGARIADOR | seg/qui 03:30 + diária 12:00 | corre o backbone de campanhas, revê copy, propõe conteúdo consent-first | `campanhas`, `campanha_pecas`, `revisao_itens`, `eventos_agente`, `escalacoes` |
| GESTOR-DE-CLIENTE | diária 07:15 + suporte \*:0/15 | relatório mensal, triagem de onboarding, win-back, supervisão de suporte | `revisao_itens`, `eventos_agente`, `escalacoes` |
| SENTINELA-SERVIÇO | 06,12,18,23:40 | watchdog: freshness, alucinação, breaker-bypass, cobertura | **só** `eventos_agente` (achados) + `escalacoes` |

Cada invocação: `claude -p` headless via `deploy/bin/correr-agente.sh`, allowlist exata de
subcomandos `manage.py`, `--max-turns`, `timeout`, e SAI. O passo LLM do sentinela é opcional
(`CHECKAL_SENTINELA_LLM=1`); por omissão a passagem é 100 % determinista.

## 3. Tabelas novas (`checkal/app/models_swarm.py` — aditivas, portáveis)

| Tabela | Papel |
|---|---|
| `eventos_agente` | journal append-only do enxame (achados do Sentinela, conteúdo proposto, escaladas) |
| `campanhas` + `campanha_pecas` | persistem o que `motor.correr_campanhas` só devolvia em memória; UNIQUE (campanha, nif, passo) |
| `revisao_itens` | **a fila de aprovação 1-clique** (alias histórico: `fila_revisao`); `token_aprovacao` + `camada_risco` 1–4 + lease/backoff do drain |
| `contactos_coletiva` | ledger de outreach por NIF (cadência, opt-out ao nível da identidade) |
| `faturas` | ledger de faturas-recibo; UNIQUEs `stripe_invoice_id` / `ix_fatura_id` |
| `metricas_rollup` | rollups (dia, canal, campanha, métrica) — upsert idempotente |
| `supressao_nif` | "não contactar" permanente ao nível do NIF (nunca limpo pela conservação) |
| `aprovacoes` | 1 linha por decisão do dono; **CHECK autor ≠ decidido_por** |
| `escalacoes` · `agente_execucoes` · `digests` · `custo_llm` | governação: o que subiu ao dono, saúde/custo de cada passagem, digests |

Migração: `db.init_db()` importa `models_swarm` e faz `create_all` (aditiva, idempotente —
correr 2× não falha; nenhuma tabela existente é alterada; `Lead`/`OptOut` intactos).

## 4. Matriz de gates (quem abre o quê)

| Gate | Default | Quem abre | O que bloqueia |
|---|---|---|---|
| `CHECKAL_MODO_TESTE` | `True` | dono (env) | TODOS os seams de rede (envio, IMAP, Telegram, faturação) |
| `CHECKAL_PARECER_RGPD_OK` | `False` | dono, após parecer | canal frio (com o de cima e o SMTP, via `pode_enviar_frio_global`) |
| `COLD_SMTP_*` | vazios | dono (env) | qualquer ligação SMTP de cold (getcheckal.com) |
| `CHECKAL_ANTHROPIC_DPA_OK` | `False` | dono, após DPA da Anthropic | **arranque de qualquer agente LLM** (wrapper + `maestro-run`) |
| Gate DGC (`fila.dgc_ok`) | fechado | feed DGC fresco e não-vazio | envio frio — lista vazia/estagnada = todos opostos |
| Linter (`compliance/linter.py`) | fail-closed | — (determinista) | NADA reprovado é aprovável; import falhado ⇒ recusa |
| Token 1-clique (`fila.aprovar`) | — | **só o dono** | toda a ação irreversível externa; autor nunca aprova |
| `PAUSA_LLM` (teto de custo) | limpa | automático (teto) / reset 00:00 | só os passos LLM — **nunca toca gates de compliance** |

Cumulativos: um email frio real exige parecer + modo teste OFF + SMTP + compliance por
contacto + DGC fresca + linter aprovado + item aprovado pelo dono com token. Qualquer elo
fechado ⇒ fica em fila.

## 5. Rollout faseado (critérios em números)

- **Fase 0 — fundações (sem agentes IA a agir).** Deploy + smoke-test TOConline real (ATCUD +
  hash) + snapshots RNAL frescos + widget consent-first. *Passa quando:* 1 FR certificada real;
  2 varrimentos consecutivos frescos; dead-man verdes 7 dias; ≥1 lead opt-in real.
- **Fase 1 — Angariador + Maestro (semi-manual).** Timers `angariador`/`maestro-*` ativados;
  tudo cai em `pendente`; digest diário + gate 1-clique manual. Cold só depois do portão externo
  (§7 abaixo). *Passa quando:* 0 peças enviadas reprovadas pelo linter; opt-out < 2 % e
  spam-complaint < 0,1 % nos primeiros ~200 envios (cap 20/dia); mediana evento→rascunho < 72 h;
  ≥ 1 verificação→pago atribuída ao cold.
- **Fase 2 — Gestor + Sentinela.** *Passa quando:* `requer_atencao` < 5 % e sem backlog > 48 h;
  relatório mensal a 100 % dos ativos; renovação D0 mensurável; 0 clientes ativos sem cobertura.
- **Auto-aprovação:** só ações de risco mínimo JÁ provadas, promovidas por config pelo dono.
  Envio em massa, publicação, faturas e cobranças **nunca** saem do gate humano.

## 6. Alarmes

**P1 — parar + página imediata:** teto LLM atingido (PAUSA_LLM); Sentinela deteta serviço não
prestado (snapshot estagnado, falso «cancelado», cliente sem cobertura); fatura falhada/duplicada
ou sem ATCUD; webhook com assinatura inválida recorrente; QUALQUER sinal de tentativa de contornar
`pode_enviar_frio_global`/`MODO_TESTE` (deve ser impossível — se aparecer é incidente); OOM kill.

**P2 — destaque no digest/página:** dead-man em falta; item `morto` na fila; entregabilidade a
degradar; backlog `requer_atencao` acima de limiar; suporte jurídico/reclamação/confiança baixa;
backup falhado.

**P3 — só digest:** filas `pendentes_parecer` a acumular (esperado com o cold gated); métricas
fora de tendência.

## 7. O que ainda depende do dono (fora de código)

Em ordem: (1) parecer RGPD favorável → `CHECKAL_PARECER_RGPD_OK=True`; (2) DPA comercial da
Anthropic → `CHECKAL_ANTHROPIC_DPA_OK=True`; (3) `CHECKAL_MODO_TESTE=False`; (4) `COLD_SMTP_*`
de getcheckal.com; (5) feed DGC (`CHECKAL_LISTA_DGC_PATH`); (6) seguro E&O antes de escalar;
(7) `sudo systemctl enable --now` dos timers (ficam **disabled** até lá).

## 8. Notas de desenho registadas (tensões resolvidas na construção)

- **Links checkal.pt em canal COLD:** a ADENDA §1 manda o CTA "Pagar já" apontar a
  `checkal.pt/pagar`, e o seam carimba o opt-out em `checkal.pt/remover` — logo a regra RT
  "checkal.pt em cold" foi implementada como **remetente/domínio de envio** (endereços
  `@checkal.pt`, menções de remetente): é isso que o linter bloqueia; links de destino são
  legítimos (a reputação a proteger é a de ENVIO).
- **`motor.compor_email_frio` mantém a copy antiga** ("exploração irregular"): o §5 do
  prompt-mestre só autoriza correções de copy em `prospeccao.py`/`transacional.py`. Em
  consequência, os drafts do `angariador detetar` nascem `linter_ok=False` e voltam ao agente
  para reescrita do corpo (fail-closed a funcionar como desenhado). Se o dono quiser, a mesma
  correção de 2 frases pode ser aplicada a `motor.py` mais tarde.
- **`fila_revisao` = `revisao_itens`:** um único nome de tabela (`revisao_itens`); as specs
  antigas que referem `fila_revisao` apontam para ela.
- **Achados do Sentinela** vivem em `eventos_agente` (tipo `achado`) — a tabela
  `sentinela_achados` da spec individual foi absorvida pelo journal, conforme o prompt-mestre.
- **`RuntimeMaxSec` + `Type=oneshot`:** o systemd ignora `RuntimeMaxSec` em oneshot; o campo
  mantém-se por paridade com a spec, e o limite EFETIVO é `TimeoutStartSec=960` + o `timeout 840`
  do wrapper (dupla guarda).
- **Cartas a singulares (decisão do dono, 18/07/2026):** email/SMS a singulares continua a
  exigir opt-in (nunca a frio), mas o canal POSTAL é admissível — e os dados necessários
  (nome do titular + morada) **já ficam retidos internamente no espelho `registos`** (o
  mirror lícito do RNAL). Nada se perde por o canal estar parqueado: quando o dono o ativar,
  o backbone regenera o lote de cartas (`ProspetoCarta`) a partir do espelho, sem scraping e
  sem esses campos passarem alguma vez pelo contexto dos agentes LLM (minimização mantida).
- **Instalação isolada no Polaris:** tudo (código, venv, BD, prompts, segredos, locks,
  PAUSA_LLM) vive dentro da pasta do projeto; o symlink `/home/diogo/checkal-polaris` dá às
  units um caminho sem espaços, e `deploy/polaris/` traz as units nativas + `agente.env`
  (não versionado) + `instalar.sh`. Só os ficheiros de unit (ponteiros, sem segredos) são
  copiados para `/etc/systemd/system`.

## 9. Instalação e validação de cgroups

Ver `deploy/systemd/README.md` — inclui o procedimento de instalação, a prova de que o
`claude -p` cai no cgroup limitado (`systemd-cgls` + `memory.max`) e a tabela de timers.
