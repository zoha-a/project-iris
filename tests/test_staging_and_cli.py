"""Staging output and the documented one-command run."""

from __future__ import annotations

import json

from iris_ingest.cli import main
from iris_ingest.staging import JsonlRejectionWriter, JsonlStagingWriter


def test_jsonl_output_is_one_canonical_record_per_line(tmp_path, csv_result):
    path = tmp_path / "out.jsonl"
    written = JsonlStagingWriter(path).write(csv_result.records)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert written == len(lines) == 22

    first = json.loads(lines[0])
    assert list(first) == [
        "country_code",
        "region_code",
        "source_id",
        "source_date",
        "fetched_at",
        "attributes",
        "geom",
        "uncertainty",
    ]
    assert first["geom"]["type"] == "Point"
    assert json.loads(lines[-1])["geom"] is None


def test_output_is_byte_identical_across_runs(tmp_path, csv_result):
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    JsonlStagingWriter(first).write(csv_result.records)
    JsonlStagingWriter(second).write(csv_result.records)
    assert first.read_bytes() == second.read_bytes()


def test_rejection_file_explains_each_failure(tmp_path, invalid_csv_result):
    path = tmp_path / "rejects.jsonl"
    JsonlRejectionWriter(path).write(invalid_csv_result.rejections)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 9
    assert rows[0]["reason"] == "missing_country_code"
    assert rows[0]["raw"]["site_id"] == "101"


def test_every_record_renders_postgis_ready_ewkb(csv_result):
    with_geom = [record for record in csv_result.records if record.geom is not None]
    assert len(with_geom) == 20

    for record in with_geom:
        # 0101000020E6100000... = little-endian Point, SRID 4326.
        assert record.geom_ewkb_hex().startswith("0101000020E6100000")

    without_geom = next(record for record in csv_result.records if record.geom is None)
    assert without_geom.geom_ewkb_hex() is None


def test_demo_command_ingests_every_fixture(tmp_path, capsys):
    exit_code = main(
        ["demo", "--out-dir", str(tmp_path), "--fetched-at", "2026-09-29T00:00:00Z"]
    )
    assert exit_code == 0

    assert len((tmp_path / "de_nw_sites.jsonl").read_text(encoding="utf-8").splitlines()) == 22
    assert len((tmp_path / "nl_ge_sites.jsonl").read_text(encoding="utf-8").splitlines()) == 7
    assert (tmp_path / "de_nw_sites_invalid.jsonl").read_text(encoding="utf-8") == ""

    summary = capsys.readouterr().out
    assert "de_nw_csv" in summary
    assert "invalid_country_code=2" in summary


def test_ingest_command_accepts_a_dotted_adapter_path(tmp_path, fixtures_dir):
    exit_code = main(
        [
            "ingest",
            "--adapter",
            "iris_ingest.adapters.geojson_sites:GeoJsonSitesAdapter",
            "--source",
            str(fixtures_dir / "nl_ge_sites.geojson"),
            "--out",
            str(tmp_path / "nl.jsonl"),
            "--rejects",
            str(tmp_path / "nl.rejects.jsonl"),
            "--fetched-at",
            "2026-09-29T00:00:00Z",
        ]
    )
    assert exit_code == 0
    assert len((tmp_path / "nl.jsonl").read_text(encoding="utf-8").splitlines()) == 7


def test_fail_on_reject_flag_surfaces_bad_input(tmp_path, fixtures_dir):
    exit_code = main(
        [
            "ingest",
            "--adapter",
            "csv",
            "--source",
            str(fixtures_dir / "de_nw_sites_invalid.csv"),
            "--out",
            str(tmp_path / "bad.jsonl"),
            "--fail-on-reject",
        ]
    )
    assert exit_code == 1
