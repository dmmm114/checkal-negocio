# ARQUITETURA DO ENXAME DE AGENTES — CheckAL @ Polaris

> Fonte de verdade do sistema de agentes autónomos. Estado: desenho fechado, backbone determinista construído, camada de agentes por construir sobre gates de código já existentes. PT-PT. Regra-mãe que atravessa tudo: **reversível-até-ao-gate e auditável** — o portão é código, não disciplina.

---

## 1. Princípio de desenho e mapa do sistema

### 1.1. A restrição que molda tudo: RAM, não inteligência

Polaris é um home server Ubuntu (Tailscale) onde **já houve OOM kill por sessões Claude Code persistentes**. Esta é a restrição dura, não negociável, que determina a forma do sistema inteiro: **nenhum processo persistente**. Não há daemon, não há worker a rodar, não há agente "vivo". Cada agente é uma **invocação single-shot, headless, on-demand** (`claude -p …`), lançada por systemd timer (ou drain de uma fila SQLite), que faz o trabalho, escreve na BD/fila de revisão, e **SAI**. Toda a observabilidade assenta em artefactos em disco/SQLite + pings HTTP — nunca num processo a vigiar.

Corolário: o estado NÃO vive na memória do agente (não há memória entre passagens). Vive na base de dados. Um agente single-shot sem estado lê o mundo das tabelas, decide, escreve o resultado nas tabelas, e desaparece. O anel fecha-se por **estado persistido**, não por chamadas entre processos.

### 1.2. Duas camadas, uma fronteira dura

```
┌──────────────────────────────────────────────────────────────────┐
│  AGENTES LLM (single-shot, claude -p no Polaris)                  │
│  MAESTRO · ANGARIADOR · GESTOR-DE-CLIENTE · SENTINELA-SERVIÇO     │
│  SUPERVISIONAM · REDIGEM · ORQUESTRAM · DETETAM                   │
│  — nunca reimplementam lógica, nunca forçam gates —              │
└───────────────┬──────────────────────────────────────────────────┘
                │  CHAMAM funções / LEEM e ESCREVEM tabelas
                ▼
┌──────────────────────────────────────────────────────────────────┐
│  BACKBONE DETERMINISTA (Python/FastAPI + Postgres, JÁ construído) │
│  rnal ingest+diff · regulatório · onboarding · dunning ·          │
│  faturação · breaker · núcleo de compliance (nif/email/           │
│  minimização/optout) · gates de código (pode_enviar_frio_global)  │
│  — continua a MANDAR; as tabelas de agentes são passivas —        │
└──────────────────────────────────────────────────────────────────┘
```

**O que é determinista fica determinista.** Os crons existentes (varrimento RNAL, diff, regulatório, onboarding, dunning, faturação, breaker, compliance) não são substituídos nem reimplementados pelos agentes. Os agentes correm **por cima**: sondam eventos, redigem texto, orquestram ciclos de vida, detetam falhas — e **chamam** as funções deterministas. A inteligência do LLM é de redação e orquestração; a lógica de negócio e de segurança é código testado.

### 1.3. Caveat honesto de soberania de dados

O Claude CLI é o motor IA dos agentes novos, mas **continua a enviar prompts para a API da Anthropic — inferência nos EUA**. **Não** mantém dados na UE. Consequência de desenho, não afterthought:

- Os agentes operam sobre dados **agregados / genéricos / opted-in**.
- **Prospects (cold):** o modelo vê **só** estatísticas de segmento + email genérico coletivo (`geral@`/`info@`/`reservas@`). **Nunca** campos pessoais de singular. A minimização é feita por geradores que descartam no ato — o sistema não materializa lista de envio nem faz scraping.
- **Clientes singulares/ENI opted-in:** os dados do AL enviados à IA **são pessoais** → exigem **DPA (art. 28.º) + mecanismo de transferência** da Anthropic. Opções: (A) Bedrock `eu-central-1` (Frankfurt) remove o Cap. V; (B) API EUA = SCCs + TIA. Sem treino sobre dados de API. Isto é gated por código (ver §4 e §7).

---

## 2. O roster — e porque exatamente quatro

Quatro agentes, não menos (perde-se separação de poderes) e não mais (multiplica superfície de RAM/custo sem ganho). A partição não é funcional-arbitrária: segue **fronteiras de risco de dados, de cadência e de autoridade**.

