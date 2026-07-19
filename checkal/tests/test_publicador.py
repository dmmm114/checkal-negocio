"""Testes do PUBLICADOR — parte 1: render determinista do artigo + sitemap.

`app/publicador.py` é "o braço determinista da publicação — o LLM propõe, o
dono/config aprova, ISTO publica" (fase 3, F3.3). Esta suite cobre só a parte 1:
`md_para_html`, `render_artigo`, `atualizar_sitemap`. A passagem completa
(drain/ensaio, git, wrangler) é a F3.4 — fora do âmbito daqui.

Escritos ANTES da implementação (TDD). Sem BD, sem rede: funções puras sobre
dicts/ficheiros.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models_swarm as ms
import manage
from app.compliance.linter import Canal, PecaOutward
from app.swarm import fila
from app import publicador

# Baseado no `_ARTIGO_OK` de test_manage_editor_comunicador.py, com
# `data_publicacao` fixa (necessário para o teste de idempotência — sem data
# fixa, `render_artigo` carimbaria `date.today()` e duas chamadas em dias
# diferentes divergiriam).
_ARTIGO = {
    "slug": "regulamentos-al-porto",
    "titulo": "Regulamentos municipais de Alojamento Local no Porto: o essencial",
    "meta_description": "O que muda para o AL no Porto e onde confirmar na fonte oficial.",
    "tipo_pagina": "pilar",
    "data_publicacao": "2026-07-19",
    "seccoes": [
        {"h2": "O que é o regulamento municipal",
         "corpo_md": "Cada município pode definir regras próprias para o AL."},
        {"h2": "Onde confirmar",
         "corpo_md": "A fonte oficial é o portal do município e o Diário da República."},
    ],
    "fontes": [
        {"url": "https://www.cm-porto.pt/regulamento-al",
         "titulo": "Regulamento AL — CM Porto", "data": "2026-05-10",
         "excerto": "O presente regulamento, publicado a 10 de maio de 2026, "
                    "define as regras aplicáveis."},
    ],
}

# Cabeçalho + entrada de "/" — cópia do formato real de site/sitemap.xml
# (indentação 2 espaços no <url>, 4 nos filhos).
SITEMAP_BASE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.checkal.pt/</loc>
    <lastmod>2026-07-17</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def test_md_para_html_paragrafos_negrito_listas():
    md = "Primeiro **par**.\n\nSegundo.\n\n1. um\n2. dois\n\n- a\n- b"
    html = publicador.md_para_html(md)
    assert "<p>Primeiro <strong>par</strong>.</p>" in html
    assert "<ol>" in html and "<li>um</li>" in html
    assert "<ul>" in html and "<li>a</li>" in html


def test_md_para_html_escapa_html():
    assert "&lt;script&gt;" in publicador.md_para_html("olá <script>alert(1)</script>")


def test_render_artigo_estrutura_completa():
    html = publicador.render_artigo(_ARTIGO)
    # canonical/OG/JSON-LD/slug
    assert f'href="https://www.checkal.pt/{_ARTIGO["slug"]}"' in html
    assert '"datePublished": "' in html
    # blocos garantidos ao linter (fonte única — as CONSTANTES, não cópias):
    from app.compliance.linter import DIVULGACAO_IA, DISCLAIMER_NAO_ACONSELHAMENTO
    assert DIVULGACAO_IA in html
    assert DISCLAIMER_NAO_ACONSELHAMENTO in html
    # fontes e CTA com data-evento por slug (header E corpo — a revisão notou
    # que faltava cobrir o do header)
    assert _ARTIGO["fontes"][0]["url"] in html
    assert f'data-evento="cta_{_ARTIGO["slug"]}_header"' in html
    assert f'data-evento="cta_{_ARTIGO["slug"]}_corpo"' in html
    # sem scripts inline executáveis (CSP script-src 'self'); ld+json permitido
    scripts = re.findall(r"<script(?![^>]*application/ld\+json)[^>]*>", html)
    assert all("src=" in s for s in scripts)


def test_render_artigo_idempotente():
    assert publicador.render_artigo(_ARTIGO) == publicador.render_artigo(_ARTIGO)


def test_sitemap_acrescenta_e_atualiza_idempotente(tmp_path):
    sm = tmp_path / "sitemap.xml"
    sm.write_text(SITEMAP_BASE)
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-19")
    txt = sm.read_text()
    assert "<loc>https://www.checkal.pt/regulamentos-al-porto</loc>" in txt
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-20")
    txt2 = sm.read_text()
    assert txt2.count("regulamentos-al-porto") == 1          # atualiza, não duplica
    assert "<lastmod>2026-07-20</lastmod>" in txt2


def test_render_artigo_sem_data_carimba_hoje():
    artigo = {k: v for k, v in _ARTIGO.items() if k != "data_publicacao"}
    html = publicador.render_artigo(artigo)
    assert f'"datePublished": "{date.today().isoformat()}"' in html


# ==========================================================================
#  Regressão — 2 Critical de XSS apanhados em revisão (2026-07-19)
# ==========================================================================
def test_render_recusa_slug_hostil():
    """O slug é autorado pelo LLM e entra cru em canonical/og:url/data-evento
    ×2/sitemap — whitelist estrita, não só escape (mata injeção E path
    traversal de uma vez)."""
    mau = dict(_ARTIGO)
    mau["slug"] = '../../evil"><script>x</script>'
    with pytest.raises(ValueError):
        publicador.render_artigo(mau)


def test_render_titulo_hostil_nao_fecha_script():
    """O `titulo` entra no JSON-LD via json.dumps (não html.escape) — sem
    neutralizar `<`/`>`/`&`, um `</script>` no valor fecha o bloco JSON-LD
    prematuramente e o `<script>` seguinte executa."""
    mau = dict(_ARTIGO)
    mau["titulo"] = "Olá </script><script>alert(1)</script>"
    html_out = publicador.render_artigo(mau)
    assert "</script><script>alert" not in html_out
    # e o head só tem scripts src= ou ld+json (regex do teste de estrutura)
    scripts = re.findall(r"<script(?![^>]*application/ld\+json)[^>]*>", html_out)
    assert all("src=" in s for s in scripts)


def test_sitemap_recusa_slug_hostil(tmp_path):
    sm = tmp_path / "sitemap.xml"
    sm.write_text(SITEMAP_BASE)
    with pytest.raises(ValueError):
        publicador.atualizar_sitemap(sm, slug="../../evil", lastmod="2026-07-19")


def test_render_recusa_fonte_javascript():
    """As fontes entram cruas no `href` (`_render_fontes`) — um esquema não
    http(s) (`javascript:`, `data:`, …) executaria no clique. Whitelist
    estrita fail-closed: só `http://`/`https://` (case-insensitive) rendeza
    como link; qualquer outro esquema levanta `ValueError`."""
    mau = dict(_ARTIGO)
    mau["fontes"] = [{"url": "javascript:alert(1)", "titulo": "Fonte hostil"}]
    with pytest.raises(ValueError):
        publicador.render_artigo(mau)


# ==========================================================================
#  F3.4 — a passagem: modo ensaio (read-only) vs modo live (drain + git +
#  wrangler pinado). Isolamento igual a test_swarm_fila.py/test_gate_web.py:
#  BD SQLite temporária via monkeypatch de db.engine/db.SessionLocal. SEM
#  git/wrangler/rede reais — `executar` é sempre um fake.
# ==========================================================================
def _agora() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_publicador_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


# Post conforme (linter R4: fonte oficial cm-porto.pt no próprio texto) — o
# mesmo texto de test_gate_web.py/_POST_OK.
_POST_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al"
)


def _semear_artigo(s, *, agente_origem: str = "editor", estado_pendente: bool = False,
                    artigo: dict | None = None) -> int:
    """Enfileira um `artigo_seo` conforme com o payload no `EventoAgente`
    (exatamente como `manage._cmd_editor_enfileirar` o faz) e, por omissão,
    aprova-o já (token + `fila.aprovar`). `estado_pendente=True` deixa-o
    `pendente` — usado pelos testes de auto-aprovação sob flag."""
    artigo = artigo if artigo is not None else _ARTIGO
    texto, url_fonte, excerto = manage._texto_lint_artigo(artigo)
    peca = PecaOutward(
        texto=texto, canal=Canal.PAGINA_PUBLICA,
        url_fonte=url_fonte, excerto=excerto, gerado_por_ia=True,
    )
    evento = ms.EventoAgente(
        agente=agente_origem, tipo="conteudo_proposto",
        mensagem=f"artigo proposto (/{artigo['slug']})",
        payload={"tipo": "artigo_seo", "artigo": artigo},
        criado_em=_agora(),
    )
    s.add(evento)
    s.flush()
    item = fila.enfileirar(
        s, tipo="artigo_seo", risco="alto", agente_origem=agente_origem,
        ref_tipo="evento_agente", ref_id=str(evento.id),
        resumo=f"artigo_seo /{artigo['slug']}",
        peca=peca,
    )
    s.flush()
    if not estado_pendente:
        token = fila.gerar_token(s, item.id)
        fila.aprovar(s, item.id, token=token, decidido_por="dono")
    return item.id


def _semear_post_grupo(s, *, agente_origem: str = "comunicador") -> int:
    peca = PecaOutward(texto=_POST_OK, canal=Canal.POST_SOCIAL)
    item = fila.enfileirar(
        s, tipo="post_grupo", risco="medio", camada_risco=2,
        agente_origem=agente_origem, resumo="Post sobre o regulamento do Porto",
        peca=peca,
    )
    s.flush()
    token = fila.gerar_token(s, item.id)
    fila.aprovar(s, item.id, token=token, decidido_por="dono")
    return item.id


def _site_fake(tmp_path):
    """`site_dir` fake: sitemap.xml base + `functions/` vazia (para o `cp -r`
    — nunca corre de verdade, `executar` é fake, mas o caminho tem de existir
    para o teste ler o conteúdo real do sitemap/HTML escritos por `correr`)."""
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "sitemap.xml").write_text(SITEMAP_BASE, encoding="utf-8")
    (site_dir / "functions").mkdir()
    return site_dir


class _ResultadoFake:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _texto_cmd(cmd) -> str:
    return " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)


def _fake_executar(
    chamadas: list, *, falha_wrangler: bool = False,
    diff_returncode: int = 1, wrangler_stdout: str | None = None,
):
    """Fake de `executar`: acumula os cmds em `chamadas`.

    `git diff --cached --quiet` devolve `.returncode=diff_returncode` — por
    omissão 1 (HÁ staged changes ⇒ o guard do commit vazio deixa o `git
    commit` acontecer, o caminho normal de uma publicação nova). Os testes de
    retry passam `diff_returncode=0` (nada staged — a 1.ª tentativa já
    comitou) para provar que a 2.ª passagem salta o `commit` mas continua para
    o push+deploy.

    O wrangler devolve `.stdout` com "Uploading Functions bundle" (sucesso)
    por omissão, ou o `wrangler_stdout` explícito (para o teste do marcador
    ausente), ou levanta `CalledProcessError` se `falha_wrangler=True` (para o
    teste de falha de deploy). Nunca toca em git/wrangler/rede reais."""
    def _exec(cmd, **kw):
        chamadas.append(cmd)
        texto = _texto_cmd(cmd)
        if "diff" in texto and "--cached" in texto:
            return _ResultadoFake(returncode=diff_returncode)
        if "wrangler" in texto:
            if falha_wrangler:
                raise subprocess.CalledProcessError(1, cmd, output="", stderr="deploy falhou")
            stdout = (
                wrangler_stdout if wrangler_stdout is not None
                else "Uploading Functions bundle\n✨ Deployment complete\n"
            )
            return _ResultadoFake(stdout=stdout)
        return _ResultadoFake(stdout="")
    return _exec


def test_correr_em_modo_teste_nao_drena_nem_executa(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    with db.get_session() as s:
        item_id = _semear_artigo(s)

    chamadas: list = []
    rel = publicador.correr(
        site_dir=tmp_path / "site", ensaio_dir=tmp_path / "ensaio",
        executar=lambda cmd, **kw: chamadas.append(cmd),
    )

    assert rel["modo"] == "ensaio"
    assert chamadas == []                                  # zero git/wrangler

    # item CONTINUA aprovado — não foi drenado nem marcado feito (drenar em
    # ensaio marcaria 'feito' sem publicar de facto, perdendo-o).
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "aprovado"
        assert item.lease_ate is None

    assert (tmp_path / "ensaio" / "regulamentos-al-porto.html").exists()


def test_ensaio_tolera_item_malformado(bd, tmp_path, monkeypatch):
    """O ensaio é diagnóstico read-only sobre itens já aprovados na BD — um
    payload malformado (aqui: slug inválido, que `render_artigo` recusa com
    `ValueError`) não pode rebentar a passagem nem impedir os restantes itens
    de renderizar: fica no relatório com o erro, a passagem continua."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    mau = dict(_ARTIGO)
    mau["slug"] = "../evil"
    with db.get_session() as s:
        id_bom = _semear_artigo(s)
        id_mau = _semear_artigo(s, artigo=mau)

    chamadas: list = []
    rel = publicador.correr(
        site_dir=tmp_path / "site", ensaio_dir=tmp_path / "ensaio",
        executar=lambda cmd, **kw: chamadas.append(cmd),
    )

    assert rel["modo"] == "ensaio"
    assert chamadas == []
    bons = [a for a in rel["artigos"] if "erro" not in a]
    maus = [a for a in rel["artigos"] if "erro" in a]
    assert len(bons) == 1 and bons[0]["item_id"] == id_bom
    assert len(maus) == 1 and maus[0]["item_id"] == id_mau
    assert (tmp_path / "ensaio" / "regulamentos-al-porto.html").exists()


