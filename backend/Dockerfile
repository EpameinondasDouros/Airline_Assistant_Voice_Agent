FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY agents ./agents
COPY testing ./testing
COPY start.sh ./start.sh

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e .

RUN chmod +x /app/start.sh

EXPOSE 8000

CMD ["./start.sh"]
