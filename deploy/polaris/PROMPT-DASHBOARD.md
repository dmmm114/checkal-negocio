# Prompt — página "Sala de Controlo" dos agentes CheckAL no dashboard do Polaris

> Colar o bloco abaixo na sessão Claude do projeto do dashboard. Conceito: 4
> figurinhas (uma por agente) com estados a-dormir/a-trabalhar/alerta, detalhe ao
> clicar, KPIs e o digest diário do Maestro. **Página 100 % read-only** — a
> aprovação 1-clique fica para o painel do próprio CheckAL (fase 2).

```
Quero uma página nova no meu dashboard do Polaris: a "Sala de Controlo" dos agentes
CheckAL. O CheckAL é um projeto meu que corre nesta máquina com 4 agentes de IA
single-shot (acordam por systemd timer, trabalham, escrevem numa BD SQLite e saem)
— por isso não aparecem como processos permanentes; o estado deles lê-se da BD e
dos timers. Integra com o stack existente do dashboard.

REGRAS DURAS (não negociáveis):
- Acesso à BD ESTRITAMENTE READ-ONLY: abre sempre com URI
  "file:/home/diogo/checkal-polaris/checkal/data/checkal.db?mode=ro" (e/ou
  PRAGMA query_only=ON). NUNCA escrevas nesta BD, nunca faças INSERT/UPDATE,
  nunca importes código do projeto CheckAL — só SELECTs.
- NÃO leias /home/diogo/checkal-polaris/deploy/polaris/agente.env (segredos).
- Timeouts curtos e tolerância a "database is locked" (outro processo pode estar
  a escrever); refresca por polling (ex.: 10–30 s).
- Não mostres emails/nomes de prospects em listas; usa agregados e resumos
  (os detalhes finos ficam para o painel do próprio CheckAL).

FONTES DE DADOS:
1) BD SQLite (caminho acima), tabelas relevantes:
   - agente_execucoes: agente, modo, iniciado_em, terminado_em, estado
     (a_correr|ok|falhou|morto), exit_code, retry_pedido → última passagem de cada agente.
   - eventos_agente: journal append-only (agente, tipo [achado|conteudo_proposto|
     escalada|...], severidade, mensagem, payload JSON, criado_em) → timeline "o que
     andou a fazer"; os "achado" do sentinela têm payload.categoria.
   - escalacoes: agente, severidade (baixa|media|alta|critica), mensagem, estado
     (aberta|...), criado_em → badges de alerta nas figurinhas.
   - revisao_itens: tipo, risco, camada_risco (1–4), estado (pendente|aprovado|...),
     agente_origem, resumo, criado_em → a fila de aprovação humana (contar pendentes).
   - digests: dia, corpo_md (markdown do resumo diário do Maestro), criado_em,
     enviado_em → renderizar o mais recente.
   - custo_llm: dia, agente, input_tokens, output_tokens, custo_eur_cent → custo de
     hoje por agente e total vs teto de 5 €/dia (500 cents).
   - campanhas / campanha_pecas: funil de prospeção (contagens por estado).
   - Domínio (só contagens/último): registos (COUNT = ALs vigiados), varrimentos
     (último concluido_em + estado = freshness do serviço), eventos_registo
     (COUNT por tipo nas últimas 24h/7d = diffs detetados), clientes (por estado),
     leads (por estado).
2) systemd (sem sudo): `systemctl list-timers 'checkal*' --all --no-pager` →
   próxima passagem agendada de cada timer (checkal-sentinela, checkal-maestro-digest,
   checkal-maestro-governanca, checkal-angariador, checkal-gestor, checkal-cron-*).
3) Runtime: /home/diogo/checkal-polaris/deploy/polaris/run/ — se existir
   "<instancia>.lock" o agente está A TRABALHAR agora; se existir "PAUSA_LLM" o
   teto de custo disparou (mostrar aviso).

A PÁGINA (conceito: figurinhas a trabalhar):
- 4 cartões-personagem: MAESTRO 🎩 "o governador" (digest 07:50 + governança
  11:50/15:50/19:50), ANGARIADOR 🎣 "a aquisição" (seg/qui 03:30 + diária 12:00),
  GESTOR 🤝 "a retenção" (diária 07:15), SENTINELA 🦉 "o watchdog" (06:40, 12:40,
  18:40, 23:40). Cada cartão tem um avatar animado com 3 estados:
  · a dormir (zzz) + countdown "próxima passagem em Xh Ym" (do systemctl),
  · a trabalhar (animação) quando o .lock existe,
  · alerta (badge vermelho) = nº de escalações abertas desse agente.
  E uma linha de estado: última passagem (quando, ok/falhou) + custo de hoje.
- Clicar num cartão abre o detalhe: timeline dos eventos_agente desse agente
  (últimos 20), última execução, pendentes na fila de revisão com origem nele,
  e a agenda (próximos disparos do timer).
- Topo da página, faixa de KPIs: ALs vigiados (COUNT registos) · freshness do
  último varrimento (verde se < 4 dias) · diffs 7d · fila de aprovação pendente ·
  custo LLM hoje vs teto 5 € · flag PAUSA_LLM se ativa.
- Secção "Digest do Maestro": renderiza o corpo_md do digest mais recente
  (markdown → HTML), com a data.
- Secção "Máquinas de fundo" (discreta): os crons deterministas
  (varrimento 2×/sem, DRE, dunning, backup) com o próximo disparo — são o
  backbone, não são personagens.
- Estética: divertida mas legível (as figurinhas podem ser emoji/SVG animado);
  tudo em PT-PT. A página é privada (rede local/Tailscale).

Fase 2 (NÃO fazer agora, só deixar espaço no layout): botão "aprovar/rejeitar"
nos itens da fila — será um link para o painel do próprio CheckAL, nunca escrita
direta nesta BD.
```

Nota (para o CheckAL, não para o dashboard): se os agentes começarem a registar
erros "database is locked" por causa das leituras do dashboard, ativar WAL na BD
(`PRAGMA journal_mode=WAL`) — melhora a concorrência leitor/escritor.
