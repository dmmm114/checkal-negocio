"""Onboarding automático do pagante (FDS 3, SPEC-FDS3.md §onboarding).

Fecha o funil «compra → relatório sem intervenção humana»: dado o `cliente_id` de um
pagante já materializado (com fatura-recibo certificada), obtém o detalhe individual do(s)
seu(s) registo(s) RNAL, persiste-o, compõe o **relatório inicial** (PDF) e envia o **email
de boas-vindas** — relatório em anexo, link da fatura já emitida e link do **selo** público
`config.BASE_URL/selo/{nr}`. É o ponto de junção das peças da Aquisição/Produtos
(`app.rnal.detalhe`, `app.relatorio`, `app.selo`, `app.envio`), todas já construídas.

Fronteira e injeção (LIVE-GATED, MODO DE TESTE):
  - `obter_detalhe` e `enviar` são **injetados** por quem chama. Em produção compõem-se
    atrás dos seams (`app.rnal.detalhe.obter_detalhe`, que cria o seu próprio `httpx.Client`,
    e `app.envio.obter_enviador()`, que devolve `None` sob modo de teste). Nos testes
    injetam-se dublês — logo **nada toca a rede**.
  - A composição em produção e o gancho no fulfillment vivem em `app.fulfillment`
    (`_agendar_boas_vindas`), não aqui: este módulo é puro orquestrador sobre a sessão.

Disciplina inviolável (SPEC-FDS3):
  - **IDEMPOTENTE.** Re-processar o mesmo cliente **não** duplica envios: grava-se um
    marcador em `alertas` (`origem=onboarding`/`onboarding_tarefa`); a presença de qualquer
    marcador faz a 2.ª passagem ser um no-op.
  - **G4.** O relatório nunca afirma "cancelado" a partir do detalhe (isso vive na copy de
    `app.relatorio`); um detalhe `indeterminado`/`nao_encontrado` (ou uma falha de transporte
    ao obtê-lo) **não rebenta**: o relatório sai com a ressalva e regista-se uma **tarefa
    para o dono** (ponto semi-manual, <5%). Uma falha de rede nunca marca "cancelado".
  - **Só dados públicos em saídas públicas.** O email de boas-vindas é transacional, para o
    próprio assinante (pode conter os seus dados); a saída **pública** é o selo, cujo
    conteúdo é filtrado por lista branca em `app.web.selo` — este módulo só lá põe o *link*.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import app.config as config
import app.db as db
import app.models as models
from app.emails import transacional
from app.emails.base import EmailRenderizado
from app.relatorio import RelatorioInicial, gerar_relatorio_inicial, render_pdf
from app.rnal.detalhe import (
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
    persistir_detalhe,
)

__all__ = [
    "ResultadoOnboarding",
    "ORIGEM_ONBOARDING",
    "ORIGEM_TAREFA_DONO",
    "CANAL_TAREFA",
    "processar_onboarding",
]

# Marcadores em `alertas` (Text). `origem=onboarding` = email de boas-vindas enviado;
# `origem=onboarding_tarefa` = ponto semi-manual a resolver pelo dono. Qualquer um serve
# de âncora de idempotência (ver `_ja_processado`).
ORIGEM_ONBOARDING = "onboarding"
ORIGEM_TAREFA_DONO = "onboarding_tarefa"
CANAL_TAREFA = "tarefa_dono"  # distingue a tarefa interna de um envio real ao cliente

# Estados do detalhe que exigem confirmação humana (o relatório sai com ressalva).
_ESTADOS_RESSALVA = frozenset({ESTADO_INDETERMINADO, ESTADO_NAO_ENCONTRADO})

# Assinatura do detalhe injetado e do enviador (para leitura; não impõe verificação).
ObterDetalhe = Callable[..., DetalheRegisto]
Enviar = Callable[..., Any]


@dataclass(frozen=True)
class ResultadoOnboarding:
    """Desfecho de uma passagem de onboarding (para auditoria / o chamador do wire).

    `enviado` marca se o email de boas-vindas saiu nesta passagem; `idempotente` que o
    cliente já tinha sido processado (no-op); `requer_atencao`/`tarefas` sinalizam o ponto
    semi-manual (detalhe ambíguo, sem registo, sem email). `email_id` é o id da Resend.
    """

    cliente_id: int
    enviado: bool = False
    idempotente: bool = False
    email_id: str | None = None
    nrs: tuple[int, ...] = ()
    requer_atencao: bool = False
    tarefas: tuple[str, ...] = ()


# ==========================================================================
#  Idempotência (marcador em `alertas`)
# ==========================================================================
def _ja_processado(s: Any, cliente_id: int) -> bool:
    """Diz se este cliente já foi objeto de onboarding (envio OU tarefa registada)."""
    return (
        s.query(models.Alerta)
        .filter(
            models.Alerta.cliente_id == cliente_id,
            models.Alerta.origem.in_([ORIGEM_ONBOARDING, ORIGEM_TAREFA_DONO]),
        )
        .first()
        is not None
    )


def _marcar(
    s: Any, *, cliente_id: int, origem: str, conteudo: str, canal: str, nr_registo: int | None
) -> None:
    """Grava um marcador em `alertas` (envio de boas-vindas ou tarefa para o dono)."""
    s.add(
        models.Alerta(
            cliente_id=cliente_id,
            nr_registo=nr_registo,
            origem=origem,
            conteudo=conteudo,
            canal=canal,
            enviado_em=datetime.now(timezone.utc),
        )
    )


# ==========================================================================
#  Composição do email de boas-vindas
# ==========================================================================
def _selo_url(nr_registo: int) -> str:
    return f"{config.BASE_URL}/selo/{nr_registo}"


def _nome_al(s: Any, nr: int) -> str:
    """Nome público do estabelecimento do 1.º registo (cabeçalho do email de boas-vindas)."""
    registo = s.get(models.Registo, nr)
    if registo is not None and registo.nome_alojamento:
        return registo.nome_alojamento
    return "teu Alojamento Local"


def _compor_boas_vindas(
    s: Any, cliente: models.Cliente, nrs: tuple[int, ...], *, requer_atencao: bool
) -> EmailRenderizado:
    """Compõe o email de boas-vindas (branded, template WF2) a partir dos dados do pagante.

    Substitui o HTML ad-hoc: a copy/estilo/rodapé/opt-out vivem no template `boas_vindas`
    (`app.emails.transacional`, sobre `app.emails.base`); aqui só se reúnem os DADOS — nome
    do AL, selo(s) público(s), permalink da fatura-recibo já emitida e a ressalva do ponto
    semi-manual (G4: nunca afirma "cancelado"). O Relatório Inicial segue em anexo (PDF).
    """
    selos = [_selo_url(nr) for nr in nrs]
    return transacional.boas_vindas(
        nome_al=_nome_al(s, nrs[0]),
        nr_registo=str(nrs[0]),
        url_selo=selos[0],
        selos_extra=selos[1:],
        url_fatura=cliente.ix_permalink or "",
        requer_atencao=requer_atencao,
        nome=cliente.nome or None,
        email_destinatario=cliente.email or "",
    )


# ==========================================================================
#  Ponto de entrada
# ==========================================================================
def processar_onboarding(
    cliente_id: int,
    *,
    obter_detalhe: ObterDetalhe,
    enviar: Enviar,
) -> ResultadoOnboarding:
    """Executa o onboarding de um pagante: detalhe → relatório → email de boas-vindas.

    Parâmetros
    ----------
    cliente_id:
        Id do assinante já materializado (com fatura emitida) em `clientes`.
    obter_detalhe:
        `obter_detalhe(nr) -> DetalheRegisto` **injetado** (mock nos testes; em produção o
        `app.rnal.detalhe.obter_detalhe`, que cria o seu próprio cliente HTTP). Uma exceção
        ao obter o detalhe é degradada para `indeterminado` (nunca "cancelado" por rede).
    enviar:
        `enviar(*, para, assunto, html, anexos, **kw) -> ResultadoEnvio` **injetado** (mock
        nos testes; em produção o *callable* de `app.envio.obter_enviador`).

    Idempotente por marcador em `alertas`. Devolve um :class:`ResultadoOnboarding`.
    """
    with db.get_session() as s:
        cliente = s.get(models.Cliente, cliente_id)
        if cliente is None:
            # Nada a fazer (sem cliente não há sequer onde gravar tarefa) — não rebenta.
            return ResultadoOnboarding(
                cliente_id=cliente_id, requer_atencao=True, tarefas=("cliente inexistente",)
            )

        # Idempotência: já processado → no-op (não reenvia, não re-regista tarefa).
        if _ja_processado(s, cliente_id):
            nrs = tuple(sorted(r.nr_registo for r in cliente.registos))
            return ResultadoOnboarding(cliente_id=cliente_id, idempotente=True, nrs=nrs)

        nrs = tuple(sorted(r.nr_registo for r in cliente.registos))
        tarefas: list[str] = []

        # --- Sem registo associado: ponto semi-manual (desambiguação), não envia ---
        if not nrs:
            msg = "cliente sem registo RNAL associado — desambiguação manual necessária"
            tarefas.append(msg)
            _marcar(
                s, cliente_id=cliente_id, origem=ORIGEM_TAREFA_DONO,
                conteudo=msg, canal=CANAL_TAREFA, nr_registo=None,
            )
            return ResultadoOnboarding(
                cliente_id=cliente_id, requer_atencao=True, tarefas=tuple(tarefas)
            )

        # --- Sem email do cliente: não há para onde enviar → tarefa para o dono ---
        if not cliente.email:
            msg = "cliente sem email — enviar relatório inicial manualmente"
            tarefas.append(msg)
            _marcar(
                s, cliente_id=cliente_id, origem=ORIGEM_TAREFA_DONO,
                conteudo=msg, canal=CANAL_TAREFA, nr_registo=nrs[0],
            )
            return ResultadoOnboarding(
                cliente_id=cliente_id, nrs=nrs, requer_atencao=True, tarefas=tuple(tarefas)
            )

        # --- Detalhe + relatório + PDF por registo ---
        relatorios: list[RelatorioInicial] = []
        anexos: list[dict[str, Any]] = []
        for nr in nrs:
            try:
                detalhe = obter_detalhe(nr)
            except Exception:
                # G4: falha de transporte esgotada → conservador `indeterminado` (pára e avisa),
                # nunca "cancelado" por rede. Persiste-se e segue-se (o email sai à mesma).
                detalhe = DetalheRegisto(nr_registo=nr, estado=ESTADO_INDETERMINADO)
                tarefas.append(f"registo {nr}: detalhe indisponível (falha ao obter) — reconfirmar")

            persistir_detalhe(s, detalhe)
            if detalhe.estado in _ESTADOS_RESSALVA:
                tarefas.append(
                    f"registo {nr}: estado '{detalhe.estado}' no detalhe — confirmar manualmente"
                )

            relatorio = gerar_relatorio_inicial(cliente, detalhe)
            relatorios.append(relatorio)
            anexos.append({"filename": f"relatorio-checkal-{nr}.pdf", "conteudo": render_pdf(relatorio)})

        requer_atencao = bool(tarefas)
        email = _compor_boas_vindas(s, cliente, nrs, requer_atencao=requer_atencao)

        resultado_envio = enviar(
            para=cliente.email,
            assunto=email.assunto,
            html=email.html,
            anexos=anexos,
            texto=email.texto,
            idempotency_key=f"onboarding-{cliente_id}",
        )
        email_id = getattr(resultado_envio, "id", None)

        # Marcadores: o de envio (idempotência do email) + as tarefas semi-manuais.
        _marcar(
            s, cliente_id=cliente_id, origem=ORIGEM_ONBOARDING,
            conteudo=f"email de boas-vindas enviado (id={email_id})",
            canal="email", nr_registo=nrs[0],
        )
        for msg in tarefas:
            _marcar(
                s, cliente_id=cliente_id, origem=ORIGEM_TAREFA_DONO,
                conteudo=msg, canal=CANAL_TAREFA, nr_registo=nrs[0],
            )

        return ResultadoOnboarding(
            cliente_id=cliente_id,
            enviado=True,
            email_id=email_id,
            nrs=nrs,
            requer_atencao=requer_atencao,
            tarefas=tuple(tarefas),
        )