| Agente | Missão de 1 linha | Perfil de dados | Cadência | Autoridade |
|---|---|---|---|---|
| **MAESTRO** | Governa o enxame, compõe o digest diário, opera o **único** gate 1-clique | Agregado (lê métricas, nunca domínio) | `08,13,19:30` (digest 19:30) | **Única** com poder de libertar gates e aplicar tetos |
| **ANGARIADOR** | Motor de aquisição fria por cima do backbone hard-gated | Coletivas minimizadas (NIF 5/6 + genérico) | `08,14,20:00`, event-driven | Propõe; nunca envia nem publica |
| **GESTOR-DE-CLIENTE** | Ciclo de vida do pagante: onboarding, relatório anti-churn, dunning, suporte | Pessoas identificadas opted-in | dunning/relatório `07:15`; suporte `*:0/15` | Orquestra; envio em massa passa pelo gate |
| **SENTINELA-SERVIÇO** | Watchdog adversário: o serviço prometido foi de facto prestado? | Read-only + fonte oficial | `06,12,18,23:40` (timer **próprio**) | Deteta e prova; **zero** ação externa |

### Porque cada um é separado (o argumento, não a lista)

- **MAESTRO isolado dos executores** por **conflito de interesse**: quem PROPÕE enviar/cobrar não pode ser quem APROVA. É o único que fala com o dono e o único com autoridade de gate. Perfil de permissões único (write de libertação de gate + leitura agregada, **zero** ação de domínio).
- **ANGARIADOR isolado** porque concentra a **superfície RGPD/AI-Act máxima** (prospeção fria, art. 5/1/b) num único invólucro auditável que pode ficar **DESLIGADO por código** sem paralisar o resto. Funde-lo com o Gestor misturaria dados frios não-consentidos com dados de clientes no mesmo contexto de modelo — inaceitável.
- **GESTOR isolado** porque trata **pessoas identificadas que consentiram** — regime jurídico e reputação de domínio (`checkal.pt`/Resend) **opostos** aos do Angariador (prospects minimizados/`getcheckal.com`). Toca dinheiro (faturas/dunning/reembolsos) e a caixa de suporte.
- **SENTINELA isolado, com timer próprio descorrelacionado**, porque o pior modo de falha é **o serviço falhar em silêncio**, e o watchdog tem de conseguir apanhar **o próprio Maestro morto** (OOM kill, timer não-disparado, exceção engolida). Se o Maestro se auto-vigiasse, uma falha do Maestro levava a monitorização junto — falha correlacionada ("quem vigia o vigia"). O método é distinto: verificação **adversária de integridade de dados contra a fonte oficial**, não raciocínio sobre métricas.

---

## 3. O loop fechado, estado partilhado, métricas e feedback honesto

### 3.1. O anel Sentir → Decidir → Redigir → Vet → Aprovar → Agir → Medir → Aprender

Não é um pipeline linear: é um **anel** em que o output de um agente é escrito numa tabela que se torna o input do seguinte. **Nenhum agente chama outro diretamente** — comunicam por estado persistido + fila de revisão; o Maestro arbitra. Isto mantém cada invocação single-shot e sem processo persistente.

**Percurso de uma oportunidade de cold (Angariador → Maestro → envio):**

| Fase | Quem | Ação | A "cola" (onde escreve/lê) |
|---|---|---|---|
| SENTIR | ANGARIADOR | `gatilhos.detetar_gatilhos()` sonda `eventos_registo`/`eventos_regulatorios`, janela 72h | Marca eventos com `CANAL_GATILHO` (idempotente) |
| DECIDIR | ANGARIADOR | `segmentacao.segmentar()` → só coletiva NIF 5/6 + genérico; singular descartado no ato | Materializa só `ContactoEnderecavel` (campos coletivos) |
| REDIGIR | ANGARIADOR | `motor.compor_email_frio()` / `render_sequencia()` (D+0/D+4/D+10) | Rascunho em memória |
| VET | ANGARIADOR | **Linter determinista** + `optout.filtrar_optout()` + `pode_enviar_frio()` | `Campanha`+`CampanhaPeca` (`linter_ok`) → `RevisaoItem` pendente |
| APROVAR | MAESTRO | Gate 1-clique por camadas de risco no digest; liberta `remetente_frio` | Estado do gate / `RevisaoItem.estado` |
| AGIR | (seam gated) | `correr_campanhas(remetente_frio=<injetado>)` só se `pode_enviar_frio_global()` ∧ injetado ∧ `< cap` | `CampanhaPeca.enviado_em` / `ContactoColetiva` |
| MEDIR | MAESTRO + GESTOR | aberturas/respostas/opt-out; reply → `correr_suporte()` | `EventoAgente`, `MetricaRollup` |
| APRENDER | dono + MAESTRO | curadoria manual de guardrails + few-shot | Ficheiro de prompts (§3.4) |

