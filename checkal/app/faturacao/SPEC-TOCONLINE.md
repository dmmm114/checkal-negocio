# SPEC — Integração TOConline (fatura-recibo certificada + AT) — cliente DROP-IN

> Contrato de construção do adaptador **TOConline** (Cloudware), pensado para ser um
> **drop-in** do `invoicexpress_client.py` já existente (FDS 2). O dono usa o TOConline
> no Radar Marca e quer a mesma faturação automática no CheckAL, numa **série nova** cujo
> `id` ele dará depois.
> **Não é código de produção** — é o desenho verificado que o código tem de cumprir.
> Estado: 2026-07-05. Autor: síntese de investigação de 3 ângulos da API TOConline.
>
> **Objetivo:** ao pagamento confirmado (webhook Stripe `checkout.session.completed`),
> emitir uma **fatura-recibo (FR) certificada** com NIF do cliente, na **série nova (CKL)**,
> garantir que fica **comunicada à AT** (ATCUD/hash SAF-T), obter o **PDF** e anexá-lo ao
> email de boas-vindas.
>
> **Regra anti-alucinação:** cada ponto está marcado **[VERIFICADO]** (com URL da doc
> oficial) ou **[ASSUMIDO]** (a confirmar contra o Swagger/Postman ou numa emissão real
> antes de escrever o adaptador). A doc do TOConline é **pública para leitura** mas
> **fechada para credenciais** (obtêm-se logadas em *Empresa > Dados API*).

---

## 0. Contrato drop-in (o que NÃO pode mudar)

O adaptador TOConline **tem de expor a MESMA fronteira pública** que
`invoicexpress_client.py`, para ser intermutável sem tocar em quem chama (webhook/fulfillment):

```python
def emitir_fatura_recibo(
    *,
    nome: str,
    nif: str,
    email: str,
    itens: Sequence[Mapping[str, Any]],   # {"nome","preco" (IVA incl.),"quantidade"?,"descricao"?}
    cliente_http: Any,                    # cliente HTTP INJETADO (LIVE-GATED; nunca criado aqui)
    codigo_cliente: str | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> FaturaRecibo: ...
```

**`FaturaRecibo` (dataclass frozen) — campos idênticos** (mesmos nomes; o adaptador
preenche-os a partir do vocabulário TOConline):

```python
@dataclass(frozen=True)
class FaturaRecibo:
    id: str            # <- id do commercial_sales_document
    sequence_number: str  # <- document_no (ex. "FR 2026/1")
    atcud: str         # <- ATCUD completo (ver §4 — ponto crítico a confirmar)
    saft_hash: str     # <- document_hash_sum (hash SAF-T do documento) [VERIFICADO existe]
    total: float       # <- total do documento (guarda G3)
    permalink: str     # <- URL público do PDF (url_for_print) ou vazio
    pdf_url: str | None
    estado: str        # <- "finalizado" (docs FR nascem finalizados)
```

**Guardas idênticas (inviolável — copiar o comportamento, não só os nomes):**
- **G2 — `FaturaNaoCertificada`**: levantar se `atcud` vazio/`"N/D"`/`"N/A"` **ou**
  `saft_hash` (document_hash_sum) ausente. Sem prova de comunicação à AT, o documento
  **não** é uma fatura "boa".
- **G3 — `TotalInesperado`**: levantar se `total` devolvido divergir do
  `total_esperado(itens)` além de `TOLERANCIA_TOTAL_EUR` (0,01 €). Apanha taxa de IVA
  errada aplicada silenciosamente.

Reutilizar **as mesmas exceções e a mesma hierarquia** já definidas
(`ErroTOConline`↔`ErroInvoiceXpress`, `FaturaNaoCertificada`, `TotalInesperado`).
As classes de exceção podem ser partilhadas num módulo comum ou reexportadas — o
importante é que quem apanha `FaturaNaoCertificada`/`TotalInesperado` continue a funcionar.

**Disciplina LIVE-GATED (inviolável):** o módulo **não cria** cliente HTTP; recebe-o
injetado (mock nos testes; `httpx.Client` real só em produção com `CHECKAL_MODO_TESTE=False`).
Ver §2.0 — a diferença é que o cliente injetado do TOConline **já traz o Bearer e os
headers JSON:API**; a obtenção/renovação do token vive **fora** de `emitir_fatura_recibo`.

---

## 1. Fluxo end-to-end no webhook (faturação automática)

