"""Motor de campanhas (FDS 6, SPEC-FDS6.md §motor) — gatilho → segmento → envio.

Orquestra, sem toque humano, a prospeção a frio B2B do CheckAL:

    gatilhos  →  segmentação (núcleo de compliance)  →  composição da copy  →
      · segmento COLD  → só ENVIA (via `remetente_frio` injetado) se
        `pode_enviar_frio(contacto)` for True; caso contrário o draft fica em fila
        `pendentes_parecer` (composto, não enviado);
      · segmento CARTA → gera o PDF multi-carta (upload manual e-carta CTT).

🚦 **O PORTÃO é CÓDIGO, não disciplina** (o coração deste sprint). O canal frio
eletrónico é PROIBIDO até o dono ter o parecer favorável do jurista RGPD (CLAUDE.md
/ LEGAL.md §1). É por isso que:

  - `pode_enviar_frio(contacto)` só devolve True se, CUMULATIVAMENTE:
      1. `config.pode_enviar_frio_global()` — parecer OK **e** modo de teste OFF
         **e** SMTP de cold configurado;
      2. o contacto passa o núcleo de compliance — coletiva 5/6
         (`nif.e_enderecavel`) **e** email genérico (`email.e_generico`), através de
         `minimizacao.filtrar_enderecaveis`;
      3. **não** consta da oposição DGC nem do opt-out (`optout.filtrar_optout`).
  - Com `CHECKAL_PARECER_RGPD_OK=False` (o default), um registo novo coletivo-
    genérico gera o draft mas **fica pendente_parecer** — nada sai. Um registo de
    pessoa singular gera **carta** e NUNCA cold.

FRONTEIRA DURA (SPEC-RESEND §0): o cold vive num módulo separado sobre
`getcheckal.com` (`app.campanhas.cold_email`) — este motor **nunca** importa nem
toca a Resend (`app.envio`); partilhar reputação com `checkal.pt` suspenderia a
conta transacional e derrubaria os alertas dos clientes pagantes.

Fronteira transacional (igual a `app.campanhas.gatilhos` / `app.alertas_estado`):
`correr_campanhas` recebe a `session` do chamador e **não faz commit** — a transação
é do orquestrador (o cron do wire, sob `db.get_session`). Um rollback do chamador
desfaz os marcadores de idempotência e os eventos ficam por usar (retry natural).

Política de volume (não são segredos): a janela `config.CAMPANHA_JANELA_H` (72h) é o
SLA "evento → prospeção correspondente" — eventos mais antigos que a janela são
**deliberadamente saltados** (nunca se prospeta a frio sobre dados estagnados de um
cron parado). O `config.CAMPANHA_CAP_DIARIO` limita os **envios** por passagem
(warm-up do domínio irmão): o excedente elegível fica em fila (`RAZAO_CAP`).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import app.config as config
import app.models as models
from app.campanhas import carta, segmentacao
from app.campanhas.gatilhos import (
    LIMIAR_LIMPEZA,
    MOTIVO_ALTERACAO,
    ORIGEM_EVENTO_REGISTO,
    ORIGEM_EVENTO_REGULATORIO,
    detetar_gatilhos,
)
from app.compliance import minimizacao, optout

__all__ = [
    "RAZAO_GATE",
    "RAZAO_SEM_REMETENTE",
    "RAZAO_CAP",
    "RascunhoFrio",
    "ResultadoCampanha",
    "pode_enviar_frio",
    "compor_email_frio",
    "correr_campanhas",
]

# --- Razões pelas quais um cold ficou por enviar (fica em `pendentes_parecer`) ---
RAZAO_GATE = "gate_fechado"          # `pode_enviar_frio` False (parecer/modo/SMTP/compliance/optout)
RAZAO_SEM_REMETENTE = "sem_remetente"  # o motor não recebeu `remetente_frio`
RAZAO_CAP = "cap_diario"             # cap diário atingido — excedente adiado (warm-up)


# ==========================================================================
#  Estruturas de saída
# ==========================================================================
@dataclass(frozen=True, slots=True)
class RascunhoFrio:
    """Um email frio COMPOSTO mas NÃO enviado — fila `pendentes_parecer`.

    É o "critério de feito" do sprint sem o risco: a peça de prospeção é gerada
    dentro da janela, mas o envio fica retido enquanto o portão RGPD não abrir (ou
    enquanto o cap/remetente não permitir). Guarda o essencial para auditoria.
    """

    para: str
    assunto: str
    html: str
    proveniencia: str
    motivo: str          # motivo do gatilho de origem (novo|alteracao_relevante|limpeza)
    razao: str           # porque não foi enviado (RAZAO_*)


@dataclass(slots=True)
class ResultadoCampanha:
    """Resultado de uma passagem do motor de campanhas.

    Campos
    ------
    gatilhos:      nº de gatilhos DETETADOS nesta passagem (alguns podem ser
                   saltados pela janela — ver `pendentes_parecer`/`enviados`).
    enviados:      lista de `ResultadoFrio` efetivamente enviados (só com o portão
                   aberto — vazia enquanto o parecer não chegar).
    pendentes_parecer: drafts compostos mas retidos (parecer OFF / sem remetente / cap).
    cartas:        nº de prospetos encaminhados para o canal postal.
    carta_pdf:     PDF multi-carta (bytes) para upload manual, ou None se não houve.
    descartados:   contagem de registos que não entraram em canal nenhum (malformados,
                   sem nome para carta) — NÃO inclui os suprimidos por opt-out.
    proveniencias: proveniência de cada contacto cold tratado (prova de lookup
                   dirigido, não scraping — PASSO 2).
    optouts:       emails suprimidos por oposição DGC / opt-out (Lei 41/2004, 13.º-B).
    """

    gatilhos: int
    enviados: list = field(default_factory=list)
    pendentes_parecer: list[RascunhoFrio] = field(default_factory=list)
    cartas: int = 0
    carta_pdf: bytes | None = None
    descartados: int = 0
    proveniencias: list[str] = field(default_factory=list)
    optouts: list[str] = field(default_factory=list)


# ==========================================================================
#  🚦 pode_enviar_frio — o TRIPLO GATE por contacto
# ==========================================================================
def pode_enviar_frio(
    contacto: object,
    *,
    lista_dgc: Iterable[str] = (),
    log_optout: Iterable[str] = (),
) -> bool:
    """True SÓ se o `contacto` puder ser contactado a frio AGORA — triplo gate.

    Cumulativo (SPEC-FDS6.md §portão bloqueante), na ordem mais barata → mais cara:

      1. **Gate global** — `config.pode_enviar_frio_global()`: parecer RGPD favorável
         (`CHECKAL_PARECER_RGPD_OK`) **e** modo de teste OFF (`CHECKAL_MODO_TESTE`)
         **e** SMTP de cold configurado (`cold_smtp_ativo`). Enquanto o parecer não
         chegar (o default), devolve sempre False — NENHUM email frio sai.
      2. **Núcleo de compliance** — o contacto é reconstituído no mínimo
         (`{Contribuinte, Email}`) e passado por `minimizacao.filtrar_enderecaveis`,
         que reaplica coletiva 5/6 (`nif.e_enderecavel`) **e** email genérico
         (`email.e_generico`). Defesa em profundidade: mesmo que a montante algo
         escapasse, aqui o singular/pessoal cai.
      3. **Oposição** — cruza o email com a oposição DGC + opt-out interno
         (`optout.filtrar_optout`); constando de qualquer, não se contacta.

    `lista_dgc`/`log_optout` são injetados (a fonte real liga-se no motor); vazios
    por omissão. Viés conservador: qualquer gate fechado ⇒ False.
    """
    # Gate 1 — o PORTÃO global (o mais barato e o mais decisivo).
    if not config.pode_enviar_frio_global():
        return False

    # Gate 2 — núcleo de compliance, pela MESMA porta que a segmentação usou.
    nif = str(getattr(contacto, "nif", "") or "")
    email = str(getattr(contacto, "email_generico", "") or "")
    registo_min = {"Contribuinte": nif, "Email": email}
    if next(iter(minimizacao.filtrar_enderecaveis([registo_min])), None) is None:
        return False

    # Gate 3 — oposição DGC + opt-out (último filtro antes de contactar).
    if next(
        iter(optout.filtrar_optout([contacto], lista_dgc=lista_dgc, log_optout=log_optout)),
        None,
    ) is None:
        return False

    return True


# ==========================================================================
#  Composição da copy (COPY-VENDAS.md §2 — email frio a pessoa coletiva)
# ==========================================================================
_DISCLAIMER_INDEPENDENCIA = (
    "O CheckAL é um serviço privado e independente de monitorização de Alojamento "
    "Local, sem qualquer vínculo ao Turismo de Portugal, ao RNAL ou a qualquer "
    "câmara municipal. Este email não é uma notificação oficial."
)


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _fmt_eur(v: int) -> str:
    """25000 -> '25.000' (milhares à portuguesa), a partir de `config.COIMA`."""
    return f"{v:,}".replace(",", ".")


def compor_email_frio(contacto: object) -> tuple[str, str]:
    """Compõe (assunto, html) do email frio B2B a partir de um `ContactoEnderecavel`.

    Copy da COPY-VENDAS.md §2 (Email 1 / D+0), com merge só dos campos que o
    contacto minimizado transporta (nome da coletiva, nº de registo, concelho) —
    **sem inventar dados**. As coimas saem de `config.COIMA` (folha canónica).

    Deliberadamente **não** crava o link `checkal.pt/remover`: o opt-out 1-clique
    personalizado (corpo + headers List-Unsubscribe, RFC 8058) é carimbado pelo seam
    de envio (`cold_email.enviar_frio`) no momento do envio — cravá-lo aqui
    impediria o seam de personalizar o corpo por destinatário.
    """
    nr = _texto(getattr(contacto, "nr_registo", ""))
    nome = _texto(getattr(contacto, "nome_coletiva", "")) or "a vossa empresa"
    concelho = _texto(getattr(contacto, "concelho", ""))
    ref_concelho = f" ({concelho})" if concelho else ""
    cta = f"checkal.pt/v/{nr}" if nr else "checkal.pt"

    assunto = (
        f"Registo de AL n.º {nr} — quem vigia os prazos?"
        if nr
        else "O vosso Alojamento Local — quem vigia os prazos?"
    )

    coima_lo, coima_hi = config.COIMA["coletiva"]
    html = "".join(
        [
            f"<p style='font-size:12px;color:#666'><em>{_DISCLAIMER_INDEPENDENCIA}</em></p>",
            "<p>Bom dia,</p>",
            f"<p>A {nome} é titular do registo de Alojamento Local n.º {nr}{ref_concelho}. "
            "Encontrámo-lo na lista pública do RNAL — é isso que fazemos: vigiamos os "
            "120.000+ registos do país.</p>",
            "<p>Desde março de 2025 a prova anual do seguro é obrigatória, e as câmaras "
            "já cancelaram <strong>mais de 10.000 registos</strong> por incumprimento. "
            "Para pessoas coletivas, as coimas por exploração irregular vão de "
            f"<strong>{_fmt_eur(coima_lo)}€ a {_fmt_eur(coima_hi)}€</strong>.</p>",
            "<p>O CheckAL monitoriza semanalmente o estado do registo, o prazo do seguro "
            "e os regulamentos do concelho, e envia alertas interpretados. No dia 1 de "
            "cada mês, um relatório confirma que está tudo em ordem.</p>",
            "<p><strong>Veja grátis o estado atual do vosso registo (30 segundos):</strong>"
            f"<br><a href='https://{cta}'>{cta}</a></p>",
            "<p>Cumprimentos,<br>Diogo Mendes · CheckAL</p>",
            "<p style='font-size:12px;color:#666'>Proteção de dados: o CheckAL é operado "
            "por Cosmic Oasis, Lda. Os dados de contacto desta mensagem foram obtidos do "
            "registo público RNAL (art. 10.º do DL n.º 128/2014). Base legal: interesse "
            "legítimo (art. 6.º, n.º 1, al. f) do RGPD); comunicação B2B a pessoa "
            "coletiva. Conservamos os dados por um máximo de 12 meses ou até oposição. "
            "Tem direito de acesso, retificação, apagamento e queixa à CNPD (cnpd.pt).</p>",
        ]
    )
    return assunto, html


# ==========================================================================
#  Janela de 72h — só se prospeta sobre eventos frescos
# ==========================================================================
def _normalizar_utc(dt: datetime) -> datetime:
    """SQLite devolve datetimes ingénuos mesmo em colunas `timezone=True`; assume UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _dentro_janela(dt: datetime | None, *, agora: datetime, janela_h: int) -> bool:
    """True se `dt` cair dentro da janela `[agora - janela_h, ...]`.

    `dt is None` (sem carimbo) ⇒ True (não penaliza por falta de timestamp — o
    pipeline preenche-o na prática; nunca dropamos por ausência de sinal).
    """
    if dt is None:
        return True
    return _normalizar_utc(dt) >= agora - timedelta(hours=janela_h)