**Percurso de um pagante (Angariador fecha → Gestor retém):** verificação→pago → `fulfillment.processar_checkout` → `onboarding.processar_onboarding` (os <5% ambíguos viram tarefa `requer_atencao` que o Gestor tria) → relatório mensal anti-churn (Gestor orquestra o buraco sem cron) → régua `dunning.correr_dunning` D-30…D+21 → win-back. Em paralelo, **Sentinela** (timer próprio) verifica que o serviço foi de facto prestado e escala achados à fila — cada achado pode reabrir o loop (ex.: reprocessar varrimento estagnado).

### 3.2. Estado partilhado — as 7 tabelas aditivas (`models_swarm.py`)

Aditivas a `app/models.py`, importadas a seguir para partilhar `Base.metadata`. Reutilizam `Lead`/`OptOut` e **nunca** os redefinem. Só tipos portáveis (SQLite dev / Postgres prod); dinheiro em **Integer de cêntimos**; UNIQUE/idempotência em cada ponto de reentrega.

1. **`EventoAgente`** — journal append-only da camada de agentes (o "event bus" do enxame). É a fonte que o Maestro lê para o digest e onde o Sentinela regista achados. `execucao_id` correlaciona todos os eventos de uma invocação (prova que o cron correu **E** produziu verdade — o buraco que o dead-man switch não apanha). `ref_tipo/ref_id` como par de texto (PKs heterogéneas: `nr_registo` int, `nif` texto). `escalado` evita re-notificar o mesmo facto. **Imutável: nunca UPDATE — corrige-se com novo evento.**
2. **`Campanha`** — 1 linha por passagem de aquisição (hoje só em memória em `ResultadoCampanha`). Sem persistir, o Maestro não pode reportar funil. Guarda `n_gatilhos/n_elegiveis/n_enviados/n_pendentes/n_descartados`.
3. **`CampanhaPeca`** — materialização durável do `RascunhoFrio`: 1 email composto por contacto. **Só campos de coletiva.** `linter_ok` grava o veredito do linter **antes** de ser aprovável (obrigatório). `agendado_para` dá autonomia proativa (follow-up D+4/D+10 sem processo persistente). `UNIQUE(campanha_id, nif, passo)` = idempotência de cadência (não duplicar toques).
4. **`RevisaoItem`** — a fila 1-clique por camadas de risco. Separada da peça (a decisão ≠ o conteúdo) para o Maestro arbitrar sem tocar domínio, e para a **mesma** fila governar emails frios, páginas e faturas. `linter_achados` (JSON) + `risco` tornam a aprovação "por camadas". `agente_origem` nunca é o Maestro (conflito de interesse).
5. **`ContactoColetiva`** — ledger de outreach **keyed por NIF** (não por email): a identidade legal é o que importa para não recontactar e para suprimir. Uma coletiva que rode `geral@`→`reservas@` continua suprimida. `n_toques`/`ultimo_passo` dão a memória de cadência que um agente sem estado precisa.
6. **`Fatura`** — 1 linha por fatura-recibo certificada (checkout ou renovação anual). Os `ix_*` em `clientes` guardam só a última; o MRR exige histórico. **Dois `unique` distintos** (`stripe_invoice_id`, `ix_fatura_id`) = duas fronteiras de idempotência (Stripe reentrega vs provider) contra FR fiscal duplicada (L1). `ix_atcud` = guarda G2 (sem ATCUD, não certificada).
7. **`SupressaoNif`** — "não contactar" a nível de **identidade legal (NIF)**, a par do `OptOut` (por email). Fecha a lacuna de a supressão ser só por email. **Permanente por desenho** (art. 21 RGPD / Lei 41/2004 13.º-B) — a limpeza de prospects nunca lhe toca. O cruzamento no envio passa a ser **duplo**: email ∉ optouts **E** nif ∉ supressao_nif.

**Consentimento granular reutilizado, não redefinido:** `Lead.consent_alertas` (serviço) e `Lead.consent_ofertas` (marketing) são independentes, cada um com a sua prova (`consentimento_texto_versao`/`_em`/`ip`). É a salvaguarda consent-first; nenhuma tabela nova a duplica.

