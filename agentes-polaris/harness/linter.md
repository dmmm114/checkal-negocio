# ESPECIFICAÇÃO — Linter Determinista de Texto Outward-Facing (guarda do output dos agentes CheckAL)

## 0. Papel e âncora no repo
O linter é o **portão de qualidade textual** que corre ANTES de qualquer texto produzido por agente (ANGARIADOR, GESTOR-DE-CLIENTE) ser marcado *aprovável* — a montante da aprovação 1-clique do MAESTRO. **Não substitui** os detetores já existentes; **compõe-nos e amplia-os** para todo o texto outward-facing (não só o alerta):

- Reutiliza `app.ia.validacao.validar_alerta` (grounding: fonte citada + zero valores órfãos).
- Reutiliza `app.ia.guardrails.validar_nao_prescritivo` (anti-atividade-reservada, Lei 10/2024).
- Acrescenta as regras de forma/RGPD/AI-Act que aqueles dois não cobrem (opt-out, divulgação de IA, disclaimer, rodapé/remetente do cold, coima-como-ameaça).

Módulo proposto: `checkal/app/compliance/linter.py`. Função pura, determinística, **conservadora** (na dúvida REJEITA — o viés inviolável já vigente em `validacao.py`/`guardrails.py`).

## 1. ENTRADA
```
lint(peca: PecaOutward) -> ResultadoLint
```
`PecaOutward` (frozen) transporta o que o linter precisa para decidir sem adivinhar:
- `texto: str` — corpo renderizado (texto/HTML normalizado a texto).
- `canal: Canal` — enum `{ALERTA, COLD, NURTURE_TRANSACIONAL, PAGINA_PUBLICA, ONE_PAGER, RELATORIO}`. Define quais regras EXIGE (tabela §3).
- `url_fonte: str | None`, `excerto: str | None` — passados a `validar_alerta` quando o canal afirma factos regulatórios.
- `gerado_por_ia: bool` — se a peça foi redigida por modelo (dispara a exigência de divulgação de IA).
- `tem_optout_carimbado: bool` — sinal do seam de envio (o cold carimba o opt-out no seam `cold_email`, não no corpo do agente; ver §3 nota).

## 2. SAÍDA
```
@dataclass(frozen=True)
class ResultadoLint:
    aprovado: bool                 # True só se NENHUMA regra bloqueante falhar
    violacoes: list[Violacao]      # vazio se aprovado
    versao: str                    # "LINTER_VERSAO" — versionado como GUARDRAILS_VERSAO

@dataclass(frozen=True)
class Violacao:
    regra: str                     # id estável, ex. "R1_ILEGALIDADE"
    severidade: Severidade         # BLOQUEIA | AVISA
    trecho: str                    # excerto ofensor (para o agente corrigir)
    razao: str                     # mensagem PT-PT acionável
```
`aprovado = not any(v.severidade is BLOQUEIA for v in violacoes)`. Espelha o par `(valido, motivos)` de `ResultadoValidacao`, acrescentando `trecho` para regeneração dirigida.

## 3. REGRAS (deteção concreta)

**Citações da fonte são removidas antes da varredura** (mesma técnica de `guardrails._RE_CITACAO`: «…», "…", "…"): um excerto do regulamento pode conter "tem de" / "ilegal" e é legítimo citá-lo. Varre-se só a voz própria do agente.

### Proibições (BLOQUEIA)
- **R1 — Afirmar ilegalidade/incumprimento sobre o cliente/AL.** Regex sobre o texto sem-citações: `\b(ilegal|sem\s+seguro|em\s+incumprimento|incumprimento|em\s+infra(c)?[çc][aã]o|irregular(idade)?|est[áa]s?\s+obrigad|[ée]s\s+obrigad)\b` e reflexivos `\b(encontra|fica)-se\s+em\s+(incumprimento|infra)`. Já parcialmente coberto por `guardrails`; o linter reafirma como regra própria porque agora incide também em cold/páginas.
- **R2 — Conclusão jurídica (atividade reservada).** Delega em `validar_nao_prescritivo(texto)`: obrigação/dever pessoal + ato jurídico, infinitivo pessoal (`para regularizares/comunicares…`), prazo com dono (`tens N dias para…`), clítica (`compete-te…`). Qualquer `motivo` devolvido → Violação R2 BLOQUEIA.
- **R3 — Coima como ameaça individualizada.** BLOQUEIA se um valor de coima aparecer ligado à 2.ª pessoa/posse: `\b(a\s+tua|vais\s+ser|arriscas|podes\s+ser)\b.{0,40}(coima|multa(do)?)` ou `(coima|multa).{0,20}(que\s+te|para\s+ti)`. **Permitido** (AVISA→ok) só o condicional impessoal com moldura da fonte: `pode(m)?\s+ir\s+de\s+.{0,30}\s+a\s+` ancorado nos valores de `config.COIMA` (`singular 2 500–4 000 €`, `coletiva 25 000–40 000 €`). Qualquer coima fora destas molduras ou sem âncora no excerto → cai também em R6 (grounding).

### Exigências (BLOQUEIA se ausentes, por canal)

