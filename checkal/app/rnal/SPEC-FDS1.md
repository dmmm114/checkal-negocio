# FDS 1 — Ingestão RNAL + BD + Diffing + Regra dos 2 varrimentos

> Contrato de construção (committado junto do código). Alinhado com AUTOMACAO.md §1 e §7.
> Critério de "feito" (AUTOMACAO.md §7): 2 varrimentos completos guardados; eventos
> gerados corretamente num teste com dados mutados.

## Princípios (AUTOMACAO.md §1, §6)
- Pipeline batch idempotente. Tudo o que falha tem retry; tudo o que é ambíguo **pára e avisa**, não age.
- **Nunca fazer diffing sobre dados suspeitos:** se a validação Pydantic do JSON falhar (chave em falta,
  tipo errado), o varrimento é marcado `abortado` e o diffing não corre.
- Portabilidade: dev = SQLite, prod = Postgres (o `app.db` já troca por URL). Usar **tipos de coluna
  portáteis** — `JSON` (não `JSONB`/`ARRAY`), `DateTime` (não `timestamptz`), `Text`, `Integer`, `Date`.
  Assim os testes correm em SQLite.

## Formato do registo RNAL (da API `list_RNAL`, verificado)
```json
{"RNAL_Registo": {
  "NrRegisto": "100031/AL", "DataRegisto": "2019-07-16", "NomeAlojamento": "…",
  "Modalidade": "Estabelecimento de hospedagem", "NrCamas": 2, "NrUtentes": "4",
  "Endereco": "…", "CodPostal": "8000-444", "Localidade": "Faro", "Freguesia": "…",
  "Concelho": "Faro", "Distrito": "Faro",
  "TitulardaExploracao": {"Tipo": "Pessoa coletiva", "Nome": "…", "Contribuinte": "513029591", "Email": "…"},
  "DTMNFR": "080508"}}
```
Notas: `NrRegisto` vem como `"100031/AL"` → o inteiro é `int(nr.split("/")[0])`. `NrUtentes`/`NrCamas`
podem vir string ou int. `Telefone`/`Telemovel` podem existir dentro de `TitulardaExploracao` (opcionais).

## Módulos e contrato (fronteiras disjuntas — cada agente escreve só o(s) seu(s) ficheiro(s))

### `app/models.py` (+ `tests/test_models.py`)
Modelos SQLAlchemy 2.0 (herdam `app.db.Base`) para o esquema canónico (AUTOMACAO.md §1):
`registos`, `varrimentos`, `eventos_registo`, `detalhes_cliente`, `clientes`, `clientes_registos`,
`eventos_regulatorios`, `alertas`. Colunas exatamente como no esquema, com tipos portáteis
(`concelhos text[]` → `JSON`; `campos_alterados jsonb` → `JSON`; `timestamptz` → `DateTime(timezone=True)`).
`registos.nr_registo` = PK inteiro. Testes: `db.init_db()` cria tudo em SQLite; inserir/ler um `registo`
e um `evento_registo` com `campos_alterados` JSON; relação `clientes_registos`.

### `app/rnal/schema.py` (+ `tests/test_rnal_schema.py`)
Pydantic v2. `RegistoRNAL` valida um registo bruto (aninhado em `RNAL_Registo`). `parse_registo(bruto) ->
RegistoRNAL`. `parse_lista(json_list) -> list[RegistoRNAL]`. `class DriftEsquemaRNAL(Exception)`: levantada
quando a estrutura esperada muda (campo obrigatório em falta/tipo incompatível). `NrRegisto`, `Concelho`,
`TitulardaExploracao` são obrigatórios; o resto opcional. `nr_registo: int` derivado de `NrRegisto`
(validator que corta em `/`). `titular_tipo` normalizado para `"singular"|"coletiva"` a partir de
`Tipo` ("Pessoa coletiva"→"coletiva", "Pessoa singular"→"singular"). Testes: registo válido → objeto;
falta `NrRegisto`/`Concelho` → `DriftEsquemaRNAL`; `NrUtentes` string e int ambos aceites.

