"""Lote de cartas físicas — o canal postal do CheckAL (SPEC-FDS6.md §carta).

A carta A4 é o **único** canal legítimo de prospeção a **pessoa singular / ENI**
(COPY-VENDAS.md §1, LEGAL.md): a singulares o email frio está PROIBIDO, mas o
correio postal, ao abrigo do interesse legítimo e com opt-out em
`checkal.pt/remover`, é admissível (em teste). Este módulo faz o *mail-merge* de um
lote de prospetos numa peça PDF multi-carta e devolve os *bytes* — para o dono
**subir manualmente** ao portal e-carta dos CTT. Nada aqui envia nada: não há rede,
não há CTT, não há automação de expedição (o cold eletrónico é outro módulo, e nunca
toca singulares).

Princípios (inviolável — é conformidade, não só qualidade):

  - **Sem inventar dados.** O *merge* só escreve o que vem no prospeto. Campo em
    falta → frase neutra ou omissão, **nunca** um valor fabricado: sem alojamento,
    escreve-se "o seu Alojamento Local"; sem concelho conhecido, usa-se o bloco
    regulatório **nacional** (factos do país, não de um concelho que não temos);
    sem NIF/morada do remetente, a cláusula respetiva é **omitida** (a regra de
    bloqueio da COPY-VENDAS proíbe deixar `[entidade]/[NIPC]/[morada]` por preencher).
  - **Copy fixa de conformidade em cada carta:** disclaimer de independência no
    topo ("não é uma notificação oficial") + rodapé RGPD completo (origem RNAL,
    base legal, retenção de 12 meses, opt-out `checkal.pt/remover`, queixa à CNPD).
  - **Robustez a dados do RNAL:** os nomes de titular/alojamento chegam da fonte
    pública e podem trazer caracteres fora de Latin-1 (aspas curvas, travessões,
    €, emoji, CJK). As fontes *core* do fpdf2 são Latin-1; toda a escrita passa por
    :func:`_sanitizar`, que mapeia os casos comuns e substitui o resto — o PDF
    nunca rebenta por causa de um nome exótico.

Peças públicas:
  - :func:`bloco_regulatorio` — o mini-diagnóstico (Lisboa / Porto / nacional).
  - :func:`texto_carta` — a carta de um prospeto como texto simples (função pura;
    é a fonte de verdade do conteúdo, partilhada pelo PDF e testável isoladamente).
  - :func:`gerar_lote_cartas` — o PDF multi-carta (uma página A4 por prospeto).
  - :class:`Remetente` — identidade do operador injetável no rodapé RGPD.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# --- Identidade do operador (rodapé RGPD) -----------------------------------
# `entidade` é a decisão fechada do dossier (CLAUDE.md: veículo Cosmic Oasis, Lda.).
# `nipc`/`morada` NÃO se inventam: nascem vazios e só entram no rodapé quando o
# dono os injeta — enquanto vazios, a cláusula respetiva é omitida (nunca sai um
# placeholder por preencher). Ver COPY-VENDAS.md §7 (regra de bloqueio).


@dataclass(frozen=True, slots=True)
class Remetente:
    """Identidade do operador impressa no rodapé RGPD da carta.

    `nipc` e `morada` são opcionais **de propósito**: sem eles, a cláusula que os
    usaria é omitida em vez de deixar um placeholder — o merge nunca imprime
    `[NIPC]`/`[morada]`. `entidade` tem um default (o veículo do dossier), mas
    pode ser substituído por injeção.
    """

    entidade: str = "Cosmic Oasis, Lda."
    nipc: str = ""
    morada: str = ""


REMETENTE_PADRAO = Remetente()

# --- Copy fixa de conformidade (redação canónica — COPY-VENDAS.md §1) --------

_DISCLAIMER_INDEPENDENCIA = (
    "O CheckAL é um serviço privado e independente de monitorização de Alojamento "
    "Local, sem qualquer vínculo ao Turismo de Portugal, ao RNAL ou a qualquer "
    "câmara municipal. Esta carta não é uma notificação oficial."
)

# Blocos regulatórios (o mini-diagnóstico). Só factos públicos e documentados
# (COPY-VENDAS.md §1 / notas de fonte). O fallback nacional usa apenas o número
# do país — nunca se fabrica um facto específico de um concelho sem bloco próprio.
_BLOCO_LISBOA = (
    "Talvez saiba que o regulamento municipal de Alojamento Local de Lisboa foi "
    "alterado em dezembro de 2025 (Aviso n.º 29926-A/2025/2), com novas áreas de "
    "contenção por bairro. E que, desde março de 2025, todos os titulares têm de "
    "comunicar anualmente a prova do seguro de responsabilidade civil - a Câmara "
    "de Lisboa já cancelou 6.765 registos de quem não o fez. A nível nacional, já "
    "foram cancelados mais de 10.000 registos."
)
_BLOCO_PORTO = (
    "Talvez saiba que a Câmara do Porto anunciou em maio de 2026 o cancelamento de "
    "1.413 registos de Alojamento Local, num processo nacional que já eliminou mais "
    "de 10.000 registos por falta de seguro comunicado ou por inatividade."
)
_BLOCO_NACIONAL = (
    "Desde março de 2025, a prova anual do seguro de responsabilidade civil é "
    "obrigatória para todos os titulares de Alojamento Local. A nível nacional, as "
    "câmaras já cancelaram mais de 10.000 registos por falta de seguro comunicado "
    "ou por inatividade - e novos regulamentos municipais continuam a surgir ao "
    "abrigo do DL 76/2024."
)


def bloco_regulatorio(concelho: str | None) -> str:
    """Devolve o mini-diagnóstico regulatório adequado ao `concelho`.

    Lisboa e Porto têm blocos próprios (factos documentados desse concelho);
    qualquer outro concelho — ou concelho ausente/vazio — recebe o bloco
    **nacional**, que só invoca o número do país. Nunca se transporta um facto de
    um concelho para outro nem se fabrica regulamentação para um concelho sem bloco.
    Comparação robusta a maiúsculas/espaços.
    """
    chave = (concelho or "").strip().casefold()
    if chave == "lisboa":
        return _BLOCO_LISBOA
    if chave == "porto":
        return _BLOCO_PORTO
    return _BLOCO_NACIONAL


# --- Extração tolerante do prospeto (dict OU objeto com atributos) ----------

def _valor(prospeto: object, *chaves: str) -> str:
    """Primeiro valor não vazio entre `chaves`, de um Mapping ou de atributos.

    Aceita tanto um dict (chaves amigáveis ou à RNAL) como um objeto tipo
    `Registo` (atributos). Normaliza a str e apara; ausência/None/"" → "".
    """
    for chave in chaves:
        if isinstance(prospeto, Mapping):
            valor = prospeto.get(chave)
        else:
            valor = getattr(prospeto, chave, None)
        if valor is not None and str(valor).strip() != "":
            return str(valor).strip()
    return ""


def _campos(prospeto: object) -> dict[str, str]:
    """Extrai os campos de merge do prospeto (tudo str; ausência → "")."""
    return {
        "nr": _valor(prospeto, "nr_registo", "NrRegisto", "nr", "numero"),
        "nome": _valor(prospeto, "nome", "Nome", "titular_nome", "nome_titular"),
        "alojamento": _valor(
            prospeto, "nome_alojamento", "NomeAlojamento", "alojamento", "estabelecimento"
        ),
        "concelho": _valor(prospeto, "concelho", "Concelho"),
        "freguesia": _valor(prospeto, "freguesia", "Freguesia"),
        "morada": _valor(prospeto, "morada", "Morada", "endereco", "Endereco"),
        "cod_postal": _valor(prospeto, "cod_postal", "CodPostal", "codigo_postal", "cp"),
    }


# --- Composição da carta (fonte de verdade única: `_blocos`) ----------------

def _rodape_rgpd(remetente: Remetente) -> str:
    """Rodapé RGPD integral. `nipc`/`morada` só entram se fornecidos (sem placeholders)."""
    identificacao = f"Proteção de dados: o CheckAL é operado por {remetente.entidade}"
    if remetente.nipc:
        identificacao += f", NIPC {remetente.nipc}"
    if remetente.morada:
        identificacao += f", com sede em {remetente.morada}"
    identificacao += "."

    oposicao = "Pode opor-se a qualquer momento, sem custos, em checkal.pt/remover"
    if remetente.morada:
        oposicao += " ou por carta para a morada acima"
    oposicao += "."

    return " ".join([
        identificacao,
        "Os seus dados de contacto foram obtidos do registo público RNAL, cuja "
        "divulgação é obrigatória por força do art. 10.º do DL n.º 128/2014, de 29 "
        "de agosto.",
        "Base legal do tratamento: interesse legítimo (art. 6.º, n.º 1, al. f) do "
        "RGPD) - informar titulares de Alojamento Local sobre um serviço diretamente "
        "relacionado com a sua atividade.",
        "Conservamos os seus dados de contacto por um máximo de 12 meses ou até à "
        "sua oposição, o que ocorrer primeiro.",
        oposicao,
        "Tem ainda direito de acesso, retificação e apagamento, e o direito de "
        "apresentar queixa à CNPD (cnpd.pt). Política de privacidade completa: "
        "checkal.pt/privacidade.",
    ])


def _blocos(prospeto: object, remetente: Remetente) -> list[tuple[str, str]]:
    """Devolve a carta como lista ordenada de (estilo, texto) — sem inventar dados.

    Fonte de verdade partilhada por :func:`texto_carta` (que junta os textos) e por
    :func:`gerar_lote_cartas` (que os desenha com a tipografia de cada estilo).
    Estilos: `marca`, `destinatario`, `disclaimer`, `corpo`, `assinatura`, `rodape`.
    """
    c = _campos(prospeto)
    blocos: list[tuple[str, str]] = []

    # Cabeçalho da marca.
    blocos.append((
        "marca",
        "CheckAL · checkal.pt · Serviço independente de monitorização de Alojamento Local",
    ))

    # Destinatário: só linhas realmente conhecidas (nada de morada inventada).
    linha_localidade = " ".join(p for p in (c["cod_postal"], c["concelho"]) if p).strip()
    destinatario = [ln for ln in (c["nome"], c["morada"], linha_localidade) if ln]
    if destinatario:
        blocos.append(("destinatario", "\n".join(destinatario)))

    # Disclaimer de independência (fixo, obrigatório).
    blocos.append(("disclaimer", _DISCLAIMER_INDEPENDENCIA))

    # Saudação — com nome se houver, neutra se não.
    saudacao = f"Exmo.(a) Sr.(a) {c['nome']}," if c["nome"] else "Exmo.(a) Sr.(a),"
    blocos.append(("corpo", saudacao))

    # 1.ª frase: objeto da carta. Sem alojamento → frase neutra; sem nr → sem número.
    alvo = f"o {c['alojamento']}" if c["alojamento"] else "o seu Alojamento Local"
    if c["nr"]:
        alvo += f", registo de Alojamento Local n.º {c['nr']}"
    local = ""
    if c["freguesia"] and c["concelho"]:
        local = f", em {c['freguesia']}, {c['concelho']}"
    elif c["concelho"]:
        local = f", em {c['concelho']}"
    elif c["freguesia"]:
        local = f", em {c['freguesia']}"
    blocos.append(("corpo", f"Escrevo-lhe sobre {alvo}{local}."))

    blocos.append((
        "corpo",
        "Somos um serviço privado que vigia o registo nacional de Alojamento Local "
        "- e o seu registo consta da lista pública que analisámos esta semana.",
    ))

    # Mini-diagnóstico regulatório (escolhido pelo concelho).
    blocos.append(("corpo", bloco_regulatorio(c["concelho"])))

    blocos.append((
        "corpo",
        "O risco não é a lei de hoje - é a de amanhã: regulamentos municipais novos, "
        "reavaliação das áreas de contenção de 3 em 3 anos, prazos de seguro e "
        "notificações com poucos dias para responder. Quem falha um prazo arrisca "
        "coimas de 2.500 euros a 4.000 euros e, no limite, o cancelamento do registo. "
        "Ninguém o avisa pessoalmente - publica-se em Diário da República e presume-se "
        "que leu.",
    ))
    blocos.append((
        "corpo",
        "É isso que fazemos por si: vigiamos o seu registo, o seu seguro e o seu "
        "concelho todas as semanas, e só lhe escrevemos quando algo o afeta - "
        "explicado em português claro, com o que fazer a seguir. E no dia 1 de cada "
        "mês recebe um relatório a confirmar que está tudo em ordem.",
    ))

    # CTA — só leva /v/<nr> se houver nr (senão cai no domínio base, sem inventar).
    url = f"checkal.pt/v/{c['nr']}" if c["nr"] else "checkal.pt"
    blocos.append((
        "corpo",
        f"Comece por ver, grátis e em 30 segundos, o estado atual do seu registo em "
        f"{url}. Sem registo, sem cartão, sem compromisso.",
    ))

    blocos.append(("assinatura", "Com os melhores cumprimentos,\nDiogo Mendes · Fundador, CheckAL"))
    blocos.append(("rodape", _rodape_rgpd(remetente)))
    return blocos


def texto_carta(prospeto: object, *, remetente: Remetente | None = None) -> str:
    """Devolve a carta de um prospeto como texto simples (função pura).

    Faz o mail-merge **sem inventar dados** e concatena todas as secções. É a fonte
    de verdade do conteúdo — testável isoladamente e reutilizada pela geração do PDF.
    """
    blocos = _blocos(prospeto, remetente or REMETENTE_PADRAO)
    return "\n\n".join(texto for _, texto in blocos if texto)


# --- Sanitização para as fontes core (Latin-1) do fpdf2 ---------------------
# Mapa dos caracteres fora de Latin-1 mais comuns em dados/copy → equivalente
# seguro. O que sobrar é substituído por "?" no `encode(..., "replace")` — o PDF
# nunca rebenta por um nome exótico vindo do RNAL.
_MAPA_LATIN1 = {
    "€": "EUR", "✓": "", "✔": "", "→": "->", "←": "<-", "•": "-",
    "–": "-", "—": "-", "‑": "-", "…": "...",
    "’": "'", "‘": "'", "‛": "'", "“": '"', "”": '"', "„": '"',
    " ": " ", " ": " ", " ": " ", "™": "(TM)", "®": "(R)", "©": "(C)",
}


def _sanitizar(texto: str) -> str:
    """Torna `texto` seguro para as fontes core (Latin-1) do fpdf2, sem rebentar."""
    for origem, destino in _MAPA_LATIN1.items():
        texto = texto.replace(origem, destino)
    return texto.encode("latin-1", "replace").decode("latin-1")


# --- Geração do PDF multi-carta ---------------------------------------------

# Estilo de cada tipo de bloco: (família implícita Helvetica, estilo, tamanho, altura de linha).
_MARGEM_MM = 16.0
_LARGURA_LINHA = 0  # multi_cell: 0 = até à margem direita


def gerar_lote_cartas(
    prospetos: Iterable[object], *, remetente: Remetente | None = None
) -> bytes:
    """Devolve o PDF (bytes) do lote de cartas — uma página A4 por prospeto.

    Cada prospeto ocupa a **sua** página (mail-merge do nº de registo + mini-
    diagnóstico + copy fixa de conformidade). O PDF destina-se a **upload manual**
    ao portal e-carta dos CTT — este módulo não envia nada, não toca a rede.

    Toda a escrita passa por :func:`_sanitizar` (fontes core Latin-1). Um lote vazio
    é recusado (`ValueError`): não há carta sem prospeto.
    """
    from fpdf import FPDF

    prospetos = list(prospetos)
    if not prospetos:
        raise ValueError("lote de cartas vazio: não há prospetos para gerar.")

    remetente = remetente or REMETENTE_PADRAO

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=_MARGEM_MM)
    pdf.set_margins(_MARGEM_MM, _MARGEM_MM, _MARGEM_MM)

    for prospeto in prospetos:
        pdf.add_page()
        for estilo, texto in _blocos(prospeto, remetente):
            _desenhar_bloco(pdf, estilo, texto)

    return bytes(pdf.output())


def _desenhar_bloco(pdf, estilo: str, texto: str) -> None:
    """Desenha um bloco da carta com a tipografia do seu `estilo`."""
    texto = _sanitizar(texto)
    if estilo == "marca":
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(15, 118, 110)  # teal da marca
        pdf.multi_cell(_LARGURA_LINHA, 4.6, text=texto, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1.5)
    elif estilo == "destinatario":
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(_LARGURA_LINHA, 5, text=texto, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    elif estilo == "disclaimer":
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_fill_color(240, 244, 245)
        pdf.multi_cell(
            _LARGURA_LINHA, 4.3, text=texto, border=1, fill=True,
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(2.5)
    elif estilo == "assinatura":
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(_LARGURA_LINHA, 5, text=texto, new_x="LMARGIN", new_y="NEXT")
    elif estilo == "rodape":
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(_LARGURA_LINHA, 3.4, text=texto, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    else:  # "corpo"
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(_LARGURA_LINHA, 5, text=texto, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.6)


__all__ = ["Remetente", "bloco_regulatorio", "texto_carta", "gerar_lote_cartas"]
