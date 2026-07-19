# CheckAL — Estado do projeto (fonte de verdade)

> Atualizado 19/07/2026. Software **100% construído e testado**, tudo **LIVE-GATED** (nada
> envia/cobra/liga sem as chaves do dono). **1616 testes verdes, 0 skips.** ~16k linhas de app.
> **Dossier do advogado v2 fechado** (`dossier-advogado/DOSSIER-CheckAL.html`) — ver secções no fim.

## O que está construído

| Camada | Módulos | Estado |
|---|---|---|
| **Compliance** (PASSO 0–3) | `app/compliance/*` (nif, email, minimização, opt-out DGC) | ✅ |
| **FDS 1** pipeline RNAL | `app/rnal/*` (ingest, schema, hashing, diffing 2-varrimentos, detalhe) | ✅ |
| **FDS 2** billing | `app/web/webhook_stripe`, `app/fulfillment`, `app/billing` | ✅ |
| **Faturação** | `app/faturacao/*` — **TOConline** (ativo, OAuth) + InvoiceXpress (reserva) | ✅ (série por criar) |
| **FDS 3** onboarding+selo | `app/onboarding`, `app/selo`, `app/alertas_estado` | ✅ (MVP vendável) |
| **FDS 4** regulatório+IA | `app/regulatorio/*`, `app/ia/*` (Haiku triagem + Sonnet, anti-alucinação) | ✅ |
| **FDS 5** fiabilidade | `app/breaker` (canários — entrega cancelamentos reais), `app/dunning`, `app/suporte`, `app/observabilidade`, `app/backups`, `app/crons` | ✅ |
| **FDS 6** campanhas | `app/campanhas/*` — cold **HARD-GATED** pelo parecer | ✅ (desligado) |
| **Fase 1 · Website** | `app/web` — landing+widget consent-first, preços, privacidade/T&C, selo, opt-out | ✅ |
| **Fase 1 · Emails** | `app/emails/*` — transacional, dunning, cold, todos com marca+opt-out | ✅ |
| **Fase 1 · Dashboard** | `app/web/admin/*` — overview, clientes, campanhas, alertas, compliance, leads | ✅ |
| **Deploy** | `Dockerfile`, `deploy/` (compose+Caddy+systemd), `manage.py`, `RUNBOOK-GO-LIVE.md` | ✅ |
| **Marca** | `marca-esbocos/Marca_final/` (✓AL badge) aplicada no site/emails/selo | ✅ |
| **Dados** | `data/concelhos.txt` (289 concelhos, varrimento nacional) | ✅ |

## Decisões legais encodadas (parecer RGPD)
Ver `LEGAL-PARECER-DECISOES.md`. **Motor = consentimento + parcerias.** Cold OFF
(`CHECKAL_PARECER_RGPD_OK=false`); email a singulares/ENI bloqueado por desenho. Consentimento
granular, conservação 6 meses, oposição absoluta, serviço = ferramenta informativa. Minutas:
`REGISTO-ATIVIDADES-ART30.md`, `LIA-COLD-GERAL.md`, `ANEXO1-nota-informacao-corrigida.md`,
`ANEXO3-alerta-exemplo.html`. **Bloqueador do cold quase fechado:** forte indício de que o art. 10.º
n.º 5 torna o email público — falta confirmação documental do advogado.

## Dossier do advogado (v2 — fechado 12/07/2026)
Artefacto final: **`dossier-advogado/DOSSIER-CheckAL.html`** (HTML único print-ready → Imprimir→PDF) +
`EMAIL-ADVOGADO.md` (email de acompanhamento). Pede ao advogado: validar **3 pontos** (fonte do email/
art. 10.º n.º 5; transferências internacionais; atividade reservada via alerta) + **5 minutas** + **4
decisões**. Fechado em 2 rondas do consultor + verificação adversária (workflow 3 lentes + 1 leitura):
- **Numeração de anexos:** NENHUMA secção usa "Anexo N" (colidia com a numeração interna dos docs
  reproduzidos). Nota-ponte na carta §5 mapeia «Anexo 1»=nota de informação (=Minuta 5), «Anexo 2»=
  consentimento, «Anexo 3»=alerta. **O alerta é o Anexo 3 canónico.**
- **Responsabilidade/seguro:** teto = **total pago nos 24 meses (fixo)**; **ZERO promessa de seguro E&O**
  em todo o dossier; parágrafo E&O condicional removido de `termos.html §6`; §8 de
  `LEGAL-PARECER-DECISOES.md` reescrito para bater certo (era "12–24 meses / apólice E&O já aplicada").
- Placeholders `[NIPC]`/`[morada]`/`[telefone]` + nome do advogado = só o dono preenche. `[data]` das
  minutas fica de propósito (guarda de publicação = sinaliza rascunho pendente).
