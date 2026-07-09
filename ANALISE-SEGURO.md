# Análise do pilar SEGURO — amostra de 200 páginas individuais do RNAL

> Item 3 do roadmap (CLAUDE.md): "Amostrar 200 páginas individuais RNAL → medir preenchimento
> do bloco seguro (decide copy do pilar seguro — PRODUTO.md §2)". **Feito a 09/07/2026.**
> Metodologia: amostra estratificada proporcional pelos 23 concelhos do dimensionamento
> (~60% do universo), 200 registos ativos, páginas obtidas com pausas de 1,5 s e UA
> identificado, parse pelo próprio parser do produto (`app.rnal.detalhe`). Dados brutos
> preservados em scratchpad (`amostra_seguro.json`); sem PII neste documento.

## Resultados

| Métrica | Valor | % |
|---|---:|---:|
| Páginas obtidas e parseadas | 200/200 | 100% |
| Estado `ativo` (parser) | 200/200 | 100% — **zero `indeterminado`, zero erros** |
| Bloco seguro: companhia presente | 200/200 | 100% |
| Bloco seguro: apólice + **validade** presentes | 138/200 | 69% |
| **Sem validade visível** | 62/200 | **31%** |
| **Validade CADUCADA** (< hoje), entre os que a mostram | 67/138 | **48,6%** |
| → Seguro em falta OU caducado no registo público | **129/200** | **64,5%** |

Por tipo de titular:

| | n | sem validade | caducado (dos que mostram) |
|---|---:|---:|---:|
| **Singular/ENI** | 119 | 46 (38,7%) | 37/73 (50,7%) |
| **Coletiva** | 81 | 16 (19,8%) | 30/65 (46,2%) |

## Leitura para o produto

1. **O pilar seguro é o mais forte dos três checks.** ~2 em cada 3 ALs ativos têm o bloco de
   seguro **em falta ou desatualizado** na consulta pública. É um problema real, mensurável,
   maioritário — e é exatamente o que o CheckAL vigia e alerta.
2. **Copy recomendada (factual, verificável):**
   > "Verificámos 200 alojamentos ao acaso no registo público: **1 em cada 3 não mostra a
   > validade do seguro obrigatório; dos que mostram, quase metade está caducada.** O teu
   > mostra o quê? Faz o check grátis."
3. **Honestidade obrigatória na copy e nos alertas:** validade caducada NO REGISTO ≠
   necessariamente AL sem seguro — pode ter renovado e não atualizado o registo. O alerta
   diz "a validade do seguro no registo público terminou a {data} — se já renovaste,
   atualiza o registo; se não, age" (informação, não acusação). Nunca afirmar "estás sem
   seguro".
4. **Singulares são o segmento mais exposto** (39% sem validade; 51% caducada) — reforça o
   funil consent-first (widget) como canal certo para eles.
5. **Validação técnica de bónus:** o parser de detalhe fez 200/200 páginas reais sem um
   único `indeterminado` — a base dos canários do breaker e do refresh diário dos clientes
   está sólida em produção.

## Limitações
- n=200 estratificado nos 23 concelhos de maior mercado (~60% do universo): margem ~±7 p.p.
  (95%); concelhos pequenos sub-representados.
- "Companhia 100%" pode refletir persistência do último valor conhecido no registo; a
  validade é o campo operacionalmente fiável.
- Fotografia de 09/07/2026; repetir a medição trimestralmente (o pipeline já o permite).
