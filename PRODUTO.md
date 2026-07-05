# CheckAL — Produto & Serviço

> Parte do dossier CheckAL. Constantes e cadências: ver folha canónica em PLANO-NEGOCIO.md §5.

## Produto & Serviço

### 1. Oferta em tiers

Três planos, todos anuais ou plurianuais (nunca mensais — decisão fechada). O preço é por estabelecimento AL, porque o objeto monitorizado é o registo RNAL, não a pessoa.

| | **Base** | **Base Trienal** | **Portfólio** |
|---|---|---|---|
| Preço | 49€/ano por AL | 119€/3 anos por AL (poupa 28€, ~19%) | 149€/ano ou 359€/3 anos (4–10 ALs); 11–25 ALs: Portfólio+ 299€/ano; 26–50: Max 499€/ano |
| ALs adicionais | +19€/ano (2.º e 3.º) | +45€/3 anos cada | incluídos até 10 |
| Monitorização do registo RNAL | ✅ diária (registo do cliente) | ✅ | ✅ |
| Vigilância do seguro RC (ver nota na secção 2 sobre a fonte de dados) | ✅ | ✅ | ✅ |
| Alertas regulatórios (concelho + nacional) interpretados por IA | ✅ | ✅ | ✅ |
| Relatório mensal de tranquilidade | ✅ | ✅ | ✅ consolidado multi-AL |
| Selo "CheckAL ✓ — AL Verificado" (digital + página de verificação) | ✅ | ✅ | ✅ |
| Autocolante físico do selo | — | ✅ (oferta) | ✅ (todos os ALs) |
| Dashboard | — (email-first + área mínima) | — | ✅ |
| Export CSV / múltiplos utilizadores | — | — | ✅ |

**Decisões e porquês:**
- **Base a 49€/AL/ano**: o cliente-alvo (1–3 ALs, não-técnico) compra tranquilidade, não software. Tudo o que gera valor percebido (alertas interpretados, relatório, selo) está no Base — não se degrada o plano de entrada, porque o churn na renovação é o maior risco do modelo anual.
- **Trienal a 119€**: captura cash à cabeça do perfil "pagar e esquecer" e elimina dois momentos de churn. O autocolante físico oferecido no trienal custa ~1,50€ (impressão + CTT) e cria compromisso tangível — quem cola o selo na porta não cancela.
- **Portfólio a 149€/ano**: um gestor com 8 ALs pagaria 8×49€ = 392€ à la carte; 149€ é uma decisão instantânea e ainda assim triplica o ticket médio. O dashboard só existe aqui porque só este perfil o usa — construí-lo para o Base seria custo sem retenção.

Conta de sanidade para o objetivo (1.500€/mês = 18.000€/ano) — **a métrica é uma só, a da secção de Pricing**, para não haver contas paralelas: receita anualizada blended de 45,3€/cliente (o trienal conta anualizado: 119€ ÷ 3 = 39,7€/ano, nunca como cash de um ano). 18.000€ ÷ 45,3€ ≈ 397 → **meta: ~400 clientes ativos em carteira em termos brutos — a medida canónica é 490 clientes para 1.500€/mês líquidos de IVA (PRICING.md §4)** (o que, contando o churn do primeiro ciclo de renovação, implica ~490 aquisições brutas acumuladas). 400 clientes em 120.000 prospects = 0,33% de conversão da base. Alcançável.

---

### 2. Taxonomia de alertas

Duas cadências de verificação: **diária** para tudo o que respeita aos ALs dos clientes (páginas individuais RNAL — centenas de fetches, custo residual) e para as fontes legais (DRE, sites municipais); **semanal** para o snapshot nacional dos ~120k registos (diffing por concelho, que alimenta também a prospeção).

