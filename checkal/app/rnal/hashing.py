"""Hash dos campos relevantes de um registo RNAL, para diffing barato.

O diffing (SPEC-FDS1.md §diffing) não compara registos campo a campo: compara
um `sha256` estável dos campos que interessam para deteção de alterações. Assim
uma linha `registos.hash_campos` diferente entre dois varrimentos = evento
`alterado`, sem carregar/serializar o registo inteiro.

Contrato (SPEC-FDS1.md §hashing):
  - `hash_campos(registo)` aceita um `RegistoRNAL` (objeto com atributos
    achatados) OU um dict achatado (chaves = nomes canónicos dos campos).
  - Determinístico: mesma entrada lógica → mesmo hash.
  - Sensível: alterar qualquer campo relevante muda o hash.
  - Insensível: campos irrelevantes (ex.: `DTMNFR`, `nr_registo`, datas) não
    entram no hash.

Os campos relevantes e a sua ordem canónica são `CAMPOS_RELEVANTES`.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

# Ordem canónica dos campos que entram no hash (SPEC-FDS1.md §hashing).
# NÃO reordenar sem migrar todos os `registos.hash_campos` existentes: a ordem
# faz parte da definição do hash.
CAMPOS_RELEVANTES: tuple[str, ...] = (
    "nome_alojamento",
    "modalidade",
    "nr_camas",
    "nr_utentes",
    "endereco",
    "cod_postal",
    "freguesia",
    "concelho",
    "distrito",
    "titular_tipo",
    "titular_nome",
    "nif",
    "email",
    "telefone",
    "telemovel",
)

# Separador de unidades (ASCII US, 0x1F): impossível de confundir com conteúdo
# real dos campos, logo evita colisões por deslocamento entre campos vizinhos.
_SEP = "\x1f"

# Campos do titular → nomes candidatos dentro de um sub-objeto/sub-dict `titular`
# (ou `TitulardaExploracao`), caso o RegistoRNAL guarde o titular aninhado em vez
# de atributos achatados. Rede de segurança para o desacoplamento entre módulos.
_TITULAR_ANINHADO: dict[str, tuple[str, ...]] = {
    "titular_tipo": ("tipo", "Tipo"),
    "titular_nome": ("nome", "Nome"),
    "nif": ("nif", "Contribuinte"),
    "email": ("email", "Email"),
    "telefone": ("telefone", "Telefone"),
    "telemovel": ("telemovel", "Telemovel"),
}
_CONTENTORES_TITULAR = ("titular", "TitulardaExploracao")


def _valor_campo(registo: Any, campo: str) -> Any:
    """Lê `campo` de um dict achatado ou de um objeto, com recurso a titular aninhado."""
    if isinstance(registo, Mapping):
        if campo in registo:
            return registo[campo]
        return _titular_de_mapping(registo, campo)
    if hasattr(registo, campo):
        return getattr(registo, campo)
    return _titular_de_objeto(registo, campo)


def _titular_de_mapping(registo: Mapping, campo: str) -> Any:
    candidatos = _TITULAR_ANINHADO.get(campo)
    if not candidatos:
        return None
    for chave in _CONTENTORES_TITULAR:
        sub = registo.get(chave)
        if isinstance(sub, Mapping):
            for nome in candidatos:
                if nome in sub:
                    return sub[nome]
    return None


def _titular_de_objeto(registo: Any, campo: str) -> Any:
    candidatos = _TITULAR_ANINHADO.get(campo)
    if not candidatos:
        return None
    for chave in _CONTENTORES_TITULAR:
        sub = getattr(registo, chave, None)
        if sub is None:
            continue
        for nome in candidatos:
            if hasattr(sub, nome):
                return getattr(sub, nome)
    return None


def _normalizar(valor: Any) -> str:
    """Forma canónica de um valor: `None`/vazio → ""; números e strings coincidem."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "1" if valor else "0"
    return str(valor).strip()


def hash_campos(registo: Any) -> str:
    """Devolve o sha256 hex dos campos relevantes de `registo`, em ordem canónica.

    `registo` pode ser um `RegistoRNAL` (ou qualquer objeto com os atributos
    achatados) ou um dict achatado. Campos ausentes contam como vazios.
    """
    partes = [
        f"{campo}={_normalizar(_valor_campo(registo, campo))}"
        for campo in CAMPOS_RELEVANTES
    ]
    payload = _SEP.join(partes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
