#!/usr/bin/env python3
# user_activity_daily.py - Daily user activity report generation
# Queries PostgreSQL aggregates, reads per-user S3 data, generates
# activity reports, stores to S3 for admin-service consumption
#
# Owner: data-team@otterworks.dev
# TODO ETL-098: Optimize S3 reads with range requests (2019-12-01)
# TODO ETL-160: Cache PostgreSQL connection across runs (deferred Q2 2020)
# TODO ETL-210: Add email notification for report generation (never done)

import gzip
import json
import logging
import sys
import zlib
from datetime import datetime, timedelta, timezone

import psycopg2
from botocore.exceptions import BotoCoreError, ClientError

from etl_common.clients import pg_connection, s3_client
from etl_common.config import DatabaseConfig, load_config
from etl_common.logging_setup import setup_logging

logger = logging.getLogger("user_activity_daily")

LOOKBACK_DAYS = 30
S3_REPORTS_PREFIX = "reports/user-activity"
TOP_USERS_KEY = "analytics/daily/year=%s/month=%s/day=%s/top_users.jsonl.gz"
MISSING_KEY_CODES = {"NoSuchKey", "404"}

SUMMARY_COLUMNS = [
    "report_date",
    "active_users",
    "active_documents",
    "active_files",
    "total_events",
    "documents_created",
    "documents_edited",
    "comments_added",
    "files_uploaded",
    "files_shared",
    "files_deleted",
    "bytes_uploaded",
]

SUMMARY_SQL = """
    SELECT
        report_date,
        active_users,
        active_documents,
        active_files,
        total_events,
        documents_created,
        documents_edited,
        comments_added,
        files_uploaded,
        files_shared,
        files_deleted,
        bytes_uploaded
    FROM analytics_daily_summary
    WHERE report_date BETWEEN %s::date - (%s * interval '1 day') AND %s::date
    ORDER BY report_date;
"""


# ---------------------------------------------------------------- extract


def extract_daily_summaries(db: DatabaseConfig, ds, lookback_days):
    logger.info(
        "Querying PostgreSQL for analytics aggregates (lookback: %d days)...", lookback_days
    )
    try:
        with pg_connection(db) as conn, conn.cursor() as cursor:
            cursor.execute(SUMMARY_SQL, (ds, lookback_days, ds))
            rows = cursor.fetchall()
    except psycopg2.Error as e:
        logger.error("PostgreSQL query failed: %s", e)
        sys.exit(1)
    logger.info("Retrieved %d daily summary records", len(rows))
    return rows


def _parse_top_users(body, key, records):
    """Append each JSONL record in ``body`` to ``records``."""
    try:
        for line in gzip.decompress(body).decode("utf-8").strip().split("\n"):
            if line:
                records.append(json.loads(line))
    except (OSError, EOFError, zlib.error, UnicodeDecodeError, ValueError) as e:
        logger.warning("Skipping unreadable activity data at %s: %s", key, e)


def extract_user_activity(s3, bucket, ds, lookback_days):
    """Read the per-day top_users partitions written by analytics_daily."""
    logger.info("Reading per-user activity data from S3 (lookback: %d days)...", lookback_days)
    records = []
    execution_date = datetime.strptime(ds, "%Y-%m-%d")

    for day_offset in range(lookback_days):
        check_date = execution_date - timedelta(days=day_offset)
        key = TOP_USERS_KEY % (
            check_date.strftime("%Y"), check_date.strftime("%m"), check_date.strftime("%d")
        )
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as e:
            # Not every day has a partition.
            if e.response.get("Error", {}).get("Code") in MISSING_KEY_CODES:
                logger.debug("No activity data at s3://%s/%s", bucket, key)
            else:
                logger.warning("Failed to read s3://%s/%s: %s", bucket, key, e)
            continue
        except BotoCoreError as e:
            logger.warning("Failed to read s3://%s/%s: %s", bucket, key, e)
            continue
        _parse_top_users(body, key, records)

    return records


