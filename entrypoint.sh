#!/bin/bash
set -e

echo "Starting AutoBlog Generator API..."

# Run database migrations
python -m alembic upgrade head

# Start FastAPI server
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
