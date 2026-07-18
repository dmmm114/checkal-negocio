# PROMPT-MESTRE PARA O FABLE (ultracode) — CheckAL · agentes autónomos no Polaris

> Cola isto no Claude fable em ultracode para CONSTRUIR os agentes. **Lê primeiro a ADENDA autoritativa; em conflito, a ADENDA manda.** Detalhes de pagamento em `PAGAMENTOS-IFTHENPAY.md`.

---

## ADENDA AUTORITÁRIA (decisões do dono, pós-desenho)

# DECISÕES DE EXECUÇÃO — autoritativas (pós-workflow)

> Estas decisões foram tomadas pelo dono **depois** de o workflow de desenho ter corrido.
> **Em qualquer conflito com o resto do pacote (arquitetura, specs, prompt-mestre), MANDAM ESTAS.**
> Data: 2026-07-18.

## 1. Pagamento a partir do email — Opção A (gerar ao vivo no clique)
O email cold **nunca** leva a referência Multibanco crua. Leva **dois** CTA: **"Pagar já"** e
**"Fazer o check grátis"** (alternativa de menor compromisso, contraria a suspeita de esquema).
O **"Pagar já"** aponta para uma **URL assinada e com validade** → página própria
`checkal.pt/pagar?t=<token>`. O token referencia `{campanha, segmento, nr_registo?, plano_sugerido}`
e **não contém qualquer dado pessoal**.

**Porquê A e não pré-gerar:** (a) o valor da referência é fixo na geração e o plano só se sabe depois
de o cliente escolher; (b) o MB Way exige o telemóvel do cliente (só se obtém numa página); (c) sem
página não se captam **NIF + T&C** — logo não há fatura-recibo válida nem contrato; (d) pré-gerar
milhares de referências para uma taxa de pagamento ~0,5% cria refs pendentes, gestão de validade e um
mapa ref→destinatário de todos. A chamada ao IfThenPay é sub-segundo — a Opção A não perde nada.

## 2. Página `/pagar` — própria, em checkal.pt, "clean" e a transmitir SEGURANÇA (requisito, não estética)
- HTTPS/cadeado; **identificação completa** (Cosmic Oasis, Lda. · NIPC · morada) bem visível.
- "Serviço privado e independente" explícito; **marcas oficiais Multibanco / MB Way**; nota
  "pagamento processado por **IfThenPay**".
- **T&C visíveis + captura de NIF + aceitação** antes do pagamento; **fatura prometida no ecrã**.
- **Sem dark patterns.** Objetivo declarado: **matar a objeção "isto cheira a esquema"** (objeção #4
  do próprio site) e passar confiança a um cliente de 45–65 anos.

## 3. Cobrança = IfThenPay (build NOVO)
As chaves já estão previstas na config (`IFTHENPAY_MB_KEY`, `IFTHENPAY_MBWAY_KEY`,
`IFTHENPAY_ANTIPHISHING_KEY`, `IFTHENPAY_BASE`) **mas a integração não está construída** (o que existe é
Stripe Payment Links). Métodos na página: **Referência Multibanco + MB Way + Transferência (IBAN)**.
- **MB ref / MB Way** confirmam por **callback** (com antiphishing key) → ativação automática.
- **Transferência** = reconciliação **semi-manual**: o **Gestor-de-Cliente** marca "por casar" até bater.
- Detalhe de build em `PAGAMENTOS-IFTHENPAY.md`.

## 4. Faturação = TOConline, série **CKL** separada
Mesma empresa (Cosmic Oasis, mesmo NIF); série **nova** registada na AT →
`TOCONLINE_SERIES_ID`/`TOCONLINE_SERIES_PREFIX`. Segrega a contabilidade da Radar Marca dentro do
mesmo NIF (bom para gestão e para um futuro *asset deal*). O código já tem a guarda `SerieNaoConfigurada`
(não emite sem série). **Stripe fica secundário/opcional** — não é preciso para a via cold-direto.
**Antes da 1.ª fatura real:** smoke-test TOConline para fechar os ~15 campos `TODO[ASSUMIDO]`.

## 5. Renovação anual = nova referência/MB Way a D-30 (sem cartão guardado)
Mais limpo e seguro para o cliente low-touch (não fica com dados de cartão em lado nenhum). O
**Gestor-de-Cliente** trata do ciclo de renovação/dunning por referência.

## 6. Domínios
`checkal.pt` **já comprado** (marca/site/landing/faturas/selo/página `/pagar`). O **envio do cold**
continua em **domínio separado** (getcheckal.com ou equivalente) para proteger a reputação de
`checkal.pt` — esse domínio de envio **ainda precisa de ser garantido**.

## 7. Canais e IA (recap das decisões do dono)
- **Cold a pessoas coletivas PRIMEIRO**; **cartas parqueadas** (o build não as ativa); **SEM** canal de
  contabilistas/parcerias — angariação **direta**.
- **IA = Claude CLI no Polaris** (headless, single-shot, systemd, `MemoryMax`).
  ⚠️ **Caveat encodado:** o Claude CLI **não** localiza dados na UE (inferência na API da Anthropic,
  EUA). Fechar **DPA da Anthropic** + **minimização**: o modelo **nunca** vê campos pessoais de
  singular; dados pessoais só quando **opted-in**.

