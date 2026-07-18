"""Linter determinista de texto outward-facing — o portão de qualidade do ENXAME.

Corre ANTES de qualquer texto produzido por agente (ANGARIADOR, GESTOR-DE-CLIENTE,
SENTINELA) ser marcado *aprovável* — a montante da aprovação 1-clique do MAESTRO.
**Não substitui** os detetores existentes; **compõe-os e amplia-os** para todo o
texto outward-facing (não só o alerta):

  - Reutiliza :func:`app.ia.validacao.validar_alerta` (grounding: fonte citada +
    zero valores órfãos) — regras R4/R6.
  - Reutiliza :func:`app.ia.guardrails.validar_nao_prescritivo` (anti-atividade-
    reservada, Lei 10/2024) — regra R2 — e a técnica `_RE_CITACAO` (as citações da
    fonte são removidas antes da varredura da voz própria).
  - Acrescenta as regras de forma/RGPD/AI-Act que aqueles não cobrem: coima-como-
    ameaça e moldura canónica (R3), divulgação de IA (R5, AI Act art. 50),
    disclaimer "informação, não aconselhamento" (R7), opt-out 1-clique (R8),
    identificação legal do remetente cold (R9) — e as regras extra do red-team:
    checkal.pt como REMETENTE em canal COLD, coima a <2 frases de um identificador
    do destinatário, verbo de estado jurídico sobre "o seu/o vosso" registo.

Fronteira de domínio (nota ADENDA §1/§6): no canal COLD o que é proibido é o
`checkal.pt` como REMETENTE/domínio de envio (a reputação transacional é o ativo a
proteger). Links de DESTINO para checkal.pt são legítimos e desejados — o CTA
"Pagar já" do próprio email frio aponta a `checkal.pt/pagar` (decisão do dono).

Função pura, determinística, SEM I/O de rede/BD, conservadora: na dúvida REJEITA
(o viés inviolável herdado de `validacao.py`/`guardrails.py` — alargar a deteção é
sempre seguro; nunca um falso "aprovado").
"""
from __future__ import annotations

import enum
import html as _html
import re
from dataclasses import dataclass, field

import app.config as config
from app.ia.guardrails import _RE_CITACAO, validar_nao_prescritivo
from app.ia.validacao import validar_alerta

__all__ = [
    "Canal",
    "Severidade",
    "PecaOutward",
    "Violacao",
    "ResultadoLint",
    "LINTER_VERSAO",
    "DIVULGACAO_IA",
    "lint",
]

# Versionado como GUARDRAILS_VERSAO — parte do dossier de defesa (regras curadas).
LINTER_VERSAO = "2026-07-18"

# Frase canónica de divulgação de IA (AI Act art. 50) — os templates redigidos por
# agente embutem-na; o linter (R5) reprova a ausência quando `gerado_por_ia=True`.
DIVULGACAO_IA = (
    "Conteúdo preparado com apoio de inteligência artificial (IA) e validado por "
    "regras automáticas do CheckAL."
)


# ==========================================================================
#  Tipos
# ==========================================================================
class Canal(enum.Enum):
    """Canal da peça — define quais regras o linter EXIGE (tabela de despacho)."""

    ALERTA = "alerta"
    COLD = "cold"
    NURTURE_TRANSACIONAL = "nurture_transacional"
    PAGINA_PUBLICA = "pagina_publica"
    ONE_PAGER = "one_pager"
    RELATORIO = "relatorio"


class Severidade(enum.Enum):
    BLOQUEIA = "bloqueia"
    AVISA = "avisa"


@dataclass(frozen=True)
class PecaOutward:
    """Uma peça de texto outward-facing a vetar (imutável).

    :param texto: corpo renderizado (texto ou HTML — o linter normaliza a texto).
    :param canal: o :class:`Canal` da peça (despacho de regras).
    :param url_fonte: URL do documento-fonte (passada a `validar_alerta` — R4/R6).
    :param excerto: excerto do documento-fonte (grounding de valores — R6).
    :param gerado_por_ia: a peça foi redigida por modelo? (dispara R5).
    :param tem_optout_carimbado: o seam de envio carimba o opt-out (RFC 8058)?
        No cold, o opt-out real é carimbado por `cold_email.enviar_frio` — este
        sinal evita reprovar um rascunho cujo opt-out chega no seam.
    """

    texto: str
    canal: Canal
    url_fonte: str | None = None
    excerto: str | None = None
    gerado_por_ia: bool = False
    tem_optout_carimbado: bool = False


@dataclass(frozen=True)
class Violacao:
    regra: str                     # id estável, ex. "R1_ILEGALIDADE"
    severidade: Severidade         # BLOQUEIA | AVISA
    trecho: str                    # excerto ofensor (para o agente corrigir)
    razao: str                     # mensagem PT-PT acionável