**Pré-validação obrigatória do pilar seguro (antes do FDS 1 — bloqueante para o copy, não para o produto).** A ALEP estima ~70.000 ALs sem seguro submetido, e a prova anual do seguro pós-março/2025 pode correr pela plataforma Gov.pt **sem se refletir na página individual do RNAL** — ou seja, o campo "validade da apólice" no RNAL pode estar vazio ou desatualizado mesmo quando o seguro está em dia. Antes de escrever uma linha de copy sobre seguro: **amostrar 200 páginas individuais do RNAL e medir em quantas o bloco seguro (companhia/apólice/validade) está preenchido e com data futura.** A regra decorre do resultado:
- **(a) Se o bloco for visível e atualizado** na maioria dos registos com seguro em dia → A3/A4 correm sobre a data do RNAL e o selo pode afirmar "Seguro: verificado no RNAL".
- **(b) Se não for visível/fiável** → o cliente introduz a data de fim da apólice no onboarding (um campo, 10 segundos) e o A3 passa a lembrete por data declarada; o A4 nunca é 🔴 sem fonte oficial confirmável.
- **(c) Em qualquer cenário, o selo e os relatórios só afirmam o que foi efetivamente verificado** — nunca "Seguro ✅" a partir de uma declaração, e nunca um 🟡 "não confirmável" fabricado a quem tem o seguro em dia. Mostrar um alerta amarelo falso a um cliente cumpridor é prática comercial enganosa (risco DL 57/2008) e mata a confiança no produto no primeiro contacto.

| # | O que se monitoriza | Gatilho | Urgência |
|---|---|---|---|
| A1 | Existência do registo no RNAL | O n.º RNAL do cliente desaparece do diff / página individual devolve estado alterado | 🔴 |
| A2 | Dados do registo | Alteração de titular, capacidade, modalidade ou morada no registo | 🟡 |
| A3 | Validade do seguro RC obrigatório | D-60, D-30 e D-7 antes da data de fim da apólice — data do RNAL quando lá constar (cenário a); caso contrário, data declarada pelo cliente no onboarding (cenário b) | 🟡 |
| A4 | Seguro RC expirado | Data ultrapassada sem renovação: 🔴 apenas quando confirmável em fonte oficial; se a fonte for a declaração do cliente, é lembrete insistente (D0 e D+7) que pede confirmação da renovação | 🔴 (fonte oficial) / 🟡 (data declarada) |
| A5 | Regulamento municipal de AL (DL 76/2024) | Novo regulamento, projeto em consulta pública ou deliberação da assembleia municipal no concelho do AL | 🟡→🔴 conforme conteúdo |
| A6 | Áreas de contenção / crescimento sustentável | Criação ou reavaliação de área que abranja a freguesia do AL | 🔴 se abrange; 🟡 se no concelho |
| A7 | Legislação nacional (DRE) | DL, lei ou portaria que altere o regime do AL (DL 128/2014 e sucessores) | 🟡 |
| A8 | Campanhas municipais de "limpeza" de registos | Edital/aviso municipal a exigir comprovativos, cruzado com A1/A4 | 🔴 |
| A9 | Prazos legais de resposta | Qualquer alerta que envolva notificação camarária — o prazo para enviar o comprovativo do seguro pedido pelo município é de **3 dias**, sob pena de cancelamento (art. 13.º-A, n.º 7 do [DL 128/2014](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid=3085&tabela=leis)) | 🔴 |

**Exemplos de mensagem (assunto do email):**
- A1 🔴: *"URGENTE: o registo AL 114144 deixou de constar como ativo no RNAL — age nos próximos dias"*
- A3 🟡: *"O seguro do teu AL 'Casa do Mar' expira a 15/08 — renova até lá ou arriscas o cancelamento do registo"*
- A5 🟡: *"Cascais pôs em consulta pública o regulamento municipal de AL — 2 propostas afetam-te, 1 não"*
- A6 🔴: *"A freguesia de Santa Maria Maior foi declarada área de contenção — o que muda (e o que NÃO muda) para o teu registo existente"*
- A7 🟡: *"Novo decreto-lei altera as regras do AL — impacto no teu caso: baixo. Explicamos porquê."*

