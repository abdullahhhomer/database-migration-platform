FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir dbt-databricks

COPY migration_platform /app/migration_platform

WORKDIR /app/migration_platform

CMD ["dbt", "--version"]