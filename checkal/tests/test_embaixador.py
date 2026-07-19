"""EMBAIXADOR — deteção compliance-gated de candidatos a parceiro (canal GTM
n.º 2) + subcomandos `manage.py` (fase 1 do enxame, spec 2026-07-19 §1).

Cobre o módulo determinista `app.embaixador.detetar_candidatos` (pré-filtro
SQL grosseiro + portão de compliance canónico + dedupe + agregados
não-pessoais) e os subcomandos `embaixador {detetar | lint --stdin |
enfileirar --tipo proposta_parceria --stdin --nif N | estado}`.

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação
(TDD).
"""
from __future__ import annotations

import io
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
import manage
from app.embaixador import detetar_candidatos
from tests.test_manage_agentes import _TEXTO_COLD_OK


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_embaixador_test.db'}"
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


def _stdin(monkeypatch, texto: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


def _seed_grupo(
    s, nif: str, n: int, *, email: str, titular_tipo: str = "coletiva",
    nome: str = "Gestora Multi-AL, Lda.", concelhos=None, modalidades=None,
    camas=None, nr_base: int = 100000,
) -> None:
    """Semeia `n` registos ATIVOS com o mesmo NIF — uma "carteira" multi-AL."""
    concelhos = concelhos or ["Faro"]
    modalidades = modalidades or ["moradia"]
    camas = camas or [4]
    for i in range(n):
        s.add(models.Registo(
            nr_registo=nr_base + i,
            nome_alojamento=f"Alojamento {i}",
            concelho=concelhos[i % len(concelhos)],
            modalidade=modalidades[i % len(modalidades)],
            nr_camas=camas[i % len(camas)],
            titular_tipo=titular_tipo,
            titular_nome=nome,
            nif=nif,
            email=email,
            hash_campos="h",
        ))


# ==========================================================================
#  detetar_candidatos — módulo determinista
# ==========================================================================
def test_deteccao_respeita_limiar_e_so_coletivas_com_email_generico(bd):
    with db.get_session() as s:
        _seed_grupo(
            s, "513111111", 6, email="geral@multial.pt",
            nome="Gestora Multi-AL, Lda.",
            concelhos=["Faro", "Lisboa", "Porto"],
            modalidades=["moradia", "apartamento"],
            camas=[4, 6, 2], nr_base=100000,
        )
        # Abaixo do limiar (3 < 5) — nunca deve aparecer.
        _seed_grupo(s, "600222222", 3, email="reservas@poucos.pt", nr_base=200000)
        # Só email pessoal — sem email genérico, o portão recusa o grupo inteiro.
        _seed_grupo(s, "513333333", 5, email="joao.silva@gmail.com", nr_base=300000)

    with db.get_session() as s:
        candidatos = detetar_candidatos(s, limiar=5)

    assert {c["nif"] for c in candidatos} == {"513111111"}

    c = candidatos[0]
    assert c["nome_coletiva"] == "Gestora Multi-AL, Lda."
    assert c["email_generico"] == "geral@multial.pt"
    assert c["n_registos"] == 6
    assert c["concelhos"] == ["Faro", "Lisboa", "Porto"]
    assert c["modalidades"] == ["apartamento", "moradia"]
    assert c["total_camas"] == sum([4, 6, 2, 4, 6, 2])
    assert c["proveniencia"]


def test_deteccao_autoridade_e_enderecavel_nao_titular_tipo(bd):
    with db.get_session() as s:
        # titular_tipo diz "coletiva" mas o NIF começa por 7 (coletiva
        # NÃO-RESIDENTE) — e_enderecavel exige 1.º dígito em {5,6}; fica fora.
        _seed_grupo(
            s, "710444444", 6, email="geral@naoresidente.pt",
            titular_tipo="coletiva", nr_base=400000,
        )
        # titular_tipo diz "singular" mas o NIF É coletivo (5/6) — a
        # autoridade é o NIF, não o campo de texto; ENTRA.
        _seed_grupo(
            s, "513555555", 6, email="geral@rotulomau.pt",
            titular_tipo="singular", nr_base=500000,
        )

    with db.get_session() as s:
        nifs = {c["nif"] for c in detetar_candidatos(s, limiar=5)}

    assert "710444444" not in nifs
    assert "513555555" in nifs


def test_deteccao_dedupe_exclui_nif_com_proposta_ja_na_fila(bd):
    with db.get_session() as s:
        _seed_grupo(s, "513666666", 6, email="geral@dedupe.pt", nr_base=600000)
        # Já existe uma proposta_parceria na fila p/ este NIF — mesmo já
        # DECIDIDA (rejeitada) conta para o dedupe ("qualquer estado").
        evento = ms.EventoAgente(
            agente="embaixador", tipo="conteudo_proposto",
            payload={"tipo": "proposta_parceria", "nif": "513666666",
                     "corpo_texto": "proposta anterior"},
            criado_em=manage._agora(),
        )
        s.add(evento)
        s.flush()
        s.add(ms.RevisaoItem(
            tipo="proposta_parceria", risco="alto", camada_risco=4,
            agente_origem="embaixador", ref_tipo="evento_agente",
            ref_id=str(evento.id), estado="rejeitado", linter_ok=True,
            criado_em=manage._agora(),
        ))

    with db.get_session() as s:
        nifs = {c["nif"] for c in detetar_candidatos(s, limiar=5)}

    assert "513666666" not in nifs


def test_deteccao_dedupe_canonicaliza_nif_pt_prefixo_e_espacos(bd):
    """Add-on à revisão E3: o dedupe usa `nif._limpar` dos DOIS lados — um
    payload gravado como "PT 509375499" (prefixo + espaço, como um agente
    poderia escrever a mão) e o NIF limpo "509375499" na BD do RNAL são o
    MESMO titular; sem canonicalização, o candidato voltaria a ser proposto."""
    with db.get_session() as s:
        _seed_grupo(s, "509375499", 6, email="geral@ptprefixo.pt", nr_base=610000)
        evento = ms.EventoAgente(
            agente="embaixador", tipo="conteudo_proposto",
            payload={"tipo": "proposta_parceria", "nif": "PT 509375499",
                     "corpo_texto": "proposta anterior"},
            criado_em=manage._agora(),
        )
        s.add(evento)
        s.flush()
        s.add(ms.RevisaoItem(
            tipo="proposta_parceria", risco="alto", camada_risco=4,
            agente_origem="embaixador", ref_tipo="evento_agente",
            ref_id=str(evento.id), estado="pendente", linter_ok=True,
            criado_em=manage._agora(),
        ))

    with db.get_session() as s:
        nifs = {c["nif"] for c in detetar_candidatos(s, limiar=5)}

    assert "509375499" not in nifs


def test_deteccao_optout_exclui(bd):
    with db.get_session() as s:
        _seed_grupo(s, "513777777", 6, email="geral@optout.pt", nr_base=700000)

    with db.get_session() as s:
        candidatos = detetar_candidatos(
            s, limiar=5, log_optout=["geral@optout.pt"],
        )
    assert candidatos == []


def test_deteccao_singular_nunca_aparece_no_output(bd):
    with db.get_session() as s:
        _seed_grupo(s, "513888888", 6, email="geral@candidato.pt", nr_base=800000)
        # Registos de pessoa singular (NIF 2xx) — nunca devem contaminar o
        # output, mesmo coexistindo na mesma BD.
        for i in range(6):
            s.add(models.Registo(
                nr_registo=900000 + i, nome_alojamento="Casa da Maria",
                concelho="Faro", modalidade="moradia", nr_camas=2,
                titular_tipo="singular", titular_nome="Maria Santos",
                nif="234555666", email="maria.santos@gmail.com",
                hash_campos="h",
            ))

    with db.get_session() as s:
        candidatos = detetar_candidatos(s, limiar=5)

    bruto = json.dumps(candidatos, ensure_ascii=False)
    assert "singular" not in bruto
    assert "Maria" not in bruto
    assert "maria.santos" not in bruto
    assert "234555666" not in bruto


# ==========================================================================
#  manage.py — subcomandos
# ==========================================================================
def test_embaixador_detetar_cli_wiring_optout(bd, capsys):
    """`_cmd_embaixador_detetar` liga o OptOut real da BD (como o ANGARIADOR
    faz para o log_optout) — um candidato cujo email já está na tabela
    `optouts` não pode sair no `detetar` do subcomando."""
    with db.get_session() as s:
        _seed_grupo(s, "513999999", 6, email="geral@wiring.pt", nr_base=110000)
        s.add(models.OptOut(email="geral@wiring.pt", origem="formulario"))

    rc = manage.main(["embaixador", "detetar", "--limiar", "5", "--max", "10"])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["candidatos"] == []
    assert dados["total"] == 0


def test_embaixador_lint_aprova_texto_conforme(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _TEXTO_COLD_OK)
    assert manage.main(["embaixador", "lint", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True


def test_embaixador_enfileirar_cria_item_cold_camada_4(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _TEXTO_COLD_OK)
    rc = manage.main([
        "embaixador", "enfileirar", "--tipo", "proposta_parceria", "--stdin",
        "--nif", "513111111",
    ])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True

    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "proposta_parceria"
        assert item.risco == "alto"
        assert item.camada_risco == 4
        assert item.agente_origem == "embaixador"
        assert item.ref_tipo == "evento_agente"
        assert item.estado == "pendente"
        assert item.linter_ok is True
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "embaixador"
        assert evento.tipo == "conteudo_proposto"
        assert evento.payload["tipo"] == "proposta_parceria"
        assert evento.payload["nif"] == "513111111"
        assert evento.payload["corpo_texto"] == _TEXTO_COLD_OK


def test_embaixador_enfileirar_sem_nif_falha(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _TEXTO_COLD_OK)
    rc = manage.main([
        "embaixador", "enfileirar", "--tipo", "proposta_parceria", "--stdin",
    ])
    assert rc == 2
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_embaixador_enfileirar_reprovado_nao_insere(bd, capsys, monkeypatch):
    """Texto sem o disclaimer (R7) nem a identificação Cosmic Oasis (R9) —
    o opt-out (R8) até passaria via `tem_optout_carimbado=True`, mas R7/R9
    continuam a bloquear (fail-closed; nada é inserido)."""
    _stdin(monkeypatch, "Bom dia, temos uma proposta de parceria comercial.")
    rc = manage.main([
        "embaixador", "enfileirar", "--tipo", "proposta_parceria", "--stdin",
        "--nif", "513111111",
    ])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert dados["violacoes"]
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0
        assert s.query(ms.EventoAgente).count() == 0


def test_embaixador_enfileirar_escalar(bd, capsys):
    rc = manage.main([
        "embaixador", "enfileirar", "--tipo", "proposta_parceria",
        "--nif", "513111111",
        "--escalar", "--motivo", "sem candidatos elegíveis esta semana",
    ])
    assert rc == 0
    assert _json_out(capsys) == {"escalado": True}
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1


def test_embaixador_estado_conta_por_estado(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _TEXTO_COLD_OK)
    manage.main([
        "embaixador", "enfileirar", "--tipo", "proposta_parceria", "--stdin",
        "--nif", "513111111",
    ])
    capsys.readouterr()
    assert manage.main(["embaixador", "estado"]) == 0
    dados = _json_out(capsys)
    assert dados["revisao"] == {"pendente": 1}


def test_embaixador_estado_vazio(bd, capsys):
    assert manage.main(["embaixador", "estado"]) == 0
    assert _json_out(capsys) == {"revisao": {}}


# ==========================================================================
#  MAESTRO vê o EMBAIXADOR
# ==========================================================================
def test_maestro_saude_inclui_embaixador(bd, capsys):
    assert manage.main(["maestro-saude"]) == 0
    dados = _json_out(capsys)
    assert "embaixador" in dados["executores"]


def test_maestro_retry_aceita_embaixador():
    p = manage._construir_parser()
    assert p.parse_args(
        ["maestro-retry", "--agente", "embaixador", "--backoff", "60"]
    ).agente == "embaixador"
