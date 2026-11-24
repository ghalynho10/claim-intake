"""The command line, the file set it writes, and the committed digest
(spec 0003, AC-1, AC-6, AC-8, AC-9).

The command runs in a separate Python process with a different hash seed, so
the digest it produces also proves two processes give identical packets.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from claim_intake.generator.__main__ import run
from claim_intake.generator.families.base import Line
from claim_intake.generator.io import dataset_digest, packet_hash, read_packet
from claim_intake.generator.models import Packet
from claim_intake.generator.pipeline import DEV_SEED, generate_dataset
from claim_intake.generator.verify import PacketVerificationError

# The SHA 256 of the 20 dev packets' bytes on Python 3.12. A deliberate change
# to the generator means: copy the new digest here, then re read by hand only
# the packets whose hash changed (spec 0003, AC-1 and AC-10).
DEV_DIGEST = "4ce7b2330a9ba5ee91dfde0dd14e024de9f590328afea39f95cc36e3840a6f75"


@pytest.fixture(scope="module")
def dev_set() -> list[Packet]:
    return generate_dataset(DEV_SEED, 20)


def _command(out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONHASHSEED": "1234"}
    return subprocess.run(
        [sys.executable, "-m", "claim_intake.generator", "--out", str(out), *extra],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_dev_set_digest_is_pinned(dev_set: list[Packet]) -> None:
    digest = dataset_digest(dev_set)
    assert digest == DEV_DIGEST, (
        f"dev set bytes changed on Python {platform.python_version()}: new digest {digest}. "
        "If the change is deliberate, copy it into DEV_DIGEST and re read the packets "
        "whose hash changed."
    )


def test_command_writes_twenty_files_equal_to_the_in_process_set(
    tmp_path: Path, dev_set: list[Packet]
) -> None:
    out = tmp_path / "dev"
    result = _command(out)
    assert result.returncode == 0, result.stderr
    paths = sorted(out.glob("pkt-*.json"))
    assert [p.name for p in paths] == [f"pkt-{n:03d}.json" for n in range(1, 21)]
    from_disk = [read_packet(p) for p in paths]
    assert from_disk == dev_set
    assert dataset_digest(from_disk) == dataset_digest(dev_set)
    assert [packet_hash(p) for p in from_disk] == [packet_hash(p) for p in dev_set]


def test_command_logs_json_lines_with_ids_and_never_values(
    tmp_path: Path, dev_set: list[Packet]
) -> None:
    result = _command(tmp_path / "dev")
    assert result.stdout == ""
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert {e["claim_id"] for e in events} >= {p.packet_id for p in dev_set}
    assert all(e["request_id"] is None for e in events)
    assert any("20" in e["msg"] for e in events)
    values = {
        value
        for packet in dev_set
        for entry in packet.expected
        if (value := entry.value) is not None and len(value) > 3
    }
    assert not any(value in result.stderr for value in values)


def test_command_refuses_existing_packets_unless_forced(tmp_path: Path) -> None:
    out = tmp_path / "dev"
    assert _command(out, "--count", "2").returncode == 0
    before = {p.name: p.read_bytes() for p in out.glob("pkt-*.json")}

    refused = _command(out, "--count", "3")
    assert refused.returncode == 1
    assert "--force" in refused.stderr
    assert {p.name: p.read_bytes() for p in out.glob("pkt-*.json")} == before

    (out / "pkt-099.json").write_text("{}")
    forced = _command(out, "--count", "3", "--force")
    assert forced.returncode == 0, forced.stderr
    assert sorted(p.name for p in out.glob("pkt-*.json")) == [
        "pkt-001.json",
        "pkt-002.json",
        "pkt-003.json",
    ]


def _break_surfaces(lines: list[Line], rng: object) -> list[str]:
    del rng
    out = []
    for line in lines:
        text = line.text
        for assertion in line.assertions:
            text = text.replace(assertion.surface, assertion.surface[::-1])
        out.append(text)
    return out


def test_a_failed_packet_writes_no_file(tmp_path: Path) -> None:
    out = tmp_path / "dev"
    with pytest.raises(PacketVerificationError):
        run(DEV_SEED, 20, out, noise=_break_surfaces)
    assert not out.exists() or not any(out.iterdir())


def test_a_failed_packet_exits_one_naming_ids_not_values(tmp_path: Path) -> None:
    with pytest.raises(PacketVerificationError) as caught:
        run(DEV_SEED, 1, tmp_path / "dev", noise=_break_surfaces)
    message = str(caught.value)
    assert "pkt-001" in message
    packet = generate_dataset(DEV_SEED, 1)[0]
    assert packet.scenario.loss_location is not None
    assert packet.scenario.loss_location not in message
