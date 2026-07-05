"""Adaptador TOConline (Cloudware): emissão de **fatura-recibo certificada** (série CKL).

Fornecedor de faturação **ativo** do CheckAL (o dono usa TOConline no Radar Marca).
Desenhado como **drop-in** de :mod:`app.faturacao.invoicexpress_client`: expõe a
mesma fronteira pública e devolve a mesma :class:`FaturaRecibo`, para que o
fulfillment troque de fornecedor sem tocar em quem chama. Ver `SPEC-TOCONLINE.md`.

Fluxo (SPEC-TOCONLINE §1), **um passo a menos** que a InvoiceXpress (a FR nasce
finalizada — não há `change-state`):

    [1] POST  /api/v1/commercial_sales_documents   → cria a FR (auto-finalizada)
    [2] (opc) POST /send_document_at_webservice     → comunica à AT (só se a série
                                                       NÃO comunicar automaticamente)
    [3] GET   /api/v1/commercial_sales_documents/<id>  → lê ATCUD + document_hash_sum + total
    [4] GET   /api/url_for_print/<id>               → componentes do PDF (tolera 202/ausência)

A dataclass :class:`FaturaRecibo`, a hierarquia de exceções e os helpers de
preço/certificação vivem em :mod:`app.faturacao.base` (tronco partilhado). Este
módulo importa-os e **re-exporta** os nomes históricos deste fornecedor
(`ErroTOConline`, `FaturaRecibo`, `FaturaNaoCertificada`, `TotalInesperado`,
`preco_liquido`, `total_esperado`, `emitir_fatura_recibo`).

Guardas (não devolvem fatura "boa" quando a realidade fiscal falha):
  - **G2 — `FaturaNaoCertificada`**: `atcud` vazio/"N/D"/"N/A" ou `saft_hash`
    (`document_hash_sum`) ausente — sem prova de comunicação à AT (SPEC §4.2).
  - **G3 — `TotalInesperado`**: `total` devolvido diverge do `total_esperado(itens)`
    além de `TOLERANCIA_TOTAL_EUR` (apanha taxa de IVA mal aplicada).
  - **Guarda extra — `SerieNaoConfigurada`**: `config.TOCONLINE_SERIES_ID` **e**
    `config.TOCONLINE_SERIES_PREFIX` ambos vazios — não se emite sem série. Esta
    guarda dispara **antes** de qualquer chamada HTTP (LIVE-GATED preservado).

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria
nenhum cliente HTTP nem conhece OAuth: recebe o `cliente_http` **injetado** (mock
nos testes; `httpx.Client` real só em produção) e o `access_token` **injetado** (a
obtenção/renovação do token — `authorization_code` + `refresh_token`, SPEC §2 —
vive num cron/helper externo). Cada pedido leva `Authorization: Bearer <token>` +
`Content-Type: application/vnd.api+json`. Correr os testes nunca toca a rede.

O `cliente_http` é qualquer objeto à laia de `httpx.Client` com:
  - ``post(url, *, headers=..., json=...) -> resposta``
  - ``get(url, *, headers=..., params=...) -> resposta``
onde `resposta` expõe ``status_code: int``, ``json() -> dict`` e ``raise_for_status()``.
O `dormir` (pausa do PDF) é injetável (neutralizado nos testes).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import app.config as config
from app.faturacao.base import (
    TOLERANCIA_TOTAL_EUR,
    ErroFaturacao,
    FaturaNaoCertificada,
    FaturaRecibo,
    TotalInesperado,
    atcud_valido,
    preco_liquido,
    saft_presente,
    total_esperado,
)

# Compat: o nome histórico da exceção base deste adaptador É a exceção partilhada.
# Um `except ErroTOConline` apanha as guardas G2/G3/série (que descendem de
# `ErroFaturacao`), seja qual for o fornecedor ativo.
ErroTOConline = ErroFaturacao


class SerieNaoConfigurada(ErroFaturacao):
    """Guarda extra: nem `TOCONLINE_SERIES_ID` nem `TOCONLINE_SERIES_PREFIX` definidos.

    Sem uma série registada na AT não se emite fatura-recibo. Dispara **antes** de
    qualquer chamada HTTP (o `cliente_http` nem é tocado).
    """


# Fronteira pública inalterada face à IX: `FaturaRecibo`, guardas e helpers vêm de
# `base` mas continuam acessíveis como `toconline_client.<nome>`.
__all__ = [
    "FaturaRecibo",
    "ErroTOConline",
    "FaturaNaoCertificada",
    "TotalInesperado",
    "SerieNaoConfigurada",
    "preco_liquido",
    "total_esperado",
    "emitir_fatura_recibo",
]

# --- Constantes do fluxo -------------------------------------------------
ESTADO_FINALIZADO = "finalizado"   # os FR nascem finalizados (SPEC §3.1)
ITEM_TIPO = "Service"              # linha de serviço (subscrição)


# ==========================================================================
#  PONTO ÚNICO DE MAPEAMENTO JSON:API  — [ASSUMIDO] até confirmação no Swagger
# --------------------------------------------------------------------------
#  Vários nomes de campo do JSON:API do TOConline ainda NÃO estão confirmados
#  contra o Swagger/uma emissão real (SPEC-TOCONLINE §7). Estão TODOS reunidos
#  AQUI para que, quando o Diogo confirmar, se corrija num ÚNICO sítio sem mexer
#  na lógica do fluxo. Cada linha diz [VERIFICADO] ou [ASSUMIDO/TODO].
# ==========================================================================
TIPO_RECURSO = "commercial_sales_documents"          # [VERIFICADO] recurso JSON:API
DOCUMENT_TYPE_FR = "FR"                              # [VERIFICADO] fatura-recibo

# Atributos ENVIADOS na criação (corpo) ------------------------------------
ATTR_DOCUMENT_TYPE = "document_type"                 # [VERIFICADO]
ATTR_SERIE_ID = "document_series_id"                 # TODO[ASSUMIDO] nome exato (vs commercial_document_series_id)
ATTR_SERIE_PREFIX = "document_series_prefix"         # TODO[ASSUMIDO] alternativa por prefixo
ATTR_DATE = "date"                                   # TODO[ASSUMIDO] formato ISO yyyy-mm-dd (IX usa dd/mm/yyyy)
ATTR_DUE_DATE = "due_date"                           # TODO[ASSUMIDO]
ATTR_CLIENTE_NOME = "customer_business_name"         # [VERIFICADO]
ATTR_CLIENTE_NIF = "customer_tax_registration_number"  # [VERIFICADO]
ATTR_CLIENTE_EMAIL = "customer_email"                # TODO[ASSUMIDO] nome exato
ATTR_CLIENTE_CODIGO = "customer_code"                # TODO[ASSUMIDO] id estável nosso (evita duplicar clientes)
ATTR_VAT_INCLUDED = "vat_included_prices"            # [VERIFICADO campo]
ATTR_LINHAS = "lines"                                # [VERIFICADO]
ATTR_LINHA_TIPO = "item_type"                        # [VERIFICADO]
ATTR_LINHA_DESC = "description"                       # [VERIFICADO]
ATTR_LINHA_QTD = "quantity"                          # [VERIFICADO]
ATTR_LINHA_PRECO = "unit_price"                      # [VERIFICADO]
ATTR_LINHA_TAX_CODE = "tax_code"                     # TODO[ASSUMIDO valor] (confirmar via /taxes)
ATTR_LINHA_TAX_PCT = "tax_percentage"               # [VERIFICADO]

# Campos LIDOS da resposta (create/details) --------------------------------
RESP_DOCUMENT_NO = "document_no"                     # [VERIFICADO] ex. "FR 2026/1" → sequence_number
RESP_SAFT_HASH = "document_hash_sum"                 # [VERIFICADO] hash SAF-T → saft_hash
RESP_TOTAL = "total"                                 # TODO[ASSUMIDO nome] total bruto (guarda G3)
RESP_ATCUD = "atcud"                                 # TODO[ASSUMIDO] ATCUD completo por documento (§4.2)
RESP_ATCUD_PREFIX = "atcud_prefix"                   # [VERIFICADO na série] p/ compor ATCUD
RESP_PERMALINK = "permalink"                         # TODO[ASSUMIDO]
RESP_ESTADO = "status"                               # TODO[ASSUMIDO nome]

# Config sem entrada dedicada ainda (getattr defensivo; o Diogo confirma depois):
#   TOCONLINE_TAX_CODE   → classificação de IVA 23% da linha (SPEC §3.4)
#   TOCONLINE_AT_MANUAL  → True ⇒ comunicar à AT explicitamente (SPEC §3.2/§4.3)
#   TOCONLINE_AT_USERNAME / TOCONLINE_AT_PASSWORD → credenciais do Portal das Finanças
_TAX_CODE_PADRAO = "NOR"


# ==========================================================================
#  Helpers internos
# ==========================================================================
def _api_base() -> str:
    """Base da API JSON:API (por-conta; vem no ficheiro de *Empresa > Dados API*)."""
    return str(config.TOCONLINE_API_URL or "").rstrip("/")


def _headers(access_token: str) -> dict[str, str]:
    """Headers JSON:API + Bearer (o `access_token` é injetado; renovado fora daqui)."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/json",
    }


