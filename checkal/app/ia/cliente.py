"""Wrapper fino sobre o SDK Anthropic: uma chamada estruturada (JSON) + uma de texto.

Fronteira do módulo (SPEC-FDS4 §BASE + SPEC-IA §2/§3/§4): recebe um cliente Anthropic
já composto (**injetado** pelo seam :func:`app.ia.obter_cliente_ia`) e faz **uma** chamada
ao modelo, devolvendo o resultado já normalizado. Dois modos, um por passo do pipeline:

    - :func:`pedir_json` — **Passo 1, triagem** (Haiku, `config.MODEL_TRIAGEM`). Structured
      output (`output_config.format` com `json_schema`) garante que o 1.º bloco de texto é
      JSON do schema → devolve um `dict`. Haiku não usa adaptive thinking (fica off por
      omissão) → **não** se envia `thinking`.
    - :func:`pedir_texto` — **Passo 2, redação** (Sonnet, `config.MODEL_ALERTA`). Prosa
      PT-PT → devolve `str`. No Sonnet 5 o adaptive thinking está LIGADO por omissão, pelo
      que se envia `thinking={"type": "disabled"}` explícito (redação determinística a
      seguir a template; latência irrelevante).

Regras invioláveis da forma do pedido (SPEC-IA §4.2 — *gotchas* do Sonnet 5):
  - **Nunca** se envia `temperature`/`top_p`/`top_k` — o Sonnet 5 devolve **400** a qualquer
    parâmetro de amostragem. A fidelidade vem do prompt + validação, não da temperatura.
  - `output_config` (JSON) e `thinking` (texto) são exclusivos de cada modo.
  - O `sistema` (str **ou** lista de blocos de conteúdo) passa **intacto** — é quem chama
    (`app.ia.alerta`) que põe o excerto no último bloco com `cache_control` ttl 1h; este
    wrapper é agnóstico à cache (ordena estável→volátil quem monta o prompt).

A submissão/polling do Batch API real fica **atrás desta interface** (SPEC-FDS4 §fora de
âmbito): a triagem/redação só veem `pedir_json`/`pedir_texto`, nunca `.messages` direto —
trocar o transporte síncrono por batch mexe só aqui. Em produção o critério de "feito"
(SPEC-IA §6.1) é uma `messages.create` síncrona; o batch entra depois sem mudar os chamadores.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria nem importa
nenhum cliente Anthropic — o `cliente_ia` é sempre **injetado** por quem chama (falso nos
testes; SDK real só em produção, composto por :func:`app.ia.obter_cliente_ia`). Assim, correr
os testes nunca toca a IA/rede.

O `cliente_ia` é qualquer objeto à laia de `anthropic.Anthropic` com:
  - ``messages.create(*, model, max_tokens, messages, ...) -> mensagem``
onde `mensagem` expõe ``content`` (lista de blocos com ``.type`` e ``.text``) e ``stop_reason``.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

__all__ = [
    "ErroIA",
    "pedir_json",
    "pedir_texto",
    "MAX_TOKENS_JSON",
    "MAX_TOKENS_TEXTO",
    "THINKING_DESLIGADO",
]

# Folga de `max_tokens` por passo (SPEC-IA §3/§4.2). Triagem: JSON curto (~200 tok) →
# 400 chega e sobra. Redação: ≤180 palavras mas o tokenizer do Sonnet 5 gasta ~30% mais →
# 700 dá margem sem risco de truncar. Ambos parametrizáveis por quem chama.
MAX_TOKENS_JSON = 400
MAX_TOKENS_TEXTO = 700

# Sonnet 5 tem adaptive thinking LIGADO por omissão (queima tokens de pensamento contra o
# `max_tokens`); desliga-se explicitamente para redação determinística (SPEC-IA §4.2).
THINKING_DESLIGADO = {"type": "disabled"}


class ErroIA(RuntimeError):
    """A resposta do modelo não trouxe o resultado esperado (sem texto, ou JSON inválido)."""


# ==========================================================================
#  Helpers internos — leitura da resposta (à laia de `anthropic.types.Message`)
# ==========================================================================
def _texto_da_mensagem(mensagem: Any) -> str:
    """Concatena o texto de todos os blocos ``type == "text"`` da resposta.

    Uma resposta normal traz um único bloco de texto; junta-se por robustez. Blocos não
    textuais (ex. `thinking`, `tool_use`) são ignorados. Sem qualquer bloco de texto (ex.
    um `refusal` sem prosa) devolve ``""`` — cabe a quem chama decidir (a validação do
    alerta reprova e cai no formato manual; :func:`pedir_json` trata como erro).
    """
    blocos = getattr(mensagem, "content", None) or []
    partes = [
        b.text
        for b in blocos
        if getattr(b, "type", None) == "text" and getattr(b, "text", None)
    ]
    return "".join(partes)


def _corpo_base(*, modelo: str, sistema: Any, utilizador: str, max_tokens: int) -> dict[str, Any]:
    """Monta a parte comum do request (model + max_tokens + messages [+ system]).

    Nunca inclui parâmetros de amostragem (`temperature`/`top_p`/`top_k` → 400 no Sonnet 5).
    O `sistema` (str ou lista de blocos) passa intacto; ausente (`None`) → sem `system`.
    """
    corpo: dict[str, Any] = {
        "model": modelo,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": utilizador}],
    }
    if sistema is not None:
        corpo["system"] = sistema
    return corpo


# ==========================================================================
#  Passo 1 — triagem (Haiku): structured output → dict
# ==========================================================================
def pedir_json(
    cliente_ia: Any,
    *,
    modelo: str,
    utilizador: str,
    esquema: dict[str, Any],
    sistema: str | Sequence[Any] | None = None,
    max_tokens: int = MAX_TOKENS_JSON,
) -> dict[str, Any]:
    """Chama o modelo com **structured output** e devolve o JSON garantido como `dict`.

    Parâmetros
    ----------
    cliente_ia:
        Cliente Anthropic **injetado** (falso nos testes; nunca criado aqui — LIVE-GATED).
    modelo:
        Model id (ex. `config.MODEL_TRIAGEM`).
    utilizador:
        Conteúdo da mensagem `user` (título + ~3.000 primeiras palavras do documento).
    esquema:
        JSON Schema do output (passado cru em `output_config.format`). É de quem chama
        (`app.ia.triagem`) — este wrapper é agnóstico ao domínio.
    sistema:
        Instruções de sistema opcionais (str ou lista de blocos); ausente → sem `system`.
    max_tokens:
        Teto de tokens de saída (default :data:`MAX_TOKENS_JSON`).

    Devolve o `dict` de `json.loads` do 1.º bloco de texto (o schema garante que é JSON).
    Não envia `thinking` (Haiku: off por omissão) nem parâmetros de amostragem.

    Levanta
    -------
    ErroIA
        A resposta não trouxe texto, ou o texto não é JSON válido.
    """
    corpo = _corpo_base(
        modelo=modelo, sistema=sistema, utilizador=utilizador, max_tokens=max_tokens
    )
    corpo["output_config"] = {"format": {"type": "json_schema", "schema": esquema}}

    mensagem = cliente_ia.messages.create(**corpo)

    texto = _texto_da_mensagem(mensagem).strip()
    if not texto:
        raise ErroIA("Resposta de triagem sem bloco de texto (JSON não disponível).")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:  # structured output falhou (ex. refusal) → erro claro
        raise ErroIA(f"Resposta de triagem não é JSON válido: {e}") from e
    if not isinstance(dados, dict):
        raise ErroIA("Resposta de triagem não é um objeto JSON.")
    return dados


# ==========================================================================
#  Passo 2 — redação (Sonnet): prosa PT-PT → str
# ==========================================================================
def pedir_texto(
    cliente_ia: Any,
    *,
    modelo: str,
    utilizador: str,
    sistema: str | Sequence[Any] | None = None,
    max_tokens: int = MAX_TOKENS_TEXTO,
) -> str:
    """Chama o modelo em modo de texto e devolve a prosa (`str`).

    Parâmetros
    ----------
    cliente_ia:
        Cliente Anthropic **injetado** (falso nos testes; nunca criado aqui — LIVE-GATED).
    modelo:
        Model id (ex. `config.MODEL_ALERTA`).
    utilizador:
        Conteúdo da mensagem `user` — os DADOS DO AL específicos deste cliente (varia por
        par evento×cliente; sem `cache_control`).
    sistema:
        Papel + regras invioláveis + EXCERTO do documento (str ou lista de blocos). Quem
        chama (`app.ia.alerta`) põe o excerto no último bloco com `cache_control` ttl 1h;
        este wrapper passa a estrutura intacta.
    max_tokens:
        Teto de tokens de saída (default :data:`MAX_TOKENS_TEXTO`).

    Envia `thinking={"type": "disabled"}` (Sonnet 5: adaptive thinking ligado por omissão)
    e **nunca** parâmetros de amostragem nem `output_config`. Sem qualquer bloco de texto
    (ex. `refusal` sem prosa) devolve ``""`` — a validação a jusante reprova e cai no
    formato manual de recurso (nunca fica nada por comunicar).
    """
    corpo = _corpo_base(
        modelo=modelo, sistema=sistema, utilizador=utilizador, max_tokens=max_tokens
    )
    corpo["thinking"] = THINKING_DESLIGADO

    mensagem = cliente_ia.messages.create(**corpo)
    return _texto_da_mensagem(mensagem)
