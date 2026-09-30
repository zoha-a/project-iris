"""The adapter contract.

A new IRIS source is added by subclassing :class:`SourceAdapter` and writing
two methods. Extraction and field mapping are source-specific; normalization,
validation and the staging handoff are owned by this module and are marked
``@final`` so a source cannot quietly opt out of the rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar, final

from .models import (
    CanonicalRecord,
    IngestResult,
    RecordRejected,
    RejectedRecord,
    RejectionReason,
    SourceRecord,
)
from .validation import normalize_and_validate

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceAdapter(ABC):
    """Base class every IRIS source adapter implements.

    Subclasses must set :attr:`source_name` and implement :meth:`extract` and
    :meth:`to_source_record`. Everything else is inherited.
    """

    #: Stable identifier for the source, used in logs and staging rows.
    source_name: ClassVar[str] = ""

    #: Optional prefix applied to the source's own key to build ``source_id``.
    source_id_prefix: ClassVar[str] = ""

    def __init__(self, *, clock: Clock | None = None) -> None:
        if not type(self).source_name:
            raise TypeError(f"{type(self).__name__} must define a non-empty 'source_name'")
        self._clock: Clock = clock or utc_now

    @property
    def source_uri(self) -> str:
        """Where this adapter reads from, for reporting. Override when useful."""
        return self.source_name

    @abstractmethod
    def extract(self) -> Iterator[Mapping[str, Any]]:
        """Yield raw records exactly as the source provides them."""

    @abstractmethod
    def to_source_record(self, raw: Mapping[str, Any]) -> SourceRecord:
        """Map one raw record onto the shared :class:`SourceRecord` fields."""

    @final
    def run(self) -> IngestResult:
        """Extract, normalize, validate and collect results for this source."""
        fetched_at = self._clock()
        records: list[CanonicalRecord] = []
        rejections: list[RejectedRecord] = []

        for raw in self.extract():
            outcome = self._process(raw, fetched_at)
            if isinstance(outcome, CanonicalRecord):
                records.append(outcome)
            else:
                rejections.append(outcome)

        return IngestResult(
            source_name=self.source_name,
            source_uri=self.source_uri,
            records=tuple(records),
            rejections=tuple(rejections),
        )

    @final
    def _process(
        self, raw: Mapping[str, Any], fetched_at: datetime
    ) -> CanonicalRecord | RejectedRecord:
        try:
            source_record = self.to_source_record(raw)
        except RecordRejected as exc:
            return self._reject(raw, None, exc.reason, exc.message)
        except Exception as exc:  # a broken mapping must not abort the whole run
            return self._reject(raw, None, RejectionReason.MAPPING_ERROR, str(exc))

        try:
            return normalize_and_validate(
                source_record,
                source_id_prefix=self.source_id_prefix,
                fetched_at=fetched_at,
            )
        except RecordRejected as exc:
            key = source_record.source_key
            return self._reject(
                raw,
                None if key is None else str(key).strip() or None,
                exc.reason,
                exc.message,
            )

    def _reject(
        self,
        raw: Mapping[str, Any],
        source_key: str | None,
        reason: RejectionReason,
        message: str,
    ) -> RejectedRecord:
        return RejectedRecord(
            reason=reason,
            message=message,
            source_name=self.source_name,
            source_key=source_key,
            raw=dict(raw),
        )


def run_all(adapters: Iterable[SourceAdapter]) -> list[IngestResult]:
    """Convenience helper for running several adapters in sequence."""
    return [adapter.run() for adapter in adapters]
