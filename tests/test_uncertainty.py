"""Uncertainty as an explicit contract.

The rule under test throughout: silence from a source means "unknown", and
unknown must never be readable as "exact".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from iris_ingest.geometry import LatLon
from iris_ingest.models import (
    RecordRejected,
    RejectionReason,
    SourceRecord,
    Uncertainty,
    UncertaintyBasis,
)
from iris_ingest.validation import normalize_and_validate

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def build(**overrides) -> SourceRecord:
    defaults = {
        "source_key": "001",
        "country": "de",
        "region": "nw",
        "source_date": "2026-09-01",
        "attributes": {},
        "geometry": LatLon(lat=51.2, lon=6.8),
    }
    return SourceRecord(**{**defaults, **overrides})


def validate(record: SourceRecord):
    return normalize_and_validate(record, source_id_prefix="", fetched_at=NOW)


def test_unstated_uncertainty_is_unknown_not_zero():
    uncertainty = validate(build()).uncertainty

    assert uncertainty.positional_accuracy_m is None
    assert uncertainty.basis is UncertaintyBasis.UNKNOWN
    assert uncertainty.is_stated is False


def test_stated_accuracy_is_parsed_to_metres():
    uncertainty = validate(build(positional_accuracy_m="25", uncertainty_basis="measured")).uncertainty

    assert uncertainty.positional_accuracy_m == 25.0
    assert uncertainty.basis is UncertaintyBasis.MEASURED
    assert uncertainty.is_stated is True


def test_basis_may_be_known_while_accuracy_is_not():
    uncertainty = validate(build(uncertainty_basis="estimated")).uncertainty

    assert uncertainty.basis is UncertaintyBasis.ESTIMATED
    assert uncertainty.positional_accuracy_m is None
    assert uncertainty.is_stated is True


def test_accuracy_without_a_position_is_rejected():
    with pytest.raises(RecordRejected) as caught:
        validate(build(geometry=None, positional_accuracy_m=10))

    assert caught.value.reason is RejectionReason.INVALID_UNCERTAINTY
    assert "no position" in caught.value.message


def test_a_record_without_a_position_may_still_declare_its_basis():
    record = validate(build(geometry=None, uncertainty_basis="estimated"))

    assert record.geom is None
    assert record.uncertainty.basis is UncertaintyBasis.ESTIMATED
    assert record.uncertainty.positional_accuracy_m is None


@pytest.mark.parametrize(
    "accuracy",
    [0, "0", -5, "-0.5", "circa 10", float("inf"), float("nan")],
    ids=["zero", "zero-text", "negative", "negative-text", "not-a-number", "inf", "nan"],
)
def test_impossible_accuracy_is_rejected(accuracy):
    with pytest.raises(RecordRejected) as caught:
        validate(build(positional_accuracy_m=accuracy))
    assert caught.value.reason is RejectionReason.INVALID_UNCERTAINTY


def test_zero_accuracy_is_refused_rather_than_treated_as_exact():
    """0 m would assert a perfect position, which no source can honestly claim."""
    with pytest.raises(RecordRejected) as caught:
        validate(build(positional_accuracy_m=0))
    assert "perfect position" in caught.value.message


def test_negative_accuracy_says_what_is_actually_wrong():
    with pytest.raises(RecordRejected) as caught:
        validate(build(positional_accuracy_m=-5))
    assert "negative" in caught.value.message


def test_unknown_basis_word_is_rejected_not_coerced():
    with pytest.raises(RecordRejected) as caught:
        validate(build(uncertainty_basis="geraten"))

    assert caught.value.reason is RejectionReason.INVALID_UNCERTAINTY
    assert "measured" in caught.value.message  # the message lists what is allowed


@pytest.mark.parametrize("value", ["MEASURED", " Measured ", "measured"])
def test_basis_casing_and_padding_are_normalized(value):
    assert validate(build(uncertainty_basis=value)).uncertainty.basis is UncertaintyBasis.MEASURED


def test_uncertainty_is_serialized_alongside_the_record():
    record = validate(build(positional_accuracy_m=5, uncertainty_basis="measured"))
    assert record.to_dict()["uncertainty"] == {
        "positional_accuracy_m": 5.0,
        "basis": "measured",
    }


def test_unknown_uncertainty_serializes_as_nulls_not_omitted():
    """The field is always present, so a reader cannot miss that it is unknown."""
    payload = validate(build()).to_dict()

    assert "uncertainty" in payload
    assert payload["uncertainty"] == {"positional_accuracy_m": None, "basis": "unknown"}


def test_uncertainty_defaults_to_unknown_when_constructed_directly():
    assert Uncertainty().basis is UncertaintyBasis.UNKNOWN
    assert Uncertainty().positional_accuracy_m is None


def test_csv_fixture_carries_a_mix_of_stated_and_unstated_accuracy(csv_result):
    unstated = {
        record.source_id
        for record in csv_result.records
        if record.uncertainty.positional_accuracy_m is None
    }
    assert unstated == {"fixture-006", "fixture-011", "fixture-016", "fixture-021", "fixture-022"}

    by_id = {record.source_id: record for record in csv_result.records}
    assert by_id["fixture-001"].uncertainty.positional_accuracy_m == 5.0
    assert by_id["fixture-001"].uncertainty.basis is UncertaintyBasis.MEASURED
    assert by_id["fixture-009"].uncertainty.basis is UncertaintyBasis.DERIVED


def test_geojson_fixture_carries_uncertainty_through_a_different_field_name(geojson_result):
    by_id = {record.source_id: record for record in geojson_result.records}

    assert by_id["NL-GE-001"].uncertainty.positional_accuracy_m == 10.0
    assert by_id["NL-GE-004"].uncertainty.positional_accuracy_m is None
    assert by_id["NL-GE-004"].uncertainty.basis is UncertaintyBasis.ESTIMATED
    # No uncertainty properties at all on this feature.
    assert by_id["NL-GE-006"].uncertainty.is_stated is False
    # No geometry, so no accuracy is possible, but the basis still applies.
    assert by_id["NL-GE-007"].geom is None
    assert by_id["NL-GE-007"].uncertainty.basis is UncertaintyBasis.ESTIMATED
