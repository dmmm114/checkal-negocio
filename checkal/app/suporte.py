"""Suporte de 1.ª linha por IA (FDS 5, AUTOMACAO.md §5): cron de 15 min sobre `apoio@`.

Fronteira do módulo (SPEC-FDS5 §suporte): drena a caixa `apoio@checkal.pt` e, por cada
email não lido, decide **responder** (facto) ou **escalar ao dono** (Telegram/forward)::

    correr_suporte(session, *, leitor, cliente_ia, enviar, escalar) -> ResultadoSuporte

Para cada email:
  1. **Estado do cliente** — cruza-se o remetente com a BD (`clientes`/`registos`) para
     compor o bloco de estado da KB (a par da :data:`FAQ` fixa do produto). Remetente sem
     subscrição → responde-se à FAQ na mesma, com a nota "sem subscrição associada".
  2. **Decisão (Sonnet)** — uma chamada **structured output** (:func:`app.ia.cliente.pedir_json`
     com `config.MODEL_ALERTA`) devolve `{acao, categoria, confianca, resposta}`. O modelo
     compõe a resposta factual **e** classifica o pedido; a política de escalação é
     **reimposta em código** (defesa em profundidade) — nunca se confia só no `acao` do modelo.
  3. **Ramo** — 🚦 **ESCALA e NÃO responde sozinho** se detetar pedido jurídico específico,
     reclamação, intenção de cancelar com queixa, ou **confiança baixa** (:func:`_deve_escalar`).
     Caso contrário, responde ao remetente pelo `enviar` injetado. Em qualquer ramo, o email
     é marcado como processado (idempotência: a próxima corrida não o revê).

**Fail-safe (nada se perde, nada à toa):** IA indisponível (`cliente_ia is None`), JSON
inválido do modelo, ou `acao`/enum fora do esperado → **escala** (nunca uma resposta
automática insegura). Decisão de responder mas sem `enviar` → **escala** como salvaguarda.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria nenhum
cliente de rede — o `leitor` (IMAP), o `cliente_ia` (Anthropic), o `enviar` (Resend) e o
`escalar` (Telegram/forward) são **todos injetados** por quem chama. Os compositores
:func:`obter_leitor` (imaplib) e :func:`obter_escalador` (Telegram via httpx) são os
**únicos** pontos que ligam à rede/IMAP, e devolvem ``None`` sob `config.CHECKAL_MODO_TESTE`
ou sem credenciais (`config.imap_ativo()` / `config.telegram_ativo()`) — pelo que correr os
testes nunca toca a rede/IMAP. Os imports de `imaplib`/`email`/`httpx` são **tardios**,
dentro dos compositores/adaptadores, nunca no topo.

O `leitor` é qualquer objeto com:
  - ``nao_lidos() -> list[EmailRecebido]``    (emails por tratar)
  - ``marcar_processado(uid: str) -> None``   (marca \\Seen, idempotência)

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from typing import Any

import app.config as config
import app.models as models
from app.ia import cliente as _cliente

__all__ = [
    "EmailRecebido",
    "Decisao",
    "ResultadoSuporte",
    "correr_suporte",
    "obter_leitor",
    "obter_escalador",
    "ESQUEMA_SUPORTE",
    "FAQ",
    "GATILHOS_ESCALACAO",
    "ACOES",
    "CATEGORIAS",
    "CONFIANCAS",
]

# ==========================================================================
#  Vocabulário da decisão (enums do structured output)
# ==========================================================================
ACOES = ("responder", "escalar")
CATEGORIAS = ("factual", "juridico", "reclamacao", "cancelar_queixa", "outro")
CONFIANCAS = ("alta", "media", "baixa")

# Categorias que **obrigam** escalação ao dono, independentemente do `acao` do modelo
# (SPEC-FDS5 §suporte / AUTOMACAO §5): pedido jurídico específico, reclamação, e
# intenção de cancelar com queixa. A confiança baixa é tratada à parte em `_deve_escalar`.
GATILHOS_ESCALACAO = frozenset({"juridico", "reclamacao", "cancelar_queixa"})

# Schema do structured output da decisão de suporte (passado cru em `output_config.format`).
ESQUEMA_SUPORTE = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": list(ACOES)},
        "categoria": {"type": "string", "enum": list(CATEGORIAS)},
        "confianca": {"type": "string", "enum": list(CONFIANCAS)},
        "resposta": {"type": "string"},
    },
    "required": ["acao", "categoria", "confianca", "resposta"],
    "additionalProperties": False,
}

# Knowledge base fixa — factos do produto que o modelo pode citar. Sem jargão jurídico e
# sem aconselhamento (LEGAL.md: informação, não aconselhamento). Preços/coimas alinhados
# com a folha canónica (`config.PLANOS`, `config.COIMA`) — não repetir números fora daqui.
FAQ = (
    "FAQ DO CHECKAL (podes citar estes factos):\n"
    "- O que é: uma subscrição que vigia o registo RNAL, o seguro obrigatório e os "
    "regulamentos municipais de cada Alojamento Local, com alertas por email.\n"
    "- Preços (IVA incl.): Anual 49€/ano; Trienal 119€/3 anos; +19€/ano por AL adicional; "
    "Portfólio 149€ (4–10 ALs) / 299€ (11–25) / 499€ (26–50).\n"
    "- Garantia: 30 dias, reembolso total sem perguntas.\n"
    "- Mudar cartão / faturação: o cliente gere o cartão no portal de pagamento; se não "
    "encontrar o link, envia-se de novo.\n"
    "- Estado do registo: o CheckAL mostra o estado atual do AL no RNAL na página do "
    "cliente; um registo sinalizado é verificado antes de qualquer alerta de cancelamento.\n"
    "- Cadência: a página individual dos clientes é verificada diariamente; compromisso de "
    "deteção até 7 dias.\n"
    "- Cancelar: o cliente pode cancelar a renovação a qualquer momento; a subscrição "
    "corre até ao fim do período pago.\n"
    "- Natureza: os alertas são informação a partir de fontes públicas; não constituem "
    "aconselhamento jurídico."
)

# Papel + regras do modelo. Estável (o estado do cliente e o email entram à parte).
_SISTEMA_REGRAS = (
    "És o assistente de apoio ao cliente do CheckAL. Respondes em português de Portugal, "
    "de forma breve, factual e simpática, a proprietários de Alojamento Local.\n"
    "Regras invioláveis:\n"
    "1. Responde APENAS com base na FAQ e no ESTADO DO CLIENTE abaixo. Se a resposta não "
    "estiver aí, define confianca=baixa (o pedido será escalado a um humano).\n"
    "2. NUNCA dês aconselhamento jurídico. Se o email pede uma interpretação legal "
    "específica, define categoria=juridico.\n"
    "3. Se o email é uma reclamação, define categoria=reclamacao. Se manifesta intenção de "
    "cancelar COM queixa/insatisfação, define categoria=cancelar_queixa.\n"
    "4. Perguntas factuais respondíveis pela FAQ/estado → acao=responder, categoria=factual, "
    "e escreve a resposta no campo `resposta` (sem inventar números nem prazos).\n"
    "5. Na dúvida sobre se deves responder, escolhe confianca=baixa."
)

# Assinatura dos seams injetados (só para leitura; não impõe verificação).
Enviar = Callable[..., Any]
Escalar = Callable[..., Any]


# ==========================================================================
#  Estruturas de dados
# ==========================================================================
@dataclass(frozen=True)
class EmailRecebido:
    """Um email não lido da caixa `apoio@`, já normalizado pelo `leitor`.

    :param uid: identificador estável na caixa (para marcar como processado).
    :param de: endereço do remetente **já extraído** (sem `Nome <...>`).
    :param assunto: assunto do email.
    :param corpo: corpo em texto simples.
    """

    uid: str
    de: str
    assunto: str
    corpo: str


@dataclass(frozen=True)
class Decisao:
    """Decisão do modelo sobre um email, já normalizada aos enums.

    :param acao: `responder` | `escalar`.
    :param categoria: `factual` | `juridico` | `reclamacao` | `cancelar_queixa` | `outro`.
    :param confianca: `alta` | `media` | `baixa`.
    :param resposta: rascunho da resposta factual (usado só se se responder).
    """

    acao: str
    categoria: str
    confianca: str
    resposta: str


@dataclass
class ResultadoSuporte:
    """Sumário de uma corrida do cron de suporte (a caixa/BD são a fonte de verdade)."""

    lidos: int = 0
    respondidos: int = 0
    escalados: int = 0


# ==========================================================================
#  KB — estado do cliente lido da BD
# ==========================================================================
def _estado_cliente(session: Any, email: str) -> str:
    """Bloco de KB com o estado do cliente do `email` (ou nota de "sem subscrição").

    Cruza o remetente com `clientes` (match exato e, em falha, *case-insensitive*) e lista
    os ALs monitorizados. Um registo com `desaparecido_em` preenchido é descrito como
    **em verificação** — nunca como "cancelado" (respeita a guarda de sequência: só o
    breaker confirma cancelamentos).
    """
    alvo = (email or "").strip()
    cliente = None
    if alvo:
        cliente = (
            session.query(models.Cliente)
            .filter(models.Cliente.email == alvo)
            .first()
        )
        if cliente is None:  # tolerância a diferenças de caixa no endereço
            cliente = (
                session.query(models.Cliente)
                .filter(models.Cliente.email.ilike(alvo))
                .first()
            )
    if cliente is None:
        return "ESTADO DO CLIENTE: sem subscrição CheckAL associada a este email."

    linhas = [
        "ESTADO DO CLIENTE:",
        f"- Nome: {cliente.nome or '(sem nome)'} <{cliente.email or ''}>",
        f"- Plano: {cliente.plano or '(sem plano)'}; subscrição: {cliente.estado or '(sem estado)'}.",
    ]
    registos = list(getattr(cliente, "registos", None) or [])
    if registos:
        linhas.append("- ALs monitorizados:")
        for r in registos:
            estado_r = "ativo no RNAL" if r.desaparecido_em is None else "sinalizado, em verificação"
            nome_r = r.nome_alojamento or "(sem nome)"
            concelho_r = r.concelho or "(sem concelho)"
            linhas.append(f"  · nº {r.nr_registo}, \"{nome_r}\", {concelho_r} — {estado_r}")
    else:
        linhas.append("- ALs monitorizados: nenhum associado.")
    return "\n".join(linhas)


def _montar_sistema(estado: str) -> str:
    """Compõe o `system`: regras + FAQ (fixa) + estado do cliente (volátil)."""
    return f"{_SISTEMA_REGRAS}\n\n{FAQ}\n\n{estado}"


def _montar_utilizador(msg: EmailRecebido) -> str:
    """Compõe a mensagem `user`: o email do cliente (assunto + corpo)."""
    return f"EMAIL DO CLIENTE\nAssunto: {msg.assunto}\n\n{msg.corpo}"


# ==========================================================================
#  Decisão — chamada ao modelo + normalização defensiva
# ==========================================================================
def _decisao_de(dados: dict[str, Any]) -> Decisao:
    """Normaliza o dict do modelo a :class:`Decisao`, com defaults **seguros**.

    Qualquer valor fora do enum vira o ramo seguro: `acao`→`escalar`, `categoria`→`outro`,
    `confianca`→`baixa`. Assim um drift do modelo nunca produz uma resposta automática à toa.
    """
    acao = dados.get("acao")
    categoria = dados.get("categoria")
    confianca = dados.get("confianca")
    resposta = dados.get("resposta") or ""
    return Decisao(
        acao=acao if acao in ACOES else "escalar",
        categoria=categoria if categoria in CATEGORIAS else "outro",
        confianca=confianca if confianca in CONFIANCAS else "baixa",
        resposta=str(resposta),
    )


def _classificar(msg: EmailRecebido, estado: str, *, cliente_ia: Any) -> Decisao:
    """Decide sobre um email via structured output (Sonnet), ou escala se não puder.

    `cliente_ia is None` (IA indisponível) ou JSON inválido (`ErroIA`) → decisão de
    **escalar** com confiança baixa: nunca se responde automaticamente sem base.
    """
    if cliente_ia is None:
        return Decisao(acao="escalar", categoria="outro", confianca="baixa", resposta="")
    try:
        dados = _cliente.pedir_json(
            cliente_ia,
            modelo=config.MODEL_ALERTA,
            utilizador=_montar_utilizador(msg),
            esquema=ESQUEMA_SUPORTE,
            sistema=_montar_sistema(estado),
        )
    except _cliente.ErroIA:
        return Decisao(acao="escalar", categoria="outro", confianca="baixa", resposta="")
    return _decisao_de(dados)


def _deve_escalar(d: Decisao) -> bool:
    """Política de escalação (reimposta em código, defesa em profundidade).

    Escala se o modelo pediu escalar, se a categoria é de gatilho (jurídico/reclamação/
    cancelar-com-queixa), ou se a confiança é baixa.
    """
    return (
        d.acao == "escalar"
        or d.categoria in GATILHOS_ESCALACAO
        or d.confianca == "baixa"
    )


# ==========================================================================
#  Composição das mensagens de saída (resposta ao cliente / escalação ao dono)
# ==========================================================================
def _assunto_resposta(msg: EmailRecebido) -> str:
    """Assunto da resposta ao cliente (prefixo `Re:` idempotente)."""
    base = (msg.assunto or "o teu pedido").strip()
    return base if base.lower().startswith("re:") else f"Re: {base}"


def _html_resposta(resposta: str) -> str:
    """Corpo HTML mínimo da resposta ao cliente (texto + disclaimer factual)."""
    disclaimer = (
        "Isto é apoio ao cliente do CheckAL; a informação sobre regras de AL vem de fontes "
        "públicas e não constitui aconselhamento jurídico."
    )
    return (
        f"<p>{escape(resposta)}</p>"
        f'<p style="font-size:.85em;color:#6b7280">{escape(disclaimer)}</p>'
    )


def _corpo_escalacao(msg: EmailRecebido, decisao: Decisao, motivo: str) -> str:
    """Texto da escalação ao dono — inclui o email original para o dono decidir."""
    return (
        f"Motivo: {motivo}\n"
        f"De: {msg.de}\n"
        f"Assunto: {msg.assunto}\n"
        f"Categoria/Confiança: {decisao.categoria}/{decisao.confianca}\n"
        f"---\n{msg.corpo}"
    )


def _motivo(decisao: Decisao) -> str:
    """Frase-motivo da escalação (para o assunto/corpo ao dono)."""
    if decisao.categoria in GATILHOS_ESCALACAO:
        return {
            "juridico": "pedido jurídico específico",
            "reclamacao": "reclamação",
            "cancelar_queixa": "intenção de cancelar com queixa",
        }[decisao.categoria]
    if decisao.confianca == "baixa":
        return "confiança baixa / sem base na KB"
    return "escalação pedida pela análise"


# ==========================================================================
#  API pública — o cron
# ==========================================================================
def correr_suporte(
    session: Any,
    *,
    leitor: Any,
    cliente_ia: Any,
    enviar: Enviar | None = None,
    escalar: Escalar | None = None,
) -> ResultadoSuporte:
    """Corre uma passagem do suporte de 1.ª linha: lê `apoio@`, responde ou escala.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy de quem chama (para ler o estado do cliente da BD).
    leitor:
        Leitor de caixa **injetado** (`nao_lidos()`/`marcar_processado(uid)`); ``None`` ⇒
        caixa indisponível (live-gate) — não faz nada.
    cliente_ia:
        Cliente Anthropic **injetado** (falso nos testes; ``None`` ⇒ IA indisponível → escala).
    enviar:
        `enviar(*, para, assunto, html, ...)` **injetado** (Resend); ``None`` ⇒ envio
        indisponível → a resposta factual é **escalada** como salvaguarda (nada se perde).
    escalar:
        `escalar(*, assunto, corpo)` **injetado** (Telegram/forward ao dono).

    Devolve um :class:`ResultadoSuporte`. Cada email é marcado como processado (idempotência)
    após ser tratado; um email cujo tratamento não pôde concluir (sem escalador disponível
    para um caso que exige escalação) fica por marcar, para nova tentativa na próxima corrida.
    """
    resultado = ResultadoSuporte()
    if leitor is None:
        return resultado

    for msg in leitor.nao_lidos():
        resultado.lidos += 1
        estado = _estado_cliente(session, msg.de)
        decisao = _classificar(msg, estado, cliente_ia=cliente_ia)

        # Ramo A — escalar (gatilho, confiança baixa, ou IA indisponível). NÃO responde.
        if _deve_escalar(decisao):
            if _escala(msg, decisao, escalar):
                resultado.escalados += 1
                leitor.marcar_processado(msg.uid)
            continue

        # Ramo B — responder factual. Sem enviador → escala como salvaguarda.
        if enviar is not None and msg.de:
            enviar(
                para=msg.de,
                assunto=_assunto_resposta(msg),
                html=_html_resposta(decisao.resposta),
                texto=decisao.resposta,
                de=config.EMAIL_APOIO,
                idempotency_key=f"suporte-{msg.uid}",
            )
            resultado.respondidos += 1
            leitor.marcar_processado(msg.uid)
        elif _escala(msg, decisao, escalar):
            resultado.escalados += 1
            leitor.marcar_processado(msg.uid)

    return resultado


def _escala(msg: EmailRecebido, decisao: Decisao, escalar: Escalar | None) -> bool:
    """Escala o `msg` ao dono via `escalar` injetado; devolve ``True`` se escalou."""
    if escalar is None:
        return False
    motivo = _motivo(decisao)
    escalar(
        assunto=f"[CheckAL suporte] Escalar: {motivo} — {msg.assunto}",
        corpo=_corpo_escalacao(msg, decisao, motivo),
    )
    return True


# ==========================================================================
#  Compositores LIVE-GATED — os únicos pontos que ligam a IMAP / Telegram
# ==========================================================================
def obter_leitor() -> Any | None:
    """Compõe o leitor da caixa `apoio@` (imaplib), ou ``None`` (LIVE-GATED).

    Devolve ``None`` (sem importar `imaplib` nem ligar) sob `config.CHECKAL_MODO_TESTE`
    ou sem credenciais IMAP (`config.imap_ativo()`). Em produção liga por IMAPS e devolve
    um objeto com `nao_lidos()`/`marcar_processado(uid)`. O `imaplib`/`email` importam-se
    **tardiamente**, aqui — nunca no topo — pelo que os testes nunca tocam IMAP.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    if not config.imap_ativo():
        return None
    return _LeitorImap()


