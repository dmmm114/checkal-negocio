# FDS 5 — Fiabilidade: dunning + suporte IA + circuit breaker + observabilidade + backups

> Contrato de construção. Alinhado com AUTOMACAO.md §5/§6/§7.
> Critério de "feito": simulação de cartão falhado percorre a sequência toda; matar um
> cron dispara alerta; simulação de limpeza em massa num concelho de teste segue o ramo
> certo (real→alerta, API→suspensão).

## Disciplina transversal (inviolável)
- **MODO DE TESTE, LIVE-GATED.** Zero rede/IA/IMAP/subprocess real nos testes — tudo
  injetado/mockado; seams live-gated. TDD. Cada agente toca só nos seus ficheiros.
- **🚦 Este sprint RESOLVE a guarda de sequência do FDS 1/3:** os alertas `desaparecido`
  retidos (`pendente_desambiguacao`) só são LIBERTADOS (enviados) depois de o breaker
  confirmar cancelamento real; se for API partida, são SUPRIMIDOS; se ambíguo, ESCALA ao dono.

## Módulos e contrato (fronteiras disjuntas)

### `app/config.py` (aditivo)
`HEALTHCHECKS_*` (slugs/URLs de ping), `IMAP_*` (host/user/pass de apoio@), `TELEGRAM_*`
(escalação ao dono), `BACKUP_*`. `BREAKER_PCT_CONCELHO`/`REGRA_N_VARRIMENTOS` já existem.

### `app/breaker.py` + `tests/test_breaker.py` — O MÓDULO-CHAVE
`avaliar_concelho(concelho, desaparecidos, base_total) -> Decisao`: se
`desaparecidos/base_total > config.BREAKER_PCT_CONCELHO` → dispara desambiguação; senão
`normal`. `desambiguar(concelho, nrs_amostra, *, obter_detalhe) -> Veredicto ∈ {real,
api_partida, ambiguo}`: amostra 10–20 páginas individuais via `app.rnal.detalhe.obter_detalhe`
(injetado); `cancelado`/`suspenso` predominante → `real`; `nao_encontrado`/erro predominante
→ `api_partida`; mistura inconclusiva → `ambiguo`. `resolver_pendentes(session, concelho,
veredicto, *, enviar) -> ...`: **real** → liberta os alertas `desaparecido` retidos desse
concelho (`pendente_desambiguacao`→envia via `enviar` injetado, marca `enviado_em`);
**api_partida** → suprime (mantém evento `processado=false` para retry, não envia) + FYI ao dono;
**ambiguo** → escala ao dono, não envia. **Isolamento por concelho:** o breaker de um concelho
nunca afeta outro. Testa todos os ramos com dados mutados + `obter_detalhe`/`enviar` mockados.

### `app/dunning.py` + `tests/test_dunning.py`
Sequência de renovação/cobrança (AUTOMACAO §5), cron diário: **D-30** email "renova a {data}"
(com resumo de valor entregue), **D-7** aviso, **D0** (Stripe cobra — já via Smart Retries),
**D+3/D+7** emails de falha (o evento `invoice.payment_failed` já marca falha no FDS 2),
**D+21** downgrade `estado=cancelado` + email final. Trienal: sem dunning; email a D-30 do fim.
Máquina de estados sobre `clientes` (`ativo`→`em_dunning`→`cancelado`), idempotente (não reenvia
o mesmo passo). Emails via `envio` (live-gated, injetado). Testa a sequência completa com relógio
e envio injetados.

### `app/suporte.py` + `tests/test_suporte.py`
Suporte 1.ª linha (AUTOMACAO §5): cron 15 min lê `apoio@` via IMAP (injetado), para cada email
não lido compõe resposta com Sonnet (`app.ia.cliente`, injetado) + KB (FAQ + estado do cliente da
BD). Responde a perguntas factuais; **ESCALA ao dono** (Telegram/forward, injetado) se detetar:
pedido jurídico específico, reclamação, intenção de cancelar com queixa, ou **confiança baixa**.
Live-gated. Testa: pergunta factual→responde; gatilho de escalação→escala e NÃO responde sozinho.

### `app/observabilidade.py` + `tests/test_observabilidade.py`
Dead-man switch (AUTOMACAO §6): `com_healthcheck(slug)` (decorator/contexto) que faz ping ao
Healthchecks.io no fim de cada cron (httpx injetado); falha/exceção → sinaliza. Testa: sucesso
faz ping de sucesso; exceção faz ping de falha e propaga.

### `app/backups.py` + `tests/test_backups.py`
`comando_pg_dump(...) -> list[str]` (composição do comando, testável sem correr) + entrypoint de
cron com retenção. Subprocess **não** corre nos testes (injetado/mockado). Testa a composição do
comando e a política de retenção.

### Wire (agente de orquestração)
Liga o breaker ao fluxo pós-varrimento (o `ingest`/pipeline expõe os desaparecidos por concelho →
`breaker.avaliar_concelho`→`desambiguar`→`resolver_pendentes`). Envolve os crons (varrimento, DRE,
dunning, suporte, backup) com `com_healthcheck`. **Preserva verdes** todos os testes anteriores;
o release de pendentes tem de respeitar a idempotência.

## Fora de âmbito no FDS 5 (não construir)
Cold/campanhas (FDS 6); Playwright real na desambiguação (usa `obter_detalhe` httpx do FDS 3);
resolução do endpoint interno do rnal.aspx (otimização fase 2).
