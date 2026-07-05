"""Teste de INTEGRAÇÃO ponta-a-ponta do FDS 4 (SPEC-FDS4 §INTEGRAÇÃO / AUTOMACAO §7).

Prova o percurso completo da camada regulatória + IA, do documento à caixa de correio::

    PDF/texto da Parte H  →  dre_pipeline.correr_dre  →  eventos_regulatorios
                          →  pipeline.correr_pipeline (triagem Haiku mock →
                             redação Sonnet mock → 3 camadas anti-alucinação)
                          →  alertas  →  envio (mock)

Encadeia o :mod:`app.regulatorio.dre_pipeline` (Camada A: contador auto-corretivo →
Parte H → grep AL → concelho → excerto do corpo) e o :mod:`app.regulatorio.pipeline`
(triagem → cruzamento com clientes → redação citada → persistência → envio) na **mesma**
sessão, tal como o cron real: o `dre_pipeline` passa as instâncias vivas dos eventos ao
`pipeline` (`eventos=res_dre.eventos`) para a IA receber o corpo por excerto.

Verifica o contrato do FDS 4:
  1. um documento da Parte H com um regulamento de AL num concelho X gera **um** evento;
  2. a triagem (Haiku mock) marca-o relevante;
  3. o alerta (Sonnet mock) é **fiel** — só usa valores do excerto (coima/prazo/data) e
     **cita a url da fonte** — e passa :func:`app.ia.validacao.validar_alerta`;
  4. o alerta é persistido em `alertas` e **enviado** (mock) ao cliente com AL em X;
  5. 🎯 um cliente **sem** AL em X **não** recebe (fan-out dirigido pelo concelho);
  6. **reprocessar não duplica** (idempotência do `dre_pipeline` por `url` e do
     `pipeline` por `EventoRegulatorio.processado`).

DISCIPLINA (inviolável): **zero rede/IA real** (SPEC-FDS4 §disciplina transversal). O
`cliente_http` é injetado (dublê); a extração de texto do PDF (`extrair_texto`) é fixada a
uma fixture-string determinística — o Helvetica core do fpdf2 não encoda o "•" do
cabeçalho real do DR, pelo que se fixa o *texto extraído*, que é o contrato real do parser
(a descodificação pypdf de bytes→texto é coberta à parte em `tests/test_dre_client.py`).
`cliente_ia` e `enviar` são falsos. BD SQLite temporária. Nada de cold.
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
    """`get(url)` devolve a resposta mapeada (404 por omissão) e regista os URLs pedidos."""

    def __init__(self, respostas: dict[str, _Resp]) -> None:
        self._respostas = respostas
        self.urls: list[str] = []

    def get(self, url: str) -> _Resp:
        self.urls.append(url)
        return self._respostas.get(url, _Resp(404, b"<html>nao publicado</html>"))


# ==========================================================================
#  Dublê do cliente Anthropic — JSON na triagem (structured output), prosa na redação
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
    """`create(**kw)`: JSON se o pedido tem `output_config` (triagem), senão a prosa."""

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
    """`enviar(*, para, assunto, html, anexos, **kw)`: regista a chamada e devolve um id."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio

        self.chamadas.append(
            {"para": para, "assunto": assunto, "html": html, "kw": kw}
        )
        return ResultadoEnvio(id="re_e2e_fds4")


# ==========================================================================
#  Fixture-string do texto extraído (mimetiza a estrutura VERIFICADA, SPEC-DRE §2.2)
# ==========================================================================
# Edição 142 de 24/07/2025 — Braga com Regulamento de AL. O sumário lista a entidade; o
# corpo (após o cabeçalho de página repetido) traz a coima, o prazo e a data — a única
# fonte de verdade da IA (o `.texto`/excerto que fundamenta o alerta).
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

DATA = date(2025, 7, 24)
EDICAO = 142


def _url(data: date, edicao: int) -> str:
    return f"{DRE_PDF_BASE}/{data.year:04d}/{data.month:02d}/2S{edicao:03d}A0000S00.pdf"


# URL única e citável do ato (PDF gratuito + fragmento da entidade) — a que o alerta cita.
URL_EVENTO = f"{_url(DATA, EDICAO)}#municipio-de-braga"

# Triagem (Haiku mock): relevante, concelho Braga.
TRIAGEM_JSON = (
    '{"relevante_para_al": "sim", "concelhos": ["Braga"], '
    '"tipo": "regulamento", "resumo_1_frase": "Novo regulamento de AL em Braga."}'
)

