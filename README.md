# music-app

Maloja-compatible scrobble receiver that writes directly to PostgreSQL. Designed as a drop-in target for [multi-scrobbler](https://github.com/FoXXMD/multi-scrobbler)'s Maloja client, providing real-time ingestion without the Maloja intermediary.

## Architecture

```
Spotify ──→ Multi-Scrobbler ──→ music-app (port 42010) ──→ PostgreSQL
Plex ─────→ Multi-Scrobbler ──→ music-app (port 42010) ──→ PostgreSQL
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/apis/mlj_1/serverinfo` | Server info (version, health) |
| GET | `/apis/mlj_1/scrobbles` | Recent scrobbles (for dedup) |
| GET | `/apis/mlj_1/test?key=...` | API key validation |
| POST | `/apis/mlj_1/newscrobble` | Submit a scrobble |
| GET | `/health` | Container health check |

## Database

Schema in `schema.sql`. Four tables: `artist`, `track`, `track_artist`, `scrobble`.

Deduplication via `UNIQUE (listened_at, track_id)` — retries are silently ignored with `ON CONFLICT DO NOTHING`.

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_HOST` | PostgreSQL hostname | `postgres` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_USER` | PostgreSQL user | `scrobble` |
| `POSTGRES_PASSWORD` | PostgreSQL password | (required) |
| `MALOJA_API_KEY` | API key for authentication | (required) |

## Build & Run

```bash
podman build -t music-app:latest .
```

Managed via systemd quadlet at `/etc/containers/systemd/scrobble-receiver.container`.

## Multi-scrobbler setup

Configure as a Maloja client in `/config/maloja.json`:

```json
[
  {
    "name": "MusicApp",
    "enable": true,
    "configureAs": "client",
    "data": {
      "url": "http://scrobble-receiver:42010",
      "apiKey": "your-api-key"
    }
  }
]
```
