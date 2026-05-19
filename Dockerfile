###########
# BUILDER #
###########

FROM localhost/sep:builder AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FASTAPI_ENV=production_docker

####################
# FRONTEND BUILDER #
####################

FROM node:22-slim AS frontend-builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@11.1.2 --activate

COPY frontend/ .

RUN pnpm install --frozen-lockfile && pnpm build

#########
# FINAL #
#########

# Use an official Python runtime as a parent image
FROM docker.io/library/python:3.11.14-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        fontconfig \
        fonts-dejavu \
        shared-mime-info && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create the sep system user
RUN groupadd --gid 1001 sep && \
    useradd --gid sep --shell /usr/sbin/nologin --home-dir /home/sep --uid 1001 --create-home sep

# Create the appropriate directories
ENV HOME=/home/sep
ENV APP_HOME=$HOME/app
RUN install -d -o 1001 -g 1001 -m 0750 $APP_HOME
WORKDIR $APP_HOME

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends netcat-openbsd && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/src/sep/wheels /wheels
COPY --from=builder /usr/src/sep/requirements.txt .
RUN pip install --no-cache-dir wheel
RUN pip install --no-cache-dir /wheels/*

# Copy entrypoint.sh
COPY ./entrypoint.sh .
COPY ./entrypoint_celery.sh .
COPY --chown=0:1001 --chmod=440 ./alembic.ini .
RUN chmod +x $APP_HOME/entrypoint.sh
RUN chmod +x $APP_HOME/entrypoint_celery.sh

# TODO: Always use .env.docker even if there's a .env
#COPY ./.env.docker .

# Copy project
ADD --chown=0:1001 --chmod=440 bundle.tgz $APP_HOME

# Copy frontend build artifacts
COPY --from=frontend-builder --chown=0:1001 /app/packages/shell/dist/ $APP_HOME/frontend/dist/

# Chown all the files to the sep system user
RUN chmod -R u+X,g+X $APP_HOME

# Change to the sep system user
USER sep

# Run entrypoint.sh
ENTRYPOINT ["/home/sep/app/entrypoint.sh"]
