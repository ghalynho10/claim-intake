"""The planning rules: rotation, parents and children, no true value (spec 0003,
Planning rules). Pure functions over the index and the scenario."""

import random

from claim_intake.fields import FieldName
from claim_intake.generator.plan import ALWAYS, OPTIONAL, PARENTS, plan_claims, rotated_out
from claim_intake.generator.values import has_insurer, injuries_truth, police_truth, sample_scenario


def test_sixteen_optional_fields_in_field_order() -> None:
    assert len(OPTIONAL) == 16
    assert OPTIONAL[0] is FieldName.POLICY_NUMBER
    assert OPTIONAL[15] is FieldName.POLICE_REPORT_NUMBER


def test_rotation_omits_each_optional_field_in_four_of_twenty() -> None:
    for field in OPTIONAL:
        omitted = [i for i in range(20) if rotated_out(field, i)]
        assert len(omitted) == 4
        assert {i % 3 for i in omitted} == {0, 1, 2}


def test_always_fields_are_always_planned() -> None:
    for index in range(20):
        planned = plan_claims(sample_scenario(index, random.Random(index)), index)
        assert all(field in planned for field in ALWAYS)


def test_children_follow_a_planned_yes_parent() -> None:
    for index in range(40):
        scenario = sample_scenario(index, random.Random(index))
        planned = plan_claims(scenario, index)
        for child, parent in PARENTS.items():
            if child in planned:
                assert parent in planned
                assert scenario.value(parent) == "yes"
            if parent not in planned:
                assert child not in planned


def test_parent_truths_and_missing_insurer_follow_the_index() -> None:
    for index in range(20):
        scenario = sample_scenario(index, random.Random(index))
        assert scenario.injuries_reported == injuries_truth(index)
        assert scenario.police_report_filed == police_truth(index)
        assert (scenario.injuries_who is None) == (injuries_truth(index) == "no")
        assert (scenario.police_report_number is None) == (police_truth(index) == "no")
        assert (scenario.other_party_insurer is None) == (not has_insurer(index))
        planned = plan_claims(scenario, index)
        if not has_insurer(index):
            assert FieldName.OTHER_PARTY_INSURER not in planned
