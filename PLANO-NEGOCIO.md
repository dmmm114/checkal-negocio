# CHECKAL — Plano de Negócio
### O teu AL? Check ✓

> **O negócio numa frase:** subscrição de 49€/ano que vigia o registo RNAL, o seguro obrigatório e os regulamentos do concelho de cada Alojamento Local português, e avisa o proprietário — em português claro, interpretado por IA — antes que um prazo falhado lhe custe uma coima de 2.500€–40.000€ ou o cancelamento do registo.

**Data:** 02/07/2026 · **Estado:** validado tecnicamente, pronto para execução · **Veículo:** Cosmic Oasis, Lda. (marca própria)

---

## Índice do dossier

| Ficheiro | Conteúdo |
|---|---|
| **PLANO-NEGOCIO.md** (este) | Sumário, validação, mercado, pressupostos canónicos, riscos, roadmap |
| **MARCA.md** | Naming completo: 23 nomes, júri, domínios, identidade CheckAL |
| **PRODUTO.md** | Tiers, taxonomia de alertas, camada IA, relatório mensal, selo, onboarding |
| **PRICING.md** | Tabela canónica de preços, psicologia de conversão, unit economics, faturação |
| **GTM.md** | **Plano operacional canónico** — segmentação, funil, motor gatilho-a-gatilho, KPIs |
| **COPY-VENDAS.md** | Carta, emails frios, landing, email de alerta, selo — copy final pronto a usar |
| **AUTOMACAO.md** | Arquitetura zero-touch: pipeline, BD, IA, stack, sprints de construção |
| **LEGAL.md** | RGPD, prospeção canal a canal, T&C, INPI, estrutura societária, faturação AT |

---

## 1. Sumário executivo

**O que é.** A réplica do modelo Radar Marca aplicada ao Alojamento Local: monitorização contínua + alertas interpretados, vendida como subscrição anual/trienal ao proprietário individual (1–3 ALs, 40–65 anos, low-touch) com tier Portfólio para gestores multi-AL. Operação 100% automatizada — um VPS de 8€/mês, seis crons, Stripe e duas APIs de email.

**Porquê agora (a tempestade perfeita, toda verificada):**
- O DL 76/2024 obrigou os municípios com >1.000 registos a deliberar regulamentação em 12 meses → vaga contínua de regulamentos municipais 2025–2027.
- A prova anual do seguro é obrigatória desde março/2025 — e **40% dos ALs não a apresentaram no prazo** (Público, dez/2025).
- As câmaras já estão a cancelar em massa: **Lisboa 6.765 registos** (fev/2026), **Porto 1.413** (mai/2026), **+10.000 a nível nacional**; a ALEP estima 40–45 mil cancelamentos no processo em curso.
- Ninguém avisa o proprietário pessoalmente: publica-se em Diário da República e presume-se que leu. **É exatamente esse o produto.**

**A vantagem estrutural.** O dataset fonte (RNAL) expõe simultaneamente o produto a monitorizar E os contactos dos prospects — nome, NIF, email e telefone, públicos por força do art. 10.º do DL 128/2014. Não há "geração de leads": há 120.000+ registos à espera do pretexto certo.

**Números-chave:**

| | |
|---|---|
| Mercado | >120.000 registos ativos · ~70.000 titulares únicos · 100% com email |
| Preço | 49€/ano · 119€/3 anos · Portfólio 149–499€/ano (IVA incluído) |
| Margem bruta | ~95% (custo de servir ~1,4€/cliente/ano) |
| CAC canal principal | 4–8€ (email frio a pessoas coletivas) |
| Meta 1 | 1.500€/mês líquidos = **490 clientes** = 0,41% da base → M12–M15 |
| Meta 2 | 5.000€/mês líquidos = 1.630 clientes = 1,36% da base → M24–M36 |
| Cash-flow | Positivo desde M1 (trienal pré-pago: 77€ cash médio à cabeça) |
| Investimento | < 3.000€ até ao lançamento (domínios, INPI, infra, testes de carta) |
| Construção | MVP vendável em 3 fins-de-semana; sistema completo em 6 |

---

## 2. Validação técnica — CONCLUÍDA (02/07/2026)

Os três pontos em aberto no handoff foram todos fechados hoje, por teste direto:

1. **✅ A API REST está VIVA.** `GET https://webservices.turismodeportugal.pt/RNT_External/rest/RNT/list_RNAL?Concelho=Lisboa` devolve JSON com todos os registos ativos: Lisboa = 11.854 registos, 6,1 MB, 63 s, **100% com email do titular**. Campos: registo completo + titular (tipo singular/coletiva, nome, NIF, telefones, email). O país inteiro (~308 concelhos) descarrega-se em ~30 min, 2×/semana, por cêntimos.

2. **✅ A página individual é server-rendered.** `rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=X` devolve num GET simples (sem headless) o detalhe completo: datas, título de autorização de utilização, titular, contactos **e o bloco do Seguro de Responsabilidade Civil** (companhia, apólice, início, validade). No registo testado o seguro estava "Sem informação..." — o que confirma o gancho de marketing (ver §7 de PRODUTO.md: pré-validação com amostra de 200 páginas antes de escrever copy sobre seguro).

3. **✅ Deteção de alterações é construível e barata.** Diffing por concelho via API (registo que desaparece = cancelado/suspenso; novo = abertura) + página individual para os clientes pagantes. Registos inexistentes devolvem resposta distinguível (página de pesquisa, sem bloco de seguro). Regra dos 2 varrimentos elimina falsos alarmes.

**Nota:** Ponta Delgada devolveu 1 registo — os Açores têm registo regional próprio, fora do RNAL. Mercado continental + Madeira primeiro; Açores fica para fase 2 (fonte própria a mapear).

---

## 3. Mercado — dados reais (amostra de 19 concelhos, 64.641 registos ≈ 54% da base)

Extraído hoje da API `list_RNAL`:

| Métrica | Valor | Implicação |
|---|---|---|
| Pessoa singular | **56,1%** | Só contactável por **carta** (Lei 41/2004) — canal caro, em teste com gate |
| Pessoa coletiva | **43,9%** | Contactável por **email frio** (opt-out) — o motor de aquisição |
| Com email | **100%** | Não há registo sem contacto |
| Com telefone | 35,9% | SMS de reforço dos alertas 🔴 (clientes; nunca prospeção) |
| Modalidade apartamento | 75% | Cliente-tipo: T1/T2 urbano ou de praia |
| Titulares únicos | 36.421 na amostra | ~56% do n.º de registos → base nacional ≈ **~70k titulares** |
| Titulares com 1 AL | 78% dos titulares (44% dos registos) | O plano Base |
| Titulares com 2+ ALs | 22% dos titulares, **56% dos registos** | O tier Portfólio não é acessório — é metade do mercado |

Concentração geográfica: Lisboa (11.854), Albufeira (10.395), Porto (9.767), Loulé (7.170), Portimão (6.030), Lagos (4.656) — 6 concelhos ≈ 42% do mercado. Gestores profissionais identificáveis por domínio de email (ex.: lovelystay.com = 580 registos na amostra) → segmento à parte, excluir do funil de massa.

Nos 9 concelhos prioritários do GTM: 53.611 registos = 29.132 titulares únicos por NIF, dos quais 6.557 com 2+ ALs e 1.454 com 5+ (pitch Portfólio direto). **Regra desde o dia 1: um titular = um contacto (dedupe por NIF).**

**O mercado encolhe — e isso é o pitch, não o problema.** 40–45 mil cancelamentos estimados em curso (ALEP): quem sobrevive precisa de vigilância, e cada cancelamento no concelho do prospect é o nosso melhor argumento ("41 registos cancelados em Cascais em junho. O teu não foi um deles."). O TAM dinâmico é KPI mensal (net adds por concelho, sai de graça do diffing).

---

## 4. Decisões-quadro (fechadas — não relitigar)

