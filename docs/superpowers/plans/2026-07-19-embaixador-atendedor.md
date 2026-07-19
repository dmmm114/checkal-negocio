# EMBAIXADOR + Atendimento pré-vendas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agente EMBAIXADOR completo (deteção compliance-gated de candidatos a parceiro + propostas B2B na fila) e atendimento com categoria pré-vendas nos dois caminhos de suporte — tudo atrás dos gates existentes.

**Architecture:** Padrão do enxame provado hoje 6×. Deteção determinista em `app/embaixador.py` (reutiliza `app/compliance` — nunca reimplementa); subcomandos manage.py; `proposta_parceria`→`Canal.COLD`; prompt/wrapper/timer; dashboard 7.º cartão. Pré-vendas: categoria nova sincronizada em `suporte.py` (CATEGORIAS+ESQUEMA+_SISTEMA_REGRAS), FAQ canónica, regex refinada com testes bidirecionais, prompt do gestor.

**Spec:** `docs/superpowers/specs/2026-07-19-embaixador-atendedor-design.md`. **Regras do repo:** TDD; `git add` explícito; suite `-p no:warnings` (nota: `-q` extra esconde o sumário); PT-PT.

**Referências de padrão (o implementador LÊ antes de cada task):** deteção → `app/campanhas/segmentacao.py` + `app/compliance/{nif,email,minimizacao,optout}.py`; subcomandos → secção COMUNICADOR/EDITOR de manage.py; prompt → `prompts/angariador.txt`; timer/wrapper → fase 1 (commits `21b5552`, `bf891f3`); dashboard → Task 9 de hoje (AGENTES/ACORDAR_INSTANCIA/UNITS_RESET/sudoers/título).

---

### E1: Categoria `pre_venda` + FAQ canónica + regex refinada

**Files:** Modify `checkal/app/suporte.py` (CATEGORIAS, ESQUEMA_SUPORTE, _SISTEMA_REGRAS, FAQ), `checkal/manage.py` (`_RE_SUPORTE_SENSIVEL`); Test: os ficheiros de teste existentes do suporte (localiza com grep `suporte` em tests/ — NÃO partas nenhum) + casos novos.

- [ ] TDD. Testes novos primeiro: (a) triagem aceita categoria `pre_venda` sem escalar (não está em GATILHOS_ESCALACAO; `_deve_escalar` devolve False com confianca alta/media); (b) `gestor suporte-triar` com resposta pré-vendas que descreve o produto ("vigiamos os regulamentos municipais do teu concelho") NÃO escala e enfileira `suporte_rascunho`; (c) resposta com uso prescritivo ("o regulamento do Porto proíbe X") CONTINUA a escalar alta; (d) os gatilhos sensíveis existentes todos intactos (corre os testes atuais do suporte).
- [ ] `suporte.py`: `CATEGORIAS = (..., "pre_venda")`; ESQUEMA_SUPORTE enum sincronizado; `_SISTEMA_REGRAS` ganha a definição (interessado sem subscrição a perguntar preço/funcionamento ⇒ responder, tom "inspetor amigo", CTA suave check grátis, nunca "AL legal"); GATILHOS_ESCALACAO INTOCADO.
- [ ] FAQ: completa com a tabela canónica do PRICING.md (Portfólio trienal 359€; +45€/3 anos por AL adicional) — compara linha a linha com PRICING.md §1 e corrige QUALQUER divergência.
- [ ] Regex: em `_RE_SUPORTE_SENSIVEL`, substitui o token solto `regulament` por `regulamento\s+(?:pro[íi]be|obriga|exige|impede|imp[õo]e)` mantendo TODO o resto byte-igual. Comentário: porquê (descrição do produto vs prescrição jurídica).
- [ ] Suite completa; commit `feat(atendimento): categoria pre_venda + FAQ canónica + regex sensível refinada`.

### E2: Prompt do gestor com bloco pré-vendas

**Files:** `checkal/prompts/gestor.txt` + `agentes-polaris/prompts/gestor.txt` (byte-idênticos no fim; ATENÇÃO: confirma se já estão em sincronia antes — se divergirem, base = checkal/prompts/).

- [ ] Bloco novo no passo de suporte: quando a triagem der `pre_venda`, redigir com: factos SÓ da tabela canónica (49€/119€/+19€; Portfólio 149-299-499€, trienal 359€); claims do PRODUTO.md (monitorização diária, seguro, regulamentos municipais, relatório mensal, selo, alertas <1h); CTA único "faz o check grátis — 30 segundos, sem cartão"; tom inspetor amigo; NUNCA "AL legal/certificado", NUNCA coima como ameaça, NUNCA desconto fora de tabela. Nota RGPD do spec (responder a pedido direto do titular). Diff vazio entre árvores; commit.

### E3: `app/embaixador.py` (deteção) + subcomandos

**Files:** Create `checkal/app/embaixador.py`; Modify `checkal/manage.py` (secção EMBAIXADOR + parser + docstring FASE D + maestro-saude tuplo + maestro-retry choices); Test: `checkal/tests/test_embaixador.py` (novo).

