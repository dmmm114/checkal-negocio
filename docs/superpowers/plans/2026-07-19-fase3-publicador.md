# Fase 3 — PUBLICADOR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Após o clique do dono no portão, o PUBLICADOR determinista transforma artigos aprovados em páginas no ar (render → sitemap → commit no repo aninhado → deploy Cloudflare Pages via staging), fecha os `post_grupo` aprovados como no-op, e suporta autonomia gradual fail-closed.

**Architecture:** Módulo novo `app/publicador.py` (padrão dos executores deterministas de topo, como `crons.py`). Job legado `_JOBS['publicador']` em manage.py (o `checkal-cron@.service` passa `%i` como UM argv) + timer `checkal-cron-publicador.timer`. `fila.drain()` ganha kwargs aditivos (`tipos`, `cap`, `incluir_auto_aprovado`) — sem chamadores em produção, retrocompatível por construção. Auto-aprovação escreve `estado='auto_aprovado'` (nunca `'aprovado'` — preserva o invariante) via `fila.auto_aprovar()` sob flag fail-closed. **Em `CHECKAL_MODO_TESTE` o publicador NÃO drena**: modo ensaio read-only (renderiza para pasta de ensaio, valida, relata) — drenar em dry-run marcaria itens `feito` sem os publicar, perdendo-os.

**Tech Stack:** Python stdlib (html, re, subprocess, pathlib), git CLI, `npx wrangler@4.111.0` (pinado). Sem dependências Python novas (mini-conversor de markdown próprio — não existe nenhum no projeto).

**Spec:** `docs/superpowers/specs/2026-07-19-enxame-editor-comunicador-publicador-design.md` §6.
**Auditoria-chave:** template = `site/porto.html` (blocos literais documentados); os artigos existentes NÃO têm a frase de IA nem o disclaimer canónico — o render TEM de os embutir importando `linter.DIVULGACAO_IA` e `linter.DISCLAIMER_NAO_ACONSELHAMENTO` (nunca strings copiadas), senão o texto lintado diverge do publicado; wrangler autentica hoje por OAuth (CLOUDFLARE_API_TOKEN opcional, tem precedência quando existir); repo `site/.git` limpo com autor local configurado; README passo 5 (linha 62) contradiz o pipeline e é corrigido aqui.

**Desvio deliberado do spec §6.3 (documentar no commit):** só `CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO`; a flag de `post_grupo` não existe (o dono cola sempre à mão — uma flag sem efeito seria ruído; YAGNI).

---

### F3.1: `drain()` ganha `tipos`, `cap` e `incluir_auto_aprovado`

**Files:** Modify `checkal/app/swarm/fila.py` (drain, ~linha 268; docstring do módulo linha 16); Test `checkal/tests/test_swarm_fila.py`.

- [ ] **Step 1 — Testes primeiro** (padrão `_enfileirar_ok`+aprovação dos testes de drain existentes, linhas 232-300 — lê-os):

```python
def test_drain_filtra_por_tipos(bd):
    # 2 itens aprovados de tipos diferentes; drain(tipos={'artigo_seo'}) só serve um.
    # O outro fica 'aprovado' intacto (sem lease) — não é apanhado por engano.
    ...


def test_drain_cap_proprio_desacoplado_do_campanha_cap(bd, monkeypatch):
    monkeypatch.setattr(config, "CAMPANHA_CAP_DIARIO", 1)
    # 3 aprovados; drain(cap=2) serve 2 — o cap próprio substitui a base do min.
    ...


def test_drain_auto_aprovado_so_com_opt_in(bd):
    # item com estado='auto_aprovado' (escrito à mão no teste): drain() normal
    # NÃO o serve; drain(incluir_auto_aprovado=True) serve.
    ...
```

(Escreve os corpos completos seguindo os seeds dos testes vizinhos; o terceiro escreve `item.estado = 'auto_aprovado'` diretamente na sessão de teste.)

- [ ] **Step 2 — Ver falhar** (`TypeError: unexpected keyword`).
- [ ] **Step 3 — Implementar** (aditivo):

```python
def drain(
    session,
    agente: str,
    limite: int | None = None,
    processador: Callable[[ms.RevisaoItem], object] | None = None,
    *,
    tipos: Iterable[str] | None = None,
    cap: int | None = None,
    incluir_auto_aprovado: bool = False,
) -> list[ms.RevisaoItem]:
```

