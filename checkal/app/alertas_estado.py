"""Alertas de estado do registo RNAL (FDS 3, SPEC-FDS3.md §alertas_estado).

Consome a fila de `eventos_registo` (os diffs do varrimento nacional detetados no
FDS 1) e, para cada cliente casado ao registo em causa, compõe um **alerta
determinístico por template** (NUNCA IA — a redação IA é do FDS 4), persiste-o em
`alertas` e — quando é caso disso — envia-o pelo enviador transacional injetado.

Mapa evento → ação para o cliente (`models.EventoRegisto.tipo`):

    novo          → ignora-se (um registo novo a nível nacional não é evento de
                    um cliente já existente); o evento é só drenado da fila.
    alterado      → compõe alerta (lista os campos que mudaram) e ENVIA.
    reapareceu    → compõe alerta ("voltou a constar") e ENVIA.
    desaparecido  → 🚦 GUARDA DE SEQUÊNCIA: compõe e PERSISTE o alerta, mas
                    marca-o pendente_desambiguacao e **NÃO** envia — espera a
                    desambiguação do FDS 5 (`app/rnal/LIMITACOES-CONHECIDAS.md`).

Disciplina inviolável (SPEC-FDS3):
  - **MODO DE TESTE, LIVE-GATED.** O `enviar` é **injetado** por quem chama (dublê
    nos testes; em produção o *callable* de `app.envio.obter_enviador`). Este módulo
    nunca cria clientes HTTP — logo os testes nunca tocam a rede.
  - **🚦 `desaparecido` NUNCA é enviado antes do FDS 5.** Persiste-se com o canal
    `pendente_desambiguacao` e `enviado_em IS NULL`; o FDS 5, após desambiguar,
    encontra estes pendentes e decide enviar ou descartar. A tabela `alertas` não
    tem coluna booleana dedicada (esquema fechado no FDS 2), pelo que o par
    (`canal == CANAL_PENDENTE`, `enviado_em IS NULL`) **é** o marcador durável do
    pendente — ver :func:`pendente_desambiguacao`.
  - **G4.** O alerta de `desaparecido` **nunca** afirma "cancelado": diz que o
    registo deixou de constar no varrimento e que se está a reconfirmar. A fonte de
    verdade do cancelamento é a desambiguação (FDS 5), não este alerta.
  - **Idempotência.** A âncora é `eventos_registo.processado`: cada evento tratado é
    marcado `processado=True` na mesma transação, pelo que uma 2.ª passagem não o
    revê. Correr `gerar_alertas_estado` duas vezes não duplica alertas nem envios.

Fronteira: a função recebe a **`session`** de quem chama (não abre a sua) e não faz
commit — a transação é do orquestrador (o cron do wire, sob `db.get_session`). Assim,
se `enviar` levantar, o rollback do chamador desfaz o alerta e o evento fica por
processar (retry natural na passagem seguinte; o `idempotency_key` da Resend evita
duplicados no lado do fornecedor).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import app.config as config
import app.models as models
from app.emails import transacional as _emails
from app.rnal.diffing import (
    TIPO_ALTERADO,
    TIPO_DESAPARECIDO,
    TIPO_NOVO,
    TIPO_REAPARECEU,
)

__all__ = [
    "ORIGEM_EVENTO_REGISTO",
    "CANAL_EMAIL",
    "CANAL_PENDENTE",
    "gerar_alertas_estado",
    "pendente_desambiguacao",
]

# Valor de `Alerta.origem` para os alertas nascidos da fila `eventos_registo`
# (a par de "eventos_regulatorios", que virá do FDS 4).
ORIGEM_EVENTO_REGISTO = "eventos_registo"

# Canais de `Alerta.canal`. `CANAL_PENDENTE` marca o alerta de `desaparecido`
# persistido mas retido para o FDS 5 (🚦 guarda de sequência); qualquer alerta
# efetivamente entregue leva `CANAL_EMAIL`.
CANAL_EMAIL = "email"
CANAL_PENDENTE = "pendente_desambiguacao"

# Assinatura do enviador injetado (só para leitura; não impõe verificação).
Enviar = Callable[..., Any]

# Rótulos legíveis dos campos do RNAL, para a lista de alterações do alerta
# `alterado` (espelham `app.rnal.hashing.CAMPOS_RELEVANTES`).
_ROTULOS_CAMPO: dict[str, str] = {
    "nome_alojamento": "nome do alojamento",
    "modalidade": "modalidade",
    "nr_camas": "nº de camas",
    "nr_utentes": "nº de utentes",
    "endereco": "endereço",
    "cod_postal": "código postal",
    "freguesia": "freguesia",
    "concelho": "concelho",
    "distrito": "distrito",
    "titular_tipo": "tipo de titular",
    "titular_nome": "titular",
    "nif": "NIF",
    "email": "email",
    "telefone": "telefone",
    "telemovel": "telemóvel",
}

# Mapa tipo de evento de registo → estado visual 🟢🟡🔴 do template `alerta_estado`.
# `reapareceu` é boa notícia (verde); `alterado` pede revisão (âmbar); `desaparecido`
# é o pior caso (coral) — mas NUNCA é enviado antes do FDS 5 (guarda de sequência).
_ESTADO_POR_TIPO: dict[str, str] = {
    TIPO_ALTERADO: "amarelo",
    TIPO_REAPARECEU: "verde",
    TIPO_DESAPARECIDO: "vermelho",
}
_TITULO_POR_TIPO: dict[str, str] = {
    TIPO_ALTERADO: "Registo RNAL atualizado",
    TIPO_REAPARECEU: "Registo RNAL voltou a constar",
    TIPO_DESAPARECIDO: "Registo RNAL deixou de constar",
}


# ==========================================================================
#  Marcador durável do "pendente_desambiguacao"
# ==========================================================================
def pendente_desambiguacao(alerta: models.Alerta) -> bool:
    """Diz se este alerta é um `desaparecido` retido à espera do FDS 5.

    O esquema de `alertas` foi fechado no FDS 2 (sem coluna booleana dedicada), por
    isso o pendente é representado pelo par durável (`canal == CANAL_PENDENTE`,
    `enviado_em IS NULL`). O FDS 5 usa isto para varrer os alertas por desambiguar.
    """
    return alerta.canal == CANAL_PENDENTE and alerta.enviado_em is None


# ==========================================================================
#  Composição determinística do conteúdo (por template, NÃO IA)
# ==========================================================================
def _nome_estabelecimento(registo: models.Registo | None, nr: int) -> str:
    """Nome público do estabelecimento, ou um rótulo pelo número se em falta.

    Só dados **públicos** do estabelecimento entram no alerta (nome + nº); nunca o
    titular/NIF, alinhado com a disciplina de minimização.
    """
    if registo is not None and registo.nome_alojamento:
        return registo.nome_alojamento
    return f"nº {nr}"


def _lista_alteracoes(campos_alterados: dict[str, Any] | None) -> str:
    """Frase legível dos campos que mudaram (`«rótulo»: «antes» → «depois»`)."""
    if not campos_alterados:
        return ""
    partes: list[str] = []
    for campo, par in campos_alterados.items():
        rotulo = _ROTULOS_CAMPO.get(campo, campo)
        if isinstance(par, (list, tuple)) and len(par) == 2:
            antes, depois = par
            partes.append(f"{rotulo}: «{antes}» → «{depois}»")
        else:
            partes.append(rotulo)
    return "; ".join(partes)


def _compor(evento: models.EventoRegisto, nome: str, nr: int) -> tuple[str, str]:
    """Devolve `(assunto, texto)` determinístico para o tipo de evento.

    Copy factual, PT-PT, sem inventar. G4: o `desaparecido` nunca diz "cancelado".
    """
    if evento.tipo == TIPO_ALTERADO:
        lista = _lista_alteracoes(evento.campos_alterados)
        detalhe = f" Alterações detetadas — {lista}." if lista else ""
        return (
            f"O registo RNAL do teu AL (nº {nr}) foi atualizado",
            f"O registo RNAL do teu Alojamento Local «{nome}» (nº {nr}) foi atualizado no "
            f"varrimento nacional do RNAL.{detalhe} Confirma se a alteração corresponde ao "
            "que esperas.",
        )
    if evento.tipo == TIPO_REAPARECEU:
        return (
            f"O registo RNAL do teu AL (nº {nr}) voltou a constar",
            f"Boa notícia: o registo RNAL do teu Alojamento Local «{nome}» (nº {nr}) voltou "
            "a constar no varrimento nacional do RNAL.",
        )
    # TIPO_DESAPARECIDO — G4: nunca afirma "cancelado"; está a reconfirmar-se.
    return (
        f"O registo RNAL do teu AL (nº {nr}) deixou de constar — a reconfirmar",
        f"O registo RNAL do teu Alojamento Local «{nome}» (nº {nr}) deixou de constar no "
        "último varrimento nacional do RNAL. Estamos a reconfirmar junto da fonte antes de "
        "tirar qualquer conclusão — não é preciso fazeres nada da tua parte por agora; "
        "avisamos-te assim que confirmarmos.",
    )


# ==========================================================================
#  Ponto de entrada
# ==========================================================================
def gerar_alertas_estado(session: Any, *, enviar: Enviar) -> list[models.Alerta]:
    """Processa a fila de `eventos_registo` e gera os alertas de estado dos clientes.

    Parâmetros
    ----------
    session:
        Sessão SQLAlchemy **de quem chama** (o cron do wire, sob `db.get_session`).
        Esta função não abre sessão nem faz commit — a transação é do chamador.
    enviar:
        `enviar(*, para, assunto, html, anexos, **kw) -> ResultadoEnvio` **injetado**
        (dublê nos testes; em produção o *callable* de `app.envio.obter_enviador`).

    Devolve a lista de :class:`models.Alerta` criados nesta passagem (enviados **e**
    pendentes). Marca cada evento tratado `processado=True` (idempotência).
    """
    pendentes = (
        session.query(models.EventoRegisto)
        .filter(models.EventoRegisto.processado.is_(False))
        .order_by(models.EventoRegisto.id)
        .all()
    )

    criados: list[models.Alerta] = []
    agora = datetime.now(timezone.utc)

    for evento in pendentes:
        # `novo` não gera alerta a clientes; drena-se na mesma (marca processado).
        if evento.tipo == TIPO_NOVO or evento.tipo not in (
            TIPO_ALTERADO, TIPO_REAPARECEU, TIPO_DESAPARECIDO
        ):
            evento.processado = True
            continue

        nr = evento.nr_registo
        clientes = _clientes_do_registo(session, nr) if nr is not None else []
        if clientes:
            registo = session.get(models.Registo, nr)
            nome = _nome_estabelecimento(registo, nr)
            assunto, texto = _compor(evento, nome, nr)
            for cliente in clientes:
                criados.append(
                    _emitir(
                        session, evento=evento, cliente=cliente, nr=nr, nome=nome,
                        assunto=assunto, texto=texto, agora=agora, enviar=enviar,
                    )
                )

        evento.processado = True

    session.flush()  # popula os ids dos alertas criados (sem commit — é do chamador)
    return criados


def _clientes_do_registo(session: Any, nr: int) -> list[models.Cliente]:
    """Clientes casados ao registo `nr` (via `clientes_registos`)."""
    return (
        session.query(models.Cliente)
        .join(models.ClienteRegisto, models.ClienteRegisto.cliente_id == models.Cliente.id)
        .filter(models.ClienteRegisto.nr_registo == nr)
        .order_by(models.Cliente.id)
        .all()
    )


def _emitir(
    session: Any,
    *,
    evento: models.EventoRegisto,
    cliente: models.Cliente,
    nr: int,
    nome: str,
    assunto: str,
    texto: str,
    agora: datetime,
    enviar: Enviar,
) -> models.Alerta:
    """Cria (e, se for caso disso, envia) o alerta de um cliente para um evento.

    🚦 `desaparecido` → canal `pendente_desambiguacao`, `enviado_em=None`, **não**
    envia (retido para o FDS 5). `alterado`/`reapareceu` → envia e data `enviado_em`.
    Um cliente sem email nunca rebenta: persiste-se o alerta por enviar (o dono
    resolve-o no ponto semi-manual).

    O email enviado é o template branded `alerta_estado` (marca + rodapé legal + opt-out
    + disclaimer garantidos pela base); o `assunto` factual do módulo é preservado. A BD
    guarda o `texto` determinístico como `conteudo` (fonte de verdade/auditoria).
    """
    retido = evento.tipo == TIPO_DESAPARECIDO
    pode_enviar = (not retido) and bool(cliente.email)

    enviado_em: datetime | None = None
    if pode_enviar:
        email = _emails.alerta_estado(
            nome_al=nome,
            estado=_ESTADO_POR_TIPO.get(evento.tipo, "amarelo"),
            assunto=assunto,
            titulo=_TITULO_POR_TIPO.get(evento.tipo, "Atualização do teu Alojamento Local"),
            corpo=texto,
            email_destinatario=cliente.email or "",
        )
        enviar(
            para=cliente.email,
            assunto=email.assunto,
            html=email.html,
            anexos=(),
            texto=email.texto,
            idempotency_key=f"alerta-{evento.id}-{cliente.id}",
        )
        enviado_em = agora

    alerta = models.Alerta(
        cliente_id=cliente.id,
        nr_registo=nr,
        origem=ORIGEM_EVENTO_REGISTO,
        origem_id=evento.id,
        conteudo=texto,
        canal=CANAL_PENDENTE if retido else CANAL_EMAIL,
        enviado_em=enviado_em,
    )
    session.add(alerta)
    return alerta
