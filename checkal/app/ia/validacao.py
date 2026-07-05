"""Rede de segurança anti-alucinação do CheckAL — validação programática do alerta.

É a **camada 2** das três camadas anti-alucinação (AUTOMACAO.md §3 / SPEC-IA §5): a
IA (Sonnet) redige o alerta a partir de um excerto do documento; **este módulo confere
o texto gerado antes de o deixar sair**. Um alerta jurídico com uma coima ou um prazo
inventados é responsabilidade real — por isso a validação é uma função **pura**,
determinística e conservadora, testada à exaustão (`tests/test_ia_validacao.py`).

Contrato::

    validar_alerta(texto_alerta, *, url_fonte, excerto) -> ResultadoValidacao

Duas regras, ambas de *grounding* (o alerta não pode afirmar nada que a fonte não
sustente):

1. **Citação da fonte.** A `url_fonte` TEM de constar literalmente do `texto_alerta`.
   Sem fonte citada não há alerta — cai a validação.
2. **Sem valores inventados.** Todo o **valor monetário** (€/euros — coimas, taxas) e
   toda a **data/prazo** mencionados no `texto_alerta` TÊM de existir no `excerto`. A
   comparação normaliza os formatos portugueses (``1.500 €``, ``2 500,00€``,
   ``1500 euros`` → o mesmo montante; ``15/06/2026`` ≡ ``15 de junho de 2026``;
   ``junho de 2026``; ``30 dias``). Qualquer valor do alerta ausente do excerto é um
   **órfão** → inválido.

🧯 VIÉS INVIOLÁVEL: **nunca** um falso ``válido`` quando há um valor órfão. Em caso de
ambiguidade a função reprova (o pipeline regenera e, à 2.ª falha, cai no formato manual
de recurso — SPEC-IA §5.3), nunca deixa passar. O grounding é assimétrico de propósito:
o alerta pode ser **menos** específico do que a fonte (dizer "junho de 2026" quando a
fonte diz "15 de junho de 2026" é seguro), mas **nunca mais** específico (inventar o
dia é reprovado).

Limitações conhecidas (a refinar contra amostra real da Parte H — SPEC-IA §9.6):
montantes escritos por extenso ("dois mil e quinhentos euros") não são apanhados (não
têm dígitos); a validação incide sobre valores **numéricos**. Números que são meros
identificadores (``Regulamento n.º 927/2025``, ``artigo 5.º``) não são valores e não
são exigidos no excerto.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

__all__ = ["ResultadoValidacao", "validar_alerta"]


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class ResultadoValidacao:
    """Veredicto da validação de um alerta (imutável).

    :param valido: ``True`` só se a fonte for citada **e** não houver valores órfãos.
    :param motivos: razões humanas da reprovação (vazio se válido).
    :param valores_orfaos: os tokens de valor do alerta sem correspondência no excerto,
        pela ordem de aparição e sem duplicados (vazio se válido).
    """

    valido: bool
    motivos: list[str] = field(default_factory=list)
    valores_orfaos: list[str] = field(default_factory=list)


# ==========================================================================
#  Léxico e padrões (todos PT-PT)
# ==========================================================================
# Separador de milhares admitido: ponto, espaço normal, espaço fino/duro (NBSP/NNBSP).
_ESP = r"[.   ]"
# Corpo de um número PT: dígitos + grupos de milhares opcionais + decimais por vírgula.
_AMT = rf"\d+(?:{_ESP}\d{{3}})*(?:,\d+)?"
# Âncora de moeda: símbolo €, "euro(s)", a abreviatura oficial "EUR"/"eur" (fronteira de
# palavra para não colar a "Europa"…) e o cifrão. **Ampliar aqui é sempre seguro** — mais
# âncoras só podem gerar MAIS órfãos (reprova), nunca um falso "válido". Uma coima
# alucinada escrita "9 999 EUR" / "9999$" tem de ser apanhada tal como "9 999 €".
_MOEDA = r"(?:€|euros?|eur\b|\$)"
# Palavra de magnitude entre o montante e a moeda ("5 milhões de euros", "3 mil €"): o
# número-mantissa é o que se fundamenta (o excerto sustenta o "5" de "5 milhões"?).
_MAG = r"(?:\s+(?:mil|milh(?:[oõ]es|[aã]o)|milhar(?:es)?)(?:\s+de)?)?"
# Ligações de intervalo: travessão/hífen colados OU conjunções isoladas por espaços.
_LIGA = r"(?:\s*[–—-]\s*|\s+(?:a|até|e|ou)\s+)"

# Expressão monetária: € antes OU depois do(s) montante(s); apanha intervalos ("2.500 a
# 4.000 €") e magnitudes ("5 milhões de euros"). O símbolo/palavra âncora é obrigatório —
# um número solto NÃO é monetário.
_RE_MONETARIO = re.compile(
    rf"{_MOEDA}\s*{_AMT}(?:{_LIGA}{_AMT})*{_MAG}"
    rf"|{_AMT}(?:{_LIGA}{_AMT})*{_MAG}\s*{_MOEDA}",
    re.IGNORECASE,
)
# Percentagens ("taxa de 15%", "15 por cento"): uma taxa municipal alucinada é tão nociva
# como uma coima inventada → o número afirmado TEM de existir no excerto (como um montante).
_RE_PERCENTAGEM = re.compile(rf"({_AMT})\s*(?:%|por\s+cento)", re.IGNORECASE)
# Número PT isolado — usado para (a) extrair cada montante dentro de uma expressão
# monetária e (b) recensear TODOS os números do excerto (conjunto de fundamentação).
_RE_NUMERO = re.compile(_AMT)

# Data numérica DD/MM/AAAA, DD-MM-AAAA ou DD.MM.AAAA. O "." é aceite como separador de
# data porque a forma dia(1-2)·mês(1-2)·ano(4) NÃO colide com o milhar "2.500" (grupos de
# exatamente 3 dígitos): "15.03.2026" é data; "2.500"/"40.000" não casam este padrão.
# Fronteiras (\d lookaround) impedem colar a dígitos vizinhos.
_RE_DATA_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")
# Data por extenso: "15 de junho de 2026" (o mês é validado contra _MESES).
_RE_DATA_ESCRITA = re.compile(
    r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})", re.IGNORECASE
)
# Mês/ano sem dia: "junho de 2026".
_RE_MES_ANO = re.compile(r"\b([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})", re.IGNORECASE)
# Prazo: número + unidade temporal (opcional "úteis" a seguir a "dias"). As unidades
# estão por ordem de comprimento decrescente ("meses" antes de "mes") para o token
# bruto capturado ser o completo, e `\b` evita colar a palavras maiores.
_RE_PRAZO = re.compile(
    r"(\d+)\s+(dias?|semanas?|meses|m[êe]s|anos?|horas?)\b(?:\s+úteis)?",
    re.IGNORECASE,
)
# URLs — removidas antes da extração de valores para os seus dígitos (datas/nºs no
# caminho) não contarem como valores afirmados pelo alerta.
_RE_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
    "dezembro": 12,
}
# Normalização de unidade de prazo para a sua base (após remover acentos).
_UNIDADES = {
    "dia": "dias", "dias": "dias",
    "semana": "semanas", "semanas": "semanas",
    "mes": "meses", "meses": "meses",
    "ano": "anos", "anos": "anos",
    "hora": "horas", "horas": "horas",
}


# ==========================================================================
#  Auxiliares puros
# ==========================================================================
def _sem_acentos(texto: str) -> str:
    """Minúsculas sem diacríticos ("março" → "marco", "até" → "ate")."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _para_decimal(bruto: str) -> Decimal | None:
    """Normaliza um número PT para :class:`Decimal` (milhares fora, vírgula → ponto).

    ``"2 500,00"`` → ``Decimal('2500.00')`` ; ``"1.500"`` → ``Decimal('1500')``. Assim
    o mesmo montante escrito de formas diferentes compara como igual, mas ``40.000`` e
    ``4.000`` continuam distintos. Devolve ``None`` se não for parseável.
    """
    limpo = re.sub(r"[.  \s]", "", bruto).replace(",", ".")
    if not limpo or limpo == ".":
        return None
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def _remover_urls(texto: str, url_fonte: str) -> str:
    """Devolve o texto sem a `url_fonte` nem quaisquer URLs (para extrair valores)."""
    if url_fonte:
        texto = texto.replace(url_fonte, " ")
    return _RE_URL.sub(" ", texto)


