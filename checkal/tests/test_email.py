"""Testes do filtro de local-part (genérico vs pessoal) — app.compliance.email.

Regra canónica (ver app/compliance/RATIONALE.md §3, `email.py`):
  - Só `generico` é endereçável por email frio B2B.
  - Genérico = local-part que É um token de negócio da whitelist, sozinho OU com
    sufixo numérico/geográfico *separado* (reservas, reservasfaro, info2,
    geral.lisboa, reservas-lagos).
  - O domínio NÃO decide (decide o local-part): reservas@gmail.com -> genérico.
  - Viés CONSERVADOR: na dúvida -> `outro` (não endereçável).
  - Heurística por token/separador+dígito, NUNCA `startswith` cru sobre letras
    (senão geraldine@ passaria por conter "geral").
"""
from __future__ import annotations

import pytest

from app.compliance.email import classificar_email, e_generico


# ---------------------------------------------------------------------------
# Genéricos (endereçáveis) — token da whitelist sozinho
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "geral@quinta.pt",
        "info@casadapraia.pt",
        "informacoes@hotel.pt",
        "reservas@apartamentos.pt",
        "reserva@villa.pt",
        "booking@stay.pt",
        "contacto@al.pt",
        "contactos@al.pt",
        "apoio@turismo.pt",
        "suporte@empresa.pt",
        "alojamento@centro.pt",
        "apartamentos@lagos.pt",
        "apartments@algarve.pt",
        "turismo@regiao.pt",
        "rececao@hotel.pt",
        "recepcao@hotel.pt",
        "faturacao@empresa.pt",
        "comercial@empresa.pt",
        "gestao@empresa.pt",
        "hello@stay.pt",
        "ola@casa.pt",
        "stay@lisboa.pt",
        "rooms@porto.pt",
        "welcome@quinta.pt",
    ],
)
def test_token_de_negocio_sozinho_e_generico(email: str) -> None:
    assert e_generico(email) is True
    assert classificar_email(email) == "generico"


# ---------------------------------------------------------------------------
# Genéricos com sufixo numérico ou geográfico (com e sem separador)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "reservasfaro@x.pt",     # token + sufixo geográfico, sem separador
        "info2@x.pt",            # token + sufixo numérico, sem separador
        "reservas2024@x.pt",     # token + ano
        "geral.lisboa@x.pt",     # token + separador + geográfico
        "reservas-lagos@x.pt",   # token + separador + geográfico
        "info-2@x.pt",           # token + separador + numérico
        "reservas.faro@x.pt",    # equivalente separado de reservasfaro
    ],
)
def test_token_com_sufixo_numerico_ou_geografico_e_generico(email: str) -> None:
    assert e_generico(email) is True
    assert classificar_email(email) == "generico"


# ---------------------------------------------------------------------------
# O domínio NÃO decide — free-provider não altera a classificação
# ---------------------------------------------------------------------------
def test_generico_em_free_provider_continua_generico() -> None:
    assert classificar_email("reservas@gmail.com") == "generico"
    assert e_generico("reservas@gmail.com") is True


def test_pessoal_em_free_provider_continua_pessoal() -> None:
    assert classificar_email("joao.silva@gmail.com") == "pessoal"
    assert e_generico("joao.silva@gmail.com") is False


# ---------------------------------------------------------------------------
# Pessoais — padrão nome.apelido (não endereçável)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "joao.silva@empresa.pt",
        "maria-costa@empresa.pt",
        "ana.pereira@gmail.com",
        "pedro_santos@x.pt",
    ],
)
def test_nome_apelido_e_pessoal(email: str) -> None:
    assert classificar_email(email) == "pessoal"
    assert e_generico(email) is False


# ---------------------------------------------------------------------------
# TRAPS — falsos positivos que DEVEM ser rejeitados (não-genéricos)
# Um teste por trap, com o motivo do risco.
# ---------------------------------------------------------------------------
def test_trap_geraldine_contem_geral_mas_nao_e_generico() -> None:
    # "geraldine" começa por "geral" — startswith cru daria falso positivo.
    assert e_generico("geraldine@x.pt") is False
    assert classificar_email("geraldine@x.pt") != "generico"


