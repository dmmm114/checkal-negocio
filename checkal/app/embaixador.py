"""EMBAIXADOR 🤵 — deteção de candidatos a parceiro B2B (canal GTM n.º 2).

Ver `docs/superpowers/specs/2026-07-19-embaixador-atendedor-design.md` §1.

Módulo determinista, read-only, no MESMO padrão de `app.campanhas.segmentacao`:
o núcleo de compliance (`app.compliance.*`) é a ÚNICA autoridade de
elegibilidade — este módulo nunca a reimplementa. `nif.e_enderecavel` decide
quem é endereçável (NÃO o campo de texto `titular_tipo`, que diverge da
realidade em centenas de registos — ver spec); `email.e_generico` decide qual
email é de negócio; `minimizacao.filtrar_enderecaveis` constrói o contacto
minimizado; `optout.filtrar_optout` cruza a oposição DGC + o opt-out interno.
O SQL do pré-filtro é só um corte grosseiro — nunca a decisão final.

Missão de negócio: um gestor multi-AL (pessoa COLETIVA, email GENÉRICO
publicado no RNAL) que já prova volume (`limiar` registos ATIVOS) é candidato
a uma parceria B2B — comissão de 20% recorrente proposta em conversa, sempre
com "termos finais por escrito" (GTM §5/6): NUNCA uma promessa pública, só um
termo de negociação das propostas individuais.

Minimização (RGPD, RATIONALE.md §3): o output NUNCA transporta dados de
pessoa singular — nem nome, nem email, nem NIF de um titular singular. Cada
candidato é um `ContactoEnderecavel` (a mesma dataclass do cold_email) mais
agregados NÃO-PESSOAIS do grupo de registos ativos (contagem, concelhos,
modalidades, camas) — nada que identifique uma pessoa física.

    detetar_candidatos(session, *, limiar=5, max_candidatos=10,
                       lista_dgc=(), log_optout=()) -> [dict, ...]

Pipeline (tudo read-only sobre `session`, nada é escrito):
  1. Pré-filtro SQL GROSSEIRO: NIF com 9 dígitos, 1.º dígito em {5,6}, registo
     ativo (`desaparecido_em IS NULL`), agrupado por NIF com
     `COUNT(*) >= limiar`. Reduz o universo ANTES do portão — não decide.
  2. Por NIF: re-valida `nif.e_enderecavel` (a autoridade — nunca
     `titular_tipo`; o SQL usa `trim()`/`substr()` que não apanha todo o
     whitespace Unicode que `nif._limpar` apanha, por isso a re-validação
     Python não é redundante), carrega o grupo ATIVO completo, escolhe o
     email genérico MAIS FREQUENTE do grupo (o "email canónico") e constrói
     o `ContactoEnderecavel` através do MESMO portão do cold
     (`minimizacao.filtrar_enderecaveis` — nunca um caminho alternativo),
     depois cruza `optout.filtrar_optout` (oposição DGC + opt-out interno).
  3. Dedupe: um NIF com `proposta_parceria` já na fila — QUALQUER estado
     (pendente, aprovado, rejeitado, …) — fica fora; um titular = um contacto
     (ver `_nifs_ja_propostos`, decisão de implementação documentada aí).
  4. Agregados não-pessoais do grupo ativo (n_registos, concelhos distintos,
     modalidades distintas, total de camas).
  5. Ordena por `n_registos` desc (as maiores carteiras primeiro) e corta a
     `max_candidatos` (o piloto GTM cobre 3-5 parceiros por passagem).
"""
from __future__ import annotations

import collections
from collections.abc import Iterable

from sqlalchemy import text

from app.compliance import minimizacao, optout
from app.compliance.email import e_generico
from app.compliance.nif import e_enderecavel

__all__ = ["detetar_candidatos"]

# Pré-filtro grosseiro (passo 1). `trim`/`substr` do SQLite não são a
# autoridade — só reduzem o universo antes do portão Python (passo 2).
_SQL_PREFILTRO = text(
    """
    SELECT nif FROM registos
    WHERE desaparecido_em IS NULL
      AND length(trim(nif)) = 9
      AND substr(trim(nif), 1, 1) IN ('5', '6')
    GROUP BY nif
    HAVING COUNT(*) >= :limiar
    """
)


def _registo_para_dict(registo) -> dict:
    """Achata um `app.models.Registo` para o formato (já "achatado", sem
    `RNAL_Registo`) que `minimizacao.filtrar_enderecaveis` sabe ler."""
    return {
        "NrRegisto": registo.nr_registo,
        "NIF": registo.nif,
        "Nome": registo.titular_nome,
        "Email": registo.email,
        "Concelho": registo.concelho,
    }