- [ ] TDD com BD temporária (fixture padrão): seed de registos coletiva/singular/multi-AL/email genérico e pessoal. Testes: deteção respeita limiar e devolve SÓ coletivas endereçáveis com email genérico (formato ContactoEnderecavel + agregados); autoridade é `e_enderecavel` (um `titular_tipo='coletiva'` com NIF 7x fica fora); dedupe exclui NIF com proposta existente na fila; opt-out exclui; singular NUNCA aparece no output; `enfileirar --tipo proposta_parceria` cria item Canal.COLD camada 4 com EventoAgente payload {nif, corpo_texto}; texto reprovado (sem R8/R9) ⇒ exit 1 nada inserido; `estado` conta por estado.
- [ ] `app/embaixador.py`: `detetar_candidatos(session, *, limiar=5, max_candidatos=10) -> list[dict]` — pré-filtro SQL + portão compliance + dedupe (query a revisao_itens tipo proposta_parceria via ref/payload nif em eventos_agente — escolhe o join mais simples e documenta) + agregados. Docstring: minimização, autoridade compliance, GTM §5/6.
- [ ] manage.py: `_TIPOS_EMBAIXADOR = {"proposta_parceria": ("proposta_parceria", "alto")}`; peça `Canal.COLD` com `tem_optout_carimbado=True` (o seam de envio carimba, como o cold do angariador); handlers estado/detetar/lint/enfileirar (+ --escalar; enfileirar exige `--nif`, guarda-o no payload). Parser + docstring + maestro (saude tuplo, retry choices += "embaixador").
- [ ] Suite; commit `feat(enxame): EMBAIXADOR — deteção compliance-gated + proposta_parceria na fila`.

### E4: Prompt + wrapper + timer + docs do enxame

**Files:** Create `checkal/prompts/embaixador.txt` + `agentes-polaris/prompts/embaixador.txt`; Modify `deploy/bin/correr-agente.sh` (2 cases), `deploy/systemd/checkal-embaixador.timer` + variante `deploy/polaris/units/` (padrões das árvores!), `deploy/polaris/instalar.sh`, `AGENTES-ENXAME.md`, `checkal/app/models_swarm.py` (comentários de agentes), unit `@.service` comentário de instâncias (2 árvores).

- [ ] Prompt no padrão da casa (identidade single-shot; passagem: estado→detetar→redigir 1-3 propostas (máx cap)→lint→enfileirar; pitch canónico com comissão 20% como proposta + "termos por escrito"; limites duros: nunca envia, nunca promete comissões como facto público, dados de singulares NUNCA, só subcomandos embaixador; escala na dúvida; output JSON 1 linha; REGRA DE DADOS). Byte-idêntico nas 2 árvores.
- [ ] Wrapper: instância `embaixador` nos 2 cases (PROMPT_FILE, ARG_LLM="passagem=parcerias"; TOOLS = Read + os 4 subcomandos). `bash -n`.
- [ ] Timer Ter 10:00 (`OnCalendar=Tue 10:00`, RandomizedDelaySec conforme árvore), 2 árvores, instalar.sh (secção agentes). `systemd-analyze verify` + `calendar`.
- [ ] AGENTES-ENXAME (linha do EMBAIXADOR na tabela), models_swarm comentários (agente enums +embaixador), comentários das units. Commit.

### E5: Dashboard — 7.º cartão + sudoers + deploy

**Files (Dashboard_Polaris — ler agent-os/CLAUDE.md primeiro):** `agent-os/app/checkal.py` (AGENTES += embaixador 🤵 "Parcerias", instancias ["embaixador"], timers ["checkal-embaixador.timer"]), `agent-os/app/checkal_acoes.py` (ACORDAR_INSTANCIA, UNITS_RESET), `agent-os/app/static/app.js` ("6 agentes"→"7 agentes"), `instalar-acoes-checkal.sh` (4 linhas sudoers), CLAUDE.md×2 ("6"→"7"), PROGRESSO-REDESIGN entrada nova.

- [ ] Editar fonte; py_compile + node --check; copiar para /home/diogo/agent-os/app/ (+ CLAUDE.md se lá existir); restart pelo procedimento EXATO; verificar snapshot() devolve 7 agentes com embaixador, processo na 8100, log limpo. Sem commit (não é git).

### E6: Site — opção pré-venda no contacto (repo aninhado)

**Files:** `site/contacto.html` (option "Comercial / pré-venda" value=comercial no select de assunto), `site/functions/api/contacto.js` (DESTINOS += comercial: "comercial@checkal.pt").

- [ ] Editar; commit no repo site/ ("contacto: assunto comercial/pré-venda") SEM push. Confirma repo site limpo antes/depois no repo principal (gitignored).

### E7: Verificação final

- [ ] Suite completa; smoke real read-only: `manage.py embaixador detetar --limiar 5 --max 3` contra a BD real (espera ~3 candidatos minimizados, zero dados de singulares — inspeciona o output!); `embaixador estado`; revisão final de conjunto (fable) sobre o range; HANDOFF `2026-07-19-embaixador-HANDOFF.md` (o que o dono liga depois: instalar.sh para o timer novo, sudoers do dashboard, IMAP/Resend para inbound e envio, gates de cold para envio real de propostas); ESTADO-DO-PROJETO nota curta. Commits.