# Um "claim" é um valor afirmado pelo texto: (posição, token_bruto, (tipo, chave)).
# `tipo` ∈ {"moeda","data","mesano","prazo"}; `chave` é a forma normalizada comparável.
_Claim = tuple[int, str, tuple[str, object]]


def _extrair_claims(texto: str) -> list[_Claim]:
    """Extrai todos os valores afirmados (monetários, datas, mês/ano, prazos)."""
    claims: list[_Claim] = []

    # Montantes monetários (cada número dentro de uma expressão com €/euros).
    for m in _RE_MONETARIO.finditer(texto):
        base = m.start()
        for n in _RE_NUMERO.finditer(m.group(0)):
            val = _para_decimal(n.group(0))
            if val is not None:
                claims.append((base + n.start(), n.group(0), ("moeda", val)))

    # Datas por extenso primeiro (para não recontar o "mês de ano" que contêm).
    spans_data_escrita: list[tuple[int, int]] = []
    for m in _RE_DATA_ESCRITA.finditer(texto):
        mes = _MESES.get(_sem_acentos(m.group(2)))
        dia = int(m.group(1))
        if mes is None or not (1 <= dia <= 31):
            continue
        ano = int(m.group(3))
        claims.append((m.start(), m.group(0), ("data", (ano, mes, dia))))
        spans_data_escrita.append(m.span())

    # Datas numéricas DD/MM/AAAA.
    for m in _RE_DATA_NUM.finditer(texto):
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= dia <= 31 and 1 <= mes <= 12:
            claims.append((m.start(), m.group(0), ("data", (ano, mes, dia))))

    # Mês/ano sem dia (ignorando os que já estão dentro de uma data por extenso).
    for m in _RE_MES_ANO.finditer(texto):
        mes = _MESES.get(_sem_acentos(m.group(1)))
        if mes is None:
            continue
        if any(ini <= m.start() < fim for ini, fim in spans_data_escrita):
            continue
        claims.append((m.start(), m.group(0), ("mesano", (int(m.group(2)), mes))))

    # Prazos.
    for m in _RE_PRAZO.finditer(texto):
        unidade = _UNIDADES.get(_sem_acentos(m.group(2)))
        if unidade is None:
            continue
        claims.append((m.start(), m.group(0), ("prazo", (int(m.group(1)), unidade))))

    # Percentagens (fundamentadas contra os números do excerto, como os montantes).
    for m in _RE_PERCENTAGEM.finditer(texto):
        val = _para_decimal(m.group(1))
        if val is not None:
            claims.append((m.start(), m.group(0), ("percent", val)))

    return claims


