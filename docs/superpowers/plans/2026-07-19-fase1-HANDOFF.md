# Fase 1 (EDITOR + COMUNICADOR) — passos manuais do dono

> Tudo o resto está commitado e testado (suite: 1578 verdes). Estes passos exigem
> sudo interativo ou decisões tuas — nenhum agente os pode fazer por ti.

## ⚠️ Lê antes de ativar

**O gasto LLM começa no momento em que correres o instalador.** O `instalar.sh`
faz `enable --now`: o EDITOR corre na próxima seg/qui às 05:00 e o COMUNICADOR
todos os dias às 07:10 — passagens `claude -p` reais (subscrição Max), a encher
a fila de revisão. O único travão real é o gate DPA (`CHECKAL_ANTHROPIC_DPA_OK`),
que já está aberto no teu `agente.env`. Se quiseres adiar, corre o instalador e
depois `sudo systemctl disable --now checkal-editor.timer checkal-comunicador.timer`.

**Armadilha do teto matinal:** a ordem da manhã é editor (seg/qui 05:00) →
comunicador (07:10) → gestor (07:15) → digest (07:50, o último). Se o teto diário
estourar cedo, o PAUSA_LLM (que só limpa à meia-noite) mata as passagens
seguintes — e o digest é a primeira baixa quando saíres do modo teste. Daí o
passo 2.

## Passos

1. **Ativar as units** (sudo interativo):
   ```
   sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh
   ```
   Instala os 2 timers novos; os existentes são idempotentes; os DESLIGADOS
   (gestor-suporte, cron-suporte, token) continuam desligados.

2. **Teto diário → 40€** — em `deploy/polaris/agente.env` (ficheiro que os
   agentes nunca leem):
   ```
   CHECKAL_TETO_DIARIO_EUR=40
   ```
   Os defaults do código ficaram em 25/10 (disjuntor); com 6 agentes o valor
   operacional decidido é 40. (O `TETO_CENTS` do dashboard Agent OS acompanha
   na atualização do cockpit.)

3. **Healthchecks** (opcional — sem HC key o wrapper faz no-op): criar checks
   com slugs `agente-editor` e `agente-comunicador`.

4. **Primeira corrida de teste** (opcional, sem esperar pelo timer):
   ```
   sudo systemctl start checkal-agente@editor.service
   ```
   Depois vê a fila: `python manage.py editor estado` / `maestro-fila`.
   (Pelo dashboard, o botão "Acordar" destes 2 agentes só funciona depois de
   reinstalares o sudoers — passo incluído na atualização do cockpit.)

## O que fica para as fases seguintes

- **Fase 2**: portão 1-clique (aprovar/rejeitar na app CheckAL) + painel
  "Para publicar" no dashboard. Sem o portão, os artigos ficam `pendente`
  (os posts podes lê-los na fila e colar à mão entretanto).
- **Fase 3**: PUBLICADOR (render→sitemap→commit→deploy Cloudflare, dry-run em
  modo teste; precisa do teu `CLOUDFLARE_API_TOKEN` de âmbito mínimo).
- **Fase 4** (adiada): análise de conversão — precisa do site live + Workers
  Analytics Engine.
