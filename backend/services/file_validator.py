"""
services/file_validator.py
──────────────────────────
Stateless file validation layer.

Responsibilities
  • Validate filename extension against the allow-list
  • Validate raw file size against the configured ceiling
  • Validate that the file is not empty or whitespace-only after read

All functions are synchronous and pure (no I/O, no DB).
They are async-friendly: call them directly inside any async endpoint or
service without wrapping in run_in_executor.

Raises
  UnsupportedFileTypeError  – extension is not in the allow-list
  FileTooLargeError         – byte size exceeds MAX_UPLOAD_SIZE_BYTES
  EmptyDocumentError        – file contains no usable content
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from services.exceptions import (
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum upload size: 20 MB (mirrors config.MAX_UPLOAD_SIZE_MB)
MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024

# Maps lowercase extension (with dot) → canonical file-type key.
# Adding a new format only requires an entry here and a matching extractor.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf":  "pdf",
    ".docx": "docx",
    ".txt":  "txt",
}

# Minimum number of non-whitespace bytes to consider a file non-empty.
MIN_CONTENT_BYTES: int = 10


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ValidationResult:
    """
    Value object returned by validate_upload on success.

    Attributes
    ----------
    file_type:
        Canonical type string derived from the extension: 'pdf', 'docx', or 'txt'.
    original_filename:
        Sanitised (stripped) original filename.
    file_size_bytes:
        Length of the raw content in bytes.
    """
    file_type: str
    original_filename: str
    file_size_bytes: int


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalise_filename(filename: str | None) -> str:
    """
    Strip whitespace and path components from a raw filename.

    os.path.basename handles both POSIX and Windows separators so that
    a client sending 'uploads/../../evil.pdf' cannot cause a traversal issue.
    """
    if not filename:
        return ""
    return os.path.basename(filename.strip())


def _get_extension(filename: str) -> str:
    """Return the lowercased file extension including the leading dot."""
    _, ext = os.path.splitext(filename)
    return ext.lower()


# ── Public API ────────────────────────────────────────────────────────────────

def validate_upload(
    filename: str | None,
    content: bytes,
    *,
    max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES,
) -> ValidationResult:
    """
    Validate a raw file upload.

    Parameters
    ----------
    filename:
        Original filename supplied by the client (may include path components).
    content:
        Raw bytes of the uploaded file.
    max_size_bytes:
        Override the default size ceiling (useful in tests).

    Returns
    -------
    ValidationResult
        Populated on success.

    Raises
    ------
    UnsupportedFileTypeError
        If the extension is missing or not in ALLOWED_EXTENSIONS.
    FileTooLargeError
        If len(content) > max_size_bytes.
    EmptyDocumentError
        If the file has no usable content (zero bytes or all whitespace).
    """
    clean_name = _normalise_filename(filename)

    # ── 1. Extension check ────────────────────────────────────────────────────
    # Done first so the error message names the offending file type before we
    # waste time reading sizes or content.
    ext = _get_extension(clean_name)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            filename=clean_name or "<unknown>",
            detected_extension=ext or "<none>",
            allowed_extensions=list(ALLOWED_EXTENSIONS.keys()),
        )

    file_type = ALLOWED_EXTENSIONS[ext]

    # ── 2. Size check ─────────────────────────────────────────────────────────
    size = len(content)
    if size > max_size_bytes:
        raise FileTooLargeError(
            filename=clean_name,
            actual_bytes=size,
            max_bytes=max_size_bytes,
        )

    # ── 3. Empty content check ────────────────────────────────────────────────
    # We check raw bytes here, not extracted text.  The text extractor performs
    # its own post-extraction emptiness check; this guard catches zero-byte
    # files before we even attempt parsing.
    if size == 0 or len(content.strip()) < MIN_CONTENT_BYTES:
        raise EmptyDocumentError(
            filename=clean_name,
            reason="File is empty or contains only whitespace.",
        )

    return ValidationResult(
        file_type=file_type,
        original_filename=clean_name,
        file_size_bytes=size,
    )


def is_allowed_extension(filename: str) -> bool:
    """
    Quick boolean check — does this filename have a supported extension?

    Useful for early-exit checks in multipart upload handlers before reading
    the full file body.
    """
    return _get_extension(_normalise_filename(filename)) in ALLOWED_EXTENSIONS


def allowed_extensions() -> list[str]:
    """Return the sorted list of allowed extensions (e.g. ['.docx', '.pdf', '.txt'])."""
    return sorted(ALLOWED_EXTENSIONS.keys())
