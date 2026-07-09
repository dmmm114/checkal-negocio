# Avaliação de Interesse Legítimo (LIA) — prospeção a frio a `geral@` de pessoa coletiva

> **MINUTA — a validar por advogado/EPD antes de publicar.**
>
> Avaliação de Interesse Legítimo (*Legitimate Interest Assessment*) para o tratamento
> de dados com fundamento no **art. 6.º, n.º 1, al. f), do RGPD**, no âmbito do contacto
> comercial a frio dirigido a **endereços genéricos de pessoas coletivas** titulares de
> Alojamento Local. Documento interno de accountability (art. 5.º/2).
>
> **Estado: DRAFT / CONDICIONAL.** O canal está **DESLIGADO**
> (`CHECKAL_PARECER_RGPD_OK=False`). Esta LIA **não** é, por si só, autorização para
> arrancar: depende dos pré-requisitos do parecer (`LEGAL-PARECER-DECISOES.md` §4),
> em especial a confirmação da base legal da fonte do email (§2) e a resolução das
> transferências internacionais (§6). Alinhada com
> `Parecer_jurista/Parecer_CheckAL_RGPD.md` (6/7/2026).

---

## 0. Enquadramento e âmbito

| Campo | Conteúdo |
|---|---|
| **Responsável** | Cosmic Oasis, Lda., NIPC `[NIPC]`, `[morada]` (operadora do CheckAL) |
| **Tratamento avaliado** | Contacto comercial a frio, por email, a **endereços genéricos** (`geral@`, `info@`, `reservas@`…) de titulares de AL que sejam **pessoas coletivas**, para apresentar o serviço CheckAL, com opt-out imediato. |
| **Fonte dos dados** | Registo Nacional de Alojamento Local (RNAL) / webservice do Turismo de Portugal. |
| **Base legal invocada** | Interesse legítimo — art. 6.º/1/f RGPD (quando haja dado pessoal); regime de comunicações — Lei 41/2004, art. 13.º-A (opt-out para pessoa coletiva). |
| **Fora de âmbito (excluído por desenho)** | Pessoas singulares e ENI (qualquer canal a frio); endereços que **identifiquem** uma pessoa singular (`nome.apelido@…`); email a singular/ENI (proibido — opt-in prévio, art. 13.º-A). |

> **Nota preliminar sobre a natureza do dado.** Um endereço **genuinamente genérico**
> (`geral@empresa.pt`) que não identifica nenhuma pessoa singular **não é dado pessoal**
> na aceção do art. 4.º/1 — nesse caso o RGPD não se aplica ao contacto e o único
> enquadramento é a Lei 41/2004 (opt-out, pessoa coletiva). Esta LIA cobre a hipótese
> conservadora em que exista **algum** elemento pessoal associado (p. ex., o registo
> ligar o endereço a uma pessoa identificável), assegurando fundamento também nesse
> cenário. **Endereços nominais são excluídos por desenho.**

---

## 1. Teste de finalidade — *há um interesse legítimo?*

**Interesse prosseguido.** Dar a conhecer, a titulares de AL que são pessoas coletivas,
um serviço (CheckAL) **diretamente relevante para a atividade regulada que exercem** —
a monitorização do registo RNAL, do seguro obrigatório e dos regulamentos municipais,
cujo incumprimento os expõe a coimas e ao cancelamento do registo.

- **Legítimo?** Sim. A promoção de produtos/serviços é reconhecida como interesse
  legítimo (considerando 47 do RGPD refere expressamente o marketing direto como um
  interesse que *pode* ser legítimo). O interesse é **real e atual** (o CheckAL existe e
  está operacional), **específico** (um serviço concreto para um público concreto) e
  **lícito** (não visa fim ilícito).
- **Interesse de terceiros / do próprio titular.** Há também um interesse do próprio
  destinatário em conhecer uma ferramenta que o ajuda a manter-se conforme e a evitar
  sanções — o que aproxima (sem substituir) a expetativa razoável.

**Conclusão do teste de finalidade:** existe interesse legítimo identificado e lícito.
✅ (com a ressalva de que "legítimo" não basta — ver testes 2 e 3).

---

## 2. Teste de necessidade — *o tratamento é necessário para esse interesse?*

- **O contacto é necessário para o fim?** Sim, na medida em que apresentar o serviço a
  quem pode beneficiar dele exige, por natureza, comunicar com essa entidade.
- **Há via menos intrusiva que atinja o mesmo?** Em larga medida, **sim** — e isso é
  determinante. O motor primário do CheckAL é **consentimento (widget) + parcerias**,
  que atingem o objetivo (angariar clientes) **sem reutilizar dados de terceiros**. O
  contacto a frio é, portanto, um **acelerador marginal**, não a única via. Isto
  **enfraquece** o argumento de necessidade: se o fim se alcança sem o tratamento, a
  necessidade é fraca.
- **Minimização.** Quando usado, o tratamento limita-se ao **estritamente necessário**:
  só endereços **genéricos**, só o dado de contacto e os dados públicos do AL, sem
  criação de perfis nem enriquecimento de dados.

**Conclusão do teste de necessidade:** o contacto é *apto* ao fim, mas **não
estritamente necessário** — existem alternativas menos intrusivas (consentimento,
parcerias). A necessidade é **fraca**, o que sobrecarrega o teste de equilíbrio.
🟡

---

## 3. Teste de equilíbrio — *o interesse prevalece sobre os direitos e a expectativa razoável do titular?*

Este é o teste decisivo, e é onde a CNPD dá **peso preponderante à expectativa
razoável** do titular no momento em que os dados foram disponibilizados
(Diretriz CNPD 2022/1; princípio da lealdade, art. 5.º/1/a).