# Redação (Sonnet mock) FIEL: só valores do excerto do corpo (2.500 €, 4.000 €, 30 dias,
# 15/06/2026) + cita a url. O "nº 100031" é identificador (sem € nem contexto de data), não
# um valor afirmado → não é exigido no excerto. Passa `validar_alerta` por construção.
PROSA_FIEL = (
    "(a) Foi publicado um novo Regulamento Municipal de Alojamento Local em Braga. "
    "(b) Afeta o teu AL? Possivelmente: o teu alojamento nº 100031, em Braga, pode ficar "
    "abrangido pela nova área de contenção. (c) Confirma a tua situação: a coima varia "
    "entre 2.500 € e 4.000 € e há um prazo de 30 dias, a contar de 15/06/2026. "
    "Lê o documento em " + URL_EVENTO
)


# ==========================================================================
#  Fixtures — lista canónica de concelhos, extração fixada, BD temporária
# ==========================================================================
@pytest.fixture()
def concelhos(monkeypatch):
    """Fixa a lista canónica (independente de `concelhos.txt`)."""
    monkeypatch.setattr(
        config, "concelhos_todos", lambda: ["Braga", "Bragança", "Porto", "Faro"]
    )


@pytest.fixture()
def texto_fixo(monkeypatch):
    """Fixa `extrair_texto`: mapeia os bytes do PDF injetado → texto extraído.

    A chave é o próprio `content` devolvido pelo cliente HTTP falso (bytes marcadores),
    tornando a extração determinística sem depender de fontes/encoding do fpdf2.
    """
    mapa: dict[bytes, str] = {}
    monkeypatch.setattr(dre_pipeline, "extrair_texto", lambda pdf: mapa[pdf])
    return mapa


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_e2e_fds4.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _pdf(marca: str) -> bytes:
    """Bytes de PDF-dublê (passam a verificação `%PDF` de `descarregar_pdf`)."""
    return b"%PDF-1.4 " + marca.encode()


def _cli_braga() -> tuple[_CliHTTP, bytes]:
    """Cliente HTTP com a edição 142 (Braga) publicada; a 143 devolve 404 por omissão."""
    pdf = _pdf("ed142")
    return _CliHTTP({_url(DATA, EDICAO): _Resp(200, pdf)}), pdf


def _semear_cliente_com_al(
    s, *, cliente_id: int, nr_registo: int, concelho: str, email: str
) -> None:
    """Semeia um cliente ativo com um AL num concelho (registo + cliente + associação)."""
    s.add(
        models.Registo(
            nr_registo=nr_registo,
            nome_alojamento=f"AL {nr_registo}",
            modalidade="Moradia",
            concelho=concelho,
            distrito=concelho,
            titular_tipo="singular",
            hash_campos="h",
        )
    )
    s.add(models.Cliente(id=cliente_id, email=email, nome="Cliente", estado="ativo"))
    s.flush()
    s.add(models.ClienteRegisto(cliente_id=cliente_id, nr_registo=nr_registo))
    s.flush()


# ==========================================================================
#  INTEGRAÇÃO 1 — da Parte H ao alerta enviado, e só ao cliente certo
# ==========================================================================
def test_e2e_da_parte_h_ao_alerta_enviado_ao_cliente_com_al_no_concelho(
    bd, concelhos, texto_fixo
):
    cli, pdf = _cli_braga()
    texto_fixo[pdf] = TEXTO_BRAGA
    enviar = _Enviar()

    with db.get_session() as s:
        # Cliente 1 — AL em Braga (o concelho X do documento): DEVE receber.
        _semear_cliente_com_al(
            s, cliente_id=1, nr_registo=100031, concelho="Braga", email="braga@exemplo.pt"
        )
        # Cliente 2 — AL em Faro (fora de X): NÃO deve receber.
        _semear_cliente_com_al(
            s, cliente_id=2, nr_registo=200099, concelho="Faro", email="faro@exemplo.pt"
        )

        # 1) Captação (Camada A): PDF real da Parte H → eventos_regulatorios.
        res_dre = dre_pipeline.correr_dre(
            s, cliente_http=cli, data=DATA, edicao_inicial=EDICAO
        )
        assert len(res_dre.eventos) == 1
        evento = res_dre.eventos[0]
        assert evento.fonte == "DRE"
        assert evento.concelhos == ["Braga"]
        assert evento.url == URL_EVENTO
        excerto = evento.texto  # corpo do ato (fonte de verdade) — tem coima/prazo/data
        assert "2.500 €" in excerto and "30 dias" in excerto and "15/06/2026" in excerto

        # 2) Pipeline IA na MESMA sessão: triagem → alerta citado → envio.
        res_pipe = pipeline.correr_pipeline(
            s,
            cliente_ia=_ClienteIA(TRIAGEM_JSON, PROSA_FIEL),
            enviar=enviar,
            eventos=res_dre.eventos,  # passagem de mão: a IA recebe o corpo por excerto
        )
        assert res_pipe.eventos_processados == 1
        assert res_pipe.eventos_relevantes == 1
        assert res_pipe.enviados == 1
        assert len(res_pipe.alertas) == 1

    # 3) O alerta final persistido é do cliente certo, citado, fiel e enviado.
    with db.get_session() as s:
        a = s.query(models.Alerta).one()  # exatamente 1 alerta em toda a BD
        assert a.origem == pipeline.ORIGEM_REGULATORIO
        assert a.cliente_id == 1 and a.nr_registo == 100031
        assert a.canal == pipeline.CANAL_EMAIL
        assert a.enviado_em is not None
        assert URL_EVENTO in a.conteudo                       # fonte citada
        assert "2.500" in a.conteudo and "30 dias" in a.conteudo  # valores do documento
        assert "7.500" not in a.conteudo                      # nada inventado

        # o evento ficou triado e processado (âncora de idempotência)
        ev = s.query(models.EventoRegulatorio).one()
        assert ev.processado is True and ev.triagem == "relevante"

        # 🧯 fidelidade: o alerta passa a validação anti-alucinação contra o próprio excerto
        assert validar_alerta(a.conteudo, url_fonte=URL_EVENTO, excerto=excerto).valido

    # 4) O envio saiu UMA vez, para o cliente de Braga, com a fonte citada e o disclaimer.
    assert len(enviar.chamadas) == 1
    chamada = enviar.chamadas[0]
    assert chamada["para"] == "braga@exemplo.pt"
    assert URL_EVENTO in chamada["html"]
    assert "aconselhamento" in chamada["html"].lower()
    assert chamada["kw"]["idempotency_key"] == "reg-1-100031"

    # 5) 🎯 O cliente SEM AL em X (Faro) não recebeu nada — nem alerta, nem email.
    assert all(c["para"] != "faro@exemplo.pt" for c in enviar.chamadas)
    with db.get_session() as s:
        assert s.query(models.Alerta).filter(models.Alerta.cliente_id == 2).count() == 0


