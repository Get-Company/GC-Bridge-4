# GC-Bridge-4

Django-based integration bridge project.

## Quickstart

1. Ensure Python 3.12+ is available.
2. Install dependencies: `uv sync` or `python -m pip install -r requirements.txt`.
3. Start DB services: `docker compose up -d`.
4. Run migrations: `python manage.py migrate`.
5. Create admin user: `python manage.py createsuperuser`.
6. Start the dev server: `python manage.py runserver`.

## Docker (PostgreSQL + Adminer)

This repo ships a local Docker setup for PostgreSQL plus Adminer.

1. Ensure Docker + Docker Compose are installed.
2. Start services: `docker compose up -d`.
3. Adminer UI: `http://localhost:8082`.

Connection parameters (Adminer):

- System: PostgreSQL
- Server: `localhost` (use `db` if Django runs inside Docker)
- Username: from `.env` (`POSTGRES_USER`)
- Password: from `.env` (`POSTGRES_PASSWORD`)
- Database: from `.env` (`POSTGRES_DB`)

## Environment

Create or update `.env` (not committed) for DB access:

```
POSTGRES_DB=gc_bridge_4
POSTGRES_USER=gc_bridge_4
POSTGRES_PASSWORD=gc_bridge_4_dev
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Django reads `.env` on startup and uses PostgreSQL by default. Update `POSTGRES_HOST` to `db` when running Django inside Docker on the server.

## Notes

- Configuration and secrets should live in a local `.env` file (not committed).
