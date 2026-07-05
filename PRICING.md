# CheckAL — Pricing & Unit Economics

> Parte do dossier CheckAL. **Nota editorial:** a timeline mês-a-mês da secção 4 deste ficheiro é o CENÁRIO UPSIDE (pressupõe cartas a passar o gate ≥0,8% e churn ≤25%). O plano operacional canónico é o cenário B do GTM.md — meta 1.500€/mês líquidos em M12–M15. A tabela de preços desta secção é a canónica para todo o dossier. Nota fiscal: na conta do IVA dedutível das cartas, a franquia postal CTT é isenta (art. 9.º CIVA) — só a impressão/envelopagem deduz; confirmar enquadramento do e-carta com o contabilista (não altera a decisão pelo regime normal).

## Pricing & Unit Economics

### 1. Tabela de preços final (decisão fechada — tabela canónica)

**Esta é a ÚNICA tabela de preços do plano.** As secções de Produto, GTM e o copy da landing referenciam esta tabela e não mantêm cópias próprias. Correções obrigatórias nas outras peças: (a) a tabela do Produto passa a usar **+19 €/ano e +45 €/3 anos** por AL adicional (não +29 €/+69 €) e **elimina a regra "+10 €/AL/ano acima de 10"**, substituída pelos tiers Portfólio+ e Portfólio Max abaixo; (b) o Portfólio trienal (359 €) passa a constar em todas as peças; (c) a landing acrescenta a linha de ALs adicionais em destaque — o cliente com 2–3 ALs é o núcleo do cliente-alvo e não pode ter de "adivinhar" o preço do 2.º AL.

| Plano | Cobertura | Preço (IVA incluído) | €/AL/ano | €/dia |
|---|---|---|---|---|
| **CheckAL Anual** | 1 AL | **49 €/ano** | 49 € | 0,13 € |
| **CheckAL Trienal** | 1 AL | **119 €/3 anos** (vs. 147 € — poupa 28 €) | 39,67 € | 0,11 € |
| **AL adicional** (2.º e 3.º) | por AL | **+19 €/ano** ou **+45 €/3 anos** | 19 € | 0,05 € |
| **Portfólio** | 4–10 ALs | **149 €/ano** ou **359 €/3 anos** | 14,90–37 € | 0,41 € |
| **Portfólio+** | 11–25 ALs | **299 €/ano** | 12–27 € | 0,82 € |
| **Portfólio Max** | 26–50 ALs | **499 €/ano** | 10–19 € | 1,37 € |

Tudo self-serve, sem "fale connosco" — coerente com zero humanos no loop.