## 8. Gate humano — inalterável
Aprovação humana em **toda a ação irreversível externa** (envio em massa, publicação, emissão de
fatura, cobrança). Cold **gated por omissão** (`CHECKAL_PARECER_RGPD_OK=False`,
`CHECKAL_MODO_TESTE=True`). Os agentes são autónomos **até** ao gate.


---

## PROMPT-MESTRE DETALHADO (do desenho)

A verificação do repo confirma os pontos-chave (manage.py com dispatch `_JOBS` de arg único a estender; gates em `config.py:143/250/305`; `COIMA`:161, `CONSERVACAO_PROSPECT_MESES=6`:190, `CAMPANHA_JANELA_H=72`:266, `CAMPANHA_CAP_DIARIO=20`:267, `COLD_FROM` getcheckal.com:261; `obter_escalador` Telegram em `suporte.py:431`; template systemd único `deploy/systemd/checkal@.service`; tabelas de domínio até `optouts`). Segue o prompt-mestre, pronto a colar.

---

# PROMPT-MESTRE — CONSTRUÇÃO DO ENXAME DE AGENTES CheckAL (colar no Claude Fable / Ultracode)

Vais construir, **dentro do repositório CheckAL já existente**, a camada de 4 agentes single-shot (MAESTRO, ANGARIADOR, GESTOR-DE-CLIENTE, SENTINELA-SERVIÇO) que **supervisiona, redige e orquestra por cima** do backbone determinista já construído — **sem nunca o reimplementar nem o contornar**. Lê primeiro este prompt inteiro. Não escrevas uma linha de código antes de teres lido os ficheiros de grounding listados em §1. Trabalha em TDD: teste primeiro, vê-o vermelho, implementa, vê-o verde. Nada de atalhos.

---

## 0. CONTEXTO (o que é o CheckAL, em 6 linhas)

Subscrição (49 €/ano) que vigia o registo RNAL, o seguro obrigatório e os regulamentos municipais de cada Alojamento Local português, com alertas interpretados por IA. Operação 100 % automatizada, dono **ausente**, veículo Cosmic Oasis, Lda. O software-núcleo **já está 100 % construído e com testes verdes** (varrimento RNAL + diff, regulatório, onboarding, dunning, faturação certificada TOConline, breaker de cancelamentos, núcleo de compliance de cold, website consent-first). O que falta — e é o teu único mandato — é a **camada de governação/agentes** que converte trabalho autónomo numa decisão diária de baixo esforço para o dono, atrás de um portão human-in-the-loop.

Ambiente de produção: **Polaris** (Ubuntu, home server, Tailscale). **RESTRIÇÃO DURA DE RAM: já houve OOM kill por sessões Claude Code persistentes.** Logo: **NENHUM processo persistente.** Cada agente é uma invocação `claude -p` single-shot, headless, lançada por systemd timer, que faz o trabalho, escreve na BD/fila e **SAI**.

---

## 1. FICHEIROS DE GROUNDING — LÊ ANTES DE CONSTRUIR (todos existem, caminhos relativos à raiz do repo)

- `CLAUDE.md` — decisões fechadas (não relitigar).
- `checkal/app/config.py` — os gates e constantes canónicas: `pode_enviar_frio_global()` (linha ~305), `CHECKAL_MODO_TESTE` (143, default `True`), `CHECKAL_PARECER_RGPD_OK` (250, default `False`), `cold_smtp_ativo()` (295), `COLD_FROM` (261, getcheckal.com), `COIMA` (161), `CAMPANHA_JANELA_H=72` (266), `CAMPANHA_CAP_DIARIO=20` (267), `CONSERVACAO_PROSPECT_MESES=6` (190), `telegram_ativo()` (285).
- `checkal/app/models.py` — `Base`, alias `_TS`, convenções de portabilidade; tabelas de domínio existentes (até `optouts`, linha 345). **Nunca redefinir** `Lead` (consent_alertas/consent_ofertas granular já existem) nem `OptOut`.
- `checkal/app/campanhas/{gatilhos,segmentacao,motor,cold_email}.py` — `detetar_gatilhos`, `segmentar`, `compor_email_frio`, `pode_enviar_frio`, `RascunhoFrio`, constantes `MOTIVO_*/ORIGEM_*/RAZAO_*`, seam de opt-out RFC 8058.
- `checkal/app/compliance/{nif,email,minimizacao,optout}.py` — `e_enderecavel`, `e_generico`, `filtrar_enderecaveis`, `filtrar_optout`, `RATIONALE.md`.
- `checkal/app/ia/{guardrails,validacao}.py` — `validar_nao_prescritivo`, `GUARDRAILS_VERSAO`, `_RE_CITACAO`, `validar_alerta`, `ResultadoValidacao` (molde da saída do linter).
- `checkal/app/emails/prospeccao.py` e `checkal/app/emails/transacional.py` — copy fria e template `relatorio_mensal` (a corrigir, ver §4-RT).
- `checkal/app/suporte.py` — `obter_escalador()` (linha 431, o único envio Telegram permitido, já live-gated), `_deve_escalar`.
- `checkal/manage.py` — dispatch `_JOBS` (dict de arg único). **Vais estendê-lo** para aceitar subcomandos com flags.
- `checkal/app/relatorio.py`, `checkal/app/onboarding.py`, `checkal/app/dunning.py`, `checkal/app/breaker.py` — as funções que o GESTOR/SENTINELA **chamam**.
- `deploy/systemd/checkal@.service` — o template systemd existente (referência de estilo).
- `checkal/app/SPEC-FASE1-AQUISICAO.md` — spec consent-first parqueada.

