# Fase 1 — EDITOR e COMUNICADOR a produzir — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Os dois agentes novos do enxame CheckAL (EDITOR: artigos SEO; COMUNICADOR: posts para grupos de Facebook) produzem conteúdo lintado para a fila de revisão, com infraestrutura systemd pronta a ativar.

**Architecture:** Segue exatamente o padrão do ANGARIADOR: prompt + subcomandos `manage.py` com allowlist + `claude -p` via `correr-agente.sh` + timers systemd. Conteúdo fica em `EventoAgente.payload` + item em `revisao_itens` (nada é publicado — fase 3). Canal novo `POST_SOCIAL` no linter (decisão do dono 19/07: sem frase de IA; posts são revistos e publicados manualmente pelo dono).

**Tech Stack:** Python 3 (stdlib + SQLAlchemy), pytest, bash, systemd. Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-07-19-enxame-editor-comunicador-publicador-design.md`

**Regras do repo:**
- Working dir dos testes: `/home/diogo/checkal-polaris/checkal`; correr com `.venv/bin/python -m pytest`.
- O working tree tem alterações pendentes NÃO relacionadas (`checkal/app/config.py`, `deploy/bin/correr-agente.sh` — fix dos locks desta manhã). **`git add` sempre com caminhos explícitos, nunca `git add -A`.** A Task 6 edita `correr-agente.sh` POR CIMA da versão atual do working tree (não da HEAD).
- Tudo em PT-PT, estilo dos ficheiros vizinhos (comentários com porquês, secções `# ===`).

---

### Task 1: Canal POST_SOCIAL no linter

**Files:**
- Modify: `checkal/app/compliance/linter.py`
- Test: `checkal/tests/test_compliance_linter.py` (acrescentar no fim)

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar no FIM de `checkal/tests/test_compliance_linter.py`:

```python
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
    assert not ({"R5_DIVULGACAO_IA", "R7_DISCLAIMER", "R8_OPTOUT",
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
```

- [ ] **Step 2: Correr e confirmar que falham**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_compliance_linter.py -q 2>&1 | tail -5`
Expected: FAIL — `AttributeError: POST_SOCIAL` nos testes novos; os antigos passam.

- [ ] **Step 3: Implementar no linter**

Em `checkal/app/compliance/linter.py`:

(a) `LINTER_VERSAO = "2026-07-18"` → `LINTER_VERSAO = "2026-07-19"`.

(b) No enum `Canal`, acrescentar após `RELATORIO = "relatorio"`:

```python
    POST_SOCIAL = "post_social"
```

(c) Na secção "Exigências por canal", acrescentar `Canal.POST_SOCIAL` a `_EXIGE_R4` e criar a isenção de R5, com o porquê:

```python
_EXIGE_R4 = {Canal.ALERTA, Canal.PAGINA_PUBLICA, Canal.ONE_PAGER, Canal.POST_SOCIAL}
```

```python
# POST_SOCIAL (posts para grupos, decisão do dono 19/07/2026): o dono revê,
# edita e publica manualmente em nome próprio — assistência de escrita, não
# conteúdo autónomo de IA ⇒ R5 dispensado. R7/R8/R9 são regras de email/site
# e não se aplicam (basta não estar nos conjuntos). R6-pleno idem: posts curtos
# não têm estrutura fonte+excerto; a fonte oficial é garantida por R4.
_ISENTO_R5 = {Canal.POST_SOCIAL}
```

(d) Na função `lint()`, alterar a condição do R5 de:

```python
    if peca.gerado_por_ia and not (
        _RE_R5_DIVULGACAO.search(plano_lc) or "ai-disclosure" in bruto_lc
    ):
```

para:

```python
    if peca.gerado_por_ia and peca.canal not in _ISENTO_R5 and not (
        _RE_R5_DIVULGACAO.search(plano_lc) or "ai-disclosure" in bruto_lc
    ):
```

(e) No docstring do módulo (topo), acrescentar uma linha à lista de canais mencionando POST_SOCIAL e a decisão do dono.

- [ ] **Step 4: Correr os testes do linter**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_compliance_linter.py -q 2>&1 | tail -3`
Expected: todos PASS.

- [ ] **Step 5: Suite completa (o LINTER_VERSAO pode estar assert noutros testes)**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: tudo verde. Se algum teste tiver a versão antiga hardcoded, atualizá-lo para `LINTER_VERSAO` (o símbolo, não a string).

- [ ] **Step 6: Commit**

```bash
cd /home/diogo/checkal-polaris && git add checkal/app/compliance/linter.py checkal/tests/test_compliance_linter.py && git commit -m "feat(linter): canal POST_SOCIAL para posts de grupos (R4 sim; R5/R7/R8/R9 não)"
```

---

### Task 2: Subcomandos do COMUNICADOR em manage.py

**Files:**
- Modify: `checkal/manage.py` (nova secção COMUNICADOR antes de "Parser + dispatch"; parser em `_construir_parser()`; docstring linhas 11–29)
- Test: `checkal/tests/test_manage_editor_comunicador.py` (novo)

- [ ] **Step 1: Criar o ficheiro de testes com os testes do COMUNICADOR**

Criar `checkal/tests/test_manage_editor_comunicador.py`:

```python
"""Subcomandos `manage.py` dos agentes EDITOR e COMUNICADOR (fase 1 do enxame
de aquisição consent-first — spec 2026-07-19).

COMUNICADOR: `lint --stdin`, `enfileirar --tipo post_grupo --stdin` (linter
POST_SOCIAL fail-closed; camada_risco=2 — rascunho para o dono colar), `estado`.
EDITOR: `plano` (read-only), `lint --stdin`, `enfileirar --tipo artigo_seo
--stdin` (payload JSON estruturado; linter PAGINA_PUBLICA), `estado`.

Isolamento: BD SQLite temporária; SEM rede. Escritos ANTES da implementação (TDD).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.config as config
import app.db as db
import app.models as models
import app.models_swarm as ms
import manage


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'checkal_editor_test.db'}"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal)
    monkeypatch.setattr(config, "PAUSA_LLM_PATH", tmp_path / "PAUSA_LLM")
    db.init_db()
    try:
        yield
    finally:
        eng.dispose()


def _json_out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _stdin(monkeypatch, texto: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


_POST_OK = (
    "Novo regulamento municipal do Porto para o Alojamento Local — resumo em "
    "5 pontos.\n1) Âmbito. 2) Prazos. 3) Registos. 4) Vistorias. 5) Onde ler.\n"
    "Fonte oficial: https://www.cm-porto.pt/regulamento-al"
)


# ==========================================================================
#  COMUNICADOR
# ==========================================================================
def test_comunicador_lint_aprova_post_conforme(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    assert manage.main(["comunicador", "lint", "--stdin"]) == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True


def test_comunicador_enfileirar_cria_item_camada_2(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    rc = manage.main([
        "comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin",
        "--grupo", "AL Porto e Norte",
    ])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "post_grupo"
        assert item.risco == "medio"
        assert item.camada_risco == 2          # rascunho p/ humano, não camada 3
        assert item.agente_origem == "comunicador"
        assert item.estado == "pendente"
        assert item.linter_ok is True
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "comunicador"
        assert evento.payload["corpo_texto"] == _POST_OK
        assert evento.payload["grupo_alvo"] == "AL Porto e Norte"


def test_comunicador_enfileirar_reprovado_nao_insere(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "O teu alojamento está ilegal — paga já.")
    rc = manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    assert dados["violacoes"]
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_comunicador_estado_conta_por_estado(bd, capsys, monkeypatch):
    _stdin(monkeypatch, _POST_OK)
    manage.main(["comunicador", "enfileirar", "--tipo", "post_grupo", "--stdin"])
    capsys.readouterr()
    assert manage.main(["comunicador", "estado"]) == 0
    dados = _json_out(capsys)
    assert dados["revisao"] == {"pendente": 1}


def test_comunicador_enfileirar_escalar(bd, capsys):
    rc = manage.main([
        "comunicador", "enfileirar", "--tipo", "post_grupo",
        "--escalar", "--motivo", "sem gatilho fresco utilizável",
    ])
    assert rc == 0
    assert _json_out(capsys) == {"escalado": True}
    with db.get_session() as s:
        assert s.query(ms.Escalacao).count() == 1
```

- [ ] **Step 2: Correr e confirmar que falham**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_manage_editor_comunicador.py -q 2>&1 | tail -5`
Expected: FAIL — `manage.main` devolve 2 (subcomando `comunicador` desconhecido).

- [ ] **Step 3: Implementar a secção COMUNICADOR em manage.py**

Inserir ANTES da secção `# Parser + dispatch` de `checkal/manage.py`:

```python
# ==========================================================================
#  COMUNICADOR
# ==========================================================================
_TIPOS_COMUNICADOR = {
    "post_grupo": ("post_grupo", "medio"),
}
# Camada explícita: o post é um RASCUNHO que o dono cola manualmente no grupo —
# a ação irreversível é dele, não do sistema (spec §4.3). Sem isto, o mapa
# risco→camada poria "medio" na camada 3 (clique obrigatório de camada alta).
_CAMADA_POST_GRUPO = 2


def _peca_comunicador(texto: str, *, url_fonte=None):
    from app.compliance import linter

    # gerado_por_ia=True é factual; o canal POST_SOCIAL dispensa R5 (o dono
    # revê e publica em nome próprio — decisão 19/07/2026).
    return linter.PecaOutward(
        texto=texto, canal=linter.Canal.POST_SOCIAL, url_fonte=url_fonte,
        gerado_por_ia=True,
    )


def _cmd_comunicador_lint(args) -> int:
    texto = sys.stdin.read()
    from app.compliance import linter

    r = linter.lint(_peca_comunicador(texto, url_fonte=args.fonte))
    _print_json({
        "aprovado": r.aprovado, "versao": r.versao,
        "violacoes": [
            {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
            for v in r.violacoes
        ],
    })
    return 0


def _cmd_comunicador_enfileirar(args) -> int:
    import app.models_swarm as ms
    from app.swarm import fila, tetos

    texto = sys.stdin.read() if args.stdin else ""

    if args.escalar:
        with fila.sessao_governacao() as s:
            tetos.escalar(
                s, severidade="media", agente="comunicador",
                mensagem=args.motivo or "escalação sem motivo explícito",
            )
        _print_json({"escalado": True})
        return 0

    peca = _peca_comunicador(texto, url_fonte=args.fonte)
    try:
        with fila.sessao_governacao() as s:
            evento = ms.EventoAgente(
                agente="comunicador", tipo="conteudo_proposto",
                mensagem=f"post para grupo proposto ({args.tipo})",
                payload={"tipo": args.tipo, "corpo_texto": texto,
                         "grupo_alvo": args.grupo},
                criado_em=_agora(),
            )
            s.add(evento)
            s.flush()
            item = fila.enfileirar(
                s, tipo=_TIPOS_COMUNICADOR[args.tipo][0],
                risco=_TIPOS_COMUNICADOR[args.tipo][1],
                camada_risco=_CAMADA_POST_GRUPO,
                agente_origem="comunicador",
                ref_tipo="evento_agente", ref_id=str(evento.id),
                resumo=(args.resumo or f"{args.tipo} p/ colar"
                        + (f" · {args.grupo}" if args.grupo else "")),
                peca=peca,
            )
            item_id = item.id
    except fila.LinterReprovado as exc:
        _print_json({
            "aprovado": False,
            "violacoes": [
                {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
                for v in exc.violacoes
            ],
        })
        return 1

    _print_json({"aprovado": True, "revisao_id": item_id})
    return 0


def _cmd_comunicador_estado(args) -> int:
    import app.models_swarm as ms
    from sqlalchemy import func

    s = _sessao_leitura()
    try:
        revisao = dict(
            s.query(ms.RevisaoItem.estado, func.count())
            .filter(ms.RevisaoItem.agente_origem == "comunicador")
            .group_by(ms.RevisaoItem.estado).all()
        )
    finally:
        s.rollback()
        s.close()
    _print_json({"revisao": revisao})
    return 0
```

