"""Descarte imediato — minimização RGPD (ver RATIONALE.md §3).

Ponto único onde um lote bruto do RNAL se transforma na fatia estritamente
endereçável. A regra é **cumulativa** e o descarte é **imediato**:

    endereçável  ⇔  titular coletiva (NIF 5/6)  E  email genérico

Tudo o que não passa é descartado *no momento em que é visto* — nunca é
acumulado numa lista de "rejeitados para depois", nunca é persistido. O objeto
de saída (`ContactoEnderecavel`) guarda o **mínimo** e, por construção, **nunca**
transporta dados de pessoa singular: só se materializa quando o NIF já foi
classificado como coletivo.

Depende de:
  - `app.compliance.nif.e_enderecavel`   — portão do titular (coletiva 5/6)
  - `app.compliance.email.e_generico`    — portão do local-part (genérico)

Os imports das dependências são feitos **preguiçosamente**, dentro do gerador:
o módulo carrega mesmo que `nif`/`email` ainda estejam em construção, e a
resolução acontece só quando o fluxo é efetivamente consumido.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

# Proveniência canónica: a única base legal do canal frio é o email genérico
# de pessoa coletiva publicado no RNAL (RATIONALE.md §1).
_PROVENIENCIA_PADRAO = "rnal:email_generico_publicado"


@dataclass(slots=True)
class ContactoEnderecavel:
    """Dados mínimos de um contacto endereçável por email frio B2B.

    Só campos de pessoa COLETIVA. Sem `Tipo`, sem nome de titular singular,
    sem qualquer campo capaz de carregar dados de pessoa singular.
    """

    nr_registo: object
    nif: str
    nome_coletiva: str
    email_generico: str
    concelho: str
    proveniencia: str = _PROVENIENCIA_PADRAO


# --- Extração tolerante do registo RNAL ------------------------------------

def _titular(registo: Mapping) -> Mapping:
    """Devolve o bloco do titular, aceitando aninhado ou já achatado."""
    interno = registo.get("RNAL_Registo")
    if isinstance(interno, Mapping):
        titular = interno.get("TitulardaExploracao")
        if isinstance(titular, Mapping):
            return titular
        return interno
    return registo


def _campo(fonte: Mapping, *chaves: str) -> str:
    """Primeiro valor não vazio entre as chaves dadas, normalizado a str."""
    for chave in chaves:
        valor = fonte.get(chave)
        if valor is not None and str(valor).strip() != "":
            return str(valor).strip()
    return ""


def _nr_registo(registo: Mapping):
    interno = registo.get("RNAL_Registo")
    fonte = interno if isinstance(interno, Mapping) else registo
    valor = fonte.get("NrRegisto")
    if valor is None:
        valor = fonte.get("NrRegistoAL")
    return valor


# --- Filtro principal -------------------------------------------------------

def filtrar_enderecaveis(registos: Iterable[dict]) -> Iterator[ContactoEnderecavel]:
    """Gerador: produz **apenas** os contactos endereçáveis do lote.

    Para cada registo, aplica em fluxo os dois portões (NIF coletivo E email
    genérico). Quem passa é convertido em `ContactoEnderecavel` e cedido de
    imediato; quem falha é descartado no ato — sem acumulação, sem persistência.

    É um gerador: nada é lido do `registos` antes de o consumidor pedir, e os
    rejeitados nunca chegam a formar coleção nenhuma. Entradas malformadas
    (não-`Mapping`: None, str, lista) são descartadas no ato, sem derrubar o lote.

    ⚠️ A saída NÃO é enviável tal como está. Estes contactos ainda TÊM de passar
    por `app.compliance.optout.filtrar_optout` (cruzamento oposição DGC + opt-out)
    antes de qualquer envio — contactar quem se opôs viola o regime opt-out
    (Lei 41/2004, art. 13.º-B; ANACOM). Ordem canónica do pipeline:
        filtrar_enderecaveis  ->  optout.filtrar_optout  ->  envio.
    """
    # Import preguiçoso: tolera dependências ainda em construção e permite que
    # os testes injetem `nif`/`email` falsos antes do primeiro `next()`.
    from app.compliance.email import e_generico
    from app.compliance.nif import e_enderecavel

    for registo in registos:
        # Entrada malformada (None, str, lista, …): descarta já, não derruba o
        # resto do lote (JSON real do RNAL pode trazer uma entrada estragada).
        if not isinstance(registo, Mapping):
            continue

        titular = _titular(registo)
        nif = _campo(titular, "Contribuinte", "NIF", "NIFTitular")

        # Portão 1 — titular pessoa coletiva (NIF 5/6). Falha => descarta já.
        if not e_enderecavel(nif):
            continue

        email = _campo(titular, "Email", "EmailTitular")

        # Portão 2 — email genérico da empresa. Falha => descarta já.
        if not e_generico(email):
            continue

        # Só aqui — NIF coletivo confirmado — se materializa o objeto.
        yield ContactoEnderecavel(
            nr_registo=_nr_registo(registo),
            nif=nif,
            nome_coletiva=_campo(titular, "Nome", "NomeTitular", "Denominacao"),
            email_generico=email,
            concelho=_campo(_titular_concelho(registo), "Concelho"),
        )


def _titular_concelho(registo: Mapping) -> Mapping:
    """O concelho vive no registo (aninhado ou achatado), não no titular."""
    interno = registo.get("RNAL_Registo")
    return interno if isinstance(interno, Mapping) else registo
