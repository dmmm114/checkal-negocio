# DECISÕES DE EXECUÇÃO — autoritativas (pós-workflow)

> Estas decisões foram tomadas pelo dono **depois** de o workflow de desenho ter corrido.
> **Em qualquer conflito com o resto do pacote (arquitetura, specs, prompt-mestre), MANDAM ESTAS.**
> Data: 2026-07-18.

## 1. Pagamento a partir do email — Opção A (gerar ao vivo no clique)
O email cold **nunca** leva a referência Multibanco crua. Leva **dois** CTA: **"Pagar já"** e
**"Fazer o check grátis"** (alternativa de menor compromisso, contraria a suspeita de esquema).
O **"Pagar já"** aponta para uma **URL assinada e com validade** → página própria
`checkal.pt/pagar?t=<token>`. O token referencia `{campanha, segmento, nr_registo?, plano_sugerido}`
e **não contém qualquer dado pessoal**.

**Porquê A e não pré-gerar:** (a) o valor da referência é fixo na geração e o plano só se sabe depois
de o cliente escolher; (b) o MB Way exige o telemóvel do cliente (só se obtém numa página); (c) sem
página não se captam **NIF + T&C** — logo não há fatura-recibo válida nem contrato; (d) pré-gerar
milhares de referências para uma taxa de pagamento ~0,5% cria refs pendentes, gestão de validade e um
mapa ref→destinatário de todos. A chamada ao IfThenPay é sub-segundo — a Opção A não perde nada.

## 2. Página `/pagar` — própria, em checkal.pt, "clean" e a transmitir SEGURANÇA (requisito, não estética)
- HTTPS/cadeado; **identificação completa** (Cosmic Oasis, Lda. · NIPC · morada) bem visível.
- "Serviço privado e independente" explícito; **marcas oficiais Multibanco / MB Way**; nota
  "pagamento processado por **IfThenPay**".
- **T&C visíveis + captura de NIF + aceitação** antes do pagamento; **fatura prometida no ecrã**.
- **Sem dark patterns.** Objetivo declarado: **matar a objeção "isto cheira a esquema"** (objeção #4
  do próprio site) e passar confiança a um cliente de 45–65 anos.

## 3. Cobrança = IfThenPay (build NOVO)
As chaves já estão previstas na config (`IFTHENPAY_MB_KEY`, `IFTHENPAY_MBWAY_KEY`,
`IFTHENPAY_ANTIPHISHING_KEY`, `IFTHENPAY_BASE`) **mas a integração não está construída** (o que existe é
Stripe Payment Links). Métodos na página: **Referência Multibanco + MB Way + Transferência (IBAN)**.
- **MB ref / MB Way** confirmam por **callback** (com antiphishing key) → ativação automática.
- **Transferência** = reconciliação **semi-manual**: o **Gestor-de-Cliente** marca "por casar" até bater.
- Detalhe de build em `PAGAMENTOS-IFTHENPAY.md`.

## 4. Faturação = TOConline, série **CKL** separada
Mesma empresa (Cosmic Oasis, mesmo NIF); série **nova** registada na AT →
`TOCONLINE_SERIES_ID`/`TOCONLINE_SERIES_PREFIX`. Segrega a contabilidade da Radar Marca dentro do
mesmo NIF (bom para gestão e para um futuro *asset deal*). O código já tem a guarda `SerieNaoConfigurada`
(não emite sem série). **Stripe fica secundário/opcional** — não é preciso para a via cold-direto.
**Antes da 1.ª fatura real:** smoke-test TOConline para fechar os ~15 campos `TODO[ASSUMIDO]`.

## 5. Renovação anual = nova referência/MB Way a D-30 (sem cartão guardado)
Mais limpo e seguro para o cliente low-touch (não fica com dados de cartão em lado nenhum). O
**Gestor-de-Cliente** trata do ciclo de renovação/dunning por referência.

## 6. Domínios
`checkal.pt` **já comprado** (marca/site/landing/faturas/selo/página `/pagar`). O **envio do cold**
continua em **domínio separado** (getcheckal.com ou equivalente) para proteger a reputação de
`checkal.pt` — esse domínio de envio **ainda precisa de ser garantido**.

## 7. Canais e IA (recap das decisões do dono)
- **Cold a pessoas coletivas PRIMEIRO**; **cartas parqueadas** (o build não as ativa); **SEM** canal de
  contabilistas/parcerias — angariação **direta**.
- **IA = Claude CLI no Polaris** (headless, single-shot, systemd, `MemoryMax`).
  ⚠️ **Caveat encodado:** o Claude CLI **não** localiza dados na UE (inferência na API da Anthropic,
  EUA). Fechar **DPA da Anthropic** + **minimização**: o modelo **nunca** vê campos pessoais de
  singular; dados pessoais só quando **opted-in**.

## 8. Gate humano — inalterável
Aprovação humana em **toda a ação irreversível externa** (envio em massa, publicação, emissão de
fatura, cobrança). Cold **gated por omissão** (`CHECKAL_PARECER_RGPD_OK=False`,
`CHECKAL_MODO_TESTE=True`). Os agentes são autónomos **até** ao gate.
