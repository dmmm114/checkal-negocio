"""Painel do dono — Campanhas + Compliance (FASE 1 · WF3, SPEC-FASE1-DASHBOARD).

Duas páginas READ-FIRST do painel privado (todas sob `requer_admin`), mais a
exportação CSV da prova para a CNPD:

    GET /admin/campanhas                       — gatilhos → segmentos + fila cold
    GET /admin/compliance                      — opt-outs + proveniências + consentimentos
    GET /admin/compliance/consentimentos.csv   — export CSV (prova de consentimento)
    GET /admin/compliance/optouts.csv          — export CSV (lista de supressão)

🚦 **O portão frio é CÓDIGO, não confiança.** Esta página MOSTRA a fila de aprovação
do cold, mas o botão "Disparar" nasce **DESATIVADO** e não existe nenhum endpoint que
ENVIE: o disparo respeita `config.pode_enviar_frio_global()` (parecer RGPD +
modo de teste OFF + SMTP de cold configurado). Enquanto o portão estiver fechado (o
default), mostra-se um aviso a explicar o porquê. Se o botão for ativado (portão
aberto) continua a não haver disparo real — o envio a frio é âmbito de outro sprint
(SPEC §fora de âmbito). A página é uma vista; não muda estado.

**Read-only por construção.** Ao contrário do motor (`app.campanhas.motor`), esta
vista NÃO deteta gatilhos de forma mutante (nada de marcar eventos como usados) nem
aplica a janela de 72h (o dono quer ver TUDO o que está pendente, não só o fresco).
Reimplementa a deteção em SÓ-LEITURA e reutiliza as peças PURAS do pipeline —
`segmentacao.segmentar`, `optout.filtrar_optout`, `motor.compor_email_frio` — para
prever, sem efeitos colaterais, como o lote se reparte por cold/carta/suprimidos.

O opt-out real (tabela `optouts`) alimenta a supressão: os emails da lista de
supressão são cruzados com os candidatos cold, e os suprimidos aparecem contados
(campanhas) e por email na prova (compliance). Assim a página é coerente com a lei que
o resto do sistema aplica.

DISCIPLINA (inviolável): LIVE-GATED. Não toca a rede. Só faz SELECT (via
`db.get_session`) e renderiza pelo Jinja PARTILHADO (`app.web.marca.templates`,
autoescape ⇒ anti-XSS). A PII (emails/IPs) só se mostra a um dono AUTENTICADO — é a
operação (prova CNPD); nenhuma superfície não-autenticada a vê.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

import app.config as config
import app.db as db
import app.models as models
from app.campanhas import segmentacao
from app.campanhas.gatilhos import (
    CANAL_GATILHO,
    LIMIAR_LIMPEZA,
    MOTIVO_ALTERACAO,
    MOTIVO_LIMPEZA,
    MOTIVO_NOVO,
    ORIGEM_EVENTO_REGISTO,
    ORIGEM_EVENTO_REGULATORIO,
    RELEVANCIAS_GATILHO,
)
from app.campanhas.motor import compor_email_frio
from app.compliance import optout
from app.rnal.diffing import TIPO_ALTERADO, TIPO_DESAPARECIDO, TIPO_NOVO
from app.web.admin import requer_admin
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


# ==========================================================================
#  Deteção de gatilhos em SÓ-LEITURA (espelha app.campanhas.gatilhos, sem marcar)
# ==========================================================================
def _ids_usados(s, origem: str) -> set[int]:
    """Ids de eventos já consumidos por campanha (marcador `canal == 'campanha'`)."""
    linhas = (
        s.query(models.Alerta.origem_id)
        .filter(
            models.Alerta.canal == CANAL_GATILHO,
            models.Alerta.origem == origem,
            models.Alerta.origem_id.isnot(None),
        )
        .all()
    )
    return {oid for (oid,) in linhas}


def _add_alvo(nr, motivo, nrs_alvo, vistos, motivo_por_nr) -> None:
    if nr is None:
        return
    motivo_por_nr.setdefault(nr, motivo)
    if nr not in vistos:
        vistos.add(nr)
        nrs_alvo.append(nr)


def _detetar_readonly(s, *, limiar_limpeza: int = LIMIAR_LIMPEZA):
    """Deteta os gatilhos PENDENTES sem mutar nada (nem marca, nem janela de 72h).

    Devolve `(contagem, nrs_alvo, motivo_por_nr, concelhos_regulatorios)`, onde
    `contagem` é o mapa de contagens por tipo para o dashboard.
    """
    usados_reg = _ids_usados(s, ORIGEM_EVENTO_REGISTO)
    usados_regul = _ids_usados(s, ORIGEM_EVENTO_REGULATORIO)

    linhas = (
        s.query(models.EventoRegisto, models.Registo.concelho)
        .outerjoin(
            models.Registo,
            models.Registo.nr_registo == models.EventoRegisto.nr_registo,
        )
        .filter(models.EventoRegisto.tipo.in_((TIPO_NOVO, TIPO_ALTERADO, TIPO_DESAPARECIDO)))
        .order_by(models.EventoRegisto.id)
        .all()
    )

    contagem = {"novos": 0, "alteracoes": 0, "limpezas": 0, "regulatorios": 0}
    nrs_alvo: list = []
    vistos: set = set()
    motivo_por_nr: dict = {}
    desap: dict[str, list] = {}

    for evento, concelho in linhas:
        if evento.id in usados_reg:
            continue
        nr = evento.nr_registo
        if evento.tipo == TIPO_NOVO:
            contagem["novos"] += 1
            _add_alvo(nr, MOTIVO_NOVO, nrs_alvo, vistos, motivo_por_nr)
        elif evento.tipo == TIPO_ALTERADO:
            contagem["alteracoes"] += 1
            _add_alvo(nr, MOTIVO_ALTERACAO, nrs_alvo, vistos, motivo_por_nr)
        elif evento.tipo == TIPO_DESAPARECIDO and concelho:
            desap.setdefault(concelho, []).append(nr)

    for concelho in sorted(desap):
        if len(desap[concelho]) >= limiar_limpeza:
            contagem["limpezas"] += 1
            for nr in desap[concelho]:
                _add_alvo(nr, MOTIVO_LIMPEZA, nrs_alvo, vistos, motivo_por_nr)

    concelhos_regul: list[str] = []
    regs = (
        s.query(models.EventoRegulatorio)
        .filter(models.EventoRegulatorio.triagem.in_(tuple(RELEVANCIAS_GATILHO)))
        .order_by(models.EventoRegulatorio.id)
        .all()
    )
    for ev in regs:
        if ev.id in usados_regul:
            continue
        contagem["regulatorios"] += 1
        for c in (ev.concelhos or []):
            if c:
                concelhos_regul.append(c)

    return contagem, nrs_alvo, motivo_por_nr, concelhos_regul


def _registo_dict(r: models.Registo) -> dict:
    """Adapta um `Registo` ao formato RNAL achatado que a segmentação consome."""
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


def _carregar(s, nrs_alvo, concelhos_regul, motivo_por_nr) -> list[models.Registo]:
    """Carrega os registos-alvo: nrs diretos (ordem do gatilho) + expansão de concelho
    regulatório (ativos, por nr). Deduplica por nr. Só-leitura."""
    registos: list[models.Registo] = []
    vistos: set = set()

    if nrs_alvo:
        por_nr = {
            r.nr_registo: r
            for r in s.query(models.Registo)
            .filter(models.Registo.nr_registo.in_(nrs_alvo))
            .all()
        }
        for nr in nrs_alvo:
            r = por_nr.get(nr)
            if r is not None and r.nr_registo not in vistos:
                vistos.add(r.nr_registo)
                registos.append(r)

    if concelhos_regul:
        concelhos = list(dict.fromkeys(concelhos_regul))
        for r in (
            s.query(models.Registo)
            .filter(
                models.Registo.concelho.in_(concelhos),
                models.Registo.desaparecido_em.is_(None),
            )
            .order_by(models.Registo.nr_registo)
            .all()
        ):
            if r.nr_registo not in vistos:
                vistos.add(r.nr_registo)
                motivo_por_nr.setdefault(r.nr_registo, MOTIVO_ALTERACAO)
                registos.append(r)

    return registos


# ==========================================================================
#  Previsão read-only: gatilhos → segmentos → fila cold (sem enviar, sem mutar)
# ==========================================================================
def _preparar_campanhas(s) -> dict:
    """Vista read-only do pipeline de campanhas: contagens, segmentos e fila cold.

    Reutiliza as peças PURAS (`segmentar`, `filtrar_optout`, `compor_email_frio`) e
    cruza a lista de supressão real (tabela `optouts`) para prever os suprimidos.
    """
    contagem, nrs_alvo, motivo_por_nr, concelhos_regul = _detetar_readonly(s)
    registos = _carregar(s, nrs_alvo, concelhos_regul, motivo_por_nr)
    lote = [_registo_dict(r) for r in registos]

    segmentos = segmentacao.segmentar(lote)

    # A lista de supressão real (opt-out interno) alimenta a supressão do cold.
    optout_emails = {e for (e,) in s.query(models.OptOut.email).all()}
    cold_ok = list(
        optout.filtrar_optout(segmentos.cold_email, lista_dgc=(), log_optout=optout_emails)
    )
    ok_ids = {id(c) for c in cold_ok}
    suprimidos = [c for c in segmentos.cold_email if id(c) not in ok_ids]

    fila = []
    for c in cold_ok:
        assunto, _html = compor_email_frio(c)
        fila.append(
            {
                "nr": c.nr_registo,
                "nome": c.nome_coletiva,
                "concelho": c.concelho,
                "email": c.email_generico,
                "proveniencia": c.proveniencia,
                "motivo": motivo_por_nr.get(c.nr_registo, ""),
                "assunto": assunto,
            }
        )

    # Proveniências (prova do canal frio): todos os candidatos cold considerados
    # (enviáveis + suprimidos), com a proveniência do lookup dirigido no RNAL.
    proveniencias = [
        {
            "nr": c.nr_registo,
            "email": c.email_generico,
            "concelho": c.concelho,
            "proveniencia": c.proveniencia,
        }
        for c in list(cold_ok) + list(suprimidos)
    ]

    return {
        "contagem": contagem,
        "fila": fila,
        "n_cold": len(cold_ok),
        "n_carta": len(segmentos.carta),
        "n_suprimidos": len(suprimidos),
        "n_descartados": segmentos.descartados,
        "proveniencias": proveniencias,
    }


def _razoes_gate() -> list[str]:
    """Explica, em linguagem clara, PORQUÊ o canal frio está fechado (para o aviso)."""
    razoes: list[str] = []
    if not config.CHECKAL_PARECER_RGPD_OK:
        razoes.append(
            "Falta o parecer favorável do jurista de proteção de dados sobre a "
            "reutilização do RNAL para prospeção (portão bloqueante RGPD)."
        )
    if config.CHECKAL_MODO_TESTE:
        razoes.append("O sistema está em modo de teste (CHECKAL_MODO_TESTE ligado).")
    if not config.cold_smtp_ativo():
        razoes.append(
            "O SMTP dedicado do domínio getcheckal.com ainda não está configurado."
        )
    return razoes


# ==========================================================================
#  Compliance — opt-outs + consentimentos (Lead)
# ==========================================================================
def _lead_dict(lead: models.Lead) -> dict:
    return {
        "email": lead.email,
        "estado": lead.estado,
        "consent_alertas": lead.consent_alertas,
        "consent_ofertas": lead.consent_ofertas,
        "texto": lead.consentimento_texto_versao,
        "em": lead.consentimento_em,
        "ip": lead.ip,
        "nr": lead.nr_registo,
        "concelho": lead.concelho,
    }


def _optouts(s) -> list[dict]:
    return [
        {"email": o.email, "origem": o.origem, "criado_em": o.criado_em}
        for o in s.query(models.OptOut).order_by(models.OptOut.criado_em, models.OptOut.email).all()
    ]


def _leads(s) -> list[dict]:
    return [_lead_dict(lead) for lead in s.query(models.Lead).order_by(models.Lead.id).all()]


# Caracteres que, no início de uma célula, um spreadsheet (Excel/LibreOffice/
# Sheets) interpreta como FÓRMULA. Um email de opt-out/lead é dado PÚBLICO
# (submetido em /remover e no funil de consentimento) e a validação de email
# aceita `=SUM(..)@x.pt`, `+..`, `-..`, `@..` (só recusa espaços) — pelo que um
# atacante pode semear uma célula com `=cmd|'..'!A1`/`=HYPERLINK(..)` que EXECUTA
# quando o dono abre a "prova para a CNPD" num spreadsheet (CSV/formula injection,
# OWASP). Defesa no ÚNICO ponto de serialização: prefixa-se `'` (que o spreadsheet
# trata como texto literal) sem mudar o contrato das rotas nem as colunas.
_CSV_GATILHOS_FORMULA = ("=", "+", "-", "@", "\t", "\r", "\n")


def _sanitizar_celula(valor):
    """Neutraliza a injeção de fórmula: antepõe `'` a uma célula de texto que comece
    por um gatilho de fórmula. Valores não-texto (datas, bools, ints, None) passam
    intactos — não são interpretáveis como fórmula."""
    if isinstance(valor, str) and valor[:1] in _CSV_GATILHOS_FORMULA:
        return "'" + valor
    return valor


def _csv_response(campos: list[str], linhas: list[list], nome: str) -> Response:
    """Serializa `linhas` em CSV (com cabeçalho) e devolve-o como anexo `text/csv`.

    Cada célula passa por `_sanitizar_celula` (anti CSV/formula injection) antes de
    ser escrita — os cabeçalhos são constantes de código, não carecem de sanitização.
    """
    buf = io.StringIO()
    escritor = csv.writer(buf)
    escritor.writerow(campos)
    for linha in linhas:
        escritor.writerow([_sanitizar_celula(c) for c in linha])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


# ==========================================================================
#  Rotas — todas sob requer_admin
# ==========================================================================
@router.get("/admin/campanhas", response_class=HTMLResponse)
def campanhas(request: Request, _=Depends(requer_admin)) -> HTMLResponse:
    """Gatilhos → segmentos (cold/carta/suprimidos) + fila de aprovação do cold.

    O botão "Disparar" fica DESATIVADO e o aviso explica o porquê enquanto
    `config.pode_enviar_frio_global()` for False. Read-first: não há disparo real.
    """
    with db.get_session() as s:
        dados = _preparar_campanhas(s)
    return templates.TemplateResponse(
        request,
        "admin/campanhas.html",
        {
            "seccao": "campanhas",
            "dados": dados,
            "pode_disparar": config.pode_enviar_frio_global(),
            "razoes_gate": _razoes_gate(),
        },
    )


@router.get("/admin/compliance", response_class=HTMLResponse)
def compliance(request: Request, _=Depends(requer_admin)) -> HTMLResponse:
    """Log de opt-outs + proveniências (prova cold) + consentimentos (prova CNPD)."""
    with db.get_session() as s:
        optouts = _optouts(s)
        leads = _leads(s)
        proveniencias = _preparar_campanhas(s)["proveniencias"]
    return templates.TemplateResponse(
        request,
        "admin/compliance.html",
        {
            "seccao": "compliance",
            "optouts": optouts,
            "leads": leads,
            "proveniencias": proveniencias,
        },
    )


@router.get("/admin/compliance/consentimentos.csv")
def export_consentimentos(request: Request, _=Depends(requer_admin)) -> Response:
    """CSV da prova de consentimento dos Leads (art. 7/1 RGPD — só autenticado)."""
    with db.get_session() as s:
        leads = _leads(s)
    campos = [
        "email", "estado", "consent_alertas", "consent_ofertas",
        "consentimento_texto_versao", "consentimento_em", "ip", "nr_registo", "concelho",
    ]
    linhas = [
        [
            l["email"], l["estado"], l["consent_alertas"], l["consent_ofertas"],
            l["texto"], l["em"], l["ip"], l["nr"], l["concelho"],
        ]
        for l in leads
    ]
    return _csv_response(campos, linhas, "consentimentos.csv")


@router.get("/admin/compliance/optouts.csv")
def export_optouts(request: Request, _=Depends(requer_admin)) -> Response:
    """CSV da lista de supressão (opt-outs) — prova de que a oposição é honrada."""
    with db.get_session() as s:
        optouts = _optouts(s)
    campos = ["email", "origem", "criado_em"]
    linhas = [[o["email"], o["origem"], o["criado_em"]] for o in optouts]
    return _csv_response(campos, linhas, "optouts.csv")