**Nota factual importante (validada hoje):** a reapreciação geral dos registos em 2030, criada pela Lei 56/2023 (Mais Habitação), foi **revogada** pelo [DL 76/2024](https://diariodarepublica.pt/dr/detalhe/decreto-lei/76-2024-892301177) (cf. [análise Deloitte](https://www.deloitte.com/pt/pt/services/legal/blogs/al-06-11-2024.html)). Não vender "preparamos-te para 2030"; vender exatamente o contrário — *"em 2023 disseram-te que perdias o registo em 2030; em 2024 revogaram-no; em 2026 já saíram dezenas de regulamentos municipais. As regras mudam mais depressa do que consegues acompanhar — nós acompanhamos por ti."* A instabilidade legislativa É o produto. O A7 mantém-se para detetar qualquer reintrodução de mecanismos deste tipo.

O DL 76/2024 obriga os municípios com >1.000 registos a deliberar em 12 meses se regulamentam o AL — ou seja, 2025–2027 é uma vaga contínua de regulamentos municipais novos (Lisboa e Porto tinham prazo até nov/2025). É o vento de cauda perfeito para o A5.

---

### 3. A camada de IA (o diferenciador)

Um scraper de avisos envia links; o CheckAL envia **respostas**. Cada alerta passa por um pipeline de 4 passos antes de chegar ao cliente:

1. **Deteção** — diff no RNAL, novo documento no DRE, novo regulamento municipal.
2. **Filtragem determinística** — cruzamento por concelho, freguesia e modalidade do AL do cliente. Um regulamento do Porto nunca gera alerta a um cliente de Faro. Isto é código, não IA — a IA nunca decide *a quem* enviar.
3. **Interpretação por LLM** com template fixo e guardrails: output obrigatório em 3 blocos (afeta?/porquê/o que fazer), citação obrigatória da fonte oficial com link, proibição de aconselhamento jurídico definitivo (formulação "recomendamos que", nunca "és obrigado a" salvo quando a lei o diz textualmente), e classificação de severidade validada contra regras determinísticas (ex.: registo desaparecido é sempre 🔴, independentemente do que o modelo diga).
4. **Envio** — 🔴 em menos de 1 hora após deteção, por email **e SMS de reforço**; 🟡 no digest do dia seguinte às 9h; 🟢 agregado no relatório mensal.

**Garantia de entrega dos 🔴 (a promessa central não pode falhar em silêncio).** Um alerta com prazo legal de 3 dias não pode depender de um único email chegar à caixa de entrada de um cliente de 55 anos. O telefone do cliente está disponível desde o dia 1 (consta do RNAL e é confirmado no onboarding), portanto:
- **Todo o 🔴 dispara em simultâneo um SMS transacional**: *"CheckAL: tens um alerta URGENTE sobre o teu AL no teu email. Se não o encontrares, vê o spam ou entra em checkal.pt."* É comunicação de execução do contrato, não marketing — legal sem consentimento adicional (base contratual RGPD). Custo: ~0,05€/SMS, e os 🔴 são unidades por mês.
- **Tracking de entrega e abertura no Resend** (webhooks de bounce/open): bounce → re-envio automático para o email alternativo, se existir, + SMS; **🔴 não aberto em 24h → segundo email com assunto reformulado + segundo SMS + notificação ao dono**. Este escalonamento é a única exceção à regra "zero humanos" — justifica-se porque um 🔴 perdido é exatamente o cenário que o produto promete evitar, e o volume (poucos por mês) não cria carga operacional.

**Anatomia do email de alerta (estrutura fixa, sempre igual):**

> **[🔴 AÇÃO NECESSÁRIA] CheckAL — AL 114144 "Casa do Mar"**
>
> **Afeta o teu AL? SIM.**
> **Porquê (3 frases):** O teu registo deixou de constar como ativo no RNAL entre 24/06 e 01/07. Isto indica normalmente suspensão ou cancelamento — frequentemente por falta de comprovativo de seguro pedido pela câmara. Explorar um AL sem registo válido é contraordenação económica grave, com coimas de 2.500€ a 4.000€ para pessoas singulares e de 25.000€ a 40.000€ para pessoas coletivas (o alerta adapta o valor ao tipo de titular, que a API do RNAL nos dá).
> **O que fazer (por ordem):**
> 1. Verifica hoje o email/correio — procura notificação da CM Lisboa (prazo de resposta a pedidos de comprovativo: 3 dias).
> 2. Confirma o estado oficial: [link direto para a página RNAL do registo].
> 3. Se foi por seguro: envia a apólice válida à câmara e responde a este email — verificamos a reativação diariamente e avisamos-te quando constar.
>
> **Fonte:** RNAL, verificado a 01/07/2026 · Art. 13.º-A do DL 128/2014
> Estado geral: Registo 🔴 · Seguro 🟢 (válido até 03/2027 — fonte: RNAL *ou* data declarada pelo titular, sempre identificada) · Concelho: sem regulamento novo

**Semáforo:** 🟢 informativo (nada a fazer) · 🟡 ação recomendada com prazo (semanas) · 🔴 ação obrigatória com prazo curto (dias) e risco de coima/cancelamento. O cliente não-técnico de 55 anos entende um semáforo; não entende "DL 76/2024, art. 13.º-A, n.º 7".

---

### 4. Relatório periódico de tranquilidade

**Decisão: mensal, por email, sempre no dia 1.** Trimestral é pouco — 12 meses entre pagamento e renovação com 4 contactos não constrói hábito; 12 contactos sim. Custo marginal: zero (gerado automaticamente).

Conteúdo exato (meio ecrã de telemóvel, nunca mais):

1. **Veredicto no assunto:** *"✅ Junho: está tudo bem com o teu AL"* — o cliente fica descansado sem sequer abrir.
2. **Painel de estado:** Registo ativo 🟢 · Seguro válido até 15/03/2027 🟢 (com a fonte identificada: RNAL ou declarado pelo titular) · Área de contenção: não 🟢 · Regulamento municipal: sem alterações 🟢.
3. **O trabalho invisível (o parágrafo anti-churn):** *"Este mês verificámos o teu registo 30 vezes, analisámos 14 diplomas no Diário da República e 3 documentos municipais de Cascais. Nenhum afeta o teu AL."* — quantifica o serviço prestado nos meses em que "não aconteceu nada".
4. **O contexto que assusta na medida certa:** *"Em junho, 41 registos de AL foram cancelados ou suspensos no concelho de Cascais. O teu não foi um deles."* — este número sai de graça do diffing semanal e é o argumento de renovação mais forte do produto: o risco é real, visível e aconteceu a vizinhos.
5. **Próximos marcos:** ex. *"O teu seguro renova em 9 meses — avisamos a 60 e a 30 dias."*
6. Link para o relatório PDF trimestral (com selo e histórico), guardável/imprimível — serve de comprovativo de diligência do proprietário.

Antes da renovação anual, o email de dezembro vira **relatório anual**: totais do ano (verificações, diplomas analisados, cancelamentos no concelho) + data e valor da renovação, com 30 dias de antecedência (obrigação legal e boa prática anti-chargeback).

---

### 5. O selo "CheckAL ✓ — AL Verificado"

**Mecânica:** cada cliente tem uma página pública `checkal.pt/selo/{código aleatório}` (o caminho `/v/{NrRegisto}` fica reservado à verificação gratuita de prospects — códigos do selo não adivinháveis) que mostra em tempo quase real: nome do AL, n.º RNAL, e **apenas factos efetivamente verificados**: *Registo ativo ✅ · Seguro: verificado no RNAL ✅* (cenário a) **ou** *Seguro: declarado pelo titular, válido até MM/AAAA* (cenário b) *· Verificado a DD/MM/YYYY*. A página nunca afirma "Seguro comunicado às autoridades" nem "Seguro ✅" a partir de uma declaração não verificada — o selo vale exatamente o que a fonte permite provar, nem mais uma palavra. O cliente recebe: (a) badge em PNG/HTML para colar na descrição do anúncio Airbnb/Booking e no site próprio; (b) QR code que aponta para a página de verificação; (c) no trienal/Portfólio, autocolante físico para a porta. Se a subscrição caduca, a página passa a "verificação suspensa" — o selo morre sozinho, sem intervenção.

**Porque aumenta retenção:** o selo é a única parte do serviço *visível para terceiros*. Cancelar a subscrição deixa de ser "deixar de receber emails" e passa a ser "tirar o selo do meu anúncio e da minha porta" — perda tangível (efeito dotação).

**Porque aumenta aquisição:** cada selo num anúncio de Airbnb é um anúncio do CheckAL visto por hóspedes e, mais importante, por **outros proprietários de AL** que estudam a concorrência local. O QR na porta é visto por vizinhos — que num prédio com AL são frequentemente também proprietários de AL. Custo de aquisição deste canal: zero.

**Guardrail legal:** o selo atesta apenas factos verificáveis na fonte indicada ("registo ativo e monitorizado"; seguro só com a proveniência explícita — RNAL ou declaração do titular), nunca "AL legal" ou "AL certificado" — não somos entidade certificadora e o texto do selo tem de o deixar claro (o agente legal valida a redação final).

---

### 6. Onboarding: do pagamento ao primeiro relatório em <15 minutos

Pré-condição que torna isto trivial: **já temos a base nacional completa em cache** (snapshot semanal dos ~120k registos). O lookup do registo do cliente é instantâneo; só a página individual (estado detalhado + seguro) exige um fetch em direto.

| Passo | O que acontece | Tempo |
|---|---|---|
| 1 | Cliente insere n.º RNAL (ou nome/concelho) na landing → mini-relatório gratuito instantâneo a partir da cache (registo, localização, área de contenção). O bloco seguro/estado detalhado **não se inventa**: dispara um fetch assíncrono da página individual e o relatório completo chega por email minutos depois — o que de caminho captura o email do lead. Nunca se mostra um 🟡 "não confirmável" genérico | 5 s + email em minutos |
| 2 | CTA "Ativa a monitorização contínua" → checkout Stripe (cartão, MB Way, débito direto SEPA), escolha anual/trienal, email + NIF; se o bloco seguro do RNAL não for fiável (cenário b), pede-se a data de fim da apólice — um campo, 10 segundos | 2 min |
| 3 | Webhook de pagamento → cria conta, associa o(s) registo(s) RNAL, emite fatura (API de faturação certificada, ex. InvoiceXpress) | 5 s |
| 4 | Fetch em direto da página individual RNAL (headless) → extrai estado detalhado + dados do seguro quando disponíveis | 30–60 s |
| 5 | Gera o **Relatório Inicial de Estado** (mesmo formato do mensal + interpretação IA de qualquer 🟡/🔴 já existente à partida) | 20 s |
| 6 | Email de boas-vindas: relatório inicial + link do selo/página de verificação + badge para download + "o que vais receber e quando" | 5 s |

Total: ~3 minutos em condições normais (alvo comercial: <15 min, com folga para retries do Playwright), zero humanos. Caso-limite previsto: se o registo do cliente já estiver 🔴 no momento da compra (acontecerá — quem compra é quem está assustado), o relatório inicial é o primeiro alerta interpretado, com passos de regularização. É o melhor onboarding possível: valor máximo no minuto 3.

---

### 7. Email-first vs dashboard

**Decisão: o plano Base é email-first, sem dashboard.** O cliente de 40–65 anos low-touch não abre dashboards; abre email. Construir e manter um dashboard para quem não o usa é custo de desenvolvimento e de suporte sem efeito na retenção — a retenção no Base vem do relatório mensal e do selo.

O Base tem apenas uma **área de cliente mínima**, acessível por magic link no rodapé de cada email (sem password — passwords geram tickets de suporte, e a operação é zero-humanos):
- histórico de alertas e relatórios;
- dados do AL monitorizado e estado atual;
- faturas (download);
- gestão da subscrição: atualizar meio de pagamento, mudar email, cancelar (self-service obrigatório — cada cancelamento por email é um humano no loop).

**O dashboard é exclusivo do Portfólio** e é o argumento de upsell: tabela de todos os ALs com semáforo por linha (registo/seguro/regulamento), filtros por concelho, export CSV, utilizadores adicionais e relatório mensal consolidado. Para um gestor de 10 ALs, "os teus 10 semáforos numa página" justifica sozinho os 149€/ano.

Regra de arquitetura que decorre daqui: **todo o valor viaja por email (com SMS como canal de reforço dos 🔴); a web serve para verificar (selo) e gerir (conta)**. Isto mantém o produto simples, o suporte em zero e o desenvolvimento focado no que retém: deteção fiável, interpretação clara, presença mensal.
