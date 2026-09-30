"""Geometry normalization for the canonical ``geom`` field.

Sources describe location in different ways, so adapters hand the core one of
two declared inputs (:class:`LatLon` or :class:`GeoJSONGeometry`) and the core
turns both into the same validated GeoJSON mapping. The same mapping can be
rendered as EWKB hex for a PostGIS ``geometry(Geometry, 4326)`` column.

Coordinates are interpreted as CRS84 / EPSG:4326 longitude-latitude degrees.
Only 2D positions are supported; see README for why and how that would grow.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

SRID_WGS84 = 4326

#: Nesting depth of the ``coordinates`` member for each supported type.
_COORDINATE_DEPTH: dict[str, int] = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}

_WKB_TYPE_CODES: dict[str, int] = {
    "Point": 1,
    "LineString": 2,
    "Polygon": 3,
    "MultiPoint": 4,
    "MultiLineString": 5,
    "MultiPolygon": 6,
}

_EWKB_SRID_FLAG = 0x20000000


class GeometryError(ValueError):
    """Raised when a source geometry cannot be normalized truthfully."""


@dataclass(frozen=True, slots=True)
class LatLon:
    """A location supplied as two separate scalars, as CSV sources tend to do."""

    lat: Any
    lon: Any


@dataclass(frozen=True, slots=True)
class GeoJSONGeometry:
    """A location supplied as a GeoJSON geometry object."""

    value: Any


GeometrySource = LatLon | GeoJSONGeometry


def normalize(source: GeometrySource | None) -> dict[str, Any] | None:
    """Return a validated GeoJSON geometry, or ``None`` when there is none.

    A missing geometry is legitimate and stays ``None``. A *present but broken*
    geometry raises instead, so it can be rejected rather than quietly dropped.
    """
    match source:
        case None:
            return None
        case LatLon(lat=lat, lon=lon):
            return _point_from_lat_lon(lat, lon)
        case GeoJSONGeometry(value=None):
            return None
        case GeoJSONGeometry(value=value):
            return _from_geojson(value)
        case _:
            raise GeometryError(f"unsupported geometry source {type(source).__name__}")


def to_ewkb_hex(geom: dict[str, Any] | None, srid: int = SRID_WGS84) -> str | None:
    """Render a normalized geometry as PostGIS-compatible EWKB hex."""
    if geom is None:
        return None
    return _pack(geom, srid).hex().upper()


def _point_from_lat_lon(lat: Any, lon: Any) -> dict[str, Any]:
    if _is_blank(lat) or _is_blank(lon):
        raise GeometryError("incomplete coordinate pair: both lat and lon are required")
    return {"type": "Point", "coordinates": _position([_number(lon, "lon"), _number(lat, "lat")])}


def _from_geojson(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GeometryError("geometry must be a GeoJSON object")

    gtype = value.get("type")
    if gtype not in _COORDINATE_DEPTH:
        raise GeometryError(f"unsupported geometry type {gtype!r}")

    if "coordinates" not in value:
        raise GeometryError(f"{gtype} is missing 'coordinates'")

    coordinates = _coordinates(value["coordinates"], _COORDINATE_DEPTH[gtype], gtype)
    return {"type": gtype, "coordinates": coordinates}


def _coordinates(value: Any, depth: int, gtype: str) -> Any:
    if depth == 0:
        return _position(value)

    if not isinstance(value, (list, tuple)):
        raise GeometryError(f"{gtype} coordinates must be nested arrays")

    items = [_coordinates(item, depth - 1, gtype) for item in value]
    _check_arity(items, depth, gtype)
    return items


def _check_arity(items: list[Any], depth: int, gtype: str) -> None:
    if not items:
        raise GeometryError(f"{gtype} coordinates must not be empty")

    is_line = depth == 1 and gtype in ("LineString", "MultiLineString", "Polygon", "MultiPolygon")
    if is_line and len(items) < 2:
        raise GeometryError("a line needs at least two positions")

    is_ring = depth == 1 and gtype in ("Polygon", "MultiPolygon")
    if is_ring:
        if len(items) < 4:
            raise GeometryError("a polygon ring needs at least four positions")
        if items[0] != items[-1]:
            raise GeometryError("a polygon ring must be closed (first position repeated last)")


def _position(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        raise GeometryError("position must be a [lon, lat] array")
    if len(value) != 2:
        raise GeometryError(f"position must hold exactly two values, got {len(value)}")

    lon = _number(value[0], "lon", parse_strings=False)
    lat = _number(value[1], "lat", parse_strings=False)
    return _position_from_floats(lon, lat)


def _position_from_floats(lon: float, lat: float) -> list[float]:
    if not -180.0 <= lon <= 180.0:
        raise GeometryError(f"longitude {lon} is outside [-180, 180]")
    if not -90.0 <= lat <= 90.0:
        raise GeometryError(f"latitude {lat} is outside [-90, 90]")
    return [lon, lat]


def _number(value: Any, name: str, *, parse_strings: bool = True) -> float:
    if isinstance(value, bool):
        raise GeometryError(f"{name} must be a number, got a boolean")
    if isinstance(value, (int, float)):
        number = float(value)
    elif parse_strings and isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise GeometryError(f"{name} {value!r} is not a number") from exc
    else:
        raise GeometryError(f"{name} must be a number, got {type(value).__name__}")

    if not math.isfinite(number):
        raise GeometryError(f"{name} must be finite, got {number}")
    return number


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _pack(geom: dict[str, Any], srid: int | None) -> bytes:
    gtype = geom["type"]
    coordinates = geom["coordinates"]

    out = bytearray(b"\x01")  # little-endian byte order marker
    if srid is None:
        out += struct.pack("<I", _WKB_TYPE_CODES[gtype])
    else:
        out += struct.pack("<I", _WKB_TYPE_CODES[gtype] | _EWKB_SRID_FLAG)
        out += struct.pack("<I", srid)

    match gtype:
        case "Point":
            out += struct.pack("<dd", *coordinates)
        case "LineString":
            out += _pack_positions(coordinates)
        case "Polygon":
            out += struct.pack("<I", len(coordinates))
            for ring in coordinates:
                out += _pack_positions(ring)
        case "MultiPoint":
            out += _pack_members("Point", coordinates)
        case "MultiLineString":
            out += _pack_members("LineString", coordinates)
        case "MultiPolygon":
            out += _pack_members("Polygon", coordinates)

    return bytes(out)


def _pack_positions(positions: list[list[float]]) -> bytes:
    out = bytearray(struct.pack("<I", len(positions)))
    for lon, lat in positions:
        out += struct.pack("<dd", lon, lat)
    return bytes(out)


def _pack_members(member_type: str, members: list[Any]) -> bytes:
    # Members of a multi-geometry carry their own WKB header but no SRID.
    out = bytearray(struct.pack("<I", len(members)))
    for member in members:
        out += _pack({"type": member_type, "coordinates": member}, None)
    return bytes(out)