1. **Marca: CheckAL** · checkal.pt (livre, registar já) · selo "CheckAL ✓ — AL Verificado" → MARCA.md
2. **Cliente primário:** proprietário individual 1–3 ALs; **Portfólio** para multi-AL como upsell → PRODUTO.md
3. **Pricing:** 49€/ano · 119€/3 anos · adicionais +19€/ano · Portfólio 149/299/499€ · IVA incluído · regime normal desde o dia 1 · garantia 30 dias → PRICING.md
4. **Canais (REORDENADO, pós-revisão jurídica):** prioridade = (1) **consent-first** via widget de verificação gratuita + (2) **parcerias com contabilistas/gestores** (canal de dia 1) → depois (3) email frio B2B **só a coletivas com email genérico** e (4) carta a singulares só em teste e **com parecer jurídico favorável**. Email/SMS a singulares a frio = **proibido**. **O parecer de jurista RGPD sobre a reutilização do RNAL é bloqueante antes de qualquer cold** → GTM.md §0 + LEGAL.md §1
5. **Plano operacional canónico = consent-first + parcerias** (widget + SEO programático + selo + contabilistas), com cold B2B a coletivas como suplemento condicionado ao parecer. A timeline com cold (GTM §4) é o cenário rápido; a consent-first pura (Meta 1 ~M15–M18) é o cenário robusto e o *default* de planeamento.
6. **Operação zero-touch** (uma exceção deliberada): email-first sem dashboard no Base; suporte 1.ª linha por IA; dunning automático; o dono só entra em escalações raras **e na angariação de parceiros** (o único toque humano aceite) → AUTOMACAO.md
7. **Estrutura:** dentro da Cosmic Oasis, série de faturação própria **"CKL"**, contabilidade segregada, marca INPI em nome da sociedade, **+ seguro de RC profissional antes de escalar** — preparado para asset deal futuro → LEGAL.md

---

## 5. Folha de pressupostos canónica (única fonte de verdade)

> O crítico adversarial encontrou constantes divergentes entre secções. Esta tabela manda; qualquer número diferente noutro ficheiro está errado.

| Constante | Valor canónico |
|---|---|
| Preços (IVA incl.) | 49€/ano · 119€/3 anos · +19€/ano ou +45€/3 anos por AL adicional (2.º/3.º) · Portfólio 149€/ano ou 359€/3 anos (4–10) · Portfólio+ 299€ (11–25) · Max 499€ (26–50) |
| Receita líquida de IVA | 39,84€ (anual) · 96,75€ (trienal) · blended anualizada 36,8€ |
| Mix assumido | 60% anual / 40% trienal · cash médio à cabeça 77€ |
| **Meta 1** | 1.500€/mês **líquidos** = **490 clientes ativos** (só como referência bruta: 400) |
| **Meta 2** | 5.000€/mês líquidos = 1.630 clientes |
| Coimas (ASAE — únicos valores a usar em copy) | Singular: 2.500–4.000€ · Coletiva: 25.000–40.000€ |
| Custo carta | 1,30€/unidade (e-carta CTT, impressão dedutível, franquia isenta de IVA) |
| Gate de cartas | teste 2×500; reativar só com conversão ≥0,8%; escalar só com ≥1,2% E churn medido ≤25% |
| Email frio | tooling 120€/mês · domínios satélite, nunca checkal.pt · ≤50/dia/caixa · conversão assumida 0,3–0,6% |
| Email transacional | Resend (não SES) |
| Churn assumido | 20%/ano (anual) — **é palpite: KPI n.º 1 a medir na coorte M13–M15** · estrutural adicional 8–10% |
| Renovação trienal assumida | 60% |
| LTV blended (churn 20%) | ~262€ brutos / ~213€ líquidos · a churn 30%: ~145€ líquidos |
| CAC | email 4–8€ · carta event-triggered 87–150€ (só se passar gate) · verificador/SEO ~0€ |
| Custo de servir | ~1,4€/cliente/ano · infra total 35–50€/mês · margem bruta ~95% |
| IA | Haiku 4.5 triagem + Sonnet redação, Batch API · <10€/mês |
| Timeline canónica (cenário B) | M6: 168 clientes (~630€/mês) · Meta 1: M12–M15 · upside com cartas: M11 |

### Cadência canónica de monitorização (alinha produto, copy, selo e T&C)

| O quê | Cadência | Latência máx. de deteção |
|---|---|---|
| Página individual dos **clientes** (estado + seguro) | **Diária** (03h30; 500 clientes × 3 s ≈ 25 min) | ~24 h |
| Varrimento nacional (diffing 308 concelhos) | 2×/semana (2.ª e 5.ª, 03h00) | ≤4 dias (+ regra dos 2 varrimentos) |
| DRE Parte H + fontes municipais | Diária (07h00) | ~24 h |
| **SLA contratual (T&C)** | — | **≤7 dias** após publicação detetável |
| Regra de copy | Nunca prometer "no próprio dia" para cancelamentos; "detetamos em dias, não meses" é defensável | |

