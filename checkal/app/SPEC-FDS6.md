# FDS 6 — Motor de campanhas: gatilho → segmento → envio (HARD-GATED)

> Contrato de construção. Alinhado com AUTOMACAO.md §7 (FDS 6), GTM.md, COPY-VENDAS.md,
> LEGAL.md e o **núcleo de compliance** (`app/compliance/*`, PASSO 0–3 desta sessão).
> Critério de "feito": um registo novo inserido em teste gera, sem toque humano, o
> email/carta de prospeção correspondente dentro da janela de 72h — **mas o envio a frio
> permanece BLOQUEADO até ao parecer RGPD**.

## 🚦 PORTÃO BLOQUEANTE (o coração deste sprint — inviolável)
O canal frio eletrónico é **PROIBIDO** até o dono ter o parecer favorável do jurista RGPD
(CLAUDE.md / LEGAL.md). Isto é código, não disciplina:

- `config.CHECKAL_PARECER_RGPD_OK` (default **`False`**). Nenhum email frio sai enquanto `False`.
- **Envio frio triplamente gated** — `pode_enviar_frio(contacto) -> bool` só é `True` se, CUMULATIVAMENTE:
  1. `config.CHECKAL_PARECER_RGPD_OK is True` **e** `config.CHECKAL_MODO_TESTE is False`;
  2. o contacto passa o **núcleo de compliance**: `nif.e_enderecavel` (coletiva 5/6) **e**
     `email.e_generico` (genérico) — via `minimizacao.filtrar_enderecaveis` (singulares/pessoais
     descartados de imediato);
  3. **não** consta da oposição DGC nem do opt-out (`optout.filtrar_optout`).
- **Singular/ENI → email frio NUNCA.** Só carta (e-carta, upload manual) ou consentimento/parcerias.
- **Cold NUNCA toca o Resend** (AUP proíbe; reputação do checkal.pt é ativo — de-risco G5): domínio
  irmão `getcheckal.com` + SMTP dedicado (`config.COLD_SMTP_*`), módulo separado.
- Sem scraping: a descoberta de email é a que já está publicada (fatia endereçável do PASSO 0).

## Módulos e contrato (fronteiras disjuntas)

### `app/config.py` (aditivo)
`CHECKAL_PARECER_RGPD_OK=False` (o portão), `COLD_SMTP_HOST/PORT/USER/PASS`, `COLD_FROM`
(getcheckal.com), `CAMPANHA_JANELA_H=72`, `CAMPANHA_CAP_DIARIO` (throttle/warm-up). Defaults seguros.

### `app/campanhas/gatilhos.py` + `tests/test_gatilhos.py`
`detetar_gatilhos(session) -> list[Gatilho]`: a partir de `eventos_registo`/`eventos_regulatorios`
não usados para campanha — registo **novo**, **limpeza** (desaparecidos em massa num concelho),
**alteração relevante** — produz candidatos (nrs + motivo). Idempotente (marca usado).

### `app/campanhas/segmentacao.py` + `tests/test_segmentacao.py`
`segmentar(registos) -> Segmentos{cold_email: [...], carta: [...], descartados: int}`: usa o
**núcleo de compliance** — `minimizacao.filtrar_enderecaveis` (só coletiva 5/6 + genérico entra em
`cold_email`); singulares e coletivas-com-email-pessoal → `carta` (ou descartados p/ email, nunca
cold). Cruza `optout.filtrar_optout` (DGC + opt-out) no ramo cold. **Regista a proveniência** de cada
contacto cold (prova de lookup dirigido, não scraping — PASSO 2). Testa com registos mistos: só
coletivas genéricas não-opostas entram em cold; nenhum singular/pessoal entra em cold; opt-out excluído.

### `app/campanhas/carta.py` + `tests/test_carta.py`
`gerar_lote_cartas(prospetos) -> bytes` (PDF multi-carta, mail-merge com nº RNAL + mini-diagnóstico
por prospeto — COPY-VENDAS.md). Para **upload manual** ao portal e-carta dos CTT (não automatizado).
Testa: PDF %PDF, uma página/secção por prospeto, sem inventar dados.

### `app/campanhas/cold_email.py` + `tests/test_cold_email.py`
`obter_remetente_frio() -> callable|None` LIVE-GATED **e PARECER-GATED**: devolve `None` se
`not pode_enviar_frio_global()` (parecer off / modo teste / sem SMTP). `enviar_frio(*, para, assunto,
html, cliente_smtp)` via `COLD_SMTP_*` (getcheckal.com), com identificação clara do remetente + link
opt-out 1-clique (`checkal.pt/remover`) em cada email (PASSO 2). `cliente_smtp` injetado; **NUNCA**
importa/usa o Resend. Testa: sem parecer → None (nada envia); com tudo ligado (mock) → envia com
remetente identificado + link de remoção.

### `app/campanhas/motor.py` + `tests/test_motor.py`
`correr_campanhas(session, *, remetente_frio=None, gerar_cartas=None) -> ResultadoCampanha`:
gatilhos → segmentação (compliance) → compõe (copy de COPY-VENDAS.md) → para o segmento **cold**,
só envia via `remetente_frio` se `pode_enviar_frio(contacto)` (triplo gate) — senão fica em fila
`pendente_parecer`; para o segmento **carta**, gera o PDF (upload manual). Janela ≤72h; cap/throttle
diário; log de todos os opt-outs e proveniências. Idempotente. Testa: com parecer OFF, um registo
novo coletivo-genérico gera o draft mas **NÃO envia** (fica pendente_parecer); singular gera carta.

## Fora de âmbito / proibido
NUNCA: scraping à escala; email frio a singular/ENI; email a local-part pessoal; envio sem parecer;
cold pelo Resend. O warm-up do domínio e a escolha do provider SMTP são operacionais (checklist do dono).
