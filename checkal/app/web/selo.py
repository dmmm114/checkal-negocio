"""Página pública do selo CheckAL (SPEC-FDS3.md §selo).

`GET /selo/{nr_registo}` devolve uma página HTML pública — o *"CheckAL ✓ — AL
Verificado / Monitorizado"* — que qualquer visitante do anúncio pode abrir a partir
do badge (:func:`app.selo.snippet_anuncio`). Mostra **só dados PÚBLICOS do
estabelecimento** (nº de registo, nome, concelho/distrito, modalidade, data de registo
e o estado no RNAL). **NUNCA** dados do titular (nome, NIF, email, telefone, telemóvel).

Porquê a fronteira RGPD está no *código* e não na configuração (igual a
`app.web.verificar`): reutilizar os contactos do RNAL fora da finalidade original é o
risco nº 1 do projeto (art. 5/1/b; a CNPD sanciona). :func:`_dados_publicos` é a **lista
branca explícita** de campos que podem sair — tudo o resto do :class:`Registo`, incluindo
os contactos do titular, fica de fora por construção, não por confiança na renderização.

Estado do RNAL: derivado de `Registo.desaparecido_em` (a fonte de verdade é o diffing
nacional — FDS 1), como em `app.web.verificar`: `NULL` → ``ativo``; preenchido →
``desaparecido``. A página **não** consulta a página individual do RNAL nem afirma
"cancelado" (G4 vive no módulo do detalhe); limita-se ao que o espelho local já sabe.

Registo inexistente → **404** (a página é para ALs reais; nunca inventa um selo).
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

import app.db as db
from app.models import Registo
from app.selo import gerar_selo_svg

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes


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


def _linha(rotulo: str, valor: str | None) -> str:
    """Devolve uma linha `<dt>/<dd>` escapada, ou "" se o valor faltar (render tolerante)."""
    if not valor:
        return ""
    return f"<dt>{escape(rotulo)}</dt><dd>{escape(valor)}</dd>"


def _pagina_html(d: dict[str, str | None]) -> str:
    """Compõe a página pública do selo a partir da vista de dados públicos `d`.

    Embute o badge SVG (`gerar_selo_svg`), afirma "AL Verificado" e "AL Monitorizado",
    lista os dados públicos e mostra o estado factual no RNAL. Copy PT-PT, factual,
    sem aconselhamento (só informação). Tudo o que vem de `d` já passou pela lista branca.
    """
    nome = d["nome_alojamento"] or f"Registo RNAL n.º {d['nr_registo']}"
    badge = gerar_selo_svg(d["nr_registo"], d["nome_alojamento"] or "")

    ativo = d["estado"] == "ativo"
    estado_rnal = (
        "Ativo no RNAL ✓" if ativo
        else "Já não consta do RNAL — em verificação"
    )

    linhas = "".join((
        _linha("Registo RNAL", f"n.º {d['nr_registo']}"),
        _linha("Modalidade", d["modalidade"]),
        _linha("Concelho", d["concelho"]),
        _linha("Distrito", d["distrito"]),
        _linha("Data de registo", d["data_registo"]),
        _linha("Estado no RNAL", estado_rnal),
    ))

    return f"""<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>CheckAL ✓ — AL Verificado · {escape(nome)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; margin: 0;
           padding: 2rem 1rem; color: #111827; background: #f9fafb; }}
    main {{ max-width: 32rem; margin: 0 auto; background: #ffffff;
            border: 1px solid #e5e7eb; border-radius: 16px; padding: 1.75rem; }}
    .badge {{ text-align: center; margin-bottom: 1rem; }}
    .badge svg {{ max-width: 100%; height: auto; }}
    h1 {{ font-size: 1.35rem; margin: .25rem 0 .5rem; color: #0f766e; }}
    .estabelecimento {{ font-size: 1.05rem; font-weight: 600; margin: 0 0 1rem; }}
    dl {{ display: grid; grid-template-columns: auto 1fr; gap: .35rem 1rem; margin: 0 0 1rem; }}
    dt {{ color: #6b7280; }}
    dd {{ margin: 0; font-weight: 500; }}
    .nota {{ font-size: .82rem; color: #6b7280; border-top: 1px solid #e5e7eb;
             padding-top: 1rem; margin-top: 1rem; }}
    a {{ color: #0f766e; }}
  </style>
</head>
<body>
  <main>
    <div class="badge">{badge}</div>
    <h1>CheckAL ✓ — AL Verificado</h1>
    <p class="estabelecimento">{escape(nome)}</p>
    <p><strong>AL Monitorizado</strong> pelo CheckAL: registo RNAL, seguro obrigatório
       e regulamentos municipais sob vigilância contínua.</p>
    <dl>
      {linhas}
    </dl>
    <p class="nota">Página pública do CheckAL, gerada a partir de dados públicos do
      Registo Nacional de Alojamento Local (RNAL). Só informação; não constitui
      aconselhamento. Sem dados pessoais do titular.
      <a href="https://checkal.pt">checkal.pt</a></p>
  </main>
</body>
</html>
"""


@router.get("/selo/{nr_registo}", response_class=HTMLResponse)
def selo_publico(nr_registo: int) -> HTMLResponse:
    """Página pública do selo de um AL, a partir do espelho local do RNAL.

    Carrega o `Registo` pela PK (`nr_registo`), projeta-o na lista branca pública
    (`_dados_publicos`) e devolve a página HTML *"AL Verificado / Monitorizado"*.
    Registo inexistente → 404. Só dados públicos do estabelecimento chegam à saída.
    """
    with db.get_session() as s:
        r = s.get(Registo, nr_registo)
        if r is None:
            raise HTTPException(status_code=404, detail="Selo não encontrado para este registo.")
        pagina = _pagina_html(_dados_publicos(r))
    return HTMLResponse(content=pagina)
