# CheckAL — Enxame de agentes autónomos no Polaris (pacote de execução)

> Pacote build-ready para dar ao **Claude fable / ultracode**. Desenho fechado a 2026-07-18.
> **Ponto de entrada para construir: [`01-PROMPT-MESTRE-FABLE.md`](01-PROMPT-MESTRE-FABLE.md).**

## O que é
A camada de **4 agentes single-shot** (Claude CLI headless, systemd, memória capada — resolve o OOM do
Polaris) que **supervisiona, redige e orquestra por cima** do backbone determinista já construído, **sem
o reimplementar nem contornar os gates**. Converte trabalho autónomo numa **decisão diária de 1 clique**
para o dono, atrás de um portão human-in-the-loop.

## Os 4 agentes (cada um mapeia a um objetivo)
| Agente | Objetivo | Missão em 1 linha |
|---|---|---|
| **MAESTRO** | Governação | Orquestra os outros, consolida métricas, compõe o digest diário, opera o **único gate de aprovação 1-clique**, aplica tetos de custo, recebe escalações. Quem PROPÕE nunca é quem APROVA. |
| **ANGARIADOR** | Crescer | Deteta gatilhos → segmenta coletivas (NIF 5/6, email genérico) → redige cold + conteúdo → **linter** → fila de revisão. Não envia, não publica. Atrás do portão do cold. |
| **GESTOR-DE-CLIENTE** | Reter | Onboarding, **relatório mensal anti-churn**, dunning/renovação por referência, suporte (IMAP→triagem, escala o sensível), win-back, reconciliação de transferências. |
| **SENTINELA-SERVIÇO** | Entregar | Watchdog independente: confirma que o serviço foi **efetivamente** prestado (varrimento fresco, snapshot persistido, alerta≠alucinação, breaker confirma cancelamentos). Timer próprio, fora de fase do Maestro. |

## Ordem de leitura
1. **[`DECISOES-EXECUCAO.md`](DECISOES-EXECUCAO.md)** — decisões autoritativas do dono (pagamento, IfThenPay, TOConline, domínios). **Em conflito, mandam estas.**
2. **[`00-ARQUITETURA.md`](00-ARQUITETURA.md)** — fonte de verdade do sistema (loop, estado, gates, RAM, rollout).
3. **[`agentes/*.md`](agentes/)** — spec completa + prompt operacional + unit systemd por agente.
4. **[`harness/*.md`](harness/)** — `db` (esquema), `linter` (guarda), `obs` (systemd/custos/alarmes), `loop` (métricas/feedback), `compliance` (checklist).
5. **[`RED-TEAM.md`](RED-TEAM.md)** — 27 achados adversariais (legal · RAM/autonomia · coerência-código) e as correções.
6. **[`PAGAMENTOS-IFTHENPAY.md`](PAGAMENTOS-IFTHENPAY.md)** — a via de pagamento cold-direto.
7. **[`01-PROMPT-MESTRE-FABLE.md`](01-PROMPT-MESTRE-FABLE.md)** — o que colas no fable para construir (inclui as fases A–G).

## O que o red-team encontrou (muda a ORDEM de construção)
O desenho assume peças que **ainda não existem no código** — o prompt-mestre constrói-as primeiro:
- **O linter (`app.linter`) não existe** → toda a garantia legal depende dele → **Fase B, bloqueante**.
- **A fila de revisão (`revisao_itens`) não existe** (models.py tem 12 tabelas, nenhuma é a fila) → **Fase A**.
- **Os subcomandos `manage.py` que os agentes chamam não existem** → **Fase D**.
- **Copy fria com assunto individualizado** (`prospeccao.py`) → risco DL 57/2008 + Lei 10/2024 → correção obrigatória.
- **Feed DGC vazio / suporte IA fora do gate / cgroup ineficaz / tetos sem enforcement** → corrigidos como gates fail-closed.

## Como pôr o fable a construir
Aponta o Claude fable (ultracode) a **`01-PROMPT-MESTRE-FABLE.md`**. Ele constrói por fases (A→G), cada
uma termina com testes verdes, **tudo LIVE-GATED** (nada envia/cobra/publica sem chaves + gate aberto +
aprovação) e os **1344 testes existentes continuam verdes**. Os timers ficam `disabled` até tu os ativares.

## Como afinar depois (a superfície de tuning)
- **Voz/limites de cada agente:** `prompts/*.txt` (instalados em `checkal/prompts/*.txt`).
- **Regras de compliance/linter:** `harness/linter.md` + `harness/compliance.md`.
- **Cadência/RAM/custos:** os `.timer`/`.service` em `systemd/` + `TETO_DIARIO_EUR`.
- **O que converte:** o digest de métricas do Maestro guia os ajustes (à escala atual é curadoria humana, não ML).

## O que ainda depende de ti (externo ao código)
1. **DPA comercial da Anthropic** assinado → só então `CHECKAL_ANTHROPIC_DPA_OK=True`.
2. **Domínio de envio do cold** (getcheckal.com ou equivalente) garantido + SMTP/warm-up.
3. **Série CKL** registada no TOConline/AT + **smoke-test** da 1.ª emissão real.
4. **Chaves IfThenPay** (já tens conta) apontadas ao CheckAL; **parecer/gate do cold** (`CHECKAL_PARECER_RGPD_OK`) só quando decidires.
5. Ligar o widget consent-first (`CHECKAL_API_ORIGIN`) e o deploy (RUNBOOK).
