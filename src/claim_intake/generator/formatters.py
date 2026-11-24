"""Surface text for each field kind, and the parsers that read it back.

A canonical value (`2026-03-14`, `14:30`, `yes`) becomes the text a document
shows, and every surface must parse back to its value: that round trip is what
lets the verifier prove a label against the final text. Month and weekday names
come from tuples, never `strftime`, so the locale cannot change a byte. The
matching helpers here are the one definition of "on a word boundary" that the
sampler, the noise stage and the verifier share.
"""

import re
from datetime import date
from enum import StrEnum

from claim_intake.fields import FieldName
from claim_intake.generator.models import Family


class Kind(StrEnum):
    """How a field's value looks and how its surface is read back."""

    TEXT = "text"
    NAME = "name"
    PHONE = "phone"
    DATE = "date"
    TIME = "time"
    PHRASE = "phrase"


FIELD_KINDS: dict[FieldName, Kind] = {
    FieldName.POLICY_NUMBER: Kind.TEXT,
    FieldName.REPORTER_NAME: Kind.NAME,
    FieldName.REPORTER_CONTACT: Kind.PHONE,
    FieldName.REPORTER_RELATIONSHIP: Kind.PHRASE,
    FieldName.LOSS_DATE: Kind.DATE,
    FieldName.LOSS_TIME: Kind.TIME,
    FieldName.LOSS_LOCATION: Kind.TEXT,
    FieldName.LOSS_DESCRIPTION: Kind.TEXT,
    FieldName.VEHICLE_YEAR: Kind.TEXT,
    FieldName.VEHICLE_MAKE: Kind.TEXT,
    FieldName.VEHICLE_MODEL: Kind.TEXT,
    FieldName.DRIVER_NAME: Kind.NAME,
    FieldName.OTHER_PARTY_NAME: Kind.NAME,
    FieldName.OTHER_PARTY_VEHICLE: Kind.TEXT,
    FieldName.OTHER_PARTY_INSURER: Kind.TEXT,
    FieldName.INJURIES_REPORTED: Kind.PHRASE,
    FieldName.INJURIES_WHO: Kind.NAME,
    FieldName.POLICE_REPORT_FILED: Kind.PHRASE,
    FieldName.POLICE_REPORT_NUMBER: Kind.TEXT,
}

MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTH_ABBREVIATIONS: tuple[str, ...] = tuple(m[:3] for m in MONTHS)
WEEKDAY_ABBREVIATIONS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Words that flip or soften a claim. Noise never touches them on a claim line.
PROTECTED_WORDS: tuple[str, ...] = ("not", "no", "never", "about")


# --- matching -------------------------------------------------------------------


def normalize(text: str) -> str:
    """Lowercase and collapse every run of whitespace (newlines included) to one space."""
    return " ".join(text.lower().split())


def word_pattern(needle: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """A pattern for `needle` that only matches on word boundaries.

    Lookarounds instead of `\\b`, so a needle that starts or ends with
    punctuation (`Policy number:`) still gets a boundary check.
    """
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)", flags)


def has_word(haystack: str, needle: str) -> bool:
    """Exact case, word boundary containment."""
    return word_pattern(needle).search(haystack) is not None


def has_word_normalized(haystack: str, needle: str) -> bool:
    """Containment after lowercasing and collapsing whitespace on both sides."""
    return word_pattern(normalize(needle)).search(normalize(haystack)) is not None


def count_protected_words(text: str) -> int:
    """How many negation or qualifier words a line holds."""
    return sum(len(word_pattern(word, ignore_case=True).findall(text)) for word in PROTECTED_WORDS)


# --- dates ----------------------------------------------------------------------

