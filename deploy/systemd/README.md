# Crons do CheckAL — systemd timers

O serviço templado `checkal@.service` corre `python manage.py <job>` dentro do container.
Cada job compõe os seams live-gated do ambiente (nada envia/liga sem credenciais) e corre
sob o dead-man switch. Cadências canónicas (AUTOMACAO.md §1/§5/§6):

| Job | Cadência | OnCalendar |
|---|---|---|
| `varrimento` | 2×/semana | `Mon,Thu 03:00` |
| `dre` | diário | `*-*-* 07:00` |
| `dunning` | diário | `*-*-* 09:00` |
| `suporte` | 15 min | `*:0/15` |
| `backup` | noturno | `*-*-* 02:00` |
| `token` | ~3h (TOConline OAuth) | `*:0/180` (`00:00,03:00,…`) |

## Instalação (no servidor, uma vez)
```bash
sudo cp checkal@.service /etc/systemd/system/
# cria um .timer por job (exemplo do varrimento):
cat >/etc/systemd/system/checkal-varrimento.timer <<'EOF'
[Unit]
Description=CheckAL varrimento (2x/semana)
[Timer]
OnCalendar=Mon,Thu 03:00
Persistent=true
Unit=checkal@varrimento.service
[Install]
WantedBy=timers.target
EOF
# repetir para dre/dunning/suporte/backup/token com o OnCalendar da tabela.
sudo systemctl daemon-reload
sudo systemctl enable --now checkal-varrimento.timer   # e os restantes
```

> Nota: `varrimento` só faz diffing (não envia falso "cancelado" — ver breaker/FDS5);
> `token` mantém a cadeia OAuth do TOConline viva (refresh ~8h); `backup` faz `pg_dump`.
> O detalhe diário dos clientes (03:30) e o motor de campanhas (cold, gated) ligam-se
> quando os respetivos pré-requisitos estiverem cumpridos.
