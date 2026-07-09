# Contexto do projeto — CHECKAL (ex-Radar AL / ex-Salvaguarda)

> Memória do projeto para qualquer sessão futura. Estado a 02/07/2026: **negócio completamente idealizado, validado, com marca decidida pelo dono — pronto para execução.**

## O que é

Subscrição (49€/ano) que vigia o registo RNAL, o seguro obrigatório e os regulamentos municipais de cada Alojamento Local português, com alertas interpretados por IA. Réplica do modelo Radar Marca (INPI) aplicada ao AL. Operação 100% automatizada, veículo: Cosmic Oasis, Lda.

## Dossier (lê PLANO-NEGOCIO.md primeiro — tem o índice e a folha de pressupostos canónica)

| Ficheiro | Conteúdo |
|---|---|
| PLANO-NEGOCIO.md | Master: sumário, validação, mercado, pressupostos canónicos, riscos/planos B, roadmap |
| MARCA.md | Marca CheckAL: as 3 rondas de naming, mitigações, identidade, checklist |
| PRODUTO.md | Tiers, taxonomia de alertas, camada IA, selo, onboarding |
| PRICING.md | Tabela canónica, unit economics, faturação (secção 4 = cenário upside) |
| GTM.md | **Plano operacional canónico** (cenário B), gatilhos, KPIs |
| COPY-VENDAS.md | Carta, emails, landing, alertas — copy final pronto |
| AUTOMACAO.md | Pipeline, BD, stack, 6 sprints de construção |
| LEGAL.md | RGPD canal a canal, T&C, INPI, checklist bloqueante |
| radar-al-handoff.md | Histórico (superado) |

## Decisões fechadas — NÃO relitigar

- **Marca: CheckAL** ✓ · checkal.pt (livre a 02/07/2026; registar + variantes chekal.pt/checal.pt) · tagline "O teu AL? Check." · selo "CheckAL ✓ — AL Verificado · Verified listing" · escolha do dono após 3 rondas (~60 nomes; o júri preferia Radar AL 27/30 pela família com Radar Marca — o dono escolheu CheckAL 23/30 pelo punch e encaixe no funil; Radar AL fica como reserva estratégica). checkal.com está parqueado: NÃO comprar já; getcheckal.com (livre) é o satélite de email frio. Linguagem de estados: "passou no check ✓ / falhou o check 🔴".
- **Preços (IVA incl.):** 49€/ano · 119€/3 anos · +19€/ano por AL adicional · Portfólio 149€ (4–10) / 299€ (11–25) / 499€ (26–50) · garantia 30 dias · regime normal IVA desde o dia 1
- **Meta 1:** 1.500€/mês líquidos = 490 clientes ativos (M12–M15) · Meta 2: 5.000€/mês = 1.630 clientes
- **Canais (REORDENADO jul/2026, consent-first):** prioridade = (1) widget consent-first + (2) parcerias contabilistas/gestores (canal de dia 1) → depois (3) email frio B2B só a coletivas com email genérico e (4) carta a singulares só em teste. Email/SMS a singulares a frio = PROIBIDO
- **🚦 PORTÃO BLOQUEANTE (novo):** parecer de jurista RGPD sobre reutilizar o RNAL para prospeção ANTES de qualquer cold (risco de finalidade incompatível, art. 5/1/b; CNPD sanciona). Se negativo → consent-first puro (já é o plano). + **Seguro RC profissional/E&O antes de escalar** (a limitação a 49€ pode ser afastada como cláusula abusiva B2C) + disclaimer "informação, não aconselhamento" em cada alerta
- **Coimas para copy (ASAE):** singular 2.500–4.000€ · coletiva 25.000–40.000€ (nunca usar "7.500€")
- **Cadências:** página individual clientes = diária · varrimento nacional = 2×/semana · SLA T&C ≤7 dias · nunca prometer "no próprio dia"
- **Stack:** Python/FastAPI + Postgres, Hetzner ~8€/mês, Stripe + InvoiceXpress (série CKL), Resend, Haiku 4.5 triagem + Sonnet redação via Batch API

## Validação técnica (feita, não repetir)

- API viva: `webservices.turismodeportugal.pt/RNT_External/rest/RNT/list_RNAL?Concelho=X` → JSON completo com contactos (Lisboa: 11.854 registos, 63s, 100% email)
- Página individual `rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=X` é server-rendered (GET simples chega; tem bloco do seguro RC)
- Mercado: 120k+ registos, ~70k titulares; 56% singular/44% coletiva; multi-AL detêm 56% dos registos; Açores fora do RNAL (fase 2)

## Estado da construção (a 09/07/2026)

**Software 100% construído** — ver `ESTADO-DO-PROJETO.md` (fonte de verdade). Núcleo de compliance
+ FDS 1–6 + swap TOConline + Fase 1 (website consent-first, emails, dashboard admin) + deploy
(docker/caddy/systemd) + runbook. **1202 testes verdes, 0 skips.** Tudo LIVE-GATED (nada envia/cobra
sem chaves). Marca final aplicada (✓AL badge). Parecer RGPD recebido e traduzido em decisões
(`LEGAL-PARECER-DECISOES.md`): cold DESLIGADO por código; motor = consent-first + parcerias.

- ✅ [feito] Parecer jurista RGPD · amostra 200 páginas seguro (`ANALISE-SEGURO.md`: 64,5% em
  falta/caducado) · construção dos 6 sprints · marca · G4 resolvido empiricamente (breaker entrega
  cancelamentos reais) · lista nacional de 289 concelhos.

## Próximos passos (o que falta — depende do dono)

0. 🚦 [BLOQUEANTE cold] Advogado VALIDA as minutas (`REGISTO-ATIVIDADES-ART30.md`, `LIA-COLD-GERAL.md`,
   `ANEXO1-*`, privacidade/T&C) + os 3 pontos do parecer (base legal do email/art.10.º n.º 5 —
   forte indício de que É público; transferências internacionais; atividade reservada via `ANEXO3`)
1. Contas/chaves (RUNBOOK-GO-LIVE §0): TOConline (série→sequence_id), Stripe, Anthropic, Resend+DNS;
   registar chekal.pt/checal.pt/getcheckal.com; cotar seguro E&O; angariar 3–5 contabilistas-piloto
2. Submeter marca INPI (nominativa CHECKAL 35/42/45 + mista com o logo)
3. Deploy (RUNBOOK-GO-LIVE) → ensaio test→live (pagar-me a mim próprio + fatura AT) → ligar consent-first
4. Lançamento M1: gatilhos Porto (1.413 cancelamentos) e Funchal (regulamento) como conteúdo→widget
5. [pós-validação e §4 do parecer] só então ligar o cold `geral@` (opt-out, semi-manual). Singulares: nunca.
