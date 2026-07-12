# Decisões pós-parecer RGPD — CheckAL (âncora de execução)

> Traduz o `Parecer_jurista/Parecer_CheckAL_RGPD.md` (6/7/2026) em **decisões executáveis**.
> Regra de ouro: **o motor é consentimento + parcerias; o cold é exceção documentada, e fica
> DESLIGADO até os pré-requisitos abaixo estarem cumpridos.** Nada neste projeto envia a frio.

## 1. Decisão por canal (do parecer, Tabela D)
| Canal | Decisão | Estado no código |
|---|---|---|
| **Widget consentimento** | ✅ SIM | Ligado (WF1). Requisitos abaixo (§3). |
| **Email frio coletiva `geral@` (opt-out)** | ✅ SIM, **com condições** | **DESLIGADO** (`CHECKAL_PARECER_RGPD_OK=False`) até §4. |
| Email frio coletiva pessoa identificada (`nome@`) | 🟡 risco moderado | **Excluído por desenho** (o núcleo só aceita genérico). Não ligar. |
| Carta postal a singular/ENI | 🔴 **provavelmente inviável na prática** | O art. 10.º/5 publica o **email**, **não a morada** do titular; a morada pública no RNAL é a do **estabelecimento** (raramente a residência). Sem morada pessoal de fonte lícita, a carta a singular **não tem endereço** — marcar como **provavelmente inviável operacionalmente**, não apenas "para depois". (Se alguma vez se retomar: exige LIA escrita + Anexo 1 corrigido + fonte lícita da morada.) |
| **Email frio a singular/ENI** | 🔴 **NÃO, nunca** | **Bloqueado por desenho** (filtro NIF 5/6; opt-in exigido pela Lei 41/2004 art. 13.º-A). |

## 2. Base legal da fonte do email — DESACOPLADA do canal `geral@`
> **CORREÇÃO (2.ª opinião, 9/7):** o email frio a coletiva **NÃO depende da fonte do
> endereço**. A sua base é a **Lei 41/2004, art. 13.º-A (opt-out coletivas) + art. 13.º-B
> (listas/DGC)** + **cruzamento DGC** + **identificação do remetente e *opt-out* em cada
> mensagem**. A origem do endereço (portal, `list_RNAL`, art. 10.º) **não** é o que legitima
> o envio — deixa por isso de ser o "bloqueador crítico" do cold a `geral@`.

**O ponto (i) — art. 10.º n.º 5 — está agora CONFIRMADO** pelo consultor (7.ª versão do
texto consolidado): o RNAL **publica o "endereço eletrónico do titular da exploração"** e a
**validade do seguro obrigatório** (o contacto de emergência do art. 6.º é requisito de
registo mas **não** consta como público). Só que isto **serve outra coisa**, não o cold a
coletiva:
- a **redação da nota do art. 14.º** (podemos indicar a origem dos dados);
- os **tratamentos que tocam pessoas singulares** — onde o email/RNAL **é dado pessoal**.

**Ao advogado pede-se CONTRA-verificação, não confirmação de raiz:** que **nada** no
consolidado pós-DL 76/2024 **contradiga** a redação do art. 10.º n.º 5, e que o `list_RNAL`
não devolva mais do que o legalmente público.

**Princípio que se mantém — publicação obrigatória ≠ licença de reutilização.** Para
**pessoas singulares**, a licitude de reutilizar o email/RNAL para prospeção continua a
depender do **teste de compatibilidade de finalidades** (art. 6.º/4) — que **não é
favorável** e mantém o **cold a singulares BLOQUEADO por desenho**. A publicidade legal não
converte, por si, o dado num recurso livre para marketing.

**Termos de licença/reutilização do webservice (autónomo do RGPD):** verificar as
**condições de licença/reutilização do `list_RNAL`** — regime de **dados abertos (Lei
68/2021)** + condições específicas do **Turismo de Portugal**. Uma violação destes termos é
um **problema contratual/administrativo autónomo** do RGPD (pode existir mesmo com o RGPD
cumprido, e vice-versa). Confirmar antes de usar o webservice em produção.

→ **Ação do Diogo/advogado:** (a) CONTRA-verificar o art. 10.º n.º 5; (b) confirmar termos de
licença do `list_RNAL`; (c) o cold a coletiva assenta na Lei 41/2004 art. 13.º-A (opt-out
coletivas) + art. 13.º-B (listas/DGC) + §4, não na fonte do email.

## 3. Requisitos do widget de consentimento (implementados / a implementar)
- ✅ Checkbox **não pré-marcada** e **não condicionada** ao relatório.
- ✅ **Prova de consentimento**: timestamp + versão do texto + IP (model `Lead`).
- ✅ Identidade do responsável + link à política **junto** ao checkbox.
- ⚠️ **GRANULARIDADE (novo, exigido pela CNPD):** separar **dois** consentimentos — "alertas do serviço"
  vs "ofertas/novidades comerciais". A CNPD rejeita consentimento global para finalidades distintas.
  → **Patch ao WF1:** dois checkboxes independentes; o `Lead` regista cada um em separado.

