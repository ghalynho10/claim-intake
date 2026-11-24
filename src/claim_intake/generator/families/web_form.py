"""A web intake form: `Label: value` lines under generic section headings.

A section with no asserted field gets no heading, so an empty "Police" block
never hints at a police report. Headings and the title are machine text that
noise never edits.
"""

import random

from claim_intake.db.states import DocumentKind
from claim_intake.fields import FieldName
from claim_intake.generator.families.base import FamilySpec, Line, Stated, stated_line
from claim_intake.generator.models import Family, Scenario

FAMILY = Family.WEB_FORM
TITLE = "Claim intake form"

CHILD_CUES: dict[FieldName, str] = {
    FieldName.INJURIES_WHO: "Injured person:",
    FieldName.POLICE_REPORT_NUMBER: "Police report number:",
}

SECTIONS: tuple[tuple[str, tuple[Stated, ...]], ...] = (
    ("Policy", (Stated(FieldName.POLICY_NUMBER, "Policy number: {}", "Policy number:"),)),
    (
        "Reporter",
        (
            Stated(FieldName.REPORTER_NAME, "Reporter name: {}", "Reporter name:"),
            Stated(FieldName.REPORTER_CONTACT, "Phone: {}", "Phone:"),
            Stated(FieldName.REPORTER_RELATIONSHIP, "{}"),
        ),
    ),
    (
        "Loss",
        (
            Stated(FieldName.LOSS_DATE, "Date of loss: {}", "Date of loss:"),
            Stated(FieldName.LOSS_TIME, "Time of loss: {}", "Time of loss:"),
            Stated(FieldName.LOSS_LOCATION, "Location: {}", "Location:"),
            Stated(FieldName.LOSS_DESCRIPTION, "Description: {}", "Description:"),
        ),
    ),
    (
        "Insured vehicle",
        (
            Stated(FieldName.VEHICLE_YEAR, "Year: {}", "Year:"),
            Stated(FieldName.VEHICLE_MAKE, "Make: {}", "Make:"),
            Stated(FieldName.VEHICLE_MODEL, "Model: {}", "Model:"),
            Stated(FieldName.DRIVER_NAME, "Driver: {}", "Driver:"),
        ),
    ),
    (
        "Other party",
        (
            Stated(FieldName.OTHER_PARTY_NAME, "Other party name: {}", "Other party name:"),
            Stated(
                FieldName.OTHER_PARTY_VEHICLE, "Other party vehicle: {}", "Other party vehicle:"
            ),
            Stated(
                FieldName.OTHER_PARTY_INSURER, "Other party insurer: {}", "Other party insurer:"
            ),
        ),
    ),
    (
        "Injuries",
        (
            Stated(FieldName.INJURIES_REPORTED, "{}"),
            Stated(
                FieldName.INJURIES_WHO, "Injured person: {}", CHILD_CUES[FieldName.INJURIES_WHO]
            ),
        ),
    ),
    (
        "Police",
        (
            Stated(FieldName.POLICE_REPORT_FILED, "{}"),
            Stated(
                FieldName.POLICE_REPORT_NUMBER,
                "Police report number: {}",
                CHILD_CUES[FieldName.POLICE_REPORT_NUMBER],
            ),
        ),
    ),
)

FIXED_TEXT: tuple[str, ...] = (TITLE, *(heading for heading, _ in SECTIONS))


def render(scenario: Scenario, planned: tuple[FieldName, ...], rng: random.Random) -> list[Line]:
    """The form's lines: the title, then each non empty section after a blank line."""
    lines = [Line(TITLE, fixed=True)]
    for heading, entries in SECTIONS:
        body = [
            line
            for entry in entries
            if (line := stated_line(entry, scenario, planned, FAMILY, rng)) is not None
        ]
        if body:
            lines += [Line(""), Line(heading, fixed=True), *body]
    return lines


SPEC = FamilySpec(FAMILY, DocumentKind.FORM, render, FIXED_TEXT, CHILD_CUES)
