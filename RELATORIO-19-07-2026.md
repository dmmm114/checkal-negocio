# CheckAL — Relatório da sessão de 19/07/2026 + mapa do que falta

> Para o Diogo: tudo o que foi construído hoje, como funciona, e a lista exata
> do que fica nas tuas mãos — por ordem, com comandos. Os 4 HANDOFFs detalhados
> estão em `docs/superpowers/plans/2026-07-19-*-HANDOFF.md`; isto é o mapa geral.

---

## 1. Resumo executivo

O enxame passou de **4 agentes de governança** para **7 agentes de negócio** com o
ciclo completo de aquisição a funcionar de ponta a ponta — tudo fail-closed,
tudo atrás do teu clique:

| Agente | Papel | Cadência |
|---|---|---|
| MAESTRO 🎩 | governa, arbitra, compõe o digest com links de aprovação | 3×/dia + digest 07:50 |
| ANGARIADOR 🎣 | aquisição cold (gated pelo parecer RGPD) | seg/qui + diário |
| GESTOR 🤝 | clientes + suporte (agora também **pré-vendas**) | diário |
| SENTINELA 🦉 | watchdog de integridade | 4×/dia |
| **EDITOR ✍️** | artigos SEO consent-first → fila | seg/qui 05:00 |
| **COMUNICADOR 📣** | posts p/ grupos (tu colas) + posts da Página (automáticos após gate) | diário 07:10 |
| **EMBAIXADOR 🤵** | parcerias: deteta gestores multi-AL, redige propostas B2B | Ter 10:00 |

Mais duas peças novas que fecham o ciclo:
- **Portão 1-clique** — as rotas `/gate` que faltavam: aprovas/rejeitas do
  telemóvel pelo link do digest (antes, o digest prometia botões que não existiam).
- **PUBLICADOR ⚙️** — determinista, sem LLM: quando aprovas um artigo, renderiza
  a página fiel ao site, atualiza o sitemap, faz commit e deploy no Cloudflare.
  Em modo teste é ensaio read-only (nada sai).

**Estado:** 51 commits hoje no repo principal (+3 no repo do site), suite a
**1675 testes verdes, 0 falhas**. Dashboard com os 7 cartões e o painel "Para
publicar" **já em produção**. Nada envia, publica ou cobra até correres os
passos da secção 5 — e mesmo depois, tudo passa pelo teu gate.

---

## 2. O que foi construído (por lote)

### Lote A — Fase 1: agentes de mercado (EDITOR + COMUNICADOR)
- Canal novo `POST_SOCIAL` no linter (posts de grupos: todas as proteções legais,
  sem regras de email, **sem frase de IA** — decisão tua: revês e publicas em nome próprio).
- Subcomandos `editor {estado,plano,lint,enfileirar}` e `comunicador {estado,lint,enfileirar}`
  — o `editor plano` lê a tua BD real (concelhos, eventos regulatórios frescos).
- Artigos como JSON estruturado (slug/título/secções/fontes com excerto para grounding).
- Prompts nas 2 árvores, wrapper com allowlist estrita, timers systemd, Healthchecks,
  Maestro atualizado. Tetos recalibrados (25/10 default; 40 operacional via env).

### Lote B — Fase 2: portão 1-clique + painel
- `GET/POST /gate/{item}` na app web (token = credencial; constant-time sobre
  bytes; single-use; **idempotente** entre passagens da governança — os links do
  digest da manhã não morrem à tarde).
- `maestro-gate-token` devolve URL pronto; digest envia URLs cruas (o Telegram
  auto-linka). `checkal-web.service` (uvicorn 127.0.0.1:8600) pronto a instalar.
- Dashboard: painel **"Para publicar"** (`GET /api/checkal/fila`) com corpo
  completo e botão copiar — **nunca** expõe o token de aprovação (provado com
  tokens-isco).

### Lote C — Fase 3: PUBLICADOR
- `app/publicador.py`: render byte-fiel ao molde do site (frases legais
  importadas do linter — o que é lintado = o que é publicado, incluindo meta
  descriptions e rótulos de links), slug com whitelist anti-XSS/traversal,
  JSON-LD imune a `</script>`, sitemap idempotente, mini-conversor de markdown.
- Passagem live: auto-aprovação opt-in (`auto_aprovado`, nunca `aprovado` —
  invariante preservado), drain filtrado por tipos com cap próprio, git+push no
  repo do site, deploy Cloudflare pelo pipeline de staging com wrangler pinado
  e validação do bundle. Retry robusto (commit vazio não bloqueia).
- Timer 15/15 min (`checkal-cron@publicador`); em `MODO_TESTE` = ensaio
  read-only para `data/publicador-ensaio/`. E2E verificado em 3 cenários.

### Lote D — EMBAIXADOR + atendimento pré-vendas
- `app/embaixador.py`: deteção em 2 passos (SQL pré-filtro + portão Python com
  as funções canónicas de compliance — só coletivas NIF 5/6 com email genérico,
  opt-out cruzado, dedupe canónico por NIF). Universo real: **423 candidatos
  com 5+ ALs** (1.024 com 2+; o maior tem 292 ALs).
