"""The `public` tables: claims, their documents and evidence, fields, decisions.

Spec 0002 fixes every column and rule here. The rules that matter most live in
the database (named CHECK, UNIQUE and FOREIGN KEY constraints), so a later bug
cannot quietly break them. No `relationship()` objects yet: features 5 and 6
add the ones they navigate. The claims system's table lives in
`claim_intake.claims_system.models`, behind its own module.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from claim_intake.db.base import Base, state_column
from claim_intake.db.states import (
    ClaimStatus,
    DocumentKind,
    EvidenceStatus,
    ReviewStatus,
    ValueOrigin,
)

UUID_DEFAULT = text("uuidv7()")


class Claim(Base):
    """One claim. Its `id` is also the LangGraph `thread_id`.

    `version` goes up by one only when a document is added; it is a plain
    counter, not SQLAlchemy's `version_id_col`. `status` has no default on
    purpose: whoever creates a claim states it.
    """

    __tablename__ = "claim"
    __table_args__ = (CheckConstraint("version >= 1", name="version_min"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=UUID_DEFAULT)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[ClaimStatus] = mapped_column(state_column(ClaimStatus, "status"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    """An incoming email or form, stored exactly as received.

    One document per claim version: the document that created that version.
    """

    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("claim_id", "claim_version"),
        CheckConstraint("claim_version >= 1", name="claim_version_min"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=UUID_DEFAULT)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim.id"))
    claim_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[DocumentKind] = mapped_column(state_column(DocumentKind, "kind"))
    text: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvidenceUnit(Base):
    """One block of a document, as sent to the model API. Citations point at
    these by position."""

    __tablename__ = "evidence_unit"
    __table_args__ = (
        UniqueConstraint("document_id", "position"),
        CheckConstraint("position >= 0", name="position_min"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=UUID_DEFAULT)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class ExtractedField(Base):
    """One field of a claim, with its three independent state axes.

    `proposed_value` is what the model said and is never changed by a review;
    `value` is the current value. Which field names exist is checked in code
    (feature 5); the database takes any text.
    """

    __tablename__ = "extracted_field"
    __table_args__ = (
        UniqueConstraint("claim_id", "field_name"),
        CheckConstraint(
            "evidence_status <> 'found' "
            "OR (proposed_value IS NOT NULL AND btrim(proposed_value) <> '')",
            name="found_has_value",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=UUID_DEFAULT)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim.id"))
    field_name: Mapped[str] = mapped_column(Text)
    proposed_value: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text)
    evidence_status: Mapped[EvidenceStatus] = mapped_column(
        state_column(EvidenceStatus, "evidence_status")
    )
    value_origin: Mapped[ValueOrigin] = mapped_column(state_column(ValueOrigin, "value_origin"))
    review_status: Mapped[ReviewStatus] = mapped_column(state_column(ReviewStatus, "review_status"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Citation(Base):
    """A range of evidence units, `[start_position, end_position)`, in one
    document, backing one field.

    The composite foreign key makes the start a real unit of that document. The
    end staying within the document, and the document belonging to the field's
    claim, are checked in code (feature 5).
    """

    __tablename__ = "citation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "start_position"],
            ["evidence_unit.document_id", "evidence_unit.position"],
        ),
        CheckConstraint("start_position >= 0", name="start_min"),
        CheckConstraint("end_position > start_position", name="range"),
        Index("ix_citation_document_id", "document_id", "start_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=UUID_DEFAULT)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extracted_field.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column()
    start_position: Mapped[int] = mapped_column(Integer)
    end_position: Mapped[int] = mapped_column(Integer)
