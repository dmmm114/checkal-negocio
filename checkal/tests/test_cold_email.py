"""Testes do remetente frio (Canal B, `getcheckal.com`) — FDS 6, PARECER-GATED.

Contrato (SPEC-FDS6.md §cold_email + `app/envio/SPEC-RESEND.md` §7):

    obter_remetente_frio() -> callable | None   (LIVE-GATED **e** PARECER-GATED)
    enviar_frio(*, para, assunto, html, cliente_smtp, de=None, texto=None) -> ResultadoFrio

🚦 O PORTÃO (o coração deste sprint) é CÓDIGO, não disciplina: enquanto o dono não
tiver o parecer favorável do jurista RGPD (`config.CHECKAL_PARECER_RGPD_OK`),
`obter_remetente_frio()` devolve **None** e NENHUM email frio sai. O gate é o triplo
`config.pode_enviar_frio_global()` (parecer OK **e** modo de teste OFF **e** SMTP de
cold configurado).

FRONTEIRA DURA (SPEC-RESEND §0): o cold usa o domínio irmão `getcheckal.com` + SMTP
dedicado (`COLD_SMTP_*`), NUNCA a Resend — este módulo **não importa** `app.envio`
nem `resend` (partilhar reputação suspenderia a conta transacional). Cada email
leva remetente identificado (`COLD_FROM`) + opt-out 1-clique (`checkal.pt/remover`)
no corpo E nos headers `List-Unsubscribe`/`List-Unsubscribe-Post` (RFC 8058).

DISCIPLINA (inviolável): MODO DE TESTE, LIVE-GATED. **Zero** rede/SMTP — o
`cliente_smtp` é INJETADO/MOCKADO (`FakeSMTP`). Escrito ANTES da implementação (TDD).
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

import app.config as config
from app.campanhas import cold_email


# ==========================================================================
#  Duplo de teste: cliente SMTP falso (nunca há rede) — captura a mensagem
# ==========================================================================
class FakeSMTP:
    """Cliente à laia de `smtplib.SMTP`: regista cada `send_message` e devolve
    `recusados` (dict vazio = todos aceites; não-vazio = recipientes recusados)."""

    def __init__(self, recusados: dict | None = None):
        self.recusados = recusados or {}
        self.mensagens: list = []

    def send_message(self, msg, *args, **kwargs):
        self.mensagens.append(msg)
        return self.recusados


def _ligar_todos_os_gates(monkeypatch):
    """Abre o triplo gate global: parecer OK + modo de teste OFF + SMTP presente."""
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "cold@getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "segredo")


def _enviar(cli, **over):
    """Chamada-base de `enviar_frio` com um destinatário coletivo genérico."""
    kw = dict(
        para="reservas@empresa.pt",
        assunto="O teu AL está em ordem?",
        html="<p>O teu registo RNAL mudou de estado.</p>",
        cliente_smtp=cli,
    )
    kw.update(over)
    return cold_email.enviar_frio(**kw)


def _html_enviado(cli: FakeSMTP) -> str:
    """A parte HTML da última mensagem enviada, já descodificada."""
    msg = cli.mensagens[-1]
    parte = msg.get_body(preferencelist=("html",))
    return parte.get_content()


# ==========================================================================
#  🚦 O PORTÃO — obter_remetente_frio() é PARECER-GATED (o coração do sprint)
# ==========================================================================
def test_sem_parecer_obter_remetente_frio_devolve_none():
    # Estado de fábrica: parecer OFF (+ modo de teste ON) ⇒ None. Nada envia.
    assert config.CHECKAL_PARECER_RGPD_OK is False
    assert cold_email.obter_remetente_frio() is None


def test_modo_teste_on_devolve_none_mesmo_com_parecer(monkeypatch):
    # Parecer favorável e SMTP configurado, mas ainda em sandbox ⇒ None.
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", True)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "smtp.getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_USER", "cold@getcheckal.com")
    monkeypatch.setattr(config, "COLD_SMTP_PASS", "segredo")
    assert cold_email.obter_remetente_frio() is None


def test_sem_smtp_devolve_none(monkeypatch):
    # Parecer OK + modo de teste OFF, mas SMTP dedicado por configurar ⇒ None.
    monkeypatch.setattr(config, "CHECKAL_PARECER_RGPD_OK", True)
    monkeypatch.setattr(config, "CHECKAL_MODO_TESTE", False)
    monkeypatch.setattr(config, "COLD_SMTP_HOST", "")
    assert cold_email.obter_remetente_frio() is None


def test_tudo_ligado_devolve_callable(monkeypatch):
    # Os TRÊS gates abertos ⇒ callable. NÃO o invocamos (invocá-lo abriria um
    # smtplib.SMTP real e tocaria a rede) — só confirmamos o gate, como no Resend.
    _ligar_todos_os_gates(monkeypatch)
    remetente = cold_email.obter_remetente_frio()
    assert remetente is not None
    assert callable(remetente)


def test_pode_enviar_frio_global_reexportado_do_config():
    # A superfície pública do módulo expõe o portão global (SPEC §cold_email),
    # e é o MESMO objeto do config (lê os globals do config em tempo de chamada).
    assert cold_email.pode_enviar_frio_global is config.pode_enviar_frio_global
    assert cold_email.pode_enviar_frio_global() is False   # default: fechado


# ==========================================================================
#  enviar_frio — envia via cliente SMTP INJETADO (nunca cria rede)
# ==========================================================================
def test_enviar_frio_usa_cliente_injetado_uma_vez():
    cli = FakeSMTP()
    _enviar(cli)
    assert len(cli.mensagens) == 1          # exatamente um send_message


def test_enviar_frio_destinatario_e_assunto():
    cli = FakeSMTP()
    _enviar(cli, para="geral@empresa.pt", assunto="Assunto X")
    msg = cli.mensagens[0]
    assert msg["To"] == "geral@empresa.pt"
    assert msg["Subject"] == "Assunto X"


def test_remetente_sai_de_getcheckal_e_nunca_de_checkal_pt():
    # Fronteira DURA: o From é o COLD_FROM (getcheckal.com), jamais checkal.pt.
    cli = FakeSMTP()
    _enviar(cli)
    de = cli.mensagens[0]["From"]
    assert de == config.COLD_FROM
    assert "getcheckal.com" in de
    assert "checkal.pt" not in de


def test_remetente_pode_ser_sobreposto_mas_continua_getcheckal(monkeypatch):
    cli = FakeSMTP()
    _enviar(cli, de="CheckAL <ola@getcheckal.com>")
    assert cli.mensagens[0]["From"] == "CheckAL <ola@getcheckal.com>"


# ==========================================================================
#  Opt-out 1-clique — link no corpo E nos headers List-Unsubscribe (RFC 8058)
# ==========================================================================
def test_link_remocao_no_corpo_html():
    cli = FakeSMTP()
    _enviar(cli)
    assert "checkal.pt/remover" in _html_enviado(cli)


def test_header_list_unsubscribe_com_link_de_remocao():
    cli = FakeSMTP()
    _enviar(cli)
    msg = cli.mensagens[0]
    assert "checkal.pt/remover" in msg["List-Unsubscribe"]
    # 1-clique real (RFC 8058): o header POST tem de estar presente.
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_link_remocao_identifica_o_destinatario():
    # 1-clique verdadeiro: o link carrega quem remover (não um /remover cego).
    cli = FakeSMTP()
    res = _enviar(cli, para="reservas@casa.pt")
    assert "reservas%40casa.pt" in res.link_remocao or "reservas@casa.pt" in res.link_remocao
    assert res.link_remocao.startswith("https://checkal.pt/remover")


def test_headers_list_unsubscribe_mesmo_quando_copy_ja_tem_link():
    # Compliance é código: mesmo que a copy já traga o link, os headers entram.
    cli = FakeSMTP()
    _enviar(cli, html="<p>Já cá está: checkal.pt/remover</p>")
    assert "checkal.pt/remover" in cli.mensagens[0]["List-Unsubscribe"]


def test_rodape_nao_e_duplicado_quando_a_copy_ja_tem_o_link():
    # Se a copy já inclui checkal.pt/remover, o seam NÃO acrescenta o seu rodapé
    # (evita opt-out duplicado); o marcador do seam fica ausente.
    cli_sem = FakeSMTP()
    _enviar(cli_sem, html="<p>Sem link.</p>")
    assert cold_email.MARCADOR_RODAPE in _html_enviado(cli_sem)   # foi acrescentado

    cli_com = FakeSMTP()
    _enviar(cli_com, html="<p>Com link: checkal.pt/remover</p>")
    assert cold_email.MARCADOR_RODAPE not in _html_enviado(cli_com)  # não duplica
    assert "checkal.pt/remover" in _html_enviado(cli_com)            # mas o link persiste


# ==========================================================================
#  Resultado + erros
# ==========================================================================
def test_enviar_frio_devolve_resultado_frio():
    cli = FakeSMTP()
    res = _enviar(cli, para="info@empresa.pt")
    assert isinstance(res, cold_email.ResultadoFrio)
    assert res.para == "info@empresa.pt"
    assert res.remetente == config.COLD_FROM
    assert "checkal.pt/remover" in res.link_remocao


def test_recusa_do_destinatario_levanta_erro():
    # send_message devolve o recipiente recusado ⇒ envio não confirmado ⇒ ErroFrio.
    cli = FakeSMTP(recusados={"reservas@empresa.pt": (550, b"blocked")})
    with pytest.raises(cold_email.ErroFrio):
        _enviar(cli)


# ==========================================================================
#  FRONTEIRA DURA — o módulo NÃO importa a Resend nem app.envio
# ==========================================================================
def test_modulo_nao_importa_resend_nem_app_envio():
    # Prova por AST (não por prosa): nenhum import do módulo referencia a Resend
    # nem o pacote transacional. Docstrings podem mencionar "Resend" à vontade.
    fonte = __import__("inspect").getsource(cold_email)
    arvore = ast.parse(fonte)
    importados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados += [alias.name for alias in no.names]
        elif isinstance(no, ast.ImportFrom):
            base = no.module or ""
            importados.append(base)
            importados += [f"{base}.{alias.name}" for alias in no.names]
    for nome in importados:
        assert "resend" not in nome.lower(), f"import proibido: {nome}"
        assert not nome.startswith("app.envio"), f"import proibido: {nome}"


def test_importar_cold_email_nao_puxa_app_envio_para_sys_modules():
    # Hermético: num interpretador LIMPO (subprocesso), importar o cold_email NUNCA
    # carrega o Canal A (app.envio/resend) — nem sequer transitivamente. (Verificar o
    # sys.modules GLOBAL era não-hermético: outros testes da suite poluem-no ao importar
    # app.envio; este subprocesso isola o invariante independentemente da ordem da suite.)
    raiz = pathlib.Path(__file__).resolve().parent.parent  # .../checkal
    codigo = (
        "import sys, app.campanhas.cold_email; "
        "assert 'app.envio' not in sys.modules, 'cold_email puxou app.envio (Canal A)'; "
        "assert 'resend' not in sys.modules, 'cold_email puxou resend'"
    )
    r = subprocess.run(
        [sys.executable, "-c", codigo], cwd=str(raiz),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
