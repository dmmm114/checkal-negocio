# FASE 1 · Motor de aquisição consent-first (conteúdo/SEO + parcerias)

> O canal de DIA 1 — não precisa de advogado (é consentimento) nem de chaves. Tudo drena para
> o **widget "faz o check grátis"**. Tokens de marca: `SPEC-FASE1-WEB.md`. Copy canónica em
> `../COPY-VENDAS.md`; gatilhos e plano em `../GTM.md`; **dados reais em `../ANALISE-SEGURO.md`**.

## Regras de conteúdo (invioláveis)
- **Voz "inspetor amigo"**, alívio não medo (MARCA.md). Serviço PRIVADO, nunca aspeto de Estado.
- **Factual e honesto:** usar os números de `ANALISE-SEGURO.md` (31% sem validade de seguro; 48,6%
  caducada; 64,5% em falta/caducado) com a ressalva obrigatória: **"validade caducada no registo ≠
  estar sem seguro"** (pode ter renovado e não atualizado). NUNCA afirmar que alguém está ilegal/sem
  seguro/em incumprimento — **informação, não aconselhamento jurídico** (Lei 10/2024).
- Coimas: usar os valores canónicos do CLAUDE.md (singular 2.500–4.000€ · coletiva 25.000–40.000€),
  sempre condicionais ("pode ir de… a…"), nunca como ameaça individualizada.
- Cada página termina com **CTA para o widget** (`/` ou um parcial de widget) — "Faz o check grátis
  ao teu AL — 30 segundos, sem cartão". Consent-first: o valor entrega-se primeiro.

## Módulos

### `app/web/conteudo.py` (router) + `tests/test_conteudo.py`
Rotas GET das páginas abaixo (Jinja, extends base.html, cada uma com meta/OG/JSON-LD e o CTA do widget).

### `templates/conteudo/` — páginas de GATILHO (conversão + SEO local)
- `porto.html` — "Porto: 1.413 registos de AL cancelados. O teu está a salvo?" (GTM.md). Explica o
  evento factualmente + CTA widget. SEO local ("alojamento local Porto", "cancelamento registo AL").
- `funchal.html` — "Novo regulamento de AL no Funchal: afeta o teu?" + CTA widget.
(Genérico reutilizável: um template `gatilho.html` + dados por rota, se preferires.)

### `templates/conteudo/` — páginas PILAR (evergreen SEO)
- `registo-rnal.html` — "Como saber se o teu AL está ativo no RNAL (e o que fazer se for cancelado)".
- `seguro-al.html` — "Seguro obrigatório de Alojamento Local: o que é e como verificar" — **usa os
  dados do ANALISE-SEGURO** (com a ressalva). É o pilar mais forte.
- `regulamentos-al.html` — "Regulamentos municipais de AL e áreas de contenção: o que muda".
- `cancelamento-al.html` — "O que acontece (e o que fazer) se o teu registo de AL for cancelado".
Cada uma: informativa, cita fontes públicas (RNAL, Diário da República), termina no CTA widget.

### `templates/parceiros.html` + `app/parceiros.py` (one-pager PDF) + `tests/test_parceiros.py`
- `GET /parceiros` — página para **contabilistas e gestores de AL** (canal de dia 1): porquê referir
  clientes, o valor (carteira monitorizada, menos surpresas), como funciona a parceria, CTA de contacto
  (`parcerias@checkal.pt`). Sem prometer comissões que não existem — factual.
- `gerar_onepager_parceiro() -> bytes` (fpdf2): folha A4 com marca + argumento + dados do seguro,
  para o dono levar às reuniões-piloto. Testa: PDF %PDF, secções presentes.

### SEO plumbing
- `GET /sitemap.xml` (todas as rotas públicas) + `GET /robots.txt` (permitir; `/admin` e `/api`
  disallow). Cada página com `<title>`, `<meta description>`, Open Graph (usa a capa/OG da marca) e
  **JSON-LD** (`Organization` + `Article`/`FAQPage` onde faça sentido). `noindex` no selo/admin.

### Wire (agente de integração)
Montar `conteudo`/`parceiros`/sitemap/robots em `criar_app`. Nav do `base.html`: adicionar
"Recursos" (dropdown com as pilares) e "Parcerias". Rodapé: links para as pilares (SEO interno).
Preservar verdes os testes. e2e: cada página 200 com CTA para o widget + meta/JSON-LD válidos;
sitemap lista as rotas; robots bloqueia /admin. Red-team: nenhuma afirmação prescritiva/"ilegal"
(passa pelo espírito do guardrail — informação, não conselho); zero PII; links do CTA funcionam;
dados do seguro com a ressalva presente.

## Fora de âmbito
Blog dinâmico/CMS; anúncios pagos (é operacional); automação de e-carta. Mantém-se estático e sólido.
