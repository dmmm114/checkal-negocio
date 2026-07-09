"""Detalhe individual RNAL: estado do registo + bloco do Seguro RC (FDS 3).

Fronteira do módulo (SPEC-DETALHE, SPEC-FDS3 §detalhe): por cada **registo de
cliente pagante**, obtém a página individual do RNAL
(`config.RNAL_PAGINA?nr=<n>`, server-rendered — GET `httpx` chega, sem Playwright)
e extrai o que a API `list_RNAL` não tem: o **estado** e o **Seguro de
Responsabilidade Civil** (companhia, apólice, data de início, validade). Não fala
com a API nacional (isso é o `client`/`ingest`) nem gera alertas (isso é a camada de
alertas do FDS 3) — só obtém, faz parse e faz upsert em `detalhes_cliente`.

Disciplina inviolável (SPEC-FDS3 §G4 + AUTOMACAO.md §1: «o ambíguo pára e avisa»):
  - `estado ∈ {ativo, cancelado, suspenso, nao_encontrado, indeterminado}`, mas o
    **parser só afirma** `ativo` (a página tem o bloco de dados "RNAL nº <n>/AL") e
    `nao_encontrado` (marcador textual "Registo não encontrado", em HTTP 200). Tudo o
    resto → **`indeterminado`**. NUNCA se afirma `cancelado`/`suspenso` a partir do
    detalhe: a **calibração empírica de 09/07/2026** (nr 51233, realmente cancelado
    entre 05/07 e 09/07) concluiu que esse estado **não é observável na página** — o
    RNAL REMOVE o registo da consulta pública (HTTP 200 + «Registo não encontrado»);
    não existe banner de estado (7 nrs ausentes sondados: todos assim; 0 banners em 15
    páginas vivas). Os rótulos `ESTADO_CANCELADO`/`ESTADO_SUSPENSO` mantêm-se apenas à
    prova de futuro (se o RNAL algum dia os mostrar), nunca emitidos hoje. A
    CONFIRMAÇÃO de cancelamento pertence ao breaker (`app.breaker`): assinatura
    «alvo `nao_encontrado` + canário sabidamente ativo a responder `ativo` na mesma
    corrida» — o parser limita-se a reportar fielmente o que a página diz.
  - **Falha de transporte (rede/5xx/timeout) levanta** — nunca se escreve estado por
    falha de rede (não marcar "cancelado" por timeout). Só uma resposta HTTP 200 lida
    com sucesso produz um `DetalheRegisto` persistível.

Ancoragem de parsing: por **texto de cabeçalho** ("Seguro de Responsabilidade Civil",
"Companhia de Seguros", "Validade"), NUNCA pelos `id` OutSystems (`RichWidgets_wt7_...`),
que são regenerados a cada republicação da app (SPEC-DETALHE §6.2). Sem dependências de
parsing externas (não há lxml/bs4 no ambiente): usa-se o `html.parser` da stdlib.

Injeção para testes: `obter_detalhe(nr, *, cliente_http=None, dormir=...)` — o
`cliente_http` (qualquer objeto com `.get(url, params=...) -> httpx.Response`) e o
`dormir` são injetados; nos testes usam-se dublês e fixtures HTML, logo **nada toca a
rede**. Em produção, com `cliente_http=None`, compõe-se um `httpx.Client` próprio (o
único ponto que cria rede real), à imagem do `app.rnal.client`.
"""
from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

import app.config as config
from app.models import DetalheCliente

# --- Estados possíveis do detalhe (o parser só afirma ATIVO e NAO_ENCONTRADO) ---
ESTADO_ATIVO = "ativo"
ESTADO_CANCELADO = "cancelado"          # NUNCA observado na página (calibração 09/07/2026:
ESTADO_SUSPENSO = "suspenso"            # o RNAL remove o registo) — mantidos à prova de futuro
ESTADO_NAO_ENCONTRADO = "nao_encontrado"
ESTADO_INDETERMINADO = "indeterminado"  # G4: default conservador (pára e avisa)
ESTADOS = frozenset(
    {
        ESTADO_ATIVO,
        ESTADO_CANCELADO,
        ESTADO_SUSPENSO,
        ESTADO_NAO_ENCONTRADO,
        ESTADO_INDETERMINADO,
    }
)

# Nº de tentativas por página (1 + retry) e backoff base — SPEC-DETALHE §5 ("1 retry").
# O backoff passa por `dormir`, logo é neutralizado nos testes.
RNAL_DETALHE_TENTATIVAS = 2
RNAL_DETALHE_BACKOFF_S = 1.0

