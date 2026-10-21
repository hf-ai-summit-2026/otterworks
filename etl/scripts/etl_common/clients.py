"""Factories for the boto3 and psycopg2 clients used by the ETL scripts.

Each script builds its clients once in ``main()`` and passes them to the
stages that need them, instead of constructing a fresh client per call site.
"""

from contextlib import contextmanager
from typing import Iterator

import boto3
import psycopg2

from etl_common.config import AwsConfig, DatabaseConfig


def aws_session(aws: AwsConfig) -> boto3.session.Session:
    return boto3.session.Session(
        aws_access_key_id=aws.access_key,
        aws_secret_access_key=aws.secret_key,
        region_name=aws.region,
    )


def s3_client(aws: AwsConfig):
    return aws_session(aws).client("s3")


def sqs_client(aws: AwsConfig):
    return aws_session(aws).client("sqs")


def dynamodb_table(aws: AwsConfig, table_name: str):
    return aws_session(aws).resource("dynamodb").Table(table_name)


@contextmanager
def pg_connection(db: DatabaseConfig) -> Iterator["psycopg2.extensions.connection"]:
    """Open a PostgreSQL connection that is always closed on exit.

    The transaction is committed on success and rolled back on error.
    """
    conn = psycopg2.connect(
        host=db.host,
        port=db.port,
        dbname=db.database,
        user=db.user,
        password=db.password,
    )
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
