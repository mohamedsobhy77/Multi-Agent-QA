"""
services/exceptions.py
──────────────────────
Domain exceptions for the file ingestion pipeline.

All exceptions carry structured attributes so callers can build precise
error responses without parsing message strings.
"""

from __future__ import annotations


class QACopilotError(Exception):
    """Base class for all application-domain errors."""


# ── File validation exceptions ────────────────────────────────────────────────

class UnsupportedFileTypeError(QACopilotError):
    """
    Raised when the uploaded file's extension is not in the allow-list.

    Attributes
    ----------
    filename:           The original (or sanitised) filename.
    detected_extension: The extension that was found, e.g. '.xlsx'.
    allowed_extensions: The list of accepted extensions, e.g. ['.pdf', ...].
    """

    def __init__(
        self,
        filename: str,
        detected_extension: str,
        allowed_extensions: list[str],
    ) -> None:
        self.filename = filename
        self.detected_extension = detected_extension
        self.allowed_extensions = sorted(allowed_extensions)
        super().__init__(
            f"Unsupported file type {detected_extension!r} for {filename!r}. "
            f"Accepted extensions: {', '.join(self.allowed_extensions)}."
        )


class FileTooLargeError(QACopilotError):
    """
    Raised when the uploaded file exceeds the configured size limit.

    Attributes
    ----------
    filename:     The original filename.
    actual_bytes: Actual byte size of the file.
    max_bytes:    The configured ceiling in bytes.
    """

    def __init__(self, filename: str, actual_bytes: int, max_bytes: int) -> None:
        self.filename = filename
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes
        actual_mb = actual_bytes / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)
        super().__init__(
            f"{filename!r} is {actual_mb:.1f} MB, "
            f"which exceeds the {max_mb:.0f} MB limit."
        )


class EmptyDocumentError(QACopilotError):
    """
    Raised when a file passes size validation but contains no usable content.

    This covers:
      • Zero-byte files
      • Files whose raw bytes are all whitespace
      • PDFs/DOCXs that parse to an empty or whitespace-only text body
        (e.g. scanned image-only PDFs with no text layer)

    Attributes
    ----------
    filename: The original filename.
    reason:   Human-readable explanation of why the content was considered empty.
    """

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(
            f"No usable text content in {filename!r}: {reason}"
        )


class TextExtractionError(QACopilotError):
    """
    Raised when the parser for a supported file type throws an unexpected error.

    This is distinct from EmptyDocumentError: the file has content but the
    parser itself failed (corrupt file, unsupported internal format, etc.).

    Attributes
    ----------
    filename:  The original filename.
    file_type: The type that was attempted ('pdf', 'docx', 'txt').
    reason:    The underlying error message from the parser.
    cause:     The original exception, if available.
    """

    def __init__(
        self,
        filename: str,
        file_type: str,
        reason: str,
        cause: BaseException | None = None,
    ) -> None:
        self.filename = filename
        self.file_type = file_type
        self.reason = reason
        self.cause = cause
        super().__init__(
            f"Failed to extract text from {filename!r} "
            f"(type={file_type!r}): {reason}"
        )
