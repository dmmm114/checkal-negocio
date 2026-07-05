"""Testes do cliente Stripe — app.billing.stripe_client.

Contrato (SPEC-FDS2.md §stripe_client · SPEC-STRIPE.md §2.4):
  - `verificar_evento(payload_bruto: bytes, sig_header, *, segredo) -> dict`:
    valida a assinatura do webhook Stripe (esquema `t=,v1=`) com HMAC-SHA256
    NATIVO (stdlib hmac/hashlib) sobre o CORPO BRUTO (bytes), com tolerância de
    5 min; devolve o evento (dict). Assinatura em falta/inválida/fora de
    tolerância → `AssinaturaInvalida`.
  - `plano_de_price(price_id) -> str | None`: mapeia um Price da Stripe para o
    código de plano interno via `config.STRIPE_PRICE_PLANO`.

Disciplina: ZERO rede. A assinatura válida é gerada AQUI nos testes com o mesmo
segredo de teste, com o mesmo HMAC nativo — nunca com o SDK da Stripe.

Escritos ANTES da implementação (TDD). Um teste por propriedade.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

import app.config as config
from app.billing.stripe_client import (
    AssinaturaInvalida,
    plano_de_price,
    verificar_evento,
)

SEGREDO = "whsec_teste_segredo_ABC123"


# --------------------------------------------------------------------------
#  Helpers — geram a assinatura Stripe do lado do TESTE (HMAC-SHA256 nativo)
# --------------------------------------------------------------------------
def _assinar(payload_bruto: bytes, segredo: str, *, t: int | None = None,
             extra_esquemas: str = "") -> str:
    """Constrói um header `Stripe-Signature` (`t=...,v1=...`) para `payload_bruto`.

    Réplica exata do esquema documentado: assina `f"{t}." + corpo_bruto`.
    `extra_esquemas` permite juntar pares adicionais (ex. `v0=...`) para provar
    que são ignorados.
    """
    if t is None:
        t = int(time.time())
    assinado = f"{t}.".encode("utf-8") + payload_bruto
    v1 = hmac.new(segredo.encode("utf-8"), assinado, hashlib.sha256).hexdigest()
    header = f"t={t},v1={v1}"
    if extra_esquemas:
        header = f"{header},{extra_esquemas}"
    return header


def _evento_bytes(tipo: str = "checkout.session.completed", id_: str = "evt_1") -> bytes:
    """Corpo bruto compacto de um evento Stripe (bytes, como chega no request)."""
    return json.dumps(
        {"id": id_, "type": tipo, "data": {"object": {"id": "cs_test_1"}}},
        separators=(",", ":"),
    ).encode("utf-8")


# ==========================================================================
#  verificar_evento — assinatura válida
# ==========================================================================
def test_assinatura_valida_devolve_o_evento_como_dict():
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO)
    evento = verificar_evento(corpo, header, segredo=SEGREDO)
    assert isinstance(evento, dict)
    assert evento["id"] == "evt_1"
    assert evento["type"] == "checkout.session.completed"
    assert evento["data"]["object"]["id"] == "cs_test_1"


def test_esquemas_extra_no_header_sao_ignorados():
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO, extra_esquemas="v0=abc123deadbeef")
    evento = verificar_evento(corpo, header, segredo=SEGREDO)
    assert evento["id"] == "evt_1"


def test_multiplas_v1_uma_valida_e_aceite():
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO)
    # Uma v1 forjada ANTES da verdadeira; basta uma corresponder.
    header_com_ruido = header.replace("v1=", "v1=" + "0" * 64 + ",v1=", 1)
    evento = verificar_evento(corpo, header_com_ruido, segredo=SEGREDO)
    assert evento["type"] == "checkout.session.completed"


def test_espacos_em_torno_dos_pares_sao_tolerados():
    corpo = _evento_bytes()
    t = int(time.time())
    assinado = f"{t}.".encode("utf-8") + corpo
    v1 = hmac.new(SEGREDO.encode(), assinado, hashlib.sha256).hexdigest()
    header = f" t={t} , v1={v1} "
    evento = verificar_evento(corpo, header, segredo=SEGREDO)
    assert evento["id"] == "evt_1"


# ==========================================================================
#  verificar_evento — corpo BRUTO (byte-a-byte)
# ==========================================================================
def test_verificacao_e_sobre_o_corpo_bruto_nao_o_dict_reserializado():
    corpo = _evento_bytes()                       # compacto, sem espaços
    header = _assinar(corpo, SEGREDO)
    # Re-serializar o mesmo objeto com espaçamento diferente muda os bytes →
    # a assinatura (calculada sobre o corpo compacto) já não corresponde.
    corpo_reserializado = json.dumps(json.loads(corpo)).encode("utf-8")
    assert corpo_reserializado != corpo
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo_reserializado, header, segredo=SEGREDO)


def test_corpo_adulterado_apos_assinar_e_rejeitado():
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO)
    adulterado = corpo.replace(b"cs_test_1", b"cs_test_ATACANTE")
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(adulterado, header, segredo=SEGREDO)


# ==========================================================================
#  verificar_evento — assinatura inválida
# ==========================================================================
def test_segredo_errado_rejeita():
    corpo = _evento_bytes()
    header = _assinar(corpo, "whsec_OUTRO_segredo")
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header, segredo=SEGREDO)


def test_v1_corrompida_rejeita():
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO)
    # troca o último hex-dígito da assinatura
    ultimo = header[-1]
    subst = "0" if ultimo != "0" else "1"
    header_mau = header[:-1] + subst
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header_mau, segredo=SEGREDO)


def test_segredo_vazio_rejeita():
    corpo = _evento_bytes()
    header = _assinar(corpo, "")
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header, segredo="")


# ==========================================================================
#  verificar_evento — header malformado
# ==========================================================================
@pytest.mark.parametrize("header", [
    "",                       # vazio
    "v1=deadbeef",            # sem timestamp
    "t=123456",               # sem v1
    "lixo_sem_pares",         # sem `=`
    "t=nao_e_numero,v1=deadbeef",  # timestamp não numérico
])
def test_header_malformado_rejeita(header):
    corpo = _evento_bytes()
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header, segredo=SEGREDO)


def test_header_none_rejeita():
    corpo = _evento_bytes()
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, None, segredo=SEGREDO)  # type: ignore[arg-type]


# ==========================================================================
#  verificar_evento — tolerância temporal (5 min)
# ==========================================================================
def test_timestamp_expirado_rejeita_mesmo_com_assinatura_valida():
    corpo = _evento_bytes()
    velho = int(time.time()) - 600           # 10 min no passado (> 5 min)
    header = _assinar(corpo, SEGREDO, t=velho)  # assinatura VÁLIDA para esse t
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header, segredo=SEGREDO)


def test_timestamp_muito_no_futuro_rejeita():
    corpo = _evento_bytes()
    futuro = int(time.time()) + 600          # 10 min no futuro
    header = _assinar(corpo, SEGREDO, t=futuro)
    with pytest.raises(AssinaturaInvalida):
        verificar_evento(corpo, header, segredo=SEGREDO)


def test_dentro_da_tolerancia_e_aceite():
    corpo = _evento_bytes()
    quase = int(time.time()) - 290           # 4m50s < 5 min
    header = _assinar(corpo, SEGREDO, t=quase)
    evento = verificar_evento(corpo, header, segredo=SEGREDO)
    assert evento["id"] == "evt_1"


# ==========================================================================
#  verificar_evento — segredo por omissão vem de config
# ==========================================================================
def test_segredo_por_omissao_usa_config(monkeypatch):
    # A verificação com o default só funciona se o default resolver para o
    # valor CORRENTE de config.STRIPE_WEBHOOK_SECRET no momento da chamada.
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SEGREDO, raising=False)
    corpo = _evento_bytes()
    header = _assinar(corpo, SEGREDO)
    evento = verificar_evento(corpo, header)   # sem passar `segredo`
    assert evento["id"] == "evt_1"


# ==========================================================================
#  AssinaturaInvalida
# ==========================================================================
def test_assinatura_invalida_e_uma_excecao():
    assert issubclass(AssinaturaInvalida, Exception)


# ==========================================================================
#  plano_de_price
# ==========================================================================
def test_plano_de_price_mapeia_price_conhecido(monkeypatch):
    monkeypatch.setattr(
        config, "STRIPE_PRICE_PLANO",
        {"price_ABC_anual": "anual", "price_XYZ_trienal": "trienal"},
    )
    assert plano_de_price("price_ABC_anual") == "anual"
    assert plano_de_price("price_XYZ_trienal") == "trienal"


def test_plano_de_price_desconhecido_devolve_none(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_PRICE_PLANO", {"price_ABC_anual": "anual"})
    assert plano_de_price("price_inexistente") is None


def test_plano_de_price_le_config_no_momento_da_chamada(monkeypatch):
    # Não deve congelar o mapa na importação: alterar o config afeta a chamada.
    monkeypatch.setattr(config, "STRIPE_PRICE_PLANO", {})
    assert plano_de_price("price_novo") is None
    monkeypatch.setattr(config, "STRIPE_PRICE_PLANO", {"price_novo": "portfolio"})
    assert plano_de_price("price_novo") == "portfolio"