DATE_FORMAT_COUNT = 3
_DATE_LONG = re.compile(rf"^({'|'.join(MONTHS)}) (\d{{1,2}}), (\d{{4}})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATE_US = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def format_date(value: str, style: int) -> str:
    """A canonical `YYYY-MM-DD` date as text. Every style carries the year."""
    day = date.fromisoformat(value)
    if style == 0:
        return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"
    if style == 1:
        return day.isoformat()
    if style == 2:
        return f"{day.month:02d}/{day.day:02d}/{day.year}"
    raise ValueError("unknown date style")


def parse_date(surface: str) -> str | None:
    """The canonical date a surface was written from, or None."""
    try:
        if match := _DATE_LONG.match(surface):
            month = MONTHS.index(match[1]) + 1
            return date(int(match[3]), month, int(match[2])).isoformat()
        if match := _DATE_ISO.match(surface):
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        if match := _DATE_US.match(surface):
            return date(int(match[3]), int(match[1]), int(match[2])).isoformat()
    except ValueError:
        return None
    return None


# --- times ----------------------------------------------------------------------

TIME_FORMAT_COUNT = 2
_TIME_12 = re.compile(r"^(\d{1,2}):(\d{2}) (AM|PM)$")
_TIME_24 = re.compile(r"^(\d{2}):(\d{2})$")


def format_time(value: str, style: int) -> str:
    """A canonical 24 hour `HH:MM` time as text. The word `about` is never part of it."""
    hour, minute = (int(part) for part in value.split(":"))
    if style == 0:
        suffix = "AM" if hour < 12 else "PM"
        return f"{(hour % 12) or 12}:{minute:02d} {suffix}"
    if style == 1:
        return f"{hour:02d}:{minute:02d}"
    raise ValueError("unknown time style")


def parse_time(surface: str) -> str | None:
    """The canonical time a surface was written from, or None."""
    if match := _TIME_12.match(surface):
        hour, minute = int(match[1]), int(match[2])
        if not 1 <= hour <= 12 or minute > 59:
            return None
        hour = hour % 12 + (12 if match[3] == "PM" else 0)
        return f"{hour:02d}:{minute:02d}"
    if match := _TIME_24.match(surface):
        hour, minute = int(match[1]), int(match[2])
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"
    return None


# --- phones ---------------------------------------------------------------------

PHONE_FORMAT_COUNT = 2
_PHONE = re.compile(r"^555[-.](01\d\d)$")


def format_phone(value: str, style: int) -> str:
    """A canonical `555-01NN` phone as text, always in the range reserved for fiction."""
    if style == 0:
        return value
    if style == 1:
        return value.replace("-", ".")
    raise ValueError("unknown phone style")


def parse_phone(surface: str) -> str | None:
    """The canonical phone a surface was written from, or None."""
    match = _PHONE.match(surface)
    return f"555-{match[1]}" if match else None


# --- phrases --------------------------------------------------------------------

# One cue bearing phrase per family and value. A bare yes or no is never a phrase,
# because it sits inside ordinary words.
PHRASES: dict[FieldName, dict[Family, dict[str, str]]] = {
    FieldName.REPORTER_RELATIONSHIP: {
        Family.INFORMAL_EMAIL: {
            "self": "I am the policyholder",
            "spouse": "The policyholder is my spouse",
            "parent": "The policyholder is my child",
            "child": "The policyholder is my parent",
        },
        Family.FORMAL_EMAIL: {
            "agent": "I am the insurance agent for the policyholder",
        },
        Family.WEB_FORM: {
            "self": "Relationship to policyholder: Self",
            "spouse": "Relationship to policyholder: Spouse",
            "parent": "Relationship to policyholder: Parent",
            "child": "Relationship to policyholder: Child",
            "agent": "Relationship to policyholder: Agent",
        },
    },
    FieldName.INJURIES_REPORTED: {
        Family.INFORMAL_EMAIL: {"yes": "Someone was hurt", "no": "No one was hurt"},
        Family.FORMAL_EMAIL: {"yes": "There were injuries", "no": "There were no injuries"},
        Family.WEB_FORM: {"yes": "Injuries reported: yes", "no": "Injuries reported: no"},
    },
    FieldName.POLICE_REPORT_FILED: {
        Family.INFORMAL_EMAIL: {
            "yes": "The police came and took a report",
            "no": "The police were not called",
        },
        Family.FORMAL_EMAIL: {
            "yes": "A police report was filed",
            "no": "No police report was filed",
        },
        Family.WEB_FORM: {
            "yes": "Police report filed: yes",
            "no": "Police report filed: no",
        },
    },
}

# The cue each family keeps with a phrase field; it sits inside every phrase of
# that family for that field.
PHRASE_CUES: dict[FieldName, dict[Family, str]] = {
    FieldName.REPORTER_RELATIONSHIP: {
        Family.INFORMAL_EMAIL: "policyholder",
        Family.FORMAL_EMAIL: "insurance agent",
        Family.WEB_FORM: "Relationship to policyholder:",
    },
    FieldName.INJURIES_REPORTED: {
        Family.INFORMAL_EMAIL: "hurt",
        Family.FORMAL_EMAIL: "injuries",
        Family.WEB_FORM: "Injuries reported:",
    },
    FieldName.POLICE_REPORT_FILED: {
        Family.INFORMAL_EMAIL: "police",
        Family.FORMAL_EMAIL: "police report",
        Family.WEB_FORM: "Police report filed:",
    },
}


def phrase(field: FieldName, family: Family, value: str) -> str:
    """The phrase a family writes for one value of a phrase field."""
    return PHRASES[field][family][value]


def all_phrases(field: FieldName, value: str | None = None) -> tuple[str, ...]:
    """Every phrase of a field across families, or only those for one value."""
    return tuple(
        text
        for by_value in PHRASES[field].values()
        for phrase_value, text in by_value.items()
        if value is None or phrase_value == value
    )


def parse_phrase(field: FieldName, surface: str) -> str | None:
    """The value a phrase was written for, matched without regard to case."""
    wanted = normalize(surface)
    for by_value in PHRASES[field].values():
        for value, text in by_value.items():
            if normalize(text) == wanted:
                return value
    return None


# --- dispatch by field ----------------------------------------------------------


def name_parts(full_name: str) -> tuple[str, ...]:
    """A full name and its first and last name alone, each a possible leak."""
    first, last = full_name.split(" ")
    return (full_name, first, last)


def surface_forms(field: FieldName, value: str) -> tuple[str, ...]:
    """Every text a value can show up as, for the absent and collision checks."""
    kind = FIELD_KINDS[field]
    if kind is Kind.DATE:
        return tuple(format_date(value, style) for style in range(DATE_FORMAT_COUNT))
    if kind is Kind.TIME:
        return tuple(format_time(value, style) for style in range(TIME_FORMAT_COUNT))
    if kind is Kind.PHONE:
        return tuple(format_phone(value, style) for style in range(PHONE_FORMAT_COUNT))
    if kind is Kind.NAME:
        return name_parts(value)
    if kind is Kind.PHRASE:
        return all_phrases(field, value)
    return (value,)


def parse_surface(field: FieldName, surface: str) -> str | None:
    """The canonical value a written surface stands for, or None if it reads as nothing."""
    kind = FIELD_KINDS[field]
    if kind is Kind.DATE:
        return parse_date(surface)
    if kind is Kind.TIME:
        return parse_time(surface)
    if kind is Kind.PHONE:
        return parse_phone(surface)
    if kind is Kind.PHRASE:
        return parse_phrase(field, surface)
    return surface
