# Radar AL — Documento de Trabalho

> ⚠️ **SUPERADO a 02/07/2026.** Todos os pontos técnicos foram validados (API viva, página individual server-rendered, diffing trivial) e todas as decisões em aberto foram fechadas. O negócio chama-se agora **CHECKAL** (checkal.pt — livre à data). Ver o dossier completo: `PLANO-NEGOCIO.md` (índice), `MARCA.md`, `PRODUTO.md`, `PRICING.md`, `GTM.md`, `COPY-VENDAS.md`, `AUTOMACAO.md`, `LEGAL.md`. Este ficheiro fica como registo histórico do conceito.

> Handoff para continuar no Claude Code (Polaris). Reúne o conceito, a análise feita até aqui, os pontos por validar tecnicamente e as decisões de negócio em aberto.

---

## 1. Conceito

Réplica do modelo Radar Marca aplicada ao **Alojamento Local (AL)**: monitorização contínua do estado do registo + alterações regulatórias que afetem cada proprietário, vendida como subscrição.

A vantagem estrutural que faltava nas outras ideias exploradas (concursos públicos, insolvências) está presente aqui: **o dataset fonte expõe simultaneamente o produto a monitorizar E os contactos dos prospects**.

### Porque funciona (vs. ideias descartadas)

| Componente | Radar Marca | Radar AL |
|---|---|---|
| Dataset fonte | INPI | RNAL (Turismo de Portugal) |
| Contactos dos prospects | Nome + morada | Nome + email + telefone (públicos por lei) |
| O que monitoriza | Conflitos de marca | Estado do registo + regulamentos municipais + DRE |
| Custo de não detetar | Marca perdida | Licença cancelada, coima até 7.500€ |
| Concorrência | Baixa | Não encontrada (à data da análise) |
| Dimensão do mercado | ~1.675 prospects trabalhados | >120.000 registos ativos com email público |

### Fundamento legal dos contactos públicos
Art. 10º do DL 128/2014 obriga à divulgação pública da identificação dos titulares de exploração e respetivos contactos. Confirmado por inspeção direta de um registo (ver secção 3).

### Pressão regulatória (a dor que se vende)
- DL 76/2024: municípios passam a poder/dever regulamentar o AL (obrigatório acima de 1.000 registos no concelho) → dezenas de regulamentos municipais novos a sair.
- Áreas de contenção e de crescimento sustentável, reavaliadas no mínimo de 3 em 3 anos.
- "Limpeza" de registos em curso: municípios a notificar proprietários para submeter seguros; quem não responde perde o registo.
- Reapreciação geral dos registos anteriores a out/2023 prevista para 2030.

---

## 2. Fontes de dados e URLs

- **Registo individual** (estrutura previsível, número sequencial):
  `https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=114144`
  Trocar o `nr=` no fim acede a qualquer outro registo.

- **Pesquisa geral** (filtros por concelho, titular, nome do AL):
  `https://rnt.turismodeportugal.pt/RNT/Pesquisa_AL.aspx`

- **API REST** (apareceu nos dados abertos da CM Lisboa; deu timeout no teste via web, A CONFIRMAR no Polaris):
  `https://webservices.turismodeportugal.pt/RNT_External/rest/RNT/list_RNAL?Concelho=Lisboa`

### Exemplo de dados expostos num registo (RNAL 114144)
- Nome do alojamento, modalidade, capacidade, datas de registo/abertura
- Localização completa (morada, código postal, freguesia, concelho, distrito)
- **Titular**: qualidade (proprietário), NIPC/NIF, firma/nome, **contactos (2 telefones + email)**
- Estado do seguro de responsabilidade civil (companhia, apólice, validade) — quando preenchido

---

## 3. Pontos técnicos a VALIDAR no Polaris

Por ordem de prioridade:

1. **A API REST está viva?**
   Testar `list_RNAL?Concelho=...`. Se devolver a base por concelho, o diffing semanal fica trivial e barato. Se estiver morta, passar a scraping página a página.

2. **Scraping em volume aguenta?**
   ~120.000+ páginas. Avaliar rate limiting / bloqueio. Definir velocidade segura e tempo total de um varrimento completo.

3. **Deteção de novos registos / alterações.**
   Não foi encontrado feed/RSS/changelog público de "novos registos". A deteção tem de ser CONSTRUÍDA (mesmo padrão do Radar Marca/INPI):
   - **Método A — Snapshot + diffing**: raspar tudo periodicamente, comparar snapshots; novos = aparecem; alterações = mudam de estado.
   - **Método B — Sondagem da fronteira sequencial**: como os números RNAL são sequenciais, guardar o último número conhecido e testar só os acima na semana seguinte. Mais barato.

