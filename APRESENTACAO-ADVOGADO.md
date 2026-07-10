# Pedido de validação jurídica — Projeto CheckAL
**Cosmic Oasis, Lda.** · NIPC [NIPC] · [morada] · privacidade@checkal.pt

**Para:** [Dr.(a). / nome — ver nota sobre o destinatário no fim]
**De:** [Diogo Mendes], em representação da Cosmic Oasis, Lda.
**Data:** [data]
**Assunto:** Validação formal de 3 pontos + revisão de 5 minutas — RGPD e aquisição de clientes (serviço CheckAL)

---

Exmo.(a) Senhor(a) Dr.(a),

Na sequência da nota de decisão jurídica que nos facultou, vimos pedir a **validação formal** de três pontos aí deixados em aberto e a **revisão de cinco minutas** que preparámos. Pretendemos sair com **uma decisão executável** — *"podem fazer X, desta forma, com estas salvaguardas; evitem Y"* — e a documentação pronta.

Nota de accountability: **desativámos em código qualquer contacto comercial a frio** (interruptor `CHECKAL_PARECER_RGPD_OK`, hoje desligado). O nosso motor de aquisição é **consentimento** (formulário de verificação gratuita, onde o próprio titular consente) + **parcerias**; esse caminho arranca independentemente desta consulta. Em anexo seguem todas as minutas e o Anexo 3.

---

## 1. Enquadramento factual (mínimo)
O CheckAL é um serviço privado de subscrição (49 €/ano) que, por cada Alojamento Local (AL), monitoriza o estado do registo no RNAL, a validade do seguro obrigatório e os regulamentos municipais, enviando alertas. Sem vínculo ao Estado. Os contactos provêm do RNAL (Turismo de Portugal), público e também acessível por webservice. Os registos distinguem titular **coletiva** de **singular/ENI**.

**Dimensão da fatia endereçável a frio (já calculada — o "Passo 0"):** de ~72.900 registos amostrados (≈60% do universo nacional), a fatia **coletiva com email genérico** (`geral@`, `info@`, `reservas@`) é de **7.779 registos ≈ 1.914 empresas distintas (10,7%)**. É este — e só este — o universo do canal frio que ponderamos.

---

## 2. Os três pontos para validação formal

### (i) Base legal da fonte do email — *já verificada por nós; pedimos contra-verificação*
Verificámos o texto consolidado (PGDL, versão vigente): o **art. 10.º, n.º 5 do DL 128/2014** (na redação do DL 76/2024) determina que o Turismo de Portugal disponibiliza publicamente, além do n.º 1, o *"endereço eletrónico do titular da exploração"* e a *validade do seguro obrigatório (art. 13.º-A)*. Pedimos:
- **contra-verificação** dessa redação e que o webservice `list_RNAL` não exponha mais do que o site público ("nomeadamente" é enumeração exemplificativa);
- verificação dos **termos de licença/reutilização** do webservice (regime de dados abertos, **Lei 68/2021**, + condições do TdP) — uma violação aí é problema contratual/administrativo autónomo do RGPD.

**Importante (desacoplamento):** este ponto **não é o portão do canal `geral@`**. A licitude do email frio a pessoa coletiva assenta na **Lei 41/2004, art. 13.º-A (opt-out coletivas) + art. 13.º-B (listas/DGC)** + consulta à lista da DGC + identificação do remetente e opt-out em cada mensagem — não na fonte do endereço. O ponto (i) releva sobretudo para a **redação da nota do art. 14.º** e para qualquer tratamento que toque dados de **singulares**. E mantemos presente: **publicação obrigatória ≠ licença de reutilização** — a análise de compatibilidade de finalidades (arts. 5.º/1/b e 6.º/4) mantém-se para singulares/ENI (o próprio art. 10.º/3 remete para a Lei 58/2019).

