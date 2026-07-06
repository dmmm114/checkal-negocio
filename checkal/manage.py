"""CLI de operação do CheckAL — invocado pelos systemd timers (um job por invocação).

    python manage.py <job>
    jobs: varrimento | dre | dunning | suporte | backup | token

Cada job chama o respetivo cron (`app.crons` / `app.faturacao.cron_toconline`), que já
compõem os seams **live-gated** a partir do ambiente (nada envia/liga sem credenciais) e
correm sob o dead-man switch (`com_healthcheck`). Código de saída ≠ 0 se o job levantar
— o systemd/Healthchecks avisa o dono.
"""
from __future__ import annotations

import sys

import app.config as config


def _varrimento() -> None:
    from app.crons import cron_varrimento

    cron_varrimento(config.concelhos_todos())


def _dre() -> None:
    from app.crons import cron_dre

    cron_dre()


def _dunning() -> None:
    from app.crons import cron_dunning

    cron_dunning()


def _suporte() -> None:
    from app.crons import cron_suporte

    cron_suporte()


def _backup() -> None:
    from app.crons import cron_backup

    cron_backup()


def _token() -> None:
    # Renovação do token OAuth do TOConline (mantém a cadeia viva; ~a cada 3-4h).
    from app.faturacao.cron_toconline import main as token_main

    rc = token_main([])
    if rc:
        raise SystemExit(rc)


_JOBS = {
    "varrimento": _varrimento,  # 2×/semana (seg, qui 03:00)
    "dre": _dre,                # diário (07:00)
    "dunning": _dunning,        # diário (09:00)
    "suporte": _suporte,        # cada 15 min
    "backup": _backup,          # noturno (02:00)
    "token": _token,            # cada ~3h (TOConline OAuth)
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in _JOBS:
        sys.stderr.write("uso: manage.py <%s>\n" % "|".join(_JOBS))
        return 2
    _JOBS[argv[0]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