---

## 2. PRINCÍPIOS INVIOLÁVEIS (encodar como código, não como disciplina)

1. **Sem processos persistentes.** Cada agente = `claude -p` single-shot por systemd timer com `MemoryMax`/`MemoryHigh`/`CPUQuota`/`OOMScoreAdjust`/`RuntimeMaxSec` + `flock` anti-reentrância. Faz o trabalho, escreve, SAI.
2. **Motor IA = Claude CLI no Polaris.** CAVEAT a encodar: o Claude CLI envia prompts para a **API da Anthropic (inferência nos EUA)** — não mantém dados na UE. Logo os agentes operam sobre dados **agregados/genéricos/opted-in**. Qualquer dado pessoal de singular que chegue ao modelo exige o **DPA comercial da Anthropic** (novo gate `CHECKAL_ANTHROPIC_DPA_OK`, default `False`).
3. **O backbone determinista continua a mandar.** Os agentes **CHAMAM** as funções existentes via subcomandos `manage.py`; **nunca** reimplementam a lógica, **nunca** fazem SQL cru, **nunca** forçam/contornam `pode_enviar_frio_global()`, `CHECKAL_MODO_TESTE`, `CHECKAL_PARECER_RGPD_OK`, `COLD_SMTP_*`.
4. **Reversível-até-ao-gate.** Toda a ação irreversível externa (envio em massa cold/nurture, publicação de página, emissão de fatura, cobrança, post público) passa pela fila de revisão + aprovação 1-clique do MAESTRO. **Quem PROPÕE (executores) nunca é quem APROVA (dono via MAESTRO).** O MAESTRO gera o token; o **dono** aprova.
5. **Minimização dura.** Portão do sujeito = **NIF, não o prefixo do email**: só coletiva (1.º dígito ∈ {5,6}) é endereçável a cold; singular/ENI **nunca**, mesmo com `geral@`. O agente vê só estatísticas de segmento + email genérico coletivo; **nunca** campos pessoais de singular. Nenhuma lista de envio é materializada; nenhum scraping.
6. **Linter determinista fail-closed.** TODO o texto outward-facing produzido por agente passa pelo linter **antes** de ser aprovável. Import falhado ou `linter_ok != True` ⇒ **recusa e escala**, nunca enfileira.
7. **Fronteira dura de domínio de email.** Cold vive em **getcheckal.com** (`COLD_FROM`); nurture/transacional em **checkal.pt/Resend**. Nunca misturar no mesmo contexto de modelo; nunca importar `app.envio`/`RESEND_*`/`EMAIL_FROM` no canal frio; **todos** os links do cold (opt-out incluído) saem de getcheckal.com.
8. **Língua: PT-PT** em todo o output. Marca CheckAL, selo "CheckAL ✓ — AL Verificado", tagline "O teu AL? Check.". Estados: "passou no check ✓ / falhou o check 🔴".

---

## 3. FICHEIROS A CRIAR (a lista exata — nada a mais, nada a menos)

### 3.1 Schema aditivo — `checkal/app/models_swarm.py`
Importado a seguir a `models.py` para partilhar `Base.metadata`. Só tipos portáveis (Integer, Text, Date, Boolean, JSON, DateTime(timezone=True)); **dinheiro em Integer de cêntimos**; reutiliza `Base` e `_TS`. Tabelas (usa o schema canónico fornecido pelo HARNESS(db) verbatim, incluindo docstrings e `__table_args__`/índices/UNIQUE):
- `EventoAgente` (`eventos_agente`) — journal append-only do enxame.
- `Campanha` (`campanhas`) + `CampanhaPeca` (`campanha_pecas`) — persiste o que hoje só vive em memória (`RascunhoFrio`); UNIQUE `(campanha_id, nif, passo)`.
- `RevisaoItem` (`revisao_itens`) — a fila de aprovação humana 1-clique; guarda `linter_ok`+`linter_achados`, aponta por `ref_tipo/ref_id`, **não** duplica conteúdo. **Acrescenta** os campos `token_aprovacao: Text|None` e `camada_risco: Integer` (1 mínimo … 4 máximo) exigidos pelo MAESTRO.
- `ContactoColetiva` (`contactos_coletiva`) — ledger de outreach keyed por NIF.
- `Fatura` (`faturas`) — ledger de faturas-recibo; dois UNIQUE de idempotência (`stripe_invoice_id`, `ix_fatura_id`).
- `MetricaRollup` (`metricas_rollup`) — rollups por (dia, canal, campanha, métrica); UNIQUE para upsert idempotente.
- `SupressaoNif` (`supressao_nif`) — supressão a nível de identidade legal (permanente, nunca apagada pela limpeza).
- **Tabelas de governação adicionais** (as specs dos agentes referem-nas): `Aprovacao` (`aprovacoes`) — linha por decisão do dono, autor ≠ aprovador; `Escalacao` (`escalacoes`); `AgenteExecucao` (`agente_execucoes`) — iniciado/terminado/estado/exit_code/tokens + flag `retry_pedido`/`backoff_s`; `Digest` (`digests`) — corpo_md + metricas_json + enviado_em; `CustoLlm` (`custo_llm`) — dia/agente/input_tokens/output_tokens/custo_eur.

