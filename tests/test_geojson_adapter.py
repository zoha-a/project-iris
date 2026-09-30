"""The geospatial adapter: a different format reaching the same contract."""

from __future__ import annotations

import json

import pytest

from iris_ingest.adapters import GeoJsonSitesAdapter
from iris_ingest.models import RejectionReason


def test_valid_features_are_imported_and_the_broken_one_is_not(geojson_result):
    assert geojson_result.accepted_count == 7
    assert geojson_result.rejected_count == 1


def test_country_and_region_come_from_source_specific_property_names(geojson_result):
    assert {record.country_code for record in geojson_result.records} == {"NL"}
    assert {record.metadata.region_code for record in geojson_result.records} == {"GE"}


def test_ids_are_used_verbatim_when_the_adapter_sets_no_prefix(geojson_result):
    assert geojson_result.records[0].source_id == "NL-GE-001"


def test_polygon_geometry_survives_normalization(geojson_result):
    by_id = {record.source_id: record for record in geojson_result.records}
    polygon = by_id["NL-GE-003"].geom

    assert polygon["type"] == "Polygon"
    assert polygon["coordinates"][0][0] == polygon["coordinates"][0][-1]


def test_null_geometry_is_preserved_as_null(geojson_result):
    by_id = {record.source_id: record for record in geojson_result.records}
    assert by_id["NL-GE-007"].geom is None


def test_feature_without_a_country_is_rejected(geojson_result):
    rejection = geojson_result.rejections[0]
    assert rejection.source_key == "NL-GE-008"
    assert rejection.reason is RejectionReason.MISSING_COUNTRY_CODE


def test_both_sources_produce_the_same_canonical_key_set(csv_result, geojson_result):
    csv_keys = set(csv_result.records[0].to_dict())
    geojson_keys = set(geojson_result.records[0].to_dict())
    assert csv_keys == geojson_keys


def test_an_unsupported_crs_fails_loudly(tmp_path, clock, fixtures_dir):
    source = fixtures_dir / "nl_ge_sites.geojson"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["crs"] = {"type": "name", "properties": {"name": "EPSG:28992"}}

    path = tmp_path / "rd_new.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported CRS"):
        GeoJsonSitesAdapter(path, clock=clock).run()