def test_correr_live_publica_artigo_e_fecha_post(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    with db.get_session() as s:
        artigo_id = _semear_artigo(s)
        post_id = _semear_post_grupo(s)

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    rel = publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas),
    )

    assert rel["modo"] == "live"
    # site_dir/{slug}.html escrito; sitemap atualizado.
    assert (site_dir / "regulamentos-al-porto.html").exists()
    assert "regulamentos-al-porto" in (site_dir / "sitemap.xml").read_text(encoding="utf-8")
    # o post_grupo é no-op — nenhum ficheiro extra além do artigo.
    ficheiros = {p.name for p in site_dir.iterdir()}
    assert ficheiros == {"sitemap.xml", "functions", "regulamentos-al-porto.html"}

    # sequência de comandos: git add/commit/push + wrangler pages deploy
    # (validado via «Uploading Functions bundle» no stdout do fake).
    comandos = [_texto_cmd(c) for c in chamadas]
    assert any(c.startswith("git -C") and " add " in c for c in comandos)
    assert any(c.startswith("git -C") and " commit " in c for c in comandos)
    assert any(c.startswith("git -C") and " push " in c for c in comandos)
    assert any("wrangler" in c and "pages deploy" in c for c in comandos)

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, artigo_id).estado == "feito"
        assert s.get(ms.RevisaoItem, post_id).estado == "feito"