- Propostas B2B (`proposta_parceria`, canal COLD, camada 4) → fila → teu gate.
  Comissão 20% como ponto de partida, "termos por escrito" sempre.
- Atendimento: categoria `pre_venda` na triagem ("quanto custa?" → resposta com
  a tabela canónica + convite ao check grátis; sensível escala SEMPRE); FAQ
  corrigida (faltavam os trienais); salvaguarda legal refinada (descrever o
  produto não escala; prescrição jurídica escala mesmo com qualificadores).
- Site: opção "Informações e preços (pré-venda)" → `comercial@checkal.pt`.

### Lote E — Página de Facebook (publicação automática)
- Canal `POST_PAGINA` no linter: fonte oficial obrigatória E divulgação de IA
  ("Preparado com apoio de IA." — publicação automática não tem a tua adoção
  manual; reversível se o advogado dispensar).
- O Comunicador redige também 1 post por passagem para a Página (voz da marca);
  aprovas no portão; o **Publicador publica via Graph API oficial** — live-gated:
  sem `CHECKAL_FACEBOOK_PAGE_ID`/`_PAGE_TOKEN` no agente.env, os aprovados
  aguardam intactos (nem são drenados). Token nunca aparece em logs/erros.
- `CHECKAL_AUTO_PUBLICAR_POST_PAGINA` (default false) para autonomia total mais tarde.

### Correções de dívida apanhadas pelo caminho
Fix dos locks da manhã commitado; tetos 5→25/2→10 com teste alinhado; README do
site corrigido (passo de redeploy que partia os `/api/*`); rotação de tokens do
digest; árvores de prompts 100% sincronizadas (o angariador editorial divergia).

---

## 3. O que o processo de verificação apanhou (antes de produção)

Cada tarefa passou por implementador + revisor de conformidade + revisor de
qualidade independentes, com re-verificação adversária. Apanhados e fechados:
- **2 XSS críticos** no render (slug em atributos/URLs; `</script>` via título no JSON-LD)
- **Bug de retry** do publicador (commit vazio bloqueava a recuperação de deploys falhados)
- **Tokens não-ASCII** → HTTP 500 em vez de falhar fechado (agora TokenInvalido)
- **Rotação de tokens** que matava os links do digest todos os dias às 11:50
- **TypeError latente** no wrapper de subprocess
- **6 formas de prescrição jurídica** que escapavam à salvaguarda do suporte
- Dezenas de imprecisões de docs/prompts (incluindo divergências entre árvores)

---

## 4. Estado técnico final

- **Repo `checkal-polaris`** (master): 51 commits hoje; suite **1675 verdes, 0 skips**.
  ⚠️ **55 commits à frente do origin** (github: dmmm114/checkal-negocio) — sem backup remoto do trabalho de hoje.
- **Repo `site/`** (main): 3 commits à frente do origin (README + contacto).
- **Dashboard Agent OS**: em produção (100.72.204.114:8100, funnel 443) com 7
  cartões + painel "Para publicar"; fonte e deployment sincronizados.
- **Specs/planos/handoffs**: `docs/superpowers/` (4 specs, 5 planos, 4 handoffs).
- **Fonte de verdade atualizada**: `ESTADO-DO-PROJETO.md` (3 secções novas de hoje).

---

## 5. O QUE FALTA — o teu mapa, por ordem

### 5.1 Ativação imediata (~20 min, precisa de sudo interativo)

- [ ] **Backup primeiro (recomendo vivamente):** `cd /home/diogo/checkal-polaris && git push origin master && git -C site push origin main`
- [ ] `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
      → ativa TUDO de uma vez: timers do editor/comunicador/embaixador/publicador
      + o serviço web do portão. ⚠️ O gasto LLM dos agentes novos começa aqui
      (próximas passagens: seg/qui 05:00 editor, diário 07:10 comunicador, Ter
      10:00 embaixador). Em modo teste nada sai para o mundo — só enche a fila.
- [ ] `deploy/polaris/agente.env`: `CHECKAL_TETO_DIARIO_EUR=40` +
      `CHECKAL_GATE_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443` +
      `CHECKAL_BASE_URL=https://polaris.tail2f0d3e.ts.net:8443`
      (depois: `sudo systemctl restart checkal-web`)
- [ ] `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8600`
      → o portão fica clicável do telemóvel. (⚠️ antes: confirma que
      `CHECKAL_ADMIN_PASSWORD`/`CHECKAL_SECRET` estão no agente.env — o funnel
      expõe a app toda, incluindo /admin. Alternativa só-tailnet: `tailscale serve`.)
- [ ] `cd "…/Dashboard_Polaris" && sudo ./instalar-acoes-checkal.sh`
      → botões "Acordar" dos 3 agentes novos no dashboard.
