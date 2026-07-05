"""Orquestrador da ingestão RNAL — o único módulo do FDS 1 que toca na BD.

Fronteira do módulo (SPEC-FDS1.md §ingest): junta as peças puras (`schema`,
`hashing`, `diffing`) e o cliente HTTP (`client`) num varrimento completo,
persistindo o resultado na base. Encadeia:

    1. **fetch** — pede os registos brutos ao `client` (injetável nos testes);
    2. **validação Pydantic** — `parse_registo` de cada registo. Se a forma do
       JSON mudou (`DriftEsquemaRNAL`), o varrimento é marcado ``abortado`` e o
       diffing **não corre** (AUTOMACAO.md §1: nunca diffar sobre dados suspeitos);
    3. **normalização** — cada `RegistoRNAL` vira um `RegistoNovo` (hash + campos);
    4. **estado_atual** — carrega as linhas `registos` da BD como `RegistoEstado`;
    5. **diffing** — `diff_varrimento(estado_atual, scan, concelhos_ok)`;
    6. **persistência** — grava os `eventos_registo`, faz *upsert* em `registos`
       (`hash_campos`, `visto_ultimo`, `ausencias_consecutivas`, `desaparecido_em`)
       e escreve a linha `varrimentos` (``ok`` | ``parcial`` | ``abortado``).

Semântica dos contadores (contrato partilhado com `diffing`): um registo
**presente** repõe `ausencias_consecutivas` a 0 e limpa `desaparecido_em`; uma
**ausência contável** (concelho ∈ `concelhos_ok`) incrementa o contador — e, se o
diffing gerou o evento ``desaparecido``, carimba `desaparecido_em`; uma ausência
num concelho que **não** respondeu (varrimento parcial) fica intacta.

Idempotência: o *upsert* usa a chave natural `nr_registo`, logo reprocessar dados
iguais não duplica linhas de `registos`; um registo inalterado não gera evento.
Cada execução grava, isso sim, a sua própria linha `varrimentos` (é um facto novo).

Injeção para testes (sem rede): `executar_varrimento` aceita um `cliente` (qualquer
objeto com `fetch_todos(...) -> ResultadoVarrimento`); `ingerir_resultado` recebe
já um `ResultadoVarrimento` fabricado à mão. A BD é a que `app.db` tiver ativa.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import app.db as db
from app.models import EventoRegisto, Registo, Varrimento
from app.rnal import client
from app.rnal.client import ResultadoVarrimento
from app.rnal.diffing import (
    EventoDiff,
    RegistoEstado,
    RegistoNovo,
    TIPO_DESAPARECIDO,
    diff_varrimento,
)
from app.rnal.schema import DriftEsquemaRNAL, RegistoRNAL, parse_registo

# Estados possíveis da linha `varrimentos` (SPEC-FDS1.md §ingest).
ESTADO_OK = "ok"
ESTADO_PARCIAL = "parcial"
ESTADO_ABORTADO = "abortado"

__all__ = [
    "ResultadoIngest",
    "ingerir_resultado",
    "executar_varrimento",
    "ESTADO_OK",
    "ESTADO_PARCIAL",
    "ESTADO_ABORTADO",
]


@dataclass
class ResultadoIngest:
    """Sumário de uma execução de ingestão (para logs/testes; não é a BD).

    `eventos` são os `EventoDiff` que o diffing produziu (vazio se ``abortado`` ou
    se nada mudou). `drift` guarda a mensagem quando o varrimento foi abortado por
    drift de esquema; caso contrário é ``None``.
    """

    varrimento_id: int
    estado: str
    eventos: list[EventoDiff] = field(default_factory=list)
    total_registos: int = 0
    concelhos_ok: int = 0
    concelhos_falhados: int = 0
    raw_path: str | None = None
    drift: str | None = None

    def por_tipo(self, tipo: str) -> list[EventoDiff]:
        """Os eventos deste varrimento de um dado `tipo`."""
        return [ev for ev in self.eventos if ev.tipo == tipo]


def _para_data(valor: Any) -> date | None:
    """``"2019-07-16"`` → `date`; ``None``/vazio/ilegível → ``None`` (campo opcional)."""
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _aplicar_campos(linha: Registo, reg: RegistoRNAL) -> None:
    """Copia os campos do `RegistoRNAL` validado para a linha ORM (upsert).

    `localidade`/`dtmnfr` do `RegistoRNAL` não têm coluna em `registos` e são
    deliberadamente ignorados. `hash_campos`, `visto_*` e os contadores de ausência
    são geridos pelo chamador (dependem do diff, não só do registo).
    """
    linha.data_registo = _para_data(reg.data_registo)
    linha.nome_alojamento = reg.nome_alojamento
    linha.modalidade = reg.modalidade
    linha.nr_camas = reg.nr_camas
    linha.nr_utentes = reg.nr_utentes
    linha.endereco = reg.endereco
    linha.cod_postal = reg.cod_postal
    linha.freguesia = reg.freguesia
    linha.concelho = reg.concelho
    linha.distrito = reg.distrito
    linha.titular_tipo = reg.titular_tipo
    linha.titular_nome = reg.titular_nome
    linha.nif = reg.nif
    linha.email = reg.email
    linha.telefone = reg.telefone
    linha.telemovel = reg.telemovel


def _validar_e_normalizar(
    resultado: ResultadoVarrimento,
) -> dict[int, RegistoRNAL]:
    """Valida cada registo bruto do varrimento; drift propaga como `DriftEsquemaRNAL`.

    Devolve o mapa ``nr_registo → RegistoRNAL``. Registos com o mesmo `nr_registo`
    (raro; ex.: repetido entre concelhos) colapsam — fica o último visto.
    """
    parseados: dict[int, RegistoRNAL] = {}
    for bruto in resultado.todos_os_registos():
        reg = parse_registo(bruto)  # DriftEsquemaRNAL sobe e aborta o varrimento
        parseados[reg.nr_registo] = reg
    return parseados


def ingerir_resultado(resultado: ResultadoVarrimento) -> ResultadoIngest:
    """Persiste um `ResultadoVarrimento`: valida, difa e grava tudo numa transação.

    Caminho de drift: se a validação Pydantic falhar, grava-se apenas a linha
    `varrimentos` com estado ``abortado`` (sem eventos nem upsert) e devolve-se
    imediatamente — o diffing nunca corre sobre dados de forma duvidosa.
    """
    momento = resultado.concluido_em or datetime.now(timezone.utc)

    # (2) validação Pydantic — antes de abrir sequer a lógica de diff.
    drift_msg: str | None = None
    parseados: dict[int, RegistoRNAL] = {}
    try:
        parseados = _validar_e_normalizar(resultado)
    except DriftEsquemaRNAL as exc:
        drift_msg = str(exc)

    with db.get_session() as s:
        # --- Caminho abortado: grava o varrimento e sai (sem diffing) ---
        if drift_msg is not None:
            varr = Varrimento(
                iniciado_em=resultado.iniciado_em,
                concluido_em=resultado.concluido_em,
                concelhos_ok=resultado.n_ok,
                concelhos_falhados=resultado.n_falhados,
                total_registos=resultado.total_registos,
                raw_path=resultado.raw_path,
                estado=ESTADO_ABORTADO,
            )
            s.add(varr)
            s.flush()
            return ResultadoIngest(
                varrimento_id=varr.id,
                estado=ESTADO_ABORTADO,
                eventos=[],
                total_registos=resultado.total_registos,
                concelhos_ok=resultado.n_ok,
                concelhos_falhados=resultado.n_falhados,
                raw_path=resultado.raw_path,
                drift=drift_msg,
            )

        # --- Caminho normal ---
        estado_str = ESTADO_PARCIAL if resultado.concelhos_falhados else ESTADO_OK
        varr = Varrimento(
            iniciado_em=resultado.iniciado_em,
            concluido_em=resultado.concluido_em,
            concelhos_ok=resultado.n_ok,
            concelhos_falhados=resultado.n_falhados,
            total_registos=resultado.total_registos,
            raw_path=resultado.raw_path,
            estado=estado_str,
        )
        s.add(varr)
        s.flush()  # materializa varr.id para carimbar os eventos
        varrimento_id = varr.id

        # (3) normalização: nr_registo → RegistoNovo (hash + campos)
        scan = {nr: RegistoNovo.de_registo(reg) for nr, reg in parseados.items()}

        # (4) estado_atual da BD
        linhas = s.query(Registo).all()
        linhas_por_nr: dict[int, Registo] = {ln.nr_registo: ln for ln in linhas}
        estado_atual = {
            ln.nr_registo: RegistoEstado.de_linha(ln) for ln in linhas
        }
        concelhos_ok = set(resultado.concelhos_ok)

        # (5) diffing puro
        eventos = diff_varrimento(estado_atual, scan, concelhos_ok)
        desaparecidos = {
            ev.nr_registo for ev in eventos if ev.tipo == TIPO_DESAPARECIDO
        }

        # (6a) upsert dos presentes: repõe contadores, atualiza campos e hash
        for nr, novo in scan.items():
            reg = parseados[nr]
            linha = linhas_por_nr.get(nr)
            if linha is None:
                linha = Registo(nr_registo=nr, visto_primeiro=momento)
                s.add(linha)
                linhas_por_nr[nr] = linha
            _aplicar_campos(linha, reg)
            linha.hash_campos = novo.hash_campos
            linha.visto_ultimo = momento
            linha.ausencias_consecutivas = 0
            linha.desaparecido_em = None

        # (6b) ausentes: conta a ausência só onde o concelho respondeu
        for nr, est in estado_atual.items():
            if nr in scan:
                continue
            if est.concelho not in concelhos_ok:
                continue  # varrimento parcial p/ este concelho → ausência ignorada
            linha = linhas_por_nr[nr]
            linha.ausencias_consecutivas = (linha.ausencias_consecutivas or 0) + 1
            if nr in desaparecidos:
                linha.desaparecido_em = momento

        s.flush()  # garante que os `registos` existem antes das FKs dos eventos

        # (6c) persiste os eventos deste varrimento
        for ev in eventos:
            s.add(
                EventoRegisto(
                    nr_registo=ev.nr_registo,
                    tipo=ev.tipo,
                    campos_alterados=ev.campos_alterados,
                    varrimento_id=varrimento_id,
                    detetado_em=momento,
                )
            )

        return ResultadoIngest(
            varrimento_id=varrimento_id,
            estado=estado_str,
            eventos=list(eventos),
            total_registos=resultado.total_registos,
            concelhos_ok=resultado.n_ok,
            concelhos_falhados=resultado.n_falhados,
            raw_path=resultado.raw_path,
        )


def executar_varrimento(
    concelhos: Sequence[str],
    *,
    cliente: Any = client,
    **fetch_kwargs: Any,
) -> ResultadoIngest:
    """Varre `concelhos` via `cliente.fetch_todos` e ingere o resultado.

    `cliente` é, por omissão, o módulo `app.rnal.client`; nos testes injeta-se um
    duplo com `fetch_todos(...) -> ResultadoVarrimento` — **sem rede**. Os
    `fetch_kwargs` (ex.: `dormir`, `sink_raw`, `tentativas`) passam para o cliente.
    """
    resultado = cliente.fetch_todos(concelhos, **fetch_kwargs)
    return ingerir_resultado(resultado)
