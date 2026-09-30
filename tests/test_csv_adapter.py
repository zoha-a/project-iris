"""The tabular adapter against the committed fixtures."""

from __future__ import annotations

from iris_ingest.models import RejectionReason


def test_clean_run_imports_at_least_twenty_records(csv_result):
    assert csv_result.accepted_count == 22
    assert csv_result.rejected_count == 0


def test_every_record_carries_a_non_null_country_code(csv_result):
    assert {record.country_code for record in csv_result.records} == {"DE"}


def test_messy_country_and_region_casing_is_normalized(csv_result):
    by_id = {record.source_id: record for record in csv_result.records}

    assert by_id["fixture-004"].metadata.country_code == "DE"  # raw "DE"
    assert by_id["fixture-009"].metadata.country_code == "DE"  # raw "De"
    assert by_id["fixture-022"].metadata.country_code == "DE"  # raw " de"
    assert by_id["fixture-005"].metadata.region_code == "NW"  # raw "NW"


def test_lat_lon_columns_become_a_geom_point(csv_result):
    first = csv_result.records[0]
    assert first.geom == {"type": "Point", "coordinates": [6.7891, 51.2612]}


def test_records_without_coordinates_keep_a_null_geom(csv_result):
    without_geom = {record.source_id for record in csv_result.records if record.geom is None}
    assert without_geom == {"fixture-021", "fixture-022"}


def test_source_date_is_read_per_record_not_hardcoded(csv_result):
    dates = {record.metadata.source_date.isoformat() for record in csv_result.records}
    assert dates == {"2026-09-01", "2026-08-15"}


def test_non_canonical_columns_land_in_attributes(csv_result):
    first = csv_result.records[0]
    assert first.attributes == {"name": "Nordpark Flaeche A", "area_m2": 12400}


def test_missing_optional_attribute_is_none_not_invented(csv_result):
    by_id = {record.source_id: record for record in csv_result.records}
    assert by_id["fixture-021"].attributes["area_m2"] is None


def test_invalid_fixture_rejects_every_row_with_the_expected_reason(invalid_csv_result):
    assert invalid_csv_result.accepted_count == 0
    assert invalid_csv_result.rejected_count == 9

    reasons = {rejection.source_key: rejection.reason for rejection in invalid_csv_result.rejections}
    assert reasons == {
        "101": RejectionReason.MISSING_COUNTRY_CODE,
        "102": RejectionReason.INVALID_COUNTRY_CODE,
        "103": RejectionReason.INVALID_COUNTRY_CODE,
        "104": RejectionReason.INVALID_GEOMETRY,
        "105": RejectionReason.INVALID_GEOMETRY,
        "106": RejectionReason.MISSING_SOURCE_DATE,
        "107": RejectionReason.INVALID_UNCERTAINTY,
        "108": RejectionReason.INVALID_UNCERTAINTY,
        "109": RejectionReason.INVALID_UNCERTAINTY,
    }


def test_rejections_keep_the_raw_row_for_auditing(invalid_csv_result):
    rejection = next(r for r in invalid_csv_result.rejections if r.source_key == "102")
    assert rejection.raw["country"] == "XX"
    assert "ISO 3166-1 alpha-2" in rejection.message
