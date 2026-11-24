"""The second check: every label proven against the final text, in code.

Labels are attached by construction when a line is rendered; this module checks
them again on the text a model will actually see, so a wrong label can never
look like a model error later. Problems name packet ids, field names and the
check that failed, never claim text or values (AGENTS.md logging rule).
"""

from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.formatters import has_word
from claim_intake.generator.models import Claim, Packet


class PacketVerificationError(Exception):
    """A packet failed verification; generation stops and writes nothing."""

    def __init__(self, packet_id: str, problems: list[str]) -> None:
        self.packet_id = packet_id
        self.problems = problems
        super().__init__(f"packet {packet_id} failed verification: {'; '.join(problems)}")


def _check_claim(claim: Claim, lines: list[str]) -> list[str]:
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
    return problems


def verify_packet(packet: Packet, lines_before_noise: list[str]) -> list[str]:
    """Every problem with a packet, or an empty list when its labels hold."""
    del lines_before_noise  # used by the absent and noise checks
    problems: list[str] = []
    for document in packet.documents:
        if document.source_ref != f"{packet.packet_id}/{document.document_id}":
            problems.append(f"{document.document_id}: source_ref does not match its ids")
        seen: list[FieldName] = []
        for claim in document.claims:
            if claim.field in seen:
                problems.append(f"{claim.field}: more than one claim in one document")
            seen.append(claim.field)
            problems += _check_claim(claim, document.lines)
    claims = [claim for document in packet.documents for claim in document.claims]
    if packet.expected != derive_expected(packet.scenario, claims):
        problems.append("expected: does not match the key derived from the claims")
    return problems
