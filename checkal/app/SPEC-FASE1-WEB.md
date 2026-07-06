# FASE 1 (email-first) — Website consent-first + templates de email + dashboard

> Contrato de construção. A "cara" sobre o motor já feito (FDS 2–6). Marca FINAL aplicada.
> Este ficheiro é a fonte dos TOKENS de design — todos os agentes usam exatamente estes.

## Tokens de marca (canónicos — não inventar)
**Cores:** grafite `#0F172A` (tinta/wordmark) · verde-check `#12B76A` (o ✓ e SÓ estados
positivos) · azul-ação `#2563EB` (botões/links) · cinza-suspenso `#94A3B8` · âmbar `#F59E0B`
(🟡 atenção) · coral `#DC2626` (🔴 falhou — só cliente/alerta, NUNCA no selo público) ·
fundo-frio `#F8FAFC` · marfim `#F6F2E9` (marketing/email) · texto-secundário `#475569`.
**Tipografia:** títulos **Plus Jakarta Sans** (800/700), texto **Inter** (400/500/600).
Web: Google Fonts `<link>`. Email: fallback de sistema (`-apple-system,Segoe UI,Roboto,Arial`).
**Assets** (já em `app/web/static/marca/`): `logo-horizontal.svg`, `logo-horizontal-escuro.svg`,
`logo-empilhado.svg`, `badge-AL.svg`, `selo-ativo.svg`, `selo-suspenso.svg`.
**Voz:** o "inspetor amigo" — claro, positivo, alívio (não medo). Estados: 🟢 "passou no check ✓" ·
🟡 "1 ponto sem check" · 🔴 "falhou o check". Micro-copy: `Registo: check ✓ · Seguro: check ✓ · Regulamento: check ✓`.
**Legal (inviolável):** serviço PRIVADO, nunca aspeto de Estado; o selo atesta FACTOS
("registo ativo e verificado"), nunca "AL legal/certificado"; 🔴 nunca no selo público.
**Copy:** a copy real é canónica em `../COPY-VENDAS.md`; preços em `../PRICING.md` / `config.PLANOS`.
NÃO inventar copy nem preços — ler de lá.

## Disciplina
LIVE-GATED: nada envia/toca rede nos testes (seams injetados — `envio.obter_enviador`). TDD.
FastAPI + Jinja2 + StaticFiles (Jinja/StaticFiles montados em `app/web/app.py:criar_app`).
Cada agente toca só nos seus ficheiros. Português. Acessibilidade sénior (≥16px, contraste AA, alvos grandes).

## Módulos — WORKFLOW 1 (Website)

### `app/web/marca.py` + `app/web/static/brand.css` + `app/web/templates/base.html` + `tests/test_marca_web.py`
`marca.py`: tokens (cores/urls/planos) como constantes + `contexto_base()` p/ Jinja. `brand.css`: o
design system (variáveis CSS dos tokens, tipografia, botões, cartões, estados 🟢🟡🔴, header/footer,
responsivo mobile-first). `base.html`: layout base — header com `logo-horizontal.svg`, footer com o
qualificador legal ("CheckAL — serviço privado e independente de monitorização de AL · Cosmic Oasis,
Lda.") + links privacidade/termos/remover. Montar Jinja2Templates + StaticFiles em `criar_app`. Testa
(TestClient): `/static/brand.css` 200; base renderiza com logo.

### `app/web/landing.py` (SUBSTITUI o placeholder) + `templates/landing.html` + `tests/test_landing_web.py`
Landing consent-first (copy de COPY-VENDAS.md): hero + tagline "O teu AL? Check." + o **WIDGET**
"Faz o check grátis ao teu AL" (input nº RNAL → JS chama `GET /api/verificar?q=` → mostra o cartão de
estado 🟢🟡🔴 → formulário email + checkbox de consentimento → POST `/inscrever`). Secções: como
funciona (3 checks), preços (de `config.PLANOS`), confiança, FAQ, CTA. `GET /saude` mantém-se. Testa:
landing 200 com o widget e o form de consentimento; preços corretos.

### `app/web/paginas.py` + `templates/{precos,privacidade,termos,obrigado}.html` + `tests/test_paginas.py`
Rotas `GET /precos`, `/privacidade`, `/termos`, `/obrigado`. Preços de `config.PLANOS` (49€/119€/
portfólios). Privacidade/termos: estrutura real (responsável Cosmic Oasis Lda., finalidade, direitos,
CNPD, `privacidade@checkal.pt`) — placeholders `[NIPC]/[morada]` onde faltarem dados. Testa 200 + preços.

### `app/web/consentimento.py` (+ models `Lead`) + `templates/confirma.html` + `tests/test_consentimento.py`
Model `Lead` (aditivo em `app/models.py`): email, nr_registo, concelho, consentimento_texto_versao,
consentimento_em (DateTime), ip, estado ('pendente'|'confirmado'|'removido'), token_confirmacao, criado_em.
`POST /inscrever`: valida email + consentimento marcado → cria Lead 'pendente' + **guarda a prova**
(texto+timestamp+ip) → dispara **double opt-in** via `envio.obter_enviador` (live-gated, injetado nos
testes) → redireciona `/obrigado`. `GET /confirmar?token=`: ativa o Lead ('confirmado'). Consentimento
NÃO pré-marcado, NÃO obrigatório para o relatório. Testa: inscrição grava prova + dispara double opt-in
(mock); confirmar ativa; sem checkbox → não inscreve.

### `app/web/remover.py` + `templates/remover.html` + `tests/test_remover.py`
`GET /remover` (form) + `POST /remover` (email) → regista opt-out (tabela `optouts` do FDS6) +
marca Lead 'removido'. 1-clique via `GET /remover?e=<email>&t=<token>` (link dos emails). Confirmação.
Testa: opt-out grava e confirma; idempotente.

### Wire (agente de integração)
Montar todos os routers em `criar_app`. Enriquecer a página do selo (`app/web/selo.py`) com `base.html`
+ `selo-ativo.svg`/`selo-suspenso.svg` (mantendo zero-PII). Preservar verdes os testes anteriores.
Teste e2e: landing → widget → /api/verificar → /inscrever (consent gravado, double opt-in disparado)
→ /confirmar → /remover. Red-team: prova de consentimento gravada, opt-out funciona, ZERO PII no selo,
templates à prova de XSS (autoescape Jinja), CSRF nos POST.

## Fora de âmbito do WF1 (vêm a seguir)
Templates de email HTML (WF2) · dashboard admin (WF3) · envio real (precisa da conta Resend + DNS).
