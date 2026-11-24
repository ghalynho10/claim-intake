"""A first person email from the policyholder or a relative.

One sentence per line and no hard wrap, so a cue is never split across lines.
Each asserted field gets its own sentence, written only when the plan asserts it.
"""

import random

from claim_intake.db.states import DocumentKind
from claim_intake.fields import FieldName
from claim_intake.generator.families.base import FamilySpec, Line, Stated
from claim_intake.generator.families.email_parts import EmailTemplate, render_email
from claim_intake.generator.models import Family, Scenario

CHILD_CUES: dict[FieldName, str] = {
    FieldName.INJURIES_WHO: "My passenger",
    FieldName.POLICE_REPORT_NUMBER: "The report number is",
}

TEMPLATE = EmailTemplate(
    family=Family.INFORMAL_EMAIL,
    subject="Car accident",
    greeting="Hi,",
    opening="I am writing to report a car accident.",
    body=(
        Stated(FieldName.POLICY_NUMBER, "My policy number is {}.", "My policy number is"),
        Stated(FieldName.REPORTER_RELATIONSHIP, "{}."),
        Stated(FieldName.LOSS_DATE, "It happened on {}.", "It happened on"),
        Stated(FieldName.LOSS_TIME, "It was at about {}.", "It was at about"),
        Stated(FieldName.LOSS_LOCATION, "It happened at {}.", "It happened at"),
        Stated(FieldName.LOSS_DESCRIPTION, "What happened: {}.", "What happened:"),
        "Our car is a",
        Stated(FieldName.DRIVER_NAME, "{} was driving.", "was driving"),
        Stated(FieldName.OTHER_PARTY_NAME, "The other driver was {}.", "The other driver was"),
        Stated(FieldName.OTHER_PARTY_VEHICLE, "The other car was a {}.", "The other car was a"),
        Stated(
            FieldName.OTHER_PARTY_INSURER, "Their insurance is with {}.", "Their insurance is with"
        ),
        Stated(FieldName.INJURIES_REPORTED, "{}."),
        Stated(
            FieldName.INJURIES_WHO,
            "My passenger {} went to urgent care.",
            CHILD_CUES[FieldName.INJURIES_WHO],
        ),
        Stated(FieldName.POLICE_REPORT_FILED, "{}."),
        Stated(
            FieldName.POLICE_REPORT_NUMBER,
            "The report number is {}.",
            CHILD_CUES[FieldName.POLICE_REPORT_NUMBER],
        ),
        Stated(FieldName.REPORTER_CONTACT, "You can call me at {}.", "You can call me at"),
    ),
    closing="Thanks,",
)


def render(scenario: Scenario, planned: tuple[FieldName, ...], rng: random.Random) -> list[Line]:
    """The email's lines, each asserted field attached to every line that carries it."""
    return render_email(TEMPLATE, scenario, planned, rng)


SPEC = FamilySpec(TEMPLATE.family, DocumentKind.EMAIL, render, TEMPLATE.fixed_text(), CHILD_CUES)
