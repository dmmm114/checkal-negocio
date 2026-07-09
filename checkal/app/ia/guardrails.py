"""Guardrails anti-atividade-reservada dos alertas do CheckAL — camada 2-bis.

Contexto legal (LEGAL-PARECER-DECISOES.md §7, Lei 10/2024): a **consulta jurídica** é
atividade **reservada** a advogados/solicitadores. Concluir juridicamente pela situação
concreta de um cliente ("o teu AL está em incumprimento", "tens de regularizar") é
*procuradoria ilícita* — crime. A 2.ª opinião jurídica avisou que um **template correto
não impede** o modelo (Sonnet) de **derivar** para linguagem prescritiva num caso
concreto; por isso a defesa não pode ser só o prompt (camada 1) — precisa de um **detetor
programático** que confere o texto gerado ANTES de sair, à imagem da rede anti-alucinação
(:mod:`app.ia.validacao`).

Contrato::

    validar_nao_prescritivo(texto_alerta) -> ResultadoValidacao

Função **pura**, determinística e **conservadora** (na dúvida REPROVA — a rejeição só faz
o alerta regenerar e, persistindo, cair no formato manual de recurso, que é factual e
seguro; nunca deixa sair um alerta prescritivo).

As TRÊS distinções que o produto tem de respeitar (do consultor):

* **Facto vs conselho.** Monitorizar estado/seguro/publicação e CITAR a fonte = informação
  (OK). Concluir juridicamente pela situação do cliente = reservado (PROIBIDO).
* **Sinalização genérica vs aplicação individualizada.** "Foi publicado Y, que abrange
  estabelecimentos com Z; o teu tem Z; consulta a fonte/um profissional" = OK. "Face a Y,
  o teu **tem de** fazer W" = reservado.
* **Encaminhamento, não prescrição.** "Recomendamos que verifiques X" só é seguro se X = a
  fonte oficial ou um profissional; nunca um ato jurídico concreto.

O detetor incide sobre o **texto do ALERTA dirigido ao cliente**, não sobre o **excerto
citado da fonte**: um excerto do regulamento pode conter "tem de" e é legítimo citá-lo.
Por isso os **trechos entre aspas** («…», "…", "…") — que são citações da fonte — são
**removidos antes** da varredura. O que fica é a voz própria do alerta; é aí que uma
conclusão jurídica imperativa/individualizada é reservada.

🧯 VIÉS INVIOLÁVEL: **nunca** um falso ``válido`` perante uma conclusão jurídica
individualizada. A lista de padrões é **curada e conservadora** (alargar a deteção é
sempre seguro — só gera MAIS rejeições → formato manual —, nunca um falso "válido"). Não
reprova linguagem **informativa/condicional** ("pode afetar", "verifica", "se aplicável",
"consulta a fonte/um profissional"), que é o lado seguro.
"""
from __future__ import annotations

import re

from app.ia.validacao import ResultadoValidacao

__all__ = ["validar_nao_prescritivo", "GUARDRAILS_VERSAO"]

# Versão do detetor — parte do dossier de defesa (templates versionados + guardrails +
# disclaimers). Registável/logável a par de :data:`app.ia.alerta.ALERTA_TEMPLATE_VERSAO`.
GUARDRAILS_VERSAO = "2026-07-09"


# ==========================================================================
#  Citações da fonte — removidas antes da varredura
# ==========================================================================
# Trechos entre aspas são CITAÇÕES do documento-fonte (ex.: o excerto do regulamento pode
# dizer "cada titular tem de averbar o seguro"). Citar a fonte é informação (lado seguro),
# não a conclusão jurídica do CheckAL — por isso não é reprovado. Removem-se «…», aspas
# curvas "…" e aspas retas "…". As plicas simples ficam de fora (risco de apóstrofo/contração).
_RE_CITACAO = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")


# ==========================================================================
#  Léxico de atos jurídicos concretos (o que NÃO se pode prescrever ao cliente)
# ==========================================================================
# "tens de <ato>" é reservado; "tens de verificar/consultar/ler" (encaminhamento) é seguro
# — por isso verificar/consultar/confirmar/ler NÃO constam desta lista. Os radicais cobrem
# infinitivo e conjugações (gated sempre por um modal pessoal, que já denota prescrição).
_ATO = (
    r"(?:regulariz|legaliz|altera|corrig|cess[ae]|suspend|encerr|cancel|averb|"
    r"adapt|comunic|declar|regist|renov|requer|submet|paga|retir|remov|desativ|"
    r"sana|resolv|sane[ai])\w*"
)

