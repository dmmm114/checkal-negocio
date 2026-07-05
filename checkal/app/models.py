"""Esquema ORM canónico do CheckAL (AUTOMACAO.md §1, SPEC-FDS1.md §models).

As 8 tabelas do pipeline de dados, em SQLAlchemy 2.0 (estilo `Mapped`/
`mapped_column`), todas herdando `app.db.Base`:

    registos              — o espelho local do RNAL (1 linha por AL); PK = nr_registo
    varrimentos           — 1 linha por passagem nacional (ok|parcial|abortado)
    eventos_registo       — diffs detetados (novo|alterado|desaparecido|reapareceu)
    detalhes_cliente      — detalhe individual (estado + seguro) só de pagantes
    clientes              — assinantes
    clientes_registos     — associação muitos-para-muitos cliente↔registo
    eventos_regulatorios  — documentos captados do DRE/câmaras
    alertas               — comunicações enviadas ao cliente

**Portabilidade (dev = SQLite, prod = Postgres):** usam-se apenas tipos de coluna
portáveis — `JSON` (nunca `JSONB`/`ARRAY`), `DateTime(timezone=True)` (nunca
`timestamptz`), `Text`, `Integer`, `Date`, `Boolean`. Assim o esquema materializa-se
igual em SQLite (testes) e em Postgres (produção). O mapeamento face ao SQL da
AUTOMACAO.md: `concelhos text[]` → `JSON`; `campos_alterados jsonb` → `JSON`;
`timestamptz` → `DateTime(timezone=True)`.

`registos.ausencias_consecutivas` não consta do SQL de referência mas é exigida
pela **regra dos 2 varrimentos** (SPEC diffing/ingest): guarda o nº de varrimentos
consecutivos em que o registo faltou, para só marcar `desaparecido_em` à 2.ª ausência.

**Extensão FDS 2 (aditiva, SPEC-FDS2.md §models):** tabela `webhook_eventos`
(idempotência dos webhooks Stripe por `event.id`) e colunas em `clientes`
(`stripe_session_id`, `ix_fatura_id`, `ix_atcud`, `ix_permalink`) que ligam o
assinante à sessão Stripe e à fatura-recibo certificada do InvoiceXpress.

**Extensão TOConline (aditiva, SPEC-TOCONLINE §2.2):** tabela `toconline_tokens`
(linha única) que persiste o par de tokens OAuth2 (access ~4 h / refresh ~8 h) e
as suas validades, para o cron de renovação server-to-server. As colunas fiscais
`ix_*` de `clientes` servem qualquer fornecedor por trás da mesma interface.

**Extensão FDS 3 (aditiva, SPEC-FDS3.md §base / SPEC-DETALHE §2.1/§4):** coluna
`detalhes_cliente.seguro_inicio date` — a página individual do RNAL expõe "Data
início" da apólice a par da "Validade"; guardar ambas alimenta a copy "apólice de
X a Y" e o alerta de seguro. Puramente aditiva: não quebra FDS 1/FDS 2/swap.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Alias legível para timestamps com fuso (timestamptz → portável).
_TS = DateTime(timezone=True)


class Registo(Base):
    """Espelho local de um registo RNAL (1 linha por Alojamento Local).

    `nr_registo` é a chave natural (o inteiro de "100031/AL", já cortado no `/`),
    logo PK inteira sem autoincremento. `hash_campos` resume os campos relevantes
    para diffing barato. `visto_primeiro`/`visto_ultimo` datam a presença;
    `desaparecido_em IS NULL` significa ativo; `ausencias_consecutivas` alimenta
    a regra dos 2 varrimentos.
    """

    __tablename__ = "registos"

    nr_registo: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    data_registo: Mapped[date | None] = mapped_column(Date)
    nome_alojamento: Mapped[str | None] = mapped_column(Text)
    modalidade: Mapped[str | None] = mapped_column(Text)
    nr_camas: Mapped[int | None] = mapped_column(Integer)
    nr_utentes: Mapped[int | None] = mapped_column(Integer)
    endereco: Mapped[str | None] = mapped_column(Text)
    cod_postal: Mapped[str | None] = mapped_column(Text)
    freguesia: Mapped[str | None] = mapped_column(Text)
    concelho: Mapped[str | None] = mapped_column(Text)
    distrito: Mapped[str | None] = mapped_column(Text)
    titular_tipo: Mapped[str | None] = mapped_column(Text)  # 'singular' | 'coletiva'
    titular_nome: Mapped[str | None] = mapped_column(Text)
    nif: Mapped[str | None] = mapped_column(Text)
    telefone: Mapped[str | None] = mapped_column(Text)
    telemovel: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    hash_campos: Mapped[str | None] = mapped_column(Text)
    visto_primeiro: Mapped[datetime | None] = mapped_column(_TS)
    visto_ultimo: Mapped[datetime | None] = mapped_column(_TS)
    desaparecido_em: Mapped[datetime | None] = mapped_column(_TS)  # NULL = ativo
    ausencias_consecutivas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    eventos: Mapped[list[EventoRegisto]] = relationship(
        back_populates="registo", cascade="all, delete-orphan"
    )
    clientes: Mapped[list[Cliente]] = relationship(
        secondary="clientes_registos", back_populates="registos"
    )


class Varrimento(Base):
    """Uma passagem nacional pela API RNAL (o "scan")."""

    __tablename__ = "varrimentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iniciado_em: Mapped[datetime | None] = mapped_column(_TS)
    concluido_em: Mapped[datetime | None] = mapped_column(_TS)
    concelhos_ok: Mapped[int | None] = mapped_column(Integer)
    concelhos_falhados: Mapped[int | None] = mapped_column(Integer)
    total_registos: Mapped[int | None] = mapped_column(Integer)
    raw_path: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)  # 'ok' | 'parcial' | 'abortado'


class EventoRegisto(Base):
    """Um diff detetado num registo entre estado conhecido e um varrimento.

    `campos_alterados` (JSON) guarda, para o tipo `alterado`, o mapa
    campo → [antes, depois]. `processado` marca se o evento já gerou alertas.
    """

    __tablename__ = "eventos_registo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nr_registo: Mapped[int | None] = mapped_column(ForeignKey("registos.nr_registo"))
    tipo: Mapped[str | None] = mapped_column(Text)  # novo|desaparecido|alterado|reapareceu
    campos_alterados: Mapped[dict | None] = mapped_column(JSON)
    varrimento_id: Mapped[int | None] = mapped_column(Integer)
    detetado_em: Mapped[datetime | None] = mapped_column(_TS)
    processado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    registo: Mapped[Registo | None] = relationship(back_populates="eventos")


class DetalheCliente(Base):
    """Detalhe individual (estado + seguro RC) obtido só para registos de pagantes."""

    __tablename__ = "detalhes_cliente"

    nr_registo: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    estado_detalhado: Mapped[str | None] = mapped_column(Text)
    seguro_companhia: Mapped[str | None] = mapped_column(Text)
    seguro_apolice: Mapped[str | None] = mapped_column(Text)  # texto: guarda zeros à esquerda
    # FDS 3 (aditivo, SPEC-DETALHE §2.1/§4): a página individual expõe "Data início" da
    # apólice, a par da "Validade". Guardar as duas alimenta a copy "apólice de X a Y" e
    # dá contexto ao alerta de seguro. Ordem espelha a página (início → validade).
    seguro_inicio: Mapped[date | None] = mapped_column(Date)
    seguro_validade: Mapped[date | None] = mapped_column(Date)
    obtido_em: Mapped[datetime | None] = mapped_column(_TS)


class Cliente(Base):
    """Um assinante do CheckAL."""

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    nome: Mapped[str | None] = mapped_column(Text)
    nif: Mapped[str | None] = mapped_column(Text)
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    plano: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)  # 'ativo'|'em_dunning'|'cancelado'
    criado_em: Mapped[datetime | None] = mapped_column(_TS)

    # --- FDS 2: ligação Stripe ↔ InvoiceXpress (aditivo; NULL até haver checkout/fatura) ---
    # `unique=True` é o backstop DURÁVEL da idempotência do fulfillment: a verificação
    # "já existe cliente para esta sessão?" em `app.fulfillment` é um query-then-insert
    # (TOCTOU). Com >1 worker uvicorn, a reentrega rotineira do MESMO
    # `checkout.session.completed` pela Stripe pode fazer dois processos passarem a
    # verificação e emitirem DOIS documentos fiscais certificados (ilegal de reverter).
    # A constraint garante que o 2.º INSERT falha no `flush()` — que corre ANTES da
    # emissão da fatura — pelo que o worker perdedor aborta sem reemitir. Portátil:
    # SQLite e Postgres tratam NULLs como distintos, logo clientes sem sessão coexistem.
    stripe_session_id: Mapped[str | None] = mapped_column(Text, unique=True)  # idempotência do fulfillment
    ix_fatura_id: Mapped[str | None] = mapped_column(Text)       # id do documento InvoiceXpress
    ix_atcud: Mapped[str | None] = mapped_column(Text)           # ATCUD (identificador AT)
    ix_permalink: Mapped[str | None] = mapped_column(Text)       # permalink do PDF certificado

    registos: Mapped[list[Registo]] = relationship(
        secondary="clientes_registos", back_populates="clientes"
    )


class ClienteRegisto(Base):
    """Associação muitos-para-muitos cliente↔registo (PK composta)."""

    __tablename__ = "clientes_registos"

    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id"), primary_key=True
    )
    nr_registo: Mapped[int] = mapped_column(
        ForeignKey("registos.nr_registo"), primary_key=True
    )


class EventoRegulatorio(Base):
    """Documento captado do DRE / câmaras, antes/depois da triagem IA.

    `concelhos` (JSON, era `text[]`) lista os municípios extraídos do cabeçalho;
    `url` é única (dedup da captação).
    """

    __tablename__ = "eventos_regulatorios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, unique=True)
    titulo: Mapped[str | None] = mapped_column(Text)
    publicado_em: Mapped[date | None] = mapped_column(Date)
    concelhos: Mapped[list | None] = mapped_column(JSON)
    triagem: Mapped[str | None] = mapped_column(Text)  # 'relevante'|'irrelevante'|'duvida'
    resumo_ia: Mapped[str | None] = mapped_column(Text)
    processado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Alerta(Base):
    """Uma comunicação enviada ao cliente (origem = evento de registo ou regulatório)."""

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(Integer)
    nr_registo: Mapped[int | None] = mapped_column(Integer)
    origem: Mapped[str | None] = mapped_column(Text)  # 'eventos_registo'|'eventos_regulatorios'
    origem_id: Mapped[int | None] = mapped_column(Integer)
    conteudo: Mapped[str | None] = mapped_column(Text)
    enviado_em: Mapped[datetime | None] = mapped_column(_TS)
    canal: Mapped[str] = mapped_column(Text, default="email", nullable=False)


class WebhookEvento(Base):
    """Idempotência dos webhooks Stripe (FDS 2, SPEC-FDS2.md §models).

    A Stripe reentrega webhooks (retries, entregas duplicadas/fora de ordem). Antes de
    processar um evento, grava-se aqui o `event.id`; a PoR `event_id` é a chave: uma segunda
    entrega do mesmo evento colide na PK e é rejeitada, garantindo que o fulfillment corre
    exatamente uma vez por evento. `event_id` é `Text` (portátil SQLite/Postgres).
    """

    __tablename__ = "webhook_eventos"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)  # ex. 'evt_...'
    tipo: Mapped[str | None] = mapped_column(Text)  # ex. 'checkout.session.completed'
    recebido_em: Mapped[datetime | None] = mapped_column(_TS)


class ToconlineToken(Base):
    """Estado da autenticação OAuth2 server-to-server do TOConline (SPEC-TOCONLINE §2.2).

    **Linha única** (por convenção `id=1`): o TOConline não tem grant
    `client_credentials`, só `authorization_code` (consentimento humano único no
    arranque) + `refresh_token`. O `access_token` vale ~4 h e o `refresh_token`
    ~8 h e **roda** a cada renovação — por isso um cron externo renova de ~3–4 h e
    **persiste sempre o novo par**. A emissão de faturas nunca conhece OAuth (o
    `cliente_http` é injetado já autenticado); esta tabela é só a persistência do
    estado, para o cron saber o que renovar e quando alarmar o dono.

    Portátil (SQLite/Postgres): `Text` para os tokens, `DateTime(timezone=True)`
    para as validades. Sem segredos no código — os tokens só existem em runtime.
    """

    __tablename__ = "toconline_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str | None] = mapped_column(Text)
    access_expira_em: Mapped[datetime | None] = mapped_column(_TS)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    refresh_expira_em: Mapped[datetime | None] = mapped_column(_TS)
    atualizado_em: Mapped[datetime | None] = mapped_column(_TS)
