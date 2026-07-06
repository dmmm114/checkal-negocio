"""Templates de email do CheckAL (FASE 1 · WF2, SPEC-FASE1-EMAILS).

Todos os emails do CheckAL — transacionais (Canal A, Resend) e de prospeção (Canal B,
getcheckal.com) — são compostos a partir da **base** deste pacote (`app.emails.base`):
HTML com CSS **inline** (compatibilidade com clientes de email) + versão texto, com
header de marca por HTML/CSS (wordmark "CheckAL" + ✓ verde) e um rodapé que garante
SEMPRE: remetente identificado, rodapé legal (Cosmic Oasis, Lda. · morada) e opt-out
1-clique. Este pacote NÃO envia — o envio vive nos seams `app.envio` / `app.campanhas`.
"""