### 3.3. Métricas obrigatórias (compiladas pelo Maestro no digest)

- **Topo de funil:** gatilhos frescos/passagem; SLA evento→campanha (alerta se mediana > 72h); enviados vs cap; fila `pendentes_parecer` por razão; abertura/clique/resposta por origem (Porto cancelamentos vs Funchal regulamento vs SEO); **opt-out rate e spam-complaint rate** (kill-switch: complaint > 0,1% ⇒ pausar canal); deliverability do domínio frio separado do transacional.
- **Conversão/economia:** verificação→pago por origem (métrica-mãe de eficácia de copy); CAC por canal (cold vs consent-first); MRR, ativos/em_dunning/cancelados; churn por coorte; renovação D0 (efeito do relatório mensal).
- **Serviço (Sentinela — 1.ª classe):** freshness (varrimento 2×/sem cumprido? página individual diária persistiu snapshot fresco?); falsos positivos do breaker; **cobertura: nº de ativos sem snapshot recente (deve ser 0)**; achados de alucinação (cross-check alerta↔fonte).
- **Operação:** throughput da fila e tempo até aprovação; dead-man switches verdes; tokens consumidos vs teto; TAM net-adds (novos registos elegíveis/semana).

### 3.4. Feedback — honestidade sobre o que "aprender" significa

**Não há ML loop. Ponto.** À escala de 490 → 1.630 clientes, treinar um modelo seria teatro estatístico: volume insuficiente, atribuição ruidosa, risco regulatório de otimizar copy fria contra conversão sem supervisão. O que existe é **curadoria humana assistida**:

- "Aprender o que converte" = o dono (via digest) olha os top-performers por origem e **edita à mão** o ficheiro de guardrails + os few-shot que o Angariador injeta.
- Os agentes **propõem** candidatos ("estes 3 assuntos tiveram 2× a resposta, 0 complaints"); a promoção a few-shot é **decisão humana**.
- Auto-recuperação (retries/backoff/escalada) ≠ aprendizagem — é robustez.
- **Guarda anti-Goodhart:** métrica de sucesso (resposta/conversão) e de segurança (opt-out/complaint/achados do linter) são vigiadas **em conjunto** — nunca se promove uma variante que sobe conversão à custa de reputação ou linguagem proibida.

Dizê-lo claramente evita vender inteligência que não existe.

---

## 4. Camada de compliance, linter e gates humanos

### 4.1. Gates de código (não disciplina) — verificados SEMPRE antes de agir

- **`config.pode_enviar_frio_global()`** é o portão-mãe do cold. Devolve `True` **só se** `CHECKAL_PARECER_RGPD_OK` (default `False`) **E** `not CHECKAL_MODO_TESTE` (default `True`) **E** `cold_smtp_ativo()`. Qualquer um falhar → nenhum email frio sai; tudo cai em `pendentes_parecer`.
- **Nenhum agente pode setar, forçar ou contornar** `CHECKAL_PARECER_RGPD_OK`, `CHECKAL_MODO_TESTE`, `COLD_SMTP_*`. Libertar o gate = ação do **dono via Maestro** (injetar `remetente_frio`), nunca alteração de código pelo executor.
- **`CHECKAL_MODO_TESTE=True`** por omissão: todos os seams de rede (`obter_emissor/enviador/leitor/escalador`, `_compor_onboarding`, `_seam_obter_detalhe`) devolvem `None` → nada envia/cobra/lê IMAP/toca a rede.

### 4.2. Triplo gate cumulativo do cold (`motor.pode_enviar_frio`), por contacto

Um contacto só recebe cold se **os três** fecharem em cadeia:
1. **Global:** `pode_enviar_frio_global()`.
2. **Núcleo de compliance:** coletiva **NIF 5/6** (`compliance/nif`) **E** email **genérico** (`compliance/email`), reaplicados no ato via `minimizacao.filtrar_enderecaveis`.
3. **Oposição:** não constar da oposição **DGC** nem do opt-out interno (`optout.filtrar_optout`) — cruzamento **duplo** (email **E** NIF, §3.2).

> O agente **CHAMA** `pode_enviar_frio(contacto, lista_dgc, log_optout)` — nunca reimplementa.

### 4.3. Fronteira dura da minimização

