"""Testes do detetor anti-atividade-reservada — app.ia.guardrails (Lei 10/2024).

Contrato (LEGAL-PARECER-DECISOES.md §7)::

    validar_nao_prescritivo(texto_alerta) -> ResultadoValidacao

Camada de defesa técnica: um template correto NÃO impede o modelo (Sonnet) de derivar
para linguagem PRESCRITIVA. Este detetor **puro e determinístico** confere o texto gerado
e REPROVA conclusões jurídicas imperativas/individualizadas sobre o cliente (procuradoria
ilícita), deixando passar a informação genérica/condicional (o lado seguro).

🧯 REGRA INVIOLÁVEL: NUNCA um falso 'válido' perante uma conclusão jurídica
individualizada. Na dúvida REPROVA. TDD: escrito ANTES da implementação.
"""
from __future__ import annotations

import html
import pathlib
import re

import pytest

from app.ia.guardrails import GUARDRAILS_VERSAO, validar_nao_prescritivo
from app.ia.validacao import ResultadoValidacao

URL = "https://files.diariodarepublica.pt/gratuitos/2s/2025/07/2S142A0000S00.pdf"

# Anexo 3 renderizado (exemplo de alerta enviado ao jurista). O corpo VISÍVEL deste HTML
# tem de passar o guardrail — é a prova de que o exemplo que promovemos é não-prescritivo.
_ANEXO3 = (
    pathlib.Path(__file__).resolve().parents[2] / "ANEXO3-alerta-exemplo.html"
)


# ==========================================================================
#  Fronteira do módulo
# ==========================================================================
def test_resultado_tem_a_forma_do_contrato():
    r = validar_nao_prescritivo("texto informativo qualquer")
    assert isinstance(r, ResultadoValidacao)
    assert isinstance(r.valido, bool)
    assert isinstance(r.motivos, list)
    assert r.valores_orfaos == []  # não é um detetor de grounding


def test_none_e_vazio_nao_rebentam_e_sao_validos():
    assert validar_nao_prescritivo(None).valido is True
    assert validar_nao_prescritivo("").valido is True


def test_funcao_e_determinista():
    txt = "O teu AL está em incumprimento."
    r1 = validar_nao_prescritivo(txt)
    r2 = validar_nao_prescritivo(txt)
    assert (r1.valido, r1.motivos) == (r2.valido, r2.motivos)


def test_resultado_e_imutavel():
    r = validar_nao_prescritivo("O teu AL está em incumprimento.")
    with pytest.raises(Exception):
        r.valido = True  # frozen dataclass


# ==========================================================================
#  LADO SEGURO — informação genérica / condicional / encaminhamento → VÁLIDO
# ==========================================================================
SEGUROS = [
    # Condicional/genérico — sinalização sem conclusão individual.
    f"Foi publicado um novo regulamento que pode afetar o teu AL. Lê aqui: {URL}",
    f"Este regulamento, se aplicável ao teu caso, pode afetar o teu AL. Lê aqui: {URL}",
    (
        "Foi publicado um regulamento que abrange estabelecimentos de Alojamento Local "
        f"em área de contenção. O teu AL pode estar abrangido. Lê aqui: {URL}"
    ),
    # Encaminhamento para a fonte / um profissional (nunca um ato jurídico).
    f"Recomendamos que verifiques a tua situação junto da câmara. Lê aqui: {URL}",
    f"Consulta a fonte oficial ou um profissional (advogado/solicitador). Lê aqui: {URL}",
    f"Confirma a tua situação; pode ser necessário rever o seguro. Lê aqui: {URL}",
    # Facto + prazo declarado (sem prescrever): "há um prazo … para comunicar".
    f"Há um prazo de 30 dias para comunicar a situação, se aplicável. Lê aqui: {URL}",
    # "tens de" seguido de ENCAMINHAMENTO (verificar/consultar/ler) — seguro.
    f"Tens de verificar junto da câmara se te aplica; consulta a fonte. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", SEGUROS)
