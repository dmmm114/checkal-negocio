# SPEC — Integração Stripe (CheckAL)

> Contrato de construção do sprint de billing (AUTOMACAO.md FDS 2). **Não é código de produção** — é o que se vai construir e o que precisa de ser decidido/fornecido antes.
> Regra deste documento: tudo em **§ VERIFICADO** foi confirmado na documentação oficial da Stripe (URL citado). Tudo em **§ ASSUMIDO** ainda não foi confirmado e **não pode ser tratado como certo** até validação.
> Alinhamento de código: constantes já em `checkal/app/config.py` — `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, dicionário `PLANOS` (anual 49€, trienal 119€, portfólios), `AL_ADICIONAL_*`.
> Data da verificação: 2026-07-05.

---

## 1. Fluxo end-to-end

### 1.1 Compra (anual — subscrição com auto-renovação)

1. Cliente clica no **Payment Link** do plano anual (modo `subscription`, preço recorrente 49€/ano).
2. Na página hospedada pela Stripe preenche: email, dados de cartão (ou SEPA — ver §5 decisões), e os **2 campos custom**: `nif` e `nr_registo_al`.
3. Stripe cobra, cria automaticamente um `Customer` e uma `Subscription`, e dispara `checkout.session.completed` (com `mode = "subscription"`).
4. O nosso **webhook único** (FastAPI) verifica a assinatura, lê `custom_fields` (NIF + nº registo AL) e `customer_details.email`, e faz o fulfillment: matching contra `registos`, Relatório Inicial, **emissão da fatura-recibo no InvoiceXpress** com o NIF, email de boas-vindas + selo.
5. Renovação: a Stripe cobra sozinha a cada 12 meses (Smart Retries + emails nativos em caso de falha — §5).

### 1.2 Compra (trienal — pagamento único)

1. Payment Link separado, modo `payment` (one-off, preço 119€ não recorrente).
2. `checkout.session.completed` dispara com `mode = "payment"`. Cria `Customer` mas **não** cria `Subscription` → **não há dunning nem `invoice.payment_failed` nem `customer.subscription.deleted`** para este cliente.
3. Fulfillment igual ao anual; validade controlada pelo nosso lado (36 meses), email de renovação a D-30 do fim gerido pelo nosso cron, não pela Stripe.

### 1.3 Renovação falhada (só anual/portfólio)

Stripe tenta cobrar → falha → Smart Retries (várias tentativas em ~2 semanas) + emails nativos de "cartão falhou". Cada tentativa falhada dispara `invoice.payment_failed`. Esgotadas as tentativas, conforme a configuração escolhida a subscrição vai para `canceled`/`unpaid`/`past_due`.

### 1.4 Cancelamento (self-service)

Cliente entra no **Customer Portal** (sessão criada por nós via API, `return_url` para o checkal.pt) → cancela. Stripe dispara `customer.subscription.deleted` → webhook marca cliente `cancelado`, corta alertas, selo público passa a "monitorização suspensa".

---

## 2. Endpoints, eventos e campos concretos — § VERIFICADO

### 2.1 Criar Payment Link — `POST /v1/payment_links`
Fonte: https://docs.stripe.com/payment-links/create.md · https://docs.stripe.com/api/payment_links/payment_links/create.md

- `line_items[0][price]` = ID do Price · `line_items[0][quantity]` = 1.
- **Subscrição** = usar um `price` com `type=recurring`; **one-off** = `price` não recorrente. Opcional `subscription_data[...]` (ex. `subscription_data[metadata][...]`, `subscription_data[trial_period_days]`).
- **`custom_fields`** (array, **máximo 3 campos** — temos 2, folga OK). Por campo:
  - `custom_fields[i][key]` (alfanumérico, até 200 chars) — ex. `nif`, `nr_registo_al`.
  - `custom_fields[i][label][type]` = `"custom"` · `custom_fields[i][label][custom]` (texto visível, até 50 chars).
  - `custom_fields[i][type]` = `"text"` | `"numeric"` | `"dropdown"`.
  - `custom_fields[i][optional]` (boolean; default `false`).
  - Para texto: `custom_fields[i][text][minimum_length]` / `[maximum_length]`.
- **`after_completion[type]`** = `"redirect"` | `"hosted_confirmation"`; se redirect, `after_completion[redirect][url]` (suporta placeholder `{CHECKOUT_SESSION_ID}`).
- `phone_number_collection[enabled]` = true/false.
- `tax_id_collection[enabled]` = true/false, `tax_id_collection[required]` = `"never"` (default) | `"if_supported"` — **para VAT de empresas**, ver gotcha §5.4 (não é o caminho do NIF de consumidor).
- `invoice_creation[enabled]` (só relevante em modo `payment`; fatura Stripe, que NÃO substitui a fatura AT do InvoiceXpress) — manter **desligado**.
- `allow_promotion_codes` (boolean).
- `custom_text[submit][message]` / `custom_text[terms_of_service_acceptance][message]` (até 1200 chars).

> Payment Links podem ser criados 100% no Dashboard (no-code) OU por API. Recomendação: criar por API/uma vez e guardar a URL + o Price ID em config, para reprodutibilidade.

### 2.2 Ler os dados após a compra — objeto Checkout Session
Fonte: https://docs.stripe.com/api/checkout/sessions/object.md

- `mode`: `"payment"` | `"setup"` | `"subscription"` → **distingue trienal (payment) de anual/portfólio (subscription)**.
- `payment_status`: `"unpaid"` | `"paid"`.
- `custom_fields[]`: cada elemento tem `key`, `type`, e o valor em `text.value` / `numeric.value` / `dropdown.value`, além de `label`. Leitura: `field[field.type].value`.
- `customer`: ID do Customer (`cus_...`). `subscription`: ID (`sub_...`, só em modo subscription).
- `customer_details`: `email`, `name`, `address`, e `tax_ids[]` (cada um com `type` e `value`).
- `amount_total`, `currency`, `metadata`, `client_reference_id`.

> Leitura do NIF e nº de registo: vêm de **`custom_fields`** (não de `customer_details.tax_ids`) — ver §5.4.

### 2.3 Customer Portal
Fonte: https://docs.stripe.com/customer-management.md

- Funcionalidades self-service: **cancelar subscrição** (imediato ou no fim do período), **ver/descarregar/pagar faturas**, **atualizar método de pagamento**, atualizar morada/tax ID. (Cancelamento com "deflection"/cupão é opcional — desligar, coerente com "sem desconto" do PRICING §4.)
- Configuração no Dashboard (no-code): ativar portal, branding, o que o cliente pode fazer.
- **Acesso é por sessão personalizada por cliente** (não é um link partilhável único): `POST /v1/billing_portal/sessions` com `customer` (obrigatório) + `return_url` (obrigatório) → devolve `url`. A sessão expira (5 min inatividade / 1 h de atividade). ⇒ Precisamos de um endpoint nosso `GET /portal?...` que cria a sessão e redireciona.

### 2.4 Webhook — verificação de assinatura
Fonte: https://docs.stripe.com/webhooks.md

- Header **`Stripe-Signature`** com `t=<timestamp>` e `v1=<hmac-sha256>`.
- **Segredo de assinatura começa por `whsec_`**; **segredos diferentes para test e live** (já temos `STRIPE_WEBHOOK_SECRET` em config — precisa de valor por ambiente).
- Tolerância default 5 min (não pôr a 0).
- **Nunca alterar o corpo cru antes de verificar** (no FastAPI: ler `await request.body()` cru, não o JSON parseado, e passar o header).
- SDK Python: `stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)` → devolve o `Event`; apanhar `stripe.error.SignatureVerificationError` e `ValueError`/`JSON::ParserError` → responder 400. (Existe também a via mais recente `StripeClient.parse_event_notification(body, sig_header, secret)` — escolher UMA; ver §6 ASSUMIDO sobre versão do SDK.)
- Responder **2xx rápido**; fazer o trabalho pesado depois/async para não sofrer retries por timeout.

### 2.5 Os três eventos e o mapeamento ao fulfillment

| Evento | Quando dispara | Ação de fulfillment (AUTOMACAO §4/§5) |
|---|---|---|
| **`checkout.session.completed`** | Fim de qualquer compra (anual e trienal — distinguir por `mode`) | Verificar assinatura → ler `custom_fields` (`nif`, `nr_registo_al`) + `customer_details.email` → matching contra `registos` (por `nr_registo`, fallback fuzzy nome+concelho) → Playwright detalhe → **Relatório Inicial (PDF)** → **InvoiceXpress `POST /invoice-receipts`** com NIF (série `CKL`) → email boas-vindas via Resend + selo `checkal.pt/selo/{nr_registo}`. Guardar `customer`, `subscription`, `mode`. Idempotência por `event.id` / `session.id`. |
| **`invoice.payment_failed`** | Cada tentativa falhada de cobrança de renovação (só subscrições) | Marcar estado local (`past_due`) → ler `attempt_count` e `next_payment_attempt` da invoice. A Stripe já reenvia (Smart Retries) e envia emails nativos; os nossos emails D+3/D+7 (AUTOMACAO §5) são **complementares** e devem linkar ao Customer Portal / hosted page da Stripe, não recriar cobrança. |
| **`customer.subscription.deleted`** | Subscrição terminada (cancelamento no Portal, ou fim das retries se a política for "cancel") | Marcar cliente `cancelado` → cortar alertas → selo público → "monitorização suspensa" → (opcional) email win-back a D+45 pelo nosso cron. |

Fonte eventos/retries: https://docs.stripe.com/billing/revenue-recovery/smart-retries.md

---

## 3. Modo de teste / sandbox — § VERIFICADO

- **Test mode**: chaves `sk_test_...` e segredo de webhook de teste próprio (distinto do live). `config.STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` apontam para test durante a construção.
- **Stripe CLI** para desenvolvimento local (padrão documentado):
  - `stripe listen --forward-to localhost:8000/webhooks/stripe` → imprime um `whsec_...` temporário para usar em dev.
  - `stripe trigger checkout.session.completed` (e `invoice.payment_failed`, `customer.subscription.deleted`) para simular eventos.
  - Fonte: https://docs.stripe.com/webhooks.md (secção de teste) · https://docs.stripe.com/stripe-cli.
- **Cartões de teste** (https://docs.stripe.com/testing): `4242 4242 4242 4242` (sucesso). Para testar dunning de renovação existe um cartão que passa a 1.ª cobrança e falha as seguintes — confirmar o número exato na página de testing (marcado ASSUMIDO §6).
- Payment Links e Customer Portal têm versões de test mode isoladas (dados não passam para live).

---

## 4. O que o Diogo tem de fornecer

**Contas/chaves**
1. Conta Stripe da **Cosmic Oasis** (já existe — LEGAL §4). Ativar test mode + live.
2. `STRIPE_SECRET_KEY` (test e live) → `.env`.
3. Criar o endpoint de webhook no Dashboard (URL pública `https://checkal.pt/webhooks/stripe`) e copiar o `whsec_...` para `STRIPE_WEBHOOK_SECRET` (um por ambiente).

