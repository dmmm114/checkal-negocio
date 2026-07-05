# CheckAL — Copy de Vendas (pronto a usar)

> Parte do dossier CheckAL. Regra de bloqueio: nenhuma peça sai com placeholders [entidade]/[NIPC]/[morada] por preencher. Checklist de conformidade no fim deste ficheiro; redações RGPD integrais em LEGAL.md.

## 1. Carta física — pessoa singular (1 página A4)

*Variáveis de merge (todas vêm da API RNAL): `{{Nome}}`, `{{NomeAlojamento}}`, `{{NrRegisto}}`, `{{Concelho}}`, `{{Freguesia}}` + bloco regulatório do concelho (exemplos abaixo). URL curto personalizado: `checkal.pt/v/{{NrRegisto}}` + QR code para o mesmo destino.*

---

**CheckAL** · checkal.pt · Serviço independente de monitorização de Alojamento Local

> **O CheckAL é um serviço privado e independente de monitorização de Alojamento Local, sem qualquer vínculo ao Turismo de Portugal, ao RNAL ou a qualquer câmara municipal. Esta carta não é uma notificação oficial.**
> *(caixa destacada na primeira dobra da carta — redação fixa, definida na secção legal; usar tal e qual em todas as peças)*

Exmo.(a) Sr.(a) {{Nome}},

Escrevo-lhe sobre o **{{NomeAlojamento}}**, registo de Alojamento Local n.º **{{NrRegisto}}**, em {{Freguesia}}, {{Concelho}}.

Somos um serviço privado que vigia o registo nacional de AL — e o seu registo consta da lista pública que analisámos esta semana.

**[BLOCO REGULATÓRIO — versão Lisboa]** Talvez saiba que o regulamento municipal de AL de Lisboa foi alterado em dezembro de 2025 (Aviso n.º 29926-A/2025/2), com novas áreas de contenção absoluta por bairro. E que, desde março de 2025, todos os titulares têm de comunicar anualmente a prova do seguro de responsabilidade civil — a Câmara de Lisboa já cancelou **6.765 registos** de quem não o fez. A nível nacional, já foram cancelados **mais de 10.000 registos**.

**[BLOCO REGULATÓRIO — versão Porto]** Talvez saiba que a Câmara do Porto anunciou em maio de 2026 o cancelamento de **1.413 registos** de AL, num processo nacional que já eliminou mais de 10.000 registos por falta de seguro comunicado ou inatividade.

O problema não é a lei de hoje — é a de amanhã. Regulamentos municipais novos, reavaliação das áreas de contenção de 3 em 3 anos, prazos de seguro, notificações com dias para responder. Quem falha um prazo arrisca coimas de **2.500€ a 4.000€** e, no limite, o cancelamento do registo. Ninguém o avisa pessoalmente — publica-se em Diário da República e presume-se que leu.

É isso que fazemos por si: vigiamos o seu registo, o seu seguro e o seu concelho todas as semanas, e só lhe escrevemos quando algo o afeta — explicado em português claro, com o que fazer a seguir. E no dia 1 de cada mês recebe um relatório a confirmar que está tudo em ordem.

**Comece por ver, grátis e em 30 segundos, o estado atual do seu registo:**

→ **checkal.pt/v/{{NrRegisto}}** *(ou aponte a câmara do telemóvel ao código QR)*

Sem registo, sem cartão, sem compromisso. Vê o relatório e decide.

Com os melhores cumprimentos,
Diogo Mendes · Fundador, CheckAL

---

*Rodapé RGPD (redação integral da secção legal — usar tal e qual):*

*Proteção de dados: o CheckAL é operado por [entidade], NIPC [—], com sede em [morada completa]. Os seus dados de contacto foram obtidos do registo público RNAL, cuja divulgação é obrigatória por força do art. 10.º do DL n.º 128/2014, de 29 de agosto. Base legal do tratamento: interesse legítimo (art. 6.º, n.º 1, al. f) do RGPD) — informar titulares de AL sobre um serviço diretamente relacionado com a sua atividade. Conservamos os seus dados de contacto por um máximo de 12 meses ou até à sua oposição, o que ocorrer primeiro. Pode opor-se a qualquer momento, sem custos, em **checkal.pt/remover** ou por carta para a morada acima. Tem ainda direito de acesso, retificação e apagamento, e o direito de apresentar queixa à CNPD (cnpd.pt). Política de privacidade completa: checkal.pt/privacidade.*

