###########
# BUILDER #
###########

FROM localhost/sep:builder as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FASTAPI_ENV production_docker

#########
# FINAL #
#########

# Use an official Python runtime as a parent image
FROM docker.io/library/python:3.11.14-alpine

# Install dependencies
RUN apk update && apk add --no-cache g++

# Create the sep system user
RUN addgroup --gid 1001 -S sep && \
    adduser -G sep --shell /bin/false --disabled-password -h /home/sep --uid 1001 sep

# Create the appropriate directories
ENV HOME=/home/sep
ENV APP_HOME=$HOME/app
RUN install -d -o 1001 -g 1001 -m 0750 $APP_HOME
WORKDIR $APP_HOME

# Install dependencies
RUN apk update && apk add --no-cache netcat-openbsd
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

# Chown all the files to the sep system user
RUN chmod -R u+X,g+X $APP_HOME

# Change to the sep system user
USER sep

# Run entrypoint.sh
ENTRYPOINT ["/home/sep/app/entrypoint.sh"]
