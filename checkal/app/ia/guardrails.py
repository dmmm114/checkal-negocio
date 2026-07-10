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

As distinções que o produto tem de respeitar (do consultor):

* **Facto vs conselho.** Monitorizar estado/seguro/publicação e CITAR a fonte = informação
  (OK). Concluir juridicamente pela situação do cliente = reservado (PROIBIDO).
* **Sinalização genérica vs aplicação individualizada.** "Foi publicado Y, que abrange
  estabelecimentos com Z; o teu tem Z; consulta a fonte/um profissional" = OK. "Face a Y,
  o teu **tem de** fazer W" = reservado.
* **Encaminhamento, não prescrição.** "Recomendamos que verifiques X" só é seguro se X = a
  fonte oficial ou um profissional; nunca um ato jurídico concreto.
* **FACTOS COM DONO (regra do consultor jurídico, 2026-07-09).** Um **prazo**, **valor** ou
  **dever** é sempre **ATRIBUÍDO à FONTE** ("segundo o regulamento, os titulares abrangidos
  **dispõem de** um prazo de 30 dias para **efetuar** a comunicação"), **nunca dirigido ao
  CLIENTE** na 2.ª pessoa ("há um prazo de 30 dias, a contar de 15/06/2026, **para
  efetuares** a comunicação" / "**tens** 30 dias **para** comunicar"). Dirigir a 2.ª pessoa
  um ato jurídico — pelo **infinitivo pessoal** ("para **efetuares/regularizares/…**") ou
  por um **prazo com dono** ("tens N dias para …") — é aplicação individualizada, logo
  reservado. O par seguro usa o **infinitivo IMPESSOAL** ("para efetuar", "-ar"/"-er"/"-ir"
  sem o "-es" da 2.ª pessoa) e atribui o prazo ao documento. Corolário: **valores** só
  entram com **âncora direta no texto citado** (a coima é "a indicada no regulamento", não
  um número que o alerta afirme por si — as molduras diferem entre singular/coletiva).

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

DEFESA EM CAMADAS (honesta — este filtro NÃO é um regex perfeito)
=================================================================
Nenhum regex apanha **todas** as conjugações do português; a defesa real contra a
procuradoria ilícita é a **soma de quatro camadas** + a **supervisão humana**, não este
módulo isolado:

* **Camada 1 — template restritivo.** O prompt/template instrui o modelo a escrever
  informação factual atribuída à fonte, condicional e com encaminhamento (nunca conclusão
  jurídica individualizada). Reduz a probabilidade de o texto derivar; não a elimina.
* **Camada 2 — este filtro programático** (:func:`validar_nao_prescritivo`). Confere o
  texto gerado ANTES de sair e apanha os padrões prescritivos/individualizados **mais
  comuns**, a saber: incumprimento/ilegalidade/irregularidade afirmados sobre o cliente
  ou o AL (inclusive por verbo reflexivo "encontra-se/fica em incumprimento"); "não
  cumpres/violas"; **obrigação/necessidade/dever pessoal + ato jurídico** ("tens de /
  terás de / vais ter de / é necessário / precisas de / deves … regularizar/legalizar/…");
  **conjuntivo impessoal 2.ª pessoa** ("é necessário/preciso/obrigatório que regularizes/
  comuniques/…", lista fechada); **obrigação clítica** ("compete-te/cabe-te/incumbe-te
  <ato>"); ameaça individualizada de sanção ("vais ser multado", "a tua coima",
  "arriscas uma coima"); e **factos com dono** dirigidos ao cliente — infinitivo pessoal
  ("para efetuares/regularizares/…") e prazo com dono ("tens/terás/dispões de N dias
  para <ato>"). As **citações da fonte** entre aspas são removidas antes da varredura.
* **Camada 3 — formato factual de recurso.** Quando um alerta é reprovado (aqui) e a
  regeneração persiste, cai num formato **manual/factual** — atribuído à fonte, sem
  conclusão jurídica —, que é seguro por construção.
* **Camada 4 — amostragem humana periódica.** Revisão manual de uma amostra dos alertas
  emitidos, para apanhar o que escapou às camadas 1–3 e realimentar as regras/o template.

RESIDUAIS CONHECIDOS (documentados, não fechados aqui)
------------------------------------------------------
* **Imperativo nu de um ato jurídico** — "Regulariza a tua situação", "Comunica já à
  câmara". **NÃO** é fechado por regex: a forma imperativa da 2.ª pessoa colide com a
  **3.ª pessoa descritiva** do mesmo verbo ("o município **regulariza** os registos", "a
  plataforma **atualiza** os dados") — apanhá-la geraria **falsos positivos** de alto
  volume sobre texto legítimo. Fica coberto pelas **camadas 1** (o template não manda no
  imperativo), **3** (formato de recurso) e **4** (amostragem humana). Risco de FP de
  fechar por regex: **alto** → decisão deliberada de o deixar às outras camadas.
* Princípio geral: qualquer conjugação nova que o modelo invente e que escape às regras
  curadas é apanhada, em última instância, pela **soma das camadas + a supervisão
  humana** — não pela pretensão de um regex exaustivo.
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
    r"efetu|apresenta|sana|resolv|sane[ai])\w*"
)

# ==========================================================================
#  FACTOS COM DONO — o ato dirigido ao CLIENTE (2.ª pessoa)
# ==========================================================================
# Radicais dos MESMOS atos, SEM o sufixo livre, para montar a 2.ª pessoa do **infinitivo
# pessoal** ("efetuar**es**", "comunicar**es**", "corrigir**es**", "resolver**es**"):
# radical + (ar|er|ir) + "es". Essa desinência "-es" é a marca da 2.ª pessoa (é o que
# distingue o dirigido-ao-cliente do impessoal/atribuído-à-fonte "efetuar/comunicar"). A
# mesma forma serve o conjuntivo futuro ("se regularizares…"), também dirigido ao cliente:
# a sobre-deteção é o lado seguro. O ENCAMINHAMENTO (verific/consult/confirm/rev/ler) fica
# FORA de propósito — "para confirmares/verificares" continua seguro.
_ATO_RAIZ = (
    r"(?:regulariz|legaliz|alter|corrig|cess|suspend|encerr|cancel|averb|adapt|"
    r"comunic|declar|regist|renov|requer|submet|pag|retir|remov|desativ|efetu|"
    r"san|resolv|apresent)"
)
# Infinitivo PESSOAL da 2.ª pessoa singular de um ato: "(para )efetuares/comunicares/…".
_ATO_PESSOAL = _ATO_RAIZ + r"(?:ar|er|ir)es"
# Unidade de prazo, para o "prazo com dono" ("tens N dias/meses para <ato>").
_UNIDADE_PRAZO = r"(?:dias?|semanas?|meses|m[êe]s|anos?|horas?)"

# ==========================================================================
#  CONJUNTIVO IMPESSOAL — "é necessário/preciso/obrigatório QUE <ato>" (2.ª pessoa)
# ==========================================================================
# LISTA FECHADA das formas do **presente do conjuntivo, 2.ª pessoa do singular** dos atos
# jurídicos ("que TU regularizes/comuniques/…"). É uma lista, não um radical + "\w*",
# porque (a) a desinência "-es/-as" é a marca INEQUÍVOCA da 2.ª pessoa (o 3.º-pessoa faz
# "-e/-a": "que o município comunique/regularize" — dever de TERCEIRO, lado seguro), e
# (b) muitos destes verbos mudam de radical no conjuntivo (comunicar→comuni**qu**es,
# pagar→pa**gu**es, corrigir→corri**j**as) e por isso NÃO seriam apanhados pelos radicais
# de :data:`_ATO`. Baixo risco de FP: nenhuma 3.ª pessoa termina em "-es/-as" da 2.ª p.
_ATO_CONJUNTIVO_2P = (
    r"(?:comuniques|regularizes|alteres|corrijas|resolvas|sanes|legalizes|"
    r"apresentes|averbes|ceses|cesses|pagues|efetues)"
)
# Modais IMPESSOAIS de necessidade/obrigação seguidos de "que" ("é necessário que", "é
# preciso que", "é obrigatório que", "torna-se necessário que"). Só disparam com um verbo
# de :data:`_ATO_CONJUNTIVO_2P` a seguir — logo a 3.ª pessoa ("… que o município
# comunique") nunca casa (o conjuntivo "-e" não está na lista fechada).
_MODAL_IMPESSOAL_QUE = (
    r"(?:[ée]\s+necess[áa]rio|[ée]\s+preciso|[ée]\s+obrigat[óo]rio|"
    r"torna-se\s+necess[áa]rio)\s+que"
)

# ==========================================================================
#  OBRIGAÇÃO IMPESSOAL CLÍTICA — "compete-te / cabe-te / incumbe-te <ato>"
# ==========================================================================
# O clítico "-te" é a 2.ª pessoa: o dever fica ATRIBUÍDO AO CLIENTE. O espelho seguro é a
# 3.ª pessoa a um terceiro ("compete AO município regularizar", "cabe À câmara comunicar"),
# que não traz o "-te" e por isso não casa. Gated por _ATO: "compete-te verificar/consultar"
# (encaminhamento) fica de fora.
_OBRIG_CLITICA = r"(?:compete|cabe|incumbe)-te"

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
    #    O salto entre o modal e o ato **não atravessa "que"**: assim "é necessário QUE o
    #    município regularize" (dever de TERCEIRO, 3.ª pessoa) já não é apanhado por engano
    #    — a construção "modal + que + <2.ª pessoa>" fica a cargo da regra 6-bis (conjuntivo
    #    de lista fechada), que distingue a 2.ª da 3.ª pessoa pela desinência.
    (
        re.compile(_MODAL_OBRIG + r"(?:\s+(?!que\b)\w+){0,4}\s+(?:" + _ATO + r")\b"),
        "prescreve um ato jurídico concreto ao cliente",
    ),
    # 6-bis. CONJUNTIVO IMPESSOAL dirigido ao cliente: "é necessário/preciso/obrigatório
    #    que <ato no conjuntivo 2.ª pessoa>" ("… que regularizes/comuniques/…"). A lista
    #    fechada _ATO_CONJUNTIVO_2P só tem formas da 2.ª pessoa ("-es/-as"); a 3.ª pessoa
    #    ("… que o município comunique/regularize") NÃO casa → sem falso positivo.
    (
        re.compile(
            _MODAL_IMPESSOAL_QUE + r"(?:\s+\w+){0,2}\s+" + _ATO_CONJUNTIVO_2P + r"\b"
        ),
        "prescreve um ato jurídico ao cliente (conjuntivo impessoal, 2.ª pessoa)",
    ),
    # 6-ter. OBRIGAÇÃO IMPESSOAL CLÍTICA: "compete-te/cabe-te/incumbe-te <ato jurídico>".
    #    O clítico "-te" dirige o dever ao cliente; a 3.ª pessoa ("compete AO município
    #    regularizar") não traz "-te" e fica de fora. Gated por _ATO (encaminhamento fora).
    (
        re.compile(_OBRIG_CLITICA + r"(?:\s+\w+){0,4}\s+(?:" + _ATO + r")\b"),
        "atribui ao cliente (clítico -te) o dever de praticar um ato jurídico",
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
    # 9. FACTOS COM DONO — infinitivo PESSOAL da 2.ª pessoa a mandar o cliente praticar um
    #    ato ("para efetuares a comunicação", "para regularizares", "a contar de {data} …
    #    para efetuares"). O prazo/dever fica DIRIGIDO ao cliente em vez de ATRIBUÍDO à
    #    fonte. O par seguro usa o infinitivo IMPESSOAL ("os titulares dispõem de 30 dias
    #    para efetuar a comunicação"), que NÃO casa — não traz a desinência "-es".
    (
        re.compile(r"\b" + _ATO_PESSOAL + r"\b"),
        "dirige ao cliente (2.ª pessoa) a prática de um ato jurídico (infinitivo pessoal)",
    ),
    # 10. FACTOS COM DONO — prazo com dono: um verbo de POSSE/DISPOSIÇÃO do prazo na 2.ª/3.ª
    #     pessoa ("tens/tem/têm", o FUTURO "terás/terá/terão" — imperativo velado — e "dispões",
    #     2.ª p. de dispor, o espelho perigoso do seguro "os titulares DISPÕEM de …") + N
    #     <unidade> + "para <ato>". Aceita o conector opcional "de"/"até" e a interposição
    #     "(um/o) prazo de" ("tens um prazo de 30 dias para comunicar"). O prazo passa a
    #     pertencer ao destinatário; ATRIBUÍDO à fonte seria "há/existe um prazo de N dias …"
    #     ou "os titulares dispõem de N dias …" (verbos "há"/"dispõem" fora desta lista → seguro).
    (
        re.compile(
            r"(?:\bten?s\b|\btem\b|\bt[êe]m\b|\bter[áa]s?\b|\bter[ãa]o\b|\bdisp[õo]es\b)"
            r"\s+(?:de\s+|at[ée]\s+|(?:um|o)\s+prazo\s+de\s+)?\d+\s+"
            + _UNIDADE_PRAZO
            + r"\s+para\s+(?:\w+\s+){0,3}(?:" + _ATO + r")\b"
        ),
        "atribui ao cliente um prazo para praticar um ato (prazo com dono)",
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
