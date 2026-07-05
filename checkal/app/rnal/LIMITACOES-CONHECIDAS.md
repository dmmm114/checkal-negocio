# Limitações conhecidas do pipeline RNAL (FDS 1)

> Achados do red-team ao diffing / regra dos 2 varrimentos, conscientemente
> deferidos para o sprint onde têm a mitigação desenhada. Documentados para não
> se perderem e para impor a **guarda de sequência** abaixo.

## 🚦 GUARDA DE SEQUÊNCIA (bloqueante para o FDS 3/FDS 5)

**Nenhum alerta de estado `desaparecido` ("o teu registo foi cancelado") pode ser
ENVIADO a um cliente antes de existir a desambiguação do FDS 5** (circuit breaker
por concelho + amostragem da página individual `rnal.aspx?nr=` para confirmar
cancelado/suspenso vs API partida). Até lá, os eventos `desaparecido` são gerados e
persistidos (`processado=false`), mas **não** disparam email. O `ingest` produz o
evento; quem decide enviar é o FDS 5. Um falso "cancelado" é o pior erro do produto.

## L1 — [médio] Falso `desaparecido` em mudança de concelho com destino em falha

**Cenário:** um registo muda de concelho (ex.: Faro → Lisboa). Se o concelho de
**destino** (Lisboa) falhar/timeout em 2 varrimentos consecutivos enquanto o de
**origem** (Faro, último concelho conhecido) responde em ambos, o sistema conta 2
ausências na origem e marca `desaparecido` — apesar de o AL estar vivo no destino.

**Porquê acontece:** o estado é por-concelho e a porta `concelhos_ok` usa o concelho
**armazenado** (origem). O sistema nunca vê o registo na localização nova, logo não
pode saber que está vivo. É inerente a um modelo sem conhecimento cross-concelho.

**Porque NÃO se corrige no FDS 1:** exigiria mudar o contrato público de
`diff_varrimento` (ou conhecimento cross-concelho que o pipeline batch não tem). No
modo canónico — **varrimento nacional completo 2×/semana** — o registo aparece no
destino e gera apenas `alterado` (sem falso). O caso só surge com o destino em falha
repetida, que é precisamente o que o **circuit breaker por concelho (FDS 5)** deteta:
antes de deixar sair o alerta, amostra a página individual e vê o AL vivo.

**Mitigação:** guarda de sequência acima + circuit breaker do FDS 5. **Teste a criar
no FDS 5:** reproduzir este cenário e confirmar que a desambiguação impede o alerta.

## L2 — [baixo] Falso `desaparecido` por resposta HTTP 200 truncada

**Cenário:** a API devolve `200 OK` mas com a lista **incompleta** (bug de servidor)
em 2 varrimentos seguidos; os registos em falta atingem o limiar e geram falsos
`desaparecido` em massa.

**Porque NÃO se corrige no FDS 1:** a validação Pydantic valida a **forma por
registo**, não a **completude do lote**. Detetar isto exige uma heurística de
plausibilidade de contagem por concelho — que é, na prática, o mesmo mecanismo do
**circuit breaker por concelho (FDS 5)**: um salto anómalo de `desaparecidos` num
concelho (baseline ~0,2%/semana) dispara o breaker e a desambiguação por página
individual, que distingue limpeza real de resposta truncada.

**Mitigação:** circuit breaker do FDS 5 (limiar `config.BREAKER_PCT_CONCELHO = 0,03`)
+ dead-man switch / validação de esquema já existentes.

## Corrigido no fecho do FDS 1

- **[baixo] Falso silêncio por mismatch de nome de concelho** (caixa/espaços entre
  `concelhos_ok` e o campo `Concelho` guardado): **corrigido** — a porta passou a
  comparar com `_norm_concelho` (casefold + trim). Regressão em `tests/test_diffing.py`
  (`test_concelho_ok_bate_apesar_de_caixa_diferente...`). Contrato preservado.
