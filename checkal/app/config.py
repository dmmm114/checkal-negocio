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

# Portão 1-clique (fase 2): base URL pública das rotas /gate. Fail-closed:
# vazio ⇒ o maestro-gate-token não compõe URL e o digest cai para instrução
# manual. Em produção no Polaris: https://polaris.tail2f0d3e.ts.net:8443
# (tailscale funnel na porta 8443 — ver HANDOFF fase 2).
GATE_BASE_URL = _env("CHECKAL_GATE_BASE_URL", "")

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

# ==========================================================================
#  FASE 1 — funil consent-first: conservação de dados (parecer RGPD §5)
# ==========================================================================
# Prospects que NUNCA interagem apagam-se ao fim deste prazo. O parecer reviu o
# horizonte de 12 → 6 meses (mais seguro). A **lista de supressão** (`optouts`) NÃO
# cai nesta regra: conserva-se à parte e por mais tempo, como prova de que a oposição
# é honrada — a limpeza periódica de leads inativos (a agendar) usa esta constante e
# NUNCA toca `optouts`.
CONSERVACAO_PROSPECT_MESES = 6

# ==========================================================================
#  FDS 5 — fiabilidade: observabilidade, suporte IMAP, escalação, backups
# ==========================================================================
# Aditivo (AUTOMACAO.md §6). Todos os SEGREDOS (chaves/tokens/passwords/hosts)
# têm default VAZIO ⇒ LIVE-GATED: sem eles, nenhum seam toca a rede/IMAP/
# subprocess. Os únicos defaults não-vazios são endpoints públicos e políticas
# locais (base do Healthchecks, base da API Telegram, porta IMAP, retenção) —
# não são segredos. Os predicados `*_ativo()` (fundo do ficheiro) exprimem o gate.

# --- Healthchecks.io (dead-man switch de cada cron) ---
# Ping por slug: {base}/{ping_key}/{slug}[/fail|/start]. Sem PING_KEY ⇒ inativo.
HEALTHCHECKS_BASE_URL = _env("HEALTHCHECKS_BASE_URL", "https://hc-ping.com")
HEALTHCHECKS_PING_KEY = _env("HEALTHCHECKS_PING_KEY", "")   # ping key da conta (segredo)
HEALTHCHECKS_TIMEOUT_S = float(_env("HEALTHCHECKS_TIMEOUT_S", "10"))

# --- IMAP (mailbox apoio@ para o suporte de 1.ª linha por IA) ---
IMAP_HOST = _env("IMAP_HOST", "")            # ex.: imap.gmail.com (segredo/infra)
IMAP_PORT = int(_env("IMAP_PORT", "993"))    # IMAPS por omissão
IMAP_USER = _env("IMAP_USER", "")            # apoio@checkal.pt
IMAP_PASSWORD = _env("IMAP_PASSWORD", "")    # app-password (segredo)
IMAP_MAILBOX = _env("IMAP_MAILBOX", "INBOX")
IMAP_SSL = _env_bool("IMAP_SSL", True)

# --- Telegram (escalação ao dono: breaker ambíguo, suporte escalado, cron falhado) ---
TELEGRAM_API_BASE = _env("TELEGRAM_API_BASE", "https://api.telegram.org")
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")   # token do bot (segredo)
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")       # chat_id do dono (segredo/infra)
TELEGRAM_TIMEOUT_S = float(_env("TELEGRAM_TIMEOUT_S", "10"))

# --- Backups (pg_dump noturno + retenção; Storage Box Hetzner) ---
BACKUP_DIR = Path(_env("CHECKAL_BACKUP_DIR", str(DATA_DIR / "backups")))
BACKUP_DB_URL = _env("CHECKAL_BACKUP_DB_URL", "")     # DSN Postgres p/ pg_dump; vazio ⇒ inativo
BACKUP_PGDUMP_BIN = _env("CHECKAL_PGDUMP_BIN", "pg_dump")
BACKUP_RETENCAO_DIAS = int(_env("CHECKAL_BACKUP_RETENCAO_DIAS", "30"))

