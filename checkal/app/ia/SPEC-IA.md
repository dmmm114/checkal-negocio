# SPEC — Camada IA (Anthropic Batch + triagem/redação)

> Contrato de construção do sprint **FDS 4** (AUTOMACAO.md §7). Não é código de produção — é o
> desenho verificado que o sprint implementa. Alinhado com `app/config.py`
> (`MODEL_TRIAGEM`, `MODEL_ALERTA`, `ANTHROPIC_API_KEY`) e AUTOMACAO.md §3.
>
> **Regra desta spec:** tudo em **VERIFICADO** tem URL da doc oficial Anthropic (fetch a
> 2026-07-05). Tudo em **ASSUMIDO** não foi confirmado contra a doc e tem de ser validado
> por um smoke-test antes de se depender dele. Nada de endpoints/campos inventados.

---

## 0. Constantes já existentes (não relitigar — vêm de `app/config.py`)

| Constante | Valor | Papel nesta camada |
|---|---|---|
| `ANTHROPIC_API_KEY` | env `ANTHROPIC_API_KEY` | credencial única (SDK lê do env por omissão) |
| `MODEL_TRIAGEM` | `claude-haiku-4-5-20251001` | Passo 1 — triagem |
| `MODEL_ALERTA` | `claude-sonnet-5` | Passo 2 — redação do alerta |

O SDK `anthropic` (Python) resolve a chave a partir de `ANTHROPIC_API_KEY` sem precisar de
a passar ao construtor. Todo o resto do CheckAL é Python 3.12 + FastAPI (AUTOMACAO.md §4), pelo
que **a camada IA usa o SDK oficial `anthropic` (Python)** — não `requests`/`httpx` à mão.

---

## 1. Fluxo end-to-end

A IA entra **só no pipeline regulatório** (AUTOMACAO.md §3). Os alertas de **estado do registo**
(desaparecido/alterado) são determinísticos por template e **nunca passam pela IA** — ficam fora
desta spec.

```
eventos_regulatorios (processado=false)
        │
        │  cron regulatório já captou o documento (Parte H DRE / contenção / câmaras)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ PASSO 1 — TRIAGEM  (Haiku 4.5, Batch, structured output JSON) │
│  input:  título + ~3.000 primeiras palavras do documento     │
│  output: {relevante_para_al, concelhos[], tipo, resumo_1_frase}│
│  regra:  "duvida" == "sim" (conservador)                     │
└───────────────┬─────────────────────────────────────────────┘
                │  guarda triagem/resumo/concelhos em eventos_regulatorios
                │  relevante(sim|duvida) → continua ; nao → arquiva
                ▼
        cruza cada evento relevante × cada cliente com AL no(s) concelho(s)
                │  (N pares evento×cliente)
                ▼
┌─────────────────────────────────────────────────────────────┐
│ PASSO 2 — REDAÇÃO  (Sonnet 5, Batch, texto simples)           │
│  1 request por par evento×cliente                            │
│  system+excerto partilhados (prompt cache 1h) ; dados do AL variam│
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 3 CAMADAS ANTI-ALUCINAÇÃO (código nosso, pós-geração)         │
│  (1) template restritivo já constrange a geração              │
│  (2) validação programática: url presente? nºs/datas ⊂ excerto?│
│  (3) 2 falhas → alerta "manual" por template sem prosa da IA  │
└───────────────┬─────────────────────────────────────────────┘
                ▼
        INSERT em `alertas` → envio por Resend (fora desta spec)
```

**Porquê Batch:** desconto de 50% e latência de horas irrelevante (cadência regulatória é
diária). Um varrimento gera dezenas de docs/mês → centenas de alertas/mês; tudo cabe folgado em
1-2 batches por corrida.

---

## 2. Batch API — endpoints, SDK, campos (VERIFICADO)

Doc: <https://platform.claude.com/docs/en/build-with-claude/batch-processing> ·
API ref: <https://platform.claude.com/docs/en/api/creating-message-batches>

### 2.1 Endpoints REST

| Ação | Método + path |
|---|---|
| Criar batch | `POST /v1/messages/batches` |
| Estado do batch | `GET /v1/messages/batches/{id}` → campo `processing_status` |
| Resultados (JSONL) | `GET` ao `results_url` que vem no objeto do batch (stream) |
| Cancelar | `POST /v1/messages/batches/{id}/cancel` |
| Listar | `GET /v1/messages/batches` |

