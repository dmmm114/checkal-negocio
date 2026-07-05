# CheckAL — Arquitetura de Automação 100% (zero-touch)

> Parte do dossier CheckAL. Cadência canónica (PLANO-NEGOCIO.md §5): página individual dos CLIENTES = diária; varrimento nacional = 2×/semana; SLA contratual ≤7 dias.

## Arquitetura de automação 100% (zero-touch)

**Princípio de desenho:** o sistema é um pipeline batch com meia dúzia de crons idempotentes sobre uma base Postgres, não uma aplicação "viva". Tudo o que falha tem retry; tudo o que é ambíguo pára e avisa o dono em vez de agir. É o mesmo padrão do pipeline INPI do Radar Marca — reutiliza-se a filosofia e parte do código de diffing.

### 1. Pipeline de dados RNAL

**Cadência: 2×/semana (segunda e quinta, 03h00).** Semanal chegava para diffing, mas 2× reduz a janela de deteção de cancelamentos para ≤4 dias e dá redundância: um varrimento falhado não deixa a semana às escuras.

**Custo de um varrimento completo (conta):** Lisboa = 11.854 registos, 6,1 MB, 63 s. País ≈ 120.000 registos ≈ 10× Lisboa ≈ 62 MB e ~11 min de transferência efetiva. Com 308 pedidos sequenciais + pausa de 2 s entre concelhos (educação para com a API): **~25-35 min por varrimento**. Guardar o JSON bruto gzipado (~9 MB/varrimento) → **<1 GB/ano** de histórico completo. Irrelevante em custo.

**Esquema de BD (Postgres):**

```sql
CREATE TABLE registos (
  nr_registo      integer PRIMARY KEY,
  data_registo    date,
  nome_alojamento text, modalidade text, nr_camas int, nr_utentes int,
  endereco text, cod_postal text, freguesia text, concelho text, distrito text,
  titular_tipo    text,        -- 'singular' | 'coletiva'
  titular_nome    text, nif text, telefone text, telemovel text, email text,
  hash_campos     text,        -- sha256 dos campos relevantes, p/ diffing barato
  visto_primeiro  timestamptz, visto_ultimo timestamptz,
  desaparecido_em timestamptz  -- NULL = ativo
);

CREATE TABLE varrimentos (
  id serial PRIMARY KEY, iniciado_em timestamptz, concluido_em timestamptz,
  concelhos_ok int, concelhos_falhados int, total_registos int,
  raw_path text, estado text   -- 'ok' | 'parcial' | 'abortado'
);

CREATE TABLE eventos_registo (
  id serial PRIMARY KEY, nr_registo int REFERENCES registos,
  tipo text,                   -- 'novo' | 'desaparecido' | 'alterado' | 'reapareceu'
  campos_alterados jsonb, varrimento_id int, detetado_em timestamptz,
  processado boolean DEFAULT false
);

CREATE TABLE detalhes_cliente (   -- só para registos de clientes pagantes
  nr_registo int PRIMARY KEY, estado_detalhado text,
  seguro_companhia text, seguro_apolice text, seguro_validade date,
  obtido_em timestamptz
);

CREATE TABLE clientes (
  id serial PRIMARY KEY, email text, nome text, nif text,
  stripe_customer_id text, plano text, estado text,  -- 'ativo'|'em_dunning'|'cancelado'
  criado_em timestamptz
);
CREATE TABLE clientes_registos (cliente_id int, nr_registo int, PRIMARY KEY (cliente_id, nr_registo));

CREATE TABLE eventos_regulatorios (
  id serial PRIMARY KEY, fonte text, url text UNIQUE, titulo text,
  publicado_em date, concelhos text[], triagem text,  -- 'relevante'|'irrelevante'|'duvida'
  resumo_ia text, processado boolean DEFAULT false
);

CREATE TABLE alertas (
  id serial PRIMARY KEY, cliente_id int, nr_registo int,
  origem text, origem_id int,   -- ('eventos_registo'|'eventos_regulatorios', id)
  conteudo text, enviado_em timestamptz, canal text DEFAULT 'email'
);
```

**Diffing:** comparar o conjunto de `nr_registo` do varrimento N com o estado da tabela `registos`. Novo → `INSERT` + evento `novo`. Presente mas `hash_campos` diferente → evento `alterado` com diff de campos. Ausente → **regra dos 2 varrimentos**: só marcar `desaparecido` (= cancelado/suspenso) se faltar em dois varrimentos consecutivos E o concelho tiver devolvido resposta válida em ambos. Isto elimina falsos alarmes por timeouts parciais da API — crítico, porque um falso "o teu registo foi cancelado" destrói a confiança no produto.

