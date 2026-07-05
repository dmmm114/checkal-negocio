# SPEC — Integração DRE (Diário da República) · Pipeline Regulatório

> Contrato de construção (committado junto do código). Alinhado com **AUTOMACAO.md §2** (pipeline
> regulatório) e §3 (camada IA). Alimenta a tabela `eventos_regulatorios` (AUTOMACAO.md §1) que
> depois cruza com `clientes_registos` para gerar `alertas`.
>
> **Objetivo desta integração:** detetar, ≤24 h após publicação, regulamentos municipais de
> Alojamento Local publicados na **2.ª série, Parte H (Autarquias Locais)** do Diário da República,
> extrair concelho(s) afetado(s) e texto, e entregar à camada IA (triagem Haiku → redação Sonnet).
>
> **Regra anti-alucinação desta spec:** cada afirmação técnica está marcada **[VERIFICADO]** (com o
> URL da fonte oficial testada em 2026-07-05) ou **[ASSUMIDO]** (não confirmado — a validar antes de
> construir). NUNCA tratar um **[ASSUMIDO]** como facto no código.

---

## 0. Decisão de arquitetura (resumo)

Duas camadas, como em AUTOMACAO.md §2. **O MVP constrói só a Camada A** (fallback robusto). A Camada B
(endpoint JSON OutSystems) é otimização posterior, não bloqueante.

| Camada | Fonte | Estado | Papel |
|---|---|---|---|
| **A — PDF integral diário** | `files.diariodarepublica.pt/gratuitos/2s/...` | **[VERIFICADO]**, robusto | **Fonte primária do MVP.** Descarrega o PDF integral gratuito da 2.ª série, extrai texto, filtra Parte H por keywords, extrai concelhos. |
| **B — Endpoint JSON (OutSystems screenservices)** | `diariodarepublica.pt/dr/...` | **[ASSUMIDO]**, requer interceção Playwright | Otimização: pesquisa incremental filtrada por série/parte/keywords sem descarregar 15–30 MB/dia. Só depois de A estar a correr. |

**Porquê A primeiro:** o site é uma SPA OutSystems React (o HTML inicial da página de detalhe tem só
~2,3 KB — é uma shell; os dados carregam por `screenservices` POST). Não há API pública documentada
(confirmado: nem em dados.gov.pt — que só serve BASE/contratos — nem na INCM). O PDF integral, por
outro lado, é gratuito, tem URL previsível e conteúdo estável há anos. **É o alicerce.**

---

## 1. Fluxo end-to-end (Camada A — MVP)

```
cron diário 07h00 (AUTOMACAO.md §2)
  │
  ├─ 1. resolver o(s) número(s) de edição de ontem/hoje da 2.ª série  ── §3.2 (contador auto-corretivo)
  │
  ├─ 2. descarregar PDF integral gratuito  ── files.diariodarepublica.pt/gratuitos/2s/AAAA/MM/2S{NNN}A0000S00.pdf
  │        (guardar bruto gzipado em SNAPSHOTS_DIR, à imagem do RNAL; ~15–31 MB → ~5–10 MB gz)
  │
  ├─ 3. extrair texto  ── pypdf (fallback pdftotext/pymupdf)
  │
  ├─ 4. isolar a secção PARTE H do SUMÁRIO  ── entre "PARTE H | Autarquias locais" e o início do corpo
  │        → lista de (MUNICÍPIO, tipo_ato, nº_ato, título)
  │
  ├─ 5. triagem por keywords  ── "alojamento local", "área de contenção", "crescimento sustentável", …
  │        sobre título + corpo do ato; município → concelho normalizado (config.concelhos_todos())
  │
  ├─ 6. para cada ato candidato: extrair o TEXTO INTEGRAL do corpo (localiza nº do ato no corpo do PDF)
  │
  ├─ 7. dedup + persistir em `eventos_regulatorios`  ── chave natural = URL do ato (UNIQUE) ou (nº_ato, ano)
  │        campos: fonte='DRE', url, titulo, publicado_em, concelhos[], triagem='duvida' (default)
  │
  └─ 8. entregar à camada IA (AUTOMACAO.md §3): Haiku triagem → se relevante/dúvida, Sonnet redige alerta
           por cliente com AL no(s) concelho(s) afetado(s).
```