def test_correr_live_auto_aprova_sob_flag(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "AUTO_PUBLICAR_ARTIGO_SEO", True)
    with db.get_session() as s:
        item_id = _semear_artigo(s, estado_pendente=True)

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas),
    )

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "feito"                     # pendente → auto_aprovado → feito
        assert item.decidido_por == "auto"
        apr = s.query(ms.Aprovacao).filter(ms.Aprovacao.revisao_item_id == item_id).one()
        assert apr.decisao == "auto_aprovado"
    assert (site_dir / "regulamentos-al-porto.html").exists()


def test_correr_live_sem_flag_ignora_pendentes(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    assert config.AUTO_PUBLICAR_ARTIGO_SEO is False       # fail-closed por omissão
    with db.get_session() as s:
        item_id = _semear_artigo(s, estado_pendente=True)

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas),
    )

    # só o gate humano decide — sem a flag, pendente fica pendente.
    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "pendente"
    assert not (site_dir / "regulamentos-al-porto.html").exists()
    assert chamadas == []


# Mesmo texto de `_TEXTO_COLD_OK` em test_manage_agentes.py — peça COLD
# conforme (opt-out + identificação legal + disclaimer + divulgação de IA já
# no próprio corpo, `tem_optout_carimbado=True`).
_TEXTO_COLD_OK = (
    "Bom dia,\n\nO CheckAL vigia o registo, o seguro e os regulamentos do concelho "
    "do vosso Alojamento Local. Conteúdo preparado com apoio de inteligência "
    "artificial (IA).\n\nInformação, não aconselhamento jurídico.\n"
    "Para não voltar a ser contactado: checkal.pt/remover\n"
    "O CheckAL é operado por Cosmic Oasis, Lda."
)


