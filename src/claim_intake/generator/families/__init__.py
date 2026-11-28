"""The family registry: one interchangeable renderer per template family.

`FAMILIES` follows `Family` declaration order, so packet `index` renders with
`FAMILIES[index % 3]`. Adding a family means one new module and one entry here,
with no change to the packet format or the verifier.
"""

from claim_intake.fields import FieldName
from claim_intake.generator.families import formal_email, informal_email, web_form
from claim_intake.generator.families.base import FamilySpec
from claim_intake.generator.models import Family

FAMILIES: tuple[FamilySpec, ...] = (informal_email.SPEC, formal_email.SPEC, web_form.SPEC)


def child_cues(field: FieldName) -> tuple[str, ...]:
    """Every family's cue for a child field's line."""
    return tuple(spec.child_cues[field] for spec in FAMILIES if field in spec.child_cues)


def family_spec(family: Family) -> FamilySpec:
    """The registered spec of one family."""
    for spec in FAMILIES:
        if spec.family is family:
            return spec
    raise KeyError(family)
