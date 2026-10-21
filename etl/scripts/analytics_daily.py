#!/usr/bin/env python3
# analytics_daily.py - Daily analytics aggregation pipeline
# Pulls events from SQS + DynamoDB, aggregates, loads to S3 and PostgreSQL
#
# Owner: data-team@otterworks.dev
# TODO ETL-142: Move credentials to secrets manager (deferred Q3 2020)
# TODO ETL-201: Add unit tests (never prioritized)

import gzip
import io
import json
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import psycopg2
from botocore.exceptions import BotoCoreError, ClientError

from etl_common.clients import dynamodb_table, pg_connection, s3_client, sqs_client
from etl_common.config import DatabaseConfig, load_config
from etl_common.logging_setup import setup_logging

logger = logging.getLogger("analytics_daily")

# TODO ETL-089: Make queue URL configurable per environment (2019-11-15)
SQS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/otterworks-analytics"
SQS_MAX_MESSAGES = 10000
SQS_BATCH_SIZE = 10
SQS_MAX_CONSECUTIVE_ERRORS = 3
DYNAMODB_TABLE = "otterworks-analytics-events"
USER_ID_FIELDS = ["ownerId", "editedBy", "authorId", "deletedBy", "userId"]
TOP_USERS_LIMIT = 100

UPSERT_SQL = """
    INSERT INTO analytics_daily_summary (
        report_date, active_users, active_documents, active_files,
        total_events, documents_created, documents_edited,
        comments_added, files_uploaded, files_shared,
        files_deleted, bytes_uploaded, updated_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (report_date) DO UPDATE SET
        active_users = EXCLUDED.active_users,
        active_documents = EXCLUDED.active_documents,
        active_files = EXCLUDED.active_files,
        total_events = EXCLUDED.total_events,
        documents_created = EXCLUDED.documents_created,
        documents_edited = EXCLUDED.documents_edited,
        comments_added = EXCLUDED.comments_added,
        files_uploaded = EXCLUDED.files_uploaded,
        files_shared = EXCLUDED.files_shared,
        files_deleted = EXCLUDED.files_deleted,
        bytes_uploaded = EXCLUDED.bytes_uploaded,
        updated_at = NOW();
"""


# ---------------------------------------------------------------- extract


def extract_sqs_events(sqs):
    logger.info("Polling SQS queue: %s", SQS_QUEUE_URL)
    events = []
    messages_processed = 0
    consecutive_errors = 0

    while messages_processed < SQS_MAX_MESSAGES:
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=SQS_BATCH_SIZE,
                WaitTimeSeconds=5,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
            consecutive_errors = 0
        except (BotoCoreError, ClientError) as e:
            # TODO ETL-103: Add dead-letter queue for failed SQS calls (2020-01-08)
            consecutive_errors += 1
            logger.warning("SQS receive failed (%d consecutive): %s", consecutive_errors, e)
            if consecutive_errors >= SQS_MAX_CONSECUTIVE_ERRORS:
                logger.error("Too many SQS failures, giving up")
                break
            continue

        messages = response.get("Messages", [])
        if not messages:
            logger.info("No more messages after %d processed", messages_processed)
            break

        entries_to_delete = []
        for msg in messages:
            try:
                event = json.loads(msg["Body"])
                events.append(event)
                entries_to_delete.append(
                    {"Id": msg["MessageId"], "ReceiptHandle": msg["ReceiptHandle"]}
                )
            except (ValueError, KeyError, TypeError) as e:
                # TODO ETL-103: Add dead-letter queue for malformed messages (2020-01-08)
                logger.warning(
                    "Skipping malformed SQS message %s: %s", msg.get("MessageId", "<no id>"), e
                )

        if entries_to_delete:
            sqs.delete_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=entries_to_delete)

        messages_processed += len(messages)

    logger.info("Extracted %d events from SQS", len(events))
    return events


def _decimals_to_native(item):
    for k, v in item.items():
        if isinstance(v, Decimal):
            item[k] = int(v) if v == int(v) else float(v)
    return item


