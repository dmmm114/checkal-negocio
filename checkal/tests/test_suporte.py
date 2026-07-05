"""Testes do suporte de 1.ª linha por IA (FDS 5) — `app.suporte.correr_suporte`.

Contrato (SPEC-FDS5 §suporte, AUTOMACAO.md §5):

    correr_suporte(session, *, leitor, cliente_ia, enviar, escalar) -> ResultadoSuporte
        Cron de 15 min: lê `apoio@` via IMAP (leitor injetado); por cada email não lido
        compõe uma decisão+resposta com Sonnet (`app.ia.cliente`, injetado) apoiado numa
        KB (FAQ + estado do cliente lido da BD). Responde a perguntas factuais; **ESCALA
        ao dono** (Telegram/forward injetado) — e **não responde sozinho** — se detetar
        pedido jurídico específico, reclamação, intenção de cancelar com queixa, ou
        confiança baixa.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Zero rede/IA/IMAP real. O `leitor`
(IMAP), o `cliente_ia` (Anthropic), o `enviar` (Resend) e o `escalar` (Telegram/forward)
são **todos injetados** (dublês). BD SQLite temporária. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app import suporte


# ==========================================================================
#  Dublês — IMAP (leitor), IA (cliente), envio, escalação
# ==========================================================================
class _Leitor:
    """Leitor de caixa injetado: devolve emails não lidos e regista os marcados."""

    def __init__(self, mensagens: list[suporte.EmailRecebido]) -> None:
        self._mensagens = list(mensagens)
        self.marcados: list[str] = []

    def nao_lidos(self) -> list[suporte.EmailRecebido]:
        return list(self._mensagens)

    def marcar_processado(self, uid: str) -> None:
        self.marcados.append(uid)


class _BlocoIA:
    def __init__(self, texto: str) -> None:
        self.type = "text"
        self.text = texto


class _MsgIA:
    def __init__(self, texto: str) -> None:
        self.content = [_BlocoIA(texto)] if texto else []
        self.stop_reason = "end_turn"


class _MessagesIA:
    def __init__(self, resposta_json: str) -> None:
        self._json = resposta_json
        self.chamadas: list[dict] = []

    def create(self, **kwargs) -> _MsgIA:
        self.chamadas.append(kwargs)
        return _MsgIA(self._json)


class _ClienteIA:
    """`.messages.create(**kwargs)` devolve a decisão JSON scriptada e regista os kwargs."""

    def __init__(self, resposta_json: str) -> None:
        self.messages = _MessagesIA(resposta_json)


def _decisao_json(
    *, acao="responder", categoria="factual", confianca="alta", resposta="Resposta factual."
) -> str:
    import json

    return json.dumps(
        {"acao": acao, "categoria": categoria, "confianca": confianca, "resposta": resposta}
    )


class _Enviar:
    """Enviador transacional injetado (dublê de `app.envio`)."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, anexos=(), **kw):
        from app.envio import ResultadoEnvio

        self.chamadas.append({"para": para, "assunto": assunto, "html": html, "kw": kw})
        return ResultadoEnvio(id="re_suporte_teste")


