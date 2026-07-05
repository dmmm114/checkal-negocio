# Briefing para consulta jurídica — Proteção de dados (RGPD) e prospeção
### Projeto CheckAL · Cosmic Oasis, Lda.

> **Para:** [Jurista/Advogado de proteção de dados]
> **De:** [Diogo Mendes], Cosmic Oasis, Lda., NIPC [—]
> **Objetivo:** decisão **go / no-go** sobre uma estratégia de aquisição de clientes, antes de a executar. Não procuramos um parecer académico extenso — procuramos **respostas objetivas, por canal, que nos digam o que podemos e não podemos fazer, e sob que condições.**
> **O que mais valorizamos:** não queremos só que nos diga o que está mal — queremos que nos **aponte a melhor alternativa e a decisão mais segura** para atingirmos o objetivo (angariar clientes proprietários de AL) **sem problemas jurídicos**. Preferimos um "não faça X, faça Y assim" a um "X é arriscado". Se houver um caminho 100% seguro, mesmo que mais lento, é esse que queremos conhecer e adotar.
> **Formato de resposta ideal:** a **recomendação** da Secção D-bis + a **tabela de decisão** da Secção D. Se preencher esses dois, resolve o essencial.

---

## A. Contexto factual (o mínimo para responder com precisão)

1. **O que é o CheckAL.** Um serviço de subscrição (49€/ano) que monitoriza, para cada proprietário de Alojamento Local (AL), o estado do seu registo, a validade do seguro obrigatório e os regulamentos municipais aplicáveis, e envia alertas quando algo o afeta. É um serviço privado, sem qualquer vínculo ao Estado.

2. **A fonte dos dados.** O Registo Nacional de Alojamento Local (RNAL), do Turismo de Portugal, é público e disponibiliza — por **imposição do art. 10.º do DL n.º 128/2014** — a identificação dos titulares de exploração e os seus contactos (nome, NIF, telefone e **email**). Existe uma **API pública** que devolve estes dados por concelho. A base tem >120.000 registos ativos; cada registo indica se o titular é **"pessoa coletiva"** ou **"pessoa singular (empresário em nome individual)"**.

3. **O uso que queremos dar-lhe.** Usar esses contactos para **prospeção comercial** do CheckAL — ou seja, contactar os titulares (por email e/ou carta) a apresentar o serviço. É este o ponto que queremos validar antes de agir.

4. **Distinção que nos parece relevante.** Muitos registos de "pessoa coletiva" têm um **email genérico** (ex.: `geral@empresa.pt`, `info@...`, `reservas@...`), que não identifica nenhuma pessoa singular. Outros têm o email de uma pessoa identificada. Todos os "pessoa singular / ENI" são, por definição, dados de uma pessoa física.

5. **Funil alternativo que já temos.** Uma landing page com uma **verificação gratuita**: o proprietário insere o seu nº de registo, recebe um mini-relatório e **dá consentimento** para receber comunicações. Aqui é o próprio que nos procura e consente.

---

## B. A nossa leitura (para confirmar, corrigir ou completar)

Fizemos o trabalho de casa. Diga-nos onde estamos certos e onde estamos errados:

1. **"Público" não é "reutilizável para marketing".** Sabemos que o facto de o dado ser público por lei (transparência do registo) **não** nos dá, por si só, base legal para o reutilizar para prospeção — é um novo tratamento, com nova finalidade, que exige fundamento próprio no art. 6.º do RGPD e respeito pelo princípio da limitação das finalidades (art. 5.º/1/b).

2. **Base legal que pretendíamos invocar:** interesse legítimo (art. 6.º/1/f), com uma avaliação de interesse legítimo (LIA) documentada. Temos dúvidas se resiste, dado o peso da **expectativa razoável** do titular (quem publica o email num registo regulatório não espera marketing de terceiros).

3. **ePrivacy (Lei 41/2004, art. 13.º-A):** a nossa leitura é que comunicações eletrónicas não solicitadas exigem **opt-in prévio para pessoas singulares** (incl. ENI) e admitem **opt-out para pessoas coletivas**. A carta postal fica fora desta lei (mas não do RGPD).

