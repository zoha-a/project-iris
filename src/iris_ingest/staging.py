"""Load-to-staging writers.

Staging is deliberately the last step and knows nothing about sources. JSONL is
the default so the pipeline runs from a clean checkout with no database; the
PostGIS writer uses the same canonical records and the migration in ``sql/``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import CanonicalRecord, RejectedRecord


@runtime_checkable
class StagingWriter(Protocol):
    """Anything that can persist canonical records."""

    def write(self, records: Iterable[CanonicalRecord]) -> int: ...


class JsonlStagingWriter:
    """Writes one canonical record per line. Deterministic given a fixed clock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, records: Iterable[CanonicalRecord]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(record.to_json_line())
                handle.write("\n")
                written += 1
        return written


class JsonlRejectionWriter:
    """Writes rejected records so failures are auditable instead of invisible."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, rejections: Iterable[RejectedRecord]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            for rejection in rejections:
                handle.write(rejection.to_json_line())
                handle.write("\n")
                written += 1
        return written


class PostgresStagingWriter:
    """Upserts canonical records into a PostGIS staging table.

    Optional: requires the ``postgres`` extra and a reachable database. The
    pipeline itself never needs credentials.
    """

    def __init__(self, dsn: str, source_name: str, table: str = "staging.source_record") -> None:
        self.dsn = dsn
        self.source_name = source_name
        self.table = table

    def write(self, records: Iterable[CanonicalRecord]) -> int:
        try:
            import psycopg
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - exercised only with the extra
            raise RuntimeError("PostgresStagingWriter needs: pip install 'iris-ingest[postgres]'") from exc

        rows = [
            (
                record.metadata.country_code,
                record.metadata.source_id,
                record.metadata.region_code,
                record.metadata.source_date,
                record.metadata.fetched_at,
                self.source_name,
                Jsonb(dict(record.attributes)),
                record.geom_ewkb_hex(),
                record.uncertainty.positional_accuracy_m,
                str(record.uncertainty.basis),
            )
            for record in records
        ]
        if not rows:
            return 0

        statement = f"""
            INSERT INTO {self.table} (
                country_code, source_id, region_code, source_date,
                fetched_at, source_name, attributes, geom,
                positional_accuracy_m, uncertainty_basis
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, ST_GeomFromEWKB(decode(%s, 'hex')), %s, %s)
            ON CONFLICT (country_code, source_id) DO UPDATE SET
                region_code = EXCLUDED.region_code,
                source_date = EXCLUDED.source_date,
                fetched_at  = EXCLUDED.fetched_at,
                attributes  = EXCLUDED.attributes,
                geom        = EXCLUDED.geom,
                positional_accuracy_m = EXCLUDED.positional_accuracy_m,
                uncertainty_basis     = EXCLUDED.uncertainty_basis
        """
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.executemany(statement, rows)
            connection.commit()
        return len(rows)
