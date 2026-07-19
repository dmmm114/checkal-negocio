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
3. **Base URL no `deploy/polaris/agente.env`:**
   `CHECKAL_GATE_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443`
   (sem isto o digest escreve "aprovação manual: item <id>" — fail-closed, nada parte)
4. **Teste ponta-a-ponta:** com um item pendente na fila,
   `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python manage.py maestro-gate-token --fila-id <id>`
   → abre o `url` no telemóvel → Aprovar/Rejeitar → confirma com `maestro-fila` que saiu de pendente.