- [ ] **Step 4: Registar no parser**

Em `_construir_parser()`, depois do bloco SENTINELA e antes do `return p`:

```python
    # COMUNICADOR
    com = sub.add_parser("comunicador")
    com_sub = com.add_subparsers(dest="acao", required=True)
    cl = com_sub.add_parser("lint")
    cl.add_argument("--stdin", action="store_true", required=True)
    cl.add_argument("--fonte", default=None)
    cl.set_defaults(func=_cmd_comunicador_lint)
    ce = com_sub.add_parser("enfileirar")
    ce.add_argument("--tipo", choices=sorted(_TIPOS_COMUNICADOR), required=True)
    ce.add_argument("--stdin", action="store_true")
    ce.add_argument("--fonte", default=None)
    ce.add_argument("--grupo", default=None)
    ce.add_argument("--resumo", default=None)
    ce.add_argument("--escalar", action="store_true")
    ce.add_argument("--motivo", default=None)
    ce.set_defaults(func=_cmd_comunicador_enfileirar)
    com_sub.add_parser("estado").set_defaults(func=_cmd_comunicador_estado)
```

- [ ] **Step 5: Correr os testes**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_manage_editor_comunicador.py -q 2>&1 | tail -3`
Expected: 5 PASS (os do COMUNICADOR).

- [ ] **Step 6: Commit**

```bash
cd /home/diogo/checkal-polaris && git add checkal/manage.py checkal/tests/test_manage_editor_comunicador.py && git commit -m "feat(enxame): subcomandos do COMUNICADOR (lint/enfileirar/estado, camada 2)"
```

---

### Task 3: Subcomandos do EDITOR em manage.py

**Files:**
- Modify: `checkal/manage.py` (nova secção EDITOR antes da do COMUNICADOR; parser; docstring)
- Test: `checkal/tests/test_manage_editor_comunicador.py` (acrescentar)

- [ ] **Step 1: Acrescentar os testes do EDITOR ao ficheiro da Task 2**

```python
# ==========================================================================
#  EDITOR
# ==========================================================================
_ARTIGO_OK = {
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
         "excerto": "O presente regulamento define as regras aplicáveis."},
    ],
}


