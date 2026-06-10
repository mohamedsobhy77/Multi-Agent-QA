import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── File-type enum ────────────────────────────────────────────────────────────

class FileType(str, Enum):
    """Accepted upload formats."""
    PDF  = "pdf"
    DOCX = "docx"
    TXT  = "txt"


# ── Shared config ─────────────────────────────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class DocumentUploadMeta(_Base):
    """
    Metadata extracted from the multipart upload and validated before
    the file bytes are passed to the ingest service.

    The actual file bytes are handled by FastAPI's UploadFile — this
    schema validates only the metadata fields that travel alongside the file.
    """
    original_filename: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description="Original filename as supplied by the client.",
            examples=["product_requirements.pdf"],
        ),
    ]
    file_size_bytes: Annotated[
        int,
        Field(
            gt=0,
            le=20 * 1024 * 1024,   # 20 MB hard cap; mirrors config.MAX_UPLOAD_SIZE_MB
            description="Raw byte size of the uploaded file.",
            examples=[204_800],
        ),
    ]

    @field_validator("original_filename")
    @classmethod
    def validate_extension(cls, v: str) -> str:
        allowed = {".pdf", ".docx", ".txt"}
        dot_idx = v.rfind(".")
        ext = v[dot_idx:].lower() if dot_idx != -1 else ""
        if ext not in allowed:
            raise ValueError(
                f"File extension must be one of {sorted(allowed)}. "
                f"Received: {v!r}."
            )
        return v.strip()

    @field_validator("original_filename")
    @classmethod
    def no_path_traversal(cls, v: str) -> str:
        """Reject filenames that contain directory separators."""
        if "/" in v or "\\" in v:
            raise ValueError(
                "Filename must not contain path separators ('/' or '\\')."
            )
        return v

    @property
    def file_type(self) -> FileType:
        """Derive the FileType enum value from the filename extension."""
        ext = self.original_filename.rsplit(".", 1)[-1].lower()
        return FileType(ext)


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class DocumentSummary(_Base):
    """
    Lightweight document representation embedded inside SessionResponse.
    Omits raw_text to keep the payload small.
    """
    id: uuid.UUID = Field(
        ...,
        description="Unique document identifier.",
    )
    session_id: uuid.UUID = Field(
        ...,
        description="Parent session this document belongs to.",
    )
    file_type: FileType = Field(
        ...,
        description="Detected file format.",
        examples=[FileType.PDF],
    )
    original_filename: str = Field(
        ...,
        description="Name of the uploaded file.",
        examples=["requirements.pdf"],
    )
    file_size_bytes: int = Field(
        ...,
        ge=1,
        description="Raw file size in bytes.",
        examples=[204_800],
    )
    char_count: int = Field(
        ...,
        ge=0,
        description="Number of characters in the extracted plain text.",
        examples=[14_532],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the document row was created.",
    )


class DocumentResponse(_Base):
    """
    Full document representation including extracted text.
    Returned by endpoints that need the raw content (e.g. internal debug).
    """
    id: uuid.UUID = Field(..., description="Unique document identifier.")
    session_id: uuid.UUID = Field(..., description="Parent session identifier.")
    file_type: FileType = Field(..., description="Detected file format.")
    original_filename: str = Field(..., description="Original upload filename.")
    file_size_bytes: int = Field(..., ge=1, description="Raw file size in bytes.")
    raw_text: str = Field(
        ...,
        min_length=1,
        description="Full plain-text content extracted from the file.",
    )
    char_count: int = Field(
        ...,
        ge=0,
        description="Character count of raw_text; pre-computed for quick access.",
    )
    created_at: datetime = Field(..., description="UTC creation timestamp.")
    updated_at: datetime = Field(..., description="UTC last-update timestamp.")

    @model_validator(mode="after")
    def char_count_matches_raw_text(self) -> "DocumentResponse":
        """
        Soft-validate that char_count is consistent with raw_text length.
        Logs a discrepancy rather than raising so stale DB rows don't 500.
        """
        actual = len(self.raw_text)
        if self.char_count != actual:
            # In production you would log this; raise only in strict mode.
            object.__setattr__(self, "char_count", actual)
        return self


class UploadResponse(_Base):
    """
    Top-level response for POST /api/v1/upload.
    This is the schema the client receives after a successful file upload.
    """
    session_id: uuid.UUID = Field(
        ...,
        description=(
            "Use this ID to poll GET /api/v1/sessions/{session_id} "
            "for pipeline progress."
        ),
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    status: str = Field(
        ...,
        description="Initial session status; always 'PENDING' on upload.",
        examples=["PENDING"],
    )
    original_filename: str = Field(
        ...,
        description="Name of the file that was uploaded.",
        examples=["requirements_v2.pdf"],
    )
    document: DocumentSummary = Field(
        ...,
        description="Metadata of the stored document.",
    )
    message: str = Field(
        default="Document uploaded and text extracted successfully.",
        description="Human-readable confirmation.",
    )
