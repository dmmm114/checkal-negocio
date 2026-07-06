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
| Carta postal a singular/ENI | 🟡 com LIA | Fora de âmbito agora (precisa de LIA escrita + Anexo 1 corrigido). |
| **Email frio a singular/ENI** | 🔴 **NÃO, nunca** | **Bloqueado por desenho** (filtro NIF 5/6; opt-in exigido pela Lei 41/2004 art. 13.º-A). |

## 2. 🚦 O bloqueador crítico — a base legal da fonte do email
O parecer duvida que o **email do titular** seja campo de publicação obrigatória (poderia ser o
contacto de emergência, ou vir de uma API que devolve mais que o portal público). **Investigação (6/7):**
- O **portal público** (`rnt.turismodeportugal.pt/.../Pesquisa_AL.aspx`) devolve nº, tipo, estado,
  nome/NIF, morada — **não confirmámos o email** aí.
- A base **consolidada (pgdlisboa)** do DL 128/2014 indica que o **art. 10.º n.º 5** lista como público
  o **"endereço eletrónico do titular da exploração"** e a **validade do seguro obrigatório**. O
  contacto de emergência (art. 6.º) é requisito de registo mas **não** consta como público.
- Usámos o **webservice `list_RNAL`** (não o portal), que devolve o email — pode expor mais que o portal.

**Conclusão:** há um **forte indício de que o email É público por lei (art. 10.º n.º 5)** — o que
resolveria a dúvida a favor. **MAS** exige, antes de qualquer cold: (i) **confirmação documental** da
redação exata do art. 10.º n.º 5 no texto **consolidado pós-DL 76/2024**; (ii) validação por advogado/EPD;
(iii) confirmar que o `list_RNAL` não devolve dados além dos públicos por lei.
→ **Ação #1 do Diogo/advogado:** confirmar a redação do art. 10.º n.º 5. Enquanto não confirmado, cold OFF.

## 3. Requisitos do widget de consentimento (implementados / a implementar)
- ✅ Checkbox **não pré-marcada** e **não condicionada** ao relatório.
- ✅ **Prova de consentimento**: timestamp + versão do texto + IP (model `Lead`).
- ✅ Identidade do responsável + link à política **junto** ao checkbox.
- ⚠️ **GRANULARIDADE (novo, exigido pela CNPD):** separar **dois** consentimentos — "alertas do serviço"
  vs "ofertas/novidades comerciais". A CNPD rejeita consentimento global para finalidades distintas.
  → **Patch ao WF1:** dois checkboxes independentes; o `Lead` regista cada um em separado.

## 4. Pré-requisitos para alguma vez ligar `CHECKAL_PARECER_RGPD_OK=True` (cold `geral@`)
Todos, cumulativos:
1. §2 resolvido (base legal do email confirmada documentalmente + validada por advogado).
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
Identificar e contratualizar cada processador; resolver transferência para os fora do EEE:
| Fornecedor | Função | Sede | Transferência? |
|---|---|---|---|
| **Resend** | email transacional | EUA | ⚠️ mecanismo (DPF/SCC) |
| **Anthropic** (Haiku/Sonnet) | IA dos alertas | EUA | ⚠️ **NUNCA enviar dados pessoais de prospects** sem mecanismo; excertos regulatórios não são pessoais |
| **TOConline** (Cloudware) | faturação | PT | ✅ EEE |
| **Stripe** | pagamentos | EUA/IE | ⚠️ mecanismo |
| **IfThenPay** | pagamentos | PT | ✅ EEE |
| **Hetzner** | alojamento | DE | ✅ EEE (preferir região UE) |
→ **Regra de código:** a camada IA (FDS4) recebe **excerto do documento + dados do AL**, não dados de
prospects; manter assim. Registar art. 30.º (registo de atividades) — ver `REGISTO-ATIVIDADES-ART30.md` (a criar).

## 7. Atividade reservada (Lei 10/2024) — guarda no produto
Os alertas mantêm-se **informação genérica + monitorização de estado** (lado seguro); **nunca**
conclusões jurídicas individualizadas. Linguagem **condicional e genérica** + disclaimer **"informação,
não aconselhamento jurídico"** em cada alerta (já previsto na camada IA / templates). Gerar **Anexo 3**
(alerta de exemplo) para o advogado fechar esta análise.

## 8. Responsabilidade / T&C
Teto a 49 € é provavelmente **abusivo** (não exclui dolo/negligência grave/danos pessoais). Manter
cláusula só para a fatia validamente limitável; a proteção real é o **seguro RC profissional (E&O)** +
descrever o serviço como **ferramenta informativa, não garantia de conformidade**.

## 9. Plano de 4 semanas (do parecer) — quem faz o quê
- **S1:** confirmar a fonte (§2) · corrigir Anexo 1 · montar registo art. 30.º · decidir EPD. *(eu: docs; tu/advogado: §2)*
- **S2:** widget com Anexos 1/2 corrigidos + política + prova de consentimento → **ligar o motor de consentimento**. *(eu)*
- **S3:** contratos art. 28.º + transferências · iniciar parcerias. *(tu; eu preparo minutas/checklist)*
- **S4:** só então, e só se §4 cumprido, escrever a LIA e ligar `geral@` (opt-out). Email a singulares: nunca.

## Fontes
- Parecer: `Parecer_jurista/Parecer_CheckAL_RGPD.md`.
- DL 128/2014 (consolidado) — [pgdlisboa](https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid=3085&tabela=leis&ficha=1&pagina=1) · [DRE](https://diariodarepublica.pt/dr/detalhe/decreto-lei/128-2014-56384880) · portal público [RNT](https://rnt.turismodeportugal.pt/RNT/Pesquisa_AL.aspx).