def _serie_atributos() -> dict[str, Any]:
    """Atributos da série p/ o corpo, ou levanta :class:`SerieNaoConfigurada`.

    Prefere o `id` numérico (`TOCONLINE_SERIES_ID`); em alternativa usa o prefixo
    (`TOCONLINE_SERIES_PREFIX`). Ambos vazios ⇒ não se emite (guarda extra).
    """
    serie_id = str(config.TOCONLINE_SERIES_ID or "").strip()
    prefixo = str(config.TOCONLINE_SERIES_PREFIX or "").strip()
    if not serie_id and not prefixo:
        raise SerieNaoConfigurada(
            "Série TOConline não configurada: define TOCONLINE_SERIES_ID (id numérico "
            "dado pelo dono após criar a série CKL na UI) ou TOCONLINE_SERIES_PREFIX."
        )
    if serie_id:
        return {ATTR_SERIE_ID: int(serie_id) if serie_id.isdigit() else serie_id}
    return {ATTR_SERIE_PREFIX: prefixo}


def _atributos(payload: Any) -> dict:
    """Achata um recurso JSON:API (`{"data":{"id","attributes":{…}}}`) num dict.

    Devolve os `attributes` com o `id` do recurso injetado (chave ``"id"``). Aceita
    `data` como objeto ou lista (usa o 1.º). Tolerante a payloads já achatados.
    """
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {}
    attrs = data.get("attributes")
    achatado = dict(attrs) if isinstance(attrs, dict) else {k: v for k, v in data.items() if k != "attributes"}
    if data.get("id") is not None:
        achatado.setdefault("id", data.get("id"))
    return achatado


