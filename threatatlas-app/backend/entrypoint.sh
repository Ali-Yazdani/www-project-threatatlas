#!/bin/sh
set -e

pdm run alembic upgrade head

exec pdm run uvicorn app.main:app --host 0.0.0.0 --port 8000
