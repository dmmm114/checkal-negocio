"""Funil consent-first: inscrição com double opt-in (SPEC-FASE1-WEB §consentimento).

O coração RGPD da FASE 1. O visitante faz o "check" grátis (`/api/verificar`) e, se
quiser o relatório e os avisos, dá o email + carrega numa checkbox de consentimento
NÃO pré-marcada. Só então nasce um `Lead`:

    POST /inscrever   valida email + consentimento → cria Lead 'pendente' + GRAVA A
                      PROVA (texto+versão do consentimento, timestamp, IP) → dispara o
                      double opt-in (`envio.obter_enviador`, LIVE-GATED) → 303 /obrigado
    GET  /confirmar   ?token=… → ativa o Lead ('pendente' → 'confirmado')

Porquê o rigor: reutilizar contactos do RNAL para prospeção é o risco RGPD nº 1 do
projeto (finalidade incompatível, art. 5/1/b; a CNPD sanciona). A resposta é
consent-first PURO — ninguém entra na base de comunicação sem ter carregado ele
próprio na checkbox, e a PROVA disso (art. 7/1: o responsável tem de a demonstrar)
grava-se com o Lead: o texto EXATO que viu, quando e de onde.

Double opt-in: a inscrição não é confiada até o titular clicar na ligação enviada
por email — evita inscrições de terceiros e emails com gralhas, e é a boa prática
que a CNPD espera para consentimento por email.

DISCIPLINA (inviolável): **LIVE-GATED.** O envio passa SEMPRE por
`app.envio.obter_enviador()`, que devolve `None` sob modo de teste ou sem chave —
logo os testes nunca tocam a rede (injetam um enviador falso). Um Lead grava-se
mesmo que o envio esteja indisponível (a prova não se perde) e uma falha de
transporte NUNCA rebenta o request do utilizador. Autoescape Jinja (anti-XSS).

Nota de wiring (WF2): o HTML do email de confirmação aqui composto é PROVISÓRIO — o
agente de integração substitui-o pelo template `confirmacao_consentimento`
(`app/emails/transacional.py`), preservando este seam e a ligação `/confirmar?token=`.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func

import app.config as config
import app.db as db
import app.envio as envio
import app.models as models
from app.compliance.optout import normalizar_email
from app.emails import transacional as _emails
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# ==========================================================================
#  Texto e versão do consentimento — a PROVA que se grava (RGPD art. 7/1)
# ==========================================================================
# CONSENTIMENTO GRANULAR (parecer RGPD §3 — exigência da CNPD): duas finalidades
# INDEPENDENTES, nenhuma pré-marcada, nenhuma condicionada ao relatório gratuito.
# Estas constantes são a FONTE ÚNICA (fecha o drift — achado do red-team): são
# renderizadas como os labels dos checkboxes na landing (via contexto Jinja) E
# gravadas como a prova — o que se mostra é EXATAMENTE o que se prova.
#
# A versão sobe sempre que QUALQUER texto mudar, para que cada Lead aponte para a
# redação EXATA que o titular aceitou. NÃO se afirma aqui a base de publicidade do
# email do titular (art. 10.º ainda por confirmar — LEGAL-PARECER §2/§5).
CONSENTIMENTO_VERSAO = "2026-07-06"
CONSENTIMENTO_ALERTAS_TEXTO = (
    "Autorizo a Cosmic Oasis, Lda. (CheckAL) a enviar-me, por email, o relatório "
    "gratuito do meu Alojamento Local e alertas sobre o meu AL e o meu concelho — "
    "registo RNAL, seguro obrigatório e regulamentos municipais. Posso retirar este "
    "consentimento a qualquer momento em checkal.pt/remover."
)
CONSENTIMENTO_OFERTAS_TEXTO = (
    "Autorizo a Cosmic Oasis, Lda. (CheckAL) a enviar-me novidades e ofertas "
    "comerciais do CheckAL. É opcional e independente dos alertas do serviço."
)

# Identidade do responsável mostrada junto aos checkboxes (RGPD art. 13.º).
CONSENTIMENTO_RESPONSAVEL = "Cosmic Oasis, Lda. — CheckAL"


def _consentimento_versionado(*, alertas: bool, ofertas: bool) -> str:
    """Prova textual auto-descritiva: versão + o texto EXATO de CADA finalidade aceite.

    Regista só o que o titular marcou — a prova reflete o consentimento real, por
    finalidade (não um texto global). `alertas` está sempre presente (é o gate da
    inscrição); `ofertas` só consta se marcado.
    """
    partes = [f"[v{CONSENTIMENTO_VERSAO}]"]
    if alertas:
        partes.append(f"alertas: {CONSENTIMENTO_ALERTAS_TEXTO}")
    if ofertas:
        partes.append(f"ofertas: {CONSENTIMENTO_OFERTAS_TEXTO}")
    return " | ".join(partes)


# Janela de dedup anti-bombing: dentro dela, um novo POST /inscrever para um email
# com Lead 'pendente' ATUALIZA esse Lead em vez de criar outro e reenviar o double
# opt-in (evita encher a caixa do titular com confirmações — achado do red-team).
DEDUP_PENDENTE_JANELA = timedelta(hours=1)


# ==========================================================================
#  Validação de entrada
# ==========================================================================
# Validação de email deliberadamente simples (não RFC-completa): não vazio, um único
# "@", um "." no domínio, sem espaços. Barra o lixo óbvio; a prova real de que o email
# existe é o próprio double opt-in (só um email a sério recebe a ligação).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def _consentiu(consentimento: str | None) -> bool:
    """True só se a checkbox veio marcada (presente e não vazia).

    Um checkbox HTML não marcado NÃO envia campo; marcado envia o seu `value` ("on").
    Falha fechado: ausente, `None` ou vazio → não consentiu.
    """
    return bool(consentimento and consentimento.strip())


def _parse_nr(valor: str | None) -> int | None:
    """Interpreta o nº de registo RNAL, tolerando o sufixo "/AL" e espaços.

    Espelha `app.web.verificar._extrair_nr`: "100031", "100031/AL", " 100031 " → 100031;
    vazio ou não-numérico → `None` (o nº é contexto opcional, nunca obrigatório).
    """
    if not valor:
        return None
    cabeca = valor.strip().split("/", 1)[0].strip()
    return int(cabeca) if cabeca.isdigit() else None


def _limpar(valor: str | None) -> str | None:
    """Normaliza um campo de texto opcional: `None`/vazio → `None`; caso contrário `strip`."""
    if valor is None:
        return None
    v = valor.strip()
    return v or None


def _ip_do_request(request: Request) -> str | None:
    """IP de origem para a prova de consentimento.

    Atrás do proxy/nginx (Hetzner) o IP real vem em `X-Forwarded-For` (1.º da lista);
    sem proxy, usa-se o host da ligação direta. `None` se nenhum estiver disponível.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.client.host if request.client else None


