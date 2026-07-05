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
from html import escape
from typing import Any

import app.config as config
import app.db as db
import app.models as models
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


def _assunto(requer_atencao: bool) -> str:
    if requer_atencao:
        return "Bem-vindo ao CheckAL — o teu AL já está monitorizado (a confirmar um detalhe)"
    return "Bem-vindo ao CheckAL — o teu AL passou no check ✓"


def _bloco_selo_html(nrs: tuple[int, ...]) -> str:
    """Lista de ligações ao selo público de cada registo (só o link — dados públicos)."""
    itens = "".join(
        f'<li><a href="{escape(_selo_url(nr))}">{escape(_selo_url(nr))}</a></li>' for nr in nrs
    )
    return (
        "<p>O teu selo público <strong>CheckAL ✓ — AL Verificado</strong> "
        "(para colares no anúncio):</p>"
        f"<ul>{itens}</ul>"
    )


def _bloco_fatura_html(cliente: models.Cliente) -> str:
    """Ligação à fatura-recibo certificada já emitida (permalink guardado no cliente)."""
    if not cliente.ix_permalink:
        return ""
    link = escape(cliente.ix_permalink)
    return f'<p>A tua fatura-recibo certificada: <a href="{link}">{link}</a></p>'


def _compor_email(
    cliente: models.Cliente,
    relatorios: list[RelatorioInicial],
    nrs: tuple[int, ...],
    *,
    requer_atencao: bool,
) -> tuple[str, str]:
    """Compõe `(html, texto)` do email de boas-vindas a partir dos relatórios gerados.

    Copy factual, PT-PT, sem inventar. O detalhe fica no PDF anexo; o corpo dá as boas-vindas,
    liga à fatura e ao(s) selo(s), e — se algum detalhe ficou por confirmar — assinala a
    ressalva sem afirmar cancelamento (G4).
    """
    nome = escape(cliente.nome or "titular")
    partes = [
        f"<p>Olá {nome},</p>",
        "<p>Obrigado por subscreveres o <strong>CheckAL</strong>. A partir de agora "
        "vigiamos o registo RNAL, o seguro obrigatório e os regulamentos municipais do teu "
        "Alojamento Local, e avisamos-te se algo mudar.</p>",
        "<p>Em anexo segue o teu <strong>relatório inicial</strong> (PDF).</p>",
    ]
    if requer_atencao:
        partes.append(
            "<p>Há um detalhe do teu registo que ficamos a reconfirmar antes de tirar "
            "conclusões; assim que o validarmos, avisamos-te. Nada a fazer da tua parte.</p>"
        )
    partes.append(_bloco_fatura_html(cliente))
    if nrs:
        partes.append(_bloco_selo_html(nrs))
    partes.append(
        '<p style="font-size:.85em;color:#6b7280">Isto é informação de monitorização a '
        "partir de dados públicos do RNAL; não constitui aconselhamento jurídico.</p>"
    )
    html = "\n".join(p for p in partes if p)

    # Alternativa em texto simples: o texto de cada relatório + os links factuais.
    linhas_txt: list[str] = [f"Olá {cliente.nome or 'titular'},", ""]
    for rel in relatorios:
        linhas_txt.append(rel.texto())
        linhas_txt.append("")
    if cliente.ix_permalink:
        linhas_txt.append(f"Fatura-recibo: {cliente.ix_permalink}")
    for nr in nrs:
        linhas_txt.append(f"Selo público: {_selo_url(nr)}")
    texto = "\n".join(linhas_txt)
    return html, texto


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
        html, texto = _compor_email(cliente, relatorios, nrs, requer_atencao=requer_atencao)

        resultado_envio = enviar(
            para=cliente.email,
            assunto=_assunto(requer_atencao),
            html=html,
            anexos=anexos,
            texto=texto,
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