def test_correr_live_auto_aprova_ignora_outros_tipos(bd, tmp_path, monkeypatch):
    """PINA o filtro por tipo da auto-aprovação (docstring de `correr`, (a):
    "SÓ esse tipo — o filtro por tipo é responsabilidade de quem chama
    `auto_aprovar`, não da função"). Com `AUTO_PUBLICAR_ARTIGO_SEO=True`, um
    `post_grupo` e um `cold_email` pendentes com `linter_ok` NUNCA são
    auto-aprovados nem publicados — só `artigo_seo` o é. Sem este teste,
    remover o filtro `tipo == "artigo_seo"` de `correr` (chamando
    `fila.auto_aprovar` sobre TODOS os pendentes com `linter_ok`, tipo
    `cold_email` incluído) passaria despercebido: `auto_aprovar` em si é
    TYPE-AGNOSTIC por design (ver o seu docstring) — só o chamador guarda o
    invariante."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "AUTO_PUBLICAR_ARTIGO_SEO", True)

    with db.get_session() as s:
        post_item = fila.enfileirar(
            s, tipo="post_grupo", risco="medio", camada_risco=2,
            agente_origem="comunicador", resumo="Post sobre o regulamento do Porto",
            peca=PecaOutward(texto=_POST_OK, canal=Canal.POST_SOCIAL),
        )
        cold_item = fila.enfileirar(
            s, tipo="cold_email", risco="alto", agente_origem="angariador",
            resumo="cold d0 → geral@sul.pt",
            peca=PecaOutward(
                texto=_TEXTO_COLD_OK, canal=Canal.COLD, tem_optout_carimbado=True,
            ),
        )
        post_id, cold_id = post_item.id, cold_item.id
        assert post_item.estado == "pendente" and post_item.linter_ok is True
        assert cold_item.estado == "pendente" and cold_item.linter_ok is True

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas),
    )

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, post_id).estado == "pendente"
        assert s.get(ms.RevisaoItem, cold_id).estado == "pendente"
    assert chamadas == []          # nada foi publicado/deployado


def test_deploy_falha_marca_falhado_com_backoff(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    with db.get_session() as s:
        item_id = _semear_artigo(s)

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas, falha_wrangler=True),
    )

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "falhado"
        assert item.tentativas == 1
        assert item.nao_antes_de is not None               # backoff futuro
        assert item.lease_ate is None


def test_deploy_sem_marcador_wrangler_marca_falhado(bd, tmp_path, monkeypatch):
    """O wrangler pode sair com código 0 sem ter concluído o deploy — a única
    prova positiva aceite é a linha "Uploading Functions bundle" no stdout.
    Ausente ⇒ RuntimeError ⇒ o drain marca 'falhado' (cobre o ramo de
    validação em `_publicar_no_cloudflare`, distinto do CalledProcessError do
    teste de falha "dura")."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    with db.get_session() as s:
        item_id = _semear_artigo(s)

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas, wrangler_stdout="Success! Deployed.\n"),
    )

    comandos = [_texto_cmd(c) for c in chamadas]
    assert any("wrangler" in c and "pages deploy" in c for c in comandos)
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "falhado"
        assert item.tentativas == 1
        assert item.nao_antes_de is not None
        assert item.lease_ate is None


