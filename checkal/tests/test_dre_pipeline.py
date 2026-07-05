"""Testes do cron regulatório (Camada A) + aceitação ponta-a-ponta do FDS 4.

Duas partes:

1. **`app.regulatorio.dre_pipeline`** — a corrida diária que materializa
   `eventos_regulatorios` a partir do PDF integral gratuito da 2.ª série (contador
   auto-corretivo; Parte H → grep AL → concelho; idempotente por `url`).
2. **ACEITAÇÃO (AUTOMACAO.md §7 / SPEC-FDS4 §critério):** *"um documento real da Parte H
   gera um alerta correto E citado para um cliente de teste"* — encadeia `dre_pipeline` →
   `pipeline` na **mesma** sessão e prova o alerta final.

DISCIPLINA (inviolável): **zero rede/IA real**. O `cliente_http` é injetado (dublê); a
extração de texto do PDF (`extrair_texto`) é fixada a fixtures-string deterministas (o
Helvetica core do fpdf2 não encoda "•", pelo que os cabeçalhos reais do DR não sairiam de
um PDF gerado — fixa-se o texto extraído, que é o contrato real do parser). `cliente_ia` e
`enviar` são falsos. BD SQLite temporária. Escrito ANTES de fechar a implementação (TDD).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.ia.validacao import validar_alerta
from app.regulatorio import dre_pipeline, pipeline
from app.regulatorio.dre_client import DRE_PDF_BASE


# ==========================================================================
#  Dublês HTTP (nada toca a rede) — cliente edição-aware por URL
# ==========================================================================
class _Resp:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _CliHTTP:
    """`get(url)` devolve a resposta mapeada (ou 404 por omissão) e regista os URLs."""

    def __init__(self, respostas: dict[str, _Resp]) -> None:
        self._respostas = respostas
        self.urls: list[str] = []

    def get(self, url: str) -> _Resp:
        self.urls.append(url)
        return self._respostas.get(url, _Resp(404, b"<html>nao publicado</html>"))


# ==========================================================================
#  Fixtures-string do texto extraído (mimetizam a estrutura VERIFICADA, SPEC-DRE §2.2)
# ==========================================================================
# Positiva: edição 142 de 24/07/2025 — Braga com Regulamento de AL; o corpo (após o
# cabeçalho de página repetido) traz a coima, o prazo e a data — a fonte de verdade da IA.
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
O presente regulamento aplica-se ao alojamento local no concelho de Braga. Foi criada uma
área de contenção onde ficam suspensos novos registos. A coima aplicável varia entre
2.500 € e 4.000 €. Os titulares dispõem de um prazo de 30 dias, a contar de 15/06/2026,
para comunicar a sua situação.
"""

# Negativa: edição 29 de 11/02/2026 — Parte H (Sintra) sem qualquer keyword de AL.
TEXTO_SEM_AL = """N.º 29 • 11 de fevereiro de 2026
2.ª série
SUMÁRIO
PARTE H | Autarquias locais
MUNICÍPIO DE SINTRA
Aviso n.º 555/2026
Delimitação de unidade de execução
N.º 29 • 11 de fevereiro de 2026
"""

# Robustez: edição sem Parte H nenhuma.
TEXTO_SEM_PARTE_H = """N.º 30 • 12 de fevereiro de 2026
2.ª série
SUMÁRIO
PARTE C | Governo e administração direta e indireta do Estado
Despacho n.º 1/2026
"""

# Edição cujo cabeçalho diz OUTRO número (salto/suplemento) — deve parar e avisar.
TEXTO_NUMERO_ERRADO = """N.º 999 • 25 de julho de 2025
2.ª série
SUMÁRIO
PARTE H | Autarquias locais
MUNICÍPIO DE BRAGA
Regulamento n.º 1/2025
Regulamento de Alojamento Local
"""


def _url(data: date, edicao: int) -> str:
    return f"{DRE_PDF_BASE}/{data.year:04d}/{data.month:02d}/2S{edicao:03d}A0000S00.pdf"


