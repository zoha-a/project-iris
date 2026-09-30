# IRIS-CAND-01 — Reusable Python Source Adapter Contract

A shared ingestion core for Project IRIS. Any future data source plugs in by
subclassing one interface; extraction, normalization, validation and the
staging handoff are written once and inherited.

## Run it

Requires Python 3.12+. No database, credentials or network access needed.

```bash
python run.py demo
```

That ingests all three bundled fixtures and writes canonical JSONL plus a
rejection log to `out/`, then prints a summary:

```
source         accepted  rejected  reasons
de_nw_csv            22         0  -
de_nw_csv             0         6  invalid_country_code=2, invalid_geometry=2, missing_country_code=1, missing_source_date=1
nl_ge_geojson         7         1  missing_country_code=1
```

Tests:

```bash
pip install pytest && python -m pytest
```

Installing the package (`pip install -e ".[dev]"`) additionally provides the
`iris-ingest` console script and `python -m iris_ingest`; `run.py` exists so a
clean checkout works without installing anything.

Other commands:

```bash
python run.py list-adapters
python run.py ingest --adapter csv --source fixtures/de_nw_sites.csv --out out/de.jsonl \
                     --rejects out/de.rejects.jsonl
python run.py ingest --adapter my_package.sources:MyAdapter --source data.csv --out out/mine.jsonl
```

## The canonical record

Every source, regardless of format, produces exactly this shape:

```json
{
  "country_code": "DE",
  "region_code": "NW",
  "source_id": "fixture-001",
  "source_date": "2026-09-01",
  "fetched_at": "2026-09-29T00:00:00Z",
  "attributes": { "name": "Nordpark Flaeche A", "area_m2": 12400 },
  "geom": { "type": "Point", "coordinates": [6.7891, 51.2612] },
  "uncertainty": { "positional_accuracy_m": 5.0, "basis": "measured" }
}
```

`geom` is the canonical geometry name and is `null` only when the source
reported no location. Source metadata is modelled explicitly as
`SourceMetadata` (`source_id`, `source_date`, `fetched_at`, `country_code`,
`region_code`) and flattened on serialization. `uncertainty` extends the
minimum contract; see below. Committed samples live in `examples/`.

## Architecture

```
src/iris_ingest/
  adapter.py      SourceAdapter: the contract + the @final pipeline
  models.py       SourceRecord, SourceMetadata, CanonicalRecord, RejectedRecord
  validation.py   normalization and every contract rule, shared by all sources
  geometry.py     geometry normalization + EWKB rendering
  countries.py    ISO 3166-1 alpha-2 allow-list
  staging.py      JSONL and PostGIS writers
  cli.py          reproducible commands
  adapters/       concrete sources (csv_sites, geojson_sites)
sql/001_create_staging.sql
fixtures/         deterministic committed input
examples/         committed canonical output
```

The four responsibilities are separate objects, not four sections of one
function:

| Stage | Owner | Source-specific? |
|---|---|---|
| Extract | `SourceAdapter.extract` | yes |
| Field mapping | `SourceAdapter.to_source_record` | yes |
| Normalize + validate | `validation.normalize_and_validate` | no |
| Load to staging | `staging.*Writer` | no |

A subclass writes **only** the two `yes` rows. `SourceAdapter.run` and its
internals are `@typing.final`, so a source cannot skip validation, and adapters
never import `RejectionReason` or the country list — a test asserts this.

### Adding a source

```python
from iris_ingest import SourceAdapter, SourceRecord, LatLon

class MySitesAdapter(SourceAdapter):
    source_name = "fr_idf_api"
    source_id_prefix = "fr-"

    def extract(self):
        yield from my_rows()

    def to_source_record(self, raw):
        return SourceRecord(
            source_key=raw["id"],
            country=raw["pays"],
            region=raw["region"],
            source_date=raw["date"],
            attributes={"name": raw["nom"]},
            geometry=LatLon(lat=raw["lat"], lon=raw["lon"]),
        )
```