# ==========================================================================
#  Double opt-in — composição do email de confirmação (PROVISÓRIO; ver WF2)
# ==========================================================================
def _url_confirmacao(token: str) -> str:
    return f"{config.BASE_URL}/confirmar?token={token}"


def _disparar_double_opt_in(
    email: str, token: str, *, alertas: bool, ofertas: bool
) -> None:
    """Dispara o email de confirmação (template branded WF2) pelo seam LIVE-GATED.

    Usa `app.emails.transacional.confirmacao_consentimento` — marca + rodapé legal +
    opt-out garantidos pela base — e REFLETE o consentimento **granular** dado no widget
    (alertas do serviço / ofertas), como exige a CNPD (LEGAL-PARECER §3). Preserva o seam
    e a ligação `/confirmar?token=` (via `config.BASE_URL`).

    `envio.obter_enviador()` devolve `None` sob modo de teste ou sem chave — nesse caso
    não há para onde enviar e simplesmente não se envia (o Lead já ficou gravado com a
    prova). Uma falha de transporte é engolida: a inscrição não pode falhar por causa do
    email — o titular pode sempre repetir, e a prova de consentimento persiste.
    """
    enviar = envio.obter_enviador()
    if enviar is None:
        return
    try:
        email_render = _emails.confirmacao_consentimento(
            url_confirmar=_url_confirmacao(token),
            consente_alertas=alertas,
            consente_ofertas=ofertas,
            email_destinatario=email,
        )
        enviar(
            para=email,
            assunto=email_render.assunto,
            html=email_render.html,
            texto=email_render.texto,
            idempotency_key=f"double-opt-in-{token}",
        )
    except Exception:
        # Transporte indisponível/falhado: não é erro do utilizador. Lead já gravado.
        pass


