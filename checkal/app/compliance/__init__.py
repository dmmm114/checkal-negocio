"""Núcleo de compliance do canal de email frio B2B do CheckAL.

Faz cumprir — em código, não em disciplina humana — o enquadramento legal
fechado (ver RATIONALE.md neste diretório):

  Só é endereçável por email frio quem cumpre CUMULATIVAMENTE:
    1. titular pessoa COLETIVA com NIF começado por 5 ou 6   -> app.compliance.nif
    2. email GENÉRICO da empresa (geral@, info@, ...)         -> app.compliance.email
    3. minimização: singulares/não-endereçáveis descartados   -> app.compliance.minimizacao
    4. cruzamento com lista de oposição (DGC) + opt-out        -> app.compliance.optout

Nada neste pacote envia emails, descobre emails à escala, nem persiste dados
de pessoas singulares. É só o filtro e o andaime de prova.
"""
from __future__ import annotations
