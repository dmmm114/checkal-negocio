"""Testes do adaptador TOConline (swap de faturação) — fatura-recibo certificada.

Contrato (SPEC-TOCONLINE §0 — drop-in de `invoicexpress_client`):

    emitir_fatura_recibo(*, nome, nif, email, itens, cliente_http, access_token,
                         codigo_cliente=None, dormir=time.sleep) -> FaturaRecibo

Fluxo TOConline (SPEC §1): `POST /api/v1/commercial_sales_documents` (`document_type`
`FR`, JSON:API, **auto-finalizado** — sem `change-state`) → (opcional) comunicar à
AT → `GET .../<id>` para ler ATCUD + `document_hash_sum` + total → `url_for_print`
para o PDF (tolerado se ainda a gerar). Guardas partilhadas de `base.py`:
  - **G2** — `atcud` vazio/"N/D"/"N/A" ou `saft_hash` ausente → `FaturaNaoCertificada`.
  - **G3** — `total` devolvido ≠ `total_esperado(itens)` → `TotalInesperado`.
  - **Guarda extra** — `TOCONLINE_SERIES_ID` **e** `TOCONLINE_SERIES_PREFIX` ambos
    vazios → `SerieNaoConfigurada` (não emitir sem série; falha ANTES de tocar na rede).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** chamadas HTTP reais —
o `cliente_http` é INJETADO/MOCKADO (`FakeCliente`) e o `access_token` também é
injetado (o módulo não conhece OAuth). O `dormir` é neutralizado. As base URLs e a
série vêm de `config` (por-conta, vazias por omissão): monkeypatch nos testes.
Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config
from app.faturacao import base
from app.faturacao import toconline_client as toc


# ==========================================================================
#  Duplos de teste: cliente HTTP falso (nunca há rede) + respostas scriptadas
# ==========================================================================
class FakeResposta:
    """Resposta HTTP mínima à laia de `httpx.Response` (status + JSON + raise)."""

    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeCliente:
    """Router de respostas por (método, URL). Regista as chamadas p/ asserções.

    - `POST  …/commercial_sales_documents`         → `criar`
    - `POST  …/send_document_at_webservice`        → `at_comm`
    - `GET   …/commercial_sales_documents/<id>`    → `detalhes`
    - `GET   …/url_for_print/<id>`                 → `pdf` (None ⇒ 404, a gerar)
    """

    def __init__(self, *, criar, detalhes, pdf=None, at_comm=None):
        self.criar = criar
        self.detalhes = detalhes
        self.pdf = pdf
        self.at_comm = at_comm or FakeResposta(200, {"data": {"attributes": {"communication_status": "OK"}}})
        self.chamadas: list[tuple[str, str, dict]] = []

    def post(self, url, **kw):
        self.chamadas.append(("POST", url, kw))
        if "send_document_at_webservice" in url:
            return self.at_comm
        return self.criar

    def get(self, url, **kw):
        self.chamadas.append(("GET", url, kw))
        if "url_for_print" in url:
            return self.pdf if self.pdf is not None else FakeResposta(404, {})
        return self.detalhes

    def patch(self, url, **kw):  # pragma: no cover - só se a AT usar PATCH
        self.chamadas.append(("PATCH", url, kw))
        return self.at_comm


# --- Fábricas de payloads JSON:API canónicos (id "55", plano anual 49,00 €) ---
ID_DOC = "55"
ITENS_ANUAL = [
    {
        "nome": "CheckAL Anual",
        "descricao": "Subscrição de monitorização RNAL — 12 meses",
        "preco": 49.0,   # IVA incluído (PLANOS["anual"]["preco"])
        "quantidade": 1,
    }
]


def _envelope(doc_id, attrs):
    return {"data": {"type": "commercial_sales_documents", "id": doc_id, "attributes": attrs}}


def _resp_criar(doc_id=ID_DOC, document_no="FR 2026/1", saft_hash="a1b2c3d4e5"):
    return FakeResposta(201, _envelope(doc_id, {
        "document_no": document_no,
        "document_hash_sum": saft_hash,
        "hash_control": "1",
    }))


def _resp_detalhes(*, doc_id=ID_DOC, total=49.0, atcud="AAJF7-1", saft_hash="a1b2c3d4e5",
                   document_no="FR 2026/1", atcud_prefix=None, permalink="https://app.toconline.pt/i/55",
                   status="finalizado", **extra):
    attrs = {
        "document_no": document_no,
        "total": total,
        "document_hash_sum": saft_hash,
        "permalink": permalink,
        "status": status,
    }
    if atcud is not None:
        attrs["atcud"] = atcud
    if atcud_prefix is not None:
        attrs["atcud_prefix"] = atcud_prefix
    attrs.update(extra)
    return FakeResposta(200, _envelope(doc_id, attrs))


def _resp_pdf(scheme="https", host="app.toconline.pt", path="/public-file/xyz.pdf"):
    return FakeResposta(200, {"scheme": scheme, "host": host, "path": path})


def _cliente(**over):
    base_kw = dict(
        criar=_resp_criar(),
        detalhes=_resp_detalhes(),
        pdf=_resp_pdf(),
    )
    base_kw.update(over)
    return FakeCliente(**base_kw)


@pytest.fixture()
def serie(monkeypatch):
    """Série CKL configurada por id (o caso normal: o Diogo dá o id numérico)."""
    monkeypatch.setattr(config, "TOCONLINE_SERIES_ID", "777")
    monkeypatch.setattr(config, "TOCONLINE_SERIES_PREFIX", "")


def _emitir(cli, **over):
    kw = dict(
        nome="Titular do AL",
        nif="508000000",
        email="cliente@exemplo.pt",
        itens=ITENS_ANUAL,
        cliente_http=cli,
        access_token="tok-access-abc",
        dormir=lambda _s: None,
    )
    kw.update(over)
    return toc.emitir_fatura_recibo(**kw)


# ==========================================================================
#  Fronteira partilhada — mesmas guardas/objetos de base.py (swap não parte nada)
# ==========================================================================
def test_reexporta_a_mesma_fatura_recibo():
    assert toc.FaturaRecibo is base.FaturaRecibo


def test_reexporta_as_mesmas_guardas():
    assert toc.FaturaNaoCertificada is base.FaturaNaoCertificada
    assert toc.TotalInesperado is base.TotalInesperado


def test_erro_toconline_partilha_a_base():
    # `except ErroTOConline` legado apanha as guardas partilhadas (qualquer adaptador).
    assert issubclass(base.FaturaNaoCertificada, toc.ErroTOConline)
    assert issubclass(base.TotalInesperado, toc.ErroTOConline)


def test_serie_nao_configurada_e_erro_faturacao():
    assert issubclass(toc.SerieNaoConfigurada, base.ErroFaturacao)


# ==========================================================================
#  Happy path — fluxo completo devolve FaturaRecibo certificada
# ==========================================================================
def test_happy_path_devolve_fatura_certificada(serie):
    cli = _cliente()
    fatura = _emitir(cli)

    assert isinstance(fatura, toc.FaturaRecibo)
    assert dataclasses.is_dataclass(fatura)
    assert fatura.id == ID_DOC
    assert fatura.sequence_number == "FR 2026/1"   # <- document_no
    assert fatura.atcud == "AAJF7-1"
    assert fatura.saft_hash == "a1b2c3d4e5"         # <- document_hash_sum
    assert fatura.total == pytest.approx(49.0, abs=0.005)
    assert fatura.estado == "finalizado"
    assert fatura.pdf_url == "https://app.toconline.pt/public-file/xyz.pdf"


def test_happy_path_corpo_jsonapi_fr_serie_e_cliente(serie):
    cli = _cliente()
    _emitir(cli)
    metodo, url, kw = cli.chamadas[0]
    assert metodo == "POST" and url.endswith("/api/v1/commercial_sales_documents")

    corpo = kw["json"]
    # Wrapper JSON:API (data/type/attributes), não root "invoice"
    assert corpo["data"]["type"] == "commercial_sales_documents"
    attrs = corpo["data"]["attributes"]
    assert attrs["document_type"] == "FR"           # fatura-recibo
    # Série referenciada pelo id numérico do config
    assert attrs["document_series_id"] == 777
    # Cliente (nome, NIF, email)
    assert attrs["customer_business_name"] == "Titular do AL"
    assert attrs["customer_tax_registration_number"] == "508000000"


def test_happy_path_linha_preco_liquido_e_iva_23(serie):
    # SPEC §5 (opção líquida, escolhida): unit_price LÍQUIDO (39,84) + IVA 23%,
    # com vat_included_prices=false ⇒ o total volta a 49,00 € (guarda G3 reaproveita
    # total_esperado 1:1 tal como na IX).
    cli = _cliente()
    _emitir(cli)
    attrs = cli.chamadas[0][2]["json"]["data"]["attributes"]
    assert attrs["vat_included_prices"] is False
    linha = attrs["lines"][0]
    assert linha["unit_price"] == 39.84
    assert linha["tax_percentage"] == 23


def test_headers_levam_bearer_e_content_type_jsonapi(serie):
    # O access_token é INJETADO e vai no header Authorization: Bearer; Content-Type
    # é o do JSON:API. (LIVE-GATED: o módulo não conhece OAuth.)
    cli = _cliente()
    _emitir(cli, access_token="tok-XYZ")
    headers = cli.chamadas[0][2]["headers"]
    assert headers["Authorization"] == "Bearer tok-XYZ"
    assert headers["Content-Type"] == "application/vnd.api+json"


# ==========================================================================
#  Guarda extra — sem série não se emite (e NÃO se toca na rede)
# ==========================================================================
def test_sem_serie_levanta_serie_nao_configurada(monkeypatch):
    monkeypatch.setattr(config, "TOCONLINE_SERIES_ID", "")
    monkeypatch.setattr(config, "TOCONLINE_SERIES_PREFIX", "")
    cli = _cliente()
    with pytest.raises(toc.SerieNaoConfigurada):
        _emitir(cli)
    # Falhou ANTES de qualquer chamada HTTP (LIVE-GATED).
    assert cli.chamadas == []


def test_serie_por_prefixo_e_aceite(monkeypatch):
    # Alternativa ao id: só o prefixo configurado ⇒ document_series_prefix no corpo.
    monkeypatch.setattr(config, "TOCONLINE_SERIES_ID", "")
    monkeypatch.setattr(config, "TOCONLINE_SERIES_PREFIX", "CKL")
    cli = _cliente()
    fatura = _emitir(cli)
    assert fatura.atcud == "AAJF7-1"
    attrs = cli.chamadas[0][2]["json"]["data"]["attributes"]
    assert attrs["document_series_prefix"] == "CKL"
    assert "document_series_id" not in attrs


# ==========================================================================
#  GUARDA G2 — sem certificação AT não devolve fatura "boa"
# ==========================================================================
def test_g2_sem_atcud_levanta_fatura_nao_certificada(serie):
    # Documento sem ATCUD (nem campo direto nem atcud_prefix p/ compor) → não é "boa".
    cli = _cliente(detalhes=_resp_detalhes(atcud=None, atcud_prefix=None))
    with pytest.raises(toc.FaturaNaoCertificada):
        _emitir(cli)


def test_g2_atcud_nd_levanta_fatura_nao_certificada(serie):
    cli = _cliente(detalhes=_resp_detalhes(atcud="N/D"))
    with pytest.raises(toc.FaturaNaoCertificada):
        _emitir(cli)


def test_g2_saft_hash_ausente_levanta_fatura_nao_certificada(serie):
    cli = _cliente(detalhes=_resp_detalhes(saft_hash=""))
    with pytest.raises(toc.FaturaNaoCertificada):
        _emitir(cli)


def test_g2_atcud_composto_de_prefix_e_sequencial(serie):
    # Se o documento não trouxer ATCUD completo mas trouxer atcud_prefix + document_no,
    # o adaptador compõe `prefix-sequencial` (SPEC §4.2, opção 2) e passa a G2.
    cli = _cliente(detalhes=_resp_detalhes(atcud=None, atcud_prefix="AAJF7", document_no="FR 2026/9"))
    fatura = _emitir(cli)
    assert fatura.atcud == "AAJF7-9"


# ==========================================================================
#  GUARDA G3 — total devolvido tem de bater certo (IVA 23% incl.)
# ==========================================================================
def test_g3_total_errado_levanta_total_inesperado(serie):
    # Taxa mal aplicada ⇒ API devolve a base 39,84 em vez de 49,00. Tem de rebentar.
    cli = _cliente(detalhes=_resp_detalhes(total=39.84))
    with pytest.raises(toc.TotalInesperado):
        _emitir(cli)


def test_g3_total_certo_nao_rebenta(serie):
    cli = _cliente(detalhes=_resp_detalhes(total=49.0))
    fatura = _emitir(cli)
    assert fatura.total == pytest.approx(49.0, abs=0.005)


# ==========================================================================
#  PDF — url_for_print concatena componentes; ausência não impede certificação
# ==========================================================================
def test_pdf_ausente_nao_impede_certificacao(serie):
    # PDF ainda a gerar (url_for_print devolve 404): pdf_url None mas fatura certificada.
    cli = _cliente(pdf=None)
    fatura = _emitir(cli)
    assert fatura.pdf_url is None
    assert fatura.atcud == "AAJF7-1"
    assert fatura.total == pytest.approx(49.0, abs=0.005)


# ==========================================================================
#  Ordem do fluxo: criar → ler detalhes → PDF (sem passo de finalização)
# ==========================================================================
def test_ordem_das_chamadas_sem_change_state(serie):
    cli = _cliente()
    _emitir(cli)
    metodos = [
        (m, ("pdf" if "url_for_print" in u
             else "det" if u.rstrip("/").endswith(f"/{ID_DOC}")
             else "criar" if u.endswith("/commercial_sales_documents")
             else "outro"))
        for m, u, _ in cli.chamadas
    ]
    assert metodos[0] == ("POST", "criar")           # criar (auto-finalizado)
    # sem PUT/change-state (FR nasce finalizado)
    assert all(m != "PUT" for m, _ in metodos)
    assert ("GET", "det") in metodos                 # ler campos fiscais
    # o PDF é o último passo (não bloqueia a certificação)
    assert metodos[-1] == ("GET", "pdf")


# ==========================================================================
#  Comunicação à AT explícita (config-gated) — só quando a série NÃO comunica auto
# ==========================================================================
def test_at_manual_chama_send_document_at_webservice(serie, monkeypatch):
    monkeypatch.setattr(config, "TOCONLINE_AT_MANUAL", True, raising=False)
    cli = _cliente()
    _emitir(cli)
    at = [c for c in cli.chamadas if "send_document_at_webservice" in c[1]]
    assert len(at) == 1


def test_at_automatica_nao_chama_endpoint(serie):
    # Por omissão (série em comunicação automática) NÃO se chama o endpoint da AT.
    cli = _cliente()
    _emitir(cli)
    at = [c for c in cli.chamadas if "send_document_at_webservice" in c[1]]
    assert at == []
