# CheckAL — imagem da aplicação (FastAPI + crons). Python 3.12 slim.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências de sistema mínimas (psycopg binário não precisa de build; pg_dump p/ backups).
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# psycopg[binary] = driver Postgres em produção; gunicorn/uvicorn já em requirements.
RUN pip install -r requirements.txt "psycopg[binary]>=3.2"

COPY . .

EXPOSE 8000

# App factory (cria_app monta rotas + Jinja + static). 2 workers (idempotência já garantida
# por UNIQUE em stripe_session_id — ver FDS 2).
CMD ["uvicorn", "app.web.app:criar_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
