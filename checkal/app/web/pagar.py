"""Página `/pagar` + callback IfThenPay — a via de cobrança cold-direto (Fase G).

Decisões do dono (ADENDA §1–§5), todas encodadas:

  - O email frio leva DOIS CTAs ("Pagar já" / "Fazer o check grátis"); o
    "Pagar já" aponta para uma **URL assinada e com validade** →
    ``checkal.pt/pagar?t=<token>``. O token referencia
    ``{campanha, segmento, nr_registo?, plano_sugerido}`` e **não contém PII**.
  - A página é própria, "clean" e transmite SEGURANÇA (requisito, não estética):
    identificação completa (Cosmic Oasis, Lda. · NIPC · morada), "serviço
    privado e independente", marcas Multibanco/MB Way, "pagamento processado
    por IfThenPay", **T&C visíveis + captura de NIF + aceitação ANTES do
    pagamento**, fatura prometida no ecrã, sem dark patterns.
  - Métodos: Referência Multibanco + MB Way (confirmam por **callback** com
    anti-phishing key → ativação automática) + Transferência (IBAN) —
    reconciliação **semi-manual** (`por_casar`, resolvida pelo GESTOR via
    :func:`casar_transferencia`).
  - Fatura (TOConline, **série CKL** — guarda `SerieNaoConfigurada` a jusante)
    e onboarding SÓ com callback **pago**: o callback reutiliza
    `fulfillment.processar_checkout` (só muda a ORIGEM do gatilho — em vez do
    webhook Stripe). Stripe fica secundário/inalterado.
  - Renovação a D-30: :func:`gerar_token_renovacao` gera nova passagem por
    `/pagar` (nova referência/MB Way — **sem cartão guardado**); o ciclo de
    renovação/dunning por referência é do GESTOR-DE-CLIENTE.

LIVE-GATED: sem chaves IfThenPay, a geração devolve ``None`` (o pagamento fica
`pendente`, sem rede); sem anti-phishing key configurada, NENHUM callback é
aceite; o emissor de faturas segue o seam `app.faturacao.obter_emissor`
(``None`` sob modo de teste). A suite corre 100 % offline.
"""
from __future__ import annotations

import html as _html
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import app.config as config
import app.db as db
import app.models_swarm as ms
from app import fulfillment
from app.faturacao import ifthenpay_client as itp
from app.faturacao import obter_emissor

__all__ = [
    "router",
    "TC_VERSAO",
    "gerar_token_pagamento",
    "gerar_token_renovacao",
    "ler_token",
    "casar_transferencia",
]

router = APIRouter()

# Versão dos T&C aceites na página (prova de contrato — dossier v2, termos.html).
TC_VERSAO = "termos-2026-07-12"

# Validade do token do CTA (dias); a ADENDA exige "URL assinada e com validade".
TOKEN_VALIDADE_S = int(config._env("CHECKAL_PAGAR_TOKEN_DIAS", "30")) * 86400

# IBAN da transferência (dado pelo dono no ambiente; placeholder até lá).
IBAN = config._env("CHECKAL_IBAN", "[IBAN a confirmar]")

_METODOS = ("mbref", "mbway", "transferencia")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# ==========================================================================
#  Token assinado (sem PII) — CTA do cold + renovação D-30
# ==========================================================================
def _serializador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt="checkal-pagar")


def gerar_token_pagamento(
    *,
    campanha_id: int | None = None,
    segmento: str | None = None,
    nr_registo: int | None = None,
    plano_sugerido: str | None = None,
) -> str:
    """Assina o token do CTA "Pagar já". SÓ referências — NUNCA dados pessoais.

    A assinatura dos kwargs é fechada de propósito: passar um campo de PII
    (email/nome/NIF) rebenta com ``TypeError`` — o portão é a própria assinatura.
    """
    payload = {
        "campanha_id": campanha_id, "segmento": segmento,
        "nr_registo": nr_registo, "plano_sugerido": plano_sugerido,
    }
    return _serializador().dumps({k: v for k, v in payload.items() if v is not None})