**Detalhe individual (estado + seguro) — decisão: Playwright só para clientes, com descoberta do endpoint em paralelo.** Não vale a pena resolver o postback ASP.NET para 120k registos: o produto só precisa do detalhe para clientes pagantes (centenas). Playwright headless a ~3 s/página × 500 clientes = 25 min, **diário** (03h30 — cadência canónica: o Produto promete deteção diária do estado dos clientes e o custo é residual) + no onboarding de cada cliente novo. Na primeira sessão de Playwright, gravar o tráfego de rede (`page.on("request")`) para identificar o XHR interno que a shell de 22 KB chama; quando identificado, substituir Playwright por `httpx` direto e o custo cai para segundos. Não é bloqueante: o sistema arranca com Playwright.

### 2. Pipeline regulatório

**DRE — facto verificado: não existe API pública de dados abertos documentada** para o Diário da República (nem em [dados.gov.pt](https://dados.gov.pt/) nem no site da [INCM](https://incm.pt/site/diario-da-republica/)). Mas os regulamentos municipais de AL saem todos no mesmo sítio: **2.ª série, Parte H (Autarquias Locais)** do [diariodarepublica.pt](https://diariodarepublica.pt/dr/home) — confirmado por amostragem (ex.: [Regulamento n.º 884/2024, Loulé](https://diariodarepublica.pt/dr/detalhe/regulamento/884-2024-876155645), [Regulamento n.º 927/2025, Braga](https://files.diariodarepublica.pt/2s/2025/07/142000000/0037800403.pdf)). Estratégia em duas camadas:

1. **Cron diário (07h00)**: consultar a pesquisa do site filtrada a 2.ª série/Parte H com os termos "alojamento local", "área de contenção", "crescimento sustentável". O site é OutSystems com backend JSON (`screenservices`) — mesmo padrão de descoberta do rnal.aspx: interceta-se uma vez com Playwright, chama-se direto para sempre. Fallback robusto: o PDF integral diário da 2.ª série é **gratuito** com URL previsível (`files.diariodarepublica.pt/gratuitos/2s/AAAA/MM/...`) — descarregar, extrair texto (`pypdf`), grep de keywords + nomes de concelho. O fallback sozinho já chega para o MVP.
2. **Fontes complementares (cron semanal):** página de áreas de contenção do Turismo de Portugal (scrape + diff de HTML) e páginas de "Regulamentos" das câmaras dos **20 concelhos com mais AL** (Lisboa, Porto, Albufeira, Loulé, Portimão, Funchal, Lagos, Cascais, Sintra, Olhão…), que concentram >50% do mercado. Diff de HTML por hash; qualquer alteração vai para triagem IA.

Cada documento captado entra em `eventos_regulatorios` com `concelhos[]` extraídos por regex (o cabeçalho da Parte H identifica sempre o município) e segue para a camada IA.

### 3. Camada IA

**Modelos — decisão: Haiku 4.5 para triagem, Sonnet para redação, ambos via Batch API** (50% de desconto; latência de horas é irrelevante aqui).

**Passo 1 — Triagem (Haiku 4.5, $1/$5 por MTok).** Input: título + primeiras ~3.000 palavras do documento. Output JSON estrito (structured outputs): `{relevante_para_al: sim|nao|duvida, concelhos: [...], tipo: regulamento|contencao|limpeza|outro, resumo_1_frase}`. **Regra conservadora: `duvida` é tratado como `sim`.** Custo: ~4k tokens in + 200 out ≈ $0,005/doc; com batch, $0,0025. Mesmo a 100 docs/mês: **~€0,25/mês**.

**Passo 2 — Alerta personalizado (Sonnet).** Para cada `evento_regulatorio` relevante × cada cliente com AL no concelho afetado, uma chamada com este template:

```
SISTEMA: És o analista do CheckAL. Escreves alertas em PT-PT para proprietários
de Alojamento Local não-técnicos. Regras invioláveis:
1. Baseia-te EXCLUSIVAMENTE no excerto fornecido. Se a informação não estiver no
   excerto, escreve "o documento não especifica".
2. Cita sempre a fonte com o link fornecido. Nunca inventes números, prazos ou coimas.
3. Na dúvida sobre se afeta o cliente, assume que PODE afetar e recomenda verificação.
4. Estrutura: (a) O que aconteceu — 1 frase. (b) Afeta o teu AL? sim/não/possivelmente
   + porquê, referindo os dados concretos do AL. (c) O que deves fazer + prazo se existir.
5. Máximo 180 palavras. Sem jargão jurídico.

UTILIZADOR:
DADOS DO AL: nº {nr_registo}, "{nome_alojamento}", {modalidade}, {freguesia},
{concelho}, registado em {data_registo}, titular {tipo}.
DOCUMENTO: {titulo}, publicado {data}, fonte: {url}
EXCERTO: {texto}
```

Custo por alerta: ~5k tokens in × $3/M + 400 out × $15/M ≈ **$0,021; com batch ~$0,011 (~€0,01)**. Cenário carregado — 10 eventos/mês × 50 clientes afetados = 500 alertas ≈ **€5/mês**. A IA é a linha de custo mais barata do negócio.

**CheckALs anti-alucinação (três camadas):** (1) o template proíbe informação fora do excerto e obriga a citar a fonte; (2) validação programática pós-geração — o `{url}` tem de constar do texto final, e qualquer valor monetário/data mencionado tem de existir no excerto (regex match), senão o alerta é regenerado ou despromovido para o formato "manual"; (3) formato "manual" de recurso: se a validação falhar 2×, envia-se um alerta template sem prosa da IA ("Foi publicado {titulo} que pode afetar o teu AL em {concelho}. Lê aqui: {url}") — nunca fica nada por comunicar. Alertas de **estado do registo** (desaparecido/alterado) nem passam pela IA: são determinísticos, gerados por template a partir do diffing.

### 4. Stack de aplicação

Decisões concretas, otimizadas para um operador único que já trabalha em Python:

| Camada | Escolha | Custo/mês |
|---|---|---|
| Runtime | **Python 3.12 + FastAPI**, tudo num repo, Docker Compose | — |
| BD | **Postgres 16** no mesmo VPS | — |
| Servidor | **Hetzner CX32** (4 vCPU/8 GB — folga para Playwright) + Caddy | ~€8 |
| Crons | **systemd timers** no VPS (não cron do Kubernetes, não Airflow — nada disso é preciso) | — |
| Landing | Estático (Astro ou HTML puro) servido pelo Caddy; widget de verificação chama `GET /api/verificar?q=` que lê a BD local → resposta instantânea, sem depender da API do TP em tempo real | — |
| Billing | **Stripe Payment Links** no arranque (plano anual com auto-renovação + link trienal one-off) + **Customer Portal** para cancelamento/fatura self-service. Um único webhook (`checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`) no FastAPI trata do fulfillment. Migrar para Checkout embebido só quando houver razão | 1,5%+0,25€/tx |
| Faturação PT | **InvoiceXpress via API** — o Stripe cobra, mas a fatura-recibo certificada pela AT é obrigação legal desde a primeira venda. Webhook `checkout.session.completed` → `POST /invoice-receipts` com NIF do cliente (campo custom no checkout) → PDF anexado ao email de boas-vindas + comunicação automática à AT (SAF-T) | ~€10 |
| Email transacional | **Resend** (alertas, relatórios, dunning) — 3.000 emails/mês grátis, depois $20 | €0-18 |
| Email de prospeção | **Separado por completo**: domínio irmão (ex. `getcheckal.com`) + SMTP dedicado com warm-up e throttle. Nunca misturar frio com transacional — a reputação do `checkal.pt` é um ativo operacional | ~€30 quando ativo |
| LLM | API Anthropic (Haiku 4.5 + Sonnet, Batch) | <€10 |
| Backups/monitor | Hetzner Storage Box + Healthchecks.io (grátis) + UptimeRobot (grátis) | ~€4 |

**Total de infra: ~€35-50/mês** contra um objetivo de €1.500/mês de receita — margem bruta >95%.

**Cartas físicas — facto verificado: os CTT têm o serviço [e-carta](https://www.ctt.pt/empresas/encomendas-e-correio/enviar/producao-e-digitalizacao-de-correio/impressao-e-envelopagem/index)** (upload de PDF → os CTT imprimem, envelopam e distribuem, entrega ≤3 dias úteis), mas **sem API REST pública documentada** — é um portal para empresas. Decisão: as cartas servem a *aquisição* (campanha a titulares "pessoa singular"), não o loop operacional, portanto não precisam de ser zero-touch. Fluxo: script gera um PDF multi-carta (mail-merge com nº RNAL e mini-diagnóstico personalizado de cada prospect) → upload semanal ao portal e-carta em lote → 10 minutos de trabalho humano por semana, aceitável e pausável nas férias. Se um dia justificar, automatiza-se o upload com Playwright.

### 5. Automação do ciclo de vida

- **Onboarding (alvo: primeiro relatório <15 min após pagamento):** o Payment Link inclui um campo custom "nº de registo AL (ou nome do alojamento)". Webhook → matching automático contra `registos` (por `nr_registo`; fallback fuzzy por nome+concelho) → dispara Playwright para o detalhe (estado + seguro) → gera o **Relatório Inicial** (PDF: estado do registo, seguro, área de contenção do concelho, regulamentos ativos) → email via Resend + entrega do selo "CheckAL ✓ — AL Verificado" (PNG/SVG + snippet para o anúncio + link para a página pública de verificação `checkal.pt/selo/{nr_registo}`). Se o matching falhar (estimativa: <5% dos casos), email automático a pedir o nº correto e tarefa na fila do dono — único ponto semi-manual.
- **Renovações e dunning:** subscrição anual Stripe com auto-renew. Sequência por cron diário: **D-30** email "a tua proteção renova a {data}" (com resumo do valor entregue: "este ano monitorizámos X varrimentos e Y alterações no teu concelho" — reduz churn); **D-7** aviso de cobrança; **D0** Stripe cobra (Smart Retries ligado: 4 tentativas em 2 semanas); **D+3 e D+7** emails de falha com link Stripe para atualizar cartão; **D+21** downgrade para estado `cancelado` + email final "o teu AL deixou de estar monitorizado" (que é, em si, o melhor email de win-back possível). Trienal pré-pago: sem dunning durante 3 anos; email de renovação a D-30 do fim.
- **Cancelamento:** 100% self-service no Stripe Customer Portal; webhook marca o cliente e corta alertas. Zero fricção, zero email de "fala connosco".
- **Suporte 1.ª linha por IA:** mailbox `apoio@checkal.pt` → cron de 15 min lê via IMAP → Sonnet com knowledge base (FAQ do produto, noções de AL, estado atual do cliente injetado da BD) → responde diretamente a perguntas factuais ("qual é o estado do meu registo?", "como mudo o cartão?"); **escala para o dono** (forward + Telegram) se detetar: pedido jurídico específico, reclamação, intenção de cancelar com queixa, ou confiança baixa. Estimativa: <10 emails/semana com 370 clientes low-touch; a IA resolve 80%.

### 6. Observabilidade e fiabilidade (teste das 3 semanas de férias)

- **Dead-man switch em todos os crons:** cada job faz ping ao Healthchecks.io no fim; job que não corre ou falha → email + Telegram ao dono. Cobertura: varrimento RNAL, DRE diário, dunning, suporte, backup.
- **Deteção de mudança de esquema/API:** validação Pydantic do JSON da API `list_RNAL`; chave em falta ou tipo errado → varrimento marcado `abortado`, sem diffing, alerta ao dono. O sistema **nunca** faz diffing sobre dados suspeitos.
- **Circuit breaker de alertas em massa — por concelho, com desambiguação automática.** Um breaker global seria um erro de desenho: as limpezas em massa reais parecem-se com "API partida" (a limpeza de Lisboa cancelou 6.765 registos ≈ 5,6% da base nacional; a do Porto, 1.413 ≈ 14,5% do concelho) e um corte global de 3% teria calado os clientes precisamente no maior evento do ano — a semana em que a promessa "nunca serás apanhado de surpresa" mais vale. Regra: se um **concelho** marcar >3% da sua base como `desaparecido` num varrimento (baseline ~0,2%/semana), o breaker dispara **só para esse concelho** e o sistema desambigua sozinho antes de decidir: amostra 10-20 páginas individuais (`rnal.aspx?nr=`) dos registos desaparecidos via Playwright. Se as páginas devolvem "cancelado"/"suspenso" → o evento é **real**, os alertas seguem imediatamente (e o dono recebe um FYI, não um pedido de ação). Se devolvem 404/timeout/vazio → é a API partida → alertas desse concelho suspensos, eventos guardados como `processado=false`, retry no varrimento seguinte. Só o caso ambíguo (mistura de respostas, amostra inconclusiva) escala para o dono por email + Telegram. Os restantes concelhos nunca são afetados pelo breaker de um concelho vizinho. Custo da desambiguação: 20 páginas × 3 s = 1 minuto de Playwright — o preço de nunca falhar em silêncio no momento de maior valor do produto.
- **Backups:** `pg_dump` noturno → Storage Box Hetzner com retenção 30 dias + cópia semanal para um segundo fornecedor (B2). Restore testado 1×/trimestre.
- **Comportamento em ausência:** tudo é idempotente e re-executável; a única degradação de 3 semanas sem toque é a pausa das cartas de prospeção e suporte escalado a responder "estamos a analisar" (auto-reply da IA com promessa de prazo). Receita, alertas e cobranças não param.

### 7. Plano de construção (sprints de fim de semana)

Realista para quem já construiu o pipeline INPI — muito código de diffing, envio e billing transfere-se quase direto.

| Sprint | Entregável | Critério de "feito" |
|---|---|---|
| **FDS 1** | Ingestão dos 308 concelhos, BD, diffing, regra dos 2 varrimentos | 2 varrimentos completos guardados; eventos gerados corretamente num teste com dados mutados |
| **FDS 2** | Landing estática + widget de verificação gratuita + Stripe Payment Links + webhook de fulfillment + **integração InvoiceXpress** (fatura-recibo com NIF, comunicação AT) | Consigo pagar-me a mim próprio, ficar registado como cliente **e receber fatura certificada no email — sem isto não se pode vender legalmente nem a 1 cliente** |
| **FDS 3** | Onboarding automático (matching + Playwright detalhe + Relatório Inicial PDF + selo) + **página pública do selo** (`GET /selo/{nr_registo}` sobre dados que já estão na BD — meio-dia de trabalho, não é v2: é o mecanismo de retenção/viralidade e o onboarding já a promete) + alertas determinísticos de estado | Compra→relatório sem intervenção humana em <15 min; o link do selo mostra "AL Monitorizado" a qualquer visitante |
| **FDS 4** | Pipeline DRE (fallback PDF gratuito + grep) + triagem Haiku + alertas Sonnet com validação anti-alucinação | Documento real da Parte H gera alerta correto e citado para cliente de teste |
| **FDS 5** | Dunning D-30/D-7/D0/D+7, suporte IA por IMAP, Healthchecks + circuit breaker por concelho com desambiguação + backups | Simulação de cartão falhado percorre a sequência toda; matar um cron dispara alerta; simulação de limpeza em massa num concelho de teste segue o ramo certo (real→alerta, API→suspensão) |
| **FDS 6** | Motor de campanhas gatilho→segmento→envio: evento do diffing (registo novo, limpeza num concelho, alteração relevante) → segmentação automática (coletiva→email frio via domínio irmão; singular→lote e-carta) → campanha no ar em <72h | Um registo novo inserido em teste gera, sem toque humano, o email/carta de prospeção correspondente dentro da janela de 72h |

**MVP vendável ao fim do FDS 3** (~3 semanas de calendário): monitorização de estado do registo já justifica os 49€/ano; o regulatório entra no FDS 4 como reforço da promessa. **Honestidade sobre o GTM nos primeiros ~2 meses:** até o FDS 6 estar entregue, o motor de campanhas "zero humanos" **não existe** — as campanhas às listas da base instalada são semi-manuais: o sistema gera os segmentos e os PDFs/emails, o dono revê e dispara (10-15 min/dia). É aceitável (e até desejável, para calibrar copy e deliverability antes de automatizar), mas fica dito: o "zero-touch" total do GTM só é verdade a partir do FDS 6. **Fica para v2:** dashboard do tier Portfólio, resolução do endpoint interno do rnal.aspx e do screenservices do DRE (otimizações, não bloqueadores), automação do upload e-carta, e win-back automatizado de ex-clientes.

**Decisão-síntese:** um VPS, um repo Python, seis crons, Stripe, InvoiceXpress e duas APIs de email. Nada de filas, microserviços ou orquestradores — a escala deste negócio (120k registos, centenas de clientes, dezenas de documentos regulatórios/mês) cabe folgadamente num único servidor de €8/mês, e cada peça a mais seria superfície de falha durante as férias.
