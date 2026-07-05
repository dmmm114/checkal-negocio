"""Testes do cliente HTTP da API RNAL — app.rnal.client.

Contrato (SPEC-FDS1.md §client):
  - `fetch_concelho(concelho, *, cliente_http=None) -> list[dict]` (bruto).
  - `fetch_todos(concelhos, *, ...) -> ResultadoVarrimento` com retry por
    concelho, pausa `config.RNAL_PAUSA_S` entre concelhos, contagem de
    `concelhos_ok`/`concelhos_falhados`, e escrita do JSON bruto **gzipado**
    em `config.SNAPSHOTS_DIR` (`raw_path`), re-lível.
  - Um concelho que falha faz retry e, esgotadas as tentativas, é contado como
    falhado **sem rebentar** o varrimento (AUTOMACAO.md §1: retry + resiliência).

**Nada de rede real**: o cliente HTTP é injetado/mockado. As respostas de
sucesso são `httpx.Response` reais (para `.json()`/`raise_for_status()` fiéis);
as falhas são `httpx.ConnectError` (rede) e `httpx.Response(500)` (estado HTTP).

Escritos ANTES da implementação (TDD). Um teste por propriedade.
"""
from __future__ import annotations

import gzip
import json

import httpx
import pytest

import app.config as config
from app.rnal.client import (
    RNAL_TENTATIVAS,
    ResultadoVarrimento,
    escrever_raw_gzip,
    fetch_concelho,
    fetch_todos,
    ler_raw_gzip,
)


