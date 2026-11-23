"""Spec 0002 data model: every table round trips as the app role, and the
database itself refuses what the spec says it must refuse.

Every expected violation names its constraint (the `violates` fixture), so a
test cannot pass because something else failed.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from claim_intake.db.models import Claim, Document, EvidenceUnit
from claim_intake.db.states import ClaimStatus, DocumentKind
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
