import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base

if TYPE_CHECKING:
    from backend.models.session import Session

from enum import Enum

class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"

    ALL = [PDF, DOCX, TXT]


class Document(Base):
    """
    Stores the extracted plain-text content of an uploaded file.

    One Document belongs to one Session.  The cascade delete on the foreign key
    (ondelete="CASCADE") ensures PostgreSQL removes Document rows automatically
    when the parent Session is deleted — even outside of SQLAlchemy (e.g. raw SQL,
    admin tools, direct DB access).  SQLAlchemy's cascade="all, delete-orphan" on
    the Session side handles the ORM layer for in-session deletes.
    """

    __tablename__ = "documents"

    # ── Composite indexes declared separately so they're explicit ──────────────
    __table_args__ = (
        # Speeds up "fetch all documents for a session" queries.
        Index("ix_documents_session_id_created_at", "session_id", "created_at"),
    )

    # ── Primary key ────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique document identifier (UUIDv4).",
    )

    # ── Foreign key ────────────────────────────────────────────────────────────
    # index=True          → single-column index for FK lookups (the composite index
    #                       above also covers session_id, but having an explicit
    #                       single-column index avoids a sequential scan when
    #                       ordering / filtering by session_id alone).
    # ondelete="CASCADE"  → DB-level cascade; keeps data consistent even when rows
    #                       are deleted outside of the ORM.
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent session this document belongs to.",
    )

    # ── Columns ────────────────────────────────────────────────────────────────
    file_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        doc="Detected file format: 'pdf', 'docx', or 'txt'.",
    )

    original_filename: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Original filename as uploaded by the client.",
    )

    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Raw file size in bytes before any processing.",
    )

    # Text is PostgreSQL's unbounded text type — no length cap.
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Full plain-text content extracted from the uploaded file.",
    )

    char_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of characters in raw_text; denormalised for quick queries.",
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="UTC timestamp when the document row was created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        doc="UTC timestamp automatically refreshed on every row update.",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    # lazy="joined"  → Document queries always return the parent Session in the
    #                  same JOIN, which is safe here because we almost always need
    #                  the session context when working with a document.
    session: Mapped["Session"] = relationship(
        "Session",
        back_populates="documents",
        lazy="selectin",
        doc="Parent Session this document belongs to.",
    )

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id} "
            f"type={self.file_type!r} "
            f"chars={self.char_count} "
            f"session={self.session_id}>"
        )
