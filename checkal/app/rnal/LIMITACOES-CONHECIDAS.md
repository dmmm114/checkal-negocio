# Limitações conhecidas do pipeline RNAL (FDS 1)

> Achados do red-team ao diffing / regra dos 2 varrimentos, conscientemente
> deferidos para o sprint onde têm a mitigação desenhada. Documentados para não
> se perderem e para impor a **guarda de sequência** abaixo.
>
> **Estado a 05/07/2026 (fecho do FDS 5):** L1 e L2 estão **MITIGADAS** pelo circuit
> breaker por concelho (`app/breaker.py`) ligado ao fluxo pós-varrimento pelo WIRE
> (`app.crons.resolver_desaparecidos_pendentes`, cron `varrimento`). A guarda de
> sequência abaixo está **RESOLVIDA**. Testes: `tests/test_breaker.py` +
> `tests/test_crons.py`.

## 🚦 GUARDA DE SEQUÊNCIA — RESOLVIDA no FDS 5

**Nenhum alerta de estado `desaparecido` ("o teu registo foi cancelado") pode ser
ENVIADO a um cliente antes de existir a desambiguação do FDS 5** (circuit breaker
por concelho + amostragem da página individual `rnal.aspx?nr=` para confirmar
cancelado/suspenso vs API partida). Até lá, os eventos `desaparecido` são gerados e
persistidos (`processado=false`), mas **não** disparam email. O `ingest` produz o
evento; quem decide enviar é o FDS 5. Um falso "cancelado" é o pior erro do produto.

**Como ficou resolvida:** o FDS 3 (`app.alertas_estado.gerar_alertas_estado`) persiste
cada `desaparecido` como alerta **retido** (`canal == pendente_desambiguacao`,
`enviado_em IS NULL`) sem o enviar. O WIRE
(`app.crons.resolver_desaparecidos_pendentes`, chamado no fim do `cron_varrimento`)
agrupa os pendentes **por concelho** e, para cada um, corre
`avaliar_concelho → desambiguar → resolver_pendentes`. A amostragem da página
individual (`desambiguar`) corre para **todo** o concelho com pendentes — mesmo abaixo
do limiar `BREAKER_PCT_CONCELHO` — porque a guarda exige confirmação **positiva** antes
de qualquer envio (e a copy do ramo `real` afirma «confirmámos na página individual»).
A decisão em **dois níveis** (endurecida no red-team ao FDS 5, 05/07/2026):
`desambiguar` (maioria da amostra) decide **só** se a API está de pé — evento real vs
API partida vs ambíguo. No ramo `real`, `resolver_pendentes` **reconfirma CADA nr
individualmente** (`obter_detalhe(nr)`, propagado pelo wire) antes de enviar: a página
DAQUELE nr tem de dizer `cancelado`/`suspenso`; se disser `ativo` (AL vivo, ex.: L1) o
pendente é **suprimido** e o evento reaberto; `nao_encontrado`/`indeterminado`/erro/sem
seam → **retido, não enviado**. `api_partida` SUPRIME e reabre; `ambiguo` ESCALA. A
regra inviolável é **por-nr**: um alerta `desaparecido` só sai se a página **daquele
nr** confirmar positivamente o fim de atividade — a maioria da amostra nunca basta.
Isolamento por concelho preservado (e agora **transacional**: cada concelho corre no seu
`SAVEPOINT` — uma falha reverte só esse concelho, não desfaz os já resolvidos). Testes
ponta-a-ponta em `tests/test_crons.py` (`test_cron_varrimento_*`, `test_L1_*`,
`test_L2_*`, `test_real_maioria_cancelado_mas_um_nr_vivo_nao_e_enviado`,
`test_falha_num_concelho_nao_desfaz_o_outro`) e em `tests/test_breaker.py`
(`test_resolver_real_confirma_por_nr_*`).

> ⚠️ **Verdadeiros-positivos ainda dependem da calibração G4 do parser de detalhe.**
> O parser (`app.rnal.detalhe.parse_detalhe`) **ainda não afirma** `cancelado`/`suspenso`
> (só `ativo`/`nao_encontrado`/`indeterminado` — ver `_MARCADORES_ESTADO_SUSPEITO`, vazio
> até haver uma fixture de um `nr` REAL cancelado). Como o envio de um `desaparecido`
> exige agora, **por-nr**, um estado `cancelado`/`suspenso` positivo, **enquanto G4 não
> for calibrado a página individual nunca devolve esses estados** → todo o `desaparecido`
> é suprimido/retido (nunca enviado). É a direção segura desejada (zero falsos
> «cancelado»), mas significa **zero verdadeiros-positivos de cancelamento** até a
> calibração (Próximos passos §3: amostrar um `nr` cancelado real, gravar fixture,
> preencher `_MARCADORES_ESTADO_SUSPEITO`). Só então os cancelamentos REAIS passam a ser
> entregues.

## L1 — [médio] ~~Falso `desaparecido` em mudança de concelho com destino em falha~~ · MITIGADA (FDS 5)

> **MITIGADA a 05/07/2026** pelo circuit breaker + WIRE. Um único falso `desaparecido`
> (mudança de concelho com o destino em falha) fica **abaixo** do limiar
> `BREAKER_PCT_CONCELHO`, mas o wire amostra a página individual mesmo assim: como o AL
> está VIVO no destino, a página devolve `ativo`/`nao_encontrado` → veredicto
> `api_partida` → o pendente é **suprimido** (nunca enviado) e o evento reaberto para
> retry. Regressão: `tests/test_crons.py::test_L1_falso_unico_abaixo_do_limiar_e_suprimido`.

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

## L2 — [baixo] ~~Falso `desaparecido` por resposta HTTP 200 truncada~~ · MITIGADA (FDS 5)

> **MITIGADA a 05/07/2026** pelo circuit breaker + WIRE. Uma lista truncada faz muitos
> registos de um concelho faltarem em massa → a fração `desaparecidos/base_total` cruza
> `BREAKER_PCT_CONCELHO` e o breaker dispara; a amostragem das páginas individuais mostra
> os ALs vivos → veredicto `api_partida` → **supressão em massa** + FYI ao dono, nada
> enviado. Regressão: `tests/test_crons.py::test_L2_pico_truncado_suprime_em_massa` e
> `test_cron_varrimento_L2_nao_envia_falso`.

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