```
Stripe: checkout.session.completed
        │  (NIF recolhido como custom field / Tax ID no Checkout)
        ▼
[0] AUTH server-to-server (fora do emitir; ver §2):
    garantir access_token válido (refresh_token → /token). O cliente_http injetado
    já leva  Authorization: Bearer <access_token>  +  Content-Type: application/vnd.api+json
        ▼
[1] POST <API_URL>/api/v1/commercial_sales_documents
        │  JSON:API {data:{type:"commercial_sales_documents", attributes:{document_type:"FR",...}}}
        │  ⚠️ AO SUBMETER FICA AUTOMATICAMENTE FINALIZADO (não há change-state) [VERIFICADO]
        │  resposta traz: id, document_no, document_hash_sum, hash_control
        ▼
[2] (SE necessário) POST/PATCH <API_URL>/send_document_at_webservice
        │  comunica à AT por webservice (entity_username / entity_password base64)
        │  resposta: communication_status / communication_code / communication_message
        │  → SÓ se a série NÃO estiver em comunicação automática (a CONFIRMAR — §4)
        ▼
[3] GET <API_URL>/api/v1/commercial_sales_documents/<id>  (ou releitura)
        │  confirmar/obter ATCUD completo + document_hash_sum + total  → GUARDAS G2/G3
        ▼
[4] PDF: GET https://<host>/api/url_for_print/<id>?filter[type]=Document&filter[copies]=1
        │  devolve componentes (scheme+host+path) a concatenar → link do PDF
        ▼
[5] Anexar PDF ao email de boas-vindas (Resend)  — OU
    PATCH /api/email/document/<id> para o TOConline enviar por email
        ▼
[6] Persistir localmente: toconline_id, document_no, atcud, saft_hash, permalink, total,
    estado — auditoria + idempotência (não re-emitir)
```

**Idempotência (crítico, igual à IX):** o webhook Stripe repete-se. Guardar
`stripe_session_id → toconline_id` **antes** de emitir e verificar à entrada. Um documento
FR submetido fica **finalizado e imutável** — nunca emitir duas vezes para a mesma sessão.

**Não bloquear o webhook:** emitir (passo [1]) e, se preciso, comunicar à AT (passo [2])
no webhook; **PDF + email em tarefa assíncrona** (evita timeout e reentrega do Stripe).

---

## 2. Auth server-to-server (OAuth2) — [VERIFICADO]

> Fonte: <https://api-docs.toconline.pt/autenticacao-simplificada> ·
> <https://api-docs.toconline.pt/autenticacao-detalhada>

### 2.0 Onde vive a auth vs o emitir_fatura_recibo (drop-in)
Ao contrário da IX (`api_key` numa query string sem estado), o TOConline exige um
**access_token Bearer com validade curta**. Para manter a assinatura drop-in:

- A **obtenção/renovação do token** fica num helper próprio (ex.:
  `obter_cliente_autenticado()` / `TokenStore`) **fora** de `emitir_fatura_recibo`.
- Quem chama injeta um `cliente_http` **já autenticado**: um `httpx.Client(base_url=API_URL,
  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json",
  "Accept": "application/json"})`.
- Assim `emitir_fatura_recibo(...)` **não conhece OAuth**; só faz `post/get/patch` de
  endpoints — exatamente como a versão IX faz `post/put/get`. Nos testes, o mock ignora
  headers. **LIVE-GATED preservado.**

### 2.1 Fluxo (arranque manual único + renovação automática) — [VERIFICADO]
- **NÃO existe grant `client_credentials`** documentado. Só `authorization_code` +
  `refresh_token`. ⇒ é preciso **UM consentimento humano no browser** no arranque, que
  gera o **primeiro refresh_token**; a automação renova sozinha depois.
- **Passo 1 (uma vez, no browser):** `GET <OAUTH_URL>/auth?client_id=…&redirect_uri=…&response_type=code&scope=commercial`
  → **302** com `?code=<authorization_code>` no `Location`.
- **Passo 2 (troca code→token):** `POST <OAUTH_URL>/token`
  - Headers: `Authorization: Basic base64(client_id:client_secret)`,
    `Content-Type: application/x-www-form-urlencoded`, `Accept: application/json`.
  - Body: `grant_type=authorization_code&code=<code>&scope=commercial`.
  - Resposta JSON: `access_token`, `expires_in=14400` (**4 h**), `refresh_token`,
    `token_type=Bearer`.
- **Renovação server-to-server (o cron):** `POST <OAUTH_URL>/token`
  - Body: `grant_type=refresh_token&refresh_token=<token>&scope=commercial`;
    mesmos headers `Authorization: Basic base64(client_id:secret)`.
  - Devolve **novo `access_token` (4 h) E novo `refresh_token`** → **guardar sempre o
    novo refresh_token** (rotação; o antigo deixa de servir).

