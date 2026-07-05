"""Filtro de local-part: distingue email GENÉRICO de empresa (endereçável por
email frio B2B) de email PESSOAL ou desconhecido (não endereçável).

Ver RATIONALE.md §3 (`email.py`). Regra fechada:

  - Só `generico` é endereçável. Viés CONSERVADOR: na dúvida -> `outro`.
  - Genérico = a local-part É um token de negócio da whitelist, sozinho OU com
    sufixo numérico/geográfico separado (reservas, reservasfaro, info2,
    geral.lisboa, reservas-lagos).
  - O DOMÍNIO não decide — decide a local-part: reservas@gmail.com -> genérico;
    joao.silva@gmail.com -> pessoal.
  - Heurística por token e por separador+dígito, NUNCA `startswith` cru sobre
    letras: "geraldine" contém "geral" mas NÃO é genérico. Um prefixo-token só
    é aceite sem separador se o resto for dígitos ou um sufixo geográfico
    reconhecido.

Funções puras, sem estado, sem I/O. stdlib apenas.
"""
from __future__ import annotations

import re

# Tokens de negócio: uma local-part que se reduz a um destes é genérica.
_TOKENS_NEGOCIO: frozenset[str] = frozenset(
    {
        "geral",
        "info",
        "informacoes",
        "reservas",
        "reserva",
        "booking",
        "contacto",
        "contactos",
        "apoio",
        "suporte",
        "alojamento",
        "apartamentos",
        "apartments",
        "turismo",
        "rececao",
        "recepcao",
        "faturacao",
        "comercial",
        "gestao",
        "hello",
        "ola",
        "stay",
        "rooms",
        "welcome",
    }
)

# Sufixos geográficos aceites a colar a um token sem separador (reservasfaro) ou
# como segmentos seguintes (geral.lisboa). Lista modesta e conservadora — só
# lugares; nunca colide com os "restos" dos traps (dine, rmal, do, sec, ...).
_SUFIXOS_GEO: frozenset[str] = frozenset(
    {
        "faro",
        "lisboa",
        "porto",
        "lagos",
        "algarve",
        "cascais",
        "sintra",
        "braga",
        "coimbra",
        "aveiro",
        "evora",
        "funchal",
        "madeira",
        "acores",
        "azores",
        "guimaraes",
        "nazare",
        "ericeira",
        "albufeira",
        "portimao",
        "tavira",
        "sagres",
        "setubal",
        "obidos",
        "douro",
        "gaia",
        "matosinhos",
        "oeiras",
        "estoril",
        "norte",
        "sul",
        "centro",
    }
)

# Separadores estruturais dentro da local-part.
_SEPARADORES = re.compile(r"[._\-+]+")
_SEP_CHARS = "._-+"
_SEP_CONSECUTIVOS = re.compile(r"[._+\-]{2,}")
_DIGITOS = "0123456789"


def _normalizar(email: str) -> str:
    return (email or "").strip().lower()


def _valido(email: str) -> bool:
    """Estrutura mínima de um email: um `@`, local e domínio não vazios, domínio
    com `.` e labels não vazios, sem espaços internos."""
    if not email or any(c.isspace() for c in email):
        return False
    if email.count("@") != 1:
        return False
    local, dominio = email.split("@")
    if not local or not dominio:
        return False
    # Local-part (dot-atom, RFC 5322): não pode começar/terminar num separador
    # nem ter separadores consecutivos. '.reservas', 'reservas.', 'reservas..faro'
    # são malformados — antes eram silenciosamente aceites e classificados genéricos.
    if local[0] in _SEP_CHARS or local[-1] in _SEP_CHARS:
        return False
    if _SEP_CONSECUTIVOS.search(local):
        return False
    if "." not in dominio:
        return False
    if dominio.startswith(".") or dominio.endswith("."):
        return False
    if any(not label for label in dominio.split(".")):
        return False
    return True


def _reduz_a_token(segmento: str) -> bool:
    """O segmento É um token de negócio, tolerando sufixo numérico colado
    (info2 -> info). NUNCA aceita sufixo de letras aqui (isso é o `startswith`
    cru que gera falsos positivos)."""
    base = segmento.rstrip(_DIGITOS)
    return bool(base) and base in _TOKENS_NEGOCIO


def _token_mais_geo_sem_separador(segmento: str) -> bool:
    """Aceita `token + sufixo geográfico` sem separador (reservasfaro), exigindo
    que o resto seja um lugar reconhecido. Assim geraldine (geral+dine) cai."""
    base = segmento.rstrip(_DIGITOS)
    if not base or base in _TOKENS_NEGOCIO:
        return False  # já tratado por _reduz_a_token
    for token in _TOKENS_NEGOCIO:
        if base.startswith(token) and base != token:
            resto = base[len(token):]
            if resto in _SUFIXOS_GEO:
                return True
    return False


def _sufixo_seguro(segmento: str) -> bool:
    """Segmento pós-primeiro num local separado: só dígitos ou lugar geográfico.
    Letras arbitrárias (info.joao) NÃO passam — viés conservador."""
    return segmento.isdigit() or segmento in _SUFIXOS_GEO


def e_generico(email: str) -> bool:
    """True apenas se a local-part for endereçável (token de negócio)."""
    return classificar_email(email) == "generico"


def _local_e_generica(local: str) -> bool:
    if _SEPARADORES.search(local):
        segmentos = [s for s in _SEPARADORES.split(local) if s]
        if not segmentos:
            return False
        # Primeiro segmento tem de ser um token (tolerando dígitos colados);
        # os restantes só podem ser dígitos ou lugares.
        if not _reduz_a_token(segmentos[0]):
            return False
        return all(_sufixo_seguro(s) for s in segmentos[1:])
    # Segmento único (sem separador).
    return _reduz_a_token(local) or _token_mais_geo_sem_separador(local)


def _local_e_pessoal(local: str) -> bool:
    """Padrão nome.apelido: dois ou mais segmentos, todos só de letras e nenhum
    sendo token de negócio."""
    segmentos = [s for s in _SEPARADORES.split(local) if s]
    if len(segmentos) < 2:
        return False
    if any(_reduz_a_token(s) for s in segmentos):
        return False
    return all(s.isalpha() for s in segmentos)


def classificar_email(email: str) -> str:
    """Classifica em "generico" | "pessoal" | "outro" | "invalido".

    Só "generico" é endereçável. Ordem: validade -> genérico -> pessoal ->
    (por defeito) outro, cumprindo o viés conservador.
    """
    norm = _normalizar(email)
    if not _valido(norm):
        return "invalido"
    local, _dominio = norm.split("@")
    if _local_e_generica(local):
        return "generico"
    if _local_e_pessoal(local):
        return "pessoal"
    return "outro"