**Fatores a favor do responsável:**
- O serviço é **relevante para a atividade** do destinatário (não é oferta aleatória).
- O contacto é a um **endereço genérico** de pessoa coletiva, de **baixa intrusão** na
  esfera pessoal (não há, em regra, uma pessoa singular diretamente visada).
- **Opt-out de 1 clique** e cessação imediata reduzem o impacto e devolvem o controlo.
- Comunicação B2B, num contexto profissional, alinhada com a Lei 41/2004 (opt-out para
  pessoa coletiva).

**Fatores contra (a favor do titular):**
- **Expectativa razoável.** Quem publica um contacto num **registo regulatório** (o RNAL
  é um registo de cumprimento legal, não uma montra comercial) **não espera** receber
  marketing de terceiros com base nesse dado. O parecer é explícito: esta expectativa é
  **decisiva** e **enfraquece** o interesse legítimo.
- **Reutilização de finalidade.** O dado foi disponibilizado para transparência do
  registo, não para prospeção — há tensão com a limitação das finalidades (art. 5.º/1/b),
  atenuada, mas não eliminada, por se tratar de pessoa coletiva e endereço genérico.
- **Novo responsável.** A Cosmic Oasis não tem relação prévia com o titular; a ausência
  de relação é, segundo a própria CNPD, o fator que mais pesa nas queixas.

**Salvaguardas que reequilibram (ver §4):** limitação a genéricos, opt-out 1 clique,
nota art. 14.º na 1.ª mensagem, cruzamento DGC + supressão, exclusão absoluta de
singulares, arranque semi-manual.

**Conclusão do teste de equilíbrio:** o equilíbrio é **apertado**. Para pessoa coletiva
em endereço genérico, com todas as salvaguardas, é **defensável** — mas **não isento de
risco**, sobretudo pela expectativa razoável. Sem as salvaguardas, o interesse legítimo
**não** prevalece. 🟡

---

## 4. Salvaguardas exigidas (cumulativas, condição de licitude)

Nenhum envio ocorre sem **todas** estas salvaguardas ativas:

1. **Só endereços genéricos** de pessoa coletiva. Filtro que exclui, por desenho,
   pessoas singulares/ENI e endereços nominais (`nome.apelido@`).
2. **Opt-out de 1 clique** em cada mensagem, com cessação **imediata** e honrada.
3. **Nota de informação do art. 14.º** na primeira comunicação
   (`ANEXO1-nota-informacao-corrigida.md`) — sem afirmações não confirmadas sobre a
   base de publicidade do email.
4. **Cruzamento prévio** com a **DGC** (Lista de Oposição) e com a **lista de supressão**
   interna antes de cada envio.
5. **Lista de supressão** conservada em separado e por mais tempo (prova de que a
   oposição é honrada); prospects que não interagem eliminados em **6 meses**.
6. **Sem perfis, sem enriquecimento, sem venda** de dados; minimização.
7. **Arranque semi-manual** — o dono revê e dispara; nunca automático de início.
8. **Transferências internacionais resolvidas** (Resend/EUA com DPF ou SCC) antes de
   ativar; **nunca** enviar dados de prospects à API de IA.

---

## 5. Conclusão condicional (honesta)

**Resultado da LIA:** para o **único** subconjunto avaliado — **pessoa coletiva,
endereço genérico, com todas as salvaguardas do §4** — o interesse legítimo é
**defensável**, mas o desfecho é de **risco gerido, não eliminado**: o ponto frágil é a
**expectativa razoável** do titular perante a reutilização de um registo regulatório, à
qual a CNPD dá peso preponderante.

Por isso, e em coerência com o parecer:

- O contacto a frio é **exceção documentada, não a espinha dorsal** da aquisição. O
  motor é **consentimento + parcerias** (risco eliminado na raiz).
- Esta LIA **só** autoriza o arranque quando **todos** os pré-requisitos do parecer
  estiverem cumpridos (`LEGAL-PARECER-DECISOES.md` §4), com destaque para:
  1. **Base legal da fonte do email confirmada** documentalmente e validada por advogado
     (`LEGAL-PARECER-DECISOES.md` §2 / parecer §2) — enquanto não confirmada, **cold OFF**;
  2. **Transferências internacionais** resolvidas (parecer §6);
  3. **Contratos de subcontratação (art. 28.º)** celebrados.
- **Fora de âmbito, sempre:** email a pessoa identificada em pessoa coletiva
  (`nome@`, risco moderado — excluído por desenho) e **qualquer** contacto a frio a
  pessoa singular/ENI (proibido — art. 13.º-A da Lei 41/2004).

> **Revisão.** Reavaliar esta LIA se mudar a base legal da fonte, o volume/escala, as
> salvaguardas ou a postura da CNPD. Registar a decisão final (go/no-go) e a data.

---

## 6. Referências

- `Parecer_jurista/Parecer_CheckAL_RGPD.md` (6/7/2026) — Tabela de decisão por canal
  (canal 2), matriz de riscos, questões Q9/Q10.
- `LEGAL-PARECER-DECISOES.md` §2 (base legal da fonte), §4 (pré-requisitos), §6
  (subcontratantes/transferências).
- `REGISTO-ATIVIDADES-ART30.md` — Atividade F (NÃO ATIVA).
- `ANEXO1-nota-informacao-corrigida.md` — nota de informação (art. 14.º).
- RGPD art. 6.º/1/f, considerando 47; art. 5.º/1/a e b; art. 21.º/2 (oposição absoluta).
- Lei 41/2004, art. 13.º-A; Diretriz CNPD 2022/1 (marketing direto).
