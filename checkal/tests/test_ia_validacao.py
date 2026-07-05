"""Testes da rede de segurança anti-alucinação — app.ia.validacao (FDS 4).

Contrato (SPEC-FDS4 §validacao + SPEC-IA §5 + AUTOMACAO.md §3):

    validar_alerta(texto_alerta, *, url_fonte, excerto) -> ResultadoValidacao
    ResultadoValidacao{valido: bool, motivos: list[str], valores_orfaos: list[str]}

Camada 2 (validação programática pós-geração), **função pura e determinística**:
  1. **Citação da fonte:** `url_fonte` TEM de constar do `texto_alerta` (senão inválido).
  2. **Sem números inventados:** todo VALOR MONETÁRIO (€, coimas) e toda DATA/prazo do
     `texto_alerta` TÊM de existir no `excerto` (match por normalização PT).

🧯 REGRA INVIOLÁVEL: NUNCA um falso 'válido' quando há um valor órfão. Estes testes
exercitam à exaustão: url ausente, coima/data inventadas, formatos PT (1.500 €,
2 500,00€, 30 dias, 15/06/2026, junho de 2026), intervalos, e o alerta fiel.

DISCIPLINA: zero rede/IA — a função é pura (só regex/normalização). TDD: escrito
ANTES da implementação.
"""
from __future__ import annotations

import pytest

from app.ia.validacao import ResultadoValidacao, validar_alerta

# --- Cenário canónico (Braga, Regulamento 927/2025 — SPEC-DRE §4) --------------
URL = "https://files.diariodarepublica.pt/gratuitos/2s/2025/07/2S142A0000S00.pdf"

EXCERTO = (
    "Regulamento n.º 927/2025 do Município de Braga sobre alojamento local. "
    "A área de contenção entra em vigor a 15 de junho de 2026. "
    "O incumprimento é punível com coima de 2 500,00 € a 4 000,00 €. "
    "Os titulares dispõem de um prazo de 30 dias para regularizar a situação."
)

ALERTA_FIEL = (
    "O que aconteceu: o Município de Braga publicou um regulamento de alojamento local. "
    "Afeta o teu AL? Possivelmente — cria uma área de contenção a partir de junho de 2026. "
    "O que deves fazer: regulariza no prazo de 30 dias; a coima pode ir de 2.500 € a 4.000 €. "
    f"Lê aqui: {URL}"
)


# ==========================================================================
#  Fronteira do módulo
# ==========================================================================
def test_resultado_tem_a_forma_do_contrato():
    r = validar_alerta(ALERTA_FIEL, url_fonte=URL, excerto=EXCERTO)
    assert isinstance(r, ResultadoValidacao)
    assert isinstance(r.valido, bool)
    assert isinstance(r.motivos, list)
    assert isinstance(r.valores_orfaos, list)