@pytest.fixture()
def concelhos(monkeypatch):
    """Fixa a lista canónica (independente de data/concelhos.txt)."""
    monkeypatch.setattr(
        config, "concelhos_todos",
        lambda: ["Braga", "Bragança", "Porto", "Sintra", "Faro"],
    )


@pytest.fixture()
def texto_fixo(monkeypatch):
    """Fixa `extrair_texto`: mapeia os bytes do PDF injetado → texto extraído.

    A chave é o próprio `content` devolvido pelo cliente HTTP falso (bytes marcadores),
    o que torna a extração determinística sem depender de fontes/encoding do fpdf2.
    """
    mapa: dict[bytes, str] = {}
    monkeypatch.setattr(dre_pipeline, "extrair_texto", lambda pdf: mapa[pdf])
    return mapa


def _pdf(marca: str) -> bytes:
    """Bytes de PDF-dublê (passam a verificação `%PDF` do `descarregar_pdf`)."""
    return b"%PDF-1.4 " + marca.encode()


# ==========================================================================
#  BD SQLite temporária
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_dre.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


# ==========================================================================
#  dre_pipeline — cria evento para uma secção de AL
# ==========================================================================
def test_correr_cria_evento_para_seccao_de_al(bd, concelhos, texto_fixo):
    data = date(2025, 7, 24)
    pdf142 = _pdf("ed142")
    texto_fixo[pdf142] = TEXTO_BRAGA
    cli = _CliHTTP({_url(data, 142): _Resp(200, pdf142)})  # 143 → 404 por omissão

    with db.get_session() as s:
        res = dre_pipeline.correr_dre(
            s, cliente_http=cli, data=data, edicao_inicial=142
        )
        assert len(res.eventos) == 1
        assert res.edicoes == [142]
        ev = res.eventos[0]
        assert ev.fonte == "DRE"
        assert ev.concelhos == ["Braga"]
        assert "Regulamento" in ev.titulo
        assert ev.publicado_em == date(2025, 7, 24)
        assert ev.processado is False
        assert ev.triagem is None
        assert ev.url == f"{_url(data, 142)}#municipio-de-braga"

    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).count() == 1


def test_evento_carrega_excerto_do_corpo_em_memoria(bd, concelhos, texto_fixo):
    # o `.texto` (excerto) tem de conter os valores do CORPO (coima/prazo/data), não só o
    # sumário — é a fonte de verdade que a IA usa a jusante.
    data = date(2025, 7, 24)
    pdf142 = _pdf("ed142")
    texto_fixo[pdf142] = TEXTO_BRAGA
    cli = _CliHTTP({_url(data, 142): _Resp(200, pdf142)})

    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=142)
        excerto = res.eventos[0].texto
    assert "2.500 €" in excerto
    assert "30 dias" in excerto
    assert "15/06/2026" in excerto


def test_ignora_seccao_sem_keyword_de_al(bd, concelhos, texto_fixo):
    data = date(2026, 2, 11)
    pdf29 = _pdf("ed29")
    texto_fixo[pdf29] = TEXTO_SEM_AL
    cli = _CliHTTP({_url(data, 29): _Resp(200, pdf29)})

    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=29)
        assert res.eventos == []
        assert res.edicoes == [29]  # processou a edição, apenas não gerou evento
    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).count() == 0


def test_edicao_inexistente_para_sem_avisos(bd, concelhos, texto_fixo):
    data = date(2025, 7, 24)
    cli = _CliHTTP({})  # tudo 404
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=200)
    assert res.eventos == []
    assert res.edicoes == []
    assert res.avisos == []  # 404 é "ainda não publicado", não é anomalia


def test_sem_parte_h_nao_rebenta(bd, concelhos, texto_fixo):
    data = date(2026, 2, 12)
    pdf30 = _pdf("ed30")
    texto_fixo[pdf30] = TEXTO_SEM_PARTE_H
    cli = _CliHTTP({_url(data, 30): _Resp(200, pdf30)})
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=30)
    assert res.eventos == []
    assert res.edicoes == [30]


