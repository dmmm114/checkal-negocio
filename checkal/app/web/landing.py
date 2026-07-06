"""Landing pública consent-first do CheckAL + healthcheck (SPEC-FASE1-WEB §landing).

`GET /` serve a página inicial FINAL — a "cara" do produto sobre o motor já feito —
renderizada por Jinja a partir de `templates/landing.html` (que estende `base.html`).
`GET /saude` mantém-se como healthcheck de uptime/deploy (`{"ok": true}`).

Fronteiras (invioláveis):
  * a copy é canónica em ``../COPY-VENDAS.md`` e os preços em ``config.PLANOS`` (via
    ``marca.contexto_base()``, injetado como globais do Jinja) — este módulo NÃO
    inventa copy nem preços;
  * o widget é **consent-first**: o JS lê o nº de registo, consulta a vista pública
    ``GET /api/verificar`` (só dados do estabelecimento — ver ``app.web.verificar``) e
    só depois oferece o form de email + checkbox de consentimento que faz
    ``POST /inscrever`` (rota do módulo de consentimento). A checkbox NÃO vem
    pré-marcada e o JS constrói o cartão de estado com ``textContent`` (anti-XSS);
  * serviço PRIVADO, nunca aspeto de Estado — a barra de prova e o rodapé afirmam-no.

Puro e sem efeitos: renderizar `/` não toca a rede nem a BD (a verificação e a
inscrição vivem noutros routers e só se exercitam do lado do cliente / em POST).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import consentimento
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Página inicial consent-first (copy de COPY-VENDAS.md, preços de config.PLANOS).

    Renderiza `landing.html` com os globais da marca (`marca.contexto_base()`) já
    injetados no ambiente Jinja partilhado — hero, widget de verificação gratuita,
    "como funciona", preços, confiança, FAQ e CTA. Não consulta a BD.

    Os labels dos DOIS checkboxes de consentimento (granular — parecer RGPD §3) vêm
    das constantes canónicas de `app.web.consentimento`: a prova gravada é EXATAMENTE
    o texto mostrado (fecha o drift entre landing e a prova — achado do red-team).
    """
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "consentimento_alertas_texto": consentimento.CONSENTIMENTO_ALERTAS_TEXTO,
            "consentimento_ofertas_texto": consentimento.CONSENTIMENTO_OFERTAS_TEXTO,
            "consentimento_responsavel": consentimento.CONSENTIMENTO_RESPONSAVEL,
        },
    )


@router.get("/saude")
def saude() -> dict[str, bool]:
    """Healthcheck simples para uptime/deploy: `{"ok": true}`."""
    return {"ok": True}
