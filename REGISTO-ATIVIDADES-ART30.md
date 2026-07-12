# Registo de Atividades de Tratamento (art. 30.º RGPD) — CheckAL

> **MINUTA — a validar por advogado/EPD antes de publicar.**
>
> Registo das atividades de tratamento sob responsabilidade da **Cosmic Oasis, Lda.**
> (operadora do serviço CheckAL), nos termos do art. 30.º, n.º 1, do RGPD
> (Reg. UE 2016/679). Documento interno — não se publica; exibe-se à CNPD a pedido.
> Alinhado com o `Parecer_jurista/Parecer_CheckAL_RGPD.md` (6/7/2026) e com
> `LEGAL-PARECER-DECISOES.md`.
>
> **Estado:** rascunho de execução. A atividade **F (prospeção a frio)** está
> **NÃO ATIVA / bloqueada por desenho** (`CHECKAL_PARECER_RGPD_OK=False`) e só entra
> em produção depois de cumpridos os pré-requisitos do parecer (LIA arquivada, base
> legal da fonte confirmada, contratos art. 28.º e transferências resolvidas).

---

## 0. Identificação do responsável e contactos

| Campo | Valor |
|---|---|
| **Responsável pelo tratamento** (art. 4.º/7) | Cosmic Oasis, Lda. |
| **NIPC** | `[NIPC]` |
| **Sede / morada** | `[morada]`, Portugal |
| **Serviço operado** | CheckAL — monitorização de Alojamento Local |
| **Contacto de proteção de dados** | privacidade@checkal.pt |
| **Encarregado de Proteção de Dados (EPD/DPO)** | **Não designado por defeito** — designação **não obrigatória** hoje (não há tratamento em larga escala de categorias especiais nem monitorização sistemática em larga escala como atividade principal na aceção do art. 37.º/1/b e /c). Avaliação escrita e gatilhos de reavaliação **no bloco abaixo**. Ponto de contacto: privacidade@checkal.pt |
| **Responsável interno de privacidade** | `Diogo Mendes` (pessoa concreta na Cosmic Oasis, Lda.), contactável em privacidade@checkal.pt — assegura o cumprimento, mantém este registo e reavalia os gatilhos de EPD |
| **Autoridade de controlo** | Comissão Nacional de Proteção de Dados (CNPD) — cnpd.pt |

> **Nota sobre a fonte RNAL.** Onde uma atividade obtém dados do Registo Nacional de
> Alojamento Local (RNAL) do Turismo de Portugal: o **art. 10.º n.º 5 do DL 128/2014**
> (publica o *"endereço eletrónico do titular da exploração"* e a validade do seguro
> obrigatório) está **CONFIRMADO** pelo consultor — falta apenas **CONTRA-verificação** de
> que nada no consolidado pós-DL 76/2024 o contradiz (ver `LEGAL-PARECER-DECISOES.md` §2).
> **Princípio que se mantém: publicação obrigatória ≠ licença de reutilização** — para
> **pessoas singulares**, reutilizar o email/RNAL para prospeção depende do teste de
> **compatibilidade de finalidades** (art. 6.º/4), que **não** é favorável. **Termos de
> licença do webservice `list_RNAL`** (dados abertos — **Lei 68/2021** + condições do
> Turismo de Portugal) a verificar; a sua violação é problema **contratual/administrativo
> autónomo** do RGPD.

> **Avaliação escrita da designação de EPD (art. 37.º) e gatilhos de reavaliação.**
> **Decisão hoje: NÃO designar EPD formal** — defensável por o tratamento **não** ser de
> "larga escala" (nem categorias especiais em larga escala — art. 9.º/37.º/1/c — nem
> monitorização sistemática em larga escala como atividade principal — art. 37.º/1/b). Fica
> um **responsável interno de privacidade** nomeado (ver tabela §0). **Gatilhos que obrigam a
> reavaliar (e provavelmente a designar EPD):** (1) **ingestão da base RNAL completa**
> (varrimento nacional persistido, não só consultas pontuais); (2) ultrapassar **5.000
> titulares monitorizados** de forma contínua; (3) **novas categorias de dados**
> ou nova finalidade (ex.: perfis, enriquecimento, categorias especiais); (4) ativação da
> **prospeção a frio em larga escala**. Cada gatilho, quando ocorrer, fica registado com
> **data e decisão** neste documento.