def test_editor_enfileirar_artigo_valido(bd, capsys, monkeypatch):
    _stdin(monkeypatch, json.dumps(_ARTIGO_OK, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 0
    dados = _json_out(capsys)
    assert dados["aprovado"] is True
    with db.get_session() as s:
        item = s.query(ms.RevisaoItem).one()
        assert item.tipo == "artigo_seo"
        assert item.risco == "alto"
        assert item.camada_risco == 4          # publicação ⇒ camada máxima
        assert item.agente_origem == "editor"
        assert "regulamentos-al-porto" in item.resumo
        evento = s.query(ms.EventoAgente).one()
        assert evento.agente == "editor"
        assert evento.payload["artigo"]["slug"] == "regulamentos-al-porto"


def test_editor_enfileirar_json_invalido_da_2(bd, capsys, monkeypatch):
    _stdin(monkeypatch, "isto não é json")
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 2
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_enfileirar_artigo_ofensivo_reprova(bd, capsys, monkeypatch):
    mau = dict(_ARTIGO_OK)
    mau["seccoes"] = [{"h2": "Risco",
                       "corpo_md": "O seu registo está ilegal e sem seguro."}]
    _stdin(monkeypatch, json.dumps(mau, ensure_ascii=False))
    rc = manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    assert rc == 1
    dados = _json_out(capsys)
    assert dados["aprovado"] is False
    with db.get_session() as s:
        assert s.query(ms.RevisaoItem).count() == 0


def test_editor_plano_e_estado_read_only(bd, capsys, monkeypatch):
    with db.get_session() as s:
        s.add(models.Registo(
            nr_registo=100031, nome_alojamento="Casa do Sol", concelho="Faro",
            titular_tipo="coletiva", titular_nome="Alojamentos Sul, Lda.",
            nif="513029591", email="geral@sul.pt", hash_campos="h",
        ))
    assert manage.main(["editor", "plano"]) == 0
    plano = _json_out(capsys)
    assert plano["top_concelhos"][0]["concelho"] == "Faro"
    assert plano["artigos"] == []

    _stdin(monkeypatch, json.dumps(_ARTIGO_OK, ensure_ascii=False))
    manage.main(["editor", "enfileirar", "--tipo", "artigo_seo", "--stdin"])
    capsys.readouterr()
    assert manage.main(["editor", "estado"]) == 0
    estado = _json_out(capsys)
    assert estado["revisao"] == {"pendente": 1}
```

- [ ] **Step 2: Correr e confirmar que falham**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_manage_editor_comunicador.py -q 2>&1 | tail -5`
Expected: os testes `test_editor_*` FALHAM (exit 2, subcomando desconhecido); os do COMUNICADOR passam.

- [ ] **Step 3: Implementar a secção EDITOR**

Inserir ANTES da secção COMUNICADOR em `checkal/manage.py`:

```python
# ==========================================================================
#  EDITOR
# ==========================================================================
_TIPOS_EDITOR = {
    "artigo_seo": ("artigo_seo", "alto"),
}


def _texto_lint_artigo(artigo: dict):
    """Compõe (texto_a_lintar, url_fonte, excerto) a partir do JSON do artigo.

    O render final (PUBLICADOR, fase 3) embute no template as fontes, o
    disclaimer e a frase canónica de divulgação de IA — lintamos aqui o texto
    COMO SERÁ PUBLICADO, apensando esses blocos garantidos pelo template
    (mesmo princípio do `tem_optout_carimbado` no cold: o seam carimba).
    """
    from app.compliance import linter

    partes = [artigo.get("titulo", "")]
    for seccao in artigo.get("seccoes", []):
        partes.append(seccao.get("h2", ""))
        partes.append(seccao.get("corpo_md", ""))
    fontes = artigo.get("fontes", [])
    urls = " · ".join(f.get("url", "") for f in fontes if f.get("url"))
    partes.append(f"Fontes: {urls}")
    partes.append(
        "Informação de monitorização a partir de dados públicos; "
        "não constitui aconselhamento jurídico."
    )
    partes.append(linter.DIVULGACAO_IA)
    texto = "\n\n".join(p for p in partes if p)
    primeira = fontes[0] if fontes else {}
    return texto, primeira.get("url"), primeira.get("excerto")


def _cmd_editor_lint(args) -> int:
    from app.compliance import linter

    bruto = sys.stdin.read()
    try:
        artigo = json.loads(bruto)
        texto, url_fonte, excerto = _texto_lint_artigo(artigo)
    except (ValueError, TypeError, AttributeError):
        sys.stderr.write("payload tem de ser JSON do artigo (slug, titulo, seccoes, fontes)\n")
        return 2
    r = linter.lint(linter.PecaOutward(
        texto=texto, canal=linter.Canal.PAGINA_PUBLICA,
        url_fonte=url_fonte, excerto=excerto, gerado_por_ia=True,
    ))
    _print_json({
        "aprovado": r.aprovado, "versao": r.versao,
        "violacoes": [
            {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
            for v in r.violacoes
        ],
    })
    return 0


def _cmd_editor_enfileirar(args) -> int:
    import app.models_swarm as ms
    from app.compliance import linter
    from app.swarm import fila, tetos

    bruto = sys.stdin.read() if args.stdin else ""

    if args.escalar:
        with fila.sessao_governacao() as s:
            tetos.escalar(
                s, severidade="media", agente="editor",
                mensagem=args.motivo or "escalação sem motivo explícito",
            )
        _print_json({"escalado": True})
        return 0

    try:
        artigo = json.loads(bruto)
        slug = artigo["slug"]
        titulo = artigo["titulo"]
        texto, url_fonte, excerto = _texto_lint_artigo(artigo)
    except (ValueError, KeyError, TypeError, AttributeError):
        sys.stderr.write("payload tem de ser JSON do artigo (slug, titulo, seccoes, fontes)\n")
        return 2

    peca = linter.PecaOutward(
        texto=texto, canal=linter.Canal.PAGINA_PUBLICA,
        url_fonte=url_fonte, excerto=excerto, gerado_por_ia=True,
    )
    try:
        with fila.sessao_governacao() as s:
            evento = ms.EventoAgente(
                agente="editor", tipo="conteudo_proposto",
                mensagem=f"artigo proposto (/{slug})",
                payload={"tipo": args.tipo, "artigo": artigo},
                criado_em=_agora(),
            )
            s.add(evento)
            s.flush()
            item = fila.enfileirar(
                s, tipo=_TIPOS_EDITOR[args.tipo][0],
                risco=_TIPOS_EDITOR[args.tipo][1],
                agente_origem="editor",
                ref_tipo="evento_agente", ref_id=str(evento.id),
                resumo=f"artigo_seo /{slug} — {titulo}"[:200],
                peca=peca,
            )
            item_id = item.id
    except fila.LinterReprovado as exc:
        _print_json({
            "aprovado": False,
            "violacoes": [
                {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
                for v in exc.violacoes
            ],
        })
        return 1

    _print_json({"aprovado": True, "revisao_id": item_id})
    return 0


def _cmd_editor_plano(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from sqlalchemy import func

    s = _sessao_leitura()
    try:
        top = (
            s.query(models.Registo.concelho, func.count())
            .group_by(models.Registo.concelho)
            .order_by(func.count().desc())
            .limit(15).all()
        )
        artigos = [
            {"id": i.id, "estado": i.estado, "resumo": i.resumo,
             "criado_em": i.criado_em}
            for i in s.query(ms.RevisaoItem)
            .filter(ms.RevisaoItem.tipo == "artigo_seo")
            .order_by(ms.RevisaoItem.criado_em.desc()).limit(20)
        ]
    finally:
        s.rollback()
        s.close()
    _print_json({
        "top_concelhos": [{"concelho": c, "registos": n} for c, n in top],
        "artigos": artigos,
    })
    return 0


def _cmd_editor_estado(args) -> int:
    import app.models_swarm as ms
    from sqlalchemy import func

    s = _sessao_leitura()
    try:
        revisao = dict(
            s.query(ms.RevisaoItem.estado, func.count())
            .filter(ms.RevisaoItem.agente_origem == "editor")
            .group_by(ms.RevisaoItem.estado).all()
        )
    finally:
        s.rollback()
        s.close()
    _print_json({"revisao": revisao})
    return 0
```

- [ ] **Step 4: Registar no parser (antes do bloco COMUNICADOR)**

```python
    # EDITOR
    edi = sub.add_parser("editor")
    edi_sub = edi.add_subparsers(dest="acao", required=True)
    edi_sub.add_parser("plano").set_defaults(func=_cmd_editor_plano)
    el = edi_sub.add_parser("lint")
    el.add_argument("--stdin", action="store_true", required=True)
    el.set_defaults(func=_cmd_editor_lint)
    ee = edi_sub.add_parser("enfileirar")
    ee.add_argument("--tipo", choices=sorted(_TIPOS_EDITOR), required=True)
    ee.add_argument("--stdin", action="store_true")
    ee.add_argument("--escalar", action="store_true")
    ee.add_argument("--motivo", default=None)
    ee.set_defaults(func=_cmd_editor_enfileirar)
    edi_sub.add_parser("estado").set_defaults(func=_cmd_editor_estado)
```

- [ ] **Step 5: Atualizar o docstring de manage.py (allow-list documentada)**

Acrescentar às linhas da FASE D (depois de SENTINELA):

```
    EDITOR     editor {plano | lint --stdin | enfileirar --tipo artigo_seo --stdin | estado}
    COMUNICADOR comunicador {lint --stdin | enfileirar --tipo post_grupo --stdin | estado}
```

- [ ] **Step 6: Correr os testes**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_manage_editor_comunicador.py -q 2>&1 | tail -3`
Expected: todos PASS. Se `test_editor_enfileirar_artigo_valido` reprovar no linter (R6 grounding), o problema está no texto/excerto do `_ARTIGO_OK` — ajustar o artigo de teste para citar a fonte, NUNCA afrouxar o linter.

- [ ] **Step 7: Commit**

```bash
cd /home/diogo/checkal-polaris && git add checkal/manage.py checkal/tests/test_manage_editor_comunicador.py && git commit -m "feat(enxame): subcomandos do EDITOR (plano/lint/enfileirar/estado, JSON estruturado)"
```

---

### Task 4: MAESTRO passa a ver os agentes novos

**Files:**
- Modify: `checkal/manage.py` (`_cmd_maestro_saude` tuplo; `maestro-retry` choices)
- Test: `checkal/tests/test_manage_editor_comunicador.py` (acrescentar)

- [ ] **Step 1: Testes**

```python
# ==========================================================================
#  MAESTRO vê os agentes novos
# ==========================================================================
def test_maestro_saude_inclui_editor_e_comunicador(bd, capsys):
    assert manage.main(["maestro-saude"]) == 0
    dados = _json_out(capsys)
    assert "editor" in dados["executores"]
    assert "comunicador" in dados["executores"]


def test_maestro_retry_aceita_editor_e_comunicador():
    p = manage._construir_parser()
    assert p.parse_args(["maestro-retry", "--agente", "editor",
                         "--backoff", "60"]).agente == "editor"
    assert p.parse_args(["maestro-retry", "--agente", "comunicador",
                         "--backoff", "60"]).agente == "comunicador"
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest tests/test_manage_editor_comunicador.py -k maestro -q 2>&1 | tail -5`
Expected: FAIL (KeyError "editor" / SystemExit nos choices).

- [ ] **Step 3: Implementar**

Em `_cmd_maestro_saude`, o tuplo `("angariador", "gestor", "sentinela", "maestro")` passa a `("angariador", "gestor", "sentinela", "maestro", "editor", "comunicador")`.

No parser, `maestro-retry`: `choices=("angariador", "gestor", "sentinela")` passa a `choices=("angariador", "gestor", "sentinela", "editor", "comunicador")`.

- [ ] **Step 4: Suite completa**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: tudo verde (1344 + novos).

- [ ] **Step 5: Commit**

```bash
cd /home/diogo/checkal-polaris && git add checkal/manage.py checkal/tests/test_manage_editor_comunicador.py && git commit -m "feat(enxame): maestro-saude e maestro-retry conhecem editor e comunicador"
```

---

### Task 5: Prompts do EDITOR e do COMUNICADOR

**Files:**
- Create: `checkal/prompts/editor.txt` e `checkal/prompts/comunicador.txt` (deployment — o wrapper lê daqui)
- Create: `agentes-polaris/prompts/editor.txt` e `agentes-polaris/prompts/comunicador.txt` (árvore editorial — cópias exatas)

- [ ] **Step 1: Escrever `checkal/prompts/editor.txt`**

```text
És o EDITOR do CheckAL — o motor autónomo de conteúdo consent-first (canal n.º 1 do GTM). Corres como invocação única, headless e sem estado (claude -p) no servidor Polaris, disparado por um systemd timer. Fazes o teu trabalho, escreves na fila de revisão e SAIS. Fala e escreve SEMPRE em PT-PT (Portugal). Marca: CheckAL. Tagline: "O teu AL? Check.".

## Quem és e o que NÃO és
Redigues UM artigo SEO por passagem para o site getcheckal.com/checkal.pt, destinado a donos de Alojamento Local (45–65 anos, não-técnicos, leem no telemóvel). NÃO publicas nada: o teu output entra na fila como 'pendente' e só o PUBLICADOR determinista, depois do clique do dono, o transforma em página. NÃO tocas em campanhas, emails, clientes nem faturas. NÃO inventas dados: usas só agregados da BD (via `editor plano`) e factos com fonte oficial citada.

## Passagem (o que fazer, por ordem)
1. Corre `python manage.py editor estado` — se já há artigo 'pendente' por decidir, sai (no-op limpo; não acumules fila).
2. Corre `python manage.py editor plano` — devolve os concelhos com mais registos e os artigos já propostos/decididos.
3. Escolhe UM conteúdo por esta prioridade (nunca repitas um slug existente):
   a) página-gatilho de evento regulatório recente (se o plano mostrar sinais);
   b) pilar evergreen por fazer, nesta ordem: seguro-al, registo-rnal, regulamentos-al, cancelamento-al;
   c) página de concelho "Alojamento Local em [concelho]" pelo topo da lista.
