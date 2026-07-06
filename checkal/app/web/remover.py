"""Direito de oposição / opt-out do CheckAL (SPEC-FASE1-WEB §remover).

A lei quer o "não me contactem" **fácil, gratuito e sem fricção** (Lei 41/2004
art. 13.º-B; RGPD art. 21.º; RFC 8058 no espírito). Este router é essa saída:

    GET  /remover              → o formulário (pede o email);
    POST /remover  (email)     → regista o opt-out e confirma;
    GET  /remover?e=&t=        → opt-out de **1 clique** — o link carimbado em cada
                                 email de prospeção (:func:`app.campanhas.cold_email.link_remocao`)
                                 traz o destinatário em `e`; basta abrir para sair.

O que "registar o opt-out" faz, em código (a compliance é código, não confiança):

  1. **grava na lista de supressão** (`app.models.OptOut`, tabela `optouts`) com o
     email JÁ NORMALIZADO (minúsculas/sem espaços — `compliance.optout.normalizar_email`),
     a MESMA forma que `compliance.optout.filtrar_optout` cruza antes de cada envio.
     Assim a oposição gravada aqui de facto **exclui** o contacto lá. Idempotente pela
     chave natural (email é PK) — opor-se N vezes deixa 1 linha;
  2. **marca o(s) `Lead` desse email como `'removido'`** (fecha o consentimento do
     lado do funil consent-first).

O opt-out é deliberadamente **permissivo**: `e` (ou o email submetido) é a fonte de
verdade; o `t` do link é aceite mas NÃO é exigido nem validado contra o token — negar
uma remoção por causa de um token que não bate seria empurrar alguém para continuar a
ser contactado (o erro tem de ser sempre para o lado de NÃO contactar). Por isso
também não há CSRF token: forçar a remoção de alguém é, quando muito, um incómodo, e
qualquer fricção acrescentada ao opt-out é um risco legal maior do que o ataque.

DISCIPLINA (inviolável): LIVE-GATED. Este módulo não envia nada nem toca a rede — só
escreve na BD (via `app.db.get_session`) e renderiza pelo Jinja PARTILHADO
(`app.web.marca.templates`, autoescape ligado → anti-XSS). Português, serviço PRIVADO.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func

import app.db as db
from app.compliance.optout import normalizar_email
from app.models import Lead, OptOut
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

_TEMPLATE = "remover.html"


def _email_valido(email: str) -> bool:
    """Estrutura mínima de um email já normalizado: um `@`, local e domínio não
    vazios, domínio com `.` e sem espaços. Serve só para não gravar lixo como
    opt-out — a proteção contra markup na saída é o autoescape do Jinja, não isto.
    """
    if not email or any(c.isspace() for c in email) or email.count("@") != 1:
        return False
    local, dominio = email.split("@")
    if not local or not dominio or "." not in dominio:
        return False
    return not (dominio.startswith(".") or dominio.endswith("."))


def _pagina(
    request: Request,
    *,
    confirmado: bool,
    email: str | None = None,
    erro: str | None = None,
) -> HTMLResponse:
    """Renderiza `remover.html` pelo Jinja partilhado (globais da marca já injetados).

    `confirmado=True` → ecrã de confirmação (com o `email` ecoado, escapado pelo
    autoescape); caso contrário → o formulário, opcionalmente com um `erro` amigável.
    """
    return templates.TemplateResponse(
        request,
        _TEMPLATE,
        {"confirmado": confirmado, "email": email, "erro": erro},
    )


def _registar_opt_out(email_normalizado: str, *, origem: str) -> None:
    """Grava a oposição e marca os Leads desse email como 'removido' (idempotente).

    Get-or-create pela chave natural (`OptOut.email` é PK) → opor-se de novo não
    duplica. A marca dos Leads corre à mesma em cada chamada (definir 'removido'
    outra vez é inofensivo). Tudo numa transação (`db.get_session` faz commit).
    """
    with db.get_session() as s:
        if s.get(OptOut, email_normalizado) is None:
            s.add(OptOut(
                email=email_normalizado,
                origem=origem,
                criado_em=datetime.now(timezone.utc),
            ))
        # Fecha o consentimento do lado do funil: qualquer Lead com este email sai.
        # Comparação case-insensitive (o email de entrada já vem normalizado).
        for lead in s.query(Lead).filter(func.lower(Lead.email) == email_normalizado).all():
            lead.estado = "removido"


def _processar(request: Request, email_bruto: str, *, origem: str) -> HTMLResponse:
    """Normaliza, valida e — se válido — regista a oposição, devolvendo a página.

    Email inválido → reexibe o formulário com um aviso amigável e NÃO grava nada
    (a saída fica limpa de lixo). Email válido → grava o opt-out e confirma.
    """
    email = normalizar_email(email_bruto or "")
    if not _email_valido(email):
        return _pagina(
            request,
            confirmado=False,
            erro="Escreve um email válido para te removermos da lista.",
        )
    _registar_opt_out(email, origem=origem)
    return _pagina(request, confirmado=True, email=email)


@router.get("/remover", response_class=HTMLResponse)
def remover_form(request: Request, e: str | None = None, t: str | None = None) -> HTMLResponse:
    """Formulário de opt-out — ou o opt-out de 1 clique quando o link traz `e`.

    O link carimbado nos emails é `/remover?e=<email>&t=<token>`: a presença de `e`
    processa logo a oposição (GET idempotente, sem login). Sem `e` → mostra o
    formulário. O `t` é aceite mas não é exigido (o opt-out nunca pode falhar por
    causa de um token).
    """
    if e is not None and e.strip():
        return _processar(request, e, origem="email_1clique")
    return _pagina(request, confirmado=False)


@router.post("/remover", response_class=HTMLResponse)
def remover_submeter(request: Request, email: str = Form(...)) -> HTMLResponse:
    """Recebe o email do formulário, regista a oposição e mostra a confirmação."""
    return _processar(request, email, origem="formulario")
