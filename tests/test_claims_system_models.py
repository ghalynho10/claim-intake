"""Spec 0002, AC-8: the claims system's record table refuses a second write
under one idempotency key, or a second record for one claim version, and
stands apart from `public` (no foreign key)."""

import uuid

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from claim_intake.claims_system.models import ClaimRecord
from conftest import Violates


def _record(
    claim_id: uuid.UUID, claim_version: int = 1, key: str = "key-1", **overrides: object
) -> ClaimRecord:
    values: dict[str, object] = {
        "claim_id": claim_id,
        "claim_version": claim_version,
        "payload": {"policy_number": "P-1"},
        "payload_hash": "hash-1",
        "idempotency_key": key,
    }
    values.update(overrides)
    return ClaimRecord(**values)


def test_record_round_trips_and_refers_to_claim_by_id_only(db_session: Session) -> None:
    """The claim id need not exist in public.claim: there is no foreign key."""
    record = _record(uuid.uuid4())
    db_session.add(record)
    db_session.flush()
    record_id = record.id
    db_session.expire_all()

    stored = db_session.get_one(ClaimRecord, record_id)
    assert isinstance(stored.id, uuid.UUID) and stored.id.version == 7
    assert stored.payload == {"policy_number": "P-1"}
    assert stored.written_at is not None


def test_table_has_no_foreign_key(engine: Engine) -> None:
    assert inspect(engine).get_foreign_keys("claim_record", schema="claims_system") == []


def test_second_record_with_same_idempotency_key_is_rejected(
    db_session: Session, violates: Violates
) -> None:
    db_session.add(_record(uuid.uuid4(), key="same"))
    db_session.flush()
    with violates("uq_claim_record_idempotency_key"):
        db_session.add(_record(uuid.uuid4(), key="same"))


def test_second_record_for_same_claim_version_is_rejected(
    db_session: Session, violates: Violates
) -> None:
    claim_id = uuid.uuid4()
    db_session.add(_record(claim_id, key="k1"))
    db_session.flush()
    with violates("uq_claim_record_claim_id"):
        db_session.add(_record(claim_id, key="k2"))
    db_session.add(_record(claim_id, claim_version=2, key="k3"))
    db_session.flush()


@pytest.mark.parametrize(
    ("payload", "version", "constraint"),
    [
        ('["a"]', 1, "ck_claim_record_payload_object"),
        ("null", 1, "ck_claim_record_payload_object"),
        ("{}", 0, "ck_claim_record_claim_version_min"),
    ],
)
def test_record_checks(
    db_session: Session, violates: Violates, payload: str, version: int, constraint: str
) -> None:
    with violates(constraint):
        db_session.execute(
            text(
                "INSERT INTO claims_system.claim_record "
                "(claim_id, claim_version, payload, payload_hash, idempotency_key) "
                "VALUES (:claim_id, :version, CAST(:payload AS jsonb), 'h', 'k')"
            ),
            {"claim_id": uuid.uuid4(), "version": version, "payload": payload},
        )