def _sequencial_de(document_no: Any) -> str:
    """Extrai o nº sequencial de um `document_no` (ex. ``"FR 2026/1"`` → ``"1"``)."""
    texto = str(document_no or "").strip()
    if not texto:
        return ""
    return texto.rsplit("/", 1)[-1].strip()


def _ler_atcud(attrs: Mapping[str, Any]) -> str:
    """ATCUD do documento: campo direto se existir, senão composto (SPEC §4.2).

    1) Se a resposta trouxer o ATCUD completo (`RESP_ATCUD`) → usa-o.
    2) Senão, compõe ``atcud_prefix + "-" + sequencial`` (o `atcud_prefix` só está
       preenchido quando a série está registada na AT — que é, em si, a prova que
       a guarda G2 quer). Sem prefixo válido → devolve ``""`` (G2 rebenta).
    """
    direto = str(attrs.get(RESP_ATCUD) or "").strip()
    if direto:
        return direto
    prefixo = str(attrs.get(RESP_ATCUD_PREFIX) or "").strip()
    sequencial = _sequencial_de(attrs.get(RESP_DOCUMENT_NO))
    if prefixo and sequencial:
        return f"{prefixo}-{sequencial}"
    return ""


def _extrair_pdf_url(payload: Any) -> str | None:
    """Concatena os componentes de `url_for_print` (scheme+host+path) no link do PDF.

    Tolera variantes: componentes achatados, sob `data.attributes`, ou um campo de
    URL já pronto (`url`/`public_url`/`permalink`). Devolve ``None`` se nada servir.
    """
    attrs = _atributos(payload) if isinstance(payload, dict) else {}
    for fonte in (payload if isinstance(payload, dict) else {}, attrs):
        if not isinstance(fonte, dict):
            continue
        scheme = str(fonte.get("scheme") or "").strip()
        host = str(fonte.get("host") or "").strip()
        path = str(fonte.get("path") or "").strip()
        if scheme and host and path:
            return f"{scheme}://{host}{path if path.startswith('/') else '/' + path}"
        for chave in ("url", "public_url", "pdf_url", "permalink"):
            if fonte.get(chave):
                return str(fonte[chave])
    return None


