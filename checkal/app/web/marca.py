"""Design system do CheckAL — a FUNDAÇÃO de tokens que todo o web partilha.

Fonte ÚNICA (canónica) dos tokens de marca da FASE 1 (SPEC-FASE1-WEB §marca.py):

  * **cores** — as nove do SPEC, imutáveis (grafite, verde-check, azul-ação, …);
  * **assets** — os caminhos `/static/marca/*.svg` dos logótipos, badge e selos;
  * **planos** — reexportados de `config.PLANOS` (a folha de preços NÃO se duplica);
  * **templates** — a instância `Jinja2Templates` PARTILHADA (autoescape ligado,
    globais da marca injetados) que os routers usam para renderizar; e
  * **`contexto_base()`** — o dicionário marca/cores/assets/planos que alimenta o Jinja.

Fronteira do SPEC (inviolável): as cores vêm do SPEC e os preços de `config.PLANOS` —
este módulo NÃO inventa copy nem preços. É puro: importá-lo não toca a rede nem a BD.

Voz da marca: o "inspetor amigo" (positivo, alívio, não medo). Estados 🟢🟡🔴 têm
tokens próprios; o serviço é **PRIVADO** e nunca tem aspeto de Estado (daí o
qualificador legal presente em todo o rodapé).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

import app.config as config

# ==========================================================================
#  Cores (SPEC-FASE1-WEB §tokens — canónicas, não inventar)
# ==========================================================================
COR_GRAFITE = "#0F172A"           # tinta / wordmark
COR_VERDE_CHECK = "#12B76A"       # o ✓ e SÓ estados positivos
COR_AZUL_ACAO = "#2563EB"         # botões / links
COR_CINZA_SUSPENSO = "#94A3B8"    # verificação suspensa / neutro
COR_AMBAR = "#F59E0B"             # 🟡 atenção
COR_CORAL = "#DC2626"             # 🔴 falhou — só cliente/alerta, NUNCA no selo público
COR_FUNDO_FRIO = "#F8FAFC"        # fundo geral
COR_MARFIM = "#F6F2E9"            # marketing / email
COR_TEXTO_SECUNDARIO = "#475569"  # texto secundário

# Mapa nome→hex para o Jinja/CSS (chaves curtas, legíveis nos templates).
CORES: dict[str, str] = {
    "grafite": COR_GRAFITE,
    "verde_check": COR_VERDE_CHECK,
    "azul_acao": COR_AZUL_ACAO,
    "cinza_suspenso": COR_CINZA_SUSPENSO,
    "ambar": COR_AMBAR,
    "coral": COR_CORAL,
    "fundo_frio": COR_FUNDO_FRIO,
    "marfim": COR_MARFIM,
    "texto_secundario": COR_TEXTO_SECUNDARIO,
}

# ==========================================================================
#  Tipografia (SPEC — títulos Plus Jakarta Sans, texto Inter; Google Fonts <link>)
# ==========================================================================
FONTE_TITULOS = "'Plus Jakarta Sans'"
FONTE_TEXTO = "'Inter'"
# URL do <link> de Google Fonts (títulos 700/800, texto 400/500/600).
GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Plus+Jakarta+Sans:wght@700;800"
    "&family=Inter:wght@400;500;600"
    "&display=swap"
)

# ==========================================================================
#  Diretórios e URLs dos assets
# ==========================================================================
WEB_DIR = Path(__file__).resolve().parent          # .../app/web
STATIC_DIR = WEB_DIR / "static"                     # servido em /static
TEMPLATES_DIR = WEB_DIR / "templates"               # raiz do Jinja

STATIC_URL = "/static"
MARCA_URL = f"{STATIC_URL}/marca"
BRAND_CSS = f"{STATIC_URL}/brand.css"

LOGO_HORIZONTAL = f"{MARCA_URL}/logo-horizontal.svg"
LOGO_HORIZONTAL_ESCURO = f"{MARCA_URL}/logo-horizontal-escuro.svg"
LOGO_EMPILHADO = f"{MARCA_URL}/logo-empilhado.svg"
BADGE_AL = f"{MARCA_URL}/badge-AL.svg"
SELO_ATIVO = f"{MARCA_URL}/selo-ativo.svg"
SELO_SUSPENSO = f"{MARCA_URL}/selo-suspenso.svg"

ASSETS: dict[str, str] = {
    "brand_css": BRAND_CSS,
    "logo_horizontal": LOGO_HORIZONTAL,
    "logo_horizontal_escuro": LOGO_HORIZONTAL_ESCURO,
    "logo_empilhado": LOGO_EMPILHADO,
    "badge_al": BADGE_AL,
    "selo_ativo": SELO_ATIVO,
    "selo_suspenso": SELO_SUSPENSO,
}

# ==========================================================================
#  Identidade verbal (o mínimo estrutural — a copy longa vive em COPY-VENDAS.md)
# ==========================================================================
NOME = "CheckAL"
TAGLINE = "O teu AL? Check."
# Qualificador legal do rodapé — serviço PRIVADO, nunca aspeto de Estado (SPEC).
QUALIFICADOR_LEGAL = (
    "CheckAL — serviço privado e independente de monitorização de "
    "Alojamento Local · Cosmic Oasis, Lda."
)

# Rotas de navegação/rodapé (as páginas são construídas por outros módulos).
NAV = {
    "inicio": "/",
    "precos": "/precos",
    "privacidade": "/privacidade",
    "termos": "/termos",
    "remover": "/remover",
}

# ==========================================================================
#  Planos — reexportados de config (fonte ÚNICA; ver PRICING.md / config.PLANOS)
# ==========================================================================
PLANOS = config.PLANOS


def contexto_base() -> dict[str, Any]:
    """Contexto de marca partilhado por todos os templates Jinja.

    Devolve marca (nome/tagline/qualificador/nav), cores, assets e planos — para
    que qualquer template renderize com os tokens canónicos sem os redefinir. É
    injetado como *globais* de :data:`templates` (abaixo), pelo que está sempre
    disponível; cada rota pode ainda passar o seu próprio contexto por cima.
    """
    return {
        "marca": {
            "nome": NOME,
            "tagline": TAGLINE,
            "qualificador_legal": QUALIFICADOR_LEGAL,
            "nav": NAV,
            "google_fonts": GOOGLE_FONTS_URL,
        },
        "cores": CORES,
        "assets": ASSETS,
        "planos": PLANOS,
    }


# ==========================================================================
#  Jinja2Templates PARTILHADO — o seam de renderização de toda a FASE 1
# ==========================================================================
# Uma única instância (autoescape ligado por defeito para .html — anti-XSS) que os
# routers importam (`from app.web.marca import templates`). Os globais da marca são
# injetados uma vez, aqui, para que `base.html` e os que o estendem tenham sempre
# marca/cores/assets/planos sem cada rota os passar à mão.
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(contexto_base())
