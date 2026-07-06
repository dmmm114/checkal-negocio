# FASE 1 · WF2 — Templates de email (branded HTML) + estrutura de envio

> Tokens de marca: ver `SPEC-FASE1-WEB.md`. Copy real em `../COPY-VENDAS.md` (não inventar).
> Emails = HTML com **CSS inline** (compat. cliente de email) + versão texto. Header de marca por
> **HTML/CSS** (wordmark "CheckAL" + ✓ verde `#12B76A`) — sem depender de imagem/SVG externa.

## Disciplina
LIVE-GATED: zero rede nos testes (o cliente de envio é injetado; `envio.obter_enviador`/`cold_email`
já existem e são gated). TDD. Cada email leva SEMPRE: identificação do remetente, rodapé legal
(Cosmic Oasis, Lda. · morada [placeholder]), **opt-out 1-clique** (`checkal.pt/remover?e=&t=`) e, nos
transacionais de alerta, o disclaimer **"informação, não aconselhamento"**. Anti-alucinação: o corpo
do alerta vem da camada IA (FDS4, já validado) — o template só o embrulha; NÃO inventa factos/valores.

## Módulos

### `app/emails/base.py` + `templates/email_base.html` + `tests/test_email_base.py`
Layout base (CSS inline): header (wordmark CheckAL + ✓ verde), corpo, rodapé (legal + morada +
opt-out + link privacidade). `render_email(nome_template, **ctx) -> EmailRenderizado{assunto, html, texto}`
— renderiza + garante rodapé/opt-out presentes. Estados 🟢🟡🔴 como blocos reutilizáveis. Testa: rodapé
+ opt-out + remetente sempre presentes; html e texto gerados.

### `app/emails/transacional.py` + templates + `tests/test_emails_transacional.py`
Templates (copy de COPY-VENDAS.md):
- `boas_vindas` — boas-vindas + linha dos 3 checks + link do selo + (nota: PDF do Relatório Inicial
  anexado pelo onboarding). Assunto: "✅ O teu AL passou no check — bem-vindo ao CheckAL".
- `alerta_estado` — 🟢/🟡/🔴 (registo/seguro/regulamento); corpo determinístico OU da IA; disclaimer;
  CTA. Assunto conforme MARCA.md ("🔴 ALERTA CheckAL — o teu AL «{nome}» falhou o check: {facto}").
- `relatorio_mensal` — "Junho: o teu AL passou no check" + resumo do valor entregue.
- `confirmacao_consentimento` — double opt-in (link `/confirmar?token=`).
Testa cada um: assunto correto, estado certo, disclaimer nos alertas, opt-out.

### `app/emails/dunning.py` + templates + `tests/test_emails_dunning.py`
`renovacao_d30`, `aviso_d7`, `falha_pagamento` (D+3/D+7, link Stripe p/ atualizar cartão),
`cancelado_final` (D+21, "o teu AL deixou de estar monitorizado"). Copy de COPY-VENDAS.md/AUTOMACAO §5.
Testa assuntos + presença dos elementos.

### `app/emails/prospeccao.py` + templates + `tests/test_emails_prospeccao.py`  ⚠️ PARECER-GATED
A sequência de **cold B2B** (copy de COPY-VENDAS.md). Remetente `getcheckal.com`. Cada email: nota RGPD
(Anexo 1 do BRIEFING-JURISTA), opt-out, remetente identificado. NÃO envia (o `cold_email` do FDS6 é que
gere o envio, gated). Só o TEMPLATE. Testa: nota RGPD + opt-out presentes; usa getcheckal.com.

### Wire (agente de integração)
Ligar os templates aos pontos de envio já existentes: `app/onboarding.py` (boas_vindas + relatório),
`app/alertas_estado.py` + `app/ia/alerta.py` (alerta_estado), `app/dunning.py` (dunning), `app/campanhas`
(prospeccao), `app/web/consentimento.py` (confirmacao_consentimento). SUBSTITUIR HTML ad-hoc pelos
templates, preservando verdes os testes. Gerar 1 **email de alerta de exemplo renderizado** em
`../ANEXO3-alerta-exemplo.html` (para o briefing do jurista). e2e: cada tipo renderiza com marca+opt-out;
suite completa verde.

## Estrutura de envio (nota, não código novo pesado)
Canal A = Resend (`app/envio`, já feito) + DNS de checkal.pt. Canal B = `getcheckal.com` SMTP
(`app/campanhas/cold_email`, gated) + warm-up/throttle (`CAMPANHA_CAP_DIARIO`). Documentar em
`../RUNBOOK-ENVIO.md` (DNS SPF/DKIM/DMARC, warm-up, o que ligar por ordem).
