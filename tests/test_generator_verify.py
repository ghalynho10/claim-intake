"""The verifier catches each kind of wrong label (spec 0003, AC-3).

Each test breaks one thing in a good packet and expects the verifier to name
that field. The good packet itself must verify clean, or every negative test
would pass for the wrong reason.
"""

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.models import Claim, EvidenceLine, Packet
from claim_intake.generator.pipeline import build_packet
from claim_intake.generator.verify import PacketVerificationError, verify_packet
from generator_helpers import claim, document, problems_for, with_claim, with_document


@pytest.fixture(scope="module")
def packet() -> Packet:
    return build_packet(0)


def _before(packet: Packet) -> list[str]:
    return list(document(packet).lines)


def test_good_packet_verifies_clean(packet: Packet) -> None:
    assert verify_packet(packet, _before(packet)) == []


def test_removed_value_is_reported(packet: Packet) -> None:
    target = claim(packet, FieldName.POLICY_NUMBER)
    index = target.evidence[-1].index
    lines = list(document(packet).lines)
    lines[index] = lines[index].replace(target.surface, "")

    def drop(c: Claim) -> Claim:
        evidence = [EvidenceLine(index=e.index, text=lines[e.index]) for e in c.evidence]
        return c.model_copy(update={"evidence": evidence})

    broken = with_claim(with_document(packet, lines=lines), FieldName.POLICY_NUMBER, drop)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.POLICY_NUMBER)
    assert any("surface missing" in p for p in problems)


def test_wrong_index_is_reported(packet: Packet) -> None:
    def shift(c: Claim) -> Claim:
        first = c.evidence[0]
        moved = EvidenceLine(index=first.index + 1, text=first.text)
        return c.model_copy(update={"evidence": [moved, *c.evidence[1:]]})

    broken = with_claim(packet, FieldName.LOSS_DATE, shift)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("evidence text differs" in p for p in problems)


def test_out_of_range_index_is_reported(packet: Packet) -> None:
    def far(c: Claim) -> Claim:
        return c.model_copy(update={"evidence": [EvidenceLine(index=999, text="x")]})

    broken = with_claim(packet, FieldName.LOSS_DATE, far)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("out of range" in p for p in problems)


def test_changed_line_text_is_reported(packet: Packet) -> None:
    def edit(c: Claim) -> Claim:
        first = c.evidence[0]
        changed = EvidenceLine(index=first.index, text=first.text + " edited")
        return c.model_copy(update={"evidence": [changed, *c.evidence[1:]]})

    broken = with_claim(packet, FieldName.REPORTER_NAME, edit)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.REPORTER_NAME)
    assert any("evidence text differs" in p for p in problems)


def test_error_message_names_ids_and_fields_never_values(packet: Packet) -> None:
    target = claim(packet, FieldName.POLICY_NUMBER)
    error = PacketVerificationError(packet.packet_id, ["policy_number: surface missing"])
    assert packet.packet_id in str(error)
    assert target.value not in str(error)