---

## 6. Riscos e defensibilidade (os 3 modos de morte + planos B)

### ⚠️ Risco 0 (BLOQUEANTE, novo) — o portão jurídico + a lacuna do seguro
Dois buracos que têm de fechar **antes** do 1.º envio, não depois. São a revisão mais importante do plano:

- **Reutilizar o RNAL para prospeção pode ser ilegal (RGPD, limitação de finalidades).** "Público" não é "reutilizável para marketing"; a CNPD tem sancionado exatamente isto (caso Bisnode e afins). A divisão coletiva/singular resolve a Lei 41/2004, **não** o RGPD a montante. → **Parecer de jurista de proteção de dados é bloqueante** (LEGAL.md §1). O *fallback* já está decidido se o parecer for negativo: **consent-first puro** (widget + parcerias), que o GTM já assume como cenário principal (GTM.md §0) — por isso este risco, embora grave, **não mata o negócio**, só reordena a aquisição.
- **Falta seguro de RC profissional.** Se a IA classificar mal um regulamento e o cliente perder o registo, a limitação de responsabilidade a 49€ pode ser **afastada em tribunal** (cláusula abusiva em contrato de consumo). → Contratar apólice **E&O antes de escalar** (LEGAL.md §5, cláusula 9) + disclaimer em **cada** alerta ("informação, não aconselhamento; confirme com profissional").

### Modo de morte 1 — A fonte única fecha ou degrada (agravado pela nossa própria campanha)
O negócio inteiro assenta na API `list_RNAL` e na página `rnal.aspx`. Uma campanha de dezenas de milhares de contactos a citar "obtivemos os seus dados no RNAL" pode gerar queixas à CNPD e atenção do Turismo de Portugal → captcha, rate-limiting, remoção dos contactos públicos, fecho da API.

**Plano B — honesto sobre o que salva e o que NÃO salva (o "scraper de fallback" não é rede de segurança contra o pior cenário):**
- **Distinguir degradação suave de fecho duro.** Contra rate-limiting, captcha ou mudança de formato (**suave**), um scraper de `Pesquisa_AL.aspx` + sondagem sequencial de `nr=` ajuda. Contra **autenticação obrigatória ou fecho da API (duro), o scraper é inútil** — enfrenta o mesmo muro. Não nos iludamos: o scraper mitiga o incómodo, não a catástrofe.
- **O ativo defensável real é o histórico de snapshots** (<1 GB/ano, guardar para sempre): séries temporais por concelho que ninguém reconstrói. Sobrevive a qualquer fecho e é o que um entrante nunca terá.
- **O pilar regulatório (DRE) é independente do RNAL** — não morre se a API fechar. **Decisão estratégica: comunicar e vender primeiro a inteligência regulatória** (a interpretação "isto afeta-te e porquê"), que é o valor durável, e tratar a monitorização de estado do registo como o gancho de aquisição — mais exposto, mas não é o coração da proposta.
- **A base paga sobrevive a um fecho da API:** os clientes deram os dados no onboarding. Um fecho mata o canal de *prospeção em massa*, não o *serviço* → acelerar parcerias e SEO (já são o plano principal, §6-GTM).
- Throttle educado (2 s entre concelhos), User-Agent identificado, horário noturno; tom de campanha calibrado (nunca "temos os dados de 120 mil proprietários" — a fonte cita-se no rodapé RGPD, não no pitch).
- **Residual aceite, não mascarado:** o negócio assenta num endpoint não-contratualizado que pode mudar sem aviso. É uma **aposta consciente**, mitigada (snapshots + pilar regulatório independente + base paga já onboarded), **não eliminada**. Quem entrar no projeto tem de saber disto.

### Modo de morte 2 — Mercado finito e a encolher, funil one-shot
~70k titulares, 1/3 pode desaparecer em 2–3 anos, o pool de email esgota a primeira passagem em ~9–10 meses.

