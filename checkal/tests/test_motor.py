"""Testes do motor de campanhas (FDS 6, SPEC-FDS6.md §motor) — HARD-GATED.

Contrato:

    pode_enviar_frio(contacto, *, lista_dgc=(), log_optout=()) -> bool
      TRIPLO GATE, CUMULATIVO:
        1. `config.pode_enviar_frio_global()` — parecer OK E modo teste OFF E SMTP cold ativo;
        2. núcleo compliance — coletiva 5/6 (`nif.e_enderecavel`) + email genérico
           (`email.e_generico`) via `minimizacao.filtrar_enderecaveis`;
        3. não oposto — DGC + opt-out (`optout.filtrar_optout`).

    correr_campanhas(session, *, remetente_frio=None, gerar_cartas=None, ...) -> ResultadoCampanha
      gatilhos -> segmentar (compliance) -> compõe copy ->
        · cold: só ENVIA via `remetente_frio` se `pode_enviar_frio(contacto)`; senão
          fica em fila `pendentes_parecer` (draft composto mas não enviado);
        · carta: gera o PDF (upload manual e-carta).
      Janela <= 72h; cap diário; log de opt-outs/proveniências; idempotente.

🚦 O PORTÃO é CÓDIGO: com `CHECKAL_PARECER_RGPD_OK=False` (default), NENHUM email
frio sai — um registo novo coletivo-genérico gera o draft mas fica pendente_parecer;
um singular gera carta e NUNCA cold.

DISCIPLINA: MODO DE TESTE, LIVE-GATED. Zero rede/SMTP — `remetente_frio` e
`gerar_cartas` são INJETADOS/MOCKADOS. Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
from app.campanhas import motor
from app.campanhas.cold_email import ResultadoFrio
from app.compliance.minimizacao import ContactoEnderecavel

UTC = timezone.utc
AGORA = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# ==========================================================================
#  Fixtures: BD SQLite temporária isolada (espelha test_gatilhos)
# ==========================================================================
@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_motor.db'}"
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
#  Duplos de teste
# ==========================================================================
class FakeRemetente:
    """Remetente frio falso: regista cada chamada e devolve um `ResultadoFrio`.

    NUNCA toca a rede — substitui o callable de `obter_remetente_frio()`."""

    def __init__(self):
        self.chamadas: list[dict] = []

    def __call__(self, *, para, assunto, html, **kw):
        self.chamadas.append({"para": para, "assunto": assunto, "html": html})
        return ResultadoFrio(
            para=para,
            remetente="CheckAL <geral@getcheckal.com>",
            link_remocao=f"https://checkal.pt/remover?e={para}",
        )


class FakeCartas:
    """Gerador de cartas falso: captura os prospetos e devolve bytes de PDF."""

    def __init__(self):
        self.prospetos: list = []

    def __call__(self, prospetos, **kw):
        self.prospetos = list(prospetos)
        return b"%PDF-1.4 fake"


def _abrir_todos_os_gates(monkeypatch):
    """Abre o triplo gate GLOBAL: parecer OK + modo de teste OFF + SMTP presente."""
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "cold@getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "segredo")


# ==========================================================================
#  Semeadores
# ==========================================================================
def _semear_registo(
    *,
    nr: int,
    nif: str,
    email: str,
    nome: str,
    concelho: str = "Lisboa",
    endereco: str = "Rua Um, 1",
    cod_postal: str = "1000-001",
    freguesia: str = "Sé",
    tipo: str = "coletiva",
    desaparecido: bool = False,
) -> None:
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=nr,
            nome_alojamento=f"AL {nr}",
            concelho=concelho,
            endereco=endereco,
            cod_postal=cod_postal,
            freguesia=freguesia,
            titular_tipo=tipo,
            titular_nome=nome,
            nif=nif,
            email=email,
            visto_primeiro=AGORA,
            visto_ultimo=AGORA,
            desaparecido_em=(AGORA if desaparecido else None),
        ))


def _semear_evento_registo(*, tipo: str, nr: int, quando: datetime = AGORA) -> int:
    with db.get_session() as s:
        ev = models.EventoRegisto(
            nr_registo=nr, tipo=tipo, detetado_em=quando, processado=False,
        )
        s.add(ev)
        s.flush()
        return ev.id


def _semear_evento_regulatorio(*, concelhos: list[str], url: str,
                               publicado_em: date = date(2026, 7, 4)) -> int:
    with db.get_session() as s:
        ev = models.EventoRegulatorio(
            fonte="DRE", url=url, titulo="Regulamento municipal de AL",
            concelhos=concelhos, triagem="relevante", publicado_em=publicado_em,
            processado=True,
        )
        s.add(ev)
        s.flush()
        return ev.id


# Amostras canónicas -----------------------------------------------------
COLETIVA_GENERICA = dict(nif="500000001", email="geral@empresa.pt", nome="Empresa Um, Lda")
COLETIVA_GENERICA_2 = dict(nif="600000002", email="reservas@dois.pt", nome="Dois SA")
COLETIVA_PESSOAL = dict(nif="500000003", email="joao.silva@tres.pt", nome="Tres, Lda")
SINGULAR = dict(nif="123456789", email="ana.silva@mail.pt", nome="Ana Silva", tipo="singular")
ENI_8 = dict(nif="800000005", email="geral@seis.pt", nome="Empresario Seis", tipo="singular")


def _novo_coletiva_generica(nr: int, concelho: str = "Lisboa") -> int:
    _semear_registo(nr=nr, concelho=concelho, **COLETIVA_GENERICA)
    return _semear_evento_registo(tipo="novo", nr=nr)


def _novo_singular(nr: int, concelho: str = "Lisboa") -> int:
    _semear_registo(nr=nr, concelho=concelho, **SINGULAR)
    return _semear_evento_registo(tipo="novo", nr=nr)


def _correr(**kw) -> motor.ResultadoCampanha:
    kw.setdefault("agora", AGORA)
    with db.get_session() as s:
        return motor.correr_campanhas(s, **kw)


def _contacto_generico(nr=1) -> ContactoEnderecavel:
    return ContactoEnderecavel(
        nr_registo=nr, nif="500000001", nome_coletiva="Empresa Um, Lda",
        email_generico="geral@empresa.pt", concelho="Lisboa",
    )


# ==========================================================================
#  pode_enviar_frio — TRIPLO GATE (o coração do sprint)
# ==========================================================================
def test_pode_enviar_frio_false_sem_parecer_mesmo_com_contacto_perfeito():
    # Estado de fábrica: parecer OFF ⇒ False, ainda que o contacto seja impecável.
    assert config.CHECKAL_PARECER_RGPD_OK is False
    assert motor.pode_enviar_frio(_contacto_generico()) is False


def test_pode_enviar_frio_true_com_todos_os_gates_e_contacto_valido(monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    assert motor.pode_enviar_frio(_contacto_generico()) is True


def test_pode_enviar_frio_false_para_nif_singular_mesmo_com_gates(monkeypatch):
    # O portão de compliance é o NIF: um singular NUNCA passa, gates abertos ou não.
    _abrir_todos_os_gates(monkeypatch)
    c = ContactoEnderecavel(
        nr_registo=9, nif="123456789", nome_coletiva="Nao É Coletiva",
        email_generico="geral@x.pt", concelho="Porto",
    )
    assert motor.pode_enviar_frio(c) is False


def test_pode_enviar_frio_false_para_email_pessoal(monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    c = ContactoEnderecavel(
        nr_registo=9, nif="500000001", nome_coletiva="X, Lda",
        email_generico="joao.silva@x.pt", concelho="Porto",
    )
    assert motor.pode_enviar_frio(c) is False


def test_pode_enviar_frio_false_se_em_optout(monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    c = _contacto_generico()
    assert motor.pode_enviar_frio(c, log_optout={"geral@empresa.pt"}) is False
    assert motor.pode_enviar_frio(c, lista_dgc={"  GERAL@EMPRESA.PT "}) is False


def test_pode_enviar_frio_false_se_modo_teste_on(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "u")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "p")
    assert motor.pode_enviar_frio(_contacto_generico()) is False


# ==========================================================================
#  compor_email_frio — copy B2B (COPY-VENDAS.md §2), sem opt-out literal
# ==========================================================================
def test_compor_email_frio_traz_campos_e_copy():
    assunto, html = motor.compor_email_frio(_contacto_generico(nr=93415))
    assert "93415" in assunto
    assert "prazos" in assunto.lower()
    assert "Empresa Um, Lda" in html
    assert "93415" in html
    assert "Lisboa" in html
    assert "independente" in html
    assert "não é uma notificação oficial" in html
    assert "mais de 10.000" in html
    assert "25.000" in html                       # coima coletiva (config.COIMA)
    assert "checkal.pt/v/93415" in html
    assert "Cosmic Oasis" in html                 # responsável identificado (sem placeholders)


def test_compor_email_frio_nao_crava_link_remover_deixa_para_o_seam():
    # O opt-out 1-clique personalizado é carimbado pelo seam de envio; a copy não
    # deve cravar "checkal.pt/remover" (senão o seam não personaliza o corpo).
    _, html = motor.compor_email_frio(_contacto_generico())
    assert "checkal.pt/remover" not in html


# ==========================================================================
#  🚦 correr_campanhas — parecer OFF: draft, mas NÃO envia (o teste-âncora)
# ==========================================================================
def test_coletiva_generica_nova_gera_pendente_e_nao_envia(bd):
    _novo_coletiva_generica(1)
    rem = FakeRemetente()

    res = _correr(remetente_frio=rem)

    assert res.enviados == []                     # NADA enviado (parecer OFF)
    assert rem.chamadas == []                      # o remetente NUNCA foi chamado
    assert len(res.pendentes_parecer) == 1
    rasc = res.pendentes_parecer[0]
    assert rasc.para == "geral@empresa.pt"
    assert "1" in rasc.assunto
    assert "Empresa Um, Lda" in rasc.html
    assert rasc.proveniencia                       # proveniência registada
    assert res.carta_pdf is None
    assert res.cartas == 0


def test_singular_novo_gera_carta_e_nunca_cold(bd):
    _novo_singular(2)
    cartas = FakeCartas()
    rem = FakeRemetente()

    res = _correr(remetente_frio=rem, gerar_cartas=cartas)

    # NUNCA cold para singular
    assert res.enviados == []
    assert res.pendentes_parecer == []
    assert rem.chamadas == []
    # carta gerada
    assert res.cartas == 1
    assert res.carta_pdf == b"%PDF-1.4 fake"
    assert len(cartas.prospetos) == 1
    assert cartas.prospetos[0].nr_registo == 2


def test_carta_default_usa_gerador_real_e_produz_pdf(bd):
    _novo_singular(3)
    res = _correr()                                # sem gerar_cartas injetado
    assert res.cartas == 1
    assert res.carta_pdf is not None
    assert bytes(res.carta_pdf[:5]) == b"%PDF-"


def test_lote_misto_reparte_cold_e_carta(bd):
    _novo_coletiva_generica(1)
    _novo_singular(2)
    _semear_registo(nr=3, concelho="Lisboa", **COLETIVA_PESSOAL)  # coletiva email pessoal -> carta
    _semear_evento_registo(tipo="novo", nr=3)
    cartas = FakeCartas()

    res = _correr(gerar_cartas=cartas)

    assert [r.para for r in res.pendentes_parecer] == ["geral@empresa.pt"]
    assert sorted(p.nr_registo for p in cartas.prospetos) == [2, 3]
    assert res.cartas == 2


# ==========================================================================
#  Gates abertos: cold ENVIA via remetente_frio
# ==========================================================================
def test_com_gates_abertos_envia_via_remetente(bd, monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    _novo_coletiva_generica(1)
    rem = FakeRemetente()

    res = _correr(remetente_frio=rem)

    assert len(res.enviados) == 1
    assert res.pendentes_parecer == []
    assert len(rem.chamadas) == 1
    ch = rem.chamadas[0]
    assert ch["para"] == "geral@empresa.pt"
    assert "prazos" in ch["assunto"].lower()
    assert "Empresa Um, Lda" in ch["html"]


def test_gates_abertos_mas_sem_remetente_fica_pendente(bd, monkeypatch):
    # Gate global aberto, mas o motor não recebeu remetente_frio: compõe e fila.
    _abrir_todos_os_gates(monkeypatch)
    _novo_coletiva_generica(1)

    res = _correr(remetente_frio=None)

    assert res.enviados == []
    assert len(res.pendentes_parecer) == 1


# ==========================================================================
#  Cap diário — throttle/warm-up (SPEC §motor)
# ==========================================================================
def test_cap_diario_limita_envios_e_adia_o_resto(bd, monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    _semear_registo(nr=1, **COLETIVA_GENERICA)
    _semear_evento_registo(tipo="novo", nr=1)
    _semear_registo(nr=5, **COLETIVA_GENERICA_2)
    _semear_evento_registo(tipo="novo", nr=5)
    rem = FakeRemetente()

    res = _correr(remetente_frio=rem, cap_diario=1)

    assert len(res.enviados) == 1                  # só 1 envio (cap)
    assert len(rem.chamadas) == 1
    assert len(res.pendentes_parecer) == 1         # o excedente adiado
    assert res.pendentes_parecer[0].razao == motor.RAZAO_CAP


# ==========================================================================
#  Opt-out / DGC — log e supressão (Lei 41/2004, art. 13.º-B)
# ==========================================================================
def test_optout_dgc_suprime_do_cold_e_regista_log(bd, monkeypatch):
    _abrir_todos_os_gates(monkeypatch)
    _semear_registo(nr=1, **COLETIVA_GENERICA)
    _semear_evento_registo(tipo="novo", nr=1)
    _semear_registo(nr=5, **COLETIVA_GENERICA_2)
    _semear_evento_registo(tipo="novo", nr=5)
    rem = FakeRemetente()

    res = _correr(remetente_frio=rem, lista_dgc={"geral@empresa.pt"})

    # a oposta não é contactada nem enviada
    assert [c["para"] for c in rem.chamadas] == ["reservas@dois.pt"]
    assert "geral@empresa.pt" in res.optouts        # log de opt-outs
    # a oposta também não cai na carta (opt-out vale para todos os canais)
    assert res.carta_pdf is None


def test_proveniencias_registadas_para_cada_cold(bd):
    _novo_coletiva_generica(1)
    res = _correr()
    assert res.proveniencias
    for p in res.proveniencias:
        assert "rnal" in p.lower()


# ==========================================================================
#  Janela <= 72h — evento fora da janela é saltado (não prospetado)
# ==========================================================================
def test_evento_fora_da_janela_nao_e_prospetado(bd):
    _semear_registo(nr=1, **COLETIVA_GENERICA)
    _semear_evento_registo(tipo="novo", nr=1, quando=AGORA - timedelta(hours=100))

    res = _correr(janela_h=72)

    assert res.pendentes_parecer == []
    assert res.enviados == []
    assert res.carta_pdf is None


def test_evento_dentro_da_janela_e_prospetado(bd):
    _semear_registo(nr=1, **COLETIVA_GENERICA)
    _semear_evento_registo(tipo="novo", nr=1, quando=AGORA - timedelta(hours=10))

    res = _correr(janela_h=72)

    assert len(res.pendentes_parecer) == 1


# ==========================================================================
#  Gatilho regulatório — expansão ao concelho (registos ativos)
# ==========================================================================
def test_regulatorio_expande_ao_concelho(bd):
    _semear_evento_regulatorio(concelhos=["Funchal"], url="https://dre.pt/a/1")
    _semear_registo(nr=1, concelho="Funchal", **COLETIVA_GENERICA)        # cold
    _semear_registo(nr=2, concelho="Funchal", **SINGULAR)                 # carta
    _semear_registo(nr=3, concelho="Lisboa", **COLETIVA_GENERICA_2)       # fora do concelho
    cartas = FakeCartas()

    res = _correr(gerar_cartas=cartas)

    assert [r.para for r in res.pendentes_parecer] == ["geral@empresa.pt"]
    assert [p.nr_registo for p in cartas.prospetos] == [2]


# ==========================================================================
#  Idempotência — 2.ª passagem não reemite
# ==========================================================================
def test_idempotente_segunda_passagem_vazia(bd):
    _novo_coletiva_generica(1)
    _novo_singular(2)

    primeira = _correr()
    assert len(primeira.pendentes_parecer) == 1
    assert primeira.cartas == 1

    segunda = _correr()
    assert segunda.gatilhos == 0
    assert segunda.pendentes_parecer == []
    assert segunda.cartas == 0
    assert segunda.carta_pdf is None


def test_sem_gatilhos_resultado_vazio(bd):
    res = _correr()
    assert res.gatilhos == 0
    assert res.enviados == []
    assert res.pendentes_parecer == []
    assert res.cartas == 0
    assert res.carta_pdf is None
    assert res.descartados == 0


# ==========================================================================
#  FRONTEIRA DURA — o motor NÃO importa a Resend nem app.envio
# ==========================================================================
def test_motor_nao_importa_resend_nem_app_envio():
    fonte = __import__("inspect").getsource(motor)
    arvore = ast.parse(fonte)
    importados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados += [alias.name for alias in no.names]
        elif isinstance(no, ast.ImportFrom):
            base = no.module or ""
            importados.append(base)
            importados += [f"{base}.{alias.name}" for alias in no.names]
    for nome in importados:
        assert "resend" not in nome.lower(), f"import proibido: {nome}"
        assert not nome.startswith("app.envio"), f"import proibido: {nome}"