**Produtos/preços a criar no Dashboard (ou por API)** — devolvem `price_...` que temos de guardar em config, mapeados a `PLANOS`:
4. Preço recorrente **anual 49€/ano** (EUR, IVA incluído — ver §5.3 sobre tax behavior).
5. Preço one-off **trienal 119€**.
6. Preços/links dos portfólios (149/299/499€ e trienais) e do **AL adicional** (19€/ano, 45€/ano trienal) — decidir se são links próprios ou add-ons.

**Payment Links a criar** (guardar URLs em config): anual, trienal, + portfólios. Cada um com os 2 custom fields (§2.1).

**Configuração no Dashboard (no-code)**
7. Customer Portal: ativar, ligar branding CheckAL, permitir cancelar + faturas + atualizar cartão, **desligar** cupões de deflection.
8. Revenue recovery → Retries: escolher esquema Smart Retries (default 8 tentativas/2 semanas) e a **política de fim** (`canceled` recomendado — dispara `customer.subscription.deleted` que já tratamos).
9. Revenue recovery → Emails: ligar "Send emails when card payments fail" e "Send emails about expiring cards"; escolher destino do link (hosted page da Stripe ou o nosso Portal).

**Decisões de negócio**
10. Métodos de pagamento por plano (cartão+SEPA no recorrente; MB/MB Way só no trienal one-off — PRICING §5.3). Confirmar disponibilidade na conta (§6).
11. Textos legais do checkout (`custom_text[terms_of_service_acceptance]`) apontando aos T&C — LEGAL.

