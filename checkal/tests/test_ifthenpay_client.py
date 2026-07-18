"""Adaptador IfThenPay — app.faturacao.ifthenpay_client (Fase G, LIVE-GATED).

Regras provadas:
  - SEM chaves (`IFTHENPAY_*` vazias, o default) e sem cliente injetado, as
    funções devolvem ``None`` e NUNCA tocam a rede (padrão do resto da app);
  - com `cliente_http` FAKE injetado, `gerar_referencia_mb`/`iniciar_mbway`
    chamam os endpoints certos com a chave certa e devolvem o dict normalizado;
  - `verificar_callback` valida a anti-phishing key OBRIGATORIAMENTE:
    chave certa ⇒ ok; chave errada OU nenhuma chave configurada ⇒ recusa
    (fail-closed — sem chave configurada, nenhum callback é aceite).

Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest

import app.config as config
from app.faturacao import ifthenpay_client as itp


class _RespostaFake:
    def __init__(self, dados: dict, status_code: int = 200) -> None:
        self._dados = dados
        self.status_code = status_code

    def json(self) -> dict:
        return self._dados

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _ClienteFake:
    def __init__(self, resposta: dict) -> None:
        self.resposta = resposta
        self.chamadas: list[tuple[str, dict]] = []

    def post(self, url: str, *, json: dict | None = None, **kw) -> _RespostaFake:
        self.chamadas.append((url, json or {}))
        return _RespostaFake(self.resposta)


# ==========================================================================
#  LIVE-GATED — sem chaves, nada toca a rede
# ==========================================================================
def test_sem_chaves_gerar_referencia_devolve_none():
    assert config.IFTHENPAY_MB_KEY == ""          # default do repo
    assert itp.gerar_referencia_mb("CKL-1", 49.0) is None


def test_sem_chaves_mbway_devolve_none():
    assert itp.iniciar_mbway("CKL-1", 49.0, "912345678") is None


def test_ifthenpay_ativo_reflete_chaves(monkeypatch):
    assert itp.ifthenpay_ativo() is False
    monkeypatch.setattr(config, "IFTHENPAY_MB_KEY", "MB-XXX")
    assert itp.ifthenpay_ativo() is True


# ==========================================================================
#  Com cliente fake — geração ao vivo (Opção A da ADENDA)
# ==========================================================================
def test_gerar_referencia_mb_com_cliente_fake(monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_MB_KEY", "MB-XXX")
    fake = _ClienteFake({"Entity": "11249", "Reference": "123 456 789",
                         "Amount": "49.00", "OrderId": "CKL-1", "Status": "0"})
    r = itp.gerar_referencia_mb("CKL-1", 49.0, validade_dias=3, cliente_http=fake)
    assert r == {"entidade": "11249", "referencia": "123 456 789", "valor": "49.00"}
    url, corpo = fake.chamadas[0]
    assert "multibanco" in url
    assert corpo["mbKey"] == "MB-XXX"
    assert corpo["orderId"] == "CKL-1"


def test_iniciar_mbway_com_cliente_fake(monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_MBWAY_KEY", "MBW-YYY")
    fake = _ClienteFake({"RequestId": "req-9", "Status": "000",
                         "Message": "Pending"})
    r = itp.iniciar_mbway("CKL-2", 119.0, "912345678", cliente_http=fake)
    assert r == {"id_pedido": "req-9", "estado": "000"}
    url, corpo = fake.chamadas[0]
    assert "mbway" in url
    assert corpo["mbWayKey"] == "MBW-YYY"
    assert corpo["mobileNumber"] == "912345678"


# ==========================================================================
#  Anti-phishing — obrigatória, fail-closed
# ==========================================================================
def test_callback_sem_chave_configurada_recusa_tudo():
    assert config.IFTHENPAY_ANTIPHISHING_KEY == ""   # default
    r = itp.verificar_callback({"key": "qualquer", "orderId": "CKL-1", "amount": "49.00"})
    assert r["ok"] is False


def test_callback_chave_errada_recusa(monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")
    r = itp.verificar_callback({"key": "ANTI-ERRADA", "orderId": "CKL-1", "amount": "49.00"})
    assert r["ok"] is False


def test_callback_chave_certa_normaliza(monkeypatch):
    monkeypatch.setattr(config, "IFTHENPAY_ANTIPHISHING_KEY", "ANTI-1")
    r = itp.verificar_callback({"key": "ANTI-1", "orderId": "CKL-1", "amount": "49.00"})
    assert r["ok"] is True
    assert r["order_id"] == "CKL-1"
    assert r["valor_cent"] == 4900