def test_trap_casanova_contem_casa_mas_nao_e_generico() -> None:
    assert e_generico("casanova@x.pt") is False
    assert classificar_email("casanova@x.pt") != "generico"


def test_trap_informal_contem_info_mas_nao_e_generico() -> None:
    # "informal" começa por "info" — o resto ("rmal") não é geográfico/numérico.
    assert e_generico("informal@x.pt") is False
    assert classificar_email("informal@x.pt") != "generico"


def test_trap_infante_nao_e_generico() -> None:
    assert e_generico("infante@x.pt") is False
    assert classificar_email("infante@x.pt") != "generico"


def test_trap_marketingjoao_nao_e_generico() -> None:
    assert e_generico("marketingjoao@x.pt") is False
    assert classificar_email("marketingjoao@x.pt") != "generico"


def test_trap_reservado_contem_reserva_mas_nao_e_generico() -> None:
    # "reservado" começa por "reserva"; resto ("do") não é geográfico/numérico.
    assert e_generico("reservado@x.pt") is False


def test_trap_infosec_contem_info_mas_nao_e_generico() -> None:
    assert e_generico("infosec@x.pt") is False


# ---------------------------------------------------------------------------
# Inválidos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "",                    # vazio
        "reservas",            # sem @
        "reservas@semponto",   # domínio sem "."
        "reservas@.pt",        # domínio começa por "."
        "reservas@x.",         # domínio acaba em "."
        "@x.pt",               # local vazio
        "reservas@@x.pt",      # dois @
        "res ervas@x.pt",      # espaço interno
        "reservas@x..pt",      # label vazio no domínio
        ".reservas@x.pt",      # separador no início da local-part
        "reservas.@x.pt",      # separador no fim da local-part
        "reservas..faro@x.pt", # separadores consecutivos na local-part
        "..reservas@x.pt",     # dois separadores no início
        "-info@x.pt",          # hífen inicial
    ],
)
def test_invalidos(email: str) -> None:
    assert classificar_email(email) == "invalido"
    assert e_generico(email) is False


# ---------------------------------------------------------------------------
# Regressão (sweep [baixo]): guarda anti-regressão dos sufixos geográficos.
# Nomes próprios/apelidos PT que começam por um token de negócio NÃO podem
# tornar-se genéricos se um dia se editar _SUFIXOS_GEO. Trava a superfície de
# regressão mais provável do módulo (token+geo sem separador).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "geraldine@x.pt",   # geral+dine
        "geraldo@x.pt",     # geral+do
        "informal@x.pt",    # info+rmal
        "infante@x.pt",     # info+ante
        "infosec@x.pt",     # info+sec
        "reservado@x.pt",   # reserva+do
        "olavo@x.pt",       # ola+vo
        "olaria@x.pt",      # ola+ria
        "staygnant@x.pt",   # stay+gnant
        "casanova@x.pt",    # nome comum
        "gestor@x.pt",      # não começa por 'gestao' — guarda extra
    ],
)
def test_guarda_nomes_proprios_nunca_genericos(email: str) -> None:
    assert classificar_email(email) != "generico"


def test_none_e_invalido() -> None:
    assert classificar_email(None) == "invalido"  # type: ignore[arg-type]
    assert e_generico(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Normalização — maiúsculas e espaços à volta não alteram o resultado
# ---------------------------------------------------------------------------
def test_normaliza_maiusculas_e_espacos() -> None:
    assert classificar_email("  RESERVAS@Quinta.PT  ") == "generico"
    assert classificar_email("Joao.Silva@Empresa.PT") == "pessoal"


# ---------------------------------------------------------------------------
# Conservador: local-part só de dígitos, ou palavra desconhecida -> não genérico
# ---------------------------------------------------------------------------
def test_local_so_digitos_nao_e_generico() -> None:
    assert e_generico("2024@x.pt") is False


def test_palavra_desconhecida_e_outro() -> None:
    assert classificar_email("quintadosol@x.pt") == "outro"
    assert e_generico("quintadosol@x.pt") is False
