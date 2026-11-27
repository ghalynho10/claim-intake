"""The answer key comes from the claims by one pure function (spec 0003, AC-2).

Plain inputs, no packet pipeline: a claim in gives one found entry out, and no
claim gives an absent entry with no value and no evidence.
"""

import random

import pytest

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.models import Claim, EvidenceLine, Scenario
from claim_intake.generator.values import sample_scenario


@pytest.fixture(scope="module")
def scenario() -> Scenario:
    return sample_scenario(0, random.Random(0))


def _claim(field: FieldName, value: str, index: int = 4) -> Claim:
    line = EvidenceLine(index=index, text=f"Line with {value}")
    return Claim(field=field, value=value, surface=value, cue="", evidence=[line])


def test_no_claims_gives_nineteen_absent_entries_in_field_order(scenario: Scenario) -> None:
    # covers: AC-2
    expected = derive_expected(scenario, [])
    assert [e.field for e in expected] == list(FieldName)
    assert all(e.status is EvidenceStatus.ABSENT for e in expected)
    assert all(e.value is None and e.evidence == [] for e in expected)


def test_one_claim_is_found_with_its_value_and_evidence(scenario: Scenario) -> None:
    # covers: AC-2
    date = _claim(FieldName.LOSS_DATE, "2026-03-14")
    expected = {e.field: e for e in derive_expected(scenario, [date])}
    entry = expected[FieldName.LOSS_DATE]
    assert entry.status is EvidenceStatus.FOUND
    assert entry.value == "2026-03-14"
    assert entry.evidence == date.evidence
    others = [e for field, e in expected.items() if field is not FieldName.LOSS_DATE]
    assert all(e.status is EvidenceStatus.ABSENT for e in others)


def test_claim_order_does_not_change_the_key(scenario: Scenario) -> None:
    # covers: AC-2 (the key is always in FieldName order)
    claims = [
        _claim(FieldName.POLICE_REPORT_NUMBER, "AB1234567", 9),
        _claim(FieldName.POLICY_NUMBER, "CD7654321", 2),
    ]
    assert derive_expected(scenario, claims) == derive_expected(scenario, claims[::-1])


def test_two_claims_for_one_field_raise_naming_the_field_not_the_value(
    scenario: Scenario,
) -> None:
    # Conflicting claims are feature 11's; the starter key refuses them loudly.
    claims = [_claim(FieldName.LOSS_DATE, "2026-03-14"), _claim(FieldName.LOSS_DATE, "2026-03-15")]
    with pytest.raises(ValueError, match="loss_date") as caught:
        derive_expected(scenario, claims)
    assert "2026-03-1" not in str(caught.value)
