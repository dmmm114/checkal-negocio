"""Configuração central do CheckAL: env, caminhos, preços, limiares, cadências.

Os valores de negócio (preços, coimas, limiares) são a folha canónica do
PLANO-NEGOCIO.md §5 — única fonte de verdade. Se divergirem de um documento,
o documento está errado.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Carregamento simples de .env (sem dependência externa) ---
BASE_DIR = Path(__file__).resolve().parent.parent  # .../checkal


def _carregar_env() -> None:
    f = BASE_DIR / ".env"
    if not f.is_file():
        return
    for linha in f.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


_carregar_env()


def _env(chave: str, default: str = "") -> str:
    return os.environ.get(chave, default)


def _env_bool(chave: str, default: bool) -> bool:
    """Lê um booleano do ambiente ('1/true/sim/yes/on' → True). Ausente → `default`."""
    v = os.environ.get(chave)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "sim", "yes", "on")


def a_testar() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


# --- Caminhos ---
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# --- Base de dados ---
DB_URL = _env("CHECKAL_DB_URL", f"sqlite:///{DATA_DIR / 'checkal.db'}")

# --- Segurança ---
SECRET_KEY = _env("CHECKAL_SECRET", "dev-inseguro-trocar")
ADMIN_PASSWORD = _env("CHECKAL_ADMIN_PASSWORD", "")
_DEFAULT_SECRET = "dev-inseguro-trocar"

# --- URLs ---
BASE_URL = _env("CHECKAL_BASE_URL", "http://localhost:8000")
SITE_URL = _env("CHECKAL_SITE_URL", "http://localhost:8000")

# --- RNAL (Turismo de Portugal) ---
RNAL_API = "https://webservices.turismodeportugal.pt/RNT_External/rest/RNT/list_RNAL"
RNAL_PAGINA = "https://rnt.turismodeportugal.pt/rnt/rnal.aspx"
RNAL_PAUSA_S = 2.0          # pausa entre concelhos (educação para com a API)
RNAL_TIMEOUT_S = 180.0
RNAL_USER_AGENT = "CheckAL/1.0 (+https://checkal.pt; monitorizacao de AL)"

# --- IA ---
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
MODEL_TRIAGEM = _env("CHECKAL_MODEL_TRIAGEM", "claude-haiku-4-5-20251001")
MODEL_ALERTA = _env("CHECKAL_MODEL_ALERTA", "claude-sonnet-5")

# --- Email / SMS ---
RESEND_API_KEY = _env("RESEND_API_KEY", "")
EMAIL_FROM = _env("CHECKAL_EMAIL_FROM", "CheckAL <alertas@checkal.pt>")
EMAIL_APOIO = _env("CHECKAL_EMAIL_APOIO", "apoio@checkal.pt")
SMS_PROVIDER_KEY = _env("SMS_PROVIDER_KEY", "")

# --- IfThenPay ---
IFTHENPAY_MB_KEY = _env("IFTHENPAY_MB_KEY", "")
IFTHENPAY_MBWAY_KEY = _env("IFTHENPAY_MBWAY_KEY", "")
IFTHENPAY_ANTIPHISHING_KEY = _env("IFTHENPAY_ANTIPHISHING_KEY", "")
IFTHENPAY_BASE = _env("IFTHENPAY_BASE", "https://api.ifthenpay.com")

# --- Stripe ---
STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET", "")

# --- InvoiceXpress ---
INVOICEXPRESS_ACCOUNT = _env("INVOICEXPRESS_ACCOUNT", "")
INVOICEXPRESS_API_KEY = _env("INVOICEXPRESS_API_KEY", "")
INVOICEXPRESS_SERIE = _env("INVOICEXPRESS_SERIE", "CKL")  # NOME da série (leitura humana)
# A API não referencia a série pelo nome, mas por um id numérico (SPEC-INVOICEXPRESS §5):
INVOICEXPRESS_SEQUENCE_ID = _env("INVOICEXPRESS_SEQUENCE_ID", "")  # id numérico da série CKL
# Nome exato da taxa de 23% tal como existe na tabela de taxas da conta (SPEC-INVOICEXPRESS §2.2):
INVOICEXPRESS_TAXA_NOME = _env("INVOICEXPRESS_TAXA_NOME", "IVA23")

# --- Fornecedor de faturação ativo ---
# O dono passou a faturar via TOConline (como no Radar Marca); a InvoiceXpress
# fica como adaptador secundário/referência atrás da mesma interface. Este seletor
# escolhe qual adaptador o fulfillment usa. Default: "toconline".
CHECKAL_FATURACAO_PROVIDER = _env("CHECKAL_FATURACAO_PROVIDER", "toconline")

# --- TOConline (Cloudware) — SPEC-TOCONLINE ---
# Base URLs e credenciais são POR-CONTA (não públicas): vêm no ficheiro de config
# de *Empresa > Dados API* e ficam vazias até o dono as dar. A série CKL nova
# cria-se na UI; o seu id/prefixo entram aqui depois. Placeholders vazios ⇒
# LIVE-GATED: sem credenciais, nada toca a rede.
TOCONLINE_OAUTH_URL = _env("TOCONLINE_OAUTH_URL", "")        # base OAuth2 (/auth, /token)
TOCONLINE_API_URL = _env("TOCONLINE_API_URL", "")            # base da API JSON:API
TOCONLINE_CLIENT_ID = _env("TOCONLINE_CLIENT_ID", "")        # OAuth2 client_id
TOCONLINE_CLIENT_SECRET = _env("TOCONLINE_CLIENT_SECRET", "")  # OAuth2 client_secret
TOCONLINE_SERIES_ID = _env("TOCONLINE_SERIES_ID", "")        # id numérico da série CKL (dado depois)
TOCONLINE_SERIES_PREFIX = _env("TOCONLINE_SERIES_PREFIX", "")  # alternativa: prefixo da série

# ==========================================================================
#  FOLHA DE PRESSUPOSTOS CANÓNICA (PLANO-NEGOCIO.md §5)
# ==========================================================================
IVA = 0.23

# Preços em euros, IVA incluído. Chave = código do plano.
PLANOS = {
    "anual":       {"nome": "CheckAL Anual",   "preco": 49.0,  "meses": 12,  "als_incluidos": 1},
    "trienal":     {"nome": "CheckAL Trienal",  "preco": 119.0, "meses": 36,  "als_incluidos": 1},
    "portfolio":   {"nome": "Portfólio",        "preco": 149.0, "meses": 12,  "als_incluidos": 10, "als_min": 4},
    "portfolio3":  {"nome": "Portfólio Trienal","preco": 359.0, "meses": 36,  "als_incluidos": 10, "als_min": 4},
    "portfolio_plus": {"nome": "Portfólio+",    "preco": 299.0, "meses": 12,  "als_incluidos": 25, "als_min": 11},
    "portfolio_max":  {"nome": "Portfólio Max", "preco": 499.0, "meses": 12,  "als_incluidos": 50, "als_min": 26},
}
AL_ADICIONAL_ANUAL = 19.0    # 2.º e 3.º AL no plano anual
AL_ADICIONAL_TRIENAL = 45.0  # 2.º e 3.º AL no plano trienal

# ==========================================================================
#  FDS 2 — billing (Stripe) + faturação (InvoiceXpress)
# ==========================================================================
# MODO DE TESTE, LIVE-GATED: nenhum módulo faz chamadas HTTP reais a
# Stripe/InvoiceXpress enquanto isto for True; o dono desliga em produção.
CHECKAL_MODO_TESTE = _env_bool("CHECKAL_MODO_TESTE", True)

# Mapa price_id (Stripe) → código de plano interno (chave de PLANOS).
# Alimentado por ambiente (STRIPE_PRICE_<PLANO>), sem segredos no código; vazio se não configurado.
STRIPE_PRICE_PLANO: dict[str, str] = {
    pid: plano
    for plano in PLANOS
    if (pid := _env(f"STRIPE_PRICE_{plano.upper()}"))
}

# Mapa código de plano → Payment Link URL (Stripe). Fonte: ambiente (STRIPE_PAYMENT_LINK_<PLANO>).
STRIPE_PAYMENT_LINKS: dict[str, str] = {
    plano: url
    for plano in PLANOS
    if (url := _env(f"STRIPE_PAYMENT_LINK_{plano.upper()}"))
}

# Coimas ASAE (únicos valores a usar em copy) — por tipo de titular.
COIMA = {
    "singular": (2500, 4000),
    "coletiva": (25000, 40000),
}

# Aquisição
CUSTO_CARTA = 1.30
GATE_CARTA_CONVERSAO = 0.008          # 0,8% — abaixo disto a carta não escala
GATE_CARTA_ESCALA = 0.012             # 0,012 E churn<=25% para escalar a sério
CHURN_ASSUMIDO_ANUAL = 0.20           # PALPITE — KPI n.º 1 a medir (coorte M13–M15)

# Cadências de monitorização (dias)
CADENCIA_CLIENTE_DIAS = 1             # página individual dos clientes: diária
CADENCIA_NACIONAL_DIAS = 3           # varrimento nacional: ~2×/semana
SLA_DETECAO_DIAS = 7                  # compromisso contratual (T&C)
REGRA_N_VARRIMENTOS = 2              # nº de ausências consecutivas p/ marcar desaparecido
BREAKER_PCT_CONCELHO = 0.03          # >3% da base do concelho desaparecida → circuit breaker

# --- Cache do dashboard ---
CACHE_TTL_S = 60


def cookie_secure() -> bool:
    """Cookie de sessão só por HTTPS em produção; relaxado sob pytest."""
    return not a_testar()


def assert_seguro() -> None:
    """Recusa arrancar com configuração insegura em produção (saltado sob pytest)."""
    if a_testar():
        return
    if not ADMIN_PASSWORD:
        raise RuntimeError("CHECKAL_ADMIN_PASSWORD não definida — login admin bloqueado.")
    if SECRET_KEY == _DEFAULT_SECRET:
        raise RuntimeError("CHECKAL_SECRET não definida — sessões/magic-links forjáveis.")


def concelhos_todos() -> list[str]:
    """Lista dos 308 concelhos (carregada de data/concelhos.txt se existir)."""
    f = DATA_DIR / "concelhos.txt"
    if f.is_file():
        return [c.strip() for c in f.read_text(encoding="utf-8").splitlines() if c.strip()]
    return CONCELHOS_PRIORITARIOS


# Concelhos prioritários do GTM (Vagas 1–2) — usados por omissão até haver a lista completa.
CONCELHOS_PRIORITARIOS = [
    "Lisboa", "Porto", "Albufeira", "Loulé", "Portimão", "Funchal",
    "Cascais", "Sintra", "Mafra", "Lagos", "Faro", "Olhão", "Tavira",
    "Vila Nova de Gaia", "Setúbal", "Nazaré", "Óbidos",
]