- [ ] (Opcional) Healthchecks: criar checks `agente-editor`, `agente-comunicador`,
      `agente-embaixador`.

**Depois disto:** os agentes produzem para a fila, o digest (quando fores live)
traz links clicáveis, e tu aprovas do telemóvel. Teste rápido sem esperar:
`sudo systemctl start checkal-agente@editor.service` e vê a fila no dashboard.

### 5.2 Ligações de email (quando quiseres — "as ligações ficam para mim")

- [ ] **IMAP do apoio@** no agente.env → ativa o atendimento automático:
      `sudo systemctl enable --now checkal-cron-suporte.timer checkal-gestor-suporte.timer`
      (em modo teste, o cron autónomo é no-op; os rascunhos vêm da passagem do gestor)
- [ ] **Criar caixa `comercial@checkal.pt`** (o formulário do site já aponta para lá)
- [ ] **`RESEND_API_KEY` + `CONTACTO_REMETENTE` + `CHECKAL_API_ORIGIN`** nas env
      vars do Cloudflare Pages → o formulário de contacto e o widget passam a entregar
- [ ] **Página de Facebook**: criar a Página + App na Meta e colar
      `CHECKAL_FACEBOOK_PAGE_ID`/`_PAGE_TOKEN` no agente.env — passos exatos em
      `docs/superpowers/plans/2026-07-19-facebook-HANDOFF.md`
- [ ] **SMTP cold (getcheckal.com)** → habilita o envio real de propostas do
      EMBAIXADOR e do cold do angariador — mas só com o resto dos gates abertos (5.3)

### 5.3 Go-live global (a decisão grande — um interruptor, tudo de uma vez)

- [ ] `CHECKAL_MODO_TESTE=false` no agente.env abre TODOS os seams: digest real
      no Telegram, publicador a publicar de verdade, respostas de suporte a sair,
      Stripe/pagamentos. É decisão de negócio, não técnica. Antes: passos 5.2 +
      Telegram bot configurado + revisão dos handoffs das fases 2-3.
- [ ] (Mais tarde, com historial) `CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO=true` —
      artigos publicam sem clique. O lint já cobre 100% do publicado; mesmo
      assim recomendo semanas de historial limpo primeiro.

### 5.4 Decisões legais pendentes (advogado)

- [ ] Resposta ao dossier v2 (art. 10.º n.º 5 — desbloqueia o cold aos singulares? →
      `CHECKAL_PARECER_RGPD_OK`)
- [ ] Privacidade/termos do site (minutas → finais) — bloqueia o go-live "limpo" do site
- [ ] (Do lote de hoje, se quiseres validar) a interpretação AI Act dos posts
      sem frase de IA e a resposta pré-vendas como diligência pré-contratual

### 5.5 Go-live do site getcheckal.com/checkal.pt (escolheste tratar à parte)

- [ ] Deploy do site (pipeline no `site/README.md`); nameservers do apex
      checkal.pt PTISP → Cloudflare; env vars do Pages (5.2)
- [ ] **Workers Analytics Engine** no `/api/evento` — sem isto os dados de
      visitas perdem-se E a fase 4 não tem o que ler
- [ ] `CLOUDFLARE_API_TOKEN` de âmbito mínimo no agente.env (o wrangler funciona
      hoje pelo teu OAuth, mas pode expirar — token é o caminho robusto headless)

### 5.6 Adiado por desenho (não faças já)

- Fase 4 — agente de análise de conversão (pré-requisitos: site live + analytics)
- Follow-ups automáticos de parcerias, inbound do parcerias@ na passagem do
  EMBAIXADOR (precisa de IMAP; anotado no handoff)
- Auto-retry de itens `falhado` no drain (hoje: recuperação manual, SQL no
  handoff da fase 3)

### 5.7 Pendências antigas (herdadas, não de hoje)

Chaves IfThenPay; TOConline (série CKL + smoke); bot Telegram; feed DGC real;
seguro E&O; `BACKUP_DB_URL` (o cron de backup está live-gated sem destino!);
denominação legal Lda./Unipessoal (`[[FALTA]] n.º 2` do site).

### 5.8 Sugestões minhas para melhorar ainda o de hoje (opcionais)

1. **Apagar os drafts órfãos** `agentes-polaris/prompts/{gestor-de-cliente,sentinela-servico}.txt`
   (referem subcomandos que não existem; já sinalizados — decisão tua).
2. **Monitorizar as primeiras corridas reais** dos 3 agentes novos (posso montar
   um cron de vigilância na primeira semana, se quiseres).
3. **Selar o conteúdo aprovado por hash** (nota TOCTOU da revisão da fase 3):
   hoje nenhum código muta payloads, mas quando houver mais escritores, ligar a
   aprovação a um hash do conteúdo é a defesa certa. Fica para quando doer.
4. **Página /parceiros dinâmica + one-pager PDF** (spec antiga parqueada) — daria
   ao EMBAIXADOR um anexo de proposta melhor. Meio dia de trabalho.
