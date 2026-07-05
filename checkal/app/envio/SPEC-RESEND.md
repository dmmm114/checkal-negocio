# SPEC — Envio de email: Resend (transacional) + domínio irmão (prospeção a frio)

> Contrato de construção para o(s) sprint(s) de envio (FDS 2/3/5 = transacional; FDS 6 = prospeção). **Não é código de produção** — é a especificação verificada contra a documentação oficial.
> Regra desta spec: cada facto está marcado **[VERIFICADO]** (com URL da doc oficial) ou **[ASSUMIDO]** (a confirmar na consola/conta real). Nada de nomes de endpoints/campos inventados.
> Data da verificação: 2026-07-05.

---

## 0. A fronteira (a decisão mais importante do documento)

Há **dois canais de email completamente separados**, que nunca partilham domínio, IP, provedor nem reputação:

| | Canal A — TRANSACIONAL | Canal B — PROSPEÇÃO A FRIO |
|---|---|---|
| Para quê | Alertas, relatórios, selo, onboarding, dunning, respostas de suporte | Cold outreach B2B a coletivas com email genérico (ver LEGAL.md §2) |
| Destinatários | **Só quem já é cliente ou pediu explicitamente** (verificação gratuita, compra) | Quem **não** deu consentimento (opt-out) |
| Domínio | `checkal.pt` (subdomínio de envio — ver §2) | `getcheckal.com` (domínio irmão, ver §7) |
| Provedor | **Resend** | **NÃO Resend** — SMTP/mailbox dedicado de cold (ver §7) |
| Reputação | Ativo operacional a proteger a todo o custo | Descartável/isolada; se queimar, não afeta o Canal A |

**Porque a fronteira é dura e não uma boa-prática opcional — [VERIFICADO]:** a Política de Uso Aceitável da Resend proíbe expressamente cold email. Citação literal:
> "You are prohibited from sending unsolicited messages of any kind, including cold outreach, purchased lists, or scraped contact data."
> "All mail must be sent to recipients who have explicitly opted in to receive communications from you. Sending to unsolicited recipients is not permitted on Resend."
> — https://resend.com/legal/acceptable-use

Consequência prática: **mandar prospeção a frio pela Resend viola o contrato e leva a suspensão da conta** (que mata o canal transacional junto). Por isso o Canal B nunca toca a Resend — não por elegância, mas por sobrevivência. Isto está alinhado com AUTOMACAO.md (linha 126) e com o portão RGPD de LEGAL.md §1 (o cold só arranca com parecer favorável, e só a coletivas com email genérico).

Nota de código: `config.py` já separa por ausência — só existe `RESEND_API_KEY`/`EMAIL_FROM`. **Não** adicionar credenciais de cold ao mesmo módulo de envio transacional; o Canal B terá o seu próprio módulo e as suas próprias env vars (ver §7.5).

---

# CANAL A — TRANSACIONAL (Resend)

## 1. Fluxo end-to-end

```
Evento de negócio (alerta gerado / relatório pronto / dunning D-x / resposta suporte)
   → app/envio/resend.py monta o payload (from, to, subject, html, text, headers, tags, Idempotency-Key)
   → POST https://api.resend.com/emails  (Authorization: Bearer RESEND_API_KEY)
   → resposta { "id": "<uuid>" }  → guardar o id na BD (tabela de envios) para auditoria/dedupe
   → (assíncrono) Resend chama o nosso webhook com email.delivered / email.bounced / email.complained ...
   → POST /webhooks/resend  → atualiza estado do envio; bounce/complaint → suprimir destinatário + FYI ao dono
```

Casos de uso concretos no produto (mapa para os sprints):
- **FDS 2/3** — email de boas-vindas com fatura-recibo (PDF InvoiceXpress) + relatório inicial + selo.
- **Alertas** — 1 email por cliente afetado por evento (estado do registo, regulamento, seguro).
- **FDS 5 — dunning** — sequência D-30/D-7/D0/D+3/D+7/D+21 disparada por cron diário.
- **Suporte** — resposta da IA a `apoio@checkal.pt` (o envio de saída passa pela Resend; a leitura é IMAP, fora desta spec).

## 2. Verificação de domínio (checkal.pt) — DNS

**[VERIFICADO]** A Resend recomenda enviar de um **subdomínio**, não do domínio raiz, para isolar reputação e sinalizar intenção:
> "We recommend sending your emails from one or more subdomains (e.g., `updates.example.com`) instead of your root domain" — https://resend.com/docs/dashboard/domains/introduction