---

## Índice de atividades

| # | Atividade | Base legal principal | Estado |
|---|---|---|---|
| **A** | Verificação gratuita e captação de *leads* (consent-first) | Consentimento (6.º/1/a) + pré-contratual (6.º/1/b) | Ativa (WF1) |
| **B** | Gestão de clientes e subscrições | Execução do contrato (6.º/1/b) | Ativa |
| **C** | Alertas de estado e regulatórios | Execução do contrato (6.º/1/b) | Ativa |
| **D** | Faturação e obrigações fiscais | Obrigação legal (6.º/1/c) | Ativa |
| **E** | Suporte a clientes (com apoio de IA) | Execução do contrato (6.º/1/b) + interesse legítimo (6.º/1/f) | Ativa |
| **F** | Prospeção comercial a frio (`geral@` de pessoa coletiva) | Interesse legítimo (6.º/1/f) + Lei 41/2004 | **NÃO ATIVA / bloqueada** |

---

## Atividade A — Verificação gratuita e captação de *leads* (consent-first)

| Campo (art. 30.º/1) | Conteúdo |
|---|---|
| **Finalidade** | Executar a verificação gratuita pedida pelo próprio titular (introduz o n.º de registo, recebe mini-relatório) e, **se e só se** o autorizar por consentimento granular, enviar-lhe alertas do serviço e/ou novidades comerciais do CheckAL. |
| **Base legal (art. 6.º)** | (i) **Diligências pré-contratuais** — 6.º/1/b — para produzir e entregar o mini-relatório pedido; (ii) **Consentimento** — 6.º/1/a — para as comunicações posteriores, com dois consentimentos **separados e independentes** (alertas do serviço vs. ofertas/novidades comerciais), nenhum pré-marcado nem condicionado ao relatório. Lei 41/2004, art. 13.º-A, para o email de marketing. |
| **Categorias de titulares** | Proprietários/titulares de exploração de AL (pessoas singulares, ENI e representantes de pessoas coletivas) que usam o widget por iniciativa própria. |
| **Categorias de dados** | Email; n.º de registo AL (e dados públicos do AL a ele associados — nome do estabelecimento, concelho, estado do registo); prova de consentimento (data/hora, versão do texto consentido, endereço IP, canal); registo de cada consentimento granular em separado. |
| **Destinatários / subcontratantes** | Resend (envio de email transacional/relatório); Hetzner (alojamento aplicacional e base de dados). API pública do RNAL/Turismo de Portugal como **fonte de consulta** (não é destinatário). Nenhuma venda ou cedência a terceiros. |
| **Transferências internacionais** | **Resend (EUA)** — carece de mecanismo (Data Privacy Framework ou Cláusulas-Tipo/SCC) — ver §Transferências. Hetzner (Alemanha, EEE) — sem transferência (preferir região UE). |
| **Prazo de conservação** | *Leads* que **consentiram**: enquanto o consentimento se mantiver / a relação estiver ativa; retirada do consentimento → cessação e eliminação. *Leads* que **não interagem**: eliminação em **6 meses**. Prova de consentimento conservada enquanto necessária para demonstrar licitude (accountability), e após retirada, o registo mínimo da retirada. |
| **Medidas de segurança** | HTTPS/TLS em trânsito; base de dados de acesso restrito com credenciais próprias; princípio do mínimo (só o email e o n.º de registo); *logs* de consentimento imutáveis; autenticação forte nas consolas de fornecedores; cópias de segurança; segregação de ambientes. |

