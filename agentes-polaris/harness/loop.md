# O LOOP FECHADO, MÉTRICAS, FEEDBACK E ROLLOUT FASEADO — CheckAL

## 1. O ciclo Sentir → Decidir → Redigir → Aprovar → Agir → Medir → Aprender

O enxame não é um pipeline linear: é um anel em que o *output* de um agente é escrito numa tabela da BD que se torna o *input* do agente seguinte. Nenhum agente chama outro diretamente — todos comunicam por estado persistido (SQLite/Postgres) + fila de revisão, e o Maestro arbitra as passagens. Isto mantém cada invocação single-shot, headless e sem processo persistente (restrição dura de RAM do Polaris).

**Percurso de uma oportunidade de cold (Angariador → Maestro → envio):**

| Fase | Quem | Ação concreta | Onde escreve/lê (a "cola") |
|---|---|---|---|
| SENTIR | ANGARIADOR | `gatilhos.detetar_gatilhos(session)` sonda `eventos_registo`/`eventos_regulatorios` não usados, janela 72h | Lê eventos; marca-os com `CANAL_GATILHO` (idempotente) |
| DECIDIR | ANGARIADOR | `segmentacao.segmentar(lote)` → só `Segmentos.cold_email` (coletiva NIF 5/6 + email genérico). Singular descartado no ato (minimização) | Materializa **só** `ContactoEnderecavel` (campos coletivos) |
| REDIGIR | ANGARIADOR | `motor.compor_email_frio()` / `prospeccao.render_sequencia()` (D+0/D+4/D+10), copy PT-PT COPY-VENDAS §2 | Rascunho |
| VET | ANGARIADOR | Linter determinista corre a montante da aprovação; `optout.filtrar_optout(lista_dgc, log_optout)`; `pode_enviar_frio(contacto)` | Escreve em `pendentes_parecer` (RascunhoFrio) |
| APROVAR | MAESTRO | Gate 1-clique por camadas de risco no digest diário. Liberta `remetente_frio` (= ligar flags/SMTP), **não** altera código | Estado do gate |
| AGIR | (seam gated) | `correr_campanhas(session, remetente_frio=<injetado>)` só envia se `pode_enviar_frio_global()` ∧ remetente injetado ∧ `n_enviados < cap_diario` | `.enviados` / `.pendentes_parecer` |
| MEDIR | MAESTRO + GESTOR | Aberturas/cliques/respostas/opt-out; resposta entra no `apoio@`/reply → `suporte.correr_suporte()` | `eventos`, métricas |
| APRENDER | dono + MAESTRO | Curadoria do ficheiro de guardrails + few-shot (ver §3) | Ficheiro de prompts/guardrails |

**Percurso de um pagante (Angariador fecha → Gestor retém):** verificação→pago dispara `fulfillment.processar_checkout` → `onboarding.processar_onboarding` (os <5% ambíguos viram tarefa `requer_atencao` que o **Gestor-de-Cliente** tria) → relatório mensal anti-churn (Gestor orquestra o buraco sem cron) → régua `dunning.correr_dunning` D-30…D+21 → win-back. Em paralelo, **Sentinela-Serviço** (timer próprio, descorrelacionado) verifica que o serviço prometido foi de facto prestado (freshness do snapshot, cross-check alerta↔fonte oficial, breaker confirmou cancelamentos reais) e escala achados à fila de revisão. Cada achado do Sentinela pode reabrir o loop (ex.: reprocessar varrimento estagnado).

**Propriedade central:** tudo é **reversível-até-ao-gate**. Os executores fazem trabalho autónomo até ao portão; só o Maestro (único a falar com o dono, único com autoridade de libertar gates) converte isso numa ação irreversível externa. Quem PROPÕE nunca é quem APROVA.

---

## 2. Métricas obrigatórias

Compiladas pelo Maestro no digest diário; a maioria já sai das tabelas existentes.

**Topo de funil / aquisição (Angariador):**
- Leads/gatilhos frescos por passagem; tempo evento→campanha (SLA janela 72h — alerta se mediana > 72h)
- Emails enviados vs cap (`CAMPANHA_CAP_DIARIO`, warm-up); fila `pendentes_parecer` por razão (`RAZAO_GATE`/`RAZAO_SEM_REMETENTE`/`RAZAO_CAP`)
- Taxa de abertura, clique, resposta — por origem/gatilho (Porto cancelamentos vs Funchal regulamento vs SEO)
- **Opt-out rate e spam-complaint rate** (kill-switch de reputação: complaint > 0,1% ⇒ pausar canal; é o domínio irmão getcheckal.com em jogo)
- Deliverability (bounces, DMARC) do domínio frio, separado do transacional

**Conversão e economia:**
- verificação→pago **por origem/canal** (a métrica-mãe de eficácia de copy)
- CAC por canal; comparar cold vs consent-first
- MRR, clientes ativos / em_dunning / cancelados; churn mensal e por coorte
- LTV emergente; renovação D0 (efeito do relatório mensal)

