"""Autenticação do painel admin do CheckAL (SPEC-FASE1-DASHBOARD §auth).

A **fundação** de toda a FASE 1 · WF3: o painel é do DONO e só do dono. Aqui vive o
mínimo de segurança de que o resto do admin depende — e é CÓDIGO, não confiança:

    GET  /admin/login   → o formulário (pede a palavra-passe);
    POST /admin/login   → se `password == config.ADMIN_PASSWORD`, cria uma sessão num
                          COOKIE ASSINADO e redireciona para `/admin`; senão recusa
                          (401) e reexibe o formulário — sem cookie de sessão;
    GET  /admin/logout  → apaga o cookie e volta ao login;
    requer_admin        → a dependência FastAPI que guarda TODAS as rotas `/admin/*`
                          (exceto o próprio login/logout): sem sessão válida,
                          redireciona (303) para `/admin/login`.

**A sessão é um cookie ASSINADO, não um cookie de confiança.** Assina-se com
`itsdangerous.URLSafeTimedSerializer(config.SECRET_KEY)`: o servidor não guarda
estado de sessão nenhum — a posse de um cookie com assinatura válida (só forjável por
quem tem a `SECRET_KEY`) É a prova de autenticação. Um cookie adulterado/forjado falha
a verificação da assinatura e é rejeitado; a password NUNCA viaja no cookie. O token
carimba a hora, pelo que caduca ao fim de `SESSAO_MAX_IDADE_S`.

**Fail-closed em duas frentes:**
  * a password compara-se em tempo constante (`hmac.compare_digest`) e, se
    `config.ADMIN_PASSWORD` estiver vazia (o default sob pytest / sem `.env`),
    NENHUMA password entra — o mesmo espírito de `config.assert_seguro`, que em
    produção recusa arrancar sem password;
  * `config.cookie_secure()` põe o `Secure` no cookie em produção (só HTTPS) e
    relaxa-o sob pytest (o `TestClient` fala http e perderia um cookie `Secure`).

O login/logout são deliberadamente PÚBLICOS (não dependem de `requer_admin`, senão
não haveria como entrar); é o router do dashboard que aplica `requer_admin` às suas
rotas. LIVE-GATED: este módulo não toca a rede nem a BD — só assina/valida o cookie e
renderiza o login pelo Jinja PARTILHADO (`app.web.marca.templates`, autoescape ligado
⇒ anti-XSS).
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import app.config as config
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# --- Constantes da sessão --------------------------------------------------
COOKIE_NOME = "checkal_admin"
LOGIN_URL = "/admin/login"
LOGOUT_URL = "/admin/logout"
POS_LOGIN_URL = "/admin"                 # para onde se entra depois de autenticar
# `salt` isola este uso da SECRET_KEY de quaisquer outros tokens assinados (ex.
# double opt-in): um token de sessão nunca é aceite noutro contexto e vice-versa.
_SALT = "checkal-admin-sessao"
_PAYLOAD = "dono"                         # o conteúdo assinado (marcador; a prova é a assinatura)
SESSAO_MAX_IDADE_S = 7 * 24 * 3600       # a sessão caduca ao fim de 7 dias
_TEMPLATE = "admin/login.html"


def _serializer() -> URLSafeTimedSerializer:
    """Serializer HMAC ligado à `config.SECRET_KEY` ATUAL (lida a cada chamada).

    Ler a chave em cada chamada (em vez de a fixar no import) deixa os testes e a
    rotação de segredo funcionarem sem reimportar o módulo.
    """
    return URLSafeTimedSerializer(config.SECRET_KEY, salt=_SALT)


def criar_token_sessao() -> str:
    """Assina e devolve o token de sessão do dono (a colocar no cookie)."""
    return _serializer().dumps(_PAYLOAD)


def sessao_valida(token: str | None) -> bool:
    """True sse `token` é um cookie de sessão com assinatura válida e não caducado.

    Rejeita ausência, adulteração (assinatura partida) e expiração — em qualquer
    dúvida devolve False (fail-closed). Nunca lança.
    """
    if not token:
        return False
    try:
        valor = _serializer().loads(token, max_age=SESSAO_MAX_IDADE_S)
    except (BadSignature, SignatureExpired):
        return False
    return valor == _PAYLOAD


def _password_correta(candidata: str) -> bool:
    """Compara a password em tempo constante com `config.ADMIN_PASSWORD` (lida agora).

    Fail-closed: se a esperada estiver vazia (default sob pytest / sem `.env`),
    recusa SEMPRE — nunca se entra num sistema sem password configurada.
    """
    esperada = config.ADMIN_PASSWORD or ""
    if not esperada:
        return False
    return hmac.compare_digest(candidata or "", esperada)


def requer_admin(request: Request) -> None:
    """Dependência que guarda uma rota `/admin/*`: exige sessão assinada válida.

    Sem cookie válido, redireciona (303 See Other) para o login em vez de devolver
    um 401 cru — é um painel de browser, o dono deve cair na página de entrada. O
    redirect faz-se levantando `HTTPException` com o cabeçalho `Location` (padrão
    FastAPI para redirecionar a partir de uma dependência).
    """
    if not sessao_valida(request.cookies.get(COOKIE_NOME)):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": LOGIN_URL},
        )


def _definir_cookie_sessao(resp: RedirectResponse) -> None:
    """Carimba o cookie de sessão assinado na resposta (HttpOnly, SameSite=Lax).

    `secure` segue `config.cookie_secure()` — HTTPS-only em produção, relaxado sob
    pytest. `HttpOnly` (fora do alcance de JS) + `SameSite=Lax` (mitiga CSRF do
    cookie de sessão). `max_age` faz o browser esquecer a sessão ao fim de 7 dias,
    a par da expiração assinada no próprio token.
    """
    resp.set_cookie(
        key=COOKIE_NOME,
        value=criar_token_sessao(),
        max_age=SESSAO_MAX_IDADE_S,
        httponly=True,
        secure=config.cookie_secure(),
        samesite="lax",
        path="/",
    )


def _render_login(request: Request, *, erro: str | None = None, status_code: int = 200) -> HTMLResponse:
    """Renderiza `admin/login.html` pelo Jinja partilhado (marca já nos globais)."""
    return templates.TemplateResponse(
        request,
        _TEMPLATE,
        {"erro": erro},
        status_code=status_code,
    )


@router.get(LOGIN_URL, response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    """Mostra o formulário de entrada do painel."""
    return _render_login(request)


@router.post(LOGIN_URL)
def login_submeter(request: Request, password: str = Form(...)):
    """Verifica a password; se certa, abre sessão e redireciona para `/admin`.

    Password errada (ou vazia, ou sem password configurada) ⇒ 401 com o formulário
    reexibido e uma mensagem de erro — e SEM cookie de sessão.
    """
    if not _password_correta(password):
        return _render_login(
            request,
            erro="Palavra-passe incorreta.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    resp = RedirectResponse(url=POS_LOGIN_URL, status_code=status.HTTP_303_SEE_OTHER)
    _definir_cookie_sessao(resp)
    return resp


@router.get(LOGOUT_URL)
def logout() -> RedirectResponse:
    """Termina a sessão: apaga o cookie e volta ao login."""
    resp = RedirectResponse(url=LOGIN_URL, status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(COOKIE_NOME, path="/")
    return resp
