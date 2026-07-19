# Página de Facebook — passos manuais do dono

> O pipeline está pronto e testado: Comunicador redige → aprovas no portão →
> Publicador publica na página via Graph API. Live-gated: sem os 2 valores no
> agente.env, os posts aprovados aguardam intactos (nem são drenados).

1. **Criar a Página** de Facebook do CheckAL (perfil de marca).
2. **Criar uma App na Meta** (developers.facebook.com → Create App → Business).
3. **Obter o Page Access Token de longa duração**:
   a. Graph API Explorer → seleciona a tua app → User Token com permissões
      `pages_manage_posts` + `pages_read_engagement` → Generate.
   b. Troca por token de longa duração (~60 dias):
      `GET /oauth/access_token?grant_type=fb_exchange_token&client_id={app-id}&client_secret={app-secret}&fb_exchange_token={user-token}`
   c. Com esse token: `GET /me/accounts` → copia o `access_token` da tua página
      (Page tokens obtidos de user tokens de longa duração NÃO expiram, salvo
      mudança de password/permissões) e o `id` da página.
4. **No `deploy/polaris/agente.env`:**
   `CHECKAL_FACEBOOK_PAGE_ID=<id>` e `CHECKAL_FACEBOOK_PAGE_TOKEN=<token>`
5. **Teste**: aprova um post_pagina pendente no portão → na passagem seguinte do
   publicador (15/15 min, com MODO_TESTE=false) o post aparece na página.
   Em MODO_TESTE, o ensaio lista-o no relatório sem publicar.

## Notas
- Manutenção: o token invalida-se se mudares a password/2FA da conta ou as
  permissões da app — se os posts pararem com "falhado", renova o token (passo 3).
- (Mais tarde) `CHECKAL_AUTO_PUBLICAR_POST_PAGINA=true` publica sem clique —
  recomendo historial limpo primeiro, como nos artigos.
- Divulgação de IA: os posts da página terminam com "Preparado com apoio de IA."
  (publicação automática ≠ posts de grupo que colas em nome próprio); se o
  advogado dispensar, ajusta-se o linter/prompt.
