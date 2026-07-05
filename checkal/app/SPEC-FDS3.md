# FDS 3 — Onboarding automático + selo público + email + alertas de estado

> Contrato de construção. Alinhado com AUTOMACAO.md §5/§7 e as SPECs verificadas
> `app/rnal/SPEC-DETALHE.md` (detalhe/seguro) e `app/envio/SPEC-RESEND.md` (email).
> Critério de "feito" (AUTOMACAO.md §7): compra→relatório sem intervenção humana em
> <15 min; o link do selo mostra "AL Monitorizado" a qualquer visitante. **MVP vendável.**

## Disciplina transversal (inviolável)
- **MODO DE TESTE, LIVE-GATED.** Nada toca a rede nos testes: os clientes HTTP (RNAL,
  Resend) são **injetados/mockados**; em produção compõem-se atrás de seams live-gated
  (como `faturacao.obter_emissor`). Portabilidade SQLite/Postgres. TDD. Cada agente toca só
  nos seus ficheiros.
- **🚦 GUARDA DE SEQUÊNCIA (de `app/rnal/LIMITACOES-CONHECIDAS.md`):** nenhum alerta de
  estado **`desaparecido`** ("cancelado") é ENVIADO antes da desambiguação do FDS 5. O FDS 3
  gera o conteúdo e persiste o alerta, mas marca-o `pendente_desambiguacao` e **não** envia.
- **G4 (detalhe RNAL):** o estado "cancelado"/"suspenso" da página individual **nunca foi
  observado**. Parsing defensivo: só `ativo` e `nao_encontrado` são certos; tudo o que não
  for claramente um desses → **`indeterminado`** (pára e avisa, nunca afirma "cancelado" a
  partir do detalhe). A fonte de verdade do cancelamento é o diffing nacional (FDS 1). Deixar
  fixtures + TODO para calibrar com um `nr` cancelado real quando o dono o fornecer.

## Módulos e contrato (fronteiras disjuntas)

### `app/config.py` + `app/models.py` (EXTENSÃO aditiva) + `tests/test_models_fds3.py`
Config: `RESEND_API_KEY` (já existe), flags de envio live-gated. Models: acrescenta a
`detalhes_cliente` a coluna `seguro_inicio date` (a página expõe "Data início"; aditivo, sem
quebrar FDS1/FDS2). Testa a coluna nova.

### `app/rnal/detalhe.py` + `tests/test_detalhe.py`
`obter_detalhe(nr_registo, *, cliente_http) -> DetalheRegisto`: GET a `config.RNAL_PAGINA?nr=`
(SPEC-DETALHE), parse do **estado** e do bloco de **seguro** (companhia, apólice, validade,
início). `estado ∈ {"ativo","cancelado","suspenso","nao_encontrado","indeterminado"}` — G4:
default conservador `indeterminado`. `persistir_detalhe(session, detalhe)` → `detalhes_cliente`.
cliente_http injetado; testes com fixtures HTML (inclui um caso "ativo", um "não encontrado"
por texto em HTTP 200, e um ambíguo → indeterminado). Sem rede real.

### `app/envio/resend_client.py` + `app/envio/__init__.py` + `tests/test_resend.py`
`enviar_email(*, para, assunto, html, anexos, cliente_http) -> ResultadoEnvio` via API Resend
(SPEC-RESEND), anexos (PDF do relatório/fatura). `obter_enviador() -> callable|None` live-gated
(None sob MODO_TESTE / sem RESEND_API_KEY), à imagem de `faturacao.obter_emissor`. **Sem
webhook de bounces** (verificação Svix por confirmar — fora de âmbito). cliente_http injetado.

### `app/relatorio.py` + `tests/test_relatorio.py`
`gerar_relatorio_inicial(cliente, detalhe, *, contencao=None, regulamentos=()) -> RelatorioInicial`
(estrutura de dados) + `render_pdf(relatorio) -> bytes` (fpdf2). Secções: estado do registo,
seguro, área de contenção do concelho, regulamentos ativos (contenção/regulamentos podem vir
vazios — FDS 4 preenche; render tolera vazio). Copy factual, PT-PT, sem inventar. Testa: PDF
gerado (bytes não vazios, `%PDF`), secções presentes, tolera dados em falta.

### `app/selo.py` + `app/web/selo.py` + `tests/test_selo.py`
`app/selo.py`: `gerar_selo_svg(nr_registo, nome) -> str` (SVG inline, sem dependência) +
`snippet_anuncio(nr_registo) -> str` (HTML para colar no anúncio). `app/web/selo.py`: APIRouter
`GET /selo/{nr_registo}` → página pública HTML a partir da BD, mostra "CheckAL ✓ — AL
Verificado / Monitorizado" com **só dados públicos** do estabelecimento (nunca titular/NIF).
Testa (TestClient): selo existente 200 + "Verificado"; inexistente → 404; zero PII.

### `app/onboarding.py` + `tests/test_onboarding.py`
`processar_onboarding(cliente_id, *, obter_detalhe, enviar) -> ResultadoOnboarding`: carrega o
cliente + o(s) nr(s) associados → `obter_detalhe` (injetado) → persiste `detalhes_cliente` →
`gerar_relatorio_inicial` + `render_pdf` → compõe email de boas-vindas (relatório + fatura já
emitida + link do selo `config.BASE_URL/selo/{nr}`) → `enviar` (injetado). **Idempotente**
(re-processar não duplica envios). Se o detalhe vier `indeterminado`/`nao_encontrado`, o
relatório sai à mesma com a ressalva e regista tarefa para o dono (ponto semi-manual, <5%).
Testa: onboarding gera relatório+email; idempotência; detalhe indeterminado não rebenta.

### `app/alertas_estado.py` + `tests/test_alertas_estado.py`
`gerar_alertas_estado(session, *, enviar) -> list[Alerta]`: lê `eventos_registo` não processados
(`novo` ignora-se p/ clientes; `alterado`/`desaparecido`/`reapareceu` para clientes com esse
nr), compõe alerta **determinístico por template** (NÃO IA), persiste em `alertas`, marca o
evento `processado`. **🚦 GUARDA:** `desaparecido` → persiste com `pendente_desambiguacao=True`
e **NÃO envia** (espera FDS 5). `alterado`/`reapareceu` → envia (via `enviar` injetado). Testa:
alterado envia, desaparecido persiste mas não envia, mapeamento evento→cliente correto.

### Wire (feito pelo agente de onboarding)
Liga `onboarding.processar_onboarding` ao ponto de extensão deixado no `app/fulfillment.py`
(pós-fatura), atrás do seam live-gated (injetado nos testes). Monta o router do selo em
`app/web/app.py`. Preserva EXATAMENTE os testes FDS2/swap (idempotência, guardas) verdes.

## Fora de âmbito no FDS 3 (não construir)
Playwright real (a página é server-rendered; GET httpx chega — SPEC-DETALHE); pipeline
regulatório + IA (FDS 4 preenche contenção/regulamentos do relatório); dunning/suporte (FDS 5);
circuit breaker (FDS 5); webhook de bounces do Resend; cold (FDS 6).