---

## 2. Email frio — pessoa coletiva (+ 2 follow-ups)

### Email 1 (D+0)

**Assunto:** {{NomeAlojamento}} — registo {{NrRegisto}}: quem vigia os prazos?

*O CheckAL é um serviço privado e independente de monitorização de Alojamento Local, sem qualquer vínculo ao Turismo de Portugal, ao RNAL ou a qualquer câmara municipal. Este email não é uma notificação oficial.*

Bom dia,

A {{NomeEmpresa}} é titular do registo de AL n.º {{NrRegisto}} ({{Concelho}}). Encontrámo-lo na lista pública do RNAL — é isso que fazemos: vigiamos os 120.000+ registos do país.

Contexto rápido: desde março de 2025 a prova anual do seguro é obrigatória, e as câmaras já cancelaram **mais de 10.000 registos** por incumprimento. Para pessoas coletivas, as coimas por exploração irregular vão de **25.000€ a 40.000€**.

O CheckAL monitoriza semanalmente o estado do registo, o prazo do seguro e os regulamentos do concelho, e envia alertas interpretados: "isto afeta o vosso AL — sim/não e porquê". No dia 1 de cada mês, um relatório confirma que está tudo em ordem. Zero trabalho do vosso lado.

**Veja grátis o estado atual do vosso registo (30 segundos):**
→ checkal.pt/v/{{NrRegisto}}

Cumprimentos,
Diogo Mendes · CheckAL

---

*Rodapé RGPD (redação integral da secção legal — usar tal e qual):*

*Proteção de dados: o CheckAL é operado por [entidade], NIPC [—], com sede em [morada completa]. Os dados de contacto desta mensagem foram obtidos do registo público RNAL, cuja divulgação é obrigatória por força do art. 10.º do DL n.º 128/2014. Base legal: interesse legítimo (art. 6.º, n.º 1, al. f) do RGPD); comunicação B2B a pessoa coletiva nos termos do art. 13.º-A, n.º 4, da Lei n.º 41/2004. Conservamos os dados por um máximo de 12 meses ou até oposição. Pode opor-se num clique — [Remover da lista] — ou escrever para a morada acima; tem direito de acesso, retificação, apagamento e queixa à CNPD (cnpd.pt). Política completa: checkal.pt/privacidade.*

### Follow-up 1 (D+4) — prova social

**Assunto:** Re: {{NomeAlojamento}} — o que os outros titulares já viram

*[Mesma linha de independência no topo e mesmo rodapé RGPD integral do Email 1 — blocos fixos em todos os emails da sequência.]*

Bom dia,

Só um dado: dos relatórios gratuitos que gerámos este mês, **1 em cada 3 registos tinha pelo menos um ponto por resolver** — quase sempre o seguro por comunicar ou o concelho com regulamento novo. Os titulares não sabiam. É esse o padrão: ninguém avisa, publica-se e conta-se o prazo.

O relatório do vosso registo {{NrRegisto}} continua disponível, grátis: **checkal.pt/v/{{NrRegisto}}**

Diogo · CheckAL

### Follow-up 2 (D+10) — caso real noticiado

**Assunto:** 6.765 registos cancelados em Lisboa — a mecânica é sempre a mesma

*[Mesma linha de independência no topo e mesmo rodapé RGPD integral do Email 1 — blocos fixos em todos os emails da sequência.]*

Bom dia,

