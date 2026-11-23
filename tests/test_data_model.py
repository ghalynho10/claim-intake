"""Spec 0002 data model: every table round trips as the app role, and the
database itself refuses what the spec says it must refuse.

Every expected violation names its constraint (the `violates` fixture), so a
test cannot pass because something else failed.
"""

import itertools
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from claim_intake.db.models import Citation, Claim, Document, EvidenceUnit, ExtractedField
from claim_intake.db.states import (
    ClaimStatus,
    DocumentKind,
    EvidenceStatus,
    ReviewStatus,
    ValueOrigin,
)
from conftest import ChainFactory, Violates


def _is_db_uuid(value: object) -> bool:
    """`uuidv7()` ran in the database: Python's `uuid.uuid4` would give version 4."""
    return isinstance(value, uuid.UUID) and value.version == 7


# --- claim, document, evidence_unit (AC-2, AC-3) ---------------------------


def test_claim_insert_fills_id_version_and_timestamps(db_session: Session) -> None:
    claim = Claim(status=ClaimStatus.EXTRACTING)
    db_session.add(claim)
    db_session.flush()
    claim_id = claim.id
    db_session.expire_all()

    stored = db_session.execute(select(Claim).where(Claim.id == claim_id)).scalar_one()
    assert _is_db_uuid(stored.id)
    assert stored.version == 1
    assert stored.status is ClaimStatus.EXTRACTING
    assert stored.created_at is not None and stored.updated_at is not None


