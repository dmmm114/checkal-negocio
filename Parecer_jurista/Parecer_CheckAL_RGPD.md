# PARECER JURÍDICO
## Aquisição de clientes e proteção de dados (RGPD) — Projeto CheckAL

| | |
|---|---|
| **Responsável** | Cosmic Oasis, Lda. (operadora do serviço CheckAL) |
| **Data** | 6 de julho de 2026 |
| **Objeto** | Decisão *go / no-go* sobre a estratégia de aquisição de clientes proprietários de Alojamento Local (AL) |
| **Natureza** | Nota de decisão — informação jurídica (ver ressalva final) |

---

## 📋 Síntese executiva

O motor de aquisição deve assentar em **consentimento** (o widget de verificação gratuita) e em **parcerias** — é o único desenho que *elimina* o risco jurídico, em vez de o administrar. O contacto a frio aos dados do RNAL é, na melhor das hipóteses, risco gerido, nunca eliminado.

Por canal, em síntese: **email a pessoas singulares / ENI está vedado** (exige opt-in prévio); o canal frio mais limpo é o email a endereços genéricos de pessoa coletiva (opt-out); a carta postal a singulares é defensável com uma avaliação de interesse legítimo (LIA) documentada, mas não isenta de risco.

**Pressuposto crítico por confirmar:** que o email do titular seja efetivamente um campo de publicação obrigatória por lei. Se não for, a estratégia de contacto a frio fica muito frágil e o texto do Anexo 1 contém uma afirmação falsa. Resolver isto é a primeira tarefa, antes de qualquer decisão.

---

## ⚠️ O pressuposto crítico a confirmar

O briefing afirma que o RNAL publica o email do titular por imposição do **art. 10.º do DL 128/2014**. Este pressuposto deve ser verificado juridicamente antes de tudo o resto — há razões sérias para duvidar dele.

Pela leitura dos campos que o registo torna obrigatórios e públicos, o que aparece é nome/firma, NIF, morada do titular, nome e morada do estabelecimento e, como contacto, tipicamente o **nome, morada e telefone da pessoa a contactar em caso de emergência**. O email do titular não é, de forma evidente, um campo de publicação obrigatória.

As consequências, consoante o cenário:

- **Se o email não for campo público imposto por lei** — a base "público por imposição do art. 10.º", que consta literalmente do Anexo 1, é falsa. Uma nota de informação (art. 14.º RGPD) que invoca uma publicidade legal inexistente é, ela própria, uma violação da lealdade e transparência (art. 5.º/1/a).
- **Se o email vier do campo de contacto de emergência** — está-se a usar um dado recolhido para emergências de hóspedes com finalidade de marketing: violação grosseira da limitação das finalidades.
- **Se vier de uma API que devolve mais do que o portal público** — é preciso saber com que fundamento legal esse dado é disponibilizado.

> **Ação n.º 1:** confirmar, campo a campo, o que a fonte disponibiliza e sob que base legal. Sem isto, a análise de reutilização é especulativa.

---

## ⚖️ Enquadramento jurídico

- **RGPD (Reg. UE 2016/679):** arts. 5.º/1/a e b (lealdade, limitação das finalidades), 6.º/1/f e 6.º/4 (interesse legítimo e teste de compatibilidade), 13.º/14.º (informação), 21.º (oposição, absoluta em marketing direto), 28.º (subcontratantes), 30.º (registo de atividades), 44.º e ss. (transferências internacionais), 83.º (coimas).
- **Lei 58/2019 (execução do RGPD):** moldura nacional; a CNPD desaplicou normas suas por contrariedade ao Direito da UE (Deliberação 2019/494), pelo que o regime sancionatório se rege sobretudo pelo art. 83.º do RGPD.
- **Lei 41/2004 (Privacidade nas Comunicações Eletrónicas):** art. 13.º-A (comunicações não solicitadas — *opt-in* para pessoas singulares; *opt-out* para pessoas coletivas) e art. 13.º-B (listas de consentimento/oposição).
- **Diretriz CNPD 2022/1 (marketing direto):** na reutilização de dados para finalidade diferente da recolha inicial, o princípio da lealdade e as expectativas do titular no momento em que forneceu os dados são preponderantes — diretamente aplicável ao caso.
- **DL 128/2014 (regime do AL), na redação do DL 76/2024:** regime volátil (reverteu medidas do "Mais Habitação"); relevante como risco de negócio e para a base de publicidade da fonte.
- **Lei 10/2024 (Atos de Advogados e Solicitadores):** define consulta jurídica como aconselhamento que consiste na interpretação e aplicação de normas mediante solicitação de terceiro — relevante para a atividade reservada.
- **DL 446/85 (cláusulas contratuais gerais), Lei 24/96 e DL 84/2021:** controlo de cláusulas abusivas em contratos de consumo — relevante para o limite de responsabilidade.

---

## 🎯 Tabela de decisão por canal

