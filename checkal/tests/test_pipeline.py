"""Testes do pipeline regulatório ponta-a-ponta — `app.regulatorio.pipeline`.

Contrato (SPEC-FDS4 §pipeline, SPEC-IA §1, AUTOMACAO §3)::

    correr_pipeline(session, *, cliente_ia, enviar, eventos=None) -> ResultadoPipeline

Drena `eventos_regulatorios` por processar → triagem (Haiku) → cruza concelhos afetados
com clientes ativos → redação (Sonnet) com as 3 camadas anti-alucinação → persiste em
`alertas` → envia pelo `enviar` injetado. Idempotente por `EventoRegulatorio.processado`.

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. Zero IA/rede real — `cliente_ia` e
`enviar` são **injetados** e **falsos**. BD SQLite temporária. Escrito ANTES de fechar a
implementação (TDD); um teste por propriedade.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db
import app.models as models
from app.ia.validacao import validar_alerta
from app.regulatorio import pipeline


# ==========================================================================
#  Dublês de teste — cliente IA falso (JSON na triagem, prosa na redação) + enviar
# ==========================================================================
class _Bloco:
    def __init__(self, texto: str) -> None:
        self.type = "text"
        self.text = texto


class _Mensagem:
    def __init__(self, texto: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Bloco(texto)] if texto else []
        self.stop_reason = stop_reason


class _Messages:
    """`create(**kw)`: JSON se for structured output (triagem), senão a prosa da vez."""

    def __init__(self, json_resp: str, prosa: list[str]) -> None:
        self._json = json_resp
        self._prosa = prosa or [""]
        self._np = 0
        self.chamadas: list[dict] = []

    def create(self, **kwargs) -> _Mensagem:
        self.chamadas.append(kwargs)
        if "output_config" in kwargs:  # triagem (structured output)
            return _Mensagem(self._json)
        i = min(self._np, len(self._prosa) - 1)  # redação
        self._np += 1
        return _Mensagem(self._prosa[i])


class ClienteIAFalso:
    def __init__(self, json_resp: str, *prosa: str) -> None:
        self.messages = _Messages(json_resp, list(prosa))


class EnviarFalso:
    """`enviar(*, para, assunto, html, anexos, **kw)`: regista e devolve um id."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio

        self.chamadas.append(
            {"para": para, "assunto": assunto, "html": html, "anexos": list(anexos), "kw": kw}
        )
        return ResultadoEnvio(id="re_pipeline_test")

    @property
    def n(self) -> int:
        return len(self.chamadas)


# ==========================================================================
#  Fixtures de dados — excerto (fonte de verdade), url e respostas scriptadas
# ==========================================================================
URL = "https://files.diariodarepublica.pt/gratuitos/2s/2025/07/2S142A0000S00.pdf#municipio-de-braga"

# Excerto canónico: coima 2.500–4.000 €, prazo 30 dias, data 15/06/2026. Nada mais.
EXCERTO = (
    "Regulamento Municipal de Alojamento Local de Braga. Foi criada uma área de contenção "
    "onde ficam suspensos novos registos. A coima aplicável varia entre 2.500 € e 4.000 €. "
    "Os titulares dispõem de um prazo de 30 dias, a contar de 15/06/2026, para comunicar."
)

# Alerta fiel: só valores do excerto + cita a url.
ALERTA_VALIDO = (
    "(a) Foi publicado um novo regulamento municipal de Alojamento Local em Braga. "
    "(b) Afeta o teu AL? Possivelmente: o teu alojamento em Braga pode ficar abrangido "
    "pela nova área de contenção. (c) Confirma a tua situação; a coima varia entre "
    "2.500 € e 4.000 € e há um prazo de 30 dias. Consulta o documento em " + URL
)

# Alerta com um valor INVENTADO (7.500 € não está no excerto) → reprovado pela validação.
ALERTA_INVALIDO = (
    "Foi publicado um regulamento em Braga. A coima pode chegar a 7.500 €. "
    "Consulta em " + URL
)

JSON_SIM = (
    '{"relevante_para_al": "sim", "concelhos": ["Braga"], '
    '"tipo": "regulamento", "resumo_1_frase": "Novo regulamento de AL em Braga."}'
)
JSON_NAO = (
    '{"relevante_para_al": "nao", "concelhos": [], '
    '"tipo": "outro", "resumo_1_frase": "Nada de AL."}'
)
JSON_DUVIDA = (
    '{"relevante_para_al": "duvida", "concelhos": ["Braga"], '
    '"tipo": "regulamento", "resumo_1_frase": "Pode afetar AL em Braga."}'
)