def test_correr_live_retry_apos_falha_nao_bloqueia_no_commit_vazio(bd, tmp_path, monkeypatch):
    """Cenário de recuperação (a preocupação Important da revisão): 1.ª
    passagem falha no wrangler (item fica 'falhado', mas o `git add`+`commit`
    já correram — o working tree do site já está comitado). O dono repõe o
    item a 'aprovado' à mão (não há auto-retry no drain — mesmo padrão de
    `test_drain_processador_falha_backoff_e_morto` em test_swarm_fila.py). Na
    2.ª passagem já não há nada staged (`diff --cached --quiet` devolve 0): o
    guard do commit vazio TEM de saltar o `git commit` — sem ele, o commit
    vazio rebentaria e bloquearia push+deploy para sempre. Push e deploy
    continuam a correr sempre; o wrangler agora dá certo ⇒ item 'feito'."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    with db.get_session() as s:
        item_id = _semear_artigo(s)

    site_dir = _site_fake(tmp_path)

    # 1.ª passagem: falha no wrangler ⇒ 'falhado' + backoff (git add+commit
    # já tinham corrido antes de o wrangler rebentar).
    chamadas1: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas1, falha_wrangler=True),
    )
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "falhado"
        assert item.tentativas == 1
        # Reposição manual — o drain não re-serve 'falhado' sozinho.
        item.nao_antes_de = datetime.now(timezone.utc) - timedelta(minutes=1)
        item.lease_ate = None
        item.estado = "aprovado"

    # 2.ª passagem: nada staged (diff --cached --quiet ⇒ 0) e o wrangler já
    # funciona ⇒ SEM git commit, COM push+deploy, item 'feito'.
    chamadas2: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas2, diff_returncode=0),
    )

    comandos2 = [_texto_cmd(c) for c in chamadas2]
    assert any(c.startswith("git -C") and " diff " in c for c in comandos2)
    assert not any(c.startswith("git -C") and " commit " in c for c in comandos2)
    assert any(c.startswith("git -C") and " push " in c for c in comandos2)
    assert any("wrangler" in c and "pages deploy" in c for c in comandos2)

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, item_id).estado == "feito"


# ==========================================================================
#  FB2 — publicar_facebook + drain/ensaio de post_pagina (fase FB, 19/07)
#  Live-gated por config.facebook_ativo(): sem PAGE_ID/PAGE_TOKEN, o drain
#  nem inclui post_pagina nos tipos servidos — SEM rede real em teste, o
#  seam `http_post` é sempre um fake.
# ==========================================================================
_POST_PAGINA_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al\n"
    "Preparado com apoio de IA."
)

# Mesmo texto COLD conforme de test_manage_agentes.py/test_publicador (acima)
# — reutilizado no teste de auto-aprovação type-agnostic.
_TEXTO_COLD_OK_FB = (
    "Bom dia,\n\nO CheckAL vigia o registo, o seguro e os regulamentos do concelho "
    "do vosso Alojamento Local. Conteúdo preparado com apoio de inteligência "
    "artificial (IA).\n\nInformação, não aconselhamento jurídico.\n"
    "Para não voltar a ser contactado: checkal.pt/remover\n"
    "O CheckAL é operado por Cosmic Oasis, Lda."
)


def _semear_post_pagina(
    s, *, agente_origem: str = "comunicador", estado_pendente: bool = False,
    texto: str | None = None,
) -> int:
    """Enfileira um `post_pagina` conforme com o payload no `EventoAgente`
    exatamente como `manage._cmd_comunicador_enfileirar` o faz
    (`payload={"tipo": "post_pagina", "corpo_texto": ...}`) e, por omissão,
    aprova-o já (token + `fila.aprovar`)."""
    texto = texto if texto is not None else _POST_PAGINA_OK
    evento = ms.EventoAgente(
        agente=agente_origem, tipo="conteudo_proposto",
        mensagem="post_pagina proposto",
        payload={"tipo": "post_pagina", "corpo_texto": texto},
        criado_em=_agora(),
    )
    s.add(evento)
    s.flush()
    peca = PecaOutward(texto=texto, canal=Canal.POST_PAGINA, gerado_por_ia=True)
    item = fila.enfileirar(
        s, tipo="post_pagina", risco="alto", agente_origem=agente_origem,
        ref_tipo="evento_agente", ref_id=str(evento.id),
        resumo="post_pagina proposto",
        peca=peca,
    )
    s.flush()
    if not estado_pendente:
        token = fila.gerar_token(s, item.id)
        fila.aprovar(s, item.id, token=token, decidido_por="dono")
    return item.id


class _RespostaFacebookFake:
    def __init__(self, *, status_code: int = 200, corpo_json=None, texto: str = ""):
        self.status_code = status_code
        self._corpo_json = corpo_json
        self.text = texto

    def json(self):
        if self._corpo_json is None:
            raise ValueError("resposta sem JSON")
        return self._corpo_json


def _fake_http_post(
    chamadas: list, *, status_code: int = 200, post_id: str = "123_456",
    texto_erro: str = "",
):
    """Fake de `http_post` de `publicar_facebook`: acumula os pedidos em
    `chamadas` (nunca toca rede real) e devolve 200/{"id": post_id} por
    omissão, ou `status_code`/`texto_erro` explícitos (para os testes de
    falha)."""
    def _post(url, *, data=None, timeout=None, **kw):
        chamadas.append({"url": url, "data": data, "timeout": timeout})
        if status_code == 200:
            return _RespostaFacebookFake(status_code=200, corpo_json={"id": post_id})
        return _RespostaFacebookFake(status_code=status_code, texto=texto_erro)
    return _post


# --------------------------------------------------------------------------
#  publicar_facebook — unidade, sem BD (só o seam de rede)
# --------------------------------------------------------------------------
def test_publicar_facebook_sucesso_devolve_id_e_envia_mensagem():
    chamadas: list = []
    post_id = publicador.publicar_facebook(
        "Olá página",
        page_id="987654321",
        token="TOKEN-SECRETO",
        http_post=_fake_http_post(chamadas, post_id="999_111"),
    )
    assert post_id == "999_111"
    assert len(chamadas) == 1
    assert chamadas[0]["url"] == "https://graph.facebook.com/v21.0/987654321/feed"
    assert chamadas[0]["data"] == {"message": "Olá página", "access_token": "TOKEN-SECRETO"}
    assert chamadas[0]["timeout"] == 30


def test_publicar_facebook_erro_http_levanta_sem_vazar_token():
    chamadas: list = []
    http_post = _fake_http_post(
        chamadas, status_code=400,
        texto_erro='{"error": {"message": "token TOKEN-SECRETO inválido"}}',
    )
    with pytest.raises(RuntimeError) as exc:
        publicador.publicar_facebook(
            "Olá página", page_id="987654321", token="TOKEN-SECRETO", http_post=http_post,
        )
    assert "TOKEN-SECRETO" not in str(exc.value)


def test_publicar_facebook_sem_id_na_resposta_levanta():
    chamadas: list = []

    def _post(url, *, data=None, timeout=None, **kw):
        chamadas.append(data)
        return _RespostaFacebookFake(status_code=200, corpo_json={"algo": "sem id"})

    with pytest.raises(RuntimeError):
        publicador.publicar_facebook(
            "Olá página", page_id="987654321", token="T", http_post=_post,
        )


# --------------------------------------------------------------------------
#  correr() live — drain de post_pagina live-gated por facebook_ativo()
# --------------------------------------------------------------------------
def test_correr_live_publica_post_pagina_com_facebook_ativo(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", "987654321")
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", "TOKEN-SECRETO")
    with db.get_session() as s:
        item_id = _semear_post_pagina(s)

    site_dir = _site_fake(tmp_path)
    chamadas_git: list = []
    chamadas_fb: list = []
    rel = publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas_git),
        http_post=_fake_http_post(chamadas_fb),
    )

    assert rel["modo"] == "live"
    assert "facebook" not in rel                      # nada por configurar
    assert len(chamadas_fb) == 1
    assert chamadas_fb[0]["data"]["message"] == _POST_PAGINA_OK
    assert chamadas_fb[0]["data"]["access_token"] == "TOKEN-SECRETO"
    # post_pagina é publicação pura via Graph API — nenhum git/wrangler.
    assert chamadas_git == []

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "feito"
        assert item.lease_ate is None


def test_correr_live_sem_facebook_config_nao_drena_post_pagina(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    assert config.facebook_ativo() is False            # fail-closed por omissão
    with db.get_session() as s:
        item_id = _semear_post_pagina(s)

    site_dir = _site_fake(tmp_path)
    chamadas_fb: list = []
    rel = publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar([]),
        http_post=_fake_http_post(chamadas_fb),
    )

    assert rel["modo"] == "live"
    assert rel["facebook"] == "por configurar"
    assert chamadas_fb == []                           # zero rede

    # item fica intacto — nem foi leased (drain nem o serviu).
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "aprovado"
        assert item.lease_ate is None
        assert item.tentativas == 0


def test_correr_live_post_pagina_erro_http_marca_falhado(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", "987654321")
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", "TOKEN-SECRETO")
    with db.get_session() as s:
        item_id = _semear_post_pagina(s)

    site_dir = _site_fake(tmp_path)
    rel = publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar([]),
        http_post=_fake_http_post([], status_code=400, texto_erro="erro"),
    )

    assert rel["modo"] == "live"
    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "falhado"
        assert item.tentativas == 1
        assert item.nao_antes_de is not None
        assert item.lease_ate is None


def test_correr_live_auto_aprova_post_pagina_sob_flag(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "AUTO_PUBLICAR_POST_PAGINA", True)
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", "987654321")
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", "TOKEN-SECRETO")
    with db.get_session() as s:
        item_id = _semear_post_pagina(s, estado_pendente=True)

    site_dir = _site_fake(tmp_path)
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar([]),
        http_post=_fake_http_post([]),
    )

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "feito"                  # pendente → auto_aprovado → feito
        assert item.decidido_por == "auto"
        apr = s.query(ms.Aprovacao).filter(ms.Aprovacao.revisao_item_id == item_id).one()
        assert apr.decisao == "auto_aprovado"


def test_correr_live_auto_aprova_post_pagina_ignora_outros_tipos(bd, tmp_path, monkeypatch):
    """Espelha `test_correr_live_auto_aprova_ignora_outros_tipos`: sob
    `AUTO_PUBLICAR_POST_PAGINA=True`, um `post_grupo` e um `cold_email`
    pendentes com `linter_ok` NUNCA são auto-aprovados — só `post_pagina`
    (filtro por tipo OBRIGATÓRIO — `fila.auto_aprovar` é TYPE-AGNOSTIC)."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "AUTO_PUBLICAR_POST_PAGINA", True)

    with db.get_session() as s:
        post_item = fila.enfileirar(
            s, tipo="post_grupo", risco="medio", camada_risco=2,
            agente_origem="comunicador", resumo="Post sobre o regulamento do Porto",
            peca=PecaOutward(texto=_POST_OK, canal=Canal.POST_SOCIAL),
        )
        cold_item = fila.enfileirar(
            s, tipo="cold_email", risco="alto", agente_origem="angariador",
            resumo="cold d0 → geral@sul.pt",
            peca=PecaOutward(
                texto=_TEXTO_COLD_OK_FB, canal=Canal.COLD, tem_optout_carimbado=True,
            ),
        )
        post_id, cold_id = post_item.id, cold_item.id
        assert post_item.estado == "pendente" and post_item.linter_ok is True
        assert cold_item.estado == "pendente" and cold_item.linter_ok is True

    site_dir = _site_fake(tmp_path)
    chamadas: list = []
    publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar(chamadas),
        http_post=_fake_http_post([]),
    )

    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, post_id).estado == "pendente"
        assert s.get(ms.RevisaoItem, cold_id).estado == "pendente"
    assert chamadas == []