def _data_para_dt(d: date | None) -> datetime | None:
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _tempos_evento_registo(session, evento_ids: list[int]) -> dict[int, datetime]:
    if not evento_ids:
        return {}
    linhas = (
        session.query(models.EventoRegisto.id, models.EventoRegisto.detetado_em)
        .filter(models.EventoRegisto.id.in_(evento_ids))
        .all()
    )
    return {eid: dt for eid, dt in linhas}


def _tempos_evento_regulatorio(session, evento_ids: list[int]) -> dict[int, date]:
    if not evento_ids:
        return {}
    linhas = (
        session.query(models.EventoRegulatorio.id, models.EventoRegulatorio.publicado_em)
        .filter(models.EventoRegulatorio.id.in_(evento_ids))
        .all()
    )
    return {eid: d for eid, d in linhas}


def _alvos_na_janela(
    session, gatilhos, *, agora: datetime, janela_h: int
) -> tuple[list[int], list[str], dict[int, str]]:
    """Reparte os gatilhos frescos em nrs-alvo (registo) + concelhos (regulatório).

    Gatilhos cujo evento de origem é mais antigo que a janela são SALTADOS. Devolve
    (nrs_alvo determinísticos e sem repetição, concelhos a expandir, motivo por nr).
    """
    reg_ids = [
        eid for g in gatilhos if g.origem == ORIGEM_EVENTO_REGISTO for eid in g.evento_ids
    ]
    regul_ids = [
        eid for g in gatilhos if g.origem == ORIGEM_EVENTO_REGULATORIO for eid in g.evento_ids
    ]
    tempos_reg = _tempos_evento_registo(session, reg_ids)
    tempos_regul = _tempos_evento_regulatorio(session, regul_ids)

    nrs_alvo: list[int] = []
    vistos: set[int] = set()
    concelhos_reg: list[str] = []
    motivo_por_nr: dict[int, str] = {}

    for g in gatilhos:
        if g.origem == ORIGEM_EVENTO_REGISTO:
            marcos = [tempos_reg.get(eid) for eid in g.evento_ids]
            fresco = max((t for t in marcos if t is not None), default=None)
            if not _dentro_janela(fresco, agora=agora, janela_h=janela_h):
                continue
            for nr in g.nrs:
                if nr is None:
                    continue
                motivo_por_nr.setdefault(nr, g.motivo)
                if nr not in vistos:
                    vistos.add(nr)
                    nrs_alvo.append(nr)
        else:  # regulatório — concelho-level
            pub = None
            for eid in g.evento_ids:
                d = tempos_regul.get(eid)
                if d is not None:
                    pub = d if pub is None else max(pub, d)
            if not _dentro_janela(_data_para_dt(pub), agora=agora, janela_h=janela_h):
                continue
            concelhos_reg.extend(c for c in g.concelhos if c)

    return nrs_alvo, concelhos_reg, motivo_por_nr


