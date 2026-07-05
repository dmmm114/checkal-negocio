"""Cliente HTTP da API RNAL (`list_RNAL`) — busca por concelho e varrimento total.

Fronteira do módulo (SPEC-FDS1.md §client): fala com a API do Turismo de
Portugal via `httpx` e devolve o **JSON bruto** (sem validar — isso é do
`schema`/`ingest`). Não toca na BD.

Princípios (AUTOMACAO.md §1):
  - **Resiliência**: cada concelho tem retry; se esgotar as tentativas é contado
    como *falhado* e o varrimento continua — «um varrimento falhado não deixa a
    semana às escuras». Nada rebenta por causa de um concelho.
  - **Educação para com a API**: pausa de `config.RNAL_PAUSA_S` entre concelhos,
    `timeout` e `User-Agent` de `config`.
  - **Fidelidade**: o JSON bruto do varrimento é gravado **gzipado** em
    `config.SNAPSHOTS_DIR` (~9 MB/varrimento) para reprocessamento/auditoria.

Injeção para testes: `fetch_concelho`/`fetch_todos` aceitam um `cliente_http`
(qualquer objeto com `.get(url, params=...) -> httpx.Response`) e um `dormir`
(callable de pausa). Assim os testes correm **sem rede real** e sem esperar.
"""
from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

import app.config as config

# Nº de tentativas por concelho antes de o dar como falhado (1 + retries).
RNAL_TENTATIVAS = 3
# Backoff base entre tentativas (segundos); cresce linearmente com a tentativa.
# Passa por `dormir`, logo é neutralizado nos testes.
RNAL_BACKOFF_S = 1.0


@dataclass
class ResultadoVarrimento:
    """Resultado de um varrimento completo (uma execução de `fetch_todos`).

    Serve dois consumidores:
      - `ingest`, que persiste a linha `varrimentos` (`n_ok`/`n_falhados`,
        `total_registos`, `raw_path`) e achata os registos com `todos_os_registos()`;
      - `diffing`, que recebe `concelhos_ok` (o **conjunto** de concelhos que
        responderam validamente) para aplicar a regra dos 2 varrimentos só onde
        a API respondeu — nunca marcando «desaparecido» por timeout parcial.
    """

    registos_por_concelho: dict[str, list[dict]] = field(default_factory=dict)
    concelhos_ok: set[str] = field(default_factory=set)
    concelhos_falhados: set[str] = field(default_factory=set)
    raw_path: str | None = None
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None

    @property
    def n_ok(self) -> int:
        return len(self.concelhos_ok)

    @property
    def n_falhados(self) -> int:
        return len(self.concelhos_falhados)

    @property
    def total_registos(self) -> int:
        return sum(len(regs) for regs in self.registos_por_concelho.values())

    def todos_os_registos(self) -> list[dict]:
        """Achata os registos de todos os concelhos numa só lista (ordem de inserção)."""
        achatado: list[dict] = []
        for regs in self.registos_por_concelho.values():
            achatado.extend(regs)
        return achatado


def _novo_cliente() -> httpx.Client:
    """Cria um `httpx.Client` com o `timeout` e `User-Agent` canónicos."""
    return httpx.Client(
        timeout=config.RNAL_TIMEOUT_S,
        headers={"User-Agent": config.RNAL_USER_AGENT},
    )


