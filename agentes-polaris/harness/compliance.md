I have everything needed. Here is the operational compliance layer.

---

# CAMADA DE COMPLIANCE OPERACIONAL — CheckAL

> O checklist acionável que **cada agente** e o **linter** obedecem. Fonte de verdade determinista: `checkal/app/compliance/*`, `checkal/app/config.py`, `LEGAL-PARECER-DECISOES.md`. Os agentes **CHAMAM** estas regras/funções — **nunca** as reimplementam nem as contornam. Regra-mãe: **reversível-até-ao-gate**; toda a ação irreversível externa passa pelo human-in-the-loop 1-clique do Maestro.

---

## 1. Portões de código (não disciplina humana) — verificar SEMPRE antes de agir

1.1. **`config.pode_enviar_frio_global()`** é o portão-mãe do cold. Devolve `True` **só se** `CHECKAL_PARECER_RGPD_OK` (default `False`) **E** `not CHECKAL_MODO_TESTE` (default `True`) **E** `cold_smtp_ativo()`. Enquanto qualquer um falhar → **nenhum email frio sai**; tudo cai em `ResultadoCampanha.pendentes_parecer` (`RascunhoFrio`).

1.2. **Nenhum agente pode setar, forçar ou contornar** `CHECKAL_PARECER_RGPD_OK`, `CHECKAL_MODO_TESTE`, `COLD_SMTP_*`. Libertar o gate = ação do **dono via Maestro** (injetar `remetente_frio` real), nunca alteração de código pelo executor.

1.3. **`CHECKAL_MODO_TESTE=True`** por omissão (`config.py:143`): todos os seams de rede (`obter_emissor`, `obter_enviador`, `obter_leitor`, `obter_escalador`, `_compor_onboarding`, `_seam_obter_detalhe`) devolvem `None` → nada envia/cobra/lê IMAP/toca a rede. O ciclo-cliente (consent-first/transacional) **não** depende de `PARECER_RGPD_OK`, mas depende deste gate para agir sobre a rede.

1.4. **Dead-man switches** (Healthchecks.io) são condição de saúde, não de permissão. O Sentinela verifica-os mas **não** os trata como prova de serviço prestado (ver §9).

---

## 2. Triplo gate cumulativo do cold (`motor.pode_enviar_frio`) — por CONTACTO

Um contacto só recebe cold se **os três** gates fecharem em cadeia. Qualquer um aberto → **não envia**.

2.1. **Gate 1 — global:** `config.pode_enviar_frio_global()` (§1.1).
2.2. **Gate 2 — núcleo de compliance:** coletiva **NIF 5/6** (`compliance/nif.e_enderecavel`) **E** email **genérico** (`compliance/email.e_generico`), reaplicados no ato via `minimizacao.filtrar_enderecaveis`.
2.3. **Gate 3 — oposição:** não constar da oposição **DGC** nem do **opt-out interno** (`optout.filtrar_optout` / `deve_excluir`).

> O agente **CHAMA** `pode_enviar_frio(contacto, lista_dgc, log_optout)` — **nunca** reimplementa a lógica.

---

## 3. Fronteira dura da minimização — o que a IA PODE e NÃO PODE ver

3.1. **Portão do sujeito é o NIF, não o prefixo do email.** Só **pessoa coletiva** (1.º dígito NIF ∈ {5,6}) é endereçável a cold. Singular/ENI (NIF 1/2/3/45/8) **nunca** recebe cold — mesmo com email `geral@`. Vão só a **carta** (postal, parqueado/gated) ou **consent-first**.

3.2. **`ContactoEnderecavel` só transporta campos coletivos** (nome da coletiva, nr de registo, concelho). `ProspetoCarta` **não** leva email nem NIF. Nenhum dado pessoal de singular é **materializado**.

3.3. **O agente vê apenas** estatísticas de segmento + email genérico coletivo. **Nunca** vê campos pessoais de prospects singulares. `minimizacao`/`optout` são **geradores que descartam no ato** — o sistema **não materializa lista de envio nem faz scraping**.

3.4. **Anti-alucinação na copy:** só se faz merge dos campos que o contacto minimizado transporta; **coimas saem exclusivamente de `config.COIMA`** (`singular` 2 500–4 000 € · `coletiva` 25 000–40 000 €). Nunca inventar valores, nunca o obsoleto "7 500 €".

3.5. **Cada peça de cold leva `proveniencia='rnal:email_generico_publicado'`** — prova de lookup dirigido a um dado publicado, não de recolha em massa.

---

## 4. Nota DPA / transferência Anthropic — o Claude CLI NÃO é UE-local