> Nota: `fila_revisao` mencionada nas specs dos executores **é** a `revisao_itens` — usa um único nome (`revisao_itens`) e não dupliques. Documenta o alias.

### 3.2 Migração — `checkal/migrations/00X_swarm.py` (ou o mecanismo de migração já usado no repo; deteta-o primeiro)
Cria todas as tabelas novas de forma **aditiva e idempotente** (SQLite dev / Postgres prod). Não toca em nenhuma tabela existente. Se o repo usa `Base.metadata.create_all`, adiciona um passo que importa `models_swarm`. Testa que correr a migração duas vezes não falha.

### 3.3 Linter determinista — `checkal/app/compliance/linter.py`
Função pura, sem I/O de rede, conservadora (na dúvida REJEITA). Segue a spec HARNESS(linter) à letra:
- `lint(peca: PecaOutward) -> ResultadoLint`. `PecaOutward` (frozen): `texto`, `canal: Canal{ALERTA, COLD, NURTURE_TRANSACIONAL, PAGINA_PUBLICA, ONE_PAGER, RELATORIO}`, `url_fonte`, `excerto`, `gerado_por_ia`, `tem_optout_carimbado`.
- `ResultadoLint(aprovado, violacoes, versao="LINTER_VERSAO")` + `Violacao(regra, severidade{BLOQUEIA|AVISA}, trecho, razao)`. `aprovado = not any(v.severidade is BLOQUEIA ...)`.
- **Remove citações antes de varrer** (reutiliza a técnica de `guardrails._RE_CITACAO`).
- Regras: **R1** ilegalidade/incumprimento/sem seguro; **R2** delega em `validar_nao_prescritivo`; **R3** coima como ameaça individualizada (permite só condicional impessoal ancorado em `config.COIMA`); **R4** link de fonte oficial; **R5** divulgação de IA (AI Act art. 50); **R6** grounding via `validar_alerta`; **R7** disclaimer "informação, não aconselhamento"; **R8** opt-out 1-clique; **R9** rodapé RGPD + remetente getcheckal.com (só cold). Despacho por `Canal` conforme a tabela §3 da spec.
- **Regra extra (red-team):** no canal COLD, BLOQUEIA qualquer ocorrência de `checkal.pt` (deve ser getcheckal.com); BLOQUEIA coima a < 2 frases de um identificador do destinatário; BLOQUEIA verbo de estado jurídico ("caducou/ilegal/irregular") sobre "o seu/o vosso" registo.
- Versiona `LINTER_VERSAO` como `GUARDRAILS_VERSAO`. Reutiliza `validar_alerta`/`validar_nao_prescritivo` — **não** os reimplementa.

### 3.4 Fila de revisão + drain — `checkal/app/swarm/fila.py`
API determinista sobre `revisao_itens`/`campanha_pecas`/`contactos_coletiva`:
- `enfileirar(session, *, tipo, ref_tipo, ref_id, resumo, risco, agente_origem, peca: PecaOutward) -> RevisaoItem` — **corre o linter internamente e só insere se `aprovado=True`**; caso contrário levanta e devolve as violações para escalar (**FAIL-CLOSED**; se o import do linter falhar, recusa).
- `drain(session, agente, limite)` — padrão lease/backoff da fila de trabalho (BEGIN IMMEDIATE, marca `a_correr`+lease, processa, `feito`/`falhado`/`morto` com backoff exponencial); cap por passagem alinhado com `CAMPANHA_CAP_DIARIO`.
- `gerar_token(session, item_id)` — gera `token_aprovacao` (MAESTRO); **não aprova**.
- `aprovar(session, item_id, token, decidido_por)` — só o caminho do dono; escreve linha em `aprovacoes` com autor ≠ aprovador; valida token; só então marca `aprovado`.
- Regra dura testada: **nenhum caminho de agente escreve `estado='aprovado'`**; só `aprovar()` (dono) o faz.

### 3.5 Tetos de custo / escalação — `checkal/app/swarm/tetos.py`
- `registar_custo(session, agente, usage_json)` — parse do `usage` do `--output-format json`, estima custo pela tabela de preços do modelo (Haiku triagem / Sonnet redação), grava em `custo_llm`.
- `teto_atingido(session, dia) -> bool` — soma o gasto do dia vs `TETO_DIARIO_EUR` (nova config, ex. 5 €/dia + sub-tetos por agente).
- `flag_pausa_llm()` / `pausa_llm_ativa()` — cria/lê `/run/checkal/PAUSA_LLM` (flag-ficheiro); os crons deterministas continuam, só os passos LLM pausam. **Nunca toca gates de segurança.**
- `escalar(session, *, severidade, agente, mensagem)` — escreve em `escalacoes` (+ `eventos_agente`); o MAESTRO consolida.

