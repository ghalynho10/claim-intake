"""Small helpers that build broken copies of a good packet for the verifier's
negative tests. Packets are frozen, so every change goes through model_copy."""

from collections.abc import Callable

from claim_intake.fields import FieldName
from claim_intake.generator.models import Claim, Document, Packet


def document(packet: Packet) -> Document:
    return packet.documents[0]


def claim(packet: Packet, field: FieldName) -> Claim:
    return next(c for c in document(packet).claims if c.field is field)


def with_document(packet: Packet, **changes: object) -> Packet:
    new_document = document(packet).model_copy(update=changes)
    return packet.model_copy(update={"documents": [new_document]})


def with_claim(packet: Packet, field: FieldName, change: Callable[[Claim], Claim]) -> Packet:
    claims = [change(c) if c.field is field else c for c in document(packet).claims]
    return with_document(packet, claims=claims)


def with_lines(packet: Packet, change: Callable[[list[str]], list[str]]) -> Packet:
    return with_document(packet, lines=change(list(document(packet).lines)))


def problems_for(problems: list[str], field: FieldName) -> list[str]:
    return [p for p in problems if p.startswith(f"{field}:")]
