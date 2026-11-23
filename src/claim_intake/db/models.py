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
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from claim_intake.db.base import Base, state_column
from claim_intake.db.states import ClaimStatus, DocumentKind

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
