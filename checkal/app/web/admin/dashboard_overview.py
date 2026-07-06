"""Painel admin — visão geral + leads (SPEC-FASE1-DASHBOARD §dashboard).

As duas primeiras secções do WF3, ambas **só do dono** (todas as rotas sob
`requer_admin`, aplicado ao nível do router — sem sessão assinada válida, 303 para
o login). É read-first: SÓ lê a BD, não envia, não cobra, não toca a rede.

    GET /admin        visão geral: clientes ativos, MRR estimado, alertas enviados,
                      opt-outs, leads por estado, último varrimento.
    GET /admin/leads  os prospects consent-first (Lead) por estado — a PII (email) só
                      aqui, porque é necessária ao dono para gerir os interessados.

**MRR estimado** deriva de `config.PLANOS` (fonte ÚNICA de preços — nunca duplicada):
cada cliente ATIVO vale `preço ÷ meses` do seu plano (o mensal-equivalente), e o MRR
é a soma. Assim o número segue sempre a folha de preços canónica.

**Minimização (SPEC — "zero PII indevida"):** a visão geral mostra CONTAGENS; os
emails dos leads aparecem só em `/admin/leads`, onde o dono precisa deles para operar.

Renderiza pela instância Jinja PARTILHADA (`app.web.marca.templates`, autoescape ⇒
anti-XSS, globais de marca injetados); os templates estendem `admin/base_admin.html`
(nav + marca) que por sua vez estende `base.html`. LIVE-GATED: importar/instanciar
não toca a rede nem a BD — a persistência resolve-se por request em `app.db`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func

import app.config as config
import app.db as db
import app.models as models
from app.web.admin.auth import requer_admin
from app.web.marca import templates

# Todas as rotas do painel exigem sessão de dono (a fundação de auth já feita).
router = APIRouter(dependencies=[Depends(requer_admin)])
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# Os três estados do ciclo de vida de um Lead (double opt-in / opt-out).
_ESTADOS_LEAD = ("pendente", "confirmado", "removido")


# ==========================================================================
#  Cálculo (puro/testável) — MRR, contagens, formatação
# ==========================================================================
def _mensal_do_plano(plano: str | None) -> float:
    """Mensal-equivalente de um plano: `preço ÷ meses` de `config.PLANOS`.

    Plano desconhecido ou sem preço/meses → 0.0 (não inventa receita). É a ponte
    entre um preço anual/trienal (como se cobra) e o MRR (como se lê o negócio).
    """
    p = config.PLANOS.get(plano or "")
    if not p:
        return 0.0
    meses = p.get("meses") or 12
    preco = p.get("preco") or 0.0
    return preco / meses if meses else 0.0


def mrr_estimado(s) -> float:
    """MRR estimado: soma do mensal-equivalente de cada cliente ATIVO (2 casas).

    Só conta `estado == 'ativo'` (cancelados/dunning não faturam MRR). A fonte dos
    preços é `config.PLANOS` — este cálculo nunca hard-codeia valores.
    """
    ativos = (
        s.query(models.Cliente.plano)
        .filter(models.Cliente.estado == "ativo")
        .all()
    )
    return round(sum(_mensal_do_plano(plano) for (plano,) in ativos), 2)


def _leads_por_estado(s) -> dict[str, int]:
    """Contagem de leads por estado, com os três estados sempre presentes (0 por omissão)."""
    contagens = {estado: 0 for estado in _ESTADOS_LEAD}
    linhas = (
        s.query(models.Lead.estado, func.count())
        .group_by(models.Lead.estado)
        .all()
    )
    for estado, n in linhas:
        contagens[estado] = n  # estado inesperado adiciona-se; os três base garantidos
    return contagens


def _formatar_euros(valor: float) -> str:
    """Formata um montante em euros no estilo pt: 11.47 → ``11,47 €``."""
    return f"{valor:.2f} €".replace(".", ",")


def _formatar_data(dt: datetime | None) -> str:
    """Data dd/mm/aaaa (ou vazio se ausente)."""
    return dt.strftime("%d/%m/%Y") if dt else ""


def _ultimo_varrimento(s) -> dict[str, Any] | None:
    """O varrimento mais recente (por `iniciado_em`) como dicionário plano, ou `None`.

    Devolve primitivos (não a instância ORM) para o template não depender da sessão.
    A data mostrada é a de conclusão quando existe, senão a de início.
    """
    v = (
        s.query(models.Varrimento)
        .order_by(models.Varrimento.iniciado_em.desc())
        .first()
    )
    if v is None:
        return None
    return {
        "data": _formatar_data(v.concluido_em or v.iniciado_em),
        "estado": v.estado or "—",
        "total": v.total_registos,
    }


# ==========================================================================
#  Rotas
# ==========================================================================
@router.get("/admin", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    """Visão geral do negócio — contagens de leitura, sem PII de leads.

    Reúne, numa só leitura da BD: nº de clientes ativos, MRR estimado (de
    `config.PLANOS`), nº de alertas enviados (`enviado_em` preenchido), nº de
    opt-outs, nº de leads por estado e o último varrimento.
    """
    with db.get_session() as s:
        clientes_ativos = (
            s.query(func.count())
            .select_from(models.Cliente)
            .filter(models.Cliente.estado == "ativo")
            .scalar()
        )
        mrr = mrr_estimado(s)
        alertas_enviados = (
            s.query(func.count())
            .select_from(models.Alerta)
            .filter(models.Alerta.enviado_em.isnot(None))
            .scalar()
        )
        opt_outs = s.query(func.count()).select_from(models.OptOut).scalar()
        leads_estado = _leads_por_estado(s)
        ultimo_varrimento = _ultimo_varrimento(s)

    return templates.TemplateResponse(
        request,
        "admin/overview.html",
        {
            "secao": "overview",
            "clientes_ativos": clientes_ativos or 0,
            "mrr": mrr,
            "mrr_fmt": _formatar_euros(mrr),
            "alertas_enviados": alertas_enviados or 0,
            "opt_outs": opt_outs or 0,
            "leads_estado": leads_estado,
            "leads_total": sum(leads_estado.values()),
            "ultimo_varrimento": ultimo_varrimento,
        },
    )


@router.get("/admin/leads", response_class=HTMLResponse)
def leads(request: Request) -> HTMLResponse:
    """Prospects consent-first (Lead) por estado — a lista operacional do dono.

    Mostra os leads mais recentes primeiro, com o mínimo necessário para o dono
    operar: email, estado, o AL/concelho de contexto (opcionais) e a data. O email
    é PII, mas é aqui necessário (gerir os interessados) — não se expõe na visão geral.
    """
    with db.get_session() as s:
        linhas = (
            s.query(models.Lead)
            .order_by(models.Lead.criado_em.desc().nullslast(), models.Lead.id.desc())
            .all()
        )
        registos = [
            {
                "email": l.email,
                "estado": l.estado,
                "nr_registo": l.nr_registo,
                "concelho": l.concelho,
                "consent_ofertas": l.consent_ofertas,
                "criado": _formatar_data(l.criado_em),
            }
            for l in linhas
        ]
        leads_estado = _leads_por_estado(s)

    return templates.TemplateResponse(
        request,
        "admin/leads.html",
        {
            "secao": "leads",
            "leads": registos,
            "leads_estado": leads_estado,
            "leads_total": sum(leads_estado.values()),
        },
    )