# ==========================================================================
#  FDS 6 — motor de campanhas: prospeção a frio B2B (HARD-GATED)
# ==========================================================================
# Aditivo (SPEC-FDS6.md §config, AUTOMACAO.md §7, LEGAL.md §1). O canal de email
# frio é PROIBIDO até o dono ter o parecer favorável do jurista RGPD — e isto é
# CÓDIGO, não disciplina humana: `CHECKAL_PARECER_RGPD_OK` é o PORTÃO e nasce
# False; enquanto for False, nenhum email frio sai (`pode_enviar_frio_global`).
#
# Fronteira DURA (SPEC-RESEND §0): o cold usa o domínio irmão `getcheckal.com` +
# SMTP dedicado (`COLD_SMTP_*`), NUNCA a Resend nem `checkal.pt` — a AUP da Resend
# proíbe cold e partilhar reputação suspenderia a conta transacional, derrubando
# os alertas dos clientes pagantes. Por isso o cold tem env vars PRÓPRIAS, jamais
# reutiliza `RESEND_*`/`EMAIL_FROM`, e o `COLD_FROM` sai sempre de getcheckal.com.
#
# Os SEGREDOS (host/user/pass) têm default VAZIO ⇒ LIVE-GATED: sem eles,
# `cold_smtp_ativo()` é False e nenhum seam de envio frio toca a rede. O envio é
# TRIPLAMENTE gated por `pode_enviar_frio_global()` (fundo do ficheiro): parecer
# OK  E  modo de teste OFF  E  SMTP de cold configurado. Este gate global é a
# MONTANTE do núcleo de compliance por-contacto (`app.compliance.*`); mesmo com
# ele aberto, cada contacto ainda tem de passar nif/email/minimizacao/optout.

# 🚦 PORTÃO BLOQUEANTE — parecer de jurista RGPD sobre reutilizar o RNAL para
# prospeção. Default False (inviolável): sem parecer, o canal frio não abre.
CHECKAL_PARECER_RGPD_OK = _env_bool("CHECKAL_PARECER_RGPD_OK", False)

# SMTP dedicado do canal frio (domínio irmão getcheckal.com) — SEPARADO da Resend.
# Segredos com default vazio ⇒ live-gate; a porta 587 (submissão STARTTLS) e o
# remetente getcheckal.com não são segredos.
COLD_SMTP_HOST = _env("COLD_SMTP_HOST", "")           # host SMTP de cold (segredo/infra)
COLD_SMTP_PORT = int(_env("COLD_SMTP_PORT", "587"))   # submissão STARTTLS por omissão
COLD_SMTP_USER = _env("COLD_SMTP_USER", "")           # utilizador SMTP (segredo)
COLD_SMTP_PASS = _env("COLD_SMTP_PASS", "")           # password SMTP (segredo)
# Remetente do canal frio: SEMPRE getcheckal.com, NUNCA checkal.pt (fronteira
# dura — a reputação de checkal.pt é ativo a proteger). Não é segredo.
COLD_FROM = _env("COLD_FROM", "CheckAL <geral@getcheckal.com>")

# Política de campanha (não são segredos). `CAMPANHA_JANELA_H` é o SLA "registo
# novo → prospeção correspondente" (72h). `CAMPANHA_CAP_DIARIO` é o teto humano
# por dia (warm-up do domínio irmão — dezenas/dia, não centenas; SPEC-RESEND §7.3).
CAMPANHA_JANELA_H = int(_env("CHECKAL_CAMPANHA_JANELA_H", "72"))
CAMPANHA_CAP_DIARIO = int(_env("CHECKAL_CAMPANHA_CAP_DIARIO", "20"))


# ==========================================================================
#  ENXAME DE AGENTES (Fase C do prompt-mestre) — gates e tetos novos
# ==========================================================================
# 🚦 RT-DPA — o Claude CLI (motor IA dos agentes no Polaris) envia prompts para a
# API da Anthropic (inferência nos EUA); NÃO mantém dados na UE. Enquanto o DPA
# comercial da Anthropic não estiver assinado, NENHUM agente LLM arranca — e isto
# é código, não disciplina. Default False (inviolável).
CHECKAL_ANTHROPIC_DPA_OK = _env_bool("CHECKAL_ANTHROPIC_DPA_OK", False)