### 2.2 Validades e cadência do cron — [VERIFICADO doc / ⚠️ confirmar 8 h]
- `access_token`: **4 h** (14400 s) [VERIFICADO].
- `refresh_token`: a doc detalhada indica **~8 h** [VERIFICADO na doc extraída,
  **a confirmar na prática**]. **CRÍTICO:** se a automação ficar **>8 h sem renovar**, a
  cadeia quebra e exige **novo consentimento humano no browser**.
- **Mitigação (obrigatória):** um **cron a renovar o token a cada ~3–4 h**,
  independentemente de haver ou não faturas — a faturação por webhook é intermitente e
  não pode ser o único gatilho de renovação. Persistir `access_token`, `refresh_token`,
  `access_expira_em`, `refresh_expira_em` (BD/segredos).
- **Alarme:** se a renovação falhar (refresh expirado), notificar o dono para refazer o
  login — a faturação automática pára até isso acontecer. Não emitir silenciosamente sem token.

### 2.3 Credenciais e base URLs — [VERIFICADO fluxo / ASSUMIDO hosts]
- Obtêm-se em **Empresa > Dados API** (só admin): inserir nome+email do integrador; o
  integrador recebe por email um **ficheiro de configuração** com
  `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_URL`, `API_URL`
  — via **link temporário válido 72 h** (usar logo). Fonte: <https://api-docs.toconline.pt/setup-do-postman>
- **`OAUTH_URL` e `API_URL` NÃO são públicas** — vêm nesse ficheiro. Padrão observado numa
  lib comunitária (`dmp593/django-toconline`): host `https://app<N>.toconline.pt`
  (ex. `app10.toconline.pt`), por instância — **[ASSUMIDO]**. O host `app.toconline.pt`
  aparece confirmado só no endpoint de PDF (`url_for_print`).

---

## 3. Endpoints e campos — VERIFICADO vs ASSUMIDO

Convenções (todos os pedidos à API, exceto `/token` e o PDF público):
- Base `<API_URL>/api/v1/` (alguns auxiliares em `<API_URL>/api/…`).
- Headers: `Content-Type: application/vnd.api+json` (JSON:API), `Accept: application/json`,
  `Authorization: Bearer <access_token>`. [VERIFICADO]
  Fonte: <https://api-docs.toconline.pt/caracteristicas-dos-pedidos>
- Wrapper JSON:API: `{"data":{"type":"<recurso>","attributes":{…}}}`. Paginação `page[size]`,
  filtros `filter[…]`.
- GETs funcionam com licença expirada; **escrita exige licença ativa**. [VERIFICADO]

### 3.1 Criar fatura-recibo (FR) — [VERIFICADO estrutura / ASSUMIDO nomes de alguns campos]
- `POST /api/v1/commercial_sales_documents`
- `document_type` aceita **`FT`** (fatura), **`FS`** (simplificada), **`FR`** (fatura-recibo).
  → usar **`FR`**. **Ao submeter fica AUTOMATICAMENTE FINALIZADO** (sem passo de
  finalização; imutável depois). **Diferença central face à IX** (que exige `change-state`).
  Fonte: <https://api-docs.toconline.pt/apis/vendas/documentos-de-venda>

Corpo (JSON:API) — campos **[VERIFICADO]** salvo nota:
```json
{
  "data": {
    "type": "commercial_sales_documents",
    "attributes": {
      "document_type": "FR",
      "document_series_id": 123,               // id da série nova (§4) — ASSUMIDO nome exato
      "date": "2026-07-05",
      "due_date": "2026-07-05",
      "customer_business_name": "Nome do titular do AL",
      "customer_tax_registration_number": "508000000",
      "vat_included_prices": true,             // preços COM IVA incluído (49 € final)
      "lines": [
        {
          "item_type": "Service",
          "description": "CheckAL Anual — subscrição RNAL 12 meses",
          "quantity": 1,
          "unit_price": 49.00,                 // COM vat_included_prices=true (ver §5)
          "tax_code": "NOR",                   // classificação IVA (obter tax_id — §3.4)
          "tax_percentage": 23
        }
      ]
    }
  }
}
```
Notas:
- **`date`/`due_date`:** formato **ISO `yyyy-mm-dd`** [ASSUMIDO — confirmar; IX usa dd/mm/yyyy].
- **Série:** referencia-se por **`document_series_id`** (id interno) **OU**
  **`document_series_prefix`** (prefixo). A doc afirma "a série tem de já existir".
  **[ASSUMIDO]** o nome exato do campo na criação (`document_series_id` vs
  `commercial_document_series_id`) — confirmar no Swagger/emissão real.
