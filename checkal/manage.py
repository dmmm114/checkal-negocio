"""CLI de operação do CheckAL — invocado pelos systemd timers (um job por invocação).

    python manage.py <job>
    jobs: varrimento | dre | dunning | suporte | backup | token | publicador

Cada job chama o respetivo cron (`app.crons` / `app.faturacao.cron_toconline`), que já
compõem os seams **live-gated** a partir do ambiente (nada envia/liga sem credenciais) e
correm sob o dead-man switch (`com_healthcheck`). Código de saída ≠ 0 se o job levantar
— o systemd/Healthchecks avisa o dono.

FASE D (prompt-mestre §3.6) — subcomandos do ENXAME DE AGENTES, a allow-list exata
que cada agente single-shot usa (sem shell livre, sem SQL cru):

    MAESTRO    maestro-run --modo <governanca|digest> · maestro-metricas ·
               maestro-saude · maestro-fila · maestro-escalacoes ·
               maestro-digest --ficheiro F · maestro-escalar --sev S --msg M ·
               maestro-retry --agente A --backoff N · maestro-gate-token --fila-id N
    ANGARIADOR angariador {detetar | lint --stdin | enfileirar --tipo T --stdin | estado}
    GESTOR     gestor {onboarding-tarefas | relatorio-mensal-compor |
               dunning-estado | suporte-triar --stdin}
    SENTINELA  sentinela verificar
    EDITOR     editor {plano | lint --stdin | enfileirar --tipo artigo_seo --stdin | estado}
    COMUNICADOR comunicador {lint --stdin | enfileirar --tipo post_grupo --stdin | estado}
               (+ editor plano, leitura)

Regras duras (código, não disciplina): leituras abrem a BD em READ-ONLY
(PRAGMA query_only); escritas usam a sessão de governação (`app.swarm.fila.
sessao_governacao`), que RECUSA tocar `clientes`/`alertas`/`registos`/`faturas`/
`leads`; nenhum subcomando envia/publica/cobra — tudo cai na fila de revisão,
atrás do gate 1-clique do dono. O `maestro-run` é o único runner que encadeia
executores (SEQUENCIAL, nunca paralelo — RAM do Polaris) e SÓ invoca o passo LLM
com o gate DPA aberto, sem PAUSA_LLM e sem o teto diário atingido.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import app.config as config


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _print_json(dados: dict) -> None:
    print(json.dumps(dados, ensure_ascii=False, default=str))


# ==========================================================================
#  Jobs legados (arg único) — INALTERADOS
# ==========================================================================
def _varrimento() -> None:
    from app.crons import cron_varrimento

    cron_varrimento(config.concelhos_todos())


def _dre() -> None:
    from app.crons import cron_dre

    cron_dre()


def _dunning() -> None:
    from app.crons import cron_dunning

    cron_dunning()


def _suporte() -> None:
    from app.crons import cron_suporte

    cron_suporte()


def _backup() -> None:
    from app.crons import cron_backup

    cron_backup()


def _token() -> None:
    # Renovação do token OAuth do TOConline (mantém a cadeia viva; ~a cada 3-4h).
    from app.faturacao.cron_toconline import main as token_main

    rc = token_main([])
    if rc:
        raise SystemExit(rc)


def _publicador() -> None:
    # Passagem do PUBLICADOR (fase 3, F3.4): ensaio read-only sob MODO_TESTE;
    # em live drena artigo_seo/post_grupo aprovados, publica (git+wrangler) e
    # imprime o relatório JSON — mesmo padrão dos outros jobs desta tabela.
    from app import publicador

    _print_json(publicador.correr())


_JOBS = {
    "varrimento": _varrimento,  # 2×/semana (seg, qui 03:00)
    "dre": _dre,                # diário (07:00)
    "dunning": _dunning,        # diário (09:00)
    "suporte": _suporte,        # cada 15 min
    "backup": _backup,          # noturno (02:00)
    "token": _token,            # cada ~3h (TOConline OAuth)
    "publicador": _publicador,  # cada 15 min (drain artigo_seo/post_grupo aprovados)
}


# ==========================================================================
#  Sessões — leitura READ-ONLY vs escrita estreita de governação
# ==========================================================================
_ENGINES_COM_RESET: "weakref.WeakSet" = None  # inicializado no primeiro uso


def _sessao_leitura():
    """Sessão de LEITURA: em SQLite ativa `PRAGMA query_only=ON` (escrita rebenta).

    É a ligação que os subcomandos `maestro-*` de leitura usam — devolvem JSON
    agregado e, por construção, não conseguem escrever nada. Ao devolver a
    ligação ao pool, o PRAGMA é limpo (checkin) para não envenenar as sessões
    de escrita estreita que a seguir reutilizem a mesma ligação.
    """
    import weakref

    from sqlalchemy import event as sa_event, text

    import app.db as db

    global _ENGINES_COM_RESET
    if _ENGINES_COM_RESET is None:
        _ENGINES_COM_RESET = weakref.WeakSet()

    s = db.SessionLocal()
    if db.engine.url.get_backend_name() == "sqlite":
        if db.engine not in _ENGINES_COM_RESET:
            @sa_event.listens_for(db.engine, "checkin")
            def _reset_query_only(dbapi_conn, record):  # noqa: ANN001
                try:
                    dbapi_conn.execute("PRAGMA query_only=OFF")
                except Exception:  # noqa: BLE001 — ligação já fechada; nada a limpar
                    pass

            _ENGINES_COM_RESET.add(db.engine)
        s.execute(text("PRAGMA query_only=ON"))
    return s


def _mes_label(mes_iso: str) -> str:
    """"2026-07" → "julho de 2026" (rótulo humano do relatório mensal)."""
    nomes = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro")
    ano, mes = mes_iso.split("-")
    return f"{nomes[int(mes) - 1]} de {ano}"


# ==========================================================================
#  MAESTRO — leituras (JSON agregado; NUNCA campos pessoais)
# ==========================================================================
def _cmd_maestro_metricas(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from app.campanhas.gatilhos import CANAL_GATILHO

    agora = _agora()
    s = _sessao_leitura()
    try:
        por_estado = dict(
            s.query(models.Cliente.estado, __import__("sqlalchemy").func.count())
            .group_by(models.Cliente.estado).all()
        )
        ativos = s.query(models.Cliente).filter(models.Cliente.estado == "ativo").all()
        mrr_cents = 0
        for c in ativos:
            plano = config.PLANOS.get(c.plano or "", None)
            if plano:
                mrr_cents += round(plano["preco"] * 100 / plano["meses"])

        leads = dict(
            s.query(models.Lead.estado, __import__("sqlalchemy").func.count())
            .group_by(models.Lead.estado).all()
        )

        janela = agora - timedelta(hours=config.CAMPANHA_JANELA_H)
        frescos = (
            s.query(models.EventoRegisto)
            .filter(models.EventoRegisto.detetado_em >= janela).count()
        )
        usados = {
            oid for (oid,) in s.query(models.Alerta.origem_id)
            .filter(models.Alerta.canal == CANAL_GATILHO,
                    models.Alerta.origem == "eventos_registo",
                    models.Alerta.origem_id.isnot(None))
        }
        backlog = sum(
            1 for (eid,) in s.query(models.EventoRegisto.id) if eid not in usados
        )

        alertas_7d = (
            s.query(models.Alerta)
            .filter(models.Alerta.enviado_em >= agora - timedelta(days=7)).count()
        )
        alertas_30d = (
            s.query(models.Alerta)
            .filter(models.Alerta.enviado_em >= agora - timedelta(days=30)).count()
        )
        requer_atencao = (
            s.query(models.Alerta)
            .filter(models.Alerta.canal == "tarefa_dono").count()
        )
        fila_pendentes = (
            s.query(ms.RevisaoItem).filter(ms.RevisaoItem.estado == "pendente").count()
        )
    finally:
        s.rollback()
        s.close()

    _print_json({
        "mrr_cents": mrr_cents,
        "clientes": {
            "ativos": por_estado.get("ativo", 0),
            "em_dunning": por_estado.get("em_dunning", 0),
            "cancelados": por_estado.get("cancelado", 0),
        },
        "leads": {
            "pendente": leads.get("pendente", 0),
            "confirmado": leads.get("confirmado", 0),
            "removido": leads.get("removido", 0),
        },
        "gatilhos": {"frescos_na_janela": frescos, "backlog_por_usar": backlog},
        "alertas": {"enviados_7d": alertas_7d, "enviados_30d": alertas_30d},
        "onboarding_requer_atencao": requer_atencao,
        "fila_pendentes": fila_pendentes,
        "metas": {"meta1_clientes": 490, "meta2_clientes": 1630},
    })
    return 0


def _cmd_maestro_saude(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from app.swarm import tetos

    agora = _agora()
    s = _sessao_leitura()
    try:
        ultimo = (
            s.query(models.Varrimento)
            .filter(models.Varrimento.concluido_em.isnot(None))
            .order_by(models.Varrimento.concluido_em.desc()).first()
        )
        if ultimo is not None and ultimo.concluido_em is not None:
            fim = ultimo.concluido_em
            if fim.tzinfo is None:
                fim = fim.replace(tzinfo=timezone.utc)
            idade_dias = (agora - fim).total_seconds() / 86400
            varrimento = {
                "concluido_em": ultimo.concluido_em, "estado": ultimo.estado,
                "idade_dias": round(idade_dias, 2),
                "sla_ok": idade_dias <= config.CADENCIA_NACIONAL_DIAS + 1,
            }
        else:
            varrimento = {"concluido_em": None, "estado": None,
                          "idade_dias": None, "sla_ok": False}

        executores = {}
        for agente in ("angariador", "gestor", "sentinela", "maestro", "editor", "comunicador"):
            ex = (
                s.query(ms.AgenteExecucao)
                .filter(ms.AgenteExecucao.agente == agente)
                .order_by(ms.AgenteExecucao.iniciado_em.desc()).first()
            )
            executores[agente] = (
                None if ex is None else
                {"estado": ex.estado, "exit_code": ex.exit_code,
                 "iniciado_em": ex.iniciado_em, "retry_pedido": ex.retry_pedido}
            )

        escalacoes_abertas = (
            s.query(ms.Escalacao).filter(ms.Escalacao.estado == "aberta").count()
        )
        achados_por_escalar = (
            s.query(ms.EventoAgente)
            .filter(ms.EventoAgente.tipo == "achado",
                    ms.EventoAgente.escalado.is_(False)).count()
        )
    finally:
        s.rollback()
        s.close()

    _print_json({
        "varrimento": varrimento,
        "executores": executores,
        "escalacoes_abertas": escalacoes_abertas,
        "achados_por_escalar": achados_por_escalar,
        "healthchecks": {"ativo": config.healthchecks_ativo()},
        "gates": {
            "parecer_rgpd_ok": config.CHECKAL_PARECER_RGPD_OK,
            "modo_teste": config.CHECKAL_MODO_TESTE,
            "cold_smtp": config.cold_smtp_ativo(),
            "dpa_ok": config.CHECKAL_ANTHROPIC_DPA_OK,
            "pausa_llm": tetos.pausa_llm_ativa(),
            "pode_enviar_frio": config.pode_enviar_frio_global(),
        },
    })
    return 0


def _cmd_maestro_fila(args) -> int:
    import app.models_swarm as ms

    s = _sessao_leitura()
    try:
        pendentes = [
            {
                "id": i.id, "tipo": i.tipo, "risco": i.risco,
                "camada_risco": i.camada_risco, "linter_ok": i.linter_ok,
                "agente_origem": i.agente_origem, "resumo": i.resumo,
                "criado_em": i.criado_em, "tem_token": bool(i.token_aprovacao),
            }
            for i in s.query(ms.RevisaoItem)
            .filter(ms.RevisaoItem.estado == "pendente")
            .order_by(ms.RevisaoItem.camada_risco.desc(), ms.RevisaoItem.criado_em)
        ]
    finally:
        s.rollback()
        s.close()
    _print_json({"pendentes": pendentes})
    return 0


def _cmd_maestro_escalacoes(args) -> int:
    import app.models_swarm as ms

    s = _sessao_leitura()
    try:
        abertas = [
            {"id": e.id, "agente": e.agente, "severidade": e.severidade,
             "mensagem": e.mensagem, "criado_em": e.criado_em}
            for e in s.query(ms.Escalacao)
            .filter(ms.Escalacao.estado == "aberta")
            .order_by(ms.Escalacao.criado_em)
        ]
    finally:
        s.rollback()
        s.close()
    _print_json({"escalacoes": abertas})
    return 0


# ==========================================================================
#  MAESTRO — escritas estreitas (só tabelas de governação)
# ==========================================================================
def _cmd_maestro_digest(args) -> int:
    from pathlib import Path

    import app.models_swarm as ms
    import app.suporte as suporte
    from app.swarm import fila

    conteudo = json.loads(Path(args.ficheiro).read_text(encoding="utf-8"))
    corpo_md = conteudo.get("corpo_md")
    if not corpo_md:
        sys.stderr.write("maestro-digest: ficheiro sem corpo_md\n")
        return 2

    enviado = False
    with fila.sessao_governacao() as s:
        digest = ms.Digest(
            dia=_agora().date(), corpo_md=corpo_md,
            metricas_json=conteudo.get("metricas_json"), criado_em=_agora(),
        )
        s.add(digest)
        s.flush()
        # Único envio outward permitido ao MAESTRO: o Telegram do DONO — e mesmo
        # esse é LIVE-GATED (obter_escalador → None sob modo teste/sem credenciais).
        escalador = suporte.obter_escalador()
        if escalador is not None:
            escalador(assunto="Digest CheckAL", corpo=corpo_md)
            digest.enviado_em = _agora()
            enviado = True
        digest_id = digest.id

    _print_json({"digest_id": digest_id, "enviado": enviado})
    return 0


def _cmd_maestro_escalar(args) -> int:
    from app.swarm import fila, tetos

    with fila.sessao_governacao() as s:
        linha = tetos.escalar(
            s, severidade=args.sev, agente="maestro", mensagem=args.msg,
        )
        escalacao_id = linha.id
    _print_json({"escalacao_id": escalacao_id})
    return 0


def _cmd_maestro_retry(args) -> int:
    import app.models_swarm as ms
    from app.swarm import fila

    with fila.sessao_governacao() as s:
        ex = (
            s.query(ms.AgenteExecucao)
            .filter(ms.AgenteExecucao.agente == args.agente)
            .order_by(ms.AgenteExecucao.iniciado_em.desc()).first()
        )
        if ex is None:
            ex = ms.AgenteExecucao(
                agente=args.agente, iniciado_em=_agora(), estado="falhou",
            )
            s.add(ex)
        ex.retry_pedido = True
        ex.backoff_s = args.backoff
        s.flush()
        execucao_id = ex.id
    _print_json({"execucao_id": execucao_id, "retry_pedido": True, "backoff_s": args.backoff})
    return 0


def _cmd_maestro_gate_token(args) -> int:
    from app.swarm import fila

    with fila.sessao_governacao() as s:
        token = fila.gerar_token(s, args.fila_id)
    saida = {"fila_id": args.fila_id, "token": token}
    if config.GATE_BASE_URL:
        saida["url"] = (
            f"{config.GATE_BASE_URL.rstrip('/')}/gate/{args.fila_id}?token={token}"
        )
    _print_json(saida)
    return 0


# ==========================================================================
#  MAESTRO — runner determinista (sequencial; LLM gated)
# ==========================================================================
def _lancador_padrao():
    """Compõe o lançador de executores (wrapper), ou ``None`` (LIVE-GATED).

    Sob `CHECKAL_MODO_TESTE`, ou sem o wrapper instalado, devolve ``None`` —
    nada é lançado. Em produção corre `correr-agente.sh <agente>` por subprocess,
    SEMPRE em sequência (o chamador itera; nunca paralelo — RAM do Polaris).
    """
    import os
    import shutil

    if config.CHECKAL_MODO_TESTE:
        return None
    wrapper = os.environ.get("CHECKAL_AGENTE_WRAPPER", "/opt/checkal/bin/correr-agente.sh")
    if not (shutil.which(wrapper) or __import__("pathlib").Path(wrapper).is_file()):
        return None

    def _lancar(agente: str) -> int:
        import subprocess

        return subprocess.run([wrapper, agente], check=False).returncode

    return _lancar


def maestro_run(modo: str, *, lancador=None, lancador_llm=None) -> dict:
    """Runner determinista do MAESTRO (chamado por `maestro-run --modo <m>`).

    Por esta ordem: (1) re-executa EM SEQUÊNCIA os executores anotados com
    `retry_pedido` (a anotação do MAESTRO-LLM via `maestro-retry`), registando
    cada corrida em `agente_execucoes`; (2) SÓ DEPOIS invoca o passo LLM do
    MAESTRO — e apenas se: gate DPA aberto (`agente_llm_pode_arrancar`), sem
    `PAUSA_LLM`, e teto diário não atingido (senão: cria a pausa e ESCALA).
    O LLM nunca faz spawn — quem lança processos é este runner.

    `lancador(agente)->exit_code` e `lancador_llm(modo)->usage_json|None` são
    seams injetáveis (testes); os defaults são LIVE-GATED (None sob modo teste).
    """
    import app.models_swarm as ms
    from app.swarm import fila, tetos

    resultado: dict = {
        "modo": modo, "executores_corridos": [],
        "llm_invocado": False, "motivo_llm_skip": None,
    }

    if lancador is None:
        lancador = _lancador_padrao()

    # (1) Executores com retry pedido — SEQUENCIAL, nunca paralelo.
    if lancador is not None:
        with fila.sessao_governacao() as s:
            flagged = (
                s.query(ms.AgenteExecucao)
                .filter(ms.AgenteExecucao.retry_pedido.is_(True))
                .order_by(ms.AgenteExecucao.id).all()
            )
            for ex in flagged:
                inicio = _agora()
                exit_code = lancador(ex.agente)
                s.add(
                    ms.AgenteExecucao(
                        agente=ex.agente, execucao_id=str(uuid.uuid4()), modo=modo,
                        iniciado_em=inicio, terminado_em=_agora(),
                        estado="ok" if exit_code == 0 else "falhou",
                        exit_code=exit_code,
                    )
                )
                ex.retry_pedido = False
                resultado["executores_corridos"].append(ex.agente)

    # (2) Passo LLM do MAESTRO — atrás dos gates, por ordem de precedência.
    if not config.agente_llm_pode_arrancar():
        resultado["motivo_llm_skip"] = "dpa_fechado"
        return resultado
    if tetos.pausa_llm_ativa():
        resultado["motivo_llm_skip"] = "pausa_llm"
        return resultado

    with fila.sessao_governacao() as s:
        if tetos.teto_atingido(s):
            tetos.flag_pausa_llm()
            tetos.escalar(
                s, severidade="critica", agente="maestro",
                mensagem="Teto diário de custo LLM atingido — PAUSA_LLM criada; "
                         "os crons deterministas continuam.",
            )
            resultado["motivo_llm_skip"] = "teto_diario"
            return resultado

    if lancador_llm is None:
        # Default LIVE-GATED: sob modo teste (ou sem CLI instalado) não há LLM.
        resultado["motivo_llm_skip"] = "live_gated"
        return resultado

    usage = lancador_llm(modo)
    resultado["llm_invocado"] = True
    with fila.sessao_governacao() as s:
        if isinstance(usage, dict) and usage:
            tetos.registar_custo(s, "maestro", usage)
            tetos.verificar_e_pausar(s)
        s.add(
            ms.AgenteExecucao(
                agente="maestro", execucao_id=str(uuid.uuid4()), modo=modo,
                iniciado_em=_agora(), terminado_em=_agora(), estado="ok", exit_code=0,
            )
        )
    return resultado


def _cmd_maestro_run(args) -> int:
    _print_json(maestro_run(args.modo))
    return 0


# ==========================================================================
#  ANGARIADOR
# ==========================================================================
_TIPOS_CONTEUDO = {
    "cold_draft": ("cold_email", "alto"),
    "cold_sequencia": ("cold_email", "alto"),
    "pagina_gatilho": ("pagina_publica", "alto"),
    "pilar_seo": ("pagina_publica", "alto"),
    "one_pager": ("pagina_publica", "alto"),
}


def _peca_para_tipo(tipo: str, texto: str, *, url_fonte=None, excerto=None):
    from app.compliance import linter

    canal = {
        "cold_draft": linter.Canal.COLD,
        "cold_sequencia": linter.Canal.COLD,
        "pagina_gatilho": linter.Canal.PAGINA_PUBLICA,
        "pilar_seo": linter.Canal.PAGINA_PUBLICA,
        "one_pager": linter.Canal.ONE_PAGER,
    }[tipo]
    return linter.PecaOutward(
        texto=texto, canal=canal, url_fonte=url_fonte, excerto=excerto,
        gerado_por_ia=True,
        tem_optout_carimbado=(canal is linter.Canal.COLD),  # o seam de cold carimba
    )


def _cmd_angariador_detetar(args) -> int:
    import app.db as db
    import app.models as models
    import app.models_swarm as ms
    from app.campanhas import motor
    from app.compliance import linter
    from app.swarm import fila, tetos

    execucao_id = str(uuid.uuid4())
    lista_dgc, dgc_carregada = fila.carregar_lista_dgc()
    dgc_esta_ok = fila.dgc_ok(lista_dgc, carregada_em=dgc_carregada)

    saida: dict = {"execucao_id": execucao_id, "dgc_ok": dgc_esta_ok}

    with db.get_session() as s:
        log_optout = [linha.email for linha in s.query(models.OptOut)]
        # Canal de CARTAS parqueado (§5): não gerar PDF — só contar.
        res = motor.correr_campanhas(
            s, gerar_cartas=lambda prospetos, **kw: None,
            lista_dgc=lista_dgc, log_optout=log_optout,
        )

        if not dgc_esta_ok:
            # RT-DGC: lista vazia/estagnada ⇒ o ANGARIADOR escala (fail-closed:
            # o envio já recusaria; a escalação torna o estado visível ao dono).
            tetos.escalar(
                s, severidade="alta", agente="angariador", execucao_id=execucao_id,
                mensagem="Lista de oposição DGC vazia/estagnada — envio frio "
                         "tratado como se todos estivessem opostos (recusa).",
            )

        if res.gatilhos == 0 and not res.pendentes_parecer:
            saida.update({"noop": True, "gatilhos": 0, "pendentes": 0,
                          "descartados": res.descartados, "drafts": []})
            _print_json(saida)
            return 0

        campanha = ms.Campanha(
            canal="cold_email", execucao_id=execucao_id,
            n_gatilhos=res.gatilhos,
            n_elegiveis=len(res.pendentes_parecer) + len(res.enviados),
            n_enviados=len(res.enviados),
            n_pendentes=len(res.pendentes_parecer),
            n_descartados=res.descartados,
            criado_em=_agora(),
        )
        s.add(campanha)
        s.flush()

        drafts_json = []
        vistos: set[tuple[str, str]] = set()
        for draft in res.pendentes_parecer:
            registo = (
                s.query(models.Registo)
                .filter(models.Registo.email == draft.para)
                .order_by(models.Registo.nr_registo).first()
            )
            if registo is None or not registo.nif:
                tetos.escalar(
                    s, severidade="media", agente="angariador",
                    execucao_id=execucao_id,
                    mensagem=f"Draft sem NIF resolúvel para {draft.para!r} — "
                             "peça não persistida.",
                )
                continue
            chave = (registo.nif, "d0")
            if chave in vistos:
                continue
            vistos.add(chave)

            resultado_lint = linter.lint(
                linter.PecaOutward(
                    texto=draft.html, canal=linter.Canal.COLD,
                    tem_optout_carimbado=True,
                )
            )
            peca = ms.CampanhaPeca(
                campanha_id=campanha.id, nif=registo.nif,
                email_generico=draft.para, nome_coletiva=registo.titular_nome,
                nr_registo=registo.nr_registo, concelho=registo.concelho,
                passo="d0", assunto=draft.assunto, corpo_html=draft.html,
                proveniencia=draft.proveniencia, razao=draft.razao,
                linter_ok=resultado_lint.aprovado, criado_em=_agora(),
            )
            s.add(peca)
            s.flush()

            revisao_id = None
            if resultado_lint.aprovado:
                item = fila.enfileirar(
                    s, tipo="cold_email", risco="alto", agente_origem="angariador",
                    ref_tipo="campanha_peca", ref_id=str(peca.id),
                    resumo=f"cold d0 → {draft.para} ({registo.concelho})",
                    peca=linter.PecaOutward(
                        texto=draft.html, canal=linter.Canal.COLD,
                        tem_optout_carimbado=True,
                    ),
                )
                revisao_id = item.id

            drafts_json.append({
                "peca_id": peca.id, "revisao_id": revisao_id,
                "nif": registo.nif, "email": draft.para,
                "nome_coletiva": registo.titular_nome,
                "nr_registo": registo.nr_registo, "concelho": registo.concelho,
                "assunto": draft.assunto, "corpo_html": draft.html,
                "razao": draft.razao, "proveniencia": draft.proveniencia,
                "linter_ok": resultado_lint.aprovado,
                "violacoes": [
                    {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
                    for v in resultado_lint.violacoes
                ],
            })

        saida.update({
            "noop": False,
            "gatilhos": res.gatilhos,
            "pendentes": len(res.pendentes_parecer),
            "descartados": res.descartados,
            "optouts_suprimidos": len(res.optouts),
            "cartas_parqueadas": res.cartas,
            "drafts": drafts_json,
        })

    _print_json(saida)
    return 0


def _cmd_angariador_lint(args) -> int:
    texto = sys.stdin.read()
    peca = _peca_para_tipo(args.tipo, texto, url_fonte=args.fonte, excerto=args.excerto)
    from app.compliance import linter

    r = linter.lint(peca)
    _print_json({
        "aprovado": r.aprovado, "versao": r.versao,
        "violacoes": [
            {"regra": v.regra, "razao": v.razao, "trecho": v.trecho}
            for v in r.violacoes
        ],
    })
    return 0


def _cmd_angariador_enfileirar(args) -> int:
    import app.models_swarm as ms
    from app.swarm import fila, tetos

    texto = sys.stdin.read() if args.stdin else ""

    if args.escalar:
        with fila.sessao_governacao() as s:
            tetos.escalar(
                s, severidade="media", agente="angariador",
                mensagem=args.motivo or "escalação sem motivo explícito",
            )
        _print_json({"escalado": True})
        return 0

    peca = _peca_para_tipo(args.tipo, texto, url_fonte=args.fonte, excerto=args.excerto)
    try:
        with fila.sessao_governacao() as s:
            if args.peca_id is not None:
                # Reescrita de um cold_draft: SÓ o corpo (assunto/CTA imutáveis — RT).
                registo_peca = s.get(ms.CampanhaPeca, args.peca_id)
                if registo_peca is None:
                    sys.stderr.write(f"peça {args.peca_id} inexistente\n")
                    return 2
                item = fila.enfileirar(
                    s, tipo=_TIPOS_CONTEUDO[args.tipo][0],
                    risco=_TIPOS_CONTEUDO[args.tipo][1],
                    agente_origem="angariador",
                    ref_tipo="campanha_peca", ref_id=str(registo_peca.id),
                    resumo=f"cold {registo_peca.passo} → {registo_peca.email_generico}",
                    peca=peca,
                )
                registo_peca.corpo_html = texto
                registo_peca.linter_ok = True
                ref = {"ref_tipo": "campanha_peca", "ref_id": str(registo_peca.id)}
            else:
                evento = ms.EventoAgente(
                    agente="angariador", tipo="conteudo_proposto",
                    mensagem=f"conteúdo proposto ({args.tipo})",
                    payload={"tipo": args.tipo, "corpo_texto": texto},
                    criado_em=_agora(),
                )
                s.add(evento)
                s.flush()
                item = fila.enfileirar(
                    s, tipo=args.tipo,
                    risco=_TIPOS_CONTEUDO[args.tipo][1],
                    agente_origem="angariador",
                    ref_tipo="evento_agente", ref_id=str(evento.id),
                    resumo=f"{args.tipo} proposto",
                    peca=peca,
                )
                ref = {"ref_tipo": "evento_agente", "ref_id": str(evento.id)}
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

    _print_json({"aprovado": True, "revisao_id": item_id, **ref})
    return 0


def _cmd_angariador_estado(args) -> int:
    import app.models_swarm as ms
    from sqlalchemy import func

    s = _sessao_leitura()
    try:
        revisao = dict(
            s.query(ms.RevisaoItem.estado, func.count())
            .filter(ms.RevisaoItem.agente_origem == "angariador")
            .group_by(ms.RevisaoItem.estado).all()
        )
        pecas = dict(
            s.query(ms.CampanhaPeca.estado, func.count())
            .group_by(ms.CampanhaPeca.estado).all()
        )
        ultima = (
            s.query(ms.Campanha).order_by(ms.Campanha.id.desc()).first()
        )
    finally:
        s.rollback()
        s.close()
    _print_json({
        "revisao": revisao, "pecas": pecas,
        "ultima_campanha": None if ultima is None else
        {"id": ultima.id, "criado_em": ultima.criado_em,
         "n_pendentes": ultima.n_pendentes},
    })
    return 0


# ==========================================================================
#  GESTOR-DE-CLIENTE
# ==========================================================================
def _cmd_gestor_onboarding(args) -> int:
    import app.models as models
    from app.compliance import linter
    from app.swarm import fila

    if args.recomendar:
        texto = sys.stdin.read() if args.stdin else ""
        peca = linter.PecaOutward(
            texto=texto, canal=linter.Canal.NURTURE_TRANSACIONAL,
            gerado_por_ia=True, tem_optout_carimbado=True,  # nota interna ao dono
        )
        try:
            with fila.sessao_governacao() as s:
                item = fila.enfileirar(
                    s, tipo="onboarding_triagem", risco="baixo",
                    agente_origem="gestor", ref_tipo="alerta",
                    ref_id=str(args.alerta_id),
                    resumo=f"recomendação de onboarding (alerta {args.alerta_id})",
                    peca=peca,
                )
                item_id = item.id
        except fila.LinterReprovado as exc:
            _print_json({"aprovado": False, "violacoes": [
                {"regra": v.regra, "razao": v.razao} for v in exc.violacoes
            ]})
            return 1
        _print_json({"aprovado": True, "revisao_id": item_id})
        return 0

    s = _sessao_leitura()
    try:
        tarefas = [
            {"alerta_id": a.id, "cliente_id": a.cliente_id,
             "nr_registo": a.nr_registo, "conteudo": a.conteudo}
            for a in s.query(models.Alerta)
            .filter(models.Alerta.origem == "onboarding_tarefa",
                    models.Alerta.canal == "tarefa_dono")
            .order_by(models.Alerta.id)
        ]
    finally:
        s.rollback()
        s.close()
    _print_json({"tarefas": tarefas})
    return 0


def _cmd_gestor_relatorio(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from app.compliance import linter
    from app.emails import transacional
    from app.swarm import fila

    mes = args.mes or _agora().strftime("%Y-%m")
    label = _mes_label(mes)
    limite = args.limite

    enfileirados = 0
    saltados = 0
    with fila.sessao_governacao() as s:
        ativos = (
            s.query(models.Cliente)
            .filter(models.Cliente.estado == "ativo")
            .order_by(models.Cliente.id).all()
        )
        for cliente in ativos:
            if limite is not None and enfileirados >= limite:
                break
            ref_id = f"{cliente.id}:{mes}"
            existente = (
                s.query(ms.RevisaoItem)
                .filter(ms.RevisaoItem.ref_tipo == "relatorio_mensal",
                        ms.RevisaoItem.ref_id == ref_id).first()
            )
            if existente is not None:
                saltados += 1
                continue
            registos = list(cliente.registos or [])
            if not registos:
                saltados += 1
                continue
            registo = registos[0]

            ano, m = (int(x) for x in mes.split("-"))
            inicio_mes = date(ano, m, 1)
            concelhos = [r.concelho for r in registos if r.concelho]
            q = s.query(models.EventoRegulatorio).filter(
                models.EventoRegulatorio.publicado_em >= inicio_mes
            )
            eventos_mes = [
                e for e in q
                if not concelhos
                or any(c in (e.concelhos or []) for c in concelhos)
            ]
            n_analisadas = len(eventos_mes)
            n_relevantes = sum(1 for e in eventos_mes if e.triagem == "relevante")

            email = transacional.relatorio_mensal(
                mes=label,
                nome_al=registo.nome_alojamento or f"registo {registo.nr_registo}",
                nome=cliente.nome,
                resumo="Registo e seguro sob vigilância contínua este mês.",
                n_analisadas=n_analisadas, n_relevantes=n_relevantes,
                email_destinatario=cliente.email or "",
                divulgacao_ia=linter.DIVULGACAO_IA,
            )
            peca = linter.PecaOutward(
                texto=email.html, canal=linter.Canal.RELATORIO, gerado_por_ia=True,
            )
            evento = ms.EventoAgente(
                agente="gestor", tipo="conteudo_proposto",
                ref_tipo="relatorio_mensal", ref_id=ref_id,
                mensagem=f"relatório mensal {mes} (cliente {cliente.id})",
                payload={"assunto": email.assunto, "corpo_texto": email.texto,
                         "cliente_id": cliente.id, "mes": mes},
                criado_em=_agora(),
            )
            s.add(evento)
            fila.enfileirar(
                s, tipo="relatorio_mensal", risco="medio", agente_origem="gestor",
                ref_tipo="relatorio_mensal", ref_id=ref_id,
                resumo=f"relatório {mes} → cliente {cliente.id}",
                peca=peca,
            )
            enfileirados += 1

    _print_json({"mes": mes, "enfileirados": enfileirados, "saltados": saltados})
    return 0


# RT-suporte: temas que ESCALAM sempre, mesmo com confiança alta — estado de
# registo/seguro/regime legal na RESPOSTA. O disclaimer padrão é removido antes
# da varredura (senão "aconselhamento jurídico" auto-dispararia).
import re as _re

_RE_SUPORTE_SENSIVEL = _re.compile(
    r"estado\s+do\s+(?:teu\s+|seu\s+|vosso\s+)?registo|cancelad|caducad|suspens|"
    r"sem\s+seguro|seguro\s+(?:est[áa]|caducad\w*|expirad\w*|inv[áa]lid\w*)|"
    r"regime\s+legal|jur[íi]dic|\blei\b|"
    # "regulament" sozinho apanhava a descrição do produto ("vigiamos os
    # regulamentos municipais") — não é prescrição jurídica. Só escala o uso
    # PRESCRITIVO ("o regulamento(s) [qualificador] proíbe/obriga/exige/impede/
    # impõe", singular ou plural) — tolera até 4 tokens de qualificador entre o
    # substantivo e o verbo (revisão 19/07: adjacência estrita deixava escapar
    # "o regulamento DO PORTO proíbe" e os plurais); a descrição do produto
    # ("vigiamos os regulamentos municipais") continua a não escalar.
    r"regulamento\w*\s+(?:\S+\s+){0,4}?"
    r"(?:pro[íi]be|obriga|exige|impede|imp[õo]e|"
    r"pro[íi]bem|obrigam|exigem|impedem|imp[õo]em)"
)
_RE_SUPORTE_DISCLAIMER = _re.compile(
    r"(?:informa[çc][ãa]o[^.!?\n]{0,150}?)?n[ãa]o\s+constitu\w*\s+aconselhamento"
    r"\s*jur[íi]dic\w*"
)


def _cmd_gestor_dunning(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from app.compliance import linter
    from app.swarm import fila
    from sqlalchemy import func

    if args.winback:
        texto = sys.stdin.read() if args.stdin else ""
        peca = linter.PecaOutward(
            texto=texto, canal=linter.Canal.NURTURE_TRANSACIONAL, gerado_por_ia=True,
        )
        try:
            with fila.sessao_governacao() as s:
                item = fila.enfileirar(
                    s, tipo="winback", risco="medio", agente_origem="gestor",
                    ref_tipo="cliente", ref_id=str(args.cliente),
                    resumo=f"win-back → cliente {args.cliente}",
                    peca=peca,
                )
                item_id = item.id
        except fila.LinterReprovado as exc:
            _print_json({"aprovado": False, "violacoes": [
                {"regra": v.regra, "razao": v.razao} for v in exc.violacoes
            ]})
            return 1
        _print_json({"aprovado": True, "revisao_id": item_id})
        return 0

    hoje = _agora().date()
    s = _sessao_leitura()
    try:
        em_dunning = (
            s.query(models.Cliente)
            .filter(models.Cliente.estado == "em_dunning").count()
        )
        cancelados = (
            s.query(models.Cliente)
            .filter(models.Cliente.estado == "cancelado").count()
        )
        passos_hoje = sum(
            1 for (enviado_em,) in s.query(models.Alerta.enviado_em)
            .filter(models.Alerta.origem.like("dunning:%"))
            if enviado_em is not None and enviado_em.date() == hoje
        )
    finally:
        s.rollback()
        s.close()
    _print_json({"em_dunning": em_dunning, "cancelados": cancelados,
                 "passos_hoje": passos_hoje})
    return 0


def _cmd_gestor_suporte_triar(args) -> int:
    import app.models_swarm as ms
    from app.compliance import linter
    from app.swarm import fila, tetos

    pedido = json.loads(sys.stdin.read())
    categoria = pedido.get("categoria", "outro")
    confianca = pedido.get("confianca", "baixa")
    resposta = pedido.get("resposta") or ""

    def _escalar(motivo: str, severidade: str = "media") -> int:
        with fila.sessao_governacao() as s:
            tetos.escalar(
                s, severidade=severidade, agente="gestor",
                mensagem=f"[suporte] {motivo} — assunto: {pedido.get('assunto', '')!r}",
            )
        _print_json({"acao": "escalado", "motivo": motivo})
        return 0

    # G4 reimposto no ato do envio (RT-suporte): política em código, na frente
    # de qualquer resposta — nunca se confia só na classificação do modelo.
    from app.suporte import GATILHOS_ESCALACAO

    if categoria in GATILHOS_ESCALACAO:
        return _escalar(f"categoria {categoria}", severidade="alta")
    if confianca == "baixa" or pedido.get("acao") == "escalar":
        return _escalar("confiança baixa / escala pedida")
    sem_disclaimer = _RE_SUPORTE_DISCLAIMER.sub(" ", resposta.lower())
    m = _RE_SUPORTE_SENSIVEL.search(sem_disclaimer)
    if m:
        return _escalar(
            f"resposta toca estado de registo/seguro/regime legal ({m.group(0)!r})",
            severidade="alta",
        )

    peca = linter.PecaOutward(
        texto=resposta, canal=linter.Canal.NURTURE_TRANSACIONAL,
        gerado_por_ia=True, tem_optout_carimbado=True,  # resposta 1:1 solicitada
    )
    try:
        with fila.sessao_governacao() as s:
            evento = ms.EventoAgente(
                agente="gestor", tipo="conteudo_proposto",
                mensagem="rascunho de resposta de suporte",
                payload={"assunto": pedido.get("assunto", ""), "corpo_texto": resposta},
                criado_em=_agora(),
            )
            s.add(evento)
            s.flush()
            fila.enfileirar(
                s, tipo="suporte_rascunho", risco="medio", agente_origem="gestor",
                ref_tipo="evento_agente", ref_id=str(evento.id),
                resumo=f"resposta de suporte: {pedido.get('assunto', '')!r}",
                peca=peca,
            )
    except fila.LinterReprovado:
        return _escalar("resposta reprovada pelo linter", severidade="alta")

    _print_json({"acao": "enfileirado"})
    return 0


# ==========================================================================
#  SENTINELA-SERVIÇO — read-only; escreve SÓ eventos_agente/escalacoes
# ==========================================================================
def _cmd_sentinela_verificar(args) -> int:
    import app.models as models
    import app.models_swarm as ms
    from app.ia.validacao import validar_alerta
    from app.swarm import fila

    agora = _agora()
    achados: list[dict] = []  # {categoria, severidade, ref_tipo, ref_id, mensagem, payload}

    def _achado(categoria, severidade, ref_tipo, ref_id, mensagem, extra=None):
        achados.append({
            "categoria": categoria, "severidade": severidade,
            "ref_tipo": ref_tipo, "ref_id": str(ref_id), "mensagem": mensagem,
            "payload": {"categoria": categoria, **(extra or {})},
        })

    def _idade_dias(dt) -> float | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (agora - dt).total_seconds() / 86400

    s = _sessao_leitura()
    try:
        # 1) FRESHNESS nacional — o dead-man diz "o cron correu"; aqui olha-se a VERDADE.
        ultimo = (
            s.query(models.Varrimento)
            .filter(models.Varrimento.concluido_em.isnot(None))
            .order_by(models.Varrimento.concluido_em.desc()).first()
        )
        if ultimo is None:
            _achado("freshness_nacional", "critico", "varrimento", "nenhum",
                    "Nenhum varrimento nacional concluído registado.")
        else:
            idade = _idade_dias(ultimo.concluido_em) or 0.0
            if idade > config.SLA_DETECAO_DIAS:
                _achado("freshness_nacional", "critico", "varrimento", ultimo.id,
                        f"Varrimento nacional com {idade:.1f} dias — acima do SLA "
                        f"contratual de {config.SLA_DETECAO_DIAS} dias.",
                        {"idade_dias": round(idade, 1)})
            elif idade > config.CADENCIA_NACIONAL_DIAS + 1:
                _achado("freshness_nacional", "alto", "varrimento", ultimo.id,
                        f"Varrimento nacional com {idade:.1f} dias — fora da "
                        f"cadência de {config.CADENCIA_NACIONAL_DIAS} dias (+folga).",
                        {"idade_dias": round(idade, 1)})

        # 2+4) COBERTURA e freshness por cliente ativo — pagar e não ser vigiado é
        # dano existencial; sem sinal único de "está tudo bem".
        ativos = (
            s.query(models.Cliente)
            .filter(models.Cliente.estado == "ativo").all()
        )
        for cliente in ativos:
            registos = list(cliente.registos or [])
            if not registos:
                _achado("cobertura_cliente", "critico", "cliente", cliente.id,
                        f"Cliente ativo {cliente.id} sem registo associado — "
                        "paga e não é vigiado.")
                continue
            for registo in registos:
                detalhe = s.get(models.DetalheCliente, registo.nr_registo)
                if detalhe is None or detalhe.obtido_em is None:
                    _achado("cobertura_cliente", "critico", "registo",
                            registo.nr_registo,
                            f"Registo {registo.nr_registo} de cliente ativo sem "
                            "sonda individual persistida.")
                    continue
                idade = _idade_dias(detalhe.obtido_em) or 0.0
                if idade > config.SLA_DETECAO_DIAS:
                    _achado("freshness_cliente", "critico", "registo",
                            registo.nr_registo,
                            f"Sonda individual do registo {registo.nr_registo} com "
                            f"{idade:.1f} dias — acima do SLA de "
                            f"{config.SLA_DETECAO_DIAS} dias.",
                            {"idade_dias": round(idade, 1)})
                elif idade > config.CADENCIA_CLIENTE_DIAS + 1:
                    _achado("freshness_cliente", "alto", "registo",
                            registo.nr_registo,
                            f"Sonda individual do registo {registo.nr_registo} com "
                            f"{idade:.1f} dias — a cadência é diária.",
                            {"idade_dias": round(idade, 1)})

        # 3) BREAKER — nenhum "cancelado" ENVIADO sem rasto de desambiguação.
        enviados = (
            s.query(models.Alerta)
            .filter(models.Alerta.canal == "email",
                    models.Alerta.enviado_em.isnot(None)).all()
        )
        for alerta in enviados:
            conteudo = (alerta.conteudo or "").lower()
            if "cancelad" in conteudo or "suspens" in conteudo:
                if alerta.nr_registo is None:
                    continue
                rasto = (
                    s.query(models.Alerta)
                    .filter(models.Alerta.nr_registo == alerta.nr_registo,
                            models.Alerta.canal == "pendente_desambiguacao")
                    .first()
                )
                if rasto is None:
                    _achado("breaker_bypass", "critico", "alerta", alerta.id,
                            f"Alerta {alerta.id} afirma cancelamento/suspensão do "
                            f"registo {alerta.nr_registo} sem rasto do breaker "
                            "(pendente_desambiguacao) — possível falso «cancelado» "
                            "enviado.")

            # 3-bis) CROSS-CHECK alerta↔fonte (alucinação) — só regulatórios.
            if alerta.origem == "eventos_regulatorios" and alerta.origem_id:
                evento = s.get(models.EventoRegulatorio, alerta.origem_id)
                if evento is not None:
                    r = validar_alerta(
                        alerta.conteudo or "", url_fonte=evento.url or "",
                        excerto=(evento.resumo_ia or evento.titulo or ""),
                    )
                    if not r.valido:
                        _achado("alucinacao_alerta", "critico", "alerta", alerta.id,
                                f"Alerta {alerta.id} não bate com a fonte "
                                f"{evento.url!r}: {'; '.join(r.motivos[:3])}",
                                {"motivos": r.motivos[:5]})
    finally:
        s.rollback()
        s.close()

    # Escrita ÚNICA: eventos_agente (achados) + escalacoes (crítico) — mais nada.
    novos = 0
    with fila.sessao_governacao(permitidas={"eventos_agente", "escalacoes"}) as s:
        existentes = {
            ((e.ref_tipo or ""), (e.ref_id or ""), (e.payload or {}).get("categoria"))
            for e in s.query(ms.EventoAgente)
            .filter(ms.EventoAgente.tipo == "achado")
        }
        for a in achados:
            chave = (a["ref_tipo"], a["ref_id"], a["categoria"])
            if chave in existentes:
                continue
            novos += 1
            s.add(
                ms.EventoAgente(
                    agente="sentinela", tipo="achado",
                    severidade="critico" if a["severidade"] == "critico" else "aviso",
                    ref_tipo=a["ref_tipo"], ref_id=a["ref_id"],
                    mensagem=a["mensagem"], payload=a["payload"],
                    criado_em=agora,
                )
            )
            if a["severidade"] in ("critico", "alto"):
                s.add(
                    ms.Escalacao(
                        agente="sentinela", severidade="critica"
                        if a["severidade"] == "critico" else "alta",
                        mensagem=a["mensagem"], criado_em=agora,
                    )
                )

    por_sev: dict[str, int] = {}
    for a in achados:
        por_sev[a["severidade"]] = por_sev.get(a["severidade"], 0) + 1

    _print_json({
        "ciclo": agora.strftime("%Y-%m-%dT%H"),
        "verificacoes_corridas": 4,
        "achados": por_sev,
        "achados_novos": novos,
        "verde": not achados,
    })
    return 0


# ==========================================================================
#  EDITOR
# ==========================================================================
_TIPOS_EDITOR = {
    "artigo_seo": ("artigo_seo", "alto"),
}


def _validar_fontes_esquema(artigo: dict) -> None:
    """Valida o esquema do `url` de cada fonte na ORIGEM — mesmo critério do
    render (`app.publicador._RE_URL_HTTP`, só `http://`/`https://`). Um
    esquema hostil (`javascript:`, `data:`, …) nunca deve sequer entrar na
    fila; levanta `ValueError` (mesmo padrão do slug hostil). Chamada por
    `_cmd_editor_lint` e `_cmd_editor_enfileirar`, antes de qualquer coisa
    hostil ser sequer analisada/lintada.
    """
    from app import publicador

    for f in artigo.get("fontes", []):
        url = f.get("url", "")
        if not publicador._RE_URL_HTTP.match(url):
            raise ValueError(f"fonte com esquema não permitido: {url!r}")


def _texto_lint_artigo(artigo: dict):
    """Compõe (texto_a_lintar, url_fonte, excerto) a partir do JSON do artigo.

    O render final (PUBLICADOR, fase 3) embute no template as fontes, o
    disclaimer e a frase canónica de divulgação de IA — lintamos aqui o texto
    COMO SERÁ PUBLICADO, apensando esses blocos garantidos pelo template
    (mesmo princípio do `tem_optout_carimbado` no cold: o seam carimba). O
    template da fase 3 TEM de usar as mesmas constantes
    (`linter.DISCLAIMER_NAO_ACONSELHAMENTO` e `linter.DIVULGACAO_IA`) — senão
    o texto lintado diverge do publicado. Cobertura completa (regressão
    2026-07-19, revisão de conjunto F3): título, `meta_description` (vai para
    `<meta name="description">` e `og:description`, `publicador._HEAD_FMT`),
    secções, e — para cada fonte — o URL E os rótulos (`titulo`/`data`) que
    `publicador._render_fontes` usa como TEXTO VISÍVEL dos links, mais as
    frases canónicas.
    """
    from app.compliance import linter

    partes = [artigo.get("titulo", ""), artigo.get("meta_description", "")]
    for seccao in artigo.get("seccoes", []):
        partes.append(seccao.get("h2", ""))
        partes.append(seccao.get("corpo_md", ""))
    fontes = artigo.get("fontes", [])
    urls = " · ".join(f.get("url", "") for f in fontes if f.get("url"))
    partes.append(f"Fontes: {urls}")
    for f in fontes:
        partes.append(f.get("titulo", ""))
        partes.append(f.get("data", ""))
    partes.append(linter.DISCLAIMER_NAO_ACONSELHAMENTO)
    partes.append(linter.DIVULGACAO_IA)
    texto = "\n\n".join(p for p in partes if p)
    primeira = fontes[0] if fontes else {}
    return texto, primeira.get("url"), primeira.get("excerto")


def _cmd_editor_lint(args) -> int:
    from app import publicador
    from app.compliance import linter

    bruto = sys.stdin.read()
    try:
        artigo = json.loads(bruto)
        if not isinstance(artigo, dict):
            raise ValueError("payload tem de ser um objeto JSON")
        # Mesma whitelist do render (`app.publicador._RE_SLUG`) — recusa aqui,
        # na ORIGEM, antes de qualquer coisa hostil ser sequer analisada.
        if not publicador._RE_SLUG.fullmatch(artigo["slug"]):
            raise ValueError(f"slug inválido: {artigo['slug']!r}")
        _validar_fontes_esquema(artigo)
    except (ValueError, KeyError, TypeError):
        sys.stderr.write("payload tem de ser JSON do artigo (slug, titulo, seccoes, fontes)\n")
        return 2

    texto, url_fonte, excerto = _texto_lint_artigo(artigo)
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
    from app import publicador
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
        if not isinstance(artigo, dict):
            raise ValueError("payload tem de ser um objeto JSON")
        slug = artigo["slug"]
        # Mesma whitelist do render (`app.publicador._RE_SLUG`) — um slug
        # hostil nunca chega sequer a ser enfileirado (fail-closed na ORIGEM).
        if not publicador._RE_SLUG.fullmatch(slug):
            raise ValueError(f"slug inválido: {slug!r}")
        _validar_fontes_esquema(artigo)
        titulo = artigo["titulo"]
    except (ValueError, KeyError, TypeError):
        sys.stderr.write("payload tem de ser JSON do artigo (slug, titulo, seccoes, fontes)\n")
        return 2

    texto, url_fonte, excerto = _texto_lint_artigo(artigo)
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
        # Sinais de eventos regulatórios frescos (spec §3.2) — ativam as
        # páginas-gatilho do EDITOR. Janela de 90 dias, mais recentes primeiro;
        # só campos institucionais (nenhum dado pessoal em EventoRegulatorio).
        janela = _agora().date() - timedelta(days=90)
        eventos_regulatorios = [
            {"id": e.id, "fonte": e.fonte, "concelhos": e.concelhos,
             "publicado_em": e.publicado_em, "titulo": e.titulo,
             "resumo_ia": e.resumo_ia}
            for e in s.query(models.EventoRegulatorio)
            .filter(models.EventoRegulatorio.publicado_em.isnot(None))
            .filter(models.EventoRegulatorio.publicado_em >= janela)
            .order_by(models.EventoRegulatorio.publicado_em.desc())
            .limit(10)
        ]
    finally:
        s.rollback()
        s.close()
    _print_json({
        "top_concelhos": [{"concelho": c, "registos": n} for c, n in top],
        "artigos": artigos,
        "eventos_regulatorios": eventos_regulatorios,
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
                         "grupo_alvo": args.grupo, "fonte_url": args.fonte},
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


# ==========================================================================
#  Parser + dispatch
# ==========================================================================
def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="manage.py", add_help=True)
    sub = p.add_subparsers(dest="comando")

    # MAESTRO
    m = sub.add_parser("maestro-run")
    m.add_argument("--modo", choices=("governanca", "digest"), required=True)
    m.set_defaults(func=_cmd_maestro_run)
    sub.add_parser("maestro-metricas").set_defaults(func=_cmd_maestro_metricas)
    sub.add_parser("maestro-saude").set_defaults(func=_cmd_maestro_saude)
    sub.add_parser("maestro-fila").set_defaults(func=_cmd_maestro_fila)
    sub.add_parser("maestro-escalacoes").set_defaults(func=_cmd_maestro_escalacoes)
    d = sub.add_parser("maestro-digest")
    d.add_argument("--ficheiro", required=True)
    d.set_defaults(func=_cmd_maestro_digest)
    e = sub.add_parser("maestro-escalar")
    e.add_argument("--sev", choices=("baixa", "media", "alta", "critica"), required=True)
    e.add_argument("--msg", required=True)
    e.set_defaults(func=_cmd_maestro_escalar)
    r = sub.add_parser("maestro-retry")
    r.add_argument("--agente", choices=("angariador", "gestor", "sentinela", "editor", "comunicador"), required=True)
    r.add_argument("--backoff", type=int, required=True)
    r.set_defaults(func=_cmd_maestro_retry)
    g = sub.add_parser("maestro-gate-token")
    g.add_argument("--fila-id", type=int, required=True, dest="fila_id")
    g.set_defaults(func=_cmd_maestro_gate_token)

    # ANGARIADOR
    ang = sub.add_parser("angariador")
    ang_sub = ang.add_subparsers(dest="acao", required=True)
    ang_sub.add_parser("detetar").set_defaults(func=_cmd_angariador_detetar)
    al = ang_sub.add_parser("lint")
    al.add_argument("--stdin", action="store_true", required=True)
    al.add_argument("--tipo", choices=sorted(_TIPOS_CONTEUDO), default="cold_draft")
    al.add_argument("--fonte", default=None)
    al.add_argument("--excerto", default=None)
    al.set_defaults(func=_cmd_angariador_lint)
    ae = ang_sub.add_parser("enfileirar")
    ae.add_argument("--tipo", choices=sorted(_TIPOS_CONTEUDO), required=True)
    ae.add_argument("--stdin", action="store_true")
    ae.add_argument("--fonte", default=None)
    ae.add_argument("--excerto", default=None)
    ae.add_argument("--peca-id", type=int, default=None, dest="peca_id")
    ae.add_argument("--escalar", action="store_true")
    ae.add_argument("--motivo", default=None)
    ae.set_defaults(func=_cmd_angariador_enfileirar)
    ang_sub.add_parser("estado").set_defaults(func=_cmd_angariador_estado)

    # GESTOR
    ges = sub.add_parser("gestor")
    ges_sub = ges.add_subparsers(dest="acao", required=True)
    go = ges_sub.add_parser("onboarding-tarefas")
    go.add_argument("--recomendar", action="store_true")
    go.add_argument("--alerta-id", type=int, default=None, dest="alerta_id")
    go.add_argument("--stdin", action="store_true")
    go.set_defaults(func=_cmd_gestor_onboarding)
    gr = ges_sub.add_parser("relatorio-mensal-compor")
    gr.add_argument("--mes", default=None)
    gr.add_argument("--limite", type=int, default=None)
    gr.set_defaults(func=_cmd_gestor_relatorio)
    gd = ges_sub.add_parser("dunning-estado")
    gd.add_argument("--winback", action="store_true")
    gd.add_argument("--cliente", type=int, default=None)
    gd.add_argument("--stdin", action="store_true")
    gd.set_defaults(func=_cmd_gestor_dunning)
    gs = ges_sub.add_parser("suporte-triar")
    gs.add_argument("--stdin", action="store_true", required=True)
    gs.set_defaults(func=_cmd_gestor_suporte_triar)

    # SENTINELA
    sen = sub.add_parser("sentinela")
    sen_sub = sen.add_subparsers(dest="acao", required=True)
    sen_sub.add_parser("verificar").set_defaults(func=_cmd_sentinela_verificar)

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

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Retrocompatibilidade: jobs de arg único continuam a despachar como antes.
    if len(argv) == 1 and argv[0] in _JOBS:
        _JOBS[argv[0]]()
        return 0

    if not argv:
        sys.stderr.write(
            "uso: manage.py <%s> | <subcomando de agente>\n" % "|".join(_JOBS)
        )
        return 2

    parser = _construir_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    func = getattr(args, "func", None)
    if func is None:
        sys.stderr.write("uso: manage.py <comando>\n")
        return 2
    return func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
