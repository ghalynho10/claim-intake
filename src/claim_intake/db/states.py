"""The allowed values of every state column, as plain StrEnums.

Kept free of SQLAlchemy so parsing, scoring and graph code can use them without
importing the ORM. The database enforces the same sets through named CHECK
constraints built from these enums (`db.base.state_column`), so the two cannot
drift apart.
"""

from enum import StrEnum


class ClaimStatus(StrEnum):
    """Where a claim stands. Spec 0002, State transitions, owns the moves."""

    EXTRACTING = "extracting"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SAVED = "saved"
    REJECTED = "rejected"
    FAILED = "failed"


class DocumentKind(StrEnum):
    """The shape of an incoming document."""

    EMAIL = "email"
    FORM = "form"


class EvidenceStatus(StrEnum):
    """What the source text says about a field, independent of review."""

    FOUND = "found"
    ABSENT = "absent"
    UNREADABLE = "unreadable"
    CONFLICTING = "conflicting"
    AMBIGUOUS = "ambiguous"


class ValueOrigin(StrEnum):
    """Who supplied a field's current value."""

    MODEL_PROPOSED = "model_proposed"
    HUMAN_ENTERED = "human_entered"


class ReviewStatus(StrEnum):
    """What the reviewer did with a field."""

    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class DecisionOutcome(StrEnum):
    """The final decision on one claim version."""

    APPROVED = "approved"
    REJECTED = "rejected"


class WriteStatus(StrEnum):
    """Whether an approved payload reached the claims system."""

    PENDING = "pending"
    WRITTEN = "written"
    STALE = "stale"


class LogAction(StrEnum):
    """What a decision log row records. Field actions name a field; claim
    actions link a decision."""

    FIELD_CORRECTED = "field_corrected"
    FIELD_REJECTED = "field_rejected"
    CLAIM_APPROVED = "claim_approved"
    CLAIM_REJECTED = "claim_rejected"