# ==========================================================================
#  Passos do fluxo
# ==========================================================================
def _corpo_criar(
    *, nome: str, nif: str, email: str,
    itens: Sequence[Mapping[str, Any]], codigo_cliente: str,
    serie: Mapping[str, Any],
) -> dict:
    """Monta o corpo JSON:API de criação da FR.

    SPEC §5 (opção líquida, escolhida): `unit_price` **líquido** (`preco_liquido`) +
    `tax_percentage` 23 com `vat_included_prices=false` — assim o total volta ao
    preço de tabela (49,00 €) e a guarda G3 reaproveita `total_esperado` 1:1 como
    na IX. `tax_code` sai de `config` (default "NOR"; confirmar via `/taxes`).
    """
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # ISO (§3.1) TODO confirmar formato
    tax_code = str(getattr(config, "TOCONLINE_TAX_CODE", _TAX_CODE_PADRAO) or _TAX_CODE_PADRAO)
    linhas = [
        {
            ATTR_LINHA_TIPO: ITEM_TIPO,
            ATTR_LINHA_DESC: it.get("descricao") or it["nome"],
            ATTR_LINHA_QTD: int(it.get("quantidade", 1)),
            ATTR_LINHA_PRECO: preco_liquido(float(it["preco"])),
            ATTR_LINHA_TAX_CODE: tax_code,
            ATTR_LINHA_TAX_PCT: int(round(config.IVA * 100)),
        }
        for it in itens
    ]
    atributos: dict[str, Any] = {
        ATTR_DOCUMENT_TYPE: DOCUMENT_TYPE_FR,
        ATTR_DATE: hoje,
        ATTR_DUE_DATE: hoje,
        ATTR_CLIENTE_NOME: nome,
        ATTR_CLIENTE_NIF: nif,
        ATTR_CLIENTE_EMAIL: email,
        ATTR_CLIENTE_CODIGO: codigo_cliente,
        ATTR_VAT_INCLUDED: False,
        ATTR_LINHAS: linhas,
    }
    atributos.update(serie)
    return {"data": {"type": TIPO_RECURSO, "attributes": atributos}}


def _comunicar_at(cliente_http: Any, doc_id: str, *, access_token: str) -> None:
    """Comunica o documento à AT por webservice (SPEC §3.2), se `TOCONLINE_AT_MANUAL`.

    Só é preciso quando a série **não** está em comunicação automática (o normal é
    ser automática ⇒ este passo salta-se). `entity_username`/`entity_password` do
    Portal das Finanças vêm de `config` (a confirmar/dar pelo dono).
    """
    corpo = {
        "data": {
            "type": "send_document_at_webservice",
            "id": doc_id,
            "attributes": {
                "document_type": "sales_document",
                "entity_username": str(getattr(config, "TOCONLINE_AT_USERNAME", "") or ""),
                "entity_password": str(getattr(config, "TOCONLINE_AT_PASSWORD", "") or ""),
            },
        }
    }
    resposta = cliente_http.post(
        f"{_api_base()}/send_document_at_webservice",
        headers=_headers(access_token),
        json=corpo,
    )
    resposta.raise_for_status()


def _obter_pdf_url(
    cliente_http: Any, doc_id: str, *, access_token: str, dormir: Callable[[float], None]
) -> str | None:
    """GET a `url_for_print`; concatena os componentes no link do PDF (SPEC §3.5).

    Não bloqueia a certificação: qualquer falha/ausência (PDF ainda a gerar,
    404/202, erro) devolve ``None`` — o PDF é só para anexar ao email (FDS 3).
    `dormir` fica disponível para um eventual polling futuro.
    """
    try:
        resposta = cliente_http.get(
            f"{_api_base()}/api/url_for_print/{doc_id}",
            headers=_headers(access_token),
            params={"filter[type]": "Document", "filter[copies]": 1},
        )
        if resposta.status_code >= 300:
            return None
        return _extrair_pdf_url(resposta.json())
    except Exception:  # noqa: BLE001 — o PDF nunca derruba a emissão certificada
        return None


