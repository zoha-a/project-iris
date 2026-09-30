"""Reusable source adapter contract for Project IRIS ingestion."""

from .adapter import SourceAdapter, run_all, utc_now
from .geometry import GeoJSONGeometry, GeometryError, LatLon, SRID_WGS84, to_ewkb_hex
from .models import (
    UNKNOWN_UNCERTAINTY,
    CanonicalRecord,
    IngestResult,
    RecordRejected,
    RejectedRecord,
    RejectionReason,
    SourceMetadata,
    SourceRecord,
    Uncertainty,
    UncertaintyBasis,
)
from .staging import JsonlRejectionWriter, JsonlStagingWriter, PostgresStagingWriter, StagingWriter

__all__ = [
    "CanonicalRecord",
    "GeoJSONGeometry",
    "GeometryError",
    "IngestResult",
    "JsonlRejectionWriter",
    "JsonlStagingWriter",
    "LatLon",
    "PostgresStagingWriter",
    "RecordRejected",
    "RejectedRecord",
    "RejectionReason",
    "SRID_WGS84",
    "SourceAdapter",
    "SourceMetadata",
    "SourceRecord",
    "StagingWriter",
    "UNKNOWN_UNCERTAINTY",
    "Uncertainty",
    "UncertaintyBasis",
    "run_all",
    "to_ewkb_hex",
    "utc_now",
]
