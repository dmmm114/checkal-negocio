# Posts automáticos na Página de Facebook — Spec + Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Pedido do dono 19/07 (noite): "no Facebook quero também que publique na página do perfil que vai ser criada".

**Goal:** O COMUNICADOR redige também posts para a Página de Facebook da marca (`post_pagina`); após o gate do dono, o PUBLICADOR publica-os via Graph API oficial — live-gated até existirem `CHECKAL_FACEBOOK_PAGE_ID`/`CHECKAL_FACEBOOK_PAGE_TOKEN`.

**Decisões de desenho:**
- Canal novo `POST_PAGINA` no linter: R4 (fonte oficial) + **R5 (divulgação de IA — publicação automática não tem adoção manual do dono; linha curta "Preparado com apoio de IA." satisfaz o regex R5)**; sem R7/R8/R9; proibições globais aplicam-se. LINTER_VERSAO bump. (Divergência deliberada do POST_SOCIAL, que é colado pelo dono em nome próprio — documentar no código; reversível por decisão do advogado.)
- `post_pagina`: risco "alto" ⇒ camada 4 (publicação pelo sistema). Flag `CHECKAL_AUTO_PUBLICAR_POST_PAGINA` (fail-closed False) simétrica à dos artigos.
- Publicação = função injetável no publicador (`publicar_facebook(mensagem, *, page_id, token, http=None) -> str`), POST `https://graph.facebook.com/v21.0/{page_id}/feed` com `message`+`access_token` via httpx (dependência existente). Sem config ⇒ item fica `aprovado` intacto com nota no relatório ("facebook por configurar") — NÃO `falhado` (sem churn de backoff). Em MODO_TESTE: ensaio mostra o post, zero rede.
- Drain do publicador: tipos += `post_pagina`; `_processar` ramo novo. `post_grupo` continua no-op (dono cola).
- Dashboard: label "post de página" no mapa de tipos do painel (deploy + restart).

---

### FB1: Linter `POST_PAGINA` + config + tipo no comunicador (TDD)
- Testes: proibições globais aplicam; R4 exigido; **R5 exigido** (post sem divulgação reprova; com "Preparado com apoio de IA." aprova); R7/R8/R9 não disparam; guarda de regressão POST_SOCIAL continua isento de R5. Config: `CHECKAL_FACEBOOK_PAGE_ID`/`_PAGE_TOKEN` default "" + predicado `facebook_ativo()` (padrão `*_ativo()` do config.py) + `AUTO_PUBLICAR_POST_PAGINA` False. Comunicador: `_TIPOS_COMUNICADOR` += `"post_pagina": ("post_pagina", "alto")`; `_peca_comunicador` ganha param de canal (POST_SOCIAL para grupo, POST_PAGINA para página — despacha por `--tipo`); choices do parser. Testes de enfileirar (camada 4, payload) + reprovado sem divulgação.
- Commit: `feat(facebook): canal POST_PAGINA (com divulgação IA) + config live-gated + tipo do comunicador`

### FB2: Publicador publica na página + prompt do comunicador
- `app/publicador.py`: `publicar_facebook(...)` injetável (httpx.post, valida `id` na resposta, levanta em erro HTTP); `_processar` ramo `post_pagina`: sem `config.facebook_ativo()` ⇒ skip com nota (item mantém-se aprovado — implementar o skip DEVOLVENDO o item ao estado aprovado antes do processador? NÃO: mais simples e correto — filtrar os tipos do drain dinamicamente: só incluir `post_pagina` nos `tipos` do drain quando `facebook_ativo()`; assim o item nem é servido/leased); com config ⇒ publica e o drain marca `feito`. Pré-passo auto-aprovação: se `AUTO_PUBLICAR_POST_PAGINA`, auto_aprovar pendentes `post_pagina` com linter_ok (filtro por tipo OBRIGATÓRIO). Ensaio: renderiza/mostra o texto do post no relatório. Testes com http fake: publica e marca feito; sem config o item aprovado fica intacto (não drenado); erro HTTP ⇒ falhado+backoff; ensaio não toca rede.
- Prompt comunicador (2 árvores): passo novo — além dos posts de grupo, redigir 1 post para a Página (voz da marca, mesma matéria-prima, terminar com a linha "Preparado com apoio de IA." e link para o site quando fizer sentido) e `enfileirar --tipo post_pagina`. Nota: sem página configurada os posts aprovados aguardam — normal.
- Commit: `feat(facebook): publicador publica post_pagina via Graph API (live-gated) + prompt`

### FB3: Dashboard + handoff + verificação
- Dashboard: `FILA_TIPO_PT` += `post_pagina: "post de página"` (app.js); deploy+restart pelo procedimento; verificação snapshot ok.
- Handoff `2026-07-19-facebook-HANDOFF.md`: criar a Página; Meta App (Business) com permissão `pages_manage_posts`; obter Page ID + token de página de longa duração (passos: Graph API Explorer → user token com pages_manage_posts → /me/accounts → page access token → estender); `CHECKAL_FACEBOOK_PAGE_ID`/`_PAGE_TOKEN` no agente.env; testar com 1 post aprovado em modo live. Nota: tokens de página expiram/invalidam-se com mudança de password — renovação é manutenção do dono.
- Suite completa; smoke ensaio; revisão final (opus chega — âmbito contido); ESTADO-DO-PROJETO uma linha.