### (ii) Transferências internacionais e subcontratação (arts. 28.º e 44.º e ss.)
Subcontratantes fora do EEE: **Resend** (email, EUA), **Anthropic** (IA dos alertas, EUA), **Stripe** (pagamentos, EUA/IE — via Stripe Payments Europe, IE). No EEE: TOConline (PT), IfThenPay (PT), Hetzner (DE).

**Correção que assumimos face à nota anterior:** a IA **trata dados pessoais**. Quando o titular é **ENI/singular**, os "dados do estabelecimento" (nº RNAL — identificador único —, morada, validade do seguro) são dados pessoais de pessoa identificável; remover o nome é pseudonimização, não anonimização. Logo, **a Anthropic é subcontratante de dados pessoais hoje**, exigindo DPA + mecanismo de transferência **independentemente da estratégia de aquisição**. Pedimos que valide:
- o **mecanismo do Cap. V** por prestador (SCCs 2021 e/ou Data Privacy Framework, com verificação **datada** das listagens ativas para Stripe/Resend/Anthropic);
- que as **SCCs de 2021 já incorporam o art. 28.º** (dispensando contrato separado com os prestadores US que tenham DPA adequado) — a nossa minuta de subcontratação destina-se apenas às relações onde ditamos o papel;
- a **dupla qualificação** provável de **Stripe** e **IfThenPay** (subcontratantes + responsáveis autónomos nas obrigações próprias de AML/KYC), a refletir no registo do art. 30.º;
- em alternativa que ponderamos: correr o modelo Claude via **Amazon Bedrock, região Frankfurt (eu-central-1)**, mantendo a inferência **na UE** e eliminando a questão do Cap. V para a componente de IA. Merece a sua opinião custo/benefício vs. manter EUA com SCCs+TIA.

### (iii) Fronteira da atividade reservada (Lei n.º 10/2024)
A Lei 10/2024 (que revogou a Lei 49/2004) reserva a **consulta jurídica** — "interpretação e aplicação de normas jurídicas mediante solicitação de terceiro" — a advogados/solicitadores. Reconhecemos que a definição está **próxima** do que o produto faz. A nossa defesa assenta em três distinções que garantimos no produto real:
- **facto, não conselho:** monitorizar estado/seguro/publicação e **citar a fonte oficial** é informação; concluir juridicamente pela situação do cliente ("estás em incumprimento", "tens de alterar X") não;
- **sinalização genérica, não aplicação individualizada;**
- **encaminhamento, não prescrição** (só remetemos para a fonte oficial ou para um profissional).

Como os alertas são **gerados por IA**, um template correto não basta. Implementámos uma **defesa em camadas** (e não afirmamos um filtro perfeito — a defesa é a soma delas): **(1)** um **template restritivo** que instrui o modelo a citar a fonte e a não concluir juridicamente; **(2)** um **filtro automático** que deteta os padrões prescritivos/individualizados **mais comuns** — deveres, prazos e valores dirigidos ao cliente ("tens de…", "para efetuares…", "tens N dias para…") — e os **substitui por um formato factual de recurso**, atribuindo os factos à fonte ("segundo o regulamento, os titulares dispõem de…"); **(3)** **amostragem humana periódica**; **(4)** **versionamento dos templates** como prova. Anexamos um **alerta real** (Anexo 3) para validar a linguagem concreta.

---

