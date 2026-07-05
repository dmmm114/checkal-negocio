# SPEC — Integração InvoiceXpress (fatura-recibo certificada + AT)

> Contrato de construção para o sprint de faturação (AUTOMACAO.md §4, FDS 2).
> **Não é código de produção** — é o desenho verificado que o código tem de cumprir.
> Estado: 2026-07-05. Autor: investigação técnica assistida.
>
> **Objetivo:** ao pagamento confirmado (webhook Stripe `checkout.session.completed`),
> emitir uma **fatura-recibo certificada** com NIF do cliente, na **série CKL**,
> **finalizá-la** (torna-a documento fiscal definitivo e dispara a comunicação à AT),
> obter o **PDF** e anexá-lo ao email de boas-vindas.
>
> **Regra anti-alucinação:** cada ponto está marcado como **[VERIFICADO]** (com URL da
> doc oficial) ou **[ASSUMIDO]** (a confirmar em sandbox antes de escrever o adaptador).

---

## 0. Alinhamento com `app/config.py`

Constantes já existentes (fonte de verdade):

```python
INVOICEXPRESS_ACCOUNT = _env("INVOICEXPRESS_ACCOUNT", "")   # subdomínio da conta
INVOICEXPRESS_API_KEY = _env("INVOICEXPRESS_API_KEY", "")   # api_key (query string)
INVOICEXPRESS_SERIE   = _env("INVOICEXPRESS_SERIE", "CKL")  # NOME da série
IVA = 0.23                                                  # regime normal desde o dia 1
PLANOS = {...}  # nome + preço (IVA incluído) por plano
```

⚠️ **Gap a reconciliar (ver §5):** a API **não** referencia a série pelo nome (`"CKL"`),
referencia-a por um **`sequence_id` numérico**. É preciso acrescentar
`INVOICEXPRESS_SEQUENCE_ID` ao config (o id numérico da série CKL na conta) — o nome
`"CKL"` fica só para leitura humana / validação.

---

## 1. Fluxo end-to-end

```
Stripe: checkout.session.completed
        │  (NIF recolhido como custom field no Checkout; ver §4)
        ▼
[1] POST /invoice_receipts.json         → cria fatura-recibo em estado "draft"
        │  devolve { invoice_receipt: { id, ... } }
        ▼
[2] PUT  /invoice_receipts/:id/change-state.json  (state="finalized")
        │  → documento fiscal DEFINITIVO; recebe nº sequencial + ATCUD + saft_hash;
        │    dispara comunicação à AT se "Comunicação Automática" estiver ligada (§3, §6)
        ▼
[3] GET  /api/pdf/:id.json              → 202 enquanto gera; repetir até 200 c/ URL do PDF
        │  (polling curto; ver gotcha PDF-202)
        ▼
[4] Descarregar o PDF (HTTP GET ao permalink/pdfUrl)
        ▼
[5] Anexar PDF ao email de boas-vindas (Resend) — ou usar
    POST /invoice_receipts/:id/email-document.json para o InvoiceXpress enviar
        ▼
[6] Persistir localmente: invoicexpress_id, sequence_number, atcud, saft_hash,
    permalink, total, estado — para auditoria e para não re-emitir (idempotência)
```

**Idempotência (crítico):** o webhook Stripe pode repetir. Guardar
`stripe_session_id → invoicexpress_id` **antes** de emitir e verificar à entrada;
uma fatura finalizada **não se apaga** (só se anula com nota de crédito). Nunca emitir
duas vezes para a mesma sessão.

---

## 2. Endpoints, campos e valores concretos

### 2.1 Autenticação e base — [VERIFICADO]
- Host: `https://{INVOICEXPRESS_ACCOUNT}.app.invoicexpress.com/`
- Auth: `?api_key=…` **em query string** em todos os pedidos. Só HTTPS.
- `Content-Type: application/json` obrigatório em POST/PUT.
- Rate limit: **780 pedidos/min por conta**; excesso → **429** (implementar retry com backoff).
- Credenciais (account + api_key) em `https://www.app.invoicexpress.com/users/api`.
- Fonte: <https://docs.invoicexpress.com/>

### 2.2 Criar fatura-recibo — [VERIFICADO estrutura / ASSUMIDO root key]
- `POST /invoice_receipts.json?api_key=…`
- **Root key do corpo:** a doc oficial mostra `"invoice"` como raiz para os tipos de
  fatura (invoices, invoice_receipts, simplified_invoices partilham o mesmo schema).
  **[ASSUMIDO]** confirmar em sandbox se para `invoice_receipts` a raiz é `invoice`
  (provável) ou `invoice_receipt`.
