"""Invariantes de GOVERNAÇÃO da fila de revisão — app.swarm.fila (Fase C, §6).

Prova, em código, as regras invioláveis do enxame:
  (1) `enfileirar` corre o linter internamente e SÓ insere se `aprovado=True`;
      reprovado ⇒ levanta com as violações e NÃO insere (fail-closed);
  (2) linter ausente (import falhado) ⇒ recusa e NÃO insere (fail-closed);
  (3) NENHUM caminho de agente escreve `estado='aprovado'` — só `aprovar()`
      (o dono, com token válido) o faz, com linha em `aprovacoes` e
      autor ≠ aprovador;
  (4) `drain` só serve itens JÁ aprovados, com lease/backoff e cap alinhado
      com CAMPANHA_CAP_DIARIO;
  (5) gate DGC fail-closed: lista vazia/estagnada ⇒ recusa o envio mesmo com
      os outros gates abertos;
  (6) a sessão de governação recusa escrever em tabelas de domínio
      (clientes/alertas/registos/faturas/leads);
  (7) RT-Sentinela pré-envio: alerta "cancelado" só enfileirável com breaker
      E cross-check confirmados.

Isolamento: BD SQLite temporária. SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
from app.compliance.linter import Canal, PecaOutward
from app.compliance.minimizacao import ContactoEnderecavel
from app.swarm import fila


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_fila_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


_FONTE = "https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=100031"


def _peca_cold_ok() -> PecaOutward:
    texto = (
        "Bom dia,\n\nO CheckAL vigia o registo, o seguro e os regulamentos do "
        "concelho do vosso Alojamento Local.\n\n"
        "Informação, não aconselhamento jurídico.\n"
        "Para não voltar a ser contactado: checkal.pt/remover\n"
        "O CheckAL é operado por Cosmic Oasis, Lda."
    )
    return PecaOutward(texto=texto, canal=Canal.COLD)


def _peca_cold_ma() -> PecaOutward:
    return PecaOutward(texto="O vosso alojamento está ilegal.", canal=Canal.COLD)


def _enfileirar_ok(s, **kw):
    defaults = dict(
        tipo="cold_email", ref_tipo="campanha_peca", ref_id="1",
        resumo="draft frio", risco="alto", agente_origem="angariador",
        peca=_peca_cold_ok(),
    )
    defaults.update(kw)
    return fila.enfileirar(s, **defaults)


# ==========================================================================
#  (1) enfileirar — linter interno, fail-closed
# ==========================================================================
def test_enfileirar_insere_pendente_com_linter_ok(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        assert item.estado == "pendente"
        assert item.linter_ok is True

    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.estado == "pendente"
        assert item.agente_origem == "angariador"
        assert item.camada_risco == 4  # risco alto ⇒ camada máxima


def test_enfileirar_reprovado_levanta_e_nao_insere(bd):
    with pytest.raises(fila.LinterReprovado) as exc:
        with db.get_session() as s:
            _enfileirar_ok(s, peca=_peca_cold_ma())
    assert exc.value.violacoes  # devolve as violações para o agente/escala

    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_enfileirar_com_linter_ausente_recusa_e_nao_insere(bd, monkeypatch):
    def _rebenta():
        raise ImportError("linter indisponível")

    monkeypatch.setattr(fila, "_importar_linter", _rebenta)
    with pytest.raises(fila.LinterIndisponivel):
        with db.get_session() as s:
            _enfileirar_ok(s)

    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


# ==========================================================================
#  (3) aprovação — só o dono, com token, autor ≠ aprovador
# ==========================================================================
def test_nenhum_caminho_de_agente_escreve_aprovado(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        assert item.estado == "pendente"
        # enfileirar não aceita forçar o estado — não há kwarg para isso.
        import inspect

        assert "estado" not in inspect.signature(fila.enfileirar).parameters


def test_gerar_token_nao_aprova(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        token = fila.gerar_token(s, item.id)
        assert token
        assert item.estado == "pendente"          # gerar token NÃO aprova
        assert item.token_aprovacao == token


def test_aprovar_exige_token_valido(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        fila.gerar_token(s, item.id)
        item_id = item.id

    with pytest.raises(fila.TokenInvalido):
        with db.get_session() as s:
            fila.aprovar(s, item_id, token="errado", decidido_por="dono")

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "pendente"
        assert s.query(ms.Aprovacao).count() == 0


def test_aprovar_sem_token_gerado_recusa(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        item_id = item.id

    with pytest.raises(fila.TokenInvalido):
        with db.get_session() as s:
            fila.aprovar(s, item_id, token="", decidido_por="dono")


def test_aprovar_com_token_valido_escreve_aprovacao_autor_diferente(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        token = fila.gerar_token(s, item.id)
        item_id = item.id

    with db.get_session() as s:
        fila.aprovar(s, item_id, token=token, decidido_por="dono")

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "aprovado"
        assert item.decidido_por == "dono"
        a = s.query(ms.Aprovacao).one()
        assert a.revisao_item_id == item_id
        assert a.autor == "angariador"
        assert a.decidido_por == "dono"
        assert a.autor != a.decidido_por


def test_aprovar_pelo_proprio_autor_recusa(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        token = fila.gerar_token(s, item.id)
        item_id = item.id

    with pytest.raises(fila.AutorNaoAprova):
        with db.get_session() as s:
            fila.aprovar(s, item_id, token=token, decidido_por="angariador")

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "pendente"


def test_rejeitar_regista_decisao(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        token = fila.gerar_token(s, item.id)
        item_id = item.id

    with db.get_session() as s:
        fila.rejeitar(s, item_id, token=token, decidido_por="dono", nota="não gostei")

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "rejeitado"
        a = s.query(ms.Aprovacao).one()
        assert a.decisao == "rejeitado"


# ==========================================================================
#  (4) drain — lease/backoff, só sobre aprovados, cap diário
# ==========================================================================
def _aprovado(s, **kw) -> int:
    item = _enfileirar_ok(s, **kw)
    s.flush()
    token = fila.gerar_token(s, item.id)
    fila.aprovar(s, item.id, token=token, decidido_por="dono")
    return item.id


def test_drain_ignora_pendentes(bd):
    with db.get_session() as s:
        _enfileirar_ok(s)

    with db.get_session() as s:
        assert fila.drain(s, "angariador") == []


def test_drain_serve_aprovados_e_aplica_lease(bd):
    with db.get_session() as s:
        item_id = _aprovado(s)

    with db.get_session() as s:
        servidos = fila.drain(s, "angariador")
        assert [i.id for i in servidos] == [item_id]
        assert servidos[0].estado == "a_correr"
        assert servidos[0].lease_ate is not None

    # Dentro do lease, uma 2.ª passagem não volta a servir o mesmo item.
    with db.get_session() as s:
        assert fila.drain(s, "angariador") == []


def test_drain_processador_sucesso_marca_feito(bd):
    with db.get_session() as s:
        item_id = _aprovado(s)

    with db.get_session() as s:
        fila.drain(s, "angariador", processador=lambda item: None)

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "feito"


def test_drain_processador_falha_backoff_e_morto(bd):
    with db.get_session() as s:
        item_id = _aprovado(s)
        s.get(ms.RevisaoItem, item_id).max_tentativas = 2

    def _rebenta(item):
        raise RuntimeError("smtp em baixo")

    with db.get_session() as s:
        fila.drain(s, "angariador", processador=_rebenta)

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "falhado"
        assert item.tentativas == 1
        assert item.nao_antes_de is not None  # backoff futuro
        # torna o item já elegível outra vez (salta o backoff)
        item.nao_antes_de = datetime.now(timezone.utc) - timedelta(minutes=1)
        item.lease_ate = None
        item.estado = "aprovado"

    with db.get_session() as s:
        fila.drain(s, "angariador", processador=_rebenta)

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "morto"


def test_drain_cap_alinhado_com_campanha_cap_diario(bd, monkeypatch):
    monkeypatch.setattr(config, "CAMPANHA_CAP_DIARIO", 3)
    with db.get_session() as s:
        for i in range(5):
            _aprovado(s, ref_id=str(i), resumo=f"draft {i}")

    with db.get_session() as s:
        assert len(fila.drain(s, "angariador")) == 3


# ==========================================================================
#  (5) gate DGC fail-closed
# ==========================================================================
def _contacto() -> ContactoEnderecavel:
    return ContactoEnderecavel(
        nr_registo=100031, nif="513029591", nome_coletiva="Alojamentos Sul, Lda.",
        email_generico="geral@sul.pt", concelho="Faro",
    )


def _abrir_gates(monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "u")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "p")


def test_dgc_vazia_ou_sem_timestamp_recusa():
    agora = datetime.now(timezone.utc)
    assert fila.dgc_ok([], carregada_em=agora) is False
    assert fila.dgc_ok(["x@y.pt"], carregada_em=None) is False


def test_dgc_estagnada_recusa():
    velho = datetime.now(timezone.utc) - timedelta(days=config.DGC_MAX_IDADE_DIAS + 1)
    assert fila.dgc_ok(["x@y.pt"], carregada_em=velho) is False


def test_dgc_fresca_e_com_conteudo_aceita():
    fresco = datetime.now(timezone.utc) - timedelta(days=1)
    assert fila.dgc_ok(["x@y.pt"], carregada_em=fresco) is True


def test_envio_recusado_com_dgc_vazia_mesmo_com_gates_abertos(monkeypatch):
    _abrir_gates(monkeypatch)
    assert config.pode_enviar_frio_global() is True  # sanity: gates abertos
    ok = fila.pode_enviar_frio_com_dgc(
        _contacto(), lista_dgc=[], dgc_carregada_em=None, log_optout=[],
    )
    assert ok is False  # DGC vazia ⇒ trata todos como opostos


def test_envio_possivel_so_com_dgc_fresca(monkeypatch):
    _abrir_gates(monkeypatch)
    fresco = datetime.now(timezone.utc) - timedelta(days=1)
    ok = fila.pode_enviar_frio_com_dgc(
        _contacto(), lista_dgc=["outro@x.pt"], dgc_carregada_em=fresco, log_optout=[],
    )
    assert ok is True


def test_envio_continua_gated_por_defeito_mesmo_com_dgc():
    # Defaults do repo: parecer False + modo teste True ⇒ nunca envia.
    fresco = datetime.now(timezone.utc) - timedelta(days=1)
    ok = fila.pode_enviar_frio_com_dgc(
        _contacto(), lista_dgc=["outro@x.pt"], dgc_carregada_em=fresco, log_optout=[],
    )
    assert ok is False


# ==========================================================================
#  (6) sessão de governação — nunca toca tabelas de domínio
# ==========================================================================
def test_sessao_governacao_recusa_escrita_em_dominio(bd):
    with pytest.raises(fila.EscritaForaDaGovernacao):
        with fila.sessao_governacao() as s:
            s.add(models.Cliente(email="x@y.pt", plano="anual", estado="ativo"))
            s.flush()

    with db.get_session() as s:
        assert s.query(models.Cliente).count() == 0


def test_sessao_governacao_aceita_tabelas_do_enxame(bd):
    with fila.sessao_governacao() as s:
        s.add(
            ms.Escalacao(
                agente="angariador", severidade="alta", mensagem="lista DGC vazia",
                criado_em=datetime.now(timezone.utc),
            )
        )

    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1


# ==========================================================================
#  (7) RT-Sentinela pré-envio — "cancelado" exige breaker E cross-check
# ==========================================================================
def _peca_alerta_cancelado() -> PecaOutward:
    texto = (
        "Atualização do registo. A página oficial indica: «Estado: Cancelado». "
        f"Fonte: {_FONTE}. Informação, não aconselhamento jurídico."
    )
    return PecaOutward(
        texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE, excerto="Estado: Cancelado",
    )


def test_alerta_cancelado_sem_confirmacao_nao_enfileira(bd):
    with pytest.raises(fila.PreEnvioNaoConfirmado):
        with db.get_session() as s:
            _enfileirar_ok(s, tipo="alerta", peca=_peca_alerta_cancelado())

    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_alerta_cancelado_so_com_breaker_nao_chega(bd):
    with pytest.raises(fila.PreEnvioNaoConfirmado):
        with db.get_session() as s:
            _enfileirar_ok(
                s, tipo="alerta", peca=_peca_alerta_cancelado(),
                breaker_confirmado=True,
            )


def test_alerta_cancelado_com_breaker_e_crosscheck_enfileira(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(
            s, tipo="alerta", peca=_peca_alerta_cancelado(),
            breaker_confirmado=True, cross_check_ok=True,
        )
        assert item.estado == "pendente"


# ==========================================================================
#  Portão 1-clique (fase 2): GATE_BASE_URL fail-closed
# ==========================================================================
def test_gate_base_url_default_vazio_fail_closed():
    import app.config as config

    assert config.GATE_BASE_URL == ""


def test_token_nao_ascii_falha_fechado_sem_typeerror(bd):
    # Token de query param controlado pelo exterior: não-ASCII tem de dar
    # TokenInvalido (fail-closed), nunca TypeError/500 (regressão do
    # compare_digest sobre str).
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        fila.gerar_token(s, item.id)
        item_id = item.id

    with pytest.raises(fila.TokenInvalido):
        with db.get_session() as s:
            fila.aprovar(s, item_id, token="café-ñ", decidido_por="dono")

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "pendente"