### `app/rnal/hashing.py` (+ `tests/test_hashing.py`)
`hash_campos(registo) -> str`: sha256 hex dos campos **relevantes para diffing** (nome_alojamento,
modalidade, nr_camas, nr_utentes, endereco, cod_postal, freguesia, concelho, distrito, titular_tipo,
titular_nome, nif, email, telefone, telemovel), em ordem canónica e estável. Determinístico: mesma
entrada → mesmo hash; alterar qualquer campo relevante muda o hash; campos irrelevantes (ex.: `DTMNFR`)
não afetam. Aceita tanto um `RegistoRNAL` como um dict achatado. Testes: estabilidade, sensibilidade
por campo, insensibilidade a campos irrelevantes.

### `app/rnal/diffing.py` (+ `tests/test_diffing.py`)
Lógica **pura** de diff (sem I/O de BD — recebe estruturas em memória). Contrato:
```
diff_varrimento(estado_atual: dict[int, RegistoEstado], scan: dict[int, RegistoNovo],
                concelhos_ok: set[str]) -> list[EventoDiff]
```
- `estado_atual`: nr_registo → estado conhecido (hash_campos, desaparecido_em, ausencias_consecutivas, concelho).
- `scan`: nr_registo → registo visto neste varrimento (com concelho + hash).
- Regras: presente novo → evento `"novo"`. Presente com hash diferente → `"alterado"` (+ `campos_alterados`).
  Estava `desaparecido` e reaparece → `"reapareceu"`. **Ausente** → **regra dos 2 varrimentos**
  (`config.REGRA_N_VARRIMENTOS`): só gera `"desaparecido"` quando o registo falta em **2 varrimentos
  consecutivos** E o **concelho do registo devolveu resposta válida (∈ concelhos_ok) em ambos**. Uma só
  ausência incrementa `ausencias_consecutivas` mas NÃO gera evento. Se o concelho não está em
  `concelhos_ok` (varrimento parcial), a ausência **não conta** (não incrementa nem marca) — evita falso
  "cancelado" por timeout. Testes obrigatórios (dados mutados): novo, alterado (com diff de campos),
  1 ausência → sem evento, 2 ausências consecutivas com concelho ok → `desaparecido`, ausência com
  concelho fora de `concelhos_ok` → ignorada, reaparecimento após desaparecido.

### `app/rnal/client.py` (+ `tests/test_client.py`)
`httpx` para a API. `fetch_concelho(concelho, *, cliente_http=None) -> list[dict]` (bruto). `fetch_todos(
concelhos, *, sink_raw=None) -> ResultadoVarrimento` com retry por concelho, pausa `config.RNAL_PAUSA_S`
entre concelhos, `config.RNAL_TIMEOUT_S`, `config.RNAL_USER_AGENT`. Guarda o JSON bruto **gzipado** em
`config.SNAPSHOTS_DIR` (`raw_path`). Regista `concelhos_ok`/`concelhos_falhados`. **Nos testes, o cliente
HTTP é injetado/mockado — nada de rede real.** Testes: concelho ok, concelho que falha (retry depois
falha → conta como falhado, não rebenta), raw gzip escrito e re-lível.

### `app/rnal/ingest.py` (+ `tests/test_ingest.py`)
Orquestra um varrimento completo (o único módulo que toca BD): fetch → **validação Pydantic (drift →
varrimento `abortado`, sem diffing)** → normalização → carrega `estado_atual` da BD → `diff_varrimento`
→ persiste eventos + faz upsert em `registos` (atualiza `hash_campos`, `visto_ultimo`,
`ausencias_consecutivas`, `desaparecido_em`) → grava linha `varrimentos` (`ok`/`parcial`/`abortado`).
Idempotente. **Teste de aceitação do FDS 1**: correr 2 varrimentos sobre um conjunto de dados mutado
entre eles (1 novo, 1 alterado, 1 desaparecido nos 2, 1 ausência isolada) e verificar os eventos e o
estado final da BD. Injeta um `client` falso (sem rede).

## Fora de âmbito no FDS 1 (não construir agora)
Detalhe individual Playwright, pipeline regulatório, IA, billing, dunning, circuit breaker por concelho
(entra no FDS 5), campanhas. O breaker só é **preparado** aqui ao expor `ausencias`/percentagens; a ação
fica para o FDS 5.