# ==========================================================================
#  Página de recusa (validação falhada) — sem eco de input (anti-XSS por construção)
# ==========================================================================
_PAGINA_ERRO = """<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Inscrição incompleta · CheckAL</title>
  <link rel="stylesheet" href="/static/brand.css">
</head>
<body>
  <main style="max-width:40rem;margin:4rem auto;padding:0 1.25rem;font-size:1.0625rem">
    <h1>Faltou um passo.</h1>
    <p>Para receberes o relatório precisamos do teu email <strong>e</strong> de que
    autorizes o contacto (a caixa de consentimento). Volta atrás e tenta de novo.</p>
    <p><a href="/#verificar">Voltar ao check do meu AL</a></p>
  </main>
</body>
</html>
"""


# ==========================================================================
#  Dedup anti-bombing — reutiliza um Lead 'pendente' recente do mesmo email
# ==========================================================================
def _pendente_recente(s, email: str, agora: datetime) -> models.Lead | None:
    """O Lead 'pendente' mais recente deste email dentro da janela de dedup, ou `None`.

    Case-insensitive no email (igual ao opt-out). O filtro de recência corre no SQL
    (`criado_em >= limite`) de propósito — o SQLite devolve `datetime` naïve, pelo que
    comparar em Python com o `agora` aware rebentaria; no SQL ambos os lados passam
    pelo mesmo processador de datas e a comparação é consistente (e portável a Postgres).
    """
    limite = agora - DEDUP_PENDENTE_JANELA
    return (
        s.query(models.Lead)
        .filter(
            func.lower(models.Lead.email) == email.lower(),
            models.Lead.estado == "pendente",
            models.Lead.criado_em >= limite,
        )
        .order_by(models.Lead.criado_em.desc())
        .first()
    )


