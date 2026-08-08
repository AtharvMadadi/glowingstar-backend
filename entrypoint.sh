#!/bin/sh
set -e

echo "waiting for postgres..."
python - <<'PY'
import os, socket, time, urllib.parse
url = urllib.parse.urlparse(os.environ.get("DATABASE_URL", ""))
host, port = url.hostname or "db", url.port or 5432
for _ in range(60):
    try:
        socket.create_connection((host, port), timeout=2).close()
        print("postgres is up")
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("postgres did not become available")
PY

echo "ensuring judge runtime image is present..."
docker image inspect "${JUDGE_IMAGE:-python:3.11-slim}" >/dev/null 2>&1 \
  || docker pull "${JUDGE_IMAGE:-python:3.11-slim}"

echo "applying migrations..."
alembic upgrade head

echo "seeding problems..."
python scripts/seed_problems.py

echo "starting api..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