| Regra | Deteção | ALERTA | COLD | NURTURE | PÁGINA/ONE-PAGER |
|---|---|---|---|---|---|
| R4 link de fonte oficial | URL de `*.turismodeportugal.pt`/DRE/portal municipal presente **e** (se `url_fonte`) idêntico via `validar_alerta` | ✔ | — | — | ✔ |
| R5 divulgação de IA (AI Act art.50, desde 02/08/2026) | presença de marcador `AI-DISCLOSURE` ou frase-padrão "gerado/apoiado por IA" quando `gerado_por_ia` | ✔ | ✔ | ✔ | ✔ |
| R6 grounding de valores/prazos | `validar_alerta(texto, url_fonte, excerto)` → sem valores órfãos | ✔ | ✔(se cita coima) | — | ✔ |
| R7 disclaimer "informação, não aconselhamento" | regex `informa[çc][ãa]o[,]?\s+n[ãa]o\s+.{0,15}aconselhamento` | ✔ | ✔ | ✔ | ✔ |
| R8 opt-out 1-clique | link `checkal\.pt/remover` **ou** `tem_optout_carimbado=True` | — | ✔ | ✔ | — |
| R9 rodapé RGPD + identificação do remetente (só cold) | remetente `getcheckal\.com` (`config.COLD_FROM`) + `List-Unsubscribe` esperado no seam + identificação legal (Cosmic Oasis, Lda.) | — | ✔ | — | — |

**Nota R8/R9:** no cold, o opt-out RFC 8058 e o rodapé são carimbados pelo *seam* `cold_email.enviar_frio`, não pelo agente. O linter, sobre o rascunho do agente, verifica que **nada colide** e que `tem_optout_carimbado`/canal COLD estão coerentes; a ausência real do header é apanhada no seam. Fronteira dura mantida: o linter BLOQUEIA se um texto de canal COLD referir `checkal.pt` como remetente/domínio de envio em vez de `getcheckal.com` (proteção da reputação transacional).

## 4. ONDE CORRE NO PIPELINE
Corre **dentro da passagem single-shot do agente**, no passo "marcar aprovável", ANTES de escrever na fila de revisão:

- **ANGARIADOR:** depois de `motor.compor_email_frio` / `prospeccao.render_sequencia` e depois de gerar conteúdo consent-first (páginas-gatilho, one-pager). Só peças com `aprovado=True` entram em `ResultadoCampanha.pendentes_parecer` / fila de publicação. Corre **a montante** dos gates de envio (`pode_enviar_frio`), nunca os substitui — uma peça pode passar o linter e continuar retida pelo gate global (`pode_enviar_frio_global()==False`).
- **GESTOR-DE-CLIENTE:** sobre o relatório mensal composto (`relatorio.py` + template `relatorio_mensal`) e sobre respostas de suporte redigidas em `correr_suporte` antes de enviar/enfileirar; o G4 e os templates continuam embebidos, o linter é a rede final.
- É **puro e sem I/O de rede**: seguro sob `CHECKAL_MODO_TESTE`. `lista_dgc`/SMTP não lhe dizem respeito.

## 5. DESTINO DE UM RASCUNHO REPROVADO
Espelha a política já vigente em `guardrails`/`validacao` (regenerar → formato de recurso → humano):

1. **Volta ao agente para regeneração dirigida** (até N tentativas, p.ex. 2): as `Violacao.trecho`+`razao` alimentam o novo prompt. Regras de forma (R5/R7/R8) são tipicamente auto-corrigíveis inserindo os blocos em falta.
2. **Persistindo a reprovação** (violação de fundo R1/R2/R3/R6 que a regeneração não sana): a peça **NÃO é descartada silenciosamente** — cai em **formato de recurso** (para alerta/relatório, o formato manual/factual, seguro por construção) OU, para cold/páginas, é **enfileirada como `requer_atencao` e ESCALADA ao MAESTRO** no digest diário, nunca marcada aprovável.
3. **Registo/auditoria:** cada reprovação é logada com `regra`, `versao`, `trecho` (dossier de defesa; realimenta a curadoria das regras e a amostragem humana — camada 4). Nada reprovado chega ao gate de aprovação 1-clique; o MAESTRO só vê o que passou o linter.

**Viés inviolável (herdado):** o linter nunca produz um falso `aprovado` perante conclusão jurídica individualizada, ilegalidade afirmada, coima-ameaça ou valor órfão. Alargar a deteção é sempre seguro (mais rejeições → recurso/escala); nunca um falso "aprovado".

---
Ficheiros de grounding (todos absolutos):
- `/home/diogo/projetos/Gestor Diogo Trabalho/Ideias e vários/AL_New_ideia/checkal/app/ia/guardrails.py` (reutilizar `validar_nao_prescritivo`, `GUARDRAILS_VERSAO`, `_RE_CITACAO`)
- `/home/diogo/projetos/Gestor Diogo Trabalho/Ideias e vários/AL_New_ideia/checkal/app/ia/validacao.py` (reutilizar `validar_alerta`, `ResultadoValidacao` como molde da saída)
- `/home/diogo/projetos/Gestor Diogo Trabalho/Ideias e vários/AL_New_ideia/checkal/app/config.py` (`COIMA` §161 = molduras canónicas para R3; `COLD_FROM` para R9)
- `/home/diogo/projetos/Gestor Diogo Trabalho/Ideias e vários/AL_New_ideia/checkal/app/campanhas/cold_email.py` (`LINK_REMOCAO_BASE`, `MARCADOR_RODAPE`, List-Unsubscribe — fronteira R8/R9 carimbada no seam)
- Módulo novo proposto: `/home/diogo/projetos/Gestor Diogo Trabalho/Ideias e vários/AL_New_ideia/checkal/app/compliance/linter.py`

Nota: já existe cobertura parcial (alerta) em `guardrails.py`+`validacao.py`; o que falta construir é a camada de canal (COLD/NURTURE/PÁGINA) — regras R3/R5/R7/R8/R9 e o despacho por `Canal` — mais os testes espelho de `tests/test_ia_guardrails.py`/`test_ia_validacao.py`.