**Justificação contra o custo de inação — valores ASAE, canónicos para TODAS as peças.** A coima por exploração de AL sem registo válido é de **2.500 € a 4.000 € para pessoa singular** e de **25.000 € a 40.000 € para pessoa coletiva** (fonte: [asae.gov.pt](https://www.asae.gov.pt); DL 128/2014 na redação vigente), além do cancelamento do registo — a perda do negócio inteiro. Estes são os únicos valores a usar em landing, cartas, emails e alertas do produto. Nota de correção obrigatória: o alerta-exemplo da secção de Produto diz a um titular singular "coimas que podem ultrapassar os 7.500 €" — é falso para singulares (o 7.500 € é o teto de coletivas noutras infrações) e deve passar a "coimas de 2.500 € a 4.000 €"; o alerta deve aliás adaptar o valor ao tipo de titular, que a API do RNAL nos dá campo a campo.

A aritmética do preço, refeita com os valores certos:
- **Singular**: 49 €/ano = **1,2% da coima máxima** (4.000 €) e 2% da mínima. A coima máxima paga 82 anos de serviço.
- **Coletiva**: 49 €/ano = **0,12% da coima máxima** (40.000 €). A coima máxima paga **816 anos** de serviço. Este é o argumento mais forte de todo o negócio e estava a ser subvendido por 5x — o email frio às coletivas ancora aqui, não nos 7.500 €.
- **Portfólio**: um gestor (tipicamente coletiva) com 10 ALs tem exposição acumulada até **400.000 €** (10 × 40.000 €); 149 €/ano é **0,04% da exposição**. Mesmo um singular com 10 ALs (até 40.000 €) paga 0,37%.

**Âncoras de mercado verificadas (jul/2026):**
- **Seguro RC obrigatório de AL**: prémios entre [52 € e 441 €/ano consoante utentes e capital](https://www.alep.pt/SEGUROWEB) (protocolo ALEP/Zurich), com médias de [~80 €/ano para um apartamento](https://sgl.pt/seguro-obrigatorio-para-alojamento-local-al-o-guia-completo-para-proprietarios-em-2025/) e pacotes completos de [150–350 €/ano](https://alfaseguros.pt/blog/seguro-obrigatorio-alojamento-local-portugal/). O CheckAL custa menos do que o seguro que ele próprio vigia — e o seguro só paga *depois* do desastre; o CheckAL evita-o.
- **Consulta avulsa de advogado**: [média de 75 €, entre 50 € e 150 €](https://www.zaask.pt/quanto-custa/advogados); em áreas especializadas (imobiliário/fiscal) [150–300 €](https://portoadvogado.com/quanto-cobra-um-advogado-por-consulta/). Uma única consulta para perceber um regulamento municipal custa 1,5× o ano inteiro de CheckAL.
- **Avença de contabilista**: [média ~350 €/mês, mínimos ~100 €/mês](https://www.zaask.pt/quanto-custa/contabilistas). O CheckAL anual custa menos de meio mês da avença mais barata.

Conclusão: 49 € está deliberadamente **abaixo do item mais barato do stack de custos obrigatórios do AL** (o seguro). Não é uma decisão de orçamento, é um "sim" impulsivo. Margem para subir para 59–69 € depois de provado o funil — o preço de lançamento não é para sempre, mas os 3 primeiros meses são para maximizar volume de provas sociais e selos na rua.

### 2. Psicologia de conversão (na landing e na carta)

1. **Ancoragem na coima, sempre em primeiro — segmentada por tipo de titular.** A primeira linha de preço nunca aparece sozinha. Para singulares (cartas): "Coima por incumprimento: até 4.000 €. CheckAL: 49 €/ano." — razão 1:82. Para coletivas (email frio): "Coima por incumprimento: até 40.000 €. CheckAL: 49 €/ano." — **razão 1:816**, a âncora mais violenta do arsenal; o assunto do email às coletivas usa-a diretamente ("40.000 € de coima ou 49 €/ano?"). A API diz-nos o tipo de titular de cada registo, portanto a segmentação é automática.
2. **Custo por dia**: "13 cêntimos por dia. Menos do que o café que ofereces ao hóspede." No trienal: "11 cêntimos/dia, e esqueces o assunto durante 3 anos."
3. **Comparação com uma noite**: "O teu AL rende mais numa noite do que o CheckAL custa num ano." Para o dono de AL isto é aritmética imediata e humilhante para a objeção de preço.
4. **Trienal apresentado como default visual** (coluna destacada, "mais escolhido"), anual à esquerda como âncora de referência. O cliente-alvo é "pagar e esquecer" — o produto certo para ele é o trienal, e o desconto de 19% é a desculpa racional. A landing mostra também, na mesma vista, a linha "+19 €/ano por cada AL adicional" — o cliente com 2–3 ALs decide sem calculadora nem surpresas no checkout.
5. **Garantia: SIM — 30 dias, reembolso total, sem perguntas, incluindo no trienal.** Decisão: a lei do consumo já dá 14 dias de livre resolução em vendas à distância; estender para 30 custa quase zero (produto de custo marginal ~0) e desarma a desconfiança de comprar a uma marca desconhecida por carta/email. Enunciar como "Se em 30 dias não vires valor, devolvemos tudo."
6. **Nunca vender "software"**: vender "vigilância". A palavra-quadro em toda a comunicação é *com check ✓ / sem check* ("o teu AL passou no check" / "o teu AL falhou o check") — estado binário, loss aversion pura.

### 3. Unit economics completos

**Custo de servir (por cliente/ano, plano anual 49 €):**

| Rubrica | Conta | Custo |
|---|---|---|
| Stripe | 49 € × 1,5% + 0,25 € | 0,99 € |
| Emails transacionais (~60/ano, SES) | 60 × 0,0001 € | ~0,01 € |
| IA (interpretação de alertas) | 1 regulamento analisado serve todos os clientes do concelho; ~500 docs/ano × 0,05 € ÷ 400 clientes | ~0,06 € |
| Infra (VPS + scraping semanal do país) | ~144 €/ano ÷ 400 clientes | 0,36 € |
| Autocolante do selo + envio (one-off no onboarding) | impressão 0,35 € + franquia ~0,85 € | 1,20 € (one-off; só nos planos trienal/Portfólio, que o incluem — ver PRODUTO.md) |
| **Total** | | **~1,4 €/ano + 1,2 € one-off → margem bruta ≈ 95%** |

No trienal, o Stripe cobra uma vez (119 € × 1,5% + 0,25 € = 2,04 €) → 0,68 €/ano. Ainda melhor.

**CAC por canal:**

| Canal | Custo unitário | Conversão assumida | CAC |
|---|---|---|---|
| Email frio (pessoas coletivas, ~30% da base ≈ 36k) | ~0 € marginal; ferramentas ~50 €/mês | 0,4% com sequência de 3 toques | **~4 €** |
| Carta física (pessoas singulares) — genérica | 1,30 €/carta | 0,5% / 1% / 2% | 260 € / 130 € / 65 € |
| Carta física — **event-triggered** (seguro em falta no RNAL, regulamento novo no concelho dele) | 1,30 €/carta | 1,5% (assumido; testar) | **~87 €** |
| Verificador gratuito (lead magnet) → email nurture | ~0 € | 10–20% dos verificadores | **~0 €** |

**Decisão:** cartas genéricas em massa estão proibidas — só cartas event-triggered, em lotes de teste de 2.000 com stop-loss se a conversão medida ficar abaixo de 0,8% (CAC > 163 € mata o payback). O canal economicamente âncora é o email às coletivas + o verificador gratuito.

**LTV — cenário base e sensibilidade (líquido de custos de servir):**

Cenário base:
- **Anual**, churn 20% (meio do intervalo 15–25%): vida média = 1/0,20 = 5 anos → 49 € × 5 − ~7 € custos = **~238 € brutos** (194 € líquidos de IVA).
- **Trienal**, churn 0 na vigência, renovação trienal assumida a 60%: LTV = 119 €/(1−0,60) = **~298 € brutos** ao longo de ~7,5 anos.
- **Blended** (mix assumido 60% anual / 40% trienal): 0,6×238 + 0,4×298 = **~262 € brutos** (~213 € líquidos de IVA).

**Aviso honesto: o churn de 20% é um palpite, não um dado.** Num B2C de 40–65 anos comprado por medo, com cartões a expirar e um produto cujo sucesso é "não aconteceu nada", 30–35% de churn anual é tão plausível como 20%. A sensibilidade completa, cruzando churn com a conversão da carta (assumindo que a renovação trienal degrada em paralelo: 60%/45%/30%):

| Churn anual | Vida média | LTV anual líq. IVA | LTV blended líq. IVA | LTV:CAC carta a 0,5% (CAC 260 €) | a 1% (130 €) | a 1,5% (87 €) |
|---|---|---|---|---|---|---|
| **20%** | 5,0 anos | ~194 € | **~213 €** | 0,8:1 | 1,6:1 | **2,4:1** |
| **30%** | 3,3 anos | ~128 € | **~145 €** | 0,6:1 | 1,1:1 | 1,7:1 |
| **40%** | 2,5 anos | ~96 € | **~111 €** | 0,4:1 | 0,9:1 | 1,3:1 |

(Contas: LTV anual bruto = 49 € × vida − custos de servir; ÷1,23 para líquido de IVA. Trienal: 119 €/(1−renovação) − custos. Blended 60/40.)

Leitura: **a carta event-triggered só fecha na célula superior direita** (churn 20% × conversão 1,5%). A churn 30%, mesmo a 1,5% de conversão, o rácio cai para ~1,7:1 — marginal; a 35–40%, o canal não fecha em nenhuma conversão realista. Já o **email às coletivas fecha em TODAS as células** (pior caso: 111 €/4 € ≈ 28:1) e o verificador gratuito é imune por construção (CAC ~0). Consequência operacional, fechada:

1. **Gate de canal ligado ao churn MEDIDO, não ao assumido.** A primeira coorte anual renova em M13–M15. Até haver churn medido dessa coorte, o volume de cartas fica limitado aos lotes de teste de 2.000 (stop-loss de conversão 0,8% já definido acima). Escalar cartas para 4–5k/mês **só** se churn medido ≤ 25% E conversão medida ≥ 1,2% (rácio ≥ ~1,9:1 com payback na renovação). Se o churn medido vier a 30%+, as cartas ficam permanentemente em modo cirúrgico (só eventos de altíssima urgência, ex.: seguro caducado) e o crescimento assenta em email + verificador + selo.
2. **O churn passa a KPI de produto n.º 1** desde M1: o antídoto conhecido para "não aconteceu nada" é o relatório mensal "o teu AL passou no check" (prova de trabalho visível) + selo público — ambos já no plano de Produto; a sua eficácia mede-se na coorte M13–M15.

**LTV:CAC no cenário base**: email 213/4 ≈ **53:1**. Carta event-triggered 213/87 ≈ **2,4:1** — aceitável, mas o payback só chega na renovação (cash à cabeça blended = 0,6×49 + 0,4×119 = **77 €/cliente**, ou seja, a carta a 1,5% quase se autofinancia no mês: 40 clientes × 77 € = 3.080 € por 2.600 € de cartas).

### 4. Caminho para 1.500 €/mês e depois 5.000 €/mês

Receita anualizada blended por cliente: 0,6×49 + 0,4×39,67 = **45,3 €/ano brutos** (36,8 € líquidos de IVA).

**Decisão: todas as metas, KPIs e gates de GTM ficam fixados em receita LÍQUIDA de IVA.** A medida honesta do objetivo 1 é 1.500 €/mês líquidos = **490 clientes**; os "400 clientes" (versão bruta) deixam de ser referência em qualquer secção — quem gere ao número bruto está a gerir com 23% de ilusão.

- **1.500 €/mês líquidos de IVA** = 18.000 €/ano ÷ 36,8 € = **~490 clientes** = 0,41% da base de 120k. *(Para referência apenas: em brutos seriam ~400.)*
- **5.000 €/mês líquidos** = 60.000 €/ano ÷ 36,8 € = **~1.630 clientes** = 1,36% da base.

Mesmo o objetivo de 5.000 €/mês exige converter menos de 1,4% de um mercado onde temos o email ou a morada de 100% dos prospects e zero concorrência identificada. É conservador por construção.

**Timeline mês a mês (ano 1):** pressupostos — 12k emails/mês às coletivas (M2–M4, depois follow-ups), 2.000 cartas event-triggered/mês a partir de M3 (limitadas a este volume até ao gate de churn de M13–M15), orgânico/selo a crescer.

| Mês | Ações | Novos | Acumulado | Faturação anualizada |
|---|---|---|---|---|
| M1 | Produto + landing + verificador; beta em grupos FB de AL / ALEP | +10 | 10 | 38 €/mês |
| M2 | 1.ª vaga: 12k emails | +52 | 62 | 234 €/mês |
| M3 | 12k emails + 2k cartas | +83 | 145 | 547 €/mês |
| M4 | 12k emails + 2k cartas | +84 | 229 | 865 €/mês |
| M5 | Follow-ups + 2k cartas | +58 | 287 | 1.083 €/mês |
| M6 | Follow-ups + 2k cartas | +55 | 342 | 1.291 €/mês |
| M7–M9 | 2k cartas/mês + orgânico/selo | +42–46/mês | 474 | 1.789 €/mês |
| M10 | idem | +48 | 522 | 1.971 €/mês brutos |
| **M11** | idem | +48 | **570** | **~2.150 €/mês brutos ≈ 1.750 € líquidos → objetivo 1 (490 clientes / 1.500 € líquidos) atingido com folga; o limiar dos 490 cruza-se entre M9 e M10** |
| M12 | idem | +48 | ~618 | ~2.330 €/mês brutos (~1.900 € líquidos) |

Sanidade de cash do ano 1: 618 clientes × 77 € cash médio ≈ **47.600 € cobrados**; custos ≈ 26.000 € (20k cartas) + 600 € (ferramentas email) + 750 € (autocolantes) + 950 € (Stripe + infra + IA) ≈ 28.300 € → **operação autofinancia-se e ainda sobra**, antes de IVA e IRC. Nenhum mês exige injeção superior a ~2.700 €.

**5.000 €/mês líquidos**: partindo de 618 clientes em M12, com churn a entrar no ano 2 (~6–8 perdas/mês na coorte anual, se o churn base de 20% se confirmar) e cartas a subir para 4–5k/mês **condicionadas ao gate de M13–M15** (financiadas pelo cash acumulado, que em M12 já o permite), os net adds sobem para 70–90/mês → os 1.630 clientes chegam **entre M24 e M30**. Se o churn medido vier a 30%, o mesmo destino desloca-se para M30–M36 com mix de canais reponderado para email/verificador/selo — o negócio continua a fechar, só mais devagar. Se o selo gerar aquisição viral mensurável (cada selo num anúncio Airbnb é um anúncio nosso), encurta.

### 5. Decisões de faturação (fechadas)

1. **IVA — regime normal desde o dia 1, sem art. 53º.** O [regime de isenção do art. 53.º](https://calculariva.pt/taxas-regras/regime-isencao-art53/) (limite 15.000 €, saída imediata acima de 18.750 € intra-ano, redesenhado pelo DL 35/2025) seria tecnicamente possível num arranque lento — mas este plano cruza os 15.000 € de faturação por volta de M5–M6, o que forçaria uma transição administrativa a meio do arranque, e a isenção impede deduzir o IVA das cartas (~4.900 € de IVA dedutível no ano 1). Benefício líquido da isenção ≈ 2.400 € por ~4 meses de fricção: não vale. Além disso, se o veículo for a entidade existente que já fatura (Cosmic Oasis), a isenção nem está disponível. Regime normal, ponto.
2. **Preços com IVA incluído, sempre.** O cliente é um particular de 50 anos, não um CFO: "49 €" é 49 €. A tabela pública nunca muda com o enquadramento fiscal; o IVA é problema nosso, não dele. (Receita líquida: 39,84 € no anual, 96,75 € no trienal.)
3. **Stripe, sem alternativa.** É o único que dá subscrições + retries automáticos + hosted checkout + faturas sem escrever código de cobrança. Configuração: **cartão + SEPA Direct Debit** para planos com renovação automática; **Multibanco/MB Way** apenas como método de pagamento único no trienal (o público 40–65 confia em referências MB — não perder essa venda). ifthenpay/Eupago têm MB Way nativo mas não têm billing recorrente decente: eliminados.
4. **Dunning para renovações falhadas — sequência exata:**
   - **D-15**: email de pré-aviso da renovação com valor e data (obrigatório para renovações automáticas limpas; reduz disputas e chargebacks).
   - **D0**: tentativa de cobrança. Sucesso → recibo + "o teu AL mantém o check ✓".
   - **Falha D0**: email imediato com link Stripe para atualizar cartão + retries automáticos (Smart Retries) em **D+3, D+7, D+14**.
   - **D+7**: email 2 — "Em 7 dias o teu AL deixa de estar monitorizado." (loss framing, não desconto).
   - **D+14**: última retry + email 3 com **referência Multibanco** como via manual de pagamento.
   - **D+21**: suspensão efetiva — o selo público passa a "monitorização suspensa", email 4 confirma a perda de estado.
   - **D+45**: win-back automático "reativa hoje e retomamos onde ficou" — **sem desconto** (a integridade do preço vale mais do que recuperar meia dúzia de churns; quem volta, volta pelo medo, não pelo saldo).
   - Tudo automatizado em Stripe + emails transacionais: zero humanos, coerente com a decisão-quadro 5.

Fontes das âncoras: [ASAE — coimas AL](https://www.asae.gov.pt), [ALEP/Zurich — seguro AL](https://www.alep.pt/SEGUROWEB), [SGL Seguros](https://sgl.pt/seguro-obrigatorio-para-alojamento-local-al-o-guia-completo-para-proprietarios-em-2025/), [Alfa Seguros](https://alfaseguros.pt/blog/seguro-obrigatorio-alojamento-local-portugal/), [Zaask — honorários de advogados](https://www.zaask.pt/quanto-custa/advogados), [Porto Advogado](https://portoadvogado.com/quanto-cobra-um-advogado-por-consulta/), [Zaask — contabilistas](https://www.zaask.pt/quanto-custa/contabilistas), [CalcularIVA — art. 53.º CIVA 2026](https://calculariva.pt/taxas-regras/regime-isencao-art53/), [Portal das Finanças — art. 53.º](https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/civa_rep/Pages/artigo-53-o-do-civa.aspx).