Na query: `estados = ("aprovado", "auto_aprovado") if incluir_auto_aprovado else ("aprovado",)` → `.filter(ms.RevisaoItem.estado.in_(estados))`; se `tipos`, acrescenta `.filter(ms.RevisaoItem.tipo.in_(tuple(tipos)))`. Cap: `base = cap if cap is not None else config.CAMPANHA_CAP_DIARIO; cap_final = base if limite is None else min(limite, base)`. Docstring do drain e do módulo (linha 16) atualizados: o cap é `CAMPANHA_CAP_DIARIO` por omissão OU o `cap` do chamador; `tipos` evita que um consumidor apanhe itens de outros; `incluir_auto_aprovado` é opt-in explícito.

- [ ] **Step 4 — Verde + suite completa** (os 5 testes de drain existentes intactos).
- [ ] **Step 5 — Commit** `feat(fila): drain com tipos/cap proprios e opt-in de auto_aprovado`

---

### F3.2: Config de autonomia + `fila.auto_aprovar()`

**Files:** Modify `checkal/app/config.py` (secção ENXAME), `checkal/app/swarm/fila.py`; Test `checkal/tests/test_swarm_fila.py`.

- [ ] **Step 1 — Testes primeiro:**

```python
def test_auto_publicar_default_fail_closed():
    assert config.AUTO_PUBLICAR_ARTIGO_SEO is False


def test_auto_aprovar_escreve_auto_aprovado_nunca_aprovado(bd):
    with db.get_session() as s:
        item = _enfileirar_ok(s)
        s.flush()
        out = fila.auto_aprovar(s, item.id)
        assert out.estado == "auto_aprovado"          # NUNCA 'aprovado'
        apr = s.query(ms.Aprovacao).one()
        assert apr.decidido_por == "auto"
        assert apr.autor == item.agente_origem        # autor≠aprovador preservado
        assert apr.decisao == "auto_aprovado"


def test_auto_aprovar_recusa_nao_pendente(bd):
    # item já decidido ⇒ TokenInvalido (reutiliza a exceção de estado inválido)
    ...


def test_auto_aprovar_recusa_linter_nok(bd):
    # linter_ok=False (escrito à mão) ⇒ recusa
    ...
```

- [ ] **Step 2 — Ver falhar.** **Step 3 — Implementar:**

`config.py` (secção ENXAME DE AGENTES):

```python
# 🚦 Autonomia gradual do PUBLICADOR (fase 3) — fail-closed: o dono promove
# um tipo de artefacto a auto-publicação SÓ quando o historial for limpo.
# post_grupo não tem flag: o dono cola sempre à mão (spec §6.3, YAGNI).
AUTO_PUBLICAR_ARTIGO_SEO = _env_bool("CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO", False)
PUBLICADOR_CAP_PASSAGEM = int(_env("CHECKAL_PUBLICADOR_CAP_PASSAGEM", "2"))
```

`fila.py`, junto de `aprovar`/`rejeitar`:

```python
def auto_aprovar(session, item_id: int) -> ms.RevisaoItem:
    """Auto-aprovação por config do dono — escreve `auto_aprovado`, NUNCA `aprovado`.

    Preserva o invariante do módulo ("nenhum caminho de agente escreve
    'aprovado'"): o estado novo só é servido pelo drain com o opt-in explícito
    `incluir_auto_aprovado=True`. Exige item `pendente` com `linter_ok=True`.
    Regista a decisão em `aprovacoes` com decidido_por='auto' (autor≠aprovador
    mantido — o autor é o agente de origem). O gate de QUANDO auto-aprovar
    (config AUTO_PUBLICAR_*) é do chamador (publicador), não daqui.
    """
    item = session.get(ms.RevisaoItem, item_id)
    if item is None or item.estado != "pendente":
        raise TokenInvalido(f"item {item_id} inexistente ou já decidido")
    if not item.linter_ok:
        raise TokenInvalido(f"item {item_id} sem linter_ok — não auto-aprovável")
    autor = item.agente_origem or "desconhecido"
    session.add(ms.Aprovacao(
        revisao_item_id=item.id, autor=autor, decidido_por="auto",
        decisao="auto_aprovado", token_usado=None, nota="auto-publicação por config",
        criado_em=_agora(),
    ))
    item.estado = "auto_aprovado"
    item.decidido_em = _agora()
    item.decidido_por = "auto"
    session.flush()
    return item
```

(Confirma que `Aprovacao.token_usado` aceita None no modelo; se for NOT NULL usa `""` e nota-o.) Acrescenta `auto_aprovar` ao `__all__`.

- [ ] **Step 4 — Verde + suite.** **Step 5 — Commit** `feat(fila): auto_aprovar (estado auto_aprovado, decidido_por=auto) + flags fail-closed`

