# Núcleo de compliance — rationale e especificação

> Documento de decisão committado junto do código (regra do dono).
> Estado: fatia-alvo dimensionada e aprovada (2026-07-05). Este pacote implementa
> os controlos no **sistema**, não na disciplina humana.

## 1. Enquadramento legal fechado (não reabrir)

O RNAL é público por imposição do art. 10.º/5 do DL 128/2014 (red. DL 76/2024) para
fins fiscais/regulatórios. **Reutilizar esses contactos para marketing é finalidade
incompatível** (art. 5.º/1/b e 6.º/4 RGPD). Publicação imposta por lei ≠ direito de
reutilização.

- **Email frio a pessoa SINGULAR / ENI: PROIBIDO** (Lei 41/2004, art. 13.º-A, opt-in). O ENI é
  pessoa singular e usa NIF pessoal (1/2/3).
- **Extração automática em massa de emails de fonte pública = "harvesting"** — tida por ilícita
  para constituir base de marketing.
- **Único canal frio eletrónico válido = fatia estreita e CUMULATIVA:**
  1. titular pessoa **coletiva** — NIF começado por **5 ou 6** apenas;
  2. email **genérico** da empresa (geral@, info@, reservas@…) — **nunca** nome.apelido@ nem
     email de aspeto pessoal (esses são dados pessoais → RGPD + harvesting);
  3. descoberta do email **dirigida caso a caso**, **não** scraper à escala.
- Regime: **opt-out** (Lei 41/2004, art. 13.º-B), com cruzamento da lista de oposição de
  pessoas coletivas da **Direção-Geral do Consumidor (DGC)**. Fiscalização: ANACOM.
- Singulares/ENI só por **consentimento** (widget) ou **parcerias** — nunca por contacto frio.

🚦 **Portão bloqueante a montante:** parecer de jurista RGPD sobre reutilizar o RNAL para
prospeção, ANTES de qualquer envio. Este código é o filtro; não dispensa o parecer.

## 2. Dimensão da fatia-alvo (medida, não estimada)

Amostra de 23 concelhos = **72.868 registos ativos ≈ 60% do universo nacional**:

| Camada | Nº | % de ativos |
|---|---:|---:|
| a) Total ativos | 72.868 | 100% |
| b) Coletiva NIF 5/6 | 31.002 | 42,5% (NIF 6 ≈ 0: só 5 registos) |
| c) …com email **genérico** | **7.779** | 25,1% das coletivas |
| c) …com email pessoal/outro (NÃO ender.) | 23.223 | 74,9% das coletivas |
| **d) FATIA ENDEREÇÁVEL** | **7.779 registos / 1.914 empresas** | **10,7% dos ativos** |

Extrapolado: ~12.800 registos / ~3.000 empresas nacionais. **NIF 6 é residual → na prática o
filtro é "NIF 5", mas mantém-se 5 e 6 por correção.**

## 3. Regras que cada módulo faz cumprir

### `nif.py` — filtro de titular
- `e_enderecavel(nif) -> bool`: **True apenas** se NIF for 9 dígitos numéricos e o **1.º dígito ∈ {5,6}**.
- `classificar_nif(nif) -> "singular"|"coletiva"|"outro"|"invalido"` (só para logging/contexto):
  1/2/3 e prefixo 45 → `singular`; 5/6 → `coletiva`; restantes válidos (7x, 8, 9x) → `outro`;
  não-9-dígitos/não-numérico → `invalido`.
- **Traps a cobrir por teste:** `"45…"` (não-residente singular) NÃO é endereçável; `"8…"` (ENI) NÃO
  é endereçável; `"9…"` NÃO é endereçável; espaços/pontos/prefixo "PT" limpos antes de avaliar;
  `""`/`None`/8 ou 10 dígitos → inválido, nunca endereçável.

### `email.py` — filtro de local-part
- `e_generico(email) -> bool`; `classificar_email(email) -> "generico"|"pessoal"|"outro"|"invalido"`.
- **Só `generico` é endereçável.** Viés conservador: na dúvida, `outro` (não endereçável).
- Genérico = local-part que é um token de negócio da whitelist (geral, info, reservas, booking,
  contacto, alojamento, turismo, apartments, rececao, apoio, …), sozinho ou com sufixo
  numérico/geográfico (`reservas`, `reservasfaro`, `info2`, `geral.lisboa`).
- **Traps a cobrir por teste (falsos positivos a REJEITAR como não-genéricos):**
  `geraldine@` (contém "geral" mas é nome), `casanova@` (contém "casa"), `informal@`,
  `infante@`, `marketingjoao@` — heurística por token/sep+dígito, **nunca `startswith` cru sobre letras**.
  `pessoal`: padrão `nome.apelido@`. Free-provider (gmail/hotmail) não altera a classificação
  (decide o local-part, não o domínio): `reservas@gmail.com` = genérico; `joao.silva@gmail.com` = pessoal.

### `minimizacao.py` — descarte imediato (minimização RGPD)
- `filtrar_enderecaveis(registos) -> Iterator[ContactoEnderecavel]`: gerador que produz **apenas**
  os endereçáveis (coletiva 5/6 **E** email genérico **E** não excluído). Os registos de
  singulares/não-endereçáveis são **descartados de imediato** — nunca acumulados numa lista
  "para depois", nunca persistidos.
- `ContactoEnderecavel` guarda o **mínimo**: nr_registo, nif, nome_coletiva, email_generico,
  concelho, `proveniencia` (ex.: `"rnal:email_generico_publicado"`). **Nenhum dado de pessoa
  singular** entra no objeto de saída.
- **Trap a cobrir:** dado um lote misto, o output não pode conter nenhum email/nif de singular;
  o gerador não materializa os rejeitados.

### `optout.py` — cruzamento antes de cada envio
- `deve_excluir(email, *, lista_dgc, log_optout) -> bool`: exclui se o email normalizado
  (lowercase, trim) constar da lista de oposição de coletivas da **DGC** OU do log interno de opt-out.
- As listas são **interfaces/conjuntos injetáveis** (fonte real ligada depois). Este módulo **não envia**.
- **Traps a cobrir:** normalização (maiúsculas, espaços) antes de comparar; email em qualquer
  das listas → excluído; registo de origem/opt-out logável.

## 4. Fora de âmbito nesta fase (decisões registadas)
- **Nada de scraping.** A descoberta de email é dirigida caso a caso, com cap de volume (a montante
  deste núcleo). Se algum passo sugerir extração em massa, é para **sinalizar**, não implementar.
- **Sem envio, sem geração de listas de envio.** Só filtro + prova.
- **Lever de fase 2 (adiada):** descobrir email genérico para coletivas que só publicaram email
  pessoal. Legalmente possível *dirigido e capado*, mas: (i) só após parecer do jurista, (ii) baixo
  volume, (iii) alvos de alto valor, (iv) nunca batch sobre os ~11k. Não entra na fatia endereçável agora.
