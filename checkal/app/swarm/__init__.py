"""Camada de GOVERNAÇÃO do enxame de agentes (Fase C do prompt-mestre).

Módulos deterministas que os subcomandos `manage.py` dos agentes usam:
  - :mod:`app.swarm.fila`  — fila de revisão 1-clique (enfileirar fail-closed,
    drain lease/backoff, tokens de aprovação, gate DGC);
  - :mod:`app.swarm.tetos` — tetos de custo LLM, flag PAUSA_LLM, escalação.

Nada aqui envia, publica, cobra ou toca a rede: é a cola determinista entre o
backbone e os agentes single-shot, sempre reversível-até-ao-gate.
"""