@dataclass(frozen=True)
class ResultadoLint:
    aprovado: bool                 # True só se NENHUMA regra bloqueante falhar
    violacoes: list[Violacao] = field(default_factory=list)
    versao: str = LINTER_VERSAO


# ==========================================================================
#  Normalização (HTML → texto; citações removidas para a voz própria)
# ==========================================================================
_RE_TAG = re.compile(r"(?is)<[^>]+>")
_RE_BR = re.compile(r"(?is)<br\s*/?>|</(?:p|div|tr|h[1-6]|li)>")


def _texto_plano(texto: str) -> str:
    """HTML → texto determinístico (tira tags, resolve entidades). Idempotente."""
    t = _RE_BR.sub("\n", texto)
    t = _RE_TAG.sub(" ", t)
    t = _html.unescape(t)
    return re.sub(r"[ \t]+", " ", t).strip()


def _frases(texto: str) -> list[str]:
    """Divide em frases sem partir abreviaturas ("Lda.", "n.º") nem milhares.

    Só corta após [.!?…] seguido de espaço E de maiúscula/«/dígito — "Lda. é" e
    "n.º 100031" ficam inteiros; "100031. As coimas" corta.
    """
    partes = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"(])", texto)
    return [p.strip() for p in partes if p.strip()]


# ==========================================================================
#  R1 — ilegalidade/incumprimento afirmado (voz própria, sem citações)
# ==========================================================================
_RE_R1 = re.compile(
    r"\b(?:ilegal|sem\s+seguro|em\s+incumprimento|incumprimento|"
    r"em\s+infra[cç]?[çc][aã]o|irregular(?:idade)?|"
    r"est[áa]s?\s+obrigad\w*|[ée]s\s+obrigad\w*)\b"
)
_RE_R1_REFLEXIVO = re.compile(
    r"\b(?:encontra|fica)\w*[-\s]*se\s+em\s+(?:situa[çc][ãa]o\s+de\s+)?"
    r"(?:incumprimento|infra[cç]?[çc][aã]o)"
)

# ==========================================================================
#  R3 — coima como ameaça individualizada + moldura canónica de config.COIMA
# ==========================================================================
_RE_R3_AMEACA = [
    re.compile(r"\b(?:a\s+tua|a\s+sua|vais\s+ser|v[ãa]o\s+ser|podes\s+ser)\b.{0,40}\b(?:coima|multa\w*)"),
    re.compile(r"\b(?:coima|multa)\b.{0,20}\b(?:que\s+te|que\s+vos|para\s+ti|para\s+v[óo]s)\b"),
    re.compile(r"\barrisca[sm]?\b.{0,40}(?:coima|multa|€|euros?\b|\d)"),
]
_RE_VALOR_EUR = re.compile(
    r"(\d{1,3}(?:[.\s  ]\d{3})*(?:,\d+)?)\s*(?:€|euros?\b)"
)
_RE_COIMA_PALAVRA = re.compile(r"\b(?:coima|multa)\w*\b")

# ==========================================================================
#  Regras extra do red-team
# ==========================================================================
# Domínio de ENVIO em cold: endereço @checkal.pt ou menção de remetente/envio.
_RE_RT_DOMINIO = [
    re.compile(r"[a-z0-9._%+\-]+@checkal\.pt\b"),
    re.compile(r"\b(?:remetente|enviado\s+(?:de|por))\b[^\n]{0,60}checkal\.pt"),
]
# Verbo de estado jurídico sobre "o seu/o vosso" registo.
_RE_RT_ESTADO = re.compile(
    r"\b(?:o|do|ao)\s+(?:seu|vosso|teu)\s+registo[^.!?\n]{0,40}?"
    r"(?:caduc\w+|cancelad\w+|suspens\w+|ilegal|irregular\w*)"
)
# Identificador do destinatário (para a regra de proximidade da coima).
_RE_IDENTIFICADOR = re.compile(
    r"registo\s+(?:de\s+al(?:ojamento\s+local)?\s+)?n\.?\s*[ºo°]?\s*\d+"
    r"|\bnif\b\s*\d*"
    r"|[ée]\s+titular"
)

