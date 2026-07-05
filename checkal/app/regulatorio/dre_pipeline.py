"""Cron regulatório (Camada A) — ingestão do DRE para `eventos_regulatorios`.

Fronteira do módulo (SPEC-FDS4 §pipeline, SPEC-DRE.md §1/§3): é o **único** módulo do
DRE que toca a BD. Encadeia as peças puras do :mod:`app.regulatorio.dre_client`
(descarregar → extrair → Parte H → grep → concelho) numa corrida diária que materializa
`eventos_regulatorios` — a fila que a camada IA (:mod:`app.regulatorio.pipeline`) depois
tria e transforma em alertas citados.

Fluxo de uma corrida (SPEC-DRE §1)::

    correr_dre(session, *, cliente_http, data, edicao_inicial) -> ResultadoDRE

  1. **contador auto-corretivo** (SPEC-DRE §3.2): o nº de edição da 2.ª série **não** é
     derivável da data (reinicia por ano). Parte-se de `edicao_inicial` (o seed) e
     tenta-se `edicao_inicial`, `+1`, `+2`, … Cada candidato é descarregado; um 404/não-PDF
     significa "ainda não publicado" → **pára** (nunca inventa). A página 1 do PDF diz o
     número E a data (``N.º 142 • 24 de julho de 2025``): confirma-se que o número bate
     certo — se a página disser outro número (salto/suplemento) **pára e avisa o dono**.
  2. **Parte H**: isola-se a secção Autarquias Locais do sumário, filtra-se por keywords
     de AL (`grep_al`) e mapeia-se ``MUNICÍPIO …`` → concelho canónico (`concelhos_de`).
  3. **persistência idempotente**: cada ato de AL vira um `eventos_regulatorios` com
     `url` **UNIQUE** (o PDF gratuito + fragmento da entidade); re-correr o mesmo dia
     **não** duplica (a `url` já existe → salta). Um concelho fora da lista canónica
     **não** é descartado — cria-se o evento com ``concelhos=[]`` e regista-se um aviso
     para revisão do dono (SPEC-DRE §2.2/R7).

Cada evento criado leva, **em memória** (atributo transitório, não persistido — o esquema
de `eventos_regulatorios` não tem coluna de corpo), o **excerto do ato** em `.texto`:
localiza-se o corpo do ato no texto integral do PDF (a entidade repete-se no rodapé de
cada página do corpo — âncora fiável, SPEC-DRE §2.2). Os eventos criados devolvem-se em
`ResultadoDRE.eventos` (instâncias vivas, com referência forte) — passa-se essa lista à
:func:`app.regulatorio.pipeline.correr_pipeline` como `eventos=` para a IA receber o corpo
por excerto. (Não se confia no mapa de identidade da sessão: sendo de referências fracas,
um objeto sem referência forte é recarregado sem o `.texto`.) Num cron separado, que re-lê
a fila da BD, o excerto degrada-se ao título — seguro, porque a validação anti-alucinação
reprova qualquer valor que o excerto não sustente.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** O `cliente_http` é **injetado**
(dublê nos testes; sem rede). Só :func:`obter_cliente_http` compõe um `httpx.Client` real,
e **nunca** sob `config.CHECKAL_MODO_TESTE` (devolve ``None``) — à imagem exata de
:func:`app.envio.obter_enviador` e :func:`app.ia.obter_cliente_ia`. Correr os testes nunca
toca a rede. A função recebe a `session` de quem chama e **não** faz commit (a transação é
do orquestrador, sob `db.get_session`), o que permite a passagem de mão em memória descrita
acima. Nada de cold: isto lê só fontes públicas (Diário da República).

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import app.config as config
from app.models import EventoRegulatorio
from app.regulatorio import dre_client
from app.regulatorio.dre_client import (
    SeccaoParteH,
    concelhos_de,
    descarregar_pdf,
    extrair_parte_H,
    extrair_texto,
    grep_al,
    url_pdf_gratuito,
)

__all__ = [
    "ResultadoDRE",
    "correr_dre",
    "obter_cliente_http",
    "FONTE_DRE",
    "EDICAO_INICIAL_PADRAO",
    "MAX_EDICOES_POR_CORRIDA",
    "EXCERTO_MAX_CHARS",
    "TITULO_MAX_CHARS",
]

# Valor de `EventoRegulatorio.fonte` para os documentos captados do Diário da República.
FONTE_DRE = "DRE"

# Seed do contador auto-corretivo (SPEC-DRE §3.2): a 1.ª edição a TENTAR. Em produção o
# cron passa o número da última edição conhecida (+1); aqui há um default só para o módulo
# ser invocável. Valor conservador (edição real recente da 2.ª série de 2025).
EDICAO_INICIAL_PADRAO = 1

# Tetos defensivos de uma corrida. Uma corrida diária processa 1–2 edições; o teto de
# saltos evita um varrimento descontrolado se o download nunca devolver 404 (bug/rede).
MAX_EDICOES_POR_CORRIDA = 20

# Tamanho máximo do excerto do ato entregue à IA (SPEC-IA §4.3: excerto partilhado em
# cache). ~4 000 chars chegam para o corpo relevante de um regulamento sem inflar tokens.
EXCERTO_MAX_CHARS = 4000

# Teto do título derivado da secção (evita títulos multi-parágrafo em copy/alerta).
TITULO_MAX_CHARS = 200


# ==========================================================================
#  Resultado de uma corrida (para logs/testes; a BD é a fonte de verdade)
# ==========================================================================
@dataclass
class ResultadoDRE:
    """Sumário de uma corrida de ingestão do DRE.

    :param eventos: os `eventos_regulatorios` **novos** criados nesta corrida (não inclui
        os que já existiam — idempotência por `url`). Cada um traz `.texto` (o excerto do
        ato) em memória para a passagem à camada IA na mesma sessão.
    :param edicoes: os números de edição processados com sucesso, por ordem.
    :param avisos: mensagens para o dono (salto/suplemento, drift de layout, concelho não
        reconhecido) — a corrida **pára e avisa**, nunca inventa (SPEC-DRE §1/R6/R7).
    """

    eventos: list[EventoRegulatorio] = field(default_factory=list)
    edicoes: list[int] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ==========================================================================
#  Seam LIVE-GATED do transporte (à imagem de obter_enviador/obter_cliente_ia)
# ==========================================================================
def obter_cliente_http() -> Any | None:
    """Compõe o cliente HTTP do DRE (`httpx.Client`), ou ``None`` (LIVE-GATED).

    Devolve ``None`` (sem importar `httpx` nem tocar na rede) sob
    `config.CHECKAL_MODO_TESTE` — o default nos testes. A fonte é pública (PDF gratuito),
    logo não há chave a validar: o único portão é o modo de teste. Em produção devolve um
    cliente com o `timeout`/`User-Agent` canónicos do :mod:`app.regulatorio.dre_client`.
    """
    if config.CHECKAL_MODO_TESTE:
        return None
    return dre_client._novo_cliente()


# ==========================================================================
#  Auxiliares puros — cabeçalho da edição, título, url, excerto
# ==========================================================================
_MESES: dict[str, int] = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Cabeçalho da página 1 (SPEC-DRE §2.1/§3.2): "N.º 142 • 24 de julho de 2025". Tolera a
# extração sem acento no "º" e o bullet como "•" ou "·".
_RE_CABECALHO = re.compile(
    r"N\.\s*[ºo]?\s*(\d+)\s*[•·]\s*(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)


def _sem_acentos(texto: str) -> str:
    """Minúsculas sem diacríticos ("julho"→"julho", "Março"→"marco")."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def _cabecalho_edicao(texto: str) -> tuple[int, date] | None:
    """Lê ``(numero, data)`` do cabeçalho da página 1; ``None`` se ilegível.

    É a âncora de auto-correção do contador (SPEC-DRE §3.2): o PDF diz o número E a data,
    logo confirma-se que o candidato descarregado é mesmo a edição esperada.
    """
    m = _RE_CABECALHO.search(texto)
    if m is None:
        return None
    mes = _MESES.get(_sem_acentos(m.group(3)))
    dia = int(m.group(2))
    if mes is None or not (1 <= dia <= 31):
        return None
    try:
        return int(m.group(1)), date(int(m.group(4)), mes, dia)
    except ValueError:
        return None


