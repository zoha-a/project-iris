"""Reproducible command line entry points."""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .adapter import SourceAdapter
from .adapters import CsvSitesAdapter, GeoJsonSitesAdapter
from .models import IngestResult
from .staging import JsonlRejectionWriter, JsonlStagingWriter, PostgresStagingWriter

#: Named shortcuts. Any adapter can also be given as "module:ClassName", so a
#: new source never requires editing this file.
ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {
    "csv": CsvSitesAdapter,
    "geojson": GeoJsonSitesAdapter,
}

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@dataclass(frozen=True)
class DemoSource:
    label: str
    adapter: type[SourceAdapter]
    path: Path


DEMO_SOURCES = (
    DemoSource("de_nw_sites", CsvSitesAdapter, FIXTURES / "de_nw_sites.csv"),
    DemoSource("de_nw_sites_invalid", CsvSitesAdapter, FIXTURES / "de_nw_sites_invalid.csv"),
    DemoSource("nl_ge_sites", GeoJsonSitesAdapter, FIXTURES / "nl_ge_sites.geojson"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iris-ingest", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="ingest every bundled fixture")
    demo.add_argument("--out-dir", default="out", type=Path)
    demo.add_argument("--fetched-at", default=None, help="freeze fetched_at, ISO-8601")
    demo.set_defaults(handler=_demo)

    ingest = subparsers.add_parser("ingest", help="ingest one source")
    ingest.add_argument("--adapter", required=True, help="registry name or 'module:ClassName'")
    ingest.add_argument("--source", required=True, type=Path, help="path to the source file")
    ingest.add_argument("--out", required=True, type=Path, help="canonical JSONL output")
    ingest.add_argument("--rejects", default=None, type=Path, help="rejected records JSONL")
    ingest.add_argument("--dsn", default=None, help="optional PostGIS DSN to also load staging")
    ingest.add_argument("--fetched-at", default=None, help="freeze fetched_at, ISO-8601")
    ingest.add_argument(
        "--fail-on-reject",
        action="store_true",
        help="exit non-zero when any record is rejected",
    )
    ingest.set_defaults(handler=_ingest)

    listing = subparsers.add_parser("list-adapters", help="show registered adapters")
    listing.set_defaults(handler=_list_adapters)

    args = parser.parse_args(argv)
    return args.handler(args)


def _demo(args: argparse.Namespace) -> int:
    clock = _clock(args.fetched_at)
    results: list[IngestResult] = []

    for source in DEMO_SOURCES:
        adapter = source.adapter(source.path, clock=clock)
        result = adapter.run()
        JsonlStagingWriter(args.out_dir / f"{source.label}.jsonl").write(result.records)
        JsonlRejectionWriter(args.out_dir / f"{source.label}.rejects.jsonl").write(result.rejections)
        results.append(result)

    _print_summary(results, args.out_dir)
    return 0


def _ingest(args: argparse.Namespace) -> int:
    adapter_class = _resolve_adapter(args.adapter)
    adapter = adapter_class(args.source, clock=_clock(args.fetched_at))
    result = adapter.run()

    JsonlStagingWriter(args.out).write(result.records)
    if args.rejects:
        JsonlRejectionWriter(args.rejects).write(result.rejections)
    if args.dsn:
        loaded = PostgresStagingWriter(args.dsn, result.source_name).write(result.records)
        print(f"loaded {loaded} record(s) into PostGIS staging")

    _print_summary([result], args.out.parent)
    return 1 if args.fail_on_reject and result.rejected_count else 0


def _list_adapters(_: argparse.Namespace) -> int:
    for name, adapter_class in sorted(ADAPTER_REGISTRY.items()):
        print(f"{name:10s} {adapter_class.__module__}:{adapter_class.__qualname__}")
    print("\nAny SourceAdapter subclass also works as 'module:ClassName'.")
    return 0


def _resolve_adapter(reference: str) -> type[SourceAdapter]:
    if reference in ADAPTER_REGISTRY:
        return ADAPTER_REGISTRY[reference]
    if ":" not in reference:
        known = ", ".join(sorted(ADAPTER_REGISTRY))
        raise SystemExit(f"unknown adapter {reference!r}; try one of: {known}")

    module_name, _, class_name = reference.partition(":")
    adapter_class = getattr(importlib.import_module(module_name), class_name)
    if not issubclass(adapter_class, SourceAdapter):
        raise SystemExit(f"{reference} is not a SourceAdapter subclass")
    return adapter_class


def _clock(frozen: str | None):
    if frozen is None:
        return None
    moment = datetime.fromisoformat(frozen.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return lambda: moment


def _print_summary(results: list[IngestResult], out_dir: Path) -> None:
    width = max((len(result.source_name) for result in results), default=6)
    print(f"{'source'.ljust(width)}  accepted  rejected  reasons")
    for result in results:
        reasons = ", ".join(f"{key}={value}" for key, value in result.reasons().items()) or "-"
        print(
            f"{result.source_name.ljust(width)}  "
            f"{result.accepted_count:>8}  {result.rejected_count:>8}  {reasons}"
        )
    print(f"\noutput written to {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