- Resposta: **201 Created**.
- Fonte: <https://docs.invoicexpress.com/invoices> · <https://invoicexpress.com/api-v1/invoice-receipt/create-2>

Corpo (campos verificados no schema partilhado de faturação):

```json
{
  "invoice": {
    "date": "05/07/2026",
    "due_date": "05/07/2026",
    "sequence_id": 123456,
    "client": {
      "name": "Nome do titular do AL",
      "code": "cliente-checkal-42",
      "fiscal_id": "508000000",
      "email": "cliente@exemplo.pt"
    },
    "items": [
      {
        "name": "CheckAL Anual",
        "description": "Subscrição de monitorização RNAL — 12 meses",
        "unit_price": 39.84,
        "quantity": 1,
        "tax": { "name": "IVA23" }
      }
    ],
    "observations": "Referência Stripe: cs_test_..."
  }
}
```

Notas de campos:
- `date` / `due_date`: formato **`dd/mm/yyyy`** [VERIFICADO].
- `sequence_id`: **id numérico** da série (a série CKL) [VERIFICADO — não é o nome].
- `client.code`: identificador **obrigatório** do cliente [VERIFICADO — required];
  usar um id estável nosso (evita duplicar clientes). `client.name` também obrigatório.
- `client.fiscal_id`: **NIF do cliente** [VERIFICADO nome do campo].
- `items[].tax.name`: nome da taxa **tal como existe na tabela de taxas da conta**;
  se não existir, aplica a taxa por omissão. String exata `"IVA23"` é **[ASSUMIDO]** —
  confirmar o nome da taxa de 23% criada na conta.
- **Preço/IVA:** `PLANOS[x]["preco"]` é **IVA incluído**. A API calcula o IVA sobre
  `unit_price`, por isso decidir (§5, decisão do Diogo): (a) enviar `unit_price` líquido
  (49/1.23 = 39.84) com `tax IVA23`, ou (b) confirmar se existe modo "preço com IVA
  incluído" na conta. **[ASSUMIDO]** — validar o total final = 49,00 € em sandbox.

### 2.3 Finalizar (tornar definitivo) — [VERIFICADO com ressalva]
- `PUT /invoice_receipts/:id/change-state.json?api_key=…`
- Corpo: estado alvo `"finalized"`.
  **⚠️ Bug conhecido da doc:** a doc escreve `settled`, mas o valor que funciona é
  **`finalized`**. Fonte: readthedocs (wrapper que documenta o bug) +
  <https://python-invoicexpress.readthedocs.io/en/latest/invoice-receipt.html>
- Corpo JSON exato (root key) **[ASSUMIDO]**: `{"invoice_receipt":{"state":"finalized"}}`
  (confirmar em sandbox; alguns wrappers usam `{"invoice":{"state":"finalized"}}`).
- **Só após `finalized`** o documento tem número sequencial fiscal, ATCUD e é comunicado
  à AT. Enquanto `draft`, é rascunho sem valor legal.
- Outros estados: `canceled` (anular), `deleted` (só rascunhos). [ASSUMIDO nomes exatos]

### 2.4 Obter o documento / campos fiscais — [VERIFICADO]
- `GET /invoice_receipts/:id.json?api_key=…`
- Campos de resposta relevantes: `status`, `sequence_number` (ex. `"6/CKL"`),
  `inverted_sequence_number`, `total`, `saft_hash`, `atcud`
  ("Unique document identifier to the Tax Authority"; `"N/D"`/`"N/A"` se não registada),
  `permalink`, `archived`.
- Fonte: <https://invoicexpress.com/api-v1/invoice-receipt/get>

