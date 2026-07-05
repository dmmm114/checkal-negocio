# CheckAL — Handoff Completo
### O teu AL? Check ✓

> **Documento de transição.** Reúne tudo o que foi definido sobre o projeto CheckAL para que qualquer pessoa (sócio, programador, consultor, contabilista) possa entrar ao corrente sem contexto prévio. Autossuficiente — mas cada secção aponta para o documento detalhado onde aprofundar.
>
> **Data:** 05/07/2026 · **Estado:** estratégia 100% fechada e validada · construção da plataforma iniciada (fundação técnica) · **Veículo:** Cosmic Oasis, Lda.

---

## 0. Mapa de documentos (o dossier completo)

Este handoff é o resumo. A profundidade está em 8 documentos na pasta do projeto:

| Documento | O que contém |
|---|---|
| **PLANO-NEGOCIO.md** | Documento-mãe: sumário, validação técnica, mercado, folha de pressupostos canónica, riscos e planos B, roadmap |
| **MARCA.md** | Naming completo (3 rondas, ~60 nomes), porquê CheckAL, identidade, domínios, checklist de registo |
| **PRODUTO.md** | Tiers, taxonomia de alertas, camada de IA, relatório mensal, selo, onboarding |
| **PRICING.md** | Tabela de preços, psicologia de conversão, unit economics, faturação |
| **GTM.md** | Plano de aquisição canónico: segmentação, funil, motor de campanhas, KPIs |
| **COPY-VENDAS.md** | Copy final pronto a usar: carta, emails frios, landing, alertas, selo |
| **AUTOMACAO.md** | Arquitetura técnica zero-touch: pipelines, base de dados, IA, stack, plano de construção |
| **LEGAL.md** | RGPD, prospeção canal a canal, T&C, registo INPI, estrutura societária, faturação AT |

Existe ainda `radar-al-handoff.md` (o handoff **antigo**, da fase "Radar AL" — superado por este) e `CLAUDE.md` (memória técnica para o assistente de código).

---

## 1. O que é o CheckAL, numa página

**O problema (real, atual, documentado).** Um proprietário de Alojamento Local (AL) em Portugal pode perder o registo — e o negócio inteiro — por falhar um prazo que nunca soube que existia. As regras mudam constantemente e ninguém o avisa pessoalmente: publica-se em Diário da República e presume-se que leu.

- **Seguro obrigatório:** desde março/2025 a prova anual do seguro de responsabilidade civil é obrigatória. **40% dos ALs não a apresentaram no prazo** (Público, dez/2025).
- **Cancelamentos em massa:** Lisboa cancelou **6.765 registos** (fev/2026), Porto **1.413** (mai/2026), **+10.000 a nível nacional**. A ALEP estima 40–45 mil cancelamentos no processo em curso.
- **Vaga de regulamentos:** o DL 76/2024 obrigou os municípios com >1.000 registos a legislar sobre AL em 12 meses → dezenas de regulamentos municipais novos entre 2025 e 2027.
- **Coimas:** exploração de AL sem registo válido custa **2.500€–4.000€** (pessoa singular) ou **25.000€–40.000€** (pessoa coletiva), além do cancelamento.

**A solução.** Uma subscrição de **49€/ano** que vigia continuamente, por cada AL:
1. O **estado do registo** no RNAL (se desaparece/muda = cancelamento/suspensão);
2. A **validade do seguro** obrigatório;
3. Os **regulamentos do concelho**, áreas de contenção e legislação nacional (DRE).

E envia **alertas interpretados por IA** — não um link para o Diário da República que o proprietário não sabe ler, mas *"isto afeta o teu AL? Sim/Não, porquê, e o que fazer"* — em português claro. Nos meses sem novidade, um relatório mensal *"o teu AL passou no check ✓"*.

**A promessa:** *"O teu AL? Check."* — nunca serás apanhado de surpresa.

**A vantagem estrutural única.** O dataset que alimenta o produto (o registo público RNAL) é **também a lista de prospects**: contém nome, NIF, email e telefone de cada titular, públicos por força do art. 10.º do DL 128/2014. Não há custo de geração de leads — há 120.000+ registos à espera do pretexto de contacto certo.

---

## 2. Validação técnica — JÁ FEITA (não repetir)

Todos os pontos críticos foram testados diretamente a 02/07/2026:

1. **✅ A API pública do Turismo de Portugal está viva e é completa.**
   `GET https://webservices.turismodeportugal.pt/RNT_External/rest/RNT/list_RNAL?Concelho=Lisboa`
   devolve JSON com todos os registos ativos do concelho. Lisboa: 11.854 registos, 6,1 MB, 63 segundos, **100% com email do titular**. Campos por registo: nº, datas, nome do alojamento, modalidade, camas/utentes, morada completa, freguesia/concelho/distrito + titular (tipo singular/coletiva, nome, NIF, telefone, telemóvel, email). O país inteiro (~308 concelhos, 120k+ registos) descarrega-se em ~30 minutos.

2. **✅ A página individual é server-rendered.**
   `https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=XXXXX` devolve num GET simples (sem browser automatizado) o detalhe completo, **incluindo o bloco do Seguro de Responsabilidade Civil** (companhia, apólice, validade). Serve para o detalhe dos clientes pagantes.

3. **✅ A deteção de alterações é trivial e barata.**
   Diffing por concelho: registo que desaparece = cancelado/suspenso; novo = abertura. A "regra dos 2 varrimentos" elimina falsos alarmes.

**Dados de mercado reais** (amostra de 19 concelhos, 64.641 registos ≈ 54% da base):
- **56% pessoa singular / 44% pessoa coletiva** (determina o canal: carta vs email)
- **100% com email**, 36% com telefone
- **~70.000 titulares únicos** a nível nacional; os titulares com 2+ ALs detêm **56% dos registos** (o tier Portfólio é metade do mercado, não um acessório)
- Concentração: Lisboa, Albufeira, Porto, Loulé, Portimão, Lagos ≈ 42% do mercado
- Nota: os Açores têm registo regional próprio (fora do RNAL) → fase 2

---

## 3. Decisões fechadas (não relitigar)

### Marca
- **Nome: CheckAL** ✓ · domínio **checkal.pt** (livre à data — registar já)
- Tagline: **"O teu AL? Check."** · Selo: **"CheckAL ✓ — AL Verificado · Verified listing"**
- Escolhido pelo dono após 3 rondas de naming (~60 nomes). O júri preferia "Radar AL" (família com o negócio irmão Radar Marca); o dono escolheu CheckAL pelo *punch* e pelo encaixe no funil (o widget gratuito é "Faz o check ao teu AL"). **Radar AL fica como reserva estratégica.**
- Linguagem de estados: **"passou no check ✓" / "falhou o check 🔴"** (resolve a contradição de um nome positivo a dar más notícias)
- Domínios a registar: checkal.pt + variantes de grafia (chekal.pt, checal.pt) + getcheckal.com (satélite para email frio). **checkal.com está parqueado à venda — NÃO comprar já.**
- Detalhes: **MARCA.md**

### Preços (IVA incluído — folha canónica)
| Plano | Cobertura | Preço |
|---|---|---|
| CheckAL Anual | 1 AL | **49 €/ano** |
| CheckAL Trienal | 1 AL | **119 €/3 anos** (poupa 28 €) |
| AL adicional (2.º/3.º) | por AL | +19 €/ano ou +45 €/3 anos |
| Portfólio | 4–10 ALs | 149 €/ano ou 359 €/3 anos |
| Portfólio+ | 11–25 ALs | 299 €/ano |
| Portfólio Max | 26–50 ALs | 499 €/ano |

- Regime de IVA normal (23%) desde o dia 1 · garantia de 30 dias com reembolso total
- Trienal é o *default* visual da landing (captura cash à cabeça, reduz churn)
- Detalhes e unit economics: **PRICING.md**

### Metas
- **Meta 1: 1.500 €/mês líquidos = 490 clientes ativos** (0,41% da base) → M12–M15
- **Meta 2: 5.000 €/mês líquidos = 1.630 clientes** → M24–M36
- Margem bruta ~95% (custo de servir ~1,4 €/cliente/ano) · cash-flow positivo desde o M1 (trienal pré-pago = 77 € cash médio à cabeça) · CAC do canal principal 4–8 €

### Cliente-alvo
- **Primário:** proprietário individual com 1–3 ALs, 40–65 anos, não-técnico, "pagar e esquecer" (email-first, sem dashboard)
- **Secundário:** gestor/empresa multi-AL → tier Portfólio com dashboard (upsell)

