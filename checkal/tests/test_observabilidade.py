"""Testes FDS 5 do dead-man switch (SPEC-FDS5.md §observabilidade).

`com_healthcheck(slug)` — usável como **contexto** e como **decorator** — faz ping
ao Healthchecks.io no fim de cada cron (httpx **injetado**): sucesso → ping de
sucesso; exceção → ping de falha e a exceção **propaga** (nunca é suprimida).

Disciplina LIVE-GATED (inviolável): zero rede real. Nos testes injeta-se um cliente
HTTP falso (`_ClienteFake`) que só regista as URLs; a via de composição de um
`httpx.Client` real (`_novo_cliente`) é monkeypatched, logo nunca liga. O gate
(`config.healthchecks_ativo`) fecha os pings quando não há ping key nem cliente.

Escrito ANTES da implementação (TDD). Isolamento total: não toca noutros módulos.
"""
from __future__ import annotations

import pytest

import app.config as config
from app import observabilidade
from app.observabilidade import FALHA, INICIO, SUCESSO, com_healthcheck, url_ping

PING_KEY_TESTE = "pk-teste"
BASE_TESTE = "https://hc-ping.com"


@pytest.fixture(autouse=True)
def _config_previsivel(monkeypatch):
    """Fixa base + ping key deterministas (URLs previsíveis; gate ligado)."""
    monkeypatch.setattr(config, "HEALTHCHECKS_BASE_URL", BASE_TESTE)
    monkeypatch.setattr(config, "HEALTHCHECKS_PING_KEY", PING_KEY_TESTE)


class _RespostaFake:
    status_code = 200


class _ClienteFake:
    """Dublê de `httpx.Client`: regista as URLs de GET; nunca toca a rede.

    É também gestor de contexto (`with ... as c`) para servir a via de composição
    `_novo_cliente` sem qualquer diferença de forma para o cliente real.
    """

    def __init__(self, *, erro: Exception | None = None) -> None:
        self.gets: list[str] = []
        self._erro = erro

    def get(self, url, *args, **kwargs):
        self.gets.append(url)
        if self._erro is not None:
            raise self._erro
        return _RespostaFake()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _url(slug: str, sufixo: str = "") -> str:
    base = f"{BASE_TESTE}/{PING_KEY_TESTE}/{slug}"
    return f"{base}/{sufixo}" if sufixo else base


# --------------------------------------------------------------------------
#  Contexto — sucesso vs exceção (o par do contrato)
# --------------------------------------------------------------------------
def test_sucesso_pinga_url_de_sucesso():
    cli = _ClienteFake()
    with com_healthcheck("varrimento", cliente_http=cli):
        pass
    assert cli.gets == [_url("varrimento")]


def test_excecao_pinga_falha_e_relevanta():
    cli = _ClienteFake()
    with pytest.raises(ValueError, match="rebentou"):
        with com_healthcheck("dre", cliente_http=cli):
            raise ValueError("rebentou")
    # ping de FALHA (sufixo /fail), não de sucesso
    assert cli.gets == [_url("dre", FALHA)]


# --------------------------------------------------------------------------
#  Decorator — mesma semântica, preserva valor de retorno e metadados
# --------------------------------------------------------------------------
def test_decorator_sucesso_devolve_valor_e_pinga():
    cli = _ClienteFake()

    @com_healthcheck("dunning", cliente_http=cli)
    def cron():
        return 42

    assert cron() == 42
    assert cron.__name__ == "cron"  # functools.wraps preserva a identidade
    assert cli.gets == [_url("dunning")]


def test_decorator_excecao_pinga_falha_e_relevanta():
    cli = _ClienteFake()

    @com_healthcheck("suporte", cliente_http=cli)
    def cron():
        raise RuntimeError("falhou")

    with pytest.raises(RuntimeError, match="falhou"):
        cron()
    assert cli.gets == [_url("suporte", FALHA)]


def test_decorator_reutilizavel_em_varias_chamadas():
    # A mesma instância-decorator serve chamadas repetidas do cron (sem estado a vazar).
    cli = _ClienteFake()

    @com_healthcheck("dunning", cliente_http=cli)
    def cron():
        return "ok"

    cron()
    cron()
    assert cli.gets == [_url("dunning"), _url("dunning")]


