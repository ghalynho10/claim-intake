"""The packet shape that features 5 and 8 read (spec 0003, Packet shape).

Frozen Pydantic models, because packets cross a file boundary and come back in
through `model_validate_json`. Field declaration order is the JSON key order, so
it is part of the byte stable contract that the dataset digest pins.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_intake.db.states import DocumentKind, EvidenceStatus
from claim_intake.fields import FieldName


class Family(StrEnum):
    """The three starter template families. Declaration order is the rotation
    order: packet `index` uses family `index % 3`."""

    INFORMAL_EMAIL = "informal_email"
    FORMAL_EMAIL = "formal_email"
    WEB_FORM = "web_form"


FAMILY_ORDER: tuple[Family, ...] = tuple(Family)


def family_for(index: int) -> Family:
    """The family of packet `index`; chosen first because some value sets depend on it."""
    return FAMILY_ORDER[index % len(FAMILY_ORDER)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Scenario(_Frozen):
    """What really happened: one true value per field, or None when there is none.

    Attributes follow `FieldName` order, so the JSON reads in the same order as
    `expected`.
    """

    policy_number: str | None
    reporter_name: str | None
    reporter_contact: str | None
    reporter_relationship: str | None
    loss_date: str | None
    loss_time: str | None
    loss_location: str | None
    loss_description: str | None
    vehicle_year: str | None
    vehicle_make: str | None
    vehicle_model: str | None
    driver_name: str | None
    other_party_name: str | None
    other_party_vehicle: str | None
    other_party_insurer: str | None
    injuries_reported: str | None
    injuries_who: str | None
    police_report_filed: str | None
    police_report_number: str | None

    def value(self, field: FieldName) -> str | None:
        """The true value of one field."""
        result: str | None = getattr(self, field.value)
        return result


class EvidenceLine(_Frozen):
    """One line that carries a claim. The text is stored beside the index so a
    consumer that splits lines differently can still map by text."""

    index: int
    text: str


class Claim(_Frozen):
    """What one document asserts about one field."""

    field: FieldName
    value: str
    surface: str
    cue: str
    evidence: list[EvidenceLine]


class Document(_Frozen):
    """One source document: its final text as lines and what it asserts."""

    document_id: str
    source_ref: str
    kind: DocumentKind
    lines: list[str]
    claims: list[Claim]


class ExpectedField(_Frozen):
    """The answer key for one field, derived from the claims, never hand written."""

    field: FieldName
    status: EvidenceStatus
    value: str | None
    evidence: list[EvidenceLine]


class Packet(_Frozen):
    """One synthetic claim packet: true facts, documents, and the answer key."""

    packet_id: str
    family: Family
    seed: int
    scenario: Scenario
    documents: list[Document]
    expected: list[ExpectedField]


def document_text(document: Document) -> str:
    """The document's text as a loader sees it: its lines joined with newlines."""
    return "\n".join(document.lines)
