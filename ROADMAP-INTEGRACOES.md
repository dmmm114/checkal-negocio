# ROADMAP DE INTEGRAÇÕES — CheckAL

> Documento consolidado das 6 SPECs de integração (todas escritas e verificadas contra
> documentação oficial a 2026-07-05). Mapeia cada integração ao sprint de construção
> (AUTOMACAO.md §7, FDS 2–6), reúne o que o Diogo tem de fornecer/decidir **antes** de cada
> sprint poder ir para produção, e regista os riscos/pontos ASSUMIDOS mais perigosos.
>
> **Legenda de estado:**
> 🟢 **VERDE** — SPEC verificada, risco baixo, sem bloqueio material além de contas/chaves de rotina.
> 🟡 **AMARELO** — SPEC verificada mas com pontos ASSUMIDOS a validar em sandbox e/ou decisões de negócio pendentes.
> 🔴 **VERMELHO** — bloqueado a montante (portão RGPD / decisão em aberto) ou com buraco de conhecimento crítico por fechar.
>
> **SPECs de origem** (o detalhe canónico vive lá; este documento não o substitui):
> - `checkal/app/billing/SPEC-STRIPE.md`
> - `checkal/app/faturacao/SPEC-INVOICEXPRESS.md`
> - `checkal/app/rnal/SPEC-DETALHE.md`
> - `checkal/app/regulatorio/SPEC-DRE.md`
> - `checkal/app/ia/SPEC-IA.md`
> - `checkal/app/envio/SPEC-RESEND.md`

---

## 1. Tabela por sprint → integrações → estado

| Sprint | Entregável (AUTOMACAO §7) | Integração(ões) | Estado | Porquê essa cor |
|---|---|---|---|---|
| **FDS 2** | Landing + widget + Payment Links + webhook fulfillment + fatura certificada | **Stripe** | 🟡 | API madura e verificada, mas 8 pontos ASSUMIDOS e 1 gotcha bloqueante do ano-2 (renovações não disparam `checkout.session.completed`). Depende de config manual no Dashboard. |
| **FDS 2** | Fatura-recibo com NIF + comunicação AT | **InvoiceXpress** | 🟡 | Fluxo verificado, mas certificação fiscal/AT depende de config manual da conta (subutilizador WSE + Comunicação Automática) e 9 pontos por validar em sandbox (root keys, nome da taxa, cálculo do total). |
| **FDS 3** | Onboarding (matching + detalhe + Relatório + selo) | **RNAL detalhe** | 🟢 | Página server-rendered, `httpx` direto resolve, sem contas/chaves. **Ressalva:** 1 buraco crítico — como aparece um registo CANCELADO/SUSPENSO (não observado). Mitigado pelo diffing nacional (FDS 1). |
| **FDS 3** | Email de boas-vindas + fatura anexa + selo | **Resend (Canal A)** | 🟡 | API estável e verificada; pendente verificação de assinatura do webhook (Svix, ASSUMIDO), valores DNS exatos (só a consola gera) e decisão do subdomínio de envio. |
| **FDS 4** | Pipeline DRE (PDF gratuito + grep) | **DRE (Diário da República)** | 🟢 | Fonte primária (PDF integral gratuito) verificada end-to-end, URL previsível, **zero contas/chaves**. Camada B (screenservices) fica para fase 2, não bloqueia. |
| **FDS 4** | Triagem Haiku + redação Sonnet anti-alucinação | **Anthropic (IA/Batch)** | 🟢 | API GA, SDK oficial, sem infra extra. 6 pontos ASSUMIDOS resolvem-se num smoke-test barato no próprio sprint. |
| **FDS 5** | Dunning D-30/D-7/D0/D+7 + suporte + circuit breaker | **Stripe** (eventos de falha) + **Resend** (emails) | 🟡 | Reutiliza as duas integrações acima; herda os mesmos ASSUMIDOS (política de fim das retries, cartão de teste de falha, throttle 100/dia do plano grátis Resend). |
| **FDS 6** | Motor de campanhas → prospeção a frio | **Canal B (getcheckal.com)** — SMTP dedicado, **NÃO Resend** | 🔴 | **Bloqueado pelo portão RGPD** (parecer jurista) + seguro E&O + escolha de provedor de cold ainda em aberto + warm-up 21–28 dias. Ver §4. |