## 3. As cinco minutas a rever/validar
| # | Documento | O que validar |
|---|---|---|
| 1 | Política de Privacidade | finalidades/bases por canal, direitos (oposição absoluta art. 21.º/2), conservação 6 m, transferências, CNPD |
| 2 | Termos & Condições | serviço = ferramenta informativa (não garantia/aconselhamento); **teto de responsabilidade = total pago nos 24 meses anteriores** (a perna do limite da apólice acrescenta-se quando a E&O for contratada); sem excluir dolo/negligência grave/danos a pessoas; cláusulas de **alterações** e de **suspensão por falta de pagamento** |
| 3 | Registo de Atividades (art. 30.º) | entradas por atividade; dupla qualificação Stripe/IfThenPay; IA como tratamento de dados pessoais de clientes ENI |
| 4 | LIA — cold `geral@` | **validar para preservar a opção (ativação não iminente):** o teste de equilíbrio aguenta? as salvaguardas — universo ~1.914 empresas, cadência 1 apresentação + 1 follow-up, cruzamento DGC — são suficientes? |
| 5 | Nota de Informação (art. 14.º) | conteúdo mínimo; base do art. 10.º só após (i) |

---

## 4. Decisões em que pedimos aconselhamento
- **EPD/DPO:** propomos **não designar formalmente** (defensável por não ser "grande escala": ~centenas/poucos milhares de subscritores), nomeando responsável interno + apoio externo, e **documentando a avaliação + gatilhos de reavaliação** (ingestão da base RNAL completa; N mil subscritores; novas categorias). Confirma esta posição?
- **Conservação:** **6 meses** para prospects sem interação; lista de supressão à parte, minimizada, sem prazo (art. 21.º). Confirma?
- **Limitação de responsabilidade + E&O:** aceitamos que um cap de 49 € seria derrubado; o teto fica no **total pago nos 24 meses anteriores** e **não prometemos, para já, um seguro que ainda não temos**. Ao contratar a **E&O**, acrescentaremos a perna do limite por sinistro — e pedimos desde já orientação sobre a apólice: **exclusões de conteúdo gerado por IA** (decisivo), *claims-made* + data retroativa, **sinistros em série**, território Portugal, custos de defesa dentro/fora do limite.
- **Estratégia:** confirmamos **consentimento + parcerias** como motor. O `geral@` (opt-out) fica como **opção a preservar** — uma eventual **campanha única e curada** às ~1.914 empresas, semi-manual e depois desligada; **ativação não iminente**. Pedimos que valide a LIA para **preservar essa opção**, não para a ativar já.

**A nossa leitura por canal (para confirmar/corrigir):**
| Canal | Leitura |
|---|---|
| Formulário de verificação (consentimento) | **Pode** (consentimento granular, com prova) |
| Frio a coletiva `geral@` (opt-out) | **Pode**, sob Lei 41/2004 + DGC + opt-out por mensagem (o ponto (i) reforça, não é o portão) |
| Frio a coletiva, pessoa identificada | **Excluído por desenho** |
| **Carta postal a singular/ENI** | **Provavelmente inviável:** o art. 10.º/5 publica o *email*, não a *morada* do titular; a morada pública é a do **estabelecimento**, raramente a residência |
| Frio a singular/ENI | **Não** (opt-in, art. 13.º-A) |

---

## 5. Anexos (o dossier)
1. Nota de decisão jurídica recebida · 2. Briefing factual · 3. Documento de decisões implementadas · 4. As 5 minutas da secção 3 · 5. **Anexo 3 — alerta real** (para 2(iii)).

## 6. O que só a Cosmic Oasis fornece
**NIPC** e **morada** da sociedade (`[NIPC]`/`[morada]` nas minutas).

## 7. Resultado pretendido, destinatário e honorários
Pretendemos: confirmação/correção de 2(i)–(iii); as 5 minutas validadas; aconselhamento nas decisões da secção 4, sob a forma de **recomendação clara**. **Nota sobre o destinatário:** o ponto (ii) exige conforto em **proteção de dados/transferências**; o ponto (iii) exige conforto em **deontologia da Ordem** — pode justificar dois pareceres. Agradecemos indicação de honorários para (i) esta validação e (ii) a eventual finalização/assinatura.

Com os melhores cumprimentos,
[Diogo Mendes] — Cosmic Oasis, Lda.

> *Redações legais verificadas na versão consolidada (PGDL) à data; para citação externa, confirmar no DRE.*
