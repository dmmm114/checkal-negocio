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

## Próximos passos (por ordem)

0. 🚦 [BLOQUEANTE] Marcar consulta com jurista de proteção de dados (reutilização do RNAL) — antes de qualquer cold
1. Registar checkal.pt + chekal.pt + checal.pt + getcheckal.com — urgente (e decidir radaral.pt/.com defensivos); cotar seguro E&O; angariar 3–5 contabilistas-piloto
2. Submeter marca INPI nominativa CHECKAL classes 35/42/45 (~194€) — antes de qualquer envio público
3. Amostrar 200 páginas individuais RNAL → medir preenchimento do bloco seguro (decide copy do pilar seguro — PRODUTO.md §2)
4. Construção: 6 sprints de fim-de-semana (AUTOMACAO.md §7) — MVP vendável no FDS 3
5. Checklist legal bloqueante antes da 1.ª campanha (LEGAL.md §7)
6. Lançamento M1: gatilhos Porto (1.413 cancelamentos, mai/2026) e Funchal (regulamento, jun/2026)
