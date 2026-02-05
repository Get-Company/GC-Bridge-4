# GC-Bridge-4

Django-based integration bridge project.

## Base Classes (Abstract)

Use these as the default foundation across the project:

- `BaseModel` (`core/models/base.py`) provides `created_at`/`updated_at` fields.
- `BaseAdmin` (`core/admin.py`) provides Unfold-based admin defaults.
- `BaseService` (`core/services/base.py`) provides basic CRUD helpers.

## Installation (Local Dev)

1. Install Python 3.12+ and Git.
2. Install Docker + Docker Compose (needed for PostgreSQL/Adminer).
3. Create a virtual environment (optional but recommended).
4. Install dependencies:
   - `uv sync` (recommended), or
   - `python -m pip install -r requirements.txt`
5. Create `.env` in project root (see example below).
6. Start database services: `docker compose up -d`.
7. Run migrations: `python manage.py migrate`.
8. Create admin user: `python manage.py createsuperuser`.
9. Start the dev server: `python manage.py runserver`.
10. Open Adminer at `http://localhost:8082`.

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