---

### F3.3: Render do artigo + sitemap (`app/publicador.py` parte 1)

**Files:** Create `checkal/app/publicador.py`; Test `checkal/tests/test_publicador.py` (novo).

- [ ] **Step 1 — Testes primeiro** (`test_publicador.py`): usa o `_ARTIGO_OK` de `test_manage_editor_comunicador.py` como base (importa-o ou duplica — duplicar é ok, ficheiros de teste são independentes):

```python
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
    # fontes e CTA com data-evento por slug
    assert _ARTIGO["fontes"][0]["url"] in html
    assert f'data-evento="cta_{_ARTIGO["slug"]}_corpo"' in html
    # sem scripts inline executáveis (CSP script-src 'self'); ld+json permitido
    import re
    scripts = re.findall(r"<script(?![^>]*application/ld\+json)[^>]*>", html)
    assert all("src=" in s for s in scripts)


def test_render_artigo_idempotente():
    assert publicador.render_artigo(_ARTIGO) == publicador.render_artigo(_ARTIGO)


def test_sitemap_acrescenta_e_atualiza_idempotente(tmp_path):
    sm = tmp_path / "sitemap.xml"
    sm.write_text(SITEMAP_BASE)  # cabeçalho + entrada de "/" (copia o formato real)
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-19")
    txt = sm.read_text()
    assert "<loc>https://www.checkal.pt/regulamentos-al-porto</loc>" in txt
    publicador.atualizar_sitemap(sm, slug="regulamentos-al-porto", lastmod="2026-07-20")
    txt2 = sm.read_text()
    assert txt2.count("regulamentos-al-porto") == 1          # atualiza, não duplica
    assert "<lastmod>2026-07-20</lastmod>" in txt2
```

- [ ] **Step 2 — Ver falhar.** **Step 3 — Implementar `app/publicador.py` (parte 1):**

Estrutura do módulo (docstring PT-PT: "o braço determinista da publicação — o LLM propõe, o dono/config aprova, ISTO publica"):

1. `md_para_html(md: str) -> str` — mini-conversor determinista, `html.escape` PRIMEIRO, depois: `**x**`→`<strong>`, blocos separados por linha em branco, bloco cujas linhas começam todas por `N. `→`<ol><li>`, por `- `→`<ul><li>`, resto→`<p>`. Nada mais (sem links/h3/imagens — o corpo dos artigos não os usa; o linter/prompt garantem).
2. Constantes de template: `_HEADER`, `_FOOTER`, `_CTA`, `_HEAD_FMT` etc. — **copiar LITERALMENTE de `site/porto.html`** (incl. o SVG do logo byte a byte, o footer com a denominação legal, o skip-link, o `<script src="/assets/js/main.js" defer>`), com placeholders `{slug}`/`{titulo}`/… onde a auditoria marcou variação (title, meta description, canonical www extensionless, OG com og:image `https://checkal.pt/assets/img/og.png` SEM www — literal como nos existentes, JSON-LD Article com datePublished, `data-evento="cta_{slug}_header"` e `_corpo`, `rotulo-secao`, `p.nota` "Atualizado a {data por extenso}").
3. `render_artigo(artigo: dict) -> str` — compõe head+header+article (h1=titulo; secções h2+`md_para_html(corpo_md)`; CTA; bloco Fontes `<a href rel="noopener">` separados por ' · '; disclaimer: `DISCLAIMER_NAO_ACONSELHAMENTO` + frase `DIVULGACAO_IA`, ambos importados de `app.compliance.linter`, cada um em `<p class="nota">`)+footer. `data_publicacao` ausente ⇒ usa a data de hoje (o PUBLICADOR carimba — combinado com o prompt do editor).
4. `atualizar_sitemap(caminho: Path, *, slug: str, lastmod: str) -> None` — parse por texto (formato fixo de 4 linhas, indentação 2/4 espaços — copia o formato exato do sitemap real): se `<loc>…/{slug}</loc>` existe, substitui o `<lastmod>` dessa entrada; senão insere a entrada nova antes de `</urlset>` (changefreq monthly, priority 0.8). Idempotente.

- [ ] **Step 4 — Verde + suite.** **Step 5 — Commit** `feat(publicador): render determinista do artigo + sitemap idempotente`

---

### F3.4: Passagem do publicador (drain/ensaio, git, wrangler) + job

**Files:** Modify `checkal/app/publicador.py` (parte 2), `checkal/manage.py` (`_JOBS`); Test `checkal/tests/test_publicador.py`.

- [ ] **Step 1 — Testes primeiro** (sem rede/git reais — o executor de comandos é injetável):

