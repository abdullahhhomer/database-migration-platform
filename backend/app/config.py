"""
Connection settings for the targets.

Credentials are read from AWS Secrets Manager first (the way a real AWS
deployment would do it) and fall back to environment variables, so the
platform still runs if the secrets have not been created yet.
"""

import json
import os
import threading

from app import aws


ALL_TARGETS = ("databricks", "sqlserver", "mongodb")

_secret_cache: dict[str, dict] = {}
_secret_lock = threading.Lock()


def get_secret(name: str) -> dict:
    """Returns a JSON secret as a dict, or {} if it is unavailable."""
    with _secret_lock:
        if name in _secret_cache:
            return _secret_cache[name]

    try:
        response = aws.client("secretsmanager").get_secret_value(SecretId=name)
        value = json.loads(response["SecretString"])
    except Exception:
        # Do not cache failures: moto may simply not be up yet.
        return {}

    with _secret_lock:
        _secret_cache[name] = value

    return value


def _pick(secret: dict, key: str, env_name: str, default=None):
    value = secret.get(key)
    if value in (None, ""):
        value = os.getenv(env_name, default)
    return value


def configured_targets() -> list[str]:
    raw = os.getenv("MIGRATION_TARGETS", ",".join(ALL_TARGETS))
    targets = [t.strip() for t in raw.split(",") if t.strip()]
    return [t for t in targets if t in ALL_TARGETS]


def default_workers() -> int:
    return max(1, int(os.getenv("MIGRATION_WORKERS", "4")))


def databricks_settings() -> dict:
    secret = get_secret(aws.SECRET_DATABRICKS)
    host = (_pick(secret, "host", "DATABRICKS_HOST", "") or "").strip()
    host = host.removeprefix("https://").removeprefix("http://").strip("/")

    return {
        "host": host,
        "http_path": _pick(secret, "http_path", "DATABRICKS_HTTP_PATH", ""),
        "token": _pick(secret, "token", "DATABRICKS_TOKEN", ""),
        "catalog": _pick(secret, "catalog", "DATABRICKS_CATALOG", "migration_platform"),
        "schema": os.getenv("DATABRICKS_SCHEMA", "bronze") or "bronze",
    }


def databricks_configured() -> bool:
    s = databricks_settings()
    return bool(s["host"] and s["http_path"] and s["token"])


def sqlserver_settings() -> dict:
    secret = get_secret(aws.SECRET_SQLSERVER)

    return {
        "host": _pick(secret, "host", "SQLSERVER_HOST", "sqlserver"),
        "port": int(_pick(secret, "port", "SQLSERVER_PORT", "1433")),
        "user": _pick(secret, "username", "SQLSERVER_USER", "sa"),
        "password": _pick(secret, "password", "SQLSERVER_PASSWORD", ""),
        "database": _pick(secret, "database", "SQLSERVER_DATABASE", "migration_target"),
    }


def mongodb_settings() -> dict:
    secret = get_secret(aws.SECRET_MONGODB)

    return {
        "uri": _pick(secret, "uri", "MONGO_URI", "mongodb://mongodb:27017"),
        "database": _pick(secret, "database", "MONGO_DATABASE", "migration_target"),
    }