# ==========================================================================
#  BD SQLite temporária + helpers de sementeira
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_pipeline.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _semear_cliente_com_al(
    s, *, cliente_id: int, nr_registo: int, concelho: str, email: str = "c@exemplo.pt",
    estado: str = "ativo",
) -> None:
    s.add(models.Registo(
        nr_registo=nr_registo, nome_alojamento=f"AL {nr_registo}",
        modalidade="Apartamento", concelho=concelho, distrito=concelho,
        titular_tipo="singular", hash_campos="h",
    ))
    s.add(models.Cliente(id=cliente_id, email=email, nome="Cliente", estado=estado))
    s.flush()
    s.add(models.ClienteRegisto(cliente_id=cliente_id, nr_registo=nr_registo))
    s.flush()


def _semear_evento(
    s, *, url: str = URL, titulo: str = "Regulamento n.º 927/2025 — Alojamento Local de Braga",
    concelhos: list[str] | None = None, texto: str | None = EXCERTO,
) -> models.EventoRegulatorio:
    ev = models.EventoRegulatorio(
        fonte="DRE", url=url, titulo=titulo, publicado_em=date(2025, 7, 24),
        concelhos=concelhos if concelhos is not None else ["Braga"],
        triagem=None, processado=False,
    )
    s.add(ev)
    s.flush()
    if texto is not None:
        ev.texto = texto
    return ev


# ==========================================================================
#  Caminho feliz — evento relevante gera e envia um alerta citado
# ==========================================================================
def test_evento_relevante_gera_e_envia_alerta(bd):
    enviar = EnviarFalso()
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)  # ev com `.texto`=EXCERTO (referência forte → sem GC)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=enviar,
            eventos=[ev],  # passagem de mão do dre_pipeline: corpo por excerto
        )

    assert res.eventos_processados == 1
    assert res.eventos_relevantes == 1
    assert res.enviados == 1
    assert len(res.alertas) == 1

    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert a.origem == pipeline.ORIGEM_REGULATORIO
        assert a.cliente_id == 1
        assert a.nr_registo == 100031
        assert a.canal == pipeline.CANAL_EMAIL
        assert a.enviado_em is not None
        assert a.conteudo == ALERTA_VALIDO
        # o evento ficou triado e processado
        ev = s.query(models.EventoRegulatorio).one()
        assert ev.processado is True
        assert ev.triagem == "relevante"
        assert ev.resumo_ia == "Novo regulamento de AL em Braga."

    # o email saiu uma vez, para o cliente, com o link da fonte e o disclaimer
    assert enviar.n == 1
    chamada = enviar.chamadas[0]
    assert chamada["para"] == "c@exemplo.pt"
    assert URL in chamada["html"]
    assert "aconselhamento" in chamada["html"].lower()
    assert chamada["kw"]["idempotency_key"] == "reg-1-100031"


def test_alerta_persistido_passa_a_validacao_e_cita_a_url(bd):
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert URL in a.conteudo
        assert validar_alerta(a.conteudo, url_fonte=URL, excerto=EXCERTO).valido


def test_duvida_conta_como_relevante(bd):
    # 🧯 regra conservadora: na dúvida NÃO se cala — 'duvida' segue para redação.
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_DUVIDA, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    assert res.eventos_relevantes == 1
    assert len(res.alertas) == 1
    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).one().triagem == "duvida"


# ==========================================================================
#  Irrelevante — marca processado, não gera alerta
# ==========================================================================
def test_evento_irrelevante_nao_gera_alerta(bd):
    enviar = EnviarFalso()
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_NAO, ALERTA_VALIDO), enviar=enviar,
            eventos=[ev],
        )
    assert res.eventos_processados == 1
    assert res.eventos_relevantes == 0
    assert res.alertas == []
    assert enviar.n == 0
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
        ev = s.query(models.EventoRegulatorio).one()
        assert ev.processado is True
        assert ev.triagem == "irrelevante"


# ==========================================================================
#  Relevante mas sem clientes no concelho — processado, sem alerta
# ==========================================================================
def test_relevante_sem_clientes_no_concelho_nao_gera_alerta(bd):
    with db.get_session() as s:
        # cliente noutro concelho (Faro) — o evento é de Braga
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Faro")
        ev = _semear_evento(s, concelhos=["Braga"])
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    assert res.eventos_relevantes == 1
    assert res.alertas == []
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0
        assert s.query(models.EventoRegulatorio).one().processado is True


def test_evento_sem_concelhos_nao_cruza_ninguem(bd):
    # concelho não reconhecido pelo dre_client → evento com concelhos=[] → sem cruzamento.
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s, concelhos=[])
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_NAO, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    # JSON_NAO tem concelhos=[] também → nada a cruzar; de qualquer forma processado.
    assert res.alertas == []
    with db.get_session() as s:
        assert s.query(models.EventoRegulatorio).one().processado is True


# ==========================================================================
#  Fan-out — dois clientes no concelho afetado recebem cada um
# ==========================================================================
def test_dois_clientes_no_concelho_recebem_cada_um(bd):
    enviar = EnviarFalso()
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga", email="a@x.pt")
        _semear_cliente_com_al(s, cliente_id=2, nr_registo=100032, concelho="Braga", email="b@x.pt")
        ev = _semear_evento(s)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=enviar,
            eventos=[ev],
        )
    assert len(res.alertas) == 2
    assert res.enviados == 2
    assert {c["para"] for c in enviar.chamadas} == {"a@x.pt", "b@x.pt"}
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 2


