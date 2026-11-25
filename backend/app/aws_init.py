"""
One-off bootstrap for the mocked AWS account (moto keeps everything in
memory, so this runs on every `docker compose up`).

Creates:
  - S3 bucket          migration-landing   (raw zone of the data lake)
  - Kinesis stream     cdc-changes         (CDC event stream)
  - DynamoDB table     cdc-checkpoints     (consumer checkpoints, like KCL)
  - Secrets Manager    migration/*         (target credentials)

Run with:  python -m app.aws_init
"""

import json
import os
import sys
import time

from botocore.exceptions import ClientError

from app import aws


def wait_for_endpoint(timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            aws.client("s3").list_buckets()
            return
        except Exception as error:
            if time.time() > deadline:
                raise RuntimeError(f"AWS endpoint not reachable: {error}") from error
            print("Waiting for AWS endpoint...", flush=True)
            time.sleep(2)


def ensure_bucket() -> None:
    s3 = aws.client("s3")
    try:
        s3.head_bucket(Bucket=aws.LANDING_BUCKET)
        print(f"S3 bucket exists: {aws.LANDING_BUCKET}")
    except ClientError:
        if aws.region() == "us-east-1":
            s3.create_bucket(Bucket=aws.LANDING_BUCKET)
        else:
            s3.create_bucket(
                Bucket=aws.LANDING_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": aws.region()},
            )
        print(f"Created S3 bucket: {aws.LANDING_BUCKET}")


def ensure_stream() -> None:
    kinesis = aws.client("kinesis")
    try:
        kinesis.describe_stream_summary(StreamName=aws.CDC_STREAM)
        print(f"Kinesis stream exists: {aws.CDC_STREAM}")
    except kinesis.exceptions.ResourceNotFoundException:
        kinesis.create_stream(
            StreamName=aws.CDC_STREAM,
            ShardCount=aws.CDC_STREAM_SHARDS,
        )
        kinesis.get_waiter("stream_exists").wait(
            StreamName=aws.CDC_STREAM,
            WaiterConfig={"Delay": 1, "MaxAttempts": 30},
        )
        print(
            f"Created Kinesis stream: {aws.CDC_STREAM} "
            f"({aws.CDC_STREAM_SHARDS} shards)"
        )


def ensure_checkpoint_table() -> None:
    dynamodb = aws.client("dynamodb")
    try:
        dynamodb.describe_table(TableName=aws.CHECKPOINT_TABLE)
        print(f"DynamoDB table exists: {aws.CHECKPOINT_TABLE}")
    except dynamodb.exceptions.ResourceNotFoundException:
        dynamodb.create_table(
            TableName=aws.CHECKPOINT_TABLE,
            KeySchema=[
                {"AttributeName": "consumer", "KeyType": "HASH"},
                {"AttributeName": "shard_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "consumer", "AttributeType": "S"},
                {"AttributeName": "shard_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"Created DynamoDB table: {aws.CHECKPOINT_TABLE}")


def put_secret(name: str, value: dict) -> None:
    sm = aws.client("secretsmanager")
    body = json.dumps(value)
    try:
        sm.create_secret(Name=name, SecretString=body)
        print(f"Created secret: {name}")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=name, SecretString=body)
        print(f"Updated secret: {name}")


def ensure_secrets() -> None:
    put_secret(
        aws.SECRET_SQLSERVER,
        {
            "engine": "sqlserver",
            "host": os.getenv("SQLSERVER_HOST", "sqlserver"),
            "port": int(os.getenv("SQLSERVER_PORT", "1433")),
            "username": os.getenv("SQLSERVER_USER", "sa"),
            "password": os.getenv("SQLSERVER_PASSWORD", ""),
            "database": os.getenv("SQLSERVER_DATABASE", "migration_target"),
        },
    )

    put_secret(
        aws.SECRET_MONGODB,
        {
            "engine": "mongodb",
            "uri": os.getenv("MONGO_URI", "mongodb://mongodb:27017"),
            "database": os.getenv("MONGO_DATABASE", "migration_target"),
        },
    )

    put_secret(
        aws.SECRET_DATABRICKS,
        {
            "host": os.getenv("DATABRICKS_HOST", ""),
            "http_path": os.getenv("DATABRICKS_HTTP_PATH", ""),
            "token": os.getenv("DATABRICKS_TOKEN", ""),
            "catalog": os.getenv("DATABRICKS_CATALOG", "migration_platform"),
        },
    )


def main() -> int:
    print(f"AWS endpoint: {aws.endpoint_url() or 'real AWS'} ({aws.region()})")
    wait_for_endpoint()
    ensure_bucket()
    ensure_stream()
    ensure_checkpoint_table()
    ensure_secrets()
    print("AWS resources ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
