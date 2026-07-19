"""Subcomandos `manage.py` dos EXECUTORES — angariador/gestor/sentinela (Fase D).

Cobre:
  ANGARIADOR: `detetar` (backbone → peças persistidas + linter + DGC escala;
  idempotente), `lint --stdin`, `enfileirar --tipo … --stdin` (linter obrigatório,
  falha ⇒ nada inserido; `--escalar` regista escalação), `estado`;
  GESTOR: `onboarding-tarefas` (+ `--recomendar`), `relatorio-mensal-compor`
  (compõe, linta, enfileira p/ gate — idempotente, nunca envia), `dunning-estado`
  (+ `--winback`), `suporte-triar` (linter fail-closed; jurídico/reclamação/
  cancelamento/confiança baixa/estado-de-registo ⇒ ESCALA);
  SENTINELA: `verificar` (read-only; achados em eventos_agente; escalações p/
  crítico; nada corrige, nada envia).

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
import manage


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_agentes_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    monkeypatch.setattr(config, "PAUSA_LLM_PATH", tmp_path / "PAUSA_LLM")
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _json_out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _agora():
    return datetime.now(timezone.utc)


def _stdin(monkeypatch, texto: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


_TEXTO_COLD_OK = (
    "Bom dia,\n\nO CheckAL vigia o registo, o seguro e os regulamentos do concelho "
    "do vosso Alojamento Local. Conteúdo preparado com apoio de inteligência "
    "artificial (IA).\n\nInformação, não aconselhamento jurídico.\n"
    "Para não voltar a ser contactado: checkal.pt/remover\n"
    "O CheckAL é operado por Cosmic Oasis, Lda."
)


def _seed_registo_coletiva(s, nr=100031, email="geral@sul.pt") -> None:
    s.add(
        models.Registo(
            nr_registo=nr, nome_alojamento="Casa do Sol", concelho="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda.",
            nif="513029591", email=email, hash_campos="h",
        )
    )
    s.add(
        models.EventoRegisto(
            nr_registo=nr, tipo="novo", varrimento_id=1, detetado_em=_agora(),
        )
    )


# ==========================================================================
#  ANGARIADOR
# ==========================================================================
def test_angariador_detetar_persiste_pecas_e_devolve_agregados(bd, capsys):
    with db.get_session() as s:
        _seed_registo_coletiva(s)

    assert manage.main(["angariador", "detetar"]) == 0
    dados = _json_out(capsys)
    assert dados["gatilhos"] == 1
    assert dados["pendentes"] == 1
    assert dados["dgc_ok"] is False           # sem feed DGC ⇒ fail-closed
    assert len(dados["drafts"]) == 1
    draft = dados["drafts"][0]
    assert draft["nif"] == "513029591"        # campos coletivos apenas
    # A copy do motor ainda contém "exploração irregular" ⇒ o linter reprova o
    # draft (fail-closed); o agente reescreve o corpo e re-enfileira.
    assert draft["linter_ok"] is False
    assert draft["violacoes"]

    with db.get_session() as s:
        assert s.query(ms.Campanha).count() == 1
        peca = s.query(ms.CampanhaPeca).one()
        assert peca.estado == "pendente_parecer"
        assert peca.linter_ok is False
        # Reprovado pelo linter ⇒ NÃO entra na fila de aprovação.
        assert s.query(ms.RevisaoItem).count() == 0
        # DGC vazia ⇒ o ANGARIADOR escala (RT-DGC).
        assert s.query(ms.Escalacao).filter(ms.Escalacao.agente == "angariador").count() == 1


def test_angariador_detetar_e_idempotente(bd, capsys):
    with db.get_session() as s:
        _seed_registo_coletiva(s)

    assert manage.main(["angariador", "detetar"]) == 0
    capsys.readouterr()
    assert manage.main(["angariador", "detetar"]) == 0
    dados = _json_out(capsys)
    assert dados["gatilhos"] == 0             # eventos já usados (marcador durável)
    with db.get_session() as s:
        assert s.query(ms.CampanhaPeca).count() == 1  # não duplicou


def test_angariador_detetar_sem_eventos_e_noop(bd, capsys):
    assert manage.main(["angariador", "detetar"]) == 0
    dados = _json_out(capsys)
    assert dados["noop"] is True


def test_angariador_lint_stdin_devolve_veredicto(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "O vosso alojamento está ilegal.")
    assert manage.main(["angariador", "lint", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert dados["violacoes"]


def test_angariador_enfileirar_conteudo_aprovado(bd, capsys, monkeypatch):
    texto = (
        "# Guia: cancelamentos no Porto\n\nInformação a partir de fontes públicas; "
        "não constitui aconselhamento jurídico. Fonte oficial: "
        "https://rnt.turismodeportugal.pt/rnt. Conteúdo preparado com apoio de "
        "inteligência artificial (IA)."
    )
    _stdin(monkeypatch, texto)
    assert manage.main([
        "angariador", "enfileirar", "--tipo", "pilar_seo", "--stdin",
        "--fonte", "https://rnt.turismodeportugal.pt/rnt",
        "--excerto", "registos de alojamento local",
    ]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True

    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.estado == "pendente"
        assert item.tipo == "pilar_seo"
        # O conteúdo vive no journal (append-only) e o item aponta-lhe.
        ev = s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "conteudo_proposto").one()
        assert item.ref_tipo == "evento_agente"
        assert item.ref_id == str(ev.id)


def test_angariador_enfileirar_reprovado_nao_insere_e_sai_1(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "O vosso registo caducou — regularize já.")
    assert manage.main(["angariador", "enfileirar", "--tipo", "pilar_seo", "--stdin"]) == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_angariador_enfileirar_escalar_regista_escalacao(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "irrelevante")
    assert manage.main([
        "angariador", "enfileirar", "--tipo", "cold_draft", "--stdin",
        "--escalar", "--motivo", "linter reprovou 2x; não sei corrigir sem inventar",
    ]) == 0
    with db.get_session() as s:
        e = s.query(ms.Escalacao).one()
        assert e.agente == "angariador"
        assert "linter" in e.mensagem


def test_angariador_estado_resume_a_fila(bd, capsys):
    assert manage.main(["angariador", "estado"]) == 0
    dados = _json_out(capsys)
    assert "revisao" in dados and "pecas" in dados


# ==========================================================================
#  GESTOR-DE-CLIENTE
# ==========================================================================
def test_gestor_onboarding_tarefas_lista(bd, capsys):
    with db.get_session() as s:
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="ativo"))
        s.add(models.Alerta(cliente_id=1, origem="onboarding_tarefa",
                            canal="tarefa_dono", conteudo="match ambíguo: 2 candidatos"))

    assert manage.main(["gestor", "onboarding-tarefas"]) == 0
    dados = _json_out(capsys)
    assert len(dados["tarefas"]) == 1
    assert dados["tarefas"][0]["cliente_id"] == 1


def test_gestor_onboarding_recomendacao_enfileira_risco_baixo(bd, capsys, monkeypatch):
    with db.get_session() as s:
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="ativo"))
        s.add(models.Alerta(id=7, cliente_id=1, origem="onboarding_tarefa",
                            canal="tarefa_dono", conteudo="match ambíguo"))

    _stdin(monkeypatch, "Recomendo casar com o registo 100031 (nome+concelho batem). "
                        "Informação, não aconselhamento jurídico. "
                        "Conteúdo preparado com apoio de inteligência artificial (IA).")
    assert manage.main([
        "gestor", "onboarding-tarefas", "--recomendar", "--alerta-id", "7", "--stdin",
    ]) == 0
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "onboarding_triagem"
        assert item.risco == "baixo"
        assert item.agente_origem == "gestor"


def test_gestor_relatorio_mensal_compoe_linta_enfileira(bd, capsys):
    with db.get_session() as s:
        c = models.Cliente(email="a@b.pt", nome="Ana", plano="anual", estado="ativo")
        r = models.Registo(nr_registo=100031, nome_alojamento="Casa do Sol",
                           concelho="Faro", hash_campos="h")
        c.registos.append(r)
        s.add(c)

    assert manage.main(["gestor", "relatorio-mensal-compor", "--mes", "2026-07"]) == 0
    dados = _json_out(capsys)
    assert dados["enfileirados"] == 1

    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "relatorio_mensal"
        assert item.risco == "medio"            # envio em massa ⇒ gate 1-clique
        assert item.estado == "pendente"        # NUNCA envia por si

    # Idempotente: 2.ª passagem não duplica.
    capsys.readouterr()
    assert manage.main(["gestor", "relatorio-mensal-compor", "--mes", "2026-07"]) == 0
    assert _json_out(capsys)["enfileirados"] == 0


def test_gestor_relatorio_mensal_leva_divulgacao_ia(bd, capsys):
    from app.compliance.linter import DIVULGACAO_IA

    with db.get_session() as s:
        c = models.Cliente(email="a@b.pt", plano="anual", estado="ativo")
        c.registos.append(models.Registo(nr_registo=1, nome_alojamento="AL",
                                         concelho="Faro", hash_campos="h"))
        s.add(c)

    manage.main(["gestor", "relatorio-mensal-compor", "--mes", "2026-07"])
    with db.get_session() as s:
        ev = s.query(ms.EventoAgente).filter(
            ms.EventoAgente.tipo == "conteudo_proposto").one()
        assert DIVULGACAO_IA in (ev.payload or {}).get("corpo_texto", "")


def test_gestor_dunning_estado_resume(bd, capsys):
    with db.get_session() as s:
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="em_dunning"))
        s.add(models.Alerta(cliente_id=1, origem="dunning:aviso_d7",
                            canal="email", enviado_em=_agora()))

    assert manage.main(["gestor", "dunning-estado"]) == 0
    dados = _json_out(capsys)
    assert dados["em_dunning"] == 1
    assert dados["passos_hoje"] == 1


def test_gestor_winback_enfileira_para_o_gate(bd, capsys, monkeypatch):
    with db.get_session() as s:
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="cancelado"))

    _stdin(monkeypatch, "Olá! A porta fica aberta — quando quiseres retomar a vigilância "
                        "do teu AL, é só reativar. Informação, não aconselhamento jurídico. "
                        "Para não voltar a receber: checkal.pt/remover. "
                        "Conteúdo preparado com apoio de inteligência artificial (IA).")
    assert manage.main([
        "gestor", "dunning-estado", "--winback", "--cliente", "1", "--stdin",
    ]) == 0
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "winback"
        assert item.estado == "pendente"


def test_gestor_suporte_triar_juridico_escala_sempre(bd, capsys, monkeypatch):
    pedido = {"de_dominio": "cliente", "assunto": "Coima da câmara",
              "corpo": "Recebi uma notificação, o que diz a lei?",
              "resposta": "A lei diz que…", "categoria": "juridico", "confianca": "alta"}
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "escalado"
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1
        assert s.query(ms.RevisaoItem).count() == 0


def test_gestor_suporte_triar_estado_de_registo_escala_mesmo_confianca_alta(bd, capsys, monkeypatch):
    pedido = {"assunto": "O meu registo", "corpo": "Está tudo bem?",
              "resposta": "O seu seguro está caducado, tem de renovar.",
              "categoria": "factual", "confianca": "alta"}
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "escalado"           # RT-suporte: G4 reimposto no envio
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_gestor_suporte_triar_factual_enfileira_rascunho(bd, capsys, monkeypatch):
    pedido = {
        "assunto": "Preço", "corpo": "Quanto custa o plano anual?",
        "resposta": (
            "O plano anual custa 49€/ano, IVA incluído, com garantia de 30 dias. "
            "Informação a partir de fontes públicas; não constitui aconselhamento "
            "jurídico. Conteúdo preparado com apoio de inteligência artificial (IA)."
        ),
        "categoria": "factual", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "enfileirado"
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "suporte_rascunho"


def test_gestor_suporte_triar_resposta_reprovada_escala(bd, capsys, monkeypatch):
    pedido = {"assunto": "x", "corpo": "y",
              "resposta": "Estás ilegal, arriscas uma coima.",
              "categoria": "factual", "confianca": "alta"}
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "escalado"
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_gestor_suporte_triar_pre_venda_enfileira_rascunho(bd, capsys, monkeypatch):
    # E1: categoria pre_venda (interessado sem subscrição a perguntar preço/
    # funcionamento) segue o fluxo normal — responde e enfileira, SEM escalar.
    pedido = {
        "assunto": "Preços", "corpo": "Quanto custa e como funciona?",
        "resposta": (
            "O CheckAL vigia o registo RNAL, o seguro obrigatório e os regulamentos "
            "municipais do teu Alojamento Local, com alertas por email. Planos a "
            "partir de 49€/ano. Faz o check grátis em checkal.pt — 30 segundos, sem "
            "cartão. Informação a partir de fontes públicas; não constitui "
            "aconselhamento jurídico. Conteúdo preparado com apoio de inteligência "
            "artificial (IA)."
        ),
        "categoria": "pre_venda", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "enfileirado"
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 0
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "suporte_rascunho"


def test_gestor_suporte_triar_descricao_do_produto_nao_escala(bd, capsys, monkeypatch):
    # RT-suporte refinado: "regulamentos municipais" é descrição do produto, não
    # prescrição jurídica — não pode disparar a regex sensível (_RE_SUPORTE_SENSIVEL).
    pedido = {
        "assunto": "Como funciona", "corpo": "O que é que o CheckAL vigia?",
        "resposta": (
            "Vigiamos os regulamentos municipais do teu concelho, o registo RNAL e o "
            "seguro obrigatório, e avisamos-te por email se algo mudar. Informação a "
            "partir de fontes públicas; não constitui aconselhamento jurídico. "
            "Conteúdo preparado com apoio de inteligência artificial (IA)."
        ),
        "categoria": "factual", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "enfileirado"
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 0
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "suporte_rascunho"


def test_gestor_suporte_triar_regulamento_prescritivo_escala_alta(bd, capsys, monkeypatch):
    # uso PRESCRITIVO ("o regulamento proíbe X") continua a escalar sempre, mesmo
    # com confiança alta e categoria factual (regex refinada, não regride).
    pedido = {
        "assunto": "Posso alugar?", "corpo": "Posso alojar no piso térreo no Porto?",
        "resposta": (
            "No Porto, o regulamento proíbe alojamento local no piso térreo da "
            "zona histórica."
        ),
        "categoria": "factual", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "escalado"
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0
        esc = s.query(ms.Escalacao).one()
        assert esc.severidade == "alta"


# ==========================================================================
#  Revisão E1 (19/07 tarde): a adjacência estrita deixava escapar prescrições
#  naturais em PT ("o regulamento DO PORTO proíbe", plurais "regulamentos
#  .../obrigam/proíbem/impedem") — a regex passa a tolerar até 4 tokens de
#  qualificador entre o substantivo e o verbo, e cobre as formas plurais.
# ==========================================================================
@pytest.mark.parametrize("resposta", [
    "No Porto, o regulamento do Porto proíbe alojamento no piso térreo.",
    "O regulamento municipal do Funchal exige seguro adicional para o AL.",
    "Os regulamentos obrigam-te a registar o alojamento antes de operar.",
    "Os regulamentos municipais do Porto proíbem novos registos na zona histórica.",
    "Os regulamentos impedem o registo de novos ALs nesta rua.",
])
def test_gestor_suporte_triar_regulamento_prescritivo_com_qualificador_ou_plural_escala(
    bd, capsys, monkeypatch, resposta,
):
    pedido = {
        "assunto": "Posso alugar?", "corpo": "Posso alojar aqui?",
        "resposta": resposta, "categoria": "factual", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "escalado"
    # motivo tem de vir do RT-suporte (_RE_SUPORTE_SENSIVEL), não do linter (R2)
    # — o linter também reprovaria linguagem prescritiva, o que mascararia um
    # falso-verde da regex; isto prova que É a regex a apanhar o caso.
    assert "resposta toca estado de registo/seguro/regime legal" in dados["motivo"]
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0
        esc = s.query(ms.Escalacao).one()
        assert esc.severidade == "alta"


@pytest.mark.parametrize("resposta", [
    (
        "Acompanhamos os regulamentos e avisamos-te de mudanças por email. "
        "Informação a partir de fontes públicas; não constitui aconselhamento "
        "jurídico. Conteúdo preparado com apoio de inteligência artificial (IA)."
    ),
    (
        "O regulamento está disponível e o teu contrato obriga-te a manter o "
        "seguro em dia. Informação a partir de fontes públicas; não constitui "
        "aconselhamento jurídico. Conteúdo preparado com apoio de inteligência "
        "artificial (IA)."
    ),
])
def test_gestor_suporte_triar_regulamento_nao_prescritivo_nao_escala(
    bd, capsys, monkeypatch, resposta,
):
    # guarda anti-bleed cross-clause: o cap {0,4} não pode saltar de "regulamento"
    # para um verbo de OUTRA oração — no 2.º caso, "obriga" é do "contrato", não
    # do "regulamento"; no 1.º, é descrição do produto, sem verbo prescritivo perto.
    pedido = {
        "assunto": "Como funciona", "corpo": "O que é que o CheckAL vigia?",
        "resposta": resposta, "categoria": "factual", "confianca": "alta",
    }
    _stdin(monkeypatch, json.dumps(pedido))
    assert manage.main(["gestor", "suporte-triar", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["acao"] == "enfileirado"
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 0
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "suporte_rascunho"


# ==========================================================================
#  SENTINELA-SERVIÇO
# ==========================================================================
def test_sentinela_verificar_tudo_verde(bd, capsys):
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=_agora(), concluido_em=_agora(),
                                estado="ok", total_registos=100))

    assert manage.main(["sentinela", "verificar"]) == 0
    dados = _json_out(capsys)
    assert dados["verde"] is True
    assert dados["verificacoes_corridas"] == 4


def test_sentinela_deteta_varrimento_estagnado(bd, capsys):
    velho = _agora() - timedelta(days=10)
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=velho, concluido_em=velho,
                                estado="ok", total_registos=100))

    assert manage.main(["sentinela", "verificar"]) == 0
    dados = _json_out(capsys)
    assert dados["verde"] is False
    with db.get_session() as s:
        achado = s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "achado").first()
        assert achado is not None
        assert achado.agente == "sentinela"
        assert (achado.payload or {}).get("categoria") == "freshness_nacional"


def test_sentinela_deteta_cliente_sem_cobertura_e_escala(bd, capsys):
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=_agora(), concluido_em=_agora(),
                                estado="ok", total_registos=100))
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="ativo"))
        # ativo SEM registo associado ⇒ paga e não é vigiado (crítico).

    assert manage.main(["sentinela", "verificar"]) == 0
    dados = _json_out(capsys)
    assert dados["verde"] is False
    with db.get_session() as s:
        cats = [(e.payload or {}).get("categoria")
                for e in s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "achado")]
        assert "cobertura_cliente" in cats
        assert s.query(ms.Escalacao).count() >= 1   # crítico ⇒ escala ao Maestro


def test_sentinela_deteta_breaker_bypass(bd, capsys):
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=_agora(), concluido_em=_agora(),
                                estado="ok", total_registos=100))
        s.add(models.Registo(nr_registo=5, concelho="Porto", hash_campos="h"))
        # Alerta "cancelado" ENVIADO sem rasto de pendente_desambiguacao = bypass.
        s.add(models.Alerta(cliente_id=1, nr_registo=5, origem="eventos_registo",
                            conteudo="O registo foi cancelado.", canal="email",
                            enviado_em=_agora()))

    assert manage.main(["sentinela", "verificar"]) == 0
    dados = _json_out(capsys)
    assert dados["verde"] is False
    with db.get_session() as s:
        cats = [(e.payload or {}).get("categoria")
                for e in s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "achado")]
        assert "breaker_bypass" in cats


def test_sentinela_nao_repete_achados_no_mesmo_estado(bd, capsys):
    velho = _agora() - timedelta(days=10)
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=velho, concluido_em=velho,
                                estado="ok", total_registos=100))

    manage.main(["sentinela", "verificar"])
    with db.get_session() as s:
        n1 = s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "achado").count()
    manage.main(["sentinela", "verificar"])
    with db.get_session() as s:
        n2 = s.query(ms.EventoAgente).filter(ms.EventoAgente.tipo == "achado").count()
    assert n2 == n1  # idempotente enquanto o estado não muda


def test_sentinela_nao_toca_dominio(bd, capsys):
    velho = _agora() - timedelta(days=10)
    with db.get_session() as s:
        s.add(models.Varrimento(iniciado_em=velho, concluido_em=velho,
                                estado="ok", total_registos=3))
        s.add(models.Cliente(id=1, email="a@b.pt", plano="anual", estado="ativo"))

    manage.main(["sentinela", "verificar"])
    with db.get_session() as s:
        # nada de domínio alterado: cliente intacto, nenhum alerta criado
        assert s.query(models.Cliente).count() == 1
        assert s.query(models.Alerta).count() == 0