# ==========================================================================
#  Alerta fiel → VÁLIDO (nada por fundamentar)
# ==========================================================================
def test_alerta_fiel_e_valido_sem_orfaos_nem_motivos():
    r = validar_alerta(ALERTA_FIEL, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True
    assert r.valores_orfaos == []
    assert r.motivos == []


def test_alerta_sem_valores_com_url_e_valido():
    alerta = (
        "O Município de Braga publicou um novo regulamento de alojamento local que pode "
        f"afetar o teu AL. Recomendamos que verifiques a situação. Lê aqui: {URL}"
    )
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True
    assert r.valores_orfaos == []


# ==========================================================================
#  Camada 1 — citação da fonte
# ==========================================================================
def test_url_ausente_invalida_o_alerta():
    alerta = ALERTA_FIEL.replace(URL, "consulta o Diário da República")
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("fonte" in m.lower() for m in r.motivos)


def test_url_fonte_vazia_invalida():
    alerta = "Foi publicado um regulamento de alojamento local em Braga."
    r = validar_alerta(alerta, url_fonte="", excerto=EXCERTO)
    assert r.valido is False
    assert any("fonte" in m.lower() for m in r.motivos)


def test_url_presente_com_pontuacao_a_seguir_conta_como_citada():
    alerta = f"Foi publicado um regulamento de alojamento local. Lê aqui: {URL}."
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


# ==========================================================================
#  Camada 2 — valores monetários (coimas)
# ==========================================================================
def test_coima_inventada_fora_do_excerto_invalida():
    alerta = (
        "O incumprimento pode custar uma coima até 7.500 €. "
        f"Lê aqui: {URL}"
    )
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "7.500" in r.valores_orfaos


def test_coima_fiel_no_excerto_e_valida():
    alerta = f"A coima vai de 2.500 € a 4.000 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True
    assert r.valores_orfaos == []


def test_intervalo_com_extremo_inventado_invalida_so_o_orfao():
    # Excerto: 2 500 a 4 000 €. Alerta inventa o limite inferior (1 000).
    alerta = f"A coima vai de 1.000 € a 4.000 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "1.000" in r.valores_orfaos
    assert "4.000" not in r.valores_orfaos  # este está fundamentado


def test_simbolo_antes_do_valor_tambem_e_reconhecido():
    excerto = "A taxa municipal é de € 1.500 por ano."
    alerta = f"Vais pagar uma taxa de € 1.500. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# ---- formatos PT: o mesmo montante escrito de maneiras diferentes -------------
def test_formato_milhar_com_ponto_casa_com_inteiro_simples():
    # alerta "1.500 €" ; excerto "1500 euros" — mesmo montante.
    excerto = "Foi liquidada a taxa de 1500 euros ao município."
    alerta = f"A taxa é de 1.500 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_formato_com_espaco_e_decimais_casa_com_inteiro():
    # alerta "2 500,00€" ; excerto "2500 euros" — mesmo montante, ambos em contexto
    # monetário (grounding type-aware: montante só casa com montante do excerto).
    excerto = "A coima base fixada no regulamento é 2500 euros."
    alerta = f"A coima é de 2 500,00€. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# --- Regressão (red-team FDS4, [médio]): grounding TYPE-AWARE ------------------
# Um valor inventado que coincide com um número de OUTRO tipo no excerto (nº de
# regulamento, artigo, ano) NÃO o fundamenta — só montante contra montante.
def test_montante_inventado_que_coincide_com_no_de_regulamento_e_orfao():
    excerto = "Regulamento n.º 927/2025 — área de contenção. Sem coimas indicadas."
    alerta = f"A coima é de 927 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "927" in r.valores_orfaos


def test_montante_inventado_que_coincide_com_ano_e_orfao():
    excerto = "Publicado em 2025; entra em vigor em junho de 2026. Sem valores de coima."
    alerta = f"A coima pode chegar a 2026 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "2026" in r.valores_orfaos


def test_percentagem_inventada_que_coincide_com_artigo_e_orfa():
    excerto = "Nos termos do artigo 15.º do regulamento, sem alteração de taxas."
    alerta = f"A taxa municipal sobe para 15%. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert any("15" in o for o in r.valores_orfaos)


def test_montante_real_em_contexto_monetario_continua_valido():
    # Guarda de não-regressão: um montante genuíno (com € no excerto) mantém-se válido.
    excerto = "A coima varia entre 2.500 € e 4.000 € para o titular singular."
    alerta = f"A coima vai de 2.500 € a 4.000 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_milhar_nao_confunde_4000_com_40000():
    # Guarda contra normalização preguiçosa: 40.000 ≠ 4.000.
    alerta = f"A coima pode chegar a 40.000 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "40.000" in r.valores_orfaos


def test_valor_com_palavra_euros_no_alerta_e_no_excerto():
    excerto = "O regulamento prevê uma coima de 3000 euros."
    alerta = f"A coima é de 3.000 euros. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# ==========================================================================
#  Camada 2 — datas
# ==========================================================================
def test_data_inventada_invalida():
    alerta = f"A área de contenção entra em vigor a 15/03/2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "15/03/2026" in r.valores_orfaos


def test_data_numerica_fiel_e_valida():
    excerto = "A medida entra em vigor a 15/06/2026 em todo o concelho."
    alerta = f"Entra em vigor a 15/06/2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_data_numerica_no_alerta_casa_com_data_escrita_no_excerto():
    # alerta 15/06/2026 ; excerto "15 de junho de 2026" — mesma data.
    alerta = f"Entra em vigor a 15/06/2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


def test_data_com_travessao_como_separador():
    excerto = "Prazo-limite: 15/06/2026."
    alerta = f"Tens até 15-06-2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_mes_ano_fundamentado_por_data_completa_do_excerto():
    # alerta "junho de 2026" ; excerto tem a data completa "15 de junho de 2026".
    alerta = f"A partir de junho de 2026 há novas regras. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


def test_mes_ano_inventado_invalida():
    # Excerto só fala em junho de 2026; alerta diz julho.
    alerta = f"A partir de julho de 2026 há novas regras. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("julho" in v.lower() for v in r.valores_orfaos)


def test_data_completa_no_alerta_mais_especifica_que_o_excerto_invalida():
    # Excerto só tem o mês/ano; alerta inventa o dia (15) → mais específico → órfão.
    excerto = "As novas regras aplicam-se a partir de junho de 2026."
    alerta = f"Entra em vigor a 15/06/2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "15/06/2026" in r.valores_orfaos


def test_acentuacao_do_mes_e_tolerada():
    excerto = "Produz efeitos a 1 de março de 2026."
    alerta_com = f"A partir de março de 2026. Lê aqui: {URL}"
    alerta_sem = f"A partir de marco de 2026. Lê aqui: {URL}"
    assert validar_alerta(alerta_com, url_fonte=URL, excerto=excerto).valido is True
    assert validar_alerta(alerta_sem, url_fonte=URL, excerto=excerto).valido is True


# ==========================================================================
#  Camada 2 — prazos
# ==========================================================================
def test_prazo_fiel_e_valido():
    alerta = f"Tens um prazo de 30 dias para regularizar. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


def test_prazo_inventado_invalida():
    alerta = f"Tens um prazo de 60 dias para regularizar. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("60 dias" in v for v in r.valores_orfaos)


def test_prazo_com_unidade_diferente_invalida():
    # Excerto: 30 dias. Alerta: 30 meses (mesmo número, unidade inventada).
    alerta = f"Tens 30 meses para regularizar. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("30 meses" in v for v in r.valores_orfaos)


def test_prazo_em_meses_fundamentado():
    excerto = "O período transitório é de 3 meses."
    alerta = f"Tens 3 meses de período transitório. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# ==========================================================================
#  Números que NÃO são valores (identificadores, artigos) são ignorados
# ==========================================================================
def test_numeros_de_identificacao_nao_sao_tratados_como_valores():
    # "Regulamento n.º 927/2025" e "artigo 5.º" não são coima/data/prazo →
    # não têm de constar do excerto; o alerta continua válido.
    excerto = "Município de Braga publicou nova regulação de alojamento local."
    alerta = (
        "Foi publicado o Regulamento n.º 927/2025; ver o artigo 5.º. "
        f"Lê aqui: {URL}"
    )
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True
    assert r.valores_orfaos == []


def test_digitos_da_url_nao_sao_tratados_como_valores():
    # A url citada tem dígitos (2s/2025/07/2S142...) — não podem gerar órfãos.
    url = "https://files.diariodarepublica.pt/gratuitos/2s/2026/02/2S029A0000S00.pdf"
    excerto = "Aviso do Município de Lisboa sobre alojamento local."
    alerta = f"Foi publicado um aviso que pode afetar o teu AL. Lê aqui: {url}"
    r = validar_alerta(alerta, url_fonte=url, excerto=excerto)
    assert r.valido is True
    assert r.valores_orfaos == []


# ==========================================================================
#  Combinações e ordenação determinística dos órfãos
# ==========================================================================
def test_varios_orfaos_preservam_ordem_de_aparicao():
    alerta = (
        "A coima pode chegar a 9.999 € e a medida vigora a partir de 01/01/2030. "
        f"Lê aqui: {URL}"
    )
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert r.valores_orfaos == ["9.999", "01/01/2030"]


def test_url_ausente_e_orfao_acumulam_motivos():
    alerta = "A coima pode chegar a 9.999 €."  # sem url, e coima inventada
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("fonte" in m.lower() for m in r.motivos)
    assert "9.999" in r.valores_orfaos


def test_orfaos_sao_deduplicados_preservando_ordem():
    alerta = (
        "A coima é de 9.999 €, repita-se, 9.999 €. "
        f"Lê aqui: {URL}"
    )
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valores_orfaos == ["9.999"]


# ==========================================================================
#  Pureza / determinismo
# ==========================================================================
def test_funcao_e_determinista():
    r1 = validar_alerta(ALERTA_FIEL, url_fonte=URL, excerto=EXCERTO)
    r2 = validar_alerta(ALERTA_FIEL, url_fonte=URL, excerto=EXCERTO)
    assert (r1.valido, r1.motivos, r1.valores_orfaos) == (
        r2.valido,
        r2.motivos,
        r2.valores_orfaos,
    )


def test_resultado_e_imutavel():
    r = validar_alerta(ALERTA_FIEL, url_fonte=URL, excerto=EXCERTO)
    with pytest.raises(Exception):
        r.valido = False  # frozen dataclass


def test_texto_none_nao_rebenta_e_e_invalido_por_falta_de_fonte():
    r = validar_alerta(None, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False


# ==========================================================================
#  🧯 RED-TEAM FDS4 — âncoras de moeda alternativas não podem furar o grounding
#  (uma coima inventada escrita "EUR"/"$"/"milhões" TEM de ser apanhada)
# ==========================================================================
def test_coima_inventada_com_abreviatura_EUR_invalida():
    # "9 999 EUR" — mesma coima inventada de test_coima_inventada, outra âncora de moeda.
    alerta = f"O incumprimento custa uma coima de 9 999 EUR. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("9 999" in v or "9999" in v for v in r.valores_orfaos)


def test_coima_inventada_com_EUR_antes_do_numero_invalida():
    alerta = f"A coima pode chegar a EUR 9999. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "9999" in r.valores_orfaos


def test_coima_inventada_com_cifrao_invalida():
    alerta = f"A coima pode chegar a 9999$. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "9999" in r.valores_orfaos


def test_coima_inventada_em_milhoes_de_euros_invalida():
    # A mantissa "5" não consta do excerto → órfão (magnitude não escapa ao grounding).
    alerta = f"A coima pode chegar a 5 milhões de euros. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "5" in r.valores_orfaos


def test_EUR_nao_cola_a_palavra_europa():
    # "Europa 9999" não é uma expressão monetária: sem coima afirmada, alerta fiel válido.
    excerto = "O regulamento aplica-se em toda a Europa e no país."
    alerta = f"As regras valem em toda a Europa. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# ==========================================================================
#  🧯 RED-TEAM FDS4 — datas com "." como separador (15.03.2026)
# ==========================================================================
def test_data_inventada_com_pontos_invalida():
    alerta = f"A área de contenção entra em vigor a 15.03.2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "15.03.2026" in r.valores_orfaos


def test_data_fiel_com_pontos_e_valida():
    excerto = "A medida entra em vigor a 15/06/2026."
    alerta = f"Entra em vigor a 15.06.2026. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_milhar_com_ponto_nao_e_confundido_com_data():
    # "2.500" (milhar) não pode ser lido como data → coima fiel continua válida.
    alerta = f"A coima é de 2.500 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


# ==========================================================================
#  🧯 RED-TEAM FDS4 — percentagens (taxa municipal inventada)
# ==========================================================================
def test_percentagem_inventada_invalida():
    excerto = "Coima de 2 500 a 4 000 euros. Prazo de 30 dias."
    alerta = f"A taxa turística sobe para 22%. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "22%" in r.valores_orfaos


def test_percentagem_por_extenso_inventada_invalida():
    excerto = "Coima de 2 500 a 4 000 euros. Prazo de 30 dias."
    alerta = f"A taxa sobe 22 por cento. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False


def test_percentagem_fundamentada_e_valida():
    excerto = "É aplicada uma taxa de 30% sobre a estadia."
    alerta = f"A taxa aplicável é de 30%. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


# ==========================================================================
#  🧯 RED-TEAM FDS4 — FURO 2: data "dia de mês" SEM ano ("3 de março")
#  Não era apanhada por _RE_DATA_ESCRITA (exige ano) nem _RE_MES_ANO → passava.
#  Vira um claim "dia+mês" fundamentado contra os pares (mês,dia) do excerto.
# ==========================================================================
def test_data_dia_mes_sem_ano_inventada_invalida():
    # Repro red-team: excerto só tem "15 de junho de 2026"; alerta inventa "3 de março".
    alerta = f"Tens de regularizar até 3 de março. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("3 de mar" in v.lower() for v in r.valores_orfaos)


def test_data_dia_mes_sem_ano_fiel_e_valida():
    # Excerto tem "15 de junho" (sem ano); alerta repete o mesmo dia+mês → fiel.
    excerto = "Regulariza até 15 de junho, sob pena de coima."
    alerta = f"Tens até 15 de junho para comunicar. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_data_dia_mes_partial_fundamentado_por_data_completa_do_excerto():
    # alerta "15 de junho" (menos específico) ; excerto "15 de junho de 2026".
    # O alerta pode ser MENOS específico que a fonte — é seguro.
    alerta = f"A área de contenção começa a 15 de junho. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


def test_data_dia_mes_dia_errado_invalida():
    # Mesmo mês (junho) mas dia inventado (3 ≠ 15) → órfão.
    alerta = f"Regulariza até 3 de junho. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert any("3 de junho" in v.lower() for v in r.valores_orfaos)


# ==========================================================================
#  🧯 RED-TEAM FDS4 — FURO 3: ANO isolado como prazo ("até 2027")
#  Um ano nu (19xx/20xx) não gerava claim → passava. Vira um claim "ano"
#  fundamentado contra os anos do excerto (de datas + mês/ano + anos isolados).
# ==========================================================================
def test_ano_isolado_como_prazo_inventado_invalida():
    # Repro red-team: excerto fala de 2026; alerta dá o prazo nu "até 2027".
    alerta = f"Tens até 2027 para cumprir as novas regras. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is False
    assert "2027" in r.valores_orfaos


def test_ano_isolado_fundamentado_por_data_do_excerto_e_valido():
    # O excerto tem "15 de junho de 2026" → o ano 2026 está fundamentado.
    alerta = f"Tens até 2026 para cumprir as novas regras. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=EXCERTO)
    assert r.valido is True


def test_ano_dentro_de_identificador_de_regulamento_nao_e_valor():
    # "927/2025" é um identificador (nº/ano), NÃO um prazo → não é exigido no excerto.
    excerto = "O Município de Braga publicou nova regulação de alojamento local."
    alerta = f"Foi publicado o Regulamento n.º 927/2025. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True
    assert r.valores_orfaos == []


def test_ano_isolado_nao_colide_com_montante_em_euros():
    # "2027 €" é um montante (moeda), não deve gerar TAMBÉM um claim "ano" duplicado;
    # continua a ser reprovado como coima órfã, com um único órfão "2027".
    excerto = "A área de contenção entra em vigor em 2026. Sem valores de coima."
    alerta = f"A coima pode chegar a 2027 €. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert r.valores_orfaos == ["2027"]


# ==========================================================================
#  🧯 RED-TEAM FDS4 — FURO 4: extremo superior de intervalo com moeda implícita
#  "de 2500 euros até 9999" — o 9999 ficava fora do span monetário e não gerava
#  órfão. A deteção monetária passa a apanhar o 2.º extremo do intervalo.
# ==========================================================================
def test_intervalo_moeda_implicita_extremo_superior_inventado_invalida():
    # Repro red-team: excerto só tem "2500 euros"; alerta estende para "até 9999".
    excerto = "A coima base é de 2500 euros."
    alerta = f"A coima vai de 2500 euros até 9999. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "9999" in r.valores_orfaos


def test_intervalo_moeda_implicita_ambos_extremos_fieis_e_valido():
    # Moeda só num dos lados, mas ambos os extremos constam do excerto → válido.
    excerto = "A coima vai de 2500 a 4000 euros."
    alerta = f"A coima vai de 2500 euros até 4000. Lê aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is True


def test_intervalo_moeda_implicita_com_ate_sem_acento_invalida():
    # Repro EXATO do red-team (attack.py A7): "ate" sem diacrítico ainda é ligação de
    # intervalo → o extremo superior "9999" entra no span monetário e é órfão.
    excerto = "A coima base e de 2500 euros."
    alerta = f"A coima vai de 2500 euros ate 9999. Le aqui: {URL}"
    r = validar_alerta(alerta, url_fonte=URL, excerto=excerto)
    assert r.valido is False
    assert "9999" in r.valores_orfaos