---

## Atividade B — Gestão de clientes e subscrições

| Campo | Conteúdo |
|---|---|
| **Finalidade** | Criar e gerir a conta do cliente, prestar o serviço de monitorização subscrito, gerir a renovação/cancelamento e a garantia. |
| **Base legal (art. 6.º)** | **Execução do contrato** — 6.º/1/b. Acessoriamente, interesse legítimo (6.º/1/f) para segurança da conta e prevenção de fraude. |
| **Categorias de titulares** | Clientes/subscritores do CheckAL (singulares, ENI, representantes de coletivas) e os AL sob monitorização. |
| **Categorias de dados** | Identificação e contacto (nome, email, telefone se fornecido); n.º(s) de registo AL e respetivos dados públicos monitorizados (estado do registo, validade do seguro obrigatório, concelho/regulamentos aplicáveis); dados da conta (autenticação, preferências); histórico de subscrição. |
| **Destinatários / subcontratantes** | Hetzner (alojamento); Resend (emails de conta/serviço); Stripe e/ou IfThenPay (pagamentos — ver Atividade D). |
| **Transferências internacionais** | Stripe (EUA/IE) — mecanismo (DPF/SCC); Resend (EUA) — mecanismo. Hetzner (DE) e IfThenPay (PT) — EEE, sem transferência. |
| **Prazo de conservação** | Durante a vigência da subscrição e, após cessação, pelos prazos de prescrição/defesa de direitos e obrigações legais aplicáveis. Dados de faturação seguem o prazo fiscal (Atividade D). |
| **Medidas de segurança** | Controlo de acessos por perfil; TLS; palavras-passe cifradas/*hashing*; princípio do mínimo; registo de acessos; cópias de segurança e plano de recuperação. |

---

## Atividade C — Alertas de estado e regulatórios

| Campo | Conteúdo |
|---|---|
| **Finalidade** | Monitorizar fontes públicas (RNAL, Diário da República, regulamentos municipais) e alertar cada cliente quando uma alteração afeta o seu AL (estado do registo, seguro obrigatório, regulamento do concelho). |
| **Base legal (art. 6.º)** | **Execução do contrato** — 6.º/1/b (é o núcleo do serviço subscrito). |
| **Categorias de titulares** | Clientes/subscritores e os AL monitorizados. |
| **Categorias de dados** | N.º de registo AL e dados públicos associados; estado detetado nas fontes; email de destino do alerta; histórico de alertas enviados; excertos regulatórios usados na redação. **Nota (2.ª opinião):** para clientes **ENI / pessoa singular**, os **dados do AL** usados na redação (n.º RNAL, morada, validade do seguro) **SÃO dados pessoais** — o n.º RNAL é **identificador único** e retirar o nome é **pseudonimização, não anonimização**. Não se tratam dados pessoais de **terceiros/prospects** neste fluxo. |
| **Destinatários / subcontratantes** | Resend (envio); Anthropic (camada de IA que redige o alerta — recebe excerto do documento + dados do AL; para clientes singulares/ENI esses dados são pessoais, ver acima; nunca dados de prospects); Hetzner (alojamento/BD). |
| **Transferências internacionais** | Anthropic (EUA — **ou UE via Amazon Bedrock Frankfurt `eu-central-1`**) e Resend (EUA) — mecanismo (**SCCs + TIA**; DPF só com verificação **datada**). **A IA trata dados pessoais de clientes singulares/ENI** (os dados do AL) → **DPA (art. 28.º) + mecanismo de transferência fecham-se já**; a opção **Bedrock UE elimina o Cap. V** para a IA. Para *prospects*, mantém-se a regra: só excerto regulatório + dados do AL, nunca dados de prospects (ver `LEGAL-PARECER-DECISOES.md` §6). |
| **Prazo de conservação** | Enquanto durar a subscrição; o histórico de alertas conserva-se para prova do serviço prestado e cumprimento do SLA, pelo prazo de defesa de direitos. |
| **Medidas de segurança** | TLS; minimização dos dados enviados à IA; *prompts* sem dados pessoais de terceiros; disclaimer "informação, não aconselhamento jurídico" em cada alerta (guarda de atividade reservada — Lei 10/2024); registo de envios. |

---

## Atividade D — Faturação e obrigações fiscais

| Campo | Conteúdo |
|---|---|
| **Finalidade** | Emitir fatura-recibo, processar pagamentos e cumprir as obrigações fiscais e contabilísticas legais. |
| **Base legal (art. 6.º)** | **Obrigação legal** — 6.º/1/c (deveres fiscais/faturação); **execução do contrato** — 6.º/1/b (cobrança do preço). |
| **Categorias de titulares** | Clientes/subscritores (e, quando aplicável, o adquirente que não coincide com o utilizador). |
| **Categorias de dados** | Nome/firma, NIF/NIPC, morada de faturação, descritivo do serviço, montante, meio e data de pagamento, referências da transação. |
| **Destinatários / subcontratantes** | Software/serviço de faturação (**TOConline — Cloudware**); processadores de pagamento (**Stripe** e/ou **IfThenPay**) — **DUPLA QUALIFICAÇÃO**: são **subcontratantes** no que tratam por nossa conta **e responsáveis autónomos** nas obrigações próprias de **AML/KYC** (prevenção de branqueamento, identificação), parte em que **não** agem sob as nossas instruções; Administração Tributária (comunicação legal de faturas); contabilista certificado. |
| **Transferências internacionais** | TOConline (PT) e IfThenPay (PT) — EEE. Stripe (EUA/IE) — mecanismo (**SCCs/DPF**; as SCCs de 2021 já incorporam o art. 28.º, dispensando contrato de subcontratação separado). |
| **Prazo de conservação** | Documentos de faturação/contabilísticos conservados pelo **prazo legal fiscal** aplicável (regra geral, 10 anos) — independente do fim da relação comercial. |
| **Medidas de segurança** | Acesso restrito à área de faturação; TLS; segregação de funções; os dados de cartão **não** são tratados/armazenados pela Cosmic Oasis (ficam no processador de pagamento certificado PCI-DSS). |

---

## Atividade E — Suporte a clientes (com apoio de IA)

| Campo | Conteúdo |
|---|---|
| **Finalidade** | Responder a pedidos de suporte, dúvidas e exercício de direitos, com apoio de ferramentas de IA na triagem/redação de respostas. |
| **Base legal (art. 6.º)** | **Execução do contrato** — 6.º/1/b (suporte ao serviço); **interesse legítimo** — 6.º/1/f (qualidade e eficiência do suporte; segurança). O exercício de direitos RGPD assenta na **obrigação legal** de responder (arts. 15.º–22.º). |
| **Categorias de titulares** | Clientes e *leads* que contactam o suporte; qualquer titular que exerça direitos. |
| **Categorias de dados** | Identificação e contacto; conteúdo da mensagem/ticket; histórico de interações; dados da conta relevantes para resolver o pedido. |
| **Destinatários / subcontratantes** | Resend (email); Hetzner (alojamento); Anthropic (**apoio de IA à redação/triagem — a instruir para não receber mais dados pessoais do que o necessário e nunca categorias especiais**). |
| **Transferências internacionais** | Anthropic (EUA — **ou UE via Amazon Bedrock Frankfurt `eu-central-1`**) e Resend (EUA) — mecanismo (**SCCs + TIA**; DPF só com verificação **datada**). No suporte a IA **trata dados pessoais do cliente** (identificação, conteúdo do ticket) → **DPA + mecanismo já**; Bedrock UE elimina o Cap. V. Minimização dos dados enviados à IA; nunca categorias especiais. |
| **Prazo de conservação** | Histórico de suporte conservado pelo tempo necessário à gestão da relação e prova do exercício de direitos; pedidos de exercício de direitos conservados como prova de cumprimento pelo prazo de defesa. |
| **Medidas de segurança** | Minimização dos dados enviados à IA; acesso restrito ao suporte; TLS; registo do tratamento dos pedidos de direitos; verificação de identidade antes de dar acesso/apagar. |

---

## Atividade F — Prospeção comercial a frio (`geral@` de pessoa coletiva) — **NÃO ATIVA / BLOQUEADA**

> **Estado: NÃO ATIVA.** Bloqueada por desenho (`CHECKAL_PARECER_RGPD_OK=False`). Só
> pode ser ativada quando **todos** os pré-requisitos do parecer estiverem cumpridos
> (ver `LEGAL-PARECER-DECISOES.md` §4 e `LIA-COLD-GERAL.md`). Registada aqui por
> transparência e para estar pronta caso venha a ser ligada. **Sempre** limitada a
> endereços **genéricos** de pessoa coletiva; **nunca** a pessoas singulares/ENI nem a
> endereços que identifiquem uma pessoa singular.

| Campo | Conteúdo |
|---|---|
| **Finalidade** | Apresentar o serviço CheckAL a titulares de AL que sejam **pessoas coletivas**, contactando o seu **endereço genérico** (`geral@`, `info@`, `reservas@`…), com opt-out imediato. |
| **Base legal (art. 6.º)** | **Interesse legítimo** — 6.º/1/f — com **LIA documentada** (`LIA-COLD-GERAL.md`). Regime de comunicações: **Lei 41/2004, art. 13.º-A** — *opt-out* admissível para pessoa coletiva. **Ressalva:** um endereço genérico que não identifica pessoa singular **não é dado pessoal** — nesse caso o RGPD não se aplica ao contacto e resta a Lei 41/2004; a base 6.º/1/f só releva na medida em que haja dado pessoal associado. |
| **Categorias de titulares** | Apenas **pessoas coletivas** titulares de AL, contactadas em endereço genérico. Pessoas singulares e ENI **excluídas por desenho** (filtro por natureza jurídica / NIF). |
| **Categorias de dados** | Endereço de email **genérico** da pessoa coletiva; firma/NIPC; dados públicos do AL (estabelecimento, concelho, estado). **Sem** dados de pessoas singulares. Lista de supressão/oposição (ver conservação). |
| **Destinatários / subcontratantes** | Resend (envio, se ativado); Hetzner (alojamento). Cruzamento com a **DGC** (Lista de Oposição / Direção-Geral do Consumidor) e com a lista de supressão antes de qualquer envio. |
| **Transferências internacionais** | Resend (EUA) — mecanismo (DPF/SCC) resolvido **antes** de ativar. **Nunca** enviar dados de prospects para a API de IA. |
| **Prazo de conservação** | Prospects que **não interagem**: eliminação em **6 meses**. **Lista de supressão / oposição**: conservada **em separado e por mais tempo**, como prova de que a oposição é honrada (não se elimina o registo de quem pediu para não ser contactado). |
| **Medidas de segurança** | Filtro de exclusão de singulares/ENI e de endereços nominais; identificação do remetente e **opt-out de 1 clique** em cada mensagem; nota de informação do art. 14.º na 1.ª comunicação (`ANEXO1-nota-informacao-corrigida.md`); arranque **semi-manual** (o dono revê e dispara); cruzamento DGC + supressão; TLS; registo de envios e de oposições. |

---

## Subcontratantes (art. 28.º) e transferências internacionais (art. 44.º e ss.)

Tabela canónica (de `LEGAL-PARECER-DECISOES.md` §6). Cada subcontratante carece de
enquadramento do **art. 28.º/3** antes de tratar dados em produção — **DPA** próprio ou, para
os prestadores US com Cláusulas-Tipo, o próprio módulo das **SCCs de 2021 (que já incorporam o
art. 28.º)**, dispensando contrato separado. Os que estão fora do EEE carecem de **mecanismo
de transferência** válido (Cap. V).

> **CORREÇÃO (2.ª opinião).** A IA **trata dados pessoais HOJE** para clientes ENI/singulares
> (n.º RNAL = identificador único; **pseudonimização, não anonimização**) → **DPA + mecanismo
> com a Anthropic fecham-se já**, não "quando ligar o cold". **Stripe e IfThenPay** têm **dupla
> qualificação** (subcontratante + responsável autónomo AML/KYC). **Hetzner:** fixar região UE
> + verificar sub-subcontratantes.

| Fornecedor | Função | Sede | Transferência internacional |
|---|---|---|---|
| **Anthropic** (Haiku/Sonnet) | IA da redação dos alertas/suporte | EUA — ou **UE via Bedrock Frankfurt** | ⚠️ **Trata dados pessoais de clientes singulares/ENI** → DPA + mecanismo já. Bedrock `eu-central-1` remove o Cap. V; API EUA = SCCs + TIA (+ DPF só com verificação datada). Para *prospects*: só dados do AL, nunca dados de prospects |
| **Resend** | Email transacional / comunicações | EUA | ⚠️ Mecanismo (SCCs; DPF só com verificação datada). SCC 2021 já cobre o art. 28.º |
| **Stripe** | Pagamentos | EUA / IE | ⚠️ Mecanismo (SCCs/DPF) + **dupla qualificação** (subcontratante + responsável autónomo AML/KYC) |
| **IfThenPay** | Pagamentos | PT | ✅ EEE + **dupla qualificação** (subcontratante + responsável autónomo AML/KYC) |
| **TOConline** (Cloudware) | Faturação | PT | ✅ EEE |
| **Hetzner** | Alojamento aplicacional e BD | DE | ✅ EEE — **fixar região UE + verificar sub-subcontratantes** |

> **Regra de desenho (código).** No fluxo de *prospeção*, a camada de IA (FDS4) recebe
> **excerto do documento + dados do AL** (públicos), **não** dados pessoais de prospects —
> manter esta fronteira. Para *clientes* singulares/ENI, note-se que os dados do AL enviados à
> IA **são pessoais** (daí o DPA + mecanismo serem requisito **já**).

---

## Notas de accountability

- Este registo deve ser **revisto** sempre que uma atividade, base legal, subcontratante
  ou fluxo de dados mude — em especial **antes** de ativar a Atividade F.
- **DPIA (art. 35.º):** avaliar a necessidade de uma Avaliação de Impacto sobre a
  Proteção de Dados se a prospeção/monitorização atingir larga escala. Por defeito, o
  desenho consent-first e a minimização reduzem o risco; reavaliar a cada mudança de
  escala.
- **EPD (art. 37.º):** decisão atual = **não designar** (avaliação escrita e **gatilhos de
  reavaliação** em §0); há **responsável interno de privacidade** nomeado. Rever a cada
  gatilho (ingestão da base RNAL completa; 5.000 titulares monitorizados; novas categorias de dados;
  cold em larga escala).
- **IA = subcontratante de dados pessoais HOJE** para clientes ENI/singulares (não só
  "quando ligar o cold") → DPA + mecanismo de transferência (ou Bedrock UE) fecham-se já.
- **Stripe/IfThenPay = dupla qualificação** (subcontratante + responsável autónomo AML/KYC):
  não os tratar como meros processadores nos contratos e informações.
- **Prova de consentimento** (Atividade A) e **lista de supressão** (Atividades A/F)
  são os dois artefactos de prova mais importantes perante a CNPD — manter operacionais
  desde o dia 1.
- Ver também: `Parecer_jurista/Parecer_CheckAL_RGPD.md`, `LEGAL-PARECER-DECISOES.md`,
  `LIA-COLD-GERAL.md`, `ANEXO1-nota-informacao-corrigida.md`.