4.1. **Facto a encodar:** o Claude CLI (motor IA dos agentes novos no Polaris) **envia prompts para a API da Anthropic — inferência nos EUA**. **Não** mantém dados na UE. Logo os agentes operam sobre dados **agregados/genéricos/opted-in**.

4.2. **Regra dura de minimização à IA:** para **prospects** (cold), o modelo vê **só dados do AL / email genérico coletivo — NUNCA** dados pessoais de prospect.

4.3. **Para clientes singulares/ENI** que consentiram: os dados do AL enviados à IA **são pessoais** → exige **DPA (art. 28.º) + mecanismo de transferência** da Anthropic **já** (assinatura única). Opções: **(A) Bedrock `eu-central-1` (Frankfurt)** remove o Cap. V; **(B) API EUA** = **SCCs + TIA** (DPF só com verificação datada). Sem treino sobre dados de API.

4.4. **Registo art. 30.º** mantido (`REGISTO-ATIVIDADES-ART30.md`); EPD = **não designar hoje** (defensável por não ser larga escala), avaliação escrita + gatilhos de reavaliação documentados.

---

## 5. Conservação de dados

5.1. **Prospects inativos** apagam-se ao fim de **`CONSERVACAO_PROSPECT_MESES = 6`** (parecer reviu 12 → 6). A limpeza periódica usa esta constante.

5.2. **Lista de supressão (`optouts`) NUNCA cai nesta regra** — conserva-se à parte e por mais tempo, como prova de que a oposição é honrada (Lei 41/2004 art. 13.º-B). A limpeza de leads **nunca** toca `optouts`.

5.3. **Marcadores de idempotência** (em `alertas`: onboarding/dunning/suporte `\Seen`/fulfillment `stripe_session_id`+`event.id`) **não** se recriam nem apagam — o agente confia neles.

---

## 6. Checklist PRÉ-ENVIO de cold — obrigatória, ordem fixa (o agente executa até ao gate; o dono liberta)

Para cada passagem single-shot do ANGARIADOR:

6.1. **Gatilho fresco:** só eventos dentro da **janela `CAMPANHA_JANELA_H = 72h`** (`gatilhos.detetar_gatilhos`, idempotente). Eventos mais antigos são **deliberadamente saltados** — nunca prospetar sobre dados estagnados.
6.2. **Segmentar:** `segmentacao.segmentar(lote, lista_dgc, log_optout)` → só `.cold_email` (coletivas endereçáveis). Descartados/carta ficam de fora do cold.
6.3. **Compor** PT-PT (`motor.compor_email_frio` ou `prospeccao.render_sequencia`, cadência D+0/D+4/D+10), coimas só de `config.COIMA`.
6.4. **LINTER determinista** (ver §7) valida **todo** o texto **antes** de marcar aprovável.
6.5. **Cruzar oposição:** `optout.filtrar_optout(..., lista_dgc, log_optout)` (feed DGC + BD opt-out **injetados** pelo chamador).
6.6. **Verificar gate:** `pode_enviar_frio(contacto)` + `pode_enviar_frio_global()`.
6.7. **Cap diário:** máx. **`CAMPANHA_CAP_DIARIO = 20`** envios/passagem (warm-up do domínio irmão); excedente elegível → fila com `razao=RAZAO_CAP`.
6.8. **Fronteira de domínio:** cold vive em **`getcheckal.com`** via `COLD_SMTP_*` / `COLD_FROM` (default `CheckAL <geral@getcheckal.com>`). **NUNCA** importar `app.envio`/`RESEND_*`/`EMAIL_FROM`/`checkal.pt` — partilhar reputação suspenderia o canal transacional dos pagantes.
6.9. **Opt-out 1-clique carimbado pelo seam de envio:** `List-Unsubscribe` + `List-Unsubscribe-Post` (RFC 8058) + rodapé `checkal.pt/remover` + identificação do remetente + rodapé RGPD.
6.10. **Sem `remetente_frio` injetado → NADA sai:** tudo em `pendentes_parecer`. `correr_campanhas` **não faz commit** (transação do orquestrador; rollback devolve os eventos por usar).
6.11. **Resultado para o digest:** o agente escala ao **Maestro** os `pendentes_parecer` / ambiguidades; **não** envia nem publica por si.

---

## 7. LINTER determinista — vet obrigatório a TODO o texto outward-facing (cold, nurture, páginas, alertas, respostas de suporte) ANTES de ser aprovável

**Proíbe (bloqueia a aprovação):**
7.1. Afirmar que alguém está **"ilegal" / "sem seguro" / "em incumprimento" / "cancelado"** a partir de sinal único (G4 — só o **breaker** confirma cancelamentos reais; falha de rede → `indeterminado`, nunca `cancelado`).
7.2. Usar **coima como ameaça individualizada** (coimas só como contexto genérico, valores de `config.COIMA`).
7.3. **Conclusões jurídicas individualizadas** — atividade reservada (ver §8).