Registos DNS que a Resend exige ao adicionar um domínio (estrutura **[VERIFICADO]**; **valores exatos gerados pela consola** — ver nota):

| Registo | Host/Nome | Valor | Fonte |
|---|---|---|---|
| **MX** (bounces/feedback) | subdomínio de envio (ex. `send.checkal.pt`) | `feedback-smtp.<região>.amazonses.com` (prioridade 10) | [VERIFICADO estrutura] https://resend.com/docs/dashboard/domains/introduction ; **[ASSUMIDO]** o host `feedback-smtp.us-east-1.amazonses.com` e prioridade `10` — confirmar na consola |
| **TXT (SPF)** | mesmo subdomínio de envio | `v=spf1 include:amazonses.com ~all` | [VERIFICADO] https://dmarc.wiki/resend |
| **TXT (DKIM)** | `resend._domainkey` (no domínio) | chave pública `p=...` gerada pela Resend | [ASSUMIDO selector `resend._domainkey`] — confirmar na consola; que é TXT DKIM está [VERIFICADO] |
| **TXT (DMARC)** | `_dmarc.checkal.pt` | arranque `v=DMARC1; p=none; rua=mailto:dmarc@checkal.pt` → endurecer para `p=quarantine`/`p=reject` depois de observar relatórios | [VERIFICADO recomendação] https://dmarc.wiki/resend |