def test_cabecalho_com_outro_numero_para_e_avisa(bd, concelhos, texto_fixo):
    # a página 1 diz N.º 999 mas pedimos a 800 → salto/suplemento: pára e avisa o dono.
    data = date(2025, 7, 25)
    pdf = _pdf("ed800")
    texto_fixo[pdf] = TEXTO_NUMERO_ERRADO
    cli = _CliHTTP({_url(data, 800): _Resp(200, pdf)})
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=800)
    assert res.eventos == []
    assert res.edicoes == []
    assert any("999" in a for a in res.avisos)


def test_concelho_nao_reconhecido_cria_evento_sem_concelho_e_avisa(bd, texto_fixo, monkeypatch):
    # concelho fora da lista canónica → NÃO se descarta: evento com concelhos=[] + aviso.
    monkeypatch.setattr(config, "concelhos_todos", lambda: ["Porto"])  # Braga fora
    data = date(2025, 7, 24)
    pdf = _pdf("ed142")
    texto_fixo[pdf] = TEXTO_BRAGA
    cli = _CliHTTP({_url(data, 142): _Resp(200, pdf)})
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=142)
        assert len(res.eventos) == 1
        assert res.eventos[0].concelhos == []
        assert any("não foi reconhecido" in a or "reconhecido" in a for a in res.avisos)


def test_idempotente_por_url(bd, concelhos, texto_fixo):
    data = date(2025, 7, 24)
    pdf = _pdf("ed142")
    texto_fixo[pdf] = TEXTO_BRAGA

    def corrida():
        cli = _CliHTTP({_url(data, 142): _Resp(200, pdf)})
        with db.get_session() as s:
            return dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=142)

    res1 = corrida()
    res2 = corrida()
    assert len(res1.eventos) == 1
    assert res2.eventos == []  # a url já existia → nada novo
    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).count() == 1  # sem duplicados


def test_processa_multiplas_edicoes_sequenciais(bd, concelhos, texto_fixo):
    data = date(2025, 7, 24)
    p142, p143 = _pdf("ed142"), _pdf("ed143")
    texto_fixo[p142] = TEXTO_BRAGA
    # 143: reaproveita a estrutura de Braga mas com cabeçalho 143 e Porto
    texto_fixo[p143] = TEXTO_BRAGA.replace("142", "143").replace("BRAGA", "PORTO").replace("Braga", "Porto")
    cli = _CliHTTP({_url(data, 142): _Resp(200, p142), _url(data, 143): _Resp(200, p143)})
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=142)
    assert res.edicoes == [142, 143]
    assert {c for ev in res.eventos for c in ev.concelhos} == {"Braga", "Porto"}


def test_modo_teste_sem_cliente_injetado_nao_toca_rede(bd, monkeypatch):
    # cliente_http=None + CHECKAL_MODO_TESTE → obter_cliente_http()==None → não corre nada.
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    assert dre_pipeline.obter_cliente_http() is None
    with db.get_session() as s:
        res = dre_pipeline.correr_dre(s, cliente_http=None, data=date(2025, 7, 24))
    assert res.eventos == []
    assert res.avisos  # avisa que não correu


# ==========================================================================
#  ACEITAÇÃO FDS 4 (AUTOMACAO §7): documento real da Parte H → alerta citado
# ==========================================================================
class _BlocoIA:
    def __init__(self, texto: str) -> None:
        self.type = "text"
        self.text = texto


class _MsgIA:
    def __init__(self, texto: str) -> None:
        self.content = [_BlocoIA(texto)] if texto else []
        self.stop_reason = "end_turn"


class _MessagesIA:
    def __init__(self, json_resp: str, prosa: str) -> None:
        self._json = json_resp
        self._prosa = prosa
        self.chamadas: list[dict] = []

    def create(self, **kwargs) -> _MsgIA:
        self.chamadas.append(kwargs)
        return _MsgIA(self._json if "output_config" in kwargs else self._prosa)


