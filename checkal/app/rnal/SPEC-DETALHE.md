# SPEC — Detalhe individual RNAL (estado + seguro RC)

> Contrato de construção do módulo que obtém, por **registo de cliente pagante**, o
> detalhe da página individual do RNAL: estado do registo e **bloco do Seguro de
> Responsabilidade Civil** (companhia, apólice, validade). Alinhado com AUTOMACAO.md §1
> (tabela `detalhes_cliente`), FDS 3 (onboarding) e a cadência canónica (detalhe dos
> clientes = **diário**, `config.CADENCIA_CLIENTE_DIAS = 1`).
>
> **Âmbito:** só clientes (centenas de registos). **NÃO** fazer scraping em massa dos
> ~120k registos nacionais — isso é o que a API `list_RNAL` já cobre (FDS 1). Este
> documento é o contrato do sprint; não é código de produção.
>
> Verificação feita a **2026-07-05** contra a página live. Todas as afirmações estão
> marcadas **[VERIFICADO]** (com a fonte de onde saiu) ou **[ASSUMIDO]** (por confirmar).

---

## 0. Descoberta principal (muda o plano do AUTOMACAO.md)

**[VERIFICADO]** A página individual é **totalmente server-rendered**: um `GET` simples com
o parâmetro `nr` devolve o HTML já com **todos os dados**, incluindo a tabela do seguro RC.
**Não há shell + XHR a preencher.** Ou seja, **`httpx` + parser HTML resolve o caso hoje —
Playwright não é necessário** para a página de detalhe.

- Fonte: `GET https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=100031`
  → `HTTP 200`, `Content-Type: text/html; charset=utf-8`, corpo ~21 KB **com os dados
  reais no HTML** (tabela seguro: `Zurich | 009238995 | 2025-12-12 | 2026-12-11`).
- É uma app **OutSystems "Traditional" (WebForms) sobre `Microsoft-IIS/10.0`**
  (`<form action="RNAL.aspx" id="WebForm1">`, `__VIEWSTATE` presente na resposta, cookies
  `ASP.NET_SessionId`/`osVisitor`/`osVisit`). Apps OutSystems Traditional renderizam no
  servidor — daí os dados virem já no HTML.

> **Reconciliação com AUTOMACAO.md §1:** o texto assume "shell de 22 KB que chama um XHR
> interno, descobrir com `page.on('request')` e migrar para httpx". **A premissa do XHR não
> se confirma para esta página** — os 22 KB *são* a página com os dados. A gravação de
> tráfego com Playwright continua a ser útil como **passo de descoberta único** (confirmar
> que não há nenhuma chamada assíncrona escondida por trás de um estado que eu não vi, p.ex.
> um registo cancelado), mas o **caminho de produção é httpx direto**, não Playwright.

**Consequência:** o plano recomendado inverte a ordem — **httpx é o primário** (verificado a
funcionar), **Playwright fica como fallback** (só se aparecer proteção anti-bot sob carga, ou
se um estado ainda não observado precisar de JS). Ver §5.

---

## 1. Fluxo end-to-end

```
                      (onboarding de cliente novo)          (cron diário 03h30)
                                 │                                   │
                                 ▼                                   ▼
                     para cada nr_registo do cliente ────────────────┘
                                 │
                                 ▼
      httpx GET rnal.aspx?nr=<n>  (UA=config.RNAL_USER_AGENT, timeout, 1 retry)
                                 │
                 ┌───────────────┼────────────────────────────┐
                 ▼               ▼                             ▼
        página com dados   "Registo não encontrado"      erro rede / 5xx / timeout
        (bloco seguro)      (~30 KB, sem bloco seguro)         │
                 │               │                             ▼
                 ▼               ▼                     NÃO escrever nada;
        parse_detalhe()   estado = "nao_encontrado"    retry no próximo ciclo
                 │         (provável cancelado/         (não marcar cancelado só
                 ▼          suspenso — ver §2/§6)        por falha de rede)
   { estado_detalhado,           │
     seguro_companhia,           ▼
     seguro_apolice,      upsert detalhes_cliente (estado, obtido_em)
     seguro_validade }           │
                 │               │
                 └──────┬────────┘
                        ▼
        upsert em `detalhes_cliente` (PK nr_registo):
        estado_detalhado, seguro_companhia, seguro_apolice, seguro_validade, obtido_em
                        │
                        ▼
        regras determinísticas (FDS 3 / camada de alertas — fora deste módulo):
          - seguro_validade < hoje ........ alerta "seguro caducado"
          - seguro_validade < hoje+30d .... alerta "seguro a expirar"
          - bloco seguro ausente/vazio .... alerta "sem seguro RC visível"
          - estado != ativo ............... alerta "registo cancelado/suspenso"
```

