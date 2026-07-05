"""Cliente + parse da Camada A do DRE — PDF integral gratuito da 2.ª série.

Fronteira do módulo (SPEC-DRE.md §1/§2, SPEC-FDS4 §dre_client): resolve o URL do
PDF gratuito, descarrega-o (cliente `httpx` **injetável**), extrai texto (pypdf) e
**isola a Parte H (Autarquias Locais)** do sumário — mapeando cada bloco de entidade
a um `SeccaoParteH`. Sobre cada secção corre a triagem por keywords (`grep_al`) e a
extração de concelho (`concelhos_de`). Não toca na BD nem chama IA — isso é do
`dre_ingest`/`dre_pipeline` e da camada `app.ia`.

Princípios (SPEC-DRE §3, mesma disciplina do FDS 1):
  - **Robustez sobre adivinhação**: o número de edição não é derivável da data
    (reinicia por ano) — quem o resolve é o contador auto-corretivo do cron; aqui só
    se constrói o URL a partir de `(data, edicao)`. Uma edição inexistente devolve
    HTML/404 → `descarregar_pdf` responde ``None`` (não rebenta).
  - **Tolerância a drift**: `extrair_parte_H` tolera a ausência da secção (→ ``[]``);
    a comparação de keywords/concelhos é feita sobre texto **normalizado** (minúsculas,
    sem acentos, hifenização de fim de linha colada, espaços colapsados), porque o
    pypdf parte palavras por quebras de linha/colunas.
  - **Injeção para testes**: `descarregar_pdf` aceita `cliente_http` (qualquer objeto
    com `.get(url) -> resposta` que exponha `.status_code`/`.content`). Assim os testes
    correm **sem rede real**; o `httpx.Client` só se compõe em produção (`_novo_cliente`).

Fora de âmbito (SPEC-DRE §0/§8): Camada B (endpoint `screenservices` OutSystems),
extrato por ato individual, persistência e a camada IA.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from pypdf import PdfReader

import app.config as config

# --- Endpoint e transporte (SPEC-DRE §2.1/§3.3) ---------------------------
# Base do PDF integral gratuito da 2.ª série (VERIFICADO 2026-07-05).
DRE_PDF_BASE = "https://files.diariodarepublica.pt/gratuitos/2s"
DRE_TIMEOUT_S = 180.0  # o PDF integral chega aos ~31 MB; timeout generoso (cron noturno)
DRE_USER_AGENT = "CheckAL/1.0 (+https://checkal.pt; detecao de regulamentos de AL no DRE)"

# Keywords canónicas de triagem (AUTOMACAO.md §2 / SPEC-DRE §2.3). Comparadas sobre
# texto normalizado (sem acentos, minúsculas) — daí virem já sem depender de acentos.
DRE_KEYWORDS: tuple[str, ...] = (
    "alojamento local",
    "área de contenção",
    "crescimento sustentável",
    "registo nacional de alojamento local",
    "alojamento de curta duração",
)


@dataclass(frozen=True)
class SeccaoParteH:
    """Um bloco de entidade dentro da Parte H (Autarquias Locais) do sumário.

    - `cabecalho`: a linha do cabeçalho da entidade tal como surge no PDF
      (ex.: ``"MUNICÍPIO DE BRAGA"``, ``"CÂMARA MUNICIPAL DO PORTO"``).
    - `texto`: o bloco integral desta entidade (cabeçalho + títulos dos atos), até ao
      cabeçalho da entidade seguinte. É sobre este texto que `grep_al` procura keywords.
    """

    cabecalho: str
    texto: str


# --- Normalização (SPEC-DRE §2.3/§3.1) ------------------------------------
def _sem_acentos(texto: str) -> str:
    """Remove acentos (NFKD → ASCII), preservando a restante grafia."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _normalizar(texto: str) -> str:
    """Normaliza para comparação de keywords: cola hifenização de fim de linha,
    remove acentos, colapsa espaços/quebras e passa a minúsculas."""
    texto = unicodedata.normalize("NFC", texto)
    texto = re.sub(r"-\s*\n\s*", "", texto)  # "alo-\njamento" → "alojamento"
    texto = _sem_acentos(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.lower().strip()


def _chave_concelho(nome: str) -> str:
    """Chave de comparação de um nome de concelho (sem acentos, minúsculas, 1 espaço)."""
    return re.sub(r"\s+", " ", _sem_acentos(nome)).strip().lower()


_KEYWORDS_NORM: tuple[str, ...] = tuple(_normalizar(k) for k in DRE_KEYWORDS)

# --- Regex de estrutura (SPEC-DRE §2.2) -----------------------------------
# Início da Parte H no sumário: "PARTE H | Autarquias locais" (o "|" e as quebras de
# linha da extração são toleradas por [\s|]*).
_MARCADOR_PARTE_H = re.compile(r"PARTE\s+H\b[\s|]*Autarquias\s+locais", re.IGNORECASE)

# Fim do sumário / início do corpo: reaparece o cabeçalho de página "N.º NNN • <data>".
_FIM_SUMARIO = re.compile(r"N\.\s*[ºo]?\s*\d+\s*[•·]", re.IGNORECASE)

# Prefixos de entidade (com/sem preposição). `[IÍ]`/`[AÂ]` toleram a extração sem acento.
_PREFIXO_ENTIDADE = (
    r"MUNIC[IÍ]PIO|C[AÂ]MARA\s+MUNICIPAL|SERVI[ÇC]OS\s+MUNICIPALIZADOS"
    r"|UNI[AÃ]O\s+DAS\s+FREGUESIAS|FREGUESIA"
)
_PREPOSICAO = r"DE|DO|DA|DAS|DOS|D['’]"

# Cabeçalho de qualquer entidade (delimita os blocos da Parte H).
_CABECALHO_ENTIDADE = re.compile(
    rf"^[ \t]*((?:{_PREFIXO_ENTIDADE})\s+(?:{_PREPOSICAO})\s*[^\n]+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

# Cabeçalho de MUNICÍPIO/CÂMARA MUNICIPAL (o que mapeia a concelho); captura o nome.
_CABECALHO_MUNICIPIO = re.compile(
    rf"(?:MUNIC[IÍ]PIO|C[AÂ]MARA\s+MUNICIPAL)\s+(?:{_PREPOSICAO})\s*([^\n]+)",
    re.IGNORECASE,
)


# --- URL (SPEC-DRE §2.1) --------------------------------------------------
def url_pdf_gratuito(data: date, edicao: int) -> str:
    """Constrói o URL do PDF integral gratuito da 2.ª série para `(data, edicao)`.

    Padrão VERIFICADO (SPEC-DRE §2.1):
    ``…/gratuitos/2s/{AAAA}/{MM}/2S{NNN}A0000S00.pdf`` — mês e edição com zero-pad
    (edição a 3 dígitos). O `edicao` é o **número sequencial da 2.ª série** (reinicia
    em janeiro), resolvido pelo contador auto-corretivo do cron, **não** o dia-do-ano.
    """
    if edicao < 1:
        raise ValueError(f"Número de edição inválido: {edicao!r} (tem de ser ≥ 1).")
    return f"{DRE_PDF_BASE}/{data.year:04d}/{data.month:02d}/2S{edicao:03d}A0000S00.pdf"


# --- Download (SPEC-DRE §3.2) ---------------------------------------------
def _novo_cliente() -> httpx.Client:
    """Cria um `httpx.Client` com o `timeout`/`User-Agent` canónicos (só em produção)."""
    return httpx.Client(
        timeout=DRE_TIMEOUT_S,
        headers={"User-Agent": DRE_USER_AGENT},
        follow_redirects=True,
    )


def _descarregar(cliente_http: Any, url: str) -> bytes | None:
    """Um GET; devolve os bytes só se `200` **e** o corpo for mesmo um PDF (`%PDF`)."""
    resposta = cliente_http.get(url)
    if getattr(resposta, "status_code", None) != 200:
        return None  # 404/403/… = "ainda não publicado"
    conteudo = resposta.content or b""
    if not conteudo.startswith(b"%PDF"):
        return None  # página de erro HTML / corpo vazio ≠ PDF
    return conteudo


def descarregar_pdf(url: str, *, cliente_http: Any | None = None) -> bytes | None:
    """Descarrega o PDF de `url`; **não-200 ou não-PDF → ``None``** (sem rebentar).

    Uma edição inexistente devolve 404 (ou uma página HTML) → ``None``, sinal para o
    cron de que o número ainda não foi publicado (SPEC-DRE §3.2). O `cliente_http` é
    injetado nos testes (sem rede); em produção compõe-se um `httpx.Client` próprio.
    Erros de transporte (timeout/rede) **propagam** — o retry/alerta vive no cron.
    """
    if cliente_http is not None:
        return _descarregar(cliente_http, url)
    with _novo_cliente() as cliente:
        return _descarregar(cliente, url)


# --- Extração de texto (SPEC-DRE §3.1) ------------------------------------
def extrair_texto(pdf_bytes: bytes) -> str:
    """Extrai o texto integral do PDF com pypdf (uma página problemática não derruba
    o documento — devolve o resto)."""
    leitor = PdfReader(io.BytesIO(pdf_bytes))
    partes: list[str] = []
    for pagina in leitor.pages:
        try:
            partes.append(pagina.extract_text() or "")
        except Exception:  # noqa: BLE001 — página corrompida não invalida a edição
            partes.append("")
    return "\n".join(partes)


# --- Parte H (SPEC-DRE §2.2) ----------------------------------------------
def extrair_parte_H(texto: str) -> list[SeccaoParteH]:
    """Isola a Parte H (Autarquias Locais) do sumário e parte-a por entidade.

    Delimita de ``"PARTE H | Autarquias locais"`` até ao reaparecimento do cabeçalho
    de página do corpo (``"N.º NNN • …"``); dentro dessa região, cada cabeçalho de
    entidade (``MUNICÍPIO/CÂMARA MUNICIPAL/FREGUESIA/…``) inicia um `SeccaoParteH`.
    Tolera a ausência da secção (dia sem autarquias / drift de layout) devolvendo
    ``[]`` — nunca rebenta (SPEC-DRE §2.1 [ASSUMIDO Q1], R6).
    """
    if not texto:
        return []
    marcador = _MARCADOR_PARTE_H.search(texto)
    if marcador is None:
        return []
    inicio = marcador.end()
    fim = _FIM_SUMARIO.search(texto, inicio)
    regiao = texto[inicio : fim.start()] if fim else texto[inicio:]

    cabecalhos = list(_CABECALHO_ENTIDADE.finditer(regiao))
    seccoes: list[SeccaoParteH] = []
    for i, cab in enumerate(cabecalhos):
        fim_bloco = cabecalhos[i + 1].start() if i + 1 < len(cabecalhos) else len(regiao)
        seccoes.append(
            SeccaoParteH(
                cabecalho=cab.group(1).strip(),
                texto=regiao[cab.start() : fim_bloco].strip(),
            )
        )
    return seccoes


# --- Triagem por keywords (SPEC-DRE §2.3) ---------------------------------
def grep_al(seccao: SeccaoParteH) -> bool:
    """`True` se a secção contém alguma keyword de Alojamento Local (normalizado)."""
    alvo = _normalizar(seccao.texto)
    return any(kw in alvo for kw in _KEYWORDS_NORM)


# --- Extração de concelho (SPEC-DRE §2.2) ---------------------------------
def concelhos_de(seccao: SeccaoParteH) -> list[str]:
    """Concelho(s) reconhecido(s) no cabeçalho da secção, na grafia canónica.

    Cruza cada cabeçalho ``MUNICÍPIO/CÂMARA MUNICIPAL DE …`` com
    `config.concelhos_todos()` (comparação sem acentos/maiúsculas). Freguesias/uniões
    **não** mapeiam a concelho (sem tabela freguesia→concelho) e um nome fora da lista
    canónica é ignorado aqui — o `dre_ingest` é que o encaminha para revisão do dono,
    nunca se descarta em silêncio (SPEC-DRE §2.2/R7). Ordem = 1.ª aparição, sem repetir.
    """
    lookup = {_chave_concelho(c): c for c in config.concelhos_todos()}
    fonte = f"{seccao.cabecalho}\n{seccao.texto}"
    reconhecidos: list[str] = []
    for m in _CABECALHO_MUNICIPIO.finditer(fonte):
        canonico = lookup.get(_chave_concelho(m.group(1)))
        if canonico is not None and canonico not in reconhecidos:
            reconhecidos.append(canonico)
    return reconhecidos
