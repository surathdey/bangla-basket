# Bangla Basket backend image (FastAPI + Postgres client, no MongoDB).
# Build context is the refactor root (so brand.json at the root is included);
# the image layout mirrors the old deploy: code at /app/backend, web bundle
# at /app/backend/web_dist, brand.json at /app/brand.json.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# System deps: libpq is NOT needed (asyncpg is pure-Python + C extension
# bundled in the wheel); curl is for the container healthcheck.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY brand.json /app/brand.json
COPY schema.sql /app/schema.sql

# Local upload dirs (AI menu photos, delivery proofs, grocery images).
# In Compose these are a named volume; without it they live in the image layer.
RUN mkdir -p /app/backend/uploads/menu /app/backend/uploads/delivery \
             /app/backend/uploads/grocery

EXPOSE 8001

# Apply the schema, then serve. The backend binds 0.0.0.0:8001 inside the
# container; nginx (separate service) terminates TLS and proxies to it.
# DATABASE_URL must point at the Compose "postgres" service (see .env.example).
CMD ["sh", "-c", \
     "psql \"$DATABASE_URL\" -v ON_ERROR_STOP=1 -f /app/schema.sql && \
      exec uvicorn server:app --host 0.0.0.0 --port 8001"]