**Mitigação (já embutida no GTM):** TAM dinâmico como KPI mensal · re-contacto legítimo por **pretexto novo** (cada regulamento reabre o concelho inteiro; máx. 1×/trimestre por titular) · novos registos = trigger de venda em <7 dias · parcerias com contabilistas a partir de M6 (canal que não esgota) · subida de preço para 59€/139€ quando a prospeção deixar de ser o motor (M9–M12) · **fase 2 real: Espanha** (VUT; "check" é palavra universal — a marca viaja; o formato local — CheckAL como marca-casa ou CheckVUT — decide-se na fase 2).

### Modo de morte 3 — Cópia por incumbentes (e o incumbente não é quem se pensava)
O plano prova que isto se constrói em ~5 fins-de-semana sobre dados públicos. **Mas o incumbente mais provável não é uma software house — é o contabilista / gestor de AL.** Quem já tem a relação e os dados do proprietário são eles; juntar "vigilância de registo" é upsell trivial sobre um cliente que já servem e faturam. São, ao mesmo tempo, a **maior ameaça e o melhor canal de distribuição** — e é essa dupla natureza que define a estratégia. Software de gestão (Hostkit/Chekin) e a ALEP tocam o compliance de raspão; o Gov.pt pode um dia melhorar as notificações oficiais.

**Estratégia de moat (janela assumida: 12–18 meses):**
1. **Lock-in trienal agressivo** — a única receita verdadeiramente defendida; o trienal é o default visual da landing.
2. **Rede de selos visível** — cada selo em anúncio/porta é custo de cópia acrescido para um entrante (efeito de marca em rede).
3. **Histórico de snapshots como dado proprietário** — séries temporais por concelho que ninguém reconstrói; alimenta o SEO programático (308 páginas) e os relatórios ("o teu concelho perdeu 214 registos este trimestre").
4. **Velocidade como prova** — SLA evento→campanha <72h; quem chega uma semana depois é jornal velho.
5. **KPI trimestral de concorrência** (pesquisa ativa de entrantes).
6. **Transformar a ameaça em canal — promovido a estratégia primária (não contingência):** as parcerias com contabilistas/gestores e o white-label do motor regulatório passam de "fase 2" a **canal de dia 1** (GTM.md §0 e §6). Eles têm os gestores e os clientes *consentidos*; nós temos o pipeline, o histórico de snapshots e a interpretação. Se um deles quiser construir em vez de integrar, o white-label é mais barato para ambos do que a guerra. Bónus: leads consentidos e apresentados por terceiro de confiança **contornam o portão RGPD** (Risco 0) — é a mesma jogada a resolver dois problemas.

### Risco 4 (médio) — Prometer mais do que a arquitetura entrega
Resolvido pela cadência canónica (§5): página dos clientes diária, copy nunca diz "no próprio dia" para cancelamentos, SLA contratual ≤7 dias.

### Veredito do crítico adversarial (na íntegra, para memória futura)
> "O plano aguenta-se no núcleo: a dor é real e verificada, o acesso aos dados e aos prospects é uma vantagem estrutural genuína, os custos de servir são residuais e o trabalho legal é acima da média. Mas está mais fraco exatamente onde aposta o dinheiro: a economia das cartas assenta numa conversão que os próprios micro-pressupostos desmentem [→ resolvido: cartas fora do plano canónico, só teste com gate]; Pricing e GTM continham duas timelines divergentes [→ resolvido: GTM cenário B é canónico]. O segundo pilar (vigilância do seguro) não tem fonte garantida para metade da base [→ resolvido: pré-validação com 200 páginas antes do copy + fallback de data declarada no onboarding]. Os três modos de morte estão por endereçar [→ endereçados acima]. Nada disto é fatal se corrigido antes do lançamento."

---

## 7. Roadmap de execução

### Hoje / esta semana (custo total ~250€)
0. [ ] **[BLOQUEANTE] Marcar consulta com jurista de proteção de dados** sobre a reutilização do RNAL para prospeção (~150–400€). Nada de cold antes deste "sim" → LEGAL.md §1
1. [ ] Registar **checkal.pt** + variantes chekal.pt/checal.pt (redirects) — antes de tudo. checkal.com está parqueado à venda (Afternic): NÃO comprar já; getcheckal.com (livre) serve o email frio
2. [ ] Submeter **marca INPI** nominativa, classes 35/42/45 (~194€, orçamentar 210€)
3. [ ] **Amostrar 200 páginas individuais do RNAL** → medir taxa de preenchimento do bloco seguro (decide o copy do pilar seguro — cenário (a) ou (b) do PRODUTO.md §2)
4. [ ] Criar série de faturação **"CKL"** + comunicar à AT · conta InvoiceXpress
5. [ ] Registar Livro de Reclamações Eletrónico
6. [ ] Pedir **cotação de seguro de RC profissional / E&O** (300–800€/ano) — contratar antes de escalar → LEGAL.md §5 cláusula 9
7. [ ] Angariar **3–5 contabilistas/gestores de AL piloto** (canal de dia 1, leads consentidos) → GTM.md §0

