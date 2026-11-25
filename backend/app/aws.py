"""
AWS client factory.

Every AWS call in the platform goes through here. Locally, AWS_ENDPOINT_URL
points at the moto server (our stand-in for AWS). Against real AWS you just
remove AWS_ENDPOINT_URL and provide real credentials -- no code changes.
"""

import os
import threading

import boto3
from botocore.config import Config


LANDING_BUCKET = os.getenv("S3_LANDING_BUCKET", "migration-landing")
CDC_STREAM = os.getenv("KINESIS_STREAM", "cdc-changes")
CDC_STREAM_SHARDS = int(os.getenv("KINESIS_SHARDS", "2"))
CHECKPOINT_TABLE = os.getenv("DYNAMODB_CHECKPOINT_TABLE", "cdc-checkpoints")

SECRET_SQLSERVER = "migration/sqlserver"
SECRET_MONGODB = "migration/mongodb"
SECRET_DATABRICKS = "migration/databricks"

_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "standard"},
    connect_timeout=5,
    read_timeout=30,
)

_lock = threading.Lock()
_clients: dict[str, object] = {}


def endpoint_url() -> str | None:
    return os.getenv("AWS_ENDPOINT_URL") or None


def region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


def client(service: str):
    """Returns a cached, thread-safe boto3 client for the given service."""
    with _lock:
        if service not in _clients:
            _clients[service] = boto3.session.Session().client(
                service,
                region_name=region(),
                endpoint_url=endpoint_url(),
                config=_CONFIG,
            )
        return _clients[service]
