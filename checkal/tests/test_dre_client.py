"""Testes do cliente/parse do DRE — app.regulatorio.dre_client (FDS 4).

Contrato (SPEC-FDS4 §dre_client + SPEC-DRE.md §1/§2):
  - `url_pdf_gratuito(data, edicao) -> str`: padrão VERIFICADO
    `files.diariodarepublica.pt/gratuitos/2s/AAAA/MM/2S{NNN}A0000S00.pdf`
    (mês e edição com zero-pad; edição 3 díg.).
  - `descarregar_pdf(url, *, cliente_http) -> bytes|None`: **não-200/não-PDF → None**
    (edição inexistente / página de erro não rebentam).
  - `extrair_texto(pdf_bytes) -> str` via pypdf.
  - `extrair_parte_H(texto) -> list[SeccaoParteH]`: delimita a Parte H (Autarquias
    locais) do sumário e parte-a por entidade; tolera ausência da secção (→ []).
  - `grep_al(seccao) -> bool`: keywords AL/contenção/crescimento sustentável, com
    normalização (maiúsculas, acentos, hifenização de fim de linha).
  - `concelhos_de(seccao) -> list[str]`: extrai o concelho do cabeçalho
    `MUNICÍPIO/CÂMARA MUNICIPAL DE …`, normalizado contra `config.concelhos_todos()`.

DISCIPLINA (inviolável): **zero rede real**. O `cliente_http` é injetado/mockado;
os PDF de teste são gerados em memória (fpdf2) e o texto da Parte H é fixture-string.
Escrito ANTES da implementação (TDD). Um teste por propriedade.
"""
from __future__ import annotations

from datetime import date

import pytest
from fpdf import FPDF
from fpdf.enums import XPos, YPos

import app.config as config
from app.regulatorio.dre_client import (
    DRE_PDF_BASE,
    SeccaoParteH,
    concelhos_de,
    descarregar_pdf,
    extrair_parte_H,
    extrair_texto,
    grep_al,
    url_pdf_gratuito,
)


