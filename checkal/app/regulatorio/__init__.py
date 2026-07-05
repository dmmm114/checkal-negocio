"""Pipeline regulatório do CheckAL: deteção de regulamentos municipais de AL no DRE.

Camada A (MVP): descarrega o PDF integral gratuito da 2.ª série do Diário da República,
extrai texto, isola a Parte H (Autarquias Locais), filtra por keywords de Alojamento
Local e mapeia MUNICÍPIO→concelho, alimentando `eventos_regulatorios` — que a camada IA
(:mod:`app.ia`) tria (Haiku) e transforma em alertas citados (Sonnet).

Ver SPEC-DRE.md neste diretório para o contrato dos módulos e as fontes VERIFICADAS.
"""
from __future__ import annotations
