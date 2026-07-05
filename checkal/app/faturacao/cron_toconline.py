"""Cron de renovação do token OAuth2 do TOConline (SPEC-TOCONLINE §2.2).

Entrypoint de um **systemd timer** (~a cada 3–4 h) que mantém viva a cadeia de
autenticação server-to-server do TOConline. É preciso porque:

  - o `access_token` dura **~4 h** e o `refresh_token` **~8 h** e **roda** a cada
    renovação (o antigo deixa de servir);
  - a faturação por webhook é **intermitente** — não pode ser o único gatilho de
    renovação: se a automação ficar >8 h sem renovar, a cadeia parte e exige **novo
    consentimento humano no browser** (fluxo `authorization_code`).

:func:`renovar_token` chama :func:`app.faturacao.toconline_oauth.garantir_access_token`
(que devolve o access da cache se ainda válido, ou renova via `refresh_token`, **roda**
o refresh e **persiste** o novo par no armazém) e devolve o :class:`EstadoToken`
resultante. Correndo de ~3–4 h em ~3–4 h, cada tato renova o par bem antes de o refresh
expirar, mantendo a cadeia viva sem intervenção humana.

Se a cadeia já partiu (refresh ausente/expirado), `garantir_access_token` levanta
:class:`BootstrapNecessario` — o cron **propaga** (via :func:`main`, com código de saída
não-zero e mensagem em `stderr`) para o systemd alarmar o dono. Nunca se emite
silenciosamente sem token.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo só cria um
`httpx.Client` real em :func:`main`/quando `cliente_http` não é injetado — e só chega lá
em produção. Nos testes injeta-se `cliente_http` (mock) e `store` (memória/SQLite): nada
toca a rede. As credenciais vêm de :mod:`app.config` (env); sem elas
`garantir_access_token` levanta :class:`CredenciaisEmFalta` antes de qualquer pedido.
"""
from __future__ import annotations

import sys
from datetime import datetime

from app.faturacao.toconline_oauth import (
    ArmazemDB,
    ArmazemToken,
    BootstrapNecessario,
    CredenciaisEmFalta,
    ErroOAuth,
    EstadoToken,
    garantir_access_token,
)

__all__ = ["renovar_token", "main"]


def renovar_token(
    *,
    cliente_http: object | None = None,
    store: ArmazemToken | None = None,
    agora: datetime | None = None,
) -> EstadoToken:
    """Garante um `access_token` válido e persiste o par renovado; devolve o estado.

    Parâmetros
    ----------
    cliente_http:
        Cliente HTTP **injetado** (mock nos testes). Se ``None``, cria-se um
        `httpx.Client` real (só em produção — LIVE-GATED; ver docstring do módulo).
    store:
        Armazém do token. Por omissão o DB-backed :class:`ArmazemDB` (linha única
        `toconline_tokens`), que é o que o cron usa em produção.
    agora:
        Instante de referência (injetável nos testes); por omissão o relógio real.

    Levanta
    -------
    BootstrapNecessario
        Sem refresh_token ou refresh_token expirado — é preciso novo consentimento
        humano no browser (o cron alarma o dono; a faturação pára até isso).
    CredenciaisEmFalta
        Sem `TOCONLINE_OAUTH_URL`/`CLIENT_ID`/`CLIENT_SECRET` quando é preciso a rede.
    """
    if store is None:
        store = ArmazemDB()
    if cliente_http is None:
        cliente_http = _cliente_http()

    # Renova (ou confirma) e persiste no armazém — a rotação do refresh fica gravada.
    garantir_access_token(cliente_http=cliente_http, store=store, agora=agora)
    return store.ler()


def _cliente_http() -> object:
    """Cria o `httpx.Client` real do cron (só produção; import tardio — LIVE-GATED)."""
    import httpx

    return httpx.Client(timeout=30.0)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - entrypoint de systemd
    """Entrypoint do systemd timer: renova o token e devolve um código de saída.

    ``0`` em sucesso. Em falha da cadeia OAuth (refresh expirado → `BootstrapNecessario`)
    ou credenciais em falta, escreve o alarme em `stderr` e devolve ``1`` — o systemd
    marca a unidade como falhada e o dono é notificado para refazer o consentimento.
    """
    try:
        estado = renovar_token()
    except BootstrapNecessario as e:
        print(f"[cron_toconline] BOOTSTRAP NECESSARIO — refazer consentimento OAuth: {e}",
              file=sys.stderr)
        return 1
    except CredenciaisEmFalta as e:
        print(f"[cron_toconline] CREDENCIAIS EM FALTA: {e}", file=sys.stderr)
        return 1
    except ErroOAuth as e:
        print(f"[cron_toconline] FALHA NA RENOVACAO DO TOKEN: {e}", file=sys.stderr)
        return 1

    quando = estado.access_expira_em.isoformat() if estado.access_expira_em else "?"
    print(f"[cron_toconline] OK — access valido ate {quando}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