def _slug(texto: str) -> str:
    """Slug ASCII de um cabeçalho de entidade ("MUNICÍPIO DE BRAGA"→"municipio-de-braga")."""
    base = _sem_acentos(texto)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "ato"


def _url_evento(data: date, edicao: int, seccao: SeccaoParteH) -> str:
    """URL única e citável do ato: o PDF gratuito + fragmento da entidade.

    Em Camada A não há URL por-ato (exige metadados da Camada B, SPEC-DRE §2.4/§2.6), pelo
    que a chave natural é o PDF integral gratuito (real, verificável) + ``#<slug>`` da
    entidade — único por (edição, município) e estável para a idempotência (`url` UNIQUE).
    """
    return f"{url_pdf_gratuito(data, edicao)}#{_slug(seccao.cabecalho)}"


def _titulo_da_seccao(seccao: SeccaoParteH) -> str:
    """Título do ato: as linhas do bloco da entidade sem o cabeçalho, colapsadas.

    Para "MUNICÍPIO DE BRAGA / Regulamento n.º 927/2025 / Regulamento Municipal de
    Alojamento Local …" devolve "Regulamento n.º 927/2025 Regulamento Municipal de
    Alojamento Local …". Vazio → recai no próprio cabeçalho (nunca fica sem título).
    """
    cabecalho = seccao.cabecalho.strip()
    linhas = [ln.strip() for ln in seccao.texto.splitlines()]
    corpo = [ln for ln in linhas if ln and ln != cabecalho]
    titulo = re.sub(r"\s+", " ", " ".join(corpo)).strip()
    return (titulo or cabecalho)[:TITULO_MAX_CHARS]