# ==========================================================================
#  Exigências por canal (R4/R5/R7/R8/R9)
# ==========================================================================
_RE_R4_FONTE_OFICIAL = re.compile(
    r"turismodeportugal\.pt|dre\.pt|diariodarepublica\.pt|\.gov\.pt|cm-[a-z-]+\.pt"
)
_RE_R5_DIVULGACAO = re.compile(
    r"ai-disclosure"
    r"|(?:gerad|redigid|produzid|apoiad|preparad|elaborad|escrit)\w*"
    r"[^.!?\n]{0,60}(?:intelig[êe]ncia\s+artificial|\bia\b)"
)
_RE_R7_DISCLAIMER = re.compile(
    r"(?:informa[çc][ãa]o|informativ[oa])[^.!?\n]{0,150}?n[ãa]o[^.!?\n]{0,40}aconselhamento"
    r"|n[ãa]o\s+constitu\w*\s+aconselhamento"
)
_RE_R8_OPTOUT = re.compile(r"(?:get)?checkal\.(?:pt|com)/remover")
_RE_R9_IDENTIFICACAO = re.compile(r"cosmic\s+oasis")

# Tabela §3 da spec: que exigências cada canal tem. As PROIBIÇÕES (R1/R2/R3 +
# regras RT) aplicam-se SEMPRE, a todos os canais. `R5` só quando gerado_por_ia.
# RELATORIO = transacional do pagante: sem R7 por decisão de produto (o relatório
# mensal "passou no check" não é alerta — compliance §9.5); opt-out garantido pela
# base de email. R6-pleno (validar_alerta) nos canais que afirmam factos regulatórios.
_EXIGE_R4 = {Canal.ALERTA, Canal.PAGINA_PUBLICA, Canal.ONE_PAGER}
_EXIGE_R6_PLENO = {Canal.ALERTA, Canal.PAGINA_PUBLICA, Canal.ONE_PAGER}
_EXIGE_R7 = {Canal.ALERTA, Canal.COLD, Canal.NURTURE_TRANSACIONAL,
             Canal.PAGINA_PUBLICA, Canal.ONE_PAGER}
_EXIGE_R8 = {Canal.COLD, Canal.NURTURE_TRANSACIONAL, Canal.RELATORIO}
_EXIGE_R9 = {Canal.COLD}


def _molduras_coima() -> set[float]:
    """Os únicos valores de coima admissíveis em copy — de `config.COIMA`."""
    valores: set[float] = set()
    for par in config.COIMA.values():
        valores.update(float(v) for v in par)
    return valores


def _para_valor(bruto: str) -> float | None:
    limpo = re.sub(r"[.\s  ]", "", bruto).replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


