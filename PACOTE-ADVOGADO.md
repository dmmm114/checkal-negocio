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

### (i) Base legal da fonte do email do titular — *pré-verificado por nós*
- O parecer duvidava que o email fosse campo público por lei. **A nossa verificação (texto
  consolidado do DL 128/2014 na PGDL) indica que o art. 10.º, n.º 5 lista como público o
  "endereço eletrónico do titular da exploração" e a validade do seguro obrigatório.**
- **Pedido:** confirmar a redação exata do art. 10.º n.º 5 no consolidado **pós-DL 76/2024**, e
  que o webservice `list_RNAL` (que usamos) não expõe mais do que o legalmente público.
- **Porque importa:** se confirmado, o cold a `geral@` de coletiva (opt-out) fica defensável e a
  nota de informação pode citar a base; se não, o cold cai e ficamos 100% em consentimento.
- Fontes: [PGDL — DL 128/2014](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid=3085&tabela=leis&ficha=1&pagina=1) · [DRE](https://diariodarepublica.pt/dr/detalhe/decreto-lei/128-2014-56384880)

### (ii) Transferências internacionais + subcontratação (art. 28.º e 44.º e ss.)
- Fornecedores fora do EEE que tratam dados: **Resend** (email, EUA), **Anthropic** (IA dos
  alertas, EUA), **Stripe** (pagamentos, EUA/IE). Dentro do EEE: TOConline (PT), IfThenPay (PT),
  Hetzner (DE/UE).
- **Pedido:** validar o **mecanismo de transferência** (Cláusulas-Tipo/DPF/art. 46.º) para cada um
  de fora do EEE, e a minuta de **contrato de subcontratação (art. 28.º)**. Regra de código que já
  aplicamos: a IA recebe **excerto do documento + dados do AL**, nunca dados pessoais de prospects.

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
| Termos & Condições | `checkal/app/web/templates/termos.html` | serviço = ferramenta informativa (não garantia/aconselhamento); limitação de responsabilidade não excluir dolo/negligência grave; E&O |
| Registo de atividades (art. 30.º) | `REGISTO-ATIVIDADES-ART30.md` | completude das entradas por atividade; cold marcado NÃO ATIVO |
| LIA (interesse legítimo) — cold `geral@` | `LIA-COLD-GERAL.md` | o teste de equilíbrio aguenta? salvaguardas suficientes? |
| Nota de informação (art. 14.º) | `ANEXO1-nota-informacao-corrigida.md` | versão email + carta; sem afirmar art. 10.º até (i) fechar |

---

## 3. Decisões/aconselhamento que pedimos
- Necessidade (ou não) de **EPD/DPO** designado.
- **Prazo de conservação** de prospects: propomos **6 meses** (supressão à parte) — confirmam?
- A **cláusula de limitação de responsabilidade** + o **seguro RC profissional (E&O)** como proteção real.
- A **recomendação estratégica**: assentar em **consentimento (widget) + parcerias** (é o nosso plano) —
  confirmam que é o caminho, e o cold só como acelerador limitado a `geral@`/opt-out?

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