### 3.6 Subcomandos `manage.py` (estender o dispatch — hoje é arg-único; passa a aceitar flags)
Refatora `main()` para dispatch por subcomando com `argparse`, **preservando** os jobs existentes (`varrimento|dre|dunning|suporte|backup|token`). Adiciona a **allow-list exata** que cada agente usa (nada de shell livre, nada de SQL cru, nada de `python -c`):

**MAESTRO** (ligações read-only nos de leitura; escrita estreita só a tabelas de governação):
- `maestro-run --modo <governanca|digest>` — o **runner determinista** que encadeia os executores em **sequência** (nunca paralelo — RAM) com retry+backoff, regista em `agente_execucoes`, pinga Healthchecks, e SÓ DEPOIS invoca o `claude -p` do MAESTRO. O LLM **não faz spawn**.
- `maestro-metricas`, `maestro-saude`, `maestro-fila`, `maestro-escalacoes` — devolvem **JSON agregado**, nada escrevem, abrem BD read-only (`PRAGMA query_only`).
- `maestro-digest --ficheiro <path.json>` (persiste `digests` + envia via `suporte.obter_escalador`), `maestro-escalar --sev <...> --msg <...>`, `maestro-retry --agente <...> --backoff <s>`, `maestro-gate-token --fila-id <id>`.

**ANGARIADOR:**
- `angariador detetar` — corre `detetar_gatilhos`+`segmentar`+`compor_email_frio`, aplica o linter, escreve `cold_drafts` em `revisao_itens` (estado `pendente`), devolve JSON com **estatísticas de segmento agregadas** + drafts (só campos coletivos).
- `angariador lint --stdin`; `angariador enfileirar --tipo <t> --stdin` (linter obrigatório, falha se `linter_ok=False`); `angariador estado` (marcadores de idempotência).

**GESTOR-DE-CLIENTE:**
- `gestor onboarding-tarefas`, `gestor relatorio-mensal-compor` (compõe + passa pelo linter + enfileira para o gate; **não envia em massa** sem aprovação), `gestor dunning-estado`, `gestor suporte-triar` (passa a resposta pelo **mesmo linter fail-closed** antes de enfileirar/enviar; jurídico/reclamação/cancelamento/confiança baixa ⇒ escala).

**SENTINELA-SERVIÇO** (read-only + escrita só a `eventos_agente`/`escalacoes`):
- `sentinela verificar` — freshness do varrimento vs SLA, cross-check alerta↔fonte oficial (deteção de alucinação/falso "cancelado"), confirmação do breaker, cobertura (0 clientes ativos sem snapshot recente). Emite achados; **não corrige, sem ação externa**.

Todos os subcomandos de escrita usam transação estreita e **não podem tocar** `clientes`/`alertas`/`registos`/`faturas`/`leads`.

### 3.7 Prompts operacionais — `checkal/prompts/{maestro,angariador,gestor,sentinela}.txt`
Um por agente, PT-PT, montados read-only no container. Usa **verbatim** os `operating_prompt` fornecidos nas SPECS DOS AGENTES (o do MAESTRO está completo; para os restantes, deriva do respetivo `mission`/`hard_limits_hitl`/`inputs`/`outputs` mantendo a mesma estrutura: identidade e fronteiras → o que lê → o que decide → o que escreve → limites duros → formato de saída → regra final "na dúvida, escala").

### 3.8 Units systemd — `deploy/systemd/`
Um `.service` templado + `.timer` por agente, seguindo HARNESS(obs). **Cria**:
- `checkal-agente@.service` (template genérico) **ou** um `.service` por agente — escolhe o que melhor encaixa com o `checkal@.service` existente. Campos obrigatórios: `Type=oneshot`, `MemoryMax`, `MemoryHigh`, `CPUQuota`, `TasksMax`, `OOMScoreAdjust`, `OOMPolicy=kill`, `RuntimeMaxSec=900`, `TimeoutStartSec`, `ConditionPathExists=!/run/checkal/%i.lock`, `EnvironmentFile=/etc/checkal/agente.env`.
- **⚠️ CORREÇÃO RED-TEAM (crítica):** os limites de cgroup **têm de recair no processo real do `claude -p`**, não num cliente `docker exec` de um container partilhado. Usa `docker compose run --rm --memory=<X> --cpus=<Y>` por invocação **ou** unidade systemd nativa com `MemoryMax` real + `Delegate` **ou** `MemoryMax` no próprio serviço do container. Documenta em `deploy/systemd/README.md` como validar com `systemd-cgls` / `cat /sys/fs/cgroup/.../memory.max` que o `claude -p` cai mesmo no cgroup limitado.
- `.timer` por agente, **descorrelacionados** (`RandomizedDelaySec`, `Persistent=true`): MAESTRO digest 07:50 + governança 11:50/15:50/19:50; ANGARIADOR 03:30 seg/qui + 12:00 diário; GESTOR dunning/relatório 07:15 + suporte `*:0/15`; SENTINELA `06,12,18,23:40` (timer próprio, fora de fase do MAESTRO).
- `checkal-reset-pausa-llm.timer` (meia-noite) que limpa `/run/checkal/PAUSA_LLM`.

### 3.9 Wrapper — `deploy/bin/correr-agente.sh`
Faz, por esta ordem: `flock -n` (sai 0 se falhar) → ping START Healthchecks → verifica `/run/checkal/PAUSA_LLM` (se existe e o job usa LLM, aborta com `/log`, sai) → verifica `teto_atingido` → corre `claude -p ... --output-format json --max-turns N` com `timeout` guarda-costas → `registar_custo` → ping final sucesso/`/fail` com stderr.