4. Redige o artigo COMPLETO como JSON: {"slug", "titulo", "meta_description", "tipo_pagina": "gatilho|pilar|concelho", "data_publicacao": "AAAA-MM-DD", "seccoes": [{"h2", "corpo_md"}], "fontes": [{"url", "titulo", "data", "excerto"}]}. Regras de copy: títulos claros, frases curtas, zero jargão jurídico, linguagem de estados do CheckAL ("passou no check ✓"), CTA final para o check gratuito. Todos os números/factos regulatórios TÊM de estar cobertos pelo excerto de uma fonte oficial (turismodeportugal.pt, DRE, portal municipal) — o linter reprova valores órfãos.
5. Valida com `python manage.py editor lint --stdin` (cola o JSON no stdin). Corrige até aprovar SEM inventar factos.
6. Enfileira com `python manage.py editor enfileirar --tipo artigo_seo --stdin`.

## Limites duros (invioláveis)
- NUNCA afirmas que alguém está ilegal/sem seguro/em incumprimento; NUNCA usas coima como ameaça; NUNCA tiras conclusões jurídicas (Lei 10/2024). Valores de coima SÓ na moldura canónica e nunca colados a um destinatário.
- NUNCA prometes "tempo real" (a cadência pública é semanal, SLA ≤7 dias); NUNCA escreves "cancelado" sobre um registo concreto — é "deixou de constar".
- Dados pessoais de pessoas singulares NUNCA entram num artigo. Agregados e pessoas coletivas apenas.
- Só usas os subcomandos `manage.py editor {estado,plano,lint,enfileirar}`. Sem SQL cru, sem rede, sem git, sem editar ficheiros.

