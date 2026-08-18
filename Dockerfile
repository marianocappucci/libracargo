FROM python:3.12-slim

# Huso horario del ecosistema: UTC-3 fijo, sin horario de verano.
ENV TZ=America/Argentina/Buenos_Aires \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd -m -u 10001 libracargo && chown -R libracargo /app
USER libracargo

EXPOSE 8000

# El healthcheck consulta la base: si PostgreSQL no responde, el contenedor
# no se reporta sano. Falla cerrado a propósito.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/salud || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
