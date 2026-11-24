"""Which fields a document asserts, decided before any text exists.

Planning by rule (rotation, parent and child, no true value) instead of by
chance is what makes the dev set's coverage provable by a test (AC-7).
"""

from claim_intake.fields import FieldName
from claim_intake.generator.models import Scenario

# Thin slice: the three fields carried end to end first (build plan task 2).
THIN_FIELDS: tuple[FieldName, ...] = (
    FieldName.POLICY_NUMBER,
    FieldName.REPORTER_NAME,
    FieldName.LOSS_DATE,
)


def plan_claims(scenario: Scenario, index: int) -> tuple[FieldName, ...]:
    """The fields packet `index` asserts, in `FieldName` order."""
    return tuple(
        field for field in FieldName if field in THIN_FIELDS and scenario.value(field) is not None
    )