| # | Canal de contacto | Pode? | Condição / ressalva essencial |
|---|---|---|---|
| 1 | **Widget de verificação (consentimento)** | ✅ **SIM** | Consentimento válido (art. 4.º/11 e 7.º RGPD): checkbox não pré-preenchida e não condicionada ao relatório. Falta garantir identidade do responsável + link à política adjacentes, e registar prova do consentimento (timestamp, versão do texto). Idealmente separar "alertas do serviço" de "ofertas comerciais". |
| 2 | **Email frio a coletiva — endereço genérico** (`geral@`) | ✅ **SIM, com condições** | Se o endereço não identifica pessoa singular, não é dado pessoal e o RGPD não se aplica ao contacto. Fica só a Lei 41/2004: identificação do remetente + opt-out em cada mensagem + honrar oposição + lista de supressão. Canal frio mais limpo. |
| 3 | **Email frio a coletiva — pessoa identificada** (`nome.apelido@`) | 🟡 **COM CONDIÇÕES (risco moderado)** | É dado pessoal → RGPD aplica-se. Defensável como B2B opt-out se: LIA robusta + nota art. 14.º na 1.ª mensagem + opt-out imediato + serviço relevante à atividade. Fragilidade real: expectativa razoável. Zona cinzenta — não é "limpo". |
| 4 | **Carta postal a pessoa singular / ENI** | 🟡 **COM CONDIÇÕES** | Fora da Lei 41/2004; só RGPD. Interesse legítimo (art. 6.º/1/f) com LIA documentada + nota art. 14.º + direito de oposição (art. 21.º/2, absoluto). Canal mais defensável para chegar a singulares. Não é 100% seguro. |
| 5 | **Email frio a pessoa singular / ENI** | 🔴 **NÃO** | Lei 41/2004, art. 13.º-A, exige opt-in prévio. ENI = pessoa singular. É o principal motor de queixas à CNPD. Não fazer. |

**Arrancar amanhã:** ligar já o canal 1 (widget) e, resolvido o pressuposto da fonte, o canal 2 (`geral@`, opt-out) como acelerador. A carta postal (4) fica para depois de existir LIA escrita e Anexo 1 corrigido. Email a singulares/ENI (5): nunca.

---

## 💡 Recomendação estratégica

**Motor primário: consentimento + parcerias.** É o caminho que permite "dormir descansado". Contabilistas, gestores de AL e associações do setor trazem clientes já introduzidos ou consentidos; o widget capta quem procura o serviço. Complementar com conteúdo/SEO/anúncios que drenam tráfego para o widget — zero reutilização de dados pessoais de terceiros. Isto elimina o risco na raiz.

**Contacto a frio: exceção bem-documentada, não a espinha dorsal.** A CNPD é explícita: na reutilização, a expectativa razoável do titular é decisiva, e quem publica um contacto num registo regulatório não espera marketing de terceiros. Isso enfraquece o interesse legítimo — não o mata, mas obriga a limitar os canais frios aos de menor exposição (`geral@` em opt-out; carta postal a singulares com LIA).

---

## ⚠️ Matriz de riscos

- 🔴 **CRÍTICO (imediato).** Email frio a pessoas singulares/ENI sem opt-in — violação do art. 13.º-A da Lei 41/2004; é o principal motor de queixas à CNPD. Moldura de coima: art. 83.º RGPD (até 20 M€ / 4% do volume de negócios no escalão grave).
- 🔴 **CRÍTICO (imediato).** Invocar no Anexo 1 uma base de publicidade legal inexistente, ou usar dados do campo de emergência para marketing — violação de lealdade e de limitação das finalidades.
- 🟡 **MODERADO (6–24 meses).** Email a pessoa identificada em endereço de pessoa coletiva e carta postal a singulares assentes em interesse legítimo com LIA fraca: expostos a queixa e a ordem de cessação; desfecho típico para PME cooperante em 1.ª infração é advertência/coima modesta, mas o risco é real.
- 🟡 **MODERADO.** Ausência de contratos de subcontratação (art. 28.º) e de mecanismo de transferência internacional (art. 44.º e ss.) para fornecedores de email/IA fora do EEE.
- 🟡 **MODERADO (contínuo).** Produto a emitir recomendações individualizadas pode resvalar para consulta jurídica reservada (Lei 10/2024).
- 🟢 **ATENÇÃO.** Registo de atividades (art. 30.º) em falta; possível DPIA por larga escala; conservação de 12 meses no limite superior; cláusula de limitação de responsabilidade provavelmente abusiva; volatilidade regulatória do próprio setor do AL.

---

## 🔎 Respostas às questões específicas

### Limitação das finalidades e novo responsável (Q2)
Sendo um responsável novo que obtém dados de fonte pública, o eixo é ter **base própria no art. 6.º + lealdade + expectativa razoável + art. 14.º**. O teste de compatibilidade do art. 6.º/4 foi desenhado sobretudo para o responsável original; não vos isenta, mas a obrigação central é a base legal própria e a lealdade. Não se agarrem à ideia de que "não somos o Turismo de Portugal, logo o art. 5.º/1/b não nos apanha" — apanha, por via da lealdade.

