"""Testes do lote de cartas físicas — app.campanhas.carta (SPEC-FDS6.md §carta).

A carta física é o canal do CheckAL para **pessoa singular** (COPY-VENDAS.md §1):
uma carta A4 de mail-merge que se gera em lote e se sobe **manualmente** ao portal
e-carta dos CTT (nunca automatizado — o cold eletrónico é outro módulo, e a
singulares está PROIBIDO). Este módulo é o único do sprint que toca prospetos de
pessoa singular, e fá-lo só para o canal postal legítimo (interesse legítimo +
opt-out em checkal.pt/remover).

Garantias sob teste:
  - `texto_carta` (função pura) faz o mail-merge **sem inventar dados**: o que não
    vem no prospeto não é fabricado — nem nome, nem alojamento, nem números de um
    concelho para o qual não há bloco regulatório conhecido; nunca sobram tokens
    `{{...}}`, `None` ou os placeholders legais `[entidade]/[NIPC]/[morada]`.
  - o **mini-diagnóstico** (`bloco_regulatorio`) escolhe o bloco certo pelo concelho
    (Lisboa / Porto / fallback nacional) e não injeta factos de outro concelho.
  - `gerar_lote_cartas` produz **um PDF** (`%PDF`), com **uma secção (página) por
    prospeto**, e é robusto a texto vindo do RNAL com caracteres fora de Latin-1
    (fontes core do fpdf2), sem rebentar.
  - copy fixa de conformidade presente: disclaimer de independência + rodapé RGPD
    (checkal.pt/remover, CNPD, base legal, retenção 12 meses).

SEM rede, SEM BD: tudo são funções puras + geração de PDF em memória. Escrito ANTES
da implementação (TDD).
"""
from __future__ import annotations

import io
import types

import pypdf
import pytest

from app.campanhas import carta


# --- Prospetos de teste (mínimos e realistas; nada de PII real) --------------

def _prospeto_lisboa() -> dict:
    return {
        "nr_registo": 93415,
        "nome": "Maria Exemplo",
        "nome_alojamento": "Casa da Graça",
        "concelho": "Lisboa",
        "freguesia": "São Vicente",
        "morada": "Rua de Teste, 10",
        "cod_postal": "1100-000",
    }


def _prospeto_porto() -> dict:
    return {
        "nr_registo": 100031,
        "nome": "João Exemplo",
        "nome_alojamento": "Casa do Porto",
        "concelho": "Porto",
        "freguesia": "Cedofeita",
    }


def _prospeto_minimo() -> dict:
    # Só o nº de registo — o resto tem de degradar sem fabricar nada.
    return {"nr_registo": 555}


# ==========================================================================
#  bloco_regulatorio — o mini-diagnóstico escolhido pelo concelho
# ==========================================================================

def test_bloco_lisboa_traz_factos_de_lisboa():
    bloco = carta.bloco_regulatorio("Lisboa")
    assert "6.765" in bloco
    assert "29926" in bloco          # Aviso n.º 29926-A/2025/2
    assert "1.413" not in bloco      # facto do Porto não entra no bloco de Lisboa


def test_bloco_porto_traz_factos_do_porto_e_nao_de_lisboa():
    bloco = carta.bloco_regulatorio("Porto")
    assert "1.413" in bloco
    assert "Porto" in bloco
    assert "6.765" not in bloco       # facto de Lisboa não entra no bloco do Porto
    assert "29926" not in bloco


def test_bloco_concelho_desconhecido_usa_fallback_nacional_sem_inventar():
    # Faro não tem bloco próprio: usa o fallback nacional e NÃO fabrica números
    # de contenção/cancelamento específicos de Faro.
    bloco = carta.bloco_regulatorio("Faro")
    assert "mais de 10.000" in bloco
    assert "6.765" not in bloco
    assert "1.413" not in bloco
    assert "Faro" not in bloco        # não se inventa um "regulamento de Faro"


def test_bloco_concelho_vazio_ou_none_usa_fallback_nacional():
    for concelho in ("", "   ", None):
        bloco = carta.bloco_regulatorio(concelho)
        assert "mais de 10.000" in bloco
        assert "6.765" not in bloco
        assert "1.413" not in bloco


def test_bloco_lisboa_case_insensitive():
    assert "6.765" in carta.bloco_regulatorio("  LISBOA ")


# ==========================================================================
#  texto_carta — mail-merge puro, sem inventar dados
# ==========================================================================

def test_texto_carta_lisboa_faz_merge_dos_campos_dados():
    texto = carta.texto_carta(_prospeto_lisboa())
    assert "93415" in texto
    assert "Casa da Graça" in texto
    assert "Maria Exemplo" in texto
    assert "São Vicente" in texto
    assert "Lisboa" in texto
    assert "6.765" in texto           # mini-diagnóstico de Lisboa embutido


