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

## Estado da construção (a 12/07/2026)

**Software 100% construído** — ver `ESTADO-DO-PROJETO.md` (fonte de verdade). Núcleo de compliance
+ FDS 1–6 + swap TOConline + Fase 1 (website consent-first, emails, dashboard admin) + deploy
(docker/caddy/systemd) + runbook. **1344 testes verdes, 0 skips.** Tudo LIVE-GATED (nada envia/cobra
sem chaves). Marca final aplicada (✓AL badge). Parecer RGPD recebido e traduzido em decisões
(`LEGAL-PARECER-DECISOES.md`): cold DESLIGADO por código; motor = consent-first + parcerias.

- ✅ [feito] Parecer jurista RGPD · amostra 200 páginas seguro (`ANALISE-SEGURO.md`: 64,5% em
  falta/caducado) · construção dos 6 sprints · marca · G4 resolvido empiricamente (breaker entrega
  cancelamentos reais) · lista nacional de 289 concelhos.
- ✅ [feito 12/07] **Dossier do advogado v2 fechado** (`dossier-advogado/DOSSIER-CheckAL.html`,
  HTML print-ready → Imprimir→PDF; + `EMAIL-ADVOGADO.md`). 2 rondas do consultor + verificação
  adversária (workflow 3 lentes) resolvidas: colisão de "Anexo N" eliminada (rótulos de secção sem
  número; nota-ponte mapeia a numeração interna dos docs reproduzidos; **alerta = Anexo 3 canónico**),
  §8 de `LEGAL-PARECER-DECISOES.md` reescrito (teto = total pago em 24 meses **fixo**, SEM promessa de
  seguro E&O), parágrafo E&O removido de `termos.html §6`, nome/data preenchidos. Falta ao dono:
  `[NIPC]`/`[morada]`/`[telefone]` + nome do advogado. Reprodução: `scratchpad/montar_dossier.py`.
- ✅ [confirmado 12/07] **Canal cold já 100% construído e HARD-GATED** (FDS 6): filtro NIF 5/6 +
  genérico + descarte de singulares + opt-out DGC + triplo gate (`pode_enviar_frio_global()=False`
  por omissão) + domínio separado getcheckal.com. **196 testes do canal verdes.** NADA a construir;
  o que falta para disparar é EXTERNO (advogado, E&O, chaves SMTP getcheckal.com, feed DGC). O sistema
  **não materializa lista de envio nem faz scraping** (RATIONALE: "só filtro + prova"). A fatia do
  prefixo `geral@` não é o filtro — o filtro é o NIF; o portão continua a ser o advogado (reutilização).

## Próximos passos (o que falta — depende do dono)

0. 🚦 [BLOQUEANTE cold] Advogado VALIDA o **dossier v2 (PRONTO** — `dossier-advogado/DOSSIER-CheckAL.html`
   + `EMAIL-ADVOGADO.md`): as 5 minutas + os 3 pontos do parecer (base legal do email/art.10.º n.º 5 —
   forte indício de que É público; transferências internacionais; atividade reservada via alerta) + 4
   decisões. Falta ao dono: preencher `[NIPC]`/`[morada]`/`[telefone]` + nome do advogado, escolher, enviar.
1. Contas/chaves (RUNBOOK-GO-LIVE §0): TOConline (série→sequence_id), Stripe, Anthropic, Resend+DNS;
   registar chekal.pt/checal.pt/getcheckal.com; cotar seguro E&O; angariar 3–5 contabilistas-piloto
2. Submeter marca INPI (nominativa CHECKAL 35/42/45 + mista com o logo)
3. Deploy (RUNBOOK-GO-LIVE) → ensaio test→live (pagar-me a mim próprio + fatura AT) → ligar consent-first
4. Lançamento M1: gatilhos Porto (1.413 cancelamentos) e Funchal (regulamento) como conteúdo→widget
5. [pós-validação e §4 do parecer] só então ligar o cold `geral@` (opt-out, semi-manual). Singulares: nunca.

> **Próximo BUILD (não depende do advogado):** motor de aquisição **consent-first** — páginas-gatilho
> Porto/Funchal + pilares SEO + página de parceiros + one-pager PDF (spec pronta e parqueada em
> `checkal/app/SPEC-FASE1-AQUISICAO.md`). **Decisão do dono pendente (12/07):** (A) ligar o cold ao
> admin como botão-único *gated* vs (B) construir já o consent-first — **recomendação: B** (traz receita
> sem esperar pelo advogado; o cold está tão pronto quanto pode estar sem ele).