def gerar_token_renovacao(*, cliente_id: int, plano: str = "anual") -> str:
    """Token de RENOVAÇÃO a D-30 — reutiliza o fluxo `/pagar` (sem cartão guardado)."""
    return _serializador().dumps(
        {"renovacao_cliente": cliente_id, "plano_sugerido": plano}
    )


def ler_token(token: str, max_age_s: int | None = None) -> dict | None:
    """Lê e valida o token assinado; expirado/adulterado ⇒ ``None`` (rejeitado)."""
    try:
        return _serializador().loads(
            token, max_age=TOKEN_VALIDADE_S if max_age_s is None else max_age_s
        )
    except (BadSignature, SignatureExpired):
        return None


# ==========================================================================
#  Emissor de faturas — seam idêntico ao do webhook Stripe (LIVE-GATED)
# ==========================================================================
def _emissor() -> Any:
    """Delegado de `app.faturacao.obter_emissor` — ``None`` sob modo de teste.

    Nos testes é substituído por um duplo com um emissor falso (mesmo padrão de
    `web.webhook_stripe._emissor`). A série CKL é guardada a jusante
    (`SerieNaoConfigurada` dispara antes de qualquer HTTP).
    """
    return obter_emissor()


def _fulfillment_do_pagamento(pagamento: ms.Pagamento, emitir_fatura: Any) -> None:
    """Dispara o MESMO fulfillment do checkout — só muda a origem do gatilho.

    Constrói uma sessão sintética `ifthenpay:<order_id>` (idempotente pelo UNIQUE
    de `clientes.stripe_session_id`) e delega em `fulfillment.processar_checkout`:
    match do registo → cliente → fatura certificada (série CKL) → onboarding.
    """
    sessao = {
        "id": f"ifthenpay:{pagamento.order_id}",
        "customer": None,
        "customer_details": {"email": pagamento.email, "name": "", "address": {}},
        "custom_fields": [
            {"key": "nif", "type": "text", "text": {"value": pagamento.nif}},
            {"key": "nr_registo_al", "type": "text",
             "text": {"value": str(pagamento.nr_registo or "")}},
        ],
        "metadata": {"plano": pagamento.plano},
        "amount_total": pagamento.valor_cent,
    }
    fulfillment.processar_checkout(sessao, emitir_fatura=emitir_fatura)


