"""Shared normalization and validation.

Every adapter goes through this module, so the rules cannot drift per source.
Nothing here is ever allowed to substitute a default for a missing business
key: a record either satisfies the contract or it is rejected with a reason.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from .countries import ISO_3166_1_ALPHA_2
from .geometry import GeometryError, normalize as normalize_geometry
from .models import (
    CanonicalRecord,
    RecordRejected,
    RejectionReason,
    SourceMetadata,
    SourceRecord,
    Uncertainty,
    UncertaintyBasis,
)

_REGION_PATTERN = re.compile(r"^[A-Z0-9]{1,3}$")


def normalize_and_validate(
    record: SourceRecord,
    *,
    source_id_prefix: str,
    fetched_at: datetime,
) -> CanonicalRecord:
    """Turn one :class:`SourceRecord` into a validated :class:`CanonicalRecord`.

    Raises :class:`RecordRejected` on the first breach of the contract.
    """
    metadata = SourceMetadata(
        source_id=_source_id(record.source_key, source_id_prefix),
        source_date=_source_date(record.source_date),
        fetched_at=fetched_at,
        country_code=_country_code(record.country),
        region_code=_region_code(record.region),
    )
    geom = _geom(record.geometry)
    return CanonicalRecord(
        metadata=metadata,
        attributes=_attributes(record.attributes),
        geom=geom,
        uncertainty=_uncertainty(
            record.positional_accuracy_m,
            record.uncertainty_basis,
            has_geometry=geom is not None,
        ),
    )


def _source_id(source_key: Any, prefix: str) -> str:
    key = "" if source_key is None else str(source_key).strip()
    if not key:
        raise RecordRejected(
            RejectionReason.MISSING_SOURCE_ID,
            "source record has no identifier",
        )
    return f"{prefix}{key}"


def _country_code(value: Any) -> str:
    code = "" if value is None else str(value).strip().upper()
    if not code:
        raise RecordRejected(
            RejectionReason.MISSING_COUNTRY_CODE,
            "country_code is required and must not be defaulted",
        )
    if code not in ISO_3166_1_ALPHA_2:
        raise RecordRejected(
            RejectionReason.INVALID_COUNTRY_CODE,
            f"{code!r} is not an ISO 3166-1 alpha-2 country code",
        )
    return code


def _region_code(value: Any) -> str | None:
    if value is None:
        return None
    code = str(value).strip().upper()
    if not code:
        return None
    if not _REGION_PATTERN.match(code):
        raise RecordRejected(
            RejectionReason.INVALID_REGION_CODE,
            f"{code!r} is not a subdivision code of the form AA / A1 / AAA",
        )
    return code


def _source_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = "" if value is None else str(value).strip()
    if not text:
        raise RecordRejected(
            RejectionReason.MISSING_SOURCE_DATE,
            "source_date is part of the data contract and must be present",
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise RecordRejected(
            RejectionReason.INVALID_SOURCE_DATE,
            f"{text!r} is not an ISO-8601 date (YYYY-MM-DD)",
        ) from exc


def _attributes(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RecordRejected(
            RejectionReason.INVALID_ATTRIBUTES,
            f"attributes must be a mapping, got {type(value).__name__}",
        )

    attributes = {str(key): item for key, item in value.items()}
    try:
        json.dumps(attributes)
    except (TypeError, ValueError) as exc:
        raise RecordRejected(
            RejectionReason.INVALID_ATTRIBUTES,
            f"attributes are not JSON-serializable: {exc}",
        ) from exc
    return attributes


def _geom(value: Any) -> dict[str, Any] | None:
    try:
        return normalize_geometry(value)
    except GeometryError as exc:
        raise RecordRejected(RejectionReason.INVALID_GEOMETRY, str(exc)) from exc


def _uncertainty(accuracy: Any, basis: Any, *, has_geometry: bool) -> Uncertainty:
    return Uncertainty(
        positional_accuracy_m=_positional_accuracy(accuracy, has_geometry=has_geometry),
        basis=_uncertainty_basis(basis),
    )


def _positional_accuracy(value: Any, *, has_geometry: bool) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        # Not stated. Stays None so downstream reads "unknown", never "exact".
        return None

    if not has_geometry:
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            "positional accuracy was stated for a record that has no position",
        )

    try:
        accuracy = float(str(value).strip())
    except ValueError as exc:
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            f"positional accuracy {value!r} is not a number of metres",
        ) from exc

    if not math.isfinite(accuracy):
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            "positional accuracy must be a finite number of metres",
        )
    if accuracy < 0:
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            f"positional accuracy {accuracy} m is negative; an accuracy is a radius",
        )
    if accuracy == 0:
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            "an accuracy of 0 m claims a perfect position; "
            "leave it unset if the source did not state one",
        )
    return accuracy


def _uncertainty_basis(value: Any) -> UncertaintyBasis:
    if value is None or (isinstance(value, str) and not value.strip()):
        return UncertaintyBasis.UNKNOWN
    try:
        return UncertaintyBasis(str(value).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(basis.value for basis in UncertaintyBasis)
        raise RecordRejected(
            RejectionReason.INVALID_UNCERTAINTY,
            f"{value!r} is not a known uncertainty basis (expected one of: {allowed})",
        ) from exc
