# syntax=docker/dockerfile:1

# Stage aparte para el frontend (React+Vite), mismo patrón que el resto de la
# familia: node no hace falta en la imagen final, sólo el resultado del build.
#
# `npm ci` alcanza sin credenciales porque `libra-ui` es un repo PÚBLICO, como
# el resto de los motores. Cuando la familia pase a privada hay que agregar acá
# el mount de la deploy key y el `insteadOf`, igual que LibraDesk:
#   RUN --mount=type=ssh,id=libra-ui,target=/tmp/ssh.sock SSH_AUTH_SOCK=... \
#       git config --global url."ssh://git@github.com/...".insteadOf "https://..."
FROM node:20-slim AS frontend-build
WORKDIR /frontend
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build
# 🔴 `npm run build` devuelve 0 aunque `tsc -b` haya fallado y no haya escrito
# nada (medido el 2026-08-18: 2 errores de TypeScript, sin `dist/`, exit 0).
# Sin esta línea la imagen se construye igual y sirve un 404 donde iba la SPA.
RUN test -f dist/index.html || { echo "ERROR: el build del frontend no dejo dist/index.html"; exit 1; }

FROM python:3.12-slim

# Huso horario del ecosistema: UTC-3 fijo, sin horario de verano.
ENV TZ=America/Argentina/Buenos_Aires \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl git \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

# Horneado FUERA de /app a propósito: el docker-compose de dev monta `./:/app`
# entero para el reload de Python, y eso taparía cualquier build copiado
# adentro. `app/asgi.py` mira primero acá.
COPY --from=frontend-build /frontend/dist /opt/frontend-dist

RUN useradd -m -u 10001 libracargo && chown -R libracargo /app
USER libracargo

EXPOSE 8000

# El healthcheck consulta la base: si PostgreSQL no responde, el contenedor no
# se reporta sano. Falla cerrado a propósito.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/salud || exit 1

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