### Aquisição (REORDENADA — consent-first + parcerias primeiro)
> **Mudança importante (jul/2026):** a versão inicial punha o email frio à base RNAL como motor principal. Duas revisões obrigaram a inverter a ordem — o **risco RGPD** de reutilizar o RNAL (ver §8) e o facto de o **contabilista ser o incumbente E o melhor canal**. A nova ordem também é a mais robusta juridicamente.

1. **Consent-first — o widget "Faz o check ao teu AL"** (motor primário): o titular *pede* o relatório e consente → captura → nurture → conversão. Sem risco de reutilização de dados. Tráfego por SEO + grupos de FB + ads.
2. **Parcerias com contabilistas / gestores de AL** (canal de **dia 1**, não fase 2): leads consentidos e apresentados por terceiro de confiança; neutraliza a maior ameaça competitiva. É o único toque humano deliberadamente aceite.
3. **Email frio B2B só a coletivas com email genérico** (geral@/info@) — o único cold com base jurídica limpa; suplementar.
4. **Carta a singulares** — só teste pequeno, e **só com parecer jurídico favorável**. Fora das projeções.
- **Email/SMS a singulares a frio = PROIBIDO** (Lei 41/2004).
- **Motor perpétuo:** cada evento regulatório novo alimenta o conteúdo do widget/SEO/parcerias e, quando o cold B2B estiver ativo, dispara a campanha ao concelho afetado em <72h.
- Gatilhos quentes: Porto (1.413 cancelamentos, mai/2026), Funchal (regulamento, jun/2026), Lisboa (6.765 cancelamentos, fev/2026).
- Coimas para copy (ASAE): singular **2.500–4.000€**, coletiva **25.000–40.000€**.
- **Impacto na meta:** no cenário consent-first puro (sem cold), a Meta 1 escorrega para **~M15–M18** e o CAC sobe para ~25–35€ (ainda saudável). Com cold B2B ativo, mantém-se ~M12–M15.
- Detalhes: **GTM.md §0** e **COPY-VENDAS.md**

### Operação
- **100% automatizada, zero humanos no loop** (onboarding, cobrança, alertas, dunning, suporte 1.ª linha por IA)
- O dono só entra em escalações raras
- Tem de sobreviver a 3 semanas de férias sem toque

### Estrutura & legal
- Arranca dentro da **Cosmic Oasis, Lda.** (entidade existente) com marca própria — não constituir nova entidade agora
- Série de faturação própria **"CKL"** · contabilidade segregada (preparado para venda futura por *asset deal*)
- Marca INPI a registar (classes 35/42/45, ~194 €) **antes de qualquer envio público**
- RGPD: divisão de canais por tipo de titular, disclaimers anti-"carta oficial", lista de supressão, prova de consentimento do lead magnet
- Detalhes: **LEGAL.md**

---

## 4. Arquitetura técnica (a plataforma)

**Filosofia:** um pipeline batch com meia dúzia de crons idempotentes sobre uma base de dados, não uma aplicação "viva". Tudo o que falha tem retry; tudo o que é ambíguo pára e avisa o dono. Reutiliza a filosofia do pipeline INPI do Radar Marca (o negócio irmão).

**Stack decidida (barata, um operador único):**
| Camada | Escolha | Custo/mês |
|---|---|---|
| Runtime | Python 3.12+ / FastAPI | — |
| Base de dados | SQLite (dev/MVP) → Postgres (prod) — troca por variável de ambiente | — |
| Servidor | Hetzner CX32 + Caddy | ~8 € |
| Crons | systemd timers | — |
| Landing/dashboard | Estático servido pelo FastAPI (padrão Radar Marca) | — |
| Pagamentos recorrentes | **Stripe** (cartão/SEPA) | 1,5%+0,25 €/tx |
| Pagamentos por referência | **IfThenPay** (Multibanco / MB WAY) — o dono já tem conta | ~1,x%/tx |
| Faturação certificada | **InvoiceXpress** (série CKL, comunica à AT) | ~10 € |
| Email transacional | **Resend** | 0–18 € |
| IA | Anthropic: **Haiku 4.5** (triagem) + **Sonnet** (redação de alertas), via Batch API | <10 € |
| Observabilidade | Healthchecks.io + UptimeRobot | ~4 € |

**Total de infra ~35–50 €/mês** contra ~1.500 €/mês de receita-alvo → margem >95%.

