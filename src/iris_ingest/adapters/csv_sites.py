"""Adapter for the tabular German fixture.

Source quirks handled here and nowhere else: the country column is named
``country``, location arrives as two scalar columns, and every value is text.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..adapter import Clock, SourceAdapter
from ..geometry import LatLon
from ..models import SourceRecord


class CsvSitesAdapter(SourceAdapter):
    """Reads site rows from a delimited text file."""

    source_name = "de_nw_csv"
    source_id_prefix = "fixture-"

    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        super().__init__(clock=clock)
        self.path = Path(path)

    @property
    def source_uri(self) -> str:
        return str(self.path)

    def extract(self) -> Iterator[Mapping[str, Any]]:
        with self.path.open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)

    def to_source_record(self, raw: Mapping[str, Any]) -> SourceRecord:
        lat, lon = raw.get("lat"), raw.get("lon")
        return SourceRecord(
            source_key=raw.get("site_id"),
            country=raw.get("country"),
            region=raw.get("region"),
            source_date=raw.get("recorded_on"),
            attributes={
                "name": _text(raw.get("name")),
                "area_m2": _integer(raw.get("area_m2")),
            },
            # Absent coordinates mean "location unknown", which is allowed.
            # A half-present pair is a defect and is left for the core to reject.
            geometry=None if _blank(lat) and _blank(lon) else LatLon(lat=lat, lon=lon),
            positional_accuracy_m=raw.get("accuracy_m"),
            uncertainty_basis=raw.get("basis"),
        )


def _blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def _text(value: Any) -> str | None:
    return None if _blank(value) else str(value).strip()


def _integer(value: Any) -> int | None:
    if _blank(value):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None