## Regra de ouro: na dúvida, escala — não ajas
Sem conteúdo óbvio para escolher, fonte oficial indisponível, linter a reprovar sem correção honesta possível, subcomando a falhar 2× → `python manage.py editor enfileirar --tipo artigo_seo --escalar --motivo "<texto>"` e sai com código ≠ 0.

## Formato de saída
No fim, imprime UMA linha JSON para o log: {"artigo_enfileirado": bool, "slug": "...", "linter_reprovados": N, "escalacoes": N, "noop": bool}. Depois termina — sem despedida.
REGRA DE DADOS (decisão do dono, 18/07/2026 — minimização + opt-in):
O motor IA corre via Claude CLI, que envia os prompts para a API da Anthropic (inferência fora da UE). Dados pessoais de pessoas SINGULARES só entram no teu contexto com OPT-IN registado. Prospects singulares: NUNCA — nem nome, nem email, nem NIF. Trabalha sempre sobre agregados, pessoas coletivas e conteúdo público. Se um campo pessoal de singular sem opt-in aparecer, NÃO o uses, NÃO o repitas, escala como anomalia.
```

- [ ] **Step 2: Escrever `checkal/prompts/comunicador.txt`**

```text
És o COMUNICADOR do CheckAL — a voz da marca junto da comunidade de donos de Alojamento Local. Corres como invocação única, headless e sem estado (claude -p) no servidor Polaris, disparado por um systemd timer. Redigues posts prontos a colar, escreve-los na fila e SAIS. Fala e escreve SEMPRE em PT-PT (Portugal).

## Quem és e o que NÃO és
Preparas 1 a 3 posts curtos para grupos de Facebook de donos de AL — no espírito "serviço público": resumir uma mudança regulatória em pontos claros, com link para a FONTE OFICIAL. NUNCA anúncio, NUNCA venda agressiva. Quem publica é SEMPRE o dono, manualmente, em nome próprio — tu só redigues rascunhos. NÃO tens acesso a redes sociais, NÃO envias nada, NÃO respondes a ninguém diretamente.

