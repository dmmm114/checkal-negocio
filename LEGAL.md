# CheckAL — Legal, RGPD & Estrutura

> Parte do dossier CheckAL. A checklist de arranque legal (secção 7 deste ficheiro) é bloqueante para a primeira campanha.

## LEGAL, RGPD & ESTRUTURA

### 1. RGPD e prospeção — o portão jurídico n.º 1 (validar com jurista ANTES do 1.º envio)

**Ponto de partida:** os contactos do RNAL são públicos por imposição legal (art. 10.º do DL 128/2014), mas "público" **não é** "reutilizável para marketing". A publicação tem uma finalidade — transparência do registo — e reutilizá-los para prospeção comercial é tratamento para finalidade **potencialmente incompatível com a original** (princípio da limitação das finalidades, art. 5.º/1/b do RGPD). A [Diretriz 2022/1 da CNPD](https://www.cnpd.pt/umbraco/surface/cnpdDecision/download/121958) confirma que a Lei 41/2004 e o RGPD se aplicam **cumulativamente** ao marketing direto.

> **⚠️ ISTO NÃO ESTÁ RESOLVIDO — é o maior risco jurídico do plano. Não avançar "com o instinto".**
>
> A divisão coletivas/singulares (abaixo) resolve a *Lei 41/2004* (marketing eletrónico), mas **não** resolve, a montante, a questão do RGPD sobre a **legitimidade de reutilizar o dataset**:
> - O email estar acessível não dá, por si, base legal para o usar. O interesse legítimo (art. 6.º/1/f) exige um teste de ponderação onde pesa muito a **expectativa razoável** do titular — e quem tem o email publicado num registo regulatório *não espera* receber marketing de terceiros que o rasparam. Isto enfraquece a ponderação.
> - A CNPD e outras autoridades da UE têm sancionado a reutilização de dados públicos para fins comerciais (o caso **Bisnode**, Polónia, é o paradigma). Uma LIA escrita por nós é auto-interessada — **não substitui** parecer independente.
> - **Decisão: um parecer de jurista de proteção de dados é BLOQUEANTE antes do 1.º envio a frio.** Orçamentar 1 consulta especializada (~150–400€) — barato contra uma coima da CNPD ou a morte reputacional.
>
> **Fallback já decidido se o parecer for negativo (não é improviso):** passar a **consent-first puro** — zero contacto a frio; toda a aquisição entra pelo widget de verificação gratuita (onde o titular *pede* o relatório e consente) + parcerias (leads consentidos, apresentados por um terceiro de confiança) + SEO/ads. O GTM foi reordenado para este ser o **cenário principal**, não o de recurso (ver GTM.md §0).

**Divisão de canais (a mais defensável — mas toda condicionada ao parecer):**

| Contacto no RNAL | É dado pessoal? | Canal | Enquadramento |
|---|---|---|---|
| Coletiva, email **genérico** (geral@, info@, reservas@…) | **Não** (nenhuma pessoa singular identificada) | **Email frio B2B (opt-out)** — o cold mais limpo | RGPD não se aplica ao contacto; Lei 41/2004 art. 13.º-A/2. **Priorizar este segmento.** |
| Coletiva, email de **pessoa identificada** (nome.apelido@…) | Sim | Email frio **só após parecer favorável**; senão consent-first | Interesse legítimo + art. 13.º-A/2, mas com a exposição RGPD acima |
| Singular / ENI (empresário em nome individual) | Sim | **Sem email/SMS a frio** (proibido, art. 13.º-A/1); carta postal só em teste pequeno **e com parecer favorável** | Considerando 47 admite marketing direto como interesse legítimo, mas a reutilização do dataset carece do mesmo parecer |

**Afinação crítica (mantém-se):** o ENI é pessoa singular para a Lei 41/2004 — zero email frio, sem exceção B2B. A carta postal está fora da ePrivacy (que só cobre comunicações eletrónicas), mas **não** fora do RGPD — por isso entra no âmbito do parecer, não como dado "adquirido". A grande novidade prática: **filtrar as coletivas por email genérico dá um canal de cold quase sem risco RGPD** (não há pessoa singular identificada) — é por aí que se começa.

**LIA (avaliação de interesse legítimo) resumida — arquivar como documento interno de 1 página:**
1. *Finalidade:* prospeção de um serviço diretamente relevante para a atividade licenciada do destinatário (proteção do próprio registo AL). Interesse real e lícito.
2. *Necessidade:* dados mínimos (nome, morada do AL) que o próprio Estado publica por força do art. 10.º DL 128/2014; não há meio menos intrusivo de alcançar titulares que não procuram ativamente o serviço.
3. *Ponderação:* o titular sabe (ou deve saber) que os seus dados são públicos por lei; uma carta postal única é o meio menos intrusivo de marketing existente; impacto baixo, expectativa razoável, direito de oposição imediato e gratuito. **Balanço favorável.**

**CheckALs obrigatórias (decididas, implementar antes do 1.º envio):**
- **Dever de informação do art. 14.º RGPD** (dados não recolhidos junto do titular): cumprido na primeira comunicação, que deve dizer preto no branco — *"Obtivemos os seus dados no Registo Nacional de Alojamento Local (RNAL), de acesso público por imposição do art. 10.º do DL n.º 128/2014."*
- **Direito de oposição (art. 21.º/2 RGPD — absoluto em marketing direto):** link de 1 clique no email; na carta, URL curto tipo `checkal.pt/remover` + email de contacto. Sem login, sem fricção.
- **Lista de supressão permanente:** quem se opõe entra numa lista (email/NIF em hash) consultada antes de cada campanha. Conserva-se indefinidamente — é a prova do cumprimento.
- **Prazo de conservação de dados de prospects (decisão): 12 meses após a última campanha sem qualquer interação → eliminação.** Prospects que interagem (verificação gratuita na landing) recomeçam a contagem. Nota: os dados em bruto do RNAL usados para a monitorização dos *clientes* têm outra finalidade e outro prazo (duração do serviço) — separar os dois tratamentos no registo de atividades (art. 30.º RGPD, uma página, obrigatório; a notificação prévia à CNPD já não existe).
- **Telefone/SMS: não usar em prospeção. Decisão.** Ganho marginal, risco máximo (art. 13.º-A/1).

### 2. Informação obrigatória em carta, email e landing — template

**Elementos mínimos em qualquer peça de prospeção:** identificação completa do responsável (denominação, NIPC, morada, email), finalidade do contacto, fonte dos dados, direitos do titular, meio de oposição, referência à política de privacidade completa e ao direito de queixa à CNPD.

**Template da nota RGPD (rodapé de carta e email — usar tal e qual):**

> *Tratamento de dados: Este contacto é-lhe dirigido por [Cosmic Oasis, Lda., NIPC XXXXXXXXX, morada], responsável pelo tratamento, que opera o serviço CheckAL (checkal.pt). Obtivemos o seu nome e contacto no Registo Nacional de Alojamento Local (RNAL), público por imposição do art. 10.º do Decreto-Lei n.º 128/2014, e tratamo-los com fundamento em interesse legítimo, exclusivamente para lhe apresentar um serviço relevante para a sua atividade de Alojamento Local. Tem o direito de aceder, retificar ou apagar os seus dados e de se opor a novos contactos, gratuitamente e a todo o tempo: [checkal.pt/remover] ou privacidade@checkal.pt. Não voltaremos a contactá-lo se o pedir. Se não interagir connosco, eliminamos os seus dados de prospeção no prazo de 12 meses. Política completa: checkal.pt/privacidade. Pode apresentar reclamação à CNPD (cnpd.pt).*

Na landing: política de privacidade completa + termos + banner de cookies (só analytics com consentimento; cookies técnicos isentos).

**Consentimento do lead magnet — redação fechada (decisão).** O formulário da verificação gratuita (n.º RNAL → email) é o ponto onde se converte pessoas singulares em contactáveis por email, e o consentimento tem de cobrir **tudo o que a sequência de nurture faz de facto** — incluindo as peças comerciais (oferta trienal ao D14, newsletter ao D30). Um consentimento limitado a "alertas sobre o meu concelho" não cobre ofertas comerciais e violaria o art. 13.º-A/1 da Lei 41/2004 exatamente no segmento onde a coima não compensa. Regras:
- **Texto da checkbox (usar tal e qual):** *"Aceito receber do CheckAL, por email, alertas sobre o meu Alojamento Local e o meu concelho, bem como informação sobre os serviços e ofertas do CheckAL. Posso retirar este consentimento a qualquer momento, em 1 clique, em qualquer email."*
- **Não pré-preenchida** e **não obrigatória** para receber o mini-relatório: o envio do relatório pedido assenta em diligências pré-contratuais (art. 6.º/1/b RGPD); só a sequência de nurture exige a checkbox. Sem checkbox marcada, o prospect recebe o relatório e mais nada por email.
- **Prova de consentimento guardada por registo:** timestamp, endereço IP, versão exata do texto aceite e identificador do formulário — conservada enquanto o consentimento estiver ativo (é o ónus da prova do art. 7.º/1 RGPD perante a CNPD).
- Todo o email da sequência leva link de anulação do consentimento em 1 clique, que alimenta a lista de supressão da secção 1.

### 3. Risco de confusão com entidade oficial — linhas vermelhas

Este é o risco jurídico-reputacional n.º 1 do modelo "carta à base instalada". O paralelo do mundo das marcas é direto: há anos que circulam cartas-fatura com aparência oficial dirigidas a titulares de marcas, ao ponto de o próprio INPI manter uma página permanente de [combate aos pedidos ilegais de pagamento](https://inpi.justica.gov.pt/Sobre-o-INPI/Combate-aos-pedidos-ilegais-de-pagamento) e emitir [alertas recorrentes](https://inpi.justica.gov.pt/Noticias-do-INPI/Alerta-para-pedidos-fraudulentos-de-pagamento-de-taxas-em-nome-do-INPI); o fenómeno foi documentado na imprensa ([Visão, 2017](https://visao.pt/atualidade/economia/2017-02-26-atencao-a-fraude-no-mundo-dos-registos-e-patentes/)). O enquadramento sancionatório em Portugal: **DL 57/2008 (práticas comerciais desleais)** — a lista negra do art. 8.º proíbe criar a impressão falsa de aprovação ou ligação a organismo público, com coimas aplicadas pela ASAE; acresce responsabilidade civil e, no limite de imitação de documentos oficiais, responsabilidade penal. O Turismo de Portugal, tal como o INPI, publicaria um alerta público com o nome "CheckAL" — morte comercial instantânea.

**Regras de apresentação (obrigatórias em todas as peças):**
- **Disclaimer fixo, visível na primeira dobra da carta e no topo do email:** *"O CheckAL é um serviço privado e independente. Não temos qualquer vínculo ao Turismo de Portugal, I.P., ao RNAL ou a qualquer entidade pública."*
- Identidade visual própria e claramente comercial — **nunca** verde/vermelho institucional, brasões, "República Portuguesa", logos ou tipografia que evoquem o Estado.
- **Nunca usar:** "notificação", "aviso oficial", "intimação", "prazo legal para regularizar", "o seu registo será cancelado se não responder", referências de processo falsas, guias de pagamento, vencimentos de "taxas".
- **Nunca afirmar** que o pagamento ao CheckAL é necessário para manter o registo, o seguro ou qualquer obrigação legal.
- Enquadrar sempre como oferta comercial: "serviço de monitorização", "subscrição", preço claro, "isto é publicidade" implícito na forma.
- O medo vende-se com factos verdadeiros e assinados ("os municípios estão a cancelar registos sem seguro válido — DL 76/2024"), nunca com simulação de autoridade.

### 4. Estrutura societária — decisão: Cosmic Oasis, marca própria

**Decisão: arrancar dentro da Cosmic Oasis, com a marco CheckAL registada no INPI em nome da sociedade. Não constituir nova entidade agora.** Justificação: uma sociedade nova custa ~360€ + contabilidade organizada (~100-150€/mês = 1.200-1.800€/ano) antes do primeiro euro de receita, para um negócio cujo risco de responsabilidade já vai ser contratualmente limitado (secção 5); a Cosmic Oasis já tem contabilidade, conta bancária, Stripe e histórico — time-to-market imediato.

- **IVA art. 53.º:** irrelevante como critério de separação. O [limite de isenção é 15.000€/ano por sujeito passivo](https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/civa_rep/Pages/artigo-53-o-do-civa.aspx) (saída imediata acima de 18.750€ em ano corrente); se a Cosmic Oasis já fatura acima disso com o Radar Marca, o CheckAL nasce logo em regime normal — e criar uma entidade nova só para fracionar volume de negócios é fraude fiscal clássica. Assumir IVA a 23% desde o dia 1: preço 49€ com IVA incluído = 39,84€ líquidos (49/1,23). O pricing já decidido absorve isto.
- **Risco:** contido por T&C com limitação de responsabilidade + a natureza informativa do serviço. Se o negócio escalar para >50k€/ano, aí sim avaliar cisão para uma Lda. dedicada — com a vantagem de a essa data haver métricas para valorizar.
- **Futura venda:** vende-se por *asset deal* — marca INPI + domínio + base de clientes + código + contratos. Para isso, desde o dia 1: contratos celebrados "CheckAL, um serviço Cosmic Oasis, Lda.", faturação em série própria (série "CKL" no software de faturação), receita segregada em centro de custo próprio na contabilidade. Custo desta disciplina: zero. Valor na due diligence: enorme.

### 5. Termos & Condições — cláusulas críticas (fechadas)

1. **Natureza do serviço:** o CheckAL presta um serviço de **informação e monitorização** baseado em fontes públicas (RNAL, Diário da República, regulamentos municipais). **Não presta aconselhamento jurídico** nem substitui consulta a advogado ou solicitador; os alertas interpretados por IA são auxiliares informativos. **Disclaimer obrigatório em CADA alerta e relatório** (não só nos T&C): *"Isto é informação, não aconselhamento jurídico. Confirme com o seu contabilista, advogado ou solicitador antes de agir."* **Nota de atividade reservada:** a "consulta jurídica" (aplicar a lei ao caso concreto de uma pessoa e instruir o que fazer) é ato reservado a advogados/solicitadores (Estatuto da Ordem dos Advogados). O CheckAL fica **deliberadamente** do lado da *informação + remessa para o profissional*: os alertas usam "recomendamos que confirme/verifique", **nunca** "és obrigado a" (salvo citação textual da lei), e nunca se apresentam como substituto de parecer profissional. A camada de IA é construída com esta regra como *guardrail* (ver AUTOMACAO.md §3).
2. **Sem garantia de resultado:** o serviço não garante a manutenção do registo AL, a validade do seguro nem a conformidade legal do cliente — essas obrigações são e permanecem do titular.
3. **Dependência de fontes de terceiros:** a deteção depende da disponibilidade e exatidão das fontes públicas; indisponibilidade da API do Turismo de Portugal ou erro nos dados de origem não constitui incumprimento do CheckAL, que se obriga a diligenciar meios alternativos.
4. **SLA de deteção (compromisso comercial honesto):** *"Alertamos até 7 dias após a alteração se tornar detetável nas fontes públicas que monitorizamos"* — cobre o ciclo de varrimento semanal com folga e não promete tempo real.
5. **Limitação de responsabilidade:** responsabilidade total limitada ao valor pago pelo cliente nos 12 meses anteriores ao facto; exclusão de lucros cessantes e danos indiretos; sem exclusão de dolo/negligência grosseira (seria nula face ao art. 18.º do [DL 446/85](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?artigo_id=837A0022&nid=837&tabela=lei_velhas&pagina=1&ficha=1&nversao=1)). **Aviso honesto (correção pós-revisão):** num contrato de **consumo** (B2C), limitar a ~49€ a responsabilidade por um dano de milhares de euros pode ser considerado **cláusula abusiva/desproporcionada** (art. 18.º/19.º DL 446/85) e ser **afastado por um tribunal**, mesmo para negligência simples. A cláusula reduz o risco; **não o elimina**. A proteção real é o **seguro (cláusula 9) + o desenho do produto** (informar e remeter para o profissional, nunca instruir de forma definitiva — cláusula 1).
6. **Renovação automática — requisitos de validade (decididos):** (a) cláusula destacada e aceite ativamente no checkout ("A subscrição renova automaticamente por igual período; pode cancelar a qualquer momento até à véspera"); (b) **email de aviso 30 dias antes** de cada renovação, com preço, data e link de cancelamento em 1 clique; (c) cancelamento gratuito, pelo mesmo meio da contratação, eficaz até ao dia da renovação — o art. 22.º do DL 446/85 fulmina cláusulas que imponham antecedência excessiva de oposição, e o DL 57/2008 pune omissões enganosas: prazo de oposição curto e aviso claro blindam a renovação. No plano trienal, aviso aos 30 dias do fim dos 3 anos com renovação para novo período anual (não trienal) por defeito — menos atrito, menos contestação.
7. **Livre resolução (DL 24/2014, contrato à distância):** 14 dias com reembolso; como o serviço inicia de imediato, recolher no checkout o pedido expresso de início imediato e reembolsar proporcionalmente se o consumidor resolver dentro do prazo.
8. **Miscelânea obrigatória:** lei portuguesa; indicação de entidade RAL competente + plataforma ODR (Lei 144/2015 — obrigatório indicar, não obriga a aderir); Livro de Reclamações Eletrónico (obrigatório para prestadores de serviços online — registar em livroreclamacoes.pt antes do lançamento); alterações aos T&C com aviso de 30 dias e direito de saída.
9. **Seguro de responsabilidade civil profissional (cláusula nova — lacuna corrigida):** contratar apólice de **RC profissional / E&O (errors & omissions)** antes de escalar a base de clientes. Cenário a cobrir: a IA classifica mal um regulamento, o cliente confia, falha um prazo e perde o registo → responsabilidade civil contratual nossa, com a limitação da cláusula 5 possivelmente afastada em tribunal. Pedir cotação a corretor (Hiscox, Tranquilidade, Fidelidade e outras fazem E&O para serviços digitais); orçamentar **300–800€/ano** no arranque. É o item mais barato contra o risco mais caro do negócio. **Enquanto não houver apólice: manter a base pequena, o disclaimer por alerta impecável (cláusula 1) e a IA em modo conservador.**

### 6. Marca no INPI — registar já, 3 classes

**Decisão: pedido online de marca nacional "CHECKAL" (nominativa) nas classes 35, 42 e 45, submetido antes de qualquer envio público.** A prioridade conta da data do pedido; o funil de cartas só arranca com o pedido submetido.

- **Classe 42:** software como serviço (SaaS), monitorização eletrónica de dados — o produto em si.
- **Classe 45:** serviços de vigilância regulatória/conformidade e serviços de informação jurídica — o coração da proposta ("monitorização de conformidade regulamentar").
- **Classe 35:** compilação e sistematização de informação em bases de dados, serviços de informação comercial — cobre o mini-relatório e o selo.
- **Custo:** taxa online [127,50€ (1.ª classe) + ~33€ por classe adicional](https://justica.gov.pt/Servicos/Registar-marca-nacional) ≈ **~194€ pelas 3 classes** (a [tabela foi atualizada a 1 de julho de 2026](https://inpi.justica.gov.pt/Noticias-do-INPI/Atualizacao-das-taxas-de-propriedade-industrial-a-partir-de-1-de-julho-1) — confirmar o valor exato no ato; orçamentar 210€).
- **Timing:** publicação no BPI → 2 meses de oposição → concessão típica em ~4 meses sem oposição. O lançamento não precisa de esperar pela concessão — precisa do *pedido*.
- **Nota de risco:** "check" é elemento fraco no EUIPO (dezenas de marcas check* nas classes 35/42) — a proteção assenta no composto CHECKAL, distintivo para os serviços em causa. Vizinhos fonéticos identificados (CheckAlt, processamento de cheques EUA; CheckMAL, cibersegurança coreana) são de setores/classes distintos — risco baixo, mas incluir na pesquisa prévia do pedido. Mitigação barata: registar também a **marca mista** (logótipo + "CheckAL ✓ — AL Verificado") quando o selo estiver desenhado (+~194€), porque é o selo que vai circular nos anúncios Airbnb/Booking e é aí que a cópia doeria. Registar as variantes de grafia chekal.pt e checal.pt como redirects (~30€/ano).

### 7. Faturação — stack decidida

**Decisão: Stripe (checkout + cobrança anual/trienal recorrente) → webhook → InvoiceXpress emite fatura-recibo automaticamente e envia por email.** Justificação: o InvoiceXpress é certificado pela AT, tem API madura com integrações Stripe documentadas e replica o padrão que já opera no Radar Marca — zero curva de aprendizagem.

Obrigações cobertas:
- **Software certificado AT:** obrigatório para quem fatura por meios informáticos — o InvoiceXpress cumpre (certificado + QR code + [ATCUD, obrigatório desde 1/1/2023](https://info.portaldasfinancas.gov.pt/pt/apoio_contribuinte/questoes_frequentes/Pages/faqs-00883.aspx)). Comunicar a série "CKL" no portal da AT uma única vez antes da primeira fatura.
- **Comunicação e-Fatura:** [até ao dia 5 do mês seguinte](https://www.centralgestcloud.com/blog/artigo/66/saf-t-faturacao-o-que-e-prazo-de-entrega-e-obrigacoes); o InvoiceXpress comunica por webservice em tempo quase real — obrigação cumprida sem ação manual.
- **Documento:** fatura-recibo B2C no momento do pagamento; NIF opcional do cliente (campo no checkout, "Consumidor final" se vazio); IVA 23% incluído no preço de tabela.
- **Custo:** InvoiceXpress a partir de ~10-15€/mês — a 370 clientes (objetivo 1.500€/mês), é <1% da receita.
- **Dunning:** Stripe Smart Retries + email automático de cartão a expirar (Stripe envia nativamente) — coerente com a operação zero-humanos.

**Checklist de arranque legal (ordem de execução):**
0. **[BLOQUEANTE] Parecer de jurista de proteção de dados** sobre a reutilização do RNAL para prospeção (secção 1). **Nenhum contacto a frio antes deste "sim".**
1. Pedido de marca INPI (~194€).
2. Série de faturação **CKL** + comunicação à AT.
3. Política de privacidade + T&C (**com disclaimer por alerta**, cláusula 1) + LIA + registo de tratamentos (art. 30.º) publicados/arquivados.
4. Registo no Livro de Reclamações Eletrónico.
5. Endpoint `checkal.pt/remover` + lista de supressão funcional + registo de prova de consentimento do lead magnet.
6. **Cotação de seguro de RC profissional / E&O** (cláusula 9) — contratar antes de escalar a base.
7. Só depois, e **conforme o parecer (passo 0)** — primeira campanha, pela **nova ordem de prioridade** (GTM.md §0): (a) widget/consent-first + parcerias; (b) email frio B2B só a coletivas com **email genérico**; (c) carta a singulares só em teste e com parecer favorável.