4. **Divisão de canais que desenhámos** (a validar):
   - Coletiva com email genérico → email frio (opt-out);
   - Coletiva com email de pessoa identificada → dúvida;
   - Singular / ENI → sem email frio; eventualmente só carta postal.

---

## C. As questões concretas (é aqui que precisamos de si)

**Bloco 1 — a questão que decide tudo:**

1. **Podemos, ou não, reutilizar os contactos do RNAL para prospeção comercial do CheckAL?** Se a resposta for "depende", **de que depende** — em termos operacionais que possamos implementar?

2. O **princípio da limitação das finalidades (art. 5.º/1/b)** e o teste de compatibilidade (art. 6.º/4) aplicam-se a nós, sendo nós um **responsável de tratamento diferente** daquele que recolheu/publicou os dados (o Turismo de Portugal)? Ou, para um novo responsável que obtém dados de fonte pública, a questão resume-se a ter base legal própria (art. 6.º) + lealdade?

**Bloco 2 — por canal:**

3. **Email genérico de pessoa coletiva** (`geral@empresa.pt`): é sequer **dado pessoal** na aceção do RGPD? Se não for, confirmamos que o RGPD não se aplica a esse contacto e que o único enquadramento é a Lei 41/2004 (opt-out, pessoa coletiva)?

4. **Email de pessoa identificada em registo de pessoa coletiva** (`nome.apelido@empresa.pt`): podemos fazer email frio B2B com opt-out, ou o facto de identificar uma pessoa singular puxa-o para o regime mais restritivo?

5. **Carta postal a pessoa singular / ENI:** estando fora da Lei 41/2004, o interesse legítimo (art. 6.º/1/f) é suficiente para prospeção postal, **apesar** da questão da reutilização/finalidade? Ou o problema do Bloco 1 contamina também a carta?

6. **ENI (empresário em nome individual):** confirmamos que, para a Lei 41/2004, é tratado como **pessoa singular** (opt-in para email), independentemente de ter atividade aberta e NIF?

**Bloco 3 — conformidade e risco:**

7. **Dever de informação (art. 14.º)** — dados não recolhidos junto do titular: o texto que redigimos (Anexo 1) cumpre? Timing correto (na 1.ª comunicação)? Há alguma isenção do art. 14.º/5 aplicável?

8. **Consentimento do funil de verificação gratuita:** o texto da checkbox (Anexo 2) é válido como consentimento livre, específico e informado para a sequência de emails comerciais que se segue? Alguma correção?

9. **Prazo de conservação** dos dados de prospects que não interagem: propomos **12 meses**. Razoável?

10. **Postura da CNPD / risco real:** há deliberações recentes da CNPD (ou casos conhecidos na UE) sobre **reutilização de registos públicos para marketing** que devamos conhecer? Numa avaliação realista, qual é a **probabilidade de atuação** perante uma queixa e a **ordem de grandeza da coima**?

**Bloco 4 — secundário (pode ser 2.ª consulta, não é bloqueante):**

11. **Risco de atividade reservada:** o nosso produto interpreta regulamentos para o caso concreto do cliente ("isto afeta o teu AL; recomendamos que faças X"). Há risco de isto ser considerado **consulta jurídica reservada** a advogados/solicitadores (Estatuto da Ordem dos Advogados)? Que linguagem/limites nos mantêm do lado da *informação* e não do *aconselhamento*?

12. **Termos & Condições / responsabilidade:** confirmamos que uma cláusula que limita a nossa responsabilidade ao valor pago (~49€) pode ser tida como **abusiva** num contrato de consumo (DL 446/85), sendo o seguro de RC profissional a proteção real?

---

## D. Tabela de decisão (o formato de resposta que precisamos)

Se preencher isto, temos o go/no-go que nos falta. Para cada canal: **pode / não pode / pode com condições** + a condição essencial.

