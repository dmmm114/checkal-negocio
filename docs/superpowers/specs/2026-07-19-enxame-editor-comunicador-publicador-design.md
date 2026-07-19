# Design — EDITOR, COMUNICADOR e PUBLICADOR (expansão do enxame CheckAL)

> Aprovado pelo dono a 19/07/2026 (diálogo de brainstorming + auditoria paralela de 7
> leitores sobre o código real). Este documento é a fonte de verdade do desenho; o plano
> de implementação deriva daqui.

## 1. Objetivo e âmbito

Evoluir o enxame de agentes do CheckAL de governança/monitorização para **trabalho ativo
de mercado** nas três frentes escolhidas pelo dono: conteúdo/SEO contínuo, redes sociais
e comunidade, e produto/conversão. Isto materializa o canal n.º 1 do GTM canónico
(consent-first: tráfego SEO + grupos de Facebook + widget de check gratuito), que **não
depende do parecer RGPD** — ao contrário do cold email, que continua hard-gated.

**Fora de âmbito** (decisões do dono, 19/07/2026):
- Go-live do site getcheckal.com/checkal.pt (deploy inicial, DNS, env vars do Pages) —
  tratado à parte pelo dono.
- Parcerias com contabilistas/gestores (canal GTM n.º 2) — não entra nesta iteração.
- Cold email — permanece como está (gated por `pode_enviar_frio_global()`).

**Decisões do dono registadas (19/07/2026):**
1. Autonomia **gradual**: tudo nasce atrás do portão 1-clique; tipos de artefacto podem
   ser promovidos a auto-publicação por config, um a um, quando houver historial limpo.
2. Redes sociais em modo **"agente redige, dono publica"** (grupos de FB não permitem
   automação legítima; contas pessoais automatizadas violam os termos da Meta).
3. `CLOUDFLARE_API_TOKEN` autorizado para deploy headless (âmbito mínimo: só Pages, só o
   projeto `checkal`); criado na fase 3. A regra "sem API keys" do Dashboard_Polaris
   refere-se a chaves da Anthropic — não se aplica.
4. Canal `POST_SOCIAL` do linter **sem** frase de divulgação de IA: o dono revê, edita e
   publica em nome próprio (assistência de escrita). Artigos do site levam sempre a
   frase canónica `DIVULGACAO_IA` (AI Act art. 50) via R5.
5. `CHECKAL_TETO_DIARIO_EUR` sobe de 25 para **40** (disjuntor indicativo; subscrição
   Max, sem custo real de API).

## 2. Panorama da arquitetura

Dois agentes LLM novos + um módulo determinista + o elo de aprovação em falta:

| Peça | Natureza | Papel |
|---|---|---|
| **EDITOR** ✍️ | Agente LLM (enxame) | Conteúdo SEO contínuo para o site, segundo o GTM |
| **COMUNICADOR** 📣 | Agente LLM (enxame) | Posts/respostas para grupos de FB, prontos a colar |
| **PUBLICADOR** ⚙️ | Módulo determinista (`checkal-cron@`) | Pós-aprovação: render → sitemap → commit → deploy |
| **Portão 1-clique** | Rota web CheckAL | Resgate dos tokens [Aprovar]/[Rejeitar] do digest |

Princípio inviolável mantido: **o LLM propõe; quem executa a ação irreversível é código
determinista, depois do portão humano** (ou de auto-aprovação explicitamente promovida
pelo dono — ver §6.3). Nomes seguem a convenção do `AGENTES-ENXAME.md` (ofício em PT,
papel único). O PUBLICADOR fica **fora** da lista de agentes (é backbone, como as
campanhas) para não diluir a fronteira LLM vs determinista.

## 3. EDITOR

### 3.1 Missão e cadência
Timer 2×/semana (proposta: seg/qui 05:00, `Persistent=true`, `RandomizedDelaySec=180`).
Por passagem: escolhe e redige **um** conteúdo do plano GTM, por esta prioridade:
1. Página-gatilho de evento regulatório fresco (motor perpétuo GTM §3, SLA <72h);
2. Páginas-pilar evergreen da SPEC-FASE1 (`checkal/app/SPEC-FASE1-AQUISICAO.md`):
   `seguro-al` (a mais forte), `registo-rnal`, `regulamentos-al`, `cancelamento-al`;
3. Páginas por concelho "Alojamento Local em [concelho]" (GTM §6 M2), por ordem de
   registos ativos.

