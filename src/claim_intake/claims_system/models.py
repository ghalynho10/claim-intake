"""The simulated claims system's table, in its own `claims_system` schema.

Only `claim_intake.claims_system` may import this module (the import-linter
`protected` contract in `pyproject.toml`), because the app role can write the
schema: the import rule is what keeps every write behind `ClaimsSystemClient`
and so behind an approval. No foreign key into `public`: the claims system
refers to a claim by id only, as a separate system would.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from claim_intake.db.base import Base

SCHEMA = "claims_system"


class ClaimRecord(Base):
    """One approved write. The unique idempotency key makes a retried write
    land once; the unique (claim_id, claim_version) allows one record per
    version, and the highest version is the claim's current record."""

    __tablename__ = "claim_record"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        UniqueConstraint("claim_id", "claim_version"),
        CheckConstraint("claim_version >= 1", name="claim_version_min"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    claim_id: Mapped[uuid.UUID] = mapped_column()
    claim_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, str | None]] = mapped_column(JSONB(none_as_null=True))
    payload_hash: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