def obter_escalador() -> Escalar | None:
    """Compõe o escalador ao dono (Telegram via httpx), ou ``None`` (LIVE-GATED).

    Devolve ``None`` (sem importar `httpx` nem ligar) sob `config.CHECKAL_MODO_TESTE` ou
    sem `config.telegram_ativo()`. Em produção devolve `escalar(*, assunto, corpo)` que
    envia a mensagem ao chat do dono. O `httpx` importa-se **tardiamente**, aqui.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    if not config.telegram_ativo():
        return None

    import httpx  # import tardio: só quando de facto se liga em produção

    def escalar(*, assunto: str, corpo: str) -> None:
        url = f"{config.TELEGRAM_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        texto = f"{assunto}\n\n{corpo}"
        with httpx.Client(timeout=config.TELEGRAM_TIMEOUT_S) as c:
            r = c.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": texto})
            r.raise_for_status()

    return escalar


class _LeitorImap:
    """Adaptador imaplib da caixa `apoio@` (só instanciado por :func:`obter_leitor`).

    Liga por IMAPS a cada `nao_lidos()`, lê os `UNSEEN`, e `marcar_processado` põe `\\Seen`.
    Todos os imports de rede/stdlib-IMAP são **tardios**, dentro dos métodos, para que a mera
    importação do módulo (nos testes) nunca toque IMAP.
    """

    def nao_lidos(self) -> list[EmailRecebido]:
        import email
        import imaplib
        from email.header import decode_header, make_header
        from email.utils import parseaddr

        def _texto_do_email(msg: Any) -> str:
            if msg.is_multipart():
                for parte in msg.walk():
                    if parte.get_content_type() == "text/plain":
                        carga = parte.get_payload(decode=True) or b""
                        return carga.decode(parte.get_content_charset() or "utf-8", "replace")
                return ""
            carga = msg.get_payload(decode=True) or b""
            return carga.decode(msg.get_content_charset() or "utf-8", "replace")

        ligacao = (
            imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
            if config.IMAP_SSL
            else imaplib.IMAP4(config.IMAP_HOST, config.IMAP_PORT)
        )
        try:
            ligacao.login(config.IMAP_USER, config.IMAP_PASSWORD)
            ligacao.select(config.IMAP_MAILBOX)
            _typ, dados = ligacao.search(None, "UNSEEN")
            ids = (dados[0].split() if dados and dados[0] else [])
            mensagens: list[EmailRecebido] = []
            for num in ids:
                _t, bruto = ligacao.fetch(num, "(RFC822)")
                if not bruto or not bruto[0]:
                    continue
                msg = email.message_from_bytes(bruto[0][1])
                _nome, endereco = parseaddr(msg.get("From", ""))
                assunto = str(make_header(decode_header(msg.get("Subject", "")))) if msg.get("Subject") else ""
                mensagens.append(
                    EmailRecebido(
                        uid=num.decode() if isinstance(num, bytes) else str(num),
                        de=endereco,
                        assunto=assunto,
                        corpo=_texto_do_email(msg),
                    )
                )
            return mensagens
        finally:
            try:
                ligacao.logout()
            except Exception:  # noqa: BLE001 — logout best-effort; não mascara o resultado
                pass

    def marcar_processado(self, uid: str) -> None:
        import imaplib

        ligacao = (
            imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
            if config.IMAP_SSL
            else imaplib.IMAP4(config.IMAP_HOST, config.IMAP_PORT)
        )
        try:
            ligacao.login(config.IMAP_USER, config.IMAP_PASSWORD)
            ligacao.select(config.IMAP_MAILBOX)
            ligacao.store(uid, "+FLAGS", "\\Seen")
        finally:
            try:
                ligacao.logout()
            except Exception:  # noqa: BLE001
                pass