### 3.2 Fluxo da passagem
1. `python manage.py editor estado` — idempotência (o que já está na fila/publicado).
2. `python manage.py editor plano` — leitura agregada da BD (eventos regulatórios
   frescos, contagens por concelho) para escolher o próximo conteúdo. Read-only via
   `_sessao_leitura()` (PRAGMA query_only=ON).
3. Redige o artigo como **JSON estruturado**: `{slug, titulo, meta_description,
   seccoes: [{h2, corpo_md}], fontes: [{url, titulo, data}], data_publicacao,
   tipo_pagina: gatilho|pilar|concelho}`. Nunca HTML completo — o template é do
   PUBLICADOR.
4. `python manage.py editor lint --stdin` — pré-verificação (exit 0 mesmo reprovado; é
   consulta).
5. `python manage.py editor enfileirar --tipo artigo_seo --stdin` — o corpo entra por
   stdin (convenção da casa), grava `EventoAgente(tipo='conteudo_proposto', payload)` e
   `fila.enfileirar(...)` com `ref_tipo='evento_agente'`. Linter corre DENTRO do
   enfileirar (fail-closed); reprovado ⇒ JSON `{aprovado:false, violacoes}` + exit 1.

### 3.3 Classificação na fila
- `tipo='artigo_seo'`, `risco='alto'` ⇒ `camada_risco=4` (publicação) enquanto não for
  promovido (§6.3). Canal do linter: `PAGINA_PUBLICA` (R4 fonte oficial, R6 grounding
  pleno, R7 disclaimer, R5 divulgação IA — a frase canónica entra no rodapé do template).
- Grounding do R6: o subcomando `enfileirar` alimenta `PecaOutward.url_fonte`/`excerto`
  a partir do JSON (`fontes[0]`), para os números dos artigos-pilar (31%, 48,6%, 64,5%
  do ANALISE-SEGURO) não gerarem falsos "valores órfãos".

### 3.4 Análise de conversão — ADIADA (fase 4)
O `/api/evento` do site só faz `console.log` (logs efémeros do Cloudflare Pages) — **não
há analytics persistidos para ler**. Pré-requisitos da fase 4: site live + Workers
Analytics Engine ligado (`[[FALTA]] n.º 8` do `site/DECISOES.md`). Até lá o EDITOR não
tem passagem de conversão.

## 4. COMUNICADOR

### 4.1 Missão e cadência
Timer diário 07:10 (antes do digest das 07:50, para os posts do dia irem no digest).
Por passagem: 1–3 posts para grupos de Facebook no espírito GTM §6 M3 — "partilhar
alertas de gatilho como serviço público" ("resumo do novo regulamento do Funchal em 5
pontos", com link para a fonte oficial), **nunca anúncio**. Sem gatilho fresco: gatilhos
estruturais ("o seguro não consta no RNAL", "freguesia em contenção") ou no-op limpo —
não inventa trabalho.

### 4.2 Fluxo da passagem
`comunicador estado` → leitura agregada de gatilhos → redige posts → `comunicador lint
--stdin` → `comunicador enfileirar --tipo post_grupo --stdin`. Mesmo padrão de
armazenamento do EDITOR (EventoAgente + fila). JSON do post: `{titulo_interno,
corpo_texto, grupo_alvo_sugerido, fonte_url, gatilho_ref}`.

### 4.3 Classificação na fila e canal novo do linter
- `tipo='post_grupo'`, `risco='medio'`, **`camada_risco=2` explícita** no enfileirar
  (override do mapa automático `medio→3`): quem publica é sempre o dono, manualmente —
  o item é um rascunho para humano, não uma ação irreversível do sistema.
- **Canal novo `Canal.POST_SOCIAL`** em `app/compliance/linter.py` (sobe
  `LINTER_VERSAO`; documentar no dossier de defesa):
  - Mantém TODAS as proibições globais: R1 (nunca "ilegal/sem seguro/incumprimento" na
    voz própria), R2 (não-prescritivo, Lei 10/2024), R3 (coima nunca como ameaça
    individualizada), R6_COIMA_MOLDURA (valores € só na moldura canónica de
    `config.COIMA`), RT_COIMA_PROXIMIDADE, RT_ESTADO_JURIDICO.
  - Exige R4 (link para fonte oficial) — é a essência do formato "serviço público".
  - Dispensa R7 (disclaimer), R8 (opt-out), R9 (identificação) — regras de email/site.
  - **R5 não se aplica** (decisão do dono §1.4): posts revistos e publicados
    manualmente pelo dono não levam frase de IA.
  - Regra editorial no prompt (não mecanizável): identificar-se como fundador do
    CheckAL quando relevante, nunca astroturf; respeitar as regras de cada grupo.