# Tetos de custo LLM (swarm/tetos.py). Atingido o teto diário agregado, cria-se a
# flag-ficheiro PAUSA_LLM: os crons DETERMINISTAS continuam; só os passos LLM
# pausam. Os tetos NUNCA tocam os gates de segurança (parecer/modo teste/SMTP).
# Calibrados como DISJUNTOR (loop descontrolado), não como travão diário: o
# custo é indicativo (subscrição Max, sem faturação API) e um dia normal e
# cheio dos 4 agentes anda nos 8-15€ indicativos.
TETO_DIARIO_EUR = float(_env("CHECKAL_TETO_DIARIO_EUR", "25"))
TETO_AGENTE_EUR = float(_env("CHECKAL_TETO_AGENTE_EUR", "10"))
PAUSA_LLM_PATH = Path(_env("CHECKAL_PAUSA_LLM_PATH", "/run/checkal/PAUSA_LLM"))

# 🚦 RT-DGC — gate fail-closed do feed de oposição da DGC: o envio frio exige a
# lista carregada, não-vazia e com idade < DGC_MAX_IDADE_DIAS; lista vazia ou
# estagnada ⇒ trata-se como se TODOS estivessem opostos (recusa). O caminho do
# ficheiro é dado pelo dono quando o feed existir; vazio ⇒ gate fechado.
LISTA_DGC_PATH = _env("CHECKAL_LISTA_DGC_PATH", "")
DGC_MAX_IDADE_DIAS = int(_env("CHECKAL_DGC_MAX_IDADE_DIAS", "30"))


def anthropic_dpa_ok() -> bool:
    """O DPA comercial da Anthropic está assinado? (live-gate dos agentes LLM)."""
    return CHECKAL_ANTHROPIC_DPA_OK


def agente_llm_pode_arrancar() -> bool:
    """Portão de ARRANQUE de qualquer agente LLM (`claude -p`) no Polaris.

    False enquanto `CHECKAL_ANTHROPIC_DPA_OK` for False (RT-DPA): sem o DPA
    assinado, os dados enviados à inferência (mesmo agregados) não têm o
    enquadramento art. 28.º/Cap. V fechado — o runner e o wrapper recusam o
    arranque. Independente dos tetos de custo e dos gates de cold.
    """
    return CHECKAL_ANTHROPIC_DPA_OK


def cookie_secure() -> bool:
    """Cookie de sessão só por HTTPS em produção; relaxado sob pytest."""
    return not a_testar()


def healthchecks_ativo() -> bool:
    """O dead-man switch só pinga com ping key configurada (live-gate)."""
    return bool(HEALTHCHECKS_PING_KEY)


def imap_ativo() -> bool:
    """O suporte por IMAP só liga com host+user+password (live-gate)."""
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def telegram_ativo() -> bool:
    """A escalação Telegram só dispara com token+chat_id (live-gate)."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def backups_ativo() -> bool:
    """O pg_dump real só corre com DSN de origem definido (live-gate)."""
    return bool(BACKUP_DB_URL)


def cold_smtp_ativo() -> bool:
    """O canal frio (getcheckal.com) só liga com host+user+password de SMTP dedicado (live-gate).

    Espelha `imap_ativo`: sem os três segredos, nenhum seam de envio frio abre
    ligação SMTP. NÃO depende do parecer nem do modo de teste — esses somam-se em
    `pode_enviar_frio_global`.
    """
    return bool(COLD_SMTP_HOST and COLD_SMTP_USER and COLD_SMTP_PASS)


def pode_enviar_frio_global() -> bool:
    """Portão GLOBAL do canal frio — o único caminho para um email de prospeção sair.

    True SÓ se, CUMULATIVAMENTE (SPEC-FDS6.md §portão bloqueante):
      1. `CHECKAL_PARECER_RGPD_OK` — o dono tem parecer favorável do jurista RGPD;
      2. `CHECKAL_MODO_TESTE` está OFF — não se dispara em teste/sandbox;
      3. `cold_smtp_ativo()` — o SMTP dedicado de getcheckal.com está configurado.

    É o gate a MONTANTE do núcleo de compliance por-contacto (nif/email/
    minimizacao/optout): mesmo com isto True, cada contacto ainda tem de passar
    esse núcleo antes de ser contactado. Enquanto o parecer não chegar (o
    default), devolve sempre False — nenhum email frio sai.
    """
    return CHECKAL_PARECER_RGPD_OK and not CHECKAL_MODO_TESTE and cold_smtp_ativo()


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
