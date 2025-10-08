#!/bin/sh

# Wait for Redis to be available
echo "Waiting for Redis..."
while ! nc -z redis 6379; do
  sleep 1
done
echo "Redis started"

# Wait for PostgreSQL to be available
echo "Waiting for postgres..."
while ! nc -z sep-db 5432; do
  sleep 1
done
echo "PostgreSQL started"

celery -A app.celery "$@"
