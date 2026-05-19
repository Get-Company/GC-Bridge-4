#!/usr/bin/env sh
set -eu

run_if_enabled() {
    flag="$1"
    shift
    if [ "${flag}" = "true" ]; then
        echo "Running: $*"
        "$@"
    fi
}

if [ -n "${POSTGRES_HOST:-}" ]; then
    python - <<'PY'
import os
import socket
import time

host = os.environ["POSTGRES_HOST"]
port = int(os.environ.get("POSTGRES_PORT", "5432"))
deadline = time.monotonic() + int(os.environ.get("POSTGRES_WAIT_TIMEOUT", "60"))

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
PY
fi

run_if_enabled "${RUN_DJANGO_CHECK:-true}" python manage.py check
run_if_enabled "${RUN_COLLECTSTATIC:-false}" python manage.py collectstatic --noinput
run_if_enabled "${RUN_MIGRATIONS:-false}" python manage.py migrate --noinput

echo "Starting: $*"

exec "$@"
