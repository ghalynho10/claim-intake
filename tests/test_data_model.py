"""Spec 0002 data model: every table round trips as the app role, and the
database itself refuses what the spec says it must refuse.

Every expected violation names its constraint (the `violates` fixture), so a
test cannot pass because something else failed.
"""

import itertools
import uuid

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from claim_intake.claims_system.models import ClaimRecord
from claim_intake.db.models import (
    Citation,
    Claim,
    ClaimDecision,
    DecisionLog,
    Document,
    EvidenceUnit,
    ExtractedField,
)
from claim_intake.db.states import (
    ClaimStatus,
    DecisionOutcome,
    DocumentKind,
    EvidenceStatus,
    LogAction,
    ReviewStatus,
    ValueOrigin,
    WriteStatus,
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


# --- claim_decision (AC-6) ---------------------------------------------------


def _decision(
    claim_id: uuid.UUID,
    outcome: DecisionOutcome = DecisionOutcome.APPROVED,
    claim_version: int = 1,
    **overrides: object,
) -> ClaimDecision:
    values: dict[str, object] = {
        "claim_id": claim_id,
        "claim_version": claim_version,
        "outcome": outcome,
        "reviewer_name": "Dana Reviewer",
    }
    if outcome is DecisionOutcome.APPROVED:
        values |= {
            "payload": {"policy_number": "P-1", "loss_date": None},
            "payload_hash": "hash-1",
            "write_status": WriteStatus.PENDING,
        }
    values.update(overrides)
    return ClaimDecision(**values)


def test_second_decision_on_same_version_is_rejected_next_version_accepted(
    db_session: Session, claim_chain: ChainFactory, violates: Violates
) -> None:
    claim_id = claim_chain().claim.id
    db_session.add(_decision(claim_id, DecisionOutcome.APPROVED))
    db_session.flush()
    with violates("uq_claim_decision_claim_id"):
        db_session.add(_decision(claim_id, DecisionOutcome.REJECTED))
    db_session.add(_decision(claim_id, DecisionOutcome.REJECTED, claim_version=2))
    db_session.flush()


def test_approved_decision_round_trips_its_payload(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    decision = _decision(claim_chain().claim.id)
    db_session.add(decision)
    db_session.flush()
    decision_id = decision.id
    db_session.expire_all()

    stored = db_session.get_one(ClaimDecision, decision_id)
    assert _is_db_uuid(stored.id)
    assert stored.payload == {"policy_number": "P-1", "loss_date": None}
    assert stored.write_status is WriteStatus.PENDING
    assert stored.decided_at is not None


def test_rejected_decision_stores_payload_as_sql_null(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    decision = _decision(claim_chain().claim.id, DecisionOutcome.REJECTED, payload=None)
    db_session.add(decision)
    db_session.flush()
    is_sql_null = db_session.execute(
        text("SELECT payload IS NULL FROM claim_decision WHERE id = :id"), {"id": decision.id}
    ).scalar_one()
    assert is_sql_null is True


@pytest.mark.parametrize("missing", ["payload", "payload_hash", "write_status"])
def test_approved_decision_needs_payload_hash_and_write_status(
    db_session: Session, claim_chain: ChainFactory, violates: Violates, missing: str
) -> None:
    claim_id = claim_chain().claim.id
    with violates("ck_claim_decision_outcome_fields"):
        db_session.add(_decision(claim_id, **{missing: None}))


@pytest.mark.parametrize(
    ("column", "value"),
    [("payload", {"a": "b"}), ("payload_hash", "h"), ("write_status", WriteStatus.PENDING)],
)
def test_rejected_decision_carries_none_of_them(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    column: str,
    value: object,
) -> None:
    claim_id = claim_chain().claim.id
    with violates("ck_claim_decision_outcome_fields"):
        db_session.add(_decision(claim_id, DecisionOutcome.REJECTED, **{column: value}))


@pytest.mark.parametrize("blank", ["", "   "])
def test_decision_needs_a_reviewer_name(
    db_session: Session, claim_chain: ChainFactory, violates: Violates, blank: str
) -> None:
    claim_id = claim_chain().claim.id
    with violates("ck_claim_decision_reviewer_name_set"):
        db_session.add(_decision(claim_id, reviewer_name=blank))


@pytest.mark.parametrize("payload", ['["a"]', '"text"', "1", "null"])
def test_decision_payload_must_be_a_json_object(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    payload: str,
) -> None:
    """JSON `null` is not SQL NULL: it must be refused like any other non object."""
    claim_id = claim_chain().claim.id
    with violates("ck_claim_decision_payload_object"):
        db_session.execute(
            text(
                "INSERT INTO claim_decision "
                "(claim_id, claim_version, outcome, payload, payload_hash, write_status, "
                "reviewer_name) "
                "VALUES (:claim_id, 1, 'approved', CAST(:payload AS jsonb), 'h', 'pending', 'R')"
            ),
            {"claim_id": claim_id, "payload": payload},
        )


@pytest.mark.parametrize(
    ("outcome", "write_status", "version", "constraint"),
    [
        ("maybe", "NULL", 1, "ck_claim_decision_outcome"),
        ("approved", "'lost'", 1, "ck_claim_decision_write_status"),
        ("approved", "'pending'", 0, "ck_claim_decision_claim_version_min"),
    ],
)
def test_decision_state_and_version_checks(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    outcome: str,
    write_status: str,
    version: int,
    constraint: str,
) -> None:
    claim_id = claim_chain().claim.id
    with violates(constraint):
        db_session.execute(
            text(
                "INSERT INTO claim_decision "
                "(claim_id, claim_version, outcome, payload, payload_hash, write_status, "
                "reviewer_name) "
                f"VALUES (:claim_id, :version, :outcome, '{{}}', 'h', {write_status}, 'R')"
            ),
            {"claim_id": claim_id, "version": version, "outcome": outcome},
        )


# --- decision_log (AC-7) -----------------------------------------------------

LOG_COLUMNS = {
    "id",
    "claim_id",
    "claim_version",
    "action",
    "field_name",
    "decision_id",
    "reviewer_name",
    "created_at",
}


def test_decision_log_has_no_value_columns(engine: Engine) -> None:
    assert {c["name"] for c in inspect(engine).get_columns("decision_log")} == LOG_COLUMNS


def _log(claim_id: uuid.UUID, action: LogAction, **overrides: object) -> DecisionLog:
    values: dict[str, object] = {
        "claim_id": claim_id,
        "claim_version": 1,
        "action": action,
        "reviewer_name": "Dana Reviewer",
    }
    values.update(overrides)
    return DecisionLog(**values)


def test_log_accepts_field_and_claim_actions(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    claim_id = claim_chain().claim.id
    decision = _decision(claim_id)
    db_session.add(decision)
    db_session.flush()
    rows = [
        _log(claim_id, LogAction.FIELD_CORRECTED, field_name="policy_number"),
        _log(claim_id, LogAction.FIELD_REJECTED, field_name="loss_date"),
        _log(claim_id, LogAction.CLAIM_APPROVED, decision_id=decision.id),
    ]
    db_session.add_all(rows)
    db_session.flush()
    assert all(_is_db_uuid(r.id) for r in rows)


@pytest.mark.parametrize(
    ("action", "field_name", "with_decision"),
    [
        (LogAction.FIELD_CORRECTED, None, False),  # field action without a field
        (LogAction.FIELD_REJECTED, "policy_number", True),  # field action with a decision
        (LogAction.CLAIM_APPROVED, None, False),  # claim action without a decision
        (LogAction.CLAIM_REJECTED, "policy_number", True),  # claim action with a field
    ],
)
def test_log_action_shape_is_enforced(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    action: LogAction,
    field_name: str | None,
    with_decision: bool,
) -> None:
    claim_id = claim_chain().claim.id
    decision = _decision(claim_id)
    db_session.add(decision)
    db_session.flush()
    decision_id = decision.id if with_decision else None
    with violates("ck_decision_log_action_fields"):
        db_session.add(_log(claim_id, action, field_name=field_name, decision_id=decision_id))


@pytest.mark.parametrize("blank", ["", "   "])
def test_log_needs_a_reviewer_name(
    db_session: Session, claim_chain: ChainFactory, violates: Violates, blank: str
) -> None:
    claim_id = claim_chain().claim.id
    with violates("ck_decision_log_reviewer_name_set"):
        db_session.add(
            _log(claim_id, LogAction.FIELD_CORRECTED, field_name="f", reviewer_name=blank)
        )


@pytest.mark.parametrize(
    ("action", "version", "constraint"),
    [
        ("field_edited", 1, "ck_decision_log_action"),
        ("field_corrected", 0, "ck_decision_log_claim_version_min"),
    ],
)
def test_log_state_and_version_checks(
    db_session: Session,
    claim_chain: ChainFactory,
    violates: Violates,
    action: str,
    version: int,
    constraint: str,
) -> None:
    claim_id = claim_chain().claim.id
    with violates(constraint):
        db_session.execute(
            text(
                "INSERT INTO decision_log (claim_id, claim_version, action, field_name, "
                "reviewer_name) VALUES (:claim_id, :version, :action, 'f', 'R')"
            ),
            {"claim_id": claim_id, "version": version, "action": action},
        )


# --- every table, as the app role (AC-2) -------------------------------------


def test_one_row_in_each_of_the_eight_tables_round_trips(
    db_session: Session, claim_chain: ChainFactory
) -> None:
    """The happy path through the whole model: two documents, units, a field
    with a citation, an approved decision, a log row and a claims system record."""
    first = claim_chain(["Policy number: P-1"])
    second = claim_chain(["Correction: P-2"], claim=first.claim, claim_version=2)
    claim_id = first.claim.id

    field = _field(claim_id)
    db_session.add(field)
    db_session.flush()
    citation = Citation(
        field_id=field.id, document_id=first.document.id, start_position=0, end_position=1
    )
    decision = _decision(claim_id, claim_version=2)
    db_session.add_all([citation, decision])
    db_session.flush()
    log = _log(claim_id, LogAction.CLAIM_APPROVED, claim_version=2, decision_id=decision.id)
    record = ClaimRecord(
        claim_id=claim_id,
        claim_version=2,
        payload=decision.payload or {},
        payload_hash=decision.payload_hash or "",
        idempotency_key=str(decision.id),
    )
    db_session.add_all([log, record])
    db_session.flush()

    rows = {
        Claim: first.claim.id,
        Document: second.document.id,
        EvidenceUnit: second.units[0].id,
        ExtractedField: field.id,
        Citation: citation.id,
        ClaimDecision: decision.id,
        DecisionLog: log.id,
        ClaimRecord: record.id,
    }
    db_session.expire_all()
    for model, row_id in rows.items():
        stored = db_session.get_one(model, row_id)
        assert _is_db_uuid(stored.id), model.__name__
    assert db_session.get_one(ClaimRecord, record.id).payload == decision.payload
