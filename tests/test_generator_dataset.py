"""The 20 packet dev set as a whole (spec 0003, AC-1, AC-2, AC-7, AC-9).

Coverage is computed over the generated set, so a change to the planning rules
that starves a field of examples fails here instead of in feature 8's numbers.
"""

import re
from collections import Counter

import pytest

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.models import Family, Packet
from claim_intake.generator.pipeline import DEV_SEED, generate_dataset
from claim_intake.generator.plan import ALWAYS, PARENTS


@pytest.fixture(scope="module")
def dev_set() -> list[Packet]:
    return generate_dataset(DEV_SEED, 20)


def _status(packet: Packet, field: FieldName) -> tuple[EvidenceStatus, str | None]:
    entry = next(e for e in packet.expected if e.field is field)
    return entry.status, entry.value


def test_ids_families_and_documents(dev_set: list[Packet]) -> None:
    assert [p.packet_id for p in dev_set] == [f"pkt-{n:03d}" for n in range(1, 21)]
    assert Counter(p.family for p in dev_set) == {
        Family.INFORMAL_EMAIL: 7,
        Family.FORMAL_EMAIL: 7,
        Family.WEB_FORM: 6,
    }
    for index, packet in enumerate(dev_set):
        assert packet.family == list(Family)[index % 3]
        assert [d.document_id for d in packet.documents] == ["doc-1"]
        assert packet.documents[0].source_ref == f"{packet.packet_id}/doc-1"
        assert len(packet.expected) == 19


def test_same_seed_gives_equal_packets(dev_set: list[Packet]) -> None:
    assert generate_dataset(DEV_SEED, 20) == dev_set


def test_first_twenty_unchanged_when_the_set_grows(dev_set: list[Packet]) -> None:
    assert generate_dataset(DEV_SEED, 25)[:20] == dev_set


def test_another_seed_gives_other_packets(dev_set: list[Packet]) -> None:
    assert generate_dataset(DEV_SEED + 1, 3) != dev_set[:3]


def test_coverage(dev_set: list[Packet]) -> None:
    found: Counter[FieldName] = Counter()
    absent_families: dict[FieldName, set[Family]] = {f: set() for f in FieldName}
    absent: Counter[FieldName] = Counter()
    yes_no: Counter[tuple[FieldName, str | None]] = Counter()
    found_families: dict[FieldName, set[Family]] = {f: set() for f in FieldName}
    for packet in dev_set:
        for field in FieldName:
            status, value = _status(packet, field)
            if status is EvidenceStatus.FOUND:
                found[field] += 1
                found_families[field].add(packet.family)
                yes_no[(field, value)] += 1
            else:
                absent[field] += 1
                absent_families[field].add(packet.family)

    for field in ALWAYS:
        assert found[field] == 20, field
    for field in FieldName:
        if field in ALWAYS:
            continue
        assert absent[field] >= 2, field
        assert len(absent_families[field]) >= 2, field
        if field not in PARENTS:
            assert found[field] >= 10, field
    for parent in PARENTS.values():
        assert yes_no[(parent, "yes")] >= 4, parent
        assert yes_no[(parent, "no")] >= 4, parent
    for child in PARENTS:
        assert found[child] >= 4, child
        assert len(found_families[child]) >= 2, child


def test_no_real_contact_data(dev_set: list[Packet]) -> None:
    phones = 0
    for packet in dev_set:
        text = "\n".join(packet.documents[0].lines)
        for token in re.findall(r"\d{3}-\d{4}", text):
            assert re.fullmatch(r"555-01\d\d", token), packet.packet_id
            phones += 1
        for token in text.split():
            if "@" in token:
                assert token.strip("<>.,").endswith("@example.com"), packet.packet_id
    assert phones > 0