- **`vat_included_prices`:** booleano, default `false`. Pôr **`true`** ⇒ `unit_price=49`
  é o preço final e o líquido (~39,84 €) é calculado pela API. **[VERIFICADO campo]**
  ⚠️ **Isto inverte o helper de preço da IX** (ver §5 e mapa §8).
- **`tax_code`/`tax_percentage`:** classificação de IVA da linha; `tax_percentage=23`.
  O `tax_code` exato (ex. `"NOR"`) e o `tax_id` obtêm-se por GET (§3.4). **[ASSUMIDO valor]**
- **Resposta [VERIFICADO]:** inclui `id`, `document_no` (ex. `"FR 2026/1"`),
  `document_hash_sum` (**hash SAF-T** → mapeia para `saft_hash`) e `hash_control` (ex. `"1"`).

### 3.2 Comunicação à AT — [VERIFICADO endpoint / ASSUMIDO se é preciso]
- Endpoint próprio: `POST` (um ângulo diz `PATCH`) `<API_URL>/send_document_at_webservice`
  ```json
  {"data":{"type":"send_document_at_webservice","id":<idDoc>,
    "attributes":{"document_type":"sales_document",
      "entity_username":"<user_PortalFinancas>",
      "entity_password":"<pass_base64>"}}}
  ```
  Resposta: `communication_status`, `communication_code`, `communication_message`.
  Fonte: <https://api-docs.toconline.pt/apis/vendas/comunicacao-de-documentos-a-at>
- ⚠️ **PONTO CRÍTICO A CONFIRMAR:** a existência deste endpoint sugere que a comunicação à
  AT é um **passo explícito**. Mas o TOConline nativo costuma comunicar **automaticamente**
  ao finalizar (a série regista-se na AT uma vez). **NÃO está confirmado** qual vale via API.
  → **Decisão de design:** o adaptador deve **verificar o resultado** (ATCUD/hash presentes,
  `communication_status` OK) e, se a série estiver em comunicação automática, **saltar** o
  passo [2]; se não, chamá-lo. Tornar isto **configurável** (`TOCONLINE_AT_MANUAL` bool).
- `PATCH` vs `POST`: os ângulos divergem — **confirmar o verbo no Swagger**.

### 3.3 Séries — [VERIFICADO GET / ASSUMIDO ausência de criação por API]
- Consulta: `GET /api/commercial_document_series` com filtros
  `filter[document_type]`, `filter[prefix]`, `filter[number]`.
  Fonte: <https://api-docs.toconline.pt/apis/apis-auxiliares/documentos-de-serie>
- Cada série = recurso JSON:API com **`id`** numérico e atributos:
  `document_type`, `prefix`, `number`, **`atcud_prefix`**, `at_status`, `at_status_date`,
  `at_type`, `is_default`, `active`, `communication_date`, `company_id`, `document_series_id`.
- **[ASSUMIDO]** **não há endpoint de CRIAÇÃO de série via API** (só GET documentado) ⇒ a
  série nova é criada **na UI web** (como o Diogo já faz no Radar Marca) e a API só a lê.
  É ausência-de-evidência; validar no portal logado / suporte Cloudware.
- **`atcud_prefix`** = código de validação da série atribuído pela AT; o **ATCUD do
  documento** = `atcud_prefix + "-" + número sequencial` (ver §4).

### 3.4 Taxa de IVA 23% — [VERIFICADO]
- `GET /taxes?filter[tax_code]=<code>&filter[tax_country_region]=PT` → obter o `tax_id`/
  `tax_code` da taxa normal 23%. Usar no `tax_code` da linha (§3.1).
  Fonte: <https://api-docs.toconline.pt/apis/vendas/documentos-de-venda>

### 3.5 PDF — [VERIFICADO]
- `GET https://<host>/api/url_for_print/<id>?filter[type]=Document&filter[copies]=1`
  → devolve **componentes de URL** (scheme+host+path) a **concatenar** no link final
  (ex. `https://app.toconline.pt/public-file/…`). Exige documento **finalizado**
  (os FR já nascem finalizados). Recibo: provavelmente `filter[type]=Receipt` [ASSUMIDO].
  Fonte: <https://api-docs.toconline.pt/apis/vendas/descarregar-pdf-de-documentos-de-venda>

