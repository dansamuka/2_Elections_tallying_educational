from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import CandidateReference, StreamsReference


@dataclass(frozen=True)
class ReferenceBundle:
    candidates: CandidateReference
    streams: StreamsReference

    @property
    def complete(self) -> bool:
        return (
            self.candidates.source_verified
            and self.candidates.ballot_order_verified
            and self.streams.complete
        )

    def production_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.candidates.source_verified:
            errors.append("candidate list source is not marked verified")
        if not self.candidates.ballot_order_verified:
            errors.append("candidate ballot order is not marked verified")
        if len(self.streams.streams) != 144:
            errors.append(f"expected 144 stream rows, found {len(self.streams.streams)}")
        if not self.streams.register_source_verified:
            errors.append("certified stream register source is not marked verified")
        unresolved = [s.stream_key for s in self.streams.streams if s.registered is None]
        if unresolved:
            errors.append(f"{len(unresolved)} stream rows have no registered-voter value")
        if all(s.registered is not None for s in self.streams.streams):
            total = sum(int(s.registered or 0) for s in self.streams.streams)
            if total != self.streams.register_total:
                errors.append(
                    f"stream registered-voter sum is {total}, expected {self.streams.register_total}"
                )
        return errors


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_reference(candidates_path: Path, streams_path: Path) -> ReferenceBundle:
    return ReferenceBundle(
        candidates=CandidateReference.model_validate(_load(candidates_path)),
        streams=StreamsReference.model_validate(_load(streams_path)),
    )