### 3.10 Documentação — `AGENTES-ENXAME.md` (raiz) + `deploy/systemd/README.md`
Arquitetura do loop fechado (Sentir→Decidir→Redigir→Aprovar→Agir→Medir→Aprender), a tabela de tabelas novas, a matriz de gates, o rollout faseado (§7), a lista de alarmes P1/P2/P3, e o procedimento de instalação/validação de cgroups.

---

## 4. CORREÇÕES OBRIGATÓRIAS DO RED-TEAM (não são opcionais — são bloqueantes)

- **RT-linter fail-closed:** nenhum agente ativável antes de `linter.py` existir com bateria adversária verde. `enfileirar` recusa se o linter faltar/reprovar. Teste que prova que enqueue com linter ausente **levanta erro e não insere**.
- **RT-copy fria:** corrige `emails/prospeccao.py` — retira "exploração irregular" e "cancelamento tácito" (caracterizações jurídicas do destinatário), substitui por linguagem de serviço genérica e condicional; separa identificador do destinatário do valor de coima (nunca na mesma frase). O agente **não pode alterar assunto/CTA**, só corpo, e sempre re-linted.
- **RT-DGC fail-closed:** novo gate — o envio exige `lista_dgc` carregada com timestamp < N dias e contagem > 0; lista vazia/estagnada ⇒ trata como se todos estivessem opostos (recusa). O ANGARIADOR **escala** se detetar `lista_dgc` vazia.
- **RT-suporte no gate:** as respostas do `cron_suporte`/`gestor suporte-triar` passam pelo **mesmo linter** antes de enviar; qualquer resposta que toque estado de registo/seguro/regime legal **escala obrigatoriamente**, mesmo com confiança alta. G4 reimposto no ato do envio.
- **RT-DPA gate:** novo `CHECKAL_ANTHROPIC_DPA_OK` (default `False`) que **bloqueia por código o arranque de qualquer agente** enquanto o DPA comercial não estiver assinado. Trata nome de coletiva como potencialmente pessoal e minimiza (preferir nr+concelho+token de segmento à razão social livre quando evitável).
- **RT-fronteira de domínio:** opt-out e todos os links do cold saem de **getcheckal.com**; regra do linter reprova `checkal.pt` em canal frio.
- **RT-Sentinela pré-envio:** encadeia o cross-check alerta↔fonte + G4/breaker como **pré-condição síncrona** na composição de qualquer alerta forte antes de entrar na fila; alerta "cancelado" só enfileirável se breaker **E** cross-check confirmarem, senão degrada para "em verificação".
- **RT-divulgação de IA (art. 50):** embute a frase de divulgação nos templates redigidos por agente; o linter reprova (fail-closed) qualquer peça outward-facing gerada por IA sem ela.
- **RT-relatório mensal (RT):** `transacional.py`/`relatorio_mensal` ganha a divulgação de IA; o envio em massa passa pelo gate 1-clique.

---

## 5. O QUE **NÃO** CONSTRUIR / **NÃO** MEXER

- **Não** alteres a lógica do backbone determinista (rnal ingest+diff, regulatório, onboarding, dunning, faturação, breaker, núcleo de compliance). Só **corriges a copy** em `prospeccao.py`/`transacional.py` (RT) e **estendes** `manage.py`. Nada mais no domínio.
- **Não** redefinas `Lead`, `OptOut`, nem qualquer tabela existente. O schema novo é **aditivo**.
- **Não** construas o canal de **cartas** — fica **parqueado e gated** (`ProspetoCarta` já existe; não o ativas).
- **Não** construas canal de contabilistas/parcerias — angariação é **direta** (decisão do dono).
- **Não** ligues o **cold**: `CHECKAL_MODO_TESTE=True`, `CHECKAL_PARECER_RGPD_OK=False`, `CHECKAL_ANTHROPIC_DPA_OK=False` ficam nos defaults. Tudo o que os agentes produzem cai em `pendente`/`pendentes_parecer`. Nenhum SMTP cold configurado.
- **Não** dês a nenhum agente permissão de escrever em `clientes`/`alertas`/`registos`/`faturas`/`leads`, nem de flipar gates, nem shell livre, nem WebFetch/WebSearch, nem SQL cru.
- **Não** crontab; **só** systemd timers.

---

## 6. LIVE-GATED + TESTES VERDES (condição de aceitação dura)