O **portão do sujeito é o NIF, não o prefixo do email.** Só coletiva (NIF 1.º dígito ∈ {5,6}) é endereçável a cold — singular/ENI **nunca**, mesmo com `geral@`. `ContactoEnderecavel` só transporta campos coletivos. **Coimas saem exclusivamente de `config.COIMA`** (singular 2 500–4 000 € · coletiva 25 000–40 000 €) — nunca inventar, nunca o obsoleto "7 500 €". Cada peça leva `proveniencia='rnal:email_generico_publicado'` (prova de lookup dirigido a dado publicado, não recolha em massa).

### 4.4. O LINTER determinista — vet obrigatório a TODO o texto outward-facing

`checkal/app/compliance/linter.py`, função pura, sem I/O de rede, **conservadora (na dúvida REJEITA)**. Corre **dentro** da passagem do agente, no passo "marcar aprovável", **antes** de escrever na fila. Reutiliza `validar_alerta` (grounding) e `validar_nao_prescritivo` (anti-atividade-reservada), e acrescenta a camada de canal. **Citações da fonte são removidas antes da varredura** (só se varre a voz própria do agente).

**Proíbe (BLOQUEIA):**
- **R1** — afirmar ilegalidade/incumprimento/"sem seguro"/"cancelado" sobre o cliente/AL (G4: só o breaker confirma cancelamentos; falha de rede → `indeterminado`).
- **R2** — conclusão jurídica individualizada (atividade reservada, Lei 10/2024) via `validar_nao_prescritivo`.
- **R3** — coima como **ameaça individualizada** (permitido só o condicional impessoal ancorado em `config.COIMA`).

**Exige, por canal (BLOQUEIA se ausente):** R4 link de fonte oficial · R5 divulgação de IA (AI Act art. 50, desde 02/08/2026) · R6 grounding de valores/prazos · R7 disclaimer "informação, não aconselhamento jurídico" · R8 opt-out 1-clique · R9 rodapé RGPD + remetente `getcheckal.com`.

| Regra | ALERTA | COLD | NURTURE | PÁGINA |
|---|---|---|---|---|
| R4 fonte | ✔ | — | — | ✔ |
| R5 IA | ✔ | ✔ | ✔ | ✔ |
| R6 grounding | ✔ | ✔ (se cita coima) | — | ✔ |
| R7 disclaimer | ✔ | ✔ | ✔ | ✔ |
| R8 opt-out | — | ✔ | ✔ | — |
| R9 rodapé/remetente | — | ✔ | — | — |

**Destino de um rascunho reprovado:** (1) volta ao agente para regeneração dirigida (até N=2 tentativas; `trecho`+`razao` alimentam o novo prompt); (2) persistindo, cai em **formato de recurso** (manual/factual, seguro) ou é enfileirado `requer_atencao` e **escalado ao Maestro** — nunca descartado em silêncio, nunca marcado aprovável; (3) cada reprovação é logada (`regra`, `versao`, `trecho`) para o dossier de defesa. **Viés inviolável: nunca um falso `aprovado`** perante conclusão jurídica, ilegalidade, coima-ameaça ou valor órfão. Alargar a deteção é sempre seguro.

### 4.5. Human-in-the-loop — o único portão

Ações **irreversíveis externas** sempre gated pelo 1-clique do Maestro: **envio em massa** (cold ou nurture), **publicação de páginas**, **emissão de faturas**, **cobranças**, qualquer **post público**. Os agentes fazem tudo **até ao gate** e deixam em fila. Só ações de risco mínimo **já provadas** (ex.: relatório mensal a opted-in, respostas de suporte factuais de alta confiança) podem ser promovidas a auto-aprovação **por config** — decisão do dono, nunca do executor. Nenhum teto de custo ou alarme toca os gates de segurança.

---

## 5. Execução no Polaris — systemd, RAM, custos, alarmes

### 5.1. Padrão systemd universal

Cada agente = par `.service` (Type=oneshot) + `.timer`, via template `checkal-agente@.service`, com **tetos reais de cgroup** (o que resolve o OOM): `MemoryMax=1200M` (hard, o cgroup mata), `MemoryHigh=900M` (soft throttle), `CPUQuota=60%`, `TasksMax=64`, `OOMScoreAdjust=800` (sob pressão global, o kernel escolhe este primeiro), `OOMPolicy=kill`; `RuntimeMaxSec=900` (15 min máx/passagem) + `TimeoutStartSec=960`; `ConditionPathExists=!/run/checkal/%i.lock` (anti-reentrância).

