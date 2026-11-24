"""What a family renderer returns: lines with the claims they carry attached.

A renderer decides the surface of each claim while it writes the line, so the
label is attached by construction rather than found afterwards. Protected spans
(every surface, cue and negation word on the line) are computed here once, so
the noise stage and its tests share one definition of what noise may touch.
"""

import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from claim_intake.db.states import DocumentKind
from claim_intake.fields import FieldName
from claim_intake.generator.formatters import (
    DATE_FORMAT_COUNT,
    FIELD_KINDS,
    PHONE_FORMAT_COUNT,
    PHRASE_CUES,
    PROTECTED_WORDS,
    TIME_FORMAT_COUNT,
    Kind,
    format_date,
    format_phone,
    format_time,
    phrase,
    word_pattern,
)
from claim_intake.generator.models import Family, Scenario

# Any token with an @ in it: an address keeps its exact spelling (AC-9).
_ADDRESS = re.compile(r"\S*@\S*")


@dataclass(frozen=True)
class Assertion:
    """One claim as a line carries it: canonical value, written surface and cue."""

    field: FieldName
    value: str
    surface: str
    cue: str


@dataclass(frozen=True)
class Line:
    """One rendered line. `fixed` marks machine text (headers, headings) that
    noise never edits."""

    text: str
    assertions: tuple[Assertion, ...] = ()
    fixed: bool = False

    def protected_spans(self) -> tuple[tuple[int, int], ...]:
        """Character ranges noise must leave alone, merged and sorted."""
        if self.fixed:
            return ((0, len(self.text)),) if self.text else ()
        spans: list[tuple[int, int]] = []
        for assertion in self.assertions:
            for needle in (assertion.surface, assertion.cue):
                if needle:
                    spans.extend(m.span() for m in re.finditer(re.escape(needle), self.text))
        for word in PROTECTED_WORDS:
            spans.extend(m.span() for m in word_pattern(word, ignore_case=True).finditer(self.text))
        spans.extend(m.span() for m in _ADDRESS.finditer(self.text))
        return merge_spans(spans)


def merge_spans(spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Overlapping or touching spans become one."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


RenderFn = Callable[[Scenario, tuple[FieldName, ...], random.Random], list[Line]]


@dataclass(frozen=True)
class Stated:
    """One field's line in a template: `{}` marks where the surface goes. Phrase
    fields leave `cue` empty and take their family's phrase cue."""

    field: FieldName
    template: str
    cue: str = ""


def choose_surface(field: FieldName, value: str, family: Family, rng: random.Random) -> str:
    """The text a family writes for a value: a formatter style drawn with the
    packet's generator, the family's phrase, or the value itself."""
    kind = FIELD_KINDS[field]
    if kind is Kind.DATE:
        return format_date(value, rng.randrange(DATE_FORMAT_COUNT))
    if kind is Kind.TIME:
        return format_time(value, rng.randrange(TIME_FORMAT_COUNT))
    if kind is Kind.PHONE:
        return format_phone(value, rng.randrange(PHONE_FORMAT_COUNT))
    if kind is Kind.PHRASE:
        return phrase(field, family, value)
    return value


def stated_line(
    entry: Stated,
    scenario: Scenario,
    planned: tuple[FieldName, ...],
    family: Family,
    rng: random.Random,
) -> Line | None:
    """The entry's line with its claim attached, or None when the field is not asserted."""
    value = scenario.value(entry.field)
    if entry.field not in planned or value is None:
        return None
    surface = choose_surface(entry.field, value, family, rng)
    cue = PHRASE_CUES[entry.field][family] if FIELD_KINDS[entry.field] is Kind.PHRASE else entry.cue
    text = entry.template.format(surface)
    if cue not in text:
        raise ValueError(f"template for {entry.field} does not hold its cue")
    return Line(text, (Assertion(entry.field, value, surface, cue),))


def vehicle_line(scenario: Scenario, planned: tuple[FieldName, ...], prefix: str) -> Line | None:
    """Year, make and model on one sentence, each its own claim with the shared
    prefix as cue. A year alone reads "a 2019 model"."""
    parts: list[Assertion] = []
    for part in (FieldName.VEHICLE_YEAR, FieldName.VEHICLE_MAKE, FieldName.VEHICLE_MODEL):
        value = scenario.value(part)
        if part in planned and value is not None:
            parts.append(Assertion(part, value, value, prefix))
    if not parts:
        return None
    words = " ".join(part.surface for part in parts)
    if len(parts) == 1 and parts[0].field is FieldName.VEHICLE_YEAR:
        words = f"{words} model"
    return Line(f"{prefix} {words}.", tuple(parts))


@dataclass(frozen=True)
class FamilySpec:
    """A template family: its name, the document kind it writes, its renderer,
    its fixed text (greetings, headings, filler) for the table checks, and the
    cue that opens each child field's line, so the verifier can prove a child
    line is never written while the child is absent."""

    family: Family
    kind: DocumentKind
    render: RenderFn
    fixed_text: tuple[str, ...] = ()
    child_cues: dict[FieldName, str] = field(default_factory=dict)
