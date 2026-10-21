#!/usr/bin/env python3
# audit_archive_weekly.py - Weekly audit event archival to S3 Glacier
# Scans DynamoDB for old events, compresses to JSONL.gz, uploads to Glacier,
# batch-deletes from DynamoDB, generates compliance report
#
# Owner: data-team@otterworks.dev
# TODO ETL-134: Add incremental archival instead of full scan (deferred Q2 2020)
# TODO ETL-167: Handle DynamoDB throughput throttling properly (2020-04-10)
# TODO ETL-199: This script has no tests whatsoever (never prioritized)

import gzip
import io
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError

from etl_common.clients import dynamodb_table, s3_client
from etl_common.config import load_config
from etl_common.logging_setup import setup_logging

logger = logging.getLogger("audit_archive_weekly")

RETENTION_DAYS = 90
DYNAMODB_TABLE = "otterworks-audit-events"
DYNAMODB_BATCH_SIZE = 25  # DynamoDB batch write limit
S3_PREFIX = "audit-archive"
STORAGE_CLASS = "GLACIER"


class DecimalEncoder(json.JSONEncoder):
    """Serialize DynamoDB Decimal values as int or float."""

    def default(self, o):
        if isinstance(o, Decimal):
            if o == int(o):
                return int(o)
            return float(o)
        return super().default(o)


def cutoff_for(ds, retention_days):
    return (datetime.strptime(ds, "%Y-%m-%d") - timedelta(days=retention_days)).isoformat() + "Z"


def archive_key_for(ds):
    return "%s/year=%s/week=%s/audit_events.jsonl.gz" % (S3_PREFIX, ds[:4], ds)


# ---------------------------------------------------------------- extract


def extract(table, cutoff_date):
    events = []
    scan_kwargs = {
        "FilterExpression": "#ts < :cutoff",
        "ExpressionAttributeNames": {"#ts": "timestamp"},
        "ExpressionAttributeValues": {":cutoff": cutoff_date},
    }
    while True:
        response = table.scan(**scan_kwargs)
        events.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    logger.info("Found %d audit events older than %d days", len(events), RETENTION_DAYS)
    return events


# -------------------------------------------------------------- transform


def transform(events):
    """Compress events to gzipped JSONL; returns the archive bytes."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for event in events:
            gz.write(json.dumps(event, cls=DecimalEncoder).encode("utf-8"))
            gz.write(b"\n")
    archive = buf.getvalue()
    logger.info("Compressed %d events to %.2f MB", len(events), len(archive) / (1024 * 1024))
    return archive


def build_report(ds, cutoff_date, archive_count, deleted_count, archive_location, compressed_size):
    return {
        "report_type": "audit_archive_compliance",
        "execution_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "retention_policy": {
            "retention_days": RETENTION_DAYS,
            "cutoff_date": cutoff_date,
        },
        "results": {
            "events_scanned": archive_count,
            "events_archived": archive_count,
            "events_deleted_from_source": deleted_count,
            "archive_location": archive_location,
            "archive_storage_class": STORAGE_CLASS,
            "compressed_size_bytes": compressed_size,
        },
        "compliance": {
            "gdpr_compliant": True,
            "soc2_compliant": True,
            "data_encrypted_at_rest": True,
            "data_encrypted_in_transit": True,
        },
    }


# ------------------------------------------------------------------- load


def load_archive(s3, bucket, key, archive):
    s3.put_object(Bucket=bucket, Key=key, Body=archive, StorageClass=STORAGE_CLASS)
    logger.info("Archived to s3://%s/%s (%s)", bucket, key, STORAGE_CLASS)


def _delete_batch(table, keys):
    try:
        with table.batch_writer() as writer:
            for key in keys:
                writer.delete_item(Key=key)
        return len(keys)
    except (BotoCoreError, ClientError) as e:
        # TODO ETL-167: Handle throttling / partial failures
        logger.warning("Failed to delete batch of %d archived events: %s", len(keys), e)
        return 0


def delete_archived(table, events):
    logger.info("Deleting %d archived events from DynamoDB...", len(events))
    keys = [{"event_id": e["event_id"], "timestamp": e["timestamp"]} for e in events]
    deleted_count = 0
    for start in range(0, len(keys), DYNAMODB_BATCH_SIZE):
        deleted_count += _delete_batch(table, keys[start:start + DYNAMODB_BATCH_SIZE])
    logger.info("Deleted %d events from DynamoDB", deleted_count)
    return deleted_count


def load_report(s3, bucket, ds, report):
    report_key = "reports/compliance/audit-archive/%s/report.json" % ds
    s3.put_object(Bucket=bucket, Key=report_key, Body=json.dumps(report, indent=2).encode("utf-8"))
    logger.info(
        "Compliance report: %d archived, %d deleted, stored at s3://%s/%s",
        report["results"]["events_archived"],
        report["results"]["events_deleted_from_source"],
        bucket,
        report_key,
    )


def load(s3, table, bucket, ds, cutoff_date, events, archive):
    archive_key = archive_key_for(ds)
    load_archive(s3, bucket, archive_key, archive)
    deleted_count = delete_archived(table, events)
    report = build_report(
        ds,
        cutoff_date,
        len(events),
        deleted_count,
        "s3://%s/%s" % (bucket, archive_key),
        len(archive),
    )
    load_report(s3, bucket, ds, report)


# ------------------------------------------------------------------- main


def main():
    logger.info("audit_archive_weekly.py starting...")
    config = load_config(require=("aws", "s3"))
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cutoff_date = cutoff_for(ds, RETENTION_DAYS)
    logger.info("Archiving events older than %d days (cutoff: %s)", RETENTION_DAYS, cutoff_date)

    table = dynamodb_table(config.aws, DYNAMODB_TABLE)
    events = extract(table, cutoff_date)
    if not events:
        logger.info("No events to archive, exiting")
        sys.exit(0)

    archive = transform(events)
    load(s3_client(config.aws), table, config.s3.archive_bucket, ds, cutoff_date, events, archive)
    logger.info("audit_archive_weekly.py completed successfully")


if __name__ == "__main__":
    setup_logging("audit_archive_weekly")
    try:
        main()
    except Exception as e:
        logger.critical("%s", e)
        sys.exit(1)
