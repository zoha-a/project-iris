"""Acceptance criterion 2: a new source is a subclass and nothing else.

Every adapter in this module is declared here, in the test file. No module
under ``src/iris_ingest`` is imported for registration, edited, or monkey-
patched, yet these sources get identical normalization, validation, geometry
handling and rejection reporting.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from iris_ingest import GeoJSONGeometry, LatLon, SourceAdapter, SourceRecord
from iris_ingest.models import RejectionReason

# A third source that exists only for this test: an in-memory list of dicts
# with yet another set of field names and yet another country.
BELGIAN_ROWS = [
    {"ref": "A-1", "iso": "be", "prov": "VAN", "on": "2026-07-01", "lat": 51.21, "lng": 4.41},
    {"ref": "A-2", "iso": "BE", "prov": "van", "on": "2026-07-01", "lat": 51.05, "lng": 3.72},
    {"ref": "A-3", "iso": "be", "prov": "VAN", "on": "2026-07-01", "lat": None, "lng": None},
    {"ref": "A-4", "iso": "ZZ", "prov": "VAN", "on": "2026-07-01", "lat": 50.85, "lng": 4.35},
]


class InMemorySitesAdapter(SourceAdapter):
    source_name = "be_van_memory"
    source_id_prefix = "mem-"

    def __init__(self, rows, **kwargs):
        super().__init__(**kwargs)
        self.rows = rows

    def extract(self) -> Iterator[Mapping[str, Any]]:
        yield from self.rows

    def to_source_record(self, raw: Mapping[str, Any]) -> SourceRecord:
        has_location = raw["lat"] is not None and raw["lng"] is not None
        return SourceRecord(
            source_key=raw["ref"],
            country=raw["iso"],
            region=raw["prov"],
            source_date=raw["on"],
            attributes={"ref": raw["ref"]},
            geometry=LatLon(lat=raw["lat"], lon=raw["lng"]) if has_location else None,
        )


def test_a_brand_new_adapter_works_with_an_untouched_core(clock):
    result = InMemorySitesAdapter(BELGIAN_ROWS, clock=clock).run()

    assert result.accepted_count == 3
    assert {record.country_code for record in result.records} == {"BE"}
    assert {record.metadata.region_code for record in result.records} == {"VAN"}
    assert result.records[0].source_id == "mem-A-1"


def test_the_new_adapter_inherits_the_country_rule_for_free(clock):
    result = InMemorySitesAdapter(BELGIAN_ROWS, clock=clock).run()

    assert result.rejected_count == 1
    assert result.rejections[0].reason is RejectionReason.INVALID_COUNTRY_CODE
    assert result.rejections[0].source_key == "A-4"


def test_the_new_adapter_inherits_null_geometry_handling(clock):
    result = InMemorySitesAdapter(BELGIAN_ROWS, clock=clock).run()
    by_id = {record.source_id: record for record in result.records}
    assert by_id["mem-A-3"].geom is None


def test_a_subclass_only_has_to_write_two_methods():
    """The contract is small: everything else is inherited."""
    required = SourceAdapter.__abstractmethods__
    assert required == {"extract", "to_source_record"}

    written_here = set(vars(InMemorySitesAdapter)) & required
    assert written_here == required


def test_the_pipeline_cannot_be_bypassed_by_a_subclass():
    """run() is @final, so a source cannot skip validation."""
    assert getattr(SourceAdapter.run, "__final__", False)

    with pytest.raises(TypeError, match="source_name"):

        class Nameless(SourceAdapter):
            def extract(self):
                return iter(())

            def to_source_record(self, raw):
                raise NotImplementedError

        Nameless()


def test_adapters_do_not_reimplement_validation():
    """Guards against a source quietly growing its own country rules."""
    from iris_ingest.adapters import csv_sites, geojson_sites

    for module in (csv_sites, geojson_sites):
        body = inspect.getsource(module)
        assert "ISO_3166_1_ALPHA_2" not in body
        assert "RejectionReason" not in body