**Idempotência:** re-correr o mesmo dia não duplica eventos (URL/nº do ato é UNIQUE em
`eventos_regulatorios.url`). Tudo o que é ambíguo (edição não encontrada, extração falha, drift de
layout) **pára e avisa o dono**, não inventa — mesmo princípio do FDS 1.

---

## 2. Endpoints, URLs e formatos concretos

### 2.1 PDF integral diário gratuito — [VERIFICADO]

**Padrão de URL:**
```
https://files.diariodarepublica.pt/gratuitos/2s/{AAAA}/{MM}/2S{NNN}A0000S00.pdf
```
- `{AAAA}` = ano (4 díg.); `{MM}` = mês (2 díg., zero-pad).
- `{NNN}` = **número da edição** da 2.ª série (3 díg., zero-pad). Sequencial dentro do ano; **reinicia em janeiro**. NÃO é o dia-do-ano (ver §3.2).
- Sufixo literal `A0000S00`.

**Amostras testadas (2026-07-05, HTTP 200, `application/pdf`):**
- `.../gratuitos/2s/2026/02/2S029A0000S00.pdf` → 484 págs, ~15 MB, edição "N.º 29 • 11 de fevereiro de 2026". **[VERIFICADO]**
- `.../gratuitos/2s/2025/07/2S142A0000S00.pdf` → ~31 MB, contém Regulamento 927/2025 de Braga (AL). **[VERIFICADO]**
- Padrão `2S{NNN}A0000S00` confirmado em 7 edições distintas (029, 021, 034, 081, 121, 142, 204) de 2017–2026. **[VERIFICADO]**

**Página 1 — cabeçalho parseável (para auto-correção do contador, §3.2):** [VERIFICADO]
```
N.º 29 • 11 de fevereiro de 2026
2.ª série
```
Regex sugerido: `r"N\.º\s*(\d+)\s*•\s*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})"`.

**Estrutura interna do PDF (verificada em 2S029):** [VERIFICADO]
1. **SUMÁRIO** (índice) no topo, organizado por PARTE (C, D, E, F, G, H), listando por ato: entidade → nº do ato → título.
2. **CORPO** a seguir: texto integral de cada ato.
3. Ordem das partes no sumário: `PARTE C | Governo…`, `PARTE D | Tribunais…`, `PARTE E | Entidades administrativas independentes…`, `PARTE F | Regiões Autónomas`, `PARTE G | Empresas públicas`, **`PARTE H | Autarquias locais`** (última). (A 1.ª série tem Partes A/B; a 2.ª série de autarquias é sempre **Parte H**.)

> **[ASSUMIDO]** Nem toda a edição diária tem Parte H (dias sem publicações de autarquias). O código
> tem de tolerar ausência da secção sem rebentar. (Plausível mas não verificado exaustivamente.)

> **[ASSUMIDO]** Edições com **suplemento** (ex.: nº com "1º suplemento") terão sufixo de ficheiro
> diferente de `A0000S00`. Padrão do suplemento **não verificado**. Os regulamentos de AL costumam
> sair na edição principal, mas suplementos existem — a confirmar (ver §7).

### 2.2 Secção PARTE H do sumário — extração de concelho + ato — [VERIFICADO]

No sumário, a Parte H lista, para cada autarquia, um cabeçalho em MAIÚSCULAS seguido dos atos:
```
PARTE H | Autarquias locais
MUNICÍPIO DE BRAGA
Regulamento n.º 927/2025
<título do regulamento em 1+ linhas>
MUNICÍPIO DE BRAGANÇA
Aviso n.º ...
...
```
Cabeçalhos de entidade observados (verificados em edições reais): [VERIFICADO]
`MUNICÍPIO DE <X>`, `MUNICÍPIO DO <X>` (ex. "MUNICÍPIO DO SEIXAL"), `CÂMARA MUNICIPAL DE <X>`,
`FREGUESIA DE <X>`, `UNIÃO DAS FREGUESIAS DE <X>`.
> Para AL o relevante é o **MUNICÍPIO/CÂMARA MUNICIPAL** (o regulamento é municipal). Freguesias/uniões
> podem ser ignoradas para efeitos de concelho, mas o `<X>` do MUNICÍPIO mapeia diretamente a `concelho`.

