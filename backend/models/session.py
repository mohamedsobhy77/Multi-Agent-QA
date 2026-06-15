import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base

if TYPE_CHECKING:
    from backend.models.document import Document

from enum import Enum
class SessionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Session(Base):
    """
    Represents a single user analysis session.

    Lifecycle:
      PENDING    → created, document upload in progress
      PROCESSING → text extracted, AI pipeline running
      COMPLETED  → all artifacts generated successfully
      FAILED     → pipeline or ingestion error
    """

    __tablename__ = "sessions"

    # ── Primary key ────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique session identifier (UUIDv4, generated client-side by default).",
    )

    # ── Columns ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SessionStatus.PENDING,
        index=True,
        doc="Current lifecycle status of the session.",
    )

    original_filename: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Original name of the uploaded file as provided by the client.",
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    # server_default  → the database sets the value on INSERT (safe for bulk ops)
    # onupdate        → SQLAlchemy updates this in Python on every flush/commit
    #                   that touches this row.  We use a callable so each call
    #                   produces a fresh datetime rather than a single captured value.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="UTC timestamp when the session row was created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        doc="UTC timestamp automatically refreshed on every row update.",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    # cascade          → deleting a Session automatically deletes its Documents.
    # lazy="selectin"  → avoids N+1: SQLAlchemy fires a single IN-query to load
    #                    documents whenever Sessions are fetched.
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Document.created_at",
        doc="All documents belonging to this session (typically one for MVP).",
    )

    def __repr__(self) -> str:
        return (
            f"<Session id={self.id} "
            f"status={self.status!r} "
            f"file={self.original_filename!r}>"
        )
