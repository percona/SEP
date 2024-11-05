#!/bin/sh

# Wait for Redis to be available
echo "Waiting for Redis..."
while ! nc -z redis 6379; do
  sleep 1
done
echo "Redis started"

celery -A app.tasks.celery worker --loglevel=info