# ==========================================================================
#  Dublês de teste (nada toca a rede)
# ==========================================================================
class RespostaFake:
    """Substitui `httpx.Response`: só o que `descarregar_pdf` lê (`status_code`,
    `content`, `headers`)."""

    def __init__(self, status_code: int, content: bytes = b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class ClienteHTTPFake:
    """Substitui `httpx.Client` no download: devolve sempre a mesma resposta e
    regista os URLs pedidos em `self.urls`."""

    def __init__(self, resposta: RespostaFake):
        self.resposta = resposta
        self.urls: list[str] = []

    def get(self, url: str) -> RespostaFake:
        self.urls.append(url)
        return self.resposta


def _pdf_bytes(linhas: list[str]) -> bytes:
    """Gera um PDF de 1 página com `linhas` (uma cell por linha), extraível por pypdf."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for linha in linhas:
        pdf.cell(0, 8, linha, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


# --------------------------------------------------------------------------
#  Fixtures-string (mimetizam a estrutura VERIFICADA do sumário — SPEC-DRE §2.2)
# --------------------------------------------------------------------------
# Edição com regulamento de AL de Braga (2S142/2025) — positiva.
TEXTO_BRAGA = """N.º 142 • 24 de julho de 2025
2.ª série
SUMÁRIO
PARTE C | Governo e administração direta e indireta do Estado
Aviso n.º 1/2025
PARTE H | Autarquias locais
MUNICÍPIO DE BRAGA
Regulamento n.º 927/2025
Regulamento Municipal de Alojamento Local do Município de Braga
MUNICÍPIO DE BRAGANÇA
Aviso n.º 123/2025
Abertura de procedimento concursal comum para técnico superior
N.º 142 • 24 de julho de 2025
2.ª série
MUNICÍPIO DE BRAGA
Regulamento n.º 927/2025
[corpo] O presente regulamento aplica-se ao alojamento local no concelho...
"""

# Edição sem regulação de AL (2S029/2026) — negativa.
TEXTO_SEM_AL = """N.º 29 • 11 de fevereiro de 2026
2.ª série
SUMÁRIO
PARTE H | Autarquias locais
MUNICÍPIO DE SINTRA
Aviso n.º 555/2026
Delimitação de unidade de execução
N.º 29 • 11 de fevereiro de 2026
"""

# Edição sem Parte H (robustez).
TEXTO_SEM_PARTE_H = """N.º 30 • 12 de fevereiro de 2026
2.ª série
SUMÁRIO
PARTE C | Governo e administração direta e indireta do Estado
Despacho n.º 1/2026
"""


@pytest.fixture
def concelhos_de_teste(monkeypatch):
    """Fixa a lista canónica de concelhos (independente de data/concelhos.txt)."""
    monkeypatch.setattr(
        config,
        "concelhos_todos",
        lambda: ["Braga", "Bragança", "Porto", "Vila Nova de Gaia", "Funchal", "Sintra"],
    )


# ==========================================================================
#  url_pdf_gratuito — padrão VERIFICADO (SPEC-DRE §2.1)
# ==========================================================================
def test_url_padrao_verificado_2s142_2025():
    assert (
        url_pdf_gratuito(date(2025, 7, 24), 142)
        == f"{DRE_PDF_BASE}/2025/07/2S142A0000S00.pdf"
    )


def test_url_zero_pad_mes_e_edicao():
    # mês 1 díg. → "01"; edição 7 → "007".
    assert (
        url_pdf_gratuito(date(2026, 1, 3), 7)
        == f"{DRE_PDF_BASE}/2026/01/2S007A0000S00.pdf"
    )


def test_url_base_e_o_endpoint_gratuito_da_2a_serie():
    assert DRE_PDF_BASE == "https://files.diariodarepublica.pt/gratuitos/2s"


def test_url_edicao_invalida_rebenta():
    with pytest.raises(ValueError):
        url_pdf_gratuito(date(2026, 2, 11), 0)


# ==========================================================================
#  descarregar_pdf — não-200/não-PDF → None (cliente injetado)
# ==========================================================================
def test_descarregar_ok_devolve_bytes_do_pdf():
    corpo = b"%PDF-1.4\n...conteudo binario..."
    cli = ClienteHTTPFake(RespostaFake(200, corpo, {"content-type": "application/pdf"}))
    url = url_pdf_gratuito(date(2025, 7, 24), 142)

    out = descarregar_pdf(url, cliente_http=cli)

    assert out == corpo
    assert cli.urls == [url]  # pediu exatamente o URL dado


def test_descarregar_404_edicao_inexistente_devolve_none():
    cli = ClienteHTTPFake(RespostaFake(404, b"<html>Not Found</html>"))
    assert descarregar_pdf("http://x/2S999A0000S00.pdf", cliente_http=cli) is None


def test_descarregar_200_mas_html_nao_e_pdf_devolve_none():
    # 200 com página HTML (não começa por %PDF) → tratado como "ainda não publicado".
    cli = ClienteHTTPFake(RespostaFake(200, b"<!DOCTYPE html><html>erro</html>"))
    assert descarregar_pdf("http://x/y.pdf", cliente_http=cli) is None


def test_descarregar_200_corpo_vazio_devolve_none():
    cli = ClienteHTTPFake(RespostaFake(200, b""))
    assert descarregar_pdf("http://x/y.pdf", cliente_http=cli) is None


# ==========================================================================
#  extrair_texto — pypdf
# ==========================================================================
def test_extrair_texto_devolve_o_conteudo_do_pdf():
    pdf = _pdf_bytes(["PARTE H Autarquias locais", "MUNICIPIO DE PORTO", "Alojamento Local"])

    texto = extrair_texto(pdf)

    assert "PARTE H" in texto
    assert "MUNICIPIO DE PORTO" in texto
    assert "Alojamento Local" in texto


# ==========================================================================
#  extrair_parte_H — delimita a Parte H do sumário e parte por entidade
# ==========================================================================
def test_extrair_parte_H_devolve_uma_seccao_por_entidade():
    seccoes = extrair_parte_H(TEXTO_BRAGA)

    assert [s.cabecalho for s in seccoes] == [
        "MUNICÍPIO DE BRAGA",
        "MUNICÍPIO DE BRAGANÇA",
    ]


def test_extrair_parte_H_nao_sangra_para_o_corpo():
    # o delimitador de fim (cabeçalho de página do corpo "N.º 142 • …") corta o sumário:
    # a repetição de "MUNICÍPIO DE BRAGA" no corpo NÃO gera uma 3.ª secção.
    seccoes = extrair_parte_H(TEXTO_BRAGA)
    assert len(seccoes) == 2


def test_extrair_parte_H_seccao_contem_o_titulo_do_ato():
    seccoes = extrair_parte_H(TEXTO_BRAGA)
    braga = seccoes[0]
    assert "Regulamento n.º 927/2025" in braga.texto
    assert "Alojamento Local" in braga.texto


def test_extrair_parte_H_sem_seccao_devolve_lista_vazia():
    assert extrair_parte_H(TEXTO_SEM_PARTE_H) == []


def test_extrair_parte_H_texto_vazio_nao_rebenta():
    assert extrair_parte_H("") == []


# ==========================================================================
#  grep_al — keywords canónicas + normalização
# ==========================================================================
def test_grep_al_deteta_alojamento_local():
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE BRAGA", texto="Regulamento Municipal de Alojamento Local")
    assert grep_al(s) is True


def test_grep_al_deteta_area_de_contencao():
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE LISBOA", texto="define a área de contenção do concelho")
    assert grep_al(s) is True


def test_grep_al_deteta_crescimento_sustentavel():
    s = SeccaoParteH(cabecalho="MUNICÍPIO DO PORTO", texto="política de crescimento sustentável do AL")
    assert grep_al(s) is True


def test_grep_al_tolera_maiusculas_e_hifenizacao_de_fim_de_linha():
    # pdftotext parte palavras por hífen + quebra de linha: "Alo-\njamento Local".
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE FARO", texto="Regulamento de ALO-\nJAMENTO LOCAL de Faro")
    assert grep_al(s) is True


def test_grep_al_falso_quando_nao_ha_keywords():
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE BRAGANÇA", texto="Abertura de procedimento concursal comum")
    assert grep_al(s) is False


def test_grep_al_via_extrair_parte_H_positiva_e_negativa():
    seccoes = {s.cabecalho: s for s in extrair_parte_H(TEXTO_BRAGA)}
    assert grep_al(seccoes["MUNICÍPIO DE BRAGA"]) is True
    assert grep_al(seccoes["MUNICÍPIO DE BRAGANÇA"]) is False


def test_grep_al_edicao_negativa_nao_tem_hits():
    seccoes = extrair_parte_H(TEXTO_SEM_AL)
    assert seccoes  # há Parte H (Sintra), mas sem keywords de AL
    assert all(grep_al(s) is False for s in seccoes)


# ==========================================================================
#  concelhos_de — cabeçalho MUNICÍPIO/CÂMARA MUNICIPAL → concelho canónico
# ==========================================================================
def test_concelhos_de_municipio_simples(concelhos_de_teste):
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE BRAGA", texto="MUNICÍPIO DE BRAGA\nRegulamento n.º 927/2025")
    assert concelhos_de(s) == ["Braga"]


def test_concelhos_de_nome_composto(concelhos_de_teste):
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE VILA NOVA DE GAIA", texto="MUNICÍPIO DE VILA NOVA DE GAIA\nAviso")
    assert concelhos_de(s) == ["Vila Nova de Gaia"]


def test_concelhos_de_camara_municipal(concelhos_de_teste):
    s = SeccaoParteH(cabecalho="CÂMARA MUNICIPAL DO PORTO", texto="CÂMARA MUNICIPAL DO PORTO\nDeliberação")
    assert concelhos_de(s) == ["Porto"]


def test_concelhos_de_freguesia_nao_e_concelho(concelhos_de_teste):
    # FREGUESIA/UNIÃO não mapeia a concelho (sem tabela freguesia→concelho): [].
    s = SeccaoParteH(cabecalho="FREGUESIA DE SÃO VICENTE", texto="FREGUESIA DE SÃO VICENTE\nEdital")
    assert concelhos_de(s) == []


def test_concelhos_de_nao_reconhecido_devolve_vazio(concelhos_de_teste):
    # concelho fora da lista canónica → [] (o pipeline encaminha p/ revisão do dono).
    s = SeccaoParteH(cabecalho="MUNICÍPIO DE XPTOLÂNDIA", texto="MUNICÍPIO DE XPTOLÂNDIA\nAviso")
    assert concelhos_de(s) == []


def test_concelhos_de_via_extrair_parte_H(concelhos_de_teste):
    seccoes = {s.cabecalho: s for s in extrair_parte_H(TEXTO_BRAGA)}
    assert concelhos_de(seccoes["MUNICÍPIO DE BRAGA"]) == ["Braga"]
    assert concelhos_de(seccoes["MUNICÍPIO DE BRAGANÇA"]) == ["Bragança"]


# ==========================================================================
#  Integração através de um PDF real (fpdf2 → pypdf → parse)
# ==========================================================================
def test_pipeline_de_leitura_atraves_de_pdf_real():
    # PDF ASCII (fpdf2/Helvetica é Latin-1): sem "•", logo sem corpo → 1 secção.
    pdf = _pdf_bytes(
        [
            "PARTE H | Autarquias locais",
            "MUNICIPIO DE PORTO",
            "Regulamento Municipal de Alojamento Local do Porto",
        ]
    )
    texto = extrair_texto(pdf)
    seccoes = extrair_parte_H(texto)

    assert len(seccoes) == 1
    assert grep_al(seccoes[0]) is True
    assert concelhos_de(seccoes[0]) == ["Porto"]  # "Porto" ∈ CONCELHOS_PRIORITARIOS