def _extrair_lista(payload: Any) -> list[dict]:
    """Normaliza a resposta da API numa lista de registos brutos (dicts).

    Tolera três formas observadas/plausíveis, sem validar o conteúdo:
      - lista de registos no topo (caso esperado);
      - invólucro `{"...": [ ... ]}` (devolve a primeira lista encontrada);
      - registo único num objeto (`{"RNAL_Registo": {...}}`) → lista de 1;
      - resposta sem registos (objeto sem lista) → ``[]`` (concelho com 0 AL).
    Uma resposta que não seja lista nem objeto é lixo → `TypeError` (o concelho
    passa a falhado no `fetch_todos`, não contamina o diffing).
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for valor in payload.values():
            if isinstance(valor, list):
                return [r for r in valor if isinstance(r, dict)]
        if "RNAL_Registo" in payload or "NrRegisto" in payload:
            return [payload]
        return []
    raise TypeError(f"Resposta RNAL inesperada: {type(payload).__name__}")


def _fetch_um(cliente_http: Any, concelho: str) -> list[dict]:
    """Um pedido único (sem retry): GET → estado HTTP → JSON → lista bruta."""
    resposta = cliente_http.get(config.RNAL_API, params={"Concelho": concelho})
    resposta.raise_for_status()
    return _extrair_lista(resposta.json())


def fetch_concelho(concelho: str, *, cliente_http: Any | None = None) -> list[dict]:
    """Busca os registos brutos de um concelho. Uma tentativa; erros propagam.

    Se `cliente_http` for `None`, cria (e fecha) um `httpx.Client` próprio. Nos
    testes injeta-se um cliente falso — nunca há rede real. O retry por concelho
    vive em `fetch_todos`, não aqui.
    """
    if cliente_http is not None:
        return _fetch_um(cliente_http, concelho)
    with _novo_cliente() as cliente:
        return _fetch_um(cliente, concelho)


def _fetch_com_retry(
    concelho: str,
    *,
    cliente_http: Any,
    tentativas: int,
    dormir: Callable[[float], None],
) -> list[dict]:
    """Busca um concelho com até `tentativas` tentativas; re-levanta a última falha."""
    ultima_exc: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            return fetch_concelho(concelho, cliente_http=cliente_http)
        except Exception as exc:  # rede, HTTP, JSON inválido — tudo retriável
            ultima_exc = exc
            if tentativa < tentativas:
                dormir(RNAL_BACKOFF_S * tentativa)
    assert ultima_exc is not None  # o loop corre ≥1 vez
    raise ultima_exc


def escrever_raw_gzip(
    payload: Any, *, dir_destino: Path | None = None
) -> Path:
    """Serializa `payload` em JSON e grava-o **gzipado**; devolve o caminho.

    Nome: ``rnal_<UTC-ISO-compacto>_<8hex>.json.gz`` (o sufixo aleatório evita
    colisões dentro do mesmo segundo). Por omissão grava em `config.SNAPSHOTS_DIR`.
    """
    destino = Path(dir_destino) if dir_destino is not None else config.SNAPSHOTS_DIR
    destino.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    caminho = destino / f"rnal_{carimbo}_{uuid4().hex[:8]}.json.gz"
    dados = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with gzip.open(caminho, "wb") as fh:
        fh.write(dados)
    return caminho


def ler_raw_gzip(caminho: str | Path) -> Any:
    """Lê e desserializa um snapshot gravado por `escrever_raw_gzip`."""
    with gzip.open(caminho, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def fetch_todos(
    concelhos: Sequence[str],
    *,
    cliente_http: Any | None = None,
    sink_raw: Callable[[Any], str] | None = None,
    dormir: Callable[[float], None] = time.sleep,
    tentativas: int = RNAL_TENTATIVAS,
) -> ResultadoVarrimento:
    """Varre todos os `concelhos`, com retry por concelho e pausa entre eles.

    Resiliente: um concelho que esgota as tentativas vai para `concelhos_falhados`
    e o varrimento prossegue (não rebenta). Grava o JSON bruto do varrimento
    gzipado (via `sink_raw`, ou por omissão em `config.SNAPSHOTS_DIR`) e devolve
    um `ResultadoVarrimento`.

    Parâmetros injetáveis (testes, sem rede/espera): `cliente_http` (cliente
    falso), `sink_raw` (redireciona a escrita do raw), `dormir` (neutraliza pausas).
    """
    iniciado_em = datetime.now(timezone.utc)
    registos_por_concelho: dict[str, list[dict]] = {}
    concelhos_ok: set[str] = set()
    concelhos_falhados: set[str] = set()

    proprio_cliente = cliente_http is None
    cliente = _novo_cliente() if proprio_cliente else cliente_http
    try:
        for indice, concelho in enumerate(concelhos):
            if indice > 0:
                dormir(config.RNAL_PAUSA_S)  # educação para com a API
            try:
                registos = _fetch_com_retry(
                    concelho,
                    cliente_http=cliente,
                    tentativas=tentativas,
                    dormir=dormir,
                )
            except Exception:
                # esgotou o retry — conta como falhado, não contamina o diffing
                concelhos_falhados.add(concelho)
                continue
            registos_por_concelho[concelho] = registos
            concelhos_ok.add(concelho)
    finally:
        if proprio_cliente:
            cliente.close()

    concluido_em = datetime.now(timezone.utc)

    envelope = {
        "gerado_em": concluido_em.isoformat(),
        "concelhos_ok": sorted(concelhos_ok),
        "concelhos_falhados": sorted(concelhos_falhados),
        "registos_por_concelho": registos_por_concelho,
    }
    if sink_raw is not None:
        raw_path = sink_raw(envelope)
    else:
        raw_path = str(escrever_raw_gzip(envelope))

    return ResultadoVarrimento(
        registos_por_concelho=registos_por_concelho,
        concelhos_ok=concelhos_ok,
        concelhos_falhados=concelhos_falhados,
        raw_path=raw_path,
        iniciado_em=iniciado_em,
        concluido_em=concluido_em,
    )
