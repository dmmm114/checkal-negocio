"""Testes do adaptador InvoiceXpress (FDS 2) — emissão de fatura-recibo certificada.

Contrato (SPEC-FDS2 §invoicexpress_client + faturacao/SPEC-INVOICEXPRESS.md):

    emitir_fatura_recibo(*, nome, nif, email, itens, cliente_http) -> FaturaRecibo

Fluxo: criar `invoice_receipt` → `change-state` `finalized` → obter PDF (tolera
202→polling) → ler ATCUD + saft_hash. Guardas:
  - **G2** — `atcud` vazio/"N/D"/"N/A" ou `saft_hash` ausente → `FaturaNaoCertificada`.
  - **G3** — `total` devolvido ≠ total esperado (IVA 23% incl.) → `TotalInesperado`.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** chamadas HTTP reais —
o `cliente_http` é INJETADO/MOCKADO (`FakeCliente`). O `dormir` do polling é
neutralizado. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config
from app.faturacao import invoicexpress_client as ix


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
    """Router de respostas por (método, caminho). Regista as chamadas p/ asserções.

    - `POST  …/invoice_receipts.json`            → `criar`
    - `PUT   …/change-state.json`                → `finalizar`
    - `GET   …/api/pdf/:id.json`                 → fila `pdf` (202… depois 200)
    - `GET   …/invoice_receipts/:id.json`        → `detalhes`
    """

    def __init__(self, *, criar, finalizar, pdf, detalhes):
        self.criar = criar
        self.finalizar = finalizar
        self.pdf = list(pdf)
        self.detalhes = detalhes
        self.chamadas: list[tuple[str, str, dict]] = []

    def post(self, url, **kw):
        self.chamadas.append(("POST", url, kw))
        return self.criar

    def put(self, url, **kw):
        self.chamadas.append(("PUT", url, kw))
        return self.finalizar

    def get(self, url, **kw):
        self.chamadas.append(("GET", url, kw))
        if "/api/pdf/" in url:
            resp = self.pdf[0]
            if len(self.pdf) > 1:  # consome os 202 e retém o 200 final
                self.pdf.pop(0)
            return resp
        return self.detalhes


# --- Fábricas de payloads canónicos (id 998877, plano anual 49,00 €) ------
ID_DOC = 998877
ITENS_ANUAL = [
    {
        "nome": "CheckAL Anual",
        "descricao": "Subscrição de monitorização RNAL — 12 meses",
        "preco": 49.0,   # IVA incluído (PLANOS["anual"]["preco"])
        "quantidade": 1,
    }
]


def _resp_criar(status=201, estado="draft"):
    return FakeResposta(status, {"invoice_receipt": {"id": ID_DOC, "status": estado}})


def _resp_finalizar():
    return FakeResposta(200, {"invoice_receipt": {"id": ID_DOC, "status": "finalized"}})


def _resp_pdf_pronto():
    return FakeResposta(200, {"output": {"pdfUrl": "https://ix.example/pdf/998877.pdf"}})


def _resp_pdf_a_gerar():
    return FakeResposta(202, {})


def _resp_detalhes(*, total=49.0, atcud="ABCD1234-6", saft_hash="a1b2c3d4e5", **extra):
    corpo = {
        "id": ID_DOC,
        "status": "finalized",
        "sequence_number": "6/CKL",
        "total": total,
        "atcud": atcud,
        "saft_hash": saft_hash,
        "permalink": "https://cosmicoasis.app.invoicexpress.com/i/xyz",
    }
    corpo.update(extra)
    return FakeResposta(200, {"invoice_receipt": corpo})


def _cliente(**over):
    base = dict(
        criar=_resp_criar(),
        finalizar=_resp_finalizar(),
        pdf=[_resp_pdf_pronto()],
        detalhes=_resp_detalhes(),
    )
    base.update(over)
    return FakeCliente(**base)


# ==========================================================================
#  Helpers de preço/total (§5 da SPEC-INVOICEXPRESS)
# ==========================================================================
def test_preco_liquido_49_da_39_84():
    # 49,00 € IVA incl. → 39,84 € líquido (base sobre a qual a API aplica IVA23)
    assert ix.preco_liquido(49.0) == 39.84


def test_total_esperado_de_um_item_da_49():
    # base 39,84 + IVA(23%) 9,16 = 49,00 € (o total que a fatura tem de devolver)
    assert ix.total_esperado(ITENS_ANUAL) == pytest.approx(49.0, abs=0.005)


# ==========================================================================
#  Happy path — fluxo completo devolve FaturaRecibo certificada
# ==========================================================================
def test_happy_path_devolve_fatura_certificada():
    cli = _cliente()
    fatura = ix.emitir_fatura_recibo(
        nome="Titular do AL",
        nif="508000000",
        email="cliente@exemplo.pt",
        itens=ITENS_ANUAL,
        cliente_http=cli,
        dormir=lambda _s: None,
    )

    assert isinstance(fatura, ix.FaturaRecibo)
    assert dataclasses.is_dataclass(fatura)
    assert fatura.id == str(ID_DOC)
    assert fatura.sequence_number == "6/CKL"
    assert fatura.atcud == "ABCD1234-6"
    assert fatura.saft_hash == "a1b2c3d4e5"
    assert fatura.total == pytest.approx(49.0, abs=0.005)
    assert fatura.permalink.endswith("/i/xyz")
    assert fatura.pdf_url == "https://ix.example/pdf/998877.pdf"
    assert fatura.estado == "finalized"


def test_happy_path_envia_preco_liquido_e_taxa_iva23():
    # O corpo de criação leva unit_price LÍQUIDO (39,84) e a taxa nomeada IVA23,
    # para a API calcular o IVA e chegar aos 49,00 € (gotcha §8 da SPEC).
    cli = _cliente()
    ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
    )
    metodo, url, kw = cli.chamadas[0]
    assert metodo == "POST" and url.endswith("/invoice_receipts.json")
    corpo = kw["json"]["invoice"]
    item = corpo["items"][0]
    assert item["unit_price"] == 39.84
    assert item["tax"]["name"] == config.INVOICEXPRESS_TAXA_NOME == "IVA23"
    # NIF do cliente vai em fiscal_id
    assert corpo["client"]["fiscal_id"] == "508000000"


def test_happy_path_finaliza_com_estado_finalized():
    # A doc mente (settled); o valor que funciona é 'finalized' (gotcha §1).
    cli = _cliente()
    ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
    )
    puts = [c for c in cli.chamadas if c[0] == "PUT"]
    assert len(puts) == 1
    _metodo, url, kw = puts[0]
    assert url.endswith(f"/invoice_receipts/{ID_DOC}/change-state.json")
    estado = kw["json"]["invoice_receipt"]["state"]
    assert estado == "finalized"


# ==========================================================================
#  GUARDA G2 — sem certificação AT não devolve fatura "boa"
# ==========================================================================
def test_g2_atcud_nd_levanta_fatura_nao_certificada():
    cli = _cliente(detalhes=_resp_detalhes(atcud="N/D"))
    with pytest.raises(ix.FaturaNaoCertificada):
        ix.emitir_fatura_recibo(
            nome="Titular", nif="508000000", email="c@ex.pt",
            itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
        )


def test_g2_atcud_vazio_levanta_fatura_nao_certificada():
    cli = _cliente(detalhes=_resp_detalhes(atcud=""))
    with pytest.raises(ix.FaturaNaoCertificada):
        ix.emitir_fatura_recibo(
            nome="Titular", nif="508000000", email="c@ex.pt",
            itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
        )


def test_g2_saft_hash_ausente_levanta_fatura_nao_certificada():
    cli = _cliente(detalhes=_resp_detalhes(saft_hash=""))
    with pytest.raises(ix.FaturaNaoCertificada):
        ix.emitir_fatura_recibo(
            nome="Titular", nif="508000000", email="c@ex.pt",
            itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
        )


# ==========================================================================
#  GUARDA G3 — total devolvido tem de bater certo (IVA 23% incl.)
# ==========================================================================
def test_g3_total_errado_levanta_total_inesperado():
    # Sintoma do gotcha §8: taxa IVA23 não existe → API aplica taxa por omissão
    # (0%) → total volta 39,84 em vez de 49,00. Tem de rebentar.
    cli = _cliente(detalhes=_resp_detalhes(total=39.84))
    with pytest.raises(ix.TotalInesperado):
        ix.emitir_fatura_recibo(
            nome="Titular", nif="508000000", email="c@ex.pt",
            itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
        )


def test_g3_total_certo_nao_rebenta():
    # 49,00 € exatos passam a guarda.
    cli = _cliente(detalhes=_resp_detalhes(total=49.0))
    fatura = ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
    )
    assert fatura.total == pytest.approx(49.0, abs=0.005)


# ==========================================================================
#  PDF 202 → polling: repete o GET do PDF até 200 (sem bloquear em rede real)
# ==========================================================================
def test_pdf_202_faz_polling_ate_200():
    esperas: list[float] = []
    cli = _cliente(pdf=[_resp_pdf_a_gerar(), _resp_pdf_a_gerar(), _resp_pdf_pronto()])
    fatura = ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=esperas.append,
    )
    # certificada na mesma
    assert fatura.atcud == "ABCD1234-6"
    assert fatura.pdf_url == "https://ix.example/pdf/998877.pdf"
    # o endpoint do PDF foi batido >1 vez (202… 202… 200)
    gets_pdf = [c for c in cli.chamadas if c[0] == "GET" and "/api/pdf/" in c[1]]
    assert len(gets_pdf) >= 3
    # e houve pausa entre tentativas (dormir chamado), mas neutralizada
    assert len(esperas) >= 2


def test_pdf_202_persistente_nao_impede_certificacao():
    # PDF ainda a gerar após esgotar o polling: pdf_url None, mas a fatura
    # continua certificada (o PDF é para o email de boas-vindas, FDS 3).
    cli = _cliente(pdf=[_resp_pdf_a_gerar()])
    fatura = ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
    )
    assert fatura.pdf_url is None
    assert fatura.atcud == "ABCD1234-6"
    assert fatura.total == pytest.approx(49.0, abs=0.005)


# ==========================================================================
#  Ordem do fluxo: criar → finalizar → pdf → ler detalhes
# ==========================================================================
def test_ordem_das_chamadas():
    cli = _cliente()
    ix.emitir_fatura_recibo(
        nome="Titular", nif="508000000", email="c@ex.pt",
        itens=ITENS_ANUAL, cliente_http=cli, dormir=lambda _s: None,
    )
    metodos = [(m, ("pdf" if "/api/pdf/" in u else "det" if u.endswith(f"{ID_DOC}.json") else "outro"))
               for m, u, _ in cli.chamadas]
    assert metodos[0][0] == "POST"                       # criar
    assert metodos[1][0] == "PUT"                        # finalizar
    assert ("GET", "pdf") in metodos                     # PDF
    assert metodos[-1] == ("GET", "det")                 # ler campos fiscais por último
