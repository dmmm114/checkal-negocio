"""Camada IA do CheckAL: seam LIVE-GATED sobre o SDK Anthropic (triagem + redação).

A IA entra **só no pipeline regulatório** (AUTOMACAO.md §3 / SPEC-IA): os alertas de
**estado do registo** (desaparecido/alterado) são determinísticos por template e nunca
passam pela IA. Aqui compõem-se dois passos, ambos servidos pelo mesmo cliente:

    - **Passo 1 — triagem** (:mod:`app.ia.triagem`): Haiku (`config.MODEL_TRIAGEM`),
      structured output JSON `{relevante_para_al, concelhos[], tipo, resumo_1_frase}`.
      Regra conservadora: `duvida` é tratado como `sim`.
    - **Passo 2 — redação** (:mod:`app.ia.alerta`): Sonnet (`config.MODEL_ALERTA`),
      prosa PT-PT, com as **três camadas anti-alucinação** (:mod:`app.ia.validacao`):
      template restritivo → validação programática (URL citada; valores/datas ⊂ excerto)
      → formato manual de recurso após 2 falhas.

Este pacote expõe o **ponto único de composição** — :func:`obter_cliente_ia` — que a
triagem/redação usam sem conhecer credenciais nem transporte. À imagem **exata** de
:func:`app.faturacao.obter_emissor` e :func:`app.envio.obter_enviador`, devolve o
cliente já ligado (ou ``None``); a triagem/redação recebem-no como `cliente_ia`
injetado.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** :func:`obter_cliente_ia` é o
**único sítio** que cria um cliente Anthropic real. Sob `config.CHECKAL_MODO_TESTE`
**ou** sem `config.ANTHROPIC_API_KEY` devolve ``None`` — pelo que correr os testes
nunca toca a IA/rede. Nos testes injeta-se um `cliente_ia` falso (que devolve
respostas scriptadas) em vez deste; a Anthropic real só liga em produção, quando o
dono desliga o modo de teste e há chave.

Nota RGPD (LEGAL.md; assinalado, não bloqueante do build): o excerto do documento +
dados do AL são enviados à Anthropic e os batches **não** são elegíveis a Zero Data
Retention — portão de go-live, registado à parte.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import app.config as config

if TYPE_CHECKING:  # só para tipos — o SDK importa-se tardiamente, e nunca nos testes
    from anthropic import Anthropic

__all__ = ["obter_cliente_ia"]


def obter_cliente_ia() -> Anthropic | None:
    """Compõe o cliente Anthropic (triagem + redação), ou ``None`` (LIVE-GATED).

    Devolve o cliente do SDK oficial `anthropic` — o **único** recurso de IA/rede da
    camada — pronto a ser injetado como `cliente_ia` em :func:`app.ia.triagem.triar` e
    :func:`app.ia.alerta.gerar_alerta`.

    Devolve ``None`` (sem importar sequer o SDK nem tocar na rede) quando:
      - `config.CHECKAL_MODO_TESTE` está ligado (o default nos testes), **ou**
      - falta `config.ANTHROPIC_API_KEY` (o SDK não pode autenticar).

    Nesse caso a triagem/redação recebem um `cliente_ia` falso (testes) ou tratam o
    ``None`` como "IA indisponível". Em produção (modo de teste desligado + chave)
    devolve o cliente real. Construir o cliente **não** faz nenhuma request — a rede só
    é tocada quando a triagem/redação chamam `messages`/`messages.batches`.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    if not config.ANTHROPIC_API_KEY:
        return None

    import anthropic  # import tardio: só quando de facto se liga em produção

    # A chave passa-se explicitamente (em vez de deixar o SDK lê-la do env) para que a
    # única fonte de verdade seja `config` — o mesmo valor que o live-gate acima checou.
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
