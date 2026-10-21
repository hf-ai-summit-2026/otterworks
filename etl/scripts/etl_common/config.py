"""Typed loader for the shared ETL ``config.ini``.

Credentials are still read from the INI file; moving them to a secrets
manager is tracked separately as ETL-142.
"""

import configparser
import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_CONFIG_PATH = "/opt/etl/config.ini"
CONFIG_PATH_ENV = "ETL_CONFIG_PATH"


@dataclass(frozen=True)
class AwsConfig:
    access_key: str
    secret_key: str
    region: str


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class ServicesConfig:
    document_service_url: str
    file_service_url: str
    meilisearch_url: str
    meilisearch_api_key: str


@dataclass(frozen=True)
class S3Config:
    data_lake_bucket: str
    file_storage_bucket: str
    quarantine_bucket: str
    archive_bucket: str
    analytics_prefix: str


@dataclass(frozen=True)
class EtlConfig:
    aws: Optional[AwsConfig]
    database: Optional[DatabaseConfig]
    services: Optional[ServicesConfig]
    s3: Optional[S3Config]


def _aws(parser: configparser.ConfigParser) -> AwsConfig:
    return AwsConfig(
        access_key=parser.get("aws", "access_key"),
        secret_key=parser.get("aws", "secret_key"),
        region=parser.get("aws", "region"),
    )


def _database(parser: configparser.ConfigParser) -> DatabaseConfig:
    return DatabaseConfig(
        host=parser.get("database", "host"),
        port=parser.getint("database", "port"),
        database=parser.get("database", "database"),
        user=parser.get("database", "user"),
        password=parser.get("database", "password"),
    )


def _services(parser: configparser.ConfigParser) -> ServicesConfig:
    return ServicesConfig(
        document_service_url=parser.get("services", "document_service_url"),
        file_service_url=parser.get("services", "file_service_url"),
        meilisearch_url=parser.get("services", "meilisearch_url"),
        meilisearch_api_key=parser.get("services", "meilisearch_api_key"),
    )


def _s3(parser: configparser.ConfigParser) -> S3Config:
    return S3Config(
        data_lake_bucket=parser.get("s3", "data_lake_bucket"),
        file_storage_bucket=parser.get("s3", "file_storage_bucket"),
        quarantine_bucket=parser.get("s3", "quarantine_bucket"),
        archive_bucket=parser.get("s3", "archive_bucket"),
        analytics_prefix=parser.get("s3", "analytics_prefix"),
    )


_SECTION_LOADERS = {
    "aws": _aws,
    "database": _database,
    "services": _services,
    "s3": _s3,
}


def load_config(path: Optional[str] = None, require: tuple = ()) -> EtlConfig:
    """Load ``config.ini`` into an :class:`EtlConfig`.

    Sections listed in ``require`` must be present and complete, otherwise
    ``configparser.Error`` is raised. Other sections are loaded when present
    and left as ``None`` when absent, so a script only depends on the
    sections it actually uses.
    """
    path = path or os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH
    parser = configparser.ConfigParser()
    parser.read(path)

    unknown = set(require) - set(_SECTION_LOADERS)
    if unknown:
        raise ValueError("Unknown config section(s): %s" % ", ".join(sorted(unknown)))

    sections = {}
    for name, loader in _SECTION_LOADERS.items():
        if name in require or parser.has_section(name):
            sections[name] = loader(parser)
        else:
            sections[name] = None
    return EtlConfig(**sections)
