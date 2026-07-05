# FDS 4 — Pipeline regulatório (DRE) + camada IA (triagem Haiku + alerta Sonnet)

> Contrato de construção. Alinhado com AUTOMACAO.md §2/§3/§7 e as SPECs verificadas
> `app/regulatorio/SPEC-DRE.md` e `app/ia/SPEC-IA.md`.
> Critério de "feito" (AUTOMACAO.md §7): um documento real da Parte H gera um alerta
> correto E citado para um cliente de teste.

## Disciplina transversal (inviolável)
- **MODO DE TESTE, LIVE-GATED.** Zero rede/IA real nos testes: httpx (DRE) e o cliente
  Anthropic são **injetados/mockados**; em produção compõem-se atrás de seams live-gated
  (`obter_cliente_ia() -> None` sob `CHECKAL_MODO_TESTE`/sem `ANTHROPIC_API_KEY`). TDD.
- **Regra conservadora da triagem:** `duvida` é tratado como `sim` (nunca se cala por dúvida).
- **🧯 ANTI-ALUCINAÇÃO (o ponto mais crítico do produto — um alerta jurídico errado é
  responsabilidade real):** três camadas obrigatórias (AUTOMACAO §3). Ver `app/ia/validacao.py`.

## Módulos e contrato (fronteiras disjuntas)

### `app/config.py` (aditivo) + `app/ia/__init__.py` (seam) + `tests/test_ia_seam.py`
Config: usa `MODEL_TRIAGEM`/`MODEL_ALERTA`/`ANTHROPIC_API_KEY` (já existem). `obter_cliente_ia()
-> cliente|None` LIVE-GATED (None sob MODO_TESTE/sem key), à imagem de `faturacao.obter_emissor`.

### `app/regulatorio/dre_client.py` + `tests/test_dre_client.py`
SPEC-DRE. `url_pdf_gratuito(data, edicao) -> str` (padrão `files.diariodarepublica.pt/gratuitos/
2s/AAAA/MM/...` VERIFICADO). `descarregar_pdf(url, *, cliente_http) -> bytes|None` (não-200/não-PDF
= "ainda não publicado" → None, sem rebentar). `extrair_texto(pdf_bytes) -> str` (pypdf).
`extrair_parte_H(texto) -> list[SeccaoParteH]` (delimita a Parte H — Autarquias Locais). `grep_al(
seccao) -> bool` (keywords: "alojamento local","área de contenção","crescimento sustentável").
`concelhos_de(seccao) -> list[str]` (regex do cabeçalho da Parte H). cliente_http injetado; fixtures
de PDF/texto nos testes; tolera edição inexistente e PDF sem Parte H.

### `app/ia/validacao.py` (PURO — o coração anti-alucinação) + `tests/test_ia_validacao.py`
`validar_alerta(texto_alerta, *, url_fonte, excerto) -> ResultadoValidacao`. Camada 2 (validação
programática pós-geração):
  - **Citação da fonte:** `url_fonte` TEM de constar do `texto_alerta` (senão inválido).
  - **Sem números inventados:** todo o VALOR MONETÁRIO (€, coimas) e toda a DATA/prazo mencionados
    no `texto_alerta` TÊM de existir no `excerto` (match por regex/normalização). Qualquer valor no
    alerta ausente do excerto → inválido.
`ResultadoValidacao{valido: bool, motivos: list[str], valores_orfaos: list[str]}`. Função **pura**,
determinística, testada à exaustão (é a rede de segurança). Testa: url ausente → inválido; coima
que não está no excerto → inválido; data inventada → inválido; alerta fiel (só valores do excerto,
com url) → válido; tolera formatos PT (1.500 €, 2 500,00€, "30 dias", "15/06/2026").

### `app/ia/triagem.py` + `tests/test_triagem.py`
SPEC-IA. `triar(evento_regulatorio, *, cliente_ia) -> Triagem`: Haiku (`config.MODEL_TRIAGEM`),
input título + ~3000 palavras, **structured output** JSON estrito `{relevante_para_al: sim|nao|duvida,
concelhos: [...], tipo: regulamento|contencao|limpeza|outro, resumo_1_frase}`. **`duvida` → tratado
como `sim`** (helper `e_relevante(triagem) -> bool`). cliente_ia injetado/mockado. Testa: parse do
JSON, duvida→relevante, concelhos extraídos, cliente_ia mock (sem rede).

### `app/ia/alerta.py` + `tests/test_alerta.py`
SPEC-IA + AUTOMACAO §3 (template Sonnet). `gerar_alerta(evento, dados_al, *, cliente_ia, excerto) ->
Alerta`. Camadas anti-alucinação: **(1)** template restritivo (baseia-se SÓ no excerto, cita a fonte,
sem jargão, ≤180 palavras — usar o template canónico de AUTOMACAO §3); **(2)** corre `validacao.
validar_alerta`; se inválido, **regenera** (máx. 2×); **(3)** se falhar 2× → **formato manual de
recurso** (template sem prosa da IA: "Foi publicado {titulo} que pode afetar o teu AL em {concelho}.
Lê aqui: {url}") — nunca fica nada por comunicar. cliente_ia injetado/mockado. Testa: alerta válido à
1.ª; alerta inválido→regenera→válido; inválido 2×→fallback manual (que passa a validação por
construção); o fallback cita sempre a url.

### `app/regulatorio/dre_pipeline.py` + `app/regulatorio/pipeline.py` + `tests/test_dre_pipeline.py`
`dre_pipeline`: cron diário — determina a edição (contador auto-corretivo; seed por config),
descarrega, extrai, Parte H, grep, cria `eventos_regulatorios` (concelhos[], url UNIQUE, titulo,
publicado_em, triagem NULL). Idempotente por url. `pipeline` (end-to-end): eventos não processados →
`triagem.triar` → se relevante, para cada cliente com AL num concelho afetado → `alerta.gerar_alerta`
→ persiste em `alertas` → envia via `envio` (live-gated, injetado). Alertas regulatórios **não** têm
a guarda do FDS5 (essa é só para `desaparecido` de estado). Idempotente. Testa o end-to-end com
cliente_ia + enviar mockados.

## Fora de âmbito no FDS 4 (não construir)
Camada B do DRE (screenservices OutSystems — fase 2, só por interceção Playwright); Batch API real
(usar o cliente injetado; a submissão/polling real fica atrás do seam, testada mockada); dunning +
suporte IA + circuit breaker (FDS 5); cold (FDS 6). Registo RGPD do envio de excerto à Anthropic
(batches não-ZDR) fica assinalado como portão de go-live, não bloqueia o build.
