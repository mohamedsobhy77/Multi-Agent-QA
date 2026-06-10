"""
services/ingest.py
──────────────────
Document ingestion pipeline — the single entry point for the upload flow.

Pipeline (all steps run inside one database transaction):

    1. validate_upload()      → check extension, size, and raw emptiness
    2. extract_text_async()   → parse PDF / DOCX / TXT into plain text
    3. Session (ORM)          → create and flush to obtain session.id
    4. Document (ORM)         → create with FK to session, flush
    5. commit()               → persisted by the caller's get_db() dependency,
                                 or explicitly via ingest_document() when called
                                 outside a FastAPI request context
    6. UploadResponse         → build from flushed ORM state and return

Transaction safety
    The caller is expected to pass in an AsyncSession managed by get_db().
    get_db() commits on success and rolls back on any exception, so this
    service only calls flush() — never commit() or rollback() directly.
    For standalone / test use, ingest_document_standalone() wraps the call
    in its own commit.

Exception propagation
    Domain exceptions (UnsupportedFileTypeError, FileTooLargeError,
    EmptyDocumentError, TextExtractionError) are NOT caught here.  They
    propagate to the endpoint layer where they are mapped to HTTP responses.
    Unexpected exceptions also propagate; the get_db() dependency's except
    block rolls back the transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document
from models.session import Session, SessionStatus
from schemas.document import DocumentSummary, FileType, UploadResponse
from services.exceptions import (
    EmptyDocumentError,
    FileTooLargeError,
    TextExtractionError,
    UnsupportedFileTypeError,
)
from backend.services.file_validator import validate_upload
from backend.services.text_extractor import extract_text_async 


async def ingest_document(
    upload: UploadFile,
    db: AsyncSession,
) -> UploadResponse:
    """
    Run the full ingestion pipeline for one uploaded file.

    Parameters
    ----------
    upload:
        FastAPI UploadFile — the raw multipart file object from the endpoint.
        The entire file body is read into memory; enforce size limits before
        calling this function if memory pressure is a concern, or rely on the
        validate_upload() call inside this function to reject oversized files
        before processing begins.
    db:
        An open AsyncSession.  The session is flushed (not committed) inside
        this function.  Commit / rollback is the caller's responsibility.

    Returns
    -------
    UploadResponse
        Fully populated response schema ready to be returned from the endpoint.

    Raises
    ------
    UnsupportedFileTypeError
        The file extension is not in the allow-list (.pdf, .docx, .txt).
    FileTooLargeError
        The file exceeds MAX_UPLOAD_SIZE_BYTES (20 MB by default).
    EmptyDocumentError
        The file is empty, whitespace-only, or the parser produced no text
        (e.g. an image-only PDF with no text layer).
    TextExtractionError
        The file format is supported but the parser raised an unexpected error
        (corrupt file, unsupported internal format, etc.).
    SQLAlchemyError
        Any database-level error during flush — propagated as-is.
    """

    # ── Step 1: Read raw bytes ────────────────────────────────────────────────
    # Reading the full body before validation is intentional: we need the byte
    # length for the size check.  For very large uploads you could stream and
    # count bytes incrementally, but 20 MB fits comfortably in application memory.
    content: bytes = await upload.read()
    filename: str = upload.filename or "unknown"

    # ── Step 2: Validate (extension · size · raw emptiness) ──────────────────
    # Raises UnsupportedFileTypeError, FileTooLargeError, or EmptyDocumentError.
    # All three propagate to the caller without being caught here.
    validation = validate_upload(filename=filename, content=content)

    # ── Step 3: Extract text (CPU-bound, runs in thread pool) ─────────────────
    # extract_text_async() offloads to ThreadPoolExecutor internally so this
    # await does not block the event loop.
    # Raises EmptyDocumentError or TextExtractionError on failure.
    raw_text: str = await extract_text_async(
        data=content,
        file_type=validation.file_type,
        filename=validation.original_filename,
    )

    # ── Step 4: Persist Session ───────────────────────────────────────────────
    # flush() writes the INSERT and populates session.id without committing the
    # transaction.  If anything fails in subsequent steps, get_db() rolls back
    # and the session row is never committed to the database.
    session = Session(
        id=uuid.uuid4(),
        original_filename=validation.original_filename,
        status=SessionStatus.PENDING,
    )
    db.add(session)
    await db.flush()  # session.id is now available

    # ── Step 5: Persist Document ──────────────────────────────────────────────
    document = Document(
        id=uuid.uuid4(),
        session_id=session.id,
        file_type=validation.file_type,
        original_filename=validation.original_filename,
        file_size_bytes=validation.file_size_bytes,
        raw_text=raw_text,
        char_count=len(raw_text),
    )
    db.add(document)
    await db.flush()  # document.id and document.created_at are now available

    # ── Step 6: Build and return UploadResponse ───────────────────────────────
    # We construct the schema manually rather than using model_validate(document)
    # to avoid a second database round-trip: after flush() the ORM object is
    # fully populated in the identity map without needing a SELECT.
    return _build_upload_response(session=session, document=document)


# ── Private helper ────────────────────────────────────────────────────────────

def _build_upload_response(
    session: Session,
    document: Document,
) -> UploadResponse:
    """
    Construct an UploadResponse from flushed ORM instances.

    Using explicit field mapping (rather than model_validate) guarantees that
    no lazy-loaded attributes are accessed — safe in async context where
    implicit I/O raises greenlet errors.

    Parameters
    ----------
    session:  A flushed Session ORM instance (id, status, and timestamps set).
    document: A flushed Document ORM instance (id, created_at set).
    """
    # created_at is set by the DB server_default on flush; fall back to now()
    # only if the attribute was not populated (e.g. in unit tests using SQLite
    # where server_default may not fire synchronously).
    doc_created_at: datetime = document.created_at or datetime.now(timezone.utc)

    document_summary = DocumentSummary(
        id=document.id,
        session_id=document.session_id,
        file_type=FileType(document.file_type),
        original_filename=document.original_filename,
        file_size_bytes=document.file_size_bytes,
        char_count=document.char_count,
        created_at=doc_created_at,
    )

    return UploadResponse(
        session_id=session.id,
        status=session.status,
        original_filename=session.original_filename,
        document=document_summary,
    )
