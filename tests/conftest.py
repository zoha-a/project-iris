from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from iris_ingest.adapters import CsvSitesAdapter, GeoJsonSitesAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: Frozen so every assertion about fetched_at and every JSONL byte is stable.
FROZEN_NOW = datetime(2026, 9, 29, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def clock():
    return lambda: FROZEN_NOW


@pytest.fixture
def csv_result(clock):
    return CsvSitesAdapter(FIXTURES / "de_nw_sites.csv", clock=clock).run()


@pytest.fixture
def invalid_csv_result(clock):
    return CsvSitesAdapter(FIXTURES / "de_nw_sites_invalid.csv", clock=clock).run()


@pytest.fixture
def geojson_result(clock):
    return GeoJsonSitesAdapter(FIXTURES / "nl_ge_sites.geojson", clock=clock).run()
