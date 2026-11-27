"""The verifier catches each kind of wrong label (spec 0003, AC-3).

Each test breaks one thing in a good packet and expects the verifier to name
that field. The good packet itself must verify clean, or every negative test
would pass for the wrong reason.
"""

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.models import Claim, EvidenceLine, Packet
from claim_intake.generator.pipeline import build_packet
from claim_intake.generator.verify import PacketVerificationError, verify_packet
from generator_helpers import (
    claim,
    document,
    problems_for,
    with_claim,
    with_document,
    with_lines,
)


@pytest.fixture(scope="module")
def packet() -> Packet:
    return build_packet(0)


def _before(packet: Packet) -> list[str]:
    return list(document(packet).lines)


def test_good_packet_verifies_clean(packet: Packet) -> None:
    assert verify_packet(packet, _before(packet)) == []


def test_removed_value_is_reported(packet: Packet) -> None:
    target = claim(packet, FieldName.REPORTER_NAME)
    index = target.evidence[-1].index
    lines = list(document(packet).lines)
    lines[index] = lines[index].replace(target.surface, "")

    def drop(c: Claim) -> Claim:
        evidence = [EvidenceLine(index=e.index, text=lines[e.index]) for e in c.evidence]
        return c.model_copy(update={"evidence": evidence})

    broken = with_claim(with_document(packet, lines=lines), FieldName.REPORTER_NAME, drop)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.REPORTER_NAME)
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
    target = claim(packet, FieldName.REPORTER_NAME)
    error = PacketVerificationError(packet.packet_id, ["reporter_name: surface missing"])
    assert packet.packet_id in str(error)
    assert target.value not in str(error)


def test_surface_that_parses_to_another_value_is_reported(packet: Packet) -> None:
    def other_date(c: Claim) -> Claim:
        return c.model_copy(update={"value": "2026-01-01"})

    broken = with_claim(packet, FieldName.LOSS_DATE, other_date)
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("does not parse" in p for p in problems)


def test_unlisted_line_carrying_the_surface_is_reported(packet: Packet) -> None:
    target = claim(packet, FieldName.LOSS_LOCATION)
    broken = with_lines(packet, lambda lines: [*lines, f"Again, {target.surface}."])
    problems = problems_for(verify_packet(broken, _before(broken)), FieldName.LOSS_LOCATION)
    assert any("not evidence" in p for p in problems)


def test_claim_value_that_differs_from_the_scenario_is_reported(packet: Packet) -> None:
    scenario = packet.scenario.model_copy(update={"loss_location": "100 Elsewhere Street"})
    broken = packet.model_copy(update={"scenario": scenario})
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_LOCATION)
    assert any("differs from the scenario" in p for p in problems)


def _absent(packet: Packet, field: FieldName) -> bool:
    return any(e.field is field and e.status.value == "absent" for e in packet.expected)


def test_leaked_absent_value_is_reported(packet: Packet) -> None:
    assert _absent(packet, FieldName.POLICY_NUMBER)
    policy = packet.scenario.policy_number
    broken = with_lines(packet, lambda lines: [*lines, f"Ref {policy}"])
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.POLICY_NUMBER)
    assert any("absent value appears in the text after noise" in p for p in problems)
    problems = problems_for(verify_packet(broken, _before(broken)), FieldName.POLICY_NUMBER)
    assert any("absent value appears in the text before noise" in p for p in problems)


def test_leaked_absent_first_name_is_reported() -> None:
    packet = build_packet(6)  # rotation omits other_party_name (j = 9) here
    field = FieldName.OTHER_PARTY_NAME
    assert _absent(packet, field)
    first = str(packet.scenario.value(field)).split()[0]
    broken = with_lines(packet, lambda lines: [*lines, f"Say hi to {first.lower()}."])
    problems = problems_for(verify_packet(broken, _before(broken)), field)
    assert any("absent value appears" in p for p in problems)


def test_leaked_absent_phrase_is_reported() -> None:
    packet = build_packet(3)
    assert _absent(packet, FieldName.INJURIES_REPORTED)
    broken = with_lines(packet, lambda lines: [*lines, "Luckily no  one was HURT."])
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.INJURIES_REPORTED)
    assert any("absent phrase appears" in p for p in problems)


def test_child_found_without_a_yes_parent_is_reported(packet: Packet) -> None:
    assert not _absent(packet, FieldName.INJURIES_WHO)
    claims = [c for c in document(packet).claims if c.field is not FieldName.INJURIES_REPORTED]
    broken = with_document(packet, claims=claims)
    broken = broken.model_copy(update={"expected": derive_expected(broken.scenario, claims)})
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.INJURIES_WHO)
    assert any("without a found yes parent" in p for p in problems)


def test_child_line_without_a_found_child_is_reported() -> None:
    packet = build_packet(3)
    assert _absent(packet, FieldName.INJURIES_WHO)
    broken = with_lines(packet, lambda lines: [*lines, "The passenger went home."])
    problems = problems_for(verify_packet(broken, _before(broken)), FieldName.INJURIES_WHO)
    assert any("child line present while absent" in p for p in problems)


@pytest.mark.parametrize(
    "line",
    ["Call 555-0200 any time.", "Call 212-5550 any time.", "Mail me at a.person@gmail.com."],
)
def test_real_looking_contact_data_is_reported(packet: Packet, line: str) -> None:
    broken = with_lines(packet, lambda lines: [*lines, line])
    problems = verify_packet(broken, _before(broken))
    assert any(p.startswith("privacy:") for p in problems)