## 5. Portão 1-clique (elo em falta — corrige gap pré-existente)

Auditoria confirmou: `fila.aprovar()`/`fila.rejeitar()` **não têm chamador em produção**
(só testes). O digest promete links [Aprovar]/[Rejeitar] mas não há endpoint de resgate.
Sem isto, tudo o que o EDITOR produzir fica pendente para sempre.

- Rotas novas na app web do CheckAL (`app/web`): `GET /gate/{item_id}?token=…` (página
  de confirmação com resumo do item) e `POST /gate/{item_id}/aprovar|rejeitar` (chama
  `fila.aprovar/rejeitar` com o token; `decidido_por='dono'`). Regra autor≠aprovador já
  imposta por CHECK na BD. Token = o gerado por `maestro-gate-token` (single-use: a
  decisão invalida-o porque o item deixa de estar `pendente`).
- Beneficia TODO o enxame (era o "missing piece" do live-mode já identificado antes
  deste design).

## 6. PUBLICADOR

### 6.1 Forma e invocação
Subcomando determinista `python manage.py publicador` + instância `checkal-cron@publicador`
com `checkal-cron-publicador.timer` (a cada 15 min; no-op limpo e barato quando não há
itens aprovados). **Não passa pelo `correr-agente.sh` nem pelo claude -p** — zero LLM.
Nota: a allowlist do wrapper proíbe Write/Edit aos agentes LLM; é por isso que a
publicação TEM de ser determinista — nenhuma revisão do `--disallowedTools` é necessária.

### 6.2 O que faz por cada item `aprovado` de tipo `artigo_seo`
1. **Render**: template Python (stdlib, sem dependências novas) derivado do
   `site/porto.html` — head completo (canonical `https://www.checkal.pt/<slug>`
   extensionless, OG, JSON-LD Article `inLanguage pt-PT`), header/footer/nav/denominação
   legal/CSP centralizados no template (elimina o drift manual que a auditoria apontou).
   Rodapé do artigo: bloco Fontes (links oficiais), disclaimer "informação, não
   aconselhamento jurídico" e frase canónica `DIVULGACAO_IA`. Proibido `<script>` inline
   (CSP `script-src 'self'`).
2. **Sitemap**: acrescenta/atualiza `<url>` em `site/sitemap.xml` (loc www extensionless,
   `lastmod` do dia, changefreq monthly, priority 0.8) — hoje é manual e sem validação.
3. **Git**: commit + push no repo **aninhado** `site/.git` (remote
   `dmmm114/checkal-site`, branch main) — não no repo pai.