**[VERIFICADO]** Alinhamento: a Resend suporta **DKIM alinhamento estrito** mas **SPF só relaxado** (porque o SPF usa o subdomínio amazonses). Para o DMARC passar, basta o DKIM alinhar — por isso o DKIM é o registo crítico. (https://dmarc.wiki/resend)

**[VERIFICADO]** A Resend reverifica o DNS durante **72 horas**; se detetar → estado `Verified`, senão → `Failure`. (search oficial / docs/domains)

**Nota sobre valores exatos:** a Resend gera os valores concretos (host do MX por região, chave DKIM) **na consola quando se adiciona o domínio** — a doc pública remete para lá. Ação do Diogo: adicionar `checkal.pt` na consola, escolher subdomínio de envio, copiar os 3–4 registos exatos que a consola mostrar e pôr no DNS do registrar. Só depois disso é que os valores acima deixam de ser [ASSUMIDO].

**Decisão a tomar (§4):** `config.py` tem hoje `EMAIL_FROM = "CheckAL <alertas@checkal.pt>"` (raiz). Alinhar com a recomendação da Resend implica migrar para um subdomínio, ex. `alertas@send.checkal.pt` ou verificar o próprio `checkal.pt` como domínio de envio. Recomendação desta spec: verificar um **subdomínio** (ex. `send.checkal.pt`) e enviar de `alertas@send.checkal.pt`, mantendo `checkal.pt` raiz limpo. Isto é uma decisão do dono (afeta o remetente que os clientes veem).

## 3. Endpoints / campos concretos [VERIFICADO]

### 3.1 Enviar um email — https://resend.com/docs/api-reference/emails/send-email
- **POST** `https://api.resend.com/emails`
- Auth: header `Authorization: Bearer <RESEND_API_KEY>`
- Header opcional **`Idempotency-Key`**: string única por pedido, expira em 24h, máx. 256 chars. **Usar sempre** (ex. `alerta-{evento_id}-{cliente_id}`) para não duplicar em retries.

Campos do corpo (JSON) **[VERIFICADO]**:

| Campo | Tipo | Obrig. | Notas |
|---|---|---|---|
| `from` | string | sim | `Nome <email@dominio>` |
| `to` | string \| string[] | sim | máx. **50** destinatários |
| `subject` | string | sim | |
| `html` | string | não | |
| `text` | string | não | auto-gerado do HTML se omitido |
| `cc` / `bcc` | string \| string[] | não | |
| `reply_to` | string \| string[] | não | ex. `apoio@checkal.pt` |
| `headers` | object | não | headers custom (ex. `List-Unsubscribe`) |
| `attachments` | array | não | filename+content; máx. **40MB** por email após Base64 (chega para o PDF da fatura/relatório) |
| `tags` | array | não | pares key/value para tracking (ex. `tipo=alerta`) |
| `scheduled_at` | string | não | ISO 8601 ou linguagem natural |
| `template` | object | não | `{ id, variables }` |

Resposta **[VERIFICADO]**: `{ "id": "<uuid>" }`.

### 3.2 Envio em lote — https://resend.com/docs/api-reference/emails/send-batch-emails
- **POST** `https://api.resend.com/emails/batch`
- Corpo: **array de objetos email**, máx. **100** por pedido. **[VERIFICADO]**
- Limitação: **`attachments` e `scheduled_at` NÃO são suportados no batch.** **[VERIFICADO]**
- Uso no CheckAL: alertas em massa (N clientes afetados por um evento). Como não há attachments no batch, os alertas devem levar o conteúdo inline/link (não anexo) — coincide com o design (alertas linkam para a fonte, não anexam). Relatórios/faturas (com PDF anexo) vão **um a um** pelo endpoint singular.

### 3.3 SMTP (alternativa ao REST, mesmo canal) — https://resend.com/docs/send-with-smtp **[VERIFICADO]**
- Host: `smtp.resend.com`
- Portas: `25, 465, 587, 2465, 2587` (465/2465 = TLS implícito; 25/587/2587 = STARTTLS)
- Username: `resend`
- Password: **a própria `RESEND_API_KEY`**
- Nota: para o CheckAL a **API REST é a via preferida** (idempotência, batch, resposta com id). SMTP fica documentado como fallback, não como caminho principal.

### 3.4 Webhooks / eventos — https://resend.com/docs/dashboard/webhooks/introduction
Eventos **[VERIFICADO]**: `email.sent`, `email.delivered`, `email.bounced`, `email.complained`, `email.opened`, `email.clicked`, `email.delivery_delayed`.
- Deduplicação **[VERIFICADO]**: guardar o header `svix-id` (identificador único de cada entrega) para descartar duplicados.
- Assinatura/verificação: a Resend usa **Svix** para os webhooks. A verificação de assinatura (signing secret + headers `svix-id`/`svix-timestamp`/`svix-signature`) é **[ASSUMIDO]** — a doc consultada só confirmou o `svix-id` para dedupe; confirmar o mecanismo exato de verificação de assinatura antes de expor `/webhooks/resend` (ver §6 riscos). Tratamento CheckAL: `email.bounced`/`email.complained` → marcar destinatário como suprimido e não voltar a enviar + FYI ao dono; `email.complained` sobre um cliente é sinal forte (rever).

## 4. O que o Diogo tem de fornecer (Canal A)

1. **Conta Resend** + **API key** → env `RESEND_API_KEY` (já previsto em `config.py:71`).
2. **Decisão do remetente**: verificar `checkal.pt` raiz ou um subdomínio `send.checkal.pt` (recomendado — §2). Isto fixa `CHECKAL_EMAIL_FROM`.
3. **Acesso ao DNS** de `checkal.pt` no registrar para colar os 4 registos (MX, SPF, DKIM, DMARC) que a consola gerar.
4. **Endereço para relatórios DMARC** (ex. `dmarc@checkal.pt`).
5. **Decisão de plano**: começar no **grátis** (3.000/mês, 100/dia — §5) e definir o gatilho de upgrade para **Pro $20** (50.000/mês, sem limite diário).
6. **URL público do webhook** (`https://<host>/webhooks/resend`) registado na consola Resend, e guardar o **signing secret** do webhook → nova env (ex. `RESEND_WEBHOOK_SECRET`).

## 5. Limites do plano [VERIFICADO] — https://resend.com/pricing

| | Grátis | Pro ($20/mês) |
|---|---|---|
| Emails/mês | **3.000** | 50.000 (+$0,90/1.000 acima) |
| Limite diário | **100/dia** | **sem limite diário** |
| Domínios | 1 | 10 |
| Retenção de dados | 30 dias | 30 dias |

**Gotcha de dimensionamento:** o teto de **100/dia** do grátis é mais apertado que os 3.000/mês. Num evento regulatório grande (ex. limpeza de Lisboa, centenas de clientes num concelho a alertar no mesmo dia), 100/dia **estoura**. Regra de construção: (a) o motor de envio deve ter **throttle/fila** que respeite o limite diário e escoe o resto no dia seguinte **ou** (b) subir para Pro antes de campanhas de alerta em massa. A retenção de 30 dias implica que a **BD local é a fonte de verdade** do histórico de envios, não o painel Resend.

## 6. Riscos / gotchas (Canal A)

1. **[Bloqueante] AUP** — repetir: nunca enviar nada não-consentido pela Resend (§0). Um único lote de cold pela Resend pode suspender a conta e derrubar todos os alertas dos clientes pagantes.
2. **Verificação de assinatura do webhook [ASSUMIDO]** — não expor `/webhooks/resend` sem confirmar e implementar a verificação Svix (senão qualquer um forja bounces/complaints e faz-nos suprimir clientes reais). Confirmar em https://resend.com/docs/dashboard/webhooks (secção de verificação).
3. **Limite 100/dia no grátis** (§5) — planear throttle ou upgrade.
4. **Batch sem anexos** (§3.2) — faturas/relatórios com PDF só via endpoint singular.
5. **Valores DNS exatos** — só ficam confirmados depois de adicionar o domínio na consola; até lá, MX host/prioridade e selector DKIM são [ASSUMIDO].
6. **Bounce/complaint como sinal de retenção** — um cliente que marca alerta como spam deve escalar ao dono, não ser silenciosamente suprimido sem nota (é um cliente pagante).
7. **`reply_to`** — pôr `apoio@checkal.pt` para que respostas caiam no fluxo de suporte IMAP, não num remetente `alertas@` não monitorizado.
8. **Idempotency-Key** — obrigatório em todos os envios disparados por cron/webhook (dunning, alertas), senão um retry duplica o email ao cliente.

---

# CANAL B — PROSPEÇÃO A FRIO (domínio irmão `getcheckal.com`)

## 7. Infraestrutura separada

**Premissa jurídica (LEGAL.md §1–2):** o cold só arranca **após parecer RGPD favorável** e **só** a coletivas com email **genérico** (o `app/compliance/email.py` já classifica `generico` vs `pessoal`/`outro`; só `generico` é endereçável). Esta spec cobre a **infraestrutura de envio**; a elegibilidade do destinatário é decidida a montante por esse módulo.

**Premissa técnica:** **não Resend** (§0). O Canal B usa um provedor/servidor SMTP dedicado a cold, com **warm-up** e **throttle**, em `getcheckal.com`, isolado de `checkal.pt`.

### 7.1 DNS de `getcheckal.com` (independente de checkal.pt)
Autenticação própria e separada: SPF + DKIM + DMARC configurados para o provedor de cold escolhido (valores gerados por esse provedor, **não** os da Resend). Manter DMARC em `p=none` no arranque do warm-up e endurecer conforme a reputação estabiliza. **[ASSUMIDO]** — valores concretos dependem do provedor escolhido em §7.4.

### 7.2 Warm-up **[VERIFICADO — prática de indústria, não doc de um provedor específico]**
Duração padrão de warm-up até colocação estável na inbox: **21–28 dias**, subindo volume gradualmente. (Fontes: guias de infraestrutura de cold email 2026 — mailforge.ai, saleshandy.com; guia de IP warm-up da Twilio SendGrid: https://www.twilio.com/en-us/resource-center/email-guide-ip-warm-up). Implicação: o Canal B **não** está pronto no dia 1 — há 3–4 semanas de aquecimento antes de qualquer campanha real. Planear no calendário do FDS 6.

### 7.3 Throttle
Ritmo baixo e humano por mailbox (dezenas/dia, não centenas), rotação de mailboxes se o volume exigir. O provedor deve fazer throttle automático por ISP ou tem de ser configurado manualmente. **[VERIFICADO como requisito geral]** (guias acima).

### 7.4 Provedor (decisão em aberto — [ASSUMIDO])
Categorias de mercado 2026 (a avaliar, **nenhuma verificada como escolha**): infraestrutura de cold com mailboxes pré-aquecidas (ex. Primeforge/Infraforge/Smartlead/Instantly — nomes citados nos guias, não endossados aqui). Critérios: mailboxes/IP dedicados em `getcheckal.com`, warm-up automático, throttle por ISP, opt-out/lista de supressão. **Decisão do Diogo** — ver §7.6.

### 7.5 Código / config (fronteira dura)
- Módulo **separado** do transacional (ex. `app/prospecao/envio_frio.py`), **nunca** importa `app/envio/resend.py`.
- Env vars próprias (ex. `COLD_SMTP_HOST`, `COLD_SMTP_USER`, `COLD_SMTP_PASS`, `COLD_FROM`) — **não** reutilizar `RESEND_*` nem `EMAIL_FROM`.
- Cada peça de prospeção leva o rodapé RGPD obrigatório de LEGAL.md §44/§48 (identificação Cosmic Oasis + NIPC, fonte RNAL, opt-out `checkal.pt/remover`, referência CNPD) e header `List-Unsubscribe`.
- Lista de supressão partilhada com o registo de opt-out (`app/compliance/optout.py`) — quem pediu remoção nunca mais é contactado por nenhum canal.

### 7.6 O que o Diogo tem de fornecer (Canal B)
1. **Parecer RGPD favorável** (portão bloqueante — LEGAL.md §1) antes de qualquer envio.
2. **Registo de `getcheckal.com`** (já previsto nos próximos passos do CLAUDE.md) + acesso DNS próprio.
3. **Escolha do provedor de cold** (§7.4) e respetivas credenciais SMTP.
4. **Decisão de arranque do warm-up** (21–28 dias antes da 1.ª campanha).

## 8. Riscos / gotchas (Canal B)
1. **Contaminação cruzada** — qualquer partilha de domínio/IP/provedor entre A e B anula o isolamento; o risco é a reputação de `checkal.pt`. Auditar que os dois módulos não partilham credenciais nem remetente.
2. **RGPD** — sem parecer favorável e sem filtro `generico`, não há envio. O cold a singulares/ENI é **proibido** (LEGAL.md §2).
3. **Warm-up saltado** — enviar volume a frio sem aquecer queima o domínio irmão em dias.
4. **Opt-out** — falhar a supressão de quem pediu remoção é violação direta (Lei 41/2004) e mancha a marca.

---

## 9. Lista explícita de pontos ASSUMIDOS (a confirmar antes de construir)

| # | Ponto assumido | Como confirmar |
|---|---|---|
| A1 | Host/prioridade exatos do MX de bounces (`feedback-smtp.us-east-1.amazonses.com`, prio 10) | Adicionar `checkal.pt` na consola Resend e ler os valores gerados |
| A2 | Selector DKIM `resend._domainkey` e valor `p=...` | Idem — consola Resend |
| A3 | Região do domínio (us-east-1 default; se há escolha de região UE) | Confirmar na consola; a página docs de regiões deu 404 na verificação |
| A4 | Mecanismo exato de verificação de assinatura dos webhooks (Svix signing secret + headers) | https://resend.com/docs/dashboard/webhooks (secção verificação) antes de expor o endpoint |
| A5 | `tags` suportadas ou não no endpoint batch | Testar na sandbox / doc batch (a doc não confirmou explicitamente) |
| A6 | Provedor de cold email para `getcheckal.com` | Decisão do Diogo (§7.4) + doc do provedor escolhido |
| A7 | Valores DNS (SPF/DKIM/DMARC) de `getcheckal.com` | Dependem do provedor de A6 |

## 10. Modo de teste / sandbox
- **Resend:** testar com a API key real em modo de baixo volume; a Resend expõe **endereços de teste** e o painel mostra cada envio + eventos de webhook (útil para validar bounce/complaint sem destinatários reais). **[ASSUMIDO — confirmar os endereços de teste exatos na doc de testing da Resend]**. Deliverabilidade real só se valida com o domínio verificado (§2).
- Fluxo mínimo de aceitação (FDS 2): enviar-me a mim próprio um email de boas-vindas com PDF anexo → recebido, DKIM/SPF a passar (ver headers no destinatário), evento `email.delivered` no webhook local.
- **Cold (getcheckal.com):** validar warm-up com ferramenta de inbox-placement do provedor antes de disparar prospeção; nunca testar cold contra endereços reais fora de controlo.

---

### Fontes oficiais consultadas (2026-07-05)
- Send email: https://resend.com/docs/api-reference/emails/send-email
- Batch: https://resend.com/docs/api-reference/emails/send-batch-emails
- SMTP: https://resend.com/docs/send-with-smtp
- Webhooks: https://resend.com/docs/dashboard/webhooks/introduction
- Domínios/DNS: https://resend.com/docs/dashboard/domains/introduction ; https://dmarc.wiki/resend
- Preços/limites: https://resend.com/pricing
- AUP (proíbe cold): https://resend.com/legal/acceptable-use
- Warm-up (indústria): https://www.twilio.com/en-us/resource-center/email-guide-ip-warm-up ; https://www.mailforge.ai/blog/cold-email-infrastructure-tools
