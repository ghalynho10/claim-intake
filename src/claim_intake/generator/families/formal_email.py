"""An email from an insurance agent reporting a loss for the policyholder.

Third person wording, the same headers as the informal family. The word
"agent" appears only on the relationship line, so the relationship stays a
field to extract rather than a hint in every sentence.
"""

import random

from claim_intake.db.states import DocumentKind
from claim_intake.fields import FieldName
from claim_intake.generator.families.base import FamilySpec, Line, Stated
from claim_intake.generator.families.email_parts import EmailTemplate, render_email
from claim_intake.generator.models import Family, Scenario

CHILD_CUES: dict[FieldName, str] = {
    FieldName.INJURIES_WHO: "The injured passenger was",
    FieldName.POLICE_REPORT_NUMBER: "The police report number is",
}

TEMPLATE = EmailTemplate(
    family=Family.FORMAL_EMAIL,
    subject="New loss notice",
    greeting="Hello claims team,",
    opening="I am writing to report an auto collision.",
    body=(
        Stated(FieldName.REPORTER_RELATIONSHIP, "{}."),
        Stated(FieldName.POLICY_NUMBER, "The policy number is {}.", "The policy number is"),
        Stated(FieldName.LOSS_DATE, "The loss occurred on {}.", "The loss occurred on"),
        Stated(FieldName.LOSS_TIME, "The time of loss was about {}.", "The time of loss was about"),
        Stated(FieldName.LOSS_LOCATION, "The loss location was {}.", "The loss location was"),
        Stated(FieldName.LOSS_DESCRIPTION, "Loss description: {}.", "Loss description:"),
        "The insured vehicle is a",
        Stated(FieldName.DRIVER_NAME, "{} was driving.", "was driving"),
        Stated(FieldName.OTHER_PARTY_NAME, "The other party was {}.", "The other party was"),
        Stated(
            FieldName.OTHER_PARTY_VEHICLE,
            "The other party's vehicle was a {}.",
            "The other party's vehicle was a",
        ),
        Stated(
            FieldName.OTHER_PARTY_INSURER, "The other party is insured with {}.", "insured with"
        ),
        Stated(FieldName.INJURIES_REPORTED, "{}."),
        Stated(
            FieldName.INJURIES_WHO,
            "The injured passenger was {}.",
            CHILD_CUES[FieldName.INJURIES_WHO],
        ),
        Stated(FieldName.POLICE_REPORT_FILED, "{}."),
        Stated(
            FieldName.POLICE_REPORT_NUMBER,
            "The police report number is {}.",
            CHILD_CUES[FieldName.POLICE_REPORT_NUMBER],
        ),
        Stated(FieldName.REPORTER_CONTACT, "I can be reached at {}.", "I can be reached at"),
    ),
    closing="Regards,",
)


def render(scenario: Scenario, planned: tuple[FieldName, ...], rng: random.Random) -> list[Line]:
    """The email's lines, each asserted field attached to every line that carries it."""
    return render_email(TEMPLATE, scenario, planned, rng)


SPEC = FamilySpec(TEMPLATE.family, DocumentKind.EMAIL, render, TEMPLATE.fixed_text(), CHILD_CUES)
