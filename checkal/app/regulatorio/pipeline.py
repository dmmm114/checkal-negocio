"""Pipeline regulatório ponta-a-ponta: `eventos_regulatorios` → triagem → alertas → envio.

Fronteira do módulo (SPEC-FDS4 §pipeline, SPEC-IA §1, AUTOMACAO.md §3): drena a fila de
`eventos_regulatorios` por processar (captados pelo :mod:`app.regulatorio.dre_pipeline`) e,
para cada um::

    correr_pipeline(session, *, cliente_ia, enviar, eventos=None) -> ResultadoPipeline

  1. **Triagem (Haiku)** — :func:`app.ia.triagem.triar`. Persiste-se o veredicto no evento
     (`triagem` = `relevante`|`irrelevante`|`duvida`, `resumo_ia`) e marca-se
     `processado=True` (âncora de idempotência). 🧯 Regra conservadora: `duvida` conta como
     `sim` (:func:`app.ia.triagem.e_relevante`) — nunca se cala por dúvida.
  2. **Cruzamento** — para cada evento relevante, cruzam-se os concelhos afetados (os do
     evento, canónicos; ou, em falta, os da triagem) com os clientes **ativos** que têm um
     AL nesses concelhos (via `clientes_registos`).
  3. **Redação (Sonnet) + 3 camadas anti-alucinação** — :func:`app.ia.alerta.gerar_alerta`
     por par (evento × AL do cliente), com o **excerto** do ato como única fonte de verdade
     de montantes/datas/prazos. O alerta devolvido **passa sempre** a validação (a camada 3
     é o formato manual de recurso citado). Persiste-se em `alertas`
     (`origem='eventos_regulatorios'`, `origem_id=evento.id`) e envia-se pelo `enviar`
     injetado.

Ao contrário dos alertas de **estado do registo** (`desaparecido`/`alterado`, geridos por
:mod:`app.alertas_estado`), os alertas regulatórios **não** têm a guarda de sequência do
FDS 5 (essa é só para `desaparecido`): um documento publicado é um facto imediato — envia-se.

**Excerto:** lê-se de `evento.texto` (o corpo do ato, anexado em memória pelo
`dre_pipeline`) e, em falta, do `evento.titulo` (degradação segura — a validação impede
qualquer valor que o excerto não sustente). O corpo **não** é persistido (o esquema de
`eventos_regulatorios` não tem coluna de texto), pelo que só está disponível nas
**instâncias vivas** que o `dre_pipeline` acabou de criar: passa-se
`eventos=resultado_dre.eventos` para a IA receber o corpo por excerto. No caminho de
varrimento da fila (`eventos=None`, um cron separado que re-lê a BD), os eventos vêm sem
corpo e o excerto degrada-se ao **título** — seguro, mas mais conservador. (Não se confia
no atributo transitório sobreviver a uma releitura: o mapa de identidade do SQLAlchemy usa
referências fracas, logo um objeto sem referência forte é recarregado sem o `.texto`.)

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** `cliente_ia` e `enviar` são
**injetados** por quem chama (dublês nos testes; em produção
:func:`app.ia.obter_cliente_ia` e :func:`app.envio.obter_enviador`). Este módulo nunca cria
clientes de IA/HTTP — correr os testes nunca toca a rede. `cliente_ia is None` (IA
indisponível) faz a triagem propagar/os alertas caírem no formato manual; `enviar is None`
(envio indisponível) persiste o alerta por enviar (`enviado_em IS NULL`). A função recebe a
`session` de quem chama e **não** faz commit — a transação é do orquestrador: se `enviar`
levantar, o rollback do chamador reverte tudo e os eventos ficam por processar (retry
natural; o `idempotency_key` do envio evita duplicados no fornecedor).

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from typing import Any

import app.models as models
from app.ia import triagem as _triagem
from app.ia.alerta import gerar_alerta

__all__ = [
    "ResultadoPipeline",
    "correr_pipeline",
    "ORIGEM_REGULATORIO",
    "CANAL_EMAIL",
]

# Valor de `Alerta.origem` para os alertas nascidos da fila `eventos_regulatorios`
# (a par de "eventos_registo", de `app.alertas_estado`).
ORIGEM_REGULATORIO = "eventos_regulatorios"

# Canal de entrega (o único do Canal A transacional — Resend).
CANAL_EMAIL = "email"

# Mapa relevância da triagem → valor persistido em `EventoRegulatorio.triagem`
# ('relevante'|'irrelevante'|'duvida', conforme o comentário do modelo).
_TRIAGEM_PERSIST: dict[str, str] = {
    "sim": "relevante",
    "duvida": "duvida",
    "nao": "irrelevante",
}

# Estado de cliente que NÃO recebe alertas (assinatura terminada).
_ESTADO_CANCELADO = "cancelado"

# Disclaimer factual repetido em cada alerta (informação, não aconselhamento — LEGAL.md).
_DISCLAIMER = (
    "Isto é informação a partir de fontes públicas (Diário da República); não constitui "
    "aconselhamento jurídico."
)

# Assinatura do enviador injetado (só para leitura; não impõe verificação).
Enviar = Callable[..., Any]


# ==========================================================================
#  Resultado de uma corrida (para logs/testes; a BD é a fonte de verdade)
# ==========================================================================
@dataclass
class ResultadoPipeline:
    """Sumário de uma corrida do pipeline regulatório.

    :param alertas: os `alertas` criados nesta passagem (enviados **e** por enviar).
    :param eventos_processados: quantos `eventos_regulatorios` foram triados nesta corrida.
    :param eventos_relevantes: destes, quantos seguiram para redação (`sim`/`duvida`).
    :param enviados: quantos alertas foram efetivamente entregues pelo `enviar`.
    """

    alertas: list[models.Alerta] = field(default_factory=list)
    eventos_processados: int = 0
    eventos_relevantes: int = 0
    enviados: int = 0


# ==========================================================================
#  Auxiliares puros — excerto, cruzamento, copy
# ==========================================================================
def _excerto_do_evento(evento: Any) -> str:
    """Excerto (fonte de verdade da IA): `.texto` (corpo do ato) ou o título, em falta."""
    return (getattr(evento, "texto", None) or (evento.titulo or "") or "").strip()


def _concelhos_afetados(evento: Any, triagem: _triagem.Triagem) -> list[str]:
    """Concelhos a cruzar: os do evento (canónicos) ou, em falta, os da triagem."""
    return list(evento.concelhos or []) or list(triagem.concelhos or [])


def _clientes_com_al(
    session: Any, concelhos: list[str]
) -> list[tuple[models.Cliente, models.Registo]]:
    """Pares (cliente ativo, AL) com um registo num dos `concelhos` afetados.

    Um cliente cancelado nunca recebe (assinatura terminada); clientes ativos, em dunning
    ou de estado por definir recebem. Ordena por cliente e registo (determinístico).
    """
    if not concelhos:
        return []
    q = (
        session.query(models.Cliente, models.Registo)
        .join(models.ClienteRegisto, models.ClienteRegisto.cliente_id == models.Cliente.id)
        .join(models.Registo, models.Registo.nr_registo == models.ClienteRegisto.nr_registo)
        .filter(models.Registo.concelho.in_(list(concelhos)))
        .filter(
            (models.Cliente.estado.is_(None))
            | (models.Cliente.estado != _ESTADO_CANCELADO)
        )
        .order_by(models.Cliente.id, models.Registo.nr_registo)
    )
    return q.all()


def _assunto(registo: models.Registo) -> str:
    """Assunto do email do alerta regulatório (menciona o concelho do AL, se houver)."""
    concelho = (getattr(registo, "concelho", None) or "").strip()
    if concelho:
        return f"CheckAL: novo documento regulatório que pode afetar o teu AL em {concelho}"
    return "CheckAL: novo documento regulatório que pode afetar o teu AL"


def _html(conteudo: str, url_fonte: str) -> str:
    """Envolve o alerta num corpo HTML mínimo: texto + link da fonte + disclaimer."""
    partes = [f"<p>{escape(conteudo)}</p>"]
    if url_fonte:
        partes.append(f'<p><a href="{escape(url_fonte)}">{escape(url_fonte)}</a></p>')
    partes.append(
        f'<p style="font-size:.85em;color:#6b7280">{escape(_DISCLAIMER)}</p>'
    )
    return "".join(partes)


# ==========================================================================
#  API pública
# ==========================================================================
def correr_pipeline(
    session: Any,
    *,
    cliente_ia: Any,
    enviar: Enviar | None = None,
    eventos: list[Any] | None = None,
) -> ResultadoPipeline:
    """Corre o pipeline regulatório: triagem → alertas citados → envio.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy **de quem chama** (sob `db.get_session`). Não abre sessão nem faz
        commit — a transação é do orquestrador.
    cliente_ia:
        Cliente Anthropic **injetado** (falso nos testes; ``None`` ⇒ IA indisponível — os
        alertas caem no formato manual de recurso). Passado tal e qual à triagem/redação.
    enviar:
        `enviar(*, para, assunto, html, anexos, **kw)` **injetado** (dublê nos testes;
        ``None`` ⇒ envio indisponível — o alerta persiste-se por enviar).
    eventos:
        Lista explícita de eventos a processar (duck-typed). Passar
        ``resultado_dre.eventos`` (as instâncias vivas que o `dre_pipeline` acabou de
        criar) dá à IA o **corpo** por excerto. ``None`` → consultam-se os
        `eventos_regulatorios` com `processado=False` (excerto = título — ver o módulo).

    Devolve um :class:`ResultadoPipeline`. Idempotente: a âncora é `EventoRegulatorio.
    processado` — cada evento triado é marcado nesta transação, pelo que uma 2.ª passagem
    não o revê.

    :raises app.ia.cliente.ErroIA: a triagem não obteve JSON válido do modelo — **propaga**
        (o pipeline não fabrica um veredicto); o rollback do chamador deixa o evento por
        processar para nova tentativa.
    """
    if eventos is None:
        eventos = (
            session.query(models.EventoRegulatorio)
            .filter(models.EventoRegulatorio.processado.is_(False))
            .order_by(models.EventoRegulatorio.id)
            .all()
        )

    resultado = ResultadoPipeline()
    agora = datetime.now(timezone.utc)

    for evento in eventos:
        excerto = _excerto_do_evento(evento)

        triagem = _triagem.triar(evento, cliente_ia=cliente_ia)
        evento.triagem = _TRIAGEM_PERSIST.get(triagem.relevante_para_al, "duvida")
        evento.resumo_ia = triagem.resumo_1_frase or None
        evento.processado = True
        resultado.eventos_processados += 1

        if not _triagem.e_relevante(triagem):
            continue
        resultado.eventos_relevantes += 1

        pares = _clientes_com_al(session, _concelhos_afetados(evento, triagem))
        for cliente, registo in pares:
            gerado = gerar_alerta(
                evento, registo, cliente_ia=cliente_ia, excerto=excerto
            )
            alerta = models.Alerta(
                cliente_id=cliente.id,
                nr_registo=registo.nr_registo,
                origem=ORIGEM_REGULATORIO,
                origem_id=evento.id,
                conteudo=gerado.conteudo,
                canal=CANAL_EMAIL,
                enviado_em=None,
            )
            if enviar is not None and cliente.email:
                enviar(
                    para=cliente.email,
                    assunto=_assunto(registo),
                    html=_html(gerado.conteudo, gerado.url_fonte),
                    anexos=(),
                    texto=gerado.conteudo,
                    idempotency_key=f"reg-{evento.id}-{registo.nr_registo}",
                )
                alerta.enviado_em = agora
                resultado.enviados += 1

            session.add(alerta)
            resultado.alertas.append(alerta)

    session.flush()  # popula os ids dos alertas (sem commit — é do chamador)
    return resultado