### Construção (6 fins-de-semana — detalhe em AUTOMACAO.md §7)
| Sprint | Entregável | Marco |
|---|---|---|
| FDS 1 | Ingestão 308 concelhos + BD + diffing + regra 2 varrimentos | 2 varrimentos completos guardados |
| FDS 2 | Landing + verificador gratuito + Stripe + webhook + **InvoiceXpress** | Consigo comprar e receber fatura certificada — sem isto não se vende a 1 cliente |
| FDS 3 | Onboarding automático + relatório inicial + selo + página pública + alertas de estado | **MVP vendável** — compra→relatório <15 min sem humanos |
| FDS 4 | Pipeline DRE + triagem Haiku + alertas Sonnet com validação anti-alucinação | Documento real gera alerta correto e citado |
| FDS 5 | Dunning + suporte IA + healthchecks + circuit breaker por concelho + backups | Sobrevive a 3 semanas de férias |
| FDS 6 | Motor de campanhas gatilho→segmento→envio <72h | GTM zero-touch verdadeiro |

### Lançamento (M1–M3 — detalhe em GTM.md §0; ordem revista, consent-first)
- M1: widget no ar + beta em grupos de Facebook de AL + arranque da angariação de 3–5 contabilistas-piloto. Cold **só se o parecer jurídico já tiver chegado**: email B2B a coletivas com email genérico (gatilhos Porto/Funchal — ainda quentes)
- M2: SEO programático no ar (308 páginas) + primeiras parcerias a produzir leads + email B2B nos concelhos das Vagas 1–2. Carta-teste A (500, Porto) **só com parecer favorável**
- M3: escalar o que converter (widget/parcerias/cold-B2B) + avaliação do gate das cartas + entrada nos grupos FB como serviço público
- **Sempre, antes do 1.º envio a frio:** parecer jurídico RGPD (passo 0) + pedido INPI submetido + checklist do LEGAL.md §7 cumprida

### KPIs norte (alvos M3 / M6 / M12)
| KPI | M3 | M6 | M12 |
|---|---|---|---|
| Verificações gratuitas/mês | 350 | 800 | 2.500 |
| Conversão verificação→pago (30d) | ≥6% | ≥8% | ≥10% |
| **Clientes ativos** | 56 | 168 | 400–450 |
| CAC blended | ≤35€ | ≤12€ | ≤15€ |
| Net adds RNAL/mês (TAM dinâmico) | medir | medir | tendência |
| % 1.ª passagem email consumida | ~25% | ~60% | 100% + re-contacto |
| Tempo evento→campanha | ≤7 dias | ≤72h | ≤48h |
| Spam complaints | <0,3% sempre · opt-outs processados <24h | | |

---

## 8. Porque é que isto ganha

1. **A dor é real, atual e documentada** — 10.000+ cancelamentos, 40% sem seguro no prazo, vaga de regulamentos 2025–2027. Não é medo fabricado; é o Diário da República.
2. **O produto entrega no minuto 3** — verificação gratuita → relatório → alerta interpretado. Valor visível antes de pagar.
3. **A economia é obscena** — margem ~95%, CAC 4–8€ no canal principal, LTV:CAC >25:1 mesmo no pior cenário de churn, cash-flow positivo desde M1.
4. **Zero concorrência direta hoje** — e uma janela de 12–18 meses com moat em construção (trienal, selo, histórico, velocidade).
5. **Automação total** — o negócio cabe num VPS de 8€ e sobrevive a férias de 3 semanas. Escala de 100 para 1.600 clientes sem contratar.
6. **Reutiliza o playbook Radar Marca** — pipeline de diffing, cartas, billing: já foi feito uma vez, agora com mercado 70× maior e contactos incluídos.
