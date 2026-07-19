# CheckAL — Estado do projeto (fonte de verdade)

> Atualizado 12/07/2026. Software **100% construído e testado**, tudo **LIVE-GATED** (nada
> envia/cobra/liga sem as chaves do dono). **1344 testes verdes, 0 skips.** ~16k linhas de app.
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