Nothing under `src/iris_ingest/` changes. `tests/test_extensibility.py` proves
this by declaring a third adapter inside the test file itself and asserting it
inherits country validation, null-geometry handling and rejection reporting.

Adapters hand the core one of two declared location inputs — `LatLon` for
sources with scalar columns, `GeoJSONGeometry` for sources that already carry a
geometry — and the core turns both into the same validated `geom`.

## Data contracts enforced

- **Country is mandatory and never defaulted.** Missing, `XX` or `DEU` are all
  rejected with a distinct reason rather than coerced to `DE`. Values are
  checked against a vendored ISO 3166-1 alpha-2 list.
- **Country-scoped identity.** The staging primary key is
  `(country_code, source_id)`, so two countries may reuse a local id.
- **Geometry is never invented.** Absent coordinates give `geom: null`; a
  *half-present* pair, an out-of-range latitude, an unclosed polygon ring or a
  non-numeric ordinate are rejected.
- **CRS is explicit.** CRS84 / EPSG:4326 only. The GeoJSON adapter fails loudly
  on any other declared CRS instead of reinterpreting the numbers.
- **Source date is part of the contract.** Required and parsed as ISO-8601; a
  blank date is a rejection, not "today".
- **Units are named, never implied.** Quantities carry their unit in the key:
  `area_m2`, `positional_accuracy_m`. A bare `area` is not accepted vocabulary,
  so no reader has to guess between m², hectares and km².
- **Uncertainty is stated, never assumed.** Every record carries an
  `uncertainty` block, and an absent value reads as unknown rather than exact
  — see below.
- **Nothing is silently dropped.** Every failure becomes a `RejectedRecord`
  carrying the reason, a message and the raw row, written to a `.rejects.jsonl`
  sidecar.

## Uncertainty

The pilot publishes prospecting material where figures are explicitly
indicative, so a record that looks precise but isn't is a real hazard. Every
canonical record therefore carries an `uncertainty` block:

```json
"uncertainty": { "positional_accuracy_m": 25.0, "basis": "estimated" }
```

`positional_accuracy_m` is a radius in metres. `basis` is one of `measured`,
`estimated`, `derived` or `unknown`.

The design rule is that **silence is recorded as silence**. A source that says
nothing produces `{"positional_accuracy_m": null, "basis": "unknown"}` — never
`0` and never a default of `measured`. The field is always present in the
output, so a downstream reader cannot overlook it, and there is deliberately no
`DEFAULT 0` on the database column.

Four rules are enforced:

| Rule | Why |
|---|---|
| Accuracy without a geometry is rejected | A radius around no position is meaningless |
| `0 m` is rejected | It claims a perfect fix no survey can honestly assert |
| A negative accuracy is rejected | An accuracy is a radius |
| An unrecognized `basis` is rejected, not coerced | Guessing what a source meant defeats the point |

A record may state its `basis` without an accuracy, which is the common case
for a site known by address but not by survey.

## Fixtures

| File | Purpose |
|---|---|
| `de_nw_sites.csv` | 22 valid German rows; messy casing, scalar lat/lon, 2 rows with no coordinates, 5 with unstated accuracy |
| `de_nw_sites_invalid.csv` | 9 rows, one per validation rule |
| `nl_ge_sites.geojson` | 8 Dutch features; different format and field names, a polygon, a null geometry, mixed uncertainty, one rejection |

The two fixtures are deliberately dissimilar so the core cannot secretly depend
on either. `fetched_at` is injectable via a `clock` callable, so tests and the
committed `examples/` output are byte-for-byte reproducible.

## PostgreSQL / PostGIS

`sql/001_create_staging.sql` creates `staging.source_record` with a
`geometry(Geometry, 4326)` column named `geom`, a `NOT NULL char(2)`
`country_code`, the country-scoped primary key, format checks and a GiST index.
The uncertainty rules are mirrored as `CHECK` constraints, so the database
enforces them even if a row arrives by some other route. It is idempotent.