4. **Fontes regulatórias a cruzar** (para os alertas com valor):
   - DRE (regulamentos municipais de AL, portarias, decretos)
   - Áreas de contenção / crescimento sustentável comunicadas ao Turismo de Portugal
   - Validade do seguro obrigatório (campo no próprio RNAL)

---

## 4. Estrutura de pricing (em discussão)

### Aviso importante sobre o paralelo dos "10 anos"
O modelo dos 10 anos do Radar Marca NÃO transfere: ancora-se na validade legal do registo da marca. O registo de AL **não tem prazo de validade fixo** (é permanente enquanto cumpre requisitos). A única data periódica encontrada é a reapreciação de 2030 — única, não cíclica.

**Justificação correta para plurianual**: o risco no AL é permanente e imprevisível (não se sabe quando sai um regulamento ou uma notificação). Um produto cuja promessa é "nunca serás apanhado de surpresa" justifica cobertura contínua e longa de forma honesta — sem inventar uma âncora legal que não existe.

### Modelos analisados

**A — Plurianual pré-pago.** Ex.: 99€/3 anos ou 149€/5 anos.
- ✅ Cash à cabeça, zero churn, zero gestão de pagamentos (perfil low-touch).
- ❌ Não é receita recorrente real: para 1.500€/mês é preciso vender ~15-18 pacotes/mês *para sempre*. Para de vender = para a receita.

**B — Anual com renovação automática.** Ex.: 49€/ano.
- ✅ Recurring verdadeiro; base acumula ano após ano.
- ❌ Churn no momento da cobrança; débito automático a particulares em PT é frágil (cartões expirados, recusas) → exige dunning.

**Recomendação: anual com desconto plurianual opcional.**
Base 49€/ano + opção 119€/3 anos (vs. 147€). O proprietário passivo ("pagar e esquecer") leva o plurianual à cabeça; quem prefere anual paga anual. Captura cash de uns e recorrência de outros, e o desconto reduz churn nos clientes que menos se quer perder.

**Nível de preço**: 49€/ano é facilmente defensável. Custo de inação assimétrico — coimas até 7.500€ (pessoa coletiva) e, no limite, cancelamento do registo (perda do negócio inteiro). Margem para testar 39€–69€.

### Matemática do objetivo (1.500€/mês)
- A 15€/ano-equivalente... (recalcular conforme modelo final)
- A 49€/ano: ~370 clientes ativos para ~1.500€/mês de receita anualizada.
- A 20€/mês: 75 clientes. (Mas o utilizador prefere NÃO mensal.)
- Base de 120.000 prospects com email → mesmo a 0,3% de conversão = 360 clientes.

> NOTA: afinar esta secção depois de fechar o modelo. Os números acima misturam bases mensais/anuais e precisam de ser uniformizados.

---

## 5. Decisões de negócio em ABERTO

1. **Cliente-alvo primário** (condiciona todo o produto):
   - Proprietário individual de 1 AL → simplicidade, preço baixo, volume.
   - Gestor/empresa com vários ALs → dashboard, paga 10x mais, muito mais exigente.

2. **Modelo de pricing final** (ver secção 4).

3. **Motor de aquisição**:
   - Mercado imediato = 120.000 registos JÁ existentes (não depender de novos registos).
   - ⚠️ Ponto fraco real: o fluxo de *novos* registos hoje é baixo (contenção + limpeza → mais cancelamentos que aberturas). A aquisição deve trabalhar a base instalada desde o dia 1; a deteção de novidades serve a monitorização vendida, não a aquisição.
   - Canal: campanha postal/email no molde Radar Marca (templates de carta já existem).

4. **Estrutura societária**: decidir veículo (Cosmic Oasis? nova entidade?) e marca/INPI.

---

## 6. Próximos passos sugeridos

1. [Polaris] Testar a API REST `list_RNAL`. Vivo ou morto?
2. [Polaris] Se morto: prototipar scraper de 1 registo → validar extração de email/telefone/estado.
3. [Polaris] Medir tempo/risco de um varrimento completo (~120k registos).
4. Desenhar lógica de diffing (reaproveitar do pipeline INPI).
5. Fechar decisão de cliente-alvo + pricing.
6. Mapear fontes regulatórias (DRE, áreas de contenção) e desenhar a camada de interpretação por IA dos alertas.

---

## 7. Diferenciador com IA (Polaris)
Cada alerta entregue com interpretação automática — "este regulamento/portaria afeta o teu AL? Sim/Não e porquê" — em vez de um link cru para o DRE que o proprietário não sabe ler. É isto que separa o Radar AL de um simples scraper de avisos.
