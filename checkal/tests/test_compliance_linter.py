"""Bateria adversária do LINTER determinista — app.compliance.linter (Fase B).

O linter é o portão de qualidade textual de TODO o texto outward-facing produzido
por agente, a montante da aprovação 1-clique. Espelha o estilo de
tests/test_guardrails.py / test_ia_validacao.py. Regras cobertas:

  R1 ilegalidade/incumprimento · R2 conclusão jurídica (delega guardrails) ·
  R3 coima-ameaça + moldura de config.COIMA · R4 fonte oficial · R5 divulgação
  de IA (AI Act art. 50) · R6 grounding (validar_alerta) · R7 disclaimer ·
  R8 opt-out · R9 rodapé/remetente cold — e as regras extra do red-team:
  checkal.pt como REMETENTE em canal COLD, coima a <2 frases de um identificador
  do destinatário, verbo de estado jurídico sobre "o seu/o vosso" registo.

Casos-armadilha OBRIGATÓRIOS (prompt-mestre §6): "está ilegal", "arrisca
4.000 €", "o seu registo caducou", coima colada ao nome do destinatário,
checkal.pt como remetente em canal cold, omissão de divulgação de IA, valor de
coima fora de config.COIMA. TODOS têm de BLOQUEAR — 0 falsos "aprovado".

Função pura: sem rede, sem BD, determinística, conservadora (na dúvida REJEITA).
Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import pytest

from app.compliance.linter import (
    Canal,
    DIVULGACAO_IA,
    LINTER_VERSAO,
    PecaOutward,
    ResultadoLint,
    Severidade,
    Violacao,
    lint,
)

# ==========================================================================
#  Blocos de conformidade reutilizados nos textos "bons"
# ==========================================================================
_FONTE = "https://rnt.turismodeportugal.pt/rnt/rnal.aspx?nr=100031"
_DISCLAIMER = (
    "Informação de monitorização a partir de dados públicos do RNAL; "
    "não constitui aconselhamento jurídico."
)
_OPTOUT = "Para não voltar a ser contactado: checkal.pt/remover"
_IDENT = "O CheckAL é operado por Cosmic Oasis, Lda."


def _peca(texto: str, canal: Canal = Canal.COLD, **kw) -> PecaOutward:
    return PecaOutward(texto=texto, canal=canal, **kw)


def _cold_conforme(corpo: str, **kw) -> PecaOutward:
    """Um cold com todos os blocos exigidos (R7/R8/R9) + o corpo em teste."""
    texto = f"{corpo}\n\n{_DISCLAIMER}\n{_OPTOUT}\n{_IDENT}"
    return PecaOutward(texto=texto, canal=Canal.COLD, **kw)


def _regras(resultado: ResultadoLint) -> set[str]:
    return {v.regra for v in resultado.violacoes}


# ==========================================================================
#  Contrato e pureza
# ==========================================================================
def test_resultado_imutavel_e_versionado():
    r = lint(_peca("texto qualquer inocuo"))
    assert isinstance(r, ResultadoLint)
    assert r.versao == LINTER_VERSAO
    with pytest.raises(AttributeError):
        r.aprovado = True  # frozen


def test_aprovado_e_falso_sse_ha_violacao_bloqueante():
    r = lint(_peca("está ilegal", Canal.ALERTA))
    assert r.aprovado is False
    assert any(v.severidade is Severidade.BLOQUEIA for v in r.violacoes)


def test_violacao_traz_trecho_e_razao():
    r = lint(_peca("o alojamento está ilegal", Canal.ALERTA))
    v = next(v for v in r.violacoes if v.regra.startswith("R1"))
    assert "ilegal" in v.trecho
    assert v.razao  # mensagem PT-PT acionável


# ==========================================================================
#  🧨 CASOS-ARMADILHA OBRIGATÓRIOS (§6) — todos BLOQUEIA
# ==========================================================================
def test_armadilha_esta_ilegal_bloqueia():
    assert lint(_cold_conforme("O vosso alojamento está ilegal.")).aprovado is False


def test_armadilha_arrisca_coima_bloqueia():
    r = lint(_cold_conforme("A vossa empresa arrisca 4.000 € se nada fizer."))
    assert r.aprovado is False


def test_armadilha_o_seu_registo_caducou_bloqueia():
    r = lint(_cold_conforme("Verificámos que o seu registo caducou."))
    assert r.aprovado is False


def test_armadilha_coima_colada_ao_identificador_bloqueia():
    # Coima na frase imediatamente a seguir ao identificador do destinatário.
    corpo = (
        "A Alojamentos Sul, Lda. é titular do registo de AL n.º 100031. "
        "As coimas podem ir de 25.000€ a 40.000€."
    )
    assert lint(_cold_conforme(corpo)).aprovado is False


def test_armadilha_checkal_pt_como_remetente_em_cold_bloqueia():
    corpo = "Contacte-nos: CheckAL <alertas@checkal.pt>. O nosso serviço vigia o RNAL."
    assert lint(_cold_conforme(corpo)).aprovado is False


def test_armadilha_sem_divulgacao_ia_bloqueia():
    corpo = "O CheckAL vigia o registo do vosso Alojamento Local."
    r = lint(_cold_conforme(corpo, gerado_por_ia=True))
    assert r.aprovado is False
    assert any(v.regra.startswith("R5") for v in r.violacoes)


def test_armadilha_coima_fora_da_moldura_bloqueia():
    # "7.500€" nunca — só as molduras de config.COIMA.
    corpo = "As coimas por falta de registo podem ir até 7.500€."
    r = lint(_cold_conforme(corpo))
    assert r.aprovado is False


# ==========================================================================
#  R1 — ilegalidade/incumprimento afirmado
# ==========================================================================
@pytest.mark.parametrize(
    "frase",
    [
        "o estabelecimento encontra-se em incumprimento",
        "o AL está sem seguro válido",
        "a exploração está em infração",
        "trata-se de uma situação irregular",
        "estás obrigado a comunicar",
    ],
)
def test_r1_bloqueia_afirmacoes_de_ilegalidade(frase):
    r = lint(_peca(frase, Canal.ALERTA))
    assert r.aprovado is False
    assert any(v.regra.startswith("R1") or v.regra.startswith("R2") for v in r.violacoes)


def test_r1_ignora_citacoes_da_fonte():
    # Citar o regulamento («…») é legítimo — a voz própria é que não pode.
    texto = (
        "O regulamento diz: «o titular em incumprimento perde o registo». "
        f"Consulta a fonte: {_FONTE}. {_DISCLAIMER}"
    )
    r = lint(
        PecaOutward(
            texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE,
            excerto="o titular em incumprimento perde o registo",
        )
    )
    assert not any(v.regra.startswith("R1") for v in r.violacoes)


def test_r1_deteta_atraves_de_html():
    r = lint(_peca("<p>o alojamento est&aacute; <b>ilegal</b></p>", Canal.ALERTA))
    assert r.aprovado is False


# ==========================================================================
#  R2 — conclusão jurídica individualizada (delega em validar_nao_prescritivo)
# ==========================================================================
@pytest.mark.parametrize(
    "frase",
    [
        "tens de regularizar o registo até sexta",
        "é necessário que comuniques o seguro à câmara",
        "tens 10 dias para comunicar a alteração",
        "compete-te averbar o seguro",
    ],
)
def test_r2_bloqueia_prescricao_juridica(frase):
    r = lint(_peca(frase, Canal.ALERTA))
    assert r.aprovado is False
    assert any(v.regra.startswith("R2") for v in r.violacoes)


def test_r2_nao_bloqueia_encaminhamento_seguro():
    texto = (
        "Segundo o regulamento, os titulares abrangidos dispõem de um prazo para "
        f"efetuar a comunicação. Consulta a fonte oficial: {_FONTE}. {_DISCLAIMER}"
    )
    r = lint(
        PecaOutward(
            texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE,
            excerto="prazo para efetuar a comunicação",
        )
    )
    assert not any(v.regra.startswith("R2") for v in r.violacoes)


# ==========================================================================
#  R3 — coima como ameaça individualizada vs condicional impessoal
# ==========================================================================
@pytest.mark.parametrize(
    "frase",
    [
        "a tua coima pode chegar aos 40.000€",
        "vais ser multado",
        "arriscas uma coima pesada",
        "há uma multa que te espera",
    ],
)
def test_r3_bloqueia_coima_como_ameaca(frase):
    assert lint(_peca(frase, Canal.COLD)).aprovado is False


def test_r3_permite_condicional_impessoal_com_moldura_canonica():
    corpo = (
        "Contexto do setor: para pessoas coletivas, as coimas previstas "
        "podem ir de 25.000€ a 40.000€, segundo a moldura aplicável. "
        "O CheckAL informa; a decisão é sempre sua."
    )
    r = lint(_cold_conforme(corpo))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_r3_moldura_singular_tambem_e_aceite():
    corpo = "Para titulares singulares, as coimas podem ir de 2.500€ a 4.000€."
    r = lint(_peca(f"{corpo}\n\n{_DISCLAIMER}\n{_OPTOUT}\n{_IDENT}", Canal.NURTURE_TRANSACIONAL))
    assert not any("moldura" in v.razao for v in r.violacoes)


# ==========================================================================
#  Regras RT extra — proximidade e verbo de estado jurídico
# ==========================================================================
def test_rt_coima_afastada_do_identificador_passa():
    corpo = (
        "A Alojamentos Sul, Lda. é titular do registo de AL n.º 100031. "
        "Encontrámo-lo na lista pública do RNAL. "
        "O contexto do setor mudou muito desde 2025. "
        "As coimas para pessoas coletivas podem ir de 25.000€ a 40.000€."
    )
    r = lint(_cold_conforme(corpo))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


@pytest.mark.parametrize(
    "frase",
    [
        "o vosso registo está cancelado",
        "o seu registo foi cancelado pela câmara",
        "o vosso registo é irregular",
    ],
)
def test_rt_verbo_de_estado_juridico_sobre_o_registo_bloqueia(frase):
    assert lint(_cold_conforme(frase)).aprovado is False


def test_rt_links_para_checkal_pt_sao_permitidos_em_cold():
    # ADENDA §1: o CTA "Pagar já" do cold aponta a checkal.pt/pagar — só o
    # REMETENTE/domínio de envio é que nunca pode ser checkal.pt.
    corpo = (
        "Veja o estado do vosso registo em checkal.pt/v/100031 "
        "ou avance já: checkal.pt/pagar"
    )
    r = lint(_cold_conforme(corpo))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


# ==========================================================================
#  R4 — link de fonte oficial (ALERTA / PÁGINA)
# ==========================================================================
def test_r4_alerta_sem_fonte_oficial_bloqueia():
    r = lint(_peca(f"O teu AL passou no check. {_DISCLAIMER}", Canal.ALERTA))
    assert any(v.regra.startswith("R4") or v.regra.startswith("R6") for v in r.violacoes)
    assert r.aprovado is False


def test_r4_alerta_com_fonte_oficial_e_grounding_passa():
    texto = (
        "Estado do registo confirmado na página oficial. "
        f"Fonte: {_FONTE}. {_DISCLAIMER}"
    )
    r = lint(
        PecaOutward(
            texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE,
            excerto="Estado: Ativo",
        )
    )
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_r4_nao_exigido_em_nurture():
    texto = f"Obrigado por confirmar o teu email. {_DISCLAIMER}\n{_OPTOUT}"
    r = lint(_peca(texto, Canal.NURTURE_TRANSACIONAL))
    assert not any(v.regra.startswith("R4") for v in r.violacoes)


# ==========================================================================
#  R5 — divulgação de IA (AI Act art. 50)
# ==========================================================================
def test_r5_frase_canonica_satisfaz():
    corpo = f"O vosso AL passou no check. {DIVULGACAO_IA}"
    r = lint(_cold_conforme(corpo, gerado_por_ia=True))
    assert not any(v.regra.startswith("R5") for v in r.violacoes)


def test_r5_marcador_ai_disclosure_satisfaz():
    corpo = "O vosso AL passou no check. <!-- AI-DISCLOSURE -->"
    r = lint(_cold_conforme(corpo, gerado_por_ia=True))
    assert not any(v.regra.startswith("R5") for v in r.violacoes)


def test_r5_nao_exigido_quando_nao_gerado_por_ia():
    corpo = "O vosso AL passou no check."
    r = lint(_cold_conforme(corpo, gerado_por_ia=False))
    assert not any(v.regra.startswith("R5") for v in r.violacoes)


# ==========================================================================
#  R6 — grounding de valores (via validar_alerta)
# ==========================================================================
def test_r6_valor_orfao_no_alerta_bloqueia():
    texto = (
        f"O regulamento fixa uma taxa de 500€. Fonte: {_FONTE}. {_DISCLAIMER}"
    )
    r = lint(
        PecaOutward(
            texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE,
            excerto="O regulamento entra em vigor em breve.",  # 500€ NÃO consta
        )
    )
    assert r.aprovado is False
    assert any(v.regra.startswith("R6") for v in r.violacoes)


def test_r6_valor_fundamentado_no_excerto_passa():
    texto = f"O regulamento fixa uma taxa de 500 €. Fonte: {_FONTE}. {_DISCLAIMER}"
    r = lint(
        PecaOutward(
            texto=texto, canal=Canal.ALERTA, url_fonte=_FONTE,
            excerto="é devida uma taxa de 500 € por estabelecimento",
        )
    )
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


# ==========================================================================
#  R7 — disclaimer "informação, não aconselhamento"
# ==========================================================================
def test_r7_cold_sem_disclaimer_bloqueia():
    texto = f"O CheckAL vigia o vosso registo.\n{_OPTOUT}\n{_IDENT}"
    r = lint(_peca(texto, Canal.COLD, tem_optout_carimbado=True))
    assert any(v.regra.startswith("R7") for v in r.violacoes)


def test_r7_formulacao_curta_tambem_serve():
    texto = (
        "O CheckAL vigia o vosso registo. Informação, não aconselhamento "
        f"jurídico.\n{_OPTOUT}\n{_IDENT}"
    )
    r = lint(_peca(texto, Canal.COLD))
    assert not any(v.regra.startswith("R7") for v in r.violacoes)


def test_r7_nao_exigido_no_relatorio_mensal():
    # O relatório mensal é transacional, não alerta (compliance §9.5) — sem
    # disclaimer de aconselhamento por decisão de produto.
    texto = f"✅ julho: o teu AL passou no check.\n{_OPTOUT}"
    r = lint(_peca(texto, Canal.RELATORIO))
    assert not any(v.regra.startswith("R7") for v in r.violacoes)


# ==========================================================================
#  R8 — opt-out 1-clique (COLD/NURTURE/RELATORIO)
# ==========================================================================
def test_r8_cold_sem_optout_bloqueia():
    texto = f"O CheckAL vigia o vosso registo. {_DISCLAIMER}\n{_IDENT}"
    r = lint(_peca(texto, Canal.COLD))
    assert any(v.regra.startswith("R8") for v in r.violacoes)


def test_r8_optout_carimbado_pelo_seam_satisfaz():
    texto = f"O CheckAL vigia o vosso registo. {_DISCLAIMER}\n{_IDENT}"
    r = lint(_peca(texto, Canal.COLD, tem_optout_carimbado=True))
    assert not any(v.regra.startswith("R8") for v in r.violacoes)


# ==========================================================================
#  R9 — identificação legal do remetente (só COLD)
# ==========================================================================
def test_r9_cold_sem_identificacao_legal_bloqueia():
    texto = f"O CheckAL vigia o vosso registo. {_DISCLAIMER}\n{_OPTOUT}"
    r = lint(_peca(texto, Canal.COLD))
    assert any(v.regra.startswith("R9") for v in r.violacoes)


def test_r9_nao_exigido_fora_do_cold():
    texto = f"O teu relatório está pronto.\n{_OPTOUT}"
    r = lint(_peca(texto, Canal.RELATORIO))
    assert not any(v.regra.startswith("R9") for v in r.violacoes)


# ==========================================================================
#  Peças reais conformes — o lado seguro NÃO é reprovado
# ==========================================================================
def test_cold_completo_conforme_passa():
    corpo = (
        "Bom dia,\n\n"
        "A Alojamentos Sul, Lda. é titular do registo de AL n.º 100031 (Faro). "
        "Encontrámo-lo na lista pública do RNAL — é isso que fazemos: vigiamos "
        "os 120.000+ registos do país.\n\n"
        "O CheckAL monitoriza o estado do registo, o prazo do seguro e os "
        "regulamentos do concelho, e envia alertas interpretados.\n\n"
        "Veja grátis o estado atual do vosso registo: checkal.pt/v/100031\n\n"
        "Cumprimentos,\nDiogo Mendes · CheckAL"
    )
    r = lint(_cold_conforme(corpo))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_relatorio_mensal_conforme_passa():
    texto = (
        "✅ Julho: o teu AL «Casa do Sol» passou no check.\n"
        "Registo: check ✓ · Seguro: check ✓ · Regulamento: check ✓\n"
        f"{DIVULGACAO_IA}\n{_OPTOUT}"
    )
    r = lint(_peca(texto, Canal.RELATORIO, gerado_por_ia=True))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_texto_vazio_nao_rebenta():
    r = lint(_peca("", Canal.RELATORIO))
    assert isinstance(r.aprovado, bool)


# ==========================================================================
#  Canal POST_SOCIAL (fase 1 EDITOR/COMUNICADOR — decisão do dono 19/07/2026)
# ==========================================================================
def test_post_social_proibicoes_globais_aplicam():
    r = lint(_peca("O seu alojamento está ilegal e sem seguro.", Canal.POST_SOCIAL))
    assert r.aprovado is False
    assert "R1_ILEGALIDADE" in _regras(r)


def test_post_social_exige_fonte_oficial():
    r = lint(_peca(
        "Novo regulamento para o Alojamento Local — resumo em 5 pontos.",
        Canal.POST_SOCIAL,
    ))
    assert r.aprovado is False
    assert "R4_FONTE_OFICIAL" in _regras(r)


def test_post_social_conforme_aprova_sem_ia_disclaimer_optout():
    texto = (
        "Novo regulamento municipal do Funchal para o Alojamento Local — "
        "resumo em 5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. "
        "5) Onde ler mais.\nFonte oficial: https://www.cm-funchal.pt/regulamento-al"
    )
    r = lint(PecaOutward(texto=texto, canal=Canal.POST_SOCIAL, gerado_por_ia=True))
    assert r.aprovado is True, [v.razao for v in r.violacoes]
    # O POST_SOCIAL dispensa R5 (dono revê e publica em nome próprio), R7, R8, R9.
    assert not ({"R5_DIVULGACAO_IA", "R6_GROUNDING", "R7_DISCLAIMER", "R8_OPTOUT",
                 "R9_IDENTIFICACAO"} & _regras(r))


def test_post_social_coima_ameaca_continua_bloqueada():
    r = lint(_peca(
        "A tua coima pode chegar aos 4.000 € se não agires já. "
        "Fonte: https://www.cm-porto.pt/al",
        Canal.POST_SOCIAL,
    ))
    assert r.aprovado is False
    assert "R3_COIMA_AMEACA" in _regras(r)


def test_isencao_r5_e_exclusiva_do_post_social():
    # Guarda de regressão: PAGINA_PUBLICA gerada por IA continua a exigir R5.
    r = lint(PecaOutward(
        texto="Guia do registo RNAL. Fonte: https://rnt.turismodeportugal.pt/x",
        canal=Canal.PAGINA_PUBLICA, gerado_por_ia=True,
    ))
    assert "R5_DIVULGACAO_IA" in _regras(r)


# ==========================================================================
#  Canal POST_PAGINA (fase FB, decisão do dono 19/07/2026): posts publicados
#  AUTOMATICAMENTE na Página de Facebook via Graph API — sem adoção manual do
#  dono (diverge do POST_SOCIAL, colado pelo dono em nome próprio) ⇒ R5
#  (divulgação de IA) é EXIGIDA. Sem R6-pleno/R7/R8/R9; R4 (fonte oficial) e
#  proibições globais aplicam-se.
# ==========================================================================
_POST_PAGINA_BASE = (
    "Novo regulamento municipal do Funchal para o Alojamento Local — resumo "
    "em 5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. "
    "5) Onde ler mais.\nFonte oficial: https://www.cm-funchal.pt/regulamento-al"
)


def test_post_pagina_proibicoes_globais_aplicam():
    r = lint(_peca("O seu alojamento está ilegal e sem seguro.", Canal.POST_PAGINA))
    assert r.aprovado is False
    assert "R1_ILEGALIDADE" in _regras(r)


def test_post_pagina_exige_fonte_oficial():
    r = lint(PecaOutward(
        texto="Novo regulamento para o Alojamento Local — resumo em 5 pontos.",
        canal=Canal.POST_PAGINA, gerado_por_ia=True,
    ))
    assert r.aprovado is False
    assert "R4_FONTE_OFICIAL" in _regras(r)


def test_post_pagina_sem_divulgacao_ia_reprova_com_r5():
    # Publicação automática pela página ⇒ sem a linha de divulgação, reprova.
    r = lint(PecaOutward(texto=_POST_PAGINA_BASE, canal=Canal.POST_PAGINA,
                          gerado_por_ia=True))
    assert r.aprovado is False
    assert "R5_DIVULGACAO_IA" in _regras(r)


def test_post_pagina_com_divulgacao_curta_aprova():
    texto = f"{_POST_PAGINA_BASE}\nPreparado com apoio de IA."
    r = lint(PecaOutward(texto=texto, canal=Canal.POST_PAGINA, gerado_por_ia=True))
    assert r.aprovado is True, [f"{v.regra}: {v.razao}" for v in r.violacoes]


def test_post_pagina_r6_r7_r8_r9_nunca_disparam():
    texto = f"{_POST_PAGINA_BASE}\nPreparado com apoio de IA."
    r = lint(PecaOutward(texto=texto, canal=Canal.POST_PAGINA, gerado_por_ia=True))
    regras = _regras(r)
    assert not ({"R6_GROUNDING", "R7_DISCLAIMER", "R8_OPTOUT",
                 "R9_IDENTIFICACAO"} & regras)


def test_post_pagina_coima_ameaca_continua_bloqueada():
    r = lint(PecaOutward(
        texto="A tua coima pode chegar aos 4.000 € se não agires já. "
              "Fonte: https://www.cm-porto.pt/al\nPreparado com apoio de IA.",
        canal=Canal.POST_PAGINA, gerado_por_ia=True,
    ))
    assert r.aprovado is False
    assert "R3_COIMA_AMEACA" in _regras(r)


def test_post_social_continua_isento_de_r5_apos_post_pagina():
    # Guarda de regressão: acrescentar POST_PAGINA (que EXIGE R5) não pode
    # alterar a isenção do POST_SOCIAL (o dono publica em nome próprio).
    r = lint(PecaOutward(
        texto="O vosso AL passou no check. Fonte: https://www.cm-porto.pt/al",
        canal=Canal.POST_SOCIAL, gerado_por_ia=True,
    ))
    assert not any(v.regra.startswith("R5") for v in r.violacoes)
