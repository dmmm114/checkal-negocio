# EMBAIXADOR + Atendimento pré-vendas — passos manuais do dono

> Tudo construído e testado (suite 1650 verdes; 7.º cartão já em produção no
> dashboard). Como pediste: as ligações de email ficam para ti — nada envia
> até as ligares, e mesmo depois tudo passa pelo teu gate.

## Para ativar o EMBAIXADOR

1. `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
   → instala o `checkal-embaixador.timer` (Ter 10:00). ⚠️ Se ainda não correste o
   instalador desde as fases 1-3, este passo também ativa PELA PRIMEIRA VEZ os
   timers do editor/comunicador/publicador e o checkal-web — tudo atrás dos
   gates, mas o gasto LLM dos agentes começa aí (ver handoff da fase 1).
   Na próxima terça o agente deteta candidatos (423 gestores multi-AL com 5+ ALs
   e email genérico na tua BD) e redige 1-3 propostas para a fila — que aprovas
   no portão como os artigos.
2. `sudo ./instalar-acoes-checkal.sh` (no Dashboard_Polaris)
   → sudoers do botão "Acordar" do cartão novo.
3. **Envio real das propostas** — fica atrás dos MESMOS gates do cold
   (parecer RGPD + `CHECKAL_MODO_TESTE=false` + SMTP getcheckal.com):
   aprovar uma proposta hoje deixa-a `aprovado` na fila à espera do seam de
   envio. Quando ligares o SMTP/parecer, o envio consome a fila. Até lá, podes
   enviar à mão: copia o texto no painel "Para publicar" ANTES de aprovares
   (o painel só mostra itens pendentes — depois de decidires, sai de lá).

## Para ativar o atendimento (respostas automáticas)

4. **IMAP da caixa apoio@** no `deploy/polaris/agente.env` (as variáveis IMAP_*
   que o `config.imap_ativo()` espera) → o cron de suporte (15/15 min, timer já
   existente mas desligado — ativa-o no instalar.sh descomentando ou
   `sudo systemctl enable --now checkal-cron-suporte.timer checkal-gestor-suporte.timer`)
   passa a ler o correio, triar (agora com a categoria pré-vendas: "quanto
   custa?" recebe resposta com preços canónicos + convite ao check grátis) e:
   ATENÇÃO: em modo teste o cron autónomo é no-op total (o leitor IMAP nem
   arranca) — os rascunhos na fila vêm só da passagem do GESTOR; em modo live,
   respostas factuais/pré-venda saem sozinhas e o sensível escala SEMPRE para ti.
5. **Caixa `comercial@checkal.pt`** — criar (o formulário do site ganhou a opção
   "Informações e preços (pré-venda)" que aponta para lá; até existir, essas
   submissões falham a entrega). E `RESEND_API_KEY` nas env vars do Cloudflare
   Pages para o formulário todo funcionar (pendência antiga do site).

## Notas

- A comissão de 20% aparece nas propostas como ponto de partida de conversa com
  "termos finais por escrito" — nunca como promessa pública (regra do GTM).
- Dedupe: um NIF proposto (mesmo rejeitado) nunca é re-contactado.
- Limpeza opcional: `agentes-polaris/prompts/{gestor-de-cliente,sentinela-servico}.txt`
  são drafts órfãos de uma fase antiga (referem subcomandos que não existem);
  podem ser apagados quando quiseres.
