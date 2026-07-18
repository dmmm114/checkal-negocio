"""Esquema de estado partilhado do ENXAME (ADITIVO a app/models.py).

Fecha o loop entre o backbone determinista (registos/eventos_registo/
eventos_regulatorios/clientes/alertas/leads/optouts) e os 4 agentes single-shot
(MAESTRO / ANGARIADOR / GESTOR-DE-CLIENTE / SENTINELA-SERVICO). Nenhuma tabela
aqui substitui as existentes — só persiste o que hoje vive em memória
(RascunhoFrio), o que não tem casa (fila de aprovação humana, ledger de outreach,
faturas recorrentes, rollups de métricas) e reforça a supressão a nível de NIF.

Portabilidade (dev=SQLite, prod=Postgres): SÓ tipos portáveis — Integer, Text,
Date, Boolean, JSON (nunca JSONB/ARRAY), DateTime(timezone=True). Dinheiro em
Integer de CÊNTIMOS (exato, portável — nunca float). Reutiliza-se app.db.Base e
o alias _TS já definidos no models.py.

Nota de nomes: nas specs dos executores a fila de aprovação aparece como
`fila_revisao` — **é** a tabela `revisao_itens` daqui (nome único; não duplicar).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, Text,
    Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

_TS = DateTime(timezone=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. EVENTOS — journal append-only da camada de AGENTES (o "event bus" do enxame)
# ─────────────────────────────────────────────────────────────────────────────
class EventoAgente(Base):
    """Log append-only de tudo o que um agente FEZ ou DETETOU numa passagem.

    Distinto de `eventos_registo`/`eventos_regulatorios` (diffs do DOMÍNIO): este é
    a camada de OPERAÇÃO do enxame. É a fonte de verdade que o MAESTRO lê para
    compor o digest diário e onde o SENTINELA regista os seus achados de integridade.
    Append-only e imutável: nunca se faz UPDATE — corrige-se com um novo evento.
    """

    __tablename__ = "eventos_agente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente: Mapped[str] = mapped_column(Text, nullable=False)      # maestro|angariador|gestor|sentinela
    execucao_id: Mapped[str | None] = mapped_column(Text)          # UUID da invocação single-shot (correlaciona uma passagem)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)        # execucao_inicio|execucao_fim|detecao|escalada|erro|achado|deadman
    severidade: Mapped[str] = mapped_column(Text, default="info", nullable=False)  # info|aviso|critico
    # Ponteiro polimórfico opcional para a entidade a que o evento se refere.
    ref_tipo: Mapped[str | None] = mapped_column(Text)            # 'campanha'|'contacto'|'revisao'|'cliente'|'registo'|'fatura'
    ref_id: Mapped[str | None] = mapped_column(Text)             # id como texto (PKs heterogéneas: int nr_registo, nif, ...)
    mensagem: Mapped[str | None] = mapped_column(Text)          # frase legível p/ o digest
    payload: Mapped[dict | None] = mapped_column(JSON)         # métricas/contexto estruturado (ex.: {"freshness_h": 80})
    escalado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # já foi ao dono via digest/push?
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)

    __table_args__ = (
        # O digest e o Sentinela varrem por agente/severidade/tempo e por "ainda não escalado".
        Index("ix_evento_agente_tempo", "agente", "criado_em"),
        Index("ix_evento_por_escalar", "escalado", "severidade"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. CAMPANHAS — persiste a passagem de aquisição + cada peça (hoje só RascunhoFrio em memória)
# ─────────────────────────────────────────────────────────────────────────────
class Campanha(Base):
    """Uma passagem de aquisição do ANGARIADOR (o resultado de correr_campanhas).

    Hoje ResultadoCampanha vive só em memória; sem persistir, o Maestro não pode
    reportar funil nem o rollup de métricas por campanha existir. 1 linha por passagem.
    """

    __tablename__ = "campanhas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canal: Mapped[str] = mapped_column(Text, nullable=False)       # cold_email|carta|consent_first
    motivo: Mapped[str | None] = mapped_column(Text)             # MOTIVO_NOVO|MOTIVO_ALTERACAO|MOTIVO_LIMPEZA (gatilhos.py)
    origem: Mapped[str | None] = mapped_column(Text)            # ORIGEM_EVENTO_REGISTO|ORIGEM_EVENTO_REGULATORIO
    concelho: Mapped[str | None] = mapped_column(Text)
    execucao_id: Mapped[str | None] = mapped_column(Text)        # liga aos EventoAgente da mesma invocação
    n_gatilhos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_elegiveis: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # coletivas 5/6 + genérico pós-optout
    n_enviados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_pendentes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # ficaram em pendentes_parecer
    n_descartados: Mapped[int] = mapped_column(Integer, default=0, nullable=False) # singular/pessoal/opt-out
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)


class CampanhaPeca(Base):
    """Persistência durável do RascunhoFrio: 1 peça (email composto) por contacto.

    É a materialização do que motor.correr_campanhas devolve em .enviados/
    .pendentes_parecer. Fica em `pendente_parecer` até o gate abrir e o dono aprovar
    (via revisao_itens). Minimização: SÓ campos de coletiva — nunca dados de singular.
    """

    __tablename__ = "campanha_pecas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campanha_id: Mapped[int] = mapped_column(ForeignKey("campanhas.id"), nullable=False)
    nif: Mapped[str] = mapped_column(Text, nullable=False)         # coletiva 5/6 (chave de contacto)
    email_generico: Mapped[str] = mapped_column(Text, nullable=False)  # geral@/info@/reservas@
    nome_coletiva: Mapped[str | None] = mapped_column(Text)
    nr_registo: Mapped[int | None] = mapped_column(Integer)        # contexto RNAL (não PK)
    concelho: Mapped[str | None] = mapped_column(Text)
    passo: Mapped[str] = mapped_column(Text, default="d0", nullable=False)  # d0|d4|d10 (prospeccao.SEQUENCIA)
    assunto: Mapped[str | None] = mapped_column(Text)
    corpo_html: Mapped[str | None] = mapped_column(Text)
    proveniencia: Mapped[str | None] = mapped_column(Text)         # 'rnal:email_generico_publicado' (prova de lookup)
    estado: Mapped[str] = mapped_column(Text, default="pendente_parecer", nullable=False)
    #        pendente_parecer|em_revisao|aprovado|enviado|descartado|rejeitado
    razao: Mapped[str | None] = mapped_column(Text)               # RAZAO_GATE|RAZAO_SEM_REMETENTE|RAZAO_CAP
    linter_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # passou o linter determinista?
    agendado_para: Mapped[datetime | None] = mapped_column(_TS)    # follow-up (D+4/D+10) que o agente agendou
    enviado_em: Mapped[datetime | None] = mapped_column(_TS)
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)

    __table_args__ = (
        # Não repetir o mesmo passo à mesma coletiva na mesma campanha (idempotência da cadência).
        UniqueConstraint("campanha_id", "nif", "passo", name="uq_peca_campanha_nif_passo"),
        Index("ix_peca_estado", "estado", "agendado_para"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. REVISAO — a FILA DE APROVAÇÃO HUMANA (o único portão human-in-the-loop do Maestro)
# ─────────────────────────────────────────────────────────────────────────────
class RevisaoItem(Base):
    """Fila 1-clique por camadas de risco. Toda a ação irreversível externa passa aqui.

    O agente compõe tudo ATÉ este ponto autonomamente e cria um item `pendente`;
    o dono aprova/rejeita no digest. Ações de risco mínimo já provadas podem nascer
    `auto_aprovado` por config. NÃO guarda o conteúdo — aponta para a peça/página/fatura
    via ref_tipo/ref_id, para não duplicar (fonte única).

    Extensões exigidas pelo MAESTRO: `token_aprovacao` (o convite 1-clique gerado
    pelo Maestro; quem propõe nunca aprova) e `camada_risco` (1 mínimo … 4 máximo).
    Campos de fila-de-trabalho (`tentativas`/`nao_antes_de`/`lease_ate`) suportam o
    padrão drain/lease/backoff do executor determinista sobre itens JÁ aprovados.
    """

    __tablename__ = "revisao_itens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)        # cold_email|nurture|pagina_publica|fatura|cobranca|post
    risco: Mapped[str] = mapped_column(Text, nullable=False)       # baixo|medio|alto (a camada que o dono aprova em bloco)
    camada_risco: Mapped[int] = mapped_column(Integer, default=4, nullable=False)  # 1 mínimo … 4 máximo (default conservador)
    estado: Mapped[str] = mapped_column(Text, default="pendente", nullable=False)
    #        pendente|aprovado|rejeitado|auto_aprovado + ciclo de drain: a_correr|feito|falhado|morto
    agente_origem: Mapped[str | None] = mapped_column(Text)        # quem propôs (nunca é o maestro — conflito de interesse)
    ref_tipo: Mapped[str | None] = mapped_column(Text)            # 'campanha_peca'|'pagina'|'fatura'|'alerta'
    ref_id: Mapped[str | None] = mapped_column(Text)
    resumo: Mapped[str | None] = mapped_column(Text)             # linha para o digest
    linter_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linter_achados: Mapped[dict | None] = mapped_column(JSON)     # o que o linter assinalou (se algo)
    token_aprovacao: Mapped[str | None] = mapped_column(Text)     # gerado pelo MAESTRO; validado em aprovar()
    nota: Mapped[str | None] = mapped_column(Text)              # nota do DONO ao decidir
    # — fila de trabalho (drain lease/backoff sobre itens aprovados) —
    tentativas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_tentativas: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    nao_antes_de: Mapped[datetime | None] = mapped_column(_TS)    # backoff exponencial
    lease_ate: Mapped[datetime | None] = mapped_column(_TS)       # lease/visibilidade; expira ⇒ re-elegível
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)
    decidido_em: Mapped[datetime | None] = mapped_column(_TS)
    decidido_por: Mapped[str | None] = mapped_column(Text)       # 'dono' | 'auto' (config de auto-aprovação)

    __table_args__ = (
        # O digest do Maestro pesca "o que está pendente, por risco, mais antigo primeiro".
        Index("ix_revisao_fila", "estado", "risco", "criado_em"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONTACTOS — ledger de outreach a COLETIVAS, keyed por NIF, com opt-out
# ─────────────────────────────────────────────────────────────────────────────
class ContactoColetiva(Base):
    """Livro-razão durável de outreach a coletivas — chave natural = NIF.

    O motor é minimização pura (geradores que descartam no ato, não materializam);
    mas o ENXAME precisa de memória para (a) NÃO recontactar sobre dados estagnados,
    (b) saber em que passo da cadência vai cada coletiva, (c) respeitar opt-out a nível
    de IDENTIDADE (o NIF é estável; o geral@ pode mudar). SÓ dados de coletiva — nenhum
    campo de singular (o NIF aqui é sempre 5/6; singular nunca chega a esta tabela).
    """

    __tablename__ = "contactos_coletiva"

    nif: Mapped[str] = mapped_column(Text, primary_key=True)       # 9 díg., 1.º ∈ {5,6} — chave natural
    email_generico: Mapped[str | None] = mapped_column(Text)      # último genérico usado
    nome_coletiva: Mapped[str | None] = mapped_column(Text)
    concelho: Mapped[str | None] = mapped_column(Text)
    primeiro_contacto_em: Mapped[datetime | None] = mapped_column(_TS)
    ultimo_contacto_em: Mapped[datetime | None] = mapped_column(_TS)
    ultimo_passo: Mapped[str | None] = mapped_column(Text)        # d0|d4|d10
    n_toques: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estado: Mapped[str] = mapped_column(Text, default="ativo", nullable=False)
    #        ativo|respondeu|converteu|opt_out|esgotado
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # supressão a nível de NIF
    opt_out_em: Mapped[datetime | None] = mapped_column(_TS)
    proveniencia: Mapped[str | None] = mapped_column(Text)        # 'rnal:email_generico_publicado'

    __table_args__ = (
        Index("ix_contacto_estado", "estado"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. FATURACAO — ledger de faturas-recibo (recorrência que os ix_* de Cliente não cobrem)
# ─────────────────────────────────────────────────────────────────────────────
class Fatura(Base):
    """1 linha por fatura-recibo certificada emitida (checkout OU renovação anual).

    Os `ix_*` em `clientes` guardam SÓ a última/primeira fatura; a subscrição de
    49€/ano renova e emite N faturas ao longo dos anos — o MRR e a receita por canal
    exigem histórico. Idempotência dura: `stripe_invoice_id` e `ix_fatura_id` únicos
    (a reentrega de webhook não pode gerar 2.º documento fiscal — irreversível).
    """

    __tablename__ = "faturas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), nullable=False)
    stripe_invoice_id: Mapped[str | None] = mapped_column(Text, unique=True)  # idempotência da renovação
    ix_fatura_id: Mapped[str | None] = mapped_column(Text, unique=True)       # id documento (provider)
    ix_atcud: Mapped[str | None] = mapped_column(Text)          # ATCUD (guarda G2: sem isto = não certificada)
    ix_permalink: Mapped[str | None] = mapped_column(Text)
    serie: Mapped[str | None] = mapped_column(Text)            # série CKL
    plano: Mapped[str | None] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(Text)           # 'checkout' | 'subscription_cycle' (G1)
    total_cents: Mapped[int | None] = mapped_column(Integer)   # dinheiro em cêntimos (exato)
    iva_cents: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(Text, default="emitida", nullable=False)  # emitida|falhada|anulada
    emitida_em: Mapped[datetime | None] = mapped_column(_TS)

    __table_args__ = (
        Index("ix_fatura_cliente", "cliente_id", "emitida_em"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. METRICAS — rollups por canal/campanha/dia (o que o Maestro lê para o digest)
# ─────────────────────────────────────────────────────────────────────────────
class MetricaRollup(Base):
    """Rollup determinista por (dia, canal, campanha, métrica). Upsert idempotente.

    O Maestro NÃO recalcula funil varrendo tabelas cruas a cada passagem — lê daqui.
    UNIQUE(dia, canal, campanha_id, metrica) permite upsert: reprocessar o dia
    sobrescreve, nunca duplica. campanha_id NULL = agregado do canal (ex. transacional).
    """

    __tablename__ = "metricas_rollup"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    canal: Mapped[str] = mapped_column(Text, nullable=False)       # cold|consent|transacional|nurture|dunning
    campanha_id: Mapped[int | None] = mapped_column(Integer)      # NULL = agregado do canal
    metrica: Mapped[str] = mapped_column(Text, nullable=False)
    #        enviados|entregues|abertos|opt_outs|respostas|conversoes|pendentes_parecer|receita_cents|clientes_ativos|em_dunning
    valor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # contagens ou cêntimos
    atualizado_em: Mapped[datetime | None] = mapped_column(_TS)

    __table_args__ = (
        UniqueConstraint("dia", "canal", "campanha_id", "metrica", name="uq_metrica_dia_canal_camp"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. REFORÇO DE SUPRESSÃO — supressão a nível de NIF (complementa OptOut, que é por email)
# ─────────────────────────────────────────────────────────────────────────────
class SupressaoNif(Base):
    """"Não contactar" a nível de IDENTIDADE LEGAL (NIF), a par do OptOut por email.

    `OptOut` (existente) suprime um EMAIL; mas uma coletiva pode opor-se e depois
    reaparecer com outro genérico. `SupressaoNif` fixa a oposição à ENTIDADE. Tal como
    `optouts`, é lista de conservação PERMANENTE — NUNCA é apagada pela limpeza de
    prospects (CONSERVACAO_PROSPECT_MESES). O cruzamento no envio passa a ser duplo:
    e-mail ∉ optouts  E  nif ∉ supressao_nif.
    """

    __tablename__ = "supressao_nif"

    nif: Mapped[str] = mapped_column(Text, primary_key=True)       # chave natural, normalizado (só dígitos)
    origem: Mapped[str | None] = mapped_column(Text)             # 'dgc' | 'opt_out_email' | 'reclamacao' | 'manual'
    criado_em: Mapped[datetime | None] = mapped_column(_TS)


# ─────────────────────────────────────────────────────────────────────────────
# 8. GOVERNAÇÃO — aprovações, escalações, execuções, digests e custo LLM
# ─────────────────────────────────────────────────────────────────────────────
class Aprovacao(Base):
    """1 linha por DECISÃO do dono sobre um item da fila de revisão.

    Materializa a separação de poderes: o `autor` (executor que propôs) NUNCA é o
    `decidido_por` (o dono, ou 'auto' quando uma camada de risco mínimo foi
    explicitamente promovida por config). O CHECK é código, não disciplina.
    """

    __tablename__ = "aprovacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revisao_item_id: Mapped[int] = mapped_column(Integer, nullable=False)  # → revisao_itens.id
    autor: Mapped[str] = mapped_column(Text, nullable=False)       # agente que propôs (angariador|gestor|sentinela)
    decidido_por: Mapped[str] = mapped_column(Text, nullable=False)  # 'dono' | 'auto' — nunca o autor
    decisao: Mapped[str] = mapped_column(Text, nullable=False)     # aprovado|rejeitado
    token_usado: Mapped[str | None] = mapped_column(Text)         # o token 1-clique que validou a decisão
    nota: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)

    __table_args__ = (
        CheckConstraint("autor <> decidido_por", name="ck_aprovacao_autor_diferente"),
        Index("ix_aprovacao_item", "revisao_item_id"),
    )


class Escalacao(Base):
    """O que um executor escalou ao MAESTRO (e o Maestro consolida para o dono)."""

    __tablename__ = "escalacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente: Mapped[str] = mapped_column(Text, nullable=False)      # quem escalou
    severidade: Mapped[str] = mapped_column(Text, nullable=False)  # baixa|media|alta|critica
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    execucao_id: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text, default="aberta", nullable=False)  # aberta|consolidada|resolvida
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)
    consolidada_em: Mapped[datetime | None] = mapped_column(_TS)

    __table_args__ = (
        Index("ix_escalacao_estado", "estado", "severidade"),
    )


class AgenteExecucao(Base):
    """1 linha por invocação single-shot de um executor (saúde + custo + arbitragem).

    O runner determinista (`maestro-run`) escreve iniciado/terminado/estado/exit_code;
    o MAESTRO-LLM apenas ANOTA `retry_pedido`/`backoff_s` — o re-spawn é sempre do
    runner determinista, nunca do modelo.
    """

    __tablename__ = "agente_execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente: Mapped[str] = mapped_column(Text, nullable=False)      # angariador|gestor|sentinela|maestro
    execucao_id: Mapped[str | None] = mapped_column(Text)          # UUID (correlaciona com eventos_agente)
    modo: Mapped[str | None] = mapped_column(Text)                # governanca|digest|None
    iniciado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)
    terminado_em: Mapped[datetime | None] = mapped_column(_TS)
    estado: Mapped[str] = mapped_column(Text, default="a_correr", nullable=False)  # a_correr|ok|falhou|morto
    exit_code: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    retry_pedido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # anotação do MAESTRO
    backoff_s: Mapped[int | None] = mapped_column(Integer)
    detalhe: Mapped[str | None] = mapped_column(Text)             # stderr curto / motivo da falha

    __table_args__ = (
        Index("ix_execucao_agente_tempo", "agente", "iniciado_em"),
    )


class Digest(Base):
    """1 linha por digest composto pelo MAESTRO (o resumo diário ao dono)."""

    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    corpo_md: Mapped[str] = mapped_column(Text, nullable=False)
    metricas_json: Mapped[dict | None] = mapped_column(JSON)       # snapshot das métricas do dia
    enviado_em: Mapped[datetime | None] = mapped_column(_TS)       # NULL = composto mas não entregue (gates fechados)
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)

    __table_args__ = (
        Index("ix_digest_dia", "dia"),
    )


class Pagamento(Base):
    """1 linha por intenção/confirmação de pagamento via IfThenPay (Fase G).

    A via cold-direto da ADENDA: o email frio leva um CTA "Pagar já" com token
    assinado SEM PII → `checkal.pt/pagar` capta NIF+email+T&C ANTES de gerar o
    método AO VIVO (Opção A). MB ref/MB Way confirmam por callback (antiphishing
    obrigatória, idempotente por `order_id`); transferência fica `por_casar` até
    o GESTOR reconciliar. Fatura (TOConline série CKL) e onboarding SÓ disparam
    com o pagamento confirmado. NÃO está nas tabelas de governação: nenhum
    agente escreve aqui diretamente.
    """

    __tablename__ = "pagamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # prefixo CKL
    campanha_id: Mapped[int | None] = mapped_column(Integer)   # origem (token do cold)
    nr_registo: Mapped[int | None] = mapped_column(Integer)    # AL pré-preenchido (token)
    plano: Mapped[str] = mapped_column(Text, nullable=False)   # chave de config.PLANOS
    valor_cent: Mapped[int] = mapped_column(Integer, nullable=False)  # cêntimos (exato)
    metodo: Mapped[str] = mapped_column(Text, nullable=False)  # mbref|mbway|transferencia
    estado: Mapped[str] = mapped_column(Text, default="pendente", nullable=False)
    #        pendente|pago|expirado|por_casar|falhado
    ifthenpay_ref: Mapped[str | None] = mapped_column(Text)    # entidade+referência MB
    ifthenpay_id: Mapped[str | None] = mapped_column(Text)     # RequestId do MB Way
    nif: Mapped[str] = mapped_column(Text, nullable=False)     # captado ANTES de gerar
    email: Mapped[str] = mapped_column(Text, nullable=False)
    tc_versao: Mapped[str | None] = mapped_column(Text)        # prova de aceitação dos T&C
    tc_aceite_em: Mapped[datetime | None] = mapped_column(_TS)
    criado_em: Mapped[datetime] = mapped_column(_TS, nullable=False)
    pago_em: Mapped[datetime | None] = mapped_column(_TS)

    __table_args__ = (
        Index("ix_pagamento_estado", "estado", "criado_em"),
    )


class CustoLlm(Base):
    """Custo de inferência por (dia, agente) — alimenta os tetos (`swarm/tetos.py`).

    `custo_eur_cent` guarda CÊNTIMOS de euro (Integer, exato) com arredondamento
    SEMPRE por excesso no registo — o teto dispara mais cedo, nunca mais tarde
    (direção segura). Os tokens ficam exatos para auditoria/recalculo.
    """

    __tablename__ = "custo_llm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    agente: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    custo_eur_cent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # cêntimos (por excesso)
    criado_em: Mapped[datetime | None] = mapped_column(_TS)

    __table_args__ = (
        Index("ix_custo_dia_agente", "dia", "agente"),
    )