### 3.6 Envio por email (opcional) — [VERIFICADO]
- `PATCH /api/email/document/<id>`, body `type="email/document"`, attributes:
  `to_email` (default = email do cliente), `from_email`, `from_name`, `subject`,
  `type` (`"Document"`|`"Receipt"`). Resposta `success=true` + `to_addresses`.
  Preferir, tal como na IX, **descarregar o PDF e anexar via Resend** para o email de
  boas-vindas com copy próprio. Fonte: <https://api-docs.toconline.pt/apis/vendas/envio-de-documentos-por-email>

### 3.7 Recibo separado (só se NÃO usar FR) — [VERIFICADO existe]
- `POST /api/commercial_sales_receipts` (lines `receivable_type:"Document"`,
  `receivable_id`, `received_value`, `payment_mechanism` ex. `"MO"`). **Não é preciso** se
  emitirmos **FR** (fatura-recibo = fatura + recibo num só documento) — **[ASSUMIDO]** que a
  FR dispensa o recibo separado (comportamento fiscal padrão da FR; sem frase explícita na doc).

---

## 4. A SÉRIE nova + ATCUD/AT — como entram

### 4.1 Config (o `id` que o Diogo dá depois)
Acrescentar ao `app/config.py` um bloco TOConline, espelhando o bloco InvoiceXpress:

```python
# --- TOConline (Cloudware) ---
TOCONLINE_API_URL       = _env("TOCONLINE_API_URL", "")        # base, vem no ficheiro de config
TOCONLINE_OAUTH_URL     = _env("TOCONLINE_OAUTH_URL", "")      # base OAuth, idem
TOCONLINE_CLIENT_ID     = _env("TOCONLINE_CLIENT_ID", "")
TOCONLINE_CLIENT_SECRET = _env("TOCONLINE_CLIENT_SECRET", "")
TOCONLINE_SERIE         = _env("TOCONLINE_SERIE", "CKL")       # rótulo humano (prefixo/nome)
# A série referencia-se por id interno (preferido) OU por prefixo:
TOCONLINE_SERIE_ID      = _env("TOCONLINE_SERIE_ID", "")       # << o id que o Diogo dá DEPOIS de criar a série
TOCONLINE_SERIE_PREFIXO = _env("TOCONLINE_SERIE_PREFIXO", "")  # alternativa ao id
TOCONLINE_TAX_CODE      = _env("TOCONLINE_TAX_CODE", "NOR")    # classificação IVA 23% (confirmar via /taxes)
TOCONLINE_AT_MANUAL     = _env_bool("TOCONLINE_AT_MANUAL", False)  # True ⇒ chamar send_document_at_webservice
# Auth persistida (BD/segredos, não .env em prod): access_token, refresh_token, expiries
```

- O Diogo cria a série **na UI** e dá o **`id` numérico** → `TOCONLINE_SERIE_ID`.
  O adaptador confirma-a por `GET /api/commercial_document_series?filter[prefix]=CKL&filter[document_type]=FR`
  e valida `at_status`/`atcud_prefix` preenchidos (série registada na AT).
- Se preferir o prefixo, usar `document_series_prefix` na criação e dispensar o id.

### 4.2 ATCUD — ⚠️ PONTO MAIS FRÁGIL PARA A GUARDA G2
- **[VERIFICADO]** na resposta do documento existem `document_hash_sum` (hash SAF-T) e
  `hash_control`. **[VERIFICADO]** na série existe `atcud_prefix`.
- **[NÃO CONFIRMADO]** um **campo de resposta com o ATCUD COMPLETO** (`prefixo-sequencial`)
  por documento. O ATCUD completo aparece **impresso no PDF**.
- **Implicação para G2 (drop-in):** a guarda exige `atcud` **e** `saft_hash`. Opções, por
  ordem de preferência, a fechar antes de codar:
  1. **Se o Swagger/uma emissão real expuser um campo ATCUD** no documento → usá-lo direto.
  2. **Senão, compor** o ATCUD = `serie.atcud_prefix + "-" + n_sequencial` (extraído do
     `document_no`, ex. `"FR 2026/1"` → sequencial `1`). Guardar helper `_compor_atcud()`.
     Só é válido se `atcud_prefix` não estiver vazio (série registada na AT) — o que é,
     em si, a prova de certificação que G2 quer.
  3. **`saft_hash` = `document_hash_sum`** (VERIFICADO existe) — usar como a 2.ª metade de G2.
- **Recomendação:** manter G2 a exigir `atcud_valido(atcud)` **e** `saft_presente(saft_hash)`,
  onde `atcud` vem de (1) ou (2) e `saft_hash` de `document_hash_sum`. Se **nem** `atcud_prefix`
  na série **nem** um campo ATCUD existirem, **levantar `FaturaNaoCertificada`** — é o
  comportamento seguro (não emitir "boa" sem prova AT). Fechar isto na 1.ª emissão de teste.

