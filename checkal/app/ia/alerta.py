"""Passo 2 do pipeline regulatório — redação do alerta (Sonnet) + 3 camadas anti-alucinação.

Fronteira do módulo (SPEC-FDS4 §alerta, SPEC-IA §4/§5, AUTOMACAO.md §3): recebe um
**evento regulatório** já triado como relevante e os **dados de um AL** de um cliente,
e produz o alerta **fundamentado e citado** que lhe será enviado::

    gerar_alerta(evento, dados_al, *, cliente_ia, excerto) -> Alerta

A IA (Sonnet, `config.MODEL_ALERTA`) redige a partir de um **excerto** do documento; o
resultado nunca sai sem passar pelas **três camadas anti-alucinação** — um alerta
jurídico com uma coima ou um prazo inventados é responsabilidade real (AUTOMACAO §3):

  1. **Template restritivo (na geração).** O `system` proíbe informação fora do excerto,
     manda escrever "o documento não especifica" quando falta, e obriga a citar a `url`.
     O excerto (partilhado por todos os clientes do mesmo evento) vai no **último bloco**
     do `system` com `cache_control` ttl 1h; os DADOS DO AL (voláteis) vão no `user`
     (estável→volátil — SPEC-IA §4.3).
  2. **Validação programática (pós-geração).** Corre-se :func:`app.ia.validacao.validar_alerta`
     (url citada + todo o valor monetário/data ⊂ excerto). Inválido → **regenera**, até
     :data:`MAX_TENTATIVAS_IA` gerações de IA.
  3. **Formato manual de recurso (rede de segurança).** Falhadas as 2 tentativas (ou sem
     `cliente_ia`), envia-se um alerta por template **sem prosa da IA** — "Foi publicado
     {titulo} … em {concelho}. Lê aqui: {url}" — que **passa a validação por construção**
     (só cita a url + factos de metadados; degrada até nenhum valor ser órfão). Nunca fica
     nada por comunicar.

🧯 Invariante inviolável: :func:`gerar_alerta` **nunca** devolve um alerta que falhe
:func:`app.ia.validacao.validar_alerta` — nem o da IA (só se aceita depois de validado),
nem o do fallback (validado por construção). O fallback **cita sempre** a url.

DISCIPLINA (inviolável): **MODO DE TESTE, LIVE-GATED.** Este módulo **não** cria nem
importa nenhum cliente Anthropic — o `cliente_ia` é sempre **injetado** por quem chama
(o pipeline compõe-o via :func:`app.ia.obter_cliente_ia`; falso nos testes). Toda a
conversa com o modelo passa pelo wrapper :func:`app.ia.cliente.pedir_texto`, pelo que
correr os testes nunca toca a IA/rede. `cliente_ia is None` (IA indisponível) → vai
direto ao formato manual, sem qualquer chamada.

O `evento` e o `dados_al` são *duck-typed* (leem-se por atributo, à imagem de
`app.ia.triagem`): do `evento` usam-se `.titulo`, `.url` e `.publicado_em`; do `dados_al`
os campos do AL (`.nr_registo`, `.nome_alojamento`, `.modalidade`, `.freguesia`,
`.concelho`, `.data_registo`, `.titular_tipo`). Um `EventoRegulatorio`/`Registo`
persistido (`app.models`) serve tal e qual, sem depender de sessão de BD.

Estilo à laia de `app/config.py` (Python 3.12+, `from __future__`, PT-PT).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import app.config as config
from app.ia import cliente as _cliente
from app.ia.validacao import validar_alerta

__all__ = [
    "Alerta",
    "gerar_alerta",
    "MAX_TENTATIVAS_IA",
    "SISTEMA_REGRAS",
]

# Nº máximo de gerações de IA por par evento×cliente antes de cair no formato manual
# (SPEC-IA §5.3 / AUTOMACAO §3: "se a validação falhar 2×"). A 1.ª é a geração; a 2.ª é
# a regeneração; falhadas ambas, entra a camada 3.
MAX_TENTATIVAS_IA = 2

# System da redação — parte **fixa** (papel + regras invioláveis). Estável (sem bytes
# voláteis: datas/IDs) para não estragar o prefixo em cache. Deriva do template canónico
# de AUTOMACAO §3; o `{url}` interpola-se por evento (fica no prefixo partilhado/cacheado,
# não varia entre clientes do mesmo documento).
SISTEMA_REGRAS = (
    "És o analista do CheckAL. Escreves alertas em português de Portugal para "
    "proprietários de Alojamento Local (AL) não-técnicos. Regras invioláveis:\n"
    "1. Baseia-te EXCLUSIVAMENTE no excerto fornecido. Se a informação não estiver no "
    'excerto, escreve "o documento não especifica".\n'
    "2. Cita sempre a fonte, incluindo no texto o link exato: {url}. Nunca inventes "
    "números, prazos ou coimas — usa apenas os que constam do excerto.\n"
    "3. Na dúvida sobre se afeta o cliente, assume que PODE afetar e recomenda "
    "verificação.\n"
    "4. Estrutura: (a) O que aconteceu — 1 frase. (b) Afeta o teu AL? sim/não/"
    "possivelmente + porquê, referindo os dados concretos do AL. (c) O que deves fazer "
    "+ prazo, se existir.\n"
    "5. Máximo 180 palavras. Sem jargão jurídico."
)

# Mensagem `user` — os DADOS DO AL, que **variam** por cliente (fora da cache).
_DADOS_AL = (
    'DADOS DO AL: nº {nr_registo}, "{nome}", {modalidade}, {freguesia}, {concelho}, '
    "registado em {data_registo}, titular {titular}."
)


# ==========================================================================
#  Resultado
# ==========================================================================
@dataclass(frozen=True)
class Alerta:
    """Alerta gerado, já validado e pronto a persistir/enviar (imutável).

    :param conteudo: o texto final do alerta — prosa da IA **já validada** ou, em recurso,
        o formato manual. Garantidamente aprovado por :func:`app.ia.validacao.validar_alerta`.
    :param url_fonte: a url do documento-fonte, citada no `conteudo` (sempre presente).
    :param manual: ``True`` se o `conteudo` é o formato manual de recurso (sem prosa da IA)
        — 2 falhas de validação ou IA indisponível.
    :param tentativas_ia: nº de gerações de IA feitas (0 se `cliente_ia` era ``None``;
        1 no caminho feliz; 2 se houve regeneração ou se caiu no manual após 2 falhas).
    """

    conteudo: str
    url_fonte: str
    manual: bool
    tentativas_ia: int

    def __str__(self) -> str:  # o alerta "é" o seu conteúdo, para logging/persistência
        return self.conteudo


# ==========================================================================
#  Auxiliares puros — leitura *duck-typed* e montagem do prompt
# ==========================================================================
def _campo(fonte: Any, nome: str, default: str = "") -> Any:
    """Lê `fonte.<nome>` (atributo), normalizando ``None`` → `default`.

    *Duck-typed* como em `app.ia.triagem`: serve um `EventoRegulatorio`/`Registo` do ORM
    ou qualquer objeto equivalente, sem depender de sessão de BD.
    """
    valor = getattr(fonte, nome, default)
    return default if valor is None else valor


def _montar_sistema(evento: Any, url: str, excerto: str) -> list[dict[str, Any]]:
    """Monta o `system` em dois blocos: regras (fixas) + DOCUMENTO/EXCERTO (partilhado).

    O breakpoint de `cache_control` (ttl 1h) fica no **último** bloco — o excerto — que é
    idêntico para todos os clientes do mesmo evento (estável→volátil, SPEC-IA §4.3). Os
    dados voláteis do AL ficam no `user`, fora deste prefixo.
    """
    titulo = str(_campo(evento, "titulo")).strip()
    publicado = _campo(evento, "publicado_em", "")
    data = str(publicado) if publicado else "data não especificada"

    documento = (
        f"DOCUMENTO: {titulo}, publicado {data}, fonte: {url}\n\n"
        f"EXCERTO:\n{excerto}"
    )
    return [
        {"type": "text", "text": SISTEMA_REGRAS.format(url=url)},
        {
            "type": "text",
            "text": documento,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]


def _montar_utilizador(dados_al: Any) -> str:
    """Monta a mensagem `user` — os DADOS DO AL específicos deste cliente."""
    return _DADOS_AL.format(
        nr_registo=_campo(dados_al, "nr_registo", ""),
        nome=_campo(dados_al, "nome_alojamento", ""),
        modalidade=_campo(dados_al, "modalidade", ""),
        freguesia=_campo(dados_al, "freguesia", ""),
        concelho=_campo(dados_al, "concelho", ""),
        data_registo=_campo(dados_al, "data_registo", ""),
        titular=_campo(dados_al, "titular_tipo", ""),
    )


# ==========================================================================
#  Camada 3 — formato manual de recurso (sem prosa da IA)
# ==========================================================================
def _candidatos_manuais(titulo: str, concelho: str, url: str) -> list[str]:
    """Candidatos do formato manual, do mais rico ao mais seguro.

    O último candidato **não tem qualquer valor numérico** (só a url, que a validação
    descarta antes de extrair valores) → passa a validação por construção enquanto a url
    estiver presente. Os candidatos anteriores só são usados se também validarem — assim
    um `titulo`/`concelho` que traga um valor órfão é descartado, nunca deixa passar um
    número inventado.
    """
    candidatos: list[str] = []
    if titulo and concelho:
        candidatos.append(
            f"Foi publicado {titulo} que pode afetar o teu AL em {concelho}. "
            f"Lê aqui: {url}"
        )
    if concelho:
        candidatos.append(
            f"Foi publicado um novo documento regulatório que pode afetar o teu AL em "
            f"{concelho}. Lê aqui: {url}"
        )
    if titulo:
        candidatos.append(
            f"Foi publicado {titulo} que pode afetar o teu AL. Lê aqui: {url}"
        )
    candidatos.append(
        f"Foi publicado um novo documento regulatório que pode afetar o teu AL. "
        f"Lê aqui: {url}"
    )
    return candidatos


def _formato_manual(titulo: str, concelho: str, url: str, excerto: str) -> str:
    """Devolve o formato manual mais rico que **passa** a validação (por construção)."""
    candidatos = _candidatos_manuais(titulo, concelho, url)
    for texto in candidatos:
        if validar_alerta(texto, url_fonte=url, excerto=excerto).valido:
            return texto
    # Nenhum validou (só acontece sem url para citar) — devolve o mais seguro na mesma.
    return candidatos[-1]


# ==========================================================================
#  API pública
# ==========================================================================
def gerar_alerta(
    evento: Any,
    dados_al: Any,
    *,
    cliente_ia: Any,
    excerto: str,
) -> Alerta:
    """Gera o alerta de um par evento×cliente, com as 3 camadas anti-alucinação.

    :param evento: o evento regulatório (lê `.titulo`, `.url`, `.publicado_em`).
    :param dados_al: os dados do AL do cliente (lê os campos do `Registo`).
    :param cliente_ia: cliente Anthropic **injetado** (falso nos testes; ``None`` ⇒ IA
        indisponível → vai direto ao formato manual).
    :param excerto: o excerto do documento — a **única fonte de verdade** de montantes,
        datas e prazos (a validação fundamenta o alerta contra ele).
    :returns: :class:`Alerta` cujo `conteudo` **passa sempre** :func:`validar_alerta`.

    Fluxo: até :data:`MAX_TENTATIVAS_IA` gerações de IA, aceitando a 1.ª que valide; se
    todas falharem (ou sem `cliente_ia`), cai no formato manual de recurso. Erros de rede
    do `cliente_ia` **propagam** (o pipeline reprocessa) — só a falha de *validação* cai
    no fallback.
    """
    url = str(_campo(evento, "url")).strip()
    excerto = excerto or ""
    titulo = str(_campo(evento, "titulo")).strip()
    concelho = str(_campo(dados_al, "concelho")).strip()

    tentativas = 0
    if cliente_ia is not None:
        sistema = _montar_sistema(evento, url, excerto)
        utilizador = _montar_utilizador(dados_al)
        for _ in range(MAX_TENTATIVAS_IA):
            tentativas += 1
            texto = _cliente.pedir_texto(
                cliente_ia,
                modelo=config.MODEL_ALERTA,
                sistema=sistema,
                utilizador=utilizador,
            ).strip()
            if validar_alerta(texto, url_fonte=url, excerto=excerto).valido:
                return Alerta(
                    conteudo=texto,
                    url_fonte=url,
                    manual=False,
                    tentativas_ia=tentativas,
                )

    # Camada 3 — formato manual de recurso (válido por construção; cita sempre a url).
    return Alerta(
        conteudo=_formato_manual(titulo, concelho, url, excerto),
        url_fonte=url,
        manual=True,
        tentativas_ia=tentativas,
    )