# ==========================================================================
#  API pública
# ==========================================================================
def emitir_fatura_recibo(
    *,
    nome: str,
    nif: str,
    email: str,
    itens: Sequence[Mapping[str, Any]],
    cliente_http: Any,
    access_token: str,
    codigo_cliente: str | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> FaturaRecibo:
    """Emite uma fatura-recibo (FR) certificada via TOConline, ou levanta uma guarda.

    Drop-in de :func:`app.faturacao.invoicexpress_client.emitir_fatura_recibo` — mesma
    semântica, mesmas guardas, mesmo :class:`FaturaRecibo` — mas via TOConline
    (JSON:API, FR auto-finalizada, Bearer injetado).

    Parâmetros
    ----------
    nome, nif, email:
        Dados fiscais do cliente (`nif` → `customer_tax_registration_number`).
    itens:
        Sequência de dicts ``{"nome", "preco" (IVA incl.), "quantidade"?, "descricao"?}``.
    cliente_http:
        Cliente HTTP **injetado** (mock nos testes; nunca criado aqui — LIVE-GATED).
    access_token:
        Bearer OAuth2 **injetado** (renovação num cron externo; o módulo não faz OAuth).
    codigo_cliente:
        Id estável do cliente (evita duplicá-lo na conta); por omissão deriva do NIF.
    dormir:
        Pausa (PDF); neutralizada nos testes.

    Levanta
    -------
    SerieNaoConfigurada
        Guarda extra — série não configurada (dispara antes de qualquer HTTP).
    FaturaNaoCertificada
        Guarda G2 — sem ATCUD/saft_hash (documento não comunicado à AT).
    TotalInesperado
        Guarda G3 — total devolvido diverge do esperado (IVA 23% incl.).
    ErroTOConline
        Resposta de criação sem `id`.
    """
    # [guarda extra] série — falha ANTES de tocar na rede (LIVE-GATED)
    serie = _serie_atributos()

    codigo = codigo_cliente or f"checkal-{nif}"
    headers = _headers(access_token)

    # [1] criar FR (nasce finalizada — sem change-state)
    r_criar = cliente_http.post(
        f"{_api_base()}/api/v1/commercial_sales_documents",
        headers=headers,
        json=_corpo_criar(
            nome=nome, nif=nif, email=email, itens=itens,
            codigo_cliente=codigo, serie=serie,
        ),
    )
    r_criar.raise_for_status()
    doc_id = str(_atributos(r_criar.json()).get("id", "") or "")
    if not doc_id:
        raise ErroTOConline("Resposta de criação da fatura-recibo (TOConline) sem `id`.")

    # [2] comunicar à AT (só se a série não comunicar automaticamente)
    if bool(getattr(config, "TOCONLINE_AT_MANUAL", False)):
        _comunicar_at(cliente_http, doc_id, access_token=access_token)

    # [3] ler campos fiscais (ATCUD, saft_hash, total, sequência, permalink, estado)
    r_det = cliente_http.get(
        f"{_api_base()}/api/v1/commercial_sales_documents/{doc_id}",
        headers=headers,
        params={},
    )
    r_det.raise_for_status()
    det = _atributos(r_det.json())

    atcud = _ler_atcud(det)
    saft_hash = det.get(RESP_SAFT_HASH)

    # [4] PDF (concatena componentes de url_for_print; não bloqueia a certificação)
    pdf_url = _obter_pdf_url(cliente_http, doc_id, access_token=access_token, dormir=dormir)

    # GUARDA G2 — certificação AT
    if not atcud_valido(atcud) or not saft_presente(saft_hash):
        raise FaturaNaoCertificada(
            f"Fatura {doc_id} (TOConline) sem certificação AT "
            f"(atcud={atcud!r}, saft_hash={'presente' if saft_presente(saft_hash) else 'ausente'}).",
            doc_id=doc_id,
        )

    # GUARDA G3 — total tem de bater certo (IVA 23% incl.)
    total_devolvido = float(det.get(RESP_TOTAL) or 0.0)
    esperado = total_esperado(itens)
    if abs(total_devolvido - esperado) > TOLERANCIA_TOTAL_EUR:
        raise TotalInesperado(
            f"Fatura {doc_id} (TOConline): total devolvido {total_devolvido:.2f} € "
            f"!= esperado {esperado:.2f} € (taxa de IVA mal aplicada?).",
            doc_id=doc_id,
        )

    return FaturaRecibo(
        id=doc_id,
        sequence_number=str(det.get(RESP_DOCUMENT_NO, "") or ""),
        atcud=str(atcud),
        saft_hash=str(saft_hash),
        total=total_devolvido,
        permalink=str(det.get(RESP_PERMALINK, "") or ""),
        pdf_url=pdf_url,
        estado=str(det.get(RESP_ESTADO, ESTADO_FINALIZADO) or ESTADO_FINALIZADO),
    )