**Delimitação da secção Parte H no sumário:** de `"PARTE H | Autarquias locais"` até ao início do
corpo (primeira repetição do cabeçalho de página / primeiro ato do corpo). Estratégia robusta: a Parte H
é a **última** parte do sumário → vai de `"PARTE H | Autarquias locais"` até à próxima linha que seja
o cabeçalho de página do corpo (`r"N\.º\s*\d+\s*•.*\d{4}"` repetido, ou primeiro `MUNICÍPIO…` que
reaparece muito mais abaixo). **[ASSUMIDO — a robustez exata do delimitador de fim do sumário deve ser
testada com ≥10 edições reais; ver §7.]**

**Extração de concelho — dois métodos (usar #1 como primário, #2 como rede):**
1. **Parse do sumário Parte H** (limpo, poucos falsos positivos): dividir a secção por cabeçalhos
   `^(MUNICÍPIO|CÂMARA MUNICIPAL)\s+(DE|DO|DA|D')\s+(.+)$` → cada bloco = (concelho, [(tipo,nº,título)]).
2. **Grep no texto integral** (rede de segurança): para cada ocorrência de keyword, localizar o
   cabeçalho `MUNICÍPIO …` imediatamente anterior. (Verificado: no corpo da edição de Braga, cada
   página do ato repete "MUNICÍPIO DE BRAGA" + "Regulamento n.º 927/2025" no rodapé — âncora fiável.)

**Normalização de concelho:** passar `<X>` (title-case, corrigir "D'"/"DE"/"DO"/"DA") e cruzar com
`config.concelhos_todos()` / `config.CONCELHOS_PRIORITARIOS`. Guardar só concelhos reconhecidos em
`eventos_regulatorios.concelhos[]`; nome não reconhecido → registar para revisão do dono (não descartar).

### 2.3 Triagem por keywords — [parcialmente VERIFICADO]

Keywords canónicas (AUTOMACAO.md §2): `"alojamento local"`, `"área de contenção"`,
`"crescimento sustentável"`. Sugestão de conjunto alargado (a afinar): `"alojamento local"`, `"AL"`
(só com fronteira de palavra e contexto — alto ruído, usar com cuidado), `"área de contenção"`,
`"contenção"`, `"crescimento sustentável"`, `"registo nacional de alojamento local"`, `"RNAL"`,
`"taxa municipal turística"`, `"alojamento de curta duração"`.
- **[VERIFICADO]** `grep -i "alojamento local"` na edição de Braga (2S142/2025) → **10 ocorrências**
  no corpo do Regulamento 927/2025 (título, âmbito, cessação de atividade, etc.).
- **[VERIFICADO]** `grep -i "alojamento local"` na edição 2S029/2026 → **0 ocorrências** (dia sem
  regulação de AL) → confirma que a keyword filtra ruído corretamente (a maioria dos dias é 0 hits).
- **Comparação de keywords deve ser feita sobre texto normalizado** (minúsculas, sem acentos, espaços
  colapsados) porque o pdftotext parte palavras por quebras de linha/hifenização.

### 2.4 PDF de extrato por ato (individual) — [VERIFICADO, mas requer metadados]

Padrão (edições antigas e novas coexistem):
```
https://files.diariodarepublica.pt/2s/{AAAA}/{MM}/{NNN}000000/{PPPPP}{QQQQQ}.pdf
```
- `{NNN}000000` = número da edição + zeros. (Ex.: `142000000`.)
- `{PPPPP}{QQQQQ}` = página inicial + página final, **5 díg. cada, concatenadas**.
  - **[VERIFICADO]** `.../2s/2025/07/142000000/0037800403.pdf` → 26 págs = páginas **378–403**
    (`00378`+`00403`). É o extrato SÓ do Regulamento 927/2025 de Braga (~960 KB).
- **Vantagem:** descarrega só o ato (KB) em vez da edição inteira (MB).
- **Limitação:** exige saber o intervalo de páginas do ato → só disponível via metadados do ato
  (página de detalhe / endpoint JSON, Camada B). **Não é construível às cegas.** No MVP não se usa;
  fica documentado para a Camada B.

### 2.5 Página de detalhe do ato — [VERIFICADO que é SPA]

```
https://diariodarepublica.pt/dr/detalhe/{tipo}/{numero}-{ano}-{id}
  ex.: https://diariodarepublica.pt/dr/detalhe/regulamento/927-2025-876155645
```
- **[VERIFICADO]** É uma SPA **OutSystems React** (`OutSystemsReactView.js`, `dr.index.js`,
  `dr.appDefinition.js`). O HTML inicial tem ~2,3 KB (shell + loaders); **os dados vêm por chamadas
  `screenservices` após render** — por isso um GET simples/`WebFetch` devolve página vazia.
- **[VERIFICADO]** `dr.appDefinition.js` servido é um stub de ~664 bytes → **não** revela nomes de
  módulo/screen estaticamente. O nome do módulo e o caminho screenservices **têm de ser descobertos ao
  vivo** (interceção Playwright, `page.on("request")`), como diz AUTOMACAO.md §2.

### 2.6 Camada B — endpoint JSON OutSystems (screenservices) — [ASSUMIDO]

Forma **típica** de um endpoint OutSystems Reactive (padrão geral da plataforma, NÃO confirmado para
este site):
```
POST https://diariodarepublica.pt/dr/screenservices/{Módulo}/{Bloco}/{Ação}/DataActionGet...
Content-Type: application/json
Body: {"versionInfo": {...}, "viewName": "...", "inputParameters": {...}}
```
- **Tudo ASSUMIDO:** nome do módulo, do bloco, da data action, e a forma exata dos parâmetros
  (filtro série/parte/keywords/datas). **NÃO inventar no código.** O procedimento correto (AUTOMACAO §2):
  1. Playwright abre a pesquisa do site filtrada a 2.ª série/Parte H + keyword.
  2. `page.on("request")` grava o(s) POST `screenservices`.
  3. Reproduzir esse POST com `httpx` e fixar o contrato **depois de observado**.
- Até lá, Camada B fica por especificar. Camada A não depende disto.

---

## 3. Detalhes operacionais críticos

### 3.1 Extração de texto do PDF

- **Primário:** `pypdf` (já disponível: v6.x). **Fallback:** `pdftotext` (poppler, verificado a
  extrair estas edições corretamente) ou `pymupdf`/`fitz` (disponível). Recomendação: **pymupdf** dá
  melhor fidelidade de layout de colunas em DRs; validar contra pypdf.
- Edições grandes (484 págs / 31 MB) extraem em segundos — custo desprezável (cron noturno).
- **Normalizar** o texto extraído (unicode NFC, colar hifenização de fim de linha, colapsar espaços)
  antes de keyword-match e de extração de concelho.

### 3.2 Resolver o número da edição (`{NNN}`) — GOTCHA principal

O ficheiro é indexado por **número de edição**, não por data, e o número reinicia todo o ano — logo
não há fórmula data→número. **Solução: contador auto-corretivo** (verificável porque a página 1 do PDF
diz o número E a data — §2.1):
1. Guardar em BD o último `(numero, data)` processado da 2.ª série.
2. No cron, tentar `numero+1`, `numero+2`, … (a 2.ª série sai em dias úteis; pode haver >1 edição/dia
   em datas de pico, mas o número é sempre sequencial).
3. Para cada candidato: HTTP GET do PDF; se 404 → não existe ainda, parar. Se 200 → ler a linha 1,
   **confirmar que a data ∈ {ontem, hoje}** e que `numero` da página == candidato. Só então processar.
4. Persistir o novo `(numero, data)`. Nunca saltar números (um salto = edição perdida → avisar dono).
- **Arranque a frio:** semear o contador manualmente com o número/data de uma edição recente conhecida.
- **[ASSUMIDO]** que 404 é o código devolvido para número inexistente — a confirmar (pode ser 403/página
  HTML). O código deve tratar "não-PDF ou não-200" como "ainda não existe".

### 3.3 Cadência e config

- Cron **diário 07h00** (AUTOMACAO.md §2). Não há constante DRE em `config.py` — **adicionar**:
  `DRE_CRON_HORA = 7`, `DRE_KEYWORDS = [...]`, `DRE_PDF_BASE = "https://files.diariodarepublica.pt/gratuitos/2s"`,
  `DRE_USER_AGENT` (reutilizar o padrão de `RNAL_USER_AGENT`: `"CheckAL/1.0 (+https://checkal.pt; …)"`).
- Reutilizar `SNAPSHOTS_DIR` para o PDF bruto gzipado (histórico barato, à imagem do RNAL).
- Persistência em `eventos_regulatorios` (tabela já no esquema, AUTOMACAO.md §1) com tipos portáteis
  (SQLite dev / Postgres prod), como no FDS 1: `concelhos text[]` → `JSON`, `publicado_em` → `Date`.

### 3.4 Entrega à camada IA (fronteira com AUTOMACAO.md §3)

- `eventos_regulatorios` novos entram com `triagem` por preencher. **Passo 1 — Haiku**
  (`config.MODEL_TRIAGEM` = `claude-haiku-4-5-20251001`): input = título + ~3.000 palavras; output JSON
  estrito `{relevante_para_al, concelhos[], tipo, resumo_1_frase}`. **Regra: `duvida` == `sim`.**
- **Passo 2 — Sonnet** (`config.MODEL_ALERTA`): redige alerta por (evento × cliente com AL no concelho),
  com as três camadas anti-alucinação (template proíbe info fora do excerto; validação programática de
  URL/valores; formato "manual" de recurso). Ambos via **Batch API** (50% desconto).
  > **[ASSUMIDO — verificar em SPEC de IA / claude-api]** `config.MODEL_ALERTA` está como
  > `"claude-sonnet-5"` (sem sufixo de data). Confirmar o ID exato do modelo Sonnet e o suporte do
  > Batch API antes de faturar tokens. (Fora do âmbito desta integração DRE, mas é a fronteira a jusante.)

---

## 4. Modo de teste / sandbox

- **Não há sandbox** — os PDFs gratuitos são públicos e imutáveis. Testar contra **edições reais fixas**
  (fixtures determinísticas), sem rede nos testes:
  - **Fixture positiva:** 2S142/2025 (Braga, Regulamento 927/2025 de AL) → deve gerar ≥1 evento com
    `concelhos=["Braga"]` e título do regulamento.
  - **Fixture negativa:** 2S029/2026 → **0 eventos** (nenhuma keyword de AL) → confirma que não há
    falsos positivos.
  - **Fixture de robustez:** edição sem Parte H → não rebenta, 0 eventos.
- Guardar 2–3 PDFs reais (ou o texto já extraído, mais leve) como fixtures em `tests/fixtures/dre/`.
- O cliente HTTP é **injetado/mockado** nos testes (como no `app/rnal/client.py`) — nada de rede real.
- **Teste de aceitação:** dado o PDF de Braga como fixture, o pipeline produz exatamente 1 evento
  regulatório com concelho "Braga", URL/nº do ato corretos, e o texto integral do ato disponível para a IA.

---

## 5. O que o Diogo tem de fornecer (contas / chaves / decisões)

1. **Nada de contas/chaves para a Camada A** — os PDFs gratuitos são anónimos e públicos. (Vantagem
   grande: zero dependência de credenciais para a fonte primária.)
2. **Decisão — conjunto final de keywords** (§2.3): confirmar/afinar a lista. Trade-off recall vs ruído
   (ex.: incluir "taxa municipal turística"? incluir "contenção" isolado?).
3. **Decisão — âmbito de concelhos:** monitorizar os 308 (`concelhos.txt`) ou só os prioritários? Para
   Parte H, sugestão: **captar todos os concelhos** (o custo é o mesmo — 1 PDF/dia) e filtrar a jusante
   por quem tem clientes lá.
4. **Semear o contador de edição** (§3.2) com um `(numero, data)` recente conhecido no arranque.
5. **[Fase 2 / Camada B]** Autorizar uma sessão Playwright para intercetar o endpoint `screenservices`
   (só quando/se se quiser a pesquisa incremental — não bloqueia o MVP).
6. **Chave Anthropic** (`ANTHROPIC_API_KEY`) — já é dependência global do produto (camada IA), não
   específica do DRE.

---

## 6. Riscos e gotchas

| # | Risco | Mitigação |
|---|---|---|
| R1 | **Número de edição** não é derivável da data e reinicia por ano | Contador auto-corretivo com verificação pela página 1 (§3.2); nunca saltar números; salto → avisar dono. |
| R2 | **Suplementos** de edição têm sufixo de ficheiro diferente de `A0000S00` (padrão não verificado) | §7-Q4. Enquanto não confirmado, se o `numero+1` "salta" um dia com regulação, o dono é avisado; considerar também varrer o índice do site. |
| R3 | **pdftotext/pypdf partem palavras** (hifenização, colunas) → keyword falha | Normalizar texto (colar hífens de fim de linha, colapsar espaços, remover acentos) antes do match. |
| R4 | **Falsos negativos de keyword** (regulamento de AL que não usa "alojamento local" no título mas sim "arrendamento de curta duração" ou outra formulação) | Keyword-set alargado + `duvida==sim` na IA + rede de segurança: correr Haiku sobre TODOS os regulamentos (não só avisos) da Parte H, keyword ou não. Regulamentos são poucos/dia. |
| R5 | **PDF integral pesado** (15–31 MB/dia) | Custo trivial (cron noturno, <1 GB/ano gz). Descarregar com timeout generoso e retry. |
| R6 | **Layout do sumário muda** (INCM redesenha o PDF) → delimitação da Parte H parte-se | Testes de drift: se "PARTE H | Autarquias locais" não for encontrado mas houver keywords no corpo, **não descartar** — cair para o método #2 (grep integral + âncora MUNICÍPIO) e avisar o dono. |
| R7 | **Concelho não reconhecido** (grafia, freguesia em vez de município) | Cruzar com lista canónica; não-reconhecido vai para fila de revisão do dono, nunca é silenciosamente descartado. |
| R8 | **Alucinação da IA** sobre prazos/coimas do regulamento | As três camadas de AUTOMACAO §3 (template restrito, validação programática de valores/URL, formato manual de recurso). Determinístico onde possível. |
| R9 | **Legal/disclaimer** | Cada alerta leva "informação, não aconselhamento" (CLAUDE.md, LEGAL.md). A fonte (URL do DR) é sempre citada. |
| R10 | **Camada B (screenservices) frágil** — muda quando a INCM faz deploy OutSystems | Por isso é otimização, não fundação. Camada A (PDF) é o contrato estável. Se B partir, o produto continua a funcionar com A. |

---

## 7. Pontos ASSUMIDOS a confirmar (checklist bloqueante antes de fechar o contrato)

- [ ] **Q1 — Nem toda a edição tem Parte H.** Confirmar comportamento em dias sem autarquias (secção
      ausente). *(§2.1; assumido plausível, testar com ≥10 edições.)*
- [ ] **Q2 — Delimitador de FIM da secção Parte H do sumário.** Fixar a heurística exata (onde acaba o
      sumário e começa o corpo) contra ≥10 edições reais variadas. *(§2.2)*
- [ ] **Q3 — Código HTTP para número inexistente** (404 vs 403 vs HTML). Tratar "não-200/não-PDF" como
      "ainda não publicado". *(§3.2)*
- [ ] **Q4 — Padrão de ficheiro de SUPLEMENTOS** (`2S{NNN}...` com sufixo ≠ `A0000S00`). Descobrir e
      cobrir, ou aceitar o risco R2 documentado. *(§2.1)*
- [ ] **Q5 — Pode haver >1 edição da 2.ª série no mesmo dia?** (afeta o passo do contador). *(§3.2)*
- [ ] **Q6 — Endpoint screenservices (Camada B):** módulo, bloco, data action, forma dos parâmetros —
      TUDO por intercetar ao vivo. Nada disto pode aparecer no código como facto. *(§2.6)*
- [ ] **Q7 — Extrato por ato (§2.4):** confirmar que o intervalo de páginas vem sempre dos metadados do
      ato (Camada B) e que a codificação `{PPPPP}{QQQQQ}` é estável. *(verificado 1 caso; generalizar.)*
- [ ] **Q8 — ID do modelo Sonnet** (`config.MODEL_ALERTA="claude-sonnet-5"`) e suporte Batch API —
      confirmar via referência claude-api antes de faturar. *(fronteira a jusante, §3.4)*
- [ ] **Q9 — Cobertura Açores/Madeira:** regulamentos das Regiões Autónomas saem na **Parte F** (Regiões
      Autónomas) ou na Parte H (autarquias madeirenses/açorianas)? Funchal é município → **Parte H**
      (verificado indiretamente: gatilho Funchal jun/2026 é regulamento municipal). Confirmar mecânica
      para regiões. *(RNAL exclui Açores — fase 2; mas o gatilho de lançamento Funchal é Parte H.)*

---

## 8. Fronteiras de módulos (proposta de construção — a detalhar no plano do sprint)

Análoga ao FDS 1 (fronteiras disjuntas, lógica pura testável sem rede):

- `app/regulatorio/dre_client.py` — HTTP: resolver número (§3.2), descarregar PDF, guardar gz. Cliente injetável.
- `app/regulatorio/dre_pdf.py` — **puro**: extrair texto (pypdf/pymupdf), normalizar. Testável com fixtures.
- `app/regulatorio/dre_parse.py` — **puro**: isolar Parte H, mapear MUNICÍPIO→atos, keyword-match,
  normalizar concelho contra `config.concelhos_todos()`, extrair texto integral do ato. Testável com fixtures.
- `app/regulatorio/dre_ingest.py` — orquestra (único a tocar BD): parse → dedup por URL/nº → persistir
  `eventos_regulatorios` → marcar para IA. Idempotente.
- `tests/fixtures/dre/` — 2S142-2025 (positiva Braga), 2S029-2026 (negativa), edição sem Parte H (robustez).

**Fora de âmbito deste sprint:** Camada B (screenservices), extrato por ato (§2.4), a própria camada IA
(vive em AUTOMACAO §3 / SPEC de IA), billing.

---

### Anexo — fontes verificadas (testadas 2026-07-05)

- PDF integral gratuito 2.ª série (padrão): `https://files.diariodarepublica.pt/gratuitos/2s/2026/02/2S029A0000S00.pdf` (484 pp; contém "PARTE H | Autarquias locais")
- Edição com regulamento de AL: `https://files.diariodarepublica.pt/gratuitos/2s/2025/07/2S142A0000S00.pdf` ("alojamento local" ×10; MUNICÍPIO DE BRAGA → Regulamento 927/2025)
- Extrato por ato (Braga 927/2025): `https://files.diariodarepublica.pt/2s/2025/07/142000000/0037800403.pdf` (26 pp = pp. 378–403)
- Página de detalhe (SPA OutSystems React): `https://diariodarepublica.pt/dr/detalhe/regulamento/927-2025-876155645`
- Confirmado sem API pública de dados abertos do DR/legislação (dados.gov.pt só serve BASE/contratos): `https://dados.gov.pt/`
