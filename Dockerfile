###########
# BUILDER #
###########

# Use an official Python runtime as a parent image
FROM python:3.11-alpine AS builder

# Set work directory
WORKDIR /usr/src/sep

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FASTAPI_ENV production_docker

# Install system dependencies
RUN apk update && apk add --no-cache gcc

# Export requirements
RUN pip install --upgrade pip wheel poetry==1.8.3 poetry-plugin-export
COPY ./pyproject.toml ./poetry.lock /usr/src/sep/
RUN poetry export --with postgresql -f requirements.txt --output requirements.txt

# Build Wheel archives for requirements
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/sep/wheels -r requirements.txt


#########
# FINAL #
#########

# Use an official Python runtime as a parent image
FROM python:3.11-alpine

# Create directory for the sep user
RUN mkdir -p /home/sep

# Create the sep system user
RUN addgroup --gid 1001 -S sep && \
    adduser -G sep --shell /bin/false --disabled-password -H --uid 1001 sep

# Create the appropriate directories
ENV HOME=/home/sep
ENV APP_HOME=$HOME/app
RUN mkdir $APP_HOME
WORKDIR $APP_HOME

# Install dependencies
RUN apk update && apk add --no-cache netcat-openbsd
COPY --from=builder /usr/src/sep/wheels /wheels
COPY --from=builder /usr/src/sep/requirements.txt .
RUN pip install --upgrade pip wheel
RUN pip install --no-cache /wheels/*

# Copy entrypoint.sh
COPY ./entrypoint.sh .
COPY ./entrypoint_persistent.sh .
RUN chmod +x $APP_HOME/entrypoint.sh
RUN chmod +x $APP_HOME/entrypoint_persistent.sh

# TODO: Always use .env.docker even if there's a .env
COPY ./.env.docker .env

# Copy project
COPY . $APP_HOME

# Chown all the files to the sep system user
RUN chown -R sep:sep $APP_HOME

# Change to the sep system user
USER sep

# Run entrypoint.sh
ENTRYPOINT ["/home/sep/app/entrypoint.sh"]
