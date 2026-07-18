"""Composição da aplicação web do CheckAL (FDS 2/3 + FASE 1 · SPEC-FASE1-WEB §Wire).

`criar_app() -> FastAPI` é a **fábrica** que monta, numa única aplicação, TODOS os
routers do website — mantidos deliberadamente em módulos disjuntos (fronteiras do
SPEC) e reunidos só aqui:

    app.web.landing         → GET /                    (landing consent-first)
                              GET /saude               (healthcheck de uptime/deploy)
    app.web.verificar       → GET /api/verificar       (verificação pública consent-first)
    app.web.paginas         → GET /precos /privacidade /termos /obrigado
    app.web.consentimento   → POST /inscrever · GET /confirmar (double opt-in)
    app.web.remover         → GET/POST /remover        (opt-out / direito de oposição)
    app.web.selo            → GET /selo/{nr_registo}    (página pública do selo — FDS 3)
    app.web.webhook_stripe  → POST /webhooks/stripe     (webhook único da Stripe)

    app.web.admin.auth               → GET/POST /admin/login · GET /admin/logout
    app.web.admin.dashboard_overview → GET /admin · GET /admin/leads
    app.web.admin.dashboard_clientes → GET /admin/clientes · GET /admin/alertas
    app.web.admin.dashboard_campanhas→ GET /admin/campanhas · /admin/compliance (+CSV)

O painel `/admin/*` é a área PRIVADA do dono (FASE 1 · WF3): o login é público (senão
não haveria como entrar), mas todas as rotas do dashboard estão sob `requer_admin`
(sessão assinada `itsdangerous` + `config.SECRET_KEY`). Os routers do admin já
carregam o prefixo `/admin` nos próprios paths, pelo que se montam SEM prefixo
adicional (montá-los com `prefix="/admin"` duplicaria para `/admin/admin`). O portão
de cold é CÓDIGO, não confiança: a página de campanhas mostra a fila mas o botão de
disparo nasce DESATIVADO e não existe endpoint que ENVIE (respeita
`config.pode_enviar_frio_global()`).

Porquê uma *fábrica* e não um `app` de módulo: cada teste (e cada processo de
produção) obtém uma instância fresca com os routers montados, sem estado global de
importação. A configuração da BD vive em `app.db` (o motor é trocado por um SQLite
temporário nos testes via monkeypatch), pelo que esta fábrica **não** cria tabelas
nem toca a rede — limita-se a compor as rotas. Assim `criar_app()` é puro e sem
efeitos colaterais: importá-lo/instanciá-lo durante a recolha de testes não escreve
na BD de dev nem liga a Stripe/InvoiceXpress.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Nada aqui faz chamadas HTTP
reais nem envia emails: o double opt-in passa pelo seam `app.envio.obter_enviador`
(devolve `None` em teste) e o cliente HTTP do InvoiceXpress é composto (e *gated*)
dentro do webhook. Nada de emails, nada de cold.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web import (
    consentimento,
    landing,
    marca,
    pagar,
    paginas,
    remover,
    selo,
    verificar,
    webhook_stripe,
)
from app.web.admin import (
    auth as admin_auth,
    dashboard_campanhas,
    dashboard_clientes,
    dashboard_overview,
)


def criar_app() -> FastAPI:
    """Cria e devolve a aplicação FastAPI do CheckAL com TODOS os routers montados.

    Monta a landing (+ healthcheck), a verificação pública consent-first, as páginas
    institucionais, o funil de consentimento (double opt-in), o opt-out, a página
    pública do selo e o webhook único da Stripe. Não cria tabelas nem abre ligações: a
    persistência resolve-se em `app.db` no momento de cada request (o que permite aos
    testes trocarem o motor por um SQLite temporário antes de exercitar as rotas).
    """
    app = FastAPI(
        title="CheckAL",
        description="Monitorização RNAL + seguro + regulamentos municipais de Alojamento Local.",
        version="3.0",  # FDS 3
    )
    # Design system (FASE 1): serve brand.css + assets de marca em /static. A
    # instância Jinja2Templates partilhada vive em `app.web.marca` (autoescape
    # ligado, globais da marca injetados) e é usada pelos routers ao renderizar.
    app.mount("/static", StaticFiles(directory=str(marca.STATIC_DIR)), name="static")

    app.include_router(landing.router)
    app.include_router(verificar.router)
    app.include_router(paginas.router)
    app.include_router(consentimento.router)
    app.include_router(remover.router)
    app.include_router(selo.router)
    app.include_router(webhook_stripe.router)
    # Fase G — pagamento cold-direto (IfThenPay, LIVE-GATED): GET/POST /pagar +
    # POST /callback/ifthenpay. Fatura (série CKL) e onboarding só com callback pago.
    app.include_router(pagar.router)

    # Painel admin (FASE 1 · WF3) — área privada do dono. Os routers já embutem o
    # prefixo `/admin` nos paths, por isso montam-se sem prefixo adicional. O login é
    # público; o dashboard está sob `requer_admin`.
    app.include_router(admin_auth.router)
    app.include_router(dashboard_overview.router)
    app.include_router(dashboard_clientes.router)
    app.include_router(dashboard_campanhas.router)
    return app