# Prefixos de OBRIGAÇÃO/NECESSIDADE/DEVER dirigidos ao cliente (todos IMPERATIVOS ou de
# certeza — NUNCA condicionais). Gated sempre por um _ATO (ato jurídico concreto): assim
# "<obrigação> verificar/consultar/rever/ler" (encaminhamento) fica de fora (esses verbos
# não estão em _ATO), mas "<obrigação> regularizar/legalizar/…" é reservado. Inclui:
# presente ("tens de", "tem de", "têm de"), FUTURO ("terás de", "terá de", "terão de"),
# perifrástico ("vais ter de", "vai ter de"), obrigação ("és/está/fica obrigado a"),
# NECESSIDADE de certeza ("é/será necessário" — **não** "poderá/pode ser necessário", que é
# condicional e seguro), NECESSIDADE pessoal ("precisas de") e DEVER ("deves", "deverás").
_MODAL_OBRIG = (
    r"(?:"
    r"ten?s\s+(?:de|que)|tem\s+(?:de|que)|t[êe]m\s+(?:de|que)|"          # tens/tem/têm de/que
    r"ter[áa]s?\s+(?:de|que)|ter[ãa]o\s+(?:de|que)|"                     # terá(s)/terão de/que
    r"vais?\s+ter\s+(?:de|que)|v[ãa]o\s+ter\s+(?:de|que)|"               # vais/vai/vão ter de
    r"[ée]s?\s+obrigad[oa]s?\s+a|s[ãa]o\s+obrigad[oa]s?\s+a|"            # és/é/são obrigado a
    r"est[áa]s?\s+obrigad[oa]s?\s+a|est[ãa]o\s+obrigad[oa]s?\s+a|"       # estás/está/estão obrigado a
    r"fica[sm]?\s+obrigad[oa]s?\s+a|"                                    # fica/ficas/ficam obrigado a
    r"ser[áa]\s+necess[áa]rio|[ée]\s+necess[áa]rio|"                     # será/é necessário (certeza)
    r"precisa[sm]?\s+de|"                                                # precisas/precisa/precisam de
    r"deve[sm]?\b|dever[áa]s?\b|dever[ãa]o\b"                            # deves/deve/devem/deverás/deverá/deverão
    r")"
)


