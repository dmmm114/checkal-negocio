"""Esquema Pydantic v2 do registo RNAL — validação e normalização do JSON bruto.

Fronteira do módulo (SPEC-FDS1.md §schema): transforma um registo bruto da API
`list_RNAL` (aninhado em `RNAL_Registo`, chaves PascalCase) num `RegistoRNAL`
achatado e com tipos normalizados, pronto para o `hashing`/`diffing`.

Princípio de segurança do pipeline (AUTOMACAO.md §1, §6): **nunca fazer diffing
sobre dados suspeitos**. Se a estrutura esperada mudar — chave obrigatória em
falta ou tipo incompatível — levanta-se `DriftEsquemaRNAL` para que o
orquestrador (`ingest`) marque o varrimento como `abortado` e NÃO corra o diff.

Notas do formato verificado:
  - `NrRegisto` vem como ``"100031/AL"`` → o inteiro é ``int(nr.split("/")[0])``.
  - `NrCamas`/`NrUtentes` podem vir string ou int.
  - Os contactos do titular (`Nome`, `Contribuinte`, `Email`, `Telefone`,
    `Telemovel`) vivem dentro de `TitulardaExploracao` e são achatados para o topo.
  - `Tipo` do titular é normalizado para ``"singular"`` | ``"coletiva"``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Chaves obrigatórias do registo interno. A ausência de qualquer uma é drift:
# sem elas não há registo identificável nem titular para alertar.
_OBRIGATORIAS = ("NrRegisto", "Concelho", "TitulardaExploracao")


class DriftEsquemaRNAL(Exception):
    """A estrutura do JSON RNAL divergiu do contrato (chave em falta / tipo errado).

    Sinaliza que o varrimento deve ser **abortado** sem correr diffing: agir sobre
    dados cuja forma mudou geraria eventos falsos (ex.: um falso "cancelado").
    """


def _para_inteiro_opcional(valor: Any, *, campo: str) -> int | None:
    """Converte string/int num inteiro; ``None``/``""`` → ``None``; lixo → drift.

    `NrCamas`/`NrUtentes` chegam ora como ``2`` ora como ``"4"``. Um valor não
    numérico é tipo incompatível (drift), não um mero opcional em falta.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):  # bool é subtipo de int — recusa explicitamente
        raise DriftEsquemaRNAL(f"{campo} com tipo booleano inesperado: {valor!r}")
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError) as exc:
        raise DriftEsquemaRNAL(f"{campo} não numérico: {valor!r}") from exc