**MVP vendável ao fim do FDS 3.** Os dois sprints com integrações mais frágeis (Stripe+InvoiceXpress no FDS 2) são exatamente os bloqueantes de "vender legalmente" — precisam da checklist do Diogo fechada antes de qualquer venda.

---

## 2. CHECKLIST DO DIOGO (bloqueante) — agrupada por sprint, por urgência

> Nada abaixo é código; é o que **só o Diogo pode fornecer/decidir** e que trava o sprint de ir a
> produção. Ordenado dentro de cada sprint por urgência (o que bloqueia mais coisas primeiro).

### 🚦 PORTÃO A MONTANTE (antes de FDS 6 e de qualquer envio a frio) — ver §4
- [ ] **Parecer de jurista RGPD** sobre reutilizar o RNAL para prospeção (finalidade incompatível, art. 5/1/b).
- [ ] **Seguro RC profissional / E&O** contratado antes de escalar.
- [ ] **Disclaimer "informação, não aconselhamento"** em cada alerta (já previsto no template IA).

### FDS 2 — Stripe + InvoiceXpress (bloqueia a 1.ª venda legal)

**Stripe**
- [ ] Ativar **test + live** na conta Stripe da Cosmic Oasis; fornecer `STRIPE_SECRET_KEY` (test e live) para `.env`.
- [ ] Criar endpoint de webhook no Dashboard (`https://checkal.pt/webhooks/stripe`) e copiar o `whsec_` para `STRIPE_WEBHOOK_SECRET` (um por ambiente).
- [ ] Criar **Prices + Payment Links** (anual 49€ recorrente, trienal 119€ one-off, portfólios, AL adicional); guardar `price_id` + URL por plano em config. Cada link com os 2 custom fields (`nif`, `nr_registo_al`).
- [ ] Configurar **Customer Portal** (cancelar + faturas + atualizar cartão; **desligar** cupões de deflection).
- [ ] Escolher esquema **Smart Retries** e a **política de fim** (recomendado `cancel` → dispara `customer.subscription.deleted` já tratado); ligar emails de falha + de cartão a expirar.
- [ ] Decidir **métodos de pagamento por plano** (cartão+SEPA no recorrente; MB/MB Way só no trienal) e textos legais/T&C do checkout.

**InvoiceXpress**
- [ ] Conta InvoiceXpress com API ativa: **subdomínio** → `INVOICEXPRESS_ACCOUNT`, **api_key** → `INVOICEXPRESS_API_KEY`.
- [ ] Criar a **série CKL** na conta e **registá-la na AT**; fornecer o **`sequence_id` NUMÉRICO** → novo `INVOICEXPRESS_SEQUENCE_ID` (o nome "CKL" sozinho não chega para a API).
- [ ] Ativar **Comunicação Automática à AT** (escolher o método uma vez no ano civil) + criar **subutilizador no Portal das Finanças com permissão WSE** (comunicação/gestão de séries por webservice). **Sem isto as faturas saem sem ATCUD = ilegais.**
- [ ] Confirmar o **nome exato da taxa de 23%** na conta (é "IVA23"?).
- [ ] Decidir **preço vs IVA**: enviar `unit_price` líquido 39,84 para total 49,00, ou usar modo IVA-incluído — validar o total em sandbox.
- [ ] Definir **política de cliente sem NIF** (consumidor final `999999990` vs bloquear checkout). O NIF é recolhido no Stripe via custom field.
- [ ] Confirmar com suporte se há **sandbox dedicada** ou se se testa com série de rascunho na conta real.

### FDS 3 — RNAL detalhe + Resend (Canal A)