def test_claim_holds_two_documents_with_ordered_units(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    first = claim_chain(["a1", "a2"])
    second = claim_chain(["b1", "b2", "b3"], claim=first.claim, claim_version=2)
    db_session.expire_all()

    docs = (
        db_session.execute(
            select(Document)
            .where(Document.claim_id == first.claim.id)
            .order_by(Document.claim_version)
        )
        .scalars()
        .all()
    )
    assert [d.claim_version for d in docs] == [1, 2]
    assert all(_is_db_uuid(d.id) for d in docs)
    assert docs[0].kind is DocumentKind.EMAIL and docs[0].text == "a1\na2"
    assert docs[0].source_ref is None

    for doc, expected in ((first.document, ["a1", "a2"]), (second.document, ["b1", "b2", "b3"])):
        units = (
            db_session.execute(
                select(EvidenceUnit)
                .where(EvidenceUnit.document_id == doc.id)
                .order_by(EvidenceUnit.position)
            )
            .scalars()
            .all()
        )
        assert [u.text for u in units] == expected
        assert [u.position for u in units] == list(range(len(expected)))
        assert all(_is_db_uuid(u.id) for u in units)


def test_second_document_for_same_claim_version_is_rejected(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    chain = claim_chain()
    with violates("uq_document_claim_id"):
        db_session.add(
            Document(claim_id=chain.claim.id, claim_version=1, kind=DocumentKind.FORM, text="x")
        )


def test_second_unit_at_same_position_is_rejected(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    chain = claim_chain()
    with violates("uq_evidence_unit_document_id"):
        db_session.add(EvidenceUnit(document_id=chain.document.id, position=0, text="dup"))


def test_document_needs_an_existing_claim(db_session: Session, violates: Violates) -> None:
    with violates("fk_document_claim_id_claim"):
        db_session.add(
            Document(claim_id=uuid.uuid4(), claim_version=1, kind=DocumentKind.EMAIL, text="x")
        )


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        ("INSERT INTO claim (status) VALUES ('bogus')", "ck_claim_status"),
        ("INSERT INTO claim (status, version) VALUES ('extracting', 0)", "ck_claim_version_min"),
    ],
)
def test_claim_checks(db_session: Session, violates: Violates, sql: str, constraint: str) -> None:
    with violates(constraint):
        db_session.execute(text(sql))


def test_document_and_unit_checks(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    chain = claim_chain()
    params = {"claim": chain.claim.id, "doc": chain.document.id}
    with violates("ck_document_kind"):
        db_session.execute(
            text(
                "INSERT INTO document (claim_id, claim_version, kind, text) "
                "VALUES (:claim, 5, 'fax', 'x')"
            ),
            params,
        )
    with violates("ck_document_claim_version_min"):
        db_session.execute(
            text(
                "INSERT INTO document (claim_id, claim_version, kind, text) "
                "VALUES (:claim, 0, 'email', 'x')"
            ),
            params,
        )
    with violates("ck_evidence_unit_position_min"):
        db_session.execute(
            text("INSERT INTO evidence_unit (document_id, position, text) VALUES (:doc, -1, 'x')"),
            params,
        )


# --- extracted_field (AC-4) -------------------------------------------------


def _field(claim_id: uuid.UUID, name: str = "policy_number", **overrides: object) -> ExtractedField:
    values: dict[str, object] = {
        "claim_id": claim_id,
        "field_name": name,
        "proposed_value": "P-1",
        "value": "P-1",
        "evidence_status": EvidenceStatus.FOUND,
        "value_origin": ValueOrigin.MODEL_PROPOSED,
        "review_status": ReviewStatus.PENDING,
    }
    values.update(overrides)
    return ExtractedField(**values)


def test_every_combination_of_the_three_axes_is_accepted(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    claim_id = claim_chain().claim.id
    combos = list(itertools.product(EvidenceStatus, ValueOrigin, ReviewStatus))
    assert len(combos) == 40
    for i, (evidence, origin, review) in enumerate(combos):
        db_session.add(
            _field(
                claim_id,
                f"field_{i}",
                proposed_value=f"v{i}",
                evidence_status=evidence,
                value_origin=origin,
                review_status=review,
            )
        )
    db_session.flush()
    db_session.expire_all()

    stored = (
        db_session.execute(select(ExtractedField).where(ExtractedField.claim_id == claim_id))
        .scalars()
        .all()
    )
    assert {(f.evidence_status, f.value_origin, f.review_status) for f in stored} == set(combos)
    assert all(_is_db_uuid(f.id) for f in stored)


def test_proposed_value_and_value_are_stored_independently(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    claim_id = claim_chain().claim.id
    field = _field(
        claim_id,
        proposed_value="P-1",
        value="P-2",
        value_origin=ValueOrigin.HUMAN_ENTERED,
        review_status=ReviewStatus.CORRECTED,
    )
    db_session.add(field)
    db_session.flush()
    field_id = field.id
    db_session.expire_all()

    stored = db_session.get_one(ExtractedField, field_id)
    assert (stored.proposed_value, stored.value) == ("P-1", "P-2")


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_found_field_needs_a_proposed_value(
    db_session: Session, claim_chain: ChainFactory, violates: Violates, blank: str | None
) -> None:
    claim_id = claim_chain().claim.id
    with violates("ck_extracted_field_found_has_value"):
        db_session.add(_field(claim_id, proposed_value=blank))


def test_absent_field_may_have_no_proposed_value(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    claim_id = claim_chain().claim.id
    db_session.add(
        _field(claim_id, proposed_value=None, value=None, evidence_status=EvidenceStatus.ABSENT)
    )
    db_session.flush()


def test_second_field_with_same_name_is_rejected(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    claim_id = claim_chain().claim.id
    db_session.add(_field(claim_id))
    db_session.flush()
    with violates("uq_extracted_field_claim_id"):
        db_session.add(_field(claim_id))


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("evidence_status", "ck_extracted_field_evidence_status"),
        ("value_origin", "ck_extracted_field_value_origin"),
        ("review_status", "ck_extracted_field_review_status"),
    ],
)
def test_axis_value_outside_its_set_is_rejected(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    column: str,
    constraint: str,
) -> None:
    row = {
        "claim_id": claim_chain().claim.id,
        "evidence_status": "found",
        "value_origin": "model_proposed",
        "review_status": "pending",
    }
    row[column] = "bogus"
    with violates(constraint):
        db_session.execute(
            text(
                "INSERT INTO extracted_field "
                "(claim_id, field_name, proposed_value, value, "
                "evidence_status, value_origin, review_status) "
                "VALUES (:claim_id, 'f', 'v', 'v', "
                ":evidence_status, :value_origin, :review_status)"
            ),
            row,
        )


# --- citation (AC-5) ---------------------------------------------------------


def test_field_holds_two_citations(db_session: Session, claim_chain: ChainFactory) -> None:
    chain = claim_chain(["u0", "u1", "u2"])
    field = _field(chain.claim.id)
    db_session.add(field)
    db_session.flush()
    doc_id = chain.document.id
    db_session.add_all(
        [
            Citation(field_id=field.id, document_id=doc_id, start_position=0, end_position=1),
            Citation(field_id=field.id, document_id=doc_id, start_position=1, end_position=3),
        ]
    )
    db_session.flush()
    db_session.expire_all()

    stored = (
        db_session.execute(
            select(Citation).where(Citation.field_id == field.id).order_by(Citation.start_position)
        )
        .scalars()
        .all()
    )
    assert [(c.start_position, c.end_position) for c in stored] == [(0, 1), (1, 3)]
    assert all(_is_db_uuid(c.id) for c in stored)


@pytest.mark.parametrize(
    ("start", "end", "constraint"),
    [
        (5, 6, "fk_citation_document_id_evidence_unit"),  # no unit at position 5
        (1, 1, "ck_citation_range"),
        (1, 0, "ck_citation_range"),
        (-1, 1, "ck_citation_start_min"),
    ],
)
def test_citation_rules(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    start: int,
    end: int,
    constraint: str,
) -> None:
    chain = claim_chain(["u0", "u1"])
    field = _field(chain.claim.id)
    db_session.add(field)
    db_session.flush()
    with violates(constraint):
        db_session.add(
            Citation(
                field_id=field.id,
                document_id=chain.document.id,
                start_position=start,
                end_position=end,
            )
        )


def test_citation_start_must_be_a_unit_of_its_own_document(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    """Position 2 exists in the second document but not in the first."""
    first = claim_chain(["a0"])
    claim_chain(["b0", "b1", "b2"], claim=first.claim, claim_version=2)
    field = _field(first.claim.id)
    db_session.add(field)
    db_session.flush()
    with violates("fk_citation_document_id_evidence_unit"):
        db_session.add(
            Citation(
                field_id=field.id,
                document_id=first.document.id,
                start_position=2,
                end_position=3,
            )
        )