| # | Canal de contacto | Pode? | Condição / ressalva essencial |
|---|---|---|---|
| 1 | **Widget de verificação gratuita** (o titular pede e consente) | | |
| 2 | **Email frio a coletiva, email genérico** (`geral@`) | | |
| 3 | **Email frio a coletiva, email de pessoa identificada** | | |
| 4 | **Carta postal a pessoa singular / ENI** | | |
| 5 | **Email frio a pessoa singular / ENI** (assumimos que **não**) | | |

**Pergunta-resumo:** se tivéssemos de arrancar **amanhã** apenas com os canais claramente seguros, quais ligava sem hesitar, e que texto/salvaguarda exigia em cada um?

---

## D-bis. A recomendação (a pergunta mais importante do briefing)

Acima de todas as respostas por canal, é isto que mais precisamos de si:

1. **Qual é a estratégia de aquisição mais segura que ainda nos permite atingir o objetivo?** Assumindo que queremos angariar proprietários de AL de forma sustentável, **desenhe-nos o caminho que elimina (ou reduz ao mínimo defensável) o risco jurídico** — mesmo que seja mais lento ou mais caro. Preferimos o caminho certo ao caminho rápido.

2. **Se o contacto a frio ao RNAL for problemático, qual é a alternativa que recomenda?** Ex.: assentar tudo em consentimento (o nosso widget de verificação gratuita) e em parcerias com contabilistas/gestores que trazem clientes já consentidos — é este o desenho que nos aconselha? Vê outro melhor?

3. **O que nos falta ver?** Aponte qualquer risco, obrigação ou boa prática que **não** esteja neste briefing e que um profissional experiente sinalizaria (registo de tratamentos, DPO, encarregado de proteção de dados, transferências, subcontratantes de IA/email, etc.).

4. **Dê-nos a decisão, não só as opções.** Se estivesse no nosso lugar e quisesse dormir descansado, **que faria exatamente** nas próximas 4 semanas, por que ordem?

O resultado que procuramos desta consulta é uma frase que possamos executar: *"Podem fazer isto, desta forma, com estas salvaguardas — e devem evitar aquilo."*

---

## E. Anexos para validação

**Anexo 1 — Nota de informação RGPD (rodapé de carta/email que propomos):**
> *Tratamento de dados: Este contacto é-lhe dirigido pela Cosmic Oasis, Lda. (NIPC [—], [morada]), responsável pelo tratamento, que opera o serviço CheckAL. Obtivemos o seu nome e contacto no Registo Nacional de Alojamento Local (RNAL), público por imposição do art. 10.º do DL n.º 128/2014, e tratamo-los com fundamento em interesse legítimo, exclusivamente para lhe apresentar um serviço relevante para a sua atividade de Alojamento Local. Pode aceder, retificar, apagar e opor-se a novos contactos, gratuitamente e a todo o tempo, em checkal.pt/remover ou privacidade@checkal.pt. Se não interagir, eliminamos os seus dados de prospeção em 12 meses. Política completa: checkal.pt/privacidade. Pode reclamar à CNPD (cnpd.pt).*

**Anexo 2 — Texto da checkbox de consentimento (funil de verificação gratuita):**
> *"Aceito receber do CheckAL, por email, alertas sobre o meu Alojamento Local e o meu concelho, bem como informação sobre os serviços e ofertas do CheckAL. Posso retirar este consentimento a qualquer momento, em 1 clique, em qualquer email."* (não pré-preenchida; não obrigatória para receber o relatório)

**Anexo 3 — Exemplo de alerta enviado ao cliente** (para a questão 11): *[anexar 1 email de alerta real do produto, com a estrutura "Afeta o teu AL? Sim/Não · porquê · o que fazer · fonte"]*

---

*Notas práticas: (a) o que nos trava neste momento é o **Bloco 1 + a Tabela D** — se só houver tempo para isso, chega para decidirmos; (b) se concluir que a estratégia de contacto a frio não é viável, já temos um plano alternativo assente 100% em consentimento (o widget) e parcerias — nesse caso, a pergunta passa a ser apenas "o funil de consentimento (Anexos 1 e 2) está impecável?"; (c) agradecemos indicação de honorários para (i) esta consulta de decisão e (ii) eventual redação da política de privacidade + T&C.*
