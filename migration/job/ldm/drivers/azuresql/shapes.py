"""Registered stg.<table> column shapes, shared by the staging and validation collaborators."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...errors import ConfigError
from ...typemap import ColumnSpec


@dataclass
class _Shape:
    key_columns: tuple[str, ...]
    hash_columns: tuple[str, ...]
    specs: list[ColumnSpec]

    @property
    def target_columns(self) -> list[str]:
        return [c for s in self.specs for c in s.target_columns]


class ShapeRegistry:
    def __init__(self) -> None:
        self.tables: dict[str, _Shape] = {}

    def register(
        self, table: str, key_columns: Sequence[str], hash_columns: Sequence[str], specs: list[ColumnSpec]
    ) -> None:
        self.tables[table] = _Shape(tuple(key_columns), tuple(hash_columns), specs)

    def get(self, table: str) -> _Shape:
        if table not in self.tables:
            raise ConfigError(f"table {table} was not registered with the target driver")
        return self.tables[table]