# ==========================================================================
#  API pública
# ==========================================================================
def lint(peca: PecaOutward) -> ResultadoLint:
    """Veta uma peça outward-facing. Devolve :class:`ResultadoLint` (imutável).

    `aprovado = not any(v.severidade is BLOQUEIA)`. Função pura: sem rede, sem BD,
    determinística. Na dúvida REJEITA — nunca um falso "aprovado" perante conclusão
    jurídica individualizada, ilegalidade afirmada, coima-ameaça ou valor órfão.
    """
    violacoes: list[Violacao] = []

    bruto_lc = (peca.texto or "").lower()  # p/ deteções que o strip de HTML esconderia
    plano = _texto_plano(peca.texto or "")
    # A voz própria: sem as citações da fonte (mesma técnica de guardrails).
    voz = _RE_CITACAO.sub(" ", plano)
    voz_lc = voz.lower()

    def _bloqueia(regra: str, trecho: str, razao: str) -> None:
        violacoes.append(
            Violacao(regra=regra, severidade=Severidade.BLOQUEIA,
                     trecho=" ".join(trecho.split())[:160], razao=razao)
        )

    # ---------- Proibições (todos os canais) ----------
    # R1 — ilegalidade/incumprimento afirmado.
    for rx in (_RE_R1, _RE_R1_REFLEXIVO):
        m = rx.search(voz_lc)
        if m:
            _bloqueia(
                "R1_ILEGALIDADE", m.group(0),
                "Afirma ilegalidade/incumprimento — os alertas descrevem factos "
                "atribuídos à fonte, nunca o estado jurídico de alguém.",
            )
            break

    # R2 — conclusão jurídica individualizada (delegado nos guardrails).
    r2 = validar_nao_prescritivo(plano)
    for motivo in r2.motivos:
        _bloqueia("R2_PRESCRITIVO", motivo, motivo)

    # R3 — coima como ameaça individualizada.
    for rx in _RE_R3_AMEACA:
        m = rx.search(voz_lc)
        if m:
            _bloqueia(
                "R3_COIMA_AMEACA", m.group(0),
                "Usa a coima como ameaça individualizada — só é admissível o "
                "condicional impessoal ('podem ir de … a …') com a moldura canónica.",
            )
            break

    # R6-moldura — qualquer valor de coima fora de config.COIMA é proibido.
    molduras = _molduras_coima()
    frases = _frases(voz)
    idx_coima: list[int] = []
    idx_ident: list[int] = []
    for i, frase in enumerate(frases):
        frase_lc = frase.lower()
        if _RE_COIMA_PALAVRA.search(frase_lc):
            idx_coima.append(i)
            for m in _RE_VALOR_EUR.finditer(frase_lc):
                valor = _para_valor(m.group(1))
                if valor is not None and valor not in molduras:
                    _bloqueia(
                        "R6_COIMA_MOLDURA", frase,
                        f"Valor de coima {m.group(0)!r} fora da moldura canónica "
                        "de config.COIMA (singular 2.500–4.000 € · coletiva "
                        "25.000–40.000 €).",
                    )
        if _RE_IDENTIFICADOR.search(frase_lc):
            idx_ident.append(i)

    # RT — coima a < 2 frases de um identificador do destinatário.
    for ic in idx_coima:
        if any(abs(ic - ii) < 2 for ii in idx_ident):
            _bloqueia(
                "RT_COIMA_PROXIMIDADE", frases[ic],
                "Coima a menos de 2 frases de um identificador do destinatário — "
                "separa o contexto de coimas da identificação do registo/empresa.",
            )
            break

    # RT — verbo de estado jurídico sobre "o seu/o vosso" registo.
    m = _RE_RT_ESTADO.search(voz_lc)
    if m:
        _bloqueia(
            "RT_ESTADO_JURIDICO", m.group(0),
            "Afirma um estado jurídico ('caducou/cancelado/ilegal') sobre o registo "
            "do destinatário — descreve como 'em verificação' e cita a fonte.",
        )

    # RT — fronteira de domínio: checkal.pt como REMETENTE em canal COLD.
    # Varre também o texto BRUTO: num HTML, "<geral@checkal.pt>" parece uma tag
    # e o strip escondê-lo-ia da varredura sobre o texto plano.
    if peca.canal is Canal.COLD:
        for rx in _RE_RT_DOMINIO:
            m = rx.search(voz_lc) or rx.search(bruto_lc)
            if m:
                _bloqueia(
                    "RT_DOMINIO_COLD", m.group(0),
                    "O cold NUNCA usa checkal.pt como remetente/domínio de envio — "
                    "o canal frio vive em getcheckal.com (COLD_FROM). Links de "
                    "destino para checkal.pt são permitidos; endereços @checkal.pt não.",
                )
                break

    # ---------- Exigências por canal ----------
    plano_lc = plano.lower()

    if peca.canal in _EXIGE_R4 and not _RE_R4_FONTE_OFICIAL.search(plano_lc):
        _bloqueia(
            "R4_FONTE_OFICIAL", plano_lc[:80],
            "Falta o link para a fonte oficial (turismodeportugal.pt / DRE / "
            "portal municipal).",
        )

    # R5: o marcador pode viver num comentário HTML (<!-- AI-DISCLOSURE -->),
    # que o strip de tags remove — por isso aceita-se também no texto bruto.
    if peca.gerado_por_ia and not (
        _RE_R5_DIVULGACAO.search(plano_lc) or "ai-disclosure" in bruto_lc
    ):
        _bloqueia(
            "R5_DIVULGACAO_IA", plano_lc[:80],
            "Peça gerada por IA sem divulgação legível (AI Act art. 50) — embute "
            f"a frase canónica: {DIVULGACAO_IA!r}",
        )

    if peca.canal in _EXIGE_R6_PLENO:
        r6 = validar_alerta(
            plano, url_fonte=peca.url_fonte or "", excerto=peca.excerto or ""
        )
        for motivo in r6.motivos:
            _bloqueia("R6_GROUNDING", motivo, motivo)

    if peca.canal in _EXIGE_R7 and not _RE_R7_DISCLAIMER.search(plano_lc):
        _bloqueia(
            "R7_DISCLAIMER", plano_lc[:80],
            "Falta o disclaimer 'informação, não aconselhamento jurídico'.",
        )

    if peca.canal in _EXIGE_R8:
        if not peca.tem_optout_carimbado and not _RE_R8_OPTOUT.search(plano_lc):
            _bloqueia(
                "R8_OPTOUT", plano_lc[:80],
                "Falta o opt-out 1-clique (checkal.pt/remover) e o seam não o "
                "carimba (tem_optout_carimbado=False).",
            )

    if peca.canal in _EXIGE_R9 and not _RE_R9_IDENTIFICACAO.search(plano_lc):
        _bloqueia(
            "R9_IDENTIFICACAO", plano_lc[:80],
            "Falta a identificação legal do remetente (Cosmic Oasis, Lda.) no cold.",
        )

    aprovado = not any(v.severidade is Severidade.BLOQUEIA for v in violacoes)
    return ResultadoLint(aprovado=aprovado, violacoes=violacoes)
