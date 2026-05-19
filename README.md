# GC-Bridge-4

Django integration bridge between Microtech and Shopware 6.

The supported deployment target is an Ubuntu Linux server running Docker Compose. Windows Scheduled Tasks, Caddy/Uvicorn service deployment, and direct local Microtech COM workers are obsolete for this repository.

## Contents

- [Project Rules](#project-rules)
- [Local Development](#local-development)
- [Ubuntu Deployment](#ubuntu-deployment)
- [Runtime Commands](#runtime-commands)
- [Environment](#environment)
- [Celery Tasks](#celery-tasks)
- [Adminer](#adminer)

## Project Rules

- Keep secrets out of git. Use `.env` locally and on the server.
- New models must inherit `BaseModel`.
- New admin classes must inherit `BaseAdmin`.
- New services must inherit `BaseService`.
- Local Python commands must use `.venv/bin/python`.
- Do not run local database operations unless a local database was intentionally started.

## Local Development

Install dependencies:

```bash
uv sync
```

Start the local Docker services:

```bash
docker compose up -d db redis
```

Run Django commands through the virtualenv:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Build the Sphinx handbook:

```bash
make -C docs inventory
make -C docs html
```

## Ubuntu Deployment

Install Docker Engine and the Docker Compose plugin on the Ubuntu server, then clone the repository to:

```bash
/opt/GC-Bridge-4
```

Create `/opt/GC-Bridge-4/.env` with the required environment variables. Then build and start the full stack:

```bash
cd /opt/GC-Bridge-4
docker compose build
docker compose up -d
```

The Compose stack contains:

- `web`: Gunicorn/Django. The entrypoint waits for Postgres and runs `check`, `collectstatic`, and `migrate` before Gunicorn starts.
- `nginx`: HTTP reverse proxy and static/media file serving.
- `db`: PostgreSQL.
- `redis`: Celery broker/result backend.
- `celery`: Celery worker.
- `celery-beat`: Celery scheduler.
- `adminer`: optional database UI behind the `tools` profile.

Install the systemd unit if the stack should start on boot:

```bash
sudo cp deploy/linux/gc-bridge.service /etc/systemd/system/gc-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable gc-bridge
sudo systemctl start gc-bridge
```

Check status and logs:

```bash
sudo systemctl status gc-bridge
docker compose ps
docker compose logs -f web nginx celery celery-beat
```

Deploy a new version:

```bash
cd /opt/GC-Bridge-4
git fetch --tags origin
git pull --ff-only
docker compose build
docker compose up -d --remove-orphans
```

## Runtime Commands

Run Django management commands inside the web container:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py sync_status
```

Product sync:

```bash
docker compose exec web python manage.py scheduled_product_sync --limit 100
docker compose exec web python manage.py microtech_sync_products --all --limit 100
docker compose exec web python manage.py shopware_sync_products --all --limit 100 --batch-size 50
```

Order sync:

```bash
docker compose exec web python manage.py shopware_sync_open_orders
docker compose exec web python manage.py microtech_order_upsert <BESTELLNUMMER>
```

## Environment

Minimal server variables:

```bash
DJANGO_SECRET_KEY=
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=example.com,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.com,http://localhost

POSTGRES_DB=gc_bridge_4
POSTGRES_USER=gc_bridge_4
POSTGRES_PASSWORD=

SHOPWARE6_SHOP_URL=
SHOPWARE6_ADMIN_API_URL=
SHOPWARE6_ID=
SHOPWARE6_SECRET=

MICROTECH_GRAPHQL_HOST=10.0.0.5
MICROTECH_GRAPHQL_URL=http://10.0.0.5:8888/graphql/
```

`MICROTECH_GRAPHQL_URL` has priority. If it is empty, GC-Bridge builds the endpoint from `MICROTECH_GRAPHQL_HOST`, optional `MICROTECH_GRAPHQL_PORT` defaulting to `8888`, optional `MICROTECH_GRAPHQL_SCHEME` defaulting to `http`, and optional `MICROTECH_GRAPHQL_PATH` defaulting to `graphql`.

Entrypoint flags:

```bash
RUN_DJANGO_CHECK=true
RUN_COLLECTSTATIC=true
RUN_MIGRATIONS=true
CELERY_WORKER_CONCURRENCY=2
```

The web service enables these by default. Celery worker and beat disable them.
The Celery worker starts with `--concurrency=${CELERY_WORKER_CONCURRENCY:-2}`.

## Celery Tasks

The admin sidebar contains `System > Celery Tasks` for superusers. It can enqueue these tasks:

- `products.scheduled_product_sync`
- `products.microtech_sync_products`
- `products.shopware_sync_products`
- `products.shopware_force_product_image_uploads`
- `mappei.scrape_daily_prices`
- `orders.shopware_sync_open_orders`
- `orders.microtech_order_upsert`
- `customer.microtech_customer_upsert`
- `customer.microtech_customer_lookup`
- `hr.sync_holidays`
- `hr.year_transition`

`System > Celery Scheduler` uses `django-celery-beat` and stores schedules in the database.
After migrations are applied, create `CrontabSchedule` or `IntervalSchedule` entries and attach them to `PeriodicTask` records.
The registered Celery task dropdown includes the tasks above.

Default static beat settings are still present as fallback/seed-style schedules:

```bash
CELERY_SCHEDULED_PRODUCT_SYNC_ENABLED=true
CELERY_SCHEDULED_PRODUCT_SYNC_HOUR=*
CELERY_SCHEDULED_PRODUCT_SYNC_MINUTE=0
CELERY_SHOPWARE_OPEN_ORDERS_SYNC_ENABLED=false
```

## Adminer

Adminer is optional and only starts with the `tools` profile:

```bash
docker compose --profile tools up -d adminer
```

Connection values:

- Server: `db`
- User: value of `POSTGRES_USER`
- Password: value of `POSTGRES_PASSWORD`
- Database: value of `POSTGRES_DB`
