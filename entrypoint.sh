#!/bin/sh

# Wait for Casdoor to be available
echo "Waiting for Casdoor..."
while ! nc -z casdoor 8000; do
  sleep 1
done
echo "Casdoor started"

# Start the FastAPI app
echo "Starting SEP app..."
poetry run python -m app.sep.main --logging=debug
