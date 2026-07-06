"""Páginas institucionais do CheckAL — preços, privacidade, termos, obrigado.

SPEC-FASE1-WEB §paginas. Quatro rotas GET que renderizam pela instância Jinja
PARTILHADA (`app.web.marca.templates` — autoescape ligado anti-XSS, globais de
marca/cores/assets/planos injetados), cada template estendendo `base.html`:

    GET /precos       tabela de preços      (fonte ÚNICA: config.PLANOS / PRICING.md)
    GET /privacidade  política RGPD         (responsável Cosmic Oasis, Lda.; CNPD; direitos)
    GET /termos       termos & condições    (natureza informativa; SLA ≤7 dias; garantia)
    GET /obrigado     confirmação           (double opt-in pendente — verifica o email)

Fronteira do SPEC (inviolável): NÃO se inventa copy nem preços. Os preços vêm de
`config.PLANOS`/`config.AL_ADICIONAL_*`/`config.COIMA`; a estrutura legal reflete
LEGAL.md e COPY-VENDAS.md. Onde faltam dados da entidade (NIPC/morada), ficam
placeholders honestos `[NIPC]`/`[morada]` — a regra de bloqueio de campanha (nenhuma
peça sai com placeholders por preencher) resolve-se ao ter os dados reais, não a
esconder a lacuna nas páginas institucionais.

Voz: o "inspetor amigo" — claro, positivo, alívio. Serviço **PRIVADO** e independente,
nunca aspeto de Estado (o qualificador legal vive no rodapé de `base.html`).

Puro e LIVE-GATED: renderizar templates não toca a rede nem a BD.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import app.config as config
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# Canal de contacto para direitos RGPD (LEGAL.md — usar tal e qual).
EMAIL_PRIVACIDADE = "privacidade@checkal.pt"


def _fmt_milhar(n: float) -> str:
    """Formata um inteiro com separador de milhar português: 2500 → ``2.500``."""
    return f"{int(n):,}".replace(",", ".")


@router.get("/precos", response_class=HTMLResponse)
def precos(request: Request) -> HTMLResponse:
    """Tabela de preços — valores canónicos de `config.PLANOS` (nunca duplicados aqui).

    Os planos chegam ao template pelos globais da marca (`planos`); os extras que não
    vivem no dicionário `PLANOS` (AL adicional, âncora de coima) passam por contexto,
    lidos de `config` — a folha de preços continua a ser fonte única.
    """
    return templates.TemplateResponse(
        request,
        "precos.html",
        {
            "al_adicional_anual": config.AL_ADICIONAL_ANUAL,
            "al_adicional_trienal": config.AL_ADICIONAL_TRIENAL,
            # âncora de custo de inação (ASAE, valores canónicos — PRICING.md §1)
            "coima_singular_min": _fmt_milhar(config.COIMA["singular"][0]),
            "coima_coletiva_max": _fmt_milhar(config.COIMA["coletiva"][1]),
        },
    )


@router.get("/privacidade", response_class=HTMLResponse)
def privacidade(request: Request) -> HTMLResponse:
    """Política de privacidade RGPD (responsável Cosmic Oasis, Lda.; CNPD; direitos)."""
    return templates.TemplateResponse(
        request,
        "privacidade.html",
        {"email_privacidade": EMAIL_PRIVACIDADE},
    )


@router.get("/termos", response_class=HTMLResponse)
def termos(request: Request) -> HTMLResponse:
    """Termos & Condições (natureza informativa; SLA ≤7 dias; garantia 30 dias)."""
    return templates.TemplateResponse(
        request,
        "termos.html",
        {"email_privacidade": EMAIL_PRIVACIDADE},
    )


@router.get("/obrigado", response_class=HTMLResponse)
def obrigado(request: Request) -> HTMLResponse:
    """Confirmação pós-inscrição — double opt-in pendente (verifica a caixa de entrada)."""
    return templates.TemplateResponse(request, "obrigado.html", {})