# --------------------------------------------------------------------------
#  Isolamento: o sink por omissão escreve em config.SNAPSHOTS_DIR — redireciona
#  para um tmp por teste para nunca poluir o data/snapshots do repositório.
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _snapshots_isolados(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", tmp_path / "snapshots")


# --------------------------------------------------------------------------
#  Dublês de teste (nada toca a rede)
# --------------------------------------------------------------------------
def _registo(nr: int, concelho: str, **over) -> dict:
    """Um registo bruto no formato da API (`RNAL_Registo` aninhado)."""
    interno = {
        "NrRegisto": f"{nr}/AL",
        "Concelho": concelho,
        "NomeAlojamento": f"AL {nr}",
        "TitulardaExploracao": {
            "Tipo": "Pessoa singular",
            "Nome": "Fulano",
            "Contribuinte": "123456789",
            "Email": "a@b.pt",
        },
    }
    interno.update(over)
    return {"RNAL_Registo": interno}


def _responde(payload):
    """Devolve um callable que produz uma `httpx.Response` 200 com `payload`."""
    def _fn() -> httpx.Response:
        pedido = httpx.Request("GET", config.RNAL_API)
        return httpx.Response(200, json=payload, request=pedido)
    return _fn


def _responde_500():
    """Callable que devolve uma resposta HTTP 500 (erro de estado)."""
    def _fn() -> httpx.Response:
        pedido = httpx.Request("GET", config.RNAL_API)
        return httpx.Response(500, request=pedido)
    return _fn


class FalhaRede:
    """Callable que simula falha de rede; opcionalmente recupera após `ate` falhas.

    Conta as invocações (`n`) — permite provar que o retry foi tentado.
    """

    def __init__(self, *, ate: int | None = None, sucesso=None):
        self.n = 0
        self.ate = ate            # nº de falhas iniciais antes de recuperar
        self.sucesso = sucesso or []

    def __call__(self) -> httpx.Response:
        self.n += 1
        if self.ate is not None and self.n > self.ate:
            pedido = httpx.Request("GET", config.RNAL_API)
            return httpx.Response(200, json=self.sucesso, request=pedido)
        raise httpx.ConnectError("falha simulada de rede")


class ClienteFake:
    """Substitui `httpx.Client`. Mapeia concelho → callable de resposta.

    Regista cada `.get` em `self.chamadas` como `(url, concelho)`.
    """

    def __init__(self, mapa: dict):
        self.mapa = mapa
        self.chamadas: list[tuple[str, str | None]] = []

    def get(self, url, params=None) -> httpx.Response:
        concelho = (params or {}).get("Concelho")
        self.chamadas.append((url, concelho))
        return self.mapa[concelho]()


class Relogio:
    """Captura as pausas pedidas a `dormir` (sem dormir de verdade)."""

    def __init__(self):
        self.pausas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.pausas.append(segundos)


# --------------------------------------------------------------------------
#  fetch_concelho — devolve a lista bruta
# --------------------------------------------------------------------------
def test_fetch_concelho_ok_devolve_lista_bruta():
    r1, r2 = _registo(1, "Faro"), _registo(2, "Faro")
    cli = ClienteFake({"Faro": _responde([r1, r2])})

    out = fetch_concelho("Faro", cliente_http=cli)

    assert out == [r1, r2]
    assert out[0]["RNAL_Registo"]["NrRegisto"] == "1/AL"


def test_fetch_concelho_usa_url_e_param_concelho():
    cli = ClienteFake({"Loulé": _responde([])})

    fetch_concelho("Loulé", cliente_http=cli)

    assert cli.chamadas == [(config.RNAL_API, "Loulé")]


def test_fetch_concelho_sem_resultados_devolve_lista_vazia():
    # concelho sem AL / resposta sem lista → [] (respondeu validamente, 0 registos)
    cli = ClienteFake({"Corvo": _responde({"mensagem": "sem resultados"})})
    assert fetch_concelho("Corvo", cliente_http=cli) == []


def test_fetch_concelho_desembrulha_wrapper_dict():
    rec = _registo(9, "Faro")
    cli = ClienteFake({"Faro": _responde({"RNAL": [rec]})})
    assert fetch_concelho("Faro", cliente_http=cli) == [rec]


def test_fetch_concelho_registo_unico_dict_vira_lista():
    rec = _registo(9, "Faro")  # tem chave RNAL_Registo mas não é uma lista
    cli = ClienteFake({"Faro": _responde(rec)})
    assert fetch_concelho("Faro", cliente_http=cli) == [rec]


def test_fetch_concelho_propaga_erro_de_rede():
    # sem retry a este nível: fetch_concelho levanta; o retry vive em fetch_todos
    cli = ClienteFake({"Faro": FalhaRede()})
    with pytest.raises(httpx.HTTPError):
        fetch_concelho("Faro", cliente_http=cli)


def test_fetch_concelho_erro_http_levanta():
    cli = ClienteFake({"Faro": _responde_500()})
    with pytest.raises(httpx.HTTPStatusError):
        fetch_concelho("Faro", cliente_http=cli)


# --------------------------------------------------------------------------
#  fetch_todos — contagem ok/falhados, retry, resiliência
# --------------------------------------------------------------------------
def test_fetch_todos_conta_ok_e_falhados_sem_rebentar():
    r1 = _registo(1, "Faro")
    r2, r3 = _registo(2, "Loulé"), _registo(3, "Loulé")
    falha = FalhaRede()
    cli = ClienteFake({
        "Faro": _responde([r1]),
        "XFalha": falha,
        "Loulé": _responde([r2, r3]),
    })

    res = fetch_todos(
        ["Faro", "XFalha", "Loulé"], cliente_http=cli, dormir=Relogio(),
    )

    assert isinstance(res, ResultadoVarrimento)
    assert res.concelhos_ok == {"Faro", "Loulé"}
    assert res.concelhos_falhados == {"XFalha"}
    assert res.n_ok == 2 and res.n_falhados == 1
    assert res.total_registos == 3
    assert res.registos_por_concelho["Loulé"] == [r2, r3]
    # o concelho falhado NÃO aparece no mapa de registos
    assert "XFalha" not in res.registos_por_concelho


def test_fetch_todos_faz_retry_no_concelho_falhado():
    falha = FalhaRede()  # falha sempre
    cli = ClienteFake({"XFalha": falha})

    res = fetch_todos(["XFalha"], cliente_http=cli, dormir=Relogio())

    assert res.concelhos_falhados == {"XFalha"}
    assert falha.n == RNAL_TENTATIVAS  # tentou exatamente RNAL_TENTATIVAS vezes


def test_fetch_todos_retry_recupera_conta_ok():
    rec = _registo(7, "Faro")
    falha = FalhaRede(ate=1, sucesso=[rec])  # falha 1×, depois responde
    cli = ClienteFake({"Faro": falha})

    res = fetch_todos(["Faro"], cliente_http=cli, dormir=Relogio())

    assert res.concelhos_ok == {"Faro"}
    assert res.registos_por_concelho["Faro"] == [rec]
    assert falha.n == 2  # 1 falha + 1 sucesso


def test_fetch_todos_erro_http_conta_falhado():
    cli = ClienteFake({"Faro": _responde_500()})
    res = fetch_todos(["Faro"], cliente_http=cli, dormir=Relogio())
    assert res.concelhos_falhados == {"Faro"}


# --------------------------------------------------------------------------
#  Pausa entre concelhos (config.RNAL_PAUSA_S)
# --------------------------------------------------------------------------
def test_fetch_todos_pausa_entre_concelhos():
    relogio = Relogio()
    cli = ClienteFake({
        "Faro": _responde([]), "Loulé": _responde([]), "Lagos": _responde([]),
    })

    fetch_todos(["Faro", "Loulé", "Lagos"], cliente_http=cli, dormir=relogio)

    # N concelhos ok, sem retries → N-1 pausas, todas de RNAL_PAUSA_S
    assert relogio.pausas == [config.RNAL_PAUSA_S, config.RNAL_PAUSA_S]


def test_fetch_todos_um_concelho_nao_pausa():
    relogio = Relogio()
    cli = ClienteFake({"Faro": _responde([])})
    fetch_todos(["Faro"], cliente_http=cli, dormir=relogio)
    assert relogio.pausas == []


def test_fetch_todos_lista_vazia_devolve_resultado_vazio():
    res = fetch_todos([], cliente_http=ClienteFake({}), dormir=Relogio())
    assert res.concelhos_ok == set() and res.concelhos_falhados == set()
    assert res.total_registos == 0


# --------------------------------------------------------------------------
#  Snapshot raw gzip: escrito e re-lível
# --------------------------------------------------------------------------
def test_escrever_e_ler_raw_gzip_round_trip(tmp_path):
    payload = {"registos_por_concelho": {"Faro": [_registo(1, "Faro")]}, "n": 1}

    caminho = escrever_raw_gzip(payload, dir_destino=tmp_path)

    assert caminho.exists()
    assert str(caminho).endswith(".json.gz")
    assert caminho.parent == tmp_path
    # é mesmo gzip válido
    with gzip.open(caminho, "rb") as fh:
        assert json.loads(fh.read().decode("utf-8")) == payload
    # e o leitor do módulo devolve o mesmo
    assert ler_raw_gzip(caminho) == payload


def test_escrever_raw_gzip_default_usa_snapshots_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", tmp_path)
    caminho = escrever_raw_gzip({"x": 1})
    assert caminho.parent == tmp_path


def test_fetch_todos_grava_raw_relible(tmp_path):
    r1 = _registo(1, "Faro")
    escritos: list = []

    def sink(payload) -> str:
        caminho = escrever_raw_gzip(payload, dir_destino=tmp_path)
        escritos.append(caminho)
        return str(caminho)

    cli = ClienteFake({"Faro": _responde([r1]), "XFalha": FalhaRede()})
    res = fetch_todos(
        ["Faro", "XFalha"], cliente_http=cli, dormir=Relogio(), sink_raw=sink,
    )

    assert res.raw_path is not None
    assert len(escritos) == 1
    lido = ler_raw_gzip(res.raw_path)
    assert lido["registos_por_concelho"]["Faro"] == [r1]
    assert set(lido["concelhos_ok"]) == {"Faro"}
    assert set(lido["concelhos_falhados"]) == {"XFalha"}


def test_resultado_todos_os_registos_achata_por_concelho():
    r1, r2, r3 = _registo(1, "Faro"), _registo(2, "Loulé"), _registo(3, "Loulé")
    cli = ClienteFake({"Faro": _responde([r1]), "Loulé": _responde([r2, r3])})

    res = fetch_todos(["Faro", "Loulé"], cliente_http=cli, dormir=Relogio())

    todos = res.todos_os_registos()
    assert todos == [r1, r2, r3]