# Marcadores textuais (comparados sem acentos e em minúsculas — ver `_norm`).
_MARCADOR_NAO_ENCONTRADO = "registo nao encontrado"  # "Registo não encontrado, pesquise..."
_MARCADOR_BLOCO_DADOS = "rnal n"                      # "RNAL nº <n>/AL" (deteta detalhe válido)
_CABECALHO_SEGURO = "companhia"                       # cabeçalho "Companhia de Seguros"

# 🚦 CALIBRAÇÃO CONCLUÍDA (09/07/2026, sondagem dirigida): um `nr` REALMENTE cancelado
# (51233 — ativo na list_RNAL a 05/07, ausente a 09/07) devolve HTTP 200 + «Registo não
# encontrado» — o RNAL REMOVE o registo da consulta pública; **não existe banner de
# estado** (mais 7 nrs ausentes sondados: idem; 0 banners em 15 páginas vivas). Este
# tuple fica VAZIO de propósito: não há marcadores a acrescentar. Mantém-se como ponto
# de extensão defensivo — se o RNAL algum dia mostrar um banner, os marcadores entram
# aqui (normalizados, sem acentos) e levam a página a `indeterminado` (pára e avisa),
# NUNCA diretamente a `cancelado`. A confirmação de cancelamento vive no breaker
# (`app.breaker`: alvo `nao_encontrado` + canário `ativo` na mesma corrida).
_MARCADORES_ESTADO_SUSPEITO: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetalheRegisto:
    """Resultado do parse da página individual RNAL (imutável).

    `estado` é um dos :data:`ESTADOS` (na prática só `ativo`/`nao_encontrado`/
    `indeterminado` saem do parser — ver G4). Os campos de seguro são o que a API
    nacional não expõe. `obtido_em` fica `None` no parse puro; é carimbado por
    :func:`obter_detalhe` (momento da obtenção) ou por :func:`persistir_detalhe`.
    """

    nr_registo: int
    estado: str
    seguro_companhia: str | None = None
    seguro_apolice: str | None = None      # texto: guarda zeros à esquerda (nunca int)
    seguro_inicio: date | None = None
    seguro_validade: date | None = None
    obtido_em: datetime | None = None


# ==========================================================================
#  Normalização de texto (sem acentos, minúsculas) — matching robusto de rótulos
# ==========================================================================
def _sem_acentos(texto: str) -> str:
    """Remove acentos por decomposição NFKD (ex.: 'início'→'inicio', 'nº'→'no')."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _norm(texto: str) -> str:
    """Minúsculas, sem acentos e sem espaços nas pontas — para comparar rótulos/marcadores."""
    return _sem_acentos(texto).casefold().strip()


# ==========================================================================
#  Parser de tabelas HTML (stdlib) — coleta tabelas (linhas de células) + texto
# ==========================================================================
class _ParserTabelas(HTMLParser):
    """Extrai, sem dependências externas, todas as `<table>` como listas de linhas de
    células (texto de `<th>`/`<td>`) e acumula o texto visível da página.

    Robusto a aninhamento: mantém pilhas paralelas de tabelas/linhas abertas e uma
    pilha de células abertas, para que linhas de uma tabela aninhada não contaminem a
    de fora. Ignora `<thead>`/`<tbody>` (as linhas acumulam por ordem de aparição).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabelas: list[list[list[str]]] = []
        self.textos: list[str] = []
        self._tabelas_abertas: list[list[list[str]]] = []
        self._linhas_abertas: list[list[str] | None] = []
        self._celulas_abertas: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._tabelas_abertas.append([])
            self._linhas_abertas.append(None)
        elif tag == "tr":
            if self._linhas_abertas:
                self._linhas_abertas[-1] = []
        elif tag in ("td", "th"):
            self._celulas_abertas.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            texto = "".join(self._celulas_abertas.pop()).strip() if self._celulas_abertas else ""
            if self._linhas_abertas and self._linhas_abertas[-1] is not None:
                self._linhas_abertas[-1].append(texto)
        elif tag == "tr":
            if self._linhas_abertas and self._linhas_abertas[-1] is not None:
                if self._tabelas_abertas:
                    self._tabelas_abertas[-1].append(self._linhas_abertas[-1])
                self._linhas_abertas[-1] = None
        elif tag == "table":
            if self._tabelas_abertas:
                linhas = self._tabelas_abertas.pop()
                self._linhas_abertas.pop()
                self.tabelas.append(linhas)

    def handle_data(self, data: str) -> None:
        self.textos.append(data)
        if self._celulas_abertas:
            self._celulas_abertas[-1].append(data)


def _analisar_html(html: str) -> _ParserTabelas:
    parser = _ParserTabelas()
    parser.feed(html)
    parser.close()
    return parser


# ==========================================================================
#  Parse do bloco de seguro
# ==========================================================================
def _indice_coluna(cabecalho: list[str], *agulhas: str) -> int | None:
    """Índice da 1.ª célula do cabeçalho cujo texto normalizado contém uma das `agulhas`."""
    for i, celula in enumerate(cabecalho):
        norm = _norm(celula)
        if any(a in norm for a in agulhas):
            return i
    return None


