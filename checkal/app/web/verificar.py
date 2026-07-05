"""Verificação pública consent-first de um Alojamento Local (SPEC-FDS2.md §verificar).

O widget do site deixa qualquer visitante confirmar se um AL consta do espelho local
do RNAL. A resposta expõe APENAS dados públicos do estabelecimento — nº de registo,
nome, concelho, estado (`ativo`|`desaparecido`) e data de registo. NUNCA devolve dados
do titular (NIF, email, telefone, nome do titular).

Porquê a fronteira está no *código* e não na configuração: reutilizar os contactos do
RNAL para prospeção é o risco RGPD nº 1 do projeto (finalidade incompatível, art. 5/1/b;
a CNPD sanciona). A vista pública é, por isso, uma lista branca explícita de campos, e o
`response_model` do FastAPI filtra qualquer coisa que lhe escape.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

import app.db as db
from app.models import Registo


class ResultadoVerificacao(BaseModel):
    """Vista pública consent-first — o contrato de saída do endpoint.

    Só campos do estabelecimento. Serve de `response_model`: o FastAPI descarta
    qualquer campo que não conste aqui, pelo que nenhum dado de titular pode vazar
    mesmo que fosse passado por engano.
    """

    encontrado: bool
    nr_registo: int | None = None
    nome_alojamento: str | None = None
    concelho: str | None = None
    estado: str | None = None  # 'ativo' | 'desaparecido'
    data_registo: str | None = None  # ISO-8601 (AAAA-MM-DD) ou None


router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


def _extrair_nr(q: str) -> int | None:
    """Interpreta `q` como nº de registo RNAL, tolerando o sufixo "/AL".

    Aceita "100031", "100031/AL", " 100031 "; devolve o inteiro, ou `None` se `q`
    não for um número de registo (segue então para a procura por nome).
    """
    cabeca = q.strip().split("/", 1)[0].strip()
    return int(cabeca) if cabeca.isdigit() else None


def _padrao_like(texto: str) -> str:
    """Escapa `texto` para uso seguro num ILIKE (neutraliza `%`, `_` e `\\`)."""
    esc = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def _para_saida(r: Registo) -> ResultadoVerificacao:
    """Projeta um `Registo` na vista pública (lista branca explícita de campos).

    O estado deriva de `desaparecido_em`: `NULL` → `ativo`; preenchido → `desaparecido`.
    """
    return ResultadoVerificacao(
        encontrado=True,
        nr_registo=r.nr_registo,
        nome_alojamento=r.nome_alojamento,
        concelho=r.concelho,
        estado="ativo" if r.desaparecido_em is None else "desaparecido",
        data_registo=r.data_registo.isoformat() if r.data_registo else None,
    )


@router.get("/api/verificar", response_model=ResultadoVerificacao)
def verificar(
    q: str = Query(default="", description="nº de registo RNAL ou nome do alojamento"),
) -> ResultadoVerificacao:
    """Procura um AL por nº de registo ou por nome (case-insensitive).

    Estratégia: se `q` for um número de registo, procura pela PK; caso contrário
    procura pelo nome do alojamento de forma case-insensitive. Devolve sempre um
    `ResultadoVerificacao` (nunca 404) para o widget distinguir "não encontrado"
    de erro. `q` vazio → não encontrado.
    """
    termo = q.strip()
    if not termo:
        return ResultadoVerificacao(encontrado=False)

    with db.get_session() as s:
        nr = _extrair_nr(termo)
        if nr is not None:
            r = s.get(Registo, nr)
            return _para_saida(r) if r is not None else ResultadoVerificacao(encontrado=False)

        r = s.scalars(
            select(Registo)
            .where(Registo.nome_alojamento.ilike(_padrao_like(termo), escape="\\"))
            .order_by(Registo.nr_registo)
        ).first()
        return _para_saida(r) if r is not None else ResultadoVerificacao(encontrado=False)