Loading is optional and needs no credentials for the graded run:

```bash
psql "$DSN" -f sql/001_create_staging.sql
pip install -e ".[postgres]"
python run.py ingest --adapter csv --source fixtures/de_nw_sites.csv \
                     --out out/de.jsonl --dsn "$DSN"
```

`CanonicalRecord.geom_ewkb_hex()` renders EWKB with the SRID flag set, which
`ST_GeomFromEWKB` consumes directly. The encoder is hand-rolled over `struct`
so the package has zero runtime dependencies; it is verified against PostGIS's
known output for `SRID=4326;POINT(1 2)`.

## Tests

92 tests, `python -m pytest`. Weighted toward the conditions most likely to
corrupt downstream analysis rather than toward line coverage:

| File | Covers |
|---|---|
| `test_geometry.py` | lon/lat ordering, range checks, ring closure, EWKB byte layout |
| `test_validation.py` | every rejection reason, trimming, date parsing, canonical key names |
| `test_uncertainty.py` | unknown-vs-exact, accuracy without a position, basis coercion |
| `test_csv_adapter.py` | 22-record clean run, null geometry, per-row rejection reasons |
| `test_geojson_adapter.py` | second format, polygon passthrough, CRS guard, identical key set |
| `test_extensibility.py` | acceptance criterion 2 — a third adapter declared in the test file |
| `test_staging_and_cli.py` | JSONL shape, byte-level determinism, CLI exit codes |

## Assumptions

- `region_code` is optional (`AA` / `A1` / `AAA`); `country_code` is not.
  A source that omits a region is usable; one that omits a country is not.
- `DEU` is rejected rather than mapped to `DE`. Translating alpha-3 to alpha-2
  is a guess about the source's intent, and quiet guessing is what the
  country rule exists to prevent.
- A record whose *attributes* are unparseable (`area_m2 = "n/a"`) keeps the
  record with that attribute `null`. Only contract fields cause rejection.
- Uncertainty is modelled at record level and scoped to position plus a
  collection basis. Per-attribute uncertainty (a tolerance on `area_m2`) is
  the obvious next step but is not needed by the pilot's screening logic.
- Adapters read local files. A remote source would replace `extract` only.

## Deliberate simplifications

| Simplification | Production path |
|---|---|
| 2D positions only; a 3D coordinate is rejected | Carry Z through normalization and the WKB encoder, or reproject explicitly |
| Only CRS84/EPSG:4326 accepted | Add a reprojection step in the core keyed off the declared source CRS |
| Staging load is row-by-row `executemany` | `COPY` into an unlogged staging table, then a promotion transaction |
| Rejections go to a JSONL sidecar | A `staging.rejected_record` table feeding a data-quality dashboard |
| Country list is vendored | Track the ISO register, or use `pycountry` with a pinned revision |
| Uncertainty covers position and basis only | Per-attribute tolerances, plus a confidence score combining source authority and age |
| No promotion step | Staging → core promotion with country-scoped dedupe and the eco-point baseline held as an explicit, versioned assumption |
| `fetched_at` is per-run | Per-request fetch timestamps once sources are genuinely remote |

## Acceptance criteria

1. **Clean run imports at least 20 fixture records** — 22 from the CSV fixture
   plus 7 from the GeoJSON fixture; asserted in
   `test_clean_run_imports_at_least_twenty_records`.
2. **A second adapter is implemented only by subclassing** — `GeoJsonSitesAdapter`
   ships as one, and `tests/test_extensibility.py` adds a third without touching
   the core.
3. **Invalid `country_code` is rejected rather than defaulted to DE** — see
   `test_bad_country_is_rejected_and_never_defaulted_to_de`.
4. **Geometry field is named `geom`** — in the canonical record, the JSONL
   output and the PostGIS table.
