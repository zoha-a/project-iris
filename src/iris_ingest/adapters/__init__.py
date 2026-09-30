"""Concrete source adapters.

Adding a source here requires no change to :mod:`iris_ingest.adapter`,
:mod:`iris_ingest.validation` or :mod:`iris_ingest.staging`.
"""

from .csv_sites import CsvSitesAdapter
from .geojson_sites import GeoJsonSitesAdapter

__all__ = ["CsvSitesAdapter", "GeoJsonSitesAdapter"]
