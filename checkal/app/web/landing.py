"""Landing pública do CheckAL + healthcheck (SPEC-FDS2.md §landing).

`GET /` serve a página inicial; `GET /saude` é o healthcheck de uptime/deploy
(`{"ok": true}`).

A copy aqui é deliberadamente PLACEHOLDER: a copy final (carta, headline, selo) é
canónica em COPY-VENDAS.md e não se inventa neste módulo. O ponto de extensão é a
constante `_PAGINA_HTML` — no FDS 3 troca-se por template Jinja com a copy real.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
roteador = router  # alias PT, para montagem por qualquer um dos nomes

# Copy PLACEHOLDER — substituída pela copy canónica de COPY-VENDAS.md (FDS 3).
_PAGINA_HTML = """<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CheckAL</title>
</head>
<body>
  <main>
    <h1>CheckAL</h1>
    <p>[PLACEHOLDER] Landing do CheckAL &mdash; a copy final vem de COPY-VENDAS.md.</p>
    <!-- O widget de verificação consome GET /api/verificar?q= (consent-first). -->
  </main>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """Página inicial (placeholder). Devolve HTML com content-type `text/html`."""
    return HTMLResponse(content=_PAGINA_HTML)


@router.get("/saude")
def saude() -> dict[str, bool]:
    """Healthcheck simples para uptime/deploy: `{"ok": true}`."""
    return {"ok": True}