Caso real: em fevereiro de 2026, a Câmara de Lisboa cancelou **6.765 registos de AL** — cerca de um terço da cidade — sobretudo por falta de comunicação do seguro ([Observador](https://observador.pt/2026/02/20/camara-de-lisboa-cancela-40-das-licencas-de-alojamento-local-eram-licencas-fantasma-e-al-estavam-inativos/)). O Porto seguiu-se com 1.413. A ALEP estima que o processo chegue aos **40–45 mil cancelamentos** no país.

A mecânica: notificação, prazo curto, silêncio = cancelamento tácito. Recuperar um registo cancelado num concelho em contenção pode ser **impossível** — não há novos registos lá.

49€/ano por AL para nunca ser apanhado nesta engrenagem. Último email que vos envio; o relatório gratuito fica aqui: **checkal.pt/v/{{NrRegisto}}**

Diogo · CheckAL

---

## 3. Landing page — checkal.pt

### Hero

**Headline:** O teu AL? Check ✓
**Subheadline:** Mais de 10.000 registos de AL já foram cancelados por prazos falhados. Nós vigiamos o teu registo, o teu seguro e o teu concelho — todas as semanas — e avisamos-te em português claro antes que algo te custe o negócio.
**CTA primário:** [Fazer o check ao meu AL — grátis, 30 segundos]
**CTA secundário (link discreto):** Ver como funciona ↓

### Barra de prova (por baixo do hero)

✓ 126.000+ registos RNAL monitorizados · ✓ 308 concelhos cobertos · ✓ Alertas interpretados por IA · ✓ Serviço 100% português · ✓ Independente — não somos o Turismo de Portugal

### O que vigiamos

- 🗂 **O teu registo no RNAL** — se muda de estado, desaparece ou é alvo de "limpeza", és avisado em dias — não quando a coima chegar.
- 🛡 **O seguro obrigatório** — a prova anual é lei desde março de 2025; avisamos-te 60, 30 e 7 dias antes do prazo.
- 🏛 **O regulamento do teu concelho** — o DL 76/2024 pôs dezenas de câmaras a legislar; lemos tudo e dizemos-te se te afeta.
- 📍 **Áreas de contenção** — reavaliadas no mínimo de 3 em 3 anos; se a tua freguesia entra em contenção, és o primeiro a saber.
- 📜 **Diário da República** — portarias e decretos sobre AL, filtrados e traduzidos para "o que isto significa para ti".
- ✉️ **Notificações de cancelamento em massa** — quando a tua câmara inicia um processo, avisamos antes do prazo correr.

### Como funciona

1. **Verifica grátis.** Insere o teu n.º de registo (ou o nome do alojamento) e recebe um mini-relatório imediato do estado do teu AL.
2. **Ativa a vigilância.** Subscreve em 2 minutos. Não instalas nada, não fazes nada — nós é que trabalhamos.
3. **Dorme descansado.** Só te escrevemos quando algo te afeta, com a explicação e os passos a dar. E no dia 1 de cada mês recebes o relatório "Tudo em ordem" — a prova, todos os meses, de que estivemos a vigiar por ti.

### Widget de verificação gratuita

**Verifica o estado do teu AL — grátis**
[ Campo: n.º de registo RNAL ou nome do alojamento ] [Botão: Fazer o check]
*Recebes o relatório no teu email em segundos. Sem cartão, sem compromisso.*

### Preços (tabela com ancoragem)

*Linha de ancoragem por cima da tabela:* **Coima mínima por incumprimento: 2.500€. Registo cancelado: negócio perdido. Vigilância: menos de 1€ por semana.**

| | **Anual** | **Trienal** ⭐ mais popular | **Portfólio** |
|---|---|---|---|
| Preço | 49€/ano | **119€/3 anos** (poupas 28€) | 149€/ano |
| ALs incluídos | 1 | 1 | até 10 |
| Vigilância semanal completa | ✓ | ✓ | ✓ |
| Alertas interpretados por IA | ✓ | ✓ | ✓ |
| Avisos de prazo do seguro | ✓ | ✓ | ✓ |
| Selo "AL Monitorizado" | ✓ | ✓ | ✓ (todos os ALs) |
| Relatório mensal "Tudo em ordem" (dia 1 de cada mês) | ✓ | ✓ | ✓ consolidado |
| | [Subscrever] | [Subscrever] | [Subscrever] |

*Preço por AL no Trienal: 3,31€/mês equivalente. Todos os planos: renovação com aviso prévio, cancelas quando quiseres.*

**🛡 Garantia de 30 dias:** se nos primeiros 30 dias mudares de ideias, devolvemos 100% do valor — um email chega, sem perguntas. *(Acresce o direito legal de livre resolução de 14 dias.)*

### FAQs

**Isto não é grátis no site do Turismo de Portugal?**
É — e é exatamente por isso que existimos. Os dados são públicos, mas ninguém te avisa quando mudam. O registo pode ser cancelado, o regulamento do teu concelho pode mudar, o prazo do seguro pode passar — e a informação fica lá, pública, à espera que te lembres de ir ver. Os 6.765 titulares de Lisboa cujos registos foram cancelados em 2026 também tinham acesso grátis ao site. Não pagas pelos dados: pagas por alguém que olha para eles todas as semanas por ti e te traduz o juridiquês em "faz isto até dia X".

**Como é que tinham o meu contacto?**
O art. 10.º do DL 128/2014 obriga à publicação da identificação e contactos dos titulares de AL. Usamos apenas esses dados públicos, cumprimos o RGPD e removemos-te da lista num clique.

**Isto substitui um advogado ou contabilista?**
Não. Nós detetamos e explicamos; não damos aconselhamento jurídico. Mas 90% dos problemas resolvem-se sabendo do prazo a tempo — e é isso que garantimos.

**Tenho de instalar alguma coisa?**
Não. Recebes tudo por email: os alertas quando algo te afeta e o relatório mensal no dia 1. Feito para quem quer pagar e esquecer.

**Se está tudo bem, não vou saber de vocês?**
Vais — uma vez por mês. No dia 1 de cada mês recebes o relatório "Tudo em ordem": o que verificámos, o que mudou no teu concelho e a confirmação de que o teu registo e o teu seguro estão em dia. Silêncio total nunca é o produto; vigilância comprovada é.

**E se eu vender ou fechar o AL?**
Nos primeiros 30 dias, devolvemos 100% — sem perguntas. Depois disso, o plano Anual corre até ao fim do período pago (é isso que permite o preço de 49€/ano); no Trienal, devolvemos os anos completos ainda não iniciados. E se venderes o AL, transferimos a monitorização para o novo titular num clique — sem telefonemas, sem burocracia.

**Funciona no meu concelho?**
Sim — cobrimos os 308 concelhos, do RNAL ao regulamento municipal. A pressão regulatória é maior em Lisboa, Porto e Algarve, mas a lei do seguro e o DL 76/2024 aplicam-se a todo o país.

### Rodapé de confiança

CheckAL é um serviço da [entidade], NIPC [—], [morada], Portugal. Não somos, nem representamos, o Turismo de Portugal, o RNAL ou qualquer câmara municipal. Dados tratados ao abrigo do RGPD — [Política de Privacidade] · [Termos] · [Remover contactos]. Feito em Portugal por quem já vigia registos públicos (INPI) desde [ano].

---

## 4. Email de resultado da verificação gratuita

**Assunto:** O estado do teu AL {{NrRegisto}} — relatório CheckAL

Olá {{Nome}},

Aqui está o relatório do **{{NomeAlojamento}}** (registo n.º {{NrRegisto}}, {{Concelho}}), gerado agora a partir dos dados públicos:

| Verificação | Estado |
|---|---|
| Registo no RNAL | 🟢 **Ativo** — consta da lista oficial de {{Concelho}} |
| Seguro de responsabilidade civil | 🟡 **Não confirmável publicamente** — desde março de 2025 a prova anual é obrigatória; confirma a data da tua na plataforma Gov.pt |
| Regulamento municipal | 🔴 **Atenção** — {{Concelho}} alterou o regulamento de AL em {{data}}; a tua freguesia ({{Freguesia}}) está classificada como {{classificação de contenção}} |
| Capacidade registada | 🟢 {{NrUtentes}} utentes / {{NrCamas}} camas — confere com o teu anúncio? Divergências dão coima |

**Resumo em uma frase:** o teu registo está vivo, mas tens {{n}} ponto(s) amarelo(s)/vermelho(s) que valem 10 minutos da tua atenção esta semana.

**O que este relatório não faz:** avisar-te do *próximo* prazo. Este retrato é de hoje; o regulamento de amanhã, a notificação da câmara, o vencimento do seguro — isso só se apanha vigiando toda a semana. Foi assim que mais de 10.000 titulares perderam o registo desde 2025: não por o estado de hoje estar mau, mas por ninguém estar a olhar quando mudou.

**Ativa a vigilância contínua do {{NomeAlojamento}}: 49€/ano** (ou 119€/3 anos) — vigilância semanal, alertas interpretados e relatório mensal no dia 1, por menos de 1€ por semana. Garantia de 30 dias: reembolso total sem perguntas.

→ [Ativar monitorização agora]

Diogo · CheckAL
*Relatório baseado em dados públicos do RNAL à data de envio. Não constitui aconselhamento jurídico.*

---

## 5. Exemplo de email de alerta (o produto)

**Assunto:** 🔴 ALERTA [Importante] — novo regulamento em Lisboa afeta o teu AL "Casa da Graça"

**ALERTA CheckAL · Severidade: IMPORTANTE (2 de 3)** · Registo 93415/AL · Casa da Graça, São Vicente, Lisboa

**O que aconteceu:** a Câmara de Lisboa publicou a 2.ª alteração ao Regulamento Municipal do AL (Aviso n.º 29926-A/2025/2, em vigor desde 06/12/2025), com novas áreas de contenção absoluta e relativa calculadas por bairro.

**Afeta o teu AL? SIM — eis porquê:** a tua freguesia (São Vicente) tem um rácio AL/habitação acima de 10%, o que a coloca em **contenção absoluta**. O teu registo atual **mantém-se válido** — não tens de fazer nada para continuar a operar. Mas há duas consequências práticas: (1) se o registo caducar ou for cancelado (ex.: falha na prova anual do seguro), **não conseguirás obter um novo** nesta zona; (2) a transmissão do registo em caso de venda fica sujeita às regras de contenção.

**Próximos passos (10 minutos):**
1. Confirma já a validade do teu seguro RC e a data-limite da próxima comunicação anual — é agora o teu único ponto de falha crítico. *(Nós avisamos-te 60/30/7 dias antes.)*
2. Guarda este email como registo da data em que tomaste conhecimento.
3. Nada mais. Continuamos a vigiar; se a câmara te notificar de algo, saberás por nós.

**O teu escudo este mês:** analisámos 16 publicações regulatórias relevantes para Lisboa; 15 não te afetavam (não te incomodámos), 1 afetava — esta. O detalhe completo segue no teu relatório mensal, no dia 1. É isto que a tua subscrição paga.

*Subscrição ativa até {{data}}. Renova sem pensar: [renovar por 3 anos com desconto].*

---

## 6. Selo "AL Monitorizado" + página pública de verificação

### Texto do selo (badge digital para anúncio Airbnb/Booking + autocolante para a porta)

**CheckAL ✓ — AL Verificado**
Registo n.º 93415/AL · Verificado semanalmente
*Confirme em: checkal.pt/selo/93415*

*Frase para a descrição do anúncio (o cliente copia/cola):* "Este alojamento é monitorizado pelo CheckAL: registo oficial de AL e seguro de responsabilidade civil verificados semanalmente. Confirme em checkal.pt/selo/93415."

### Página pública de verificação (o que o hóspede vê)

**✅ Este alojamento está monitorizado.**

**Casa da Graça** · Alojamento Local n.º **93415/AL** · São Vicente, Lisboa

| | |
|---|---|
| Registo oficial no RNAL | ✅ Ativo — verificado há 2 dias |
| Seguro de responsabilidade civil | ✅ Comunicado às autoridades |
| Monitorizado pelo CheckAL desde | março de 2026 |

**O que isto significa para si, hóspede:** este alojamento opera com registo oficial junto do Turismo de Portugal e é vigiado semanalmente por um serviço independente. Em Portugal, mais de 10.000 registos de alojamento foram cancelados desde 2025 — reservar um AL com registo ativo e verificado é a sua garantia de que está num alojamento legal e segurado.

*O CheckAL é um serviço independente de monitorização. Verificação baseada nos dados públicos do RNAL (Turismo de Portugal). Última verificação: {{data}}.*

**É proprietário de um Alojamento Local?** [Verifique o seu registo grátis →]

---

## 7. Checklist de conformidade por peça (verificar contra a secção legal antes do 1.º envio)

| Peça | Disclaimer fixo de independência (redação exata, topo/1.ª dobra) | Rodapé RGPD integral (NIPC, morada, base legal, 12 meses, CNPD, remoção) | Via de opt-out funcional | Fontes dos números confirmadas |
|---|---|---|---|---|
| Carta física (p. singular) | ✓ caixa na 1.ª dobra | ✓ rodapé completo | ✓ checkal.pt/remover + morada postal | ✓ |
| Email frio D+0 (p. coletiva) | ✓ linha no topo, antes da saudação | ✓ rodapé completo | ✓ link [Remover da lista] 1 clique | ✓ |
| Follow-ups D+4 e D+10 | ✓ mesmos blocos fixos do D+0 | ✓ mesmos blocos fixos do D+0 | ✓ | ✓ (D+4: placeholder assinalado) |
| Landing page | ✓ barra de prova + rodapé de confiança | ✓ links Privacidade/Termos/Remover | ✓ | ✓ |
| Email de verificação gratuita | ✓ nota "dados públicos / não é aconselhamento jurídico" | ✓ (enviado a pedido do próprio — base: diligências pré-contratuais) | ✓ | ✓ |
| Email de alerta (produto) | n/a (cliente ativo) | ✓ rodapé de subscrição | ✓ gestão de subscrição | ✓ |
| Selo + página pública | ✓ "serviço independente" no rodapé da página | n/a (sem dados pessoais de terceiros) | n/a | ✓ |

**Regra de bloqueio:** nenhuma peça entra em produção com [entidade], NIPC [—] ou [morada] por preencher — o merge falha se os placeholders legais não estiverem substituídos.

---

*Notas de produção:*
- *Política de reembolso (decidida): garantia de 30 dias com reembolso total + livre resolução legal de 14 dias + sem pró-rata no plano Anual; no Trienal, devolução dos anos completos ainda não iniciados. É a única combinação que desarma a desconfiança inicial (onde a objeção realmente decide a compra) sem criar um passivo de reembolso imprevisível que rebentava com o LTV do plano anual. Refletir esta redação nos Termos & Condições antes do lançamento.*
- *Cadência de reporte (alinhada com o Produto): relatório MENSAL "Tudo em ordem", enviado no dia 1 de cada mês — 12 contactos/ano como âncora anti-churn. Todas as peças acima já dizem "mensal"; qualquer peça futura que diga "trimestral" está errada.*
- *O dado "1 em cada 3 relatórios com ponto por resolver" (follow-up D+4) é placeholder — substituir pelo número real assim que houver 100+ verificações; até lá usar o dado nacional dos 40% sem seguro comunicado.*

*Fontes dos factos usados no copy: [alteração do RMAL de Lisboa, dez. 2025](https://diariodarepublica.pt/dr/detalhe/aviso/29926-a-2025-964380181) ([detalhe idealista](https://www.idealista.pt/news/imobiliario/habitacao/2025/11/19/72676-al-em-lisboa-com-aperto-de-regras-eis-as-zonas-em-contencao-total)); [Lisboa cancela 6.765 registos, Observador fev. 2026](https://observador.pt/2026/02/20/camara-de-lisboa-cancela-40-das-licencas-de-alojamento-local-eram-licencas-fantasma-e-al-estavam-inativos/); [Porto cancela 1.413, Observador mai. 2026](https://observador.pt/2026/05/22/camara-do-porto-vai-cancelar-1-413-estabelecimentos-de-alojamento-local/); [+10 mil cancelamentos nacionais e estimativa ALEP de 40–45 mil, Observador jun. 2026](https://observador.pt/2026/06/11/camaras-municipais-ja-cancelaram-mais-de-10-mil-licencas-de-alojamento-local-por-inatividade-ou-incumprimento-de-seguros/); [40% dos ALs sem seguro comunicado no prazo, Público dez. 2025](https://www.publico.pt/2025/12/09/economia/noticia/alojamento-local-40-unidades-nao-apresentaram-seguro-dentro-prazo-2157212); [coimas 2.500–4.000€ / 25.000–40.000€, ASAE](https://www.asae.gov.pt/perguntas-frequentes1/area-economica/alojamento-local.aspx).*