# ==========================================================================
#  Cliente cancelado não recebe
# ==========================================================================
def test_cliente_cancelado_nao_recebe(bd):
    with db.get_session() as s:
        _semear_cliente_com_al(
            s, cliente_id=1, nr_registo=100031, concelho="Braga", estado="cancelado"
        )
        ev = _semear_evento(s)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    assert res.alertas == []
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 0


# ==========================================================================
#  enviar=None (envio indisponível) → persiste o alerta por enviar
# ==========================================================================
def test_enviar_none_persiste_sem_enviar(bd):
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=None,
            eventos=[ev],
        )
    assert len(res.alertas) == 1
    assert res.enviados == 0
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert a.enviado_em is None  # persistido, por enviar


# ==========================================================================
#  Idempotência — 2.ª passagem (fila da BD) não revê eventos já processados
# ==========================================================================
def test_idempotente_nao_reprocessa(bd):
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=EnviarFalso(),
            eventos=[ev],
        )
    # 2.ª corrida, agora varrendo a fila da BD: o evento já está processado → nada novo.
    enviar2 = EnviarFalso()
    with db.get_session() as s:
        res2 = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=enviar2
        )
    assert res2.eventos_processados == 0
    assert res2.alertas == []
    assert enviar2.n == 0
    with db.get_session() as s:
        assert s.query(models.Alerta).count() == 1  # continua só 1


# ==========================================================================
#  Fila da BD (eventos=None) — sem corpo persistido → excerto degrada ao título
# ==========================================================================
def test_fila_da_bd_processa_eventos_pendentes(bd):
    # eventos=None → varre `processado=False`. Sem `.texto` persistido, o excerto é o
    # título; a prosa com valores fora do título é reprovada e cai no manual (válido).
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        _semear_evento(s, texto=None)  # persistido sem corpo
        res = pipeline.correr_pipeline(
            s, cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO), enviar=EnviarFalso()
        )
    assert res.eventos_processados == 1
    assert len(res.alertas) == 1
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert URL in a.conteudo
        titulo = s.query(models.EventoRegulatorio).one().titulo
        assert validar_alerta(a.conteudo, url_fonte=URL, excerto=titulo).valido


# ==========================================================================
#  Camada 3 — IA que inventa cai no formato manual (válido, citado)
# ==========================================================================
def test_ia_que_inventa_cai_no_formato_manual_valido(bd):
    # a IA devolve o mesmo alerta com 7.500 € (órfão vs excerto) nas 2 tentativas → manual.
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        pipeline.correr_pipeline(
            s,
            cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_INVALIDO, ALERTA_INVALIDO),
            enviar=EnviarFalso(),
            eventos=[ev],
        )
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert "7.500" not in a.conteudo           # nada de valor inventado
        assert URL in a.conteudo                    # o fallback cita sempre a url
        assert validar_alerta(a.conteudo, url_fonte=URL, excerto=EXCERTO).valido


# ==========================================================================
#  Excerto — degrada ao título quando o evento não traz corpo (`.texto`)
# ==========================================================================
def test_excerto_degrada_ao_titulo_sem_texto(bd):
    # Mesmo passando o evento, sem `.texto` o excerto é o título; a IA a inventar valores
    # (2.500 €, fora do título) é reprovada e cai no manual — que só cita url + título.
    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s, texto=None)  # sem corpo
        pipeline.correr_pipeline(
            s,
            cliente_ia=ClienteIAFalso(JSON_SIM, ALERTA_VALIDO),  # cita 2.500 €, fora do título
            enviar=EnviarFalso(),
            eventos=[ev],
        )
    with db.get_session() as s:
        a = s.query(models.Alerta).one()
        assert "2.500" not in a.conteudo   # o valor não fundamentado no título não passa
        assert URL in a.conteudo
        titulo = s.query(models.EventoRegulatorio).one().titulo
        assert validar_alerta(a.conteudo, url_fonte=URL, excerto=titulo).valido


# ==========================================================================
#  Erro da IA na triagem propaga (não fabrica veredicto)
# ==========================================================================
def test_triagem_sem_json_valido_propaga_erro_ia(bd):
    from app.ia import cliente as cli

    with db.get_session() as s:
        _semear_cliente_com_al(s, cliente_id=1, nr_registo=100031, concelho="Braga")
        ev = _semear_evento(s)
        with pytest.raises(cli.ErroIA):
            pipeline.correr_pipeline(
                s, cliente_ia=ClienteIAFalso("isto não é JSON", ALERTA_VALIDO),
                enviar=EnviarFalso(), eventos=[ev],
            )
