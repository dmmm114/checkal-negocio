# Fase 3 — passos manuais do dono

1. Instalar o timer: `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
   (o publicador corre 15/15 min; em MODO_TESTE=True é ensaio read-only — renderiza
   para checkal/data/publicador-ensaio/ e NÃO toca em git/Cloudflare)
2. (Opcional, recomendado p/ robustez headless) Token Cloudflare de âmbito mínimo
   (Pages:Edit no projeto checkal) no agente.env:
   `CLOUDFLARE_API_TOKEN=...` e `CLOUDFLARE_ACCOUNT_ID=8425658e8ce8ed9cb42a39a6de2e1105`
   — HOJE o wrangler autentica pelo teu OAuth login (funciona, mas pode expirar).
3. Ir live: quando quiseres publicação real, `CHECKAL_MODO_TESTE=false` no agente.env
   ⚠️ isto abre TODOS os seams live-gated do CheckAL (Stripe, Telegram, digest LLM…),
   não só o publicador — decisão de go-live global, não do publicador.
4. Autonomia gradual (mais tarde, com historial): `CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO=true`
   — artigos com linter_ok passam a publicar sem clique. post_grupo é sempre manual.
5. Primeiro artigo real: aprova no portão (link do digest) → próxima passagem publica →
   confirma em https://checkal.pages.dev/{slug} e no sitemap.

## Recuperação de itens `falhado`

O drain não faz auto-retry: se a publicação de um artigo falhar (ex.: wrangler
em baixo), o item fica `falhado` e PARA. Recuperar = repor o estado a
`aprovado` na BD (sqlite3 …/checkal.db "UPDATE revisao_itens SET estado='aprovado',
nao_antes_de=NULL, lease_ate=NULL WHERE id=<id> AND estado='falhado'") — a
passagem seguinte retoma (o commit vazio já não bloqueia; push+deploy são
idempotentes). Se já corrigiste a causa-raiz e queres orçamento de falhas
fresco, acrescenta `tentativas=0` ao SET (senão um item em tentativas=4 morre
à próxima falha). Itens `morto` (5 falhas) merecem investigação antes de repor.
