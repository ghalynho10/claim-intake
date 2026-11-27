"""What each template family writes (spec 0003, Template families, Planning
rules, Value sourcing rows for `From`, relationship and the form headings).

Checked over a larger generated set than the dev set, so a rule that only
breaks for a rare draw still shows up.
"""

import random
import re

import pytest

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.families import web_form
from claim_intake.generator.families.base import Stated, stated_line, vehicle_line
from claim_intake.generator.models import Family, Packet, family_for
from claim_intake.generator.pipeline import DEV_SEED, generate_dataset
from claim_intake.generator.values import RELATIONSHIPS_BY_FAMILY, sample_scenario

_FROM = re.compile(r"^From: (?:(?P<name>.+) <)?(?P<local>[^@<>]+)@example\.com>?$")
_SENDER_TOKEN = re.compile(r"[bcdfghjkmnpqrstvwxz]{2}\d{4}")
# Words that say how the reporter relates to the policyholder, or who drove.
_ROLE_WORDS = ("spouse", "parent", "child", "agent", "husband", "wife", "policyholder")


@pytest.fixture(scope="module")
def packets() -> list[Packet]:
    return generate_dataset(DEV_SEED, 200)


def _entry(packet: Packet, field: FieldName) -> tuple[EvidenceStatus, set[int]]:
    entry = next(e for e in packet.expected if e.field is field)
    return entry.status, {e.index for e in entry.evidence}


def test_from_header_is_a_token_at_example_com_named_only_when_the_name_is_found(
    packets: list[Packet],
) -> None:
    # covers: AC-9, Value sourcing "From address"
    emails = [p for p in packets if p.family is not Family.WEB_FORM]
    for packet in emails:
        lines = packet.documents[0].lines
        match = _FROM.match(lines[0])
        assert match, packet.packet_id
        assert _SENDER_TOKEN.fullmatch(match["local"]), packet.packet_id
        status, evidence = _entry(packet, FieldName.REPORTER_NAME)
        if status is EvidenceStatus.FOUND:
            assert match["name"] == packet.scenario.reporter_name, packet.packet_id
            assert {0, len(lines) - 1} <= evidence, packet.packet_id
        else:
            assert match["name"] is None, packet.packet_id
        contact = packet.scenario.reporter_contact
        assert contact is not None and contact not in lines[0], packet.packet_id
    assert len(emails) > 100


def test_relationship_comes_from_the_familys_value_set() -> None:
    # Planning rules, "Relationship by family"
    for index in range(60):
        scenario = sample_scenario(index, random.Random(index))
        family = family_for(index)
        assert scenario.reporter_relationship in RELATIONSHIPS_BY_FAMILY[family]
        if family is Family.FORMAL_EMAIL:
            assert scenario.reporter_relationship == "agent"
        if family is Family.INFORMAL_EMAIL:
            assert scenario.reporter_relationship != "agent"


def test_role_words_appear_only_on_the_relationship_line(packets: list[Packet]) -> None:
    # Planning rules, "People": guards the first AC-10 read ("My passenger"
    # implied the reporter drove). A word check, not a judgment of meaning.
    for packet in packets:
        _, relationship_lines = _entry(packet, FieldName.REPORTER_RELATIONSHIP)
        for index, text in enumerate(packet.documents[0].lines):
            assert "my passenger" not in text.lower(), packet.packet_id
            if index in relationship_lines:
                continue
            words = set(re.findall(r"[a-z]+", text.lower()))
            assert not words & set(_ROLE_WORDS), (packet.packet_id, index)


def test_web_form_heading_appears_only_over_a_section_with_lines(
    packets: list[Packet],
) -> None:
    # Template families: "A section with no lines has no heading"
    forms = [p for p in packets if p.family is Family.WEB_FORM]
    for packet in forms:
        lines = packet.documents[0].lines
        for heading, entries in web_form.SECTIONS:
            has_lines = any(
                _entry(packet, entry.field)[0] is EvidenceStatus.FOUND for entry in entries
            )
            assert (heading in lines) == has_lines, (packet.packet_id, heading)
            if has_lines:
                after = lines[lines.index(heading) + 1]
                assert after.strip(), (packet.packet_id, heading)
    assert len(forms) > 50


def test_a_template_without_its_cue_is_refused() -> None:
    scenario = sample_scenario(0, random.Random(0))
    entry = Stated(FieldName.POLICY_NUMBER, "Number {}", "Policy number:")
    with pytest.raises(ValueError, match="policy_number"):
        stated_line(entry, scenario, (FieldName.POLICY_NUMBER,), Family.WEB_FORM, random.Random(0))


def test_a_field_not_planned_gets_no_line() -> None:
    scenario = sample_scenario(0, random.Random(0))
    entry = Stated(FieldName.POLICY_NUMBER, "Policy number: {}", "Policy number:")
    assert stated_line(entry, scenario, (), Family.WEB_FORM, random.Random(0)) is None


def test_vehicle_line_with_only_a_year_reads_as_a_model_year() -> None:
    scenario = sample_scenario(0, random.Random(0))
    line = vehicle_line(scenario, (FieldName.VEHICLE_YEAR,), "Our car is a")
    assert line is not None
    assert line.text == f"Our car is a {scenario.vehicle_year} model."
    assert [a.field for a in line.assertions] == [FieldName.VEHICLE_YEAR]


def test_vehicle_line_carries_year_make_and_model_as_three_claims() -> None:
    scenario = sample_scenario(0, random.Random(0))
    planned = (FieldName.VEHICLE_YEAR, FieldName.VEHICLE_MAKE, FieldName.VEHICLE_MODEL)
    line = vehicle_line(scenario, planned, "Our car is a")
    assert line is not None
    words = f"{scenario.vehicle_year} {scenario.vehicle_make} {scenario.vehicle_model}"
    assert line.text == f"Our car is a {words}."
    assert [a.field for a in line.assertions] == list(planned)
    assert vehicle_line(scenario, (), "Our car is a") is None