**Timers descorrelacionados** (nunca dois pesados na mesma janela): Maestro `08,13,19:30` · Angariador `08,14,20:00` · Gestor dunning `07:15` + suporte `*:0/15` · Sentinela `06,12,18,23:40` (fora de fase do Maestro, para o poder apanhar morto). `RandomizedDelaySec=300` de-sincroniza; `Persistent=true` apanha passagens perdidas.

**Wrapper `correr-agente.sh %i`**, por ordem: (1) `flock -n` (2.ª camada anti-reentrância); (2) ping START ao Healthchecks.io; (3) verifica `/run/checkal/PAUSA_LLM` (se existe e o job usa LLM, aborta com `/log`, não `/fail`); (4) corre `claude -p "$(cat prompts/$AGENTE.md)" --output-format json --max-turns N` com `timeout` de guarda-costas; (5) regista tokens/custo na BD; (6) ping final: sucesso → `$HC_URL/$AGENTE`, falha → `/fail` com stderr.

### 5.2. Fila de trabalho SQLite (drain on-demand)

`/opt/checkal/var/fila.db` (WAL), separada do domínio. Tabela `trabalho(agente, tipo, payload, estado, tentativas, max_tentativas, nao_antes_de, lease_ate, …)`. Drain single-shot: `BEGIN IMMEDIATE` → seleciona elegíveis → marca `a_correr`+`lease_ate=now+15min` → COMMIT (o lease evita dupla-execução; idempotência de domínio é a rede final). Sucesso → `feito`; exceção → `tentativas+1` com backoff `min(2^n·60s, 6h)`; `>=max` → `morto` + escala. Timers dão cadência garantida; a fila dá reação a eventos e retry sem processo persistente. **O drain é sempre single-shot.**

### 5.3. Tetos de custo

Cada passagem escreve `custo_llm(dia, agente, input_tokens, output_tokens, custo_eur, ts)` a partir do `usage` do JSON. `TETO_DIARIO_EUR` (~5€/dia agregado, sub-tetos por agente): antes de cada chamada LLM o wrapper soma o gasto do dia; se `>= TETO` → cria `/run/checkal/PAUSA_LLM`, **não** chama o modelo, pagina o dono. A flag limpa-se à meia-noite. **Os crons deterministas continuam a correr — só os passos LLM pausam.** Circuit breaker por passagem: `--max-turns` + `RuntimeMaxSec=900`.

**Caps de rate por código:** `CAMPANHA_CAP_DIARIO=20` cold/dia/caixa (warm-up `getcheckal.com`); excedente → fila com `razao=RAZAO_CAP`. Cap de nurture análogo para `checkal.pt`/Resend, **separado** (fronteira dura de reputação). **Regra dura: os tetos pausam LLM e paginam; NUNCA tocam `pode_enviar_frio_global`/`MODO_TESTE`/`PARECER_RGPD_OK` — esses só o dono.**

### 5.4. Escalação e alarmes

Dois canais: **DIGEST DIÁRIO** (Maestro 19:30, Telegram) com MRR, funil, gatilhos, entregabilidade, `requer_atencao`, `pendentes_parecer`, dead-man switches, gasto vs teto + **aprovação 1-clique por camadas**; e **PÁGINA IMEDIATA** (P1, fora de cadência). Healthchecks.io é o canal de reserva independente do Polaris.

- **P1 (parar + página):** teto LLM atingido; Sentinela deteta serviço não prestado (snapshot estagnado / alerta alucinado / cliente sem cobertura em silêncio); FR falhada/duplicada ou ATCUD ausente; webhook Stripe inválido recorrente; tentativa de abrir SMTP cold com gate fechado ou qualquer sinal de contorno de gate; OOM kill.
- **P2 (digest com destaque + página):** dead-man switch em falta; item `morto`; entregabilidade a degradar; backlog `requer_atencao`; suporte jurídico/reclamação/cancelamento ou IA indisponível; backup falhou.
- **P3 (só digest):** `pendentes_parecer` a acumular (esperado enquanto o cold está gated); métricas fora de tendência.

---

## 6. Rollout faseado — critérios em números

**Fase 0 — Fundações (sem agentes IA a agir).** Provisionar Polaris (timers com tetos de cgroup **reais**, §7) + deploy + smoke-test de emissão real TOConline (ATCUD + `document_hash_sum` numa FR de teste — resolve o risco fiscal L1/L2) + snapshots RNAL a persistir + widget consent-first no ar.
*Passagem:* 1 FR certificada real validada; 2 varrimentos nacionais consecutivos com snapshot fresco; dead-man switches verdes 7 dias; widget capta ≥ 1 lead opt-in real.

