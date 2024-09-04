###########
# BUILDER #
###########

# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FASTAPI_ENV production

# Set the working directory in the container
WORKDIR /app

# install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc netcat-traditional

# Install dependencies
COPY pyproject.toml /app/
COPY poetry.lock /app/
RUN pip install --upgrade pip poetry
RUN poetry install

# Copy the current directory contents into the container at /code
COPY . /app/

# Copy the entrypoint script
COPY entrypoint.sh /app/entrypoint.sh

# Give execute permissions to the entrypoint script
RUN chmod +x /app/entrypoint.sh
