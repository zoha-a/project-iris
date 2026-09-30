"""Adapter for the geospatial Dutch fixture.

Demonstrates that a second source is a subclass and nothing else: different
file format, different property names, different country, same core.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..adapter import Clock, SourceAdapter
from ..geometry import GeoJSONGeometry
from ..models import SourceRecord

#: CRS names this adapter accepts. A source in any other CRS needs an explicit
#: reprojection step rather than a silent reinterpretation of its coordinates.
_SUPPORTED_CRS = {
    "urn:ogc:def:crs:OGC:1.3:CRS84",
    "urn:ogc:def:crs:EPSG::4326",
    "EPSG:4326",
}


class GeoJsonSitesAdapter(SourceAdapter):
    """Reads features from a GeoJSON ``FeatureCollection``."""

    source_name = "nl_ge_geojson"

    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        super().__init__(clock=clock)
        self.path = Path(path)

    @property
    def source_uri(self) -> str:
        return str(self.path)

    def extract(self) -> Iterator[Mapping[str, Any]]:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if document.get("type") != "FeatureCollection":
            raise ValueError(f"{self.path} is not a GeoJSON FeatureCollection")
        _assert_supported_crs(document)
        yield from document.get("features", [])

    def to_source_record(self, raw: Mapping[str, Any]) -> SourceRecord:
        properties = raw.get("properties") or {}
        return SourceRecord(
            source_key=properties.get("id"),
            country=properties.get("land"),
            region=properties.get("prov"),
            source_date=properties.get("peildatum"),
            attributes={
                "name": properties.get("naam"),
                "area_m2": properties.get("opp_m2"),
            },
            geometry=GeoJSONGeometry(raw.get("geometry")),
            positional_accuracy_m=properties.get("nauwkeurigheid_m"),
            uncertainty_basis=properties.get("basis"),
        )


def _assert_supported_crs(document: Mapping[str, Any]) -> None:
    crs = document.get("crs")
    if crs is None:
        return  # GeoJSON defaults to CRS84, which is what we want.
    name = (crs.get("properties") or {}).get("name")
    if name not in _SUPPORTED_CRS:
        raise ValueError(f"unsupported CRS {name!r}; expected CRS84 / EPSG:4326")
