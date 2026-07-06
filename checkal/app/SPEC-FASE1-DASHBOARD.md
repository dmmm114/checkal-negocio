# FASE 1 · WF3 — Dashboard admin (operação zero-touch)

> Tokens/marca: `SPEC-FASE1-WEB.md`. O painel do dono para ver e gerir tudo. Read-first;
> ações só as seguras (nada que ENVIE/COBRE a frio sem os gates). Autenticado.

## Disciplina
LIVE-GATED. TDD. Autoescape Jinja. Só o dono acede (`config.ADMIN_PASSWORD` + sessão assinada
`itsdangerous` + `config.SECRET_KEY`; `config.assert_seguro` já exige ambos em produção; sob pytest
relaxado). Nenhum botão dispara cold/pagamento — o cold mostra-se mas o disparo respeita
`config.pode_enviar_frio_global()` (parecer). Cada agente toca só nos seus ficheiros.

## Módulos

### `app/web/admin/auth.py` + `templates/admin/login.html` + `tests/test_admin_auth.py`
`GET /admin/login` (form) + `POST /admin/login` (password == `config.ADMIN_PASSWORD` → cookie de sessão
assinado, `Secure` em prod via `config.cookie_secure()`) + `GET /admin/logout`. Dependência FastAPI
`requer_admin` que protege todas as rotas `/admin/*` (401/redir login). Testa: sem sessão → bloqueado;
password certa → entra; errada → recusa; logout limpa.

### `app/web/admin/dashboard.py` + `templates/admin/{base_admin,overview,clientes,campanhas,alertas,compliance,leads}.html` + `tests/test_admin_dashboard.py`
Todas sob `requer_admin`. Lê a BD (só leitura, exceto marcações internas seguras):
- **`/admin` (overview):** nº clientes ativos, MRR estimado (de `PLANOS`), nº alertas enviados,
  nº opt-outs, nº leads (por estado), último varrimento + saúde dos crons (se registada).
- **`/admin/clientes`:** lista (email, plano, estado, nº AL, criado) + detalhe/histórico.
- **`/admin/campanhas`:** gatilhos → segmentos (cold_email / carta / suprimidos) + a **fila de
  aprovação** do cold. O botão "aprovar/disparar" fica **DESATIVADO** com aviso enquanto
  `config.pode_enviar_frio_global()` for False (mostra o porquê: parecer/pré-requisitos).
- **`/admin/alertas`:** fila de alertas + os **`desaparecido` pendentes de desambiguação** (revisão
  do dono; só informa, o breaker decide).
- **`/admin/compliance`:** log de **opt-outs** + **proveniências** (prova cold) + **consentimentos**
  (leads: texto+versão+timestamp+IP) — a prova para a CNPD, exportável (CSV).
- **`/admin/leads`:** prospects consent-first por estado (pendente/confirmado/removido).
Testa (TestClient, autenticado): cada página 200 com os números certos de dados semeados; o botão de
cold está desativado sob gate fechado; zero PII exposta indevidamente além do necessário à operação.

### Wire (agente de integração)
Montar o router admin em `criar_app` (prefixo `/admin`). base_admin.html com nav + a marca. Preservar
verdes todos os testes. e2e admin: login → overview → cada secção. Red-team: sem sessão nada acede;
o cold não dispara sob gate fechado; a exportação de compliance não vaza dados a não-autenticados;
CSRF nos POST (login/ações).

## Fora de âmbito
Envio real; automação do cold; métricas avançadas/gráficos (v2). Mantém-se simples e sólido.