### Nota de informação — Anexo 1 (Q7)
Perto, mas **incompleto**. Faltam: categorias de dados tratados; identificação do EPD (se existir); categorias de destinatários/subcontratantes; transferências internacionais (se aplicável). E, crítico, a frase "público por imposição do art. 10.º" tem de ser verdadeira, senão sai. O timing (informar na 1.ª comunicação) está correto. Nenhuma isenção do art. 14.º/5 vos serve: como contactam diretamente, têm de informar nesse contacto.

### Consentimento do funil — Anexo 2 (Q8)
Válido no essencial (não pré-preenchido, não condicionado ao relatório). Melhorar: separar "alertas do serviço" de "ofertas comerciais" (granularidade — a CNPD rejeita consentimentos globais para finalidades distintas); garantir identidade do responsável + link à política junto ao checkbox; guardar prova (log, versão do texto, nota informativa).

### Prazo de conservação (Q9)
12 meses é defensável mas está no limite superior; para quem nunca interage, 6 meses é mais seguro. A **lista de supressão** de quem fez opt-out conserva-se separadamente e por mais tempo — é o que permite provar que a oposição é honrada.

### Postura da CNPD e risco real (Q10)
As queixas por marketing não solicitado aumentaram muito, sobretudo de entidades com quem os titulares não têm relação; a CNPD emitiu diretriz para enquadrar como decidirá as contraordenações ao art. 13.º-A conjugado com o RGPD. Moldura: art. 83.º RGPD. Avaliação realista: atuação sobretudo por queixa; para PME cooperante em 1.ª infração, ordem de cessação + coima modesta é o desfecho típico — mas o canal email-a-singulares é o de maior exposição.

### Atividade reservada (Q11)
Risco real. A Lei 10/2024 reserva a consulta jurídica a advogados e solicitadores. "Isto afeta o teu AL, recomendamos que faças X" é fronteiriço: informação genérica e monitorização de estado ficam do lado seguro; conclusões jurídicas individualizadas sobre a situação concreta do cliente, não. Manter linguagem condicional e genérica, incluir disclaimers ("informação, não aconselhamento jurídico"), não redigir peças nem representar. Avaliação definitiva depende do exemplo de alerta (Anexo 3), ainda não fornecido.

### Limite de responsabilidade a 49 € (Q12)
A vossa leitura está certa. Num contrato de consumo, um teto de responsabilidade a 49 € é muito provavelmente **abusivo** (DL 446/85, arts. 18.º e 19.º; Lei 24/96; DL 84/2021) — não pode excluir dolo, negligência grave ou danos pessoais. A cláusula pode subsistir para a fatia validamente limitável (negligência leve, dano patrimonial, proporcional), mas a proteção real é o **seguro de RC profissional** + descrição honesta do serviço como ferramenta informativa, não garantia de conformidade.

---

## 🗓️ Plano de ação — próximas 4 semanas

1. **Semana 1** — resolver o pressuposto da fonte (o que é público e sob que base). Corrigir o Anexo 1. Montar o registo de atividades de tratamento (art. 30.º). Decidir sobre EPD.
2. **Semana 2** — finalizar o widget com Anexos 1 e 2 corrigidos, política de privacidade e mecanismo de prova de consentimento. Ligar o motor de consentimento.
3. **Semana 3** — contratos de subcontratação (art. 28.º) com todos os processadores; resolver transferências internacionais (email/IA fora do EEE); iniciar parcerias.
4. **Semana 4** — só então, se quiserem cold como acelerador: escrever a LIA e ligar apenas `geral@` (opt-out) e/ou carta postal a singulares com nota art. 14.º. Email a singulares fica desligado.

---

## 🔮 Cenários a antecipar

- **Queixa à CNPD sobre email frio:** provável se o canal 5 for ligado. Preparar já a lista de supressão e a prova de opt-out/opt-in para demonstrar diligência.
- **Pedido de acesso/oposição (arts. 15.º/21.º):** a oposição a marketing é absoluta — o processo de cessação imediata tem de estar operacional desde o dia 1.
- **Alteração do regime do AL:** o setor mudou pelo DL 76/2024 e pode voltar a mudar; a fonte de dados e a proposta de valor do produto dependem de um quadro instável.
- **Fornecedor de IA/email fora do EEE:** nunca enviar dados pessoais de prospects para uma API de IA sem mecanismo de transferência resolvido.

---

## ❓ Questões a clarificar

1. Confirmação documental de que campos o RNAL publica e com que base legal (pressuposto crítico).
2. Exemplo real de alerta enviado ao cliente (Anexo 3), para fechar a análise da atividade reservada.
3. Que fornecedores de email e de IA serão usados e onde estão sediados (para transferências internacionais e contratos art. 28.º).

---

## 📚 Ressalva

*Este documento constitui informação e análise jurídica de decisão, não um parecer formal assinado por advogado inscrito na Ordem. Três pontos exigem validação de advogado/EPD antes de produção: (i) a base legal da fonte do email; (ii) o mecanismo de transferência internacional para os fornecedores de email/IA; (iii) a fronteira da atividade reservada, à luz do Anexo 3. A afirmação de publicidade legal no Anexo 1 não deve ser publicada sem confirmação documental.*
