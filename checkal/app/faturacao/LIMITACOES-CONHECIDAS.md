# Limitações conhecidas da faturação (swap TOConline)

> Achados [baixo] do red-team ao swap, todos **pré-existentes** (não introduzidos pelo
> swap) e conscientemente deferidos para o hardening de *go-live*. O red-team não
> encontrou nenhum buraco de severidade média+ introduzido pelo swap (445 testes verdes).

## Corrigido no fecho do swap
- **[baixo] Fuga de file descriptors** — `_emissor_toconline`/`_emissor_invoicexpress`
  criavam um `httpx.Client` que nunca era fechado (um por evento). **Corrigido**: o
  cliente HTTP passou a ser aberto/fechado por emissão via `with httpx.Client(...)`.

## L1 — [baixo] Emit-then-verify: FR duplicada no provider se a série não estiver certificada
**Cenário:** se a série TOConline não tiver ATCUD/registo AT (config partida), o fluxo
cria+finaliza a FR no TOConline (documento imutável), a guarda **G2** deteta a falta de
ATCUD e faz **rollback do cliente local** → a Stripe reentrega o `checkout.session.completed`
→ cria uma **2.ª FR** no provider. Resultado: documentos fiscais duplicados no TOConline.

**Porquê é aceitável agora:** só ocorre com **série mal configurada** — precisamente o que
o smoke-test de go-live apanha (ver checklist: emitir 1 FR de teste e confirmar `atcud` e
`document_hash_sum` preenchidos **antes** de apontar tráfego real da Stripe). Idêntico ao
adaptador InvoiceXpress (create+finalize); não é específico do TOConline.

**Hardening de go-live:** (1) smoke-test obrigatório da série (ATCUD real) antes de produção;
(2) opcional: registar a tentativa de emissão de forma durável (fora do rollback do cliente)
para as reentregas não reemitirem — é o padrão exactly-once que fica para uma iteração dedicada.

## L2 — [baixo] Renovação de token gasta uma rotação antes de detetar série em falta
**Cenário:** com credenciais OAuth presentes mas `TOCONLINE_SERIES_ID`/`PREFIX` vazios, o
`_emissor_toconline` renova o access token (uma troca `/token`, rotação do refresh) **antes**
de `toconline_client` levantar `SerieNaoConfigurada`. Não há emissão nem quebra de cadeia; é
só uma rotação de refresh desperdiçada, auto-limitada pela cache do access token.

**Hardening de go-live:** short-circuit da série no compositor antes de tocar no OAuth
(devolver um emissor que levanta `SerieNaoConfigurada` sem renovar). Trivial; deferido por
ser puramente cosmético e para não alterar a semântica None-vs-raise do compositor agora.