# ==========================================================================
#  Rotas
# ==========================================================================
@router.post("/inscrever", response_model=None)
def inscrever(
    request: Request,
    email: str = Form(default=""),
    consent_alertas: str | None = Form(default=None),
    consent_ofertas: str | None = Form(default=None),
    consentimento: str | None = Form(default=None),  # legado: alias de consent_alertas
    nr_registo: str | None = Form(default=None),
    concelho: str | None = Form(default=None),
) -> HTMLResponse | RedirectResponse:
    """Inscreve um interessado consent-first (GRANULAR) e dispara o double opt-in.

    Consentimento GRANULAR (parecer RGPD §3): `consent_alertas` (comunicações do
    serviço) é o GATE — sem ele não nasce Lead; `consent_ofertas` (marketing) é extra
    opcional. O campo legado `consentimento` mapeia para alertas (compat do contrato
    antigo). Grava-se a PROVA por finalidade (texto+versão, quando, IP).

    Dedup anti-bombing: se já existir um Lead 'pendente' recente para o email,
    ATUALIZA-o (consentimentos + prova) em vez de criar outro e reenviar a confirmação.

    Sem email válido ou sem consentimento de alertas → 400 (nada gravado, nada enviado).
    """
    # Alertas (serviço) é o valor e o GATE; ofertas (marketing) é extra. O legado
    # `consentimento` conta como alertas (nunca como ofertas — o default seguro).
    quer_alertas = _consentiu(consent_alertas) or _consentiu(consentimento)
    quer_ofertas = _consentiu(consent_ofertas)

    if not _email_valido(email) or not quer_alertas:
        # Falha fechado: não cria Lead nem envia. 400 com página sem eco de input.
        return HTMLResponse(content=_PAGINA_ERRO, status_code=400)

    email_limpo = email.strip()
    agora = datetime.now(timezone.utc)
    prova = _consentimento_versionado(alertas=quer_alertas, ofertas=quer_ofertas)
    ip = _ip_do_request(request)
    nr = _parse_nr(nr_registo)
    conc = _limpar(concelho)

    token: str | None = None  # só se atribui a um Lead NOVO → gate do double opt-in
    with db.get_session() as s:
        pendente = _pendente_recente(s, email_limpo, agora)
        if pendente is not None:
            # Reutiliza: atualiza a prova/consentimentos do 'pendente'; NÃO reenvia.
            pendente.consent_alertas = quer_alertas
            pendente.consent_ofertas = quer_ofertas
            pendente.consentimento_texto_versao = prova
            pendente.consentimento_em = agora
            pendente.ip = ip
            if nr is not None:
                pendente.nr_registo = nr
            if conc is not None:
                pendente.concelho = conc
        else:
            token = secrets.token_urlsafe(32)
            s.add(models.Lead(
                email=email_limpo,
                nr_registo=nr,
                concelho=conc,
                consent_alertas=quer_alertas,            # a PROVA (o quê — serviço)
                consent_ofertas=quer_ofertas,            # a PROVA (o quê — marketing)
                consentimento_texto_versao=prova,        # a PROVA (texto+versão)
                consentimento_em=agora,                  # a PROVA (quando)
                ip=ip,                                   # a PROVA (de onde)
                estado="pendente",
                token_confirmacao=token,
                criado_em=agora,
            ))
        # commit no fim do `with` (db.get_session): a prova fica DURÁVEL antes do envio.

    # Double opt-in só para um Lead NOVO — LIVE-GATED, best-effort, nunca rebenta o
    # request (o reutilizado já recebeu a confirmação; reenviá-la seria o bombing).
    if token is not None:
        _disparar_double_opt_in(
            email_limpo, token, alertas=quer_alertas, ofertas=quer_ofertas
        )

    # 303 See Other: após um POST, o browser segue com GET para /obrigado (evita reenvio).
    return RedirectResponse(url="/obrigado", status_code=303)


@router.get("/confirmar", response_class=HTMLResponse)
def confirmar(request: Request, token: str = "") -> HTMLResponse:
    """Ativa o Lead do double opt-in: 'pendente' → 'confirmado'.

    Procura o Lead pelo `token_confirmacao`. Encontrado e não removido → passa a
    'confirmado' (idempotente: reconfirmar mantém 'confirmado'). Token vazio,
    desconhecido, ou Lead já removido → página de "ligação inválida" (não rebenta,
    não reativa um opt-out). Renderiza `confirma.html`.

    Des-supressão (parecer RGPD red-team §4a): confirmar é um re-consentimento
    EXPLÍCITO (o próprio titular clicou), pelo que se REMOVE o email da lista de
    supressão (`optouts`) — senão a pessoa re-autorizava mas continuaria excluída
    pelo núcleo de compliance. A supressão só cede a esta revogação pelo titular.
    """
    confirmado = False
    if token.strip():
        with db.get_session() as s:
            lead = (
                s.query(models.Lead)
                .filter(models.Lead.token_confirmacao == token.strip())
                .first()
            )
            if lead is not None and lead.estado != "removido":
                lead.estado = "confirmado"  # commit no fim do `with`
                optout = s.get(models.OptOut, normalizar_email(lead.email))
                if optout is not None:
                    s.delete(optout)  # des-suprime: o titular reautorizou
                confirmado = True

    status = 200 if confirmado else 404
    return templates.TemplateResponse(
        request, "confirma.html", {"confirmado": confirmado}, status_code=status
    )
