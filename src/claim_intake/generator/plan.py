"""Which fields a document asserts, decided before any text exists.

Planning by rule (rotation, parent and child, no true value) instead of by
chance is what makes the dev set's coverage provable by a test (AC-7).
"""

from claim_intake.fields import FieldName
from claim_intake.generator.models import Scenario

# Asserted in every packet.
ALWAYS: tuple[FieldName, ...] = (
    FieldName.LOSS_DATE,
    FieldName.LOSS_LOCATION,
    FieldName.LOSS_DESCRIPTION,
)

# The other 16 fields in FieldName order; a field's position here is its `j`.
OPTIONAL: tuple[FieldName, ...] = tuple(field for field in FieldName if field not in ALWAYS)

PARENTS: dict[FieldName, FieldName] = {
    FieldName.INJURIES_WHO: FieldName.INJURIES_REPORTED,
    FieldName.POLICE_REPORT_NUMBER: FieldName.POLICE_REPORT_FILED,
}

ROTATION = 5


def rotated_out(field: FieldName, index: int) -> bool:
    """Optional field `j` is omitted from packet `i` when `(i + j) % 5 == 0`.

    Each optional field is omitted in 4 of 20 packets across all 3 families.
    Fields `j` and `j + 5` are always omitted together: by design for the dev
    set, and a pattern feature 14's test set must not inherit.
    """
    return (index + OPTIONAL.index(field)) % ROTATION == 0


def plan_claims(scenario: Scenario, index: int) -> tuple[FieldName, ...]:
    """The fields packet `index` asserts, in `FieldName` order.

    A field with no true value is never asserted, and a child is asserted only
    when its parent is asserted with `yes`.
    """
    planned: list[FieldName] = []
    for field in FieldName:
        if scenario.value(field) is None:
            continue
        if field not in ALWAYS and rotated_out(field, index):
            continue
        parent = PARENTS.get(field)
        if parent is not None and (parent not in planned or scenario.value(parent) != "yes"):
            continue
        planned.append(field)
    return tuple(planned)