# ==========================================================================
#  Carregamento e adaptação dos registos
# ==========================================================================
def _carregar_registos(
    session, nrs_alvo: list[int], concelhos_reg: list[str], motivo_por_nr: dict[int, str]
) -> list[models.Registo]:
    """Carrega os registos-alvo: os nrs diretos (ordem do gatilho) + a expansão dos
    concelhos regulatórios (registos ATIVOS, por nr). Deduplica por nr."""
    registos: list[models.Registo] = []
    vistos: set[int] = set()

    if nrs_alvo:
        linhas = (
            session.query(models.Registo)
            .filter(models.Registo.nr_registo.in_(nrs_alvo))
            .all()
        )
        por_nr = {r.nr_registo: r for r in linhas}
        for nr in nrs_alvo:  # preserva a ordem determinística do gatilho
            r = por_nr.get(nr)
            if r is not None and r.nr_registo not in vistos:
                vistos.add(r.nr_registo)
                registos.append(r)

    if concelhos_reg:
        concelhos = list(dict.fromkeys(concelhos_reg))
        linhas = (
            session.query(models.Registo)
            .filter(
                models.Registo.concelho.in_(concelhos),
                models.Registo.desaparecido_em.is_(None),  # só ativos
            )
            .order_by(models.Registo.nr_registo)
            .all()
        )
        for r in linhas:
            if r.nr_registo not in vistos:
                vistos.add(r.nr_registo)
                motivo_por_nr.setdefault(r.nr_registo, MOTIVO_ALTERACAO)
                registos.append(r)

    return registos


