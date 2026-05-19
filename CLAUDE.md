# CLAUDE.md

## Deployment

GC-Bridge deploys to an Ubuntu Linux server through Docker Compose.

- Project path: `/opt/GC-Bridge-4`
- Runtime stack: `docker-compose.yml`
- Web entrypoint: `docker/entrypoint.sh`
- Reverse proxy: `nginx` service with `docker/nginx.conf`
- Background jobs: `celery` and `celery-beat`
- Optional boot integration: `deploy/linux/gc-bridge.service`

Windows Scheduled Tasks, Caddy/Uvicorn deployment, and local Microtech COM workers are obsolete for this repository.

## Deploy Flow

Pushing a version tag triggers `.github/workflows/deploy.yml` on a Linux self-hosted runner:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The runner checks out the tag in `/opt/GC-Bridge-4`, writes `VERSION`, builds the image, and runs:

```bash
docker compose up -d --remove-orphans
```

The web container entrypoint waits for Postgres, then runs `manage.py check`, `collectstatic`, and `migrate` before Gunicorn starts.

## Useful Commands

```bash
cd /opt/GC-Bridge-4
docker compose ps
docker compose logs -f web nginx celery celery-beat
docker compose exec web python manage.py check
```

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