**RNAL detalhe** (sem contas/chaves — só decisões)
- [ ] **[CRÍTICO] Fornecer um `nr` real CANCELADO e um SUSPENSO** (ex.: dos 1.413 cancelamentos do Porto) para confirmar como a página os mostra. Maior buraco de conhecimento; desbloqueia a deteção de estado e a fixture de teste.
- [ ] Decisão de esquema: juntar coluna `seguro_inicio (date)` a `detalhes_cliente`? (a página expõe "Data início", o schema canónico não tem).
- [ ] Confirmar cadência/hora do refresh diário (03h30, `CADENCIA_CLIENTE_DIAS=1`) e que o onboarding dispara refresh imediato.
- [ ] Conforto com o volume (centenas de GET/dia a um portal do Estado, UA identificável + pausas).

**Resend (Canal A)**
- [ ] Conta Resend + **API key** → `RESEND_API_KEY`.
- [ ] **Decisão do remetente**: verificar `checkal.pt` raiz ou subdomínio `send.checkal.pt` (recomendado). Hoje `config.py` usa `alertas@checkal.pt` raiz, contra a recomendação da Resend.
- [ ] Acesso ao **DNS de checkal.pt** para colar os 4 registos (MX/SPF/DKIM/DMARC) gerados pela consola + endereço para relatórios DMARC.
- [ ] URL público do webhook `/webhooks/resend` registado na consola + guardar o **signing secret** → nova env `RESEND_WEBHOOK_SECRET`.
- [ ] Decisão de plano e gatilho de upgrade grátis→Pro (o teto de 100/dia estoura num evento regulatório grande).

### FDS 4 — DRE + IA (Anthropic)

**DRE** (sem contas/chaves — só decisões)
- [ ] Decisão: conjunto final de **keywords** (recall vs ruído — incluir "taxa municipal turística"? "contenção" isolado?).
- [ ] Decisão: monitorizar os **308 concelhos** ou só os prioritários (sugestão: captar todos — o custo é 1 PDF/dia igual — e filtrar a jusante).
- [ ] **Semear o contador de número de edição** no arranque com um `(numero, data)` recente conhecido.

**Anthropic (IA)**
- [ ] Criar conta Anthropic + **`ANTHROPIC_API_KEY`** (dependência global do produto).
- [ ] Confirmar **tier de rate-limit** cobre a Batches API (uso é minúsculo, validar).
- [ ] Confirmar acesso da conta aos model IDs (`claude-haiku-4-5-20251001`, `claude-sonnet-5`).
- [ ] Confirmar `thinking:disabled` no Sonnet 5 (recomendado).
- [ ] **Congelar a redação final PT-PT do template** de alerta (mantê-la estável pelo caching).
- [ ] Definir cadência do cron de submissão/polling do batch.
- [ ] **Registo/decisão RGPD**: excerto do doc + dados do AL vão à Anthropic e batches **não são ZDR** — cruzar com LEGAL.md antes de produção.

### FDS 5 — Dunning (reutiliza Stripe + Resend)
- [ ] Nenhuma conta nova; depende de fechar os ASSUMIDOS de Stripe (evento de renovação, política de fim das retries, cartão de teste de falha) e o throttle/upgrade do Resend.

### FDS 6 — Prospeção a frio (Canal B) — 🔴 gated
- [ ] **Parecer RGPD favorável** (portão bloqueante) — sem isto não há envio.
- [ ] Registo de **getcheckal.com** + acesso DNS próprio.
- [ ] **Escolha do provedor de cold** dedicado (NÃO Resend) + credenciais SMTP próprias (`COLD_SMTP_*`, `COLD_FROM`).
- [ ] Arranque do **warm-up 21–28 dias** antes da 1.ª campanha.

---

## 3. Registo de riscos — ASSUMIDOS mais perigosos e gotchas

### 3.1 Gotchas bloqueantes (podem partir a legalidade ou o dinheiro)