## 4. Pré-requisitos para alguma vez ligar `CHECKAL_PARECER_RGPD_OK=True` (cold `geral@`)
Todos, cumulativos:
1. **Regime de comunicações verificado** — Lei 41/2004 **art. 13.º-A (opt-out coletivas) + art. 13.º-B (listas/DGC)** + cruzamento **DGC** + identificação/opt-out por mensagem. (A fonte do email **deixou de ser** o bloqueador — §2; falta só a CONTRA-verificação do art. 10.º n.º 5 e dos termos de licença do `list_RNAL`.)
2. **LIA escrita** (avaliação de interesse legítimo) arquivada.
3. **Anexo 1 corrigido** (§5) — sem afirmações falsas.
4. **Contratos art. 28.º** com subcontratantes + **mecanismo de transferência internacional** resolvido (§6).
5. **Lista de supressão / oposição** operacional e cruzamento **DGC** ativo (já no código, FDS6).
6. Arranque **semi-manual** (o dono revê e dispara; nunca automático de início).
Mesmo cumpridos, o email a **pessoa identificada** e a **singular** ficam sempre fora.

## 5. Anexo 1 (nota de informação) — CORREÇÃO obrigatória
A frase "público por imposição do art. 10.º" **só pode ser usada se o §2 for confirmado**. Até lá, a
nota não afirma a base de publicidade. Faltam (a acrescentar): categorias de dados tratados;
identificação do EPD (se existir); categorias de destinatários/subcontratantes; transferências
internacionais (se aplicável). **Conservação: 12 → 6 meses** para quem nunca interage (mais seguro); a
**lista de supressão** conserva-se à parte e por mais tempo (prova de que a oposição é honrada).

## 6. Subcontratantes (art. 28.º) e transferências (art. 44.º e ss.)
Identificar e contratualizar cada processador; resolver transferência para os fora do EEE.

> **CORREÇÃO (2.ª opinião, 9/7) — cai a tese "a IA nunca recebe dados pessoais".** É
> **FALSA** para clientes **ENI / pessoa singular**: os dados do estabelecimento que a IA
> processa (**n.º RNAL, morada, validade do seguro**) **são dados pessoais** — o **n.º RNAL
> é um identificador único** do titular, e tirar o nome é **pseudonimização, não
> anonimização** (o titular continua reidentificável). Logo, **a Anthropic é HOJE
> subcontratante de DADOS PESSOAIS** no serviço a clientes singulares/ENI —
> **independentemente da estratégia de aquisição** (cold ou consent-first). **Conclusão
> executável:** **DPA (art. 28.º) + mecanismo de transferência com a Anthropic fecham-se
> JÁ**, não "quando ligarmos o cold". A antiga regra de código (a IA vê dados do AL, não de
> prospects) continua a valer para *prospects*, mas **não** isenta de RGPD o tratamento dos
> dados dos *clientes* singulares.

**Duas arquiteturas possíveis para a IA (decidir):**
- **(A) Claude via Amazon Bedrock, região Frankfurt (`eu-central-1`)** — mantém a
  **inferência na UE** e **elimina a questão do Cap. V** (transferência internacional) para
  a camada de IA. **Preferida** se quisermos fechar o risco na origem.
- **(B) API direta da Anthropic (EUA)** — exige **SCCs (Cláusulas-Tipo) + TIA (*Transfer
  Impact Assessment*)** e, se se invocar o **DPF (Data Privacy Framework)**, **verificação
  DATADA** de que a entidade concreta consta da lista DPF ativa (a inscrição pode ser
  suspensa; a verificação tem de ter data e ser refeita periodicamente).

**Notas transversais (aplicam-se à tabela):**
- **As SCCs de 2021 já incorporam o art. 28.º:** para os prestadores US com **DPA adequado**,
  **não é preciso um contrato de subcontratação separado** — o módulo aplicável das
  Cláusulas-Tipo já contém as cláusulas do art. 28.º/3. Basta assinar o DPA/SCC do fornecedor
  e verificar que cobre o módulo certo (responsável→subcontratante).
- **Stripe e IfThenPay têm DUPLA QUALIFICAÇÃO:** **subcontratantes** no que tratam por nossa
  conta **E responsáveis autónomos** nas suas obrigações próprias de **AML/KYC** (prevenção
  de branqueamento, identificação). Nessa parte **não** agem sob as nossas instruções —
  refletir na política e no registo art. 30.º; não os tratar como meros processadores.