# ==========================================================================
#  INTEGRAÇÃO 2 — reprocessar não duplica (dedup por url + processado)
# ==========================================================================
def test_e2e_reprocessar_nao_duplica(bd, concelhos, texto_fixo):
    pdf = _pdf("ed142")
    texto_fixo[pdf] = TEXTO_BRAGA

    # --- 1.ª corrida completa: cria 1 evento e envia 1 alerta ---
    with db.get_session() as s:
        _semear_cliente_com_al(
            s, cliente_id=1, nr_registo=100031, concelho="Braga", email="braga@exemplo.pt"
        )
        cli1 = _CliHTTP({_url(DATA, EDICAO): _Resp(200, pdf)})
        res_dre1 = dre_pipeline.correr_dre(
            s, cliente_http=cli1, data=DATA, edicao_inicial=EDICAO
        )
        res_pipe1 = pipeline.correr_pipeline(
            s,
            cliente_ia=_ClienteIA(TRIAGEM_JSON, PROSA_FIEL),
            enviar=_Enviar(),
            eventos=res_dre1.eventos,
        )
    assert len(res_dre1.eventos) == 1
    assert len(res_pipe1.alertas) == 1

    # --- 2.ª corrida idêntica: o dre_pipeline é idempotente por `url` → 0 eventos novos;
    #     o pipeline com essa lista vazia não gera nem envia nada ---
    enviar2 = _Enviar()
    with db.get_session() as s:
        cli2 = _CliHTTP({_url(DATA, EDICAO): _Resp(200, pdf)})
        res_dre2 = dre_pipeline.correr_dre(
            s, cliente_http=cli2, data=DATA, edicao_inicial=EDICAO
        )
        assert res_dre2.eventos == []  # a url já existia → nada novo captado
        res_pipe2 = pipeline.correr_pipeline(
            s,
            cliente_ia=_ClienteIA(TRIAGEM_JSON, PROSA_FIEL),
            enviar=enviar2,
            eventos=res_dre2.eventos,
        )
    assert res_pipe2.alertas == []
    assert enviar2.chamadas == []

    # --- 3.ª corrida a varrer a FILA da BD (eventos=None): o evento já está `processado`
    #     → o pipeline não o revê (idempotência por `EventoRegulatorio.processado`) ---
    enviar3 = _Enviar()
    with db.get_session() as s:
        res_pipe3 = pipeline.correr_pipeline(
            s, cliente_ia=_ClienteIA(TRIAGEM_JSON, PROSA_FIEL), enviar=enviar3
        )
    assert res_pipe3.eventos_processados == 0
    assert res_pipe3.alertas == []
    assert enviar3.chamadas == []

    # --- estado final: exatamente 1 evento e 1 alerta em toda a BD ---
    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).count() == 1
        assert s.query(models.Alerta).count() == 1