- **Tudo live-gated:** nada envia/cobra/publica/liga SMTP/IMAP sem (a) chaves reais **e** (b) gate aberto **e** (c) aprovação 1-clique. Sob `CHECKAL_MODO_TESTE=True` (default) todos os seams de rede devolvem `None`. O suite completo corre **offline, sem chaves, sem rede**.
- **TDD:** cada módulo novo tem testes-espelho em `checkal/tests/` (segue o estilo de `test_ia_guardrails.py`/`test_ia_validacao.py`). Casos-armadilha obrigatórios do linter: "está ilegal", "arrisca 4.000 €", "o seu registo caducou", coima colada ao nome do destinatário, `checkal.pt` em canal cold, omissão de divulgação de IA, valor de coima fora de `config.COIMA`.
- **Os 1344 testes existentes têm de continuar verdes, 0 skips.** Corre a suite inteira antes de declarares conclusão. Não marques nada como passado sem veres o output verde (evidência antes de afirmação).
- Testes de invariantes de governação: (1) nenhum caminho de agente escreve `estado='aprovado'` fora de `aprovar()`; (2) `aprovar` exige linha em `aprovacoes` com autor ≠ aprovador; (3) ação externa só dispara com token válido **E** gate de código aberto; (4) `enfileirar` com linter ausente/reprovado não insere; (5) migração idempotente (corre 2× sem falhar); (6) DGC vazia ⇒ recusa; (7) DPA gate fechado ⇒ agente não arranca.

---

## 7. ORDEM DE CONSTRUÇÃO FASEADA (não saltes fases; cada uma termina verde)

**Fase A — Schema + migração.** `models_swarm.py` + migração aditiva idempotente + testes de criação/portabilidade. **Gate de passagem:** tabelas criam em SQLite e (mock) Postgres; migração 2× OK; suite existente continua verde.

**Fase B — Linter.** `compliance/linter.py` + bateria adversária completa (todos os casos-armadilha). **Gate:** 0 falsos "aprovado" nos casos-armadilha; R1–R9 + regras RT verdes. **Bloqueante:** nenhuma fase seguinte arranca sem isto.

**Fase C — Fila + tetos + gates novos.** `swarm/fila.py`, `swarm/tetos.py`, `CHECKAL_ANTHROPIC_DPA_OK`, gate DGC fail-closed, correções de copy RT. **Gate:** invariantes de governação (§6) verdes; `enfileirar` fail-closed provado.

**Fase D — Subcomandos `manage.py`.** Estende dispatch; implementa os subcomandos por agente chamando o backbone. **Gate:** cada subcomando devolve JSON correto sobre fixtures; nenhum escreve em domínio; leituras são read-only.

**Fase E — Prompts + wrapper + systemd.** `prompts/*.txt`, `correr-agente.sh`, units `.service`/`.timer` com cgroups **reais** (correção RT), timer de reset da pausa. **Gate:** `systemd-analyze verify` passa; README documenta a validação de cgroup; **timers criados mas ficam `disabled` até o dono os ativar** (não os habilites tu).

**Fase F — Doc + suite final.** `AGENTES-ENXAME.md`, `deploy/systemd/README.md`; corre a suite completa. **Gate:** toda a suite verde, 0 skips; checklist §8 toda ✓.

---

## 8. CHECKLIST DE ACEITAÇÃO (tem de estar tudo ✓ para declarar conclusão)

**Schema & migração**
- [ ] `models_swarm.py` importado após `models.py`; só tipos portáveis; dinheiro em cêntimos; `Lead`/`OptOut` intactos.
- [ ] Todas as tabelas novas criadas (eventos_agente, campanhas, campanha_pecas, revisao_itens, contactos_coletiva, faturas, metricas_rollup, supressao_nif, aprovacoes, escalacoes, agente_execucoes, digests, custo_llm); UNIQUE/índices de idempotência presentes.
- [ ] Migração aditiva e idempotente (corre 2× sem erro); nenhuma tabela existente alterada.

**Linter (bloqueante)**
- [ ] `compliance/linter.py` puro, sem rede, fail-closed; reutiliza `validar_alerta`/`validar_nao_prescritivo`/`_RE_CITACAO`.
- [ ] R1–R9 + regras RT (checkal.pt em cold, coima colada a identificador, verbo de estado jurídico sobre "o seu registo") verdes.
- [ ] Casos-armadilha ("está ilegal", "arrisca 4.000 €", "o seu registo caducou", coima fora de `config.COIMA`, sem divulgação IA) todos BLOQUEIA.
- [ ] `LINTER_VERSAO` versionado.

**Fila, gates e governação**
- [ ] `enfileirar` corre o linter e só insere se `aprovado=True`; import falhado ⇒ recusa+escala (teste prova que não insere).
- [ ] Nenhum caminho de agente escreve `estado='aprovado'`; só `aprovar()` (dono) o faz, com autor ≠ aprovador em `aprovacoes`.
- [ ] Ação externa só dispara com token válido **E** gate de código aberto.
- [ ] `CHECKAL_ANTHROPIC_DPA_OK` (default False) bloqueia arranque de qualquer agente.
- [ ] Gate DGC fail-closed: lista vazia/estagnada ⇒ recusa; ANGARIADOR escala.
- [ ] Tetos: `custo_llm` registado; `TETO_DIARIO_EUR` cria `/run/checkal/PAUSA_LLM`; **gates de segurança nunca tocados** pelos tetos.

**Copy & fronteiras**
- [ ] `prospeccao.py` sem "exploração irregular"/"cancelamento tácito"; identificador do destinatário nunca na mesma frase que a coima; assunto/CTA imutáveis pelo agente.
- [ ] Todos os links do cold (opt-out incluído) em getcheckal.com; nunca `app.envio`/`RESEND_*` no canal frio.
- [ ] Divulgação de IA (art. 50) embutida nos templates redigidos por agente; linter reprova a ausência.
- [ ] Respostas de suporte passam pelo linter antes de sair; jurídico/reclamação/cancelamento/confiança baixa escalam.
- [ ] Sentinela: alerta "cancelado" só enfileirável com breaker **E** cross-check; senão "em verificação".