def _registo_para_dict(r: models.Registo) -> dict:
    """Adapta um `Registo` ao formato RNAL achatado que a segmentação consome.

    Só campos publicados; a segmentação/minimização decide o canal e descarta os
    dados de pessoa singular (nunca os materializa no ramo cold)."""
    return {
        "NrRegisto": r.nr_registo,
        "Contribuinte": r.nif,
        "Email": r.email,
        "Nome": r.titular_nome,
        "Concelho": r.concelho,
        "Endereco": r.endereco,
        "CodPostal": r.cod_postal,
        "Freguesia": r.freguesia,
        "NomeAlojamento": r.nome_alojamento,
    }


# ==========================================================================
#  Orquestrador
# ==========================================================================
def correr_campanhas(
    session,
    *,
    remetente_frio=None,
    gerar_cartas=None,
    lista_dgc: Iterable[str] = (),
    log_optout: Iterable[str] = (),
    agora: datetime | None = None,
    janela_h: int | None = None,
    cap_diario: int | None = None,
    limiar_limpeza: int = LIMIAR_LIMPEZA,
    remetente_carta: carta.Remetente | None = None,
) -> ResultadoCampanha:
    """Corre uma passagem do motor: gatilho → segmento → envio/pendente/carta.

    Fluxo (SPEC-FDS6.md §motor):
      1. `detetar_gatilhos` (idempotente; marca eventos usados para campanha);
      2. filtra pela janela de 72h e resolve os registos-alvo (nrs + expansão de
         concelho regulatório);
      3. `segmentacao.segmentar` reparte pelo núcleo de compliance;
      4. cruza a oposição DGC + opt-out (registando os suprimidos);
      5. para cada cold, compõe a copy e — só se `pode_enviar_frio(contacto)` e
         houver `remetente_frio` e o cap diário o permitir — **envia**; senão fica
         em `pendentes_parecer`;
      6. gera o PDF multi-carta para o canal postal.

    **Não faz commit** (a transação é do chamador). `remetente_frio`/`gerar_cartas`
    são INJETADOS (LIVE-GATED); por omissão a carta usa `carta.gerar_lote_cartas` e
    o cold **não** compõe remetente real — fica tudo em `pendentes_parecer`.

    Parâmetros de política (injetáveis; default = folha canónica de `config`):
    `agora` (relógio), `janela_h` (SLA 72h), `cap_diario` (teto de envios/passagem).
    """
    agora = agora or datetime.now(timezone.utc)
    janela_h = config.CAMPANHA_JANELA_H if janela_h is None else janela_h
    cap_diario = config.CAMPANHA_CAP_DIARIO if cap_diario is None else cap_diario

    gatilhos = detetar_gatilhos(session, limiar_limpeza=limiar_limpeza)

    nrs_alvo, concelhos_reg, motivo_por_nr = _alvos_na_janela(
        session, gatilhos, agora=agora, janela_h=janela_h
    )
    registos = _carregar_registos(session, nrs_alvo, concelhos_reg, motivo_por_nr)
    lote = [_registo_para_dict(r) for r in registos]

    # Segmentação SEM opt-out aqui — o motor aplica o opt-out logo a seguir para
    # poder REGISTAR os suprimidos (log de opt-outs). O núcleo de compliance
    # (coletiva 5/6 + genérico) continua a ser a autoridade do ramo cold.
    segmentos = segmentacao.segmentar(lote)

    # Oposição DGC + opt-out — supressão e log.
    cold_ok = list(
        optout.filtrar_optout(segmentos.cold_email, lista_dgc=lista_dgc, log_optout=log_optout)
    )
    ok_ids = {id(c) for c in cold_ok}
    optouts = [c.email_generico for c in segmentos.cold_email if id(c) not in ok_ids]

    # Ramo cold — compõe sempre; só envia com o triplo gate + remetente + cap.
    enviados: list = []
    pendentes: list[RascunhoFrio] = []
    proveniencias: list[str] = []
    n_enviados = 0

    for contacto in cold_ok:
        assunto, html = compor_email_frio(contacto)
        proveniencias.append(contacto.proveniencia)
        motivo = motivo_por_nr.get(contacto.nr_registo, "")

        pode = remetente_frio is not None and pode_enviar_frio(
            contacto, lista_dgc=lista_dgc, log_optout=log_optout
        )
        if pode and n_enviados < cap_diario:
            enviados.append(
                remetente_frio(para=contacto.email_generico, assunto=assunto, html=html)
            )
            n_enviados += 1
            continue

        if remetente_frio is None:
            razao = RAZAO_SEM_REMETENTE
        elif not pode:
            razao = RAZAO_GATE
        else:
            razao = RAZAO_CAP
        pendentes.append(
            RascunhoFrio(
                para=contacto.email_generico,
                assunto=assunto,
                html=html,
                proveniencia=contacto.proveniencia,
                motivo=motivo,
                razao=razao,
            )
        )

    # Ramo carta — PDF multi-carta para upload manual (só se houver prospetos).
    carta_pdf: bytes | None = None
    if segmentos.carta:
        gerar = gerar_cartas or carta.gerar_lote_cartas
        extra = {} if remetente_carta is None else {"remetente": remetente_carta}
        carta_pdf = gerar(segmentos.carta, **extra)

    return ResultadoCampanha(
        gatilhos=len(gatilhos),
        enviados=enviados,
        pendentes_parecer=pendentes,
        cartas=len(segmentos.carta),
        carta_pdf=carta_pdf,
        descartados=segmentos.descartados,
        proveniencias=proveniencias,
        optouts=optouts,
    )
