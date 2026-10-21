#!/usr/bin/env python3
# storage_cleanup_daily.py - Daily orphaned S3 object cleanup
# Lists S3 objects, compares with DynamoDB metadata, quarantines orphans,
# generates storage savings report
#
# Owner: data-team@otterworks.dev
# TODO ETL-091: Add S3 lifecycle rules instead of manual cleanup (2019-11-20)
# TODO ETL-156: Parallelize S3 listing for large buckets (deferred Q1 2020)
# TODO ETL-203: Add dry-run mode for testing (never implemented)

import json
import logging
import sys
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError

from etl_common.clients import dynamodb_table, s3_client
from etl_common.config import load_config
from etl_common.logging_setup import setup_logging

logger = logging.getLogger("storage_cleanup_daily")

FILES_PREFIX = "files/"
QUARANTINE_PREFIX = "quarantined"
DYNAMODB_TABLE = "otterworks-file-metadata"
S3_USD_PER_GB_MONTH = 0.023


# ---------------------------------------------------------------- extract


def extract_objects(s3, bucket):
    logger.info("Listing objects in s3://%s/%s", bucket, FILES_PREFIX)
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=FILES_PREFIX):
        for obj in page.get("Contents", []):
            objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            })
    logger.info(
        "Found %d objects in S3 (%d bytes total)", len(objects), sum(o["size"] for o in objects)
    )
    return objects


def extract_referenced_keys(table):
    logger.info("Scanning DynamoDB table %s for metadata references...", DYNAMODB_TABLE)
    referenced = set()
    scan_kwargs = {"ProjectionExpression": "s3_key"}
    while True:
        response = table.scan(**scan_kwargs)
        for item in response.get("Items", []):
            s3_key = item.get("s3_key", "")
            if s3_key:
                referenced.add(s3_key)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    logger.info("Found %d S3 keys referenced in metadata", len(referenced))
    return referenced


def extract(s3, table, bucket):
    return extract_objects(s3, bucket), extract_referenced_keys(table)


# -------------------------------------------------------------- transform


def transform(objects, referenced_keys):
    orphaned = [obj for obj in objects if obj["key"] not in referenced_keys]
    orphaned_bytes = sum(obj["size"] for obj in orphaned)
    logger.info(
        "Found %d orphaned objects (%.2f MB)", len(orphaned), orphaned_bytes / (1024 * 1024)
    )
    return orphaned


def build_report(ds, objects, orphaned, moved_count, failed_count, quarantine_bucket):
    total_objects = len(objects)
    total_size_bytes = sum(o["size"] for o in objects)
    orphaned_count = len(orphaned)
    orphaned_bytes = sum(o["size"] for o in orphaned)
    savings_gb = orphaned_bytes / (1024 ** 3)

    return {
        "report_type": "storage_cleanup",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "inventory": {
            "total_objects": total_objects,
            "total_size_bytes": total_size_bytes,
            "total_size_gb": round(total_size_bytes / (1024 ** 3), 4),
        },
        "orphans": {
            "orphaned_objects": orphaned_count,
            "orphaned_bytes": orphaned_bytes,
            "orphaned_size_gb": round(savings_gb, 4),
            "orphan_percentage": round(
                (orphaned_count / total_objects * 100) if total_objects else 0, 2
            ),
        },
        "cleanup": {
            "objects_quarantined": moved_count,
            "objects_failed": failed_count,
            "quarantine_bucket": quarantine_bucket,
        },
        "savings": {
            "storage_freed_gb": round(savings_gb, 4),
            "estimated_monthly_savings_usd": round(savings_gb * S3_USD_PER_GB_MONTH, 4),
        },
    }


# ------------------------------------------------------------------- load


def quarantine(s3, source_bucket, quarantine_bucket, ds, orphaned):
    """Move orphans to the quarantine bucket; returns (moved, failed)."""
    if not orphaned:
        logger.info("No orphaned objects to quarantine")
        return 0, 0

    logger.info("Moving %d orphaned objects to quarantine...", len(orphaned))
    moved_count = 0
    failed_count = 0
    for obj in orphaned:
        source_key = obj["key"]
        try:
            s3.copy_object(
                Bucket=quarantine_bucket,
                Key="%s/%s/%s" % (QUARANTINE_PREFIX, ds, source_key),
                CopySource={"Bucket": source_bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
            s3.delete_object(Bucket=source_bucket, Key=source_key)
            moved_count += 1
        except (BotoCoreError, ClientError) as e:
            logger.warning("Failed to quarantine %s: %s", source_key, e)
            failed_count += 1

    logger.info(
        "Quarantined %d objects (%d failed) to s3://%s/%s/%s/",
        moved_count, failed_count, quarantine_bucket, QUARANTINE_PREFIX, ds,
    )
    return moved_count, failed_count


def load_report(s3, bucket, ds, report):
    s3.put_object(
        Bucket=bucket,
        Key="reports/storage-cleanup/%s/report.json" % ds,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )
    logger.info(
        "Storage cleanup report: %d orphans quarantined, %.4f GB freed, ~$%.4f/month saved",
        report["cleanup"]["objects_quarantined"],
        report["orphans"]["orphaned_bytes"] / (1024 ** 3),
        report["savings"]["estimated_monthly_savings_usd"],
    )


def load(s3, s3_buckets, ds, objects, orphaned):
    moved_count, failed_count = quarantine(
        s3, s3_buckets.file_storage_bucket, s3_buckets.quarantine_bucket, ds, orphaned
    )
    report = build_report(
        ds, objects, orphaned, moved_count, failed_count, s3_buckets.quarantine_bucket
    )
    load_report(s3, s3_buckets.data_lake_bucket, ds, report)


# ------------------------------------------------------------------- main


def main():
    logger.info("storage_cleanup_daily.py starting...")
    config = load_config(require=("aws", "s3"))
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    s3 = s3_client(config.aws)

    objects, referenced_keys = extract(
        s3, dynamodb_table(config.aws, DYNAMODB_TABLE), config.s3.file_storage_bucket
    )
    orphaned = transform(objects, referenced_keys)
    load(s3, config.s3, ds, objects, orphaned)
    logger.info("storage_cleanup_daily.py completed successfully")


if __name__ == "__main__":
    setup_logging("storage_cleanup_daily")
    try:
        main()
    except Exception as e:
        logger.critical("%s", e)
        sys.exit(1)
