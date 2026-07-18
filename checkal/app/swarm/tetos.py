"""Tetos de custo LLM, flag de pausa e escalação — app.swarm.tetos (Fase C).

O circuito de contenção de custo do enxame no Polaris:

  - :func:`registar_custo` parseia o `usage` do `claude -p --output-format json`
    e grava em `custo_llm` (tokens exatos + custo em CÊNTIMOS, arredondado POR
    EXCESSO — o teto dispara mais cedo, nunca mais tarde);
  - :func:`teto_atingido` soma o gasto do dia vs `config.TETO_DIARIO_EUR`
    (+ sub-teto por agente via :func:`teto_agente_atingido`);
  - :func:`verificar_e_pausar` cria a flag-ficheiro `PAUSA_LLM`
    (`config.PAUSA_LLM_PATH`): os crons DETERMINISTAS continuam a correr — só os
    passos LLM pausam (o wrapper `correr-agente.sh` verifica a flag);
  - :func:`escalar` regista a escalação (`escalacoes` + `eventos_agente`) que o
    MAESTRO consolida no digest/página.

REGRA DURA (inviolável, testada): os tetos pausam trabalho LLM e paginam o dono;
NUNCA tocam nos gates de segurança (`pode_enviar_frio_global`, `CHECKAL_MODO_TESTE`,
`CHECKAL_PARECER_RGPD_OK`, DPA) — esses são independentes e só o dono os liberta.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

from sqlalchemy import func

import app.config as config
import app.models_swarm as ms

__all__ = [
    "PRECOS_EUR_MTOK",
    "registar_custo",
    "custo_do_dia_eur",
    "teto_atingido",
    "teto_agente_atingido",
    "flag_pausa_llm",
    "pausa_llm_ativa",
    "limpar_pausa_llm",
    "verificar_e_pausar",
    "escalar",
]

# Preços de referência (EUR por Mtok: input, output). Tratam-se os preços USD
# como EUR — sobreestimativa deliberada (o teto dispara mais cedo; direção
# segura). Modelo desconhecido/ausente ⇒ assume-se o mais caro (Sonnet).
PRECOS_EUR_MTOK: dict[str, tuple[float, float]] = {
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
}
_MODELO_DEFAULT = "sonnet"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _precos_do_modelo(modelo: str | None) -> tuple[float, float]:
    nome = (modelo or "").lower()
    for chave, precos in PRECOS_EUR_MTOK.items():
        if chave in nome:
            return precos
    return PRECOS_EUR_MTOK[_MODELO_DEFAULT]


def _extrair_usage(usage_json: dict) -> tuple[int, int, str | None]:
    """(input_tokens, output_tokens, modelo) do JSON do CLI — tolerante à forma.

    Aceita o objeto completo do `--output-format json` (com `usage` aninhado e
    `model` ao lado) ou o próprio `usage` achatado. Tokens de cache contam como
    input ao preço cheio (sobreestimativa — direção segura).
    """
    usage = usage_json.get("usage") if isinstance(usage_json.get("usage"), dict) else usage_json
    entrada = int(usage.get("input_tokens") or 0)
    entrada += int(usage.get("cache_creation_input_tokens") or 0)
    entrada += int(usage.get("cache_read_input_tokens") or 0)
    saida = int(usage.get("output_tokens") or 0)
    modelo = usage_json.get("model") or usage.get("model")
    return entrada, saida, modelo


def registar_custo(
    session,
    agente: str,
    usage_json: dict,
    *,
    dia: date | None = None,
    modelo: str | None = None,
) -> ms.CustoLlm:
    """Grava uma linha em `custo_llm` a partir do `usage` de uma invocação.

    O custo é estimado pela tabela de preços do modelo (Haiku triagem / Sonnet
    redação) e guardado em cêntimos POR EXCESSO (`ceil`). A transação é do
    chamador (sem commit aqui).
    """
    entrada, saida, modelo_visto = _extrair_usage(usage_json or {})
    preco_in, preco_out = _precos_do_modelo(modelo or modelo_visto)
    custo_eur = entrada / 1_000_000 * preco_in + saida / 1_000_000 * preco_out
    linha = ms.CustoLlm(
        dia=dia or _agora().date(),
        agente=agente,
        input_tokens=entrada,
        output_tokens=saida,
        custo_eur_cent=math.ceil(custo_eur * 100),
        criado_em=_agora(),
    )
    session.add(linha)
    session.flush()
    return linha


def custo_do_dia_eur(session, dia: date | None = None, *, agente: str | None = None) -> float:
    """Soma o gasto do `dia` (todos os agentes, ou um só) em EUR."""
    q = session.query(func.coalesce(func.sum(ms.CustoLlm.custo_eur_cent), 0)).filter(
        ms.CustoLlm.dia == (dia or _agora().date())
    )
    if agente is not None:
        q = q.filter(ms.CustoLlm.agente == agente)
    return q.scalar() / 100.0


def teto_atingido(session, dia: date | None = None) -> bool:
    """O gasto agregado do dia atingiu `config.TETO_DIARIO_EUR`?"""
    return custo_do_dia_eur(session, dia) >= config.TETO_DIARIO_EUR


def teto_agente_atingido(session, agente: str, dia: date | None = None) -> bool:
    """O gasto do `agente` no dia atingiu o sub-teto `config.TETO_AGENTE_EUR`?"""
    return custo_do_dia_eur(session, dia, agente=agente) >= config.TETO_AGENTE_EUR


# ==========================================================================
#  Flag-ficheiro PAUSA_LLM — pausa passos LLM; crons deterministas continuam
# ==========================================================================
def flag_pausa_llm() -> None:
    """Cria a flag `PAUSA_LLM` (idempotente). NÃO toca gates de segurança."""
    caminho = config.PAUSA_LLM_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.touch(exist_ok=True)


def pausa_llm_ativa() -> bool:
    return config.PAUSA_LLM_PATH.exists()


def limpar_pausa_llm() -> None:
    """Remove a flag (timer de reset à meia-noite, ou o dono manualmente)."""
    config.PAUSA_LLM_PATH.unlink(missing_ok=True)


def verificar_e_pausar(session, dia: date | None = None) -> bool:
    """Se o teto diário foi atingido, cria a PAUSA_LLM e devolve True.

    Chamado pelo wrapper antes de cada invocação LLM e após `registar_custo`.
    Não pagina aqui — quem deteta True chama :func:`escalar` (P1).
    """
    if teto_atingido(session, dia):
        flag_pausa_llm()
        return True
    return False


# ==========================================================================
#  Escalação — a linha que o MAESTRO consolida
# ==========================================================================
def escalar(
    session,
    *,
    severidade: str,
    agente: str,
    mensagem: str,
    execucao_id: str | None = None,
) -> ms.Escalacao:
    """Escreve a escalação em `escalacoes` (+ rasto em `eventos_agente`)."""
    linha = ms.Escalacao(
        agente=agente, severidade=severidade, mensagem=mensagem,
        execucao_id=execucao_id, criado_em=_agora(),
    )
    session.add(linha)
    session.add(
        ms.EventoAgente(
            agente=agente, execucao_id=execucao_id, tipo="escalada",
            severidade="critico" if severidade == "critica" else "aviso",
            mensagem=mensagem, criado_em=_agora(),
        )
    )
    session.flush()
    return linha
