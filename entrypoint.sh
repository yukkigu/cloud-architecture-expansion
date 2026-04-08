#!/bin/sh
set -e

# Apply database migrations
alembic upgrade head
# Start the FastAPI application using Uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 8080