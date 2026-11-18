from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class DocumentType(Enum):
    DIGITAL_PDF = auto()
    IMAGE = auto()
    SCANNED_PDF = auto()


@dataclass
class IngestedDocument:
    source_path: Path
    doc_type: DocumentType
    total_pages: int
    json: dict
    markdown: str
    ingestion_ms: float = 0.0


@dataclass
class MappingResult:
    contract_id: str
    carrier: str
    rates: list[dict] = field(default_factory=list)
    origin_arb: list[dict] = field(default_factory=list)
    dest_arb: list[dict] = field(default_factory=list)


@dataclass
class PipelineResult:
    source_file: Path
    success: bool
    document: IngestedDocument | None = None
    extraction: dict | None = None
    mapping: MappingResult | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0