| # | Integração | Gotcha | Consequência se ignorado | Ação |
|---|---|---|---|---|
| G1 | **Stripe** | Renovações anuais bem-sucedidas disparam `invoice.paid`/`invoice.payment_succeeded`, **não** `checkout.session.completed`. Os 3 eventos previstos **não cobrem o ano-2+**. | A fatura-recibo AT das renovações **não é emitida** → incumprimento fiscal recorrente. | Adicionar `invoice.paid` ao webhook, filtrando `billing_reason=subscription_cycle` para não duplicar a 1.ª fatura. **Confirmar nome exato do evento/campo antes de cablar.** |
| G2 | **InvoiceXpress** | Comunicação à AT depende de **config manual da conta** (subutilizador WSE + Comunicação Automática), não da API. | Faturas saem **sem ATCUD**, por comunicar = ilegais. | Smoke-test pós-emissão: verificar `atcud != "N/D"` e `saft_hash` preenchidos. Bloquear produção até confirmado no e-fatura. |
| G3 | **InvoiceXpress** | Se o nome da taxa ("IVA23") não existir, a API aplica a **taxa por omissão silenciosamente**. | Fatura com IVA errado. | Validar `total` devolvido = 49,00 € em sandbox antes de produção. |
| G4 | **RNAL detalhe** | **Estado CANCELADO/SUSPENSO nunca foi observado** na página. Todo o valor do produto é detetar "o teu registo foi cancelado". | Deteção de estado no detalhe não é fiável. | Fonte primária do cancelamento continua a ser o **diffing nacional list_RNAL (FDS 1)**; obter `nr` cancelado real antes de confiar no detalhe; tudo o que não é claramente "ativo"/"não encontrado" → `indeterminado` (pára e avisa). |
| G5 | **Resend** | AUP **proíbe cold email**; verificação de assinatura do webhook (Svix) ainda ASSUMIDA. | Um lote de cold pela Resend **suspende a conta e derruba os alertas dos pagantes**; webhook sem verificação → qualquer um forja bounces e faz suprimir clientes reais. | Canal B **nunca** toca a Resend (módulo/credenciais separados); **não expor `/webhooks/resend`** sem implementar verificação Svix. |

### 3.2 ASSUMIDOS a validar em sandbox/smoke-test antes de construir

- **Stripe:** evento exato de renovação (G1); tax behavior `inclusive` para IVA 23%; inexistência de tipo Tax ID PT para consumidor (NIF vai por custom_fields, não `tax_ids`); versão do SDK e `construct_event` vs `parse_event_notification`; cartão de teste que falha em renovação; disponibilidade SEPA/MB Way; `customer_creation` no trienal (entrar no Portal); política de fim das retries (`cancel` vs `unpaid`/`past_due` → muda o evento de corte).
- **InvoiceXpress:** root key do corpo de criação (`invoice` vs `invoice_receipt`); root key do change-state; endpoint do PDF (`/api/pdf/:id.json` vs `/invoice_receipts/:id/pdf.json`) e forma do 202→200; `unit_price` líquido vs modo IVA-incluído; imediatez da comunicação AT no change-state; existência de sandbox dedicada.
- **RNAL detalhe:** ≤1 linha de seguro sempre (schema só guarda uma); datas sempre ISO; GET nunca precisa de cookie/`__VIEWSTATE`/JS sob todos os estados; sem anti-bot sob centenas de req/dia; registo sem seguro → linha vazia (não erro).
- **DRE:** nem toda a edição tem Parte H (tolerar ausência); delimitador de fim da Parte H (fixar contra ≥10 edições); código HTTP para edição inexistente (tratar não-200/não-PDF como "ainda não publicado"); padrão de ficheiro dos suplementos; >1 edição no mesmo dia; endpoint screenservices da Camada B (só por interceção Playwright — nada no código como facto).
- **Resend:** valores DNS exatos (MX host/prioridade, selector DKIM) só a consola gera; região do domínio (us-east-1 vs UE); mecanismo de verificação Svix; `tags` no endpoint batch; endereços de teste/sandbox.
- **IA:** nesting exato de `output_config` dentro de `MessageCreateParamsNonStreaming` em batch; assinaturas dos objetos de resultado do SDK; `cache_control ttl:"1h"` aceite no corpo do batch; rate limits do tier inicial; ID exato de `claude-sonnet-5` e suporte Batch (cross-check com skill claude-api); regex de valores/datas PT a calibrar contra amostra real da Parte H.