class RegistoRNAL(BaseModel):
    """Registo RNAL validado e achatado (uma linha lógica da tabela ``registos``).

    Aceita tanto o invólucro ``{"RNAL_Registo": {...}}`` como o dicionário
    interno já desembrulhado. Os nomes dos atributos coincidem com os campos
    relevantes para diffing (ver `hashing.hash_campos`).
    """

    model_config = ConfigDict(extra="ignore")

    nr_registo: int          # derivado de NrRegisto ("100031/AL" → 100031)
    data_registo: str | None = None
    nome_alojamento: str | None = None
    modalidade: str | None = None
    nr_camas: int | None = None
    nr_utentes: int | None = None
    endereco: str | None = None
    cod_postal: str | None = None
    localidade: str | None = None
    freguesia: str | None = None
    concelho: str            # obrigatório
    distrito: str | None = None
    titular_tipo: str | None = None   # "singular" | "coletiva" | None
    titular_nome: str | None = None
    nif: str | None = None
    email: str | None = None
    telefone: str | None = None
    telemovel: str | None = None
    dtmnfr: str | None = None         # irrelevante p/ diffing; guardado por fidelidade

    # -- Normalização estrutural (corre ANTES da validação dos campos) --
    @model_validator(mode="before")
    @classmethod
    def _desembrulhar_e_achatar(cls, dados: Any) -> Any:
        """Desembrulha `RNAL_Registo`, valida obrigatórias e achata o titular.

        Levanta `DriftEsquemaRNAL` — não `ValidationError` — para que a forma
        errada do JSON pare o pipeline de modo inequívoco.
        """
        if not isinstance(dados, dict):
            raise DriftEsquemaRNAL(f"Registo não é um objeto JSON: {type(dados).__name__}")

        interno = dados.get("RNAL_Registo", dados)
        if not isinstance(interno, dict):
            raise DriftEsquemaRNAL("RNAL_Registo não é um objeto JSON")

        for chave in _OBRIGATORIAS:
            if interno.get(chave) is None:
                raise DriftEsquemaRNAL(f"Campo obrigatório em falta: {chave}")

        titular = interno["TitulardaExploracao"]
        if not isinstance(titular, dict):
            raise DriftEsquemaRNAL("TitulardaExploracao não é um objeto JSON")

        # Dicionário achatado com nomes snake_case — sem depender de aliases.
        return {
            "nr_registo": interno.get("NrRegisto"),
            "data_registo": interno.get("DataRegisto"),
            "nome_alojamento": interno.get("NomeAlojamento"),
            "modalidade": interno.get("Modalidade"),
            "nr_camas": interno.get("NrCamas"),
            "nr_utentes": interno.get("NrUtentes"),
            "endereco": interno.get("Endereco"),
            "cod_postal": interno.get("CodPostal"),
            "localidade": interno.get("Localidade"),
            "freguesia": interno.get("Freguesia"),
            "concelho": interno.get("Concelho"),
            "distrito": interno.get("Distrito"),
            "titular_tipo": titular.get("Tipo"),
            "titular_nome": titular.get("Nome"),
            "nif": titular.get("Contribuinte"),
            "email": titular.get("Email"),
            "telefone": titular.get("Telefone"),
            "telemovel": titular.get("Telemovel"),
            "dtmnfr": interno.get("DTMNFR"),
        }

    @field_validator("nr_registo", mode="before")
    @classmethod
    def _corta_nr_registo(cls, valor: Any) -> int:
        """``"100031/AL"`` → ``100031``. Não numérico → drift (tipo incompatível)."""
        if isinstance(valor, bool):
            raise DriftEsquemaRNAL(f"NrRegisto com tipo booleano: {valor!r}")
        if isinstance(valor, int):
            return valor
        parte = str(valor).split("/", 1)[0].strip()
        try:
            return int(parte)
        except (TypeError, ValueError) as exc:
            raise DriftEsquemaRNAL(f"NrRegisto inválido: {valor!r}") from exc

    @field_validator("nr_camas", mode="before")
    @classmethod
    def _coage_nr_camas(cls, valor: Any) -> int | None:
        return _para_inteiro_opcional(valor, campo="NrCamas")

    @field_validator("nr_utentes", mode="before")
    @classmethod
    def _coage_nr_utentes(cls, valor: Any) -> int | None:
        return _para_inteiro_opcional(valor, campo="NrUtentes")

    @field_validator("titular_tipo", mode="before")
    @classmethod
    def _normaliza_titular_tipo(cls, valor: Any) -> str | None:
        """`Tipo` → ``"singular"`` | ``"coletiva"``; desconhecido/ausente → ``None``.

        `Tipo` não é obrigatório, por isso um valor inesperado não é drift — fica
        ``None`` e o classificador de NIF (`app.compliance.nif`) decide a jusante.
        Tolera a grafia antiga "colectiva".
        """
        if valor is None:
            return None
        texto = str(valor).strip().lower()
        if "colectiv" in texto or "coletiv" in texto:
            return "coletiva"
        if "singular" in texto:
            return "singular"
        return None


def parse_registo(bruto: Any) -> RegistoRNAL:
    """Valida um registo bruto (invólucro `RNAL_Registo` ou já interno).

    Qualquer `ValidationError` residual do Pydantic é reescrita como
    `DriftEsquemaRNAL`, garantindo um único tipo de falha para o pipeline apanhar.
    """
    try:
        return RegistoRNAL.model_validate(bruto)
    except DriftEsquemaRNAL:
        raise
    except Exception as exc:  # ValidationError e afins → drift
        raise DriftEsquemaRNAL(f"Registo RNAL inválido: {exc}") from exc


def parse_lista(bruto_lista: Any) -> list[RegistoRNAL]:
    """Valida a lista de registos de um varrimento. Estrutura errada → drift."""
    if not isinstance(bruto_lista, list):
        raise DriftEsquemaRNAL(
            f"Esperava uma lista de registos, veio {type(bruto_lista).__name__}"
        )
    return [parse_registo(item) for item in bruto_lista]
