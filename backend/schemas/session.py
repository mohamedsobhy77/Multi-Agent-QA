import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Status enum ───────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    """
    Lifecycle states of an analysis session.

    Inheriting from str ensures the value serialises as a plain string
    (e.g. "PENDING") in JSON rather than {"value": "PENDING"}.
    """
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"


# ── Shared config ─────────────────────────────────────────────────────────────

class _Base(BaseModel):
    """
    Shared Pydantic config for all session schemas.

    from_attributes=True  → allows constructing from SQLAlchemy ORM instances
                            via model_validate(orm_obj).
    populate_by_name=True → accepts both alias and field name in input data.
    """
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SessionCreateRequest(_Base):
    """
    Body for manually creating a session (used in tests and admin tooling).

    In the normal upload flow the session is created implicitly by the ingest
    service — this schema exists for cases where you want to pre-create a
    session before attaching a document.
    """
    original_filename: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description="Original name of the file the user intends to upload.",
            examples=["requirements_v2.pdf"],
        ),
    ]

    @field_validator("original_filename")
    @classmethod
    def filename_must_have_valid_extension(cls, v: str) -> str:
        allowed = {".pdf", ".docx", ".txt"}
        suffix = "." + v.rsplit(".", 1)[-1].lower() if "." in v else ""
        if suffix not in allowed:
            raise ValueError(
                f"Filename must end with one of {sorted(allowed)}, got {v!r}."
            )
        return v.strip()


class SessionStatusUpdateRequest(_Base):
    """
    Body for updating only the status of an existing session.
    Used by the n8n pipeline callback in Sprint 2.
    """
    status: SessionStatus = Field(
        ...,
        description="New lifecycle status to apply to the session.",
        examples=[SessionStatus.PROCESSING],
    )


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SessionResponse(_Base):
    """
    Full session representation returned to the client.
    Maps directly to the Session ORM model.
    """
    id: uuid.UUID = Field(
        ...,
        description="Unique session identifier.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    status: SessionStatus = Field(
        ...,
        description="Current lifecycle status.",
    )
    original_filename: str = Field(
        ...,
        description="Name of the uploaded file.",
        examples=["requirements_v2.pdf"],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the session was created.",
    )
    updated_at: datetime = Field(
        ...,
        description="UTC timestamp of the most recent update.",
    )

    # Inline document summary — present after a file has been ingested.
    # Declared as forward-ref string; resolved below via model_rebuild().
    document: "DocumentSummary | None" = Field(
        default=None,
        description="Summary of the attached document, if ingestion has completed.",
    )


class SessionCreateResponse(_Base):
    """
    Slim response returned immediately after the upload endpoint creates
    a session.  The client uses session_id to poll /sessions/{id}.
    """
    session_id: uuid.UUID = Field(
        ...,
        description="Use this ID to poll pipeline status.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    status: SessionStatus = Field(
        default=SessionStatus.PENDING,
        description="Always PENDING immediately after creation.",
    )
    original_filename: str = Field(
        ...,
        description="Name of the uploaded file.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the session was created.",
    )
    message: str = Field(
        default="Session created. Document upload accepted.",
        description="Human-readable confirmation message.",
    )


class SessionListResponse(_Base):
    """Paginated list of sessions."""
    items: list[SessionResponse] = Field(
        default_factory=list,
        description="Page of session objects.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of sessions matching the query.",
    )
    page: int = Field(
        ...,
        ge=1,
        description="Current page number (1-based).",
    )
    page_size: int = Field(
        ...,
        ge=1,
        le=100,
        description="Number of items per page.",
    )


# ── Forward-reference resolution ──────────────────────────────────────────────
# Imported here (after SessionResponse is defined) to avoid a circular import.
# document.py imports SessionStatus from this module; it does NOT import
# SessionResponse — so the import below is safe.

from schemas.document import DocumentSummary  # noqa: E402

SessionResponse.model_rebuild()
