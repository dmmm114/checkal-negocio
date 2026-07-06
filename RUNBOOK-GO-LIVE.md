# CheckAL — Runbook de go-live

> Sequência para pôr o CheckAL no ar em **checkal.pt**, por ordem. O código está todo
> feito e **live-gated**: nada envia/cobra/liga sem as chaves. Acende-se peça a peça.
> **O cold (Canal B) NÃO liga aqui** — só depois dos pré-requisitos do `LEGAL-PARECER-DECISOES.md §4`.

## 0. Pré-requisitos (contas/chaves) — o que só tu obténs
- **TOConline:** Empresa → Dados API → `OAUTH_CLIENT_ID/SECRET/URL` + `API_URL` (link 72h); fazer o
  **consentimento OAuth** uma vez; **criar a série** → dá o `document_series_id`; confirmar Cosmic Oasis/IVA.
- **Stripe:** conta + `STRIPE_SECRET_KEY` (test+live) + webhook em `https://checkal.pt/webhooks/stripe`
  → `STRIPE_WEBHOOK_SECRET`; criar **Payment Links/Prices** (anual 49€, trienal 119€, portfólios) +
  **Customer Portal**. Adicionar `invoice.paid` aos eventos do webhook (renovações — gotcha G1).
- **Anthropic:** `ANTHROPIC_API_KEY`.
- **Resend:** conta + `RESEND_API_KEY` + acesso ao **DNS de checkal.pt**.
- **Domínios:** confirmar checkal.pt (✅); registar chekal.pt, checal.pt, getcheckal.com.
- **Servidor:** Hetzner CX32 (Docker instalado).

## 1. DNS de checkal.pt
- `A  @  → <IP do servidor>` · `A  www → <IP>` (Caddy trata do HTTPS automático).
- **Email transacional (Resend):** colar os registos **MX/SPF/DKIM/DMARC** que a consola da Resend gera
  (recomenda-se remetente `alertas@send.checkal.pt` — subdomínio dedicado; ver de-risco Resend).

## 2. Servidor + deploy
```bash
ssh root@<IP>
git clone <repo> /opt/checkal && cd /opt/checkal/deploy
cp ../checkal/.env.example ../checkal/.env      # preencher TODAS as chaves + CHECKAL_MODO_TESTE=true no início
echo "POSTGRES_PASSWORD=<gerar>" > .env          # senha do Postgres do compose
docker compose up -d --build                     # app + postgres + caddy (HTTPS auto)
docker compose exec -T app python -c "import app.db as d; d.init_db()"   # cria as tabelas
```
Verificar: `https://checkal.pt/saude` → `{"ok": true}` · `https://checkal.pt` → landing.

## 3. Crons (systemd timers)
Ver `deploy/systemd/README.md` — instalar `checkal@.service` + os `.timer` (varrimento, dre, dunning,
suporte, backup, token). `sudo systemctl enable --now checkal-*.timer`.

## 4. Observabilidade + backups
- **Healthchecks.io:** criar um check por cron; pôr os slugs/URL em `HEALTHCHECKS_*` no `.env`.
- **UptimeRobot:** monitorizar `https://checkal.pt/saude`.
- **Backups:** o cron `backup` faz `pg_dump`; confirmar destino (Storage Box) em `BACKUP_*`.

## 5. Ensaio em modo de teste → live
1. Com `CHECKAL_MODO_TESTE=true` + chaves **test** da Stripe/TOConline: fazer um checkout de teste →
   confirmar que cria **cliente + fatura-recibo com ATCUD** (TOConline) + email de boas-vindas (Resend).
   **Smoke-test da série (crítico):** confirmar `atcud` real na fatura de teste **antes** de faturar a sério.
2. Passar `CHECKAL_MODO_TESTE=false` + chaves **live** → **pagar-me a mim próprio** → 1.º cliente real +
   fatura AT no email. **A partir daqui vende-se legalmente.**

## 6. Ligar o motor de aquisição (consent-first)
- Widget "faz o check grátis" já no ar (landing). Confirmar o fluxo: verificar → **consentimento
  granular** (alertas vs ofertas) → double opt-in → sequência.
- Publicar **política de privacidade + T&C** (páginas já existentes); preencher `[NIPC]/[morada]`.
- Angariar **3–5 contabilistas-piloto** (canal de dia 1, sem qualquer risco RGPD).

## 7. 🚦 Cold (Canal B) — só depois de TUDO isto (`LEGAL-PARECER-DECISOES.md §4`)
Confirmar a base legal do email (art. 10.º n.º 5) + LIA escrita + Anexo 1 corrigido + contratos art. 28.º
+ transferências + lista de supressão/DGC. Só então `CHECKAL_PARECER_RGPD_OK=true`, e mesmo assim
**semi-manual** (revês e disparas). Nunca a singulares/ENI.

## Gatilhos de lançamento (M1)
Porto (1.413 cancelamentos, mai/2026) e Funchal (regulamento, jun/2026) — usar como mote de conteúdo
que drena tráfego para o widget (consent-first), não como lista de cold.
