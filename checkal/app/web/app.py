"""Composição da aplicação web do CheckAL (FDS 2, SPEC-FDS2.md §app).

`criar_app() -> FastAPI` é a **fábrica** que monta, numa única aplicação, os três
routers do FDS 2 — mantidos deliberadamente em módulos disjuntos (fronteiras do
SPEC) e reunidos só aqui:

    app.web.landing         → GET /            (landing placeholder)
                              GET /saude       (healthcheck de uptime/deploy)
    app.web.verificar       → GET /api/verificar   (verificação pública consent-first)
    app.web.webhook_stripe  → POST /webhooks/stripe (webhook único da Stripe)
    app.web.selo            → GET /selo/{nr_registo} (página pública do selo — FDS 3)

Porquê uma *fábrica* e não um `app` de módulo: cada teste (e cada processo de
produção) obtém uma instância fresca com os routers montados, sem estado global de
importação. A configuração da BD vive em `app.db` (o motor é trocado por um SQLite
temporário nos testes via monkeypatch), pelo que esta fábrica **não** cria tabelas
nem toca a rede — limita-se a compor as rotas. Assim `criar_app()` é puro e sem
efeitos colaterais: importá-lo/instanciá-lo durante a recolha de testes não escreve
na BD de dev nem liga a Stripe/InvoiceXpress.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Nada aqui faz chamadas HTTP
reais; o cliente HTTP do InvoiceXpress é composto (e *gated*) dentro do webhook, e
injetado no fulfillment. Nada de emails, nada de cold.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.web import landing, selo, verificar, webhook_stripe


def criar_app() -> FastAPI:
    """Cria e devolve a aplicação FastAPI do CheckAL com os três routers montados.

    Monta, por esta ordem, a landing (+ healthcheck), a verificação pública
    consent-first, o webhook único da Stripe e a página pública do selo (FDS 3). Não
    cria tabelas nem abre ligações: a persistência resolve-se em `app.db` no momento de
    cada request (o que permite aos testes trocarem o motor por um SQLite temporário
    antes de exercitar as rotas).
    """
    app = FastAPI(
        title="CheckAL",
        description="Monitorização RNAL + seguro + regulamentos municipais de Alojamento Local.",
        version="3.0",  # FDS 3
    )
    app.include_router(landing.router)
    app.include_router(verificar.router)
    app.include_router(webhook_stripe.router)
    app.include_router(selo.router)
    return app
