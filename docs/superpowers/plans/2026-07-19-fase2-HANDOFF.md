# Fase 2 — passos manuais do dono

> O portão 1-clique está pronto no código; falta servi-lo e ligá-lo ao digest.

1. **Instalar/ativar o serviço web** (sudo interativo):
   `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
   (idempotente para o resto; adiciona o checkal-web.service em 127.0.0.1:8600)
2. **Expor o portão via tailscale** — escolhe UMA:
   - **Funnel (público, recomendado se o telemóvel não tem Tailscale):**
     `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8600`
     (fechar: `sudo tailscale funnel --https=8443 off`)
   - **Serve (só tailnet, mais contido):**
     `sudo tailscale serve --bg --https=8443 http://127.0.0.1:8600`
   ⚠️ Em ambos os casos expões a app CheckAL INTEIRA nessa porta, incluindo /admin —
   confirma que o login admin está protegido (ADMIN_PASSWORD/SECRET_KEY no agente.env)
   antes de abrir. O gate em si é seguro por token.
3. **Base URLs no `deploy/polaris/agente.env`** (ambas):
   `CHECKAL_GATE_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443`
   (sem isto o digest escreve "aprovação manual: item <id>" — fail-closed, nada parte)
   `CHECKAL_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443`
   (as páginas públicas não-gate — /selo, /confirmar — geram links absolutos a partir
   desta; o default é localhost:8000 e sairia partido para quem clica de fora)
4. **Teste ponta-a-ponta:** com um item pendente na fila,
   `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python manage.py maestro-gate-token --fila-id <id>`
   → abre o `url` no telemóvel → Aprovar/Rejeitar → confirma com `maestro-fila` que saiu de pendente.

## Recomendação de segurança (opcional, mas boa ideia)

O `checkal-web.service` herda o `agente.env` inteiro — a app pública fica com TODOS
os segredos (Telegram, SMTP, ifthenpay, TOConline) em processo. Least-privilege:
criar um `deploy/polaris/web.env` só com `CHECKAL_SECRET`, `CHECKAL_ADMIN_PASSWORD`,
`CHECKAL_BASE_URL` e `CHECKAL_GATE_BASE_URL` (+ o que a BD precisar), e trocar o
`EnvironmentFile=` da unit para ele. Se quiseres, pede-me e eu preparo a mudança.
