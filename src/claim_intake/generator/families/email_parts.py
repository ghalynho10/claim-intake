"""Header lines both email families share.

`From` and `Date` are the headers RFC 5322 section 3.6 requires; `To` and
`Subject` are added because real claim emails carry them. Headers are machine
text, so noise never edits them.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta

from claim_intake.fields import FieldName
from claim_intake.generator.families.base import Assertion, Line, Stated, stated_line, vehicle_line
from claim_intake.generator.formatters import MONTH_ABBREVIATIONS, WEEKDAY_ABBREVIATIONS
from claim_intake.generator.models import Family, Scenario

CLAIMS_INBOX = "claims@example.com"
_TOKEN_LETTERS = "bcdfghjkmnpqrstvwxz"
SENT_HOURS: tuple[int, ...] = tuple(range(7, 22))


def sender_token(rng: random.Random) -> str:
    """A `From` local part that is no one's name: two consonants and four digits."""
    letters = "".join(rng.choice(_TOKEN_LETTERS) for _ in range(2))
    return f"{letters}{rng.randrange(1000, 10_000)}"


def from_line(scenario: Scenario, planned: tuple[FieldName, ...], token: str) -> Line:
    """The `From` header; it shows the reporter's name only when the name is asserted."""
    address = f"{token}@example.com"
    name = scenario.reporter_name
    if FieldName.REPORTER_NAME in planned and name is not None:
        assertion = Assertion(FieldName.REPORTER_NAME, name, name, "From:")
        return Line(f"From: {name} <{address}>", (assertion,), fixed=True)
    return Line(f"From: {address}", fixed=True)


def date_line(scenario: Scenario, rng: random.Random) -> Line:
    """The `Date` header: always sent after the loss, never in the loss hour.

    The draws are the loss date plus 0 to 3 days and an hour other than the loss
    hour. Only a header that would not be after the loss (same day, earlier hour)
    is redrawn, after the other draws, so every other packet keeps its own random
    stream: first with an hour after the loss hour, or, when no sent hour (07 to
    21) is left that day, on a day 1 to 3 days later. The header and the loss
    time are read as the same local time; the fixed offset is not modelled.
    """
    if scenario.loss_date is None or scenario.loss_time is None:
        raise ValueError("every scenario has a loss date and a loss time")
    loss_day = date.fromisoformat(scenario.loss_date)
    loss_hour = int(scenario.loss_time[:2])
    days = rng.randrange(4)
    hour = rng.choice([h for h in SENT_HOURS if h != loss_hour])
    # A minute equal to the loss hour could make "MM:SS" read as the loss time.
    minute = rng.choice([m for m in range(60) if m != loss_hour])
    second = rng.randrange(60)
    if days == 0 and hour < loss_hour:
        later = [h for h in SENT_HOURS if h > loss_hour]
        if later:
            hour = rng.choice(later)
        else:
            days = 1 + rng.randrange(3)
    sent = loss_day + timedelta(days=days)
    weekday = WEEKDAY_ABBREVIATIONS[sent.weekday()]
    month = MONTH_ABBREVIATIONS[sent.month - 1]
    stamp = f"{sent.day:02d} {month} {sent.year} {hour:02d}:{minute:02d}:{second:02d} -0500"
    return Line(f"Date: {weekday}, {stamp}", fixed=True)


def headers(
    scenario: Scenario,
    planned: tuple[FieldName, ...],
    rng: random.Random,
    subject: str,
) -> list[Line]:
    """From, To, Date and Subject, then the blank line that ends the header block.

    The subject names the policy number when it is asserted, which makes it a
    second evidence line for that claim.
    """
    token = sender_token(rng)
    lines = [from_line(scenario, planned, token), Line(f"To: {CLAIMS_INBOX}", fixed=True)]
    lines.append(date_line(scenario, rng))
    policy = scenario.policy_number
    if FieldName.POLICY_NUMBER in planned and policy is not None:
        assertion = Assertion(FieldName.POLICY_NUMBER, policy, policy, "policy")
        lines.append(Line(f"Subject: {subject}, policy {policy}", (assertion,), fixed=True))
    else:
        lines.append(Line(f"Subject: {subject}", fixed=True))
    lines.append(Line(""))
    return lines


def sign_off(scenario: Scenario, planned: tuple[FieldName, ...], closing: str) -> list[Line]:
    """A blank line, the closing word, and the reporter's name when it is asserted."""
    lines = [Line(""), Line(closing, fixed=True)]
    name = scenario.reporter_name
    if FieldName.REPORTER_NAME in planned and name is not None:
        lines.append(Line(name, (Assertion(FieldName.REPORTER_NAME, name, name, ""),)))
    return lines


@dataclass(frozen=True)
class EmailTemplate:
    """The fixed text of one email family and the order of its body sentences.

    A body entry is a `Stated` field sentence, or a string: the prefix of the
    combined vehicle sentence at that position.
    """

    family: Family
    subject: str
    greeting: str
    opening: str
    body: tuple[Stated | str, ...]
    closing: str

    def fixed_text(self) -> tuple[str, ...]:
        """Subject, greeting, opening and closing, for the table checks."""
        return (self.subject, self.greeting, self.opening, self.closing)


def render_email(
    template: EmailTemplate,
    scenario: Scenario,
    planned: tuple[FieldName, ...],
    rng: random.Random,
) -> list[Line]:
    """Headers, greeting, one sentence per asserted field, then the sign off."""
    lines = headers(scenario, planned, rng, template.subject)
    lines += [Line(template.greeting), Line(""), Line(template.opening)]
    for entry in template.body:
        if isinstance(entry, str):
            line = vehicle_line(scenario, planned, entry)
        else:
            line = stated_line(entry, scenario, planned, template.family, rng)
        if line is not None:
            lines.append(line)
    lines += sign_off(scenario, planned, template.closing)
    return lines