**Componentes do sistema:**
1. **Pipeline de dados RNAL** — cron 2×/semana puxa os ~308 concelhos, normaliza, guarda snapshot, faz diffing (novos/desaparecidos/alterados). Página individual (estado+seguro) só para clientes, diariamente.
2. **Pipeline regulatório** — monitoriza o Diário da República (2.ª série, Parte H) e sites das câmaras prioritárias, extrai e classifica por concelho.
3. **Camada de IA** — para cada evento × cada cliente afetado, gera um alerta personalizado com salvaguardas anti-alucinação (cita sempre a fonte, classificação conservadora).
4. **Plataforma web** — landing + widget de verificação gratuita + área de cliente + **dashboard admin** (à semelhança do Radar Marca) + página pública do selo.
5. **Pagamentos & faturação** — Stripe + IfThenPay + InvoiceXpress.
6. **Ciclo de vida** — onboarding automático (<15 min do pagamento ao 1.º relatório), dunning, suporte por IA.
7. **Observabilidade** — dead-man switches, deteção de mudança de esquema da API, circuit breaker por concelho, backups.

**Plano de construção:** MVP vendável em **3 fins-de-semana**, sistema completo em **6**. Detalhe sprint a sprint em **AUTOMACAO.md §7**.

---

## 5. Estado atual da construção

**Estratégia:** ✅ 100% completa e documentada (os 8 ficheiros do dossier).

**Código:** 🔨 fundação iniciada em `checkal/`:
- `checkal/requirements.txt` — dependências (FastAPI, SQLAlchemy, httpx, Jinja2, anthropic)
- `checkal/.env.example` — todas as variáveis de ambiente e credenciais necessárias
- `checkal/app/config.py` — configuração central com a folha de pressupostos canónica (preços, coimas, limiares, cadências)
- `checkal/app/db.py` — motor SQLAlchemy (SQLite dev / Postgres prod)

**Por construir** (a fundação continua, depois os módulos-folha):
- Modelos de dados (o contrato partilhado)
- Cliente RNAL + ingestão + diffing (a "verificação de dados")
- Parser da página individual (seguro/estado)
- Pipeline regulatório (DRE)
- Camada de IA (classificação + redação de alertas)
- Web: landing, widget de check gratuito, área de cliente, **dashboard admin**, página do selo
- Integrações: IfThenPay, Stripe, InvoiceXpress, Resend
- Templates de comunicação (alertas, relatório mensal, boas-vindas, dunning, resultado do check)
- Ciclo de vida: onboarding, dunning, suporte IA
- Observabilidade e testes

---

## 6. O que é preciso para avançar (credenciais e contas)

Para a plataforma ir para produção, o dono precisa de reunir/fornecer:

| Item | Onde obter | Estado |
|---|---|---|
| 🚦 **[BLOQUEANTE] Parecer jurídico RGPD** — pode o RNAL ser usado para prospeção? | Jurista de proteção de dados (~150–400 €) | ⬜ **marcar antes de qualquer cold** |
| **Seguro RC profissional / E&O** — cobre erro de classificação da IA | Corretor (Hiscox/Tranquilidade/Fidelidade, 300–800 €/ano) | ⬜ cotação antes de escalar |
| Domínio **checkal.pt** (+ chekal.pt, checal.pt, getcheckal.com) | Registrar .pt (ex: dominios.pt / Amen) | ⬜ a registar |
| Marca INPI **CHECKAL** classes 35/42/45 | inpi.justica.gov.pt (~194 €) | ⬜ a submeter (antes de qualquer envio) |
| **IfThenPay** — MB Key, MB WAY Key, Anti-Phishing Key | backoffice.ifthenpay.com (o dono já tem conta) | ⬜ fornecer chaves |
| **Stripe** — Secret Key, Webhook Secret, Price IDs (anual/trienal) | dashboard.stripe.com | ⬜ criar produtos |
| **InvoiceXpress** — conta + API Key + série CKL | invoicexpress.com | ⬜ configurar série CKL e comunicar à AT |
| **Resend** — API Key + domínio verificado | resend.com | ⬜ verificar checkal.pt |
| **Anthropic** — API Key | console.anthropic.com | ⬜ obter chave |
| **Hetzner** — servidor CX32 | hetzner.com | ⬜ provisionar |
| Livro de Reclamações Eletrónico | livroreclamacoes.pt | ⬜ registar |

Todas as chaves entram no ficheiro `checkal/.env` (ver `.env.example` para a lista exata). Nenhuma é *bloqueante* para continuar a construir — o código é feito com placeholders e testes.

