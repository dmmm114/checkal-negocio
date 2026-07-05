"""Backups noturnos do CheckAL: composição do `pg_dump` + retenção (LIVE-GATED).

O teste das 3 semanas de férias (AUTOMACAO.md §6) exige que a base de dados sobreviva
a uma perda do VPS sem intervenção humana: um `pg_dump` noturno escreve um arquivo
restaurável para o Storage Box da Hetzner e uma política de retenção poda os arquivos
mais velhos que a janela (`config.BACKUP_RETENCAO_DIAS`, 30 dias por omissão).

Este módulo tem **duas peças testáveis sem correr nada**:

    - :func:`comando_pg_dump` — compõe o `argv` do `pg_dump` (arquivo *custom*,
      restaurável com `pg_restore`; portável, sem dono/privilégios embutidos). Não corre;
      só devolve a lista de tokens.
    - :func:`ficheiros_a_apagar` — decide, por nome de ficheiro (timestamp UTC embutido),
      quais backups estão fora da janela de retenção. **Nunca** considera ficheiros que
      não sejam backups nossos (prefixo + sufixo + timestamp válido) — uma salvaguarda
      dura para nunca apagar por engano a BD, configs ou o backup de outrem.

E um **entrypoint de cron** — :func:`correr_backup` / :func:`main` — que junta as duas
via *seams* injetados.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** O `pg_dump` corre por um seam
:func:`_correr_subprocess` (subprocess) que só é criado/chamado em produção; nos testes
injeta-se `correr`/`listar`/`apagar` — **zero subprocess/rede**. Sem `config.BACKUP_DB_URL`
(o default) o backup é live-gated: :func:`correr_backup` levanta :class:`BackupInativo`
**antes** de tocar em qualquer subprocess (ver :func:`app.config.backups_ativo`).
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.config as config

__all__ = [
    "PREFIXO_BACKUP",
    "SUFIXO_BACKUP",
    "FORMATO_TS",
    "BackupInativo",
    "ResultadoBackup",
    "comando_pg_dump",
    "nome_ficheiro_backup",
    "ficheiros_a_apagar",
    "correr_backup",
    "main",
]

# Padrão de nomes: `checkal-<UTC>.dump`, com o timestamp em ISO-básico ordenável
# lexicograficamente (== ordem cronológica). Só ficheiros que casam este padrão são
# candidatos à retenção — a garantia de nunca apagar ficheiros alheios.
PREFIXO_BACKUP = "checkal-"
SUFIXO_BACKUP = ".dump"
FORMATO_TS = "%Y%m%dT%H%M%SZ"


class BackupInativo(RuntimeError):
    """Backup pedido sem DSN de origem — live-gate (`config.backups_ativo()` é False)."""


@dataclass(frozen=True)
class ResultadoBackup:
    """Resultado de uma corrida do cron de backup.

    Atributos
    ---------
    destino:
        Caminho do arquivo escrito por este `pg_dump`.
    comando:
        `argv` composto e passado ao seam de execução (útil para logging/auditoria).
    apagados:
        Backups podados por retenção nesta corrida (lista de :class:`Path`).
    executado:
        ``True`` quando o dump foi disparado (o seam `correr` foi chamado).
    """

    destino: Path
    comando: list[str]
    apagados: list[Path]
    executado: bool


def _para_utc(agora: datetime) -> datetime:
    """Normaliza para UTC; um `datetime` ingénuo é interpretado como UTC.

    Torna o nome do ficheiro e a retenção **deterministas**, independentes do fuso
    horário da máquina onde o cron corre.
    """
    if agora.tzinfo is None:
        return agora.replace(tzinfo=timezone.utc)
    return agora.astimezone(timezone.utc)


def nome_ficheiro_backup(agora: datetime) -> str:
    """Nome do arquivo de backup para o instante `agora` (`checkal-<UTC>.dump`)."""
    return f"{PREFIXO_BACKUP}{_para_utc(agora).strftime(FORMATO_TS)}{SUFIXO_BACKUP}"


def _ts_do_nome(nome: str) -> datetime | None:
    """Extrai o timestamp UTC de um nome de backup nosso, ou ``None`` se não for um.

    Só devolve um instante para nomes com o **prefixo E o sufixo** nossos E um
    timestamp que casa :data:`FORMATO_TS`. Qualquer outra coisa (a BD, uma config,
    um `.dump` alheio) devolve ``None`` — nunca é candidata a ser apagada.
    """
    if not (nome.startswith(PREFIXO_BACKUP) and nome.endswith(SUFIXO_BACKUP)):
        return None
    meio = nome[len(PREFIXO_BACKUP) : len(nome) - len(SUFIXO_BACKUP)]
    try:
        return datetime.strptime(meio, FORMATO_TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def comando_pg_dump(
    *,
    dsn: str,
    destino: Path | str,
    pgdump_bin: str | None = None,
    formato: str = "custom",
) -> list[str]:
    """Compõe o `argv` do `pg_dump` (não corre nada — só devolve a lista de tokens).

    Parâmetros
    ----------
    dsn:
        DSN Postgres de **origem** (ex.: ``postgresql://user:pass@host:5432/db``).
        Vazio ⇒ :class:`BackupInativo` (live-gate na própria composição).
    destino:
        Caminho do arquivo a escrever.
    pgdump_bin:
        Binário do `pg_dump`; por omissão :data:`config.BACKUP_PGDUMP_BIN`.
    formato:
        Formato de saída (``custom`` por omissão — arquivo comprimido restaurável com
        `pg_restore`, que suporta restauro seletivo/paralelo).

    O arquivo sai **portável** (`--no-owner`, `--no-privileges`): restaura-se numa conta
    ou instância diferente sem depender dos papéis/ACLs da origem — o que interessa para
    um restauro de emergência noutra máquina.
    """
    if not dsn:
        raise BackupInativo(
            "DSN de origem vazio — backup live-gated (ver config.backups_ativo())."
        )
    binario = pgdump_bin or config.BACKUP_PGDUMP_BIN
    return [
        binario,
        f"--dbname={dsn}",
        f"--format={formato}",
        "--no-owner",
        "--no-privileges",
        f"--file={destino}",
    ]


def ficheiros_a_apagar(
    ficheiros: Iterable[Path | str],
    *,
    agora: datetime,
    retencao_dias: int,
) -> list[Path]:
    """Backups fora da janela de retenção — os candidatos a apagar.

    Um ficheiro é apagado sse (e só se) for um backup nosso (prefixo/sufixo/timestamp
    válidos) **e** o seu timestamp for **estritamente** anterior a
    ``agora - retencao_dias``. Ficheiros não reconhecidos são **sempre** ignorados — a
    salvaguarda para nunca apagar a BD, configs ou o backup de outrem.
    """
    limite = _para_utc(agora) - timedelta(days=retencao_dias)
    apagar: list[Path] = []
    for f in ficheiros:
        p = Path(f)
        ts = _ts_do_nome(p.name)
        if ts is None:
            continue
        if ts < limite:
            apagar.append(p)
    return apagar


def _correr_subprocess(comando: list[str]) -> object:  # pragma: no cover - só produção
    """Corre o `pg_dump` de facto (import tardio de `subprocess` — LIVE-GATED).

    Só é chamado quando `correr` não é injetado, o que só acontece em produção. Levanta
    `subprocess.CalledProcessError` se o `pg_dump` sair com código != 0 — a falha propaga
    (via :func:`correr_backup`) para o dead-man switch (Healthchecks) e o systemd.
    """
    import subprocess

    return subprocess.run(comando, check=True, capture_output=True)


def _listar_dir(diretorio: Path) -> list[Path]:  # pragma: no cover - trivial FS
    """Lista os ficheiros do diretório de backups (seam injetável nos testes)."""
    if not diretorio.is_dir():
        return []
    return [p for p in diretorio.iterdir() if p.is_file()]


def _apagar_ficheiro(caminho: Path) -> None:  # pragma: no cover - trivial FS
    """Apaga um ficheiro (seam injetável nos testes)."""
    caminho.unlink()


def correr_backup(
    *,
    dsn: str | None = None,
    destino_dir: Path | str | None = None,
    pgdump_bin: str | None = None,
    retencao_dias: int | None = None,
    formato: str = "custom",
    agora: datetime | None = None,
    correr: Callable[[list[str]], object] | None = None,
    listar: Callable[[Path], Iterable[Path]] | None = None,
    apagar: Callable[[Path], object] | None = None,
) -> ResultadoBackup:
    """Corre o backup: compõe o comando, dispara o `pg_dump` e poda os antigos.

    Todos os *seams* de efeito colateral são injetáveis (e injetados nos testes):
    `correr` (subprocess do `pg_dump`), `listar` (conteúdo do diretório) e `apagar`
    (remoção). Por omissão usam as implementações reais — que só se acionam em produção.

    O que faz, por ordem:
      1. resolve parâmetros em falta a partir de :mod:`app.config`;
      2. **live-gate**: sem `dsn` (nem `config.BACKUP_DB_URL`) levanta :class:`BackupInativo`
         **antes** de qualquer subprocess;
      3. compõe o comando (:func:`comando_pg_dump`) e dispara-o **uma vez** via `correr`;
      4. lista o diretório e apaga os backups fora da janela (:func:`ficheiros_a_apagar`).

    Levanta
    -------
    BackupInativo
        Sem DSN de origem (live-gate).
    """
    dsn = config.BACKUP_DB_URL if dsn is None else dsn
    if not dsn:
        raise BackupInativo(
            "BACKUP_DB_URL vazio — backup live-gated (config.backups_ativo() é False)."
        )
    destino_dir = Path(config.BACKUP_DIR if destino_dir is None else destino_dir)
    pgdump_bin = pgdump_bin or config.BACKUP_PGDUMP_BIN
    retencao_dias = config.BACKUP_RETENCAO_DIAS if retencao_dias is None else retencao_dias
    agora = agora or datetime.now(timezone.utc)
    if correr is None:
        correr = _correr_subprocess
    if listar is None:
        listar = _listar_dir
    if apagar is None:
        apagar = _apagar_ficheiro

    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / nome_ficheiro_backup(agora)
    comando = comando_pg_dump(
        dsn=dsn, destino=destino, pgdump_bin=pgdump_bin, formato=formato
    )

    # 1) dump — seam injetado; em produção corre o pg_dump de facto e propaga a falha.
    correr(comando)

    # 2) retenção — só backups nossos fora da janela; o arquivo recém-escrito fica.
    existentes = list(listar(destino_dir))
    apagados = ficheiros_a_apagar(existentes, agora=agora, retencao_dias=retencao_dias)
    for p in apagados:
        apagar(p)

    return ResultadoBackup(
        destino=destino, comando=comando, apagados=list(apagados), executado=True
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - entrypoint de systemd
    """Entrypoint do systemd timer noturno: corre o backup e devolve o código de saída.

    ``0`` em sucesso. Live-gate (sem DSN) ou falha do `pg_dump`/retenção escrevem o alarme
    em `stderr` e devolvem ``1`` — o systemd marca a unidade como falhada e o dead-man
    switch (Healthchecks, ligado pelo wire) avisa o dono. Nunca falha em silêncio.
    """
    try:
        res = correr_backup()
    except BackupInativo as e:
        print(f"[backups] INATIVO — {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - qualquer falha do dump/retenção alarma
        print(f"[backups] FALHA — {e}", file=sys.stderr)
        return 1
    print(f"[backups] OK — {res.destino.name} · {len(res.apagados)} antigos apagados")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