```python
def test_correr_em_modo_teste_nao_drena_nem_executa(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    # seed: item artigo_seo aprovado (via fila.aprovar com token)
    chamadas = []
    rel = publicador.correr(site_dir=tmp_path_site_fake, ensaio_dir=tmp_path / "ensaio",
                            executar=lambda cmd, **kw: chamadas.append(cmd))
    assert rel["modo"] == "ensaio"
    assert chamadas == []                                  # zero git/wrangler
    # item CONTINUA aprovado (não foi drenado nem marcado feito):
    ...
    # e o HTML de ensaio existe:
    assert (tmp_path / "ensaio" / "regulamentos-al-porto.html").exists()


def test_correr_live_publica_artigo_e_fecha_post(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    # seed: 1 artigo aprovado + 1 post_grupo aprovado
    chamadas = []
    rel = publicador.correr(site_dir=site_fake, ensaio_dir=..., executar=fake_exec)
    # site_fake/{slug}.html escrito; sitemap atualizado;
    # sequência de comandos contém git add/commit/push e wrangler pages deploy
    # com a validação de «Uploading Functions bundle» (fake_exec devolve stdout com a linha);
    # post_grupo ficou 'feito' sem nenhum ficheiro escrito;
    # artigo ficou 'feito'.
    ...


def test_correr_live_auto_aprova_sob_flag(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "AUTO_PUBLICAR_ARTIGO_SEO", True)
    # seed: artigo PENDENTE com linter_ok ⇒ após correr(): auto_aprovado→publicado ('feito')
    ...


def test_correr_live_sem_flag_ignora_pendentes(bd, ...):
    # pendente fica pendente — só o gate humano decide
    ...


def test_deploy_falha_marca_falhado_com_backoff(bd, ...):
    # fake_exec levanta CalledProcessError no wrangler ⇒ item 'falhado', tentativas=1
    ...
```

(Corpos completos com os seeds via `fila.enfileirar`+`gerar_token`+`aprovar` — padrão dos testes do gate.)

- [ ] **Step 2 — Ver falhar.** **Step 3 — Implementar:**

`publicador.correr(site_dir=Path("/home/diogo/checkal-polaris/site"), ensaio_dir=Path(".../checkal/data/publicador-ensaio"), executar=None) -> dict`:

1. `executar` default = wrapper de `subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=…)` — injetável nos testes.
2. **Modo ensaio** (`config.CHECKAL_MODO_TESTE`): SELECT read-only dos itens `aprovado`/`auto_aprovado`-elegíveis (SEM drain, SEM lease), renderiza cada artigo para `ensaio_dir/{slug}.html`, valida sitemap em memória, devolve relatório `{"modo": "ensaio", "artigos": [...], "posts": N}`. Nada de git/wrangler/escrita no site_dir.
3. **Modo live**: (a) pré-passo: se `config.AUTO_PUBLICAR_ARTIGO_SEO`, `fila.auto_aprovar` em cada `artigo_seo` pendente com `linter_ok` (dentro de `sessao_governacao`); (b) `fila.drain(s, "publicador", tipos=("artigo_seo", "post_grupo"), cap=config.PUBLICADOR_CAP_PASSAGEM, incluir_auto_aprovado=True, processador=_processar)`; (c) `_processar(item)`: `post_grupo` ⇒ return (no-op ⇒ drain marca feito); `artigo_seo` ⇒ carrega o artigo do `EventoAgente.payload` (ref_id), `render_artigo`, escreve `site_dir/{slug}.html`, `atualizar_sitemap`, e UMA publicação por passagem no fim? — NÃO: mantém simples e robusto: git add/commit/push + deploy POR ITEM (idempotente por slug: overwrite determinista tolera re-serviço após lease expirado). Comandos exatos:
   - `git -C {site_dir} add {slug}.html sitemap.xml` · `git -C {site_dir} commit -m "artigo: /{slug} (publicador)"` · `git -C {site_dir} push origin main`
   - staging: `rm -rf {site_dir.parent}/stage && mkdir -p stage/dist` + `rsync -a --exclude='.git' --exclude='.wrangler' --exclude='*.md' --exclude='tools' --exclude='functions' {site_dir}/ stage/dist/` + `cp -r {site_dir}/functions stage/functions` + `npx --yes wrangler@4.111.0 pages deploy dist --project-name checkal --branch main` com `cwd=stage` (versão PINADA — o npx sem pin flutua)
   - valida `"Uploading Functions bundle"` no stdout do wrangler; ausente ⇒ `raise RuntimeError` (⇒ backoff do drain).
