# CheckAL — Estado do projeto (fonte de verdade)

> Atualizado 09/07/2026. Software **100% construído e testado**, tudo **LIVE-GATED** (nada
> envia/cobra/liga sem as chaves do dono). **1202 testes verdes, 0 skips.** ~16k linhas de app.

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
