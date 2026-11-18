"""
Custom exceptions for the SHAKE extraction pipeline.
"""


class ShakeError(Exception):
    """Base exception for all domain logic errors in SHAKE."""


class IngestionError(ShakeError):
    """Raised when PDF ingestion or text conversion fails."""


class UnsupportedDocumentError(ShakeError):
    """Raised when a document type (like an image or scanned PDF) cannot be processed."""


class ExtractionError(ShakeError):
    """Raised when structured data extraction fails."""


class MappingError(ShakeError):
    """Raised when data mapping fails."""


class ExportError(ShakeError):
    """Raised when exporting to JSON/CSV/XLSX fails."""
