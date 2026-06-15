"""
api/v1/endpoints/upload.py
──────────────────────────
Upload and session-status endpoints.

Routes
------
POST /api/v1/upload
    Accept a multipart file upload, run the full ingestion pipeline,
    and return a populated UploadResponse.

GET /api/v1/sessions/{session_id}
    Return the current status and document metadata for an existing session.
    Used by the frontend to poll pipeline progress in Sprint 2+.

Exception → HTTP mapping
------------------------
UnsupportedFileTypeError  → 422  (file format not supported)
FileTooLargeError         → 413  (payload too large)
EmptyDocumentError        → 400  (file has no usable content)
TextExtractionError       → 422  (file is supported but parser failed)
Session not found         → 404
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.models.session import Session
from backend.schemas.document import DocumentSummary, FileType, UploadResponse
from backend.schemas.session import SessionResponse, SessionStatus
from backend.services.exceptions import (
    EmptyDocumentError,
    FileTooLargeError,
    TextExtractionError,
    UnsupportedFileTypeError,
)
from backend.services.ingest import ingest_document

router = APIRouter()


# ── POST /upload ──────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a requirement document",
    description=(
        "Upload a PDF, DOCX, or TXT requirements document. "
        "Text is extracted synchronously; the session is persisted and a "
        "`session_id` is returned for polling the AI pipeline in subsequent "
        "sprints via `GET /api/v1/sessions/{session_id}`."
    ),
    responses={
        201: {"description": "Document uploaded and text extracted."},
        400: {"description": "File is empty or contains no usable text."},
        413: {"description": "File exceeds the 20 MB size limit."},
        422: {"description": "Unsupported file type or parser failure."},
    },
)
async def upload_document(
    file: UploadFile = File(
        ...,
        description="Requirement document to analyse (.pdf, .docx, or .txt).",
    ),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """
    Run the full ingestion pipeline:
      1. Validate extension, size, and raw content.
      2. Extract plain text (PDF / DOCX / TXT).
      3. Persist Session + Document rows.
      4. Return UploadResponse with session_id for polling.

    The database transaction is committed by the `get_db()` dependency after
    this function returns.  On any exception get_db() rolls back automatically.
    """
    try:
        return await ingest_document(upload=file, db=db)

    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": str(exc),
                "filename": exc.filename,
                "actual_mb": round(exc.actual_bytes / (1024 * 1024), 2),
                "max_mb": round(exc.max_bytes / (1024 * 1024), 0),
            },
        ) from exc

    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": str(exc),
                "filename": exc.filename,
                "detected_extension": exc.detected_extension,
                "allowed_extensions": exc.allowed_extensions,
            },
        ) from exc

    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EMPTY_DOCUMENT",
                "message": str(exc),
                "filename": exc.filename,
                "reason": exc.reason,
            },
        ) from exc

    except TextExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "TEXT_EXTRACTION_FAILED",
                "message": str(exc),
                "filename": exc.filename,
                "file_type": exc.file_type,
                "reason": exc.reason,
            },
        ) from exc


# ── GET /sessions/{session_id} ────────────────────────────────────────────────

@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get session status",
    description=(
        "Retrieve the current lifecycle status and document metadata for an "
        "existing session.  Poll this endpoint to track pipeline progress once "
        "the AI pipeline is wired in Sprint 2."
    ),
    responses={
        200: {"description": "Session found and returned."},
        404: {"description": "No session exists for the given ID."},
    },
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """
    Load a Session by its UUID primary key.

    The Session ORM model uses lazy="selectin" on the `documents` relationship,
    so the query returns the associated Document rows in a single IN-query
    without an additional round-trip.

    Returns SessionResponse with an inline DocumentSummary when a document
    is attached, or document=None for sessions that failed before persistence.
    """
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session: Session | None = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": f"Session '{session_id}' does not exist.",
                "session_id": str(session_id),
            },
        )

    # Build DocumentSummary from the first (and normally only) document.
    # Sprint 1 enforces one document per session; the list model on the ORM
    # exists to leave the door open for multi-document sessions later.
    doc_summary: DocumentSummary | None = None
    if session.documents:
        doc = session.documents[0]
        doc_summary = DocumentSummary(
            id=doc.id,
            session_id=doc.session_id,
            file_type=FileType(doc.file_type),
            original_filename=doc.original_filename,
            file_size_bytes=doc.file_size_bytes,
            char_count=doc.char_count,
            created_at=doc.created_at,
        )

    return SessionResponse(
        id=session.id,
        status=SessionStatus(session.status),
        original_filename=session.original_filename,
        created_at=session.created_at,
        updated_at=session.updated_at,
        document=doc_summary,
    )
