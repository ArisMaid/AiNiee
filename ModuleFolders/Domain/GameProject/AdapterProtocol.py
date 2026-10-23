"""Backend-neutral extraction and write contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from .Models import TranslationUnit, Issue


@dataclass(frozen=True)
class ExtractionResult:
    units: tuple[TranslationUnit, ...] = ()
    issues: tuple[Issue, ...] = ()
    files: tuple[dict, ...] = ()
    stats: dict = field(default_factory=dict)


class GameAdapter(Protocol):
    adapter_id: str
    version: str

    def probe(self, source): ...
    def capabilities(self) -> dict: ...
    def extract(self, source, profile=None, progress=None, document_cache=None) -> ExtractionResult: ...
