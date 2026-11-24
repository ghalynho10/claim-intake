"""The second check: every label proven against the final text, in code.

Labels are attached by construction when a line is rendered; this module checks
them again on the text a model will actually see, so a wrong label can never
look like a model error later. Problems name packet ids, field names and the
check that failed, never claim text or values (AGENTS.md logging rule).
"""

import re

from claim_intake.db.states import EvidenceStatus
from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.families import child_cues
from claim_intake.generator.formatters import (
    FIELD_KINDS,
    Kind,
    all_phrases,
    count_protected_words,
    has_word,
    has_word_normalized,
    parse_surface,
    surface_forms,
)
from claim_intake.generator.models import Claim, ExpectedField, Packet
from claim_intake.generator.plan import PARENTS

_PHONE_SHAPE = re.compile(r"\d{3}-\d{4}")
_FICTIONAL_PHONE = re.compile(r"555-01\d\d")
_FICTIONAL_ADDRESS = re.compile(r"[\w.+-]+@example\.com")


class PacketVerificationError(Exception):
    """A packet failed verification; generation stops and writes nothing."""

    def __init__(self, packet_id: str, problems: list[str]) -> None:
        self.packet_id = packet_id
        self.problems = problems
        super().__init__(f"packet {packet_id} failed verification: {'; '.join(problems)}")


def _check_claim(claim: Claim, lines: list[str], truth: str | None) -> list[str]:
    """AC-3: the claim sits on its evidence lines, reads back to its value, matches
    the scenario, and every line carrying it is listed."""
    field = claim.field
    if not claim.evidence:
        return [f"{field}: claim has no evidence line"]
    problems: list[str] = []
    for line in claim.evidence:
        if not 0 <= line.index < len(lines):
            problems.append(f"{field}: evidence index {line.index} is out of range")
            continue
        if line.text != lines[line.index]:
            problems.append(f"{field}: evidence text differs from line {line.index}")
        if not has_word(lines[line.index], claim.surface):
            problems.append(f"{field}: surface missing from line {line.index}")
    if parse_surface(field, claim.surface) != claim.value:
        problems.append(f"{field}: surface does not parse to the claim value")
    if claim.value != truth:
        problems.append(f"{field}: claim value differs from the scenario")
    listed = {line.index for line in claim.evidence}
    for index, text in enumerate(lines):
        if index not in listed and has_word_normalized(text, claim.surface):
            problems.append(f"{field}: line {index} carries the surface but is not evidence")
    in_range = [lines[e.index] for e in claim.evidence if 0 <= e.index < len(lines)]
    if claim.cue and not any(claim.cue in text for text in in_range):
        problems.append(f"{field}: cue missing from its evidence lines")
    return problems


def _check_absent(
    entry: ExpectedField, truth: str | None, claims: list[Claim], texts: dict[str, str]
) -> list[str]:
    """AC-4: an absent field has no claim, and neither its true value nor, for a
    phrase field, any of its phrases shows up before or after noise."""
    field = entry.field
    problems: list[str] = []
    if any(claim.field is field for claim in claims):
        problems.append(f"{field}: absent but a line carries a claim for it")
    if FIELD_KINDS[field] is Kind.PHRASE:
        needles = all_phrases(field)
        what = "phrase"
    else:
        needles = surface_forms(field, truth) if truth is not None else ()
        what = "value"
    for stage, text in texts.items():
        if any(has_word_normalized(text, needle) for needle in needles):
            problems.append(f"{field}: absent {what} appears in the text {stage}")
    return problems


def _check_children(expected: dict[FieldName, ExpectedField], texts: dict[str, str]) -> list[str]:
    """AC-5: a child is found only under a found `yes` parent, and its line is
    written only when it is found."""
    problems: list[str] = []
    for child, parent in PARENTS.items():
        parent_entry = expected[parent]
        if expected[child].status is EvidenceStatus.FOUND:
            if parent_entry.status is not EvidenceStatus.FOUND or parent_entry.value != "yes":
                problems.append(f"{child}: found without a found yes parent")
            continue
        for stage, text in texts.items():
            if any(has_word_normalized(text, cue) for cue in child_cues(child)):
                problems.append(f"{child}: child line present while absent, {stage}")
    return problems


def _check_noise(claims: list[Claim], before: list[str], after: list[str]) -> list[str]:
    """AC-6: on every claim line, noise kept the surface, the cue and each
    negation or qualifier word at least as often as before."""
    if len(before) != len(after):
        return ["noise: line count changed"]
    problems: list[str] = []
    for claim in claims:
        for line in claim.evidence:
            if not 0 <= line.index < len(after):
                continue
            old, new = before[line.index], after[line.index]
            for needle in (claim.surface, claim.cue):
                if needle and new.count(needle) < old.count(needle):
                    problems.append(f"{claim.field}: noise changed a protected span")
            if count_protected_words(new) < count_protected_words(old):
                problems.append(f"{claim.field}: noise dropped a protected word")
    return problems


def check_contact_tokens(lines: list[str]) -> list[str]:
    """AC-9: every phone shaped token is in 555-0100..0199 and every address
    ends in @example.com, so no real contact data can slip in."""
    problems: list[str] = []
    for index, text in enumerate(lines):
        if any(not _FICTIONAL_PHONE.fullmatch(m) for m in _PHONE_SHAPE.findall(text)):
            problems.append(f"privacy: line {index} has a phone outside the fictional range")
        for token in text.split():
            if "@" in token and not _FICTIONAL_ADDRESS.fullmatch(token.strip("<>.,;:")):
                problems.append(f"privacy: line {index} has an address outside example.com")
    return problems


def verify_packet(packet: Packet, lines_before_noise: list[str]) -> list[str]:
    """Every problem with a packet, or an empty list when its labels hold."""
    problems: list[str] = []
    claims: list[Claim] = []
    final: list[str] = []
    for document in packet.documents:
        if document.source_ref != f"{packet.packet_id}/{document.document_id}":
            problems.append(f"{document.document_id}: source_ref does not match its ids")
        seen: list[FieldName] = []
        for claim in document.claims:
            if claim.field in seen:
                problems.append(f"{claim.field}: more than one claim in one document")
            seen.append(claim.field)
            problems += _check_claim(claim, document.lines, packet.scenario.value(claim.field))
        problems += _check_noise(document.claims, lines_before_noise, document.lines)
        problems += check_contact_tokens(document.lines)
        claims += document.claims
        final += document.lines

    if [entry.field for entry in packet.expected] != list(FieldName):
        return [*problems, "expected: not one entry per field in FieldName order"]
    if packet.expected != derive_expected(packet.scenario, claims):
        problems.append("expected: does not match the key derived from the claims")

    texts = {"before noise": "\n".join(lines_before_noise), "after noise": "\n".join(final)}
    expected = {entry.field: entry for entry in packet.expected}
    for entry in packet.expected:
        if entry.status is EvidenceStatus.ABSENT:
            truth = packet.scenario.value(entry.field)
            problems += _check_absent(entry, truth, claims, texts)
    problems += _check_children(expected, texts)
    return problems