---

## 5. Riscos / gotchas

**5.1 — Renovações bem-sucedidas NÃO estão nos 3 eventos.** O ano-2+ de uma subscrição cobra e dispara `invoice.paid` / `invoice.payment_succeeded`, **não** `checkout.session.completed`. Como a fatura-recibo AT (InvoiceXpress) é obrigatória **em cada cobrança**, o conjunto atual (`checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`) **não emite fatura nas renovações anuais**. → **Decisão necessária**: adicionar `invoice.paid` (ou `invoice.payment_succeeded`) ao webhook para faturar renovações, filtrando `billing_reason` (`subscription_cycle`) para não duplicar a fatura da 1.ª compra. Este ponto é bloqueante do "faturar legalmente desde a 1.ª venda" para o ano 2. (Verificado que renovações usam eventos de invoice, não checkout: https://docs.stripe.com/billing/revenue-recovery/smart-retries.md e modelo de subscrições.)

**5.2 — `checkout.session.completed` serve os dois modos.** É obrigatório ramificar por `session.mode` (`subscription` vs `payment`) para não tratar o trienal como subscrição (não tem `sub_...`, não tem dunning).

**5.3 — IVA incluído no preço.** Os preços de tabela são IVA incl. (23%). Ao criar os Prices há que definir o *tax behavior* como `inclusive` (ou não usar Stripe Tax e deixar o cálculo/emissão de IVA ao InvoiceXpress). Não deixar a Stripe somar 23% por cima. Confirmar (§6).

**5.4 — NIF de consumidor ≠ Tax ID/VAT da Stripe.** `tax_id_collection`/`customer_details.tax_ids` destina-se a **números de IVA de empresas** (ex. tipo `eu_vat`); o NIF de um particular português não é um VAT number e não tem um `type` de consumidor equivalente garantido. → **Recolher o NIF por `custom_fields`** (campo `nif`, `optional=true`, "Consumidor final" se vazio, conforme LEGAL §fiscal), e ler de `custom_fields`, não de `tax_ids`. (A doc mostra `tax_ids` com tipos como `es_nif` etc.; a adequação de um tipo PT para consumidor está ASSUMIDA §6.)

**5.5 — Custom fields só no checkout inicial.** Os valores de `custom_fields` são capturados na compra e vivem na Checkout Session. Não voltam a ser pedidos nas renovações → guardar NIF e nº de registo na nossa BD no primeiro `checkout.session.completed`.

**5.6 — Corpo cru do webhook.** No FastAPI, verificar a assinatura sobre o **body byte-a-byte** (`await request.body()`), nunca sobre o dict re-serializado — senão a verificação falha sempre.

**5.7 — Idempotência.** A Stripe reenvia webhooks (retries) e pode entregar duplicados/fora de ordem. Guardar `event.id` processados e tornar o fulfillment idempotente (não emitir 2 faturas para a mesma `session.id`).

**5.8 — Máx. 3 custom fields e tipos.** Temos 2 (`nif`, `nr_registo_al`) → OK. Usar **`type=text`** para ambos: o nº de registo AL contém `/` (ex. `12345/AL`) e o NIF, apesar de numérico, é mais seguro como texto (evita perda de zeros/validação estranha). Validar formato do nosso lado.

**5.9 — Portal precisa de `customer` + sessão efémera.** Não há link estático; construir `GET /portal` que autentica o nosso cliente, chama `POST /v1/billing_portal/sessions` e redireciona para o `url`. Trienal (só payment) entra no Portal mas só verá faturas (sem subscrição para cancelar).

**5.10 — Reconciliação Stripe↔InvoiceXpress.** Se o `POST /invoice-receipts` do InvoiceXpress falhar depois de a Stripe já ter cobrado, fica um pagamento sem fatura AT. → fila de retry + alerta (Healthchecks/Telegram), nunca engolir a falha.

**5.11 — Métodos de pagamento vs recorrência.** MB/MB Way não suportam cobrança recorrente decente (PRICING §5.3) → só no trienal one-off. Confirmar que estão ativos na conta e restritos por link (§6).

---

## 6. Pontos ASSUMIDOS — a confirmar antes de construir

1. **Evento de renovação para faturar** (§5.1): assumido `invoice.paid`/`invoice.payment_succeeded` com `billing_reason=subscription_cycle`. Confirmar nome exato do evento e do campo em https://docs.stripe.com/api/events/types e https://docs.stripe.com/api/invoices/object antes de o cablar.
2. **Tax behavior `inclusive`** nos Prices para IVA incluído (§5.3) — confirmar em https://docs.stripe.com/tax/products-prices-tax-codes-tax-behavior (ou decidir não usar Stripe Tax).
3. **Tipo de Tax ID PT para consumidor**: assumido que **não existe** um `type` adequado e que o NIF vai por custom field (§5.4). Confirmar a lista de tipos suportados em https://docs.stripe.com/api/customer_tax_ids (procurar `pt_*`).
4. **Versão do SDK Python** e API preferida (`stripe.Webhook.construct_event` vs `StripeClient.parse_event_notification`) — fixar a versão em `requirements` e escolher UMA (a segunda é a nova API baseada em cliente). Confirmar em https://docs.stripe.com/webhooks.md.
5. **Cartão de teste de falha em renovação** (§3): confirmar o número exato em https://docs.stripe.com/testing (secção "declined/retry").
6. **Disponibilidade de SEPA/MB Way na conta** e como restringir métodos por Payment Link — confirmar em https://docs.stripe.com/payments/payment-methods e nas definições da conta.
7. **Comportamento de criação de Customer em modo `payment`** (trienal): assumido que o Payment Link cria sempre um Customer; confirmar em https://docs.stripe.com/api/payment_links (parâmetro `customer_creation`) para garantir que o trienal também entra no Portal.
8. **Política de fim das retries**: assumido `cancel` (⇒ `customer.subscription.deleted`). Se se escolher `unpaid`/`past_due`, o evento de corte muda e o webhook tem de tratar `customer.subscription.updated` — decidir no Dashboard (§4.8) e alinhar o webhook.

---

## 7. Alinhamento com `config.py`

- Usar `STRIPE_SECRET_KEY` e `STRIPE_WEBHOOK_SECRET` já existentes.
- Adicionar mapa `plano → {price_id, payment_link_url}` (novo em config) coerente com `PLANOS` (anual 49€ / trienal 119€ / portfólios). Guardar Price IDs de test e live separados.
- `INVOICEXPRESS_SERIE = "CKL"` já definido → usar no fulfillment.
- Endpoint do webhook sugerido: `POST /webhooks/stripe`; endpoint do portal: `GET /portal`.
