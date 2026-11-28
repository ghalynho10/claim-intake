"""Packet files round trip and the write rules (spec 0003, AC-2, AC-8)."""

import hashlib
import json
from pathlib import Path

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.io import (
    OutputNotEmptyError,
    dataset_digest,
    packet_hash,
    packet_to_bytes,
    read_packet,
    write_packets,
)
from claim_intake.generator.models import Packet, document_text
from claim_intake.generator.pipeline import build_packet, generate_dataset


@pytest.fixture(scope="module")
def packet() -> Packet:
    return build_packet(0)


def test_packet_shape(packet: Packet) -> None:
    assert packet.packet_id == "pkt-001"
    assert len(packet.documents) == 1
    doc = packet.documents[0]
    assert doc.document_id == "doc-1"
    assert doc.source_ref == "pkt-001/doc-1"
    assert [e.field for e in packet.expected] == list(FieldName)
    assert {e.status.value for e in packet.expected} <= {"found", "absent"}


def test_written_file_reads_back_equal(packet: Packet, tmp_path: Path) -> None:
    [path] = write_packets([packet], tmp_path)
    assert path.name == "pkt-001.json"
    assert read_packet(path) == packet
    raw = path.read_bytes()
    assert raw == packet_to_bytes(packet)
    assert raw.endswith(b"}\n")


def test_lines_join_into_the_document_text(packet: Packet) -> None:
    doc = packet.documents[0]
    assert document_text(doc).split("\n") == doc.lines


def test_file_keys_follow_the_packet_shape_order(packet: Packet) -> None:
    # covers: AC-8 (fixed key order, so the bytes are stable)
    data = json.loads(packet_to_bytes(packet))
    assert list(data) == ["packet_id", "family", "seed", "scenario", "documents", "expected"]
    assert list(data["scenario"]) == [field.value for field in FieldName]
    doc = data["documents"][0]
    assert list(doc) == ["document_id", "source_ref", "kind", "lines", "claims"]
    assert list(doc["claims"][0]) == ["field", "value", "surface", "cue", "evidence"]
    assert list(doc["claims"][0]["evidence"][0]) == ["index", "text"]
    assert list(data["expected"][0]) == ["field", "status", "value", "evidence"]


def test_digest_does_not_depend_on_the_order_packets_are_passed() -> None:
    # covers: AC-1 (SHA 256 over each packet's bytes in id order)
    packets = generate_dataset(count=3)
    assert dataset_digest(packets[::-1]) == dataset_digest(packets)
    expected = hashlib.sha256(b"".join(packet_to_bytes(p) for p in packets)).hexdigest()
    assert dataset_digest(packets) == expected
    assert packet_hash(packets[0]) == hashlib.sha256(packet_to_bytes(packets[0])).hexdigest()


def test_refuses_a_folder_with_packets_unless_forced(packet: Packet, tmp_path: Path) -> None:
    write_packets([packet], tmp_path)
    stray = tmp_path / "pkt-099.json"
    stray.write_text("{}")
    other = tmp_path / "notes.txt"
    other.write_text("keep me")
    with pytest.raises(OutputNotEmptyError):
        write_packets([packet], tmp_path)
    write_packets([packet], tmp_path, force=True)
    assert not stray.exists()
    assert other.exists()
    assert sorted(p.name for p in tmp_path.glob("pkt-*.json")) == ["pkt-001.json"]