def test_linguagem_segura_passa(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is True, r.motivos
    assert r.motivos == []


# ==========================================================================
#  LADO RESERVADO — conclusões jurídicas individualizadas → REPROVA (cada padrão)
# ==========================================================================
PRESCRITIVOS = [
    # Incumprimento.
    f"Neste momento estás em incumprimento. Lê aqui: {URL}",
    f"O teu AL está em incumprimento com o novo regulamento. Lê aqui: {URL}",
    # Ilegal / irregular.
    f"Sem o averbamento, estás ilegal. Lê aqui: {URL}",
    f"O teu AL está irregular perante a câmara. Lê aqui: {URL}",
    f"O teu registo é ilegal sem seguro. Lê aqui: {URL}",
    f"Operar assim é ilegal. Lê aqui: {URL}",
    # Não conforme / não cumpre.
    f"O teu AL não está conforme o novo regulamento. Lê aqui: {URL}",
    f"O teu AL não cumpre as novas regras. Lê aqui: {URL}",
    f"Não cumpres os requisitos exigidos. Lê aqui: {URL}",
    # Viola.
    f"Com o novo regulamento, violas a lei. Lê aqui: {URL}",
    # Obrigação pessoal + ato jurídico concreto.
    f"Tens de regularizar a tua situação. Lê aqui: {URL}",
    f"Tens que legalizar o registo já. Lê aqui: {URL}",
    f"És obrigado a cessar a atividade. Lê aqui: {URL}",
    f"Estás obrigado a alterar o averbamento do seguro. Lê aqui: {URL}",
    f"O teu AL tem de comunicar a situação à câmara. Lê aqui: {URL}",
    # Ameaça individualizada de sanção.
    f"Se não agires, vais ser multado. Lê aqui: {URL}",
    f"Serás sancionado pela câmara. Lê aqui: {URL}",
    f"Vais apanhar uma coima. Lê aqui: {URL}",
    f"A tua coima pode ser aplicada já. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", PRESCRITIVOS)
def test_linguagem_prescritiva_reprova(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is False, f"deveria reprovar: {texto!r}"
    assert r.motivos, "uma reprovação tem de trazer motivo"


# ==========================================================================
#  RED-TEAM (2026-07-09) — imperativos velados que escapavam à v. inicial
#  Cada um é uma CONCLUSÃO JURÍDICA imperativa/individualizada que ERA ENVIADA
#  (bypass do guardrail, severidade CRÍTICA). Regressão: TÊM de reprovar.
# ==========================================================================
PRESCRITIVOS_VELADOS = [
    # Necessidade de CERTEZA (não condicional) + ato jurídico.
    f"Face ao novo regulamento, será necessário regularizar a tua situação. Lê aqui: {URL}",
    f"É necessário que regularizes a tua situação. Lê aqui: {URL}",
    # Futuro de "ter de" (2.ª e 3.ª pessoa) + perifrástico "vais ter de".
    f"O teu AL terá de comunicar a situação à câmara. Lê aqui: {URL}",
    f"Terás de regularizar o registo. Lê aqui: {URL}",
    f"Vais ter de legalizar o averbamento do seguro. Lê aqui: {URL}",
    # Necessidade pessoal "precisas de" e dever "deves/deverás".
    f"Precisas de regularizar o teu registo. Lê aqui: {URL}",
    f"Deves regularizar a tua situação. Lê aqui: {URL}",
    f"Deverás corrigir o averbamento. Lê aqui: {URL}",
    # Sinónimos de ato jurídico ausentes do léxico inicial (sanar/resolver).
    f"Tens de sanar a irregularidade. Lê aqui: {URL}",
    f"Tens de resolver a tua situação. Lê aqui: {URL}",
    # Obrigação em 3.ª pessoa reflexiva ("fica obrigado a").
    f"O proprietário deste AL fica obrigado a regularizar. Lê aqui: {URL}",
    # Ato jurídico + dano ("sob pena de coima") e risco individualizado ("arriscas").
    f"Deves regularizar, sob pena de coima. Lê aqui: {URL}",
    f"Caso não regularizes, arriscas uma coima. Lê aqui: {URL}",
    # Estados jurídicos por verbo reflexivo/ligação (contornavam "estás/o teu … é").
    f"O teu AL encontra-se em incumprimento. Lê aqui: {URL}",
    f"O teu AL não se encontra conforme. Lê aqui: {URL}",
    f"O teu registo fica ilegal sem seguro. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", PRESCRITIVOS_VELADOS)
def test_imperativos_velados_reprovam(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is False, f"BYPASS CRÍTICO — deveria reprovar: {texto!r}"
    assert r.motivos


# ==========================================================================
#  Anti-regressão do LADO SEGURO — a versão condicional NÃO pode ser reprovada
#  (o par exato do imperativo perigoso). Distinção certeza vs condicional.
# ==========================================================================
SEGUROS_CONDICIONAIS = [
    # "poderá/pode ser necessário" (condicional) — mesmo seguido de ato jurídico — é seguro.
    f"Poderá ser necessário rever o seguro, se aplicável. Lê aqui: {URL}",
    f"Pode ser necessário regularizar; consulta um profissional. Lê aqui: {URL}",
    # Encaminhamento com modal forte mas verbo não-jurídico (verificar/rever/consultar).
    f"Tens de verificar se te aplica; consulta a fonte. Lê aqui: {URL}",
    f"Deves rever a documentação e consultar um profissional. Lê aqui: {URL}",
    f"Precisas de confirmar junto da câmara se te aplica. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", SEGUROS_CONDICIONAIS)
def test_condicional_e_encaminhamento_continuam_seguros(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is True, f"FALSO POSITIVO — devia passar: {texto!r} / {r.motivos}"


# ==========================================================================
#  Distinção facto vs conselho — "tens de verificar" seguro vs "tens de regularizar" não
# ==========================================================================
def test_tens_de_verificar_e_seguro_mas_tens_de_regularizar_nao():
    assert validar_nao_prescritivo(
        f"Tens de verificar a tua situação. Lê aqui: {URL}"
    ).valido is True
    assert validar_nao_prescritivo(
        f"Tens de regularizar a tua situação. Lê aqui: {URL}"
    ).valido is False


# ==========================================================================
#  CITAÇÃO DA FONTE — "tem de" DENTRO de aspas (excerto) NÃO reprova o alerta
# ==========================================================================
def test_tem_de_dentro_de_aspas_e_citacao_nao_reprova():
    # O excerto do regulamento (entre «…») pode conter "tem de"; citá-lo é informação.
    alerta = (
        "Foi publicado o Regulamento. O documento estabelece que "
        "«cada titular tem de averbar o seguro obrigatório no prazo legal». "
        f"Isto pode afetar o teu AL; consulta a fonte. Lê aqui: {URL}"
    )
    r = validar_nao_prescritivo(alerta)
    assert r.valido is True, r.motivos


def test_tem_de_dentro_de_aspas_retas_tambem_e_citacao():
    alerta = (
        'O documento diz: "os titulares têm de comunicar a situação". '
        f"Pode afetar o teu AL. Lê aqui: {URL}"
    )
    assert validar_nao_prescritivo(alerta).valido is True


def test_conclusao_do_proprio_alerta_fora_de_aspas_continua_a_reprovar():
    # Mesmo com uma citação legítima entre aspas, a conclusão PRÓPRIA do alerta (fora de
    # aspas) é reservada e tem de reprovar.
    alerta = (
        "O documento diz «cada titular tem de averbar o seguro». "
        f"Portanto, o teu AL está em incumprimento. Lê aqui: {URL}"
    )
    r = validar_nao_prescritivo(alerta)
    assert r.valido is False


# ==========================================================================
#  FACTOS COM DONO (2026-07-09) — o consultor apanhou que o Anexo 3 dizia ao cliente
#  "…para efetuares a comunicação": uma INSTRUÇÃO INDIVIDUALIZADA (infinitivo pessoal
#  da 2.ª pessoa) que o guardrail deixava passar. Prazo/valor/dever é ATRIBUÍDO à fonte,
#  nunca dirigido ao cliente. Regressão CRÍTICA: estas formas TÊM de reprovar.
# ==========================================================================
# A frase exata do Anexo 3 antigo — o bypass concreto que motivou o reforço.
FRASE_ANTIGA_ANEXO3 = (
    "Há um prazo de 30 dias, a contar de 15/06/2026, para efetuares a comunicação. "
    f"Lê aqui: {URL}"
)
# A redação corrigida (colada do consultor) — atribuída à FONTE, infinitivo IMPESSOAL.
FRASE_NOVA_ANEXO3 = (
    "Próximo passo: consulta o regulamento oficial e confirma a tua situação. Segundo o "
    "documento, os titulares abrangidos dispõem de um prazo de 30 dias, contado de "
    "15/06/2026, para efetuar a comunicação ali prevista, e a exploração irregular fica "
    "sujeita à coima indicada no regulamento. Em caso de dúvida sobre a tua situação "
    "concreta, confirma com um advogado, solicitador ou o teu contabilista. "
    f"Lê aqui: {URL}"
)

# (a) Infinitivo PESSOAL da 2.ª pessoa a mandar praticar um ato ("(para) efetuares …").
ATO_PESSOAL_2P = [
    f"Há um prazo para efetuares a comunicação. Lê aqui: {URL}",
    f"Tens 15 dias, a contar de hoje, para comunicares a alteração. Lê aqui: {URL}",
    f"O prazo serve para regularizares a tua situação. Lê aqui: {URL}",
    f"É o momento de legalizares o registo. Lê aqui: {URL}",
    f"Precisarás disto para corrigires o averbamento. Lê aqui: {URL}",
    f"Isto ajuda-te a sanares a irregularidade. Lê aqui: {URL}",
    f"Terás tempo para resolveres a situação. Lê aqui: {URL}",
    f"Convém para alterares os dados. Lê aqui: {URL}",
    f"Há um prazo para cessares a exploração. Lê aqui: {URL}",
    f"Serve para apresentares o pedido. Lê aqui: {URL}",
    f"O prazo é para averbares o seguro. Lê aqui: {URL}",
]
# (b) Prazo COM DONO — "tens/tem/têm N <unidade> para <ato>" (com ou sem "de"/"até").
PRAZO_COM_DONO = [
    f"Tens 30 dias para comunicar a situação à câmara. Lê aqui: {URL}",
    f"O teu AL tem 30 dias para regularizar. Lê aqui: {URL}",
    f"Têm 15 dias para averbar o seguro. Lê aqui: {URL}",
    f"Tens até 30 dias para comunicar a alteração. Lê aqui: {URL}",
    f"Tens 2 meses para legalizar o registo. Lê aqui: {URL}",
    # RED-TEAM 2026-07-09 (2.ª ronda) — imperativo velado no FUTURO ("terás/terá/terão N
    # dias para …"), "dispões" (2.ª p. de dispor, o espelho do seguro "dispõem") e a
    # interposição "(um/o) prazo de" entre o verbo e o número. Todos ESCAPAVAM à rule 10.
    f"Terás até 30 dias para comunicar a situação. Lê aqui: {URL}",
    f"Terás 30 dias para regularizar. Lê aqui: {URL}",
    f"O teu AL terá 30 dias para comunicar. Lê aqui: {URL}",
    f"Os titulares terão 30 dias para averbar. Lê aqui: {URL}",
    f"Dispões de 30 dias para comunicar a situação. Lê aqui: {URL}",
    f"Tens um prazo de 30 dias para comunicar. Lê aqui: {URL}",
    f"Tens o prazo de 30 dias para regularizar. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", [FRASE_ANTIGA_ANEXO3, *ATO_PESSOAL_2P, *PRAZO_COM_DONO])
def test_factos_com_dono_dirigidos_ao_cliente_reprovam(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is False, f"BYPASS CRÍTICO — deveria reprovar: {texto!r}"
    assert r.motivos


# Pares SEGUROS — o MESMO facto ATRIBUÍDO à fonte / no infinitivo IMPESSOAL passa. É a
# distinção que separa o dirigido-ao-cliente do sinalizado: NÃO pode virar falso positivo.
FACTO_ATRIBUIDO_A_FONTE = [
    FRASE_NOVA_ANEXO3,
    # Infinitivo IMPESSOAL ("para efetuar/comunicar/regularizar") atribuído aos titulares.
    f"Segundo o regulamento, os titulares dispõem de 30 dias para efetuar a comunicação. Lê aqui: {URL}",
    f"O documento prevê um prazo de 30 dias para comunicar a alteração. Lê aqui: {URL}",
    f"Há um prazo de 30 dias para regularizar, se aplicável. Lê aqui: {URL}",
    # Espelho SEGURO do prazo-com-dono no futuro/dispor: o mesmo prazo ATRIBUÍDO à fonte
    # (verbos "dispõem"/"existe"/"há", nunca "tens/terás/dispões") NÃO pode virar falso positivo.
    f"Os titulares dispõem de um prazo de 30 dias para efetuar a comunicação. Lê aqui: {URL}",
    f"Existe um prazo de 30 dias para comunicar, contado da publicação. Lê aqui: {URL}",
    # Encaminhamento em infinitivo pessoal (verbos NÃO-jurídicos) continua seguro.
    f"Convém confirmares se a tua morada está no perímetro. Lê aqui: {URL}",
    f"Serve para verificares a tua situação junto da câmara. Lê aqui: {URL}",
    f"É útil para consultares o regulamento. Lê aqui: {URL}",
]


@pytest.mark.parametrize("texto", FACTO_ATRIBUIDO_A_FONTE)
def test_facto_atribuido_a_fonte_ou_encaminhamento_passa(texto):
    r = validar_nao_prescritivo(texto)
    assert r.valido is True, f"FALSO POSITIVO — devia passar: {texto!r} / {r.motivos}"


def test_par_exato_do_anexo3_antigo_reprova_novo_passa():
    # O núcleo da correção: a frase antiga do Anexo 3 reprova; a nova (do consultor) passa.
    assert validar_nao_prescritivo(FRASE_ANTIGA_ANEXO3).valido is False
    assert validar_nao_prescritivo(FRASE_NOVA_ANEXO3).valido is True


# ==========================================================================
#  Prova do artefacto — o Anexo 3 REGENERADO (HTML) passa o guardrail
# ==========================================================================
def _texto_visivel(html_bruto: str) -> str:
    """Corpo visível do email (sem <head>, sem tags, entidades resolvidas)."""
    corpo = html_bruto.split("</head>", 1)[-1]
    texto = html.unescape(re.sub(r"<[^>]+>", " ", corpo))
    return re.sub(r"\s+", " ", texto).strip()


def test_anexo3_regenerado_passa_o_guardrail():
    bruto = _ANEXO3.read_text(encoding="utf-8")
    # Já não contém a instrução individualizada antiga…
    assert "para efetuares" not in bruto
    # …e contém a redação atribuída à fonte, no infinitivo impessoal.
    assert "para efetuar a comunicação" in bruto
    # A coima já não é afirmada como número solto (só "a indicada no regulamento").
    assert "2.500" not in bruto and "4.000" not in bruto
    # Gralha do H1 corrigida.
    assert "«Casa da Graça» — 1 ponto sem check" in bruto
    # E o corpo visível é NÃO-prescritivo.
    r = validar_nao_prescritivo(_texto_visivel(bruto))
    assert r.valido is True, r.motivos


# ==========================================================================
#  Versão do detetor (dossier de defesa)
# ==========================================================================
def test_versao_do_guardrail_e_uma_data_estavel():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", GUARDRAILS_VERSAO)