Tabela destino (AUTOMACAO.md §1, já canónica):

```sql
CREATE TABLE detalhes_cliente (   -- só para registos de clientes pagantes
  nr_registo int PRIMARY KEY, estado_detalhado text,
  seguro_companhia text, seguro_apolice text, seguro_validade date,
  obtido_em timestamptz
);
```

> Nota de esquema: a página expõe também **"Data início"** da apólice, que **não** existe em
> `detalhes_cliente`. Decisão do Diogo: ignorar, ou juntar coluna `seguro_inicio date`
> (recomendado — barato e útil para a copy "apólice de X a Y"). Ver §4.

---

## 2. Campos concretos verificados (seletores e mapeamento)

### 2.1 Bloco do Seguro RC — **[VERIFICADO]**

Fonte: HTML de `rnal.aspx?nr=100031`, `?nr=1`, `?nr=5`, `?nr=100` (2026-07-05).

Estrutura server-rendered:

```html
<div ...>Seguro de Responsabilidade Civil</div>
<table class="TableRecords ..." id="RichWidgets_wt7_block_wtMainContent_wt2_wtTableRecords_Seguro">
  <thead><tr>
    <th>Companhia de Seguros</th><th>Apólice nº</th><th>Data início</th><th>Validade</th>
  </tr></thead>
  <tbody><tr>
    <td>Zurich</td><td>009238995</td><td>2025-12-12</td><td>2026-12-11</td>
  </tr></tbody>
</table>
```

| Coluna HTML | Campo `detalhes_cliente` | Exemplos verificados |
|---|---|---|
| Companhia de Seguros | `seguro_companhia` (text) | `Zurich`, `CA Seguros`, `Generali Tranquilidade` |
| Apólice nº | `seguro_apolice` (text) | `009238995`, `03662951`, `0007859994` (**manter string** — têm zeros à esquerda) |
| Data início | *(sem coluna; ver §4)* | `2025-12-12`, `2026-07-03` |
| Validade | `seguro_validade` (date) | `2026-12-11`, `2025-08-01`, `2025-07-03` |

- **[VERIFICADO]** Datas no formato **ISO `YYYY-MM-DD`** em todos os 4 exemplos.
- **[VERIFICADO]** Em todos os 4 exemplos a tabela tem **exatamente 1 linha** de dados.
- **[VERIFICADO]** A validade **pode estar no passado** e a linha continua listada
  (ex.: `?nr=100` → validade `2025-07-03`, já caducada a 2026-07-05). Isto **é** o sinal de
  produto "seguro caducado": comparar `seguro_validade` com `date.today()`, não confiar em
  qualquer estado textual.