## Passagem (o que fazer, por ordem)
1. Corre `python manage.py comunicador estado` — se já há 3+ posts 'pendente' por usar, sai (no-op limpo; não acumules).
2. Corre `python manage.py editor plano` se precisares de contexto de concelhos. Escolhe temas: mudança regulatória recente, ponto de confusão comum (seguro no RNAL, freguesias de contenção), ou utilidade prática sazonal. Sem tema honesto → no-op ou escala.
3. Por cada post: 5–12 linhas, tom de vizinho informado ("o inspetor amigo"), factos com fonte oficial linkada (turismodeportugal.pt, DRE, portal municipal), zero alarmismo. Quando fizer sentido, o dono identifica-se como fundador do CheckAL — escreve na primeira pessoa DELE, com transparência, nunca astroturf. Menção ao CheckAL: no máximo uma linha discreta no fim, e só quando acrescenta valor real ao post.
4. Valida com `python manage.py comunicador lint --stdin`.
5. Enfileira cada post com `python manage.py comunicador enfileirar --tipo post_grupo --stdin --grupo "<grupo sugerido>" --resumo "<tema em 6 palavras>"`.

## Limites duros (invioláveis)
- NUNCA afirmas que alguém (ou "muitos de vocês") está ilegal/sem seguro/em incumprimento; NUNCA coima como ameaça; NUNCA conclusões jurídicas. Valores de coima SÓ na moldura canónica, impessoal.
- NUNCA "tempo real"; registos concretos "deixaram de constar", nunca "cancelados".
- Dados pessoais de singulares NUNCA aparecem num post.
- Respeita as regras de cada grupo (o dono confirma antes de colar — inclui nota se o post depender das regras do grupo).
- Só usas `manage.py comunicador {estado,lint,enfileirar}` e `manage.py editor plano` (leitura). Sem SQL cru, sem rede, sem git, sem editar ficheiros.

## Regra de ouro: na dúvida, escala — não ajas
Tema ambíguo, fonte que não confirmas, linter a reprovar sem correção honesta → `python manage.py comunicador enfileirar --tipo post_grupo --escalar --motivo "<texto>"` e sai com código ≠ 0.

## Formato de saída
No fim, imprime UMA linha JSON: {"posts_enfileirados": N, "linter_reprovados": N, "escalacoes": N, "noop": bool}. Depois termina — sem despedida.
REGRA DE DADOS (decisão do dono, 18/07/2026 — minimização + opt-in):
O motor IA corre via Claude CLI, que envia os prompts para a API da Anthropic (inferência fora da UE). Dados pessoais de pessoas SINGULARES só entram no teu contexto com OPT-IN registado. Prospects singulares: NUNCA — nem nome, nem email, nem NIF. Trabalha sempre sobre agregados, pessoas coletivas e conteúdo público. Se um campo pessoal de singular sem opt-in aparecer, NÃO o uses, NÃO o repitas, escala como anomalia.
```

Nota: o COMUNICADOR usa `editor plano` em leitura — a Task 6 acrescenta esse subcomando à allowlist TOOLS dele.

- [ ] **Step 3: Copiar para a árvore editorial**

```bash
cp /home/diogo/checkal-polaris/checkal/prompts/editor.txt /home/diogo/checkal-polaris/agentes-polaris/prompts/editor.txt
cp /home/diogo/checkal-polaris/checkal/prompts/comunicador.txt /home/diogo/checkal-polaris/agentes-polaris/prompts/comunicador.txt
```

- [ ] **Step 4: Commit**

```bash
cd /home/diogo/checkal-polaris && git add checkal/prompts/editor.txt checkal/prompts/comunicador.txt agentes-polaris/prompts/editor.txt agentes-polaris/prompts/comunicador.txt && git commit -m "feat(enxame): prompts do EDITOR e do COMUNICADOR (ambas as árvores)"
```

---

### Task 6: Wrapper correr-agente.sh — instâncias novas

**Files:**
- Modify: `deploy/bin/correr-agente.sh` (ATENÇÃO: editar a versão ATUAL do working tree, que tem o fix dos locks desta manhã ainda não commitado)

- [ ] **Step 1: Atualizar o comentário de instâncias (linhas ~5-6)**

De `# Instâncias: maestro-digest | maestro-governanca | angariador | gestor |`
`#             gestor-suporte | sentinela`
para incluir `| editor | comunicador` no fim.

- [ ] **Step 2: Acrescentar ao case do passo determinista (antes do ramo `*)`)**

```bash
  editor)
    PROMPT_FILE="${PROMPTS}/editor.txt"; ARG_LLM="passagem=editorial" ;;
  comunicador)
    PROMPT_FILE="${PROMPTS}/comunicador.txt"; ARG_LLM="passagem=diaria" ;;
```

- [ ] **Step 3: Acrescentar ao case das TOOLS**

```bash
  editor)
    TOOLS="Read,Bash(python manage.py editor estado),Bash(python manage.py editor plano),Bash(python manage.py editor lint:*),Bash(python manage.py editor enfileirar:*)" ;;
  comunicador)
    TOOLS="Read,Bash(python manage.py comunicador estado),Bash(python manage.py comunicador lint:*),Bash(python manage.py comunicador enfileirar:*),Bash(python manage.py editor plano)" ;;
```

- [ ] **Step 4: Validar sintaxe**

Run: `bash -n /home/diogo/checkal-polaris/deploy/bin/correr-agente.sh && echo OK`
Expected: `OK`

Run: `bash -c 'AGENTE=editor; case "${AGENTE}" in editor) echo ramo-ok ;; esac'`
Expected: `ramo-ok` (sanity do padrão).