### 4.3 Comunicação à AT — decisão operacional
- Se a série estiver em **comunicação automática** (o normal no TOConline), o documento FR
  sai já comunicado ⇒ `TOCONLINE_AT_MANUAL=False`, saltar passo [2], e G2 valida o resultado.
- Se **não**, `TOCONLINE_AT_MANUAL=True` ⇒ chamar `send_document_at_webservice` com
  `entity_username`/`entity_password` (base64) do **Portal das Finanças da Cosmic Oasis**,
  e só depois reler para G2. **Confirmar com o Diogo qual é o caso** (§6 checklist).

---

## 5. Preço/IVA — divergência face à IX (não copiar cegamente)

- Na **IX** enviamos `unit_price` **líquido** (49/1,23 = 39,84 €) + taxa `IVA23`.
- No **TOConline**, com **`vat_included_prices=true`** enviamos `unit_price=49` (bruto) e a
  API deriva o líquido. **⇒ o helper `preco_liquido()` NÃO se usa na linha** quando
  `vat_included_prices=true`; envia-se o preço de tabela tal-e-qual.
- **`total_esperado(itens)`** (guarda G3) **mantém-se**: continua a dar o preço de tabela
  (49,00 €), que é o que a API deve devolver em `total`. A implementação atual de
  `total_esperado` (base líquida + IVA) devolve 49,00 € para 49,00 € de tabela, portanto
  **serve tal como está** — mas confirmar que o `total` devolvido pelo TOConline é o **bruto
  com IVA** (esperado) e não a base. **[ASSUMIDO — validar na emissão de teste]**.
- **Alternativa** (se `vat_included_prices=true` der problemas): enviar `unit_price` líquido
  (`preco_liquido`) com `vat_included_prices=false` — aí o helper da IX reaproveita-se 1:1.
  Escolher **uma** e validar `total == 49,00 €`.

---

## 6. CHECKLIST DO DIOGO (TOConline) — o que fica dependente de ti

1. **Conta TOConline da Cosmic Oasis, Lda** ativa, com **NIF correto** e **regime normal de
   IVA (23%)** — confirmar (a mesma lógica do Radar Marca, empresa diferente/mesma conta?).
2. **Provisionar credenciais API:** *Empresa > Dados API* → adicionar integrador (nome+email)
   → recolher o **ficheiro de configuração** com `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`,
   `OAUTH_URL`, `API_URL` (**link válido 72 h — usar logo**). Dá-me estes 4 valores.
3. **Consentimento OAuth único no browser** (fluxo `authorization_code`) para gerar o
   **primeiro refresh_token** — interação humana obrigatória **uma vez**; depois automatiza.
4. **Criar a SÉRIE nova (FR) na UI** do TOConline e **registá-la na AT** (ver `at_status`/
   `atcud_prefix` preenchidos) → **dá-me o `id` numérico** (ou o prefixo) → `TOCONLINE_SERIE_ID`.
5. **Comunicação à AT:** confirmar se a série comunica **automaticamente** ao finalizar
   **ou** se é preciso o passo manual. Se manual, dá-me `entity_username`/`entity_password`
   do **Portal das Finanças** (subutilizador com permissão de comunicação de documentos).
6. **Taxa de IVA 23%:** confirmar o `tax_code` (via `GET /taxes?filter[tax_country_region]=PT`)
   → `TOCONLINE_TAX_CODE`.
7. **Decisão de preço:** `vat_included_prices=true` (unit_price=49) vs líquido — validamos
   numa emissão de teste que o **total dá 49,00 €**.
8. **Recolha do NIF no Stripe Checkout** (Tax ID / custom field obrigatório) → vai em
   `customer_tax_registration_number`. Política para cliente sem NIF (consumidor final?).
9. **Ambiente de teste:** **não há sandbox dedicada documentada** (§7). Confirmar com o
   suporte Cloudware se dá para testar sem comunicar à AT (série de teste / documento não
   comunicado), **ou** aceitar testar na conta real com 1 FR de valor mínimo e depois anular.

---

## 7. Doc FECHADA/insuficiente — o que fica por confirmar e como

**Estado da doc:** **PARCIAL** — pública para leitura (api-docs.toconline.pt, versões `.md`,
índice `/llms.txt`, Swagger no SwaggerHub, Postman), **fechada para credenciais e URLs base**
(vêm no ficheiro de *Empresa > Dados API*). **Não há sandbox, rate limits nem SDK oficial
documentados.**

