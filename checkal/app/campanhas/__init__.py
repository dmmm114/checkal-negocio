"""Motor de campanhas do CheckAL (FDS 6): gatilho → segmento → envio — HARD-GATED.

A partir de um evento de negócio (registo RNAL novo, limpeza de um concelho,
alteração relevante) o motor deteta gatilhos, segmenta os prospetos pelo **núcleo
de compliance** (`app.compliance.*`) e compõe a peça de prospeção correspondente
— tudo sem toque humano, dentro da janela de `config.CAMPANHA_JANELA_H`.

🚦 **O canal de email frio é HARD-GATED.** É código, não disciplina humana:

  - O PORTÃO é `config.CHECKAL_PARECER_RGPD_OK` (default **False**): enquanto o
    dono não tiver o parecer favorável do jurista RGPD (CLAUDE.md / LEGAL.md §1),
    **nenhum** email frio sai. Um prospeto elegível fica em fila `pendente_parecer`.
  - O envio frio é TRIPLAMENTE gated por `config.pode_enviar_frio_global()`
    (parecer OK **e** modo de teste OFF **e** SMTP de cold configurado) **e**, por
    contacto, pelo núcleo de compliance: coletiva 5/6 (`nif.e_enderecavel`) **e**
    email genérico (`email.e_generico`) via `minimizacao.filtrar_enderecaveis`,
    **e** não oposto/opt-out (`optout.filtrar_optout`).
  - **Singular/ENI e email de aspeto pessoal NUNCA recebem cold** — só carta
    (upload manual e-carta) ou consentimento/parcerias.

Fronteira DURA (SPEC-RESEND §0): o cold usa o domínio irmão `getcheckal.com` +
SMTP dedicado (`config.COLD_SMTP_*`), num módulo **separado** — **nunca** importa
`app.envio` (Resend). Cada email frio leva remetente identificado + opt-out
1-clique (`checkal.pt/remover`) e regista a proveniência (prova de lookup
dirigido, não scraping). Sem scraping à escala.

Submódulos (contrato em SPEC-FDS6.md §módulos):
    gatilhos     — deteta candidatos a partir dos eventos não usados (idempotente)
    segmentacao  — separa cold_email / carta / descartados via núcleo de compliance
    carta        — lote PDF mail-merge para upload manual ao portal e-carta (CTT)
    cold_email   — remetente frio LIVE-GATED **e** PARECER-GATED (SMTP getcheckal.com)
    motor        — orquestra gatilho → segmento → composição → envio/pendente_parecer
"""
from __future__ import annotations
