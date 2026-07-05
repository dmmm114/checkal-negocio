# FDS 2 — Landing + widget + Stripe + webhook fulfillment + InvoiceXpress

> Contrato de construção (committado junto do código). Alinhado com AUTOMACAO.md §4/§7 e as
> SPECs verificadas `app/billing/SPEC-STRIPE.md` e `app/faturacao/SPEC-INVOICEXPRESS.md`
> (o detalhe canónico dos endpoints/campos vive nelas — LÊ-AS).
> Critério de "feito" (AUTOMACAO.md §7): consigo pagar-me a mim próprio, ficar registado como
> cliente E receber fatura-recibo certificada — sem isto não se vende legalmente nem a 1 cliente.

## Disciplina transversal (inviolável)
- **MODO DE TESTE, LIVE-GATED.** Nenhum módulo faz chamadas HTTP reais a Stripe/InvoiceXpress nos
  testes: o cliente HTTP é **injetado/mockado**. `config.CHECKAL_MODO_TESTE` (default `True`) — em
  produção o dono desliga; sem chaves, nada liga.
- Portabilidade SQLite/Postgres (tipos portáteis). TDD: teste antes da implementação. Cada agente
  toca só nos seus ficheiros.
- **Idempotência**: webhooks são reentregues; toda a ação de fulfillment é idempotente por
  `event.id` (tabela `webhook_eventos`) e por `stripe_session_id`.
- **Corpo cru**: a assinatura do webhook Stripe verifica-se sobre o body **bruto** (bytes), nunca
  sobre o dict re-serializado.

## Módulos e contrato (fronteiras disjuntas)

### `app/models.py` (EXTENSÃO aditiva) + `tests/test_models_fds2.py`
Acrescenta, **sem quebrar os testes do FDS 1**: tabela `webhook_eventos(event_id PK text, tipo text,
recebido_em DateTime)`; colunas em `clientes`: `stripe_session_id text`, `ix_fatura_id text`,
`ix_atcud text`, `ix_permalink text`. Testa: criação + insert/idempotência do event_id (PK duplicada rejeitada).

### `app/config.py` (EXTENSÃO aditiva)
`CHECKAL_MODO_TESTE=True`; `INVOICEXPRESS_SEQUENCE_ID` (id numérico da série CKL); `INVOICEXPRESS_TAXA_NOME`
(default "IVA23"); mapa `STRIPE_PRICE_PLANO` (price_id→código de plano); `STRIPE_PAYMENT_LINKS` (plano→URL).
Alinhar com PLANOS já existente. Sem segredos no código.

### `app/billing/stripe_client.py` + `tests/test_stripe_client.py`
`verificar_evento(payload_bruto: bytes, sig_header: str, *, segredo=config.STRIPE_WEBHOOK_SECRET) -> dict`
— valida assinatura (esquema `t=,v1=`, tolerância 5 min) e devolve o evento; assinatura inválida →
`AssinaturaInvalida`. `plano_de_price(price_id) -> str|None`. Sem chamadas de rede (a verificação é
cripto local com o segredo). Testa: assinatura válida (gerada nos testes com o segredo de teste),
inválida, e fora de tolerância → rejeitada.

### `app/faturacao/invoicexpress_client.py` + `tests/test_invoicexpress_client.py`
`emitir_fatura_recibo(*, nome, nif, email, itens, cliente_http) -> FaturaRecibo` — fluxo (SPEC-INVOICEXPRESS):
criar `invoice_receipt` → `change-state` `finalized` → obter PDF (tolera 202→polling) → **ler ATCUD +
saft_hash**. **GUARDA G2**: se `atcud` vazio/"N/D" ou `saft_hash` ausente → `FaturaNaoCertificada`
(não devolve fatura "boa"). **GUARDA G3**: validar que o `total` devolvido == total esperado (IVA 23%
incluído) senão `TotalInesperado`. `cliente_http` injetado (mock nos testes). Testa: happy path (mock
devolve atcud+saft_hash+total certos), atcud em falta → raise, total errado → raise, 202→polling do PDF.

### `app/web/verificar.py` + `tests/test_verificar.py`
`GET /api/verificar?q=` (nº de registo OU nome) → lê a BD local (`registos`) → JSON consent-first:
`{encontrado: bool, nr_registo, nome_alojamento, concelho, estado: "ativo"|"desaparecido", data_registo}`.
**Só dados públicos do estabelecimento** — nunca NIF/email/contactos do titular. Testa: hit por nr, hit
por nome (case-insensitive), miss, e que nenhum campo de titular sai no JSON.

### `app/web/landing.py` + `tests/test_landing.py`
Rotas da landing estática/Jinja: `GET /` (página) e `GET /saude` (healthcheck `{ok:true}`). Copy pode ser
placeholder (a copy final vem de COPY-VENDAS.md; não a inventes). Testa: 200 e content-type.

### `app/fulfillment.py` + `tests/test_fulfillment.py`
Orquestra (único sítio, além do webhook, que compõe tudo). `processar_checkout(sessao, *, ix_http) ->
Resultado`: extrai NIF+nr_registo dos `custom_fields`, email de `customer_details` → **match** contra
`registos` por `nr_registo` (fallback fuzzy por nome+concelho) → cria/atualiza `clientes` +
`clientes_registos` → `emitir_fatura_recibo` → guarda `ix_fatura_id/ix_atcud/ix_permalink`. **Idempotente
por `stripe_session_id`** (repetir a mesma sessão não duplica cliente nem fatura). `processar_renovacao(
invoice, *, ix_http)` (G1: só `billing_reason=subscription_cycle`) → emite fatura da renovação.
`marcar_cancelado(subscription)`; `registar_falha_pagamento(invoice)` (regista; o dunning é FDS 5).
O email de boas-vindas é FDS 3 — aqui deixa um ponto de extensão, não envies. Testa: fulfillment cria
cliente+fatura, idempotência, fallback de match, renovação emite 2.ª fatura.

### `app/web/webhook_stripe.py` + `tests/test_webhook_stripe.py`
`POST /webhooks/stripe`: lê body **bruto** → `verificar_evento` → **idempotência** (grava `event_id`;
já visto → 200 sem reprocessar) → despacha: `checkout.session.completed`→`processar_checkout`;
`invoice.paid`→`processar_renovacao`; `invoice.payment_failed`→`registar_falha_pagamento`;
`customer.subscription.deleted`→`marcar_cancelado`. Responde 2xx rápido; assinatura inválida → 400.
Testa: cada um dos 4 eventos é despachado à ação certa; reentrega do mesmo `event.id` não duplica;
assinatura inválida → 400; evento não-tratado → 200 (ignora).

### `app/web/app.py` + `tests/test_app.py`
`criar_app() -> FastAPI` que monta as rotas (`verificar`, `landing`, `webhook_stripe`). Testa (via
`fastapi.testclient.TestClient`): app arranca, `/saude` 200, rotas registadas.

## Fora de âmbito no FDS 2 (não construir)
Onboarding/Relatório/selo (FDS 3), envio de email (FDS 3), dunning (FDS 5), Customer Portal server-side
(config no Dashboard; opcionalmente um endpoint de sessão do portal fica como stub). Nada de cold.