**Por confirmar antes de codar (abrir o Swagger + 1 emissão real fecha quase tudo):**
- [ ] **`OAUTH_URL` / `API_URL` reais** (host `app<N>.toconline.pt`?) — do ficheiro de config.
- [ ] **Validade real do refresh_token** (8 h?) → fixa a cadência do cron.
- [ ] **Nome exato do campo da série na criação** (`document_series_id` vs
      `commercial_document_series_id` vs `document_series_prefix`).
- [ ] **Campo ATCUD completo na resposta do documento?** (senão, compor via `atcud_prefix`
      + sequencial — §4.2). **É o ponto que decide a robustez de G2.**
- [ ] **Comunicação à AT: automática ao finalizar ou passo explícito** `send_document_at_webservice`
      (e o verbo: `POST` vs `PATCH`).
- [ ] **`total` devolvido é bruto (com IVA) ou base** → fecha o helper de preço (§5) e G3.
- [ ] **Formato de data** (`yyyy-mm-dd` vs `dd/mm/yyyy`).
- [ ] **`tax_code` exato** da taxa 23% (via `/taxes`).
- [ ] **FR dispensa recibo separado** (assumido, sem frase explícita).
- [ ] **Existe criação de série por API?** (assumido que não — só UI).
- [ ] **Rate limits reais** (não documentados; tratar 429 com backoff por precaução).

