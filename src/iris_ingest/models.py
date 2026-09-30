"""The canonical record contract shared by every IRIS source adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from .geometry import GeometrySource, to_ewkb_hex


class RejectionReason(StrEnum):
    """Why a source record did not make it into staging."""

    MISSING_SOURCE_ID = "missing_source_id"
    MISSING_COUNTRY_CODE = "missing_country_code"
    INVALID_COUNTRY_CODE = "invalid_country_code"
    MISSING_SOURCE_DATE = "missing_source_date"
    INVALID_SOURCE_DATE = "invalid_source_date"
    INVALID_REGION_CODE = "invalid_region_code"
    INVALID_GEOMETRY = "invalid_geometry"
    INVALID_ATTRIBUTES = "invalid_attributes"
    INVALID_UNCERTAINTY = "invalid_uncertainty"
    MAPPING_ERROR = "mapping_error"


class UncertaintyBasis(StrEnum):
    """How the values on a record were arrived at."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    DERIVED = "derived"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Uncertainty:
    """How much a record should be trusted, stated rather than assumed.

    ``positional_accuracy_m`` is a radius in metres. ``None`` means the source
    did not state one, which is *not* the same as zero: downstream code must
    treat an unknown accuracy as unknown, never as an exact position.
    """

    positional_accuracy_m: float | None = None
    basis: UncertaintyBasis = UncertaintyBasis.UNKNOWN

    @property
    def is_stated(self) -> bool:
        """True when the source told us anything at all about confidence."""
        return self.positional_accuracy_m is not None or self.basis is not UncertaintyBasis.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "positional_accuracy_m": self.positional_accuracy_m,
            "basis": str(self.basis),
        }


#: The only honest default: we were told nothing.
UNKNOWN_UNCERTAINTY = Uncertainty()


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One record as an adapter sees it: fields renamed, values still raw.

    Adapters produce these. Cleaning, typing and validation belong to the core,
    so every source is held to identical rules.
    """

    source_key: Any
    country: Any
    region: Any
    source_date: Any
    attributes: Mapping[str, Any] = field(default_factory=dict)
    geometry: GeometrySource | None = None
    # Uncertainty as the source stated it. Left unset means "not stated", which
    # the core turns into an explicit unknown rather than an implied certainty.
    positional_accuracy_m: Any = None
    uncertainty_basis: Any = None


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Provenance carried by every canonical record."""

    source_id: str
    source_date: date
    fetched_at: datetime
    country_code: str
    region_code: str | None


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    """The one shape downstream IRIS code is allowed to depend on."""

    metadata: SourceMetadata
    attributes: Mapping[str, Any]
    geom: Mapping[str, Any] | None
    uncertainty: Uncertainty = UNKNOWN_UNCERTAINTY

    @property
    def country_code(self) -> str:
        return self.metadata.country_code

    @property
    def source_id(self) -> str:
        return self.metadata.source_id

    def to_dict(self) -> dict[str, Any]:
        """Flatten to the documented wire shape, with a stable key order."""
        return {
            "country_code": self.metadata.country_code,
            "region_code": self.metadata.region_code,
            "source_id": self.metadata.source_id,
            "source_date": self.metadata.source_date.isoformat(),
            "fetched_at": _iso_utc(self.metadata.fetched_at),
            "attributes": dict(self.attributes),
            "geom": dict(self.geom) if self.geom is not None else None,
            "uncertainty": self.uncertainty.to_dict(),
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def geom_ewkb_hex(self) -> str | None:
        """PostGIS-ready hex for a ``geometry(Geometry, 4326)`` column."""
        return to_ewkb_hex(dict(self.geom) if self.geom is not None else None)


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    """A record that failed the contract, kept for auditing rather than dropped."""

    reason: RejectionReason
    message: str
    source_name: str
    source_key: str | None
    raw: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_key": self.source_key,
            "reason": str(self.reason),
            "message": self.message,
            "raw": _jsonable(self.raw),
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one adapter run."""

    source_name: str
    source_uri: str
    records: tuple[CanonicalRecord, ...]
    rejections: tuple[RejectedRecord, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.records)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)

    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rejection in self.rejections:
            counts[str(rejection.reason)] = counts.get(str(rejection.reason), 0) + 1
        return dict(sorted(counts.items()))


class RecordRejected(Exception):
    """Internal signal that a record breaches the contract."""

    def __init__(self, reason: RejectionReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _iso_utc(value: datetime) -> str:
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return {str(key): str(item) for key, item in dict(value).items()}
    return value
