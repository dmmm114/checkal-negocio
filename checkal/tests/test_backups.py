"""Testes FDS 5 dos backups noturnos (SPEC-FDS5.md §backups).

Contrato (`app.backups`):

    comando_pg_dump(*, dsn, destino, pgdump_bin=None, formato="custom") -> list[str]
    nome_ficheiro_backup(agora) -> str
    ficheiros_a_apagar(ficheiros, *, agora, retencao_dias) -> list[Path]
    correr_backup(*, dsn, destino_dir, correr, listar, apagar, ...) -> ResultadoBackup
    main(argv=None) -> int  (entrypoint de systemd)

Testa a **composição do comando** e a **política de retenção** — nada mais. Disciplina
(inviolável): MODO DE TESTE, LIVE-GATED. **Zero subprocess/rede** — o `pg_dump` é um seam
INJETADO/MOCKADO (`correr`) que este teste NUNCA deixa correr de verdade; a listagem e a
remoção de ficheiros também são injetadas. Sem DSN de origem, o backup é live-gated e
levanta `BackupInativo` antes de tocar em qualquer subprocess. Escrito ANTES da
implementação (TDD).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.backups as backups
import app.config as config

UTC = timezone.utc


# --------------------------------------------------------------------------
#  Composição do comando pg_dump (testável sem correr)
# --------------------------------------------------------------------------
def test_comando_pg_dump_composicao_basica():
    cmd = backups.comando_pg_dump(
        dsn="postgresql://u:p@h:5432/checkal",
        destino=Path("/bak/checkal-20260705T030000Z.dump"),
        pgdump_bin="pg_dump",
    )
    assert isinstance(cmd, list)
    assert all(isinstance(t, str) for t in cmd)
    # binário é o primeiro token
    assert cmd[0] == "pg_dump"
    # DSN de origem, formato de arquivo restaurável (custom) e destino explícito
    assert "--dbname=postgresql://u:p@h:5432/checkal" in cmd
    assert "--format=custom" in cmd
    assert "--file=/bak/checkal-20260705T030000Z.dump" in cmd


def test_comando_pg_dump_arquivo_portavel():
    # arquivo restaurável noutra conta/instância: sem dono nem privilégios embutidos
    cmd = backups.comando_pg_dump(dsn="postgresql://x/db", destino=Path("/b/f.dump"))
    assert "--no-owner" in cmd
    assert "--no-privileges" in cmd


def test_comando_pg_dump_bin_por_defeito_vem_da_config(monkeypatch):
    monkeypatch.setattr(config, "BACKUP_PGDUMP_BIN", "/usr/lib/postgresql/16/bin/pg_dump")
    cmd = backups.comando_pg_dump(dsn="postgresql://x/db", destino=Path("/b/f.dump"))
    assert cmd[0] == "/usr/lib/postgresql/16/bin/pg_dump"


def test_comando_pg_dump_formato_override():
    cmd = backups.comando_pg_dump(
        dsn="postgresql://x/db", destino=Path("/b/f.sql"), formato="plain"
    )
    assert "--format=plain" in cmd
    assert "--format=custom" not in cmd


def test_comando_pg_dump_dsn_vazio_recusa():
    # live-gate na própria composição: sem DSN não há comando possível
    with pytest.raises(backups.BackupInativo):
        backups.comando_pg_dump(dsn="", destino=Path("/b/f.dump"))


# --------------------------------------------------------------------------
#  Nome do ficheiro (timestamp UTC, ordenável lexicograficamente)
# --------------------------------------------------------------------------
def test_nome_ficheiro_formato_utc():
    nome = backups.nome_ficheiro_backup(datetime(2026, 7, 5, 3, 30, 15, tzinfo=UTC))
    assert nome == "checkal-20260705T033015Z.dump"


def test_nome_ficheiro_naive_tratado_como_utc():
    # datetime ingénuo é interpretado como UTC (determinismo — não depende do TZ da máquina)
    assert backups.nome_ficheiro_backup(datetime(2026, 1, 2, 4, 5, 6)) == \
        "checkal-20260102T040506Z.dump"


def test_nome_ficheiro_tz_convertido_para_utc():
    # 03:00 em UTC+1 == 02:00Z
    tz1 = timezone(timedelta(hours=1))
    assert backups.nome_ficheiro_backup(datetime(2026, 7, 5, 3, 0, 0, tzinfo=tz1)) == \
        "checkal-20260705T020000Z.dump"


def test_nome_ficheiro_ordena_cronologicamente():
    cedo = backups.nome_ficheiro_backup(datetime(2026, 7, 5, 3, 0, tzinfo=UTC))
    tarde = backups.nome_ficheiro_backup(datetime(2026, 7, 5, 4, 0, tzinfo=UTC))
    assert cedo < tarde  # ordem lexicográfica == ordem temporal


# --------------------------------------------------------------------------
#  Política de retenção (função pura, sem tocar no FS)
# --------------------------------------------------------------------------
def _nome_para(agora: datetime) -> str:
    return backups.nome_ficheiro_backup(agora)


def test_retencao_apaga_velhos_mantem_recentes():
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    velho = _nome_para(agora - timedelta(days=40))
    recente = _nome_para(agora - timedelta(days=5))
    apagar = backups.ficheiros_a_apagar(
        [Path("/b") / velho, Path("/b") / recente], agora=agora, retencao_dias=30
    )
    nomes = {p.name for p in apagar}
    assert velho in nomes
    assert recente not in nomes


def test_retencao_fronteira_estrita():
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    # exatamente 30 dias: dentro da janela (não apaga); 30d+1s: fora (apaga)
    dentro = _nome_para(agora - timedelta(days=30))
    fora = _nome_para(agora - timedelta(days=30, seconds=1))
    apagar = backups.ficheiros_a_apagar(
        [Path("/b") / dentro, Path("/b") / fora], agora=agora, retencao_dias=30
    )
    nomes = {p.name for p in apagar}
    assert fora in nomes
    assert dentro not in nomes


def test_retencao_ignora_ficheiros_alheios():
    # SEGURANÇA: nunca apaga o que não é um backup nosso, por mais velho que pareça
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    alheios = [
        Path("/b/database.sqlite"),
        Path("/b/checkal.conf"),                    # prefixo parecido, sufixo errado
        Path("/b/checkal-lixo.dump"),               # timestamp inválido
        Path("/b/2020-01-01.dump"),                 # sufixo certo, sem prefixo
    ]
    apagar = backups.ficheiros_a_apagar(alheios, agora=agora, retencao_dias=1)
    assert apagar == []


def test_retencao_aceita_str_e_path():
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    velho = _nome_para(agora - timedelta(days=99))
    apagar = backups.ficheiros_a_apagar([f"/b/{velho}"], agora=agora, retencao_dias=30)
    assert [p.name for p in apagar] == [velho]
    assert all(isinstance(p, Path) for p in apagar)


# --------------------------------------------------------------------------
#  Entrypoint de cron — subprocess/listagem/remoção TODOS injetados (não correm)
# --------------------------------------------------------------------------
class _Spy:
    def __init__(self):
        self.chamadas: list = []

    def __call__(self, arg):
        self.chamadas.append(arg)
        return object()


def test_correr_backup_compoe_e_dispara_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_PGDUMP_BIN", "pg_dump")
    correr = _Spy()
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    res = backups.correr_backup(
        dsn="postgresql://u:p@h/checkal",
        destino_dir=tmp_path,
        retencao_dias=30,
        agora=agora,
        correr=correr,
        listar=lambda _d: [],       # dir vazio ⇒ nada a apagar
        apagar=lambda _p: None,
    )
    # o dump foi disparado exatamente uma vez, com o comando composto
    assert len(correr.chamadas) == 1
    cmd = correr.chamadas[0]
    assert cmd == res.comando
    assert cmd[0] == "pg_dump"
    assert f"--file={tmp_path / 'checkal-20260705T030000Z.dump'}" in cmd
    assert "--dbname=postgresql://u:p@h/checkal" in cmd
    assert res.destino == tmp_path / "checkal-20260705T030000Z.dump"
    assert res.executado is True
    assert res.apagados == []


def test_correr_backup_aplica_retencao(tmp_path):
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    velho = tmp_path / _nome_para(agora - timedelta(days=45))
    recente = tmp_path / _nome_para(agora - timedelta(days=1))
    alheio = tmp_path / "nao-mexer.dump"
    apagados = _Spy()
    res = backups.correr_backup(
        dsn="postgresql://x/db",
        destino_dir=tmp_path,
        retencao_dias=30,
        agora=agora,
        correr=lambda _c: None,
        listar=lambda _d: [velho, recente, alheio],
        apagar=apagados,
    )
    # apaga só o backup velho; poupa o recente e o ficheiro alheio
    assert apagados.chamadas == [velho]
    assert res.apagados == [velho]


def test_correr_backup_live_gate_sem_dsn_nao_corre_subprocess(monkeypatch):
    # sem BACKUP_DB_URL e sem dsn ⇒ BackupInativo ANTES de qualquer subprocess
    monkeypatch.setattr(config, "BACKUP_DB_URL", "")
    correr = _Spy()
    with pytest.raises(backups.BackupInativo):
        backups.correr_backup(correr=correr, listar=lambda _d: [], apagar=lambda _p: None)
    assert correr.chamadas == []  # o pg_dump nunca foi tocado


def test_correr_backup_usa_dsn_da_config_quando_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DB_URL", "postgresql://cfg/db")
    correr = _Spy()
    res = backups.correr_backup(
        destino_dir=tmp_path,
        agora=datetime(2026, 7, 5, 3, 0, tzinfo=UTC),
        correr=correr,
        listar=lambda _d: [],
        apagar=lambda _p: None,
    )
    assert "--dbname=postgresql://cfg/db" in res.comando
    assert len(correr.chamadas) == 1


def test_correr_backup_retencao_dias_por_defeito_da_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_RETENCAO_DIAS", 7)
    agora = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)
    # 10 dias > janela de 7 ⇒ apagado
    velho = tmp_path / _nome_para(agora - timedelta(days=10))
    apagados = _Spy()
    backups.correr_backup(
        dsn="postgresql://x/db",
        destino_dir=tmp_path,
        agora=agora,
        correr=lambda _c: None,
        listar=lambda _d: [velho],
        apagar=apagados,
    )
    assert apagados.chamadas == [velho]


# --------------------------------------------------------------------------
#  main() — entrypoint de systemd (subprocess injetado; nunca corre real)
# --------------------------------------------------------------------------
def test_main_sucesso_devolve_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "BACKUP_DB_URL", "postgresql://x/db")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path)
    # injeta a execução via a fábrica interna, garantindo que nenhum subprocess real corre
    monkeypatch.setattr(backups, "_correr_subprocess", lambda _c: None)
    assert backups.main([]) == 0
    assert "OK" in capsys.readouterr().out


def test_main_inativo_devolve_um(monkeypatch, capsys):
    monkeypatch.setattr(config, "BACKUP_DB_URL", "")
    monkeypatch.setattr(backups, "_correr_subprocess", lambda _c: pytest.fail("não deve correr"))
    assert backups.main([]) == 1
    assert "INATIVO" in capsys.readouterr().err
