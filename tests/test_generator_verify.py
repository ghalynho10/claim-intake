"""The verifier catches each kind of wrong label (spec 0003, AC-3).

Each test breaks one thing in a good packet and expects the verifier to name
that field. The good packet itself must verify clean, or every negative test
would pass for the wrong reason.
"""

import pytest

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.families import child_cues
from claim_intake.generator.formatters import (
    PHONE_FORMAT_COUNT,
    TIME_FORMAT_COUNT,
    format_phone,
    format_time,
)
from claim_intake.generator.models import Claim, EvidenceLine, Packet
from claim_intake.generator.pipeline import build_packet
from claim_intake.generator.plan import PARENTS
from claim_intake.generator.values import INSURERS
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


# --- checks added by /test: verifier rules the tests above leave untried ---------


def test_claim_without_evidence_is_reported(packet: Packet) -> None:
    # covers: AC-3 (each claim sits on at least one evidence line)
    broken = with_claim(
        packet, FieldName.LOSS_DATE, lambda c: c.model_copy(update={"evidence": []})
    )
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("no evidence line" in p for p in problems)


def test_cue_missing_from_its_evidence_lines_is_reported(packet: Packet) -> None:
    # covers: AC-3 (a phrase or role cue is kept with its claim)
    broken = with_claim(
        packet, FieldName.LOSS_DATE, lambda c: c.model_copy(update={"cue": "Written on"})
    )
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("cue missing" in p for p in problems)


def test_two_claims_for_one_field_are_reported_not_raised(packet: Packet) -> None:
    # covers: AC-2, AC-3 (verify_packet returns every problem as a list)
    doc = document(packet)
    twice = claim(packet, FieldName.LOSS_DATE)
    broken = with_document(packet, claims=[*doc.claims, twice])
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("more than one claim" in p for p in problems)


def test_source_ref_that_does_not_match_the_ids_is_reported(packet: Packet) -> None:
    # covers: AC-2 (source_ref is "<packet_id>/<document_id>")
    broken = with_document(packet, source_ref="pkt-999/doc-1")
    problems = verify_packet(broken, _before(packet))
    assert any("source_ref does not match" in p for p in problems)


def test_expected_out_of_field_order_is_reported(packet: Packet) -> None:
    # covers: AC-2 (exactly one entry per FieldName, in FieldName order)
    broken = packet.model_copy(update={"expected": list(reversed(packet.expected))})
    problems = verify_packet(broken, _before(packet))
    assert "expected: not one entry per field in FieldName order" in problems


def test_expected_that_is_not_the_derived_key_is_reported(packet: Packet) -> None:
    # covers: AC-2 (expected comes from derive_expected, never by hand)
    expected = [
        e.model_copy(update={"status": EvidenceStatus.ABSENT, "value": None, "evidence": []})
        if e.field is FieldName.LOSS_LOCATION
        else e
        for e in packet.expected
    ]
    broken = packet.model_copy(update={"expected": expected})
    problems = verify_packet(broken, _before(packet))
    assert "expected: does not match the key derived from the claims" in problems


def test_absent_field_that_a_line_still_claims_is_reported(packet: Packet) -> None:
    # covers: AC-4 (line check: no line carries a claim for an absent field)
    expected = [
        e.model_copy(update={"status": EvidenceStatus.ABSENT, "value": None, "evidence": []})
        if e.field is FieldName.LOSS_DATE
        else e
        for e in packet.expected
    ]
    broken = packet.model_copy(update={"expected": expected})
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.LOSS_DATE)
    assert any("absent but a line carries a claim" in p for p in problems)


@pytest.mark.parametrize(
    ("index", "field", "style"),
    [(1, FieldName.LOSS_TIME, style) for style in range(TIME_FORMAT_COUNT)]
    + [(3, FieldName.REPORTER_CONTACT, style) for style in range(PHONE_FORMAT_COUNT)],
)
def test_absent_value_leaked_in_any_format_is_reported(
    index: int, field: FieldName, style: int
) -> None:
    # covers: AC-4 (every surface form the formatter can produce is checked)
    packet = build_packet(index)  # the rotation omits this field in this packet
    assert _absent(packet, field)
    truth = packet.scenario.value(field)
    assert truth is not None
    leak = format_time(truth, style) if field is FieldName.LOSS_TIME else format_phone(truth, style)
    broken = with_lines(packet, lambda lines: [*lines, f"Noted: {leak}."])
    problems = problems_for(verify_packet(broken, _before(broken)), field)
    assert any("absent value appears" in p for p in problems)


def test_absent_field_without_a_true_value_skips_the_value_check() -> None:
    # covers: AC-4 (no true value: only the line and phrase checks apply)
    packet = build_packet(3)  # index % 4 == 3: the other party has no insurer
    field = FieldName.OTHER_PARTY_INSURER
    assert packet.scenario.value(field) is None
    assert _absent(packet, field)
    broken = with_lines(packet, lambda lines: [*lines, f"Insured with {INSURERS[0]}."])
    assert problems_for(verify_packet(broken, _before(broken)), field) == []


def test_child_found_under_a_no_parent_is_reported(packet: Packet) -> None:
    # covers: AC-5 (a child is found only under a found "yes" parent)
    assert not _absent(packet, FieldName.INJURIES_WHO)
    broken = with_claim(
        packet, FieldName.INJURIES_REPORTED, lambda c: c.model_copy(update={"value": "no"})
    )
    claims = document(broken).claims
    broken = broken.model_copy(update={"expected": derive_expected(broken.scenario, claims)})
    problems = problems_for(verify_packet(broken, _before(packet)), FieldName.INJURIES_WHO)
    assert any("without a found yes parent" in p for p in problems)


@pytest.mark.parametrize(
    ("child", "cue"),
    [(child, cue) for child in PARENTS for cue in child_cues(child)],
)
def test_any_familys_child_line_without_a_found_child_is_reported(
    child: FieldName, cue: str
) -> None:
    # covers: AC-5 (a child's line appears only when the child is found)
    packet = build_packet(3)  # both parents are "no" here, so both children are absent
    assert _absent(packet, child)
    broken = with_lines(packet, lambda lines: [*lines, f"{cue} Someone Else."])
    problems = problems_for(verify_packet(broken, _before(broken)), child)
    assert any("child line present while absent" in p for p in problems)
