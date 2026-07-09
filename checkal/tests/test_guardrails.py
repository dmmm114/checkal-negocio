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

import pytest

from app.ia.guardrails import GUARDRAILS_VERSAO, validar_nao_prescritivo
from app.ia.validacao import ResultadoValidacao

URL = "https://files.diariodarepublica.pt/gratuitos/2s/2025/07/2S142A0000S00.pdf"


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
#  Versão do detetor (dossier de defesa)
# ==========================================================================
def test_versao_do_guardrail_e_uma_data_estavel():
    import re

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", GUARDRAILS_VERSAO)