### 3.3 Gotchas técnicos transversais (já resolvidos nas SPECs)
- **Idempotência** (Stripe reenvia webhooks; InvoiceXpress não re-emite): guardar `event.id`/`session.id`, mapear `stripe_session_id → ix_id` antes de emitir.
- **Corpo cru do webhook Stripe** — verificar assinatura sobre `await request.body()`, nunca sobre o dict re-serializado.
- **Resultados de batch desordenados** — indexar sempre por `custom_id`, nunca por posição.
- **Sonnet 5**: `thinking:disabled` (adaptive ligado por omissão gasta tokens) e **não enviar** `temperature/top_p/top_k` (400).
- **InvoiceXpress**: a doc mente ao dizer `settled` — o valor real é `finalized`; PDF devolve 202 enquanto gera (polling assíncrono, não bloquear o webhook).
- **DRE**: ficheiro indexado por número de edição (reinicia por ano) — contador auto-corretivo verificável pela página 1 do PDF.
- **RNAL**: IDs OutSystems (`wt7`...) voláteis — ancorar seletores em texto de cabeçalho; "Registo não encontrado" é HTTP 200, detetar por texto.

---

## 4. Portão bloqueante a montante (CLAUDE.md) — recordatório

> **Antes de qualquer envio a frio (Canal B / FDS 6), independentemente da prontidão técnica:**

1. **🚦 Parecer de jurista RGPD** sobre reutilizar o RNAL para prospeção — risco de finalidade incompatível (art. 5/1/b; a CNPD sanciona). Se negativo → **consent-first puro** (widget + parcerias contabilistas), que já é o plano prioritário.
2. **Seguro RC profissional / E&O** antes de escalar (a limitação de responsabilidade a 49€ pode ser afastada como cláusula abusiva B2C).
3. **Disclaimer "informação, não aconselhamento"** em cada alerta (já embebido no template da camada IA).

Além disso, a **AUP da Resend proíbe cold email** (§3.1 G5): mesmo com parecer favorável, a prospeção corre **sempre** em infraestrutura dedicada e isolada (`getcheckal.com`), nunca na Resend. O Canal A (transacional) é um ativo operacional a proteger — se a conta Resend for suspensa, caem os alertas dos clientes pagantes.

O **registo/decisão RGPD sobre a Anthropic** (excerto do documento + dados do AL enviados; batches não são Zero Data Retention) é um portão menor mas real: cruzar com LEGAL.md antes de pôr a camada IA em produção (FDS 4).

---

## Sumário executivo

**Verde (pronto a construir, sem bloqueio material):** o pipeline **DRE** e a camada **IA (Anthropic)** do FDS 4, e o **detalhe RNAL** do FDS 3. Nenhum precisa de contas pagas novas — o DRE corre sobre PDFs públicos gratuitos e o RNAL sobre uma página server-rendered aberta; a IA só precisa da `ANTHROPIC_API_KEY`. Os pontos por confirmar resolvem-se com smoke-tests baratos dentro do próprio sprint.

**Amarelo (à espera do Diogo):** o coração comercial — **Stripe + InvoiceXpress (FDS 2)** e o **Resend transacional (FDS 3)**. Estão totalmente especificados e verificados, mas dependem de configuração manual que só o Diogo faz: chaves/webhooks Stripe, série CKL registada na AT + subutilizador WSE + Comunicação Automática no InvoiceXpress, e DNS/domínio verificado no Resend. Há dois gotchas que travam a legalidade: as **renovações anuais** precisam de um evento extra (`invoice.paid`) para faturar, e as faturas só são legais com **ATCUD/comunicação AT** ativos.

**Vermelho (bloqueado a montante):** a **prospeção a frio (Canal B, FDS 6)**, presa ao **portão RGPD** (parecer jurídico + seguro E&O) e a decisões de infraestrutura de cold ainda em aberto. O caminho consent-first já é o plano prioritário e não depende disto.

**Buraco único a fechar cedo:** obter um `nr` de registo **CANCELADO real** para confirmar a deteção de estado no detalhe RNAL — é onde assenta a promessa central do produto.