**Fase 1 — Ligar Angariador + Maestro (semi-manual).** Angariador enche `pendentes_parecer`; Maestro compila digest e opera o gate **manual** por lote. Cold só dispara depois do portão bloqueante: `CHECKAL_PARECER_RGPD_OK=True` + SMTP `getcheckal.com` + sair de `MODO_TESTE`. Até lá tudo em fila (motor construído e hard-gated).
*Passagem:* linter reprova **0** peças enviadas; opt-out **< 2%** e spam-complaint **< 0,1%** nos primeiros ~200 envios (cap 20/dia); evento→rascunho **< 72h** mediana; ≥ 1 verificação→pago atribuída ao cold.

**Fase 2 — Ligar Gestor + Sentinela.** Gestor assume onboarding ambíguo, relatório mensal, dunning, suporte IMAP; Sentinela audita serviço em timer independente.
*Passagem:* `requer_atencao` **< 5%** do volume, sem backlog > 48h; relatório mensal entregue a **100%** dos ativos; renovação D0 mensurável; Sentinela com **0** ativos sem cobertura e **0** falsos-positivos do breaker não-detetados.

**Promoção a auto-aprovação:** só risco mínimo e provado em N passagens. Envio em massa cold, publicação de páginas, emissão de faturas e cobranças **nunca** saem do gate.

**Invariante em todas as fases:** o backbone mantém-se determinista; os agentes supervisionam/redigem/orquestram e **chamam** as funções — nunca reimplementam nem forçam `pode_enviar_frio_global()`/`MODO_TESTE`.

---

## 7. Achados do red-team e como o desenho os resolve

### Legal-reputacional

| # | Achado (severidade) | Resolução no desenho |
|---|---|---|
| L1 | **Linter é ponto único de falha e não existe** (crítica). Toda a garantia legal assenta em `vet_texto`; se for stub, o dono aprova texto ilegal julgando-o filtrado. | **Bloqueante de rollout:** nenhum agente ativa antes de `compliance/linter.py` existir com bateria adversária (armadilhas: "está ilegal", "arrisca 4.000€", "o seu registo caducou", omissão de IA). O enqueue é **fail-closed**: import falhado ou `linter_ok!=True` → recusa e escala, nunca enfileira. `CampanhaPeca.linter_ok=False` por default → só peças com `True` entram no gate. Teste que prova que enqueue com linter ausente levanta erro e não insere. |
| L2 | **Copy fria atual já tangencia ameaça** (crítica): assunto individualizado + "exploração irregular 25–40k€" + "silêncio = cancelamento tácito". Angariador pode amplificar. | Congelar identificador individualizado no **assunto** quando o corpo menciona coima (R3 reprova coima a <2 frases de um identificador do destinatário); reescrever base retirando "exploração irregular"/"cancelamento tácito" (caracterizações jurídicas) → linguagem de serviço condicional ("se um AL não renovar…"). **Por config, o agente só altera corpo — nunca assunto/CTA — e sempre re-linted.** R1 reprova verbo de estado jurídico sobre "o seu/vosso" registo. |
| L3 | **Feed DGC vazio por omissão** (alta): `lista_dgc` default `()`; abrir gate sem feed fresco = cold para inscritos na oposição (Lei 41/2004 13.º-B). | Gate de código: o envio exige `lista_dgc` com timestamp < N dias **e** contagem > 0; lista vazia/estagnada → **fail-closed** (trata todos como opostos / recusa passagem). Angariador **escala** se detetar lista vazia em vez de prosseguir. Feed DGC consta como portão externo em §12 da compliance. |
| L4 | **Auto-resposta de suporte fora do gate e do linter** (alta): `cron_suporte` responde em tempo real; o Gestor só revê a posteriori — tarde demais. | Respostas passam pelo **mesmo linter** antes de enviar (fail-closed: reprova → escala, não responde). Auto-resposta restrita a categorias factual/administrativo com template; qualquer toque em estado de registo/seguro/regime legal **escala obrigatoriamente**, mesmo com confiança alta (`suporte._deve_escalar`, fail-safe). G4 reforçado **no ato do envio**, não só na composição. |
| L5 | **Transferência internacional sem gate de DPA** (alta): Claude CLI infere nos EUA; sem `CHECKAL_ANTHROPIC_DPA_OK` cada passagem é transferência sem base. | Criar **`CHECKAL_ANTHROPIC_DPA_OK` (default False)** que bloqueia por código o arranque de **qualquer** agente até o DPA estar assinado e registado. Tratar razão social de coletiva como **potencialmente pessoal** (ex.: "João Silva Unipessoal Lda", NIF 5) e minimizar também no Angariador (enviar nr+concelho+token de segmento, não a razão social livre, quando evitável). RoPA da transferência antes do go-live (art. 30.º; opção Bedrock `eu-central-1` remove o Cap. V). |
| L6 | **Opt-out do cold aponta para checkal.pt** (média): cruza a reputação que a separação de domínio pretendia proteger. | Servir opt-out e **todos** os links do canal frio a partir de `getcheckal.com/remover`. **R9 do linter reprova qualquer ocorrência de `checkal.pt` em texto de canal COLD.** Angariador não pode copiar assets/URLs de `COPY-VENDAS.md` (checkal.pt) para drafts frios. |
| L7 | **Alerta alucinado só apanhado post-hoc** (média): Sentinela é read-only e assíncrono; falso "cancelado" já saiu ao pagante. | Encadear a verificação de integridade (cross-check alerta↔fonte + G4/breaker) como **pré-condição síncrona** na composição de qualquer alerta forte, antes de entrar na fila. Alerta "cancelado" só enfileirável se breaker **E** cross-check confirmarem; senão degrada para "em verificação". |
| L8 | **Divulgação de IA prometida mas não nos templates** (média): art. 50 aplicável 02/08/2026. | Embutir a frase de divulgação nos templates redigidos por agente; **R5 do linter reprova (fail-closed)** qualquer peça outward-facing gerada por IA sem ela. Clarificar juridicamente o âmbito real do art. 50 para não sobre/sub-cumprir, mantendo o compromisso. |
| L9 | **Arquitetura de gate/fila é aspiracional** (média): `fila_revisao`/aprovações/subcomandos não existem. Lançar sem esta camada = trabalho autónomo sem o gate que o torna seguro. | Tratar a camada de governação (as 7 tabelas de §3.2 + subcomandos + token de aprovação + trilho em `EventoAgente`) como **pré-requisito bloqueante**, com testes que provem: (1) nenhum caminho de agente escreve fora de `RevisaoItem`; (2) aprovação exige linha com `decidido_por` distinto de `agente_origem`; (3) ação externa só dispara com aprovação válida **E** gate de código aberto. Nenhum timer ativa antes disto verde. |

