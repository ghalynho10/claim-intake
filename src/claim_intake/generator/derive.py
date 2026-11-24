"""The answer key, derived from what the document asserts.

One pure function builds `expected`, so no label is ever written by hand and a
change to the claims is a change to the key.
"""

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.models import Claim, ExpectedField, Scenario


def derive_expected(scenario: Scenario, claims: list[Claim]) -> list[ExpectedField]:
    """One entry per field in `FieldName` order: no claim is absent, one claim is found.

    `scenario` is part of the signature because the key is defined from both the
    world and the document; the starter rules need only the claims. Two claims for
    one field (conflicting, feature 11) are not built yet, so they raise.
    """
    del scenario  # the starter rules read only the claims
    expected: list[ExpectedField] = []
    for field in FieldName:
        matching = [claim for claim in claims if claim.field is field]
        if len(matching) > 1:
            raise ValueError(f"field {field} has more than one claim")
        if matching:
            claim = matching[0]
            expected.append(
                ExpectedField(
                    field=field,
                    status=EvidenceStatus.FOUND,
                    value=claim.value,
                    evidence=claim.evidence,
                )
            )
        else:
            expected.append(
                ExpectedField(field=field, status=EvidenceStatus.ABSENT, value=None, evidence=[])
            )
    return expected
