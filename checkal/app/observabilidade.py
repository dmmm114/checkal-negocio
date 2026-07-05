"""Dead-man switch dos crons: ping ao Healthchecks.io no fim de cada job (FDS 5).

Fronteira do módulo (SPEC-FDS5.md §observabilidade + AUTOMACAO.md §6): cada cron
(varrimento RNAL, DRE diário, dunning, suporte, backup) envolve-se em
:class:`com_healthcheck` — usável como **contexto** ou como **decorator** — que faz
um ping ao Healthchecks.io *quando o job termina*:

    - o cron **completa** sem exceção  → ping de **sucesso** (`{base}/{key}/{slug}`);
    - o cron **levanta**               → ping de **falha** (`.../{slug}/fail`) e a
      exceção **propaga** intacta (o wrapper nunca a suprime);
    - opcional `pingar_inicio=True`     → ping de **início** (`.../{slug}/start`) à
      entrada, para o Healthchecks medir a duração do job.

Um cron que não corre (VPS em baixo, cron partido) simplesmente **não pinga** — e é
essa ausência de ping dentro do período esperado que o Healthchecks.io converte em
alerta (email + Telegram ao dono, AUTOMACAO.md §6). Daí "dead-man switch": o silêncio
é o sinal.

Modelo de ping do Healthchecks.io (ver `config.HEALTHCHECKS_*`):
    GET {HEALTHCHECKS_BASE_URL}/{HEALTHCHECKS_PING_KEY}/{slug}[/fail|/start]

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.**
  - O `cliente_http` (à laia de `httpx.Client`, com `.get(url) -> resposta`) é
    **injetado** por quem chama; nos testes é um dublê, logo correr os testes nunca
    toca a rede. Sem injeção **e** com o gate ligado (`config.healthchecks_ativo()`,
    i.e. há ping key), compõe-se um `httpx.Client` real via :func:`_novo_cliente` — o
    **único** ponto que cria rede. Sem key e sem injeção → **no-op** (nada pinga).
  - A observabilidade **nunca quebra nem mascara o cron**: qualquer falha do próprio
    ping (rede/timeout) é engolida. No ramo de exceção, engolir o erro do ping é o que
    garante que a exceção ORIGINAL do cron é a que propaga — nunca a da rede de
    monitorização.

Fora de âmbito (SPEC-FDS5 §fora de âmbito): o agendamento dos crons e a configuração
das checks no Healthchecks.io (é infraestrutura, não código); a escalação em si
(Telegram) é do lado do Healthchecks para o dead-man, e de `app.suporte`/breaker para
as escalações de conteúdo.
"""
from __future__ import annotations

import functools
from typing import Any

import app.config as config

__all__ = [
    "com_healthcheck",
    "url_ping",
    "SUCESSO",
    "FALHA",
    "INICIO",
]

# Sufixos do endpoint de ping do Healthchecks.io. Sucesso é o caminho "nu" (sem
# sufixo); `/fail` e `/start` são os documentados para falha e início do job.
SUCESSO = ""
FALHA = "fail"
INICIO = "start"


def url_ping(slug: str, sufixo: str = SUCESSO) -> str:
    """Compõe a URL de ping para `slug` (puro, testável sem rede).

    `{HEALTHCHECKS_BASE_URL}/{HEALTHCHECKS_PING_KEY}/{slug}[/{sufixo}]`, lido de
    `config` no momento da chamada (respeita monkeypatch nos testes). Uma barra final
    na base é normalizada e partes vazias (ex.: ping key ausente) são omitidas, para
    nunca sair uma URL com `//`.
    """
    partes = [
        config.HEALTHCHECKS_BASE_URL.rstrip("/"),
        config.HEALTHCHECKS_PING_KEY,
        slug,
        sufixo,
    ]
    return "/".join(p for p in partes if p)


def _novo_cliente() -> Any:
    """Compõe um `httpx.Client` para os pings (o único ponto que cria rede real).

    Import tardio (à imagem de :func:`app.envio.obter_enviador`): o `httpx` só é
    importado quando de facto se vai pingar em produção. Só é chamado quando o gate
    está ligado e não há cliente injetado.
    """
    import httpx  # import tardio: só quando se liga em produção

    return httpx.Client(timeout=config.HEALTHCHECKS_TIMEOUT_S)


class com_healthcheck:
    """Dead-man switch de um cron — contexto **e** decorator (SPEC-FDS5 §observabilidade).

    Uso como contexto::

        with com_healthcheck("varrimento", cliente_http=cli):
            correr_varrimento()

    Uso como decorator::

        @com_healthcheck("varrimento")
        def cron_varrimento():
            ...

    Em ambos: fim sem exceção → ping de sucesso; exceção → ping `/fail` **e a exceção
    propaga**. `pingar_inicio=True` acrescenta um ping `/start` à entrada.

    Parâmetros
    ----------
    slug:
        Identificador da check no Healthchecks.io (ex.: `"varrimento"`, `"dre"`,
        `"dunning"`, `"suporte"`, `"backup"`).
    cliente_http:
        Cliente HTTP **injetado** (dublê nos testes; nunca criado aqui). Se `None`,
        e o gate estiver ligado, compõe-se um real por ping via :func:`_novo_cliente`;
        se o gate estiver desligado (sem ping key), não se pinga (LIVE-GATED).
    pingar_inicio:
        Se `True`, pinga `/start` à entrada (Healthchecks mede a duração do job).
    """

    def __init__(
        self,
        slug: str,
        *,
        cliente_http: Any | None = None,
        pingar_inicio: bool = False,
    ) -> None:
        self._slug = slug
        self._cliente_http = cliente_http
        self._pingar_inicio = pingar_inicio

    # -- gate + envio do ping (best-effort: nunca levanta) --
    def _deve_pingar(self) -> bool:
        """Pinga se há cliente injetado (testes/wire) OU o gate está ligado (há key)."""
        return self._cliente_http is not None or config.healthchecks_ativo()

    def _ping(self, sufixo: str) -> None:
        """Faz um ping best-effort; engole qualquer falha (observabilidade nunca quebra).

        Engolir a falha é deliberado: no ramo de exceção do cron é o que impede que um
        erro de rede do ping mascare a exceção ORIGINAL que está a propagar.
        """
        if not self._deve_pingar():
            return
        url = url_ping(self._slug, sufixo)
        try:
            if self._cliente_http is not None:
                self._cliente_http.get(url)
            else:
                with _novo_cliente() as cliente:  # fecha o cliente após o ping
                    cliente.get(url)
        except Exception:
            # Rede/timeout do próprio ping — irrelevante para o resultado do cron.
            pass

    # -- protocolo de contexto --
    def __enter__(self) -> com_healthcheck:
        if self._pingar_inicio:
            self._ping(INICIO)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self._ping(FALHA if exc_type is not None else SUCESSO)
        return False  # nunca suprime a exceção — o cron falhado tem de propagar

    # -- protocolo de decorator (reutilizável em chamadas repetidas: sem estado a vazar) --
    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return wrapper