4. Devolve relatório dict; `manage.py`: `_JOBS["publicador"] = _publicador` com `def _publicador(): from app import publicador; import json; print(json.dumps(publicador.correr(), ensure_ascii=False, default=str))` (padrão dos jobs legados; atualiza o docstring do topo — linha dos jobs).

- [ ] **Step 4 — Verde + suite completa.** **Step 5 — Commit** `feat(publicador): passagem ensaio/live com drain filtrado, git+wrangler pinado, job manage.py`

---

### F3.5: Timer + instalador + README + HANDOFF fase 3

**Files:** Create `deploy/polaris/units/checkal-cron-publicador.timer`; Modify `deploy/polaris/instalar.sh`, `site/README.md` (passo 5, linha 62 — é repo git PRÓPRIO: commit separado lá); Create `docs/superpowers/plans/2026-07-19-fase3-HANDOFF.md`.

- [ ] **Step 1 — Timer** (padrão exato de `checkal-cron-dre.timer` da árvore units/ — sem comentários):

```ini
[Unit]
Description=CheckAL cron publicador (15 em 15 min)
[Timer]
OnCalendar=*:0/15
RandomizedDelaySec=60
Persistent=true
Unit=checkal-cron@publicador.service
[Install]
WantedBy=timers.target
```

(Confere o formato real de um timer vizinho e espelha — incl. se têm linhas em branco.)

- [ ] **Step 2 — `instalar.sh`:** acrescenta `checkal-cron-publicador.timer` à linha dos crons deterministas.
- [ ] **Step 3 — README do site** (repo aninhado!): substitui a linha 62 `5. **Redeploys**: npx wrangler pages deploy site …` por `5. **Redeploys**: repete SEMPRE o passo 2 (staging + functions como irmã) — nunca deployar site/ diretamente. O PUBLICADOR do CheckAL automatiza exatamente esse pipeline.`; commit NO repo site/: `git -C site add README.md && git -C site commit -m "README: passo 5 alinhado com o pipeline de staging (era contraditório)"` — SEM push (o push é do publicador/dono).
- [ ] **Step 4 — HANDOFF fase 3:**

```markdown
# Fase 3 — passos manuais do dono

1. Instalar o timer: `sudo /home/diogo/checkal-polaris/deploy/polaris/instalar.sh`
   (o publicador corre 15/15 min; em MODO_TESTE=True é ensaio read-only — renderiza
   para checkal/data/publicador-ensaio/ e NÃO toca em git/Cloudflare)
2. (Opcional, recomendado p/ robustez headless) Token Cloudflare de âmbito mínimo
   (Pages:Edit no projeto checkal) no agente.env:
   `CLOUDFLARE_API_TOKEN=...` e `CLOUDFLARE_ACCOUNT_ID=8425658e8ce8ed9cb42a39a6de2e1105`
   — HOJE o wrangler autentica pelo teu OAuth login (funciona, mas pode expirar).
3. Ir live: quando quiseres publicação real, `CHECKAL_MODO_TESTE=false` no agente.env
   ⚠️ isto abre TODOS os seams live-gated do CheckAL (Stripe, Telegram, digest LLM…),
   não só o publicador — decisão de go-live global, não do publicador.
4. Autonomia gradual (mais tarde, com historial): `CHECKAL_AUTO_PUBLICAR_ARTIGO_SEO=true`
   — artigos com linter_ok passam a publicar sem clique. post_grupo é sempre manual.
5. Primeiro artigo real: aprova no portão (link do digest) → próxima passagem publica →
   confirma em https://checkal.pages.dev/{slug} e no sitemap.
```

- [ ] **Step 5 — Validar** (`bash -n`, `systemd-analyze verify` do timer). **Step 6 — Commits** (repo principal: timer+instalar.sh+HANDOFF; repo site: README).

---

### F3.6: Verificação final da fase 3

- [ ] Suite completa verde; ensaio ponta-a-ponta REAL: seed de artigo na BD real? NÃO — usa BD temporária: enfileira artigo → aprova via `fila.aprovar` → `publicador.correr()` com `site_dir` clonado para /tmp (cópia do site real) e MODO_TESTE=False com `executar` fake → HTML final inspecionado à mão (blocos todos presentes) + sitemap; depois ensaio com MODO_TESTE=True contra a BD real (fila vazia ⇒ relatório limpo). Revisão final de conjunto (subagente fable) sobre o range da fase 3 + atualização de `ESTADO-DO-PROJETO.md` se o padrão da casa o pedir (verifica o cabeçalho).