- **Reprodução:** `scratchpad/montar_dossier.py` (renderiza as minutas via TestClient + junta os .md;
  precisa de `pip install markdown`).

## Canal cold — confirmado construído e desligado (12/07/2026)
O FDS 6 já implementa TODA a verificação; **NADA a construir**. Triplo gate em `pode_enviar_frio()`:
(1) `pode_enviar_frio_global()` (parecer + modo-teste OFF + SMTP cold), (2) núcleo compliance (coletiva
5/6 + genérico + descarte de singular), (3) oposição DGC/opt-out. Copy já com disclaimer + rodapé RGPD
(fonte, base legal, conservação 12m, direitos, CNPD) + opt-out 1-clique, sobre **getcheckal.com** (nunca
Resend). **196 testes do canal verdes; gate fechado por omissão.** O prefixo `geral@` NÃO é o filtro — o
filtro é o NIF (5/6); o portão é o advogado (reutilização do RNAL). Para disparar falta EXTERNO:
advogado→`CHECKAL_PARECER_RGPD_OK=true`, E&O, credenciais `COLD_SMTP_*`, feed DGC real.

## Descobertas empíricas (esta sessão)
- **Fatia endereçável cold:** 7.779 registos / ~1.914 empresas (10,7%) — nicho, complementar.
- **Pilar seguro** (`ANALISE-SEGURO.md`): **64,5% dos ALs têm o seguro em falta ou caducado** no
  registo público → é o check mais forte. Copy decidida.
- **G4:** um cancelamento real → página "não encontrado" (não há banner). Breaker recalibrado com
  **canários** (alvo não-encontrado + canário ativo = cancelamento confirmado). Fim do risco de
  nunca entregar cancelamentos reais.

## O que falta (só o dono destranca)
1. **Advogado** valida minutas + os 3 pontos abertos do parecer.
2. **Chaves/contas** (RUNBOOK §0): TOConline (série), Stripe, Anthropic, Resend+DNS; domínios; E&O; INPI.
3. **Deploy** (RUNBOOK) → ensaio test→live → **consent-first no ar** (widget + contabilistas).
4. Cold só depois da validação + `LEGAL-PARECER §4`, e sempre semi-manual.

## Honestidade
Nada foi enviado/cobrado/publicado — falta o deploy + chaves do dono. Documentos legais são
**minutas** (exigem advogado). Reconciliação v2 pendente: existem dois caminhos de composição de
email cold (`campanhas/motor` e `emails/prospeccao`) — irrelevante enquanto o cold está desligado.

---

## Sessão 18–19/07/2026 — Enxame de agentes construído e LANÇADO no Polaris

**O que existe agora (commits `a699a51`→`314a737`; 1558 testes verdes, 0 skips):**
a camada de 4 agentes single-shot (MAESTRO, ANGARIADOR, GESTOR-DE-CLIENTE,
SENTINELA-SERVIÇO) por cima do backbone determinista — linter fail-closed, fila de
aprovação 1-clique (autor≠aprovador), tetos de custo LLM com PAUSA_LLM, subcomandos
`manage.py`, prompts PT-PT, wrapper + units systemd nativas (cgroups reais no
`claude -p`), e a Fase G de pagamentos (IfThenPay + `/pagar` + série CKL, LIVE-GATED).
Arquitetura e decisões em `AGENTES-ENXAME.md`.

**Lançado a 19/07:** timers armados no Polaris (instalação isolada no projeto;
symlink `/home/diogo/checkal-polaris`; segredos em `deploy/polaris/agente.env`,
fora do git). 1.º varrimento nacional: **289/289 concelhos, 119.538 registos, 0
falhas**; os 119.538 eventos de bootstrap foram marcados `bootstrap_baseline` (a
prospeção parte de zero e só reage a diffs reais). Sentinela verde; angariador
provado de ponta a ponta com o modelo real (no-op limpo + escalação DGC vazia).

**Gates:** parecer RGPD e DPA abertos pelo dono (18/07; dados de singulares só com
opt-in — regra encodada nos prompts; canal postal admissível, moradas já retidas no
espelho `registos`). `CHECKAL_MODO_TESTE=true` — **nada envia, cobra ou publica**;
digests ficam na BD até haver bot Telegram + ensaio test→live.

**Honestidade:** os agentes trabalham e acumulam fila, mas nenhum email/fatura/
publicação saiu nem pode sair por código. Pendentes externos: chaves IfThenPay
(pedidas), getcheckal.com + SMTP cold, TOConline (série CKL + smoke-test),
Telegram, feed DGC, E&O. Pendentes de build: endpoint de aprovação 1-clique e
deploy web do FastAPI (`/pagar`/callback) — antes de ativar pagamentos.