def extract_dynamodb_events(table, ds):
    events = []
    scan_kwargs = {
        "FilterExpression": "begins_with(event_date, :ds)",
        "ExpressionAttributeValues": {":ds": ds},
    }
    while True:
        response = table.scan(**scan_kwargs)
        events.extend(_decimals_to_native(item) for item in response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    logger.info("Extracted %d events from DynamoDB for %s", len(events), ds)
    return events


def extract(sqs, table, ds):
    events = extract_sqs_events(sqs) + extract_dynamodb_events(table, ds)
    logger.info("Total events to process: %d", len(events))
    return events


# -------------------------------------------------------------- transform


def _parse_hour(ts):
    if isinstance(ts, str):
        try:
            return "%02d" % datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
        except ValueError:
            pass
    return "00"


def _nested_counts(df, outer, inner):
    """{outer_value: {inner_value: count}} in first-seen order."""
    counts = df.groupby([outer, inner], sort=False, dropna=False).size()
    nested = {}
    for (outer_value, inner_value), count in counts.items():
        nested.setdefault(outer_value, {})[inner_value] = int(count)
    return nested


def _distinct(df, mask, column):
    if column not in df.columns:
        return set()
    return set(df.loc[mask, column].dropna().unique())


def build_events_frame(events):
    # TODO ETL-155: This pandas approach is slow for large datasets, consider PySpark (2020-03-22)
    df = pd.DataFrame(events)

    if "event_type" in df.columns and "eventType" not in df.columns:
        df["eventType"] = df["event_type"]
    if "eventType" not in df.columns:
        df["eventType"] = "unknown"

    df["resolved_user_id"] = "unknown"
    for col in USER_ID_FIELDS:
        if col in df.columns:
            mask = (df["resolved_user_id"] == "unknown") & df[col].notna() & (df[col] != "")
            df.loc[mask, "resolved_user_id"] = df.loc[mask, col]

    df["hour"] = df["timestamp"].apply(_parse_hour) if "timestamp" in df.columns else "00"
    return df


def transform(events):
    df = build_events_frame(events)
    event_type = df["eventType"]
    type_counts = event_type.value_counts(dropna=False)

    def count(name):
        return int(type_counts.get(name, 0))

    active_users = set(df["resolved_user_id"].unique()) - {"unknown"}

    user_summaries = [
        {"user_id": uid, "actions": actions, "total": sum(actions.values())}
        for uid, actions in _nested_counts(df, "resolved_user_id", "eventType").items()
    ]
    user_summaries.sort(key=lambda x: x["total"], reverse=True)
    user_summaries = user_summaries[:TOP_USERS_LIMIT]

    active_documents = _distinct(
        df, event_type.isin(["document_created", "document_edited"]), "documentId"
    )
    active_files = _distinct(
        df, event_type.isin(["file_uploaded", "file_shared", "file_deleted"]), "fileId"
    )
    bytes_uploaded = 0
    if "sizeBytes" in df.columns:
        bytes_uploaded = int(df.loc[event_type == "file_uploaded", "sizeBytes"].fillna(0).sum())

    hourly_breakdown = dict(sorted(_nested_counts(df, "hour", "eventType").items()))

    document_metrics = {
        "created": count("document_created"),
        "edited": count("document_edited"),
        "comments": count("comment_added"),
    }
    file_metrics = {
        "uploaded": count("file_uploaded"),
        "shared": count("file_shared"),
        "deleted": count("file_deleted"),
        "bytes_uploaded": bytes_uploaded,
    }
    summary = {
        "active_users": len(active_users),
        "active_documents": len(active_documents),
        "active_files": len(active_files),
        "total_events": len(events),
        "documents_created": document_metrics["created"],
        "documents_edited": document_metrics["edited"],
        "comments_added": document_metrics["comments"],
        "files_uploaded": file_metrics["uploaded"],
        "files_shared": file_metrics["shared"],
        "files_deleted": file_metrics["deleted"],
        "bytes_uploaded": bytes_uploaded,
    }

    logger.info(
        "Aggregation complete: %d events, %d active users, %d documents, %d files",
        summary["total_events"],
        summary["active_users"],
        summary["active_documents"],
        summary["active_files"],
    )
    return {
        "summary": summary,
        "hourly_breakdown": hourly_breakdown,
        "user_summaries": user_summaries,
        "document_metrics": document_metrics,
        "file_metrics": file_metrics,
    }


def build_report(ds, result):
    hourly_breakdown = result["hourly_breakdown"]
    peak_hour = None
    if hourly_breakdown:
        hour, counts = max(hourly_breakdown.items(), key=lambda x: sum(x[1].values()))
        peak_hour = {"hour": hour, "event_count": sum(counts.values())}

    return {
        "report_type": "daily_analytics",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": result["summary"],
        "highlights": {
            "peak_hour": peak_hour,
            "most_active_users": [u["user_id"] for u in result["user_summaries"][:5]],
        },
        "document_metrics": result["document_metrics"],
        "file_metrics": result["file_metrics"],
    }


# ------------------------------------------------------------------- load


def partition_key(analytics_prefix, ds):
    return "%s/year=%s/month=%s/day=%s" % (analytics_prefix, ds[:4], ds[5:7], ds[8:10])


def _gzip_jsonl(records):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for record in records:
            gz.write(json.dumps(record).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def load_data_lake(s3, bucket, prefix, result):
    summary_key = "%s/summary.json.gz" % prefix
    s3.put_object(
        Bucket=bucket,
        Key=summary_key,
        Body=gzip.compress(json.dumps(result["summary"], indent=2).encode("utf-8")),
    )
    logger.info("Uploaded summary to s3://%s/%s", bucket, summary_key)

    s3.put_object(
        Bucket=bucket,
        Key="%s/hourly_breakdown.json.gz" % prefix,
        Body=gzip.compress(json.dumps(result["hourly_breakdown"], indent=2).encode("utf-8")),
    )
    s3.put_object(
        Bucket=bucket,
        Key="%s/top_users.jsonl.gz" % prefix,
        Body=_gzip_jsonl(result["user_summaries"]),
    )
    logger.info("Loaded analytics data to s3://%s/%s", bucket, prefix)


def load_postgres(db: DatabaseConfig, ds, summary):
    logger.info("Connecting to PostgreSQL at %s:%d/%s", db.host, db.port, db.database)
    params = (
        ds,
        summary["active_users"],
        summary["active_documents"],
        summary["active_files"],
        summary["total_events"],
        summary["documents_created"],
        summary["documents_edited"],
        summary["comments_added"],
        summary["files_uploaded"],
        summary["files_shared"],
        summary["files_deleted"],
        summary["bytes_uploaded"],
    )
    try:
        with pg_connection(db) as conn, conn.cursor() as cursor:
            cursor.execute(UPSERT_SQL, params)
        logger.info("Updated PostgreSQL daily aggregates for %s", ds)
    except psycopg2.Error as e:
        # Don't exit -- still try to generate the report.
        logger.error("PostgreSQL update failed: %s", e)


def load_report(s3, bucket, ds, report):
    s3.put_object(
        Bucket=bucket,
        Key="reports/analytics/daily/%s/report.json" % ds,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )
    logger.info(
        "Generated daily analytics report: %d events, %d active users",
        report["summary"]["total_events"],
        report["summary"]["active_users"],
    )


def load(s3, db: DatabaseConfig, bucket, analytics_prefix, ds, result):
    load_data_lake(s3, bucket, partition_key(analytics_prefix, ds), result)
    load_postgres(db, ds, result["summary"])
    load_report(s3, bucket, ds, build_report(ds, result))


# ------------------------------------------------------------------- main


def main():
    logger.info("analytics_daily.py starting...")
    config = load_config(require=("aws", "database", "s3"))
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    logger.info("Processing analytics for date: %s", ds)

    events = extract(
        sqs_client(config.aws), dynamodb_table(config.aws, DYNAMODB_TABLE), ds
    )
    if not events:
        logger.warning("No events found, exiting")
        sys.exit(0)

    result = transform(events)
    load(
        s3_client(config.aws),
        config.database,
        config.s3.data_lake_bucket,
        config.s3.analytics_prefix,
        ds,
        result,
    )
    logger.info("analytics_daily.py completed successfully")


if __name__ == "__main__":
    setup_logging("analytics_daily")
    try:
        main()
    except Exception as e:
        logger.critical("%s", e)
        sys.exit(1)
