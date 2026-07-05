"""Relatório inicial de onboarding do CheckAL (FDS 3, SPEC-FDS3 §relatorio).

Fronteira do módulo: dado um **cliente** (assinante) e o **detalhe** individual do
seu registo RNAL (:class:`app.rnal.detalhe.DetalheRegisto`), compõe o relatório de
boas-vindas — uma estrutura de dados factual, PT-PT, **sem inventar** — e rende-o em
PDF (fpdf2). Não fala com a rede nem com a BD: só transforma dados que lhe são dados.
O onboarding (FDS 3) é quem obtém o detalhe, persiste, chama este módulo e envia.

As quatro secções canónicas (SPEC-FDS3 §relatorio):
  1. **Estado do registo RNAL** — a partir de `detalhe.estado`.
  2. **Seguro de responsabilidade civil** — a partir do bloco de seguro do detalhe.
  3. **Área de contenção do concelho** — `contencao` (o FDS 4 preenche; tolera `None`).
  4. **Regulamentos municipais** — `regulamentos` (o FDS 4 preenche; tolera vazio).

Disciplina inviolável:
  - **G4 (SPEC-FDS3):** o relatório **nunca afirma "cancelado"** a partir do detalhe. O
    detalhe só afirma `ativo`/`nao_encontrado`; tudo o resto é `indeterminado`. Para
    `nao_encontrado`/`indeterminado` a copy é uma **ressalva de confirmação** ("requer
    confirmação"), jamais uma afirmação de cancelamento/suspensão.
  - **Sem inventar:** quando `contencao`/`regulamentos` vêm vazios (FDS 4 ainda não
    preencheu), a copy diz que a monitorização fica ativa e que ainda nada há a assinalar
    **neste relatório** — nunca afirma taxativamente que "não existe" contenção nem
    regulamento (não temos essa certeza nesta fase).

Render em PDF: usa o *core font* Helvetica (sem dependência de fontes externas). O core
font codifica em latin-1, que cobre o português acentuado; :func:`_pdf_safe` sanea os
poucos caracteres fora de latin-1 (travessões, aspas curvas, símbolos) para o render
nunca rebentar com texto real.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from fpdf import FPDF

from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    DetalheRegisto,
)

__all__ = [
    "SecaoRelatorio",
    "RelatorioInicial",
    "SECAO_ESTADO",
    "SECAO_SEGURO",
    "SECAO_CONTENCAO",
    "SECAO_REGULAMENTOS",
    "TITULO_RELATORIO",
    "gerar_relatorio_inicial",
    "render_pdf",
]

# Títulos canónicos das secções (constantes para o onboarding e os testes ancorarem).
SECAO_ESTADO = "Estado do registo RNAL"
SECAO_SEGURO = "Seguro de responsabilidade civil"
SECAO_CONTENCAO = "Área de contenção do concelho"
SECAO_REGULAMENTOS = "Regulamentos municipais"

TITULO_RELATORIO = "Relatório inicial CheckAL"


# ==========================================================================
#  Estrutura de dados (imutável)
# ==========================================================================
@dataclass(frozen=True)
class SecaoRelatorio:
    """Uma secção do relatório: título + parágrafos de copy (todos não vazios)."""

    titulo: str
    paragrafos: tuple[str, ...]


@dataclass(frozen=True)
class RelatorioInicial:
    """O relatório inicial de onboarding, pronto a renderizar ou a inspecionar.

    `cabecalho` são as linhas de identificação (AL, registo, concelho, cliente, data);
    `secoes` são as quatro secções canónicas. Puramente dados — sem I/O.
    """

    nr_registo: int
    nome_alojamento: str | None
    concelho: str | None
    cliente_nome: str | None
    gerado_em: date
    cabecalho: tuple[str, ...]
    secoes: tuple[SecaoRelatorio, ...]
    titulo: str = TITULO_RELATORIO

    def texto(self) -> str:
        """Todo o texto do relatório numa string (título + cabeçalho + secções).

        Útil para o corpo do email de boas-vindas e para os testes ancorarem em copy.
        """
        linhas: list[str] = [self.titulo, *self.cabecalho]
        for secao in self.secoes:
            linhas.append(secao.titulo)
            linhas.extend(secao.paragrafos)
        return "\n".join(linhas)


# ==========================================================================
#  Auxiliares de leitura (duck-typed — não exige ORM/BD)
# ==========================================================================
def _iso(d: date | None) -> str | None:
    """Data em ISO `YYYY-MM-DD`, ou `None` se ausente."""
    return d.isoformat() if d is not None else None


def _registo_correspondente(cliente: Any, nr_registo: int) -> Any | None:
    """O registo do `cliente` cujo `nr_registo` casa com o do detalhe (ou `None`).

    Lê `cliente.registos` de forma defensiva (pode não existir ou vir vazio). Não toca
    a BD: percorre a coleção já carregada — dá jeito para a copy (nome do AL, concelho).
    """
    for registo in (getattr(cliente, "registos", None) or ()):
        if getattr(registo, "nr_registo", None) == nr_registo:
            return registo
    return None


def _texto_contencao(contencao: Any) -> str | None:
    """Normaliza `contencao` (None | str | objeto com `.descricao`) para texto, ou `None`."""
    if contencao is None:
        return None
    if isinstance(contencao, str):
        return contencao.strip() or None
    descricao = getattr(contencao, "descricao", None)
    if descricao:
        return str(descricao).strip() or None
    texto = str(contencao).strip()
    return texto or None


def _linha_regulamento(reg: Any) -> str | None:
    """Uma linha por regulamento: string tal-qual, ou o `.titulo` do objeto."""
    if isinstance(reg, str):
        return reg.strip() or None
    titulo = getattr(reg, "titulo", None)
    if titulo:
        return str(titulo).strip() or None
    texto = str(reg).strip()
    return texto or None


# ==========================================================================
#  Construção das secções (copy factual, PT-PT, sem inventar)
# ==========================================================================
def _rotulo_registo(nr_registo: int) -> str:
    return f"n.º {nr_registo}/AL"


def _secao_estado(detalhe: DetalheRegisto, *, hoje: date) -> SecaoRelatorio:
    """Estado do registo. G4: nunca afirma cancelamento a partir do detalhe."""
    rot = _rotulo_registo(detalhe.nr_registo)
    if detalhe.estado == ESTADO_ATIVO:
        paragrafos = (
            f"O registo {rot} consta como ativo no RNAL na data desta verificação "
            f"({hoje.isoformat()}).",
            "A partir de agora o CheckAL passa a acompanhar regularmente este registo "
            "e avisa-o se detetar alguma alteração.",
        )
    elif detalhe.estado == ESTADO_NAO_ENCONTRADO:
        paragrafos = (
            f"Nesta verificação, a página individual do RNAL não devolveu o registo {rot}.",
            "Este sinal, por si só, não é prova de que o registo deixou de estar válido "
            "(pode ser uma indisponibilidade temporária do portal). Requer confirmação: "
            "vamos reconfirmá-lo antes de tirar qualquer conclusão e avisamos o que "
            "encontrarmos.",
        )
    elif detalhe.estado == ESTADO_INDETERMINADO:
        paragrafos = (
            f"Nesta verificação não foi possível determinar com segurança o estado do "
            f"registo {rot} a partir da página individual do RNAL.",
            "Por prudência, não tiramos conclusões a partir de um sinal ambíguo. Requer "
            "confirmação: vamos reconfirmar e avisá-lo do resultado.",
        )
    else:
        # Estados não observáveis a partir do detalhe (calibração futura) — reporta o
        # rótulo cru, sem interpretar, mantendo a mesma prudência.
        paragrafos = (
            f"Estado do registo {rot} comunicado pela página individual: "
            f"{detalhe.estado}. Requer confirmação antes de qualquer conclusão.",
        )
    return SecaoRelatorio(titulo=SECAO_ESTADO, paragrafos=paragrafos)


def _secao_seguro(detalhe: DetalheRegisto, *, hoje: date) -> SecaoRelatorio:
    """Bloco do seguro RC. Sem apólice visível → nota da obrigatoriedade (sem inventar)."""
    if not detalhe.seguro_companhia:
        paragrafos = (
            "Não foi identificada, na página individual do RNAL, uma apólice de seguro "
            "de responsabilidade civil associada a este registo.",
            "O seguro de responsabilidade civil é obrigatório para o Alojamento Local. "
            "Confirme se está contratado e devidamente comunicado no RNAL.",
        )
        return SecaoRelatorio(titulo=SECAO_SEGURO, paragrafos=paragrafos)

    partes = [f"Apólice de responsabilidade civil identificada no RNAL: {detalhe.seguro_companhia}"]
    if detalhe.seguro_apolice:
        partes.append(f"apólice n.º {detalhe.seguro_apolice}")
    inicio = _iso(detalhe.seguro_inicio)
    validade = _iso(detalhe.seguro_validade)
    if inicio and validade:
        partes.append(f"em vigor de {inicio} a {validade}")
    elif validade:
        partes.append(f"com validade até {validade}")
    elif inicio:
        partes.append(f"com início em {inicio}")
    linha = ", ".join(partes) + "."

    paragrafos: list[str] = [linha]
    if detalhe.seguro_validade is not None and detalhe.seguro_validade < hoje:
        paragrafos.append(
            f"Atenção: a validade indicada ({validade}) é anterior à data deste "
            f"relatório ({hoje.isoformat()}). Confirme a renovação da apólice."
        )
    return SecaoRelatorio(titulo=SECAO_SEGURO, paragrafos=tuple(paragrafos))


def _secao_contencao(contencao: Any, *, concelho: str | None) -> SecaoRelatorio:
    """Área de contenção do concelho. Tolera `None` sem afirmar ausência (FDS 4 preenche)."""
    texto = _texto_contencao(contencao)
    if texto:
        return SecaoRelatorio(titulo=SECAO_CONTENCAO, paragrafos=(texto,))
    sufixo = f" de {concelho}" if concelho else ""
    paragrafos = (
        f"Ainda não há, neste relatório inicial, uma avaliação da área de contenção do "
        f"concelho{sufixo}.",
        "A monitorização do regime municipal fica ativa e comunicamos-lhe qualquer "
        "alteração relevante ao regime de contenção.",
    )
    return SecaoRelatorio(titulo=SECAO_CONTENCAO, paragrafos=paragrafos)


def _secao_regulamentos(regulamentos: Iterable[Any]) -> SecaoRelatorio:
    """Regulamentos municipais ativos. Tolera vazio sem afirmar que não existem."""
    linhas = [linha for reg in (regulamentos or ()) if (linha := _linha_regulamento(reg))]
    if linhas:
        paragrafos = (
            "Regulamentos municipais assinalados para este registo:",
            *[f"- {linha}" for linha in linhas],
        )
        return SecaoRelatorio(titulo=SECAO_REGULAMENTOS, paragrafos=paragrafos)
    paragrafos = (
        "Ainda não há regulamentos municipais a assinalar neste relatório inicial.",
        "A monitorização municipal fica ativa e comunicamos-lhe qualquer regulamento "
        "relevante para o seu Alojamento Local.",
    )
    return SecaoRelatorio(titulo=SECAO_REGULAMENTOS, paragrafos=paragrafos)


def _cabecalho(
    *,
    nr_registo: int,
    nome_alojamento: str | None,
    concelho: str | None,
    cliente_nome: str | None,
    gerado_em: date,
) -> tuple[str, ...]:
    linhas: list[str] = []
    if nome_alojamento:
        linhas.append(f"Alojamento Local: {nome_alojamento}")
    linhas.append(f"Registo RNAL: {_rotulo_registo(nr_registo)}")
    if concelho:
        linhas.append(f"Concelho: {concelho}")
    if cliente_nome:
        linhas.append(f"Cliente: {cliente_nome}")
    linhas.append(f"Relatório gerado em {gerado_em.isoformat()}")
    return tuple(linhas)


# ==========================================================================
#  Ponto de entrada: gerar a estrutura
# ==========================================================================
def gerar_relatorio_inicial(
    cliente: Any,
    detalhe: DetalheRegisto,
    *,
    contencao: Any | None = None,
    regulamentos: Sequence[Any] = (),
    hoje: date | None = None,
) -> RelatorioInicial:
    """Compõe o :class:`RelatorioInicial` a partir do cliente e do detalhe do registo.

    - `cliente`: duck-typed — usa `cliente.nome` e, se existir, `cliente.registos` (para
      o nome do AL e o concelho); nunca toca a BD.
    - `detalhe`: :class:`app.rnal.detalhe.DetalheRegisto` (estado + bloco de seguro).
    - `contencao`: `None` | `str` | objeto com `.descricao` — o FDS 4 preenche; `None`
      gera copy de "monitorização ativa, ainda nada a assinalar" (não afirma ausência).
    - `regulamentos`: sequência de strings ou objetos com `.titulo` — idem, tolera vazio.
    - `hoje`: injetável para testes determinísticos; por omissão `date.today()`.

    Factual e G4-seguro: nunca afirma cancelamento a partir do detalhe.
    """
    quando = hoje or date.today()
    registo = _registo_correspondente(cliente, detalhe.nr_registo)
    nome_alojamento = getattr(registo, "nome_alojamento", None) if registo else None
    concelho = getattr(registo, "concelho", None) if registo else None
    cliente_nome = getattr(cliente, "nome", None)

    cabecalho = _cabecalho(
        nr_registo=detalhe.nr_registo,
        nome_alojamento=nome_alojamento,
        concelho=concelho,
        cliente_nome=cliente_nome,
        gerado_em=quando,
    )
    secoes = (
        _secao_estado(detalhe, hoje=quando),
        _secao_seguro(detalhe, hoje=quando),
        _secao_contencao(contencao, concelho=concelho),
        _secao_regulamentos(regulamentos),
    )
    return RelatorioInicial(
        nr_registo=detalhe.nr_registo,
        nome_alojamento=nome_alojamento,
        concelho=concelho,
        cliente_nome=cliente_nome,
        gerado_em=quando,
        cabecalho=cabecalho,
        secoes=secoes,
    )


# ==========================================================================
#  Render em PDF (fpdf2, core font — sem dependência de fontes externas)
# ==========================================================================
# Caracteres comuns fora de latin-1 → equivalentes seguros para o core font.
_SUBST_PDF = {
    "–": "-",   # – en dash
    "—": "-",   # — em dash
    "−": "-",   # − minus
    "“": '"',   # “
    "”": '"',   # ”
    "„": '"',   # „
    "‘": "'",   # ‘
    "’": "'",   # ’
    "…": "...",  # …
    "✓": "",    # ✓
    "✔": "",    # ✔
    "€": "EUR",  # €
    " ": " ",   # nbsp
}


def _pdf_safe(texto: str) -> str:
    """Texto seguro para o core font (latin-1): mapeia caracteres comuns e faz fallback.

    O português acentuado cabe em latin-1; só travessões, aspas curvas e alguns símbolos
    é que não — esses são substituídos. O `encode(..., "replace")` final é a rede de
    segurança para qualquer resto, para o render nunca rebentar com texto real.
    """
    for origem, destino in _SUBST_PDF.items():
        texto = texto.replace(origem, destino)
    return texto.encode("latin-1", "replace").decode("latin-1")


def render_pdf(relatorio: RelatorioInicial) -> bytes:
    """Rende o `relatorio` num PDF A4 (bytes que começam por `%PDF`).

    fpdf2 com o core font Helvetica — sem fontes externas nem outra dependência. Tolera
    secções com parágrafos vazios (não há; mas o `multi_cell` saltaria strings vazias).
    """
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(left=18, top=18, right=18)
    pdf.set_title(_pdf_safe(relatorio.titulo))
    pdf.add_page()

    # Título
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, text=_pdf_safe(relatorio.titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # Cabeçalho (identificação)
    pdf.set_font("Helvetica", size=10)
    for linha in relatorio.cabecalho:
        pdf.multi_cell(0, 6, text=_pdf_safe(linha), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Secções
    for secao in relatorio.secoes:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, text=_pdf_safe(secao.titulo), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for paragrafo in secao.paragrafos:
            if not paragrafo.strip():
                continue
            pdf.multi_cell(0, 5.5, text=_pdf_safe(paragrafo), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # Rodapé factual (informação, não aconselhamento — CLAUDE.md/LEGAL)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        0,
        4,
        text=_pdf_safe(
            "Este relatório reúne informação pública do RNAL para fins de monitorização. "
            "É informação, não aconselhamento jurídico."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    return bytes(pdf.output())
