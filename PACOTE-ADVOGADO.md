# Pacote para o advogado / EPD — CheckAL (Cosmic Oasis, Lda.)

> Tudo o que precisa de validação jurídica, num só sítio. Estado: 09/07/2026.
> O parecer recebido é uma **nota de decisão** (não um parecer formal assinado). Pede
> validação de advogado inscrito em **3 pontos** antes de produção + revisão das minutas.
> **O contacto a frio está DESLIGADO em código** (`CHECKAL_PARECER_RGPD_OK=false`) até isto fechar.
> O lançamento por **consentimento + parcerias NÃO depende disto** e pode arrancar já.

---

## O que pedimos ao advogado (uma frase)
> "Confirmem-nos os 3 pontos abaixo, validem as 5 minutas, e digam-nos **o que podemos ligar,
> desta forma, com estas salvaguardas** — de preferência uma decisão, não só opções."

---

## 1. Os 3 pontos que exigem validação formal (o parecer deixou-os em aberto)

### (i) Base legal da fonte do email do titular — *CONTRA-verificação, não confirmação de raiz*
- **O art. 10.º n.º 5 está CONFIRMADO** pelo consultor (7.ª versão consolidada): o RNAL
  publica o **"endereço eletrónico do titular da exploração"** e a **validade do seguro
  obrigatório**.
- **DESACOPLAR do canal `geral@`:** o email frio a **pessoa coletiva** assenta na **Lei
  41/2004, art. 13.º-A (opt-out coletivas) + art. 13.º-B (listas/DGC)** + cruzamento **DGC** +
  identificação/opt-out por mensagem — **NÃO na fonte do endereço**. O ponto (i) serve a **redação da nota do art.
  14.º** e os **tratamentos que tocam pessoas singulares** (onde o email É dado pessoal), não
  a legitimação do cold a coletiva.
- **Pedido (CONTRA-verificação, não confirmação de raiz):** que **nada** no consolidado
  **pós-DL 76/2024** contradiga a redação do art. 10.º n.º 5; **e** verificar os **termos de
  licença/reutilização do webservice `list_RNAL`** — regime de **dados abertos (Lei 68/2021)**
  + condições do **Turismo de Portugal**. Uma violação desses termos é **problema
  contratual/administrativo autónomo** do RGPD (independente e cumulável).
- **Princípio a manter:** **publicação obrigatória ≠ licença de reutilização** — para
  singulares, a reutilização depende do **teste de compatibilidade de finalidades** (art.
  6.º/4), que se mantém.
