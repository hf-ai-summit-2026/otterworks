#!/usr/bin/env python3
# search_reindex_weekly.py - Weekly full reindex of MeiliSearch
# Clears MeiliSearch indices, paginates through document-service and
# file-service APIs, bulk-indexes into MeiliSearch, validates counts
#
# Owner: data-team@otterworks.dev
# TODO ETL-112: Add retry logic for transient API failures (2019-12-20)
# TODO ETL-145: Use connection pooling for service API requests (deferred Q3 2020)
# TODO ETL-188: Add timeout handling everywhere (never done)

import json
import logging
import sys
import time

import requests

from etl_common.config import ServicesConfig, load_config
from etl_common.logging_setup import setup_logging

logger = logging.getLogger("search_reindex_weekly")

DOCUMENTS_INDEX = "documents"
FILES_INDEX = "files"
API_PAGE_SIZE = 100
SETTINGS_TASK_TIMEOUT = 60
INDEX_TASK_TIMEOUT = 120
RANKING_RULES = ["words", "typo", "proximity", "attribute", "sort", "exactness"]

INDEX_SETTINGS = {
    DOCUMENTS_INDEX: {
        "searchableAttributes": ["title", "content", "tags"],
        "filterableAttributes": ["type", "owner_id", "tags", "created_at", "updated_at"],
        "sortableAttributes": ["updated_at", "created_at"],
        "rankingRules": RANKING_RULES,
    },
    FILES_INDEX: {
        "searchableAttributes": ["name", "tags", "mime_type"],
        "filterableAttributes": [
            "type", "owner_id", "mime_type", "folder_id", "tags", "created_at", "updated_at",
        ],
        "sortableAttributes": ["updated_at", "created_at", "size"],
        "rankingRules": RANKING_RULES,
    },
}


class MeiliSearch:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        if api_key:
            self.session.headers["Authorization"] = "Bearer %s" % api_key

    def request(self, method, path, body=None):
        data = json.dumps(body) if body is not None else None
        resp = self.session.request(method, "%s%s" % (self.base_url, path), data=data)
        resp.raise_for_status()
        return resp.json()

    def wait_for_task(self, task_uid, timeout):
        """Poll a task until it finishes; returns the last task payload seen."""
        task = {}
        if task_uid is None:
            return task
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.request("GET", "/tasks/%s" % task_uid)
            if task.get("status") in ("succeeded", "failed"):
                break
            time.sleep(1)
        return task

    def run_task(self, method, path, body=None, timeout=SETTINGS_TASK_TIMEOUT):
        task_uid = self.request(method, path, body).get("taskUid")
        return task_uid, self.wait_for_task(task_uid, timeout)

    def document_count(self, index):
        return self.request("GET", "/indexes/%s/stats" % index).get("numberOfDocuments", 0)


# ----------------------------------------------------------------- setup


def reset_indices(meili):
    logger.info("Clearing MeiliSearch indices...")
    for index in (DOCUMENTS_INDEX, FILES_INDEX):
        try:
            task_uid, task = meili.run_task("DELETE", "/indexes/%s" % index)
            if task.get("status") == "failed":
                logger.warning("Delete task %s failed", task_uid)
            logger.info("Deleted index: %s", index)
        except (requests.RequestException, ValueError) as e:
            logger.info("Index %s did not exist, skipping delete (%s)", index, e)

    for index in (DOCUMENTS_INDEX, FILES_INDEX):
        meili.run_task("POST", "/indexes", {"uid": index, "primaryKey": "id"})
        logger.info("Created index: %s", index)

    for index, settings in INDEX_SETTINGS.items():
        meili.run_task("PATCH", "/indexes/%s/settings" % index, settings)
    logger.info("MeiliSearch indices configured")


# ---------------------------------------------------------------- extract


def extract_pages(url, size_param, items_key):
    """Yield each non-empty page of items from a paginated service API."""
    page = 1
    while True:
        resp = requests.get(url, params={"page": page, size_param: API_PAGE_SIZE})
        resp.raise_for_status()
        data = resp.json()
        items = data.get(items_key, data.get("items", []))
        if not items:
            return
        yield items
        if len(items) < API_PAGE_SIZE:
            return
        page += 1


def extract_documents(document_service_url):
    return extract_pages("%s/api/v1/documents" % document_service_url, "size", "documents")


def extract_files(file_service_url):
    return extract_pages("%s/api/v1/files" % file_service_url, "page_size", "files")


# -------------------------------------------------------------- transform


def transform_document(doc):
    return {
        "id": doc.get("document_id", doc.get("id", "")),
        "title": doc.get("title", ""),
        "content": doc.get("content", ""),
        "owner_id": doc.get("owner_id", ""),
        "tags": doc.get("tags", []),
        "type": "document",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def transform_file(f):
    return {
        "id": f.get("file_id", f.get("id", "")),
        "name": f.get("file_name", f.get("name", "")),
        "owner_id": f.get("owner_id", ""),
        "mime_type": f.get("mime_type", ""),
        "folder_id": f.get("folder_id", ""),
        "size": f.get("size_bytes", f.get("size", 0)),
        "tags": f.get("tags", []),
        "type": "file",
        "created_at": f.get("created_at"),
        "updated_at": f.get("updated_at"),
    }


def transform(pages, transform_item):
    for page in pages:
        yield [transform_item(item) for item in page]


# ------------------------------------------------------------------- load


def load(meili, index, batches):
    indexed = 0
    for batch in batches:
        _, task = meili.run_task(
            "POST", "/indexes/%s/documents" % index, batch, timeout=INDEX_TASK_TIMEOUT
        )
        if task.get("status") == "failed":
            logger.warning("Index task failed: %s", task.get("error", {}))
        indexed += len(batch)
    logger.info("Indexed %d %s into %s", indexed, index, index)
    return indexed


def validate(meili, docs_indexed, files_indexed):
    logger.info("Validating index counts...")
    docs_count = meili.document_count(DOCUMENTS_INDEX)
    files_count = meili.document_count(FILES_INDEX)
    logger.info(
        "Validation: documents=%d (expected %d), files=%d (expected %d)",
        docs_count, docs_indexed, files_count, files_indexed,
    )
    if docs_count != docs_indexed:
        logger.error("Documents index count mismatch: %d != %d", docs_count, docs_indexed)
        sys.exit(1)
    if files_count != files_indexed:
        logger.error("Files index count mismatch: %d != %d", files_count, files_indexed)
        sys.exit(1)


# ------------------------------------------------------------------- main


def main():
    logger.info("search_reindex_weekly.py starting...")
    services: ServicesConfig = load_config(require=("services",)).services
    meili = MeiliSearch(services.meilisearch_url, services.meilisearch_api_key)

    reset_indices(meili)

    logger.info("Indexing documents from document-service...")
    docs_indexed = load(
        meili,
        DOCUMENTS_INDEX,
        transform(extract_documents(services.document_service_url), transform_document),
    )

    logger.info("Indexing files from file-service...")
    files_indexed = load(
        meili, FILES_INDEX, transform(extract_files(services.file_service_url), transform_file)
    )

    validate(meili, docs_indexed, files_indexed)
    logger.info("search_reindex_weekly.py completed successfully")


if __name__ == "__main__":
    setup_logging("search_reindex_weekly")
    try:
        main()
    except Exception as e:
        logger.critical("%s", e)
        sys.exit(1)