def test_texto_carta_minimo_nao_inventa_nada():
    texto = carta.texto_carta(_prospeto_minimo())
    # o nº de registo dado aparece
    assert "555" in texto
    # NADA de concelho-específico foi fabricado
    assert "Lisboa" not in texto
    assert "Porto" not in texto
    assert "6.765" not in texto
    assert "1.413" not in texto
    # fallback nacional presente
    assert "mais de 10.000" in texto
    # sem placeholders por preencher nem lixo de merge
    assert "{{" not in texto and "}}" not in texto
    assert "None" not in texto
    assert "[entidade]" not in texto
    assert "[NIPC]" not in texto
    assert "[morada]" not in texto
    # alojamento em falta → frase neutra, não um nome inventado
    assert "o seu Alojamento Local" in texto


def test_texto_carta_sem_nr_nao_fabrica_numero_de_registo():
    texto = carta.texto_carta({"concelho": "Lisboa"})
    # não pode aparecer um nº inventado nem o token de merge; o CTA cai para o
    # domínio base sem /v/<nr>.
    assert "{{" not in texto
    assert "None" not in texto
    assert "checkal.pt/v/" not in texto


def test_texto_carta_tem_disclaimer_de_independencia():
    texto = carta.texto_carta(_prospeto_lisboa())
    assert "independente" in texto
    assert "não é uma notificação oficial" in texto
    assert "Turismo de Portugal" in texto


def test_texto_carta_tem_rodape_rgpd_completo():
    texto = carta.texto_carta(_prospeto_lisboa())
    assert "checkal.pt/remover" in texto        # via de opt-out funcional
    assert "CNPD" in texto
    assert "128/2014" in texto                   # base legal da publicação RNAL
    assert "interesse legítimo" in texto
    assert "12 meses" in texto


def test_texto_carta_rgpd_sem_nipc_nao_imprime_placeholder():
    # Sem NIPC/morada injetados, o rodapé NÃO pode conter placeholders por
    # preencher (regra de bloqueio da COPY-VENDAS) — omite-se a cláusula.
    texto = carta.texto_carta(_prospeto_lisboa())
    assert "[NIPC]" not in texto
    assert "NIPC —" not in texto
    assert "[morada]" not in texto


def test_texto_carta_rgpd_com_remetente_injeta_nipc_e_morada():
    rem = carta.Remetente(entidade="Cosmic Oasis, Lda.", nipc="516000000",
                          morada="Rua X, 1, Lisboa")
    texto = carta.texto_carta(_prospeto_lisboa(), remetente=rem)
    assert "516000000" in texto
    assert "Rua X, 1, Lisboa" in texto
    assert "Cosmic Oasis, Lda." in texto


def test_texto_carta_aceita_objeto_com_atributos():
    # o motor pode passar um objeto tipo Registo (atributos), não só um dict.
    prospeto = types.SimpleNamespace(
        nr_registo=777,
        titular_nome="Ana Atributo",
        nome_alojamento="Casa Atributo",
        concelho="Porto",
        freguesia="Bonfim",
    )
    texto = carta.texto_carta(prospeto)
    assert "777" in texto
    assert "Ana Atributo" in texto
    assert "Casa Atributo" in texto
    assert "1.413" in texto           # bloco do Porto


# ==========================================================================
#  gerar_lote_cartas — o PDF multi-carta para upload manual (e-carta CTT)
# ==========================================================================

def _paginas(pdf_bytes: bytes) -> list[str]:
    leitor = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return [p.extract_text() or "" for p in leitor.pages]


def test_lote_devolve_pdf():
    out = carta.gerar_lote_cartas([_prospeto_lisboa()])
    assert isinstance(out, (bytes, bytearray))
    assert bytes(out[:5]) == b"%PDF-"


def test_lote_uma_pagina_por_prospeto():
    prospetos = [_prospeto_lisboa(), _prospeto_porto(), _prospeto_minimo()]
    out = carta.gerar_lote_cartas(prospetos)
    paginas = _paginas(bytes(out))
    assert len(paginas) == len(prospetos)   # uma secção (página A4) por prospeto


def test_lote_cada_pagina_leva_o_seu_registo():
    prospetos = [_prospeto_lisboa(), _prospeto_porto(), _prospeto_minimo()]
    out = carta.gerar_lote_cartas(prospetos)
    paginas = [p.replace(" ", "") for p in _paginas(bytes(out))]
    for prospeto, pagina in zip(prospetos, paginas):
        assert str(prospeto["nr_registo"]) in pagina


def test_lote_robusto_a_caracteres_fora_de_latin1():
    # Nomes reais do RNAL podem trazer aspas curvas, travessões, emoji, CJK…
    # As fontes core do fpdf2 são Latin-1: o módulo tem de sanear, não rebentar.
    prospeto = {
        "nr_registo": 42,
        "nome": "José “Zé” Silva — \U0001f3e0 你好",
        "nome_alojamento": "Apartamento € → Mar",
        "concelho": "Lisboa",
    }
    out = carta.gerar_lote_cartas([prospeto])
    assert bytes(out[:5]) == b"%PDF-"
    assert len(_paginas(bytes(out))) == 1


def test_lote_vazio_recusa():
    with pytest.raises(ValueError):
        carta.gerar_lote_cartas([])
