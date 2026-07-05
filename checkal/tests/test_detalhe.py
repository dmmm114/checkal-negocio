"""Testes do detalhe individual RNAL — app.rnal.detalhe (FDS 3, SPEC-DETALHE).

Contrato (SPEC-FDS3 §detalhe + SPEC-DETALHE):
  - `parse_detalhe(html, *, nr_registo) -> DetalheRegisto`: parser **puro** (sem I/O),
    ancorado em **texto de cabeçalho** (nunca nos `id` OutSystems voláteis — §6.2).
    estado ∈ {ativo, cancelado, suspenso, nao_encontrado, indeterminado}.
  - **G4 (inviolável):** default conservador `indeterminado`. Só `ativo` (bloco de dados
    "RNAL nº") e `nao_encontrado` (marcador textual em HTTP 200) são afirmados. O parser
    NUNCA afirma `cancelado`/`suspenso` a partir do detalhe — tudo o que não é claramente
    um daqueles dois vai para `indeterminado` (pára e avisa).
  - `obter_detalhe(nr_registo, *, cliente_http) -> DetalheRegisto`: GET a
    `config.RNAL_PAGINA?nr=`, 1 retry; falha de transporte **levanta** (não se escreve
    estado por falha de rede — nunca "cancelado" por timeout).
  - `persistir_detalhe(session, detalhe) -> DetalheCliente`: upsert por `nr_registo` (PK),
    idempotente.

**Zero rede real**: o `cliente_http` é injetado/mockado; as respostas são `httpx.Response`
reais (para `.text`/`.raise_for_status()` fiéis). Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.rnal.detalhe import (
    ESTADO_ATIVO,
    ESTADO_CANCELADO,
    ESTADO_INDETERMINADO,
    ESTADO_NAO_ENCONTRADO,
    ESTADO_SUSPENSO,
    ESTADOS,
    DetalheRegisto,
    obter_detalhe,
    parse_detalhe,
    persistir_detalhe,
)


# ==========================================================================
#  Fixtures HTML — réplicas fiéis da página OutSystems server-rendered
#  (estrutura verificada 2026-07-05: "RNAL nº <n>/AL" + tabela de seguro com
#  cabeçalhos Companhia de Seguros / Apólice nº / Data início / Validade).
#  Os `id` RichWidgets_wt* estão de propósito para provar que o parser os ignora.
# ==========================================================================
def _pagina(corpo: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"pt\"><head><title>RNAL</title></head><body>"
        "<form action=\"RNAL.aspx\" id=\"WebForm1\">"
        "<input type=\"hidden\" name=\"__VIEWSTATE\" value=\"dGVzdA==\" />"
        f"{corpo}"
        "</form></body></html>"
    )


def _tabela_seguro(linhas_html: str) -> str:
    return (
        "<div class=\"Titulo\">Seguro de Responsabilidade Civil</div>"
        "<table class=\"TableRecords OSFillParent\" "
        "id=\"RichWidgets_wt7_block_wtMainContent_wt2_wtTableRecords_Seguro\">"
        "<thead><tr>"
        "<th>Companhia de Seguros</th><th>Apólice nº</th>"
        "<th>Data início</th><th>Validade</th>"
        "</tr></thead>"
        f"<tbody>{linhas_html}</tbody></table>"
    )


def _bloco_dados(nr: int, nome: str) -> str:
    return (
        f"<span class=\"Label\">RNAL nº</span> <span class=\"Value\">{nr}/AL</span>"
        "<span class=\"Label\">Registado em</span> <span class=\"Value\">2019-07-16</span>"
        f"<span class=\"Label\">Nome do Alojamento</span> <span class=\"Value\">{nome}</span>"
    )


# Ativo com seguro válido (nr=100031, Zurich, validade futura 2026-12-11).
HTML_ATIVO = _pagina(
    _bloco_dados(100031, "BAIXA DE FARO ROOFTOP")
    + _tabela_seguro(
        "<tr><td>Zurich</td><td>009238995</td>"
        "<td>2025-12-12</td><td>2026-12-11</td></tr>"
    )
)

# Ativo mas com seguro CADUCADO (nr=100, validade 2025-07-03, já no passado).
# Sinal de PRODUTO (seguro caducado), NÃO um estado de cancelamento — continua "ativo".
HTML_CADUCADO = _pagina(
    _bloco_dados(100, "APARTAMENTO CADUCADO")
    + _tabela_seguro(
        "<tr><td>CA Seguros</td><td>03662951</td>"
        "<td>2024-07-03</td><td>2025-07-03</td></tr>"
    )
)

# "Registo não encontrado" — HTTP 200, página diferente, sem bloco de seguro (§2.3/§6.3).
HTML_NAO_ENCONTRADO = _pagina(
    "<div class=\"Feedback_Message\">Registo não encontrado, pesquise por Atividade!</div>"
)

# Ambíguo: nem bloco de dados ("RNAL nº") nem marcador de "não encontrado" → indeterminado.
HTML_AMBIGUO = _pagina(
    "<div class=\"Feedback_Message\">Ocorreu um erro. Tente novamente mais tarde.</div>"
)

# Bloco de dados presente mas SEM tabela de seguro (registo sem RC visível — gotcha §6.9).
HTML_SEM_SEGURO = _pagina(_bloco_dados(200, "CASA SEM SEGURO"))

# Tabela de seguro presente mas com <tbody> vazio → seguro_* None, estado ativo.
HTML_SEGURO_VAZIO = _pagina(_bloco_dados(201, "SEM APOLICE") + _tabela_seguro(""))

# Múltiplas linhas de seguro → escolher a de MAIOR validade (gotcha §6.5).
HTML_MULTI_SEGURO = _pagina(
    _bloco_dados(300, "MULTI APOLICE")
    + _tabela_seguro(
        "<tr><td>CA Seguros</td><td>111</td><td>2023-01-01</td><td>2024-01-01</td></tr>"
        "<tr><td>Zurich</td><td>222</td><td>2026-01-01</td><td>2027-05-05</td></tr>"
    )
)

# Data de validade malformada (não-ISO) → indeterminado (não None silencioso — gotcha §6.8).
HTML_DATA_MALFORMADA = _pagina(
    _bloco_dados(400, "DATA ESTRANHA")
    + _tabela_seguro(
        "<tr><td>Generali</td><td>333</td><td>2025-01-01</td><td>31/12/2026</td></tr>"
    )
)

TODAS_AS_FIXTURES = [
    HTML_ATIVO,
    HTML_CADUCADO,
    HTML_NAO_ENCONTRADO,
    HTML_AMBIGUO,
    HTML_SEM_SEGURO,
    HTML_SEGURO_VAZIO,
    HTML_MULTI_SEGURO,
    HTML_DATA_MALFORMADA,
]


# ==========================================================================
#  Dublês de teste (nada toca a rede)
# ==========================================================================
def _resp(html: str, status: int = 200) -> httpx.Response:
    pedido = httpx.Request("GET", config.RNAL_PAGINA)
    return httpx.Response(status, text=html, request=pedido)


class ClienteHTML:
    """Cliente falso: devolve sempre o mesmo HTML e regista as chamadas."""

    def __init__(self, html: str, status: int = 200):
        self.html = html
        self.status = status
        self.chamadas: list[tuple[str, dict]] = []

    def get(self, url, params=None) -> httpx.Response:
        self.chamadas.append((url, dict(params or {})))
        return _resp(self.html, self.status)


class ClienteFalha:
    """Falha `falhas` vezes (ConnectError) e depois devolve `html`; ou falha sempre."""

    def __init__(self, *, falhas: int = 0, html: str | None = None, sempre: bool = False):
        self.falhas = falhas
        self.html = html
        self.sempre = sempre
        self.n = 0

    def get(self, url, params=None) -> httpx.Response:
        self.n += 1
        if self.sempre or self.n <= self.falhas:
            raise httpx.ConnectError("falha simulada de rede")
        return _resp(self.html or "")


class Cliente500:
    """Devolve sempre HTTP 500 (erro de estado, não de transporte)."""

    def __init__(self):
        self.n = 0

    def get(self, url, params=None) -> httpx.Response:
        self.n += 1
        return _resp("<html>erro</html>", status=500)


class Relogio:
    """Captura as pausas pedidas a `dormir` (sem dormir de verdade)."""

    def __init__(self):
        self.pausas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.pausas.append(segundos)


# ==========================================================================
#  parse_detalhe — estado
# ==========================================================================
def test_parse_ativo_com_seguro():
    d = parse_detalhe(HTML_ATIVO, nr_registo=100031)
    assert isinstance(d, DetalheRegisto)
    assert d.nr_registo == 100031
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia == "Zurich"
    # zeros à esquerda preservados (texto, nunca int — gotcha §6.4)
    assert d.seguro_apolice == "009238995"
    assert d.seguro_inicio == date(2025, 12, 12)
    assert d.seguro_validade == date(2026, 12, 11)
    # parse puro: obtido_em fica por carimbar (é obter_detalhe que o põe)
    assert d.obtido_em is None


def test_parse_seguro_caducado_continua_ativo():
    # validade no passado é sinal de produto, NÃO cancelamento: estado permanece ativo.
    d = parse_detalhe(HTML_CADUCADO, nr_registo=100)
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_validade == date(2025, 7, 3)
    assert d.seguro_validade < date.today()
    assert d.seguro_companhia == "CA Seguros"


def test_parse_nao_encontrado_por_texto_em_http_200():
    d = parse_detalhe(HTML_NAO_ENCONTRADO, nr_registo=100032)
    assert d.estado == ESTADO_NAO_ENCONTRADO
    assert d.seguro_companhia is None
    assert d.seguro_apolice is None
    assert d.seguro_inicio is None
    assert d.seguro_validade is None


def test_parse_ambiguo_vai_para_indeterminado():
    # nem bloco de dados nem marcador "não encontrado" → G4: indeterminado (pára e avisa)
    d = parse_detalhe(HTML_AMBIGUO, nr_registo=999)
    assert d.estado == ESTADO_INDETERMINADO


def test_parse_sem_bloco_seguro_fica_ativo_sem_seguro():
    # registo válido sem RC visível: seguro_* None, mas o estado é ativo (gotcha §6.9)
    d = parse_detalhe(HTML_SEM_SEGURO, nr_registo=200)
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia is None
    assert d.seguro_apolice is None
    assert d.seguro_validade is None


def test_parse_tabela_seguro_vazia_fica_ativo_sem_seguro():
    d = parse_detalhe(HTML_SEGURO_VAZIO, nr_registo=201)
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia is None
    assert d.seguro_validade is None


def test_parse_multiplas_linhas_escolhe_maior_validade():
    # gotcha §6.5: o schema guarda 1 seguro → escolher a apólice de maior validade
    d = parse_detalhe(HTML_MULTI_SEGURO, nr_registo=300)
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia == "Zurich"
    assert d.seguro_apolice == "222"
    assert d.seguro_validade == date(2027, 5, 5)


def test_parse_data_malformada_vai_para_indeterminado():
    # gotcha §6.8: data presente mas não-ISO NÃO vira None silencioso → indeterminado
    d = parse_detalhe(HTML_DATA_MALFORMADA, nr_registo=400)
    assert d.estado == ESTADO_INDETERMINADO
    assert d.seguro_validade is None          # a data má não foi inventada
    assert d.seguro_companhia == "Generali"   # o resto do bloco preserva-se
    assert d.seguro_inicio == date(2025, 1, 1)


def test_parser_ancorado_em_texto_ignora_ids_outsystems():
    # os id="RichWidgets_wt7_..." mudam a cada republicação (§6.2). Trocá-los não afeta o parse.
    html_trocado = HTML_ATIVO.replace("wt7", "wt99").replace("wt2", "wt42")
    d = parse_detalhe(html_trocado, nr_registo=100031)
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia == "Zurich"
    assert d.seguro_validade == date(2026, 12, 11)


def test_estados_enum_completo():
    assert ESTADOS == {
        ESTADO_ATIVO,
        ESTADO_CANCELADO,
        ESTADO_SUSPENSO,
        ESTADO_NAO_ENCONTRADO,
        ESTADO_INDETERMINADO,
    }


def test_g4_parser_nunca_afirma_cancelado_ou_suspenso():
    # Disciplina inviolável: nenhuma fixture pública pode produzir cancelado/suspenso.
    for i, html in enumerate(TODAS_AS_FIXTURES):
        d = parse_detalhe(html, nr_registo=i)
        assert d.estado in ESTADOS
        assert d.estado not in {ESTADO_CANCELADO, ESTADO_SUSPENSO}


@pytest.mark.skip(
    reason="G4/TODO: calibrar com um nr REAL cancelado/suspenso (SPEC-DETALHE §4 item 1). "
    "Enquanto o estado não for observado na página, o parser mantém-no em 'indeterminado'."
)
def test_parse_cancelado_real_TODO_calibrar():  # pragma: no cover
    # Quando o dono fornecer um nr comprovadamente cancelado, gravar a fixture real e
    # decidir aqui se a página o mostra por banner (→ ESTADO_CANCELADO) ou se some
    # (→ ESTADO_NAO_ENCONTRADO). Até lá, NÃO afirmar 'cancelado' a partir do detalhe.
    raise NotImplementedError


# ==========================================================================
#  obter_detalhe — HTTP (injetado) + carimbo obtido_em + retry/erro
# ==========================================================================
def test_obter_detalhe_usa_pagina_e_param_nr():
    cli = ClienteHTML(HTML_ATIVO)
    d = obter_detalhe(100031, cliente_http=cli)
    assert cli.chamadas == [(config.RNAL_PAGINA, {"nr": 100031})]
    assert d.estado == ESTADO_ATIVO
    assert d.seguro_companhia == "Zurich"


def test_obter_detalhe_carimba_obtido_em_tz_aware():
    cli = ClienteHTML(HTML_ATIVO)
    antes = datetime.now(timezone.utc)
    d = obter_detalhe(100031, cliente_http=cli)
    depois = datetime.now(timezone.utc)
    assert d.obtido_em is not None
    assert d.obtido_em.tzinfo is not None
    assert antes <= d.obtido_em <= depois


def test_obter_detalhe_faz_retry_e_recupera():
    cli = ClienteFalha(falhas=1, html=HTML_ATIVO)
    relogio = Relogio()
    d = obter_detalhe(100031, cliente_http=cli, dormir=relogio)
    assert cli.n == 2                 # 1 falha + 1 sucesso
    assert len(relogio.pausas) == 1   # 1 backoff entre tentativas
    assert d.estado == ESTADO_ATIVO


def test_obter_detalhe_falha_de_rede_levanta_nao_marca_estado():
    # nunca "cancelado" por falha de transporte: propaga o erro, não devolve detalhe (§1)
    cli = ClienteFalha(sempre=True)
    relogio = Relogio()
    with pytest.raises(httpx.ConnectError):
        obter_detalhe(100031, cliente_http=cli, dormir=relogio)
    assert cli.n == 2  # esgotou as tentativas (1 + 1 retry)


def test_obter_detalhe_5xx_levanta():
    cli = Cliente500()
    with pytest.raises(httpx.HTTPStatusError):
        obter_detalhe(100031, cliente_http=cli, dormir=Relogio())
    assert cli.n == 2


# ==========================================================================
#  persistir_detalhe — upsert em detalhes_cliente (idempotente)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_detalhe.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _contar_detalhes() -> int:
    with db.get_session() as s:
        return s.scalar(select(func.count()).select_from(models.DetalheCliente))


def test_persistir_cria_linha_com_seguro(bd):
    det = parse_detalhe(HTML_ATIVO, nr_registo=100031)
    with db.get_session() as s:
        obj = persistir_detalhe(s, det)
        assert obj.nr_registo == 100031

    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d is not None
        assert d.estado_detalhado == ESTADO_ATIVO
        assert d.seguro_companhia == "Zurich"
        assert d.seguro_apolice == "009238995"
        assert d.seguro_inicio == date(2025, 12, 12)
        assert d.seguro_validade == date(2026, 12, 11)
        assert d.obtido_em is not None  # persistir carimba se o detalhe não o trouxer


def test_persistir_idempotente_nao_duplica(bd):
    det = parse_detalhe(HTML_ATIVO, nr_registo=100031)
    with db.get_session() as s:
        persistir_detalhe(s, det)
    with db.get_session() as s:
        persistir_detalhe(s, det)  # 2.ª vez: upsert, não novo INSERT
    assert _contar_detalhes() == 1


def test_persistir_atualiza_estado_existente(bd):
    # 1.ª obtenção: ativo. 2.ª: página passou a "não encontrado" → atualiza a MESMA linha.
    with db.get_session() as s:
        persistir_detalhe(s, parse_detalhe(HTML_ATIVO, nr_registo=100031))
    with db.get_session() as s:
        persistir_detalhe(s, parse_detalhe(HTML_NAO_ENCONTRADO, nr_registo=100031))

    assert _contar_detalhes() == 1
    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100031)
        assert d.estado_detalhado == ESTADO_NAO_ENCONTRADO
        # o seguro anterior é limpo quando o registo deixa de o expor
        assert d.seguro_companhia is None
        assert d.seguro_validade is None


def test_persistir_nao_encontrado_e_persistido(bd):
    # §1: mesmo "nao_encontrado" é gravado (estado + obtido_em) — só a falha de rede não escreve
    det = parse_detalhe(HTML_NAO_ENCONTRADO, nr_registo=100032)
    with db.get_session() as s:
        persistir_detalhe(s, det)
    with db.get_session() as s:
        d = s.get(models.DetalheCliente, 100032)
        assert d is not None
        assert d.estado_detalhado == ESTADO_NAO_ENCONTRADO
