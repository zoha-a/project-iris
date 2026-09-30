-- Project IRIS: staging table for adapter output.
-- PostgreSQL 16+ / PostGIS 3.4+. Safe to re-run.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.source_record (
    -- Every persisted business entity carries a country, and identifiers are
    -- country-scoped so two sources may reuse the same local id per country.
    country_code  char(2)      NOT NULL,
    source_id     text         NOT NULL,
    region_code   text         NULL,
    source_date   date         NOT NULL,
    fetched_at    timestamptz  NOT NULL,
    source_name   text         NOT NULL,
    attributes    jsonb        NOT NULL DEFAULT '{}'::jsonb,
    -- Canonical geometry column name, nullable because "location unknown" is
    -- a legitimate state that must never be filled in with a guess.
    geom          geometry(Geometry, 4326) NULL,
    -- Uncertainty is explicit. NULL accuracy means the source stated none; it
    -- must never be read as an exact position, which is why there is no
    -- DEFAULT 0 here. The basis defaults to 'unknown' for the same reason.
    positional_accuracy_m  double precision NULL,
    uncertainty_basis      text NOT NULL DEFAULT 'unknown',
    loaded_at     timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT source_record_pkey
        PRIMARY KEY (country_code, source_id),
    CONSTRAINT source_record_accuracy_positive
        CHECK (positional_accuracy_m IS NULL OR positional_accuracy_m > 0),
    CONSTRAINT source_record_accuracy_needs_position
        CHECK (geom IS NOT NULL OR positional_accuracy_m IS NULL),
    CONSTRAINT source_record_uncertainty_basis_known
        CHECK (uncertainty_basis IN ('measured', 'estimated', 'derived', 'unknown')),
    CONSTRAINT source_record_country_code_format
        CHECK (country_code ~ '^[A-Z]{2}$'),
    CONSTRAINT source_record_region_code_format
        CHECK (region_code IS NULL OR region_code ~ '^[A-Z0-9]{1,3}$'),
    CONSTRAINT source_record_geom_srid
        CHECK (geom IS NULL OR ST_SRID(geom) = 4326)
);

CREATE INDEX IF NOT EXISTS source_record_geom_gix
    ON staging.source_record USING gist (geom);

CREATE INDEX IF NOT EXISTS source_record_country_date_idx
    ON staging.source_record (country_code, source_date DESC);

COMMENT ON TABLE  staging.source_record IS
    'Untrusted adapter output awaiting promotion. One row per canonical record.';
COMMENT ON COLUMN staging.source_record.geom IS
    'CRS84 / EPSG:4326. NULL means the source reported no location.';
COMMENT ON COLUMN staging.source_record.positional_accuracy_m IS
    'Radius in metres. NULL means the source stated no accuracy, NOT that the position is exact.';