def _excerto_do_ato(texto_completo: str, seccao: SeccaoParteH) -> str:
    """Excerto do ato para a IA: o corpo localizado pela âncora da entidade, ou o sumário.

    A entidade (``MUNICÍPIO DE …``) reaparece no corpo do ato (rodapé de cada página —
    âncora VERIFICADA, SPEC-DRE §2.2). Se houver ≥2 ocorrências no texto integral, a última
    marca o corpo → devolve-se uma janela a partir daí (com coimas/prazos, se existirem).
    Com uma só ocorrência (só sumário), devolve-se o bloco do sumário — o que temos, sem
    inventar. A validação anti-alucinação (:mod:`app.ia.validacao`) fundamenta o alerta
    contra este excerto, pelo que um excerto mais pobre só torna o alerta mais conservador.
    """
    ocorrencias = [m.start() for m in re.finditer(re.escape(seccao.cabecalho), texto_completo)]
    if len(ocorrencias) >= 2:
        inicio = ocorrencias[-1]
        return texto_completo[inicio : inicio + EXCERTO_MAX_CHARS].strip()
    return seccao.texto.strip()


# ==========================================================================
#  Persistência de um evento (idempotente por url)
# ==========================================================================
def _obter_ou_criar_evento(
    session: Any,
    *,
    data: date,
    edicao: int,
    publicado_em: date,
    seccao: SeccaoParteH,
    concelhos: list[str],
    texto_completo: str,
) -> EventoRegulatorio | None:
    """Get-or-create de um `eventos_regulatorios` pela `url` (UNIQUE).

    Devolve o evento **novo** criado, ou ``None`` se já existia (idempotência). Em ambos os
    casos anexa o excerto do ato em `.texto` (em memória) para a camada IA da mesma sessão.
    """
    url = _url_evento(data, edicao, seccao)
    excerto = _excerto_do_ato(texto_completo, seccao)

    existente = (
        session.query(EventoRegulatorio).filter(EventoRegulatorio.url == url).first()
    )
    if existente is not None:
        existente.texto = excerto  # em memória: dá corpo ao pipeline se correr na mesma sessão
        return None

    evento = EventoRegulatorio(
        fonte=FONTE_DRE,
        url=url,
        titulo=_titulo_da_seccao(seccao),
        publicado_em=publicado_em,
        concelhos=list(concelhos),
        triagem=None,
        processado=False,
    )
    session.add(evento)
    session.flush()  # materializa o id (origem_id dos alertas) e fixa a url UNIQUE
    evento.texto = excerto
    return evento