def _fundamentacao(
    excerto: str,
) -> tuple[set[Decimal], set[tuple[int, int, int]], set[tuple[int, int]], set[tuple[int, str]]]:
    """Constrói os conjuntos de valores que o excerto sustenta.

    Devolve ``(numeros, datas_completas, meses_ano, prazos)``:
      - ``numeros``: TODOS os números do excerto (fundamentam montantes — a pergunta é
        "este número existe na fonte?", independentemente de ter € ao lado);
      - ``datas_completas``: ``{(ano, mes, dia)}`` das datas explícitas;
      - ``meses_ano``: ``{(ano, mes)}`` — dos mês/ano E do mês de cada data completa;
      - ``prazos``: ``{(numero, unidade)}``.
    """
    numeros: set[Decimal] = set()
    for n in _RE_NUMERO.finditer(excerto):
        val = _para_decimal(n.group(0))
        if val is not None:
            numeros.add(val)

    datas: set[tuple[int, int, int]] = set()
    meses: set[tuple[int, int]] = set()
    prazos: set[tuple[int, str]] = set()
    for _, _, (tipo, chave) in _extrair_claims(excerto):
        if tipo == "data":
            ano, mes, dia = chave  # type: ignore[misc]
            datas.add((ano, mes, dia))
            meses.add((ano, mes))
        elif tipo == "mesano":
            meses.add(chave)  # type: ignore[arg-type]
        elif tipo == "prazo":
            prazos.add(chave)  # type: ignore[arg-type]

    return numeros, datas, meses, prazos


def _fundamentado(tipo: str, chave: object, funds: tuple) -> bool:
    """Um valor do alerta está fundamentado no excerto?"""
    numeros, datas, meses, prazos = funds
    if tipo in ("moeda", "percent"):
        return chave in numeros
    if tipo == "data":
        return chave in datas
    if tipo == "mesano":
        return chave in meses
    if tipo == "prazo":
        return chave in prazos
    return False


# ==========================================================================
#  API pública
# ==========================================================================
def validar_alerta(
    texto_alerta: str | None, *, url_fonte: str, excerto: str
) -> ResultadoValidacao:
    """Valida um alerta gerado pela IA (grounding: fonte citada + valores ⊂ excerto).

    :param texto_alerta: o texto redigido pela IA (ou ``None``/"" — trata-se como sem
        fonte citada e sem valores).
    :param url_fonte: a URL do documento-fonte, que TEM de constar do `texto_alerta`.
    :param excerto: o excerto do documento em que o alerta se baseia — a única fonte de
        verdade para montantes/datas/prazos.
    :returns: :class:`ResultadoValidacao`. ``valido`` só é ``True`` se a fonte for
        citada e nenhum valor for órfão.

    Função **pura**: sem rede, sem estado, determinística. Ver o módulo para o viés
    conservador (na dúvida, reprova).
    """
    texto = texto_alerta or ""
    url = (url_fonte or "").strip()

    motivos: list[str] = []

    # Regra 1 — a fonte tem de estar citada.
    if not url or url not in texto:
        motivos.append(
            "A fonte não é citada: a url do documento não consta do texto do alerta."
        )

    # Regra 2 — nenhum valor pode ser inventado (fora do excerto).
    funds = _fundamentacao(excerto or "")
    texto_valores = _remover_urls(texto, url)
    orfaos: list[str] = []
    for _, bruto, (tipo, chave) in sorted(
        _extrair_claims(texto_valores), key=lambda c: c[0]
    ):
        if not _fundamentado(tipo, chave, funds):
            orfaos.append(bruto)

    # Dedup preservando a ordem de aparição.
    orfaos = list(dict.fromkeys(orfaos))
    for bruto in orfaos:
        motivos.append(f"Valor sem correspondência no excerto: {bruto!r}.")

    return ResultadoValidacao(
        valido=not motivos,
        motivos=motivos,
        valores_orfaos=orfaos,
    )
