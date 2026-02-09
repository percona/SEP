#!/bin/sh

# Wait for Casdoor to be available
echo "Waiting for Casdoor..."
while ! nc -z casdoor 8000; do
    sleep 1
done
echo "Casdoor started"

# Wait for PostgreSQL to be available
echo "Waiting for postgres..."
while ! nc -z sep-db 5432; do
    sleep 1
done
echo "PostgreSQL started"

# Apply migrations
alembic --name="$1" upgrade head

# Start the FastAPI app
python -m "app.$1.main"
