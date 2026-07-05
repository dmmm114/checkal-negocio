"""Segmentação de campanhas (FDS 6) — encaminha cada registo pelo canal legal.

Este é o ponto onde um lote bruto do RNAL se reparte pelos canais de prospeção,
com o **núcleo de compliance** (`app.compliance.*`) como ÚNICA autoridade de
elegibilidade. Não há disciplina humana no meio: a lei está no código.

    segmentar(registos) -> Segmentos{cold_email, carta, descartados}

Regras fechadas (SPEC-FDS6.md §segmentacao, RATIONALE.md §1/§3):

  cold_email — canal de email frio B2B. SÓ entra quem passa, CUMULATIVAMENTE:
     1. titular pessoa COLETIVA, NIF 5/6  (`nif.e_enderecavel`)  E
     2. email GENÉRICO da empresa        (`email.e_generico`)   E
     3. NÃO consta da oposição DGC nem do opt-out (`optout.filtrar_optout`).
     Os dois primeiros são aplicados por `minimizacao.filtrar_enderecaveis`, que
     descarta singulares/pessoais de imediato (minimização RGPD — nunca os
     materializa). Cada contacto cold leva `proveniencia` registada (o email
     genérico publicado no RNAL — prova de lookup dirigido, NÃO scraping).

  carta — canal POSTAL (upload manual e-carta). Recebe os NÃO-endereçáveis por
     email: singulares/ENI e coletivas cujo único email publicado é pessoal.
     ⚠️ Nenhum email viaja neste ramo — o `ProspetoCarta` guarda só nº RNAL,
     nome e morada. Materializar o email de um singular recriaria a lista de
     marketing eletrónico proibida (Lei 41/2004; harvesting). A carta viaja por
     morada, não por email.

  descartados — contagem do que não entra em canal nenhum: entradas malformadas,
     coletivas genéricas que se OPUSERAM (respeito ao opt-out em qualquer canal)
     e registos sem nome com que endereçar uma carta.

🚦 Fronteira inviolável: singular/ENI NUNCA vai a cold, ainda que o email seja
genérico — o portão é o NIF (o email genérico de um singular continua a ser dado
de pessoa singular). Este módulo só CLASSIFICA; o envio é ainda gated a montante
por `config.pode_enviar_frio_global()` (parecer RGPD) no motor.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.compliance import minimizacao, optout
from app.compliance.minimizacao import ContactoEnderecavel
from app.compliance.nif import classificar_nif

__all__ = ["ContactoEnderecavel", "ProspetoCarta", "Segmentos", "segmentar"]

# Proveniência canónica do ramo carta: a morada publicada no RNAL, não scraping.
_PROVENIENCIA_CARTA = "rnal:morada_publicada"


@dataclass(slots=True)
class ProspetoCarta:
    """Dados mínimos para uma carta postal de prospeção (mail-merge).

    Canal POSTAL — por isso **sem email** (e sem NIF): guarda apenas o que o
    envelope e o mail-merge precisam. Assim nenhum email de pessoa singular é
    materializado numa estrutura de saída. `tipo` é só contexto para a copy.
    """

    nr_registo: object
    nome: str
    endereco: str
    cod_postal: str
    localidade: str
    concelho: str
    tipo: str  # "singular" | "coletiva" | "outro" | "invalido" — só p/ contexto
    proveniencia: str = _PROVENIENCIA_CARTA


@dataclass(slots=True)
class Segmentos:
    """Resultado da segmentação de um lote: os três destinos disjuntos."""

    cold_email: list[ContactoEnderecavel]
    carta: list[ProspetoCarta]
    descartados: int


# --- Extração tolerante do registo RNAL (aninhado ou achatado) --------------

def _bloco(registo: Mapping) -> Mapping:
    """Bloco do registo onde vive a morada/concelho (aninhado ou já achatado)."""
    interno = registo.get("RNAL_Registo")
    return interno if isinstance(interno, Mapping) else registo


def _titular(registo: Mapping) -> Mapping:
    """Bloco do titular (aninhado sob TitulardaExploracao ou achatado no topo)."""
    interno = _bloco(registo)
    titular = interno.get("TitulardaExploracao")
    return titular if isinstance(titular, Mapping) else interno


def _campo(fonte: Mapping, *chaves: str) -> str:
    """Primeiro valor não vazio entre as chaves dadas, normalizado a str."""
    for chave in chaves:
        valor = fonte.get(chave)
        if valor is not None and str(valor).strip() != "":
            return str(valor).strip()
    return ""


def _nr_registo(registo: Mapping):
    fonte = _bloco(registo)
    valor = fonte.get("NrRegisto")
    if valor is None:
        valor = fonte.get("NrRegistoAL")
    return valor


# --- Ramo carta -------------------------------------------------------------

def _para_carta(registo: Mapping) -> ProspetoCarta | None:
    """Constrói um `ProspetoCarta` para um registo NÃO-endereçável por email.

    Devolve ``None`` (a contar como descartado) se não houver nome com que
    endereçar a carta — um envelope sem destinatário não se envia. NUNCA copia o
    email para dentro do objeto (canal postal; minimização).
    """
    titular = _titular(registo)
    nome = _campo(titular, "Nome", "NomeTitular", "Denominacao")
    if not nome:
        return None

    bloco = _bloco(registo)
    nif = _campo(titular, "Contribuinte", "NIF", "NIFTitular")
    return ProspetoCarta(
        nr_registo=_nr_registo(registo),
        nome=nome,
        endereco=_campo(bloco, "Endereco", "Morada", "Rua"),
        cod_postal=_campo(bloco, "CodPostal", "CodigoPostal", "CodPostalTitular"),
        localidade=_campo(bloco, "Localidade"),
        concelho=_campo(bloco, "Concelho"),
        tipo=classificar_nif(nif),
    )


# --- Segmentador ------------------------------------------------------------

def segmentar(
    registos: Iterable[dict],
    *,
    lista_dgc: Iterable[str] = (),
    log_optout: Iterable[str] = (),
) -> Segmentos:
    """Reparte um lote misto do RNAL pelos canais legais de prospeção.

    Passagem única sobre o lote. Para cada registo aplica o núcleo de compliance
    do ramo cold — `minimizacao.filtrar_enderecaveis` (coletiva 5/6 + genérico) —
    e, se passar, torna-o candidato cold; caso contrário tenta o canal postal via
    `_para_carta`. No fim, o ramo cold é cruzado UMA vez com a oposição DGC + o
    opt-out interno (`optout.filtrar_optout`) — os excluídos aí contam como
    descartados (opuseram-se; não se contactam por nenhum canal).

    `lista_dgc`/`log_optout` são injetados (a fonte real liga-se no motor); vazios
    por omissão. Este módulo só CLASSIFICA — não envia. O envio a frio permanece
    gated a montante por `config.pode_enviar_frio_global()` (parecer RGPD).
    """
    cold_candidatos: list[ContactoEnderecavel] = []
    carta: list[ProspetoCarta] = []
    descartados = 0

    for registo in registos:
        # Entrada malformada (None, str, lista, …): descarta e continua o lote.
        if not isinstance(registo, Mapping):
            descartados += 1
            continue

        # Ramo cold — autoridade única do núcleo: coletiva 5/6 + email genérico.
        # `filtrar_enderecaveis` sobre 1 registo cede 0 ou 1 contacto minimizado;
        # singulares/pessoais são descartados de imediato lá dentro (RGPD).
        contacto = next(iter(minimizacao.filtrar_enderecaveis([registo])), None)
        if contacto is not None:
            cold_candidatos.append(contacto)
            continue

        # Não endereçável por email frio -> canal postal (carta), NUNCA cold.
        prospeto = _para_carta(registo)
        if prospeto is None:
            descartados += 1
        else:
            carta.append(prospeto)

    # Último filtro do ramo cold: oposição DGC + opt-out (Lei 41/2004, art. 13.º-B).
    # Feito em lote (normaliza as listas UMA vez). Os excluídos saem do cold e
    # contam como descartados — não recaem na carta.
    cold_email = list(
        optout.filtrar_optout(cold_candidatos, lista_dgc=lista_dgc, log_optout=log_optout)
    )
    descartados += len(cold_candidatos) - len(cold_email)

    return Segmentos(cold_email=cold_email, carta=carta, descartados=descartados)