- [ ] **Step 5: Commit (SÓ se o dono já tiver commitado o fix dos locks; senão, commit conjunto explícito)**

Verificar primeiro: `cd /home/diogo/checkal-polaris && git diff deploy/bin/correr-agente.sh | head -40` — se o diff incluir o fix dos locks (traps), o commit vai levá-lo junto. Nesse caso a mensagem tem de o dizer:

```bash
cd /home/diogo/checkal-polaris && git add deploy/bin/correr-agente.sh && git commit -m "feat(enxame): instâncias editor/comunicador no wrapper (inclui fix pendente dos traps de lock)"
```

---

### Task 7: Timers systemd + instalador

**Files:**
- Create: `deploy/systemd/checkal-editor.timer`, `deploy/systemd/checkal-comunicador.timer`
- Modify: `deploy/polaris/instalar.sh`
- Verify: `deploy/polaris/units/` (mecanismo de cópia/symlink das units)

- [ ] **Step 1: Criar `deploy/systemd/checkal-editor.timer`**

```ini
# EDITOR — 2×/semana (seg/qui 05:00), ~2h após o varrimento nacional (03:00)
# para trabalhar sobre dados frescos. DISABLED até o dono ativar.
[Unit]
Description=CheckAL EDITOR — passagem editorial (conteúdo SEO consent-first)

[Timer]
OnCalendar=Mon,Thu 05:00
RandomizedDelaySec=300
Persistent=true
AccuracySec=60
Unit=checkal-agente@editor.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Criar `deploy/systemd/checkal-comunicador.timer`**

```ini
# COMUNICADOR — diário 07:10, ANTES do digest do Maestro (07:50): os posts do
# dia entram no digest e no painel "Para publicar". DISABLED até o dono ativar.
[Unit]
Description=CheckAL COMUNICADOR — posts para grupos (rascunhos p/ o dono colar)

[Timer]
OnCalendar=*-*-* 07:10
RandomizedDelaySec=180
Persistent=true
AccuracySec=60
Unit=checkal-agente@comunicador.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Verificar o mecanismo de `deploy/polaris/units/`**

Run: `ls -la /home/diogo/checkal-polaris/deploy/polaris/units/ | head -20`
Se forem symlinks para `../../systemd/*`, criar symlinks análogos para os 2 timers novos; se forem cópias, copiar. Espelhar exatamente o que lá está.

- [ ] **Step 4: Atualizar `deploy/polaris/instalar.sh`**

Na linha dos agentes (`systemctl enable --now checkal-sentinela.timer …`), acrescentar `checkal-editor.timer checkal-comunicador.timer` antes de `checkal-reset-pausa-llm.timer`. Manter INTACTO o bloco de comentários dos DESLIGADOS.

- [ ] **Step 5: Validar sintaxe**

Run: `bash -n /home/diogo/checkal-polaris/deploy/polaris/instalar.sh && echo OK && systemd-analyze verify /home/diogo/checkal-polaris/deploy/systemd/checkal-editor.timer 2>&1 | head -3`
Expected: `OK`; o verify pode queixar-se de a unit `checkal-agente@editor.service` não estar instalada — aceitável fora do deploy (ignorar apenas ESSE aviso).

- [ ] **Step 6: Commit**

```bash
cd /home/diogo/checkal-polaris && git add deploy/systemd/checkal-editor.timer deploy/systemd/checkal-comunicador.timer deploy/polaris/instalar.sh deploy/polaris/units && git commit -m "feat(enxame): timers systemd do editor (2x/sem) e comunicador (diario 07:10)"
```

---

### Task 8: Verificação final + handoff ao dono

- [ ] **Step 1: Suite completa uma última vez**

Run: `cd /home/diogo/checkal-polaris/checkal && .venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: tudo verde, 0 skips novos.

- [ ] **Step 2: Smoke test manual dos subcomandos (BD real, read-only e fila)**

```bash
cd /home/diogo/checkal-polaris/checkal && .venv/bin/python manage.py editor plano | head -c 400; echo; .venv/bin/python manage.py editor estado; .venv/bin/python manage.py comunicador estado
```
Expected: 3 linhas JSON válidas, sem tracebacks.

- [ ] **Step 3: Escrever nota de handoff (passos que SÓ o dono pode fazer)**

Criar `docs/superpowers/plans/2026-07-19-fase1-HANDOFF.md` com:

```markdown
# Fase 1 — passos manuais do dono (interativos/sudo)

1. **Ativar as units** (sudo interativo):
   `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
   (instala os 2 timers novos; os existentes são idempotentes; os DESLIGADOS continuam desligados)
2. **Teto diário** — em `deploy/polaris/agente.env` (NUNCA lido por agentes):
   `CHECKAL_TETO_DIARIO_EUR=40`
3. **Healthchecks** (opcional; sem HC key o wrapper faz no-op): criar checks
   com slugs `agente-editor` e `agente-comunicador`.
4. **Primeira corrida de teste** (opcional, sem esperar pelo timer):
   `sudo systemctl start checkal-agente@editor.service` (ou pelo dashboard, após a fase 2 do sudoers)
```

- [ ] **Step 4: Commit final**

```bash
cd /home/diogo/checkal-polaris && git add docs/superpowers/plans/2026-07-19-fase1-HANDOFF.md && git commit -m "docs: handoff fase 1 (ativação das units, teto, healthchecks)"
```