def extract(db: DatabaseConfig, s3, bucket, ds, lookback_days):
    rows = extract_daily_summaries(db, ds, lookback_days)
    user_records = extract_user_activity(s3, bucket, ds, lookback_days)
    return rows, user_records


# -------------------------------------------------------------- transform


def transform_daily_summaries(rows):
    summaries = []
    for row in rows:
        record = {}
        for col, val in zip(SUMMARY_COLUMNS, row):
            record[col] = val.isoformat() if hasattr(val, "isoformat") else val
        summaries.append(record)
    return summaries


def aggregate_user_activity(user_records, lookback_days):
    user_totals = {}
    for user_data in user_records:
        if not isinstance(user_data, dict):
            logger.warning("Skipping malformed activity record: %r", user_data)
            continue
        uid = user_data.get("user_id", "unknown")
        totals = user_totals.setdefault(
            uid, {"user_id": uid, "total_actions": 0, "active_days": 0, "actions_by_type": {}}
        )
        totals["total_actions"] += user_data.get("total", 0)
        totals["active_days"] += 1
        for action_type, count in user_data.get("actions", {}).items():
            totals["actions_by_type"][action_type] = (
                totals["actions_by_type"].get(action_type, 0) + count
            )

    user_list = sorted(user_totals.values(), key=lambda x: x["total_actions"], reverse=True)
    logger.info("Aggregated activity for %d users over %d days", len(user_list), lookback_days)
    return user_list


def build_report(ds, lookback_days, daily_summaries, user_list):
    total_events = sum(d.get("total_events", 0) for d in daily_summaries)
    peak_active_users = max((d.get("active_users", 0) for d in daily_summaries), default=0)
    avg_daily_events = total_events / len(daily_summaries) if daily_summaries else 0

    return {
        "report_type": "user_activity",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "trends": {
            "total_events": total_events,
            "peak_active_users": peak_active_users,
            "avg_daily_events": round(avg_daily_events, 2),
            "reporting_days": len(daily_summaries),
        },
        "daily_summaries": daily_summaries,
        "user_summaries": user_list[:500],
        "top_users": user_list[:20],
    }


def transform(rows, user_records, ds, lookback_days):
    daily_summaries = transform_daily_summaries(rows)
    user_list = aggregate_user_activity(user_records, lookback_days)
    return build_report(ds, lookback_days, daily_summaries, user_list)


# ------------------------------------------------------------------- load


def load(s3, bucket, ds, report):
    logger.info("Storing reports to S3...")
    body = json.dumps(report, indent=2, default=str).encode("utf-8")

    report_key = "%s/%s/activity_report.json" % (S3_REPORTS_PREFIX, ds)
    s3.put_object(Bucket=bucket, Key=report_key, Body=body)

    # Latest pointer for admin-service.
    s3.put_object(
        Bucket=bucket, Key="%s/latest/activity_report.json" % S3_REPORTS_PREFIX, Body=body
    )

    # Per-user summaries as JSONL for individual user lookups.
    user_summaries = report.get("user_summaries", [])
    if user_summaries:
        lines = [json.dumps(u, default=str) for u in user_summaries]
        s3.put_object(
            Bucket=bucket,
            Key="%s/%s/user_summaries.jsonl" % (S3_REPORTS_PREFIX, ds),
            Body=("\n".join(lines) + "\n").encode("utf-8"),
        )

    logger.info(
        "Stored activity report: %d user summaries at s3://%s/%s",
        len(user_summaries),
        bucket,
        report_key,
    )


# ------------------------------------------------------------------- main


def main():
    logger.info("user_activity_daily.py starting...")
    config = load_config(require=("aws", "database", "s3"))
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    bucket = config.s3.data_lake_bucket
    s3 = s3_client(config.aws)

    rows, user_records = extract(config.database, s3, bucket, ds, LOOKBACK_DAYS)
    report = transform(rows, user_records, ds, LOOKBACK_DAYS)
    load(s3, bucket, ds, report)
    logger.info("user_activity_daily.py completed successfully")


if __name__ == "__main__":
    setup_logging("user_activity_daily")
    try:
        main()
    except Exception as e:
        logger.critical("%s", e)
        sys.exit(1)