def _nifs_ja_propostos(session) -> frozenset[str]:
    """NIFs com `proposta_parceria` já na fila, em QUALQUER estado (regra 3
    do plano E3 — um titular = um contacto).

    Decisão de implementação: em vez de um JOIN SQL com `json_extract` sobre
    `eventos_agente.payload` (frágil — depende do dialeto SQLite/Postgres e
    da forma como o payload foi serializado), carregam-se os `RevisaoItem`
    do tipo `proposta_parceria` (poucas dezenas esperadas — piloto GTM de
    3-5 parceiros/semana) e os `EventoAgente` que eles referenciam, e
    cruza-se em Python. Mais simples, robusto e portátil entre backends —
    o volume nunca justifica a fragilidade do JSON path no SQL.
    """
    import app.models_swarm as ms

    ref_ids: set[int] = set()
    for (ref_id,) in (
        session.query(ms.RevisaoItem.ref_id)
        .filter(ms.RevisaoItem.tipo == "proposta_parceria",
                ms.RevisaoItem.ref_tipo == "evento_agente")
    ):
        if ref_id is not None and str(ref_id).isdigit():
            ref_ids.add(int(ref_id))
    if not ref_ids:
        return frozenset()

    nifs: set[str] = set()
    for (payload,) in (
        session.query(ms.EventoAgente.payload)
        .filter(ms.EventoAgente.id.in_(ref_ids))
    ):
        if isinstance(payload, dict):
            nif = payload.get("nif")
            if isinstance(nif, str) and nif:
                nifs.add(nif)
    return frozenset(nifs)


def detetar_candidatos(
    session,
    *,
    limiar: int = 5,
    max_candidatos: int = 10,
    lista_dgc: Iterable[str] = (),
    log_optout: Iterable[str] = (),
) -> list[dict]:
    """Deteta candidatos a parceiro (ver docstring do módulo). Read-only.

    Devolve uma lista de dicts JSON-serializáveis, ordenada por `n_registos`
    desc e cortada a `max_candidatos`. Cada dict tem os campos do
    `ContactoEnderecavel` (nif, nome_coletiva, email_generico, concelho,
    proveniencia) mais os agregados não-pessoais (n_registos, concelhos,
    modalidades, total_camas). Nunca um único campo de pessoa singular.
    """
    import app.models as models

    nifs_excluidos = _nifs_ja_propostos(session)
    linhas = session.execute(_SQL_PREFILTRO, {"limiar": limiar}).fetchall()

    candidatos: list[dict] = []
    for (nif_bruto,) in linhas:
        nif = (nif_bruto or "").strip()
        # Autoridade — NUNCA `titular_tipo` (RATIONALE.md §3; ~695 divergem
        # na BD real). Reforçado mesmo sendo o SQL já um filtro por prefixo:
        # apanha whitespace Unicode/edge-cases que `trim()` do SQLite ignora.
        if not e_enderecavel(nif):
            continue
        if nif in nifs_excluidos:  # regra 3 — dedupe (qualquer estado)
            continue

        grupo = (
            session.query(models.Registo)
            .filter(models.Registo.nif == nif_bruto,
                    models.Registo.desaparecido_em.is_(None))
            .all()
        )
        if not grupo:
            continue

        emails_genericos = [r.email for r in grupo if e_generico(r.email or "")]
        if not emails_genericos:
            continue  # nenhum email de negócio no grupo — não endereçável
        email_canonico = collections.Counter(emails_genericos).most_common(1)[0][0]
        registo_ref = next(
            (r for r in grupo if r.email == email_canonico), grupo[0]
        )

        # O MESMO portão do cold — nunca um caminho alternativo de decisão.
        contacto = next(
            iter(minimizacao.filtrar_enderecaveis([_registo_para_dict(registo_ref)])),
            None,
        )
        if contacto is None:
            continue  # o portão canónico recusou — a decisão não se questiona

        contacto = next(
            iter(optout.filtrar_optout(
                [contacto], lista_dgc=lista_dgc, log_optout=log_optout,
            )),
            None,
        )
        if contacto is None:
            continue  # oposição DGC ou opt-out interno

        candidatos.append({
            "nif": contacto.nif,
            "nome_coletiva": contacto.nome_coletiva,
            "email_generico": contacto.email_generico,
            "concelho": contacto.concelho,
            "proveniencia": contacto.proveniencia,
            "n_registos": len(grupo),
            "concelhos": sorted({r.concelho for r in grupo if r.concelho}),
            "modalidades": sorted({r.modalidade for r in grupo if r.modalidade}),
            "total_camas": sum(r.nr_camas or 0 for r in grupo),
        })

    candidatos.sort(key=lambda c: c["n_registos"], reverse=True)
    return candidatos[:max_candidatos]
