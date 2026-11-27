"""Packet seeds, ids and claim assembly in the pipeline (spec 0003, AC-1, AC-2,
Value sourcing: packet_seed and packet_id).

`assemble_claims` turns rendered lines into one claim per field; it must list
every line that carries the field and take each evidence text from the final
(noisy) lines, or the verifier would check the wrong text.
"""

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.families.base import Assertion, Line
from claim_intake.generator.pipeline import (
    DEV_SEED,
    assemble_claims,
    build_packet,
    generate_dataset,
)

NAME = Assertion(FieldName.REPORTER_NAME, "Maria Lopez", "Maria Lopez", "From:")
NAME_NO_CUE = Assertion(FieldName.REPORTER_NAME, "Maria Lopez", "Maria Lopez", "")


def test_every_dev_packet_has_its_own_seed_from_the_master_seed() -> None:
    # covers: AC-1 (packet_seed = master_seed * 10_000 + index)
    packets = generate_dataset(DEV_SEED, 20)
    assert [p.seed for p in packets] == [DEV_SEED * 10_000 + i for i in range(20)]


def test_another_master_seed_moves_the_packet_seed() -> None:
    # covers: AC-1, Value sourcing "Seed a packet" (pkt-003 with --seed 7 is 70002)
    packet = build_packet(2, seed=7)
    assert packet.packet_id == "pkt-003"
    assert packet.seed == 70_002


def test_claim_lists_every_carrying_line_with_final_text() -> None:
    # covers: AC-3 (every line that carries the surface is evidence)
    rendered = [
        Line("From: Maria Lopez <xy1234@example.com>", (NAME,), fixed=True),
        Line("Hi,"),
        Line("Maria Lopez", (NAME_NO_CUE,)),
    ]
    final = ["From: Maria Lopez <xy1234@example.com>", "Hi, ", "Maria Lopez "]
    [claim] = assemble_claims(rendered, final)
    assert claim.field is FieldName.REPORTER_NAME
    assert [(e.index, e.text) for e in claim.evidence] == [(0, final[0]), (2, final[2])]
    assert claim.cue == "From:"


def test_claims_come_out_in_field_order() -> None:
    date = Assertion(FieldName.LOSS_DATE, "2026-03-14", "March 14, 2026", "on")
    rendered = [Line("on March 14, 2026", (date,)), Line("Maria Lopez", (NAME_NO_CUE,))]
    claims = assemble_claims(rendered, [line.text for line in rendered])
    assert [c.field for c in claims] == [FieldName.REPORTER_NAME, FieldName.LOSS_DATE]


def test_one_field_written_with_two_surfaces_is_refused() -> None:
    other = Assertion(FieldName.REPORTER_NAME, "Maria Lopez", "M. Lopez", "")
    rendered = [Line("Maria Lopez", (NAME_NO_CUE,)), Line("M. Lopez", (other,))]
    with pytest.raises(ValueError, match="reporter_name"):
        assemble_claims(rendered, [line.text for line in rendered])
