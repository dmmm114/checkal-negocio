"""Portão 1-clique do CheckAL — GET/POST /gate/{item_id} (Fase 2 do enxame, F2.2).

`fila.aprovar`/`fila.rejeitar` nunca tiveram chamador em produção até aqui: este
router fecha o ciclo token → clique → decisão. O **token** (gerado pelo MAESTRO
em `fila.gerar_token`, gravado em `revisao_itens.token_aprovacao`) é a ÚNICA
credencial — tal como `/inscrever` e `/remover`, não há sessão nem login.

    GET  /gate/{item_id}?token=…          MOSTRA o item (nunca decide);
    POST /gate/{item_id}/aprovar (token)  DECIDE — aprova, via `fila.aprovar`;
    POST /gate/{item_id}/rejeitar (token) DECIDE — rejeita, via `fila.rejeitar`.

O GET faz a MESMA verificação local que `fila._decidir` faz a jusante — token
vazio/errado, item inexistente ou já não-`pendente` → `estado="invalido"` —
com a MESMA técnica constant-time sobre BYTES (`secrets.compare_digest`, NUNCA
sobre `str`: um token não-ASCII levantaria `TypeError` em vez de recusar
limpo — commit 74b47c7). É uma verificação de EXIBIÇÃO; quem decide de facto é
sempre `fila.aprovar`/`fila.rejeitar`, que repetem o mesmo circuito no POST.

`autor ≠ aprovador` é imposto a JUSANTE (`fila._decidir`, via
`AutorNaoAprova`): este router só apanha a exceção como defesa em profundidade
— com `decidido_por="dono"` só dispararia se `agente_origem == "dono"`, o que
não acontece com os agentes que hoje enfileiram (editor/comunicador).

Página pública mas NÃO indexável (`noindex`): o link só circula pelo digest do
dono, nunca deve aparecer numa pesquisa. NUNCA se imprime/renderiza
`token_aprovacao` fora do hidden input do form — que reutiliza o token que já
veio no query param do GET, não o valor gravado no item.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

import app.db as db
import app.models_swarm as ms
from app.swarm import fila
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


def _item_para_template(item: ms.RevisaoItem) -> dict[str, object]:
    """Lista branca do item para o template — nunca inclui `token_aprovacao`."""
    return {
        "id": item.id,
        "tipo": item.tipo,
        "agente_origem": item.agente_origem,
        "risco": item.risco,
        "camada_risco": item.camada_risco,
        "resumo": item.resumo,
    }


def _token_bate(token: str, item: ms.RevisaoItem) -> bool:
    """Verificação LOCAL (só de exibição) do token — constant-time sobre BYTES.

    Espelha `fila._decidir`: nunca `compare_digest` sobre `str` (não-ASCII
    levantaria `TypeError`) — sempre bytes UTF-8, e falha fechado se qualquer
    um dos lados estiver vazio.
    """
    if not token or not item.token_aprovacao:
        return False
    return secrets.compare_digest(
        token.encode("utf-8"), item.token_aprovacao.encode("utf-8")
    )


@router.get("/gate/{item_id}", response_class=HTMLResponse)
def gate_ver(request: Request, item_id: int, token: str = "") -> HTMLResponse:
    """Mostra o item pendente se o token bater — esta rota NUNCA escreve na BD.

    Item inexistente, já não-`pendente`, ou token vazio/errado/não-ASCII →
    `estado="invalido"` (sempre 200 — a página de estado, nunca um 500).
    """
    item_ctx: dict[str, object] | None = None
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        if item is not None and item.estado == "pendente" and _token_bate(token, item):
            item_ctx = _item_para_template(item)

    estado = "pendente" if item_ctx is not None else "invalido"
    return templates.TemplateResponse(
        request, "gate.html", {"estado": estado, "item": item_ctx, "token": token}
    )


def _decidir(
    request: Request, item_id: int, *, token: str, acao, estado_sucesso: str
) -> HTMLResponse:
    """Chama `acao` (`fila.aprovar`/`fila.rejeitar`) na sessão de governação.

    Token inválido ou autor==aprovador (defesa em profundidade — não deveria
    disparar com os agentes atuais) → `estado="invalido"`, nunca um 500.
    """
    try:
        with fila.sessao_governacao() as s:
            acao(s, item_id, token=token, decidido_por="dono")
    except (fila.TokenInvalido, fila.AutorNaoAprova):
        estado = "invalido"
    else:
        estado = estado_sucesso

    return templates.TemplateResponse(
        request, "gate.html", {"estado": estado, "item": None, "token": ""}
    )


@router.post("/gate/{item_id}/aprovar", response_class=HTMLResponse)
def gate_aprovar(request: Request, item_id: int, token: str = Form(default="")) -> HTMLResponse:
    """Aprova o item — só decide com token válido (via `fila.aprovar`)."""
    return _decidir(
        request, item_id, token=token, acao=fila.aprovar, estado_sucesso="aprovado"
    )


@router.post("/gate/{item_id}/rejeitar", response_class=HTMLResponse)
def gate_rejeitar(request: Request, item_id: int, token: str = Form(default="")) -> HTMLResponse:
    """Rejeita o item — mesmo circuito de validação do que aprovar."""
    return _decidir(
        request, item_id, token=token, acao=fila.rejeitar, estado_sucesso="rejeitado"
    )
