"""Core contract rules, exercised without going through a file."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from iris_ingest.geometry import LatLon
from iris_ingest.models import RecordRejected, RejectionReason, SourceRecord
from iris_ingest.validation import normalize_and_validate

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def build(**overrides) -> SourceRecord:
    defaults = {
        "source_key": "001",
        "country": "de",
        "region": "nw",
        "source_date": "2026-09-01",
        "attributes": {"name": "Test"},
        "geometry": None,
    }
    return SourceRecord(**{**defaults, **overrides})


def validate(record: SourceRecord, prefix: str = "fixture-"):
    return normalize_and_validate(record, source_id_prefix=prefix, fetched_at=NOW)


def test_country_and_region_are_trimmed_and_uppercased():
    record = validate(build(country=" de ", region=" nw "))
    assert record.metadata.country_code == "DE"
    assert record.metadata.region_code == "NW"


@pytest.mark.parametrize(
    ("country", "reason"),
    [
        (None, RejectionReason.MISSING_COUNTRY_CODE),
        ("", RejectionReason.MISSING_COUNTRY_CODE),
        ("   ", RejectionReason.MISSING_COUNTRY_CODE),
        ("XX", RejectionReason.INVALID_COUNTRY_CODE),
        ("DEU", RejectionReason.INVALID_COUNTRY_CODE),
        ("1", RejectionReason.INVALID_COUNTRY_CODE),
    ],
)
def test_bad_country_is_rejected_and_never_defaulted_to_de(country, reason):
    with pytest.raises(RecordRejected) as caught:
        validate(build(country=country))
    assert caught.value.reason is reason


def test_region_is_optional():
    assert validate(build(region=None)).metadata.region_code is None
    assert validate(build(region="  ")).metadata.region_code is None


def test_unparseable_region_is_rejected():
    with pytest.raises(RecordRejected) as caught:
        validate(build(region="Nordrhein-Westfalen"))
    assert caught.value.reason is RejectionReason.INVALID_REGION_CODE


def test_source_date_is_parsed_to_a_date():
    assert validate(build()).metadata.source_date == date(2026, 9, 1)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, RejectionReason.MISSING_SOURCE_DATE),
        ("", RejectionReason.MISSING_SOURCE_DATE),
        ("01.09.2026", RejectionReason.INVALID_SOURCE_DATE),
        ("2026-13-01", RejectionReason.INVALID_SOURCE_DATE),
    ],
)
def test_bad_source_date_is_rejected(value, reason):
    with pytest.raises(RecordRejected) as caught:
        validate(build(source_date=value))
    assert caught.value.reason is reason


def test_missing_identifier_is_rejected():
    with pytest.raises(RecordRejected) as caught:
        validate(build(source_key="  "))
    assert caught.value.reason is RejectionReason.MISSING_SOURCE_ID


def test_source_id_is_prefixed_by_the_adapter_contract():
    assert validate(build(source_key="001")).metadata.source_id == "fixture-001"
    assert validate(build(source_key="NL-001"), prefix="").metadata.source_id == "NL-001"


def test_broken_geometry_is_rejected_rather_than_nulled():
    with pytest.raises(RecordRejected) as caught:
        validate(build(geometry=LatLon(lat="95.0", lon="6.7")))
    assert caught.value.reason is RejectionReason.INVALID_GEOMETRY


def test_non_serializable_attributes_are_rejected():
    with pytest.raises(RecordRejected) as caught:
        validate(build(attributes={"blob": object()}))
    assert caught.value.reason is RejectionReason.INVALID_ATTRIBUTES


def test_canonical_dict_uses_the_documented_field_names():
    record = validate(build(geometry=LatLon(lat=51.2, lon=6.8)))
    assert record.to_dict() == {
        "country_code": "DE",
        "region_code": "NW",
        "source_id": "fixture-001",
        "source_date": "2026-09-01",
        "fetched_at": "2026-09-29T00:00:00Z",
        "attributes": {"name": "Test"},
        "geom": {"type": "Point", "coordinates": [6.8, 51.2]},
        "uncertainty": {"positional_accuracy_m": None, "basis": "unknown"},
    }
