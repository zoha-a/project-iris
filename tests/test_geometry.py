"""Geometry normalization: the highest-risk correctness area in a geo pipeline."""

from __future__ import annotations

import struct

import pytest

from iris_ingest.geometry import (
    GeoJSONGeometry,
    GeometryError,
    LatLon,
    normalize,
    to_ewkb_hex,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[5.0, 51.0], [5.1, 51.0], [5.1, 51.1], [5.0, 51.1], [5.0, 51.0]]],
}


def test_lat_lon_becomes_a_point_in_lon_lat_order():
    geom = normalize(LatLon(lat="51.2612", lon="6.7891"))
    assert geom == {"type": "Point", "coordinates": [6.7891, 51.2612]}


def test_absent_geometry_stays_none():
    assert normalize(None) is None
    assert normalize(GeoJSONGeometry(None)) is None


@pytest.mark.parametrize(
    "source",
    [
        LatLon(lat="95.0", lon="6.7"),
        LatLon(lat="51.2", lon="200.0"),
        LatLon(lat="51.2", lon="ost"),
        LatLon(lat="51.2", lon=""),
        LatLon(lat=None, lon=6.7),
    ],
    ids=["lat-out-of-range", "lon-out-of-range", "lon-not-a-number", "lon-blank", "lat-missing"],
)
def test_broken_coordinates_raise_instead_of_being_dropped(source):
    with pytest.raises(GeometryError):
        normalize(source)


@pytest.mark.parametrize(
    "value",
    [
        {"type": "Circle", "coordinates": [1, 2]},
        {"type": "Point"},
        {"type": "Point", "coordinates": [1.0]},
        {"type": "Point", "coordinates": [1.0, 2.0, 3.0]},
        {"type": "Point", "coordinates": ["1.0", "2.0"]},
        {"type": "LineString", "coordinates": [[1.0, 2.0]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
    ],
    ids=[
        "unsupported-type",
        "no-coordinates",
        "position-too-short",
        "3d-position-unsupported",
        "position-not-numeric",
        "line-needs-two-positions",
        "ring-not-closed",
        "ring-too-short",
    ],
)
def test_malformed_geojson_is_rejected(value):
    with pytest.raises(GeometryError):
        normalize(GeoJSONGeometry(value))


def test_valid_polygon_survives_unchanged():
    assert normalize(GeoJSONGeometry(POLYGON)) == POLYGON


def test_ewkb_matches_postgis_for_a_known_point():
    geom = {"type": "Point", "coordinates": [1.0, 2.0]}
    assert to_ewkb_hex(geom) == "0101000020E6100000000000000000F03F0000000000000040"


def test_ewkb_is_none_when_there_is_no_geometry():
    assert to_ewkb_hex(None) is None


def test_ewkb_header_declares_srid_4326_for_a_polygon():
    payload = bytes.fromhex(to_ewkb_hex(POLYGON))
    byte_order, type_code, srid = struct.unpack_from("<BII", payload, 0)

    assert byte_order == 1  # little endian
    assert type_code == 3 | 0x20000000  # Polygon with the EWKB SRID flag
    assert srid == 4326
