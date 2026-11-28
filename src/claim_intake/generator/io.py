"""Packet files: one JSON file per packet, byte stable, and the dataset digest.

`packet_to_bytes` is the one serialisation the writer, the digest and the hand
read packet hash all share, so a hash names exactly the bytes on disk.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path

from claim_intake.generator.models import Packet

PACKET_GLOB = "pkt-*.json"


class OutputNotEmptyError(Exception):
    """The output folder already holds packet files and `force` was not given."""


def packet_to_bytes(packet: Packet) -> bytes:
    """Indented JSON in field declaration order, ending in a newline."""
    return (packet.model_dump_json(indent=2) + "\n").encode("utf-8")


def packet_hash(packet: Packet) -> str:
    """The SHA 256 of one packet's file bytes, for the hand read record."""
    return hashlib.sha256(packet_to_bytes(packet)).hexdigest()


def dataset_digest(packets: Sequence[Packet]) -> str:
    """The SHA 256 over every packet's bytes, in packet id order."""
    digest = hashlib.sha256()
    for packet in sorted(packets, key=lambda p: p.packet_id):
        digest.update(packet_to_bytes(packet))
    return digest.hexdigest()


def packet_path(out: Path, packet: Packet) -> Path:
    """Where a packet's file lives inside the output folder."""
    return out / f"{packet.packet_id}.json"


def write_packets(packets: Sequence[Packet], out: Path, *, force: bool = False) -> list[Path]:
    """Write one file per packet into `out`, refusing a folder that already holds
    packet files unless `force`, which deletes those files first."""
    out.mkdir(parents=True, exist_ok=True)
    existing = sorted(out.glob(PACKET_GLOB))
    if existing and not force:
        raise OutputNotEmptyError(f"{len(existing)} packet files already in the output folder")
    for path in existing:
        path.unlink()
    written: list[Path] = []
    for packet in packets:
        path = packet_path(out, packet)
        path.write_bytes(packet_to_bytes(packet))
        written.append(path)
    return written


def read_packet(path: Path) -> Packet:
    """Load one packet file back into an equal `Packet`."""
    return Packet.model_validate_json(path.read_bytes())