def _celula(linha: list[str], indice: int | None) -> str:
    """Texto (stripado) da célula em `indice`, ou "" se o índice for inválido/ausente."""
    if indice is None or indice < 0 or indice >= len(linha):
        return ""
    return linha[indice].strip()


def _parse_data_iso(texto: str) -> tuple[date | None, bool]:
    """`(date, suspeita)`: vazio→(None, False); ISO válida→(date, False); malformada→(None, True).

    Uma data **presente mas não-ISO** é suspeita (gotcha §6.8): não se inventa `None`
    silencioso — quem chama promove o estado a `indeterminado` (pára e avisa).
    """
    t = (texto or "").strip()
    if not t:
        return None, False
    try:
        return date.fromisoformat(t), False
    except ValueError:
        return None, True


def _escolher_linha_seguro(
    linhas: list[list[str]], idx_validade: int | None
) -> tuple[list[str], bool]:
    """Entre várias apólices, escolhe a de MAIOR validade (gotcha §6.5); 1 linha → ela mesma.

    Devolve também se alguma validade estava malformada (para sinalizar suspeita).
    """
    if len(linhas) == 1:
        return linhas[0], False
    melhor: list[str] | None = None
    melhor_data: date | None = None
    suspeita = False
    for linha in linhas:
        data, s = _parse_data_iso(_celula(linha, idx_validade))
        suspeita = suspeita or s
        if data is not None and (melhor_data is None or data > melhor_data):
            melhor_data, melhor = data, linha
    return (melhor if melhor is not None else linhas[0]), suspeita


def _extrair_seguro(tabelas: list[list[list[str]]]) -> tuple[dict[str, Any], bool]:
    """Extrai `{seguro_companhia, seguro_apolice, seguro_inicio, seguro_validade}` + suspeita.

    Localiza a tabela de seguro pelo **cabeçalho** ("Companhia de Seguros" …). Sem tabela
    ou sem linhas de dados → todos os campos `None` (registo sem RC visível, não é erro —
    gotcha §6.9). `suspeita=True` sinaliza uma data presente mas malformada.
    """
    vazio: dict[str, Any] = {
        "seguro_companhia": None,
        "seguro_apolice": None,
        "seguro_inicio": None,
        "seguro_validade": None,
    }
    for tabela in tabelas:
        idx_cabecalho = next(
            (i for i, linha in enumerate(tabela)
             if any(_CABECALHO_SEGURO in _norm(c) for c in linha)),
            None,
        )
        if idx_cabecalho is None:
            continue

        cabecalho = tabela[idx_cabecalho]
        i_companhia = _indice_coluna(cabecalho, "companhia")
        i_apolice = _indice_coluna(cabecalho, "apolice")
        i_inicio = _indice_coluna(cabecalho, "inicio")
        i_validade = _indice_coluna(cabecalho, "validade")

        linhas_dados = [
            linha for linha in tabela[idx_cabecalho + 1:]
            if any(c.strip() for c in linha)
        ]
        if not linhas_dados:
            return vazio, False

        escolhida, suspeita = _escolher_linha_seguro(linhas_dados, i_validade)
        inicio, s_ini = _parse_data_iso(_celula(escolhida, i_inicio))
        validade, s_val = _parse_data_iso(_celula(escolhida, i_validade))
        seguro = {
            "seguro_companhia": _celula(escolhida, i_companhia) or None,
            "seguro_apolice": _celula(escolhida, i_apolice) or None,
            "seguro_inicio": inicio,
            "seguro_validade": validade,
        }
        return seguro, (suspeita or s_ini or s_val)

    return vazio, False


# ==========================================================================
#  Parse do detalhe (puro — testável por fixture, sem I/O)
# ==========================================================================
def parse_detalhe(html: str, *, nr_registo: int) -> DetalheRegisto:
    """Faz o parse do HTML da página individual → :class:`DetalheRegisto` (puro, sem rede).

    Regra de estado (G4, conservadora):
      1. marcador "Registo não encontrado" no texto → `nao_encontrado`;
      2. senão, se há bloco de dados ("RNAL nº") → `ativo` (e faz parse do seguro);
         uma data de seguro malformada, porém, promove o estado a `indeterminado`;
      3. caso contrário → `indeterminado`.
    Nunca devolve `cancelado`/`suspenso` — calibração de 09/07/2026: esse estado NÃO é
    observável na página (registos cancelados são removidos da consulta pública e caem
    na regra 1); a confirmação de cancelamento pertence ao breaker, não ao parser.
    """
    parser = _analisar_html(html)
    texto = _norm(" ".join(parser.textos))

    if _MARCADOR_NAO_ENCONTRADO in texto:
        return DetalheRegisto(nr_registo=nr_registo, estado=ESTADO_NAO_ENCONTRADO)

    if any(m in texto for m in _MARCADORES_ESTADO_SUSPEITO):
        # calibração futura: banner de estado ainda-não-observado → pára e avisa (G4)
        return DetalheRegisto(nr_registo=nr_registo, estado=ESTADO_INDETERMINADO)

    if _MARCADOR_BLOCO_DADOS not in texto:
        return DetalheRegisto(nr_registo=nr_registo, estado=ESTADO_INDETERMINADO)

    seguro, suspeita = _extrair_seguro(parser.tabelas)
    estado = ESTADO_INDETERMINADO if suspeita else ESTADO_ATIVO
    return DetalheRegisto(nr_registo=nr_registo, estado=estado, **seguro)