---

## 7. Próximos passos (por ordem)

**Esta semana (~300 € + consulta jurídica, desbloqueia tudo):**
1. 🚦 **[BLOQUEANTE] Marcar consulta com jurista de proteção de dados** — o RNAL pode ser usado para prospeção? Nada de contacto a frio antes deste "sim" (ver §8 e LEGAL.md §1)
2. Registar **checkal.pt** + variantes de grafia + getcheckal.com
3. Submeter a **marca INPI** (classes 35/42/45)
4. **Amostrar 200 páginas individuais do RNAL** para medir a taxa de preenchimento do bloco do seguro — decide o copy do pilar "seguro" (ver PRODUTO.md §2)
5. Pedir **cotação de seguro de RC profissional / E&O** e arrancar a angariação de 3–5 contabilistas-piloto
6. Reunir as credenciais da secção 6

**Construção (6 fins-de-semana — AUTOMACAO.md §7):**
| Sprint | Entregável |
|---|---|
| FDS 1 | Ingestão dos 308 concelhos + base de dados + diffing |
| FDS 2 | Landing + widget de check gratuito + Stripe/IfThenPay + webhook + InvoiceXpress |
| FDS 3 | **MVP vendável** — onboarding automático + relatório inicial + selo + dashboard |
| FDS 4 | Pipeline DRE + triagem IA + alertas com validação anti-alucinação |
| FDS 5 | Dunning + suporte IA + observabilidade + circuit breaker |
| FDS 6 | Motor de campanhas gatilho→segmento→envio <72h |

**Lançamento (M1):** aproveitar os gatilhos quentes — Porto (1.413 cancelamentos) e Funchal (regulamento novo) — com a checklist legal do LEGAL.md §7 cumprida antes da primeira campanha.

---

## 8. Os riscos (honesto — inclui os que ainda estão abertos)

Detalhe em PLANO-NEGOCIO.md §6. **Dois riscos são bloqueantes e têm de fechar antes do 1.º envio.**

**🚦 Risco 0 — os dois portões antes do lançamento (abertos):**
1. **Reutilizar o RNAL para prospeção pode ser ilegal (RGPD).** "Público" ≠ "reutilizável para marketing" — a CNPD tem sancionado isto. A divisão coletiva/singular resolve a lei do marketing eletrónico, mas **não** a questão a montante do RGPD (limitação de finalidades). → **Parecer de jurista é bloqueante.** Se for negativo, o plano pivota para consent-first puro (widget + parcerias) — foi por isto que reordenámos a aquisição (§3). Não mata o negócio; reordena-o.
2. **Falta seguro de RC profissional.** Se a IA classificar mal e o cliente perder o registo, a limitação de responsabilidade a 49€ pode cair em tribunal (cláusula abusiva B2C). → Apólice E&O antes de escalar + disclaimer em cada alerta ("informação, não aconselhamento").

**Três modos de morte (endereçados, com honestidade sobre o residual):**
1. **A fonte de dados (RNAL) fecha ou degrada.** O "scraper de fallback" **só ajuda contra degradação suave** (rate-limiting, formato); contra fecho duro (autenticação obrigatória), é inútil — enfrenta o mesmo muro. O que realmente salva: o **histórico de snapshots** (ativo insubstituível), o **pilar regulatório DRE** (independente do RNAL) e a **base paga já onboarded**. Estratégia: vender primeiro a inteligência regulatória (durável), tratar a monitorização de estado como o gancho (exposto). **Residual aceite, não mascarado** — aposta consciente num endpoint não-contratualizado.
2. **Mercado finito e a encolher** (1/3 pode desaparecer em 2–3 anos) — re-contacto por pretexto novo, parcerias, subida de preço, expansão para Espanha (fase 2).
3. **Cópia por incumbentes — e o incumbente é o contabilista/gestor de AL, não uma software house.** Quem já tem a relação e os dados do proprietário são eles; juntar "vigilância" é upsell trivial. São a maior ameaça **e** o melhor canal → por isso as parcerias/white-label passaram a **canal primário** (§3), não contingência. Moat adicional: lock-in trienal, rede de selos, histórico de snapshots, velocidade <72h.

---

*Handoff preparado a 05/07/2026. Para o detalhe de qualquer secção, abrir o documento correspondente do dossier (secção 0). Para o estado do código, ver a pasta `checkal/` e o `CLAUDE.md`.*