### RAM / autonomia / irreversível

| # | Achado (severidade) | Resolução no desenho |
|---|---|---|
| R-1 | **cgroup ineficaz** (ALTA): correr agentes via `docker compose exec` num container partilhado põe os limites no processo cliente do `docker exec`, **não** no `claude -p` real (contabilizado no cgroup do container). Os caps de RAM prometidos são inócuos → reproduz o OOM. | **Não** correr via `docker compose exec`. Ou (a) `docker compose run --rm --memory=X --cpus=Y` por invocação, ou (b) **unidade systemd nativa** com `MemoryMax/MemoryHigh/CPUQuota` reais + `Delegate`, ou (c) `MemoryMax` no próprio container no compose. **Validar com `systemd-cgls` / `cat /sys/fs/cgroup/.../memory.max`** que o processo do `claude -p` cai mesmo no cgroup limitado. Sem isto, o pilar "restrição dura de RAM" fica por cumprir — é critério de Fase 0. |
| R-2 | **Overlap & timeout** (ALTA): faltam `TimeoutStartSec/RuntimeMaxSec` e lock → passagens sobrepostas e processos pendurados. | Template `checkal-agente@.service` traz `RuntimeMaxSec=900` + `TimeoutStartSec=960` + `ConditionPathExists=!/run/checkal/%i.lock` + `flock -n` no wrapper (dupla camada anti-reentrância). Lease de 15 min na fila SQLite fecha o overlap do drain. |

---

### Invariante de fecho

Tudo é **reversível-até-ao-gate e auditável**. Os executores fazem trabalho autónomo até ao portão; só o Maestro converte isso em ação irreversível externa; **quem propõe nunca é quem aprova**. Nenhum teto de custo ou alarme altera gates de compliance/segurança — `pode_enviar_frio_global`, `CHECKAL_MODO_TESTE`, `CHECKAL_PARECER_RGPD_OK`, `CHECKAL_ANTHROPIC_DPA_OK` só o dono os liberta. O backbone determinista manda; os agentes redigem, supervisionam e orquestram por cima. O portão é código, não disciplina.