**Como fechar:** (a) pedir ao Diogo o ficheiro de credenciais (desbloqueia URLs base);
(b) abrir a spec OpenAPI no SwaggerHub
(<https://app.swaggerhub.com/apis-docs/toconline.pt/toc-online_open_api/1.0.0>) e a coleção
Postman; (c) fazer **1 emissão de teste na série nova** e inspecionar a resposta crua
(ATCUD, document_hash_sum, total, communication_status). Sem sandbox, combinar com o Diogo
o teste controlado do ponto 9 da checklist.

---

## 8. Mapa de equivalência InvoiceXpress → TOConline

| Conceito | InvoiceXpress (atual) | TOConline (novo) | Estado |
|---|---|---|---|
| Auth | `?api_key=` em query (sem estado) | **OAuth2 Bearer** (authorization_code + refresh_token, 4 h) | [VERIFICADO] |
| Onde vive a auth | trivial (params) | **helper/cron externo**; cliente injetado já traz o Bearer | design |
| Host | `{conta}.app.invoicexpress.com` | `<API_URL>` (≈ `app<N>.toconline.pt`) do ficheiro de config | [ASSUMIDO host] |
| Content-Type | `application/json` | `application/vnd.api+json` (JSON:API) | [VERIFICADO] |
| Criar FR | `POST /invoice_receipts.json` (draft) | `POST /api/v1/commercial_sales_documents` (`document_type:"FR"`) | [VERIFICADO] |
| Finalizar | **passo separado** `PUT …/change-state` (`finalized`) | **automático ao submeter** (sem passo) | [VERIFICADO] |
| Root/wrapper | `{"invoice":{…}}` | `{"data":{"type":"commercial_sales_documents","attributes":{…}}}` | [VERIFICADO] |
| Série | `sequence_id` numérico | `document_series_id` (id) ou `document_series_prefix` | [ASSUMIDO nome] |
| Config série | `INVOICEXPRESS_SEQUENCE_ID` | `TOCONLINE_SERIE_ID` (id que o Diogo dá) | — |
| Cliente | `client{name,code,fiscal_id,email}` | `customer_business_name`, `customer_tax_registration_number`, email | [VERIFICADO] |
| NIF | `client.fiscal_id` | `customer_tax_registration_number` | [VERIFICADO] |
| Linha | `items[]{name,unit_price(líq),tax{name}}` | `lines[]{item_type,description,quantity,unit_price,tax_code,tax_percentage}` | [VERIFICADO] |
| Preço/IVA | `unit_price` **líquido** (39,84) + `IVA23` | `unit_price` **bruto** (49) + `vat_included_prices:true` | [VERIFICADO campo] |
| Taxa 23% | nome `"IVA23"` na conta | `tax_code` via `GET /taxes?filter[tax_country_region]=PT` | [VERIFICADO] |
| Comunicação AT | **config da conta** (Comunicação Automática), implícita no finalizar | **automática OU** `send_document_at_webservice` explícito | [VERIFICADO endpoint / ASSUMIDO qual] |
| Nº fiscal | `sequence_number` (ex. `"6/CKL"`) | `document_no` (ex. `"FR 2026/1"`) → `sequence_number` | [VERIFICADO] |
| Hash SAF-T | `saft_hash` | `document_hash_sum` → `saft_hash` | [VERIFICADO] |
| ATCUD | `atcud` (campo de resposta) | **não confirmado como campo**; compor `atcud_prefix`+sequencial | ⚠️ [A CONFIRMAR] |
| PDF | `GET /api/pdf/:id.json` (202→200) | `GET /api/url_for_print/<id>?filter[type]=Document` (componentes a concatenar) | [VERIFICADO] |
| Email pelo emissor | `POST …/email-document.json` | `PATCH /api/email/document/<id>` | [VERIFICADO] |
| Total (G3) | `total` de resposta | `total` de resposta | [VERIFICADO existe] |
| Guarda G2 | `atcud` + `saft_hash` | idem (`atcud` composto/campo + `document_hash_sum`) | contrato |
| Guarda G3 | `total` vs esperado | idem | contrato |
| Idempotência | `stripe_session_id → ix_id` | `stripe_session_id → toconline_id` | contrato |

**O que muda no código do adaptador (vs `invoicexpress_client.py`):**
1. Um **passo a menos** (não há `change-state`; FR nasce finalizado).
2. Um **passo a mais possível** (comunicação AT explícita, condicional a `TOCONLINE_AT_MANUAL`).
3. **Auth Bearer** (cliente injetado já autenticado; cron de refresh externo).
4. **Wrapper JSON:API** (`data/type/attributes`) em vez de root `"invoice"`.
5. **Preço bruto** com `vat_included_prices=true` (não usar `preco_liquido` na linha).
6. **ATCUD** possivelmente composto (helper) em vez de campo direto.
7. **PDF** por concatenação de componentes de `url_for_print`, não por polling 202.
Tudo o resto (assinatura, `FaturaRecibo`, guardas G2/G3, `total_esperado`, LIVE-GATED,
idempotência) **mantém-se idêntico**.

---

## 9. Fontes (doc oficial consultada)
- <https://api-docs.toconline.pt/> — portal, `/llms.txt`, versões `.md`
- <https://api-docs.toconline.pt/autenticacao-simplificada> · <https://api-docs.toconline.pt/autenticacao-detalhada> — OAuth2, tokens, validades
- <https://api-docs.toconline.pt/setup-do-postman> — credenciais (Empresa > Dados API), link 72 h
- <https://api-docs.toconline.pt/caracteristicas-dos-pedidos> — headers JSON:API, paginação, licença
- <https://api-docs.toconline.pt/apis/vendas/documentos-de-venda> — criar FR, document_type, série, taxa
- <https://api-docs.toconline.pt/apis/apis-auxiliares/documentos-de-serie> — séries (GET, atcud_prefix, at_status)
- <https://api-docs.toconline.pt/apis/vendas/comunicacao-de-documentos-a-at> — send_document_at_webservice
- <https://api-docs.toconline.pt/apis/vendas/descarregar-pdf-de-documentos-de-venda> — url_for_print
- <https://api-docs.toconline.pt/apis/vendas/envio-de-documentos-por-email> — email/document
- <https://app.swaggerhub.com/apis-docs/toconline.pt/toc-online_open_api/1.0.0> — spec OpenAPI (fechar ASSUMIDOS)

---

## SUMÁRIO EXECUTIVO (≤180 palavras)

**Construível já (sem esperar pelo Diogo):** todo o esqueleto do adaptador `toconline_client.py`
como **drop-in** de `invoicexpress_client.py` — mesma assinatura `emitir_fatura_recibo(*, nome,
nif, email, itens, cliente_http) -> FaturaRecibo`, mesma `FaturaRecibo`, mesmas guardas G2
(`FaturaNaoCertificada`) e G3 (`TotalInesperado`), LIVE-GATED e idempotência. Endpoints e
wrapper JSON:API estão **verificados** na doc pública: `POST commercial_sales_documents`
(`FR`, auto-finalizado), séries por GET, PDF via `url_for_print`, email, hash SAF-T
(`document_hash_sum`). O cron de refresh OAuth e o bloco de config novo também se escrevem já.
Dá para ter o adaptador **codado e testado com mocks** hoje.

**À espera de credenciais/confirmação:** `API_URL`/`OAUTH_URL` reais, `client_id/secret`
(ficheiro de *Empresa > Dados API*, link 72 h), o **`id` da série nova** (criada na UI),
o `tax_code` do IVA 23%, se a **AT é automática ou explícita**, e — o ponto mais frágil — se
existe um **campo ATCUD** na resposta ou se há que compô-lo via `atcud_prefix`+sequencial.
Não há sandbox: fechar estes pontos com o Swagger + **1 emissão de teste** na conta real.
