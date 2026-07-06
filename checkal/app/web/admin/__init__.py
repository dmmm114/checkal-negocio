"""Painel admin do CheckAL (FASE 1 · WF3) — área privada, só do dono.

Este pacote reúne a autenticação (`auth`) e, nos módulos irmãos, o dashboard. A
fundação de segurança vive em `auth`: a dependência `requer_admin` guarda todas as
rotas do painel e o router de auth serve o login/logout. Reexporta-se aqui o
essencial para o resto do WF3 e o agente de integração montarem sem conhecer o
caminho interno:

    from app.web.admin import requer_admin          # guardar rotas do dashboard
    from app.web.admin import router as auth_router  # montar login/logout em criar_app
"""
from __future__ import annotations

from app.web.admin.auth import COOKIE_NOME, requer_admin, router

__all__ = ["COOKIE_NOME", "requer_admin", "router"]