4. **Deploy**: SEMPRE o pipeline de staging do `site/README.md` passo 2 — rsync para
   `stage/dist` excluindo `*.md`/`tools`/`functions`, `functions/` copiada como pasta
   IRMÃ de `dist`, `npx wrangler pages deploy dist --project-name checkal --branch main`
   com `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` do ambiente, e **validação da
   linha «Uploading Functions bundle»** no output (senão os /api/* dão 405). O passo 5
   do README (contraditório — deploy direto de `site/`) fica corrigido no README como
   parte desta obra.
5. **Estados**: usa `fila.drain(...)` — sucesso ⇒ `feito`; exceção ⇒ backoff exponencial
   até `morto` (mecânica já existente).

**Ciclo de vida dos `post_grupo`**: o dono marca no portão 1-clique — [Aprovar] =
"publiquei/vou publicar" e [Rejeitar] = descartado. O PUBLICADOR consome `post_grupo`
aprovados como **no-op de registo** (nada a publicar — o humano já o fez) e marca-os
`feito`, fechando o ciclo e mantendo o KPI da fila limpo.

### 6.3 Gates e autonomia gradual
- **Só consome itens `aprovado`** — "publicação nunca sai do gate humano" mantém-se.
- **`CHECKAL_MODO_TESTE=True` ⇒ dry-run**: renderiza, valida sitemap e staging, NÃO faz
  push nem deploy; regista o resultado como evento. O PUBLICADOR adota este gate
  explicitamente (hoje nenhum gate cobre deploy web).
- **Autonomia gradual** (config nova, fail-closed, padrão `_env_bool` default False):
  `CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO`, `CHECKAL_AUTO_PUBLICAR_POST_GRUPO` (este último
  sem efeito prático — posts são sempre colados pelo dono — existe por simetria e para
  o painel). Quando True para um tipo, um passo pré-drain do PUBLICADOR auto-aprova
  itens `pendente` desse tipo com `linter_ok=True`: escreve `Aprovacao` com
  `decidido_por='auto'` (CHECK `autor<>decidido_por` satisfeito) e `estado='auto_aprovado'`
  → tratado como `aprovado` pelo drain. Implementa o caminho `auto_aprovado` previsto no
  schema mas nunca construído. Compatível com AGENTES-ENXAME §5: "só ações de risco
  mínimo já provadas, promovidas por config pelo dono".
- Env vars mudam por edição do `agente.env` pelo dono + restart — sem UI de toggling
  nesta iteração (YAGNI; a tabela de config em BD fica para quando doer).

### 6.4 Correções necessárias em `fila.py` (retrocompatíveis)
- `drain()` ganha parâmetro opcional `tipos: set[str] | None` — a query atual seleciona
  TODOS os itens `aprovado` (o parâmetro `agente` não filtra nada); sem isto o
  PUBLICADOR apanharia e marcaria `a_correr` itens de cold_email/winback de outros
  consumidores.
- `drain()` ganha `cap: int | None` próprio — o cap atual está acoplado a
  `config.CAMPANHA_CAP_DIARIO` (semântica de campanhas de email, sem relação com
  publicar páginas).
- Default `tipos=None`/`cap=None` preserva o comportamento atual (testes existentes
  intocados).

## 7. Infraestrutura (wrapper, units, timers, saúde)

Passos exatos (confirmados pela auditoria do runner):
1. Prompts novos `checkal/prompts/editor.txt` e `comunicador.txt` no padrão da casa
   (identidade single-shot headless, PT-PT, lista fechada de subcomandos, gates como
   facto, regra de dados/minimização, "na dúvida, escala"). Manter a árvore editorial
   `agentes-polaris/prompts/` em sincronia (são DUAS árvores; o wrapper só lê
   `checkal/prompts/`).
2. `deploy/bin/correr-agente.sh`: instâncias `editor` e `comunicador` nos DOIS `case`
   (passo determinista/PROMPT_FILE/ARG_LLM; e TOOLS =
   `Read,Bash(python manage.py editor estado),Bash(python manage.py editor plano),Bash(python manage.py editor lint:*),Bash(python manage.py editor enfileirar:*)`
   e análogo para comunicador). Sem passo determinista pré-LLM (como o angariador).
   Atenção à semântica do trap (o 2.º trap SUBSTITUI o 1.º — repetir limpeza completa).
   Nomes de instância SEM hífen (a agregação de custo faz `split('-')[0]`).
3. Units/timers em `deploy/systemd/`: `checkal-editor.timer` (Mon,Thu 05:00) e
   `checkal-comunicador.timer` (diário 07:10) sobre `checkal-agente@%i.service`;
   `checkal-cron-publicador.timer` (`*:0/15`) sobre `checkal-cron@publicador.service`.
   Atualizar `deploy/polaris/instalar.sh` MANTENDO as exclusões existentes
   (gestor-suporte, cron-suporte, token ficam off).
4. Allowlist em 3 sítios sincronizados: case TOOLS do wrapper, docstring do `manage.py`,
   prompts.
5. `manage.py`: novos grupos `editor {estado,plano,lint,enfileirar}` e
   `comunicador {estado,lint,enfileirar}`; mapa tipo→(tipo_fila,risco) próprio (não
   reutilizar `_TIPOS_CONTEUDO` do angariador); `maestro-retry` choices += editor,
   comunicador; tuplo do `_cmd_maestro_saude` += editor, comunicador.
6. Healthchecks: checks novos `agente-editor`, `agente-comunicador` (slug derivado da
   instância) + check do cron publicador.
7. Prompt do MAESTRO: atualização editorial (novos executores na lista, novos tipos na
   fila, portão 1-clique agora funcional).
8. Tetos: `CHECKAL_TETO_DIARIO_EUR=40` no `agente.env` (editado pelo dono; o ficheiro
   nunca é lido por agentes). `TETO_CENTS` do dashboard (`app/checkal.py`) tem de
   acompanhar (2500→4000).

## 8. Cockpit (Dashboard_Polaris — Sala de Controlo)

- `agent-os/app/checkal.py`: entradas novas no dict `AGENTES` (editor ✍️, comunicador 📣,
  com `instancias` e `timers` corretos) — cartões, detalhe, badge e animações herdam
  automaticamente. PUBLICADOR entra nas **Máquinas de fundo** (`MAQUINAS`), não em
  `AGENTES`.
- `agent-os/app/checkal_acoes.py`: `ACORDAR_INSTANCIA` += editor/comunicador;
  `UNITS_RESET` += as units novas; `MAQUINAS_EXEC` += publicador.
- `instalar-acoes-checkal.sh`: linhas enumeradas novas no sudoers
  (`checkal-agente@{editor,comunicador}.service`, `checkal-cron@publicador.service` +
  reset-failed) — sem isto os botões respondem 503. Reinstalar uma vez com sudo.
- **Painel "Para publicar"**: endpoint novo `GET /api/checkal/fila` (separado do
  snapshot de 10s para não inchar o payload nem forçar re-renders) — lê `revisao_itens`
  pendentes de `post_grupo` (e preview de `artigo_seo`) com corpo completo via join a
  `eventos_agente` (payload JSON). Botão copiar = `navigator.clipboard.writeText`
  client-side. A BD do CheckAL continua **estritamente read-only** para o dashboard;
  aprovar/rejeitar vive no portão web do próprio CheckAL (§5), nunca aqui.
- UI: título "O enxame · 4 agentes" → "6 agentes"; verificar `.agente-grid` com 6
  cartões. Deploy pela regra da casa: editar fonte → copiar para `/home/diogo/agent-os/`
  → restart só se `app/*.py` mudou.

## 9. Faseamento

| Fase | Entrega | Critério de pronto |
|---|---|---|
| **1 — Agentes a produzir** | Canal POST_SOCIAL no linter; tipos novos; subcomandos editor/comunicador; prompts; wrapper/units/timers; Healthchecks; edições maestro | Passagens reais dos 2 agentes a encher a fila; testes verdes |
| **2 — Dono a decidir** | Portão 1-clique na app CheckAL; painel "Para publicar" + cartões novos + sudoers no dashboard | Dono aprova/rejeita do digest; copia posts do painel |
| **3 — Publicação real** | PUBLICADOR completo (render, sitemap, git, deploy staging, gates) em dry-run sob MODO_TESTE; config AUTO_PUBLICAR; token Cloudflare criado pelo dono | Dry-run limpo ponta-a-ponta; com site live + MODO_TESTE off, primeira página publicada após clique |
| **4 — Conversão (adiada)** | Passagem de análise de conversão do EDITOR | Pré-requisitos: site live + Workers Analytics Engine |

Fase 1 funciona mesmo com o site offline (a fila enche, nada é publicado). As fases são
independentes e cada uma tem valor por si.

## 10. Testes

Estilo da casa (suite atual: 1344 verdes, 0 skips; tudo sem rede, sob MODO_TESTE):
- Linter: canal POST_SOCIAL — proibições globais disparam; R4 exigido; R5/R7/R8/R9 não
  disparam; LINTER_VERSAO subiu.
- Subcomandos: editor/comunicador estado/plano/lint/enfileirar (stdin, exit codes 0/1/2,
  JSON de uma linha, sessões read-only vs governação).
- fila: `drain(tipos=…)` filtra; `cap` desacoplado; defaults preservam comportamento
  (testes existentes passam intocados); auto-aprovação escreve Aprovacao
  `decidido_por='auto'` e respeita o CHECK.
- Portão web: aprovar/rejeitar com token válido/ inválido/ reutilizado; autor≠aprovador.
- PUBLICADOR: render determinista (golden file), sitemap idempotente, dry-run sob
  MODO_TESTE não toca em git/rede (mocks), validação «Uploading Functions bundle».
- Dashboard: snapshot com 6 agentes; `/api/checkal/fila` read-only.

## 11. Riscos aceites e pendências externas

- **Analytics sem persistência** — bloqueia a fase 4; decisão do dono ligar o Workers
  Analytics Engine quando tratar do go-live.
- **Apex checkal.pt fora do Cloudflare** (nameservers PTISP) — links novos usam
  `www.checkal.pt` até à migração (já é a convenção do site).
- **Denominação legal em disputa** (`[[FALTA]] n.º 2`: "Lda." vs "Unipessoal") — o
  template do PUBLICADOR centraliza a denominação num único sítio; corrigir lá quando o
  dono fechar a questão.
- **Minutas legais do site** (privacidade/termos aguardam advogado) — assunto do
  go-live, fora deste âmbito.
- **DPA da Anthropic** (`CHECKAL_ANTHROPIC_DPA_OK`) — os 2 agentes novos ficam sujeitos
  ao mesmo gate de arranque que os 4 atuais (estado atual do flag: o que estiver no
  `agente.env`, que nunca lemos).
- **Pressão no teto diário** — mitigada pela subida para 40€; monitorizável no cockpit.