# ==========================================================================
#  Núcleo da corrida
# ==========================================================================
def _correr(
    session: Any,
    cliente_http: Any,
    data: date,
    edicao_inicial: int,
    max_edicoes: int,
) -> ResultadoDRE:
    resultado = ResultadoDRE()
    edicao = edicao_inicial

    for _ in range(max_edicoes):
        url_pdf = url_pdf_gratuito(data, edicao)
        pdf = descarregar_pdf(url_pdf, cliente_http=cliente_http)
        if pdf is None:
            break  # 404/não-PDF = "ainda não publicado" → pára (normal, sem aviso)

        texto = extrair_texto(pdf)
        cabecalho = _cabecalho_edicao(texto)
        if cabecalho is None:
            resultado.avisos.append(
                f"Edição {edicao}: cabeçalho da página 1 ilegível — rever manualmente "
                "(possível drift de layout)."
            )
            break
        numero, publicado_em = cabecalho
        if numero != edicao:
            # A página diz outro número → salto/suplemento (SPEC-DRE §3.2/R1/R2): pára e avisa.
            resultado.avisos.append(
                f"Edição {edicao}: a página 1 diz N.º {numero} — possível salto ou "
                "suplemento; a corrida parou para revisão do dono."
            )
            break

        seccoes = extrair_parte_H(texto)
        if not seccoes and grep_al(SeccaoParteH(cabecalho="", texto=texto)):
            # Keyword de AL no corpo mas sem Parte H no sumário → drift (SPEC-DRE R6).
            resultado.avisos.append(
                f"Edição {edicao}: keyword de AL no corpo mas Parte H não isolada no "
                "sumário — rever (drift de layout)."
            )

        for seccao in seccoes:
            if not grep_al(seccao):
                continue
            concelhos = concelhos_de(seccao)
            if not concelhos:
                resultado.avisos.append(
                    f"Edição {edicao}: '{seccao.cabecalho}' regula AL mas o concelho não "
                    "foi reconhecido — evento criado sem concelho, para revisão do dono."
                )
            evento = _obter_ou_criar_evento(
                session,
                data=data,
                edicao=edicao,
                publicado_em=publicado_em,
                seccao=seccao,
                concelhos=concelhos,
                texto_completo=texto,
            )
            if evento is not None:
                resultado.eventos.append(evento)

        resultado.edicoes.append(edicao)
        edicao += 1

    session.flush()
    return resultado


# ==========================================================================
#  API pública
# ==========================================================================
def correr_dre(
    session: Any,
    *,
    cliente_http: Any | None = None,
    data: date | None = None,
    edicao_inicial: int | None = None,
    max_edicoes: int = MAX_EDICOES_POR_CORRIDA,
) -> ResultadoDRE:
    """Corre a ingestão do DRE (Camada A) e materializa `eventos_regulatorios`.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy **de quem chama** (sob `db.get_session`). Esta função não abre
        sessão nem faz commit — a transação é do orquestrador, o que permite a passagem em
        memória do excerto para a camada IA na mesma sessão.
    cliente_http:
        Cliente HTTP **injetado** (dublê nos testes; qualquer objeto com ``.get(url)``).
        ``None`` → compõe-se via :func:`obter_cliente_http` (LIVE-GATED: sob modo de teste
        devolve ``None`` e a corrida sai sem tocar a rede, com um aviso).
    data:
        Data de referência (ano/mês do caminho do PDF). ``None`` → hoje.
    edicao_inicial:
        Seed do contador auto-corretivo — a 1.ª edição a tentar. ``None`` →
        :data:`EDICAO_INICIAL_PADRAO`.
    max_edicoes:
        Teto de edições a processar numa corrida (defensivo).

    Devolve um :class:`ResultadoDRE`. Idempotente: re-correr não duplica eventos (`url`
    UNIQUE). Erros de transporte (timeout/rede) **propagam** — o retry/alerta vive no cron.
    """
    data = data or date.today()
    edicao_inicial = (
        int(edicao_inicial) if edicao_inicial is not None else EDICAO_INICIAL_PADRAO
    )

    if cliente_http is not None:
        return _correr(session, cliente_http, data, edicao_inicial, max_edicoes)

    proprio = obter_cliente_http()
    if proprio is None:
        return ResultadoDRE(
            avisos=[
                "cliente_http indisponível (modo de teste ou sem transporte): a ingestão "
                "do DRE não corre e nada toca a rede."
            ]
        )
    try:
        return _correr(session, proprio, data, edicao_inicial, max_edicoes)
    finally:
        proprio.close()
