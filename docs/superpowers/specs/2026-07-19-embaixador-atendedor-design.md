# Design — EMBAIXADOR (parcerias) + Atendimento pré-vendas

> Pedido do dono 19/07/2026 ("cria tudo; eu faço as ligações de email depois").
> Tudo o que depende de ligações externas (IMAP, Resend/SMTP, envio real) fica
> atrás dos gates existentes — construção completa, ativação é do dono.

## 1. EMBAIXADOR 🤵 — o agente de parcerias (canal GTM n.º 2)

**Missão:** detetar candidatos a parceiro na BD RNAL (gestores multi-AL — SÓ
pessoas coletivas com email genérico) e redigir propostas de parceria B2B que
entram na fila de revisão atrás do gate do dono. O envio real fica live-gated
como o cold (SMTP/parecer). Universo real (BD 19/07): 423 candidatos com 5+ ALs
e email genérico; 1.024 com 2+; top carteiras 292/184/169 ALs.

**Deteção (módulo determinista `app/embaixador.py`, padrão da segmentação):**
1. Pré-filtro SQL read-only: NIF coletivo (substr 5/6, len 9), `desaparecido_em
   IS NULL`, `GROUP BY nif HAVING COUNT(*) >= limiar` (default 5, configurável).
2. Portão Python OBRIGATÓRIO com as funções canónicas de `app/compliance`
   (NUNCA reimplementar): `nif.e_enderecavel`, `email.e_generico`,
   `minimizacao.filtrar_enderecaveis`, `optout.filtrar_optout` — a autoridade é
   `e_enderecavel`, não `titular_tipo` (~695 divergem). Email canónico = o
   genérico mais frequente do grupo.
3. Dedupe: exclui NIFs que já têm `proposta_parceria` na fila (qualquer estado)
   — um titular = um contacto.
4. Output minimizado p/ LLM: `ContactoEnderecavel` + agregados não-pessoais
   (n_registos, concelhos, modalidades, camas). Singulares NUNCA.

**Artefactos:** tipo novo `proposta_parceria` → `Canal.COLD` do linter (herda
R7 disclaimer, R8 opt-out, R9 identificação Cosmic Oasis, RT_DOMINIO — remetente
getcheckal.com; é B2B frio, as regras servem à letra). Risco alto ⇒ camada 4.
Pitch canónico: PRICING (Portfólio 149/299/499€ + trienal 359€), argumento "10
ALs = exposição até 400.000€ → 149€ = 0,04%"; comissão 20% recorrente do GTM §5
como proposta de conversa, com "termos finais por escrito" SEMPRE (a página
pública não promete comissões — as propostas individuais podem propor).

**Cadência:** timer semanal (Ter 10:00), cap 3 propostas/passagem (piloto GTM =
3-5 parceiros). Subcomandos: `embaixador {estado, detetar, lint --stdin,
enfileirar --tipo proposta_parceria --stdin --nif N [--escalar --motivo M]}`.
Infra: prompt (2 árvores), wrapper TOOLS, `checkal-embaixador.timer`,
maestro-saude/retry, Healthchecks `agente-embaixador`, AGENTES-ENXAME, cartão
no dashboard (7.º agente) + sudoers.

**Inbound (formulário /parceiros do site):** continua a ir para
parcerias@checkal.pt via Resend (fail-closed sem chave). O EMBAIXADOR não lê
email (sem IMAP no âmbito); quando o dono ligar o IMAP, decide-se se o inbound
entra na passagem (fase posterior — anotado no handoff).

## 2. Atendimento pré-vendas (GESTOR + cron de suporte)

**Problema:** as 5 categorias de triagem (factual/juridico/reclamacao/
cancelar_queixa/outro) não têm pré-vendas; um "quanto custa?" recebe tom de
apoio seco, sem CTA; e a regex sensível (`regulament`) faz a própria descrição
do produto escalar com severidade alta.

**Mudanças (nos DOIS caminhos, em sincronia):**
1. Categoria nova `pre_venda` em `app/suporte.py` (CATEGORIAS + ESQUEMA_SUPORTE
   + _SISTEMA_REGRAS): interessado/curioso sem subscrição a perguntar por
   preços/funcionamento ⇒ `responder` com tom "inspetor amigo" + CTA suave para
   o check grátis. NÃO entra nos GATILHOS_ESCALACAO. Confiança baixa continua a
   escalar (fail-closed intacto).
2. FAQ alinhada com a tabela CANÓNICA completa do PRICING.md (acrescenta
   Portfólio trienal 359€ e +45€/3 anos — hoje divergem) + claims permitidos do
   PRODUTO.md; NUNCA "AL legal/certificado".
3. Regex `_RE_SUPORTE_SENSIVEL` (manage.py): refinar SÓ o token `regulament` —
   passa a exigir uso prescritivo (`regulamento (proíbe|obriga|exige|impede|
   impõe)`) para que "vigiamos os regulamentos municipais" (descrição do
   produto) não escale, MANTENDO todos os outros gatilhos intactos. Testes
   pinam as duas direções (descrição passa; prescrição escala).
4. Prompt do gestor (2 árvores): bloco pré-vendas com os factos canónicos e a
   regra de tom; CTA sempre para o check grátis, nunca fecho agressivo.
5. Site: opção "Comercial / pré-venda" no select de contacto.html + destino
   `comercial@checkal.pt` em contacto.js (repo aninhado, commit SEM push — vai
   no próximo deploy do dono).

**RGPD (decisão de desenho, a validar pelo dono se quiser):** responder a quem
nos escreve é resposta a pedido direto do titular (diligência pré-contratual)
— o email recebido entra no contexto da triagem como já hoje acontece no
suporte; a REGRA DE DADOS mantém-se para tudo o resto (nunca prospetar
singulares, nunca guardar além do fluxo).

## 3. Fora de âmbito / fica para o dono ligar

IMAP (apoio@/parcerias@), Resend/SMTP, envio real de propostas (gates de cold),
deploy do site. Handoff próprio no fim da implementação.