**Serviço (Sentinela — 1.ª classe):**
- Freshness: varrimento nacional 2×/sem cumprido? página individual diária persistiu snapshot fresco? (não o dead-man switch — a **verdade** do dado)
- Alertas por severidade; **falsos positivos do breaker** (falsos "cancelado" apanhados antes de afirmação forte)
- Cobertura: nº de clientes ativos sem snapshot recente (deve ser 0)
- Achados de alucinação (cross-check alerta↔fonte oficial)

**Operação:**
- Throughput da fila de revisão; tempo médio até aprovação 1-clique
- Dead-man switches (Healthchecks.io) verdes; orçamento de tokens/API consumido vs teto
- TAM net-adds (novos registos RNAL elegíveis por semana — reabastecimento do funil)

---

## 3. Feedback — honestidade sobre o que "aprender" significa aqui

**Não há ML loop. Ponto.** A esta escala (Metas: 490 → 1.630 clientes) treinar um modelo seria teatro estatístico: volume insuficiente, atribuição ruidosa, e risco regulatório de otimizar copy fria contra métricas de conversão sem supervisão humana.

O que existe é **curadoria humana assistida**:
- "Aprender o que converte" = o dono (via digest do Maestro) olha para os top-performers por origem (assunto/ângulo com melhor resposta e menor opt-out) e **edita à mão** o ficheiro de guardrails + o conjunto de **few-shot examples** que o Angariador injeta na composição.
- Os agentes propõem candidatos ("estes 3 assuntos tiveram 2× a resposta, 0 complaints"); **a promoção a few-shot é decisão humana**, não um gradiente automático.
- Auto-recuperação ≠ aprendizagem: retries/backoff e escalada de exceções são robustez, não otimização.
- Guard-rail contra Goodhart: como a métrica de sucesso (resposta/conversão) e a métrica de segurança (opt-out/complaint/achados do linter) são vigiadas em conjunto, nunca se promove uma variante que suba conversão à custa de reputação ou de linguagem proibida.

Ou seja: o "loop de aprendizagem" é um humano curador com bom instrumento de medição, não um sistema que se auto-treina. Dizê-lo claramente evita vender inteligência que não existe.

---

## 4. Rollout faseado (cold-first, alinhado com a decisão do dono) — critérios em números

**Fase 0 — Fundações (sem agentes IA a agir).**
Provisionar Polaris (systemd timers com MemoryMax/CPUQuota/OOMScoreAdjust) + deploy (docker/caddy/systemd) + smoke-test de emissão real TOConline (ATCUD + document_hash_sum preenchidos numa FR de teste — resolve o risco fiscal L1/L2) + snapshots RNAL a persistir + widget consent-first no ar.
*Critério de passagem:* 1 FR certificada real emitida e validada; 2 varrimentos nacionais consecutivos com snapshot fresco; dead-man switches verdes 7 dias; widget capta ≥ 1 lead opt-in real.

**Fase 1 — Ligar Angariador + Maestro (semi-manual).**
Angariador corre event-driven e enche `pendentes_parecer`; Maestro compila digest e opera o gate 1-clique **manual** para cada lote. Cold só dispara **depois** do portão bloqueante: `CHECKAL_PARECER_RGPD_OK=True` (parecer do jurista) + SMTP getcheckal.com + sair de `CHECKAL_MODO_TESTE`. Até lá, tudo fica em fila (o motor está construído e hard-gated).
*Critério de passagem:* linter reprova 0 peças enviadas; opt-out < 2% e spam-complaint < 0,1% nos primeiros ~200 envios (cap 20/dia, warm-up); tempo evento→rascunho < 72h em mediana; ≥ 1 verificação→pago atribuída ao cold.

**Fase 2 — Ligar Gestor-de-Cliente + Sentinela-Serviço.**
Gestor assume onboarding ambíguo, relatório mensal, dunning, suporte IMAP. Sentinela corre em timer independente a auditar serviço.
*Critério de passagem:* tarefas `requer_atencao` resolvidas < 5% do volume e sem backlog > 48h; relatório mensal entregue a 100% dos ativos; renovação D0 mensurável; Sentinela com 0 clientes ativos sem cobertura e falsos-positivos do breaker = 0 não-detetados.

**Promoção a auto-aprovação:** só ações de risco mínimo e **já provadas** em N passagens (ex.: relatório mensal a pagantes opt-in, respostas de suporte factuais de alta confiança) passam a auto-aprovadas por config. Envio em massa cold, publicação de páginas públicas, emissão de faturas e cobranças **nunca** saem do gate human-in-the-loop.

---

**Invariante em todas as fases:** o backbone determinista (rnal ingest+diff, regulatório, onboarding, dunning, faturação, breaker, núcleo de compliance) mantém-se determinista; os agentes supervisionam/redigem/orquestram por cima e **chamam** as funções — nunca reimplementam a lógica nem forçam `pode_enviar_frio_global()`/`CHECKAL_MODO_TESTE`. O portão é código, não disciplina.