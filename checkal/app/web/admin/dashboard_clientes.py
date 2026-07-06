"""Dashboard admin — clientes + alertas (SPEC-FASE1-DASHBOARD §dashboard).

Duas páginas de LEITURA do painel do dono, sob `requer_admin` (o painel é do DONO e só
do dono — a fronteira é CÓDIGO, não confiança):

    GET /admin/clientes  → a lista dos assinantes (email, nome, plano, estado, n.º AL,
                           criado) + o detalhe/histórico de cada um (alojamentos
                           associados + alertas já enviados). Read-first: nenhuma ação
                           que ENVIE ou COBRE nada — só informa.
    GET /admin/alertas   → a fila de alertas enviados + os eventos `desaparecido`
                           PENDENTES de desambiguação (`processado=False`). É a revisão
                           do dono (SPEC): "só informa, o breaker decide" — nenhum botão
                           aqui reprocessa/decide.

DISCIPLINA (inviolável): LIVE-GATED, só-leitura. Este módulo NÃO envia emails, NÃO
cobra, NÃO toca a rede — limita-se a ler a BD (`app.db.get_session`) e a renderizar
pelo Jinja PARTILHADO (`app.web.marca.templates`, autoescape ligado ⇒ anti-XSS).

**Minimização (parecer RGPD §5 / red-team do SPEC — "zero PII exposta indevidamente"):**
o painel de clientes projeta cada linha numa lista branca explícita de campos
OPERACIONAIS (o e-mail do PRÓPRIO assinante, plano, estado, n.º de AL, datas, e o
nome/concelho/estado dos alojamentos que ele monitoriza). Os **contactos do TITULAR do
RNAL** (NIF, email, telefone, telemóvel, nome do titular) associados a cada `Registo`
NUNCA são projetados — ficam de fora por construção, não por confiança na renderização.

Todos os dados chegam ao template já materializados em dicts simples, montados DENTRO
da sessão: nada de objetos ORM a atravessar a fronteira da sessão (evita lazy-loads
destacados) e a lista branca fecha-se aqui, num único sítio auditável.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import app.db as db
import app.models as models
from app.config import PLANOS
from app.web.admin.auth import requer_admin
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


# ==========================================================================
#  Formatação (pura, sem PII)
# ==========================================================================
def _fmt_dt(dt: datetime | None) -> str:
    """Data/hora legível e curta (`AAAA-MM-DD HH:MM`), ou travessão se ausente.

    O SQLite devolve datetimes naïve e o Postgres aware; formatar por componentes
    (`strftime`) é indiferente ao fuso e nunca rebenta com a diferença.
    """
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def _nome_plano(codigo: str | None) -> str:
    """Nome legível do plano a partir de `config.PLANOS` (fonte única); fallback ao código."""
    info = PLANOS.get(codigo or "", {})
    return info.get("nome") or (codigo or "—")


def _estado_registo(r: models.Registo) -> str:
    """Estado do AL no espelho do RNAL: ativo enquanto `desaparecido_em` for NULL."""
    return "ativo" if r.desaparecido_em is None else "desaparecido"


# ==========================================================================
#  Projeções (lista branca — a fronteira de minimização)
# ==========================================================================
def _projetar_al(r: models.Registo) -> dict[str, Any]:
    """Um alojamento associado, SÓ com campos do estabelecimento (nunca do titular)."""
    return {
        "nr_registo": r.nr_registo,
        "nome": r.nome_alojamento,
        "concelho": r.concelho,
        "estado": _estado_registo(r),
    }


def _projetar_alerta_cliente(a: models.Alerta) -> dict[str, Any]:
    """Um alerta no histórico de um cliente (campos operacionais)."""
    return {
        "nr_registo": a.nr_registo,
        "origem": a.origem,
        "conteudo": a.conteudo,
        "canal": a.canal,
        "enviado": _fmt_dt(a.enviado_em),
    }


def _carregar_clientes(s) -> list[dict[str, Any]]:
    """Materializa a lista de clientes + detalhe/histórico, dentro da sessão.

    Para cada assinante: os campos operacionais da linha, os alojamentos que
    monitoriza (lista branca `_projetar_al`) e os alertas já enviados. Tudo em dicts
    simples — nenhum objeto ORM atravessa a fronteira da sessão.
    """
    clientes = (
        s.query(models.Cliente)
        .order_by(models.Cliente.criado_em.desc(), models.Cliente.id.desc())
        .all()
    )
    linhas: list[dict[str, Any]] = []
    for c in clientes:
        als = (
            s.query(models.Registo)
            .join(
                models.ClienteRegisto,
                models.ClienteRegisto.nr_registo == models.Registo.nr_registo,
            )
            .filter(models.ClienteRegisto.cliente_id == c.id)
            .order_by(models.Registo.nr_registo)
            .all()
        )
        alertas = (
            s.query(models.Alerta)
            .filter(models.Alerta.cliente_id == c.id)
            .order_by(models.Alerta.enviado_em.desc())
            .all()
        )
        linhas.append({
            "id": c.id,
            "email": c.email,
            "nome": c.nome,
            "plano_nome": _nome_plano(c.plano),
            "estado": c.estado,
            "n_al": len(als),
            "criado": _fmt_dt(c.criado_em),
            "als": [_projetar_al(r) for r in als],
            "alertas": [_projetar_alerta_cliente(a) for a in alertas],
        })
    return linhas


def _carregar_alertas(s) -> list[dict[str, Any]]:
    """A fila de alertas enviados (mais recente primeiro), com o email do assinante."""
    alertas = (
        s.query(models.Alerta)
        .order_by(models.Alerta.enviado_em.desc(), models.Alerta.id.desc())
        .all()
    )
    # Mapa cliente_id → email (uma query; `cliente_id` do alerta é inteiro solto, não FK).
    ids = {a.cliente_id for a in alertas if a.cliente_id is not None}
    emails: dict[int, str | None] = {}
    if ids:
        for cid, email in (
            s.query(models.Cliente.id, models.Cliente.email)
            .filter(models.Cliente.id.in_(ids))
            .all()
        ):
            emails[cid] = email
    return [
        {
            "cliente_id": a.cliente_id,
            "cliente_email": emails.get(a.cliente_id),
            "nr_registo": a.nr_registo,
            "origem": a.origem,
            "conteudo": a.conteudo,
            "canal": a.canal,
            "enviado": _fmt_dt(a.enviado_em),
        }
        for a in alertas
    ]


def _carregar_desaparecidos_pendentes(s) -> list[dict[str, Any]]:
    """Os eventos `desaparecido` NÃO processados — a fila de desambiguação do dono.

    Só `tipo == 'desaparecido'` E `processado == False` (um `alterado` ou um
    desaparecido já processado NÃO entram). Junta o nome/concelho do estabelecimento
    (campos públicos) para o dono situar o AL; nunca dados do titular.
    """
    eventos = (
        s.query(models.EventoRegisto)
        .filter(
            models.EventoRegisto.tipo == "desaparecido",
            models.EventoRegisto.processado.is_(False),
        )
        .order_by(models.EventoRegisto.detetado_em.desc(), models.EventoRegisto.id.desc())
        .all()
    )
    linhas: list[dict[str, Any]] = []
    for e in eventos:
        r = s.get(models.Registo, e.nr_registo) if e.nr_registo is not None else None
        linhas.append({
            "nr_registo": e.nr_registo,
            "nome": r.nome_alojamento if r is not None else None,
            "concelho": r.concelho if r is not None else None,
            "detetado": _fmt_dt(e.detetado_em),
        })
    return linhas


# ==========================================================================
#  Rotas (todas sob requer_admin)
# ==========================================================================
@router.get("/admin/clientes", response_class=HTMLResponse)
def clientes(request: Request, _=Depends(requer_admin)) -> HTMLResponse:
    """Lista dos assinantes + detalhe/histórico. Só leitura; minimizada (lista branca)."""
    with db.get_session() as s:
        linhas = _carregar_clientes(s)
    return templates.TemplateResponse(
        request, "admin/clientes.html", {"clientes": linhas, "secao": "clientes"}
    )


@router.get("/admin/alertas", response_class=HTMLResponse)
def alertas(request: Request, _=Depends(requer_admin)) -> HTMLResponse:
    """Fila de alertas enviados + desaparecidos pendentes de desambiguação. Só informa."""
    with db.get_session() as s:
        fila = _carregar_alertas(s)
        desaparecidos = _carregar_desaparecidos_pendentes(s)
    return templates.TemplateResponse(
        request,
        "admin/alertas.html",
        {"alertas": fila, "desaparecidos": desaparecidos, "secao": "alertas"},
    )