# ==========================================================================
#  Regras curadas — cada uma deteta uma CONCLUSÃO JURÍDICA imperativa/individualizada
# ==========================================================================
# Trabalham sobre o texto em minúsculas (acentos preservados). Classes de caracteres
# toleram pequenas variações ("está/esta", "não/nao", "é/e" onde não colide). O cliente é
# tratado por "tu"/"o teu …" (voz do produto) — a norma citada usa 3.ª pessoa impessoal,
# pelo que ancorar na 2.ª pessoa/"o teu …" separa naturalmente o individualizado do genérico.
_REGRAS: list[tuple[re.Pattern[str], str]] = [
    # 1. Incumprimento afirmado (estado jurídico individual).
    (
        re.compile(r"est[áa]s?\s+em\s+(?:situa[çc][ãa]o\s+de\s+)?incumprimento"),
        "afirma que o cliente/AL está em incumprimento",
    ),
    (
        re.compile(r"(?:o\s+teu|a\s+tua)\s+\w+(?:\s+\w+){0,2}\s+em\s+incumprimento"),
        "afirma incumprimento do AL do cliente",
    ),
    # 1-bis. Verbo reflexivo/ligação ("encontra-se em incumprimento", "fica em situação
    # irregular") — a 3.ª pessoa reflexiva contorna a âncora "estás/o teu" das regras 1/2.
    (
        re.compile(
            r"(?:encontra\w*|fica\w*)[-\s]*se\s+em\s+"
            r"(?:situa[çc][ãa]o\s+de\s+)?(?:incumprimento|situa[çc][ãa]o\s+irregular)"
        ),
        "afirma que o AL do cliente está em incumprimento/irregular",
    ),
    # 2. Ilegal / irregular afirmado sobre o cliente.
    (
        re.compile(r"est[áa]s?\s+(?:em\s+situa[çc][ãa]o\s+)?(?:ilegal|irregular)"),
        "afirma que o cliente está ilegal/irregular",
    ),
    (
        re.compile(
            r"(?:o\s+teu|a\s+tua)\s+\w+(?:\s+\w+){0,2}\s+(?:é|e|est[áa])\s+"
            r"(?:ilegal|irregular)"
        ),
        "conclui que o AL do cliente é/está ilegal/irregular",
    ),
    (re.compile(r"\bé\s+(?:ilegal|irregular)\b"), "conclui ilegalidade/irregularidade"),
    (
        re.compile(r"\bfica[sm]?\s+(?:ilegal|irregular)\b"),
        "conclui que o cliente/AL fica ilegal/irregular",
    ),
    # 3. Não-conformidade concluída.
    (
        re.compile(
            r"n[ãa]o\s+est[áa]s?\s+(?:em\s+conformidade|conforme|regular|"
            r"regulariz\w*|legal)"
        ),
        "conclui que o cliente/AL não está conforme/regular",
    ),
    (
        re.compile(
            r"(?:o\s+teu|a\s+tua)\s+\w+(?:\s+\w+){0,2}\s+n[ãa]o\s+"
            r"(?:cumpre|est[áa]\s+conform\w*|est[áa]\s+regular\w*)"
        ),
        "conclui que o AL do cliente não cumpre/não está conforme",
    ),
    # 3-bis. "não se encontra conforme/regular/em conformidade" (reflexivo).
    (
        re.compile(
            r"n[ãa]o\s+se\s+encontra\s+(?:em\s+conformidade|conforme|regular)"
        ),
        "conclui que o cliente/AL não se encontra conforme/regular",
    ),
    # 4. "não cumpres/não cumpre".
    (re.compile(r"n[ãa]o\s+cumpres?\b"), "afirma que o cliente não cumpre"),
    # 5. "violas/viola".
    (re.compile(r"\bvi[oó]la[s]?\b"), "afirma que o cliente viola a norma"),
    # 6. Obrigação/necessidade/dever pessoal + ato jurídico concreto ("tens de / terás de /
    #    vais ter de / é necessário / precisas de / deves … regularizar/legalizar/…"). O
    #    ato tem de ser um _ATO (jurídico); "<modal> verificar/consultar/rever" fica de fora.
    (
        re.compile(_MODAL_OBRIG + r"(?:\s+\w+){0,4}\s+(?:" + _ATO + r")\b"),
        "prescreve um ato jurídico concreto ao cliente",
    ),
    # 7. Ameaça individualizada de sanção ("vais ser multado", "a tua coima").
    (
        re.compile(
            r"vais\s+(?:ser|ficar)\s+(?:multad[oa]s?|sancionad[oa]s?|"
            r"penalizad[oa]s?|coimad[oa]s?)"
        ),
        "ameaça o cliente com sanção",
    ),
    (
        re.compile(r"ser[áa]s\s+(?:multad[oa]s?|sancionad[oa]s?|penalizad[oa]s?)"),
        "ameaça o cliente com sanção",
    ),
    (
        re.compile(r"vais\s+(?:levar|apanhar|ter)\s+(?:uma\s+)?(?:coima|multa)"),
        "ameaça o cliente com coima/multa",
    ),
    (re.compile(r"\ba\s+tua\s+(?:coima|multa)\b"), "individualiza a coima/multa ao cliente"),
    # 8. Ameaça de risco individualizada ("arriscas uma coima", "arriscas uma sanção").
    (
        re.compile(
            r"arrisca[sm]?\s+(?:uma?\s+)?"
            r"(?:coima|multa|san[çc]\w*|contraordena\w*|penaliza\w*)"
        ),
        "ameaça o cliente com o risco de uma sanção",
    ),
]


# ==========================================================================
#  API pública
# ==========================================================================
def validar_nao_prescritivo(texto_alerta: str | None) -> ResultadoValidacao:
    """Reprova o alerta se contiver uma CONCLUSÃO JURÍDICA imperativa/individualizada.

    :param texto_alerta: o texto dirigido ao cliente (``None``/"" ⇒ nada a reprovar).
    :returns: :class:`app.ia.validacao.ResultadoValidacao`. ``valido`` é ``True`` só se
        nenhuma regra prescritiva disparar; os ``motivos`` descrevem o que foi detetado
        (``valores_orfaos`` fica sempre vazio — este detetor não é de *grounding*).

    Função **pura** (só regex), determinística e conservadora. Trechos entre aspas
    (citações da fonte) são removidos antes da varredura — ver o módulo.
    """
    bruto = (texto_alerta or "").lower()
    # Remove as citações da fonte (entre aspas) para não reprovar o excerto legítimo.
    texto = _RE_CITACAO.sub(" ", bruto)

    motivos: list[str] = []
    vistos: set[str] = set()
    for regex, descricao in _REGRAS:
        m = regex.search(texto)
        if m and descricao not in vistos:
            vistos.add(descricao)
            trecho = " ".join(m.group(0).split())
            motivos.append(f"Linguagem prescritiva/reservada — {descricao}: {trecho!r}.")

    return ResultadoValidacao(valido=not motivos, motivos=motivos, valores_orfaos=[])