- **Hetzner:** **fixar contratualmente a região UE** **e verificar a cadeia de
  sub-subcontratantes** (art. 28.º/2 e /4) — escolher a região não basta se um
  sub-subcontratante estiver fora do EEE.

| Fornecedor | Função | Sede | Transferência? |
|---|---|---|---|
| **Anthropic** (Haiku/Sonnet) | IA dos alertas/suporte | EUA — ou **UE via Bedrock Frankfurt** | ⚠️ **Trata dados pessoais de clientes singulares/ENI HOJE** → DPA + mecanismo **já**. Opção (A) Bedrock `eu-central-1` remove o Cap. V; opção (B) API EUA = SCCs + TIA (+ DPF só com verificação datada). Para *prospects*, manter: só dados do AL, nunca dados de prospects |
| **Resend** | email transacional | EUA | ⚠️ mecanismo (SCCs; DPF só com verificação datada). SCC 2021 já cobre o art. 28.º |
| **Stripe** | pagamentos | EUA/IE | ⚠️ mecanismo (SCCs/DPF) + **dupla qualificação** (subcontratante + responsável autónomo AML/KYC) |
| **IfThenPay** | pagamentos | PT | ✅ EEE + **dupla qualificação** (subcontratante + responsável autónomo AML/KYC) |
| **TOConline** (Cloudware) | faturação | PT | ✅ EEE |
| **Hetzner** | alojamento | DE | ✅ EEE — **fixar região UE + verificar sub-subcontratantes** |
→ **Regra de código (mantida para prospects):** no fluxo de *prospeção*, a camada IA (FDS4)
recebe **excerto do documento + dados do AL**, não dados de prospects; manter assim. **Mas**
para *clientes* singulares/ENI os dados do AL enviados à IA **são pessoais** — daí o DPA +
mecanismo de transferência serem requisito **já**. Registar art. 30.º — ver
`REGISTO-ATIVIDADES-ART30.md`.

## 7. Atividade reservada (Lei 10/2024) — guarda no produto
Os alertas mantêm-se **informação genérica + monitorização de estado** (lado seguro); **nunca**
conclusões jurídicas individualizadas. Linguagem **condicional e genérica** + disclaimer **"informação,
não aconselhamento jurídico"** em cada alerta (já previsto na camada IA / templates). O **Anexo 3**
(alerta de exemplo) **já foi gerado e consta deste dossier** (secção «Exemplo real de alerta») — fecha a
análise da atividade reservada.

## 8. Responsabilidade / T&C
**CORREÇÃO (2.ª opinião):** um teto a **49 €** seria **derrubado em tribunal** — funciona como
**quase-exclusão** face ao dano previsível (perda do registo AL = dezenas de milhares de €).
**Teto aplicado hoje:** o **total pago nos 24 meses** anteriores ao facto, sem excluir
**dolo/negligência grave/danos a pessoas** nem os direitos imperativos do consumo, e descrevendo
o serviço como **ferramenta informativa, não garantia de conformidade**. **Já aplicado em
`termos.html §6`.** **Decisão fechada:** enquanto **não houver apólice E&O contratada, não se
promete seguro nos T&C**; quando a **E&O** for contratada, acrescenta-se a **perna do limite por
sinistro da apólice** (a proteção real). A **checklist da apólice E&O** (exclusões de conteúdo IA;
claims-made + data retroativa; sinistros em série; território PT; custos de defesa dentro/fora do
limite) fica em **comentário interno** nesse template, para quando a apólice for cotada.

## 9. Plano de 4 semanas (do parecer) — quem faz o quê
- **S1:** CONTRA-verificar a fonte + termos de licença do `list_RNAL` (§2) · corrigir Anexo 1 · montar registo art. 30.º · **EPD: decisão = NÃO designar hoje** (defensável por não ser "larga escala") — mas **documentar a avaliação escrita + gatilhos de reavaliação** e **nomear responsável interno de privacidade** (ver `REGISTO-ATIVIDADES-ART30.md §0`). *(eu: docs; tu/advogado: §2)*
- **S2:** widget com Anexos 1/2 corrigidos + política + prova de consentimento → **ligar o motor de consentimento**. *(eu)*
- **S3:** contratos art. 28.º + transferências · iniciar parcerias. *(tu; eu preparo minutas/checklist)*
- **S4:** só então, e só se §4 cumprido, escrever a LIA e ligar `geral@` (opt-out). Email a singulares: nunca.

## Fontes
- Parecer: `Parecer_jurista/Parecer_CheckAL_RGPD.md`.
- DL 128/2014 (consolidado) — [pgdlisboa](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid=3085&tabela=leis&ficha=1&pagina=1) · [DRE](https://diariodarepublica.pt/dr/detalhe/decreto-lei/128-2014-56384880) · portal público [RNT](https://rnt.turismodeportugal.pt/RNT/Pesquisa_AL.aspx).