**Execução & RAM**
- [ ] Um `.service`+`.timer` por agente; `MemoryMax`/`MemoryHigh`/`CPUQuota`/`OOMScoreAdjust`/`RuntimeMaxSec`/`flock` presentes.
- [ ] Cgroups recaem no processo real do `claude -p` (não num `docker exec` de container partilhado); validação documentada.
- [ ] Timers descorrelacionados; SENTINELA em timer próprio fora de fase; reset da pausa LLM à meia-noite.
- [ ] `maestro-run` encadeia executores em **sequência** (nunca paralelo); LLM não faz spawn.
- [ ] Timers ficam **disabled** até o dono os ativar.

**Live-gated & testes**
- [ ] `CHECKAL_MODO_TESTE=True`, `CHECKAL_PARECER_RGPD_OK=False`, `CHECKAL_ANTHROPIC_DPA_OK=False` nos defaults; nenhum SMTP cold configurado; nada envia/cobra/publica.
- [ ] Suite completa verde, **0 skips**, offline sem chaves; os 1344 testes pré-existentes continuam verdes.
- [ ] `AGENTES-ENXAME.md` + `deploy/systemd/README.md` escritos (arquitetura, gates, rollout, alarmes, validação de cgroup).

**Regra final:** se algo neste prompt colide com o que encontrares no repo, **PÁRA e reporta** — não improvises, não relitigues decisões fechadas, não contornes gates. O portão é código, não disciplina.

---

## FASE G — Pagamento cold-direto (IfThenPay + página `/pagar` + TOConline série CKL)

> Decisão do dono (ADENDA §1–5). Detalhe completo em `agentes-polaris/PAGAMENTOS-IFTHENPAY.md`.
> Constrói com os mesmos princípios das fases A–F: **LIVE-GATED, TDD, testes verdes, nada envia/cobra sem chaves**.
> As chaves IfThenPay já existem na config (`IFTHENPAY_MB_KEY/MBWAY_KEY/ANTIPHISHING_KEY/BASE`) mas a integração **não existe** — é build novo.

**Ficheiros a criar:**
- `checkal/app/faturacao/ifthenpay_client.py` — `gerar_referencia_mb(order_id, valor, validade_dias)`, `iniciar_mbway(order_id, valor, telemovel)`, `verificar_callback(payload, antiphishing_key)`. LIVE-GATED (sem `IFTHENPAY_*` ⇒ `None`, nunca toca a rede). Testes offline por cliente HTTP fake.
- `checkal/app/web/pagar.py` — `GET/POST /pagar` (token assinado **sem PII**: campanha/segmento/nr_registo?/plano; capta **NIF+email+aceitação T&C** ANTES de gerar; gera método **ao vivo**) + `POST /callback/ifthenpay` (**idempotente**; valida antiphishing → fulfillment → TOConline **série CKL** → onboarding). Requisitos de confiança da ADENDA §2 (HTTPS, identificação Cosmic Oasis/NIPC/morada, marcas MB/MB Way, "processado por IfThenPay", T&C visíveis, sem dark patterns).
- Tabela `Pagamento` (`pagamentos`) em `models_swarm.py`: `order_id` (único, prefixo CKL), `campanha_id?`, `nr_registo?`, `plano`, `valor_cent`, `metodo{mbref|mbway|transferencia}`, `estado{pendente|pago|expirado|por_casar|falhado}`, `ifthenpay_ref?`, `ifthenpay_id?`, `nif`, `email`, `tc_versao`, `tc_aceite_em`, `criado_em`, `pago_em`.
- **Reutiliza** `faturacao/toconline_client.py`+`base.py` (série CKL via `TOCONLINE_SERIES_ID`/`_PREFIX`, guarda `SerieNaoConfigurada`) e `onboarding`/`fulfillment` — só muda a **origem do gatilho** (callback IfThenPay em vez de webhook Stripe). **Stripe fica secundário/inalterado.**
- **Renovação:** token de renovação a **D-30** gera nova ref/MB Way (sem cartão guardado) — liga ao **GESTOR-DE-CLIENTE**.
- **Transferência:** estado `por_casar`, reconciliada pelo **GESTOR-DE-CLIENTE** (casa montante+refª→order → mesmo fulfillment).

**Ligação ao ANGARIADOR:** o email cold liga o botão **"Pagar já"** a `/pagar` (nunca referência crua); o **linter** trata o corpo do email; o ANGARIADOR **não** altera assunto/CTA.

**Gate/aceitação:**
- [ ] LIVE-GATED (sem `IFTHENPAY_*` não há rede); callback **idempotente**; antiphishing **obrigatória**; token expirado rejeitado; `/pagar` capta NIF+T&C **antes** de gerar; guarda série CKL; fatura só com callback **pago** (transferência = exceção reconciliada por humano/agente).
- [ ] Antes da 1.ª fatura real: **smoke-test TOConline** fecha os ~15 campos `TODO[ASSUMIDO]`.
- [ ] Suite verde, 0 skips; os 1344 testes pré-existentes continuam verdes.