class _ClienteIA:
    def __init__(self, json_resp: str, prosa: str) -> None:
        self.messages = _MessagesIA(json_resp, prosa)


class _Enviar:
    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio

        self.chamadas.append({"para": para, "assunto": assunto, "html": html, "kw": kw})
        return ResultadoEnvio(id="re_aceitacao_fds4")


def test_aceitacao_documento_parte_h_gera_alerta_correto_e_citado(bd, concelhos, texto_fixo):
    data = date(2025, 7, 24)
    pdf = _pdf("ed142")
    texto_fixo[pdf] = TEXTO_BRAGA
    cli = _CliHTTP({_url(data, 142): _Resp(200, pdf)})

    url_evento = f"{_url(data, 142)}#municipio-de-braga"
    triagem_json = (
        '{"relevante_para_al": "sim", "concelhos": ["Braga"], '
        '"tipo": "regulamento", "resumo_1_frase": "Novo regulamento de AL em Braga."}'
    )
    # prosa fiel: só valores do excerto do corpo (2.500 €, 4.000 €, 30 dias) + cita a url.
    prosa = (
        "(a) Foi publicado um novo regulamento municipal de Alojamento Local em Braga. "
        "(b) Afeta o teu AL? Possivelmente: o teu alojamento nº 100031, em Braga, pode "
        "ficar abrangido pela área de contenção. (c) Confirma a tua situação; a coima "
        "varia entre 2.500 € e 4.000 € e há um prazo de 30 dias. Lê o documento em "
        + url_evento
    )
    enviar = _Enviar()

    with db.get_session() as s:
        # cliente de teste com um AL em Braga
        s.add(models.Registo(
            nr_registo=100031, nome_alojamento="Casa do Minho", modalidade="Moradia",
            concelho="Braga", distrito="Braga", titular_tipo="singular", hash_campos="h",
        ))
        s.add(models.Cliente(id=1, email="dono@exemplo.pt", nome="Dono", estado="ativo"))
        s.flush()
        s.add(models.ClienteRegisto(cliente_id=1, nr_registo=100031))
        s.flush()

        # 1) captação (Camada A): PDF real da Parte H → eventos_regulatorios
        res_dre = dre_pipeline.correr_dre(s, cliente_http=cli, data=data, edicao_inicial=142)
        assert len(res_dre.eventos) == 1
        excerto_doc = res_dre.eventos[0].texto  # o corpo do ato (fonte de verdade da IA)

        # 2) pipeline IA na MESMA sessão → triagem → alerta citado → envio. Passa-se a lista
        #    de eventos captados (referência forte) para a IA receber o corpo por excerto.
        res_pipe = pipeline.correr_pipeline(
            s, cliente_ia=_ClienteIA(triagem_json, prosa), enviar=enviar,
            eventos=res_dre.eventos,
        )
        assert res_pipe.eventos_relevantes == 1
        assert res_pipe.enviados == 1

    # 3) verificação do alerta final persistido
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert a.origem == "eventos_regulatorios"
        assert a.cliente_id == 1
        assert a.nr_registo == 100031
        assert a.enviado_em is not None
        assert url_evento in a.conteudo                       # citado
        assert "2.500" in a.conteudo and "30 dias" in a.conteudo  # valores do documento
        # o alerta é fiel ao excerto do próprio documento (a fonte de verdade)
        ev = s.query(models.EventoRegulatorio).one()
        assert ev.processado is True and ev.triagem == "relevante"
        assert validar_alerta(a.conteudo, url_fonte=url_evento, excerto=excerto_doc).valido

    # o email saiu para o cliente, com a fonte citada
    assert len(enviar.chamadas) == 1
    assert enviar.chamadas[0]["para"] == "dono@exemplo.pt"
    assert url_evento in enviar.chamadas[0]["html"]
