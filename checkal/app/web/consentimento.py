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
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.config as config
import app.db as db
import app.envio as envio
import app.models as models
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# ==========================================================================
#  Texto e versão do consentimento — a PROVA que se grava (RGPD art. 7/1)
# ==========================================================================
# A versão sobe sempre que o texto mudar, para que cada Lead aponte para a redação
# EXATA que o titular aceitou. Grava-se o texto versionado inteiro (auto-descritivo).
CONSENTIMENTO_VERSAO = "2026-07-05"
CONSENTIMENTO_TEXTO = (
    "Autorizo a Cosmic Oasis, Lda. (CheckAL) a enviar-me, por email, o relatório "
    "gratuito do meu Alojamento Local e comunicações sobre o serviço. Posso retirar "
    "o consentimento a qualquer momento em checkal.pt/remover."
)


def _consentimento_versionado() -> str:
    """A prova textual auto-descritiva: versão + o texto EXATO mostrado ao titular."""
    return f"[v{CONSENTIMENTO_VERSAO}] {CONSENTIMENTO_TEXTO}"


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


def _email_confirmacao_html(token: str) -> str:
    """HTML provisório do double opt-in (substituído pelo template WF2 no wiring).

    Copy factual, PT-PT, voz "inspetor amigo". O `token` é URL-safe (secrets), mas
    escapa-se na mesma por defesa em profundidade (autoescape só cobre o Jinja).
    """
    url = escape(_url_confirmacao(token))
    return (
        "<p>Olá,</p>"
        "<p>Falta um passo para o <strong>CheckAL</strong> começar a vigiar o teu "
        "Alojamento Local. Confirma que és tu ao carregar na ligação:</p>"
        f'<p><a href="{url}">Confirmar a minha inscrição ✓</a></p>'
        f"<p>Se a ligação não abrir, copia este endereço: {url}</p>"
        "<p>Se não foste tu a pedir isto, ignora este email — nada acontece sem esta "
        "confirmação.</p>"
        '<p style="font-size:.85em;color:#475569">CheckAL — serviço privado e '
        "independente de monitorização de Alojamento Local · Cosmic Oasis, Lda.</p>"
    )


def _disparar_double_opt_in(email: str, token: str) -> None:
    """Dispara o email de confirmação pelo seam LIVE-GATED, sem nunca rebentar o request.

    `envio.obter_enviador()` devolve `None` sob modo de teste ou sem chave — nesse caso
    não há para onde enviar e simplesmente não se envia (o Lead já ficou gravado com a
    prova). Uma falha de transporte é engolida: a inscrição não pode falhar por causa do
    email — o titular pode sempre repetir, e a prova de consentimento persiste.
    """
    enviar = envio.obter_enviador()
    if enviar is None:
        return
    try:
        enviar(
            para=email,
            assunto="Confirma a tua inscrição no CheckAL ✓",
            html=_email_confirmacao_html(token),
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
#  Rotas
# ==========================================================================
@router.post("/inscrever", response_model=None)
def inscrever(
    request: Request,
    email: str = Form(default=""),
    consentimento: str | None = Form(default=None),
    nr_registo: str | None = Form(default=None),
    concelho: str | None = Form(default=None),
) -> HTMLResponse | RedirectResponse:
    """Inscreve um interessado consent-first e dispara o double opt-in.

    Fluxo: valida email + consentimento → cria `Lead` 'pendente' com a PROVA (texto+
    versão, timestamp, IP) → email de confirmação (LIVE-GATED) → 303 `/obrigado`.
    Sem email válido ou sem consentimento → 400 (nada gravado, nada enviado).
    """
    if not _email_valido(email) or not _consentiu(consentimento):
        # Falha fechado: não cria Lead nem envia. 400 com página sem eco de input.
        return HTMLResponse(content=_PAGINA_ERRO, status_code=400)

    agora = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)

    with db.get_session() as s:
        s.add(models.Lead(
            email=email.strip(),
            nr_registo=_parse_nr(nr_registo),
            concelho=_limpar(concelho),
            consentimento_texto_versao=_consentimento_versionado(),  # a PROVA (texto+versão)
            consentimento_em=agora,                                  # a PROVA (quando)
            ip=_ip_do_request(request),                              # a PROVA (de onde)
            estado="pendente",
            token_confirmacao=token,
            criado_em=agora,
        ))
        # commit no fim do `with` (db.get_session): a prova fica DURÁVEL antes do envio.

    # Double opt-in: best-effort e LIVE-GATED — nunca rebenta o request (Lead já gravado).
    _disparar_double_opt_in(email.strip(), token)

    # 303 See Other: após um POST, o browser segue com GET para /obrigado (evita reenvio).
    return RedirectResponse(url="/obrigado", status_code=303)


@router.get("/confirmar", response_class=HTMLResponse)
def confirmar(request: Request, token: str = "") -> HTMLResponse:
    """Ativa o Lead do double opt-in: 'pendente' → 'confirmado'.

    Procura o Lead pelo `token_confirmacao`. Encontrado e não removido → passa a
    'confirmado' (idempotente: reconfirmar mantém 'confirmado'). Token vazio,
    desconhecido, ou Lead já removido → página de "ligação inválida" (não rebenta,
    não reativa um opt-out). Renderiza `confirma.html`.
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
                confirmado = True

    status = 200 if confirmado else 404
    return templates.TemplateResponse(
        request, "confirma.html", {"confirmado": confirmado}, status_code=status
    )
