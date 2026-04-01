## Stage 1: Build the React UI
FROM node:22-slim AS ui-build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

## Stage 2: Python API + static UI
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache .

COPY --from=ui-build /ui/dist static/

ENV STATIC_DIR=/app/static

EXPOSE 42010

ENTRYPOINT ["python", "-m"]
CMD ["music_app.receiver"]