# ==========================================================================
#  Obtenção HTTP (o único ponto que pode criar rede real; injetável nos testes)
# ==========================================================================
def _novo_cliente() -> httpx.Client:
    """`httpx.Client` com o `timeout`/`User-Agent` canónicos e follow_redirects (§5)."""
    return httpx.Client(
        timeout=config.RNAL_TIMEOUT_S,
        headers={"User-Agent": config.RNAL_USER_AGENT},
        follow_redirects=True,
    )


def _get_com_retry(
    cliente_http: Any,
    nr_registo: int,
    *,
    tentativas: int,
    dormir: Callable[[float], None],
) -> str:
    """GET à página com até `tentativas` tentativas; re-levanta a última falha.

    Falha de transporte OU estado HTTP != 2xx são retriáveis; esgotadas as tentativas a
    exceção propaga (quem chama NÃO escreve estado — §1: nunca "cancelado" por rede).
    """
    ultima_exc: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = cliente_http.get(config.RNAL_PAGINA, params={"nr": nr_registo})
            resposta.raise_for_status()
            return resposta.text
        except Exception as exc:  # rede, timeout, 5xx — tudo retriável
            ultima_exc = exc
            if tentativa < tentativas:
                dormir(RNAL_DETALHE_BACKOFF_S * tentativa)
    assert ultima_exc is not None  # o loop corre ≥1 vez
    raise ultima_exc


def obter_detalhe(
    nr_registo: int,
    *,
    cliente_http: Any | None = None,
    dormir: Callable[[float], None] = time.sleep,
    tentativas: int = RNAL_DETALHE_TENTATIVAS,
) -> DetalheRegisto:
    """Obtém e faz parse do detalhe individual de `nr_registo` (carimba `obtido_em`).

    GET a `config.RNAL_PAGINA?nr=<n>` com 1 retry. Se `cliente_http` for `None`, cria (e
    fecha) um `httpx.Client` próprio — o único ponto que toca a rede; nos testes injeta-se
    um dublê, logo nunca há rede real. Uma falha de transporte esgotado o retry **levanta**
    (não se devolve detalhe nem se escreve estado por falha de rede — §1).
    """
    proprio_cliente = cliente_http is None
    cliente = _novo_cliente() if proprio_cliente else cliente_http
    try:
        html = _get_com_retry(cliente, nr_registo, tentativas=tentativas, dormir=dormir)
    finally:
        if proprio_cliente:
            cliente.close()

    detalhe = parse_detalhe(html, nr_registo=nr_registo)
    return replace(detalhe, obtido_em=datetime.now(timezone.utc))


# ==========================================================================
#  Persistência (upsert idempotente em detalhes_cliente)
# ==========================================================================
def persistir_detalhe(session: Any, detalhe: DetalheRegisto) -> DetalheCliente:
    """Upsert de `detalhe` em `detalhes_cliente` (PK `nr_registo`); devolve a linha.

    Idempotente: correr 2× com o mesmo `nr_registo` atualiza a mesma linha (não duplica).
    Reescreve **todos** os campos de seguro — quando um registo deixa de expor a apólice,
    os valores antigos são limpos (`None`), não ficam obsoletos. `obtido_em` vem do detalhe
    (carimbado por :func:`obter_detalhe`) ou, em falta, carimba-se agora.
    """
    linha = session.get(DetalheCliente, detalhe.nr_registo)
    if linha is None:
        linha = DetalheCliente(nr_registo=detalhe.nr_registo)
        session.add(linha)

    linha.estado_detalhado = detalhe.estado
    linha.seguro_companhia = detalhe.seguro_companhia
    linha.seguro_apolice = detalhe.seguro_apolice
    linha.seguro_inicio = detalhe.seguro_inicio
    linha.seguro_validade = detalhe.seguro_validade
    linha.obtido_em = detalhe.obtido_em or datetime.now(timezone.utc)

    session.flush()
    return linha