**Âncora de parsing recomendada:** localizar pelo **texto do cabeçalho** ("Seguro de
Responsabilidade Civil" e as `<th>` "Companhia de Seguros"/"Apólice nº"/"Validade"),
**não** pelo `id="RichWidgets_wt7_block_..._wtTableRecords_Seguro"`. Os `id` OutSystems
(`wt7`, `wt2`, ...) **são regenerados a cada republicação** da app — ancorar neles é frágil
(ver §6). Parser sugerido: `selectolax` (rápido) ou `lxml`.

### 2.2 Restante detalhe do registo — **[VERIFICADO]** (presente no mesmo HTML)

Todos server-rendered (exemplo `?nr=100031`):

- **RNAL nº**: `100031/AL` · **Registado em**: `2019-07-16`
- **Nome do Alojamento**: `BAIXA DE FARO ROOFTOP`
- **Data de abertura ao público**, **Data de registo na Câmara Municipal**,
  **Imóvel posterior a 1951?**, **Nº título de autorização de utilização**
- **Modalidade**: `Estabelecimento de hospedagem`
- **Capacidade** (tabela): Nº Utentes / Nº Quartos / Nº Camas / Nº Dormitórios / Nº Beliches
- **Localização** (tabela `..._wtTableRecords_Local`): via, porta, andar, código postal,
  localidade, freguesia, concelho, distrito
- **Titular(es)** (tabela `..._wtTableRecords_Titular`): Na qualidade de / NIPC-NIF /
  Firma ou nome / Contactos (email)

> Estes campos **já vêm da API `list_RNAL`** (FDS 1) e não precisam de re-scraping por aqui.
> Servem só como **verificação cruzada** no onboarding (confirmar que o `nr` do cliente casa
> com o registo certo). O detalhe individual **acrescenta o que a API não tem: o seguro RC**.

### 2.3 Estado do registo — **[PARCIALMENTE VERIFICADO / ASSUMIDO]**

- **[VERIFICADO]** Para um registo **ativo**, **não há** um rótulo textual "Estado: Ativo"
  nem "Situação" na página. A presença do bloco de dados + bloco seguro = registo válido.
- **[VERIFICADO]** Para um `nr` **inexistente** (`?nr=100032`, `?nr=99999999`), a resposta é
  **HTTP 200** mas uma **página diferente (~30 KB)**, sem bloco seguro e sem "RNAL nº", com a
  mensagem literal: **"Registo não encontrado, pesquise por Atividade!"**.
- **[ASSUMIDO — POR CONFIRMAR, ALTA PRIORIDADE]** Como aparece um registo **cancelado** ou
  **suspenso**. Duas hipóteses, nenhuma confirmada (não tive um `nr` cancelado real para
  testar):
  1. Passa a devolver a mesma página "Registo não encontrado" (i.e. cancelado ≡ removido).
  2. Continua a renderizar mas com um banner/rótulo de estado ("Cancelado"/"Suspenso").

  **Detecção de estado neste módulo (proposta segura enquanto (1)/(2) não estão confirmadas):**
  ```
  estado_detalhado =
    "ativo"          se HTML tem bloco de dados + "RNAL nº <n>/AL"
    "nao_encontrado" se HTML == página "Registo não encontrado" (marcador textual)
    "indeterminado"  caso contrário  (→ pára e avisa; não gerar alerta de cancelamento)
  ```
  O **sinal fiável de cancelamento continua a ser o diffing nacional da `list_RNAL`**
  (FDS 1, regra dos 2 varrimentos). Este módulo **confirma/enriquece**, não é a fonte
  primária do "cancelado". Ver §6 (gotcha #1).

---

## 3. Modo de teste / sandbox

**Não existe sandbox** — é um portal público do Turismo de Portugal. Estratégia de teste:

1. **Fixtures HTML gravados** (recomendado, testes offline e determinísticos): guardar em
   `app/rnal/tests/fixtures/` os HTML reais já capturados —
   - `detalhe_ativo_com_seguro.html` (ex.: `nr=100031`, seguro válido)
   - `detalhe_seguro_caducado.html` (ex.: `nr=100` — validade 2025-07-03)
   - `detalhe_nao_encontrado.html` (ex.: `nr=100032`)
   - **(a obter)** `detalhe_cancelado.html` / `detalhe_suspenso.html` — assim que o Diogo
     fornecer um `nr` real cancelado (ver §4).
   Testar `parse_detalhe(html) -> DetalheRNAL` contra cada fixture. **Zero rede nos testes**
   (mesmo princípio do `client.py` do FDS 1).
2. **Teste de contrato/smoke (opt-in, marcado, fora do CI):** um teste que faz 1 GET real a
   `nr=100031` e valida que o parser ainda encontra o bloco seguro — deteta quando o Turismo
   de Portugal muda o layout. Correr manualmente/agendado, nunca no CI normal.
3. **Descoberta única com Playwright (uma só vez, não é produção):** abrir a página com
   `page.on("request", ...)` a registar todo o tráfego, para **confirmar empiricamente que
   não há nenhum XHR** por trás de nenhum estado (sobretudo o estado cancelado, ainda não
   observado). Guardar o log. Se confirmar zero XHR relevante → Playwright sai do plano.

---

## 4. O que o Diogo tem de fornecer

| # | Item | Porquê | Bloqueia o quê |
|---|---|---|---|
| 1 | **Um `nr` de registo comprovadamente CANCELADO e um SUSPENSO** (ex.: dos 1.413 cancelamentos do Porto) | Confirmar §2.3 — como a página representa esses estados. É o maior buraco de conhecimento. | Deteção de estado no detalhe; fixture de teste |
| 2 | **Decisão de esquema:** juntar `seguro_inicio date` a `detalhes_cliente`? | A página dá "Data início" da apólice; útil para copy, mas não está no schema canónico | Migração da tabela |
| 3 | **Decisão de política:** cadência do refresh do detalhe dos clientes = diária às 03h30 (já em `config.CADENCIA_CLIENTE_DIAS=1`) — confirmar hora e se onboarding dispara refresh imediato | Agendamento (FDS 3) | Cron |
| 4 | **Parecer sobre educação de acesso:** UA identificável (`config.RNAL_USER_AGENT` já o faz), 1 req/registo/dia, pausa entre pedidos. Confirmar que está confortável com o volume (centenas/dia) a um portal do Estado | Boa vizinhança / risco reputacional | — |

**Nada de novas contas/chaves.** Não há autenticação: é acesso público. As constantes já
existem em `app/config.py`: `RNAL_PAGINA` (= `https://rnt.turismodeportugal.pt/rnt/rnal.aspx`),
`RNAL_USER_AGENT`, `RNAL_TIMEOUT_S`, `RNAL_PAUSA_S`. **Reutilizar essas — não criar novas.**

---

## 5. Estratégia de implementação (recomendada)

- **Primário — httpx** (verificado a funcionar hoje):
  `GET {config.RNAL_PAGINA}?nr=<n>`, header `User-Agent: config.RNAL_USER_AGENT`,
  `timeout=config.RNAL_TIMEOUT_S`, **1 retry** com backoff, `follow_redirects=True`.
  Não é preciso enviar cookies nem `__VIEWSTATE` (verificado: o 1.º GET já devolve os dados).
  Pausa `config.RNAL_PAUSA_S` entre registos.
- **Parser puro** `parse_detalhe(html: str) -> DetalheRNAL` (sem I/O — testável por fixture):
  ancorar por **texto de cabeçalho** (ver §2.1), devolver
  `estado_detalhado, seguro_companhia, seguro_apolice, seguro_validade[, seguro_inicio]`.
  Se o HTML não é nem "detalhe válido" nem "não encontrado" → `estado="indeterminado"`
  e **levantar/sinalizar** (princípio AUTOMACAO §1: o ambíguo pára e avisa).
- **Fallback — Playwright** (só se aparecer proteção anti-bot / Cloudflare / captcha sob
  carga, ou se um estado precisar de JS): headless, ~3 s/página, reutilizar a mesma função de
  parsing sobre `page.content()`. O servidor CX32 já tem folga para Playwright (AUTOMACAO §
  stack). **Não** é o caminho por omissão.
- **Idempotência:** `upsert` por `nr_registo` (PK). Correr 2× seguidas deixa o mesmo estado.
- **Isolamento de falha:** falha de rede/5xx/timeout **não** escreve estado — retry no ciclo
  seguinte. Nunca marcar cancelado por erro de transporte (mesma filosofia da regra dos 2
  varrimentos).

---

## 6. Riscos / gotchas

1. **[CRÍTICO] Estado cancelado/suspenso não observado.** Todo o valor do produto assenta em
   detetar "o teu registo foi cancelado". Ainda **não** confirmei como a página o mostra
   (§2.3). Mitigação: (a) fonte primária do cancelamento é o diffing `list_RNAL` (FDS 1);
   (b) obter `nr` cancelado real (§4 item 1) antes de confiar no detalhe para este estado;
   (c) enquanto não confirmado, tratar tudo o que não é claramente "ativo" nem
   "nao_encontrado" como `indeterminado` → pára e avisa.
2. **IDs OutSystems voláteis.** `id="RichWidgets_wt7_block_..."` muda a cada republicação da
   app. **Nunca** ancorar seletores nos `wtN`. Ancorar em texto de cabeçalho estável
   ("Seguro de Responsabilidade Civil", "Companhia de Seguros", "Validade"). O teste smoke
   (§3.2) é a rede de segurança para mudanças de layout.
3. **"Registo não encontrado" é HTTP 200, não 404.** Tem de ser detetado por **marcador
   textual** ("Registo não encontrado, pesquise por Atividade!") e/ou ausência do bloco de
   dados — não por status code.
4. **Nº de apólice com zeros à esquerda** (`0007859994`, `03662951`). **Guardar como `text`**
   (o schema já o faz). Nunca converter para int.
5. **Múltiplas linhas de seguro.** Todos os 4 exemplos tiveram 1 linha, mas o schema
   `detalhes_cliente` só guarda **um** seguro. **[ASSUMIDO]** que há sempre ≤1 apólice ativa.
   Se aparecerem várias linhas, decidir a regra (ex.: a de maior `Validade`). Guardar o HTML
   bruto no snapshot para poder reprocessar.
6. **Cookies de sessão OutSystems** (`ASP.NET_SessionId`, `osVisit` ~30 min). Não são
   necessários para o GET, mas se um dia forem, o httpx deve usar um `Client` com cookie jar
   por ciclo. Estado observado: não necessários (2026-07-05).
7. **Volume/educação.** Centenas de GET/dia a um portal do Estado. Manter UA identificável +
   pausa + horário noturno (03h30). Risco de bloqueio por IP se abusar — outra razão para
   **não** fazer scraping em massa dos 120k por aqui.
8. **Formato de data.** Todos ISO `YYYY-MM-DD` nos exemplos, mas **[ASSUMIDO]** que é sempre
   assim. Parser deve validar e mandar para `indeterminado` (não `None` silencioso) se falhar.
9. **Bloco seguro ausente.** Um registo pode não ter seguro registado (linha vazia ou tabela
   sem `<tbody>` com dados). **[ASSUMIDO]** — não observei o caso. Tratar como
   `seguro_* = NULL` + sinal de produto "sem seguro RC visível" (não como erro de parsing).

---

## 7. Lista explícita de pontos ASSUMIDOS a confirmar

| # | Assunção | Como confirmar |
|---|---|---|
| A1 | Registo **cancelado/suspenso** → "Registo não encontrado" **ou** banner de estado | Testar com `nr` cancelado real (Porto/Funchal). §4 item 1 |
| A2 | Existe sempre **≤1 linha** de seguro | Amostrar registos multi-apólice; ver se `<tbody>` tem >1 `<tr>` |
| A3 | Datas sempre **ISO `YYYY-MM-DD`** | Amostragem maior; validar no parser |
| A4 | GET **nunca** precisa de cookie/`__VIEWSTATE`/JS | Descoberta única Playwright (§3.3) a registar tráfego |
| A5 | **Sem** proteção anti-bot sob carga (centenas/dia) | Teste de carga controlado antes de escalar clientes |
| A6 | Registo **sem seguro** → linha/tabela vazia (não erro) | Encontrar um `nr` sem apólice registada |
| A7 | Não existe rótulo "Estado/Situação" para ativos | Confirmado nos 4 exemplos ativos; reconfirmar em amostra maior |

---

## 8. Referências (fontes verificadas 2026-07-05)

- Página live (server-rendered, com bloco seguro):
  `https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=100031`
  (também `?nr=1`, `?nr=5`, `?nr=100`)
- Página "não encontrado" (HTTP 200, ~30 KB):
  `https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=100032`
- Constantes de projeto: `app/config.py` (`RNAL_PAGINA`, `RNAL_USER_AGENT`,
  `RNAL_TIMEOUT_S`, `RNAL_PAUSA_S`, `CADENCIA_CLIENTE_DIAS`)
- Esquema `detalhes_cliente`: `AUTOMACAO.md §1`
- Racional Playwright/onboarding: `AUTOMACAO.md §1` (Detalhe individual) e roadmap FDS 3
```