**Exige (sem isto não passa):**
7.4. **Link de fonte** oficial.
7.5. **Divulgação de IA** (AI Act art. 50 — ver §10).
7.6. **Opt-out** presente.
7.7. **Disclaimer "informação, não aconselhamento jurídico"** em cada alerta.

---

## 8. Atividade reservada (Lei 10/2024) — guarda no produto

8.1. Os alertas mantêm-se **informação genérica + monitorização de estado**. **Nunca** conclusões jurídicas individualizadas.
8.2. **Linguagem condicional e genérica** + disclaimer **"informação, não aconselhamento jurídico"** em cada alerta (Anexo 3 canónico é o exemplo aprovado).
8.3. **Responsabilidade/T&C:** teto = **total pago nos 24 meses** anteriores ao facto (fixo), **sem** excluir dolo/negligência grave/danos a pessoas nem direitos imperativos do consumo; serviço descrito como **ferramenta informativa, não garantia de conformidade** (`termos.html §6`). **Enquanto não houver apólice E&O contratada, não se promete seguro nos T&C.**

---

## 9. Ciclo-cliente (consent-first/transacional) — regras que o GESTOR-DE-CLIENTE obedece

9.1. **Regime distinto do cold:** dados de **pessoas identificadas que consentiram** (opt-in/transacional), domínio **`checkal.pt`/Resend** — **nunca** misturar no mesmo contexto de modelo com dados frios de prospects.
9.2. **G4 embebido:** nenhuma saída afirma `cancelado`/`ilegal`/`sem seguro` de sinal único; registo sinalizado descreve-se como **"em verificação"**. Falha de rede → `indeterminado`, nunca `cancelado`.
9.3. **Injeção de dependências universal:** onboarding/dunning/suporte/fulfillment **nunca** criam clientes HTTP — recebem seams injetados.
9.4. **Escalação de suporte reimposta em código** (`suporte._deve_escalar`): jurídico/reclamação/cancelar_queixa/confiança baixa/IA indisponível → escala ao dono. **Na dúvida, escala** (fail-safe).
9.5. **Relatório mensal anti-churn** ("o teu AL passou no check ✓") é **transacional, não alerta** (sem disclaimer de aconselhamento) — mas o **envio em massa passa pelo gate 1-clique** do Maestro.
9.6. **Risco fiscal TOConline:** exige **smoke-test de emissão real** (ATCUD + `document_hash_sum` preenchidos) antes de apontar tráfego Stripe real — senão FR fiscal duplicada em reentregas de webhook (L1). Guardas G2 (`FaturaNaoCertificada`) / G3 (`TotalInesperado`) são bloqueantes.

---

## 10. AI Act art. 50 — transparência (aplicável desde 2/ago/2026)

10.1. **Todo o conteúdo gerado por IA e dirigido a pessoas** (cold, nurture, respostas de suporte, alertas redigidos por modelo, páginas) leva **divulgação de IA legível** — o linter (§7.5) bloqueia o que não a tiver.
10.2. A divulgação é **cumulativa** com opt-out, link de fonte e disclaimer — nenhuma substitui as outras.

---

## 11. Human-in-the-loop — o que EXIGE aprovação 1-clique do dono (via Maestro)

Ações **irreversíveis externas**, sempre gated: **envio em massa** (cold ou nurture), **publicação de páginas públicas**, **emissão de faturas**, **cobranças**, **qualquer post público**. Os agentes fazem tudo **até ao gate** de forma autónoma e deixam em fila de revisão/`pendentes_parecer`. Ações de risco mínimo **já provadas** podem ser promovidas a **auto-aprovação por config** — decisão do dono, não do executor.

---

## 12. Sequência de portões externos ainda por abrir (fora de código — decisão do dono)

Cold só dispara quando, **em ordem**: (1) **parecer favorável** do jurista RGPD → `CHECKAL_PARECER_RGPD_OK=True`; (2) **`CHECKAL_MODO_TESTE=False`**; (3) **`COLD_SMTP_*`** de `getcheckal.com` configurado; (4) **seguro E&O** cotado/contratado antes de escalar; (5) **feed DGC** ligado. Até lá, o motor está **tão pronto quanto pode estar** e permanece hard-gated por código.

Fontes: `checkal/app/config.py` (COIMA, JANELA=72, CAP=20, CONSERVACAO=6, gates), `checkal/app/compliance/{nif,email,minimizacao,optout}.py`, `checkal/app/campanhas/{motor,segmentacao,gatilhos,cold_email}.py`, `LEGAL-PARECER-DECISOES.md` §§5–8.