class _Escalar:
    """Escalador injetado (dublê de Telegram/forward ao dono)."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, *, assunto, corpo):
        self.chamadas.append({"assunto": assunto, "corpo": corpo})


def _email(
    uid="1", de="dono@exemplo.pt", assunto="Dúvida", corpo="Qual é o estado do meu registo?"
) -> suporte.EmailRecebido:
    return suporte.EmailRecebido(uid=uid, de=de, assunto=assunto, corpo=corpo)


# ==========================================================================
#  BD SQLite temporária (mesma disciplina do test_dre_pipeline)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_suporte.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _cria_cliente(s, *, email="dono@exemplo.pt", nr=100031, concelho="Braga", estado="ativo"):
    s.add(models.Registo(
        nr_registo=nr, nome_alojamento="Casa do Minho", modalidade="Moradia",
        concelho=concelho, distrito=concelho, titular_tipo="singular", hash_campos="h",
    ))
    s.add(models.Cliente(id=1, email=email, nome="Dono", plano="anual", estado=estado))
    s.flush()
    s.add(models.ClienteRegisto(cliente_id=1, nr_registo=nr))
    s.flush()


# ==========================================================================
#  Caminho feliz — pergunta factual → responde, não escala
# ==========================================================================
def test_factual_responde_e_nao_escala(bd):
    leitor = _Leitor([_email()])
    ia = _ClienteIA(_decisao_json(resposta="O teu registo nº 100031 está ativo no RNAL."))
    enviar, escalar = _Enviar(), _Escalar()

    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )

    assert res.lidos == 1
    assert res.respondidos == 1
    assert res.escalados == 0
    # respondeu ao remetente, não escalou
    assert len(enviar.chamadas) == 1
    assert enviar.chamadas[0]["para"] == "dono@exemplo.pt"
    assert "100031" in enviar.chamadas[0]["html"]
    assert escalar.chamadas == []
    # marcou o email como processado (idempotência: não reprocessa)
    assert leitor.marcados == ["1"]


def test_estado_do_cliente_e_faq_vao_na_kb(bd):
    # a KB passada ao modelo tem de conter o ESTADO do cliente (registo/concelho) e a FAQ.
    leitor = _Leitor([_email(assunto="Estado", corpo="Como está o meu AL?")])
    ia = _ClienteIA(_decisao_json())
    with db.get_session() as s:
        _cria_cliente(s, concelho="Loulé")
        suporte.correr_suporte(s, leitor=leitor, cliente_ia=ia, enviar=_Enviar(), escalar=_Escalar())

    kwargs = ia.messages.chamadas[0]
    sistema = kwargs["system"]
    sistema_txt = sistema if isinstance(sistema, str) else str(sistema)
    assert "100031" in sistema_txt          # o registo do cliente
    assert "Loulé" in sistema_txt           # o concelho do cliente
    assert "49" in sistema_txt               # a FAQ (preço) faz parte da KB
    # o corpo do email vai como mensagem do utilizador
    assert "Como está o meu AL?" in kwargs["messages"][0]["content"]
    # structured output: usou o esquema de suporte
    assert kwargs["output_config"]["format"]["schema"] == suporte.ESQUEMA_SUPORTE


# ==========================================================================
#  Gatilhos de escalação — escala e NÃO responde sozinho
# ==========================================================================
@pytest.mark.parametrize("categoria", ["juridico", "reclamacao", "cancelar_queixa"])
def test_gatilho_de_categoria_escala_e_nao_responde(bd, categoria):
    # mesmo que o modelo diga acao=responder, a categoria de gatilho força a escalação.
    leitor = _Leitor([_email(corpo="Quero processar-vos / reclamação / cancelo com queixa")])
    ia = _ClienteIA(_decisao_json(acao="responder", categoria=categoria, confianca="alta"))
    enviar, escalar = _Enviar(), _Escalar()

    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )

    assert res.escalados == 1
    assert res.respondidos == 0
    assert len(escalar.chamadas) == 1
    assert enviar.chamadas == []            # NÃO responde sozinho
    assert leitor.marcados == ["1"]         # mas marca como tratado
    # o email original vai no corpo da escalação (o dono vê tudo)
    assert "dono@exemplo.pt" in escalar.chamadas[0]["corpo"]


def test_confianca_baixa_escala(bd):
    leitor = _Leitor([_email()])
    ia = _ClienteIA(_decisao_json(acao="responder", categoria="factual", confianca="baixa"))
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )
    assert res.escalados == 1
    assert res.respondidos == 0
    assert enviar.chamadas == []
    assert len(escalar.chamadas) == 1


def test_acao_escalar_do_modelo_e_respeitada(bd):
    leitor = _Leitor([_email()])
    ia = _ClienteIA(_decisao_json(acao="escalar", categoria="outro", confianca="alta"))
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )
    assert res.escalados == 1
    assert enviar.chamadas == []


# ==========================================================================
#  Robustez — IA indisponível / JSON inválido → escala (nunca responde à toa)
# ==========================================================================
def test_ia_indisponivel_escala_sem_chamar_modelo(bd):
    leitor = _Leitor([_email()])
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=None, enviar=enviar, escalar=escalar
        )
    assert res.escalados == 1
    assert res.respondidos == 0
    assert enviar.chamadas == []
    assert len(escalar.chamadas) == 1
    assert leitor.marcados == ["1"]


def test_json_invalido_do_modelo_escala(bd):
    leitor = _Leitor([_email()])
    ia = _ClienteIA("isto não é JSON")     # pedir_json → ErroIA → escala por segurança
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )
    assert res.escalados == 1
    assert res.respondidos == 0
    assert enviar.chamadas == []


def test_decisao_fora_do_enum_escala(bd):
    # drift do modelo: acao desconhecida → decisão insegura → escala (nunca responde).
    leitor = _Leitor([_email()])
    ia = _ClienteIA(_decisao_json(acao="qualquer_coisa", categoria="factual", confianca="alta"))
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )
    assert res.escalados == 1
    assert enviar.chamadas == []


# ==========================================================================
#  Salvaguardas de entrega — nada se perde
# ==========================================================================
def test_enviar_indisponivel_escala_como_salvaguarda(bd):
    # decisão de responder mas sem enviador → escala para o dono (não se perde o email).
    leitor = _Leitor([_email()])
    ia = _ClienteIA(_decisao_json())
    escalar = _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=None, escalar=escalar
        )
    assert res.respondidos == 0
    assert res.escalados == 1
    assert len(escalar.chamadas) == 1
    assert leitor.marcados == ["1"]


def test_leitor_none_nao_faz_nada(bd):
    # caixa indisponível (live-gate) → cron não faz nada, sem tocar em IA/envio.
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        res = suporte.correr_suporte(
            s, leitor=None, cliente_ia=None, enviar=enviar, escalar=escalar
        )
    assert res.lidos == 0
    assert res.respondidos == 0
    assert res.escalados == 0
    assert enviar.chamadas == []
    assert escalar.chamadas == []


# ==========================================================================
#  Remetente sem subscrição — responde à FAQ na mesma
# ==========================================================================
def test_sem_subscricao_ainda_responde_faq(bd):
    leitor = _Leitor([_email(de="curioso@exemplo.pt", corpo="Quanto custa o CheckAL?")])
    ia = _ClienteIA(_decisao_json(resposta="O CheckAL custa 49€/ano."))
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)  # cliente é dono@, não curioso@
        res = suporte.correr_suporte(
            s, leitor=leitor, cliente_ia=ia, enviar=enviar, escalar=escalar
        )
    assert res.respondidos == 1
    assert enviar.chamadas[0]["para"] == "curioso@exemplo.pt"
    # a KB assinala que não há subscrição associada a este email
    sistema = ia.messages.chamadas[0]["system"]
    assert "sem subscrição" in (sistema if isinstance(sistema, str) else str(sistema)).lower()


# ==========================================================================
#  Vários emails — cada um segue o seu ramo, isolados
# ==========================================================================
def test_varios_emails_ramos_independentes(bd):
    factual = _email(uid="10", corpo="Como mudo o cartão?")
    juridico = _email(uid="11", corpo="Vou avançar com uma ação judicial contra vocês.")
    # o mesmo cliente_ia responderia igual; usa-se um leitor com 2 emails e 2 clientes IA
    # distintos por email não é possível com um único injetado — testa-se via 2 corridas.
    ia_factual = _ClienteIA(_decisao_json(categoria="factual"))
    ia_juridico = _ClienteIA(_decisao_json(categoria="juridico"))
    enviar, escalar = _Enviar(), _Escalar()
    with db.get_session() as s:
        _cria_cliente(s)
        r1 = suporte.correr_suporte(
            s, leitor=_Leitor([factual]), cliente_ia=ia_factual, enviar=enviar, escalar=escalar
        )
        r2 = suporte.correr_suporte(
            s, leitor=_Leitor([juridico]), cliente_ia=ia_juridico, enviar=enviar, escalar=escalar
        )
    assert r1.respondidos == 1 and r1.escalados == 0
    assert r2.respondidos == 0 and r2.escalados == 1
    assert len(enviar.chamadas) == 1
    assert len(escalar.chamadas) == 1


# ==========================================================================
#  Live-gate dos compositores — sob modo de teste nada toca a rede/IMAP
# ==========================================================================
def test_obter_leitor_e_escalador_none_sob_modo_teste(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    assert suporte.obter_leitor() is None
    assert suporte.obter_escalador() is None


def test_obter_leitor_none_sem_credenciais_imap(monkeypatch):
    # modo de teste desligado mas sem IMAP configurado → continua a não ligar (live-gate).
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "IMAP_HOST", "")
    monkeypatch.setattr(config, "IMAP_USER", "")
    monkeypatch.setattr(config, "IMAP_PASSWORD", "")
    assert suporte.obter_leitor() is None


def test_obter_escalador_none_sem_telegram(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    assert suporte.obter_escalador() is None