### 2.5 Gerar / obter o PDF — [VERIFICADO com 2 variantes]
- Variante canónica v1: `GET /api/pdf/:document-id.json?api_key=…`
  (Fonte: <https://docs.invoicexpress.com/invoices>)
- Variante vista em wrapper: `GET /invoice_receipts/:id/pdf.json`
  (Fonte: readthedocs) — **[ASSUMIDO]** qual responde; testar `/api/pdf/:id.json` primeiro.
- Comportamento: pode devolver **HTTP 202** enquanto o PDF é gerado; repetir (polling)
  até 200 com um objeto que contém o **URL do PDF** (`pdfUrl`/`output.pdfUrl`/`permalink`).
  Depois fazer GET a esse URL para descarregar os bytes. [VERIFICADO comportamento 202]

### 2.6 (Opcional) Enviar por email pelo InvoiceXpress — [VERIFICADO]
- `POST /invoice_receipts/:id/email-document.json?api_key=…`
- Corpo: `client{ email, save }`, `subject`, `body` (**texto simples**).
- Alternativa à anexação via Resend. Para o email de boas-vindas com copy próprio,
  **preferir** descarregar o PDF (§2.5) e anexar via Resend (EMAIL_FROM do config).

### 2.7 Séries / sequences — [VERIFICADO]
- Criar: `POST /sequences.json`
- Listar: `GET /sequences.json` → obter o `id` numérico da série CKL
- Atualizar: `PUT /sequences/:id.json`
- **Registar na AT (obter ATCUD/validation_code):** `PUT /sequences/:id/register.json`
  - Sem corpo; devolve o objeto da sequência com `current_*_validation_code` (o código
    de validação ATCUD por tipo de documento).
  - Erros: 401 (api_key), 404 (série inexistente), **409** (já registada, code `005`),
    422 (credenciais AT inválidas na conta).
- Objeto sequência: `id`, `serie`, `default_sequence` (bool), `current_invoice_number`,
  `current_*_validation_code`.
- Fonte: <https://invoicexpress.com/api-v2/sequences/register/>

---

## 3. Comunicação à AT (SAF-T / ATCUD) — [VERIFICADO parcial]

- A comunicação à AT **não é um endpoint que chamamos por documento**; é uma
  **configuração da conta**: `Configurações → Comunicação Automática → escolher 1 de 3 opções`.
  Fonte: <https://invoicexpress.com/faqs/at/comunicacao-documentos>
- Regra legal: **num ano civil só se pode comunicar por um único método** — manter
  coerência até ao fim do ano. [VERIFICADO]
- Com "Comunicação Automática" ligada, ao **finalizar** o documento o InvoiceXpress
  comunica-o à AT por webservice e trata do SAF-T. **[ASSUMIDO]** que é imediato no
  `change-state`; confirmar em sandbox (ver o `atcud`/`saft_hash` preencherem-se).
- **Pré-requisito no lado do Diogo (Portal das Finanças / acesso.gov.pt):** criar um
  subutilizador com a operação **"WSE — Comunicação e Gestão de Séries por webservice"**
  autorizada, e ligar essas credenciais na conta InvoiceXpress. Sem isto o
  `register.json` devolve 422 e não há ATCUD. [VERIFICADO requisito]

---

## 4. O que o Diogo tem de fornecer (contas, chaves, decisões)

1. **Conta InvoiceXpress** ativa (plano com API) e o **subdomínio** → `INVOICEXPRESS_ACCOUNT`.
2. **API key** (em `app.invoicexpress.com/users/api`) → `INVOICEXPRESS_API_KEY`.
3. **Série CKL criada na conta** e **registada na AT** → guardar o **`sequence_id`
   numérico** em `INVOICEXPRESS_SEQUENCE_ID` (novo no config).
4. **Comunicação Automática à AT ativada** na conta (escolher o método **uma vez** no
   arranque do ano civil) + **subutilizador AT com permissão WSE** (Portal das Finanças).
5. **Nome exato da taxa de 23%** na conta (confirmar se é `"IVA23"`).
6. **Decisão de preço vs IVA:** enviar `unit_price` líquido (39,84 €) para dar total
   49,00 €, ou usar modo "IVA incluído" da conta — decidir e validar o total.
7. **Recolha do NIF no Stripe Checkout:** ativar o campo fiscal (Tax ID) ou um
   **custom field** obrigatório para NIF, para o passar em `client.fiscal_id`.
   Decidir política quando o cliente não dá NIF (consumidor final `999999990`?).
8. **Sandbox:** confirmar se a InvoiceXpress oferece conta de testes separada, ou se se
   testa na conta real com uma **série de rascunho/teste** (ver §7). [ASSUMIDO — perguntar ao suporte]

---

## 5. Gap de configuração a resolver no código

- Acrescentar ao `config.py`:
  ```python
  INVOICEXPRESS_SEQUENCE_ID = _env("INVOICEXPRESS_SEQUENCE_ID", "")  # id numérico da série CKL
  ```
- Manter `INVOICEXPRESS_SERIE = "CKL"` só como rótulo/validação (comparar com
  `sequence_number` devolvido, que virá tipo `"12/CKL"`).
- **Preço:** definir um helper que, a partir de `PLANOS[x]["preco"]` (IVA incl.) e `IVA`,
  produza o `unit_price` a enviar, coerente com a decisão do ponto §4.6.

---

## 6. Riscos e gotchas

1. **`settled` vs `finalized`** — a doc mente; usar `finalized` (§2.3).
2. **Root key `"invoice"`** para invoice_receipts (não `"invoice_receipt"`) — quirk do
   schema partilhado; **confirmar em sandbox** antes de assumir.
3. **PDF 202** — o GET do PDF não devolve o ficheiro à primeira; é preciso polling curto
   até 200 e só depois descarregar o URL. Não bloquear o webhook do Stripe à espera:
   emitir+finalizar no webhook, e **gerar/anexar PDF em tarefa assíncrona** (evita
   timeout do webhook e reentrega Stripe).
4. **Idempotência** — Stripe reentrega webhooks; mapear `stripe_session_id → ix_id` e
   verificar antes de emitir. Documento finalizado **não se apaga**.
5. **Comunicação AT depende da conta**, não da API — se o Diogo não ativar a Comunicação
   Automática + subutilizador WSE, as faturas saem sem ATCUD e ficam por comunicar
   (ilegal). Verificar `atcud != "N/D"` na resposta como *smoke test* pós-emissão.
6. **Método único de comunicação por ano civil** — não alternar SAF-T manual ↔ automático
   a meio do ano.
7. **Rate limit 780/min** — folgado para este volume, mas tratar 429 com retry/backoff.
8. **Nome da taxa** — se `"IVA23"` não existir, a API aplica a taxa por omissão
   silenciosamente → fatura com IVA errado. Validar o `total` devolvido = 49,00 €.
9. **Cliente sem NIF** — decidir fluxo (consumidor final vs bloquear checkout sem NIF).
   Para B2B (contabilistas/coletivas) o NIF é sempre exigível.
10. **Formato de data `dd/mm/yyyy`** — não enviar ISO `yyyy-mm-dd`.
11. **Fuso/estado draft** — se o processo falhar entre criar (draft) e finalizar, fica um
    rascunho pendente; ter reconciliação (listar drafts órfãos e finalizar/apagar).

---

## 7. Modo de teste / sandbox — [ASSUMIDO — confirmar]

- **Não confirmei** doc oficial de um ambiente sandbox dedicado da InvoiceXpress.
  Padrões possíveis (a validar com suporte `support@invoicexpress.com`):
  - Conta de testes separada (subdomínio próprio) com api_key de testes, **ou**
  - Testar na conta real com uma **série marcada como teste/rascunho** e documentos
    `draft` que não se finalizam (não comunicam à AT), **ou**
  - Conta trial durante avaliação.
- **Plano de teste mínimo (independente do ambiente):**
  1. `GET /sequences.json` → confirmar id da série CKL.
  2. `POST /invoice_receipts.json` com dados fictícios → confirmar 201 e root key real.
  3. `GET /invoice_receipts/:id.json` → estado `draft`.
  4. `PUT …/change-state.json` `finalized` → confirmar `sequence_number` "N/CKL",
     `atcud` preenchido, `saft_hash` presente.
  5. `GET /api/pdf/:id.json` → tratar 202→200; descarregar PDF; abrir.
  6. Confirmar total = 49,00 € (decisão IVA correta).
- **Só passar a produção** depois de a Comunicação Automática AT estar confirmada
  (documento aparece no Portal das Finanças / e-fatura).

---

## 8. Pontos ASSUMIDOS a confirmar (checklist antes de codar o adaptador)

- [ ] Root key do corpo de criação: `"invoice"` vs `"invoice_receipt"`.
- [ ] Root key do corpo de `change-state`: `{"invoice_receipt":{"state":...}}` vs `{"invoice":...}`.
- [ ] Valor exato do estado final (`finalized`) e nomes de `canceled`/`deleted`.
- [ ] Endpoint do PDF: `/api/pdf/:id.json` vs `/invoice_receipts/:id/pdf.json`; forma do 202.
- [ ] Nome exato da taxa de 23% na conta (`"IVA23"`?).
- [ ] `unit_price` líquido vs modo IVA-incluído (total tem de dar 49,00 €).
- [ ] Comunicação AT é imediata no `change-state` (verificar `atcud`/`saft_hash`).
- [ ] Existência e forma do ambiente sandbox.
- [ ] Política de cliente sem NIF (consumidor final `999999990` vs bloquear).
- [ ] Campos obrigatórios mínimos de `client` (name+code confirmados; fiscal_id exigido?).

---

## 9. Fontes (documentação oficial consultada)

- <https://docs.invoicexpress.com/> — base, auth, rate limit, tipos de documento
- <https://docs.invoicexpress.com/invoices> — criação, root key, change-state, PDF
- <https://invoicexpress.com/api-v1/invoice-receipt/create-2> — criação de fatura-recibo (v1)
- <https://invoicexpress.com/api-v1/invoice-receipt/get> — campos de resposta (atcud, saft_hash, permalink)
- <https://invoicexpress.com/api-v2/sequences/register/> — registar série / ATCUD
- <https://invoicexpress.com/faqs/at/comunicacao-documentos> — comunicação à AT (config da conta)
- <https://python-invoicexpress.readthedocs.io/en/latest/invoice-receipt.html> — bug `settled`→`finalized`, PDF 202, email-document
