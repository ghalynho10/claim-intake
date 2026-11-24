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
from claim_intake.generator.formatters import PROTECTED_WORDS, word_pattern
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
class FamilySpec:
    """A template family: its name, the document kind it writes, its renderer,
    and its fixed text (greetings, headings, filler) for the table checks."""

    family: Family
    kind: DocumentKind
    render: RenderFn
    fixed_text: tuple[str, ...] = field(default=())