## Sessão 19/07/2026 (tarde) — Enxame de AQUISIÇÃO: 6 agentes, portão 1-clique, PUBLICADOR

**Fase 1 — agentes de mercado (spec+planos em `docs/superpowers/`):** o enxame passou
de 4 para **6 agentes**: EDITOR (artigos SEO consent-first, JSON estruturado, 2×/sem)
e COMUNICADOR (posts "serviço público" para grupos de FB, camada 2 — o dono cola à
mão, diário 07:10). Canal novo `POST_SOCIAL` no linter (sem frase de IA por decisão
do dono; R4 obrigatório), subcomandos `editor`/`comunicador` no manage.py, prompts
nas 2 árvores, wrapper + timers. Tetos recalibrados (defaults 25/10; operacional 40).

**Fase 2 — portão 1-clique (o elo que faltava):** `fila.aprovar/rejeitar` ganharam o
1.º chamador real: rotas `/gate/{item_id}` GET/POST na app web (token = credencial,
constant-time sobre bytes, single-use, idempotente entre passagens da governança),
`maestro-gate-token` devolve `url` (CHECKAL_GATE_BASE_URL, fail-closed), digest com
URLs cruas clicáveis no Telegram, serviço `checkal-web.service` (uvicorn 127.0.0.1:8600;
exposição tailscale 8443 = passo do dono). Dashboard Agent OS: 6 cartões + painel
"Para publicar" (`GET /api/checkal/fila`, nunca expõe token) — EM PRODUÇÃO.

**Fase 3 — PUBLICADOR (o braço que publica):** `app/publicador.py` determinista:
render byte-fiel ao molde do site (frases canónicas importadas do linter; slug
whitelist anti-XSS/traversal; JSON-LD imune a `</script>`), sitemap idempotente,
drain filtrado por tipos com cap próprio, auto-aprovação opt-in fail-closed
(`auto_aprovado`, nunca `aprovado`), git+push no repo aninhado do site, deploy
Cloudflare via staging com wrangler PINADO e validação do bundle. Em MODO_TESTE é
**ensaio read-only** (não drena — nada se perde). Timer `checkal-cron@publicador`
15/15 min. E2E verificado (3 cenários PASS, zero escrita fora do esperado).

**Processo:** cada tarefa com implementador + revisão dupla + re-verificação
adversária; a revisão apanhou e fechou 2 XSS críticos, 1 bug de retry (commit vazio),
tokens não-ASCII (TypeError→fail-closed) e a rotação de tokens que matava os links
do digest. Handoffs do dono em `docs/superpowers/plans/2026-07-19-fase*-HANDOFF.md`.

## Sessão 19/07/2026 (noite) — 7.º agente EMBAIXADOR + atendimento pré-vendas

**EMBAIXADOR 🤵** (canal GTM n.º 2 — parcerias): deteção compliance-gated de
gestores multi-AL (SÓ coletivas 5/6 com email genérico, autoridade =
`nif.e_enderecavel`, opt-out cruzado, dedupe canónico por NIF; universo real:
423 candidatos 5+/1.024 2+) em `app/embaixador.py`; propostas B2B
(`proposta_parceria`, Canal.COLD, camada 4) na fila atrás do gate; timer Ter
10:00; 7.º cartão no dashboard EM PRODUÇÃO. Envio real fica atrás dos gates do
cold (parecer+SMTP) — handoff próprio.

**Atendimento pré-vendas**: categoria `pre_venda` na triagem (responde com tom
"inspetor amigo" + CTA check grátis; sensível continua a escalar SEMPRE), FAQ
alinhada à tabela canónica completa do PRICING, regex de salvaguarda refinada
(prescrição jurídica escala mesmo com qualificadores/plurais; descrição do
produto já não escala), bloco pré-vendas no prompt do gestor, opção
"comercial" no formulário do site (caixa comercial@ por criar — handoff).
Suite: 1650 verdes. Handoffs: `docs/superpowers/plans/2026-07-19-embaixador-HANDOFF.md`.

**Página de Facebook** (FB1-3): canal `POST_PAGINA` novo no linter (R4+R5
divulgação de IA obrigatória; sem R7/R8/R9), comunicador redige `post_pagina`
a par dos posts de grupo, publicador publica na página via Graph API
(`publicar_facebook`) — live-gated por `CHECKAL_FACEBOOK_PAGE_ID`/
`_PAGE_TOKEN` no agente.env (sem config, o item fica `aprovado` intacto, não
drenado); dashboard ganhou o label "post de página". Suite: 1675 verdes.
Handoff próprio: `docs/superpowers/plans/2026-07-19-facebook-HANDOFF.md`.
