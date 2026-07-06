"""Página pública do selo CheckAL (SPEC-FDS3.md §selo · SPEC-FASE1-WEB §Wire).

`GET /selo/{nr_registo}` devolve uma página HTML pública — o *"CheckAL ✓ — AL
Verificado / Monitorizado"* — que qualquer visitante do anúncio pode abrir a partir
do badge (:func:`app.selo.snippet_anuncio`). Mostra **só dados PÚBLICOS do
estabelecimento** (nº de registo, nome, concelho/distrito, modalidade, data de registo
e o estado no RNAL). **NUNCA** dados do titular (nome, NIF, email, telefone, telemóvel).

Marca FINAL aplicada (FASE 1): a página estende `base.html` (chrome/rodapé legal) e
embute o selo da MARCA — `selo-ativo.svg` (AL ativo no RNAL) ou `selo-suspenso.svg`
(AL que já não consta — verificação suspensa, cinza). O coral 🔴 **NUNCA** entra no
selo público: um AL fora do RNAL usa o selo *suspenso*, nunca o de falha.

Porquê a fronteira RGPD está no *código* e não na configuração (igual a
`app.web.verificar`): reutilizar os contactos do RNAL fora da finalidade original é o
risco nº 1 do projeto (art. 5/1/b; a CNPD sanciona). :func:`_dados_publicos` é a **lista
branca explícita** de campos que podem sair — tudo o resto do :class:`Registo`, incluindo
os contactos do titular, fica de fora por construção, não por confiança na renderização.
Só o dicionário `d` (a lista branca), o `nome` público e o SVG estático da marca chegam
ao template — e o `nome`/`d` saem autoescapados (anti-XSS) pelo Jinja partilhado.

Estado do RNAL: derivado de `Registo.desaparecido_em` (a fonte de verdade é o diffing
nacional — FDS 1), como em `app.web.verificar`: `NULL` → ``ativo``; preenchido →
``desaparecido``. A página **não** consulta a página individual do RNAL nem afirma
"cancelado" (G4 vive no módulo do detalhe); limita-se ao que o espelho local já sabe.

Registo inexistente → **404** (a página é para ALs reais; nunca inventa um selo).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

import app.db as db
from app.models import Registo
from app.web import marca
from app.web.marca import templates

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# Selos da MARCA embutidos INLINE (assets estáticos de confiança — sem PII, sem rede).
# Lidos uma vez à importação (puro: ficheiro local, nada de I/O externo). No template
# saem com `| safe` — é markup nosso, não input do utilizador.
_MARCA_DIR = marca.STATIC_DIR / "marca"
_SELO_ATIVO_SVG = (_MARCA_DIR / "selo-ativo.svg").read_text(encoding="utf-8")
_SELO_SUSPENSO_SVG = (_MARCA_DIR / "selo-suspenso.svg").read_text(encoding="utf-8")


def _dados_publicos(r: Registo) -> dict[str, str | None]:
    """Projeta um `Registo` na **lista branca** de campos públicos do estabelecimento.

    Só campos do próprio alojamento; NADA do titular (nome/NIF/email/telefone/telemóvel)
    nem `titular_tipo`. O `estado` deriva de `desaparecido_em` (NULL → ``ativo``). Esta
    função é a fronteira RGPD: se um campo não estiver aqui, não pode chegar à página.
    """
    return {
        "nr_registo": str(r.nr_registo),
        "nome_alojamento": r.nome_alojamento,
        "modalidade": r.modalidade,
        "concelho": r.concelho,
        "distrito": r.distrito,
        "data_registo": r.data_registo.isoformat() if r.data_registo else None,
        "estado": "ativo" if r.desaparecido_em is None else "desaparecido",
    }


@router.get("/selo/{nr_registo}", response_class=HTMLResponse)
def selo_publico(request: Request, nr_registo: int) -> HTMLResponse:
    """Página pública do selo de um AL, a partir do espelho local do RNAL.

    Carrega o `Registo` pela PK (`nr_registo`), projeta-o na lista branca pública
    (`_dados_publicos`) e renderiza `selo.html` (estende `base.html`) com o selo da
    marca — *ativo* ou *suspenso* conforme o estado no RNAL. Registo inexistente → 404.
    Só dados públicos do estabelecimento (mais o SVG estático) chegam à saída.
    """
    with db.get_session() as s:
        r = s.get(Registo, nr_registo)
        if r is None:
            raise HTTPException(status_code=404, detail="Selo não encontrado para este registo.")
        d = _dados_publicos(r)

    ativo = d["estado"] == "ativo"
    contexto = {
        "d": d,
        "nome": d["nome_alojamento"] or f"Registo RNAL n.º {d['nr_registo']}",
        "titulo_estado": "AL Verificado" if ativo else "Verificação suspensa",
        "estado_rnal": (
            "Ativo no RNAL ✓" if ativo
            else "Já não consta do RNAL — em verificação"
        ),
        "selo_svg": _SELO_ATIVO_SVG if ativo else _SELO_SUSPENSO_SVG,
    }
    return templates.TemplateResponse(request, "selo.html", contexto)
