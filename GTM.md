# CheckAL — Go-to-Market & Motor de Aquisição

> **PLANO OPERACIONAL CANÓNICO** (cenário B: email + SEO + selo; cartas só em teste com gate). Parte do dossier CheckAL.

## Go-to-Market & Motor de Aquisição

### Princípio operativo

A vantagem estrutural do CheckAL é única: **o dataset que alimenta o produto é a lista de prospects**. Cada registo RNAL traz nome, NIF, email e telefone do titular — públicos por força do art. 10.º do DL 128/2014. Não há "geração de leads": há uma base de >120.000 registos à espera de ser trabalhada com o pretexto certo, no momento certo. Todo este capítulo é a engenharia desse pretexto.

Números reais (extraídos hoje da API `list_RNAL`, 9 concelhos prioritários):

| Concelho | Registos | Pessoa coletiva | Pessoa singular | % com email |
|---|---|---|---|---|
| Lisboa | 11.854 | 55% | 45% | 100% |
| Porto | 9.767 | 61% | 39% | 100% |
| Albufeira | 10.395 | 36% | 64% | 100% |
| Loulé | 7.170 | 42% | 58% | 100% |
| Portimão | 6.030 | 34% | 66% | 100% |
| Funchal | 3.261 | 49% | 51% | 100% |
| Cascais | 2.756 | 37% | 63% | 100% |
| Sintra | 1.228 | 39% | 61% | 100% |
| Mafra | 1.150 | 31% | 69% | 100% |
| **Total** | **53.611** | **24.757 (46%)** | **28.854 (54%)** | **100%** |

Estes 9 concelhos são ~45% da base nacional. Deduplicados por NIF: **29.132 titulares únicos**, dos quais **6.557 têm 2+ ALs** (alvo natural do tier Portfólio) e **1.454 têm 5+ ALs**. Regra operacional desde o dia 1: **um titular = um contacto** (dedupe por NIF), nunca N cartas para N registos.

---

### 0. Prioridade de canais — REORDENADA (pós-revisão de risco, jul/2026)

A versão anterior deste plano punha o email frio à base RNAL como motor principal. Duas revisões obrigam a **inverter a ordem** (sem deitar nada fora):
1. **O risco RGPD de reutilizar o RNAL para prospeção** é um portão jurídico bloqueante (LEGAL.md §1) — no pior caso, zero contacto a frio.
2. **O incumbente e o melhor canal são a mesma entidade: o contabilista / gestor de AL** (secção 6), não uma software house.

**Nova ordem de prioridade (a que o plano assume por defeito):**

| # | Canal | Porque é primeiro | Risco RGPD |
|---|---|---|---|
| **1** | **Consent-first: widget de verificação gratuita** — o titular *pede* o relatório e consente | Motor primário (secção 2). Tráfego por SEO + grupos de FB + ads | **Nenhum** (é o próprio a pedir) |
| **2** | **Parcerias com contabilistas / gestores de AL** — leads consentidos, apresentados por terceiro de confiança | Neutraliza a maior ameaça e não esgota com a base. Passa de "fase 2" a **canal de dia 1** (secção 6) | **Nenhum** (lead consentido) |
| **3** | **Email frio B2B só a coletivas com email genérico** (geral@/info@) | O único cold com base jurídica limpa (não é dado pessoal) | Baixo — suplementar, não estruturante |
| **4** | **Carta a singulares** | Só teste pequeno, e **só com parecer jurídico favorável** | Alto — fora das projeções |

As projeções da secção 4 continuam válidas como **cenário com cold B2B**; a secção 2 (novo aviso sobre o topo de funil) dá o cenário **consent-first puro** — mais lento (Meta 1 escorrega para ~M15–M18) mas robusto e sem dependência do portão jurídico.

---

### 1. Segmentação da base

Três eixos, aplicados por esta ordem:

**Eixo A — Canal, por tipo de titular (revisto — condicionado ao parecer jurídico, LEGAL.md §1):**
- **Coletiva com email genérico** (geral@/info@/reservas@): **email frio B2B com opt-out** — o cold mais limpo (não é dado pessoal, RGPD não se aplica ao contacto). Custo marginal ~0,015€/envio. É o único motor de volume a frio que arranca **sem depender do parecer**. Filtrar a base por padrão de email genérico é o primeiro passo operacional.
- **Coletiva com email de pessoa identificada**: email frio **só após parecer favorável**; senão, entra na lista de consent-first (só é contactada se vier ela ao widget).
- **Pessoa singular / ENI**: **sem email/SMS a frio (proibido)**. Carta física apenas como **2 lotes de teste de 500**, e **duplamente travada**: (a) gate de conversão ≥0,8% (a conta honesta da secção 2 dá 0,2–0,65% → CAC 200–650€, inviável contra 77€ de cash à cabeça) **e** (b) parecer jurídico favorável (a carta está fora da ePrivacy mas dentro do RGPD). Fora de todas as projeções de receita até passar **os dois** portões. Se falhar qualquer um, o canal carta morre e o crescimento assenta em consent-first + parcerias (§0).

**Eixo B — Prioridade geográfica (a dor manda).** Validei por pesquisa os concelhos onde algo REAL já aconteceu pós-DL 76/2024:

| Vaga | Concelhos | Gatilho verificado |
|---|---|---|
| **Vaga 1 (M1–M3)** | **Porto** | Câmara anunciou o **cancelamento de 1.413 registos AL** em incumprimento ([Observador, mai/2026](https://observador.pt/2026/05/22/camara-do-porto-vai-cancelar-1-413-estabelecimentos-de-alojamento-local/)) + regulamento de crescimento sustentável com contenção em 5 freguesias (Miragaia, Santo Ildefonso, São Nicolau, Sé, Vitória) |
| | **Lisboa** | 2.ª alteração ao Regulamento Municipal aprovada a 2/dez/2025: contenção relativa (rácio ≥5%) e absoluta (≥10%), monitorização **mensal** dos rácios, regras novas de transmissão e suspensão ([Cuatrecasas](https://www.cuatrecasas.com/en/global/real-estate/art/amendment-lisbon-municipal-regulation-short-term-letting), [Aviso n.º 29926-A/2025/2](https://diariodarepublica.pt/dr/detalhe/aviso/29926-a-2025-964380181)) |
| | **Funchal** | Regulamento aprovado na Assembleia Municipal em jun/2026 — proíbe novos AL em edifícios de habitação coletiva ([DNotícias](https://www.dnoticias.pt/2026/6/24/496642-regulamento-que-limita-alojamento-local-no-funchal-aprovado-na-assembleia-municipal/)) |
| | **Cascais, Sintra** (+ Lisboa) | Câmaras começaram em 2025 a **notificar ALs sem seguro com 10 dias para regularizar, sob pena de cancelamento**; a ALEP estimou ~70.000 ALs sem seguro submetido — mais de metade da base nacional ([ECO](https://eco.sapo.pt/2025/07/02/camaras-de-lisboa-cascais-e-sintra-ja-comecaram-a-notificar-alojamentos-locais-sem-seguro/)) |
| | **Mafra (Ericeira)** | Área de contenção desde 2019, cap de 20% de AL por fogos — registos ali são ativos irrecuperáveis se caducarem ([CM Mafra](https://www.cm-mafra.pt/pages/746)) |
| **Vaga 2 (M3–M6)** | **Albufeira, Loulé, Portimão** (+ Lagos, Lagoa, Tavira, Faro) | >1.000 registos cada → obrigados pelo DL 76/2024 a deliberar sobre regulamentação (prazo de 12 meses); ainda sem regulamento = incerteza máxima, o argumento é "vem aí, fica a saber primeiro" |
| **Vaga 3 (M6+)** | Resto do país por ordem decrescente de nº de registos | Vila Nova de Gaia (áreas de suspensão) à cabeça |

**Eixo C — Valor, por dimensão do titular:**
- **2+ registos no mesmo NIF** (6.557 só nas Vagas 1–2): pitch direto ao tier **Portfólio**; uma carta/email diferente ("os teus 4 ALs, um só radar").
- **1 registo, ≤4 camas** (a mediana é 2–4 camas em todos os concelhos medidos): plano base 49€/ano, mensagem de simplicidade total.
- **Modalidade "Estabelecimento de hospedagem" / >6 camas**: prioridade dentro de cada lote — mais receita em jogo, mais propensão a pagar.

---

### 2. O funil âncora: verificação gratuita → monitorização paga

A landing checkal.pt tem **um único CTA**: "Faz o check ao teu AL — grátis, 30 segundos". O proprietário insere o n.º RNAL ou o nome do alojamento e recebe um mini-relatório instantâneo.

**Passo a passo e taxas (planeamento no limite inferior dos benchmarks):**

1. **Contacto → visita.** Carta com QR code + URL curta personalizada (`checkal.pt/porto`): 3–5% de visita com gatilho real (benchmark direct mail 1–3% de resposta; o gatilho concreto e o QR sobem isto). Email frio: 35–45% abertura, 2–4% clique.
2. **Visita → verificação.** O visitante que chegou por causa do SEU registo verifica: 60–70% (é o único CTA; pré-preenchemos o n.º RNAL no link da carta/email — a fricção é zero).
3. **Verificação → captura de email.** O mini-relatório aparece no ecrã resumido; o relatório completo em PDF vai por email, com checkbox de consentimento para "alertas sobre o meu concelho" (base legal limpa para o nurture). Captura: 70–80% dos que verificam.
4. **O mini-relatório mostra sempre 1 risco real**, por esta hierarquia: (a) *seguro não confirmado no RNAL* — atinge ~metade da base e as câmaras já cancelam por isto; (b) *freguesia em área de contenção* — "o teu registo é irrecuperável se caducar; hoje vale literalmente dinheiro"; (c) *concelho com regulamento novo/em preparação* — "estas regras mudaram no teu concelho nos últimos 12 meses". Nunca entregar "está tudo bem, adeus": mesmo o registo impecável recebe "3 alterações regulatórias previstas para o teu concelho que não controlas".
5. **Verificação → pagamento.** Direto (na página de resultado, upsell imediato: "monitoriza isto por 49€/ano — menos de 14 cêntimos/dia; a coima mínima é 50x isto"): 8–15% dos verificados com risco detetado. Mais o nurture:
6. **Sequência de nurture (30 dias):** D0 relatório PDF + oferta; D2 explicação do risco detetado em linguagem de gente; D7 caso real com nome de concelho ("o Porto cancelou 1.413 registos — verificámos: 31% não tinham seguro submetido"); D14 oferta trienal 119€ ("fecha isto por 3 anos e esquece"); D30 entra na newsletter regulatória mensal do concelho dele — que o mantém quente até ao próximo gatilho. Conversão adicional do nurture: 3–5% da lista em 60 dias.

**A multiplicação, feita até ao fim (é com isto que a secção 4 faz contas).** Por 1.000 cartas: via direta = 3–5% visita × 60–70% verificação × 8–15% pagamento = **0,14%–0,53%**; via nurture = ~1,9–2,8% de emails capturados × 3–5% = **+0,06%–0,14%**. Total ponta-a-ponta: **0,2%–0,65% por carta**. O cenário base para cartas é portanto **0,5% (5 clientes/1.000)** — e é o topo do intervalo, não o pessimista; exige gatilho forte. Não existe cenário micro coerente que dê 1–1,5% sem que os passos individuais superem os benchmarks — se acontecer, os testes de 500 vão mostrá-lo, e só aí as cartas escalam. Restantes canais, por 1.000 contactos: **email de gatilho** (evento real no concelho do destinatário) → 5–8 clientes (0,5–0,8%); **email frio sem gatilho fresco** → 2–4 clientes (0,2–0,4%). Tráfego frio orgânico (SEO): landing→pagamento 1,5–3%.

**⚠️ Aviso sobre o topo de funil do widget (o pressuposto mais otimista do plano — corrigido).** A taxa verificação→pago (8–15%) só vale se houver *tráfego para o widget*. No cenário com cold B2B, esse tráfego vem sobretudo dos emails; se o cold encolher (portão RGPD, LEGAL.md §1), o widget passa a depender de **SEO** (lento a maturar, 3–6 meses), **grupos de FB** e **ads pagos**. Números assumidos para o cenário consent-first: SEO+FB dão ~200–400 verificações/mês a partir do M4 (a crescer); ads Google/Meta a ~1–2€/clique × 40–50% chega-ao-widget × 8–12% pago ⇒ **CAC de ads ~25–60€** (confortável no trienal, marginal no anual). **Consequência honesta:** sem cold, a Meta 1 (490 clientes) escorrega para **~M15–M18** e o CAC blended sobe de ~6€ para **~25–35€** — ainda saudável (LTV blended ~213€), mas o negócio deixa de ser "quase sem custo de aquisição". Os ads são o *pressure valve* que compra velocidade quando o orgânico não chega, e é isso que financia a diferença. Este é o número que faltava ao plano: **o widget não é tráfego grátis — é tráfego que ou se ganha devagar (SEO/parcerias) ou se compra (ads).**

---

### 3. O motor perpétuo: campanhas gatilho-a-gatilho

**A decisão central deste GTM**: o marketing do CheckAL não tem calendário próprio — **é acionado pelos mesmos eventos que o produto deteta**. Cada evento regulatório é simultaneamente (1) prova de que o produto funciona, (2) pretexto de contacto com pico de recetividade e (3) conteúdo SEO. O sistema:

**Pipeline (automatizado, zero humanos):**
1. **Fontes monitorizadas**: diffing semanal do RNAL (um lote de registos que desaparece num concelho = câmara a "limpar" → gatilho); Diário da República/DRE (avisos e regulamentos municipais de AL); editais e atas municipais dos ~25 concelhos com >1.000 registos; Google Alerts/notícias.
2. **Classificação por IA**: evento → concelho/freguesia afetada, tipo (cancelamento em massa, regulamento novo, área de contenção, consulta pública, notificação de seguros), severidade.
3. **Geração do segmento**: query ao snapshot RNAL → todos os titulares do concelho/freguesia afetada, deduplicados por NIF, divididos coletiva/singular.
4. **Geração do copy por IA** (template + facto concreto + prova): assunto tipo *"A Câmara do Porto vai cancelar 1.413 registos de AL. O teu está na lista de risco?"* — verificável, datado, com link para a fonte oficial. Zero fear-mongering inventado: só factos com data.
5. **Envio em <72h** do evento. O SLA importa: chegar uma semana depois do Público já não é "radar", é jornal velho. E é a demonstração viva da promessa do produto.
6. **Subproduto automático**: cada gatilho publica/atualiza a página "Alojamento Local em [concelho]: o que mudou" no site → alimenta o SEO e dá material para partilhar nos grupos de Facebook.

**Gatilhos já disponíveis para os primeiros 90 dias** (não são hipóteses — aconteceram):

| Gatilho | Segmento | Canal | Data do pretexto |
|---|---|---|---|
| Porto: cancelamento de 1.413 registos | 9.767 registos Porto | Email (coletivas) + carta-teste (singulares, priorizar 5 freguesias de contenção) | mai/2026 — ainda quente |
| Funchal: regulamento proíbe AL novo em habitação coletiva | 3.261 registos Funchal | Email + carta-teste | jun/2026 — quentíssimo |
| Lisboa: novo RMAL com contenção a 2 níveis e monitorização mensal | 11.854 registos Lisboa | Email primeiro (55% coletivas) | dez/2025 |
| Notificações de seguro (Lisboa/Cascais/Sintra) + 70k ALs sem seguro | Nacional, priorizar estes 3 concelhos | Email (+ carta só se passar o gate) | recorrente desde 2025 |
| Algarve: prazo de deliberação DL 76/2024 | Albufeira/Loulé/Portimão (23.595 registos) | Email | rolante |

Quando não há gatilho fresco num concelho, o lote da semana usa o gatilho estrutural que nunca expira: "o teu seguro não consta no RNAL" (metade da base) ou "a tua freguesia está em contenção" (o registo como ativo valioso).

---

### 4. Cadência operacional e projeção (primeiros 6 meses)

**Decisão pré-tomada — o plano base É o cenário B (email + SEO + selo, cartas a zero).** Pelo próprio modelo micro da secção 2, as cartas convertem 0,2–0,65% — abaixo do gate de viabilidade (0,8%). Logo, as projeções abaixo **não contam com um único cliente de carta**. Os 2 lotes de teste de 500 (M1 e M2) mantêm-se como gate obrigatório: custo total 1.200€, tratado como despesa de I&D de canal. Se um teste medir **≥0,8%**, as cartas reativam-se só para o segmento Portfólio (ticket maior aguenta CAC de 150€); **≥1,5%**, escalam para toda a base singular — e tudo o que daí vier é upside sobre este plano, nunca o seu suporte.

**Infraestrutura de email frio** (montar no M1): 4–6 domínios satélite (nunca checkal.pt), 12–15 caixas, warm-up de 3 semanas, ≤50 envios/dia/caixa, sequência de 3 toques, opt-out em 1 clique, supressão por NIF. Custo: ~120€/mês (Smartlead/Instantly + domínios). **Cartas**: fulfillment tipo Lob/ClickSend/CTT Directo a ~1,30€/unidade — só os 2 lotes de teste.

| Mês | Emails frios | Cartas (teste, fora da conta) | Custo mkt | Novos clientes (conta) | Acumulado |
|---|---|---|---|---|---|
| M1 | 2.000 (Porto/Funchal, gatilho) | 500 (Porto, teste A) | 720€ | 2.000×0,5% = **10** | 10 |
| M2 | 4.000 (Lisboa + Funchal) | 500 (Funchal, teste B) | 720€ | 4.000×0,5% = **20** | 30 |
| M3 | 6.000 (Lisboa + Cascais/Sintra seguros) | 0 (avaliar gate) | 220€ | 6.000×0,4% + SEO 2 = **26** | 56 |
| M4 | 8.000 (Algarve arranca) | 0 | 220€ | 32 + SEO/FB 4 = **36** | 92 |
| M5 | 8.000 | 0 | 220€ | 32 + orgânico 6 = **38** | 130 |
| M6 | 8.000 | 0 | 220€ | 28 + orgânico 10 = **38** | **168** |

*Notas à conta*: emails de gatilho a 0,5–0,6%, emails frios sem gatilho fresco a 0,3–0,4%; o M6 já assume ligeira fadiga do pool (ver secção 5). Volume de email limitado pela infraestrutura de deliverability, não pelo dinheiro. Custo M3+ inclui 100€/mês de tooling SEO/conteúdo.

**Receita** (mix assumido: 60% anual 49€, 40% trienal 119€ — o low-touch 40–65 anos leva trienal acima da média):
- Receita anualizada por cliente: 0,6×49 + 0,4×(119/3) = 29,4 + 15,9 = **45,3€/ano**.
- **M6: 168 clientes ≈ 7.600€ ARR ≈ 630€/mês.**
- **Meta 1.500€/mês brutos = 18.000€ ARR = ~400 clientes → atingida entre M12 e M14 (na medida canónica — líquidos de IVA — são 490 clientes, ~M14–M15)** com email nos concelhos da Vaga 3 + re-contacto da base com gatilhos novos + SEO/referral a compor (35–45 novos/mês em M7–M12: 168 + 6×40 ≈ 410 ao M12–M13). Sejamos honestos: a meta não cai ao M6 nem ao M10; cai à volta do fim do ano 1 — e se as cartas passarem o gate, antecipa 1–2 meses.
- **Cash é outra história (e melhor)**: cash médio à cabeça = 0,6×49 + 0,4×119 = **77€/cliente**. Cash acumulado M6: 168×77 ≈ **12.900€** contra ~2.320€ de custos de marketing acumulados. O negócio é cash-flow positivo desde o M1.
- **CAC**: email puro 4–8€ (120€/mês ÷ 20–30 clientes); blended M4–M6 ≈ 660€/112 ≈ **6€**. As cartas de teste, se falharem, custam 1.200€ de aprendizagem — não CAC. Se passarem o gate a 0,8–1,5%, o CAC de carta (80–150€) só se aceita em Portfólio/trienal, pago pelo cash à cabeça desse segmento.

---

### 5. O mercado é finito e está a encolher — TAM dinâmico e a fase 2

Este plano não pode fingir que os 120.000 registos são um poço sem fundo. Três factos:

1. **A base está a encolher.** A própria ALEP — citada no nosso copy — estima **40–45 mil cancelamentos** em curso (limpezas de seguro, contenção, regulamentos novos): ~1/3 dos prospects pode desaparecer em 2–3 anos. Em áreas de contenção não entram registos novos; o handoff avisa: mais cancelamentos que aberturas.
2. **O pool de email esgota-se dentro do ano 1.** Coletivas ≈ 45.000 registos ≈ ~25.000 titulares únicos (rácio de dedupe medido: 54%). A ~2.700 novos titulares contactados/mês (8.000 emails ÷ 3 toques), a primeira passagem completa faz-se em **~9–10 meses**; os concelhos prioritários (Vagas 1–2) esgotam a primeira passagem por M6–M7.
3. **Churn estrutural somado ao churn de renovação.** Cliente que vende ou fecha o AL é churn que nenhum produto trava. Assumo **8–10%/ano de churn estrutural** além do de renovação; o trienal pré-pago protege o cash, não a base.

**Decisões (tomadas, não opções):**

- **TAM dinâmico como KPI mensal desde o M1.** O diffing semanal do RNAL já produz isto de graça: **net adds por concelho** (registos novos − cancelados). Entra no dashboard ao lado dos KPIs de funil (secção 7). Se o mercado encolher 2%/mês num concelho, o plano de prospeção desse concelho ajusta-se automaticamente — e o próprio número é conteúdo/copy ("o teu concelho perdeu 214 registos este trimestre").
- **A base não é one-shot por contacto — é one-shot por pretexto.** Cada regulamento novo, cada limpeza municipal, cada alteração de contenção **reabre a base inteira do concelho** para re-contacto legítimo (e com melhor conversão que o primeiro toque, porque o medo é fresco). O motor da secção 3 já gera estes pretextos; a regra operacional é: **re-contacto de cada titular no máximo 1x/trimestre e só com gatilho novo e datado**. Isto converte o esgotamento da primeira passagem num ciclo anual de 3–4 passagens.
- **Novos registos = trigger de venda imediato, ativo desde o M2.** O diffing deteta cada registo novo em <7 dias. Email/carta automática: *"Registaste um AL há 3 dias. O teu concelho tem regulamento em preparação — protege o registo desde o dia 1."* É o momento de máxima atenção do proprietário. Fluxo pequeno (o mercado encolhe) mas de conversão desproporcionada — e custa zero, o pipeline já existe.
- **Parcerias com contabilistas — PROMOVIDAS a canal de dia 1 (§0).** Não são fase 2: são o segundo pilar do plano a par do widget. Um contabilista com 30 clientes AL é um canal que não se esgota com a base RNAL, traz leads **consentidos** (resolve o portão RGPD) e neutraliza a maior ameaça competitiva (secção 6). Comissão 20% recorrente, materiais automatizados; a negociação inicial é **o único toque humano deliberadamente aceite** no plano (exceção assumida ao "zero-touch", porque compra distribuição defensável). Risco a gerir: concentração por parceiro — não deixar nenhum parceiro passar de ~15% da base.
- **Subida de preço quando a prospeção deixar de ser o motor.** Quando o volume de primeira passagem se esgotar (M9–M12), o crescimento passa a vir de SEO, referral, selo e parcerias — canais em que o preço não é o travão. Decisão: **novos clientes a 59€/ano (trienal 139€) a partir desse ponto**, com grandfathering dos existentes. Racional: num mercado a encolher, extrai-se mais valor por cliente em vez de mais clientes por euro; o custo de inação (coima de 2.500–4.000€ singular / 25.000–40.000€ coletiva) aguenta 59€ tão bem como 49€.

---

### 6. Canais secundários — os 2 primeiros a ativar (decisão tomada)

**Ativar já (M2): SEO programático — 308 páginas "Alojamento Local em [concelho]".** Cada página gerada do próprio dataset: nº de registos ativos, evolução (o diffing dá a série temporal), regulamento municipal em vigor/em preparação, áreas de contenção, freguesias, e o widget de verificação gratuita. Custo marginal ~zero, ninguém em Portugal tem estes dados agregados, e captura pesquisas de intenção máxima ("regulamento AL cascais", "área de contenção porto AL"). Decisão: é o canal com melhor razão custo/ativo permanente e defende a marca a prazo — e no cenário B (cartas mortas) é o segundo pilar do crescimento, não um extra.

**Ativar já (M3): grupos de Facebook de proprietários de AL.** É onde o cliente-alvo (40–65, não-técnico) realmente está; os grupos de AL em Portugal têm dezenas de milhares de membros e vivem de pânico regulatório. Modo de entrada: partilhar os alertas de gatilho como serviço público ("resumo do novo regulamento do Funchal em 5 pontos, verifiquem o vosso seguro aqui") — nunca anúncio. Decisão: custo zero, mesmo público, e cada gatilho da secção 3 já produz o conteúdo.

**Em fila (não ativar antes de M5–M6, para não dispersar):**
- **Referral**: "1 ano grátis por cada indicação que pague" — simples, automatizável, margem aguenta (CAC via referral = 49€ de receita adiada). Ativar ao M4–M5, quando houver ~100 clientes para o alimentar.
- **Parcerias** com contabilistas (que tratam do e-fatura/AT de dezenas de ALs cada) e ALEP: comissão 20% recorrente ou white-label do relatório. **Reclassificadas como canal de dia 1 (§0 e secção 5)** — são simultaneamente a maior ameaça competitiva e o melhor canal de distribuição, e trazem leads consentidos que contornam o portão RGPD. Exigem o único toque humano aceite do plano. Arrancar a angariação de 3–5 parceiros-piloto já no M1–M2, em paralelo com o widget.

---

### 7. Métricas norte

| KPI | M3 | M6 | M12 | Porquê este |
|---|---|---|---|---|
| **Verificações gratuitas/mês** | 350 | 800 | 2.500 | Topo do funil; mede se os pretextos estão a puxar |
| **Conversão verificação→pago (janela 30d)** | ≥6% | ≥8% | ≥10% | Saúde do funil âncora; se cair, o problema é oferta/risco mostrado, não tráfego |
| **Clientes ativos pagos** | 56 | 168 | 400–450 | A métrica-mãe; 400 = meta 1.500€/mês |
| **CAC blended** | ≤35€ (inclui cartas-teste) | ≤12€ | ≤15€ | Baixo por construção no cenário B; só sobe se as cartas passarem o gate ≥0,8% — subida aceitável porque é paga pelo cash Portfólio/trienal |
| **Net adds RNAL/mês (mercado)** | medir | medir | tendência | O TAM dinâmico da secção 5; se o concelho encolhe, a prospeção e o copy ajustam-se — é o KPI que impede o plano de assumir um mercado que já não existe |
| **% da 1.ª passagem de email consumida** | ~25% | ~60% | 100% + re-contacto | Mede a distância ao esgotamento do canal; ao cruzar 80%, a fase 2 (secção 5) já tem de estar a produzir |
| **Tempo evento→campanha enviada** | ≤7 dias | ≤72h | ≤48h | O SLA do motor perpétuo; é também a prova pública da promessa do produto |

Guardrail adicional (não-KPI, mas mata o negócio se falhar): **taxa de spam complaints do email frio <0,3%** e opt-outs processados em <24h — a máquina de volume vive de deliverability e de ficar do lado certo do RGPD/e-Privacy.

**Fontes principais**: [Observador — Porto cancela 1.413 ALs](https://observador.pt/2026/05/22/camara-do-porto-vai-cancelar-1-413-estabelecimentos-de-alojamento-local/) · [ECO — notificações de seguro Lisboa/Cascais/Sintra, 70k sem seguro](https://eco.sapo.pt/2025/07/02/camaras-de-lisboa-cascais-e-sintra-ja-comecaram-a-notificar-alojamentos-locais-sem-seguro/) · [Cuatrecasas — 2.ª alteração RMAL Lisboa](https://www.cuatrecasas.com/en/global/real-estate/art/amendment-lisbon-municipal-regulation-short-term-letting) · [DNotícias — regulamento AL Funchal](https://www.dnoticias.pt/2026/6/24/496642-regulamento-que-limita-alojamento-local-no-funchal-aprovado-na-assembleia-municipal/) · [CM Porto — regulamento crescimento sustentável](https://atividadeseconomicas.cm-porto.pt/destaque/regulamento-municipal-para-o-crescimento-sustentavel-do-alojamento-local-do-porto) · [CM Mafra — contenção Ericeira](https://www.cm-mafra.pt/pages/746) · Dados de registos/titulares: API RNAL `list_RNAL`, extração de 2026-07-02 (9 concelhos, 53.611 registos).