def test_correr_live_regressao_artigo_e_grupo_intactos_com_post_pagina_na_fila(
    bd, tmp_path, monkeypatch,
):
    """Regressão de conjunto: um `post_pagina` aprovado na fila (sem config
    de Facebook) não pode interferir na publicação normal de `artigo_seo`/
    `post_grupo` — mesma passagem, três tipos coexistem."""
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    with db.get_session() as s:
        artigo_id = _semear_artigo(s)
        post_grupo_id = _semear_post_grupo(s)
        post_pagina_id = _semear_post_pagina(s)

    site_dir = _site_fake(tmp_path)
    rel = publicador.correr(
        site_dir=site_dir, ensaio_dir=tmp_path / "ensaio",
        executar=_fake_executar([]),
        http_post=_fake_http_post([]),
    )

    assert rel["facebook"] == "por configurar"
    with db.get_session() as s:
        assert s.get(ms.RevisaoItem, artigo_id).estado == "feito"
        assert s.get(ms.RevisaoItem, post_grupo_id).estado == "feito"
        item_pagina = s.get(ms.RevisaoItem, post_pagina_id)
        assert item_pagina.estado == "aprovado"
        assert item_pagina.lease_ate is None


# --------------------------------------------------------------------------
#  Ensaio — post_pagina elegível aparece no relatório, zero rede/drain
# --------------------------------------------------------------------------
def test_correr_ensaio_lista_post_pagina_sem_tocar_rede(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    with db.get_session() as s:
        item_id = _semear_post_pagina(s)

    chamadas_fb: list = []

    def _post_nunca_chamado(*a, **kw):
        chamadas_fb.append((a, kw))
        raise AssertionError("ensaio não deve tocar a rede")

    rel = publicador.correr(
        site_dir=tmp_path / "site", ensaio_dir=tmp_path / "ensaio",
        executar=lambda cmd, **kw: (_ for _ in ()).throw(AssertionError("sem comandos em ensaio")),
        http_post=_post_nunca_chamado,
    )

    assert rel["modo"] == "ensaio"
    assert rel["posts_pagina"] == [{"id": item_id, "resumo": "post_pagina proposto"}]
    assert chamadas_fb == []

    with db.get_session() as s:
        item = s.get(ms.RevisaoItem, item_id)
        assert item.estado == "aprovado"               # ensaio não drena
