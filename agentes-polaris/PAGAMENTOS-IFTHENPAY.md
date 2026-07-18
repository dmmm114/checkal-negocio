# PAGAMENTOS — IfThenPay + página `/pagar` + TOConline (série CKL)

> Spec de construção do caminho de pagamento cold-direto. Honra `DECISOES-EXECUCAO.md`.
> Estado atual no código: **config já prevê IfThenPay** (`IFTHENPAY_MB_KEY`, `IFTHENPAY_MBWAY_KEY`,
> `IFTHENPAY_ANTIPHISHING_KEY`, `IFTHENPAY_BASE`) **mas a integração NÃO existe**; a cobrança
> construída é Stripe Payment Links. Isto é **build novo**, pequeno e LIVE-GATED.

## Fluxo (fim a fim)
```
Email (getcheckal.com, coletiva, mailbox genérico)
  → botão "Pagar já"  =  URL assinada c/ validade → checkal.pt/pagar?t=<token>
  → GET /pagar        =  mostra oferta + planos (49€/119€/Portfólio); pré-preenche AL se o token trouxer nr_registo
  → POST /pagar       =  capta NIF + email + aceitação T&C; cria `pagamentos`(estado=pendente);
                         escolhe método → gera AO VIVO via IfThenPay:
                           • Referência Multibanco (entidade+ref+valor)  → mostra + envia por email
                           • MB Way (telemóvel do cliente)               → push para a app
                           • Transferência (IBAN + refª interna)         → estado "por_casar"
  → POST /callback/ifthenpay  (MB/MB Way pagos)  =  valida antiphishing → marca pago (idempotente)
  → fulfillment  → fatura-recibo TOConline (série CKL)  → onboarding (relatório inicial + selo)
```

## Módulo `app/faturacao/ifthenpay_client.py` (novo)
- `gerar_referencia_mb(order_id, valor, validade_dias) -> {entidade, referencia, valor}` — usa
  `IFTHENPAY_MB_KEY` + `IFTHENPAY_BASE`.
- `iniciar_mbway(order_id, valor, telemovel) -> {id_pedido, estado}` — usa `IFTHENPAY_MBWAY_KEY`.
- `verificar_callback(payload, chave=IFTHENPAY_ANTIPHISHING_KEY) -> {ok, order_id, valor}` — valida a
  anti-phishing key antes de aceitar qualquer confirmação.
- **LIVE-GATED:** sem chaves → devolve `None`/erro controlado, **nunca** toca a rede (padrão igual ao
  resto da app). Testes offline por injeção de cliente HTTP fake.

## Web
- `GET /pagar` + `POST /pagar` (página própria checkal.pt — requisitos de confiança do §2 das decisões).
- `POST /callback/ifthenpay` — idempotente; reprocessar o mesmo pagamento não duplica fatura nem
  onboarding.
- Token do botão: assinado (HMAC/itsdangerous), com validade; payload **sem PII**
  (`campanha_id`, `segmento`, `nr_registo?`, `plano_sugerido`).

## Tabela `pagamentos` (nova, SQLAlchemy portável)
`id, order_id (único, prefixo CKL), campanha_id?, nr_registo?, plano, valor_cent, metodo
[mbref|mbway|transferencia], estado [pendente|pago|expirado|por_casar|falhado], ifthenpay_ref?,
ifthenpay_id?, nif, email, tc_versao, tc_aceite_em, criado_em, pago_em`.

## Ligação ao existente (reutilizar, não reescrever)
- **Fatura:** reutilizar o adaptador TOConline (`faturacao/toconline_client.py`, `base.py`) — só muda a
  **origem** do gatilho: em vez de webhook Stripe, é o **callback IfThenPay** que chama o fulfillment.
- **Onboarding:** reutilizar `onboarding.processar_onboarding` / `fulfillment.processar_checkout`
  (matching de registo → Playwright detalhe → relatório inicial → selo).
- **Série CKL:** `TOCONLINE_SERIES_ID`/`_PREFIX` no ambiente; guarda `SerieNaoConfigurada` mantém-se.

## Transferência bancária
Mostra IBAN + referência interna; `estado=por_casar`. O **Gestor-de-Cliente** reconcilia (casa
montante+refª→order) e, ao casar, dispara o mesmo fulfillment. Sem API bancária → semi-manual assumido.

## Renovação
A **D-30**, gerar **nova** referência/MB Way e enviar (sem cartão guardado). Reutiliza o mesmo fluxo de
`/pagar` com um token de renovação. Régua de dunning por referência (não por cobrança automática).

## Segurança / anti-fraude
- Anti-phishing key **obrigatória** em todos os callbacks; rejeitar o que não valida.
- Idempotência por `order_id`.
- Nunca ativar serviço nem emitir fatura sem callback **pago** confirmado (transferência = exceção
  reconciliada por humano/agente).

## Aceitação (testes)
- LIVE-GATED (sem chaves não há rede); geração de ref/MB Way por cliente fake; callback idempotente;
  guarda de série CKL; token expirado/rejeitado; `/pagar` capta NIF+T&C antes de gerar; verdes.
