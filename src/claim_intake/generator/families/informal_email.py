"""A first person email from the policyholder or a relative.

One sentence per line and no hard wrap, so a cue is never split across lines.
Each asserted field gets its own sentence, written only when the plan asserts it.
"""

import random

from claim_intake.db.states import DocumentKind
from claim_intake.fields import FieldName
from claim_intake.generator.families.base import Assertion, FamilySpec, Line
from claim_intake.generator.families.email_parts import headers, sign_off
from claim_intake.generator.formatters import (
    DATE_FORMAT_COUNT,
    PHONE_FORMAT_COUNT,
    PHRASE_CUES,
    TIME_FORMAT_COUNT,
    format_date,
    format_phone,
    format_time,
    phrase,
)
from claim_intake.generator.models import Family, Scenario

FAMILY = Family.INFORMAL_EMAIL
SUBJECT = "Car accident"
GREETING = "Hi,"
OPENING = "I am writing to report a car accident."
CLOSING = "Thanks,"

FIXED_TEXT: tuple[str, ...] = (SUBJECT, GREETING, OPENING, CLOSING)
CHILD_CUES: dict[FieldName, str] = {
    FieldName.INJURIES_WHO: "My passenger",
    FieldName.POLICE_REPORT_NUMBER: "The report number is",
}


def _sentence(text: str, *assertions: Assertion) -> Line:
    return Line(text, assertions)


def _phrase_line(field: FieldName, value: str, tail: str = ".") -> Line:
    surface = phrase(field, FAMILY, value)
    cue = PHRASE_CUES[field][FAMILY]
    return _sentence(f"{surface}{tail}", Assertion(field, value, surface, cue))


def _vehicle_line(scenario: Scenario, planned: tuple[FieldName, ...]) -> Line | None:
    parts: list[Assertion] = []
    for field in (FieldName.VEHICLE_YEAR, FieldName.VEHICLE_MAKE, FieldName.VEHICLE_MODEL):
        value = scenario.value(field)
        if field in planned and value is not None:
            parts.append(Assertion(field, value, value, "Our car is a"))
    if not parts:
        return None
    words = " ".join(part.surface for part in parts)
    if len(parts) == 1 and parts[0].field is FieldName.VEHICLE_YEAR:
        words = f"{words} model"
    return _sentence(f"Our car is a {words}.", *parts)


def render(scenario: Scenario, planned: tuple[FieldName, ...], rng: random.Random) -> list[Line]:
    """The email's lines, each asserted field attached to every line that carries it."""

    def asserted(field: FieldName) -> str | None:
        value = scenario.value(field)
        return value if field in planned else None

    lines = headers(scenario, planned, rng, SUBJECT)
    lines += [Line(GREETING), Line(""), Line(OPENING)]

    if (policy := asserted(FieldName.POLICY_NUMBER)) is not None:
        cue = "My policy number is"
        lines.append(
            _sentence(f"{cue} {policy}.", Assertion(FieldName.POLICY_NUMBER, policy, policy, cue))
        )
    if (relationship := asserted(FieldName.REPORTER_RELATIONSHIP)) is not None:
        lines.append(_phrase_line(FieldName.REPORTER_RELATIONSHIP, relationship))
    if (loss_date := asserted(FieldName.LOSS_DATE)) is not None:
        surface = format_date(loss_date, rng.randrange(DATE_FORMAT_COUNT))
        cue = "It happened on"
        lines.append(
            _sentence(f"{cue} {surface}.", Assertion(FieldName.LOSS_DATE, loss_date, surface, cue))
        )
    if (loss_time := asserted(FieldName.LOSS_TIME)) is not None:
        surface = format_time(loss_time, rng.randrange(TIME_FORMAT_COUNT))
        cue = "It was at about"
        lines.append(
            _sentence(f"{cue} {surface}.", Assertion(FieldName.LOSS_TIME, loss_time, surface, cue))
        )
    if (location := asserted(FieldName.LOSS_LOCATION)) is not None:
        cue = "It happened at"
        lines.append(
            _sentence(
                f"{cue} {location}.", Assertion(FieldName.LOSS_LOCATION, location, location, cue)
            )
        )
    if (description := asserted(FieldName.LOSS_DESCRIPTION)) is not None:
        cue = "What happened:"
        lines.append(
            _sentence(
                f"{cue} {description}.",
                Assertion(FieldName.LOSS_DESCRIPTION, description, description, cue),
            )
        )
    if (vehicle := _vehicle_line(scenario, planned)) is not None:
        lines.append(vehicle)
    if (driver := asserted(FieldName.DRIVER_NAME)) is not None:
        cue = "was driving"
        lines.append(
            _sentence(f"{driver} {cue}.", Assertion(FieldName.DRIVER_NAME, driver, driver, cue))
        )
    if (other := asserted(FieldName.OTHER_PARTY_NAME)) is not None:
        cue = "The other driver was"
        lines.append(
            _sentence(f"{cue} {other}.", Assertion(FieldName.OTHER_PARTY_NAME, other, other, cue))
        )
    if (other_vehicle := asserted(FieldName.OTHER_PARTY_VEHICLE)) is not None:
        cue = "The other car was a"
        lines.append(
            _sentence(
                f"{cue} {other_vehicle}.",
                Assertion(FieldName.OTHER_PARTY_VEHICLE, other_vehicle, other_vehicle, cue),
            )
        )
    if (insurer := asserted(FieldName.OTHER_PARTY_INSURER)) is not None:
        cue = "Their insurance is with"
        lines.append(
            _sentence(
                f"{cue} {insurer}.", Assertion(FieldName.OTHER_PARTY_INSURER, insurer, insurer, cue)
            )
        )
    if (injuries := asserted(FieldName.INJURIES_REPORTED)) is not None:
        lines.append(_phrase_line(FieldName.INJURIES_REPORTED, injuries))
    if (passenger := asserted(FieldName.INJURIES_WHO)) is not None:
        cue = CHILD_CUES[FieldName.INJURIES_WHO]
        lines.append(
            _sentence(
                f"{cue} {passenger} went to urgent care.",
                Assertion(FieldName.INJURIES_WHO, passenger, passenger, cue),
            )
        )
    if (police := asserted(FieldName.POLICE_REPORT_FILED)) is not None:
        lines.append(_phrase_line(FieldName.POLICE_REPORT_FILED, police))
    if (report := asserted(FieldName.POLICE_REPORT_NUMBER)) is not None:
        cue = CHILD_CUES[FieldName.POLICE_REPORT_NUMBER]
        lines.append(
            _sentence(
                f"{cue} {report}.", Assertion(FieldName.POLICE_REPORT_NUMBER, report, report, cue)
            )
        )
    if (phone := asserted(FieldName.REPORTER_CONTACT)) is not None:
        surface = format_phone(phone, rng.randrange(PHONE_FORMAT_COUNT))
        cue = "You can call me at"
        lines.append(
            _sentence(
                f"{cue} {surface}.", Assertion(FieldName.REPORTER_CONTACT, phone, surface, cue)
            )
        )

    lines += sign_off(scenario, planned, CLOSING)
    return lines


SPEC = FamilySpec(FAMILY, DocumentKind.EMAIL, render, FIXED_TEXT, CHILD_CUES)