# --------------------------------------------------------------------------
#  A observabilidade NUNCA quebra nem mascara o cron
# --------------------------------------------------------------------------
def test_ping_de_sucesso_falhado_nao_quebra_o_cron():
    # O corpo corre bem; o ping de sucesso rebenta (rede) mas NÃO propaga.
    cli = _ClienteFake(erro=OSError("rede caiu"))
    with com_healthcheck("backup", cliente_http=cli):
        pass
    assert cli.gets == [_url("backup")]  # tentou pingar, engoliu o erro


def test_ping_de_falha_falhado_nao_mascara_excecao_original():
    # No ramo de exceção, se o próprio ping /fail rebentar, propaga a exceção
    # ORIGINAL do cron (não a da rede) — senão o erro real perder-se-ia.
    cli = _ClienteFake(erro=OSError("rede caiu"))
    with pytest.raises(ValueError, match="original"):
        with com_healthcheck("backup", cliente_http=cli):
            raise ValueError("original")
    assert cli.gets == [_url("backup", FALHA)]


# --------------------------------------------------------------------------
#  Live-gate — sem ping key nem cliente injetado, nada toca a rede
# --------------------------------------------------------------------------
def test_gate_desligado_sem_key_nem_cliente_nao_compoe_rede(monkeypatch):
    monkeypatch.setattr(config, "HEALTHCHECKS_PING_KEY", "")

    def _explode():
        raise AssertionError("não devia compor cliente HTTP sem ping key (live-gate)")

    monkeypatch.setattr(observabilidade, "_novo_cliente", _explode)
    assert config.healthchecks_ativo() is False

    resultado = []

    @com_healthcheck("varrimento")
    def cron():
        resultado.append("correu")
        return "feito"

    assert cron() == "feito"      # o cron corre na mesma
    assert resultado == ["correu"]  # e não houve tentativa de rede


def test_compoe_cliente_quando_ativo_e_sem_injecao(monkeypatch):
    # Sem cliente injetado mas com ping key (fixture) → compõe via `_novo_cliente`
    # (monkeypatched para um dublê) e pinga sucesso, sem tocar a rede.
    cli = _ClienteFake()
    monkeypatch.setattr(observabilidade, "_novo_cliente", lambda: cli)
    with com_healthcheck("varrimento"):
        pass
    assert cli.gets == [_url("varrimento")]


# --------------------------------------------------------------------------
#  Construção pura da URL (testável sem rede)
# --------------------------------------------------------------------------
def test_url_ping_sucesso_falha_e_inicio():
    assert url_ping("varrimento", SUCESSO) == _url("varrimento")
    assert url_ping("varrimento", FALHA) == _url("varrimento", "fail")
    assert url_ping("varrimento", INICIO) == _url("varrimento", "start")


def test_url_ping_normaliza_barra_final_da_base(monkeypatch):
    monkeypatch.setattr(config, "HEALTHCHECKS_BASE_URL", "https://hc-ping.com/")
    assert url_ping("x", SUCESSO) == f"https://hc-ping.com/{PING_KEY_TESTE}/x"


def test_sufixos_sao_os_do_healthchecks():
    assert (SUCESSO, FALHA, INICIO) == ("", "fail", "start")


# --------------------------------------------------------------------------
#  Ping de início (opcional): mede duração do cron no Healthchecks
# --------------------------------------------------------------------------
def test_pingar_inicio_faz_start_e_depois_sucesso():
    cli = _ClienteFake()
    with com_healthcheck("varrimento", cliente_http=cli, pingar_inicio=True):
        pass
    assert cli.gets == [_url("varrimento", INICIO), _url("varrimento")]


def test_pingar_inicio_com_excecao_faz_start_e_falha():
    cli = _ClienteFake()
    with pytest.raises(RuntimeError):
        with com_healthcheck("dre", cliente_http=cli, pingar_inicio=True):
            raise RuntimeError("x")
    assert cli.gets == [_url("dre", INICIO), _url("dre", FALHA)]