# ==========================================================================
#  Página — blocos HTML (confiança primeiro; sem dark patterns)
# ==========================================================================
def _pagina(corpo: str, *, status_code: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagar — CheckAL</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
      background:#FAF7F2;color:#1F2937;margin:0;padding:24px;}}
 main{{max-width:640px;margin:0 auto;background:#fff;border-radius:14px;
      padding:28px;box-shadow:0 1px 8px rgba(0,0,0,.06);}}
 h1{{font-size:24px;margin:0 0 6px 0}} label{{display:block;margin:12px 0 4px;font-weight:600}}
 input,select{{width:100%;padding:10px;border:1px solid #D1D5DB;border-radius:8px;font-size:16px}}
 button{{margin-top:18px;padding:13px 22px;background:#2563EB;color:#fff;border:0;
        border-radius:10px;font-size:16px;font-weight:600;cursor:pointer}}
 .selo{{color:#12B76A;font-weight:700}} .nota{{font-size:13px;color:#6B7280;margin-top:16px}}
 .caixa{{background:#F3F6FA;border-radius:10px;padding:12px 16px;margin:14px 0}}
</style></head><body><main>{corpo}</main></body></html>"""
    return HTMLResponse(html, status_code=status_code)


_RODAPE_CONFIANCA = (
    '<div class="nota">'
    "<p><strong>CheckAL</strong> é um serviço <strong>privado e independente</strong> "
    "de monitorização de Alojamento Local — sem vínculo ao Turismo de Portugal, ao "
    "RNAL ou a qualquer câmara municipal.</p>"
    "<p>Operado por <strong>Cosmic Oasis, Lda.</strong> · NIPC: [NIPC] · [morada]. "
    "Pagamento processado por <strong>IfThenPay</strong> (Referência "
    "<strong>Multibanco</strong> · <strong>MB Way</strong> · Transferência). "
    "Recebe a <strong>fatura-recibo</strong> por email após a confirmação do "
    "pagamento.</p>"
    '<p><a href="/termos">Termos e Condições</a> · '
    '<a href="/privacidade">Política de privacidade</a></p>'
    "</div>"
)


def _erro(mensagem: str, status_code: int = 400) -> HTMLResponse:
    corpo = (
        f"<h1>CheckAL <span class='selo'>✓</span></h1><p>{_html.escape(mensagem)}</p>"
        '<p><a href="https://checkal.pt">Ir para checkal.pt</a> — pode sempre fazer '
        "o check grátis do seu AL e voltar a este passo.</p>" + _RODAPE_CONFIANCA
    )
    return _pagina(corpo, status_code=status_code)


def _opcoes_planos(sugerido: str | None) -> str:
    linhas = []
    for codigo in ("anual", "trienal", "portfolio"):
        dados = config.PLANOS[codigo]
        sel = " selected" if codigo == (sugerido or "anual") else ""
        linhas.append(
            f'<option value="{codigo}"{sel}>{_html.escape(dados["nome"])} — '
            f'{dados["preco"]:.0f}€ (IVA incluído)</option>'
        )
    return "".join(linhas)


@router.get("/pagar", response_class=HTMLResponse)
def pagar_get(request: Request, t: str = "") -> HTMLResponse:
    """A página de pagamento (ADENDA §2). Token inválido/expirado ⇒ rejeitado."""
    dados = ler_token(t) if t else None
    if dados is None:
        return _erro(
            "Este link de pagamento expirou ou não é válido. Por segurança, os "
            "links têm validade limitada."
        )

    nr = dados.get("nr_registo")
    contexto_al = (
        f'<div class="caixa">Registo de AL pré-selecionado: <strong>n.º '
        f"{int(nr)}</strong> — confirmamos tudo no relatório inicial.</div>"
        if nr else ""
    )
    corpo = (
        "<h1>Ativar o CheckAL <span class='selo'>✓</span></h1>"
        "<p>Vigilância contínua do registo RNAL, do seguro obrigatório e dos "
        "regulamentos do concelho — com alertas explicados e um relatório mensal.</p>"
        + contexto_al +
        f'<form method="post" action="/pagar">'
        f'<input type="hidden" name="t" value="{_html.escape(t)}">'
        '<label for="plano">Plano</label>'
        f'<select id="plano" name="plano">{_opcoes_planos(dados.get("plano_sugerido"))}</select>'
        '<label for="nif">NIF (para a fatura-recibo)</label>'
        '<input id="nif" name="nif" inputmode="numeric" required '
        'placeholder="NIF para a fatura">'
        '<label for="email">Email</label>'
        '<input id="email" name="email" type="email" required '
        'placeholder="onde recebe os alertas e a fatura">'
        '<label for="telemovel">Telemóvel (só para MB Way)</label>'
        '<input id="telemovel" name="telemovel" inputmode="tel" placeholder="9XXXXXXXX">'
        '<label for="metodo">Método de pagamento</label>'
        '<select id="metodo" name="metodo">'
        '<option value="mbref">Referência Multibanco</option>'
        '<option value="mbway">MB Way</option>'
        '<option value="transferencia">Transferência bancária (IBAN)</option>'
        "</select>"
        '<label style="font-weight:400;margin-top:14px">'
        '<input type="checkbox" name="tc_aceite" value="1" style="width:auto"> '
        'Li e aceito os <a href="/termos" target="_blank">Termos e Condições</a> '
        "e a <a href='/privacidade' target='_blank'>política de privacidade</a>.</label>"
        "<button type='submit'>Continuar para o pagamento</button>"
        "</form>"
        "<p class='nota'>Sem subscrição automática de cartão: na renovação anual "
        "receberá uma nova referência — decide sempre em cada renovação.</p>"
        + _RODAPE_CONFIANCA
    )
    return _pagina(corpo)


def _nif_valido(nif: str) -> bool:
    limpo = nif.strip().replace(" ", "")
    return len(limpo) == 9 and limpo.isascii() and limpo.isdigit()


@router.post("/pagar", response_class=HTMLResponse)
def pagar_post(
    request: Request,
    t: str = Form(""),
    plano: str = Form("anual"),
    nif: str = Form(""),
    email: str = Form(""),
    telemovel: str = Form(""),
    metodo: str = Form("mbref"),
    tc_aceite: str = Form(""),
) -> HTMLResponse:
    """Capta NIF + email + aceitação dos T&C ANTES de gerar o método (ao vivo)."""
    dados = ler_token(t) if t else None
    if dados is None:
        return _erro("Este link de pagamento expirou ou não é válido.")
    if not tc_aceite:
        return _erro(
            "É preciso aceitar os Termos e Condições antes do pagamento — sem "
            "aceitação não há contrato nem fatura."
        )
    if not _nif_valido(nif):
        return _erro("O NIF tem de ter 9 dígitos (é usado na fatura-recibo).")
    if "@" not in email or "." not in email.split("@")[-1]:
        return _erro("O email não parece válido.")
    if plano not in config.PLANOS:
        return _erro("Plano desconhecido.")
    if metodo not in _METODOS:
        return _erro("Método de pagamento desconhecido.")
    if metodo == "mbway" and not telemovel.strip():
        return _erro("O MB Way precisa do número de telemóvel.")

    preco = float(config.PLANOS[plano]["preco"])
    order_id = f"CKL-{uuid.uuid4().hex[:10].upper()}"
    agora = _agora()

    with db.get_session() as s:
        pagamento = ms.Pagamento(
            order_id=order_id,
            campanha_id=dados.get("campanha_id"),
            nr_registo=dados.get("nr_registo"),
            plano=plano,
            valor_cent=round(preco * 100),
            metodo=metodo,
            estado="por_casar" if metodo == "transferencia" else "pendente",
            nif=nif.strip(),
            email=email.strip(),
            tc_versao=TC_VERSAO,
            tc_aceite_em=agora,
            criado_em=agora,
        )
        s.add(pagamento)
        s.flush()

        # Geração AO VIVO (Opção A) — LIVE-GATED: sem chaves devolve None.
        detalhe = ""
        if metodo == "mbref":
            ref = itp.gerar_referencia_mb(order_id, preco, validade_dias=7)
            if ref is not None:
                pagamento.ifthenpay_ref = f"{ref['entidade']} {ref['referencia']}"
                detalhe = (
                    f'<div class="caixa"><strong>Entidade:</strong> {ref["entidade"]}'
                    f' · <strong>Referência:</strong> {ref["referencia"]}'
                    f' · <strong>Valor:</strong> {ref["valor"]}€</div>'
                    "<p>Assim que o pagamento for confirmado, ativamos a vigilância "
                    "e enviamos a fatura-recibo por email.</p>"
                )
            else:
                detalhe = (
                    "<p>De momento não foi possível gerar a referência Multibanco. "
                    "Guardámos o seu pedido — receberá a referência por email "
                    "muito em breve, sem qualquer custo adicional.</p>"
                )
        elif metodo == "mbway":
            pedido = itp.iniciar_mbway(order_id, preco, telemovel.strip())
            if pedido is not None:
                pagamento.ifthenpay_id = pedido["id_pedido"]
                detalhe = (
                    "<p>Enviámos o pedido para a sua app <strong>MB Way</strong> "
                    f"({_html.escape(telemovel.strip())}). Confirme no telemóvel; "
                    "assim que o pagamento entrar, ativamos tudo e enviamos a "
                    "fatura-recibo.</p>"
                )
            else:
                detalhe = (
                    "<p>De momento não foi possível iniciar o MB Way. Guardámos o "
                    "seu pedido — entraremos em contacto por email muito em breve.</p>"
                )
        else:  # transferencia
            detalhe = (
                f'<div class="caixa"><strong>IBAN:</strong> {_html.escape(IBAN)}'
                f' · <strong>Referência interna:</strong> {order_id}'
                f' · <strong>Valor:</strong> {preco:.2f}€</div>'
                "<p>Use a referência interna na descrição da transferência. A "
                "confirmação é manual e pode demorar até 1 dia útil; depois "
                "ativamos a vigilância e enviamos a fatura-recibo.</p>"
            )

    corpo = (
        "<h1>Quase lá <span class='selo'>✓</span></h1>"
        f"<p>Pedido <strong>{order_id}</strong> · plano "
        f"<strong>{_html.escape(config.PLANOS[plano]['nome'])}</strong> · "
        f"<strong>{preco:.0f}€</strong> (IVA incluído).</p>"
        + detalhe +
        "<p class='nota'>A fatura-recibo é emitida após a confirmação do "
        "pagamento e enviada para o seu email.</p>"
        + _RODAPE_CONFIANCA
    )
    return _pagina(corpo)


# ==========================================================================
#  Callback IfThenPay — idempotente; antiphishing obrigatória; fulfillment
# ==========================================================================
@router.post("/callback/ifthenpay")
async def callback_ifthenpay(request: Request):
    """Confirmação MB/MB Way. Fatura + onboarding SÓ aqui (callback pago)."""
    payload: dict = dict(request.query_params)
    try:
        corpo = await request.json()
        if isinstance(corpo, dict):
            payload.update(corpo)
    except Exception:  # noqa: BLE001 — callbacks reais vêm por query string
        pass

    veredicto = itp.verificar_callback(payload)
    if not veredicto.get("ok"):
        return HTMLResponse("antiphishing inválida", status_code=403)

    order_id = veredicto["order_id"]
    with db.get_session() as s:
        pagamento = (
            s.query(ms.Pagamento)
            .filter(ms.Pagamento.order_id == order_id).first()
        )
        if pagamento is None:
            return HTMLResponse("order desconhecida", status_code=404)
        if pagamento.estado == "pago":
            return HTMLResponse("OK (idempotente)")  # reentrega — nada a refazer
        valor_cent = veredicto.get("valor_cent")
        if valor_cent is not None and valor_cent != pagamento.valor_cent:
            return HTMLResponse("montante divergente", status_code=400)
        pagamento_id = pagamento.id

    # Fulfillment ANTES de marcar pago: se falhar, o estado fica `pendente` e a
    # reentrega do callback volta a tentar (o fulfillment é idempotente pela
    # sessão sintética `ifthenpay:<order_id>` — nunca 2.º documento fiscal).
    emitir = _emissor()
    with db.get_session() as s:
        pagamento = s.get(ms.Pagamento, pagamento_id)
        if emitir is not None:
            _fulfillment_do_pagamento(pagamento, emitir)
        pagamento.estado = "pago"
        pagamento.pago_em = _agora()

    return HTMLResponse("OK")


# ==========================================================================
#  Transferência — reconciliação semi-manual (GESTOR) → mesmo fulfillment
# ==========================================================================
def casar_transferencia(
    session,
    *,
    order_id: str,
    valor_cent: int,
    emitir_fatura: Any | None = None,
) -> ms.Pagamento:
    """Casa uma transferência recebida (montante + referência interna → order).

    Chamado no circuito do GESTOR-DE-CLIENTE **depois** da confirmação humana do
    extrato (a emissão de fatura é irreversível — camada alta do gate). Montante
    divergente ⇒ ``ValueError`` e nada muda. Idempotente: já pago ⇒ devolve.
    """
    pagamento = (
        session.query(ms.Pagamento)
        .filter(ms.Pagamento.order_id == order_id).first()
    )
    if pagamento is None:
        raise ValueError(f"pagamento {order_id!r} inexistente")
    if pagamento.estado == "pago":
        return pagamento
    if pagamento.estado != "por_casar":
        raise ValueError(f"pagamento {order_id!r} não está por casar ({pagamento.estado})")
    if valor_cent != pagamento.valor_cent:
        raise ValueError(
            f"montante {valor_cent} não bate com o pedido {pagamento.valor_cent}"
        )

    emitir = emitir_fatura if emitir_fatura is not None else _emissor()
    if emitir is not None:
        _fulfillment_do_pagamento(pagamento, emitir)
    pagamento.estado = "pago"
    pagamento.pago_em = _agora()
    session.flush()
    return pagamento