**Sem beta header.** Batch API é GA na Claude API 1ª-parte
(<https://platform.claude.com/docs/en/build-with-claude/batch-processing>).

### 2.2 SDK Python (VERIFICADO — claude-api skill, `python/claude-api/batches.md`)

```python
import anthropic, time
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

client = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do env

# 1) criar
batch = client.messages.batches.create(requests=[
    Request(custom_id="...", params=MessageCreateParamsNonStreaming(
        model=MODEL_TRIAGEM, max_tokens=300, messages=[...], output_config={...})),
    # ...
])

# 2) pollar até terminar
while client.messages.batches.retrieve(batch.id).processing_status != "ended":
    time.sleep(60)

# 3) resultados (ordem NÃO garantida → indexar por custom_id)
for r in client.messages.batches.results(batch.id):
    if r.result.type == "succeeded":
        msg = r.result.message           # objeto Message normal
        texto = next(b.text for b in msg.content if b.type == "text")
    # errored / canceled / expired → tratar (ver 2.4)
```

`.cancel(id)` e `.list(limit=...)` também existem. `.list()` auto-pagina ao iterar.

### 2.3 Corpo do request e limites (VERIFICADO)

- Cada item: `custom_id` **único** + `params` (= um corpo Messages API normal).
- `custom_id` tem de casar `^[a-zA-Z0-9_-]{1,64}$` (1–64 chars, alfanum + `-` + `_`).
  → esquema sugerido: `t-{evento_id}` (triagem) e `a-{evento_id}-{nr_registo}` (alerta).
- Limite por batch: **100.000 requests OU 256 MB**, o que primeiro chegar.
- Cada request precisa de `max_tokens >= 1`. **`max_tokens: 0` (cache pre-warming) NÃO é aceite
  dentro de batch.**
- **Ordem dos resultados não é garantida** — casar sempre por `custom_id`, nunca por posição.
- Validação dos `params` é **assíncrona**: erros só aparecem quando o batch termina. Mitigação
  oficial: validar a forma do request com **uma** chamada Messages API normal antes de submeter
  em massa.

### 2.4 Estados e tipos de resultado (VERIFICADO)

- `processing_status`: começa `in_progress`, passa a `ended` quando todos terminaram (aí há
  `results_url`). (`canceling` durante cancelamento.)
- `request_counts`: `{succeeded, errored, canceled, expired}` — bom para o dead-man switch/log.
- 4 tipos em `result.type`:
  - `succeeded` → tem `result.message`.
  - `errored` → invalid_request ou erro interno; **não é faturado**. invalid_request = corrigir
    e resubmeter; erro interno = seguro resubmeter.
  - `canceled` → **não faturado**.
  - `expired` → passou as 24h antes de correr; **não faturado**; resubmeter.

### 2.5 Tempos, retenção, preço (VERIFICADO)

- A maioria dos batches acaba em **< 1h**; **máximo 24h** — o que não completar em 24h fica
  `expired`.
- `results_url` disponível **29 dias** após criação (depois o batch continua visível mas sem
  download).
- **Desconto de 50%** em input + output + tokens especiais (empilha com prompt caching).
- **Prompt caching dentro do batch:** suportado, mas cache-hits são *best-effort* (30–98%
  conforme tráfego). Como um batch pode demorar > 5 min, a doc recomenda **TTL de 1 hora**
  (`cache_control: {"type":"ephemeral","ttl":"1h"}`) para o contexto partilhado. Isto é a
  alavanca-chave do Passo 2 (ver §4.3).
- **Não elegível para Zero Data Retention** — os dados são retidos pela política padrão da
  feature. (Cross-ref LEGAL.md: o excerto do documento + dados do AL são enviados à Anthropic.)

---

## 3. Passo 1 — Triagem (Haiku 4.5 + structured outputs)

### 3.1 JSON garantido via `output_config.format` (VERIFICADO)

Doc: <https://platform.claude.com/docs/en/build-with-claude/structured-outputs>

- Structured outputs (`output_config.format` com `json_schema`) é **GA em Haiku 4.5 e Sonnet 5**
  (lista de modelos suportados na doc).
- **Funciona com a Batches API e com streaming** (secção "Key Takeaways" / compatibilidade).
- Regras do schema: **`additionalProperties: false` obrigatório** em cada objeto; `required`
  tem de listar os campos; **`enum` é suportado** (strings/números/bools/null). **Não** suporta
  `minLength`/`maxLength`/`pattern`/`minimum`/`maximum`/`multipleOf` nem schemas recursivos.
- Custo de compilação: 1ª chamada de um schema novo tem latência extra (compila a gramática);
  fica **em cache 24h** por estrutura de schema. → manter o schema **estável e único**.
- `messages.parse()` + Pydantic é o helper recomendado na chamada síncrona, mas **em batch o
  request é construído à mão** → passa-se `output_config` cru dentro de `MessageCreateParamsNonStreaming`
  e faz-se `json.loads()` + validação Pydantic ao texto do resultado.

### 3.2 Schema de triagem (deriva de AUTOMACAO.md §3)

```json
{
  "type": "object",
  "properties": {
    "relevante_para_al": { "type": "string", "enum": ["sim", "nao", "duvida"] },
    "concelhos":         { "type": "array", "items": { "type": "string" } },
    "tipo":              { "type": "string", "enum": ["regulamento", "contencao", "limpeza", "outro"] },
    "resumo_1_frase":    { "type": "string" }
  },
  "required": ["relevante_para_al", "concelhos", "tipo", "resumo_1_frase"],
  "additionalProperties": false
}
```

Passado como:
```python
output_config = {"format": {"type": "json_schema", "schema": <schema acima>}}
```

- **Regra conservadora (AUTOMACAO §3):** `duvida` é tratado como `sim` no código a jusante.
- Input: título + ~3.000 primeiras palavras. Haiku 4.5 tem contexto 200k → folga total.
- `max_tokens ≈ 200–300` (o JSON é curto). Haiku **não** usa `effort`/adaptive thinking; não se
  configura `thinking` (fica off por omissão) — mais barato e determinístico.
- Ler o resultado: em `succeeded`, `output_config.format` garante que o **primeiro bloco de
  texto** é JSON válido do schema → `json.loads(texto)`; validar ainda com Pydantic por defesa.
- **Custo estimado (AUTOMACAO §3):** ~$0,0025/doc com batch → ~€0,25/mês a 100 docs/mês.

---

## 4. Passo 2 — Redação do alerta (Sonnet 5, texto simples)

### 4.1 Sem structured output aqui — é prosa

O alerta é **texto em PT-PT** (não JSON), logo **não** se usa `output_config.format`. A garantia
de qualidade vem das 3 camadas anti-alucinação (§5), não do schema.

### 4.2 Gotchas do Sonnet 5 (VERIFICADO — claude-api skill, migração Sonnet 5)

- **Adaptive thinking está LIGADO por omissão** quando o campo `thinking` é omitido. Isto gasta
  tokens de pensamento e conta contra `max_tokens` → um alerta de ~400 tokens pode truncar ou
  encarecer. **Decisão desta spec: `thinking={"type":"disabled"}`** para redação determinística
  a seguir a template (alertas curtos, latência já irrelevante no batch).
- **Parâmetros de amostragem removidos:** `temperature`, `top_p`, `top_k` → **400 se enviados**.
  Não usar `temperature=0`; a fidelidade vem do prompt + validação, não da temperatura.
- Novo tokenizer (~30% mais tokens que Sonnet 4.6 p/ o mesmo texto) — dar folga a `max_tokens`
  (o template pede ≤180 palavras; `max_tokens ≈ 600` é seguro).
- **Prefill removido** (400 na última msg assistant) — não aplicável (não usamos prefill).

### 4.3 Template + prompt caching (fan-out evento × clientes)

O template do system + o excerto do documento são **idênticos** para todos os N clientes do mesmo
evento; só variam os DADOS DO AL. Estruturar o prompt como:

```
tools → system → messages          # ordem de render (estável → volátil)
[ system: papel + regras invioláveis + EXCERTO do documento ]  ← cache_control ephemeral 1h
[ user:   DADOS DO AL específicos deste cliente ]              ← varia, sem cache
```

- Colocar `cache_control: {"type":"ephemeral","ttl":"1h"}` no **último bloco partilhado** (o
  excerto). O 50% do batch **empilha** com o desconto de cache-read (~0,1× do input).
- Ordenar sempre estável-antes-de-volátil: qualquer byte volátil antes do breakpoint invalida a
  cache (prefix-match). Nada de `datetime.now()`/IDs no system.
- Template do system e do user já estão redigidos em AUTOMACAO.md §3 — reutilizar tal e qual
  (regras: baseia-te só no excerto; cita a fonte {url}; nunca inventes números/prazos/coimas;
  ≤180 palavras; estrutura (a)(b)(c)). Diogo confirma a redação final PT-PT.
- **Custo estimado (AUTOMACAO §3):** ~$0,011/alerta com batch → ~€5/mês no cenário carregado.

---

## 5. Três camadas anti-alucinação (código nosso — VERIFICADO contra AUTOMACAO §3)

> A API garante **forma** (JSON no Passo 1), **nunca** garante **veracidade factual**. O
> grounding é imposto pelo nosso código no pós-processamento. Estas camadas são código do
> CheckAL, não features da API.

1. **Template restritivo (na geração):** o system proíbe informação fora do excerto, obriga a
   escrever "o documento não especifica" quando falta, e obriga a citar `{url}`. (§4.3)
2. **Validação programática (pós-geração), por alerta:**
   - O `{url}` fornecido **tem de constar** literalmente do texto gerado.
   - Qualquer **valor monetário ou data** mencionado no texto tem de **existir no excerto**
     (regex match contra o excerto original). Se aparecer um número/data que não está no
     excerto → alerta reprovado.
   - Falha → **regenerar** (nova tentativa) ou despromover.
3. **Fallback "manual" (rede de segurança):** após **2 falhas** de validação, envia-se um alerta
   por template **sem prosa da IA**:
   `"Foi publicado {titulo} que pode afetar o teu AL em {concelho}. Lê aqui: {url}"`.
   Nunca fica nada por comunicar.

Regex a implementar (guia, não exaustivo): valores monetários `€\s?\d[\d.\s]*` / `\d[\d.\s]*\s?€`
e datas PT (`\d{1,2}/\d{1,2}/\d{4}`, `\d{1,2}\s+de\s+\w+\s+de\s+\d{4}`). Normalizar espaços/pontos
antes de comparar. **Refinar contra amostra real** de documentos da Parte H no FDS 4.

**Também tratar `stop_reason == "refusal"`** (VERIFICADO — structured outputs doc): num refusal o
output pode não respeitar o schema/template → tratar como falha de validação e cair no fallback.

---

## 6. Modo de teste / sandbox

Não há "sandbox" separado na Anthropic — testa-se contra a API real com a chave normal:

1. **Smoke-test unitário (síncrono, barato):** antes de qualquer batch, correr **uma**
   `client.messages.create(...)` com o mesmo `params` (a doc recomenda validar a forma via
   Messages API porque a validação do batch é assíncrona). Um doc real da Parte H → confirmar
   que a triagem devolve JSON do schema e o alerta passa as 3 camadas. É o critério de "feito"
   do FDS 4 (AUTOMACAO §7).
2. **Batch de 2 requests:** replicar o exemplo mínimo da doc (2 `custom_id`) para exercitar
   create → poll `processing_status` → `results()` → indexação por `custom_id`.
3. **Custo de teste desprezável** (Haiku + Sonnet, poucos requests, com 50% batch).
4. **Chaves de teste vs produção:** usar uma workspace/chave separada de dev se quiser isolar
   billing (opcional; a Anthropic não tem "test mode" tipo Stripe).

---

## 7. O que o Diogo tem de fornecer (contas, chaves, decisões)

| # | Item | Detalhe |
|---|---|---|
| 1 | **Conta Anthropic + `ANTHROPIC_API_KEY`** | criar em console.anthropic.com; pôr em `.env` como `ANTHROPIC_API_KEY`. |
| 2 | **Tier de rate-limit suficiente** | Batches têm limites próprios (RPM da API de batches + nº de requests em fila). Cenário CheckAL é minúsculo (dezenas–centenas/mês), mas confirmar que o tier inicial os cobre. |
| 3 | **Confirmar os model IDs** | `MODEL_TRIAGEM=claude-haiku-4-5-20251001`, `MODEL_ALERTA=claude-sonnet-5` já em config.py — só validar que a conta tem acesso. |
| 4 | **Decisão: `thinking` no Sonnet 5** | esta spec recomenda `disabled` (ver §4.2); confirmar. |
| 5 | **Redação final PT-PT do template** | o rascunho está em AUTOMACAO.md §3; congelar a versão final (impacta caching — mantê-la estável). |
| 6 | **Cadência do cron de batch** | quando submeter/pollar (ex.: a seguir ao cron regulatório das 07h00). Decisão operacional. |
| 7 | **Ciente RGPD** | excerto do doc + dados do AL vão para a Anthropic; batches não são ZDR. Cruzar com LEGAL.md antes de produção. |

Não é preciso nenhum beta header, nenhuma infra extra, nenhuma dependência além do SDK `anthropic`.

---

## 8. Riscos / gotchas

| Risco | Impacto | Mitigação |
|---|---|---|
| Sonnet 5 com thinking adaptive ligado por omissão | tokens/€ a mais, `max_tokens` truncado | `thinking={"type":"disabled"}` explícito (§4.2) |
| Enviar `temperature`/`top_p`/`top_k` ao Sonnet 5 | **400** | não enviar nenhum parâmetro de amostragem |
| Assumir ordem dos resultados do batch | alerta cai no cliente errado | indexar **sempre** por `custom_id` |
| Validação do batch é assíncrona | erros de forma só aparecem no fim (24h perdidas) | smoke-test síncrono da forma antes de submeter (§6.1) |
| `custom_id` fora do regex `^[a-zA-Z0-9_-]{1,64}$` | batch rejeita | usar `t-{id}` / `a-{id}-{nr}`; nada de `:`/espaços |
| Grammar compilation na 1ª chamada de schema novo | latência extra + micro-custo | manter o schema de triagem estável e único (cache 24h) |
| Batch pode expirar às 24h sob carga | requests `expired` (não faturados) | reprocessar `expired`/`errored(interno)`; dead-man switch lê `request_counts` |
| Prompt cache best-effort em batch (30–98%) | poupança variável | TTL 1h no excerto; ordenar estável→volátil (§4.3) |
| Structured output num `refusal` | JSON pode não bater certo | tratar `stop_reason=="refusal"` como falha → fallback manual |
| IA "inventa" coima/prazo apesar do template | erro factual grave (destrói confiança) | camada 2 (regex nºs/datas ⊂ excerto) + fallback (§5) |
| Batches não elegíveis a ZDR | dados retidos na Anthropic | decisão/registo RGPD (LEGAL.md) antes de produção |

---

## 9. Pontos ASSUMIDOS a confirmar (não verificados contra a doc)

1. **Nesting exato de `output_config` dentro de `MessageCreateParamsNonStreaming` no batch.** A
   doc confirma que structured outputs "funciona com a Batches API" e que `output_config` é um
   param normal de `messages.create`, mas **não vi um exemplo oficial batch+structured-output
   combinados**. → **smoke-test:** submeter 1 request de triagem em batch e confirmar que o
   `succeeded.message.content[0].text` é JSON do schema. (Confiança alta, mas por confirmar.)
2. **Assinaturas exatas dos objetos de resultado do SDK** (`r.result.type`, `r.result.message`,
   `r.result.error.type`) — vêm da skill/exemplos, não de execução real nesta sessão. Confirmar
   ao correr o batch de 2 requests.
3. **`cache_control` com `ttl:"1h"` dentro de `params` de batch** aceite tal e qual — a doc diz
   para usar TTL 1h em batches, mas confirmar a chave exata no corpo do request via smoke-test.
4. **Rate limits concretos** da Batches API para o tier inicial da conta do Diogo — depende da
   conta; ler `x-ratelimit-*` / a página de rate limits após criar a chave.
5. **Redação final do template** (AUTOMACAO §3 é rascunho) — decisão do Diogo, não facto de API.
6. **Regex de valores/datas PT** — o desenho está fixado, mas os padrões concretos têm de ser
   calibrados contra uma amostra real de documentos da Parte H no FDS 4.

---

### Fontes oficiais citadas
- Batch processing — <https://platform.claude.com/docs/en/build-with-claude/batch-processing>
- Batches API ref — <https://platform.claude.com/docs/en/api/creating-message-batches>
- Structured outputs — <https://platform.claude.com/docs/en/build-with-claude/structured-outputs>
- Tool use / `tool_choice` (alternativa de JSON garantido) — <https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview>