- Fontes: [PGDL — DL 128/2014](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid=3085&tabela=leis&ficha=1&pagina=1) · [DRE](https://diariodarepublica.pt/dr/detalhe/decreto-lei/128-2014-56384880)

### (ii) Transferências internacionais + subcontratação (art. 28.º e 44.º e ss.)
- Fornecedores fora do EEE que tratam dados: **Resend** (email, EUA), **Anthropic** (IA dos
  alertas, EUA), **Stripe** (pagamentos, EUA/IE). Dentro do EEE: TOConline (PT), IfThenPay (PT),
  Hetzner (DE/UE).
- **CORREÇÃO (2.ª opinião):** a IA **trata dados pessoais HOJE** para clientes **ENI/singulares**
  — o **n.º RNAL + morada + validade do seguro são dados pessoais** (n.º RNAL = identificador
  único; tirar o nome é **pseudonimização, não anonimização**). Logo **DPA + mecanismo de
  transferência com a Anthropic fecham-se já**, independentemente do cold. A regra "a IA só vê
  dados do AL, não de prospects" vale para *prospects*, mas **não** isenta os *clientes* singulares.
- **Pedido:** validar o **mecanismo de transferência** para cada fornecedor fora do EEE e a minuta
  de subcontratação, tendo em conta que:
  - **Claude via Amazon Bedrock (Frankfurt, `eu-central-1`)** mantém a inferência na UE e
    **elimina o Cap. V** para a IA; a alternativa (API direta EUA) exige **SCCs + TIA** (+ DPF só
    com verificação **datada** da listagem);
  - as **SCCs de 2021 já incorporam o art. 28.º** — para os US com DPA adequado, **não** é preciso
    contrato de subcontratação separado;
  - **Stripe e IfThenPay** têm **dupla qualificação** (subcontratante + **responsável autónomo** nas
    obrigações próprias de AML/KYC) — refletir na minuta e no registo art. 30.º;
  - **Hetzner**: **fixar região UE** + verificar a **cadeia de sub-subcontratantes**.

### (iii) Fronteira da atividade reservada (Lei 10/2024) — à luz de um alerta REAL
- O produto interpreta regulamentos para o caso do cliente ("isto pode afetar o teu AL; verifica X").
- **Pedido:** confirmar que a linguagem nos mantém do lado da **informação** e não do **aconselhamento
  jurídico reservado**. Anexámos um **alerta real renderizado** (`ANEXO3-alerta-exemplo.html`) —
  o parecer disse que a avaliação definitiva dependia dele. Já usa disclaimer "informação, não
  aconselhamento jurídico" e cita a fonte oficial.

---

## 2. As 5 minutas a rever/aprovar (já redigidas por nós)
| Documento | Ficheiro | O que validar |
|---|---|---|
| Política de privacidade | `checkal/app/web/templates/privacidade.html` | finalidades por canal, bases legais, direitos (oposição absoluta art. 21.º), conservação 6 m, transferências, CNPD |
| Termos & Condições | `checkal/app/web/templates/termos.html` | serviço = ferramenta informativa (não garantia/aconselhamento); **teto = total pago nos 24 meses anteriores** (NÃO se promete a apólice ainda inexistente; a perna do limite por sinistro acrescenta-se quando a E&O for contratada); não excluir dolo/negligência grave/danos a pessoas; **checklist E&O** em comentário interno (exclusões de conteúdo IA; claims-made + data retroativa; sinistros em série; território PT; custos de defesa) |
| Registo de atividades (art. 30.º) | `REGISTO-ATIVIDADES-ART30.md` | completude das entradas por atividade; cold marcado NÃO ATIVO |
| LIA (interesse legítimo) — cold `geral@` | `LIA-COLD-GERAL.md` | **validar para PRESERVAR A OPÇÃO (ativação não iminente):** o teste de equilíbrio aguenta? salvaguardas (universo ~1.914 empresas; cadência 1 + 1 follow-up; DGC) suficientes? |
| Nota de informação (art. 14.º) | `ANEXO1-nota-informacao-corrigida.md` | versão **email** (art. 10.º n.º 5 já CONFIRMADO — falta só CONTRA-verificar); a **carta a singular é provavelmente inviável na prática** — o art. 10.º/5 publica o **email, não a morada** do titular, e a morada pública é a do **estabelecimento**, raramente a residência |

---

## 3. Decisões/aconselhamento que pedimos
- Necessidade (ou não) de **EPD/DPO** designado. **A nossa decisão:** não designar hoje
  (defensável por não ser "larga escala"), mas **documentámos a avaliação escrita + gatilhos de
  reavaliação** (ingestão da base RNAL completa; **5.000 subscritores**; novas categorias de dados) e
  **nomeámos responsável interno de privacidade** — ver `REGISTO-ATIVIDADES-ART30.md §0`. Confirmam?
- **Prazo de conservação** de prospects: propomos **6 meses** (supressão à parte) — confirmam?
- A **cláusula de limitação de responsabilidade** — teto = **total pago nos 24 meses anteriores**
  (não um teto a 49 €, que seria abusivo). **Decidimos NÃO prometer nos T&C um seguro que ainda não
  temos** — a perna do limite por sinistro e a menção à E&O acrescentam-se quando a apólice for
  contratada. Ver a **checklist da apólice E&O** em comentário interno de `termos.html §6`.
- A **recomendação estratégica**: assentar em **consentimento (widget) + parcerias** (é o motor).
  O cold `geral@` fica como **opção a preservar** (campanha única e curada, semi-manual, ativação não
  iminente) — pedimos que valide a LIA para **preservar a opção**, não para ativar já. Confirmam o caminho?

---

## 4. O que enviar ao advogado (o dossier)
1. `Parecer_jurista/Parecer_CheckAL_RGPD.md` (a nota de decisão recebida)
2. `BRIEFING-JURISTA-RGPD.md` (o contexto factual que preparámos)
3. `LEGAL-PARECER-DECISOES.md` (o que decidimos e encodámos no software)
4. As 5 minutas da secção 2
5. `ANEXO3-alerta-exemplo.html` (o alerta real, para o ponto (iii))

## 5. O que só a Cosmic Oasis preenche
- **NIPC** e **morada** da Cosmic Oasis, Lda. (placeholders `[NIPC]`/`[morada]` em todas as minutas).

---

## Resultado que queremos desta consulta
Uma frase executável: *"Podem ligar o canal X, desta forma, com estas salvaguardas; evitem Y"* —
e as 5 minutas validadas (ou com as correções necessárias). Enquanto os pontos (i)–(iii) não
fecharem, o cold permanece desligado; o consent-first arranca sem depender disto.
