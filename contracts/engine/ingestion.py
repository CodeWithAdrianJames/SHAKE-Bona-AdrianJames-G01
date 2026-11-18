from __future__ import annotations

import json
import time
from pathlib import Path

import opendataloader_pdf
import pymupdf

from contracts.engine.errors import IngestionError, UnsupportedDocumentError
from contracts.engine.models import DocumentType, IngestedDocument
from contracts.utils.logger import get_shared_logger

logger = get_shared_logger(__name__)


def classify_document(file_path: Path, sample_pages: int = 3) -> DocumentType:
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        return DocumentType.IMAGE

    if ext == ".pdf":
        try:
            char_counts: list[int] = []
            with pymupdf.open(str(file_path)) as doc:
                pages_to_check = min(sample_pages, len(doc))
                for page_num in range(pages_to_check):
                    text = doc[page_num].get_text("text")
                    char_counts.append(len(text.strip()))

            if not char_counts or (sum(char_counts) / len(char_counts)) < 150:
                return DocumentType.SCANNED_PDF

            return DocumentType.DIGITAL_PDF

        except Exception as exc:
            logger.warning("PyMuPDF read failed for %s: %s", file_path.name, exc)
            return DocumentType.SCANNED_PDF

    raise ValueError(f"Unsupported file extension: {ext}")


def ingest_file(file_path: Path | str, output_path: Path | str) -> IngestedDocument:
    file_path = Path(file_path)
    output_path = Path(output_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    doc_type = classify_document(file_path)
    if doc_type in (DocumentType.IMAGE, DocumentType.SCANNED_PDF):
        logger.error(
            "[OpenDataLoader] Scanned and/or Images are not allowed: %s",
            file_path.name,
        )
        raise UnsupportedDocumentError(
            f"Scanned PDFs and images are not allowed: {file_path.name}"
        )

    output_path.mkdir(parents=True, exist_ok=True)
    logger.info("[OpenDataLoader] Converting %s ...", file_path.name)
    t_start = time.perf_counter()

    try:
        convert(file_path, output_path)
    except Exception as exc:
        raise IngestionError(
            f"PDF layout conversion failed for {file_path.name}: {exc}"
        ) from exc

    json_file = output_path / f"{file_path.stem}.json"
    if not json_file.exists():
        files = list(output_path.glob("*.json"))
        if not files:
            raise FileNotFoundError(f"JSON output not generated for {file_path.name}")
        json_file = files[0]

    md_file = json_file.with_suffix(".md")
    if not md_file.exists():
        raise FileNotFoundError(f"Markdown pair not found for {json_file.name}")

    data = json.loads(json_file.read_text(encoding="utf-8"))
    full_markdown = md_file.read_text(encoding="utf-8")
    total_pages = data.get("number of pages", 0)

    elapsed_ms = (time.perf_counter() - t_start) * 1000
    logger.info(
        "Ingested %s: %s pages in %.0fms [%s]",
        file_path.name,
        total_pages,
        elapsed_ms,
        doc_type.name,
    )

    return IngestedDocument(
        source_path=file_path,
        doc_type=doc_type,
        total_pages=total_pages,
        json=data,
        markdown=full_markdown,
        ingestion_ms=elapsed_ms,
    )


def convert(file_path: Path, output_path: Path) -> None:
    opendataloader_pdf.convert(
        input_path=str(file_path),
        output_dir=str(output_path),
        format=["json", "markdown"],
        use_struct_tree=True,
        table_method="cluster",
        quiet=True,
    )
    logger.info("Java-only conversion succeeded.")


def ingest_batch(
    file_paths: list[Path], output_path: Path
) -> list[IngestedDocument]:
    output_path.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    opendataloader_pdf.convert(
        input_path=[str(p) for p in file_paths],
        output_dir=str(output_path),
        format=["json", "markdown"],
        use_struct_tree=True,
        table_method="cluster",
        quiet=True,
    )
    logger.info(
        "Batch conversion of %d file(s) completed in %.0fms",
        len(file_paths),
        (time.perf_counter() - t_start) * 1000,
    )

    docs: list[IngestedDocument] = []
    for file_path in file_paths:
        json_file = output_path / f"{file_path.stem}.json"
        if not json_file.exists():
            candidates = list(output_path.glob("*.json"))
            if not candidates:
                raise FileNotFoundError(
                    f"JSON output not generated for {file_path.name}"
                )
            json_file = candidates[0]

        md_file = json_file.with_suffix(".md")
        if not md_file.exists():
            raise FileNotFoundError(f"Markdown pair not found for {json_file.name}")

        data = json.loads(json_file.read_text(encoding="utf-8"))
        docs.append(
            IngestedDocument(
                source_path=file_path,
                doc_type=DocumentType.DIGITAL_PDF,
                total_pages=data.get("number of pages", 0),
                json=data,
                markdown=md_file.read_text(encoding="utf-8"),
            )
        )

    return docs
